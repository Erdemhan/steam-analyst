"""Unit tests for analysis.pipeline module."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from steam_analyst.analysis.pipeline import AnalysisReport, run_analysis
from steam_analyst.analysis.errors import AnalysisError
from steam_analyst.config.settings import AnalysisParams
from steam_analyst.storage import (
    append_run_event,
    create_run,
    get_connection,
    initialize_schema,
    read_analysis_result,
    write_enriched,
    write_tags,
)
from steam_analyst.storage.types import TagRow


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create a temporary database file."""
    return tmp_path / "test_analysis.db"


@pytest.fixture
def conn(db_path: Path):
    """Create a database connection with initialized schema."""
    connection = get_connection(db_path)
    initialize_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def mock_analysis_params() -> AnalysisParams:
    """Provide a mock AnalysisParams with locked values from FORMULATION.md."""
    return AnalysisParams(
        simplicity_percentile=0.40,
        trailing_window_months=24,
        min_cluster_size=5,
        opportunity_weights={
            "demand": 0.40,
            "competition": 0.30,
            "simplicity": 0.30,
        },
        min_tag_votes=0,
        max_tags_per_game=20,
        tag_distance_threshold=None,  # Provisional until run 1 data
        clustering_linkage="average",
    )


def _build_enriched_frame(n_rows: int = 30) -> pd.DataFrame:
    """Build a synthetic enriched frame for testing."""
    today = datetime.now()
    release_dates = [
        (today - timedelta(days=int(30.44 * (24 - i / (n_rows / 24))))).isoformat()
        for i in range(n_rows)
    ]

    return pd.DataFrame({
        "appid": list(range(1000, 1000 + n_rows)),
        "name": [f"Game {i}" for i in range(n_rows)],
        "app_type": ["game"] * n_rows,
        "developer": [f"Dev {i}" for i in range(n_rows)],
        "publisher": [f"Pub {i}" for i in range(n_rows)],
        "release_date": release_dates,
        "price_usd": np.random.uniform(4.99, 29.99, n_rows),
        "is_free": [False] * n_rows,
        "review_count": np.random.randint(50, 500, n_rows),
        "review_positive_pct": np.random.uniform(0.6, 0.95, n_rows),
        "owners_estimate_low": np.random.randint(100, 1000, n_rows),
        "owners_estimate_mid": np.random.randint(500, 5000, n_rows),
        "owners_estimate_high": np.random.randint(1000, 10000, n_rows),
        "size_bytes": np.random.randint(int(1e7), int(1e9), n_rows),
        "ram_bytes": np.random.randint(int(1e7), int(1e9), n_rows),
        "achievement_count": np.random.randint(0, 50, n_rows),
        "language_count": np.random.randint(1, 20, n_rows),
        "platform_count": np.random.randint(1, 4, n_rows),
        "dlc_count": np.random.randint(0, 10, n_rows),
        "dev_title_count": np.random.randint(1, 10, n_rows),
        "is_early_access": [False] * n_rows,
        "early_access_days": [0] * n_rows,
        "deck_compat": ["verified"] * n_rows,
        "genres_json": ['["Indie", "Adventure"]'] * n_rows,
        "categories_json": ['["Singleplayer"]'] * n_rows,
        "complexity_score": np.random.uniform(0.1, 0.9, n_rows),
        "imputed_features_json": ["{}"] * n_rows,
        "estimated_sales_low": np.random.randint(100, 1000, n_rows),
        "estimated_sales_mid": np.random.randint(500, 5000, n_rows),
        "estimated_sales_high": np.random.randint(1000, 10000, n_rows),
        "estimated_revenue_gross_usd": np.random.randint(5000, 50000, n_rows),
        "estimated_revenue_net_usd": np.random.randint(3000, 30000, n_rows),
        "effort_adjusted_return": np.random.randint(100, 1000, n_rows),
        "parameters_version": "test_v1",
    })


def _build_tags_frame(appids: list, n_tags_per_app: int = 3) -> list[TagRow]:
    """Build synthetic tag rows for testing."""
    tags = [
        "Indie", "Adventure", "Puzzle", "RPG", "Action",
        "Pixel Graphics", "2D", "Story-Rich", "Casual", "Exploration"
    ]

    tag_rows = []
    for appid in appids:
        selected_tags = tags[appid % len(tags): (appid % len(tags)) + n_tags_per_app]
        for rank, tag in enumerate(selected_tags, 1):
            tag_rows.append(
                TagRow(
                    appid=appid,
                    tag=tag,
                    votes=np.random.randint(50, 500),
                    rank=rank,
                )
            )

    return tag_rows


class TestAnalysisReport:
    """Tests for AnalysisReport dataclass."""

    def test_counts_internally_consistent(self):
        """scored_cluster_count + clusters_below_min_size == cluster_count."""
        report = AnalysisReport(
            run_id="test_run",
            candidates_in=100,
            simple_subset_size=40,
            rejected_by_reason={"above_simplicity_threshold": 60},
            cluster_count=10,
            scored_cluster_count=7,
            clusters_below_min_size=3,
            duration_seconds=5.0,
        )

        assert report.scored_cluster_count + report.clusters_below_min_size == report.cluster_count

    def test_empty_candidate_set_all_zero(self):
        """An empty run produces an all-zero report."""
        report = AnalysisReport(
            run_id="test_run",
            candidates_in=0,
            simple_subset_size=0,
            rejected_by_reason={},
            cluster_count=0,
            scored_cluster_count=0,
            clusters_below_min_size=0,
            duration_seconds=0.1,
        )

        assert report.candidates_in == 0
        assert report.simple_subset_size == 0
        assert report.cluster_count == 0
        assert report.scored_cluster_count == 0
        assert report.clusters_below_min_size == 0

    def test_report_is_frozen(self):
        """AnalysisReport is immutable."""
        report = AnalysisReport(
            run_id="test_run",
            candidates_in=100,
            simple_subset_size=40,
            rejected_by_reason={},
            cluster_count=8,
            scored_cluster_count=6,
            clusters_below_min_size=2,
            duration_seconds=5.0,
        )

        with pytest.raises(AttributeError):
            report.candidates_in = 200


class TestRunAnalysisFullSuccess:
    """Tests for a full successful run_analysis execution."""

    def test_run_analysis_writes_all_five_types(
        self, conn: sqlite3.Connection, mock_analysis_params: AnalysisParams
    ):
        """A successful run writes all five analysis_results types."""
        # Create a run
        run_id = create_run(
            conn,
            config={"test": "config"},
            parameters_version="test_v1",
        )

        # Emit enrichment stage_complete event to indicate enrichment ran
        append_run_event(
            conn,
            run_id,
            stage="enrichment",
            level="info",
            message="stage_complete",
        )

        # Write enriched frame and tags
        frame = _build_enriched_frame(n_rows=50)
        write_enriched(conn, run_id, frame)

        appids = frame["appid"].tolist()
        tag_rows = _build_tags_frame(appids, n_tags_per_app=4)
        write_tags(conn, run_id, tag_rows)

        # Run analysis
        events = []
        def on_event(*, stage, level, message, progress=None):
            events.append({
                "stage": stage,
                "level": level,
                "message": message,
                "progress": progress,
            })

        report = run_analysis(
            conn,
            run_id,
            mock_analysis_params,
            parameters_version="test_v1",
            on_event=on_event,
        )

        # Verify report
        assert report.run_id == run_id
        assert report.candidates_in == 50
        assert report.simple_subset_size > 0
        assert report.cluster_count > 0
        assert report.scored_cluster_count >= 0
        assert report.scored_cluster_count + report.clusters_below_min_size == report.cluster_count
        assert report.duration_seconds > 0

        # Verify all five analysis results were written
        for analysis_type in [
            "tag_clusters",
            "opportunity_matrix",
            "competition_density",
            "tag_trends",
            "tag_summary",
        ]:
            result = read_analysis_result(conn, run_id, analysis_type)
            assert result is not None, f"{analysis_type} result not found"
            assert isinstance(result, dict), f"{analysis_type} result is not a dict"

        # Verify tag_clusters structure
        tag_clusters = read_analysis_result(conn, run_id, "tag_clusters")
        assert "assignments" in tag_clusters
        assert "cluster_labels" in tag_clusters
        assert "cluster_members" in tag_clusters
        assert "method" in tag_clusters
        assert "params_used" in tag_clusters
        assert "cluster_mode_shares" in tag_clusters
        assert "excluded_generic_tags" in tag_clusters

        # Verify opportunity_matrix structure
        matrix = read_analysis_result(conn, run_id, "opportunity_matrix")
        assert "data" in matrix
        assert isinstance(matrix["data"], list)
        for row in matrix["data"]:
            for column in ("singleplayer_share", "multiplayer_share", "coop_share"):
                assert column in row

        # Verify stage_complete event was emitted via on_event
        # Check if any event matches stage_complete
        stage_complete_found = any(
            e.get("message") == "stage_complete" and e.get("stage") == "analysis"
            for e in events
        )
        # If not found via on_event, check if it was written to database
        if not stage_complete_found:
            from steam_analyst.storage import read_run_events
            db_events = read_run_events(conn, run_id)
            stage_complete_in_db = any(
                e.message == "stage_complete" and e.stage == "analysis"
                for e in db_events
            )
            assert stage_complete_in_db, "stage_complete event not found in database"
        else:
            assert stage_complete_found, "stage_complete event not emitted"

    def test_run_analysis_emits_events(
        self, conn: sqlite3.Connection, mock_analysis_params: AnalysisParams
    ):
        """run_analysis emits progress events to on_event callback."""
        # Create a run
        run_id = create_run(
            conn,
            config={"test": "config"},
            parameters_version="test_v1",
        )

        # Emit enrichment stage_complete event
        append_run_event(
            conn,
            run_id,
            stage="enrichment",
            level="info",
            message="stage_complete",
        )

        # Write enriched frame and tags
        frame = _build_enriched_frame(n_rows=30)
        write_enriched(conn, run_id, frame)

        appids = frame["appid"].tolist()
        tag_rows = _build_tags_frame(appids)
        write_tags(conn, run_id, tag_rows)

        # Collect events
        events = []
        def on_event(*, stage, level, message, progress=None):
            events.append({
                "stage": stage,
                "level": level,
                "message": message,
                "progress": progress,
            })

        run_analysis(
            conn,
            run_id,
            mock_analysis_params,
            parameters_version="test_v1",
            on_event=on_event,
        )

        # Verify events were emitted
        assert len(events) > 0
        assert all(e["stage"] == "analysis" for e in events)
        assert any(e["level"] == "info" for e in events)


class TestRunAnalysisEmptyCandidate:
    """Tests for the legitimately-empty-candidate-set case."""

    def test_empty_candidate_set_succeeds_with_empty_results(
        self, conn: sqlite3.Connection, mock_analysis_params: AnalysisParams
    ):
        """Empty candidate set (enrichment completed) returns empty report without error."""
        # Create a run
        run_id = create_run(
            conn,
            config={"test": "config"},
            parameters_version="test_v1",
        )

        # Emit enrichment stage_complete event (indicating enrichment ran but found nothing)
        append_run_event(
            conn,
            run_id,
            stage="enrichment",
            level="info",
            message="stage_complete",
        )

        # Write empty enriched frame and tags
        frame = _build_enriched_frame(n_rows=0)
        write_enriched(conn, run_id, frame)
        write_tags(conn, run_id, [])

        # Run analysis
        def on_event(*, stage, level, message, progress=None):
            pass

        report = run_analysis(
            conn,
            run_id,
            mock_analysis_params,
            parameters_version="test_v1",
            on_event=on_event,
        )

        # Verify empty report
        assert report.run_id == run_id
        assert report.candidates_in == 0
        assert report.simple_subset_size == 0
        assert report.cluster_count == 0
        assert report.scored_cluster_count == 0
        assert report.clusters_below_min_size == 0
        assert report.duration_seconds > 0

        # Verify empty but well-formed results were written
        for analysis_type in [
            "tag_clusters",
            "opportunity_matrix",
            "competition_density",
            "tag_trends",
            "tag_summary",
        ]:
            result = read_analysis_result(conn, run_id, analysis_type)
            assert result is not None, f"{analysis_type} result not found for empty set"
            assert isinstance(result, dict)
            assert "data" in result or analysis_type == "tag_clusters"


class TestRunAnalysisEnrichmentNeverRan:
    """Tests for the enrichment-never-ran error case."""

    def test_enrichment_never_ran_raises_analysis_error(
        self, conn: sqlite3.Connection, mock_analysis_params: AnalysisParams
    ):
        """Empty games_enriched with no enrichment stage_complete event raises AnalysisError."""
        # Create a run (no enrichment stage_complete event)
        run_id = create_run(
            conn,
            config={"test": "config"},
            parameters_version="test_v1",
        )

        # Write empty enriched frame (simulate incomplete enrichment)
        frame = _build_enriched_frame(n_rows=0)
        write_enriched(conn, run_id, frame)

        # Run analysis should raise AnalysisError
        def on_event(*, stage, level, message, progress=None):
            pass

        with pytest.raises(AnalysisError, match="Enrichment has not completed"):
            run_analysis(
                conn,
                run_id,
                mock_analysis_params,
                parameters_version="test_v1",
                on_event=on_event,
            )

    def test_nonexistent_run_raises_analysis_error(
        self, conn: sqlite3.Connection, mock_analysis_params: AnalysisParams
    ):
        """Nonexistent run_id raises AnalysisError."""
        def on_event(*, stage, level, message, progress=None):
            pass

        with pytest.raises(AnalysisError, match="does not exist"):
            run_analysis(
                conn,
                "nonexistent_run",
                mock_analysis_params,
                parameters_version="test_v1",
                on_event=on_event,
            )


class TestRunAnalysisEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_single_cluster_below_min_size(
        self, conn: sqlite3.Connection, mock_analysis_params: AnalysisParams
    ):
        """A single cluster below min_cluster_size is reported as below_min_size."""
        # Create a run with very few games to ensure they form a single cluster
        run_id = create_run(
            conn,
            config={"test": "config"},
            parameters_version="test_v1",
        )

        # Emit enrichment stage_complete
        append_run_event(
            conn,
            run_id,
            stage="enrichment",
            level="info",
            message="stage_complete",
        )

        # Write small enriched frame
        frame = _build_enriched_frame(n_rows=3)
        write_enriched(conn, run_id, frame)

        appids = frame["appid"].tolist()
        tag_rows = _build_tags_frame(appids, n_tags_per_app=1)
        write_tags(conn, run_id, tag_rows)

        # Run analysis
        def on_event(*, stage, level, message, progress=None):
            pass

        report = run_analysis(
            conn,
            run_id,
            mock_analysis_params,
            parameters_version="test_v1",
            on_event=on_event,
        )

        # Verify cluster count consistency
        assert report.scored_cluster_count + report.clusters_below_min_size == report.cluster_count

    def test_provisional_threshold_warning_emitted(
        self, conn: sqlite3.Connection, mock_analysis_params: AnalysisParams
    ):
        """When tag_distance_threshold is None, a provisional threshold warning is emitted."""
        # Create a run
        run_id = create_run(
            conn,
            config={"test": "config"},
            parameters_version="test_v1",
        )

        # Emit enrichment stage_complete
        append_run_event(
            conn,
            run_id,
            stage="enrichment",
            level="info",
            message="stage_complete",
        )

        # Write enriched frame
        frame = _build_enriched_frame(n_rows=30)
        write_enriched(conn, run_id, frame)

        appids = frame["appid"].tolist()
        tag_rows = _build_tags_frame(appids)
        write_tags(conn, run_id, tag_rows)

        # Use params with None threshold (provisional)
        params = AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=5,
            opportunity_weights={
                "demand": 0.40,
                "competition": 0.30,
                "simplicity": 0.30,
            },
            min_tag_votes=0,
            max_tags_per_game=20,
            tag_distance_threshold=None,  # Provisional
            clustering_linkage="average",
        )

        events = []
        def on_event(*, stage, level, message, progress=None):
            events.append({
                "stage": stage,
                "level": level,
                "message": message,
            })

        run_analysis(
            conn,
            run_id,
            params,
            parameters_version="test_v1",
            on_event=on_event,
        )

        # Verify provisional threshold message was emitted
        # (might be "provisional" or "run_local_search" related message)
        assert any(
            "provisional" in e["message"].lower() or "run_local_search" in e["message"].lower()
            for e in events
        ), "No provisional threshold message found"

    def test_complexity_score_with_nulls(
        self, conn: sqlite3.Connection, mock_analysis_params: AnalysisParams
    ):
        """Games with NULL complexity_score are handled correctly."""
        # Create a run
        run_id = create_run(
            conn,
            config={"test": "config"},
            parameters_version="test_v1",
        )

        # Emit enrichment stage_complete
        append_run_event(
            conn,
            run_id,
            stage="enrichment",
            level="info",
            message="stage_complete",
        )

        # Write enriched frame with some NULL complexity_scores
        frame = _build_enriched_frame(n_rows=30)
        frame.loc[0:4, "complexity_score"] = np.nan  # Set some to NULL
        write_enriched(conn, run_id, frame)

        appids = frame["appid"].tolist()
        tag_rows = _build_tags_frame(appids)
        write_tags(conn, run_id, tag_rows)

        # Run analysis
        def on_event(*, stage, level, message, progress=None):
            pass

        report = run_analysis(
            conn,
            run_id,
            mock_analysis_params,
            parameters_version="test_v1",
            on_event=on_event,
        )

        # Verify report is valid
        assert report.candidates_in == 30
        assert report.simple_subset_size < report.candidates_in  # Some filtered due to NULL

    def test_multiple_tags_per_game(
        self, conn: sqlite3.Connection, mock_analysis_params: AnalysisParams
    ):
        """Games with multiple tags are correctly clustered."""
        # Create a run
        run_id = create_run(
            conn,
            config={"test": "config"},
            parameters_version="test_v1",
        )

        # Emit enrichment stage_complete
        append_run_event(
            conn,
            run_id,
            stage="enrichment",
            level="info",
            message="stage_complete",
        )

        # Write enriched frame
        frame = _build_enriched_frame(n_rows=40)
        write_enriched(conn, run_id, frame)

        appids = frame["appid"].tolist()
        tag_rows = _build_tags_frame(appids, n_tags_per_app=5)  # Multiple tags per game
        write_tags(conn, run_id, tag_rows)

        # Run analysis
        def on_event(*, stage, level, message, progress=None):
            pass

        report = run_analysis(
            conn,
            run_id,
            mock_analysis_params,
            parameters_version="test_v1",
            on_event=on_event,
        )

        # Verify report
        assert report.cluster_count > 0
        assert report.simple_subset_size > 0

        # Verify tag_clusters has assignments
        tag_clusters = read_analysis_result(conn, run_id, "tag_clusters")
        assignments = tag_clusters["assignments"]
        assert len(assignments) > 0, "No cluster assignments found"
