"""Unit tests for analysis.trends module."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from steam_analyst.analysis.trends import compute_tag_trends
from steam_analyst.config.settings import AnalysisParams


class TestComputeTagTrends:
    """Tests for compute_tag_trends function."""

    def test_invalid_window_not_divisible_by_four(self):
        """Window not divisible by 4 raises ValueError."""
        frame = pd.DataFrame({
            "appid": [1],
            "release_date": ["2024-01-01"],
            "estimated_sales_mid": [100.0],
        })
        assignments = pd.DataFrame({
            "appid": [1],
            "cluster_id": [0],
        })
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=23,  # Not divisible by 4
            min_cluster_size=5,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        with pytest.raises(ValueError, match="must be evenly divisible by 4"):
            compute_tag_trends(frame, assignments, params)

    def test_empty_frame_returns_empty_result(self):
        """Empty frame returns empty result DataFrame with correct columns."""
        frame = pd.DataFrame({
            "appid": pd.Series([], dtype=int),
            "release_date": pd.Series([], dtype="datetime64[ns]"),
            "estimated_sales_mid": pd.Series([], dtype=float),
        })
        assignments = pd.DataFrame({
            "appid": pd.Series([], dtype=int),
            "cluster_id": pd.Series([], dtype=int),
        })
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        result = compute_tag_trends(frame, assignments, params)

        assert len(result) == 0
        assert list(result.columns) == [
            "cluster_id",
            "sub_window_index",
            "sub_window_start",
            "sub_window_end",
            "n_games",
            "median_estimated_sales_mid",
            "slope",
            "slope_n_subwindows",
        ]

    def test_slope_null_with_one_subwindow(self):
        """A cluster with data in exactly one sub-window has slope == NaN."""
        # Create data with all releases in the most recent sub-window (0)
        max_date = datetime(2024, 12, 31)
        sub_window_0_start = max_date - timedelta(days=4 * 30.44)
        sub_window_0_end = max_date

        frame = pd.DataFrame({
            "appid": [1, 2, 3],
            "release_date": [
                sub_window_0_start + timedelta(days=10),
                sub_window_0_start + timedelta(days=20),
                sub_window_0_start + timedelta(days=30),
            ],
            "estimated_sales_mid": [100.0, 150.0, 120.0],
        })
        assignments = pd.DataFrame({
            "appid": [1, 2, 3],
            "cluster_id": [0, 0, 0],
        })
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        result = compute_tag_trends(frame, assignments, params)

        # Filter to summary row (where sub_window_index is NaN)
        summary_rows = result[result["sub_window_index"].isna()]
        assert len(summary_rows) == 1
        assert summary_rows.iloc[0]["cluster_id"] == 0
        assert pd.isna(summary_rows.iloc[0]["slope"])
        assert summary_rows.iloc[0]["slope_n_subwindows"] == 1

    def test_slope_computed_across_multiple_subwindows(self):
        """A cluster with data across multiple sub-windows produces a computed OLS slope."""
        max_date = datetime(2024, 12, 31)

        # Create releases spread across sub-windows
        # Sub-window 0 (most recent): 4 months back
        # Sub-window 1: 8 months back
        # Sub-window 2: 12 months back
        frame_data = []
        sales_by_subwindow = {
            0: [100.0, 110.0, 105.0],  # Sub-window 0
            1: [120.0, 125.0, 130.0],  # Sub-window 1
            2: [150.0, 155.0, 160.0],  # Sub-window 2
        }

        for sub_window_idx, sales_list in sales_by_subwindow.items():
            sub_window_end = max_date - timedelta(days=sub_window_idx * 4 * 30.44)
            sub_window_start = sub_window_end - timedelta(days=4 * 30.44)
            mid_point = sub_window_start + (sub_window_end - sub_window_start) / 2

            for i, sales in enumerate(sales_list):
                frame_data.append({
                    "appid": len(frame_data) + 1,
                    "release_date": mid_point + timedelta(days=i*3),
                    "estimated_sales_mid": sales,
                })

        frame = pd.DataFrame(frame_data)
        assignments = pd.DataFrame({
            "appid": frame["appid"],
            "cluster_id": 0,
        })
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        result = compute_tag_trends(frame, assignments, params)

        # Get summary row
        summary_rows = result[result["sub_window_index"].isna()]
        assert len(summary_rows) == 1
        summary = summary_rows.iloc[0]

        # Slope should be negative (sales increased as sub_window_index increased)
        # because later sub-windows (higher index = older) have higher sales
        assert pd.notna(summary["slope"])
        assert summary["slope_n_subwindows"] == 3
        # Slope should be > 0 because sales increase with index (older=higher sales)
        assert summary["slope"] > 0

    def test_every_row_carries_sample_size(self):
        """Every output row has a non-null n_games."""
        max_date = datetime(2024, 12, 31)

        frame_data = []
        for i in range(5):
            frame_data.append({
                "appid": i + 1,
                "release_date": max_date - timedelta(days=100),  # All in sub-window 0
                "estimated_sales_mid": 100.0 + i * 10,
            })

        frame = pd.DataFrame(frame_data)
        assignments = pd.DataFrame({
            "appid": frame["appid"],
            "cluster_id": 0,
        })
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        result = compute_tag_trends(frame, assignments, params)

        # All rows should have non-null n_games
        assert result["n_games"].notna().all()

    def test_subwindow_with_zero_releases_absent(self):
        """Sub-windows with zero releases for a cluster are absent from rows."""
        max_date = datetime(2024, 12, 31)

        # Release in sub-window 0 only
        frame = pd.DataFrame({
            "appid": [1, 2],
            "release_date": [
                max_date - timedelta(days=30),
                max_date - timedelta(days=40),
            ],
            "estimated_sales_mid": [100.0, 110.0],
        })
        assignments = pd.DataFrame({
            "appid": [1, 2],
            "cluster_id": [0, 0],
        })
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        result = compute_tag_trends(frame, assignments, params)

        # Filter out summary rows
        sub_window_rows = result[result["sub_window_index"].notna()]

        # Should have only 1 sub-window row (sub-window 0)
        assert len(sub_window_rows) == 1
        assert sub_window_rows.iloc[0]["sub_window_index"] == 0
        assert sub_window_rows.iloc[0]["n_games"] == 2

    def test_multiple_clusters(self):
        """Multiple clusters are processed independently."""
        max_date = datetime(2024, 12, 31)

        frame_data = [
            {"appid": 1, "release_date": max_date - timedelta(days=30), "estimated_sales_mid": 100.0},
            {"appid": 2, "release_date": max_date - timedelta(days=40), "estimated_sales_mid": 110.0},
            {"appid": 3, "release_date": max_date - timedelta(days=200), "estimated_sales_mid": 200.0},
            {"appid": 4, "release_date": max_date - timedelta(days=210), "estimated_sales_mid": 210.0},
        ]
        frame = pd.DataFrame(frame_data)
        assignments = pd.DataFrame({
            "appid": [1, 2, 3, 4],
            "cluster_id": [0, 0, 1, 1],
        })
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        result = compute_tag_trends(frame, assignments, params)

        # Should have rows for both clusters
        assert 0 in result["cluster_id"].unique()
        assert 1 in result["cluster_id"].unique()

        # Each cluster should have a summary row
        summary_rows = result[result["sub_window_index"].isna()]
        assert len(summary_rows) == 2

    def test_median_computed_correctly(self):
        """Median sales is computed correctly for each sub-window."""
        max_date = datetime(2024, 12, 31)

        # Create 5 games in sub-window 0 with known sales
        sales_values = [100.0, 150.0, 200.0, 250.0, 300.0]
        frame_data = []
        for i, sales in enumerate(sales_values):
            frame_data.append({
                "appid": i + 1,
                "release_date": max_date - timedelta(days=30 + i*2),
                "estimated_sales_mid": sales,
            })

        frame = pd.DataFrame(frame_data)
        assignments = pd.DataFrame({
            "appid": frame["appid"],
            "cluster_id": 0,
        })
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        result = compute_tag_trends(frame, assignments, params)

        # Get the sub-window row (not summary)
        sub_window_rows = result[result["sub_window_index"].notna()]
        assert len(sub_window_rows) == 1

        # Median of [100, 150, 200, 250, 300] is 200
        assert sub_window_rows.iloc[0]["median_estimated_sales_mid"] == 200.0

    def test_nan_sales_excluded_from_median(self):
        """NaN estimated_sales_mid values are excluded from median calculation."""
        max_date = datetime(2024, 12, 31)

        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5],
            "release_date": [
                max_date - timedelta(days=30),
                max_date - timedelta(days=35),
                max_date - timedelta(days=40),
                max_date - timedelta(days=45),
                max_date - timedelta(days=50),
            ],
            "estimated_sales_mid": [100.0, np.nan, 200.0, np.nan, 300.0],
        })
        assignments = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5],
            "cluster_id": [0, 0, 0, 0, 0],
        })
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        result = compute_tag_trends(frame, assignments, params)

        sub_window_rows = result[result["sub_window_index"].notna()]
        assert len(sub_window_rows) == 1

        # Median of [100, 200, 300] is 200
        assert sub_window_rows.iloc[0]["median_estimated_sales_mid"] == 200.0
        # But n_games is still 5 (all games in the sub-window)
        assert sub_window_rows.iloc[0]["n_games"] == 5

    def test_six_subwindows_for_24_month_window(self):
        """A 24-month window creates 6 sub-windows of 4 months each."""
        max_date = datetime(2024, 12, 31)

        # Create data spread evenly across sub-windows
        frame_data = []
        for sub_window_idx in range(6):
            mid_date = max_date - timedelta(days=(sub_window_idx + 0.5) * 4 * 30.44)
            for i in range(2):
                frame_data.append({
                    "appid": sub_window_idx * 2 + i + 1,
                    "release_date": mid_date + timedelta(days=i*2),
                    "estimated_sales_mid": 100.0 + sub_window_idx * 10,
                })

        frame = pd.DataFrame(frame_data)
        assignments = pd.DataFrame({
            "appid": frame["appid"],
            "cluster_id": 0,
        })
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        result = compute_tag_trends(frame, assignments, params)

        sub_window_rows = result[result["sub_window_index"].notna()]

        # Should have 6 sub-window rows for cluster 0
        assert len(sub_window_rows) == 6
        assert set(sub_window_rows["sub_window_index"]) == {0, 1, 2, 3, 4, 5}

    def test_unmatched_appids_excluded(self):
        """Games in frame but not in assignments are excluded."""
        max_date = datetime(2024, 12, 31)

        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4],
            "release_date": [max_date - timedelta(days=30)] * 4,
            "estimated_sales_mid": [100.0, 110.0, 120.0, 130.0],
        })
        assignments = pd.DataFrame({
            "appid": [1, 2],  # Only 1 and 2, not 3 and 4
            "cluster_id": [0, 0],
        })
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        result = compute_tag_trends(frame, assignments, params)

        sub_window_rows = result[result["sub_window_index"].notna()]

        # Should only have 2 games (appid 1 and 2)
        assert sub_window_rows.iloc[0]["n_games"] == 2

    def test_release_dates_outside_window_excluded(self):
        """Games released before the trailing window are excluded."""
        max_date = datetime(2024, 12, 31)
        window_start = max_date - timedelta(days=24 * 30.44)

        frame = pd.DataFrame({
            "appid": [1, 2, 3],
            "release_date": [
                max_date - timedelta(days=10),  # In window
                max_date - timedelta(days=100),  # In window
                max_date - timedelta(days=800),  # Before window
            ],
            "estimated_sales_mid": [100.0, 110.0, 120.0],
        })
        assignments = pd.DataFrame({
            "appid": [1, 2, 3],
            "cluster_id": [0, 0, 0],
        })
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        result = compute_tag_trends(frame, assignments, params)

        sub_window_rows = result[result["sub_window_index"].notna()]

        # Only 2 games should be in the result (appid 1 and 2)
        assert sub_window_rows.iloc[0]["n_games"] == 2

    def test_column_order_correct(self):
        """Output DataFrame has columns in the correct order."""
        max_date = datetime(2024, 12, 31)

        frame = pd.DataFrame({
            "appid": [1],
            "release_date": [max_date - timedelta(days=30)],
            "estimated_sales_mid": [100.0],
        })
        assignments = pd.DataFrame({
            "appid": [1],
            "cluster_id": [0],
        })
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        result = compute_tag_trends(frame, assignments, params)

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
        assert list(result.columns) == expected_columns
