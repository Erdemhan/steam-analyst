"""Unit tests for enrichment.features pure statistical helpers."""

import numpy as np
import pandas as pd
import pytest

from steam_analyst.enrichment.features import (
    compute_developer_catalog_size,
    compute_tag_score,
    impute_missing_at_median,
    normalize_feature_log_scaled,
)


# ============================================================================
# Tests for normalize_feature_log_scaled
# ============================================================================


class TestNormalizeFeatureLogScaled:
    """Test log-scaled normalization n(x) = clip((log10(x+1) - a) / (b - a), 0, 1)."""

    def test_clips_at_zero_when_x_below_a(self):
        """Values with log10(x+1) < a clip to 0.0."""
        # x=0 -> log10(1)=0; a=1, b=5 -> (0-1)/(5-1) = -1/4 -> clip to 0.0
        result = normalize_feature_log_scaled(x=0, a=1.0, b=5.0)
        assert result == 0.0

    def test_clips_at_one_when_x_beyond_b(self):
        """Values with log10(x+1) > b clip to 1.0."""
        # x=10^6 -> log10(10^6+1) ≈ 6.0+; a=0, b=4 -> beyond upper bound -> clip to 1.0
        result = normalize_feature_log_scaled(x=10**6, a=0.0, b=4.0)
        assert result == 1.0

    def test_linear_at_bound_a_returns_zero(self):
        """When log10(x+1) == a, returns exactly 0.0."""
        # log10(x+1) = 2 -> x+1 = 100 -> x = 99
        result = normalize_feature_log_scaled(x=99, a=2.0, b=5.0)
        assert result == 0.0

    def test_linear_at_bound_b_returns_one(self):
        """When log10(x+1) == b, returns exactly 1.0."""
        # log10(x+1) = 3 -> x+1 = 1000 -> x = 999
        result = normalize_feature_log_scaled(x=999, a=2.0, b=3.0)
        assert result == 1.0

    def test_midpoint_returns_half(self):
        """A value exactly halfway between a and b on log scale returns 0.5."""
        # a=0, b=6
        # midpoint on log scale: log10(x+1) = 3
        # x+1 = 10^3 = 1000 -> x = 999
        result = normalize_feature_log_scaled(x=999, a=0.0, b=6.0)
        assert abs(result - 0.5) < 1e-9

    def test_monotonic_increase(self):
        """Values are monotonically non-decreasing in x for fixed a, b."""
        a, b = 0.0, 5.0
        x_values = [0, 1, 10, 100, 1000, 10000]
        results = [normalize_feature_log_scaled(x, a, b) for x in x_values]
        for i in range(len(results) - 1):
            assert results[i] <= results[i + 1]

    def test_degenerate_bounds_raises_valueerror(self):
        """a == b raises ValueError."""
        with pytest.raises(ValueError, match="Degenerate bounds"):
            normalize_feature_log_scaled(x=10, a=2.0, b=2.0)

    def test_negative_x_raises_valueerror(self):
        """x < 0 raises ValueError."""
        with pytest.raises(ValueError, match="x must be >= 0"):
            normalize_feature_log_scaled(x=-1, a=0.0, b=5.0)

    def test_returns_float(self):
        """Return type is float."""
        result = normalize_feature_log_scaled(x=10, a=0.0, b=5.0)
        assert isinstance(result, float)

    def test_realistic_scenario_size_bytes(self):
        """Real-world scenario: install size normalization."""
        # Empirical bounds for install size (in log10 bytes space): a≈8.0, b≈10.5
        # Small game: 100 MB = 10^8 bytes -> log10(10^8+1) ≈ 8.0
        # Large game: 100 GB = 10^11 bytes -> log10(10^11+1) ≈ 11.0
        size_small = 100 * 1024**2  # 100 MB
        size_medium = 10 * 1024**3  # 10 GB
        size_large = 100 * 1024**3  # 100 GB

        a, b = 8.0, 10.5
        score_small = normalize_feature_log_scaled(size_small, a, b)
        score_medium = normalize_feature_log_scaled(size_medium, a, b)
        score_large = normalize_feature_log_scaled(size_large, a, b)

        # Small game should score low, large game should score high
        assert score_small < score_medium < score_large
        assert 0.0 <= score_small <= 1.0
        assert 0.0 <= score_large <= 1.0


# ============================================================================
# Tests for impute_missing_at_median
# ============================================================================


class TestImputeMissingAtMedian:
    """Test median imputation and flagging of imputed rows."""

    def test_no_missing_values_unchanged(self):
        """A Series with no NaN returns itself unchanged."""
        values = pd.Series([0.2, 0.4, 0.6, 0.8], index=[0, 1, 2, 3])
        imputed, was_imputed = impute_missing_at_median(values)

        pd.testing.assert_series_equal(imputed, values)
        assert was_imputed.sum() == 0
        assert not was_imputed.any()

    def test_imputes_at_median_and_flags(self):
        """NaN values are replaced with cohort median, flagged as imputed."""
        values = pd.Series([0.2, np.nan, 0.4, 0.6], index=[0, 1, 2, 3])
        imputed, was_imputed = impute_missing_at_median(values)

        # Median of [0.2, 0.4, 0.6] = 0.4
        expected_imputed = pd.Series([0.2, 0.4, 0.4, 0.6], index=[0, 1, 2, 3])
        pd.testing.assert_series_equal(imputed, expected_imputed)

        expected_was_imputed = pd.Series(
            [False, True, False, False], index=[0, 1, 2, 3]
        )
        pd.testing.assert_series_equal(was_imputed, expected_was_imputed)

    def test_multiple_missing_values(self):
        """Multiple NaN values imputed at same median."""
        values = pd.Series([0.1, np.nan, 0.3, np.nan, 0.5])
        imputed, was_imputed = impute_missing_at_median(values)

        # Median of [0.1, 0.3, 0.5] = 0.3
        expected_imputed = pd.Series([0.1, 0.3, 0.3, 0.3, 0.5])
        pd.testing.assert_series_equal(imputed, expected_imputed)

        expected_was_imputed = pd.Series([False, True, False, True, False])
        pd.testing.assert_series_equal(was_imputed, expected_was_imputed)

    def test_even_number_of_values_uses_interpolation(self):
        """Even-sized series uses pandas median interpolation (average of middle two)."""
        # [0.2, 0.4] -> median = 0.3
        values = pd.Series([0.2, np.nan, np.nan, 0.4])
        imputed, was_imputed = impute_missing_at_median(values)

        # Median of [0.2, 0.4] = 0.3
        expected_imputed = pd.Series([0.2, 0.3, 0.3, 0.4])
        pd.testing.assert_series_equal(imputed, expected_imputed)

    def test_all_nan_raises_valueerror(self):
        """Entirely NaN series raises ValueError."""
        values = pd.Series([np.nan, np.nan, np.nan])
        with pytest.raises(ValueError, match="entirely NaN"):
            impute_missing_at_median(values)

    def test_single_non_nan_uses_that_value(self):
        """If only one non-NaN value, median is that value."""
        values = pd.Series([np.nan, 0.5, np.nan])
        imputed, was_imputed = impute_missing_at_median(values)

        expected_imputed = pd.Series([0.5, 0.5, 0.5])
        pd.testing.assert_series_equal(imputed, expected_imputed)

    def test_preserves_index(self):
        """Output Series preserve original index."""
        index = ["a", "b", "c", "d"]
        values = pd.Series([0.2, np.nan, 0.4, 0.6], index=index)
        imputed, was_imputed = impute_missing_at_median(values)

        assert list(imputed.index) == index
        assert list(was_imputed.index) == index

    def test_first_value_missing(self):
        """Imputation works when first value is NaN."""
        values = pd.Series([np.nan, 0.3, 0.5])
        imputed, was_imputed = impute_missing_at_median(values)

        # Median of [0.3, 0.5] = 0.4
        expected_imputed = pd.Series([0.4, 0.3, 0.5])
        pd.testing.assert_series_equal(imputed, expected_imputed)
        assert was_imputed[0]

    def test_last_value_missing(self):
        """Imputation works when last value is NaN."""
        values = pd.Series([0.1, 0.3, np.nan])
        imputed, was_imputed = impute_missing_at_median(values)

        # Median of [0.1, 0.3] = 0.2
        expected_imputed = pd.Series([0.1, 0.3, 0.2])
        pd.testing.assert_series_equal(imputed, expected_imputed)
        assert was_imputed[2]


# ============================================================================
# Tests for compute_tag_score
# ============================================================================


class TestComputeTagScore:
    """Test tag-match score computation."""

    def test_all_tags_match_vocabulary_scores_one(self):
        """An appid with tags entirely in vocabulary scores 1.0."""
        tags_data = {
            "appid": [1, 1, 1],
            "tag": ["Pixel Graphics", "2D", "Casual"],
            "votes": [100, 100, 100],
            "rank": [1, 2, 3],
        }
        tags = pd.DataFrame(tags_data)
        vocabulary = ["pixel graphics", "2d", "casual"]

        score = compute_tag_score(tags, vocabulary=vocabulary)

        assert score[1] == 1.0

    def test_no_tags_match_vocabulary_scores_zero(self):
        """An appid with no matching tags scores 0.0."""
        tags_data = {
            "appid": [1, 1, 1],
            "tag": ["Open World", "Multiplayer", "Physics"],
            "votes": [100, 100, 100],
            "rank": [1, 2, 3],
        }
        tags = pd.DataFrame(tags_data)
        vocabulary = ["pixel graphics", "2d", "casual"]

        score = compute_tag_score(tags, vocabulary=vocabulary)

        assert score[1] == 0.0

    def test_partial_match_computes_ratio(self):
        """Partial matches score as the ratio of matching tags."""
        tags_data = {
            "appid": [1, 1, 1, 1],
            "tag": ["Pixel Graphics", "2D", "Open World", "Multiplayer"],
            "votes": [100, 100, 100, 100],
            "rank": [1, 2, 3, 4],
        }
        tags = pd.DataFrame(tags_data)
        vocabulary = ["pixel graphics", "2d"]

        score = compute_tag_score(tags, vocabulary=vocabulary)

        # 2 out of 4 tags match -> 0.5
        assert score[1] == 0.5

    def test_case_insensitive_matching(self):
        """Tag matching is case-insensitive."""
        tags_data = {
            "appid": [1, 1],
            "tag": ["Pixel Graphics", "CASUAL"],
            "votes": [100, 100],
            "rank": [1, 2],
        }
        tags = pd.DataFrame(tags_data)
        vocabulary = ["pixel graphics", "casual"]

        score = compute_tag_score(tags, vocabulary=vocabulary)

        assert score[1] == 1.0

    def test_mixed_case_mismatch(self):
        """Case-insensitive handles mixed case in both tag and vocabulary."""
        tags_data = {
            "appid": [1],
            "tag": ["PiXeL GrApHiCs"],
            "votes": [100],
            "rank": [1],
        }
        tags = pd.DataFrame(tags_data)
        vocabulary = ["Pixel Graphics"]

        score = compute_tag_score(tags, vocabulary=vocabulary)

        assert score[1] == 1.0

    def test_multiple_appids_independent_scores(self):
        """Multiple appids have independent scores."""
        tags_data = {
            "appid": [1, 1, 2, 2, 2],
            "tag": ["Pixel Graphics", "2D", "Open World", "Multiplayer", "Physics"],
            "votes": [100, 100, 100, 100, 100],
            "rank": [1, 2, 1, 2, 3],
        }
        tags = pd.DataFrame(tags_data)
        vocabulary = ["pixel graphics", "2d"]

        score = compute_tag_score(tags, vocabulary=vocabulary)

        assert score[1] == 1.0  # Both tags match
        assert score[2] == 0.0  # No tags match

    def test_tagless_appid_absent_from_result(self):
        """An appid with zero tags is absent from the result."""
        tags_data = {
            "appid": [1, 1],
            "tag": ["Pixel Graphics", "2D"],
            "votes": [100, 100],
            "rank": [1, 2],
        }
        tags = pd.DataFrame(tags_data)
        vocabulary = ["pixel graphics", "2d"]

        score = compute_tag_score(tags, vocabulary=vocabulary)

        # appid 2 (tagless) should not be in result
        assert 2 not in score.index
        assert 1 in score.index

    def test_empty_tags_dataframe(self):
        """Empty tags DataFrame returns empty Series."""
        tags = pd.DataFrame(
            {"appid": [], "tag": [], "votes": [], "rank": []}
        )
        vocabulary = ["pixel graphics"]

        score = compute_tag_score(tags, vocabulary=vocabulary)

        assert len(score) == 0

    def test_empty_vocabulary(self):
        """Empty vocabulary results in all scores 0.0."""
        tags_data = {
            "appid": [1, 1],
            "tag": ["Pixel Graphics", "2D"],
            "votes": [100, 100],
            "rank": [1, 2],
        }
        tags = pd.DataFrame(tags_data)
        vocabulary = []

        score = compute_tag_score(tags, vocabulary=vocabulary)

        assert score[1] == 0.0

    def test_single_tag_match(self):
        """Single tag in vocabulary matches correctly."""
        tags_data = {
            "appid": [1],
            "tag": ["Pixel Graphics"],
            "votes": [100],
            "rank": [1],
        }
        tags = pd.DataFrame(tags_data)
        vocabulary = ["pixel graphics"]

        score = compute_tag_score(tags, vocabulary=vocabulary)

        assert score[1] == 1.0

    def test_many_tags_only_some_match(self):
        """App with many tags where only some match."""
        tags_data = {
            "appid": [1] * 10,
            "tag": [
                "Pixel Graphics",
                "2D",
                "Casual",
                "Open World",
                "Multiplayer",
                "Physics",
                "Procedural Generation",
                "Action",
                "Adventure",
                "RPG",
            ],
            "votes": [100] * 10,
            "rank": list(range(1, 11)),
        }
        tags = pd.DataFrame(tags_data)
        vocabulary = ["pixel graphics", "2d", "casual"]

        score = compute_tag_score(tags, vocabulary=vocabulary)

        # 3 out of 10 tags match
        assert score[1] == 0.3


# ============================================================================
# Tests for compute_developer_catalog_size
# ============================================================================


class TestComputeDeveloperCatalogSize:
    """Test developer catalog size counting."""

    def test_counts_other_titles_excluding_self(self):
        """A developer with 4 total titles produces count=3 for each row."""
        catalog = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5],
            "developer": ["DevA", "DevA", "DevA", "DevA", "DevB"],
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4],
            "developer": ["DevA", "DevA", "DevA", "DevA"],
        }).set_index("appid")

        result = compute_developer_catalog_size(frame, catalog)

        # Each DevA row should count 3 other DevA titles
        assert result[1] == 3
        assert result[2] == 3
        assert result[3] == 3
        assert result[4] == 3

    def test_single_title_developer_returns_zero(self):
        """A developer with only one title in catalog returns 0."""
        catalog = pd.DataFrame({
            "appid": [1, 2],
            "developer": ["DevA", "DevB"],
        })
        frame = pd.DataFrame({
            "appid": [1, 2],
            "developer": ["DevA", "DevB"],
        }).set_index("appid")

        result = compute_developer_catalog_size(frame, catalog)

        assert result[1] == 0
        assert result[2] == 0

    def test_nan_developer_yields_zero(self):
        """A row with developer=NaN gets 0."""
        catalog = pd.DataFrame({
            "appid": [1, 2, 3],
            "developer": ["DevA", np.nan, np.nan],
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3],
            "developer": ["DevA", np.nan, np.nan],
        }).set_index("appid")

        result = compute_developer_catalog_size(frame, catalog)

        assert result[1] == 0
        assert result[2] == 0
        assert result[3] == 0

    def test_nan_developers_do_not_match_each_other(self):
        """Two apps with NaN developer don't count as sharing a developer."""
        catalog = pd.DataFrame({
            "appid": [1, 2, 3],
            "developer": [np.nan, np.nan, "DevA"],
        })
        frame = pd.DataFrame({
            "appid": [1, 2],
            "developer": [np.nan, np.nan],
        }).set_index("appid")

        result = compute_developer_catalog_size(frame, catalog)

        # Neither should match the other or themselves
        assert result[1] == 0
        assert result[2] == 0

    def test_case_sensitive_match(self):
        """'Team Cherry' and 'team cherry' are not matched as the same developer."""
        catalog = pd.DataFrame({
            "appid": [1, 2, 3],
            "developer": ["Team Cherry", "team cherry", "DevA"],
        })
        frame = pd.DataFrame({
            "appid": [1, 2],
            "developer": ["Team Cherry", "team cherry"],
        }).set_index("appid")

        result = compute_developer_catalog_size(frame, catalog)

        # Each should only find themselves in catalog, count = 0
        assert result[1] == 0
        assert result[2] == 0

    def test_multiple_developers_independent_counts(self):
        """Multiple developers have independent counts."""
        catalog = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5, 6],
            "developer": ["DevA", "DevA", "DevA", "DevB", "DevB", "DevC"],
        })
        frame = pd.DataFrame({
            "appid": [1, 4, 6],
            "developer": ["DevA", "DevB", "DevC"],
        }).set_index("appid")

        result = compute_developer_catalog_size(frame, catalog)

        assert result[1] == 2  # DevA has 3 total, minus self = 2
        assert result[4] == 1  # DevB has 2 total, minus self = 1
        assert result[6] == 0  # DevC has 1 total, minus self = 0

    def test_frame_subset_of_catalog(self):
        """frame is a subset of catalog (candidates subset of full catalog)."""
        catalog = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5],
            "developer": ["DevA", "DevA", "DevA", "DevB", "DevB"],
        })
        # Only include appids 1, 3, 4 in frame (subset of catalog)
        frame = pd.DataFrame({
            "appid": [1, 3, 4],
            "developer": ["DevA", "DevA", "DevB"],
        }).set_index("appid")

        result = compute_developer_catalog_size(frame, catalog)

        # DevA has 3 total in catalog, minus self = 2
        # DevB has 2 total in catalog, minus self = 1
        assert result[1] == 2
        assert result[3] == 2
        assert result[4] == 1

    def test_empty_frame_returns_empty_series(self):
        """Empty frame returns empty Series."""
        catalog = pd.DataFrame({
            "appid": [1, 2],
            "developer": ["DevA", "DevB"],
        })
        frame = pd.DataFrame({
            "appid": [],
            "developer": [],
        }).set_index("appid")

        result = compute_developer_catalog_size(frame, catalog)

        assert len(result) == 0

    def test_preserves_frame_index(self):
        """Result is indexed exactly like the input frame."""
        catalog = pd.DataFrame({
            "appid": [1, 2, 3],
            "developer": ["DevA", "DevA", "DevB"],
        })
        frame = pd.DataFrame({
            "appid": [1, 2],
            "developer": ["DevA", "DevA"],
        }).set_index("appid")

        result = compute_developer_catalog_size(frame, catalog)

        assert list(result.index) == list(frame.index)

    def test_large_developer_catalog(self):
        """A prolific developer with many titles counted correctly."""
        # Create catalog with one developer having 100 titles
        appids = list(range(1, 101))
        devs = ["DevA"] * 100 + ["DevB"]
        appids.append(101)

        catalog = pd.DataFrame({
            "appid": appids,
            "developer": devs,
        })

        frame = pd.DataFrame({
            "appid": [1, 50, 100],
            "developer": ["DevA", "DevA", "DevA"],
        }).set_index("appid")

        result = compute_developer_catalog_size(frame, catalog)

        # Each DevA row should count 99 other DevA titles
        assert result[1] == 99
        assert result[50] == 99
        assert result[100] == 99

    def test_whitespace_matters_in_developer_string(self):
        """Whitespace differences prevent matching."""
        catalog = pd.DataFrame({
            "appid": [1, 2, 3],
            "developer": ["Dev A", "DevA", "Dev  A"],
        })
        frame = pd.DataFrame({
            "appid": [1, 2],
            "developer": ["Dev A", "DevA"],
        }).set_index("appid")

        result = compute_developer_catalog_size(frame, catalog)

        # All should be 0 (exact match only, no normalization)
        assert result[1] == 0
        assert result[2] == 0
