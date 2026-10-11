"""Tests for the complexity-weights section of the new-analysis form."""

from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from steam_analyst.ui.pages import weights_override_from_inputs

DEFAULTS = {"size_bytes": 0.20, "ram_bytes": 0.10, "language_count": 0.70}


class TestWeightsOverrideFromInputs:
    def test_unchanged_inputs_give_none(self):
        assert weights_override_from_inputs(dict(DEFAULTS), DEFAULTS) is None

    def test_returns_only_changed_weights(self):
        inputs = {**DEFAULTS, "ram_bytes": 0.30}
        assert weights_override_from_inputs(inputs, DEFAULTS) == {"ram_bytes": 0.30}

    def test_float_noise_is_not_a_change(self):
        inputs = {**DEFAULTS, "size_bytes": 0.2 + 1e-12}
        assert weights_override_from_inputs(inputs, DEFAULTS) is None


def _form_app():
    from unittest.mock import patch

    import streamlit as st
    from steam_analyst import config
    from steam_analyst.ui.pages import render_new_analysis_page

    settings = config.load_settings()
    captured = st.session_state.setdefault("captured_configs", [])

    def fake_start(db_path, pipeline_config, settings=None):
        captured.append(pipeline_config)
        return "fake-run-id"

    with patch("steam_analyst.orchestration.active_run_ids", return_value=[]), patch(
        "steam_analyst.orchestration.start_pipeline_async", fake_start
    ):
        render_new_analysis_page(None, settings)


@pytest.fixture
def form():
    at = AppTest.from_function(_form_app, default_timeout=60)
    at.run()
    assert not at.exception
    return at


def _weight_inputs(at):
    return {ni.key: ni for ni in at.number_input if ni.key and ni.key.startswith("weight_")}


def test_form_shows_ten_weights_with_locked_defaults(form):
    inputs = _weight_inputs(form)
    assert len(inputs) == 10
    assert inputs["weight_size_bytes"].value == pytest.approx(0.20)
    assert sum(ni.value for ni in inputs.values()) == pytest.approx(1.0)


def test_untouched_form_starts_run_without_override(form):
    form.button[0].click().run()
    assert not form.exception
    assert form.session_state["captured_configs"][0].complexity_weights_override is None


def test_changed_weight_is_passed_as_override_and_warned(form):
    _weight_inputs(form)["weight_ram_bytes"].set_value(0.30)
    form.button[0].click().run()
    assert not form.exception
    config = form.session_state["captured_configs"][0]
    assert config.complexity_weights_override == {"ram_bytes": pytest.approx(0.30)}
    assert any("Özel karmaşıklık ağırlıkları" in w.value for w in form.warning)


def test_all_zero_weights_show_an_error_and_start_nothing(form):
    for ni in _weight_inputs(form).values():
        ni.set_value(0.0)
    form.button[0].click().run()
    assert any("sıfır" in e.value.lower() or "zero" in e.value.lower() for e in form.error)
    assert form.session_state["captured_configs"] == []
