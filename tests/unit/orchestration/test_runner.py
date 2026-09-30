"""Unit tests for orchestration.runner module.

Tests thread management, run registration, cancellation, and orphaned-run
reconciliation. Avoids unbounded wall-clock waits by using controllable
threading.Event objects and polling with timeouts.
"""

import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

from steam_analyst.config.settings import Settings
from steam_analyst.orchestration.errors import PipelineError
from steam_analyst.orchestration.pipeline_config import PipelineConfig
from steam_analyst.orchestration.runner import (
    start_pipeline_async,
    resume_run,
    cancel_run,
    is_running,
    active_run_ids,
    reconcile_orphaned_runs,
    _CANCEL_REGISTRY,
    _CANCEL_REGISTRY_LOCK,
)
from steam_analyst.orchestration.stages import PipelineStage, RUN_LEVEL_STAGE
from steam_analyst.storage import (
    connect,
    initialize_schema,
    create_run,
    get_run,
    begin_run_stage,
    finish_run_stage,
)
from steam_analyst.storage.types import RunRecord, RunStage


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database file and initialize schema."""
    db_path = tmp_path / "test.db"
    with connect(db_path) as conn:
        initialize_schema(conn)
    return db_path


@pytest.fixture
def settings(temp_db_path):
    """Create a Settings instance pointing to the temp database."""
    return Settings(
        db_path=temp_db_path,
        steam_web_api_key="test_key",
        http_timeout_seconds=30.0,
        user_agent="Test-Agent/1.0",
        parameters_path=Path("config/parameters.toml"),
    )


@pytest.fixture
def pipeline_config():
    """Create a basic PipelineConfig."""
    return PipelineConfig(
        start_stage=PipelineStage.ACQUISITION,
        max_catalog_pages=None,
        request_budget_override=None,
        notes="Test run",
    )


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the cancellation registry before and after each test."""
    with _CANCEL_REGISTRY_LOCK:
        _CANCEL_REGISTRY.clear()
    yield
    with _CANCEL_REGISTRY_LOCK:
        _CANCEL_REGISTRY.clear()


def wait_for_condition(condition_fn, timeout_seconds=5.0, poll_interval=0.05):
    """Poll a condition function until it returns True or timeout.

    Args:
        condition_fn: A callable returning bool.
        timeout_seconds: Maximum time to wait.
        poll_interval: How often to check the condition.

    Returns:
        True if condition became true within timeout.

    Raises:
        AssertionError if timeout exceeded.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if condition_fn():
            return True
        time.sleep(poll_interval)
    raise AssertionError(
        f"Condition not met within {timeout_seconds} seconds"
    )


class TestStartPipelineAsync:
    """Tests for start_pipeline_async function."""

    def test_returns_run_id_immediately(self, temp_db_path, settings, pipeline_config):
        """start_pipeline_async returns a run_id before the pipeline finishes."""
        # Mock run_pipeline to block until we release it
        ready_event = threading.Event()
        proceed_event = threading.Event()

        def mock_run_pipeline(*args, **kwargs):
            ready_event.set()
            proceed_event.wait(timeout=5.0)  # Wait for test to signal proceed
            return None

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch("steam_analyst.orchestration.runner.parameters_version", return_value="abc123"):
                with patch(
                    "steam_analyst.orchestration.runner.load_settings", return_value=settings
                ):
                    # Call should return immediately
                    run_id = start_pipeline_async(temp_db_path, pipeline_config, settings=settings)

                    # Verify run_id is valid
                    assert isinstance(run_id, str)
                    assert len(run_id) > 0

                    # Wait for worker to reach the blocking point
                    wait_for_condition(ready_event.is_set, timeout_seconds=2.0)

                    # Verify is_running is True while worker is active
                    assert is_running(run_id)

                    # Signal worker to proceed
                    proceed_event.set()

                    # Wait for worker to finish
                    wait_for_condition(
                        lambda: not is_running(run_id), timeout_seconds=2.0
                    )

    def test_run_row_visible_after_return(self, temp_db_path, settings, pipeline_config):
        """After start_pipeline_async returns, the run row is immediately visible."""
        proceed_event = threading.Event()

        def mock_run_pipeline(*args, **kwargs):
            proceed_event.wait(timeout=5.0)

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch("steam_analyst.orchestration.runner.parameters_version", return_value="abc123"):
                with patch(
                    "steam_analyst.orchestration.runner.load_settings", return_value=settings
                ):
                    run_id = start_pipeline_async(temp_db_path, pipeline_config, settings=settings)

                    # Verify run row exists and is readable
                    with connect(temp_db_path) as conn:
                        run = get_run(conn, run_id)
                        assert run is not None
                        assert run.run_id == run_id
                        assert run.status in ("pending", "running")

                    proceed_event.set()
                    wait_for_condition(
                        lambda: not is_running(run_id), timeout_seconds=2.0
                    )

    def test_is_running_transitions_true_false(self, temp_db_path, settings, pipeline_config):
        """is_running(run_id) transitions True -> False after worker finishes."""
        proceed_event = threading.Event()

        def mock_run_pipeline(*args, **kwargs):
            proceed_event.wait(timeout=5.0)

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch("steam_analyst.orchestration.runner.parameters_version", return_value="abc123"):
                with patch(
                    "steam_analyst.orchestration.runner.load_settings", return_value=settings
                ):
                    run_id = start_pipeline_async(temp_db_path, pipeline_config, settings=settings)

                    # Should be running immediately
                    assert is_running(run_id)
                    assert run_id in active_run_ids()

                    # Release and wait for completion
                    proceed_event.set()
                    wait_for_condition(
                        lambda: not is_running(run_id), timeout_seconds=2.0
                    )

                    # Should no longer be running
                    assert not is_running(run_id)
                    assert run_id not in active_run_ids()

    def test_create_run_failure_starts_no_thread(self, temp_db_path, settings, pipeline_config):
        """If create_run raises, no thread is started and the exception propagates."""
        with patch(
            "steam_analyst.orchestration.runner.create_run",
            side_effect=sqlite3.Error("Database is locked"),
        ):
            with patch("steam_analyst.orchestration.runner.parameters_version", return_value="abc123"):
                with pytest.raises(sqlite3.Error):
                    start_pipeline_async(temp_db_path, pipeline_config, settings=settings)

                # Verify no run was registered
                assert len(active_run_ids()) == 0


class TestResumeRun:
    """Tests for resume_run function."""

    def test_resume_unknown_run_id_raises(self, temp_db_path, settings):
        """resume_run with unknown run_id raises PipelineError."""
        with pytest.raises(PipelineError, match="Unknown run_id"):
            resume_run(temp_db_path, "nonexistent_run_id", settings=settings)

    def test_resume_already_running_raises(self, temp_db_path, settings, pipeline_config):
        """resume_run with is_running(run_id)==True raises PipelineError."""
        # Create a run and mark it as live
        with connect(temp_db_path) as conn:
            run_id = create_run(
                conn,
                config=pipeline_config.to_dict(),
                parameters_version="abc123",
                trigger_type="manual",
                notes="Test",
            )

        # Manually register as running
        with _CANCEL_REGISTRY_LOCK:
            _CANCEL_REGISTRY[run_id] = (threading.Event(), temp_db_path)

        try:
            with pytest.raises(PipelineError, match="already running"):
                resume_run(temp_db_path, run_id, settings=settings)
        finally:
            # Clean up
            with _CANCEL_REGISTRY_LOCK:
                _CANCEL_REGISTRY.pop(run_id, None)

    def test_resume_all_stages_succeeded_raises(self, temp_db_path, settings, pipeline_config):
        """resume_run with all stages succeeded raises PipelineError."""
        # Create a run with all stages succeeded
        with connect(temp_db_path) as conn:
            run_id = create_run(
                conn,
                config=pipeline_config.to_dict(),
                parameters_version="abc123",
                trigger_type="manual",
                notes="Test",
            )

            # Create and mark all stages as succeeded
            for stage in PipelineStage:
                begin_run_stage(conn, run_id, stage.value)
                finish_run_stage(conn, run_id, stage.value, "succeeded")

        with pytest.raises(PipelineError, match="all stages succeeded"):
            resume_run(temp_db_path, run_id, settings=settings)

    def test_resume_picks_first_non_succeeded_stage_no_stages(self, temp_db_path, settings, pipeline_config):
        """resume_run with no stage rows starts from ACQUISITION."""
        # Create a run with no stage rows (crashed during preflight)
        with connect(temp_db_path) as conn:
            run_id = create_run(
                conn,
                config=pipeline_config.to_dict(),
                parameters_version="abc123",
                trigger_type="manual",
                notes="Test",
            )

        proceed_event = threading.Event()

        def mock_run_pipeline(conn, rid, config, **kwargs):
            # Verify start_stage is ACQUISITION
            assert config.start_stage == PipelineStage.ACQUISITION
            proceed_event.set()

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch(
                "steam_analyst.orchestration.runner.load_settings", return_value=settings
            ):
                returned_id = resume_run(temp_db_path, run_id, settings=settings)
                assert returned_id == run_id

                wait_for_condition(proceed_event.is_set, timeout_seconds=2.0)
                wait_for_condition(lambda: not is_running(run_id), timeout_seconds=2.0)

    def test_resume_picks_first_non_succeeded_stage_acquisition_succeeded(
        self, temp_db_path, settings, pipeline_config
    ):
        """resume_run resumes from ENRICHMENT when ACQUISITION succeeded."""
        with connect(temp_db_path) as conn:
            run_id = create_run(
                conn,
                config=pipeline_config.to_dict(),
                parameters_version="abc123",
                trigger_type="manual",
                notes="Test",
            )

            # Mark acquisition as succeeded
            begin_run_stage(conn, run_id, PipelineStage.ACQUISITION.value)
            finish_run_stage(conn, run_id, PipelineStage.ACQUISITION.value, "succeeded")

        proceed_event = threading.Event()

        def mock_run_pipeline(conn, rid, config, **kwargs):
            assert config.start_stage == PipelineStage.ENRICHMENT
            proceed_event.set()

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch(
                "steam_analyst.orchestration.runner.load_settings", return_value=settings
            ):
                returned_id = resume_run(temp_db_path, run_id, settings=settings)
                assert returned_id == run_id

                wait_for_condition(proceed_event.is_set, timeout_seconds=2.0)
                wait_for_condition(lambda: not is_running(run_id), timeout_seconds=2.0)

    def test_resume_picks_first_non_succeeded_stage_mixed_status(
        self, temp_db_path, settings, pipeline_config
    ):
        """resume_run resumes from ANALYSIS when ACQUISITION/ENRICHMENT succeeded but ANALYSIS didn't."""
        with connect(temp_db_path) as conn:
            run_id = create_run(
                conn,
                config=pipeline_config.to_dict(),
                parameters_version="abc123",
                trigger_type="manual",
                notes="Test",
            )

            # Mark acquisition and enrichment as succeeded
            for stage in [PipelineStage.ACQUISITION, PipelineStage.ENRICHMENT]:
                begin_run_stage(conn, run_id, stage.value)
                finish_run_stage(conn, run_id, stage.value, "succeeded")

        proceed_event = threading.Event()

        def mock_run_pipeline(conn, rid, config, **kwargs):
            assert config.start_stage == PipelineStage.ANALYSIS
            proceed_event.set()

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch(
                "steam_analyst.orchestration.runner.load_settings", return_value=settings
            ):
                returned_id = resume_run(temp_db_path, run_id, settings=settings)
                assert returned_id == run_id

                wait_for_condition(proceed_event.is_set, timeout_seconds=2.0)
                wait_for_condition(lambda: not is_running(run_id), timeout_seconds=2.0)

    def test_resume_returns_same_run_id(self, temp_db_path, settings, pipeline_config):
        """resume_run returns the same run_id, creates no new row."""
        with connect(temp_db_path) as conn:
            original_run_id = create_run(
                conn,
                config=pipeline_config.to_dict(),
                parameters_version="abc123",
                trigger_type="manual",
                notes="Test",
            )

        proceed_event = threading.Event()

        def mock_run_pipeline(*args, **kwargs):
            proceed_event.set()

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch(
                "steam_analyst.orchestration.runner.load_settings", return_value=settings
            ):
                returned_run_id = resume_run(temp_db_path, original_run_id, settings=settings)
                assert returned_run_id == original_run_id

                wait_for_condition(proceed_event.is_set, timeout_seconds=2.0)
                wait_for_condition(lambda: not is_running(original_run_id), timeout_seconds=2.0)


class TestCancelRun:
    """Tests for cancel_run function."""

    def test_cancel_unknown_run_returns_false(self):
        """cancel_run for unknown run_id returns False without raising."""
        result = cancel_run("nonexistent_run_id")
        assert result is False

    def test_cancel_live_run_returns_true(self, temp_db_path, settings, pipeline_config):
        """cancel_run for a registered run returns True and sets Event."""
        proceed_event = threading.Event()

        def mock_run_pipeline(*args, **kwargs):
            proceed_event.wait(timeout=5.0)

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch("steam_analyst.orchestration.runner.parameters_version", return_value="abc123"):
                with patch(
                    "steam_analyst.orchestration.runner.load_settings", return_value=settings
                ):
                    run_id = start_pipeline_async(temp_db_path, pipeline_config, settings=settings)

                    # Verify we can cancel it
                    result = cancel_run(run_id)
                    assert result is True

                    # Verify Event is set
                    with _CANCEL_REGISTRY_LOCK:
                        if run_id in _CANCEL_REGISTRY:
                            event, _ = _CANCEL_REGISTRY[run_id]
                            assert event.is_set()

                    proceed_event.set()
                    wait_for_condition(lambda: not is_running(run_id), timeout_seconds=2.0)

    def test_cancel_finished_run_returns_false(self, temp_db_path, settings, pipeline_config):
        """cancel_run for a finished run returns False."""
        proceed_event = threading.Event()

        def mock_run_pipeline(*args, **kwargs):
            proceed_event.set()

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch("steam_analyst.orchestration.runner.parameters_version", return_value="abc123"):
                with patch(
                    "steam_analyst.orchestration.runner.load_settings", return_value=settings
                ):
                    run_id = start_pipeline_async(temp_db_path, pipeline_config, settings=settings)

                    # Let it complete
                    wait_for_condition(proceed_event.is_set, timeout_seconds=2.0)
                    wait_for_condition(lambda: not is_running(run_id), timeout_seconds=2.0)

                    # Now try to cancel the finished run
                    result = cancel_run(run_id)
                    assert result is False

    def test_cancel_idempotent(self, temp_db_path, settings, pipeline_config):
        """cancel_run can be called multiple times; both return True."""
        proceed_event = threading.Event()

        def mock_run_pipeline(*args, **kwargs):
            proceed_event.wait(timeout=5.0)

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch("steam_analyst.orchestration.runner.parameters_version", return_value="abc123"):
                with patch(
                    "steam_analyst.orchestration.runner.load_settings", return_value=settings
                ):
                    run_id = start_pipeline_async(temp_db_path, pipeline_config, settings=settings)

                    # First cancel
                    result1 = cancel_run(run_id)
                    assert result1 is True

                    # Second cancel (idempotent)
                    result2 = cancel_run(run_id)
                    assert result2 is True

                    proceed_event.set()
                    wait_for_condition(lambda: not is_running(run_id), timeout_seconds=2.0)

    def test_cancel_appends_run_event(self, temp_db_path, settings, pipeline_config):
        """cancel_run appends a RUN_LEVEL_STAGE run_event."""
        proceed_event = threading.Event()

        def mock_run_pipeline(*args, **kwargs):
            proceed_event.wait(timeout=5.0)

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch("steam_analyst.orchestration.runner.parameters_version", return_value="abc123"):
                with patch(
                    "steam_analyst.orchestration.runner.load_settings", return_value=settings
                ):
                    run_id = start_pipeline_async(temp_db_path, pipeline_config, settings=settings)

                    # Cancel it
                    cancel_run(run_id)

                    # Check that a run_event was appended
                    with connect(temp_db_path) as conn:
                        # Note: read_run_events is imported from storage if available
                        # For now, we verify the event was written by checking the database directly
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT stage, message FROM run_events WHERE run_id = ? ORDER BY event_id DESC LIMIT 1",
                            (run_id,)
                        )
                        row = cursor.fetchone()
                        assert row is not None
                        stage, message = row
                        assert stage == RUN_LEVEL_STAGE
                        assert "Cancellation requested" in message or "cancel" in message.lower()

                    proceed_event.set()
                    wait_for_condition(lambda: not is_running(run_id), timeout_seconds=2.0)


class TestIsRunningAndActiveRunIds:
    """Tests for is_running and active_run_ids functions."""

    def test_is_running_false_initially(self):
        """is_running returns False for any run_id initially."""
        assert is_running("any_run_id") is False

    def test_active_run_ids_empty_initially(self):
        """active_run_ids returns empty list initially."""
        assert active_run_ids() == []

    def test_is_running_true_when_registered(self, temp_db_path, settings, pipeline_config):
        """is_running returns True for a registered run_id."""
        proceed_event = threading.Event()

        def mock_run_pipeline(*args, **kwargs):
            proceed_event.wait(timeout=5.0)

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch("steam_analyst.orchestration.runner.parameters_version", return_value="abc123"):
                with patch(
                    "steam_analyst.orchestration.runner.load_settings", return_value=settings
                ):
                    run_id = start_pipeline_async(temp_db_path, pipeline_config, settings=settings)

                    # Should be running
                    assert is_running(run_id) is True

                    proceed_event.set()
                    wait_for_condition(lambda: not is_running(run_id), timeout_seconds=2.0)

                    # Should no longer be running
                    assert is_running(run_id) is False

    def test_active_run_ids_reflects_snapshot(self, temp_db_path, settings, pipeline_config):
        """active_run_ids returns a list of all registered run_ids."""
        proceed_event = threading.Event()

        def mock_run_pipeline(*args, **kwargs):
            proceed_event.wait(timeout=5.0)

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch("steam_analyst.orchestration.runner.parameters_version", return_value="abc123"):
                with patch(
                    "steam_analyst.orchestration.runner.load_settings", return_value=settings
                ):
                    run_id_1 = start_pipeline_async(temp_db_path, pipeline_config, settings=settings)
                    run_id_2 = start_pipeline_async(temp_db_path, pipeline_config, settings=settings)

                    active = active_run_ids()
                    assert len(active) == 2
                    assert run_id_1 in active
                    assert run_id_2 in active

                    proceed_event.set()
                    wait_for_condition(lambda: len(active_run_ids()) == 0, timeout_seconds=2.0)

    def test_consistency_between_is_running_and_active_run_ids(
        self, temp_db_path, settings, pipeline_config
    ):
        """is_running(rid) consistent with (rid in active_run_ids()) for all states."""
        proceed_event = threading.Event()

        def mock_run_pipeline(*args, **kwargs):
            proceed_event.wait(timeout=5.0)

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch("steam_analyst.orchestration.runner.parameters_version", return_value="abc123"):
                with patch(
                    "steam_analyst.orchestration.runner.load_settings", return_value=settings
                ):
                    run_id_1 = start_pipeline_async(temp_db_path, pipeline_config, settings=settings)
                    run_id_2 = start_pipeline_async(temp_db_path, pipeline_config, settings=settings)
                    unknown_id = "unknown_run_id"

                    # Check consistency
                    for rid in [run_id_1, run_id_2, unknown_id]:
                        assert is_running(rid) == (rid in active_run_ids())

                    proceed_event.set()
                    wait_for_condition(lambda: len(active_run_ids()) == 0, timeout_seconds=2.0)

                    # Check consistency after completion
                    for rid in [run_id_1, run_id_2, unknown_id]:
                        assert is_running(rid) == (rid in active_run_ids())


class TestReconcileOrphanedRuns:
    """Tests for reconcile_orphaned_runs function."""

    def test_no_orphans_returns_empty_list(self, temp_db_path):
        """reconcile_orphaned_runs with no orphans returns empty list."""
        with connect(temp_db_path) as conn:
            result = reconcile_orphaned_runs(conn)
            assert result == []

    def test_orphaned_running_run_marked_failed(self, temp_db_path):
        """A run stuck 'running' is marked 'failed' with the fixed error message."""
        # Create an orphaned run
        with connect(temp_db_path) as conn:
            run_id = create_run(
                conn,
                config={"start_stage": "acquisition"},
                parameters_version="abc123",
                trigger_type="manual",
                notes="Test",
            )

        # Manually mark it as running (as if process crashed mid-execution)
        with connect(temp_db_path) as conn:
            from steam_analyst.storage import update_run_status
            update_run_status(conn, run_id, "running")

        # Reconcile
        with connect(temp_db_path) as conn:
            reconciled = reconcile_orphaned_runs(conn)
            assert run_id in reconciled

            # Verify it's now failed
            from steam_analyst.storage import get_run
            run = get_run(conn, run_id)
            assert run.status == "failed"
            assert "process terminated" in run.error_message.lower()

    def test_orphaned_pending_run_marked_failed(self, temp_db_path):
        """A run stuck 'pending' (crashed during preflight) is reconciled."""
        with connect(temp_db_path) as conn:
            run_id = create_run(
                conn,
                config={"start_stage": "acquisition"},
                parameters_version="abc123",
                trigger_type="manual",
                notes="Test",
            )

        # Manually mark it as pending (as if it never started)
        with connect(temp_db_path) as conn:
            from steam_analyst.storage import update_run_status
            update_run_status(conn, run_id, "pending")

        # Reconcile
        with connect(temp_db_path) as conn:
            reconciled = reconcile_orphaned_runs(conn)
            assert run_id in reconciled

            from steam_analyst.storage import get_run
            run = get_run(conn, run_id)
            assert run.status == "failed"

    def test_live_run_not_reconciled(self, temp_db_path, settings, pipeline_config):
        """A run present in active_run_ids() is not reconciled."""
        proceed_event = threading.Event()

        def mock_run_pipeline(*args, **kwargs):
            proceed_event.wait(timeout=5.0)

        with patch("steam_analyst.orchestration.runner.run_pipeline", mock_run_pipeline):
            with patch("steam_analyst.orchestration.runner.parameters_version", return_value="abc123"):
                with patch(
                    "steam_analyst.orchestration.runner.load_settings", return_value=settings
                ):
                    run_id = start_pipeline_async(temp_db_path, pipeline_config, settings=settings)

                    # Manually mark as running to simulate a live run
                    with connect(temp_db_path) as conn:
                        from steam_analyst.storage import update_run_status
                        update_run_status(conn, run_id, "running")

                    # Reconcile should NOT touch this live run
                    with connect(temp_db_path) as conn:
                        reconciled = reconcile_orphaned_runs(conn)
                        assert run_id not in reconciled

                        from steam_analyst.storage import get_run
                        run = get_run(conn, run_id)
                        assert run.status == "running"

                    proceed_event.set()
                    wait_for_condition(lambda: not is_running(run_id), timeout_seconds=2.0)

    def test_orphaned_run_stages_marked_failed(self, temp_db_path):
        """A reconciled run's 'running' run_stages rows are also marked failed."""
        with connect(temp_db_path) as conn:
            run_id = create_run(
                conn,
                config={"start_stage": "acquisition"},
                parameters_version="abc123",
                trigger_type="manual",
                notes="Test",
            )

            # Create a stage row left in 'running' state
            begin_run_stage(conn, run_id, PipelineStage.ACQUISITION.value)

            # Manually mark run as running
            from steam_analyst.storage import update_run_status
            update_run_status(conn, run_id, "running")

        # Reconcile
        with connect(temp_db_path) as conn:
            reconciled = reconcile_orphaned_runs(conn)
            assert run_id in reconciled

            # Check the stage is marked failed
            from steam_analyst.storage import read_run_stages
            stages = read_run_stages(conn, run_id)
            acq_stage = next((s for s in stages if s.stage == "acquisition"), None)
            assert acq_stage is not None
            assert acq_stage.status == "failed"
            assert "process terminated" in acq_stage.error_message.lower()

    def test_reconcile_idempotent(self, temp_db_path):
        """Calling reconcile_orphaned_runs twice is a no-op the second time."""
        with connect(temp_db_path) as conn:
            run_id = create_run(
                conn,
                config={"start_stage": "acquisition"},
                parameters_version="abc123",
                trigger_type="manual",
                notes="Test",
            )

        with connect(temp_db_path) as conn:
            from steam_analyst.storage import update_run_status
            update_run_status(conn, run_id, "running")

        # First reconcile
        with connect(temp_db_path) as conn:
            reconciled_1 = reconcile_orphaned_runs(conn)
            assert run_id in reconciled_1

        # Second reconcile
        with connect(temp_db_path) as conn:
            reconciled_2 = reconcile_orphaned_runs(conn)
            # Should be empty this time (already marked failed)
            assert run_id not in reconciled_2
            assert len(reconciled_2) == 0
