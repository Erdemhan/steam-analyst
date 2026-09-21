"""Tag clustering into archetypes via agglomerative hierarchical clustering.

Implements FORMULATION.md section 6's locked clustering method: Jaccard tag-distance
matrix, agglomerative hierarchical clustering with no genre anchor, and an empirically-
derived or frozen distance-cut threshold.
"""

from dataclasses import dataclass
import logging
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

from steam_analyst.config.settings import AnalysisParams


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TagClusterResult:
    """Return type of cluster_tags.

    Outcome of one cluster_tags call.

    Attributes:
        assignments: A DataFrame with columns appid, cluster_id -- one row per
            game that had at least one retained tag. A game whose tags span
            multiple clusters is assigned to the cluster its PLURALITY of tags
            belongs to (ties broken by lowest cluster_id, for determinism).
        cluster_labels: cluster_id -> label string from label_cluster.
        cluster_members: cluster_id -> list of tag strings belonging to that
            cluster.
        cooccurrence: The raw tag-by-tag co-occurrence count matrix (not the
            Jaccard distance matrix) used for labeling and available for
            reporting/debugging.
        method: Fixed string 'agglomerative_jaccard_no_genre_anchor', recorded
            for traceability.
        params_used: {'linkage': ..., 'distance_threshold': ...,
            'threshold_source': 'frozen' | 'run_local_search' | 'run_local_search_fallback_max'}
            -- records whether AnalysisParams.tag_distance_threshold was used
            verbatim (frozen) or derived fresh by this run's own search.
    """

    assignments: pd.DataFrame
    cluster_labels: dict[int, str]
    cluster_members: dict[int, list[str]]
    cooccurrence: pd.DataFrame
    method: str
    params_used: dict


def compute_jaccard_tag_distance(tags: pd.DataFrame) -> pd.DataFrame:
    """Build a tag-by-tag Jaccard distance matrix from tag co-occurrence.

    Args:
        tags: game_tags-shaped rows (appid, tag, votes, rank) for the run's
            candidate set, already filtered to tags with votes >=
            AnalysisParams.min_tag_votes by the caller.

    Returns:
        A square, symmetric DataFrame indexed and columned by the distinct tag
        strings present in `tags`, where cell (t1, t2) = 1 - |games(t1) ∩
        games(t2)| / |games(t1) ∪ games(t2)| (Jaccard DISTANCE, i.e. 1 minus
        Jaccard similarity, so 0 = identical game sets, 1 = no games in common).
        Diagonal is exactly 0.0 for every tag against itself.

    Edge cases:
        - Two tags that always co-occur on exactly the same set of games:
          distance 0.0
        - Two tags that never co-occur on any game: distance 1.0
        - A tag used by exactly one game: still produces valid distances
        - tags is empty (zero rows): returns an empty (0x0) DataFrame
    """
    # Handle empty case
    if len(tags) == 0:
        return pd.DataFrame()

    # Get distinct tags
    distinct_tags = sorted(tags["tag"].unique())
    n_tags = len(distinct_tags)

    # Create a mapping from tag to appid set
    tag_to_games = {}
    for tag in distinct_tags:
        tag_to_games[tag] = set(tags[tags["tag"] == tag]["appid"].unique())

    # Build the distance matrix
    distance_matrix = np.zeros((n_tags, n_tags), dtype=float)

    for i, tag1 in enumerate(distinct_tags):
        for j, tag2 in enumerate(distinct_tags):
            if i == j:
                # Diagonal is exactly 0.0
                distance_matrix[i, j] = 0.0
            else:
                # Compute Jaccard distance
                games1 = tag_to_games[tag1]
                games2 = tag_to_games[tag2]

                intersection = len(games1 & games2)
                union = len(games1 | games2)

                if union == 0:
                    jaccard_similarity = 1.0
                else:
                    jaccard_similarity = intersection / union

                distance = 1.0 - jaccard_similarity
                distance_matrix[i, j] = distance

    # Convert to DataFrame with tag names as index/columns
    distance_df = pd.DataFrame(
        distance_matrix,
        index=distinct_tags,
        columns=distinct_tags
    )

    return distance_df


def label_cluster(members: list[str], cooccurrence: pd.DataFrame) -> str:
    """Build a human-readable archetype label.

    Args:
        members: Tag strings belonging to one cluster.
        cooccurrence: The full tag-by-tag co-occurrence count matrix (raw
            counts, not the Jaccard distance matrix) for the run, used to rank
            members by total within-run popularity.

    Returns:
        A string joining the top 3 members (or fewer if the cluster has fewer
        than 3 tags) by total co-occurrence weight (row sum in `cooccurrence`
        restricted to `members`), separated by ' / ', e.g. 'Roguelike / Pixel
        Graphics / Difficult'. Deterministic: ties in weight are broken
        alphabetically.
    """
    if len(members) == 0:
        return ""

    # Compute weight for each member (row sum in cooccurrence)
    weights = {}
    for member in members:
        if member in cooccurrence.index:
            # Sum across all columns for this tag's row
            weight = cooccurrence.loc[member].sum()
        else:
            weight = 0
        weights[member] = weight

    # Sort by weight descending, then alphabetically for ties
    sorted_members = sorted(
        members,
        key=lambda t: (-weights[t], t)
    )

    # Take top 3
    top_members = sorted_members[:3]

    # Join with ' / '
    return " / ".join(top_members)


def cluster_tags(
    tags: pd.DataFrame,
    frame: pd.DataFrame,
    params: AnalysisParams
) -> TagClusterResult:
    """Cluster tags into archetypes and assign games to them.

    Implements FORMULATION.md section 6's locked clustering method:
    agglomerative hierarchical clustering over a Jaccard tag-distance matrix,
    no genre anchor, empirically-derived or frozen distance-cut threshold.

    Args:
        tags: The run's tag rows for the candidate set, pre-filtered to votes
            >= params.min_tag_votes.
        frame: The enriched frame (used to restrict tags to appids present in
            the candidate set).
        params: AnalysisParams with tag_distance_threshold (possibly None,
            pre-freeze), clustering_linkage, min_cluster_size, min_tag_votes,
            max_tags_per_game.

    Returns:
        A TagClusterResult.

    Algorithm:
        1. Filter tags to the candidate set in frame and apply max_tags_per_game
           limit per game.
        2. Compute the Jaccard tag-distance matrix.
        3. Run scipy.cluster.hierarchy.linkage on the condensed distance matrix
           with method=params.clustering_linkage.
        4. Determine the distance cut:
           - If params.tag_distance_threshold is not None, use it VERBATIM
             (frozen, comparable-across-runs case).
           - If it IS None (pre-freeze), perform a run-local threshold search:
             scan the distinct merge-distances in the linkage's distance column
             (ascending), pick the SMALLEST distance whose resulting flat
             clustering has at least 50% of its clusters at or above
             params.min_cluster_size in member-tag count.
           - If no threshold satisfies the 50% rule, fall back to the maximum
             merge distance (one giant cluster).
        5. Assign each game to a cluster via plurality vote of its own tags'
           cluster memberships.
        6. Label every cluster via label_cluster.

    Determinism: For a fixed (tags, frame, params) input, produces bit-identical
    output across repeated calls.
    """
    # Filter tags to appids in frame
    candidate_appids = set(frame["appid"].unique())
    tags_filtered = tags[tags["appid"].isin(candidate_appids)].copy()

    # Apply max_tags_per_game limit: keep top-voted tags per game
    if len(tags_filtered) > 0 and params.max_tags_per_game is not None:
        tags_filtered = tags_filtered.sort_values(
            ["appid", "rank"]
        ).reset_index(drop=True)
        tags_filtered = tags_filtered.groupby("appid").head(
            params.max_tags_per_game
        )

    # Handle empty tags case
    if len(tags_filtered) == 0:
        return TagClusterResult(
            assignments=pd.DataFrame(columns=["appid", "cluster_id"]),
            cluster_labels={},
            cluster_members={},
            cooccurrence=pd.DataFrame(),
            method="agglomerative_jaccard_no_genre_anchor",
            params_used={
                "linkage": params.clustering_linkage,
                "distance_threshold": None,
                "threshold_source": "none_empty_tags"
            }
        )

    # Compute the Jaccard distance matrix
    distance_df = compute_jaccard_tag_distance(tags_filtered)

    # Handle edge case: single tag or no tags
    if len(distance_df) <= 1:
        # Single tag case: one cluster
        distinct_tags = list(distance_df.index)
        cluster_members = {0: distinct_tags}
        cluster_labels = {0: label_cluster(distinct_tags, distance_df)}

        # Assign all games with that tag to cluster 0
        games_with_tags = tags_filtered[["appid"]].drop_duplicates()
        assignments = pd.DataFrame({
            "appid": games_with_tags["appid"],
            "cluster_id": 0
        })

        return TagClusterResult(
            assignments=assignments,
            cluster_labels=cluster_labels,
            cluster_members=cluster_members,
            cooccurrence=pd.DataFrame(),
            method="agglomerative_jaccard_no_genre_anchor",
            params_used={
                "linkage": params.clustering_linkage,
                "distance_threshold": None,
                "threshold_source": "single_tag"
            }
        )

    # Convert distance matrix to condensed form for linkage
    # scipy's squareform expects upper triangle, so we extract it
    distance_array = distance_df.values
    condensed = squareform(distance_array, checks=False)

    # Run hierarchical clustering
    Z = linkage(condensed, method=params.clustering_linkage)

    # Determine the distance cut threshold
    if params.tag_distance_threshold is not None:
        # Frozen threshold: use verbatim
        distance_threshold = params.tag_distance_threshold
        threshold_source = "frozen"
    else:
        # Pre-freeze: run-local threshold search
        distance_threshold, threshold_source = _search_threshold(
            Z, distance_df.index, params.min_cluster_size
        )

    # Perform flat clustering at the determined threshold
    tag_cluster_ids = fcluster(
        Z, t=distance_threshold, criterion="distance"
    )

    # Create a mapping from tag to cluster_id (1-indexed from fcluster)
    distinct_tags = list(distance_df.index)
    tag_to_cluster = {
        tag: cluster_id
        for tag, cluster_id in zip(distinct_tags, tag_cluster_ids)
    }

    # Compute cluster members (which tags belong to each cluster)
    cluster_members = {}
    for tag, cluster_id in tag_to_cluster.items():
        if cluster_id not in cluster_members:
            cluster_members[cluster_id] = []
        cluster_members[cluster_id].append(tag)

    # Sort cluster members for determinism
    for cluster_id in cluster_members:
        cluster_members[cluster_id].sort()

    # Compute co-occurrence matrix for labeling (raw counts)
    cooccurrence = pd.DataFrame(0, index=distinct_tags, columns=distinct_tags)
    for appid in tags_filtered["appid"].unique():
        app_tags = tags_filtered[tags_filtered["appid"] == appid]["tag"].unique()
        for t1 in app_tags:
            for t2 in app_tags:
                cooccurrence.loc[t1, t2] += 1

    # Label each cluster
    cluster_labels = {}
    for cluster_id, members in cluster_members.items():
        cluster_labels[cluster_id] = label_cluster(members, cooccurrence)

    # Assign each game to a cluster via plurality vote
    assignments_list = []
    for appid in tags_filtered["appid"].unique():
        app_tags = tags_filtered[tags_filtered["appid"] == appid]["tag"].tolist()

        # Count cluster memberships
        cluster_counts = {}
        for tag in app_tags:
            cluster_id = tag_to_cluster[tag]
            cluster_counts[cluster_id] = cluster_counts.get(cluster_id, 0) + 1

        # Pick the cluster with the most tags (plurality vote)
        # Ties broken by lowest cluster_id
        best_cluster = min(
            cluster_counts.items(),
            key=lambda x: (-x[1], x[0])
        )[0]

        assignments_list.append({"appid": appid, "cluster_id": best_cluster})

    assignments = pd.DataFrame(assignments_list)

    return TagClusterResult(
        assignments=assignments,
        cluster_labels=cluster_labels,
        cluster_members=cluster_members,
        cooccurrence=cooccurrence,
        method="agglomerative_jaccard_no_genre_anchor",
        params_used={
            "linkage": params.clustering_linkage,
            "distance_threshold": distance_threshold,
            "threshold_source": threshold_source
        }
    )


def _search_threshold(
    Z: np.ndarray,
    tag_names: np.ndarray | list,
    min_cluster_size: int
) -> tuple[float, str]:
    """Search for a run-local distance threshold.

    Scans the distinct merge-distances in the linkage matrix (ascending),
    and picks the SMALLEST distance whose resulting flat clustering has at
    least 50% of its clusters at or above min_cluster_size in member-tag count.

    Args:
        Z: The linkage matrix from scipy.cluster.hierarchy.linkage.
        tag_names: The ordered tag names (index of the distance DataFrame).
        min_cluster_size: Minimum cluster size to meet the 50% rule.

    Returns:
        (distance_threshold, threshold_source) where threshold_source is
        'run_local_search' if a qualifying threshold was found, or
        'run_local_search_fallback_max' if no threshold satisfied the rule
        (degenerate/tiny candidate set case).
    """
    # Get distinct merge distances from the linkage matrix
    distances = np.unique(Z[:, 2])
    distances = np.sort(distances)

    n_tags = len(tag_names)

    for distance in distances:
        # Perform flat clustering at this distance
        tag_cluster_ids = fcluster(Z, t=distance, criterion="distance")

        # Count cluster sizes (in terms of member tags)
        cluster_sizes = {}
        for cluster_id, tag_cluster_id in zip(range(n_tags), tag_cluster_ids):
            if tag_cluster_id not in cluster_sizes:
                cluster_sizes[tag_cluster_id] = 0
            cluster_sizes[tag_cluster_id] += 1

        # Check if at least 50% of clusters meet min_cluster_size
        n_clusters = len(cluster_sizes)
        clusters_above_min = sum(
            1 for size in cluster_sizes.values()
            if size >= min_cluster_size
        )
        pct_above_min = clusters_above_min / n_clusters if n_clusters > 0 else 0

        if pct_above_min >= 0.5:
            return distance, "run_local_search"

    # Fallback: use the maximum distance (one giant cluster)
    max_distance = distances[-1] if len(distances) > 0 else 0.0
    return max_distance, "run_local_search_fallback_max"
