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
from unittest.mock import MagicMock, Mock, patch

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
            "streamlit.button", return_value=False
        ):
            render_analysis_detail_page(mock_conn, mock_settings)

            mock_info.assert_called()

    def test_go_to_past_analyses_button_switches_page(self, mock_settings):
        """The 'Go to Past Analyses' button navigates to the registered past page."""
        from steam_analyst.ui import pages as ui_pages

        mock_conn = Mock(spec=sqlite3.Connection)
        st.query_params.clear()
        past_page = Mock(name="past_page")
        ui_pages.register_nav_pages({"past": past_page})

        with patch("streamlit.header"), patch("streamlit.info"), patch(
            "streamlit.button", return_value=True
        ), patch("streamlit.switch_page") as mock_switch:
            render_analysis_detail_page(mock_conn, mock_settings)

        mock_switch.assert_called_once_with(past_page)

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
                "streamlit.button", return_value=False
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


class TestCaseStudyRendering:
    """Case studies render using the real CaseStudy field names."""

    def test_real_case_study_renders_without_attribute_errors(self):
        from steam_analyst.reporting.case_studies import CaseStudy

        case_study = CaseStudy(
            appid=553850,
            name="Example Game",
            developer="Example Dev",
            release_date="Feb 8, 2024",
            price_usd=39.99,
            review_count=634411,
            review_positive_pct=0.81,
            estimated_sales_band=(1000.0, 2000.0, 3000.0),
            estimated_revenue_net_usd=float("nan"),
            complexity_score=0.48,
            top_tags=["Action", "Co-op"],
            archetype_label="Archetype 1",
            rationale="Example rationale.",
            complexity_drivers=[("install_size", 0.15)],
            store_url="https://store.steampowered.com/app/553850/",
        )
        report = Mock(spec=reporting.RunReport)
        report.is_partial = False
        report.run = Mock(status="succeeded")
        report.caveats = []
        report.funnel = Mock(candidate_count=5, simple_subset_size=3, catalog_size=100)
        report.case_studies = [case_study]
        report.opportunity_matrix = pd.DataFrame()
        report.tag_summary = pd.DataFrame()
        report.tag_trends = pd.DataFrame()
        st.query_params["run_id"] = "test-run-id"

        with patch("steam_analyst.ui.pages.reporting") as mock_reporting_module, patch(
            "steam_analyst.ui.pages.render_caveat_panel"
        ), patch("streamlit.header"), patch("streamlit.divider"), patch(
            "streamlit.subheader"
        ), patch("streamlit.dataframe"), patch("streamlit.metric"), patch(
            "streamlit.columns", return_value=[MagicMock(), MagicMock(), MagicMock()]
        ), patch("streamlit.expander") as mock_expander, patch(
            "streamlit.write"
        ) as mock_write, patch("streamlit.markdown"), patch("streamlit.caption"), patch("streamlit.info"):
            mock_reporting_module.load_run_report.return_value = report
            render_analysis_detail_page(Mock(spec=sqlite3.Connection), Mock())

        mock_expander.assert_called_once_with("Example Game (appid=553850)")
        written = " ".join(str(c.args[0]) for c in mock_write.call_args_list)
        assert "%81 olumlu" in written
        assert "bilinmiyor" in written


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


class TestSimpleSummary:
    """The plain-language summary at the top of the detail page."""

    @staticmethod
    def _report(matrix):
        return Mock(
            funnel=Mock(catalog_size=1000, candidate_count=50, simple_subset_size=20),
            opportunity_matrix=matrix,
            case_studies=[],
        )

    def test_names_top_group_when_matrix_available(self):
        from steam_analyst.ui.pages import _render_simple_summary

        matrix = pd.DataFrame(
            {
                "label": ["Archetype 1", "Archetype 2"],
                "n_games": [6, 8],
                "releases_in_window": [5, 7],
                "median_estimated_sales_mid": [1000.0, 2000.0],
                "opportunity_score": [0.2, 0.9],
            }
        )
        with patch("steam_analyst.ui.pages.st") as mock_st:
            mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
            _render_simple_summary(self._report(matrix))

        text = " ".join(str(c.args[0]) for c in mock_st.markdown.call_args_list)
        assert "Grup 2" in text
        mock_st.bar_chart.assert_called_once()
        mock_st.warning.assert_not_called()

    def test_warns_when_no_groups_formed(self):
        from steam_analyst.ui.pages import _render_simple_summary

        with patch("steam_analyst.ui.pages.st") as mock_st:
            mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
            _render_simple_summary(self._report(pd.DataFrame()))

        mock_st.warning.assert_called_once()
        assert "oluşturulamadı" in mock_st.warning.call_args.args[0]
