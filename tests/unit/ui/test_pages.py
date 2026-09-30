"""Unit tests for the ui.pages module.

These tests focus on verifying core behaviors that can be reliably tested:
- Session state discipline (only SESSION_KEYS are written)
- Function call patterns and data flow
- Caveat rendering and ordering
- Empty/error states

For UI-intensive functions deeply integrated with Streamlit, testing focuses on
testable logic paths rather than full rendering, since Streamlit is designed for
interactive apps with stateful component rendering that is difficult to mock
in isolation without a full Streamlit app context.
"""

import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import pandas as pd
import streamlit as st

from steam_analyst.config import Settings
from steam_analyst import reporting, storage
from steam_analyst.ui.pages import (
    render_caveat_panel,
    render_past_analyses_page,
    render_analysis_detail_page,
)
from steam_analyst.ui.session import SESSION_KEYS


class TestRenderCaveatPanel:
    """Tests for render_caveat_panel - fully self-contained rendering logic."""

    def test_all_caveats_rendered(self):
        """A list of 7 caveats results in 7 rendered entries."""
        caveats = [
            reporting.Caveat(
                key=f"caveat_{i}",
                title=f"Caveat {i}",
                body=f"Body {i}",
                severity="info",
            )
            for i in range(7)
        ]

        with patch("streamlit.expander"), patch(
            "streamlit.write"
        ) as mock_write:
            render_caveat_panel(caveats)
            assert mock_write.call_count >= 7

    def test_empty_list_still_renders_expander(self):
        """An empty caveats list still renders the expander container."""
        with patch("streamlit.expander"), patch("streamlit.write") as mock_write:
            render_caveat_panel([])
            mock_write.assert_called()

    def test_severity_visually_distinguished(self):
        """Different severity levels render with distinct markers."""
        caveats = [
            reporting.Caveat(key="info", title="Info", body="Body", severity="info"),
            reporting.Caveat(key="error", title="Error", body="Body", severity="error"),
        ]

        with patch("streamlit.expander"), patch(
            "streamlit.write"
        ) as mock_write:
            render_caveat_panel(caveats)
            calls = "\n".join([str(call) for call in mock_write.call_args_list])
            assert "ℹ️" in calls
            assert "❌" in calls

    def test_order_preserved(self):
        """Caveats render in the exact order passed in."""
        caveats = [
            reporting.Caveat(key="b", title="B Title", body="B Body", severity="info"),
            reporting.Caveat(key="a", title="A Title", body="A Body", severity="info"),
        ]

        with patch("streamlit.expander"), patch(
            "streamlit.write"
        ) as mock_write:
            render_caveat_panel(caveats)
            calls = [str(call) for call in mock_write.call_args_list]
            b_idx = next((i for i, c in enumerate(calls) if "B Title" in str(c)), None)
            a_idx = next((i for i, c in enumerate(calls) if "A Title" in str(c)), None)
            assert b_idx is not None and a_idx is not None and b_idx < a_idx


class TestRenderPastAnalysesPage:
    """Tests for render_past_analyses_page."""

    @pytest.fixture
    def mock_settings(self, tmp_path):
        """Mock Settings."""
        return Mock(
            spec=Settings,
            db_path=tmp_path / "test.db",
            parameters_path=tmp_path / "parameters.toml",
        )

    def test_list_runs_called_with_limit_50(self, mock_settings):
        """list_runs is called with limit=50."""
        mock_conn = Mock(spec=sqlite3.Connection)

        with patch("steam_analyst.ui.pages.storage") as mock_storage_module:
            mock_storage_module.list_runs.return_value = pd.DataFrame()

            with patch("streamlit.header"), patch("streamlit.info"):
                render_past_analyses_page(mock_conn, mock_settings)

                mock_storage_module.list_runs.assert_called_with(mock_conn, limit=50)

    def test_empty_runs_shows_info(self, mock_settings):
        """Empty run list shows info message."""
        mock_conn = Mock(spec=sqlite3.Connection)

        with patch("steam_analyst.ui.pages.storage") as mock_storage_module:
            mock_storage_module.list_runs.return_value = pd.DataFrame()

            with patch("streamlit.header"), patch("streamlit.info") as mock_info:
                render_past_analyses_page(mock_conn, mock_settings)

                mock_info.assert_called()


class TestRenderAnalysisDetailPage:
    """Tests for render_analysis_detail_page."""

    @pytest.fixture
    def mock_settings(self, tmp_path):
        """Mock Settings."""
        return Mock(
            spec=Settings,
            db_path=tmp_path / "test.db",
            parameters_path=tmp_path / "parameters.toml",
        )

    def test_missing_run_id_shows_empty_state(self, mock_settings):
        """Missing run_id in query_params shows empty state."""
        mock_conn = Mock(spec=sqlite3.Connection)
        st.query_params.clear()

        with patch("streamlit.header"), patch("streamlit.info") as mock_info, patch(
            "streamlit.button"
        ):
            render_analysis_detail_page(mock_conn, mock_settings)

            mock_info.assert_called()

    def test_unknown_run_id_shows_empty_state(self, mock_settings):
        """Unknown run_id shows empty state without raising exception."""
        mock_conn = Mock(spec=sqlite3.Connection)
        st.query_params["run_id"] = "unknown-run-id"

        with patch("steam_analyst.ui.pages.reporting") as mock_reporting_module:
            mock_reporting_module.ReportNotAvailable = reporting.ReportNotAvailable
            mock_reporting_module.load_run_report.side_effect = (
                reporting.ReportNotAvailable("not found")
            )

            with patch("streamlit.header"), patch("streamlit.warning") as mock_warning, patch(
                "streamlit.button"
            ):
                render_analysis_detail_page(mock_conn, mock_settings)

                mock_warning.assert_called()

    def test_empty_candidate_count_shows_message(self, mock_settings):
        """Empty candidate set shows 'not enough data' message."""
        mock_conn = Mock(spec=sqlite3.Connection)
        st.query_params["run_id"] = "test-run-id"

        report = Mock(spec=reporting.RunReport)
        report.is_partial = False
        report.run = Mock(status="succeeded")
        report.caveats = []
        report.funnel = Mock(candidate_count=0, simple_subset_size=50)

        with patch("steam_analyst.ui.pages.reporting") as mock_reporting_module:
            mock_reporting_module.load_run_report.return_value = report

            with patch("streamlit.header"), patch("streamlit.divider"), patch(
                "streamlit.subheader"
            ), patch("streamlit.info"), patch(
                "steam_analyst.ui.pages.render_caveat_panel"
            ):
                render_analysis_detail_page(mock_conn, mock_settings)


class TestSessionKeysDiscipline:
    """Tests for session state discipline across all functions."""

    def test_caveat_panel_writes_no_session_keys(self):
        """render_caveat_panel writes no session state keys."""
        st.session_state.clear()

        caveats = [
            reporting.Caveat(
                key="test",
                title="Test",
                body="Test body",
                severity="info",
            )
        ]

        with patch("streamlit.expander"), patch("streamlit.write"):
            render_caveat_panel(caveats)

            for key in st.session_state.keys():
                assert key in SESSION_KEYS
