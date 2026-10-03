"""Per-archetype trend detection over release dates.

Computes median estimated sales and release count per sub-window across the
trailing window W, plus a descriptive slope via ordinary least squares.
Per FORMULATION.md section 6: "Trend detection over release dates reports
the slope of median S^mid per archetype across sub-windows of W; it is
descriptive, so no significance claim is attached to it unless the sample
size per sub-window is reported alongside."
"""

from datetime import datetime, timedelta
import logging

import numpy as np
import pandas as pd
from scipy import stats

from steam_analyst.config.settings import AnalysisParams

logger = logging.getLogger(__name__)


def compute_tag_trends(
    frame: pd.DataFrame,
    assignments: pd.DataFrame,
    params: AnalysisParams
) -> pd.DataFrame:
    """Compute per-archetype release-date trends.

    Args:
        frame: The full enriched frame with columns including appid,
            release_date, estimated_sales_mid, and any games in the
            candidate set.
        assignments: cluster_tags' output (DataFrame with columns appid,
            cluster_id).
        params: AnalysisParams with trailing_window_months (W).

    Returns:
        A DataFrame with columns cluster_id, sub_window_index,
        sub_window_start, sub_window_end, n_games, median_estimated_sales_mid
        (one row per sub-window per cluster with n_games >= 1), plus one
        summary row per cluster_id with slope (linear regression slope of
        median_estimated_sales_mid across sub-windows in units of
        USD-equivalent per sub-window) and slope_n_subwindows (count of
        sub-windows actually used, i.e. with n_games >= 1). Sub-windows are
        fixed 4-month slices (12 sub-windows for W=48).

    Preconditions:
        - params.trailing_window_months is evenly divisible by 4 for a clean
          partition (e.g., 48 months -> 12 sub-windows of 4 months each).

    Postconditions:
        - A cluster_id with fewer than 2 sub-windows containing at least one
          game has slope == NaN (field left NULL rather than estimated from
          one point).
        - Every trend row (per sub-window) carries n_games, so no median is
          published without its sample size.
        - Sub-windows with zero releases for a given cluster are absent from
          that cluster's rows (not a zero-value row).

    Raises:
        ValueError: If params.trailing_window_months is not evenly divisible
            by 4.
    """
    # Validate precondition
    W = params.trailing_window_months
    if W % 4 != 0:
        raise ValueError(
            f"trailing_window_months ({W}) must be evenly divisible by 4"
        )

    # Define sub-window width in months
    sub_window_months = 4
    num_sub_windows = W // sub_window_months

    # Merge frame and assignments
    merged = frame.merge(assignments, on="appid", how="inner")

    if len(merged) == 0:
        # Empty result
        return pd.DataFrame(columns=[
            "cluster_id",
            "sub_window_index",
            "sub_window_start",
            "sub_window_end",
            "n_games",
            "median_estimated_sales_mid",
            "slope",
            "slope_n_subwindows",
        ])

    # Ensure release_date is datetime
    merged["release_date"] = pd.to_datetime(merged["release_date"])

    # Get the maximum release date to define the trailing window
    max_date = merged["release_date"].max()
    window_start = max_date - timedelta(days=W * 30.44)  # Approximate months

    # Filter to games in the trailing window
    merged = merged[merged["release_date"] >= window_start].copy()

    if len(merged) == 0:
        # No data in trailing window
        return pd.DataFrame(columns=[
            "cluster_id",
            "sub_window_index",
            "sub_window_start",
            "sub_window_end",
            "n_games",
            "median_estimated_sales_mid",
            "slope",
            "slope_n_subwindows",
        ])

    # Build sub-window rows
    rows = []
    cluster_trends = {}  # cluster_id -> list of (sub_window_index, median_sales)

    for cluster_id in sorted(merged["cluster_id"].unique()):
        cluster_data = merged[merged["cluster_id"] == cluster_id].copy()
        cluster_trends[cluster_id] = []

        for sub_window_idx in range(num_sub_windows):
            # Calculate sub-window bounds
            # Sub-window 0 is the most recent, sub-window (num_sub_windows-1) is oldest
            sub_window_end = max_date - timedelta(days=sub_window_idx * sub_window_months * 30.44)
            sub_window_start = sub_window_end - timedelta(days=sub_window_months * 30.44)

            # Filter games in this sub-window
            # Use > for start (exclusive) and <= for end (inclusive) so games
            # released at boundaries go to the more recent sub-window
            sub_window_games = cluster_data[
                (cluster_data["release_date"] > sub_window_start) &
                (cluster_data["release_date"] <= sub_window_end)
            ]

            n_games = len(sub_window_games)

            # Only include sub-windows with at least one game
            if n_games >= 1:
                median_sales = sub_window_games["estimated_sales_mid"].median()

                # Handle NaN median (should not occur if n_games >= 1, but be safe)
                if pd.notna(median_sales):
                    rows.append({
                        "cluster_id": cluster_id,
                        "sub_window_index": sub_window_idx,
                        "sub_window_start": sub_window_start,
                        "sub_window_end": sub_window_end,
                        "n_games": n_games,
                        "median_estimated_sales_mid": median_sales,
                    })
                    cluster_trends[cluster_id].append((sub_window_idx, median_sales))

    # Create output DataFrame for sub-window rows
    if rows:
        output_df = pd.DataFrame(rows)
    else:
        output_df = pd.DataFrame(columns=[
            "cluster_id",
            "sub_window_index",
            "sub_window_start",
            "sub_window_end",
            "n_games",
            "median_estimated_sales_mid",
        ])

    # Add summary rows with slope calculations
    summary_rows = []
    for cluster_id, trends in cluster_trends.items():
        if len(trends) < 2:
            # Fewer than 2 sub-windows with data: slope is NaN
            slope = np.nan
            slope_n_subwindows = len(trends)
        else:
            # Compute OLS slope
            sub_window_indices = np.array([t[0] for t in trends])
            median_sales = np.array([t[1] for t in trends])

            # Linear regression: median_sales ~ sub_window_index
            # Note: sub_window_index increases from 0 (most recent) to older
            # So a negative slope means sales increased over time (downward index)
            slope, intercept, r_value, p_value, std_err = stats.linregress(
                sub_window_indices, median_sales
            )
            slope_n_subwindows = len(trends)

        summary_rows.append({
            "cluster_id": cluster_id,
            "sub_window_index": np.nan,
            "sub_window_start": pd.NaT,
            "sub_window_end": pd.NaT,
            "n_games": slope_n_subwindows,
            "median_estimated_sales_mid": np.nan,
            "slope": slope,
            "slope_n_subwindows": slope_n_subwindows,
        })

    # Combine sub-window rows and summary rows
    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)

        # Add slope columns to sub-window output
        output_df["slope"] = np.nan
        output_df["slope_n_subwindows"] = np.nan

        # Merge summary data
        result_df = pd.concat([output_df, summary_df], ignore_index=True)
    else:
        result_df = output_df
        if len(result_df) > 0:
            result_df["slope"] = np.nan
            result_df["slope_n_subwindows"] = np.nan

    # Ensure correct column order
    expected_columns = [
        "cluster_id",
        "sub_window_index",
        "sub_window_start",
        "sub_window_end",
        "n_games",
        "median_estimated_sales_mid",
        "slope",
        "slope_n_subwindows",
    ]

    # Reorder and ensure all columns are present
    for col in expected_columns:
        if col not in result_df.columns:
            result_df[col] = np.nan

    result_df = result_df[expected_columns]

    return result_df
