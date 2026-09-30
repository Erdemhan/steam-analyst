"""Unit tests for enrichment.complexity compute_complexity_score."""

import numpy as np
import pandas as pd
import pytest

from steam_analyst.config.settings import EnrichmentParams
from steam_analyst.enrichment.complexity import compute_complexity_score


@pytest.fixture
def mock_enrichment_params_with_bounds() -> EnrichmentParams:
    """EnrichmentParams with frozen bounds from a hypothetical run 1."""
    return EnrichmentParams(
        boxleiter_multipliers={
            "niche": (20, 27, 35),
            "mainstream": (30, 37, 45),
            "broad_audience": (40, 50, 65),
        },
        genre_bucket_map={
            "Strategy": "niche",
            "Simulation": "niche",
            "Puzzle": "mainstream",
            "RPG": "mainstream",
            "Horror": "mainstream",
            "Adventure": "mainstream",
            "Action": "broad_audience",
            "Arcade": "broad_audience",
            "FPS": "broad_audience",
            "Multiplayer": "broad_audience",
        },
        storefront_cut=0.30,
        discount_factor=0.0,
        refund_regional_factor=0.0,
        complexity_weights={
            "size_bytes": 0.20,
            "early_access_days": 0.15,
            "dev_title_count": 0.15,
            "simplicity_tag_score": 0.10,
            "complexity_tag_score": 0.10,
            "achievement_count": 0.10,
            "dlc_count": 0.10,
            "platform_count": 0.05,
            "language_count": 0.05,
        },
        complexity_bounds={
            "size_bytes": (8.0, 10.5),
            "early_access_days": (0.0, 3.0),
            "dev_title_count": (0.0, 2.5),
            "achievement_count": (0.0, 3.0),
            "dlc_count": (0.0, 2.5),
            "language_count": (0.0, 2.5),
        },
        simplicity_tags=["Pixel Graphics", "2D", "Casual", "Short", "Singleplayer"],
        complexity_tags=["Open World", "Multiplayer", "Physics", "Procedural Generation"],
        effort_epsilon=0.05,
        tag_extraction_max_per_game=20,
        tag_extraction_min_votes=0,
    )


@pytest.fixture
def mock_enrichment_params_pre_freeze() -> EnrichmentParams:
    """EnrichmentParams with empty bounds (pre-freeze run 1)."""
    return EnrichmentParams(
        boxleiter_multipliers={
            "niche": (20, 27, 35),
            "mainstream": (30, 37, 45),
            "broad_audience": (40, 50, 65),
        },
        genre_bucket_map={},
        storefront_cut=0.30,
        discount_factor=0.0,
        refund_regional_factor=0.0,
        complexity_weights={
            "size_bytes": 0.20,
            "early_access_days": 0.15,
            "dev_title_count": 0.15,
            "simplicity_tag_score": 0.10,
            "complexity_tag_score": 0.10,
            "achievement_count": 0.10,
            "dlc_count": 0.10,
            "platform_count": 0.05,
            "language_count": 0.05,
        },
        complexity_bounds={},  # Pre-freeze: empty
        simplicity_tags=["Pixel Graphics", "2D", "Casual", "Short", "Singleplayer"],
        complexity_tags=["Open World", "Multiplayer", "Physics", "Procedural Generation"],
        effort_epsilon=0.05,
        tag_extraction_max_per_game=20,
        tag_extraction_min_votes=0,
    )


class TestComputeComplexityScoreFundamental:
    """Test basic functionality and edge cases."""

    def test_empty_frame_returns_empty_series(self):
        """An empty input frame returns an empty series and dataframe."""
        frame = pd.DataFrame()
        tags = pd.DataFrame()
        params = pytest.importorskip("steam_analyst.config.settings").EnrichmentParams(
            boxleiter_multipliers={},
            genre_bucket_map={},
            storefront_cut=0.30,
            discount_factor=0.0,
            refund_regional_factor=0.0,
            complexity_weights={
                "size_bytes": 0.20,
                "early_access_days": 0.15,
                "dev_title_count": 0.15,
                "simplicity_tag_score": 0.10,
                "complexity_tag_score": 0.10,
                "achievement_count": 0.10,
                "dlc_count": 0.10,
                "platform_count": 0.05,
                "language_count": 0.05,
            },
            complexity_bounds={},
            simplicity_tags=[],
            complexity_tags=[],
            effort_epsilon=0.05,
            tag_extraction_max_per_game=20,
            tag_extraction_min_votes=0,
        )
        score, contrib = compute_complexity_score(frame, tags, params)
        assert len(score) == 0
        assert len(contrib) == 0

    def test_output_series_indexed_by_appid(self, mock_enrichment_params_with_bounds):
        """Complexity score series is indexed by appid, same as input frame."""
        frame = pd.DataFrame(
            {
                "size_bytes": [1e9, 2e9],
                "is_early_access": [False, True],
                "early_access_days": [np.nan, 30.0],
                "dev_title_count": [0, 5],
                "achievement_count": [10, 20],
                "dlc_count": [0, 2],
                "platform_count": [1, 3],
                "language_count": [1, 10],
            },
            index=pd.Index([100, 200], name="appid"),
        )
        tags = pd.DataFrame(
            {
                "appid": [100, 100, 200, 200],
                "tag": ["2D", "Casual", "Open World", "Multiplayer"],
                "votes": [10, 8, 15, 12],
                "rank": [1, 2, 1, 2],
            }
        )
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )
        assert score.index.equals(frame.index)
        assert contrib.index.equals(frame.index)

    def test_output_has_all_nine_feature_columns(self, mock_enrichment_params_with_bounds):
        """Contributions dataframe has exactly 9 columns (one per feature)."""
        frame = pd.DataFrame(
            {
                "size_bytes": [1e9],
                "is_early_access": [False],
                "early_access_days": [0.0],
                "dev_title_count": [1],
                "achievement_count": [5],
                "dlc_count": [0],
                "platform_count": [2],
                "language_count": [2],
            },
            index=pd.Index([100], name="appid"),
        )
        tags = pd.DataFrame()
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )
        expected_features = [
            "size_bytes",
            "early_access_days",
            "dev_title_count",
            "simplicity_tag_score",
            "complexity_tag_score",
            "achievement_count",
            "dlc_count",
            "platform_count",
            "language_count",
        ]
        assert list(contrib.columns) == expected_features

    def test_contributions_sum_to_score_for_nonnan_rows(
        self, mock_enrichment_params_with_bounds
    ):
        """For non-NaN scores, the sum of contributions equals the score."""
        frame = pd.DataFrame(
            {
                "size_bytes": [1e9, 2e9],
                "is_early_access": [False, False],
                "early_access_days": [0.0, 0.0],
                "dev_title_count": [1, 2],
                "achievement_count": [10, 20],
                "dlc_count": [1, 2],
                "platform_count": [2, 2],
                "language_count": [5, 10],
            },
            index=pd.Index([100, 200], name="appid"),
        )
        tags = pd.DataFrame()
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )
        # Sum contributions for each row
        contrib_sums = contrib.sum(axis=1)
        # Should match the score (before final clipping, they already match)
        pd.testing.assert_series_equal(contrib_sums, score, atol=1e-9)


class TestComplexityScoreNormalization:
    """Test feature normalization and combination."""

    def test_clipping_holds_at_extremes_all_min_features(
        self, mock_enrichment_params_with_bounds
    ):
        """An all-minimum-feature row scores 0.0."""
        frame = pd.DataFrame(
            {
                "size_bytes": [1.0],  # Very small, will normalize to ~0
                "is_early_access": [False],
                "early_access_days": [0.0],  # 0 days, will normalize to 0
                "dev_title_count": [0],  # No other titles, will normalize to ~0
                "achievement_count": [0],  # No achievements
                "dlc_count": [0],  # No DLC
                "platform_count": [1],  # Only 1 platform: (1-1)/2 = 0
                "language_count": [1],  # Only 1 language: log10(2)/2.5 ~= 0.12
            },
            index=pd.Index([100], name="appid"),
        )
        tags = pd.DataFrame(
            {
                "appid": [100, 100],
                "tag": ["2D", "Casual"],  # All simplicity tags
                "votes": [10, 8],
                "rank": [1, 2],
            }
        )
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )
        # Score should be very close to 0
        assert score[100] < 0.15  # Allow some tolerance for minor features

    def test_clipping_holds_at_extremes_all_max_features(
        self, mock_enrichment_params_with_bounds
    ):
        """An all-maximum-feature row scores 1.0 (or close to it)."""
        frame = pd.DataFrame(
            {
                "size_bytes": [1e12],  # Very large
                "is_early_access": [True],
                "early_access_days": [1000.0],  # Long EA duration
                "dev_title_count": [100],  # Very prolific developer
                "achievement_count": [500],  # Many achievements
                "dlc_count": [50],  # Much DLC
                "platform_count": [3],  # All platforms: (3-1)/2 = 1.0
                "language_count": [50],  # Many languages
            },
            index=pd.Index([100], name="appid"),
        )
        tags = pd.DataFrame(
            {
                "appid": [100, 100, 100],
                "tag": ["Open World", "Multiplayer", "Physics"],  # All complexity tags
                "votes": [100, 90, 80],
                "rank": [1, 2, 3],
            }
        )
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )
        # Score should be high (near or at 1.0 due to clipping)
        assert score[100] > 0.85

    def test_platform_count_normalization(self, mock_enrichment_params_with_bounds):
        """Platform count is normalized as (count-1)/2."""
        frame = pd.DataFrame(
            {
                "size_bytes": [100.0],  # Minimal normalized value
                "is_early_access": [False],
                "early_access_days": [0.0],
                "dev_title_count": [1],
                "achievement_count": [1],
                "dlc_count": [0],
                "platform_count": [1],  # (1-1)/2 = 0.0
                "language_count": [1],
            },
            index=pd.Index([100], name="appid"),
        )
        tags = pd.DataFrame()
        score1, contrib1 = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )
        platform_contrib_1 = contrib1.loc[100, "platform_count"]

        frame.loc[100, "platform_count"] = 2  # (2-1)/2 = 0.5
        score2, contrib2 = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )
        platform_contrib_2 = contrib2.loc[100, "platform_count"]

        frame.loc[100, "platform_count"] = 3  # (3-1)/2 = 1.0
        score3, contrib3 = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )
        platform_contrib_3 = contrib3.loc[100, "platform_count"]

        # Platform contributions should increase
        assert platform_contrib_1 < platform_contrib_2 < platform_contrib_3
        # Verify the exact normalized values
        assert abs(platform_contrib_1 - 0.0 * 0.05) < 1e-9  # 0.0 * weight
        assert abs(platform_contrib_2 - 0.5 * 0.05) < 1e-9  # 0.5 * weight
        assert abs(platform_contrib_3 - 1.0 * 0.05) < 1e-9  # 1.0 * weight

    def test_simplicity_tag_score_inverted(self, mock_enrichment_params_with_bounds):
        """High simplicity tag score -> low complexity contribution."""
        frame = pd.DataFrame(
            {
                "size_bytes": [1e9, 1e9],
                "is_early_access": [False, False],
                "early_access_days": [0.0, 0.0],
                "dev_title_count": [1, 1],
                "achievement_count": [10, 10],
                "dlc_count": [0, 0],
                "platform_count": [2, 2],
                "language_count": [5, 5],
            },
            index=pd.Index([100, 200], name="appid"),
        )

        # Tags: appid 100 has simplicity tags, appid 200 has complexity tags
        tags = pd.DataFrame(
            {
                "appid": [100, 100, 100, 200, 200, 200],
                "tag": ["2D", "Casual", "Pixel Graphics", "Open World", "Multiplayer", "Physics"],
                "votes": [50, 40, 30, 50, 40, 30],
                "rank": [1, 2, 3, 1, 2, 3],
            }
        )
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )

        # Appid 100 has high simplicity -> low complexity contribution from tags
        # Appid 200 has high complexity -> high complexity contribution from tags
        assert score[100] < score[200]


class TestMedianImputation:
    """Test missing value imputation behavior."""

    def test_median_imputation_applied_and_flagged(
        self, mock_enrichment_params_with_bounds
    ):
        """A row missing achievement_count gets that feature's contribution at the cohort median."""
        frame = pd.DataFrame(
            {
                "size_bytes": [1e9, 2e9, 3e9],
                "is_early_access": [False, False, False],
                "early_access_days": [0.0, 0.0, 0.0],
                "dev_title_count": [1, 1, 1],
                "achievement_count": [10, np.nan, 30],  # Row 1 is missing
                "dlc_count": [0, 0, 0],
                "platform_count": [2, 2, 2],
                "language_count": [5, 5, 5],
            },
            index=pd.Index([100, 200, 300], name="appid"),
        )
        tags = pd.DataFrame(
            {
                "appid": [100, 200, 300],
                "tag": ["Short", "Short", "Short"],  # Neutral tag for all
                "votes": [10, 10, 10],
                "rank": [1, 1, 1],
            }
        )
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )

        # Row 200 should have achievement_count imputed at the median of normalized values
        # achievement_count raw: [10, np.nan, 30]
        # Normalized with bounds (0, 3):
        # log10(10+1) = 1.041, then (1.041-0)/3 = 0.347
        # log10(30+1) = 1.491, then (1.491-0)/3 = 0.497
        # Median of [0.347, 0.497] = 0.422
        # Contribution: 0.422 * 0.10 = 0.0422
        achievement_contrib_200 = contrib.loc[200, "achievement_count"]
        norm_10 = (np.log10(10 + 1) - 0.0) / (3.0 - 0.0)
        norm_30 = (np.log10(30 + 1) - 0.0) / (3.0 - 0.0)
        expected_median_norm = (norm_10 + norm_30) / 2.0
        expected_contrib = expected_median_norm * 0.10
        assert abs(achievement_contrib_200 - expected_contrib) < 1e-9

        # Row 200's score should not be NaN (only 1 of 9 features imputed)
        assert not pd.isna(score[200])

    def test_all_rows_missing_one_feature_falls_back_to_midpoint(
        self, mock_enrichment_params_with_bounds
    ):
        """A feature that is NaN for every row falls back to 0.5 midpoint."""
        frame = pd.DataFrame(
            {
                "size_bytes": [1e9, 2e9],
                "is_early_access": [True, True],  # Important: True so that early_access_days stays NaN
                "early_access_days": [np.nan, np.nan],  # All missing
                "dev_title_count": [1, 1],
                "achievement_count": [10, 20],
                "dlc_count": [0, 0],
                "platform_count": [2, 2],
                "language_count": [5, 5],
            },
            index=pd.Index([100, 200], name="appid"),
        )
        tags = pd.DataFrame()
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )

        # early_access_days contribution should be 0.5 * 0.15 for all rows
        expected_early_access_contrib = 0.5 * 0.15
        for appid in [100, 200]:
            assert abs(
                contrib.loc[appid, "early_access_days"] - expected_early_access_contrib
            ) < 1e-9

        # Scores should not be NaN
        assert not pd.isna(score[100])
        assert not pd.isna(score[200])


class TestTooMuchMissingData:
    """Test nullification of scores when too many features are missing."""

    def test_too_much_missing_data_yields_null_score(
        self, mock_enrichment_params_with_bounds
    ):
        """A row missing 6 of 9 features yields complexity_score == NaN."""
        frame = pd.DataFrame(
            {
                "size_bytes": [np.nan],  # Missing
                "is_early_access": [False],
                "early_access_days": [np.nan],  # Missing
                "dev_title_count": [np.nan],  # Missing
                "achievement_count": [np.nan],  # Missing
                "dlc_count": [np.nan],  # Missing
                "platform_count": [np.nan],  # Missing
                "language_count": [5],  # Present
            },
            index=pd.Index([100], name="appid"),
        )
        tags = pd.DataFrame()
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )

        # 6 of 9 features missing = 66.7% > 40% threshold
        assert pd.isna(score[100])

    def test_below_too_much_missing_threshold_yields_valid_score(
        self, mock_enrichment_params_with_bounds
    ):
        """A row missing 3 of 9 features (33%) still gets a valid score."""
        frame = pd.DataFrame(
            {
                "size_bytes": [np.nan],  # Missing
                "is_early_access": [False],
                "early_access_days": [np.nan],  # Missing
                "dev_title_count": [np.nan],  # Missing
                "achievement_count": [10],  # Present
                "dlc_count": [0],  # Present
                "platform_count": [2],  # Present
                "language_count": [5],  # Present
            },
            index=pd.Index([100], name="appid"),
        )
        tags = pd.DataFrame()
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )

        # 3 of 9 features missing = 33.3% < 40% threshold
        assert not pd.isna(score[100])
        assert 0.0 <= score[100] <= 1.0


class TestPreFreezeScenario:
    """Test behavior when complexity_bounds is empty (pre-freeze run 1)."""

    def test_empty_complexity_bounds_pre_freeze(self, mock_enrichment_params_pre_freeze):
        """With params.complexity_bounds == {}, log-scaled features are imputed at cohort median."""
        frame = pd.DataFrame(
            {
                "size_bytes": [1e9, 2e9, 3e9],
                "is_early_access": [False, False, False],
                "early_access_days": [0.0, 0.0, 0.0],
                "dev_title_count": [1, 2, 3],
                "achievement_count": [10, 20, 30],
                "dlc_count": [0, 1, 2],
                "platform_count": [1, 2, 3],
                "language_count": [5, 10, 15],
            },
            index=pd.Index([100, 200, 300], name="appid"),
        )
        tags = pd.DataFrame()
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_pre_freeze
        )

        # All log-scaled features should have identical contribution across all rows
        # (imputed at the cohort median, which is the same for everyone)
        log_scaled_features = [
            "size_bytes",
            "early_access_days",
            "dev_title_count",
            "achievement_count",
            "dlc_count",
            "language_count",
        ]

        for feature in log_scaled_features:
            contrib_values = contrib[feature].values
            # All values should be the same (0.5 * weight, since all imputed at median)
            assert np.allclose(
                contrib_values, contrib_values[0]
            ), f"Feature {feature} has varying contributions: {contrib_values}"

    def test_pre_freeze_only_linear_features_vary(self, mock_enrichment_params_pre_freeze):
        """In pre-freeze, only platform_count and tag scores vary across rows."""
        frame = pd.DataFrame(
            {
                "size_bytes": [1e9, 2e9, 3e9],
                "is_early_access": [False, False, False],
                "early_access_days": [0.0, 0.0, 0.0],
                "dev_title_count": [1, 2, 3],
                "achievement_count": [10, 20, 30],
                "dlc_count": [0, 1, 2],
                "platform_count": [1, 2, 3],  # Varying
                "language_count": [5, 10, 15],
            },
            index=pd.Index([100, 200, 300], name="appid"),
        )
        tags = pd.DataFrame(
            {
                "appid": [100, 200, 300],
                "tag": ["2D", "Open World", "Multiplayer"],
                "votes": [50, 50, 50],
                "rank": [1, 1, 1],
            }
        )
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_pre_freeze
        )

        # Platform count contributions should vary
        platform_contribs = contrib["platform_count"].values
        assert not np.allclose(platform_contribs, platform_contribs[0])

        # Simplicity tag score contributions should vary (and be negative for row 200/300)
        simplicity_contribs = contrib["simplicity_tag_score"].values
        assert not np.allclose(simplicity_contribs, simplicity_contribs[0])

        # But log-scaled features should be identical
        for feature in ["size_bytes", "dev_title_count", "achievement_count"]:
            feature_contribs = contrib[feature].values
            assert np.allclose(
                feature_contribs, feature_contribs[0]
            ), f"Pre-freeze feature {feature} should have identical contribs"


class TestWeightedSumCorrectness:
    """Test weighted sum computation against hand-calculated values."""

    def test_weighted_sum_matches_hand_computation(
        self, mock_enrichment_params_with_bounds
    ):
        """Verify exact hand-computed weighted sum."""
        # Create a synthetic row with all known normalized values
        frame = pd.DataFrame(
            {
                "size_bytes": [100.0],  # log10(101) ≈ 2.004, (2.004-8)/(10.5-8) ≈ -2.135 -> 0 (clipped)
                "is_early_access": [False],
                "early_access_days": [0.0],  # (0-0)/(3-0) = 0
                "dev_title_count": [1.0],  # log10(2) ≈ 0.301, (0.301-0)/(2.5-0) ≈ 0.120
                "achievement_count": [100.0],  # log10(101) ≈ 2.004, (2.004-0)/(3-0) ≈ 0.668
                "dlc_count": [1.0],  # log10(2) ≈ 0.301, (0.301-0)/(2.5-0) ≈ 0.120
                "platform_count": [2],  # (2-1)/2 = 0.5
                "language_count": [10.0],  # log10(11) ≈ 1.041, (1.041-0)/(2.5-0) ≈ 0.416
            },
            index=pd.Index([100], name="appid"),
        )
        tags = pd.DataFrame(
            {
                "appid": [100],
                "tag": ["2D"],  # simplicity_tag_score = 1.0, inverted -> 0.0
                "votes": [50],
                "rank": [1],
            }
        )
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )

        # Hand-compute expected score:
        # size_bytes: 0.0 * 0.20 = 0.0
        # early_access_days: 0.0 * 0.15 = 0.0
        # dev_title_count: 0.120 * 0.15 ≈ 0.018
        # simplicity_tag_score: (1.0 - 1.0) * 0.10 = 0.0  # inverted
        # complexity_tag_score: 0.0 * 0.10 = 0.0  # no complexity tags
        # achievement_count: 0.668 * 0.10 ≈ 0.0668
        # dlc_count: 0.120 * 0.10 ≈ 0.012
        # platform_count: 0.5 * 0.05 = 0.025
        # language_count: 0.416 * 0.05 ≈ 0.0208
        # Total ≈ 0.0 + 0.0 + 0.018 + 0.0 + 0.0 + 0.0668 + 0.012 + 0.025 + 0.0208 ≈ 0.1426

        expected_score = 0.1426
        assert abs(score[100] - expected_score) < 0.01  # Allow 0.01 tolerance

        # Verify contributions sum to score
        contrib_sum = contrib.loc[100].sum()
        assert abs(contrib_sum - score[100]) < 1e-9


class TestEdgeCases:
    """Test various edge cases and boundary conditions."""

    def test_all_nan_input_frame_column(self, mock_enrichment_params_with_bounds):
        """An input column that is all NaN falls back to cohort median (0.5)."""
        frame = pd.DataFrame(
            {
                "size_bytes": [1e9, 1e9],
                "is_early_access": [True, True],  # Important: True so that early_access_days stays NaN
                "early_access_days": [np.nan, np.nan],  # All NaN
                "dev_title_count": [1, 1],
                "achievement_count": [10, 10],
                "dlc_count": [0, 0],
                "platform_count": [2, 2],
                "language_count": [5, 5],
            },
            index=pd.Index([100, 200], name="appid"),
        )
        tags = pd.DataFrame()
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )

        # early_access_days should contribute 0.5 * 0.15 for all rows
        for appid in [100, 200]:
            assert abs(
                contrib.loc[appid, "early_access_days"] - 0.5 * 0.15
            ) < 1e-9

    def test_single_row_frame(self, mock_enrichment_params_with_bounds):
        """A single-row frame processes correctly."""
        frame = pd.DataFrame(
            {
                "size_bytes": [5e9],
                "is_early_access": [True],
                "early_access_days": [90.0],
                "dev_title_count": [10],
                "achievement_count": [50],
                "dlc_count": [5],
                "platform_count": [3],
                "language_count": [20],
            },
            index=pd.Index([999], name="appid"),
        )
        tags = pd.DataFrame()
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )

        assert len(score) == 1
        assert len(contrib) == 1
        assert 0.0 <= score[999] <= 1.0

    def test_values_clipped_to_zero_one_range(self, mock_enrichment_params_with_bounds):
        """Score values are always in [0, 1]."""
        # Create 100 random frames and verify all scores are in valid range
        np.random.seed(42)
        for _ in range(10):
            frame = pd.DataFrame(
                {
                    "size_bytes": np.random.uniform(1e7, 1e12, 20),
                    "is_early_access": np.random.choice([True, False], 20),
                    "early_access_days": np.random.uniform(0, 365, 20),
                    "dev_title_count": np.random.uniform(0, 100, 20),
                    "achievement_count": np.random.uniform(0, 500, 20),
                    "dlc_count": np.random.uniform(0, 50, 20),
                    "platform_count": np.random.choice([1, 2, 3], 20),
                    "language_count": np.random.uniform(1, 50, 20),
                },
                index=pd.Index(range(20), name="appid"),
            )
            tags = pd.DataFrame()
            score, contrib = compute_complexity_score(
                frame, tags, mock_enrichment_params_with_bounds
            )

            # All non-NaN scores should be in [0, 1]
            valid_scores = score.dropna()
            assert (valid_scores >= 0.0).all()
            assert (valid_scores <= 1.0).all()

    def test_zero_values_in_features(self, mock_enrichment_params_with_bounds):
        """Zero values in log-scaled features don't cause math errors."""
        frame = pd.DataFrame(
            {
                "size_bytes": [0],  # log10(0+1) = 0
                "is_early_access": [False],
                "early_access_days": [0.0],
                "dev_title_count": [0],  # log10(0+1) = 0
                "achievement_count": [0],
                "dlc_count": [0],
                "platform_count": [1],
                "language_count": [0],  # log10(0+1) = 0
            },
            index=pd.Index([100], name="appid"),
        )
        tags = pd.DataFrame()
        score, contrib = compute_complexity_score(
            frame, tags, mock_enrichment_params_with_bounds
        )

        # Should not raise an error
        assert not pd.isna(score[100])
        assert 0.0 <= score[100] <= 1.0
