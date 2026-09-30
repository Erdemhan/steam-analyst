"""Unit tests for reporting.report module.

Tests cover:
- RunReport dataclass creation and validation
- is_partial_run canonical definition (ADR-016)
- partial_run_caveat severity and error message handling
- load_run_report assembly from storage
- headline_metrics extraction
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from steam_analyst.reporting.case_studies import CaseStudy
from steam_analyst.reporting.report import (
    RunReport,
    headline_metrics,
    is_partial_run,
    load_run_report,
    partial_run_caveat,
)
from steam_analyst.reporting.types import Caveat, FunnelSummary, ReportNotAvailable
from steam_analyst.storage import (
    RunRecord,
    RunStage,
    TagRow,
    begin_run_stage,
    create_run,
    finish_run_stage,
    get_connection,
    initialize_schema,
    update_run_status,
    write_analysis_result,
    write_enriched,
    write_tags,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create a temporary database file."""
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path: Path):
    """Create a database connection with initialized schema."""
    connection = get_connection(db_path)
    initialize_schema(connection)
    yield connection
    connection.close()


def _build_enriched_dataframe(appids: list[int]) -> pd.DataFrame:
    """Helper to create a valid enriched DataFrame with all required columns."""
    return pd.DataFrame({
        "appid": appids,
        "name": [f"Game {i}" for i in appids],
        "app_type": ["game"] * len(appids),
        "developer": [f"Dev {i}" for i in appids],
        "publisher": [f"Pub {i}" for i in appids],
        "release_date": [f"2023-0{i % 9 + 1}-01" for i in appids],
        "price_usd": [9.99 + i for i in appids],
        "is_free": [False] * len(appids),
        "review_count": [100 + i * 50 for i in appids],
        "review_positive_pct": [0.75 + i * 0.01 for i in appids],
        "owners_estimate_low": [100 + i * 50 for i in appids],
        "owners_estimate_mid": [150 + i * 75 for i in appids],
        "owners_estimate_high": [200 + i * 100 for i in appids],
        "size_bytes": [1e9 + i * 1e8 for i in appids],
        "achievement_count": [10 + i for i in appids],
        "language_count": [5 + i for i in appids],
        "platform_count": [1] * len(appids),
        "dlc_count": [0] * len(appids),
        "dev_title_count": [1 + i for i in appids],
        "is_early_access": [False] * len(appids),
        "early_access_days": [0] * len(appids),
        "deck_compat": ["unknown"] * len(appids),
        "genres_json": ["[]"] * len(appids),
        "categories_json": ["[]"] * len(appids),
        "complexity_score": [0.3 + i * 0.05 for i in appids],
        "imputed_features_json": ["{}"] * len(appids),
        "estimated_sales_low": [100 + i * 50 for i in appids],
        "estimated_sales_mid": [150 + i * 75 for i in appids],
        "estimated_sales_high": [200 + i * 100 for i in appids],
        "estimated_revenue_gross_usd": [1000.0 + i * 500 for i in appids],
        "estimated_revenue_net_usd": [800.0 + i * 400 for i in appids],
        "effort_adjusted_return": [100.0 + i * 50 for i in appids],
        "parameters_version": ["v1"] * len(appids),
    })


@pytest.fixture
def completed_run_id(conn: sqlite3.Connection) -> str:
    """Create a fully completed run with all stages succeeded."""
    run_id = create_run(
        conn,
        config={"test": True},
        parameters_version="v1",
        trigger_type="manual",
    )

    # Mark all three stages as succeeded
    for stage_name in ["acquisition", "enrichment", "analysis"]:
        begin_run_stage(conn, run_id, stage_name)
        finish_run_stage(conn, run_id, stage_name, status="succeeded")

    # Update run status to succeeded
    update_run_status(conn, run_id, "succeeded", finished_at=datetime.now(timezone.utc).isoformat())

    # Write minimal analysis results
    _write_minimal_analysis_results(conn, run_id)

    # Write enriched data
    enriched_data = _build_enriched_dataframe([1, 2, 3])
    write_enriched(conn, run_id, enriched_data)

    # Write tags
    tags_data = [
        TagRow(appid=1, tag="Indie", votes=100, rank=1),
        TagRow(appid=1, tag="Puzzle", votes=50, rank=2),
        TagRow(appid=2, tag="Action", votes=200, rank=1),
        TagRow(appid=2, tag="Adventure", votes=150, rank=2),
        TagRow(appid=3, tag="RPG", votes=300, rank=1),
        TagRow(appid=3, tag="Fantasy", votes=250, rank=2),
    ]
    write_tags(conn, run_id, tags_data)

    return run_id


@pytest.fixture
def running_run_id(conn: sqlite3.Connection) -> str:
    """Create a partially completed run (still running, only acquisition done)."""
    run_id = create_run(
        conn,
        config={"test": True},
        parameters_version="v1",
        trigger_type="manual",
    )

    # Mark acquisition as succeeded
    begin_run_stage(conn, run_id, "acquisition")
    finish_run_stage(conn, run_id, "acquisition", status="succeeded")

    # Update run status to running
    update_run_status(conn, run_id, "running")

    # Enrichment and analysis not started
    # Do NOT write analysis results for partial runs

    return run_id


@pytest.fixture
def failed_run_id(conn: sqlite3.Connection) -> str:
    """Create a failed run (failed during enrichment)."""
    run_id = create_run(
        conn,
        config={"test": True},
        parameters_version="v1",
        trigger_type="manual",
    )

    # Mark acquisition as succeeded
    begin_run_stage(conn, run_id, "acquisition")
    finish_run_stage(conn, run_id, "acquisition", status="succeeded")

    # Mark enrichment as failed
    begin_run_stage(conn, run_id, "enrichment")
    finish_run_stage(
        conn, run_id, "enrichment", status="failed", error_message="enrichment: ValueError: bad row"
    )

    # Update run status to failed
    update_run_status(conn, run_id, "failed", finished_at=datetime.now(timezone.utc).isoformat(), error_message="enrichment: ValueError: bad row")

    # Analysis not attempted
    # Do NOT write analysis results for partial runs

    return run_id


@pytest.fixture
def cancelled_run_id(conn: sqlite3.Connection) -> str:
    """Create a cancelled run."""
    run_id = create_run(
        conn,
        config={"test": True},
        parameters_version="v1",
        trigger_type="manual",
    )

    # Mark acquisition as succeeded
    begin_run_stage(conn, run_id, "acquisition")
    finish_run_stage(conn, run_id, "acquisition", status="succeeded")

    # Mark enrichment as cancelled
    begin_run_stage(conn, run_id, "enrichment")
    finish_run_stage(conn, run_id, "enrichment", status="cancelled")

    # Update run status to cancelled
    update_run_status(conn, run_id, "cancelled", finished_at=datetime.now(timezone.utc).isoformat())

    # Do NOT write analysis results for partial runs

    return run_id


def _write_minimal_analysis_results(conn: sqlite3.Connection, run_id: str) -> None:
    """Write minimal but well-formed analysis results for a run."""
    # Opportunity matrix
    write_analysis_result(
        conn,
        run_id,
        "opportunity_matrix",
        {
            "data": [
                {
                    "cluster_id": 1,
                    "label": "Casual Puzzle",
                    "n_games": 10,
                    "demand_z": 0.5,
                    "competition_z": -0.3,
                    "simplicity_z": 0.2,
                    "opportunity_score": 0.8,
                    "median_estimated_sales_mid": 150,
                    "median_complexity": 0.3,
                    "releases_in_window": 2,
                }
            ]
        },
        parameters_version="v1",
    )

    # Tag summary
    write_analysis_result(
        conn,
        run_id,
        "tag_summary",
        {
            "data": [
                {
                    "tag": "Indie",
                    "n_games": 100,
                    "median_complexity_score": 0.4,
                    "median_estimated_sales_mid": 200,
                    "median_review_positive_pct": 0.8,
                    "median_price_usd": 9.99,
                }
            ]
        },
        parameters_version="v1",
    )

    # Tag trends
    write_analysis_result(
        conn,
        run_id,
        "tag_trends",
        {
            "data": [
                {
                    "tag": "Indie",
                    "period": "2023-01",
                    "n_games": 50,
                    "median_review_positive_pct": 0.79,
                }
            ]
        },
        parameters_version="v1",
    )

    # Tag clusters
    write_analysis_result(
        conn,
        run_id,
        "tag_clusters",
        {
            "assignments": [{"appid": 1, "cluster_id": 1}],
            "cluster_labels": {"1": "Casual Puzzle"},
            "cluster_members": {"1": ["tag1", "tag2"]},
            "method": "agglomerative_jaccard_no_genre_anchor",
            "params_used": {},
        },
        parameters_version="v1",
    )

    # Funnel report
    write_analysis_result(
        conn,
        run_id,
        "funnel_report",
        {
            "data": {
                "catalog_size": 10000,
                "candidate_count": 1000,
                "detail_fetched": 900,
                "detail_failed": 100,
                "simple_subset_size": 500,
            },
            "rejected_by_reason": {
                "coarse_filter.review_count_below_floor": 5000,
                "simplicity_filter.above_simplicity_threshold": 500,
            },
        },
        parameters_version="v1",
    )

    # Competition density
    write_analysis_result(
        conn,
        run_id,
        "competition_density",
        {"data": []},
        parameters_version="v1",
    )


class TestIsPartialRun:
    """Tests for is_partial_run function."""

    def test_all_succeeded_is_not_partial(self):
        """Three RunStage entries, all status='succeeded', returns False."""
        stages = [
            RunStage(
                run_id="test", stage="acquisition", status="succeeded", started_at=None, finished_at=None, attempt=0, error_message=None
            ),
            RunStage(
                run_id="test", stage="enrichment", status="succeeded", started_at=None, finished_at=None, attempt=0, error_message=None
            ),
            RunStage(
                run_id="test", stage="analysis", status="succeeded", started_at=None, finished_at=None, attempt=0, error_message=None
            ),
        ]
        assert is_partial_run(stages) is False

    def test_empty_stages_is_partial(self):
        """An empty stages list returns True."""
        assert is_partial_run([]) is True

    def test_one_failed_stage_is_partial(self):
        """Two succeeded, one failed, returns True."""
        stages = [
            RunStage(
                run_id="test", stage="acquisition", status="succeeded", started_at=None, finished_at=None, attempt=0, error_message=None
            ),
            RunStage(
                run_id="test", stage="enrichment", status="failed", started_at=None, finished_at=None, attempt=0, error_message=None
            ),
            RunStage(
                run_id="test", stage="analysis", status="pending", started_at=None, finished_at=None, attempt=0, error_message=None
            ),
        ]
        assert is_partial_run(stages) is True

    def test_extra_unknown_stage_does_not_affect_result(self):
        """All three required stages succeeded plus one unrecognized extra stage still returns False."""
        stages = [
            RunStage(
                run_id="test", stage="acquisition", status="succeeded", started_at=None, finished_at=None, attempt=0, error_message=None
            ),
            RunStage(
                run_id="test", stage="enrichment", status="succeeded", started_at=None, finished_at=None, attempt=0, error_message=None
            ),
            RunStage(
                run_id="test", stage="analysis", status="succeeded", started_at=None, finished_at=None, attempt=0, error_message=None
            ),
            RunStage(
                run_id="test", stage="future_stage", status="succeeded", started_at=None, finished_at=None, attempt=0, error_message=None
            ),
        ]
        assert is_partial_run(stages) is False

    def test_missing_one_stage_is_partial(self):
        """Missing one required stage returns True."""
        stages = [
            RunStage(
                run_id="test", stage="acquisition", status="succeeded", started_at=None, finished_at=None, attempt=0, error_message=None
            ),
            RunStage(
                run_id="test", stage="enrichment", status="succeeded", started_at=None, finished_at=None, attempt=0, error_message=None
            ),
        ]
        assert is_partial_run(stages) is True


class TestPartialRunCaveat:
    """Tests for partial_run_caveat function."""

    def test_running_severity_and_wording(self):
        """A running, partial run produces severity='warning'."""
        missing_stages = ["analysis"]
        run = RunRecord(
            run_id="test",
            started_at=datetime.now(),
            finished_at=None,
            status="running",
            trigger_type="manual",
            parent_run_id=None,
            config={},
            parameters_version="v1",
            code_version=None,
            error_message=None,
            notes=None,
        )

        caveat = partial_run_caveat(missing_stages, run)
        assert caveat.key == "partial_run"
        assert caveat.severity == "warning"
        assert "analysis" in caveat.body
        assert "None" not in caveat.body

    def test_failed_severity_and_error_message(self):
        """A failed run's caveat has severity='error' and includes error_message."""
        missing_stages = ["enrichment", "analysis"]
        run = RunRecord(
            run_id="test",
            started_at=datetime.now(),
            finished_at=datetime.now(),
            status="failed",
            trigger_type="manual",
            parent_run_id=None,
            config={},
            parameters_version="v1",
            code_version=None,
            error_message="enrichment: ValueError: bad row",
            notes=None,
        )

        caveat = partial_run_caveat(missing_stages, run)
        assert caveat.severity == "error"
        assert "enrichment: ValueError: bad row" in caveat.body
        assert "enrichment" in caveat.body

    def test_cancelled_severity_is_warning(self):
        """A cancelled run's caveat has severity='warning'."""
        missing_stages = ["analysis"]
        run = RunRecord(
            run_id="test",
            started_at=datetime.now(),
            finished_at=datetime.now(),
            status="cancelled",
            trigger_type="manual",
            parent_run_id=None,
            config={},
            parameters_version="v1",
            code_version=None,
            error_message=None,
            notes=None,
        )

        caveat = partial_run_caveat(missing_stages, run)
        assert caveat.severity == "warning"

    def test_empty_missing_stages_raises(self):
        """Calling with empty missing_stages raises ValueError."""
        run = RunRecord(
            run_id="test",
            started_at=datetime.now(),
            finished_at=None,
            status="running",
            trigger_type="manual",
            parent_run_id=None,
            config={},
            parameters_version="v1",
            code_version=None,
            error_message=None,
            notes=None,
        )

        with pytest.raises(ValueError, match="non-empty"):
            partial_run_caveat([], run)


class TestLoadRunReport:
    """Tests for load_run_report function."""

    def test_unknown_run_id_raises(self, conn: sqlite3.Connection):
        """An unknown run_id raises ReportNotAvailable."""
        with pytest.raises(ReportNotAvailable):
            load_run_report(conn, "nonexistent-run-id")

    def test_succeeded_run_not_partial(self, conn: sqlite3.Connection, completed_run_id: str):
        """A fully succeeded fixture run has is_partial=False and missing_stages=[]."""
        report = load_run_report(conn, completed_run_id)
        assert report.is_partial is False
        assert report.missing_stages == []
        assert len(report.stages) == 3
        assert all(s.status == "succeeded" for s in report.stages)

    def test_running_run_is_partial(self, conn: sqlite3.Connection, running_run_id: str):
        """A run with status='running' and only acquisition succeeded is partial."""
        report = load_run_report(conn, running_run_id)
        assert report.is_partial is True
        assert set(report.missing_stages) == {"enrichment", "analysis"}

    def test_failed_run_is_partial(self, conn: sqlite3.Connection, failed_run_id: str):
        """A failed run is partial and includes error_message in caveat."""
        report = load_run_report(conn, failed_run_id)
        assert report.is_partial is True
        assert "enrichment" in report.missing_stages

        # Check partial_run caveat is present
        partial_caveat = next((c for c in report.caveats if c.key == "partial_run"), None)
        assert partial_caveat is not None
        assert partial_caveat.severity == "error"
        assert "enrichment: ValueError: bad row" in partial_caveat.body

    def test_cancelled_run_is_partial(self, conn: sqlite3.Connection, cancelled_run_id: str):
        """A cancelled run is partial with warning severity."""
        report = load_run_report(conn, cancelled_run_id)
        assert report.is_partial is True

        partial_caveat = next((c for c in report.caveats if c.key == "partial_run"), None)
        assert partial_caveat is not None
        assert partial_caveat.severity == "warning"

    def test_completed_run_has_analysis_results(
        self, conn: sqlite3.Connection, completed_run_id: str
    ):
        """A completed run returns non-empty DataFrames for analysis results."""
        report = load_run_report(conn, completed_run_id)

        # Opportunity matrix should be non-empty (one row with label "Casual Puzzle")
        assert len(report.opportunity_matrix) > 0

        # Tag summary should be non-empty
        assert len(report.tag_summary) > 0

    def test_partial_run_has_empty_frames(self, conn: sqlite3.Connection, running_run_id: str):
        """A partial run with no analysis results has well-formed empty frames."""
        report = load_run_report(conn, running_run_id)

        # Frames should be empty but well-formed
        assert len(report.opportunity_matrix) == 0
        # Check that expected columns are present
        assert "cluster_id" in report.opportunity_matrix.columns or "Cluster ID" in report.opportunity_matrix.columns

    def test_funnel_summary_is_populated(self, conn: sqlite3.Connection, completed_run_id: str):
        """FunnelSummary is populated from funnel_report."""
        report = load_run_report(conn, completed_run_id)

        funnel = report.funnel
        assert funnel.catalog_size == 10000
        assert funnel.candidate_count == 1000
        assert funnel.detail_fetched == 900
        assert funnel.detail_failed == 100
        assert funnel.simple_subset_size == 500

    def test_caveats_include_interpretive_caveats(self, conn: sqlite3.Connection, completed_run_id: str):
        """A completed run includes all interpretive caveats."""
        report = load_run_report(conn, completed_run_id)

        # Should have at least the 8 fixed interpretive caveats
        caveat_keys = {c.key for c in report.caveats}
        assert "steamspy_owner_confidence" in caveat_keys
        assert "boxleiter_approximation" in caveat_keys

    def test_completed_run_no_partial_caveat(self, conn: sqlite3.Connection, completed_run_id: str):
        """A completed run does not have a partial_run caveat."""
        report = load_run_report(conn, completed_run_id)

        partial_caveat = next((c for c in report.caveats if c.key == "partial_run"), None)
        assert partial_caveat is None

    def test_report_dataclass_is_frozen(self, conn: sqlite3.Connection, completed_run_id: str):
        """RunReport is a frozen dataclass (immutable)."""
        report = load_run_report(conn, completed_run_id)

        with pytest.raises(AttributeError):
            report.run_id = "modified"


class TestHeadlineMetrics:
    """Tests for headline_metrics function."""

    def test_headline_metrics_for_completed_run(
        self, conn: sqlite3.Connection, completed_run_id: str
    ):
        """A completed run yields the expected top archetype and status."""
        report = load_run_report(conn, completed_run_id)
        metrics = headline_metrics(report)

        assert metrics["catalog_size"] == 10000
        assert metrics["candidate_count"] == 1000
        assert metrics["simple_subset_size"] == 500
        assert metrics["top_archetype_label"] == "Casual Puzzle"
        assert metrics["top_opportunity_score"] == 0.8
        assert metrics["status"] == "succeeded"

    def test_headline_metrics_for_empty_opportunity_matrix(self):
        """An empty opportunity_matrix yields None for both top-archetype fields."""
        opportunity_matrix = pd.DataFrame(columns=["cluster_id", "label", "opportunity_score"])
        run_record = RunRecord(
            run_id="test",
            started_at=datetime.now() - timedelta(seconds=100),
            finished_at=datetime.now(),
            status="succeeded",
            trigger_type="manual",
            parent_run_id=None,
            config={},
            parameters_version="v1",
            code_version=None,
            error_message=None,
            notes=None,
        )

        from steam_analyst.reporting.report import headline_metrics_impl

        metrics = headline_metrics_impl(opportunity_matrix, run_record, 1000, 100, 50)

        assert metrics["top_archetype_label"] is None
        assert metrics["top_opportunity_score"] is None
        assert metrics["catalog_size"] == 1000

    def test_headline_metrics_for_unfinished_run(self, conn: sqlite3.Connection, running_run_id: str):
        """A run with finished_at=None yields run_duration_seconds=None."""
        report = load_run_report(conn, running_run_id)
        metrics = headline_metrics(report)

        assert metrics["run_duration_seconds"] is None
        assert metrics["status"] == "running"

    def test_headline_metrics_duration_calculation(self):
        """Run duration is correctly calculated from started_at and finished_at."""
        start = datetime.now()
        end = start + timedelta(seconds=123)

        run_record = RunRecord(
            run_id="test",
            started_at=start,
            finished_at=end,
            status="succeeded",
            trigger_type="manual",
            parent_run_id=None,
            config={},
            parameters_version="v1",
            code_version=None,
            error_message=None,
            notes=None,
        )

        opportunity_matrix = pd.DataFrame(columns=["cluster_id", "label", "opportunity_score"])

        from steam_analyst.reporting.report import headline_metrics_impl

        metrics = headline_metrics_impl(opportunity_matrix, run_record, 0, 0, 0)

        assert metrics["run_duration_seconds"] == pytest.approx(123.0, abs=0.1)

    def test_headline_metrics_dict_has_all_expected_keys(self, conn: sqlite3.Connection, completed_run_id: str):
        """The returned dict has all expected keys."""
        report = load_run_report(conn, completed_run_id)
        metrics = headline_metrics(report)

        expected_keys = {
            "catalog_size",
            "candidate_count",
            "simple_subset_size",
            "top_archetype_label",
            "top_opportunity_score",
            "run_duration_seconds",
            "status",
        }
        assert set(metrics.keys()) == expected_keys


class TestRunReportIntegration:
    """Integration tests for complete run report assembly."""

    def test_load_run_report_matches_edge_case_no_analysis(
        self, conn: sqlite3.Connection, running_run_id: str
    ):
        """A run with no analysis_results still loads without raising."""
        report = load_run_report(conn, running_run_id)

        assert report.is_partial is True
        assert len(report.opportunity_matrix) == 0
        assert len(report.tag_summary) == 0

    def test_run_report_missing_stages_preserves_order(self, conn: sqlite3.Connection, failed_run_id: str):
        """missing_stages preserves pipeline order (acquisition, enrichment, analysis)."""
        report = load_run_report(conn, failed_run_id)

        # Acquisition succeeded, enrichment failed, analysis not attempted
        # So missing_stages should be ['enrichment', 'analysis'] in that order
        assert report.missing_stages == ["enrichment", "analysis"]

    def test_run_report_is_partial_consistent_with_missing_stages(
        self, conn: sqlite3.Connection, completed_run_id: str
    ):
        """is_partial is consistent with missing_stages."""
        report = load_run_report(conn, completed_run_id)

        # is_partial should be True iff missing_stages is non-empty
        assert report.is_partial == bool(report.missing_stages)

    def test_run_report_caveats_always_include_interpretive_caveats(
        self, conn: sqlite3.Connection, completed_run_id: str
    ):
        """Caveats always include the fixed interpretive_caveats."""
        report = load_run_report(conn, completed_run_id)

        caveat_keys = {c.key for c in report.caveats}
        # Check at least a few of the fixed caveats
        assert "steamspy_owner_confidence" in caveat_keys
        assert "boxleiter_approximation" in caveat_keys
        assert "simplicity_proxy" in caveat_keys


class TestSimpleSubset:
    """_simple_subset reproduces the analysis stage's simplicity filter from its recorded size."""

    @staticmethod
    def _frame():
        import pandas as pd

        return pd.DataFrame(
            {
                "appid": [1, 2, 3, 4, 5],
                "complexity_score": [0.5, 0.2, 0.2, None, 0.9],
            }
        )

    def test_keeps_rows_at_or_below_the_kth_smallest_score(self):
        from steam_analyst.reporting.report import _simple_subset

        assert sorted(_simple_subset(self._frame(), 3)["appid"]) == [1, 2, 3]

    def test_ties_at_the_cutoff_are_all_kept(self):
        from steam_analyst.reporting.report import _simple_subset

        assert sorted(_simple_subset(self._frame(), 1)["appid"]) == [2, 3]

    def test_zero_or_missing_size_gives_empty_subset(self):
        from steam_analyst.reporting.report import _simple_subset

        assert _simple_subset(self._frame(), 0).empty
        assert _simple_subset(self._frame(), None).empty
