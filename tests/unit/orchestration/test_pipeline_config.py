"""Unit tests for PipelineConfig dataclass."""

import json
import pytest

from steam_analyst.orchestration.pipeline_config import PipelineConfig
from steam_analyst.orchestration.stages import PipelineStage


class TestPipelineConfigDefaults:
    """Tests for default construction and values."""

    def test_default_construction(self):
        """Verify default field values."""
        config = PipelineConfig()
        assert config.start_stage == PipelineStage.ACQUISITION
        assert config.max_catalog_pages is None
        assert config.request_budget_override is None
        assert config.notes is None

    def test_frozen_dataclass(self):
        """Verify the dataclass is frozen."""
        config = PipelineConfig()
        with pytest.raises(AttributeError):
            config.start_stage = PipelineStage.ENRICHMENT


class TestPipelineConfigToDict:
    """Tests for to_dict() serialization."""

    def test_to_dict_defaults(self):
        """to_dict() with default values."""
        config = PipelineConfig()
        result = config.to_dict()

        assert result == {
            "start_stage": "acquisition",
            "max_catalog_pages": None,
            "request_budget_override": None,
            "notes": None,
        }

    def test_to_dict_all_fields(self):
        """to_dict() with all fields populated."""
        config = PipelineConfig(
            start_stage=PipelineStage.ENRICHMENT,
            max_catalog_pages=5,
            request_budget_override=1000,
            notes="smoke test",
        )
        result = config.to_dict()

        assert result == {
            "start_stage": "enrichment",
            "max_catalog_pages": 5,
            "request_budget_override": 1000,
            "notes": "smoke test",
        }

    def test_to_dict_start_stage_as_string(self):
        """to_dict() emits start_stage as plain string, not enum repr."""
        config = PipelineConfig(start_stage=PipelineStage.ANALYSIS)
        result = config.to_dict()

        # Should be the string value, not a repr like "PipelineStage.ANALYSIS"
        assert result["start_stage"] == "analysis"
        assert isinstance(result["start_stage"], str)


class TestPipelineConfigFromDict:
    """Tests for from_dict() deserialization."""

    def test_from_dict_empty_dict(self):
        """from_dict({}) returns default PipelineConfig."""
        config = PipelineConfig.from_dict({})

        assert config.start_stage == PipelineStage.ACQUISITION
        assert config.max_catalog_pages is None
        assert config.request_budget_override is None
        assert config.notes is None

    def test_from_dict_partial_fields(self):
        """from_dict() with some fields missing uses defaults for the rest."""
        data = {"start_stage": "enrichment", "max_catalog_pages": 5}
        config = PipelineConfig.from_dict(data)

        assert config.start_stage == PipelineStage.ENRICHMENT
        assert config.max_catalog_pages == 5
        assert config.request_budget_override is None
        assert config.notes is None

    def test_from_dict_ignores_unknown_keys(self):
        """from_dict() with unknown extra keys ignores them (forward compatibility)."""
        data = {
            "start_stage": "acquisition",
            "future_field": 123,
            "another_unknown": "value",
        }
        config = PipelineConfig.from_dict(data)

        assert config.start_stage == PipelineStage.ACQUISITION
        # Unknown keys are silently ignored; no attribute created
        assert not hasattr(config, "future_field")
        assert not hasattr(config, "another_unknown")

    def test_from_dict_start_stage_string_conversion(self):
        """from_dict() converts start_stage string to PipelineStage enum."""
        for stage_name, stage_enum in [
            ("acquisition", PipelineStage.ACQUISITION),
            ("enrichment", PipelineStage.ENRICHMENT),
            ("analysis", PipelineStage.ANALYSIS),
        ]:
            data = {"start_stage": stage_name}
            config = PipelineConfig.from_dict(data)
            assert config.start_stage == stage_enum
            assert isinstance(config.start_stage, PipelineStage)

    def test_from_dict_preserves_all_values(self):
        """from_dict() preserves non-None fields."""
        data = {
            "start_stage": "analysis",
            "max_catalog_pages": 10,
            "request_budget_override": 2000,
            "notes": "test run",
        }
        config = PipelineConfig.from_dict(data)

        assert config.start_stage == PipelineStage.ANALYSIS
        assert config.max_catalog_pages == 10
        assert config.request_budget_override == 2000
        assert config.notes == "test run"


class TestPipelineConfigRoundTrip:
    """Tests for to_dict/from_dict round-tripping."""

    def test_roundtrip_default_values(self):
        """A default-constructed PipelineConfig survives to_dict/from_dict unchanged."""
        original = PipelineConfig()
        roundtripped = PipelineConfig.from_dict(original.to_dict())
        assert roundtripped == original

    def test_roundtrip_all_fields_set(self):
        """A fully populated PipelineConfig survives the round trip."""
        original = PipelineConfig(
            start_stage=PipelineStage.ENRICHMENT,
            max_catalog_pages=5,
            request_budget_override=1000,
            notes="smoke test",
        )
        roundtripped = PipelineConfig.from_dict(original.to_dict())
        assert roundtripped == original

    def test_roundtrip_various_stages(self):
        """Round-trip works for each stage value."""
        for stage in PipelineStage:
            original = PipelineConfig(start_stage=stage)
            roundtripped = PipelineConfig.from_dict(original.to_dict())
            assert roundtripped == original
            assert roundtripped.start_stage == stage

    def test_roundtrip_none_fields(self):
        """Round-trip with mixed None and non-None fields."""
        original = PipelineConfig(
            start_stage=PipelineStage.ANALYSIS, max_catalog_pages=7, notes="partial"
        )
        roundtripped = PipelineConfig.from_dict(original.to_dict())
        assert roundtripped == original
        assert roundtripped.max_catalog_pages == 7
        assert roundtripped.request_budget_override is None


class TestPipelineConfigJsonRoundTrip:
    """Tests for round-tripping through actual JSON serialization."""

    def test_start_stage_json_string_roundtrip(self):
        """start_stage survives real json.dumps/json.loads round trip."""
        original = PipelineConfig(start_stage=PipelineStage.ANALYSIS)

        # Serialize to JSON string
        dict_form = original.to_dict()
        json_string = json.dumps(dict_form)

        # Deserialize from JSON string
        loaded_dict = json.loads(json_string)
        roundtripped = PipelineConfig.from_dict(loaded_dict)

        assert roundtripped == original
        assert roundtripped.start_stage == PipelineStage.ANALYSIS

    def test_full_config_json_roundtrip(self):
        """Full PipelineConfig round-trips through JSON."""
        original = PipelineConfig(
            start_stage=PipelineStage.ENRICHMENT,
            max_catalog_pages=42,
            request_budget_override=5000,
            notes="json test data",
        )

        # Serialize to JSON string and back
        json_string = json.dumps(original.to_dict())
        loaded_dict = json.loads(json_string)
        roundtripped = PipelineConfig.from_dict(loaded_dict)

        assert roundtripped == original
        assert json.dumps(roundtripped.to_dict()) == json_string

    def test_json_roundtrip_preserves_types(self):
        """JSON round-trip preserves field types."""
        original = PipelineConfig(
            max_catalog_pages=100, request_budget_override=2000
        )

        json_string = json.dumps(original.to_dict())
        roundtripped = PipelineConfig.from_dict(json.loads(json_string))

        assert isinstance(roundtripped.max_catalog_pages, int)
        assert isinstance(roundtripped.request_budget_override, int)
        assert roundtripped.max_catalog_pages == 100
        assert roundtripped.request_budget_override == 2000


class TestPipelineConfigEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_max_catalog_pages_zero(self):
        """max_catalog_pages=0 is accepted (validation happens elsewhere)."""
        config = PipelineConfig(max_catalog_pages=0)
        assert config.max_catalog_pages == 0

        # Round-trip preserves it
        roundtripped = PipelineConfig.from_dict(config.to_dict())
        assert roundtripped.max_catalog_pages == 0

    def test_large_numeric_values(self):
        """Large numeric values are preserved."""
        config = PipelineConfig(
            max_catalog_pages=999999, request_budget_override=10000000
        )
        roundtripped = PipelineConfig.from_dict(config.to_dict())
        assert roundtripped.max_catalog_pages == 999999
        assert roundtripped.request_budget_override == 10000000

    def test_notes_with_special_characters(self):
        """notes field handles special characters including newlines."""
        special_notes = 'test with "quotes" and\nnewlines\tand\ttabs'
        config = PipelineConfig(notes=special_notes)

        # Through JSON to ensure escaping works
        json_string = json.dumps(config.to_dict())
        roundtripped = PipelineConfig.from_dict(json.loads(json_string))
        assert roundtripped.notes == special_notes

    def test_empty_string_notes(self):
        """Empty string for notes is preserved (distinct from None)."""
        config = PipelineConfig(notes="")
        roundtripped = PipelineConfig.from_dict(config.to_dict())
        assert roundtripped.notes == ""
        assert roundtripped.notes is not None

    def test_from_dict_with_none_values_in_dict(self):
        """from_dict() handles explicit None values in the input dict."""
        data = {
            "start_stage": "acquisition",
            "max_catalog_pages": None,
            "request_budget_override": None,
            "notes": None,
        }
        config = PipelineConfig.from_dict(data)
        assert config.max_catalog_pages is None
        assert config.request_budget_override is None
        assert config.notes is None

    def test_from_dict_mixed_missing_and_explicit_none(self):
        """from_dict() treats missing keys and None values equivalently."""
        config_from_missing = PipelineConfig.from_dict({"start_stage": "acquisition"})
        config_from_explicit_none = PipelineConfig.from_dict(
            {
                "start_stage": "acquisition",
                "max_catalog_pages": None,
                "request_budget_override": None,
                "notes": None,
            }
        )
        assert config_from_missing == config_from_explicit_none

    def test_to_dict_always_includes_all_keys(self):
        """to_dict() includes all fields even when None."""
        config = PipelineConfig()
        result = config.to_dict()
        assert "start_stage" in result
        assert "max_catalog_pages" in result
        assert "request_budget_override" in result
        assert "notes" in result

    def test_dict_keys_exact_match(self):
        """to_dict() has exactly the expected keys (no extra, none missing)."""
        config = PipelineConfig()
        result = config.to_dict()
        expected_keys = {
            "start_stage",
            "max_catalog_pages",
            "request_budget_override",
            "notes",
        }
        assert set(result.keys()) == expected_keys


class TestPipelineConfigEquality:
    """Tests for equality and identity."""

    def test_equal_configs_are_equal(self):
        """Two PipelineConfigs with same values are equal."""
        config1 = PipelineConfig(
            start_stage=PipelineStage.ENRICHMENT,
            max_catalog_pages=5,
            request_budget_override=1000,
            notes="test",
        )
        config2 = PipelineConfig(
            start_stage=PipelineStage.ENRICHMENT,
            max_catalog_pages=5,
            request_budget_override=1000,
            notes="test",
        )
        assert config1 == config2

    def test_different_configs_not_equal(self):
        """Configs with different values are not equal."""
        config1 = PipelineConfig(start_stage=PipelineStage.ACQUISITION)
        config2 = PipelineConfig(start_stage=PipelineStage.ENRICHMENT)
        assert config1 != config2

    def test_hash_consistent(self):
        """Frozen dataclass instances are hashable."""
        config = PipelineConfig()
        # Should not raise
        hash(config)

        # Can be used in a set
        config_set = {config}
        assert config in config_set
