"""Tag clustering into archetypes via agglomerative hierarchical clustering.

Implements FORMULATION.md section 6's locked clustering method: Jaccard tag-distance
matrix, agglomerative hierarchical clustering with no genre anchor, and an empirically-
derived or frozen distance-cut threshold.
"""

from dataclasses import dataclass, field
import logging
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

from steam_analyst.analysis.scoring import _filter_to_windowed_releases
from steam_analyst.config.settings import AnalysisParams


logger = logging.getLogger(__name__)

PLAYER_MODE_TAGS: tuple[str, ...] = ("Singleplayer", "Multiplayer", "Co-op")
MODE_SHARE_COLUMNS: dict[str, str] = {
    "Singleplayer": "singleplayer_share",
    "Multiplayer": "multiplayer_share",
    "Co-op": "coop_share",
}


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
        excluded_generic_tags: Tags dropped before clustering because more than
            AnalysisParams.generic_tag_max_share of the clustered games carry
            them (sorted; empty when the exclusion is disabled or nothing
            exceeded the share).
        cluster_mode_shares: cluster_id -> {tag: share} for each tag in
            PLAYER_MODE_TAGS, where share is the fraction of the games assigned
            to that cluster that carry the tag. Computed from the tags before
            the generic-tag exclusion and never used for clustering; it only
            describes what an archetype covers.
    """

    assignments: pd.DataFrame
    cluster_labels: dict[int, str]
    cluster_members: dict[int, list[str]]
    cooccurrence: pd.DataFrame
    method: str
    params_used: dict
    excluded_generic_tags: list[str] = field(default_factory=list)
    cluster_mode_shares: dict[int, dict[str, float]] = field(default_factory=dict)


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
        0. Drop every tag carried by more than params.generic_tag_max_share of
           the games in the candidate set (before the per-game cap, so more
           specific tags can enter each game's top max_tags_per_game).
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
             (ascending) and pick the SMALLEST distance that maximizes the
             number of clusters holding at least params.min_cluster_size
             games released within the trailing window W after plurality-vote
             assignment (the scoring rule of FORMULATION.md section 6). A frame
             without a release_date_parsed column counts every game.
           - If no distance yields such a cluster, fall back to the maximum
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
    tags_all = tags_filtered.copy()

    # Drop generic tags (carried by more than generic_tag_max_share of the games)
    excluded_generic_tags: list[str] = []
    if len(tags_filtered) > 0 and params.generic_tag_max_share < 1.0:
        n_games_with_tags = tags_filtered["appid"].nunique()
        games_per_tag = tags_filtered.groupby("tag")["appid"].nunique()
        generic_mask = games_per_tag / n_games_with_tags > params.generic_tag_max_share
        excluded_generic_tags = sorted(games_per_tag.index[generic_mask])
        tags_filtered = tags_filtered[
            ~tags_filtered["tag"].isin(excluded_generic_tags)
        ].copy()

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
            },
            excluded_generic_tags=excluded_generic_tags,
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
            },
            excluded_generic_tags=excluded_generic_tags,
            cluster_mode_shares=_compute_mode_shares(assignments, tags_all),
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
        countable_appids = None
        if "release_date_parsed" in frame.columns:
            windowed = _filter_to_windowed_releases(
                frame,
                pd.DataFrame({"appid": frame["appid"].unique(), "cluster_id": 0}),
                params.trailing_window_months,
            )
            countable_appids = set(windowed["appid"]) if len(windowed) else set()
        distance_threshold, threshold_source = _search_threshold(
            Z,
            distance_df.index,
            tags_filtered,
            params.min_cluster_size,
            countable_appids,
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
        },
        excluded_generic_tags=excluded_generic_tags,
        cluster_mode_shares=_compute_mode_shares(assignments, tags_all),
    )


def _compute_mode_shares(
    assignments: pd.DataFrame, tags_all: pd.DataFrame
) -> dict[int, dict[str, float]]:
    """Share of each cluster's games that carry each player-mode tag.

    Args:
        assignments: Game-to-cluster assignments (columns appid, cluster_id).
        tags_all: Tag rows for the clustered games before any generic-tag
            exclusion or per-game cap (columns appid, tag).

    Returns:
        cluster_id -> {tag: share} for each tag in PLAYER_MODE_TAGS.
    """
    games_with_tag = {
        tag: set(tags_all.loc[tags_all["tag"] == tag, "appid"])
        for tag in PLAYER_MODE_TAGS
    }
    shares: dict[int, dict[str, float]] = {}
    for cluster_id, group in assignments.groupby("cluster_id"):
        appids = set(group["appid"])
        shares[int(cluster_id)] = {
            tag: len(appids & games_with_tag[tag]) / len(appids)
            for tag in PLAYER_MODE_TAGS
        }
    return shares


def _search_threshold(
    Z: np.ndarray,
    tag_names: np.ndarray | list,
    tags_filtered: pd.DataFrame,
    min_cluster_size: int,
    countable_appids: set | None = None,
) -> tuple[float, str]:
    """Search for a run-local distance threshold.

    Scans the distinct merge-distances in the linkage matrix (ascending) and
    picks the SMALLEST distance that maximizes the number of clusters holding
    at least min_cluster_size countable games, where games are assigned to
    clusters by plurality vote of their tags exactly as in cluster_tags.

    Args:
        Z: The linkage matrix from scipy.cluster.hierarchy.linkage.
        tag_names: The ordered tag names (index of the distance DataFrame).
        tags_filtered: Tag rows (columns appid, tag) that were clustered.
        min_cluster_size: Minimum number of countable games for a cluster to be
            scored.
        countable_appids: Games that count toward min_cluster_size (those released
            within the trailing window). None counts every game.

    Returns:
        (distance_threshold, threshold_source) where threshold_source is
        'run_local_search' if some distance yields a cluster of at least
        min_cluster_size games, or 'run_local_search_fallback_max' otherwise
        (degenerate/tiny candidate set case).
    """
    distances = np.sort(np.unique(Z[:, 2]))
    n_tags = len(tag_names)

    tag_index = {tag: i for i, tag in enumerate(tag_names)}
    appids = tags_filtered["appid"].unique()
    app_index = {appid: i for i, appid in enumerate(appids)}
    game_tag_counts = np.zeros((len(appids), n_tags))
    np.add.at(
        game_tag_counts,
        (
            tags_filtered["appid"].map(app_index).to_numpy(),
            tags_filtered["tag"].map(tag_index).to_numpy(),
        ),
        1.0,
    )

    if countable_appids is None:
        countable = np.ones(len(appids), dtype=bool)
    else:
        countable = np.array([appid in countable_appids for appid in appids])

    best_count = 0
    best_distance = None
    for distance in distances:
        labels = fcluster(Z, t=distance, criterion="distance")
        n_clusters = int(labels.max())
        membership = np.zeros((n_tags, n_clusters))
        membership[np.arange(n_tags), labels - 1] = 1.0
        # argmax returns the first maximum, i.e. the lowest cluster id on ties.
        assigned = (game_tag_counts @ membership).argmax(axis=1)
        games_per_cluster = np.bincount(assigned[countable], minlength=n_clusters)
        n_scorable = int((games_per_cluster >= min_cluster_size).sum())
        if n_scorable > best_count:
            best_count = n_scorable
            best_distance = distance

    if best_distance is not None:
        return float(best_distance), "run_local_search"

    max_distance = float(distances[-1]) if len(distances) > 0 else 0.0
    return max_distance, "run_local_search_fallback_max"
