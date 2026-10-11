"""Unit tests for the per-run complexity weights override helpers."""

import math

import pytest

from steam_analyst.config.parameters import (
    ParameterError,
    effective_parameters_version,
    resolve_complexity_weights,
    run_parameters_version,
)

DEFAULTS = {
    "size_bytes": 0.20,
    "ram_bytes": 0.10,
    "early_access_days": 0.05,
    "dev_title_count": 0.10,
    "simplicity_tag_score": 0.15,
    "complexity_tag_score": 0.15,
    "achievement_count": 0.05,
    "dlc_count": 0.05,
    "platform_count": 0.05,
    "language_count": 0.10,
}


class TestResolveComplexityWeights:
    def test_none_returns_defaults(self):
        assert resolve_complexity_weights(DEFAULTS, None) == DEFAULTS

    def test_empty_returns_defaults(self):
        assert resolve_complexity_weights(DEFAULTS, {}) == DEFAULTS

    def test_values_equal_to_defaults_return_defaults(self):
        assert resolve_complexity_weights(DEFAULTS, {"size_bytes": 0.20}) == DEFAULTS

    def test_unspecified_features_keep_default_then_rescale_to_one(self):
        result = resolve_complexity_weights(DEFAULTS, {"size_bytes": 0.40})
        assert math.isclose(sum(result.values()), 1.0)
        assert math.isclose(result["size_bytes"], 0.40 / 1.20)
        assert math.isclose(result["ram_bytes"], 0.10 / 1.20)

    def test_zero_weight_drops_a_feature(self):
        result = resolve_complexity_weights(DEFAULTS, {"language_count": 0.0})
        assert result["language_count"] == 0.0
        assert math.isclose(sum(result.values()), 1.0)

    def test_all_zero_is_rejected(self):
        with pytest.raises(ParameterError, match="all be zero"):
            resolve_complexity_weights(DEFAULTS, {k: 0.0 for k in DEFAULTS})

    @pytest.mark.parametrize("bad", [-0.1, float("nan"), float("inf")])
    def test_negative_and_non_finite_are_rejected(self, bad):
        with pytest.raises(ParameterError):
            resolve_complexity_weights(DEFAULTS, {"size_bytes": bad})

    def test_non_number_is_rejected(self):
        with pytest.raises(ParameterError, match="must be a number"):
            resolve_complexity_weights(DEFAULTS, {"size_bytes": "high"})

    def test_unknown_feature_is_rejected(self):
        with pytest.raises(ParameterError, match="unknown complexity weight"):
            resolve_complexity_weights(DEFAULTS, {"ram_gigabytes": 0.2})

    def test_does_not_mutate_inputs(self):
        override = {"size_bytes": 0.4}
        resolve_complexity_weights(DEFAULTS, override)
        assert override == {"size_bytes": 0.4}
        assert DEFAULTS["size_bytes"] == 0.20


class TestEffectiveParametersVersion:
    def test_defaults_keep_base_version(self):
        assert effective_parameters_version("abc123", DEFAULTS, dict(DEFAULTS)) == "abc123"

    def test_override_changes_version_deterministically(self):
        effective = resolve_complexity_weights(DEFAULTS, {"size_bytes": 0.4})
        first = effective_parameters_version("abc123", DEFAULTS, effective)
        second = effective_parameters_version("abc123", DEFAULTS, dict(effective))
        assert first == second
        assert first != "abc123"
        assert len(first) == 12

    def test_different_weights_give_different_versions(self):
        a = resolve_complexity_weights(DEFAULTS, {"size_bytes": 0.4})
        b = resolve_complexity_weights(DEFAULTS, {"size_bytes": 0.5})
        assert effective_parameters_version("abc123", DEFAULTS, a) != effective_parameters_version(
            "abc123", DEFAULTS, b
        )


class TestRunParametersVersion:
    def test_no_override_equals_file_hash(self, tmp_path):
        from steam_analyst.config.parameters import parameters_version

        path = tmp_path / "parameters.toml"
        path.write_text("x = 1", encoding="utf-8")
        assert run_parameters_version(path, None) == parameters_version(path)

    def test_override_against_real_parameters_changes_version(self):
        from pathlib import Path

        from steam_analyst.config.parameters import parameters_version

        path = Path(__file__).resolve().parents[3] / "config" / "parameters.toml"
        assert run_parameters_version(path, {"ram_bytes": 0.3}) != parameters_version(path)
