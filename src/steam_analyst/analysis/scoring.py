"""Archetype demand, competition density, and opportunity scoring.

Implements FORMULATION.md sections 3a and 6: per-archetype scoring and
opportunity matrix construction.
"""

from datetime import datetime, timedelta
import logging

import numpy as np
import pandas as pd

from steam_analyst.config.settings import AnalysisParams


logger = logging.getLogger(__name__)


def compute_zscore(series: pd.Series) -> pd.Series:
    """Compute a z-score over the scored cluster population.

    Args:
        series: A numeric Series, one value per scored (i.e. >= min_cluster_size)
            archetype for the current run.

    Returns:
        (series - series.mean()) / series.std(ddof=0), except when
        series.std(ddof=0) == 0 (all values identical, including the
        single-cluster case), in which case every value is 0.0 rather than NaN,
        per the module's own invariant 'Zero-variance feature when computing
        z-scores -> z defined as 0 for all clusters rather than a division by
        zero'.

    Postconditions:
        - Result has the same index and length as series.
        - If series has nonzero variance, mean(result) == 0.0 within
          floating-point tolerance.
        - Never produces NaN or +/-inf.
    """
    # Handle empty series
    if len(series) == 0:
        return pd.Series(dtype=float)

    mean_val = series.mean()
    std_val = series.std(ddof=0)

    # Zero-variance guard: if std is 0, return all zeros
    if std_val == 0.0:
        return pd.Series(0.0, index=series.index, dtype=float)

    # Standard z-score computation
    return (series - mean_val) / std_val


def _filter_to_windowed_releases(
    frame: pd.DataFrame, assignments: pd.DataFrame, trailing_window_months: int
) -> pd.DataFrame:
    """Helper: filter frame+assignments to games in the trailing window.

    Returns a DataFrame with appid, cluster_id, and all original frame columns
    for games with a parseable release_date_parsed within the trailing window.
    """
    # Early exit if empty
    if len(frame) == 0 or len(assignments) == 0:
        return pd.DataFrame()

    # Compute the trailing window boundary
    today = datetime.now()
    window_start = today - timedelta(days=trailing_window_months * 30.44)

    # Merge frame with assignments
    merged = frame.copy()
    merged = merged.merge(
        assignments[["appid", "cluster_id"]],
        on="appid",
        how="inner"
    )

    if len(merged) == 0:
        return pd.DataFrame()

    # Filter to games with a parseable release_date_parsed within the window
    # Exclude rows with NaT or NaN in release_date_parsed
    valid_dates = merged[merged["release_date_parsed"].notna()].copy()

    if len(valid_dates) == 0:
        return pd.DataFrame()

    # Convert to datetime if it's a string/object type
    if not pd.api.types.is_datetime64_any_dtype(valid_dates["release_date_parsed"]):
        valid_dates["release_date_parsed"] = pd.to_datetime(
            valid_dates["release_date_parsed"],
            errors="coerce"
        )

    # Filter to games within the trailing window
    windowed = valid_dates[
        valid_dates["release_date_parsed"] >= pd.Timestamp(window_start)
    ]

    return windowed


def compute_demand(
    frame: pd.DataFrame, assignments: pd.DataFrame, params: AnalysisParams
) -> pd.DataFrame:
    """Compute per-archetype demand statistics.

    Args:
        frame: The FULL enriched frame (not just the buildable/simple subset --
            demand and competition are computed over all valid-release-date
            candidates within the trailing window).
        assignments: cluster_tags' TagClusterResult.assignments (appid ->
            cluster_id).
        params: AnalysisParams with trailing_window_months (W=24),
            min_cluster_size.

    Returns:
        A DataFrame indexed by cluster_id with columns: n_games (count of
        releases in the window), median_estimated_sales_mid,
        median_review_count, sales_iqr_low, sales_iqr_high (25th/75th
        percentile of estimated_sales_mid within the archetype-window
        population). Only games with a parseable release_date_parsed within
        the trailing W months of the run's own execution date are included
        in these medians.

    Postconditions:
        - Every row has n_games >= 1 (an archetype with zero windowed releases
          simply does not appear as a row at all).
        - sales_iqr_low <= median_estimated_sales_mid <= sales_iqr_high for
          every row.
    """
    windowed = _filter_to_windowed_releases(
        frame, assignments, params.trailing_window_months
    )

    # Group by cluster_id and compute statistics
    demand_stats = []

    if len(windowed) == 0:
        # Return empty DataFrame with required columns
        return pd.DataFrame(columns=[
            "cluster_id",
            "n_games",
            "median_estimated_sales_mid",
            "median_review_count",
            "sales_iqr_low",
            "sales_iqr_high",
        ]).set_index("cluster_id")

    for cluster_id, group in windowed.groupby("cluster_id"):
        # Count of releases in this cluster within the window
        n_games = len(group)

        if n_games == 0:
            # Skip clusters with zero windowed releases
            continue

        # Compute medians and IQR of estimated_sales_mid
        # (only for non-NULL values)
        sales_values = group["estimated_sales_mid"].dropna()

        if len(sales_values) == 0:
            # No valid sales data; skip this cluster
            continue

        median_sales = sales_values.median()
        median_reviews = group["review_count"].median()

        # IQR: 25th and 75th percentiles
        iqr_low = sales_values.quantile(0.25)
        iqr_high = sales_values.quantile(0.75)

        demand_stats.append({
            "cluster_id": cluster_id,
            "n_games": n_games,
            "median_estimated_sales_mid": median_sales,
            "median_review_count": median_reviews,
            "sales_iqr_low": iqr_low,
            "sales_iqr_high": iqr_high,
        })

    # Convert to DataFrame and set index
    if len(demand_stats) == 0:
        return pd.DataFrame(columns=[
            "cluster_id",
            "n_games",
            "median_estimated_sales_mid",
            "median_review_count",
            "sales_iqr_low",
            "sales_iqr_high",
        ]).set_index("cluster_id")

    result = pd.DataFrame(demand_stats).set_index("cluster_id")
    return result


def compute_competition_density(
    frame: pd.DataFrame, assignments: pd.DataFrame, params: AnalysisParams
) -> pd.DataFrame:
    """Compute per-archetype competition density.

    Args:
        frame: The full enriched frame.
        assignments: cluster_tags' output.
        params: AnalysisParams with trailing_window_months.

    Returns:
        A DataFrame indexed by cluster_id with columns: n_games,
        releases_in_window (raw count), catalog_growth_adjusted_share
        (releases_in_window / total_candidate_releases_in_window, i.e. the
        archetype's SHARE of all windowed releases across the whole candidate
        set -- this is this spec's concrete resolution of FORMULATION.md's
        qualitative 'adjusted for catalog growth').

    Postconditions:
        - sum of releases_in_window across ALL archetypes equals the total
          count of candidate-set games with a parseable release date in the
          window.
        - catalog_growth_adjusted_share values across all archetypes sum to
          1.0 (within floating-point tolerance).
    """
    windowed = _filter_to_windowed_releases(
        frame, assignments, params.trailing_window_months
    )

    # Compute total candidate-set releases in window
    total_windowed_releases = len(windowed)

    if total_windowed_releases == 0:
        # Empty window: return empty DataFrame
        return pd.DataFrame(columns=[
            "cluster_id",
            "n_games",
            "releases_in_window",
            "catalog_growth_adjusted_share",
        ]).set_index("cluster_id")

    # Group by cluster_id and compute statistics
    competition_stats = []

    for cluster_id, group in windowed.groupby("cluster_id"):
        releases_in_window = len(group)

        # Share of total windowed releases
        adjusted_share = releases_in_window / total_windowed_releases

        competition_stats.append({
            "cluster_id": cluster_id,
            "n_games": releases_in_window,
            "releases_in_window": releases_in_window,
            "catalog_growth_adjusted_share": adjusted_share,
        })

    # Convert to DataFrame and set index
    if len(competition_stats) == 0:
        return pd.DataFrame(columns=[
            "cluster_id",
            "n_games",
            "releases_in_window",
            "catalog_growth_adjusted_share",
        ]).set_index("cluster_id")

    result = pd.DataFrame(competition_stats).set_index("cluster_id")
    return result


def build_opportunity_matrix(
    demand: pd.DataFrame,
    competition: pd.DataFrame,
    simplicity: pd.DataFrame,
    params: AnalysisParams,
) -> pd.DataFrame:
    """Assemble the opportunity matrix.

    Args:
        demand: compute_demand's output.
        competition: compute_competition_density's output.
        simplicity: A DataFrame indexed by cluster_id with a median_complexity
            column (median complexity_score of the archetype's windowed games).
        params: AnalysisParams with opportunity_weights, min_cluster_size.

    Returns:
        A DataFrame with columns cluster_id, label, n_games, demand_z,
        competition_z, simplicity_z, opportunity_score,
        median_estimated_sales_mid, median_complexity, releases_in_window --
        restricted to archetypes present in ALL THREE input frames with
        n_games >= params.min_cluster_size. Sigma_k = z(1 - median_complexity)
        is computed here before calling compute_zscore. Ties in opportunity_score
        are broken by cluster_id ascending.

    Postconditions:
        - Every returned row has n_games >= params.min_cluster_size.
        - z-scores are computed only over the scored (i.e. already
          min_cluster_size-filtered) population.
        - Result is sorted by opportunity_score descending, ties by cluster_id
          ascending.
    """
    # Merge demand, competition, and simplicity on cluster_id
    # Use inner join to restrict to archetypes in all three frames
    matrix = demand.copy()
    matrix = matrix.join(
        competition[["releases_in_window", "catalog_growth_adjusted_share"]],
        how="inner"
    )
    matrix = matrix.join(simplicity, how="inner")

    # Filter to archetypes with n_games >= min_cluster_size
    matrix = matrix[matrix["n_games"] >= params.min_cluster_size].copy()

    if len(matrix) == 0:
        # Return empty DataFrame with all required columns
        return pd.DataFrame(columns=[
            "cluster_id",
            "label",
            "n_games",
            "demand_z",
            "competition_z",
            "simplicity_z",
            "opportunity_score",
            "median_estimated_sales_mid",
            "median_complexity",
            "releases_in_window",
        ])

    # Reset index to make cluster_id a regular column so we can use it later
    matrix = matrix.reset_index()

    # Compute simplicity as z(1 - median_complexity)
    # Lower complexity -> higher simplicity_z
    simplicity_raw = 1.0 - matrix["median_complexity"]

    # Compute z-scores over the scored population
    demand_z = compute_zscore(matrix["median_estimated_sales_mid"])
    demand_z.index = matrix.index
    matrix["demand_z"] = demand_z.values

    competition_z = compute_zscore(matrix["catalog_growth_adjusted_share"])
    competition_z.index = matrix.index
    matrix["competition_z"] = competition_z.values

    simplicity_z = compute_zscore(simplicity_raw)
    simplicity_z.index = matrix.index
    matrix["simplicity_z"] = simplicity_z.values

    # Compute opportunity score: Omega_k = w_D * D_k - w_K * K_k + w_Sigma * Sigma_k
    w_D = params.opportunity_weights.get("demand", 0.40)
    w_K = params.opportunity_weights.get("competition", 0.30)
    w_Sigma = params.opportunity_weights.get("simplicity", 0.30)

    matrix["opportunity_score"] = (
        w_D * matrix["demand_z"]
        - w_K * matrix["competition_z"]
        + w_Sigma * matrix["simplicity_z"]
    )

    # Select and reorder columns
    # Note: label is not in demand/competition/simplicity, so we need to add it as empty
    # The caller (run_analysis) is responsible for adding labels from cluster_labels
    # For now, we add a label column (empty or TBD by caller)
    if "label" not in matrix.columns:
        matrix["label"] = ""

    # Select required columns in the right order
    result = matrix[[
        "cluster_id",
        "label",
        "n_games",
        "demand_z",
        "competition_z",
        "simplicity_z",
        "opportunity_score",
        "median_estimated_sales_mid",
        "median_complexity",
        "releases_in_window",
    ]]

    # Sort by opportunity_score descending, then cluster_id ascending
    result = result.sort_values(
        by=["opportunity_score", "cluster_id"],
        ascending=[False, True]
    ).reset_index(drop=True)

    return result


def build_tag_summary(
    frame: pd.DataFrame,
    tags: pd.DataFrame,
    params: AnalysisParams,
) -> pd.DataFrame:
    """Compute per-tag summary statistics.

    Args:
        frame: The full enriched frame.
        tags: The run's tag rows (appid, tag, votes, rank), unfiltered by
            cluster membership.
        params: AnalysisParams with min_tag_votes.

    Returns:
        A DataFrame with one row per distinct tag (post min_tag_votes filtering),
        columns: tag, n_games, median_complexity_score, median_estimated_sales_mid,
        median_review_positive_pct, median_price_usd.

    Postconditions:
        - Every row has n_games >= 1.
        - median_review_positive_pct is in [0, 1] or NaN, never a raw percentage.
    """
    # Filter tags by min_tag_votes
    filtered_tags = tags[tags["votes"] >= params.min_tag_votes].copy()

    if len(filtered_tags) == 0:
        # Return empty DataFrame with required columns
        return pd.DataFrame(columns=[
            "tag",
            "n_games",
            "median_complexity_score",
            "median_estimated_sales_mid",
            "median_review_positive_pct",
            "median_price_usd",
        ])

    # Merge tags with frame to get enriched data
    # Filter to appids that exist in both tags and frame
    merged = filtered_tags.merge(
        frame[
            [
                "appid",
                "complexity_score",
                "estimated_sales_mid",
                "review_positive_pct",
                "price_usd",
            ]
        ],
        on="appid",
        how="inner"
    )

    if len(merged) == 0:
        # Return empty DataFrame with required columns
        return pd.DataFrame(columns=[
            "tag",
            "n_games",
            "median_complexity_score",
            "median_estimated_sales_mid",
            "median_review_positive_pct",
            "median_price_usd",
        ])

    # Group by tag and compute statistics
    tag_summaries = []

    for tag, group in merged.groupby("tag"):
        # Count distinct games with this tag
        n_games = group["appid"].nunique()

        # Compute medians
        median_complexity = group["complexity_score"].median()
        median_sales = group["estimated_sales_mid"].median()
        median_review_pct = group["review_positive_pct"].median()
        median_price = group["price_usd"].median()

        tag_summaries.append({
            "tag": tag,
            "n_games": n_games,
            "median_complexity_score": median_complexity,
            "median_estimated_sales_mid": median_sales,
            "median_review_positive_pct": median_review_pct,
            "median_price_usd": median_price,
        })

    # Convert to DataFrame
    if len(tag_summaries) == 0:
        return pd.DataFrame(columns=[
            "tag",
            "n_games",
            "median_complexity_score",
            "median_estimated_sales_mid",
            "median_review_positive_pct",
            "median_price_usd",
        ])

    result = pd.DataFrame(tag_summaries)
    return result
