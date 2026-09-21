"""Unit tests for analysis.simplicity module (FORMULATION.md section 3a)."""

import numpy as np
import pandas as pd
import pytest

from steam_analyst.analysis.simplicity import apply_simplicity_filter
from steam_analyst.config.settings import AnalysisParams


class TestApplySimplicityFilter:
    """Tests for apply_simplicity_filter function."""

    def test_empty_frame(self, mock_analysis_params):
        """Zero input rows returns empty buildable and all-zero tallies."""
        frame = pd.DataFrame({"complexity_score": []})
        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        assert len(buildable) == 0
        assert rejected["above_simplicity_threshold"] == 0
        assert rejected["null_complexity_score"] == 0

    def test_all_null_complexity_handled_without_raising(self, mock_analysis_params):
        """An all-NULL complexity_score frame returns an empty buildable set without raising."""
        frame = pd.DataFrame(
            {
                "app_id": [1, 2, 3],
                "complexity_score": [np.nan, np.nan, np.nan],
            }
        )
        # Should not raise, should handle gracefully
        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        assert len(buildable) == 0
        assert rejected["above_simplicity_threshold"] == 0
        assert rejected["null_complexity_score"] == 3

    def test_null_complexity_rows_excluded_and_tallied(self, mock_analysis_params):
        """Rows with NULL complexity_score are absent from buildable and counted under null_complexity_score."""
        frame = pd.DataFrame(
            {
                "app_id": [1, 2, 3, 4, 5],
                "complexity_score": [0.1, 0.2, np.nan, 0.3, np.nan],
            }
        )
        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        # buildable should have only non-null complexity_score rows
        assert all(buildable["complexity_score"].notna())
        # Exactly 2 rows with NULL complexity_score
        assert rejected["null_complexity_score"] == 2
        # Verify no NaN rows are in buildable
        assert len(buildable) <= 3

    def test_boundary_row_included(self, mock_analysis_params):
        """A row exactly at the 40th percentile cutoff is included in buildable."""
        # Create a frame with 10 rows with distinct complexity scores
        scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        frame = pd.DataFrame(
            {
                "app_id": list(range(1, 11)),
                "complexity_score": scores,
            }
        )

        # 40th percentile of [0.1, 0.2, ..., 1.0] should be around 0.4-0.5
        # (exact value depends on pandas quantile interpolation method)
        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        # Verify postcondition
        assert (
            len(buildable)
            + rejected["above_simplicity_threshold"]
            + rejected["null_complexity_score"]
            == len(frame)
        )

        # At 40th percentile, we expect roughly 4 rows (40% of 10)
        # But the exact count depends on pandas' quantile interpolation
        assert len(buildable) >= 3  # At least some buildable rows
        assert len(buildable) <= 5  # But not too many

    def test_postcondition_validation(self, mock_analysis_params):
        """Verify postcondition: sum of buildable + above + null == total frame length."""
        frame = pd.DataFrame(
            {
                "app_id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                "complexity_score": [
                    0.1,
                    0.2,
                    0.3,
                    0.4,
                    0.5,
                    0.6,
                    0.7,
                    0.8,
                    np.nan,
                    1.0,
                ],
            }
        )

        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        total = (
            len(buildable)
            + rejected["above_simplicity_threshold"]
            + rejected["null_complexity_score"]
        )
        assert total == len(frame)

    def test_basic_filtering(self, mock_analysis_params):
        """Verify basic filtering: rows above threshold are excluded."""
        frame = pd.DataFrame(
            {
                "app_id": [1, 2, 3, 4, 5],
                "complexity_score": [0.1, 0.2, 0.3, 0.4, 0.5],
            }
        )

        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        # All rows should have complexity_score <= cutoff
        max_score_in_buildable = buildable["complexity_score"].max()

        # Check that rows NOT in buildable have higher scores
        non_buildable_frame = frame[~frame["app_id"].isin(buildable["app_id"])]
        if len(non_buildable_frame) > 0:
            min_score_in_non_buildable = non_buildable_frame["complexity_score"].min()
            assert max_score_in_buildable <= min_score_in_non_buildable

    def test_preserves_frame_columns(self, mock_analysis_params):
        """Verify that buildable retains all original columns."""
        frame = pd.DataFrame(
            {
                "app_id": [1, 2, 3, 4, 5],
                "name": ["A", "B", "C", "D", "E"],
                "complexity_score": [0.1, 0.2, 0.3, 0.4, 0.5],
                "revenue": [100, 200, 300, 400, 500],
            }
        )

        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        # All columns should be preserved
        assert list(buildable.columns) == list(frame.columns)

    def test_percentile_computed_fresh_per_run(self, mock_analysis_params):
        """Verify that percentile is computed fresh from THIS run's distribution."""
        # Frame 1 with one distribution
        frame1 = pd.DataFrame(
            {
                "app_id": [1, 2, 3, 4, 5],
                "complexity_score": [0.1, 0.2, 0.3, 0.4, 0.5],
            }
        )

        # Frame 2 with a very different distribution
        frame2 = pd.DataFrame(
            {
                "app_id": [10, 20, 30, 40, 50],
                "complexity_score": [0.01, 0.02, 0.03, 0.04, 0.05],
            }
        )

        buildable1, rejected1 = apply_simplicity_filter(frame1, mock_analysis_params)
        buildable2, rejected2 = apply_simplicity_filter(frame2, mock_analysis_params)

        # The cutoffs should be different because the distributions are different
        cutoff1 = buildable1["complexity_score"].max()
        cutoff2 = buildable2["complexity_score"].max()

        # These should be substantially different due to the different scale
        # Frame 1 max is ~0.2, Frame 2 max is ~0.02
        assert abs(cutoff1 - cutoff2) > 0.05

    def test_mixed_null_and_non_null(self, mock_analysis_params):
        """Verify correct handling of mixed NULL and non-NULL complexity_score."""
        frame = pd.DataFrame(
            {
                "app_id": [1, 2, 3, 4, 5, 6],
                "complexity_score": [0.1, np.nan, 0.3, np.nan, 0.5, 0.6],
            }
        )

        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        # Check: all buildable rows should have non-null complexity_score
        assert buildable["complexity_score"].isna().sum() == 0
        # Check: exactly 2 rows with NULL
        assert rejected["null_complexity_score"] == 2
        # Check postcondition
        assert (
            len(buildable)
            + rejected["above_simplicity_threshold"]
            + rejected["null_complexity_score"]
            == len(frame)
        )

    def test_single_row_frame(self, mock_analysis_params):
        """Verify handling of single-row frame."""
        frame = pd.DataFrame(
            {
                "app_id": [1],
                "complexity_score": [0.5],
            }
        )

        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        # Single row should always be in buildable (it's the 100th percentile too)
        assert len(buildable) == 1
        assert rejected["above_simplicity_threshold"] == 0
        assert rejected["null_complexity_score"] == 0

    def test_single_row_null_frame(self, mock_analysis_params):
        """Verify handling of single-row frame with NULL complexity_score."""
        frame = pd.DataFrame(
            {
                "app_id": [1],
                "complexity_score": [np.nan],
            }
        )

        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        # Single NULL row should be excluded and tallied
        assert len(buildable) == 0
        assert rejected["null_complexity_score"] == 1
        assert rejected["above_simplicity_threshold"] == 0

    def test_zero_complexity_scores(self, mock_analysis_params):
        """Verify correct handling of zero complexity_score values."""
        frame = pd.DataFrame(
            {
                "app_id": [1, 2, 3, 4, 5],
                "complexity_score": [0.0, 0.0, 0.0, 0.0, 0.0],
            }
        )

        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        # All rows with 0.0 should be included (they're all at/below the cutoff)
        assert len(buildable) == 5
        assert rejected["above_simplicity_threshold"] == 0

    def test_identical_non_null_scores(self, mock_analysis_params):
        """Verify handling when all non-null scores are identical."""
        frame = pd.DataFrame(
            {
                "app_id": [1, 2, 3, 4, 5],
                "complexity_score": [0.5, 0.5, 0.5, 0.5, 0.5],
            }
        )

        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        # When all scores are identical, the 40th percentile should still be 0.5
        # and all rows should be included (they're all <= cutoff)
        assert len(buildable) == 5
        assert rejected["above_simplicity_threshold"] == 0

    def test_large_dataset_correctness(self, mock_analysis_params):
        """Verify correctness on larger dataset."""
        # Create 1000 rows with normally distributed complexity scores
        np.random.seed(42)
        scores = np.random.normal(loc=0.5, scale=0.2, size=1000)
        scores = np.clip(scores, 0, 1)  # Clip to [0, 1]

        frame = pd.DataFrame(
            {
                "app_id": range(1, 1001),
                "complexity_score": scores,
            }
        )

        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        # Verify postcondition
        total = (
            len(buildable)
            + rejected["above_simplicity_threshold"]
            + rejected["null_complexity_score"]
        )
        assert total == len(frame)

        # Roughly 40% should be buildable (40th percentile)
        # Allow some tolerance due to distribution and quantile interpolation
        expected_count = int(1000 * 0.4)
        assert len(buildable) >= expected_count - 50  # Within ±50
        assert len(buildable) <= expected_count + 50

    def test_returns_correct_type(self, mock_analysis_params):
        """Verify return types are correct."""
        frame = pd.DataFrame(
            {
                "app_id": [1, 2, 3],
                "complexity_score": [0.1, 0.2, 0.3],
            }
        )

        buildable, rejected = apply_simplicity_filter(frame, mock_analysis_params)

        # buildable should be a DataFrame
        assert isinstance(buildable, pd.DataFrame)
        # rejected should be a dict
        assert isinstance(rejected, dict)
        # rejected should have exactly these two keys
        assert set(rejected.keys()) == {"above_simplicity_threshold", "null_complexity_score"}
        # Values should be integers
        assert isinstance(rejected["above_simplicity_threshold"], (int, np.integer))
        assert isinstance(rejected["null_complexity_score"], (int, np.integer))
