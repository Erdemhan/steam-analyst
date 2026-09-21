"""Unit tests for reporting.views module."""

import numpy as np
import pandas as pd
import pytest

from steam_analyst.reporting.views import (
    build_opportunity_matrix_view,
    build_tag_summary_table,
    OPPORTUNITY_MATRIX_COLUMN_MAPPING,
    TAG_SUMMARY_COLUMN_MAPPING,
)


class TestBuildOpportunityMatrixView:
    """Tests for build_opportunity_matrix_view function."""

    @pytest.fixture
    def sample_matrix(self):
        """A fixture opportunity matrix with known values."""
        return pd.DataFrame({
            "cluster_id": [1, 2, 3, 4, 5],
            "label": ["Puzzle", "Roguelike", "Platformer", "Idle", "Visual Novel"],
            "n_games": [15, 8, 20, 5, 12],
            "demand_z": [1.234567, -0.654321, 2.111111, -1.999999, 0.555555],
            "competition_z": [-0.555, 0.777, -0.333, 1.222, -0.888],
            "simplicity_z": [0.888, -0.444, 0.666, -0.111, 0.222],
            "opportunity_score": [2.5, -1.2, 3.1, -3.5, 1.1],
            "median_estimated_sales_mid": [50000.5, 75000.7, 125000.2, 10000.1, 35000.9],
            "median_complexity": [0.45, 0.65, 0.35, 0.75, 0.55],
            "releases_in_window": [8, 3, 15, 2, 7],
        })

    def test_sorted_descending_by_default(self, sample_matrix):
        """A fixture matrix is returned sorted by opportunity_score descending."""
        result = build_opportunity_matrix_view(sample_matrix)

        # Check that the opportunity score column (now renamed) is monotonically non-increasing
        opp_score_col = "Opportunity Score"
        assert opp_score_col in result.columns
        values = result[opp_score_col].values
        assert (values[:-1] >= values[1:]).all()

    def test_sorted_by_alternative_column(self, sample_matrix):
        """When sort_by='n_games', result is sorted by that column descending."""
        result = build_opportunity_matrix_view(sample_matrix, sort_by="n_games")

        # Check that n_games (renamed to "N") is monotonically non-increasing
        n_col = "N"
        assert n_col in result.columns
        values = result[n_col].values
        assert (values[:-1] >= values[1:]).all()

    def test_min_n_filters_rows(self, sample_matrix):
        """min_n=10 excludes archetypes with fewer games."""
        result = build_opportunity_matrix_view(sample_matrix, min_n=10)

        # Check that all rows have n_games >= 10
        n_col = "N"
        assert (result[n_col] >= 10).all()
        # We should have filtered out some rows
        assert len(result) < len(sample_matrix)

    def test_min_n_exact_boundary(self, sample_matrix):
        """min_n includes rows with exactly min_n games."""
        result = build_opportunity_matrix_view(sample_matrix, min_n=12)

        n_col = "N"
        # Should include the row with exactly 12 games (Visual Novel)
        assert (result[n_col] >= 12).all()
        assert 12 in result[n_col].values

    def test_empty_matrix_returns_empty_with_headers(self):
        """An empty input matrix returns an empty output with the expected column headers."""
        empty_matrix = pd.DataFrame({
            "cluster_id": [],
            "label": [],
            "n_games": [],
            "demand_z": [],
            "competition_z": [],
            "simplicity_z": [],
            "opportunity_score": [],
            "median_estimated_sales_mid": [],
            "median_complexity": [],
            "releases_in_window": [],
        })

        result = build_opportunity_matrix_view(empty_matrix)

        # Should have 0 rows
        assert len(result) == 0
        # Should have the renamed column headers
        expected_cols = set(OPPORTUNITY_MATRIX_COLUMN_MAPPING.values())
        assert set(result.columns) == expected_cols

    def test_invalid_sort_by_raises(self, sample_matrix):
        """sort_by='not_a_column' raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            build_opportunity_matrix_view(sample_matrix, sort_by="not_a_column")

        assert "not_a_column" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()

    def test_min_n_higher_than_all_returns_empty(self, sample_matrix):
        """min_n higher than every archetype's n_games returns empty but correctly headered."""
        result = build_opportunity_matrix_view(sample_matrix, min_n=1000)

        # Should have 0 rows
        assert len(result) == 0
        # Should have the renamed column headers
        expected_cols = set(OPPORTUNITY_MATRIX_COLUMN_MAPPING.values())
        assert set(result.columns) == expected_cols

    def test_rounding_z_scores_to_2_decimals(self, sample_matrix):
        """Z-score columns are rounded to 2 decimals."""
        result = build_opportunity_matrix_view(sample_matrix)

        # Check that z-score columns have at most 2 decimals
        z_cols = ["Demand (z)", "Competition (z)", "Simplicity (z)"]
        for col in z_cols:
            for val in result[col]:
                # Get the number of decimal places
                val_str = str(val)
                if "." in val_str:
                    decimals = len(val_str.split(".")[1])
                    assert decimals <= 2, f"{col} value {val} has {decimals} decimals"

    def test_rounding_dollar_figures_to_0_decimals(self, sample_matrix):
        """Dollar figure columns are rounded to 0 decimals."""
        result = build_opportunity_matrix_view(sample_matrix)

        # Est. Sales should be rounded to 0 decimals (integers)
        sales_col = "Est. Sales (band mid)"
        for val in result[sales_col]:
            assert isinstance(val, (int, float))
            assert val == int(val), f"Sales value {val} is not an integer"

    def test_rounding_complexity_to_2_decimals(self, sample_matrix):
        """Complexity column is rounded to 2 decimals."""
        result = build_opportunity_matrix_view(sample_matrix)

        complexity_col = "Complexity"
        for val in result[complexity_col]:
            # Get the number of decimal places
            val_str = str(val)
            if "." in val_str:
                decimals = len(val_str.split(".")[1])
                assert decimals <= 2

    def test_n_games_never_rounded_away(self, sample_matrix):
        """n_games is never rounded (remains an integer)."""
        result = build_opportunity_matrix_view(sample_matrix)

        n_col = "N"
        # All n_games values should be integers
        for val in result[n_col]:
            assert isinstance(val, (int, np.integer))

    def test_human_readable_column_names(self, sample_matrix):
        """All column headers are renamed to human-readable form."""
        result = build_opportunity_matrix_view(sample_matrix)

        # Check that the expected human-readable columns are present
        expected_cols = {
            "Cluster ID", "Archetype", "N", "Demand (z)", "Competition (z)",
            "Simplicity (z)", "Opportunity Score", "Est. Sales (band mid)",
            "Complexity", "Releases in Window"
        }
        assert expected_cols.issubset(set(result.columns))

    def test_with_nan_values(self):
        """NaN values in numeric columns are preserved during rounding."""
        matrix_with_nan = pd.DataFrame({
            "cluster_id": [1, 2],
            "label": ["A", "B"],
            "n_games": [10, 20],
            "demand_z": [1.234, np.nan],
            "competition_z": [0.5, 0.6],
            "simplicity_z": [0.3, 0.4],
            "opportunity_score": [2.0, np.nan],
            "median_estimated_sales_mid": [50000.0, np.nan],
            "median_complexity": [0.5, 0.6],
            "releases_in_window": [5, 10],
        })

        result = build_opportunity_matrix_view(matrix_with_nan)

        # Check that NaN is preserved
        assert pd.isna(result["Demand (z)"].iloc[1])
        assert pd.isna(result["Opportunity Score"].iloc[1])

    def test_does_not_modify_input(self, sample_matrix):
        """The function does not modify the input DataFrame."""
        original_matrix = sample_matrix.copy()

        build_opportunity_matrix_view(sample_matrix)

        # Check that the input is unchanged
        pd.testing.assert_frame_equal(sample_matrix, original_matrix)

    def test_column_order_preserved(self, sample_matrix):
        """Column order follows the original matrix column order (renamed)."""
        result = build_opportunity_matrix_view(sample_matrix)

        # Get the expected column order by mapping original columns
        expected_order = [
            OPPORTUNITY_MATRIX_COLUMN_MAPPING.get(col, col)
            for col in sample_matrix.columns
        ]

        # Check that result columns match this order
        assert list(result.columns) == expected_order


class TestBuildTagSummaryTable:
    """Tests for build_tag_summary_table function."""

    @pytest.fixture
    def sample_tag_summary(self):
        """A fixture tag summary with known values."""
        return pd.DataFrame({
            "tag": [
                "Action", "Adventure", "Puzzle", "Roguelike", "Platformer",
                "Idle", "Visual Novel", "RPG", "Strategy", "Simulation",
                "Sports", "Racing", "FPS", "Horror", "Comedy",
                "Educational", "Casual", "Indie", "Multiplayer", "Singleplayer",
            ],
            "n_games": [500, 450, 400, 380, 350, 320, 300, 280, 260, 240, 200, 180, 160, 140, 120, 100, 80, 60, 40, 20],
            "median_complexity_score": [
                0.65, 0.60, 0.35, 0.70, 0.45, 0.25, 0.30, 0.75, 0.68, 0.55,
                0.50, 0.45, 0.62, 0.55, 0.40, 0.35, 0.30, 0.50, 0.60, 0.55,
            ],
            "median_estimated_sales_mid": [
                75000, 80000, 50000, 90000, 60000, 40000, 45000, 100000, 95000, 85000,
                70000, 65000, 120000, 75000, 55000, 30000, 35000, 50000, 80000, 55000,
            ],
            "median_review_positive_pct": [
                0.78, 0.75, 0.82, 0.80, 0.76, 0.85, 0.88, 0.79, 0.77, 0.74,
                0.71, 0.73, 0.69, 0.65, 0.86, 0.90, 0.84, 0.81, 0.76, 0.80,
            ],
            "median_price_usd": [
                19.99, 24.99, 14.99, 29.99, 12.99, 4.99, 9.99, 39.99, 34.99, 29.99,
                49.99, 39.99, 59.99, 24.99, 9.99, 4.99, 7.99, 9.99, 29.99, 14.99,
            ],
        })

    def test_returns_top_n_by_game_count(self, sample_tag_summary):
        """top_n=5 returns exactly the 5 most-represented tags."""
        result = build_tag_summary_table(sample_tag_summary, top_n=5)

        # Should have exactly 5 rows
        assert len(result) == 5

        # The top 5 should be the first 5 by n_games descending
        n_col = "N"
        expected_n_values = [500, 450, 400, 380, 350]
        actual_n_values = result[n_col].tolist()
        assert actual_n_values == expected_n_values

    def test_fewer_rows_than_top_n_returns_all(self, sample_tag_summary):
        """top_n=100 on a fixture with 20 tags returns all 20, no padding."""
        result = build_tag_summary_table(sample_tag_summary, top_n=100)

        # Should have exactly 20 rows (all of them)
        assert len(result) == len(sample_tag_summary)

    def test_sorted_by_n_games_descending(self, sample_tag_summary):
        """Result is sorted by n_games descending."""
        result = build_tag_summary_table(sample_tag_summary, top_n=10)

        n_col = "N"
        # Check that values are monotonically non-increasing
        values = result[n_col].values
        assert (values[:-1] >= values[1:]).all()

    def test_empty_tag_summary_returns_empty_with_headers(self):
        """An empty input tag_summary returns an empty output with expected headers."""
        empty_summary = pd.DataFrame({
            "tag": [],
            "n_games": [],
            "median_complexity_score": [],
            "median_estimated_sales_mid": [],
            "median_review_positive_pct": [],
            "median_price_usd": [],
        })

        result = build_tag_summary_table(empty_summary)

        # Should have 0 rows
        assert len(result) == 0
        # Should have the renamed column headers
        expected_cols = set(TAG_SUMMARY_COLUMN_MAPPING.values())
        assert set(result.columns) == expected_cols

    def test_human_readable_column_names(self, sample_tag_summary):
        """All column headers are renamed to human-readable form."""
        result = build_tag_summary_table(sample_tag_summary, top_n=5)

        # Check that the expected human-readable columns are present
        expected_cols = {"Tag", "N", "Complexity", "Est. Sales (band mid)", "Positive %", "Price ($)"}
        assert expected_cols.issubset(set(result.columns))

    def test_rounding_applied(self, sample_tag_summary):
        """Numeric columns are rounded to appropriate precision."""
        result = build_tag_summary_table(sample_tag_summary, top_n=5)

        # Check complexity rounding (2 decimals)
        complexity_col = "Complexity"
        for val in result[complexity_col]:
            val_str = str(val)
            if "." in val_str:
                decimals = len(val_str.split(".")[1])
                assert decimals <= 2

        # Check sales rounding (0 decimals)
        sales_col = "Est. Sales (band mid)"
        for val in result[sales_col]:
            assert isinstance(val, (int, float))
            assert val == int(val)

        # Check price rounding (0 decimals)
        price_col = "Price ($)"
        for val in result[price_col]:
            assert isinstance(val, (int, float))
            assert val == int(val)

    def test_n_games_never_rounded(self, sample_tag_summary):
        """n_games column is never rounded away."""
        result = build_tag_summary_table(sample_tag_summary, top_n=10)

        n_col = "N"
        # All values should be integers
        for val in result[n_col]:
            assert isinstance(val, (int, np.integer))

    def test_with_nan_values(self):
        """NaN values in numeric columns are preserved during rounding."""
        tag_summary_with_nan = pd.DataFrame({
            "tag": ["Action", "Adventure"],
            "n_games": [500, 450],
            "median_complexity_score": [0.65, np.nan],
            "median_estimated_sales_mid": [75000.0, np.nan],
            "median_review_positive_pct": [0.78, 0.75],
            "median_price_usd": [19.99, 24.99],
        })

        result = build_tag_summary_table(tag_summary_with_nan)

        # Check that NaN is preserved
        assert pd.isna(result["Complexity"].iloc[1])
        assert pd.isna(result["Est. Sales (band mid)"].iloc[1])

    def test_does_not_modify_input(self, sample_tag_summary):
        """The function does not modify the input DataFrame."""
        original_summary = sample_tag_summary.copy()

        build_tag_summary_table(sample_tag_summary, top_n=5)

        # Check that the input is unchanged
        pd.testing.assert_frame_equal(sample_tag_summary, original_summary)

    def test_top_n_zero_or_negative_raises(self, sample_tag_summary):
        """top_n <= 0 raises ValueError."""
        with pytest.raises(ValueError):
            build_tag_summary_table(sample_tag_summary, top_n=0)

        with pytest.raises(ValueError):
            build_tag_summary_table(sample_tag_summary, top_n=-5)

    def test_single_row(self):
        """A tag_summary with a single row returns that row."""
        single_row = pd.DataFrame({
            "tag": ["Action"],
            "n_games": [100],
            "median_complexity_score": [0.65],
            "median_estimated_sales_mid": [75000.0],
            "median_review_positive_pct": [0.78],
            "median_price_usd": [19.99],
        })

        result = build_tag_summary_table(single_row, top_n=10)

        assert len(result) == 1
        assert result["Tag"].iloc[0] == "Action"

    def test_column_order_preserved(self, sample_tag_summary):
        """Column order follows the original tag_summary column order (renamed)."""
        result = build_tag_summary_table(sample_tag_summary, top_n=5)

        # Get the expected column order by mapping original columns
        expected_order = [
            TAG_SUMMARY_COLUMN_MAPPING.get(col, col)
            for col in sample_tag_summary.columns
        ]

        # Check that result columns match this order
        assert list(result.columns) == expected_order
