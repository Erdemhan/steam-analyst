"""
Unit tests for storage.run_stages: begin_run_stage, finish_run_stage, read_run_stages.

Tests cover:
- First-time stage creation and subsequent re-attempts (ADR-014 resume)
- Terminal status transitions and error message storage
- Tolerant reads for missing runs
- Foreign key validation
- Stage ordering and attempt tracking
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from steam_analyst.storage import schema, runs, run_stages
from steam_analyst.storage.types import StorageError


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Fixture: temporary SQLite database file."""
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path: Path) -> sqlite3.Connection:
    """Fixture: an open connection with schema initialized."""
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    # Set required pragmas
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")

    schema.initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def run_id(conn: sqlite3.Connection) -> str:
    """Fixture: a valid run_id for testing."""
    return runs.create_run(
        conn,
        config={"test": True},
        parameters_version="test-v1",
    )


class TestBeginRunStage:
    """Tests for begin_run_stage function."""

    def test_first_attempt_creates_row(self, conn: sqlite3.Connection, run_id: str):
        """Calling begin_run_stage for a stage never attempted creates the row with attempt=1."""
        attempt = run_stages.begin_run_stage(conn, run_id, "acquisition")

        assert attempt == 1

        # Verify the row exists with correct values
        stages = run_stages.read_run_stages(conn, run_id)
        assert len(stages) == 1
        assert stages[0].stage == "acquisition"
        assert stages[0].status == "running"
        assert stages[0].attempt == 1
        assert stages[0].started_at is not None
        assert stages[0].finished_at is None
        assert stages[0].error_message is None

    def test_reattempt_increments_and_resets(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """A second begin_run_stage call after finish_run_stage('succeeded') increments attempt and clears finished_at/error_message."""
        # First attempt
        attempt1 = run_stages.begin_run_stage(conn, run_id, "acquisition")
        assert attempt1 == 1

        # Finish with success
        run_stages.finish_run_stage(conn, run_id, "acquisition", "succeeded")

        # Verify finished state
        stages = run_stages.read_run_stages(conn, run_id)
        assert stages[0].status == "succeeded"
        assert stages[0].finished_at is not None

        # Second attempt (re-run)
        attempt2 = run_stages.begin_run_stage(conn, run_id, "acquisition")
        assert attempt2 == 2

        # Verify reset state
        stages = run_stages.read_run_stages(conn, run_id)
        assert len(stages) == 1
        assert stages[0].status == "running"
        assert stages[0].attempt == 2
        assert stages[0].finished_at is None
        assert stages[0].error_message is None

    def test_unknown_run_id_raises(self, conn: sqlite3.Connection):
        """begin_run_stage for a run_id absent from runs raises StorageError."""
        with pytest.raises(StorageError, match="does not exist"):
            run_stages.begin_run_stage(conn, "missing", "acquisition")

    def test_invalid_stage_raises(self, conn: sqlite3.Connection, run_id: str):
        """An out-of-vocabulary stage name raises StorageError before any write."""
        with pytest.raises(StorageError, match="stage must be one of"):
            run_stages.begin_run_stage(conn, run_id, "orchestration")

    def test_all_three_stages_can_be_begun(self, conn: sqlite3.Connection, run_id: str):
        """All three valid stages can be created for the same run."""
        for stage in ["acquisition", "enrichment", "analysis"]:
            attempt = run_stages.begin_run_stage(conn, run_id, stage)
            assert attempt == 1

        stages = run_stages.read_run_stages(conn, run_id)
        assert len(stages) == 3
        assert [s.stage for s in stages] == ["acquisition", "enrichment", "analysis"]

    def test_multiple_reattempts_increment_correctly(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """Multiple re-attempts correctly increment the attempt counter."""
        for expected_attempt in range(1, 5):
            attempt = run_stages.begin_run_stage(conn, run_id, "acquisition")
            assert attempt == expected_attempt

            # Always reset to success for the next re-attempt
            run_stages.finish_run_stage(conn, run_id, "acquisition", "succeeded")

        stages = run_stages.read_run_stages(conn, run_id)
        assert stages[0].attempt == 4

    def test_write_is_committed_before_return(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """The write is committed immediately, visible to a separate query."""
        run_stages.begin_run_stage(conn, run_id, "acquisition")

        # Open a separate connection and verify visibility
        other_conn = sqlite3.connect(
            str(conn.execute("PRAGMA database_list").fetchone()[2]),
            isolation_level=None,
        )
        other_conn.row_factory = sqlite3.Row
        other_conn.execute("PRAGMA foreign_keys=ON")

        stages = run_stages.read_run_stages(other_conn, run_id)
        assert len(stages) == 1
        assert stages[0].stage == "acquisition"

        other_conn.close()

    def test_reopen_a_running_stage(self, conn: sqlite3.Connection, run_id: str):
        """Calling begin_run_stage on a stage already 'running' resets attempt (no-op in effect)."""
        # First attempt
        run_stages.begin_run_stage(conn, run_id, "acquisition")
        stages = run_stages.read_run_stages(conn, run_id)
        first_started = stages[0].started_at

        # Call begin again without finishing (e.g., stale running row from a crash)
        attempt = run_stages.begin_run_stage(conn, run_id, "acquisition")

        # Spec says storage doesn't detect staleness; it re-opens as instructed
        # This means attempt increments (UPD side of ON CONFLICT)
        assert attempt == 2

        stages = run_stages.read_run_stages(conn, run_id)
        assert stages[0].status == "running"
        # started_at should be updated to the new begin call's time
        assert stages[0].started_at >= first_started


class TestFinishRunStage:
    """Tests for finish_run_stage function."""

    def test_finish_succeeded_sets_terminal_state(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """A begun stage finished with 'succeeded' shows finished_at set and error_message None."""
        run_stages.begin_run_stage(conn, run_id, "acquisition")
        run_stages.finish_run_stage(conn, run_id, "acquisition", "succeeded")

        stages = run_stages.read_run_stages(conn, run_id)
        assert stages[0].status == "succeeded"
        assert stages[0].finished_at is not None
        assert stages[0].error_message is None

    def test_finish_failed_stores_error_message(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """status='failed' with an error_message stores it verbatim."""
        run_stages.begin_run_stage(conn, run_id, "enrichment")

        error_msg = "enrichment: ValueError: bad row"
        run_stages.finish_run_stage(
            conn, run_id, "enrichment", "failed", error_message=error_msg
        )

        stages = run_stages.read_run_stages(conn, run_id)
        assert stages[0].status == "failed"
        assert stages[0].error_message == error_msg
        assert stages[0].finished_at is not None

    def test_finish_cancelled_with_error_message(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """status='cancelled' with error_message stores it."""
        run_stages.begin_run_stage(conn, run_id, "analysis")

        error_msg = "User requested cancellation"
        run_stages.finish_run_stage(
            conn, run_id, "analysis", "cancelled", error_message=error_msg
        )

        stages = run_stages.read_run_stages(conn, run_id)
        assert stages[0].status == "cancelled"
        assert stages[0].error_message == error_msg

    def test_finish_never_begun_raises(self, conn: sqlite3.Connection, run_id: str):
        """Calling finish_run_stage for a (run_id, stage) with no existing row raises StorageError."""
        with pytest.raises(StorageError, match="was never begun"):
            run_stages.finish_run_stage(conn, run_id, "analysis", "succeeded")

    def test_invalid_status_raises(self, conn: sqlite3.Connection, run_id: str):
        """status='running' is rejected as not a terminal value."""
        run_stages.begin_run_stage(conn, run_id, "acquisition")

        with pytest.raises(StorageError, match="status must be one of"):
            run_stages.finish_run_stage(conn, run_id, "acquisition", "running")

    def test_pending_status_rejected(self, conn: sqlite3.Connection, run_id: str):
        """status='pending' is rejected as not a terminal value."""
        run_stages.begin_run_stage(conn, run_id, "acquisition")

        with pytest.raises(StorageError, match="status must be one of"):
            run_stages.finish_run_stage(conn, run_id, "acquisition", "pending")

    def test_finish_succeeded_with_error_message_accepted(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """status='succeeded' with error_message provided is accepted and stored."""
        run_stages.begin_run_stage(conn, run_id, "acquisition")

        # Spec: error_message is accepted but not required for non-failure states
        warning_msg = "completed with warnings"
        run_stages.finish_run_stage(
            conn, run_id, "acquisition", "succeeded", error_message=warning_msg
        )

        stages = run_stages.read_run_stages(conn, run_id)
        assert stages[0].status == "succeeded"
        assert stages[0].error_message == warning_msg

    def test_finish_twice_without_begin_overwrites(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """Calling finish_run_stage twice without intervening begin_run_stage overwrites the first terminal status."""
        run_stages.begin_run_stage(conn, run_id, "acquisition")

        # First finish with succeeded
        run_stages.finish_run_stage(conn, run_id, "acquisition", "succeeded")
        stages = run_stages.read_run_stages(conn, run_id)
        first_finished_at = stages[0].finished_at

        # Second finish with failed (without begin in between)
        run_stages.finish_run_stage(
            conn,
            run_id,
            "acquisition",
            "failed",
            error_message="oops, actually failed",
        )

        stages = run_stages.read_run_stages(conn, run_id)
        assert stages[0].status == "failed"
        assert stages[0].error_message == "oops, actually failed"
        assert stages[0].finished_at >= first_finished_at

    def test_write_is_committed_before_return(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """The write is committed immediately, visible to a separate connection."""
        run_stages.begin_run_stage(conn, run_id, "acquisition")
        run_stages.finish_run_stage(conn, run_id, "acquisition", "succeeded")

        # Open a separate connection and verify visibility
        db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
        other_conn = sqlite3.connect(str(db_path), isolation_level=None)
        other_conn.row_factory = sqlite3.Row
        other_conn.execute("PRAGMA foreign_keys=ON")

        stages = run_stages.read_run_stages(other_conn, run_id)
        assert len(stages) == 1
        assert stages[0].status == "succeeded"

        other_conn.close()


class TestReadRunStages:
    """Tests for read_run_stages function."""

    def test_all_three_stages_succeeded(self, conn: sqlite3.Connection, run_id: str):
        """A run with all three stages begun and finished 'succeeded' returns three RunStage rows in pipeline order."""
        for stage in ["acquisition", "enrichment", "analysis"]:
            run_stages.begin_run_stage(conn, run_id, stage)
            run_stages.finish_run_stage(conn, run_id, stage, "succeeded")

        stages = run_stages.read_run_stages(conn, run_id)

        assert len(stages) == 3
        assert stages[0].stage == "acquisition"
        assert stages[1].stage == "enrichment"
        assert stages[2].stage == "analysis"
        assert all(s.status == "succeeded" for s in stages)

    def test_no_stages_attempted_returns_empty(self, conn: sqlite3.Connection, run_id: str):
        """A freshly created run with no begin_run_stage calls yet returns an empty list."""
        stages = run_stages.read_run_stages(conn, run_id)

        assert stages == []

    def test_unknown_run_id_returns_empty_not_error(self, conn: sqlite3.Connection):
        """A nonexistent run_id returns an empty list rather than raising."""
        stages = run_stages.read_run_stages(conn, "does-not-exist")

        assert stages == []

    def test_ordering_independent_of_insertion_order(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """If analysis was begun before acquisition, the returned order is still acquisition, enrichment, analysis."""
        # Begin in reverse order: analysis, enrichment, acquisition
        run_stages.begin_run_stage(conn, run_id, "analysis")
        run_stages.begin_run_stage(conn, run_id, "enrichment")
        run_stages.begin_run_stage(conn, run_id, "acquisition")

        stages = run_stages.read_run_stages(conn, run_id)

        assert len(stages) == 3
        assert [s.stage for s in stages] == ["acquisition", "enrichment", "analysis"]

    def test_partial_run_returns_only_attempted_stages(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """Only enrichment has been begun (acquisition row missing)."""
        run_stages.begin_run_stage(conn, run_id, "enrichment")

        stages = run_stages.read_run_stages(conn, run_id)

        assert len(stages) == 1
        assert stages[0].stage == "enrichment"

    def test_mixed_stage_statuses(self, conn: sqlite3.Connection, run_id: str):
        """A run with mixed stage statuses (some succeeded, some failed)."""
        run_stages.begin_run_stage(conn, run_id, "acquisition")
        run_stages.finish_run_stage(conn, run_id, "acquisition", "succeeded")

        run_stages.begin_run_stage(conn, run_id, "enrichment")
        run_stages.finish_run_stage(
            conn, run_id, "enrichment", "failed", error_message="enrichment failed"
        )

        run_stages.begin_run_stage(conn, run_id, "analysis")
        # Leave analysis running (no finish call)

        stages = run_stages.read_run_stages(conn, run_id)

        assert len(stages) == 3
        assert stages[0].stage == "acquisition"
        assert stages[0].status == "succeeded"
        assert stages[1].stage == "enrichment"
        assert stages[1].status == "failed"
        assert stages[2].stage == "analysis"
        assert stages[2].status == "running"

    def test_run_stages_properties_round_trip(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """RunStage properties are correctly deserialized from database rows."""
        run_stages.begin_run_stage(conn, run_id, "acquisition")
        run_stages.finish_run_stage(
            conn,
            run_id,
            "acquisition",
            "failed",
            error_message="test error",
        )

        stages = run_stages.read_run_stages(conn, run_id)
        stage = stages[0]

        assert stage.run_id == run_id
        assert stage.stage == "acquisition"
        assert stage.status == "failed"
        assert stage.attempt == 1
        assert stage.error_message == "test error"
        assert isinstance(stage.started_at, datetime)
        assert isinstance(stage.finished_at, datetime)

    def test_single_stage_at_different_attempts(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """Querying a single stage across multiple attempts shows the latest state."""
        # First attempt: succeed
        run_stages.begin_run_stage(conn, run_id, "acquisition")
        run_stages.finish_run_stage(conn, run_id, "acquisition", "succeeded")

        # Second attempt: still in progress
        run_stages.begin_run_stage(conn, run_id, "acquisition")

        stages = run_stages.read_run_stages(conn, run_id)
        assert len(stages) == 1
        assert stages[0].status == "running"
        assert stages[0].attempt == 2


class TestIntegrationScenarios:
    """Integration tests spanning multiple functions."""

    def test_full_run_lifecycle_all_stages_succeed(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """Full lifecycle: begin -> finish all stages with success."""
        for stage in ["acquisition", "enrichment", "analysis"]:
            attempt = run_stages.begin_run_stage(conn, run_id, stage)
            assert attempt == 1
            run_stages.finish_run_stage(conn, run_id, stage, "succeeded")

        stages = run_stages.read_run_stages(conn, run_id)
        assert len(stages) == 3
        assert all(s.status == "succeeded" for s in stages)

    def test_acquisition_failed_retry_then_succeed(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """Acquisition fails, retry, succeed; then proceed to enrichment."""
        # First acquisition attempt: failed
        run_stages.begin_run_stage(conn, run_id, "acquisition")
        run_stages.finish_run_stage(
            conn,
            run_id,
            "acquisition",
            "failed",
            error_message="Connection timeout",
        )

        # Retry acquisition
        attempt2 = run_stages.begin_run_stage(conn, run_id, "acquisition")
        assert attempt2 == 2
        run_stages.finish_run_stage(conn, run_id, "acquisition", "succeeded")

        # Begin enrichment
        run_stages.begin_run_stage(conn, run_id, "enrichment")

        stages = run_stages.read_run_stages(conn, run_id)
        assert len(stages) == 2
        assert stages[0].stage == "acquisition"
        assert stages[0].status == "succeeded"
        assert stages[0].attempt == 2
        assert stages[1].stage == "enrichment"
        assert stages[1].status == "running"

    def test_partial_run_resume_after_cancellation(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """Run cancelled mid-enrichment, then resumed from enrichment (ADR-014)."""
        # Acquisition succeeded
        run_stages.begin_run_stage(conn, run_id, "acquisition")
        run_stages.finish_run_stage(conn, run_id, "acquisition", "succeeded")

        # Enrichment started, then cancelled
        run_stages.begin_run_stage(conn, run_id, "enrichment")
        run_stages.finish_run_stage(
            conn,
            run_id,
            "enrichment",
            "cancelled",
            error_message="User cancelled",
        )

        # Resume: restart enrichment
        attempt2 = run_stages.begin_run_stage(conn, run_id, "enrichment")
        assert attempt2 == 2

        stages = run_stages.read_run_stages(conn, run_id)
        enrichment = [s for s in stages if s.stage == "enrichment"][0]
        assert enrichment.status == "running"
        assert enrichment.attempt == 2
        assert enrichment.error_message is None  # Cleared on re-begin

    def test_acquisition_run_multiple_times(
        self, conn: sqlite3.Connection, run_id: str
    ):
        """Acquisition can be re-run multiple times as per ADR-009."""
        attempts_to_succeed = 3

        for i in range(attempts_to_succeed - 1):
            attempt = run_stages.begin_run_stage(conn, run_id, "acquisition")
            assert attempt == i + 1
            run_stages.finish_run_stage(
                conn,
                run_id,
                "acquisition",
                "failed",
                error_message=f"Retry {i + 1}",
            )

        # Final successful attempt
        attempt = run_stages.begin_run_stage(conn, run_id, "acquisition")
        assert attempt == attempts_to_succeed
        run_stages.finish_run_stage(conn, run_id, "acquisition", "succeeded")

        stages = run_stages.read_run_stages(conn, run_id)
        assert stages[0].attempt == attempts_to_succeed
        assert stages[0].status == "succeeded"
