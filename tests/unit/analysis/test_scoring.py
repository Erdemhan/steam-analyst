"""Unit tests for analysis.scoring module."""

from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import pytest

from steam_analyst.analysis.scoring import (
    compute_zscore,
    compute_demand,
    compute_competition_density,
    build_opportunity_matrix,
    build_tag_summary,
)
from steam_analyst.config.settings import AnalysisParams


class TestComputeZscore:
    """Tests for compute_zscore function."""

    def test_standard_zscore_computation(self):
        """A series with known mean/std produces the standard z-score formula's result."""
        series = pd.Series([1, 2, 3, 4, 5], index=[10, 11, 12, 13, 14])
        result = compute_zscore(series)

        # Check length and index
        assert len(result) == len(series)
        assert (result.index == series.index).all()

        # Check mean is approximately 0
        assert abs(result.mean()) < 1e-10

        # Check values match standard formula
        expected_std = series.std(ddof=0)
        expected_mean = series.mean()
        expected = (series - expected_mean) / expected_std
        np.testing.assert_allclose(result.values, expected.values)

    def test_zero_variance_returns_all_zero(self):
        """A series of identical values returns all 0.0, not NaN."""
        series = pd.Series([5, 5, 5])
        result = compute_zscore(series)

        assert len(result) == 3
        np.testing.assert_array_equal(result.values, [0.0, 0.0, 0.0])
        assert not result.isna().any()

    def test_single_value_returns_zero(self):
        """A one-element series returns [0.0]."""
        series = pd.Series([7])
        result = compute_zscore(series)

        assert len(result) == 1
        assert result.iloc[0] == 0.0
        assert not result.isna().any()

    def test_empty_series(self):
        """An empty series returns an empty series."""
        series = pd.Series(dtype=float)
        result = compute_zscore(series)

        assert len(result) == 0

    def test_series_with_nan_entry(self):
        """A series with one NaN entry computes z-scores excluding NaN."""
        series = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0])
        result = compute_zscore(series)

        # Result should have same length as input
        assert len(result) == len(series)

        # The NaN position should propagate as NaN
        assert pd.isna(result.iloc[2])

        # Non-NaN values should be z-scored over the non-NaN population
        non_nan_series = series.dropna()
        expected_std = non_nan_series.std(ddof=0)
        expected_mean = non_nan_series.mean()

        # Check non-NaN values
        for i in [0, 1, 3, 4]:
            expected = (series.iloc[i] - expected_mean) / expected_std
            np.testing.assert_allclose(result.iloc[i], expected)

    def test_never_produces_inf(self):
        """z-scores never produce +/-inf even with extreme values."""
        series = pd.Series([1e-100, 2e-100, 3e-100])
        result = compute_zscore(series)

        assert not np.isinf(result).any()
        assert not result.isna().any()


class TestComputeDemand:
    """Tests for compute_demand function."""

    def test_median_and_iqr_computed_correctly(self, mock_analysis_params):
        """A synthetic archetype with known sales values reproduces hand-computed median and IQR."""
        # Create a frame with known sales values
        today = datetime.now()
        window_start = today - timedelta(days=mock_analysis_params.trailing_window_months * 30.44)
        in_window_date = window_start + timedelta(days=1)

        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5],
            "release_date_parsed": [in_window_date] * 5,
            "estimated_sales_mid": [100, 200, 300, 400, 500],
            "review_count": [10, 20, 30, 40, 50],
        })

        assignments = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5],
            "cluster_id": [1, 1, 1, 1, 1],
        })

        result = compute_demand(frame, assignments, mock_analysis_params)

        assert len(result) == 1
        assert result.index[0] == 1
        assert result.loc[1, "n_games"] == 5
        assert result.loc[1, "median_estimated_sales_mid"] == 300.0

        # IQR: 25th percentile of [100, 200, 300, 400, 500]
        # 25th percentile ≈ 200, 75th percentile ≈ 400
        assert result.loc[1, "sales_iqr_low"] <= 250
        assert result.loc[1, "sales_iqr_high"] >= 350

    def test_outlier_visible_in_iqr_not_hidden_by_median(self, mock_analysis_params):
        """An archetype with one extreme outlier has median close to normal values but widened IQR."""
        today = datetime.now()
        window_start = today - timedelta(days=mock_analysis_params.trailing_window_months * 30.44)
        in_window_date = window_start + timedelta(days=1)

        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5, 6, 7, 8],
            "release_date_parsed": [in_window_date] * 8,
            "estimated_sales_mid": [100, 110, 120, 130, 140, 150, 160, 5000],  # 5000 is an outlier
            "review_count": [10, 10, 10, 10, 10, 10, 10, 100],
        })

        assignments = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5, 6, 7, 8],
            "cluster_id": [1, 1, 1, 1, 1, 1, 1, 1],
        })

        result = compute_demand(frame, assignments, mock_analysis_params)

        # All 8 games should be included
        assert result.loc[1, "n_games"] == 8

        # Median should be close to the typical values (100-160), not the outlier
        assert 100 <= result.loc[1, "median_estimated_sales_mid"] <= 160

        # IQR should show the outlier's influence: iqr_high > median
        assert result.loc[1, "sales_iqr_high"] > result.loc[1, "median_estimated_sales_mid"]

    def test_unparseable_dates_excluded(self, mock_analysis_params):
        """Games with unparseable release_date do not contribute to demand statistics."""
        today = datetime.now()
        window_start = today - timedelta(days=mock_analysis_params.trailing_window_months * 30.44)
        in_window_date = window_start + timedelta(days=1)

        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4],
            "release_date_parsed": [in_window_date, in_window_date, pd.NaT, None],
            "estimated_sales_mid": [100, 200, 300, 400],
            "review_count": [10, 20, 30, 40],
        })

        assignments = pd.DataFrame({
            "appid": [1, 2, 3, 4],
            "cluster_id": [1, 1, 1, 1],
        })

        result = compute_demand(frame, assignments, mock_analysis_params)

        # Only 2 games have valid release dates
        assert result.loc[1, "n_games"] == 2
        assert result.loc[1, "median_estimated_sales_mid"] == 150.0

    def test_single_windowed_release(self, mock_analysis_params):
        """An archetype with exactly one windowed release reports n_games=1 with median==that value."""
        today = datetime.now()
        window_start = today - timedelta(days=mock_analysis_params.trailing_window_months * 30.44)
        in_window_date = window_start + timedelta(days=1)

        frame = pd.DataFrame({
            "appid": [1, 2],
            "release_date_parsed": [in_window_date, window_start - timedelta(days=100)],
            "estimated_sales_mid": [250, 100],
            "review_count": [25, 10],
        })

        assignments = pd.DataFrame({
            "appid": [1, 2],
            "cluster_id": [1, 1],
        })

        result = compute_demand(frame, assignments, mock_analysis_params)

        # Cluster 1 (same for both games) but only 1 in window
        assert result.loc[1, "n_games"] == 1
        assert result.loc[1, "median_estimated_sales_mid"] == 250.0
        # IQR degenerate case: low == high == single value
        assert result.loc[1, "sales_iqr_low"] == 250.0
        assert result.loc[1, "sales_iqr_high"] == 250.0

    def test_empty_frame(self, mock_analysis_params):
        """An empty frame returns an empty demand DataFrame."""
        frame = pd.DataFrame({
            "appid": [],
            "release_date_parsed": [],
            "estimated_sales_mid": [],
            "review_count": [],
        })

        assignments = pd.DataFrame({
            "appid": [],
            "cluster_id": [],
        })

        result = compute_demand(frame, assignments, mock_analysis_params)

        assert len(result) == 0
        assert list(result.columns) == [
            "n_games",
            "median_estimated_sales_mid",
            "median_review_count",
            "sales_iqr_low",
            "sales_iqr_high",
        ]


class TestComputeCompetitionDensity:
    """Tests for compute_competition_density function."""

    def test_catalog_growth_normalization_on_synthetic_catalog(self, mock_analysis_params):
        """A synthetic two-year catalog with known growth reflects relative, not absolute, standing."""
        today = datetime.now()
        window_start = today - timedelta(days=mock_analysis_params.trailing_window_months * 30.44)

        # First year (older): 10 releases total, 5 for cluster 1, 5 for cluster 2
        year_ago = window_start + timedelta(days=30)
        first_year_releases = [year_ago] * 10

        # Second year (recent): 20 releases total, 5 for cluster 1, 15 for cluster 2
        recent = window_start + timedelta(days=400)
        second_year_releases = [recent] * 20

        frame = pd.DataFrame({
            "appid": list(range(1, 31)),
            "release_date_parsed": first_year_releases + second_year_releases,
        })

        # Cluster 1: 5 games in both years = 10 total
        # Cluster 2: 5 games in year 1, 15 games in year 2 = 20 total
        assignments = pd.DataFrame({
            "appid": (
                list(range(1, 6)) +  # Cluster 1 first year
                list(range(6, 11)) +  # Cluster 2 first year
                list(range(11, 16)) +  # Cluster 1 second year
                list(range(16, 31))  # Cluster 2 second year
            ),
            "cluster_id": (
                [1] * 5 + [2] * 5 + [1] * 5 + [2] * 15
            ),
        })

        result = compute_competition_density(frame, assignments, mock_analysis_params)

        # Cluster 1: 10 releases out of 30 total = 1/3 ≈ 0.333
        assert result.loc[1, "releases_in_window"] == 10
        np.testing.assert_allclose(result.loc[1, "catalog_growth_adjusted_share"], 1/3, atol=1e-3)

        # Cluster 2: 20 releases out of 30 total = 2/3 ≈ 0.667
        assert result.loc[2, "releases_in_window"] == 20
        np.testing.assert_allclose(result.loc[2, "catalog_growth_adjusted_share"], 2/3, atol=1e-3)

    def test_shares_sum_to_one(self, mock_analysis_params):
        """Across all archetypes, catalog_growth_adjusted_share sums to 1.0."""
        today = datetime.now()
        window_start = today - timedelta(days=mock_analysis_params.trailing_window_months * 30.44)
        in_window_date = window_start + timedelta(days=1)

        frame = pd.DataFrame({
            "appid": list(range(1, 101)),
            "release_date_parsed": [in_window_date] * 100,
        })

        # 20 games in each of 5 clusters
        assignments = pd.DataFrame({
            "appid": list(range(1, 101)),
            "cluster_id": [i % 5 for i in range(1, 101)],
        })

        result = compute_competition_density(frame, assignments, mock_analysis_params)

        # All shares should sum to 1.0
        total_share = result["catalog_growth_adjusted_share"].sum()
        np.testing.assert_allclose(total_share, 1.0, atol=1e-10)

    def test_empty_window_returns_empty_frame(self, mock_analysis_params):
        """Zero total windowed releases returns an empty result, not a division error."""
        # All releases are outside the window (old dates)
        today = datetime.now()
        window_start = today - timedelta(days=mock_analysis_params.trailing_window_months * 30.44)
        old_date = window_start - timedelta(days=100)

        frame = pd.DataFrame({
            "appid": [1, 2, 3],
            "release_date_parsed": [old_date] * 3,
        })

        assignments = pd.DataFrame({
            "appid": [1, 2, 3],
            "cluster_id": [1, 1, 2],
        })

        result = compute_competition_density(frame, assignments, mock_analysis_params)

        # Should return an empty DataFrame
        assert len(result) == 0

    def test_zero_window_games_excluded(self, mock_analysis_params):
        """An archetype with zero windowed releases does not appear as a row."""
        today = datetime.now()
        window_start = today - timedelta(days=mock_analysis_params.trailing_window_months * 30.44)
        in_window_date = window_start + timedelta(days=1)
        old_date = window_start - timedelta(days=100)

        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4],
            "release_date_parsed": [in_window_date, in_window_date, old_date, old_date],
        })

        assignments = pd.DataFrame({
            "appid": [1, 2, 3, 4],
            "cluster_id": [1, 1, 2, 2],
        })

        result = compute_competition_density(frame, assignments, mock_analysis_params)

        # Only cluster 1 has windowed releases; cluster 2 should not appear
        assert len(result) == 1
        assert result.index[0] == 1


class TestBuildOpportunityMatrix:
    """Tests for build_opportunity_matrix function."""

    def test_reproduces_hand_computed_zscores_and_combination(self, mock_analysis_params):
        """Hand-computed z-scores and weighted combination reproduce exactly."""
        # Create three archetypes with known demand/competition/simplicity values
        demand = pd.DataFrame({
            "cluster_id": [1, 2, 3],
            "n_games": [5, 5, 5],
            "median_estimated_sales_mid": [100.0, 200.0, 300.0],
            "median_review_count": [10, 20, 30],
            "sales_iqr_low": [50.0, 150.0, 250.0],
            "sales_iqr_high": [150.0, 250.0, 350.0],
        }).set_index("cluster_id")

        competition = pd.DataFrame({
            "cluster_id": [1, 2, 3],
            "n_games": [5, 5, 5],
            "releases_in_window": [5, 5, 5],
            "catalog_growth_adjusted_share": [1/3, 1/3, 1/3],
        }).set_index("cluster_id")

        simplicity = pd.DataFrame({
            "cluster_id": [1, 2, 3],
            "median_complexity": [0.2, 0.5, 0.8],
        }).set_index("cluster_id")

        result = build_opportunity_matrix(
            demand, competition, simplicity, mock_analysis_params
        )

        # All three archetypes should be present (all have n_games >= min_cluster_size)
        assert len(result) == 3

        # Verify z-scores are computed over the population of 3
        # Since all have same catalog_growth_adjusted_share (1/3), competition_z should be 0 for all
        np.testing.assert_allclose(result["competition_z"].values, 0.0, atol=1e-10)

        # demand_z should vary (different sales values)
        assert result["demand_z"].std() > 0

        # Check opportunity score calculation matches formula
        for idx, row in result.iterrows():
            expected_opp = (
                0.40 * row["demand_z"]
                - 0.30 * row["competition_z"]
                + 0.30 * row["simplicity_z"]
            )
            np.testing.assert_allclose(row["opportunity_score"], expected_opp, atol=1e-10)

    def test_zero_variance_inputs_produce_zero_not_nan(self, mock_analysis_params):
        """Identical demand values across all archetypes produce demand_z=0, not NaN."""
        demand = pd.DataFrame({
            "cluster_id": [1, 2, 3],
            "n_games": [5, 5, 5],
            "median_estimated_sales_mid": [100.0, 100.0, 100.0],  # All identical
            "median_review_count": [10, 10, 10],
            "sales_iqr_low": [50.0, 50.0, 50.0],
            "sales_iqr_high": [150.0, 150.0, 150.0],
        }).set_index("cluster_id")

        competition = pd.DataFrame({
            "cluster_id": [1, 2, 3],
            "n_games": [5, 5, 5],
            "releases_in_window": [5, 5, 5],
            "catalog_growth_adjusted_share": [1/3, 1/3, 1/3],
        }).set_index("cluster_id")

        simplicity = pd.DataFrame({
            "cluster_id": [1, 2, 3],
            "median_complexity": [0.5, 0.5, 0.5],
        }).set_index("cluster_id")

        result = build_opportunity_matrix(
            demand, competition, simplicity, mock_analysis_params
        )

        # All demand_z values should be 0.0, not NaN
        np.testing.assert_array_equal(result["demand_z"].values, 0.0)
        assert not result["demand_z"].isna().any()

    def test_below_min_size_excluded_from_scoring(self, mock_analysis_params):
        """An archetype with n_games below min_cluster_size does not appear in result."""
        demand = pd.DataFrame({
            "cluster_id": [1, 2, 3],
            "n_games": [5, 3, 5],  # Cluster 2 below min_cluster_size=5
            "median_estimated_sales_mid": [100.0, 200.0, 300.0],
            "median_review_count": [10, 20, 30],
            "sales_iqr_low": [50.0, 150.0, 250.0],
            "sales_iqr_high": [150.0, 250.0, 350.0],
        }).set_index("cluster_id")

        competition = pd.DataFrame({
            "cluster_id": [1, 2, 3],
            "n_games": [5, 3, 5],
            "releases_in_window": [5, 3, 5],
            "catalog_growth_adjusted_share": [1/3, 1/3, 1/3],
        }).set_index("cluster_id")

        simplicity = pd.DataFrame({
            "cluster_id": [1, 2, 3],
            "median_complexity": [0.2, 0.5, 0.8],
        }).set_index("cluster_id")

        result = build_opportunity_matrix(
            demand, competition, simplicity, mock_analysis_params
        )

        # Only clusters 1 and 3 should be present
        assert len(result) == 2
        assert 2 not in result["cluster_id"].values

    def test_ties_broken_by_cluster_id(self, mock_analysis_params):
        """Two archetypes with identical opportunity_score are ordered by cluster_id ascending."""
        # Create three archetypes where all have identical metrics
        demand = pd.DataFrame({
            "cluster_id": [1, 2, 3],
            "n_games": [5, 5, 5],
            "median_estimated_sales_mid": [100.0, 100.0, 100.0],  # All same
            "median_review_count": [10, 10, 10],
            "sales_iqr_low": [50.0, 50.0, 50.0],
            "sales_iqr_high": [150.0, 150.0, 150.0],
        }).set_index("cluster_id")

        competition = pd.DataFrame({
            "cluster_id": [1, 2, 3],
            "n_games": [5, 5, 5],
            "releases_in_window": [5, 5, 5],
            "catalog_growth_adjusted_share": [1/3, 1/3, 1/3],  # All same
        }).set_index("cluster_id")

        simplicity = pd.DataFrame({
            "cluster_id": [1, 2, 3],
            "median_complexity": [0.5, 0.5, 0.5],  # All same
        }).set_index("cluster_id")

        result = build_opportunity_matrix(
            demand, competition, simplicity, mock_analysis_params
        )

        # All three should have same opportunity scores
        assert len(result) == 3
        assert result["opportunity_score"].std() < 1e-10  # All scores should be equal

        # Verify they are sorted by cluster_id ascending when scores are tied
        assert result["cluster_id"].iloc[0] == 1
        assert result["cluster_id"].iloc[1] == 2
        assert result["cluster_id"].iloc[2] == 3

    def test_empty_inputs(self, mock_analysis_params):
        """Empty input dataframes return an empty opportunity matrix."""
        demand = pd.DataFrame(columns=[
            "cluster_id",
            "n_games",
            "median_estimated_sales_mid",
            "median_review_count",
            "sales_iqr_low",
            "sales_iqr_high",
        ]).set_index("cluster_id")

        competition = pd.DataFrame(columns=[
            "cluster_id",
            "n_games",
            "releases_in_window",
            "catalog_growth_adjusted_share",
        ]).set_index("cluster_id")

        simplicity = pd.DataFrame(columns=[
            "cluster_id",
            "median_complexity",
        ]).set_index("cluster_id")

        result = build_opportunity_matrix(
            demand, competition, simplicity, mock_analysis_params
        )

        assert len(result) == 0
        assert list(result.columns) == [
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
        ]


class TestBuildTagSummary:
    """Tests for build_tag_summary function."""

    def test_single_game_tag_medians_equal_that_game(self, mock_analysis_params):
        """A tag on exactly one game has every median equal to that game's values."""
        frame = pd.DataFrame({
            "appid": [1, 2, 3],
            "complexity_score": [0.2, 0.5, 0.8],
            "estimated_sales_mid": [100, 200, 300],
            "review_positive_pct": [0.8, 0.7, 0.6],
            "price_usd": [9.99, 19.99, 29.99],
        })

        tags = pd.DataFrame({
            "appid": [1, 2, 3],
            "tag": ["unique1", "unique2", "unique3"],
            "votes": [10, 10, 10],
            "rank": [1, 1, 1],
        })

        result = build_tag_summary(frame, tags, mock_analysis_params)

        assert len(result) == 3

        # For tag "unique1", all medians should equal game 1's values
        unique1_row = result[result["tag"] == "unique1"].iloc[0]
        assert unique1_row["n_games"] == 1
        assert unique1_row["median_complexity_score"] == 0.2
        assert unique1_row["median_estimated_sales_mid"] == 100.0
        assert unique1_row["median_review_positive_pct"] == 0.8
        assert unique1_row["median_price_usd"] == 9.99

    def test_review_pct_in_ratio_range(self, mock_analysis_params):
        """median_review_positive_pct is always in [0,1] for a fixture with known review percentages."""
        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4],
            "complexity_score": [0.2, 0.5, 0.3, 0.6],
            "estimated_sales_mid": [100, 200, 150, 250],
            "review_positive_pct": [0.0, 0.5, 1.0, 0.75],
            "price_usd": [9.99, 19.99, 14.99, 24.99],
        })

        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2, 3, 4],
            "tag": ["action", "action", "action", "strategy", "action", "strategy"],
            "votes": [10, 10, 10, 10, 10, 10],
            "rank": [1, 2, 1, 1, 1, 1],
        })

        result = build_tag_summary(frame, tags, mock_analysis_params)

        # All review percentages should be in [0, 1]
        for _, row in result.iterrows():
            if pd.notna(row["median_review_positive_pct"]):
                assert 0.0 <= row["median_review_positive_pct"] <= 1.0

    def test_empty_after_min_votes_filter(self, mock_analysis_params):
        """A min_tag_votes higher than any tag's vote count returns an empty frame."""
        frame = pd.DataFrame({
            "appid": [1, 2],
            "complexity_score": [0.2, 0.5],
            "estimated_sales_mid": [100, 200],
            "review_positive_pct": [0.8, 0.7],
            "price_usd": [9.99, 19.99],
        })

        tags = pd.DataFrame({
            "appid": [1, 2],
            "tag": ["rare1", "rare2"],
            "votes": [1, 2],  # Both below any reasonable min_tag_votes
            "rank": [1, 1],
        })

        # Use a params with high min_tag_votes
        params_high_votes = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={
                "demand": 0.40,
                "competition": 0.30,
                "simplicity": 0.30,
            },
            min_tag_votes=1000,  # Much higher than any tag's votes
            max_tags_per_game=20,
            tag_distance_threshold=None,
            clustering_linkage="average",
        )

        result = build_tag_summary(frame, tags, params_high_votes)

        assert len(result) == 0
        assert list(result.columns) == [
            "tag",
            "n_games",
            "median_complexity_score",
            "median_estimated_sales_mid",
            "median_review_positive_pct",
            "median_price_usd",
        ]

    def test_tag_on_multiple_games(self, mock_analysis_params):
        """A tag applied to multiple games has n_games > 1 and computed medians."""
        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4],
            "complexity_score": [0.1, 0.2, 0.3, 0.4],
            "estimated_sales_mid": [100, 200, 300, 400],
            "review_positive_pct": [0.6, 0.7, 0.8, 0.9],
            "price_usd": [9.99, 14.99, 19.99, 24.99],
        })

        tags = pd.DataFrame({
            "appid": [1, 2, 3, 4],
            "tag": ["roguelike", "roguelike", "roguelike", "roguelike"],
            "votes": [50, 50, 50, 50],
            "rank": [1, 1, 1, 1],
        })

        result = build_tag_summary(frame, tags, mock_analysis_params)

        assert len(result) == 1
        roguelike_row = result.iloc[0]
        assert roguelike_row["tag"] == "roguelike"
        assert roguelike_row["n_games"] == 4

        # Medians should be computed from [0.1, 0.2, 0.3, 0.4], etc.
        np.testing.assert_allclose(roguelike_row["median_complexity_score"], 0.25)
        np.testing.assert_allclose(roguelike_row["median_estimated_sales_mid"], 250)
        np.testing.assert_allclose(roguelike_row["median_review_positive_pct"], 0.75)
        np.testing.assert_allclose(roguelike_row["median_price_usd"], 17.49, atol=0.1)

    def test_empty_frame(self, mock_analysis_params):
        """An empty frame returns an empty tag summary."""
        frame = pd.DataFrame({
            "appid": [],
            "complexity_score": [],
            "estimated_sales_mid": [],
            "review_positive_pct": [],
            "price_usd": [],
        })

        tags = pd.DataFrame({
            "appid": [],
            "tag": [],
            "votes": [],
            "rank": [],
        })

        result = build_tag_summary(frame, tags, mock_analysis_params)

        assert len(result) == 0
        assert list(result.columns) == [
            "tag",
            "n_games",
            "median_complexity_score",
            "median_estimated_sales_mid",
            "median_review_positive_pct",
            "median_price_usd",
        ]
