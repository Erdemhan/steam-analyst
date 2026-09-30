"""Unit tests for enrichment.revenue module (FORMULATION.md sections 2-5)."""

import numpy as np
import pandas as pd
import pytest

from steam_analyst.config.settings import EnrichmentParams
from steam_analyst.enrichment.errors import EnrichmentError
from steam_analyst.enrichment.revenue import (
    compute_effort_adjusted_return,
    estimate_revenue,
    estimate_sales,
    map_genre_bucket,
)


# ============================================================================
# Tests for map_genre_bucket
# ============================================================================


class TestMapGenreBucket:
    """Tests for genre-to-bucket mapping (FORMULATION.md section 2)."""

    def test_first_matching_genre_wins(self, mock_enrichment_params):
        """['Action','Strategy'] resolves to broad_audience (first match)."""
        genres = pd.Series(
            [
                ["Action", "Strategy"],
            ]
        )
        result = map_genre_bucket(genres, mock_enrichment_params)
        assert result.iloc[0] == "broad_audience"

    def test_unmatched_genre_falls_back_to_default(self, mock_enrichment_params):
        """A genre absent from genre_bucket_map falls back to mainstream."""
        genres = pd.Series(
            [
                ["Obscure Genre Not In Map"],
            ]
        )
        result = map_genre_bucket(genres, mock_enrichment_params)
        assert result.iloc[0] == "mainstream"

    def test_empty_genre_list_falls_back_to_default(self, mock_enrichment_params):
        """An empty genre list falls back to mainstream."""
        genres = pd.Series([[]])
        result = map_genre_bucket(genres, mock_enrichment_params)
        assert result.iloc[0] == "mainstream"

    def test_horror_maps_to_mainstream(self, mock_enrichment_params):
        """['Horror'] resolves to mainstream per FORMULATION.md section 2."""
        genres = pd.Series([["Horror"]])
        result = map_genre_bucket(genres, mock_enrichment_params)
        assert result.iloc[0] == "mainstream"

    def test_rpg_maps_to_mainstream(self, mock_enrichment_params):
        """['RPG'] resolves to mainstream per FORMULATION.md section 2."""
        genres = pd.Series([["RPG"]])
        result = map_genre_bucket(genres, mock_enrichment_params)
        assert result.iloc[0] == "mainstream"

    def test_niche_genres(self, mock_enrichment_params):
        """Strategy and Simulation map to niche."""
        genres = pd.Series([["Strategy"], ["Simulation"]])
        result = map_genre_bucket(genres, mock_enrichment_params)
        assert result.iloc[0] == "niche"
        assert result.iloc[1] == "niche"

    def test_broad_audience_genres(self, mock_enrichment_params):
        """Action, FPS, etc. map to broad_audience."""
        genres = pd.Series(
            [
                ["Action"],
                ["FPS"],
                ["Arcade"],
                ["Multiplayer"],
            ]
        )
        result = map_genre_bucket(genres, mock_enrichment_params)
        for i in range(len(genres)):
            assert result.iloc[i] == "broad_audience"

    def test_first_matching_genre_priority(self, mock_enrichment_params):
        """When multiple genres match, the first one in the list wins."""
        # Strategy (niche) is first, Action (broad) is second
        genres = pd.Series([["Strategy", "Action"]])
        result = map_genre_bucket(genres, mock_enrichment_params)
        assert result.iloc[0] == "niche"

        # Action (broad) is first, Strategy (niche) is second
        genres = pd.Series([["Action", "Strategy"]])
        result = map_genre_bucket(genres, mock_enrichment_params)
        assert result.iloc[0] == "broad_audience"

    def test_mixed_matched_and_unmatched(self, mock_enrichment_params):
        """A mix of matched and unmatched genres uses the first match."""
        genres = pd.Series(
            [
                ["Unmatched Genre 1", "RPG", "Unmatched Genre 2"],
            ]
        )
        result = map_genre_bucket(genres, mock_enrichment_params)
        assert result.iloc[0] == "mainstream"

    def test_all_unmatched_genres_fall_back(self, mock_enrichment_params):
        """All unmatched genres in a list fall back to default."""
        genres = pd.Series(
            [
                ["Obscure Genre A", "Obscure Genre B", "Obscure Genre C"],
            ]
        )
        result = map_genre_bucket(genres, mock_enrichment_params)
        assert result.iloc[0] == "mainstream"

    def test_batch_processing(self, mock_enrichment_params):
        """Process multiple rows at once."""
        genres = pd.Series(
            [
                ["Action", "Strategy"],
                ["Horror"],
                [],
                ["Obscure Genre"],
                ["RPG", "Adventure"],
            ]
        )
        result = map_genre_bucket(genres, mock_enrichment_params)
        assert len(result) == 5
        assert result.iloc[0] == "broad_audience"  # Action first
        assert result.iloc[1] == "mainstream"  # Horror
        assert result.iloc[2] == "mainstream"  # Empty list
        assert result.iloc[3] == "mainstream"  # Obscure Genre
        assert result.iloc[4] == "mainstream"  # RPG first

    def test_output_only_valid_bucket_keys(self, mock_enrichment_params):
        """Every output is one of the three known bucket keys."""
        genres = pd.Series(
            [
                ["Strategy"],
                ["Puzzle"],
                ["Action"],
                ["Obscure"],
                [],
            ]
        )
        result = map_genre_bucket(genres, mock_enrichment_params)
        valid_buckets = set(mock_enrichment_params.boxleiter_multipliers.keys())
        for bucket in result:
            assert bucket in valid_buckets


# ============================================================================
# Tests for estimate_sales
# ============================================================================


class TestEstimateSales:
    """Tests for Boxleiter sales estimation (FORMULATION.md section 2)."""

    def test_reproduces_hand_computed_values(self, mock_enrichment_params):
        """review_count=1000, bucket='mainstream' yields (30000, 37000, 45000)."""
        review_count = pd.Series([1000])
        genre_bucket = pd.Series(["mainstream"])
        result = estimate_sales(review_count, genre_bucket, mock_enrichment_params)

        assert result["estimated_sales_low"].iloc[0] == 30000.0
        assert result["estimated_sales_mid"].iloc[0] == 37000.0
        assert result["estimated_sales_high"].iloc[0] == 45000.0

    def test_zero_reviews_yields_zero_sales(self, mock_enrichment_params):
        """review_count=0 yields all-zero sales columns."""
        review_count = pd.Series([0])
        genre_bucket = pd.Series(["mainstream"])
        result = estimate_sales(review_count, genre_bucket, mock_enrichment_params)

        assert result["estimated_sales_low"].iloc[0] == 0.0
        assert result["estimated_sales_mid"].iloc[0] == 0.0
        assert result["estimated_sales_high"].iloc[0] == 0.0

    def test_ordering_low_mid_high_holds(self, mock_enrichment_params):
        """For all rows and buckets, low <= mid <= high."""
        review_counts = pd.Series([0, 100, 1000, 10000, 100000])
        genre_buckets = pd.Series(
            [
                "niche",
                "mainstream",
                "broad_audience",
                "niche",
                "mainstream",
            ]
        )
        result = estimate_sales(review_counts, genre_buckets, mock_enrichment_params)

        for idx in result.index:
            low = result.loc[idx, "estimated_sales_low"]
            mid = result.loc[idx, "estimated_sales_mid"]
            high = result.loc[idx, "estimated_sales_high"]
            assert low <= mid <= high, f"Ordering violated at {idx}: {low} <= {mid} <= {high}"

    def test_niche_multipliers(self, mock_enrichment_params):
        """Niche bucket uses (20, 27, 35)."""
        review_count = pd.Series([100])
        genre_bucket = pd.Series(["niche"])
        result = estimate_sales(review_count, genre_bucket, mock_enrichment_params)

        assert result["estimated_sales_low"].iloc[0] == 2000.0
        assert result["estimated_sales_mid"].iloc[0] == 2700.0
        assert result["estimated_sales_high"].iloc[0] == 3500.0

    def test_broad_audience_multipliers(self, mock_enrichment_params):
        """Broad audience bucket uses (40, 50, 65)."""
        review_count = pd.Series([100])
        genre_bucket = pd.Series(["broad_audience"])
        result = estimate_sales(review_count, genre_bucket, mock_enrichment_params)

        assert result["estimated_sales_low"].iloc[0] == 4000.0
        assert result["estimated_sales_mid"].iloc[0] == 5000.0
        assert result["estimated_sales_high"].iloc[0] == 6500.0

    def test_unknown_bucket_raises_enrichment_error(self, mock_enrichment_params):
        """An unknown genre_bucket value raises EnrichmentError."""
        review_count = pd.Series([1000])
        genre_bucket = pd.Series(["not_a_real_bucket"])

        with pytest.raises(EnrichmentError) as exc_info:
            estimate_sales(review_count, genre_bucket, mock_enrichment_params)
        assert "not_a_real_bucket" in str(exc_info.value)
        assert "boxleiter_multipliers" in str(exc_info.value)

    def test_large_review_count_no_ceiling(self, mock_enrichment_params):
        """Very large review counts are not capped (no review-count ceiling decision)."""
        review_count = pd.Series([1000000])
        genre_bucket = pd.Series(["mainstream"])
        result = estimate_sales(review_count, genre_bucket, mock_enrichment_params)

        # 1,000,000 * 37 = 37,000,000
        assert result["estimated_sales_mid"].iloc[0] == 37000000.0

    def test_output_columns_exist(self, mock_enrichment_params):
        """Result has exactly the three expected columns."""
        review_count = pd.Series([100])
        genre_bucket = pd.Series(["mainstream"])
        result = estimate_sales(review_count, genre_bucket, mock_enrichment_params)

        expected_cols = {"estimated_sales_low", "estimated_sales_mid", "estimated_sales_high"}
        assert set(result.columns) == expected_cols

    def test_batch_processing(self, mock_enrichment_params):
        """Process multiple rows at once."""
        review_count = pd.Series([0, 100, 1000, 10000])
        genre_bucket = pd.Series(
            [
                "niche",
                "mainstream",
                "broad_audience",
                "niche",
            ]
        )
        result = estimate_sales(review_count, genre_bucket, mock_enrichment_params)

        assert len(result) == 4
        # Check first row (niche, 0 reviews)
        assert result.iloc[0]["estimated_sales_low"] == 0.0
        # Check second row (mainstream, 100 reviews)
        assert result.iloc[1]["estimated_sales_mid"] == 3700.0


# ============================================================================
# Tests for estimate_revenue
# ============================================================================


class TestEstimateRevenue:
    """Tests for revenue estimation (FORMULATION.md section 3)."""

    def test_reproduces_hand_computed_gross_and_net(self, mock_enrichment_params):
        """sales_mid=1000, price_usd=10, tau=0.30 yields gross=10000, net=7000."""
        sales = pd.DataFrame(
            {
                "estimated_sales_low": [800],
                "estimated_sales_mid": [1000],
                "estimated_sales_high": [1200],
            }
        )
        price_usd = pd.Series([10.0])
        result = estimate_revenue(sales, price_usd, mock_enrichment_params)

        assert result["estimated_revenue_gross_usd"].iloc[0] == 10000.0
        assert result["estimated_revenue_net_usd"].iloc[0] == 7000.0

    def test_free_to_play_yields_nan_not_zero(self, mock_enrichment_params):
        """price_usd=0 yields NaN for both revenue columns."""
        sales = pd.DataFrame(
            {
                "estimated_sales_low": [1000],
                "estimated_sales_mid": [5000],
                "estimated_sales_high": [10000],
            }
        )
        price_usd = pd.Series([0.0])
        result = estimate_revenue(sales, price_usd, mock_enrichment_params)

        assert pd.isna(result["estimated_revenue_gross_usd"].iloc[0])
        assert pd.isna(result["estimated_revenue_net_usd"].iloc[0])

    def test_zero_reviews_nonfree_yields_zero_not_null(self, mock_enrichment_params):
        """price_usd=10, sales_mid=0 yields gross=0.0, net=0.0 (not NaN)."""
        sales = pd.DataFrame(
            {
                "estimated_sales_low": [0],
                "estimated_sales_mid": [0],
                "estimated_sales_high": [0],
            }
        )
        price_usd = pd.Series([10.0])
        result = estimate_revenue(sales, price_usd, mock_enrichment_params)

        assert result["estimated_revenue_gross_usd"].iloc[0] == 0.0
        assert result["estimated_revenue_net_usd"].iloc[0] == 0.0

    def test_net_is_gross_minus_cut(self, mock_enrichment_params):
        """For non-F2P rows, net = gross * (1 - tau) exactly."""
        sales = pd.DataFrame(
            {
                "estimated_sales_low": [100],
                "estimated_sales_mid": [500],
                "estimated_sales_high": [900],
            }
        )
        price_usd = pd.Series([9.99])
        result = estimate_revenue(sales, price_usd, mock_enrichment_params)

        gross = result["estimated_revenue_gross_usd"].iloc[0]
        net = result["estimated_revenue_net_usd"].iloc[0]
        expected_net = gross * (1 - mock_enrichment_params.storefront_cut)
        assert abs(net - expected_net) < 1e-9

    def test_mixed_f2p_and_nonfree(self, mock_enrichment_params):
        """A batch with both F2P and non-F2P rows handles each correctly."""
        sales = pd.DataFrame(
            {
                "estimated_sales_low": [100, 500],
                "estimated_sales_mid": [100, 500],
                "estimated_sales_high": [100, 500],
            }
        )
        price_usd = pd.Series([0.0, 5.0])
        result = estimate_revenue(sales, price_usd, mock_enrichment_params)

        # F2P row
        assert pd.isna(result["estimated_revenue_gross_usd"].iloc[0])
        assert pd.isna(result["estimated_revenue_net_usd"].iloc[0])

        # Non-F2P row
        assert result["estimated_revenue_gross_usd"].iloc[1] == 2500.0
        assert result["estimated_revenue_net_usd"].iloc[1] == 1750.0

    def test_output_columns_exist(self, mock_enrichment_params):
        """Result has exactly the two expected columns."""
        sales = pd.DataFrame(
            {
                "estimated_sales_low": [100],
                "estimated_sales_mid": [100],
                "estimated_sales_high": [100],
            }
        )
        price_usd = pd.Series([10.0])
        result = estimate_revenue(sales, price_usd, mock_enrichment_params)

        expected_cols = {"estimated_revenue_gross_usd", "estimated_revenue_net_usd"}
        assert set(result.columns) == expected_cols

    def test_high_priced_title(self, mock_enrichment_params):
        """A high-priced title computes correctly."""
        sales = pd.DataFrame(
            {
                "estimated_sales_low": [100],
                "estimated_sales_mid": [200],
                "estimated_sales_high": [300],
            }
        )
        price_usd = pd.Series([39.99])
        result = estimate_revenue(sales, price_usd, mock_enrichment_params)

        gross = result["estimated_revenue_gross_usd"].iloc[0]
        net = result["estimated_revenue_net_usd"].iloc[0]
        # 200 * 39.99 = 7998
        assert abs(gross - 7998.0) < 0.01
        # 7998 * 0.70 = 5598.6
        assert abs(net - 5598.6) < 0.01

    def test_batch_processing(self, mock_enrichment_params):
        """Process multiple rows at once."""
        sales = pd.DataFrame(
            {
                "estimated_sales_low": [0, 100, 1000],
                "estimated_sales_mid": [0, 150, 1500],
                "estimated_sales_high": [0, 200, 2000],
            }
        )
        price_usd = pd.Series([0.0, 10.0, 19.99])
        result = estimate_revenue(sales, price_usd, mock_enrichment_params)

        # F2P row
        assert pd.isna(result.iloc[0]["estimated_revenue_gross_usd"])
        # Paid row with zero reviews
        assert result.iloc[1]["estimated_revenue_gross_usd"] == 1500.0
        # Paid row with sales
        expected_gross = 1500 * 19.99
        assert abs(result.iloc[2]["estimated_revenue_gross_usd"] - expected_gross) < 0.01


# ============================================================================
# Tests for compute_effort_adjusted_return
# ============================================================================


class TestComputeEffortAdjustedReturn:
    """Tests for effort-adjusted return (FORMULATION.md section 5)."""

    def test_finite_at_zero_complexity(self, mock_enrichment_params):
        """complexity=0.0, net_revenue=1000 yields 1000/0.05=20000.0."""
        net_revenue = pd.Series([1000.0])
        complexity = pd.Series([0.0])
        result = compute_effort_adjusted_return(net_revenue, complexity, mock_enrichment_params)

        assert result.iloc[0] == 20000.0

    def test_nan_propagates_from_free_to_play(self, mock_enrichment_params):
        """net_revenue=NaN yields NaN regardless of complexity."""
        net_revenue = pd.Series([np.nan])
        complexity = pd.Series([0.3])
        result = compute_effort_adjusted_return(net_revenue, complexity, mock_enrichment_params)

        assert pd.isna(result.iloc[0])

    def test_nan_propagates_from_missing_complexity(self, mock_enrichment_params):
        """complexity=NaN yields NaN."""
        net_revenue = pd.Series([500.0])
        complexity = pd.Series([np.nan])
        result = compute_effort_adjusted_return(net_revenue, complexity, mock_enrichment_params)

        assert pd.isna(result.iloc[0])

    def test_zero_revenue_nonfree_yields_zero(self, mock_enrichment_params):
        """net_revenue=0.0, complexity=0.5 yields 0.0, not NaN."""
        net_revenue = pd.Series([0.0])
        complexity = pd.Series([0.5])
        result = compute_effort_adjusted_return(net_revenue, complexity, mock_enrichment_params)

        assert result.iloc[0] == 0.0

    def test_typical_values(self, mock_enrichment_params):
        """Typical scenario: net_revenue=5000, complexity=0.6."""
        net_revenue = pd.Series([5000.0])
        complexity = pd.Series([0.6])
        result = compute_effort_adjusted_return(net_revenue, complexity, mock_enrichment_params)

        epsilon = mock_enrichment_params.effort_epsilon
        expected = 5000.0 / (0.6 + epsilon)
        assert abs(result.iloc[0] - expected) < 1e-9

    def test_complexity_clipped_to_one(self, mock_enrichment_params):
        """complexity=1.0 (max), net_revenue=1000."""
        net_revenue = pd.Series([1000.0])
        complexity = pd.Series([1.0])
        result = compute_effort_adjusted_return(net_revenue, complexity, mock_enrichment_params)

        epsilon = mock_enrichment_params.effort_epsilon
        expected = 1000.0 / (1.0 + epsilon)
        assert abs(result.iloc[0] - expected) < 1e-9

    def test_both_nan_yields_nan(self, mock_enrichment_params):
        """Both inputs NaN yields NaN."""
        net_revenue = pd.Series([np.nan])
        complexity = pd.Series([np.nan])
        result = compute_effort_adjusted_return(net_revenue, complexity, mock_enrichment_params)

        assert pd.isna(result.iloc[0])

    def test_batch_processing(self, mock_enrichment_params):
        """Process multiple rows with mixed NaN and valid values."""
        net_revenue = pd.Series([1000.0, np.nan, 0.0, 5000.0])
        complexity = pd.Series([0.0, 0.5, 0.5, np.nan])
        result = compute_effort_adjusted_return(net_revenue, complexity, mock_enrichment_params)

        assert len(result) == 4
        # Valid: net_revenue=1000, complexity=0
        assert result.iloc[0] == 20000.0
        # NaN from net_revenue
        assert pd.isna(result.iloc[1])
        # Valid: net_revenue=0, complexity=0.5
        assert result.iloc[2] == 0.0
        # NaN from complexity
        assert pd.isna(result.iloc[3])

    def test_ordinal_only_high_values_rank_high(self, mock_enrichment_params):
        """Effort-adjusted return ranks games with high net revenue high."""
        net_revenue = pd.Series([100.0, 1000.0, 10000.0])
        complexity = pd.Series([0.5, 0.5, 0.5])
        result = compute_effort_adjusted_return(net_revenue, complexity, mock_enrichment_params)

        # Verify monotonic increasing (ordinal ranking)
        assert result.iloc[0] < result.iloc[1] < result.iloc[2]

    def test_low_complexity_amplifies_return(self, mock_enrichment_params):
        """Same net revenue; lower complexity yields higher return."""
        net_revenue = pd.Series([1000.0, 1000.0])
        complexity = pd.Series([0.1, 0.9])
        result = compute_effort_adjusted_return(net_revenue, complexity, mock_enrichment_params)

        # Lower complexity (0.1) should yield higher effort-adjusted return
        assert result.iloc[0] > result.iloc[1]


# ============================================================================
# Integration Tests: Map -> Sales -> Revenue -> Effort
# ============================================================================


class TestEnrichmentPipeline:
    """Integration tests for the enrichment pipeline."""

    def test_end_to_end_with_realistic_game_data(self, mock_enrichment_params):
        """Process a realistic game through the entire pipeline."""
        # Start with raw game data
        genres = pd.Series([["Action", "Adventure"]])
        review_count = pd.Series([5000])
        price_usd = pd.Series([19.99])
        complexity = pd.Series([0.65])

        # Step 1: Map genre
        genre_bucket = map_genre_bucket(genres, mock_enrichment_params)
        assert genre_bucket.iloc[0] == "broad_audience"

        # Step 2: Estimate sales
        sales = estimate_sales(review_count, genre_bucket, mock_enrichment_params)
        assert sales["estimated_sales_mid"].iloc[0] == 250000.0

        # Step 3: Estimate revenue
        revenue = estimate_revenue(sales, price_usd, mock_enrichment_params)
        assert abs(revenue["estimated_revenue_gross_usd"].iloc[0] - 4997500.0) < 1.0
        assert abs(
            revenue["estimated_revenue_net_usd"].iloc[0]
            - 4997500.0 * (1 - mock_enrichment_params.storefront_cut)
        ) < 1.0

        # Step 4: Compute effort-adjusted return
        effort_return = compute_effort_adjusted_return(
            revenue["estimated_revenue_net_usd"], complexity, mock_enrichment_params
        )
        assert effort_return.iloc[0] > 0  # Should be finite and positive

    def test_end_to_end_with_free_to_play_game(self, mock_enrichment_params):
        """Process a free-to-play game through the pipeline (revenue stays NULL)."""
        # F2P game data
        genres = pd.Series([["Puzzle"]])
        review_count = pd.Series([10000])
        price_usd = pd.Series([0.0])  # F2P
        complexity = pd.Series([0.3])

        # Step 1: Map genre
        genre_bucket = map_genre_bucket(genres, mock_enrichment_params)
        assert genre_bucket.iloc[0] == "mainstream"

        # Step 2: Estimate sales
        sales = estimate_sales(review_count, genre_bucket, mock_enrichment_params)
        assert sales["estimated_sales_mid"].iloc[0] == 370000.0

        # Step 3: Estimate revenue (should be NaN for F2P)
        revenue = estimate_revenue(sales, price_usd, mock_enrichment_params)
        assert pd.isna(revenue["estimated_revenue_gross_usd"].iloc[0])
        assert pd.isna(revenue["estimated_revenue_net_usd"].iloc[0])

        # Step 4: Effort-adjusted return (should be NaN due to NaN revenue)
        effort_return = compute_effort_adjusted_return(
            revenue["estimated_revenue_net_usd"], complexity, mock_enrichment_params
        )
        assert pd.isna(effort_return.iloc[0])

    def test_end_to_end_zero_review_game(self, mock_enrichment_params):
        """Process a new game with no reviews."""
        genres = pd.Series([["Strategy"]])
        review_count = pd.Series([0])
        price_usd = pd.Series([9.99])
        complexity = pd.Series([0.4])

        # Step 1: Map genre
        genre_bucket = map_genre_bucket(genres, mock_enrichment_params)
        assert genre_bucket.iloc[0] == "niche"

        # Step 2: Estimate sales
        sales = estimate_sales(review_count, genre_bucket, mock_enrichment_params)
        assert sales["estimated_sales_mid"].iloc[0] == 0.0

        # Step 3: Estimate revenue
        revenue = estimate_revenue(sales, price_usd, mock_enrichment_params)
        assert revenue["estimated_revenue_gross_usd"].iloc[0] == 0.0
        assert revenue["estimated_revenue_net_usd"].iloc[0] == 0.0

        # Step 4: Effort-adjusted return (should be 0.0, finite)
        effort_return = compute_effort_adjusted_return(
            revenue["estimated_revenue_net_usd"], complexity, mock_enrichment_params
        )
        assert effort_return.iloc[0] == 0.0
