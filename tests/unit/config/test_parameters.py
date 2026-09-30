"""Unit tests for parameter loading, validation, and versioning."""

import pytest
from pathlib import Path
from datetime import date
from typing import Any

from steam_analyst.config.parameters import (
    ParameterError,
    validate_parameters,
    parameters_version,
    load_parameters,
)
from steam_analyst.config.settings import (
    AcquisitionConfig,
    CoarseFilterCriteria,
    EnrichmentParams,
    AnalysisParams,
)


def create_minimal_valid_raw() -> dict[str, Any]:
    """Create a minimal valid raw parameter dict for testing."""
    return {
        "acquisition": {
            "steamspy_page_delay_seconds": 0.5,
            "steam_requests_per_minute": 60.0,
            "max_retries": 3,
            "backoff_base_seconds": 1.0,
            "backoff_max_seconds": 60.0,
            "request_budget": 10000,
            "coarse_filter": {
                "min_review_count": 25,
                "earliest_release_date": "2020-01-01",
                "include_free_to_play": True,
                "publisher_blocklist": ["Electronic Arts"],
            },
        },
        "enrichment": {
            "boxleiter_multipliers": {
                "niche": [20, 27, 35],
                "mainstream": [30, 37, 45],
                "broad_audience": [40, 50, 65],
            },
            "genre_bucket_map": {"default": "mainstream"},
            "revenue": {
                "storefront_cut": 0.30,
                "discount_factor": 0.0,
                "refund_regional_factor": 0.0,
            },
            "complexity_weights": {
                "size_bytes": 0.20,
                "ram_bytes": 0.10,
                "early_access_days": 0.05,
                "dev_title_count": 0.15,
                "simplicity_tag_score": 0.10,
                "complexity_tag_score": 0.10,
                "achievement_count": 0.10,
                "dlc_count": 0.10,
                "platform_count": 0.05,
                "language_count": 0.05,
            },
            "complexity_tags": {
                "simplicity_tags": ["Pixel Graphics"],
                "complexity_tags": ["Open World"],
            },
            "effort": {"epsilon": 0.05},
            "tag_extraction": {"max_per_game": 20, "min_votes": 0},
        },
        "analysis": {
            "simplicity_percentile": 0.40,
            "clustering_linkage": "average",
            "trailing_window_months": 24,
            "min_cluster_size": 5,
            "min_tag_votes": 0,
            "max_tags_per_game": 20,
            "opportunity_weights": {
                "demand": 0.40,
                "competition": 0.30,
                "simplicity": 0.30,
            },
        },
    }


class TestParameterError:
    """Tests for ParameterError exception class."""

    def test_str_with_no_context(self) -> None:
        """Bare message renders unchanged."""
        err = ParameterError("bad value")
        assert str(err) == "bad value"

    def test_str_with_path_only(self) -> None:
        """Message with path renders with path context."""
        err = ParameterError(
            "out of range", path=Path("parameters.toml")
        )
        assert "out of range" in str(err)
        assert "parameters.toml" in str(err)

    def test_str_with_key_only(self) -> None:
        """Message with key renders with key context."""
        err = ParameterError(
            "out of range", key="enrichment.storefront_cut"
        )
        assert "out of range" in str(err)
        assert "enrichment.storefront_cut" in str(err)

    def test_str_with_path_and_key(self) -> None:
        """Full context renders in a single readable string."""
        err = ParameterError(
            "out of range",
            path=Path("parameters.toml"),
            key="enrichment.storefront_cut",
        )
        result = str(err)
        assert "out of range" in result
        assert "parameters.toml" in result
        assert "enrichment.storefront_cut" in result

    def test_attributes_stored(self) -> None:
        """Error attributes are stored verbatim."""
        path = Path("config/parameters.toml")
        key = "analysis.simplicity_percentile"
        msg = "invalid value"
        err = ParameterError(msg, path=path, key=key)
        assert err.message == msg
        assert err.path == path
        assert err.key == key


class TestValidateParameters:
    """Tests for validate_parameters function."""

    def test_missing_acquisition_section(self) -> None:
        """Missing [acquisition] section raises ParameterError."""
        raw = {"enrichment": {}, "analysis": {}}
        with pytest.raises(ParameterError) as exc_info:
            validate_parameters(raw)
        assert "missing section: acquisition" in str(exc_info.value)

    def test_missing_enrichment_section(self) -> None:
        """Missing [enrichment] section raises ParameterError."""
        raw = {"acquisition": {}, "analysis": {}}
        with pytest.raises(ParameterError) as exc_info:
            validate_parameters(raw)
        assert "missing section: enrichment" in str(exc_info.value)

    def test_missing_analysis_section(self) -> None:
        """Missing [analysis] section raises ParameterError."""
        raw = {"acquisition": {}, "enrichment": {}}
        with pytest.raises(ParameterError) as exc_info:
            validate_parameters(raw)
        assert "missing section: analysis" in str(exc_info.value)

    def test_missing_coarse_filter_subsection(self) -> None:
        """Missing [acquisition.coarse_filter] subsection raises ParameterError."""
        raw = {
            "acquisition": {
                "steamspy_page_delay_seconds": 0.5,
                "steam_requests_per_minute": 60.0,
                "max_retries": 3,
                "backoff_base_seconds": 1.0,
                "backoff_max_seconds": 60.0,
                "request_budget": 10000,
                # missing coarse_filter
            },
            "enrichment": {},
            "analysis": {},
        }
        with pytest.raises(ParameterError) as exc_info:
            validate_parameters(raw)
        assert "missing key: acquisition.coarse_filter" in str(exc_info.value)

    def test_missing_coarse_filter_key(self) -> None:
        """Missing required coarse_filter key raises ParameterError."""
        raw = {
            "acquisition": {
                "steamspy_page_delay_seconds": 0.5,
                "steam_requests_per_minute": 60.0,
                "max_retries": 3,
                "backoff_base_seconds": 1.0,
                "backoff_max_seconds": 60.0,
                "request_budget": 10000,
                "coarse_filter": {
                    "min_review_count": 25,
                    "earliest_release_date": "2020-01-01",
                    "include_free_to_play": True,
                    # missing publisher_blocklist
                },
            },
            "enrichment": {},
            "analysis": {},
        }
        with pytest.raises(ParameterError) as exc_info:
            validate_parameters(raw)
        assert "publisher_blocklist" in str(exc_info.value)

    def test_missing_enrichment_subsection(self) -> None:
        """Missing [enrichment.boxleiter_multipliers] subsection raises ParameterError."""
        raw = create_minimal_valid_raw()
        # Remove boxleiter_multipliers to trigger error
        del raw["enrichment"]["boxleiter_multipliers"]

        with pytest.raises(ParameterError) as exc_info:
            validate_parameters(raw)
        assert "missing section: enrichment.boxleiter_multipliers" in str(
            exc_info.value
        )

    def test_missing_boxleiter_bucket(self) -> None:
        """Missing Boxleiter bucket raises ParameterError."""
        raw = create_minimal_valid_raw()
        # Remove mainstream bucket to trigger error
        del raw["enrichment"]["boxleiter_multipliers"]["mainstream"]

        with pytest.raises(ParameterError) as exc_info:
            validate_parameters(raw)
        assert "missing bucket" in str(exc_info.value)

    def test_unordered_multiplier_triple(self) -> None:
        """Unordered multiplier triple raises ParameterError."""
        raw = create_minimal_valid_raw()
        # Make broad_audience multipliers descending instead of ascending
        raw["enrichment"]["boxleiter_multipliers"]["broad_audience"] = [65, 50, 40]

        with pytest.raises(ParameterError) as exc_info:
            validate_parameters(raw)
        assert "unordered" in str(exc_info.value).lower()

    def test_storefront_cut_out_of_range(self) -> None:
        """Out-of-range storefront_cut raises ParameterError."""
        raw = create_minimal_valid_raw()
        raw["enrichment"]["revenue"]["storefront_cut"] = 1.5  # out of range

        with pytest.raises(ParameterError) as exc_info:
            validate_parameters(raw)
        assert "out of range" in str(exc_info.value).lower()

    def test_weights_not_summing_to_one(self) -> None:
        """Weights not summing to 1.0 raise ParameterError."""
        raw = create_minimal_valid_raw()
        # Change language_count weight so they don't sum to 1.0
        raw["enrichment"]["complexity_weights"]["language_count"] = 0.00

        with pytest.raises(ParameterError) as exc_info:
            validate_parameters(raw)
        assert "sum" in str(exc_info.value).lower()

    def test_invalid_clustering_linkage(self) -> None:
        """Invalid clustering_linkage value raises ParameterError."""
        raw = create_minimal_valid_raw()
        raw["analysis"]["clustering_linkage"] = "ward"  # invalid linkage

        with pytest.raises(ParameterError) as exc_info:
            validate_parameters(raw)
        assert "clustering_linkage" in str(exc_info.value)

    def test_opportunity_weights_not_summing_to_one(self) -> None:
        """Opportunity weights not summing to 1.0 raise ParameterError."""
        raw = create_minimal_valid_raw()
        raw["analysis"]["opportunity_weights"]["simplicity"] = 0.20  # sum becomes 0.9

        with pytest.raises(ParameterError) as exc_info:
            validate_parameters(raw)
        assert "opportunity_weights" in str(exc_info.value)


class TestParametersVersion:
    """Tests for parameters_version function."""

    def test_stable_across_repeated_reads(
        self, tmp_path: Path
    ) -> None:
        """Two calls on the same file return the same string."""
        fixture_path = Path("tests/fixtures/parameters_valid.toml").resolve()

        hash1 = parameters_version(fixture_path)
        hash2 = parameters_version(fixture_path)

        assert hash1 == hash2
        assert len(hash1) == 12
        assert all(c in "0123456789abcdef" for c in hash1)

    def test_changes_when_a_value_changes(
        self, tmp_path: Path
    ) -> None:
        """Changing a value in the file changes the hash."""
        fixture_path = Path("tests/fixtures/parameters_valid.toml").resolve()

        # Get hash of original
        original_hash = parameters_version(fixture_path)

        # Read the content
        with open(fixture_path, "r") as f:
            content = f.read()

        # Modify a value and write to temp file
        modified_content = content.replace(
            'storefront_cut = 0.30', 'storefront_cut = 0.25'
        )
        modified_path = tmp_path / "parameters_modified.toml"
        with open(modified_path, "w") as f:
            f.write(modified_content)

        # Get hash of modified
        modified_hash = parameters_version(modified_path)

        assert original_hash != modified_hash

    def test_missing_file_raises(self) -> None:
        """A nonexistent path raises ParameterError."""
        nonexistent = Path("tests/fixtures/does_not_exist.toml").resolve()
        with pytest.raises(ParameterError) as exc_info:
            parameters_version(nonexistent)
        assert "not found" in str(exc_info.value).lower()

    def test_changes_on_whitespace_change(self, tmp_path: Path) -> None:
        """Hash changes on whitespace-only edit (conservative choice)."""
        fixture_path = Path("tests/fixtures/parameters_valid.toml").resolve()

        original_hash = parameters_version(fixture_path)

        # Read and add extra whitespace
        with open(fixture_path, "r") as f:
            content = f.read()

        modified_content = content + "\n\n  \n"
        modified_path = tmp_path / "parameters_whitespace.toml"
        with open(modified_path, "w") as f:
            f.write(modified_content)

        modified_hash = parameters_version(modified_path)
        assert original_hash != modified_hash


class TestLoadParameters:
    """Tests for load_parameters function."""

    def test_load_parameters_accepts_complete_fixture(self) -> None:
        """Valid fixture loads into three populated, mutually consistent dataclasses."""
        fixture_path = Path("tests/fixtures/parameters_valid.toml").resolve()

        acq, enr, ana = load_parameters(fixture_path)

        # Verify types
        assert isinstance(acq, AcquisitionConfig)
        assert isinstance(enr, EnrichmentParams)
        assert isinstance(ana, AnalysisParams)

        # Verify some key values
        assert acq.coarse_filter.min_review_count == 25
        assert acq.request_budget == 10000
        assert enr.storefront_cut == 0.30
        assert enr.effort_epsilon == 0.05
        assert ana.simplicity_percentile == 0.40
        assert ana.clustering_linkage == "average"

    def test_load_parameters_missing_file(self) -> None:
        """A nonexistent path raises ParameterError naming that path."""
        nonexistent = Path("tests/fixtures/does_not_exist.toml").resolve()
        with pytest.raises(ParameterError) as exc_info:
            load_parameters(nonexistent)
        assert "not found" in str(exc_info.value).lower()

    def test_load_parameters_invalid_syntax(self) -> None:
        """Invalid TOML syntax raises ParameterError."""
        invalid_path = Path("tests/fixtures/parameters_invalid_syntax.toml").resolve()
        with pytest.raises(ParameterError) as exc_info:
            load_parameters(invalid_path)
        assert "toml" in str(exc_info.value).lower() or "syntax" in str(
            exc_info.value
        ).lower()

    def test_load_parameters_missing_section(self) -> None:
        """Missing [enrichment] section raises ParameterError."""
        invalid_path = Path(
            "tests/fixtures/parameters_invalid_missing_section.toml"
        ).resolve()
        with pytest.raises(ParameterError) as exc_info:
            load_parameters(invalid_path)
        assert "missing section" in str(exc_info.value).lower()

    def test_load_parameters_missing_key(self) -> None:
        """Missing required key raises ParameterError."""
        invalid_path = Path(
            "tests/fixtures/parameters_invalid_missing_key.toml"
        ).resolve()
        with pytest.raises(ParameterError) as exc_info:
            load_parameters(invalid_path)
        assert "missing key" in str(exc_info.value).lower()

    def test_load_parameters_out_of_range(self) -> None:
        """Out-of-range value raises ParameterError."""
        invalid_path = Path(
            "tests/fixtures/parameters_invalid_out_of_range.toml"
        ).resolve()
        with pytest.raises(ParameterError) as exc_info:
            load_parameters(invalid_path)
        assert "out of range" in str(exc_info.value).lower()

    def test_load_parameters_weights_not_summing(self) -> None:
        """Weights not summing to 1.0 raise ParameterError."""
        invalid_path = Path(
            "tests/fixtures/parameters_invalid_weights.toml"
        ).resolve()
        with pytest.raises(ParameterError) as exc_info:
            load_parameters(invalid_path)
        assert "sum" in str(exc_info.value).lower()

    def test_load_parameters_unordered_multiplier(self) -> None:
        """Unordered multiplier triple raises ParameterError."""
        invalid_path = Path(
            "tests/fixtures/parameters_invalid_unordered_multiplier.toml"
        ).resolve()
        with pytest.raises(ParameterError) as exc_info:
            load_parameters(invalid_path)
        assert "unordered" in str(exc_info.value).lower()

    def test_coarse_filter_optional_keys(self) -> None:
        """Optional coarse_filter keys (max_review_count, latest_release_date) can be absent."""
        fixture_path = Path("tests/fixtures/parameters_valid.toml").resolve()
        acq, _, _ = load_parameters(fixture_path)

        # max_review_count should be None (not present in fixture)
        assert acq.coarse_filter.max_review_count is None
        # latest_release_date should be None (not present in fixture)
        assert acq.coarse_filter.latest_release_date is None

    def test_tag_distance_threshold_optional(self) -> None:
        """Optional tag_distance_threshold can be absent (None until run 1)."""
        fixture_path = Path("tests/fixtures/parameters_valid.toml").resolve()
        _, _, ana = load_parameters(fixture_path)

        # tag_distance_threshold should be None (not present in fixture)
        assert ana.tag_distance_threshold is None

    def test_boxleiter_multipliers_converted_to_tuples(self) -> None:
        """Boxleiter multipliers from TOML arrays are converted to tuples."""
        fixture_path = Path("tests/fixtures/parameters_valid.toml").resolve()
        _, enr, _ = load_parameters(fixture_path)

        # Verify they are tuples
        assert isinstance(enr.boxleiter_multipliers["niche"], tuple)
        assert isinstance(enr.boxleiter_multipliers["mainstream"], tuple)
        assert isinstance(enr.boxleiter_multipliers["broad_audience"], tuple)

        # Verify values
        assert enr.boxleiter_multipliers["niche"] == (20, 27, 35)
        assert enr.boxleiter_multipliers["mainstream"] == (30, 37, 45)
        assert enr.boxleiter_multipliers["broad_audience"] == (40, 50, 65)

    def test_dates_parsed_correctly(self) -> None:
        """Date strings in TOML are parsed to date objects."""
        fixture_path = Path("tests/fixtures/parameters_valid.toml").resolve()
        acq, _, _ = load_parameters(fixture_path)

        # earliest_release_date should be a date object
        assert isinstance(acq.coarse_filter.earliest_release_date, date)
        assert acq.coarse_filter.earliest_release_date == date(2020, 1, 1)

    def test_complexity_bounds_defaults_to_empty_dict(self) -> None:
        """complexity_bounds defaults to empty dict when absent."""
        fixture_path = Path("tests/fixtures/parameters_valid.toml").resolve()
        _, enr, _ = load_parameters(fixture_path)

        assert enr.complexity_bounds == {}

    def test_all_dataclass_fields_populated(self) -> None:
        """All dataclass fields are populated from the fixture."""
        fixture_path = Path("tests/fixtures/parameters_valid.toml").resolve()
        acq, enr, ana = load_parameters(fixture_path)

        # AcquisitionConfig fields
        assert acq.steamspy_page_delay_seconds == 0.5
        assert acq.steam_requests_per_minute == 60.0
        assert acq.max_retries == 3
        assert acq.backoff_base_seconds == 1.0
        assert acq.backoff_max_seconds == 60.0
        assert acq.request_budget == 10000
        assert acq.coarse_filter is not None

        # CoarseFilterCriteria fields
        assert acq.coarse_filter.min_review_count == 25
        assert acq.coarse_filter.include_free_to_play is True
        assert len(acq.coarse_filter.publisher_blocklist) > 0

        # EnrichmentParams fields
        assert len(enr.boxleiter_multipliers) == 3
        assert len(enr.genre_bucket_map) > 0
        assert enr.storefront_cut == 0.30
        assert enr.discount_factor == 0.0
        assert enr.refund_regional_factor == 0.0
        assert len(enr.complexity_weights) == 10
        assert len(enr.simplicity_tags) > 0
        assert len(enr.complexity_tags) > 0
        assert enr.effort_epsilon == 0.05

        # AnalysisParams fields
        assert ana.simplicity_percentile == 0.40
        assert ana.trailing_window_months == 24
        assert ana.min_cluster_size == 5
        assert len(ana.opportunity_weights) == 3
        assert ana.min_tag_votes == 0
        assert ana.max_tags_per_game == 20
        assert ana.clustering_linkage == "average"
