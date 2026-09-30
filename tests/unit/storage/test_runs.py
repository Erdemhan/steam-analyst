"""
Unit tests for storage.runs module (create_run, get_run, list_runs, delete_run, update_run_status).
"""

import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from steam_analyst.storage.connection import get_connection
from steam_analyst.storage.runs import (
    create_run,
    delete_run,
    get_run,
    list_runs,
    update_run_status,
)
from steam_analyst.storage.schema import initialize_schema
from steam_analyst.storage.types import RunRecord, StorageError


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


class TestCreateRun:
    """Tests for create_run function."""

    def test_create_run_returns_sortable_ids(self, conn):
        """Two sequential calls produce distinct run_ids."""
        config = {"key": "value"}
        params_version = "abc123"

        run_id_1 = create_run(
            conn,
            config=config,
            parameters_version=params_version,
        )
        # Add a small delay to ensure different millisecond timestamps
        time.sleep(0.01)
        run_id_2 = create_run(
            conn,
            config=config,
            parameters_version=params_version,
        )

        # With millisecond precision and a small delay, these should be sortable
        assert run_id_1 < run_id_2, "Second run_id should sort after first (lexicographically)"
        # Ensure they're different
        assert run_id_1 != run_id_2

    def test_create_run_roundtrips_through_get_run(self, conn):
        """All fields passed to create_run are readable back unchanged via get_run."""
        config = {"key": "value", "nested": {"inner": 42}}
        params_version = "abc123"
        trigger_type = "manual"
        code_version = "v1.0"
        notes = "Test notes"

        run_id = create_run(
            conn,
            config=config,
            parameters_version=params_version,
            trigger_type=trigger_type,
            code_version=code_version,
            notes=notes,
        )

        record = get_run(conn, run_id)
        assert record is not None
        assert record.run_id == run_id
        assert record.config == config
        assert record.parameters_version == params_version
        assert record.status == "pending"
        assert record.trigger_type == trigger_type
        assert record.code_version == code_version
        assert record.notes == notes
        assert record.finished_at is None
        assert record.error_message is None
        assert record.parent_run_id is None

    def test_create_run_with_parent_run_id(self, conn):
        """create_run with a valid parent_run_id succeeds and is stored."""
        config = {"key": "value"}
        params_version = "abc123"

        parent_id = create_run(conn, config=config, parameters_version=params_version)
        child_id = create_run(
            conn,
            config=config,
            parameters_version=params_version,
            parent_run_id=parent_id,
        )

        record = get_run(conn, child_id)
        assert record is not None
        assert record.parent_run_id == parent_id

    def test_invalid_trigger_type_raises(self, conn):
        """trigger_type='cron' raises StorageError."""
        with pytest.raises(StorageError) as exc_info:
            create_run(
                conn,
                config={"key": "value"},
                parameters_version="abc123",
                trigger_type="cron",
            )
        assert "trigger_type" in str(exc_info.value).lower()

    def test_unknown_parent_run_id_raises(self, conn):
        """A nonexistent parent_run_id raises StorageError."""
        with pytest.raises(StorageError):
            create_run(
                conn,
                config={"key": "value"},
                parameters_version="abc123",
                parent_run_id="does-not-exist",
            )

    def test_non_json_serializable_config_raises(self, conn):
        """config containing a non-JSON-serializable value raises StorageError."""

        class CustomObject:
            pass

        with pytest.raises(StorageError) as exc_info:
            create_run(
                conn,
                config={"bad": CustomObject()},
                parameters_version="abc123",
            )
        assert "json" in str(exc_info.value).lower()

    def test_create_run_with_scheduled_trigger_type(self, conn):
        """trigger_type='scheduled' is accepted and stored."""
        run_id = create_run(
            conn,
            config={"key": "value"},
            parameters_version="abc123",
            trigger_type="scheduled",
        )
        record = get_run(conn, run_id)
        assert record.trigger_type == "scheduled"

    def test_run_id_format(self, conn):
        """Generated run_id has the expected format: YYYYMMDDTHHMMSSFFFZ-XXXXXX."""
        run_id = create_run(
            conn,
            config={},
            parameters_version="abc123",
        )
        # Format: YYYYMMDDTHHMMSSFFFZ-XXXXXX (19 chars + dash + 6 hex chars)
        parts = run_id.split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 19  # YYYYMMDDTHHMMSSFFFZ (with FFF = milliseconds)
        assert len(parts[1]) == 6   # 6 hex chars
        assert parts[0].endswith("Z")


class TestGetRun:
    """Tests for get_run function."""

    def test_get_existing_run(self, conn):
        """A run created via create_run is retrievable with matching fields."""
        config = {"key": "value"}
        params_version = "abc123"

        run_id = create_run(
            conn,
            config=config,
            parameters_version=params_version,
        )

        record = get_run(conn, run_id)
        assert record is not None
        assert record.run_id == run_id
        assert record.config == config
        assert record.parameters_version == params_version
        assert record.status == "pending"

    def test_get_unknown_run_returns_none(self, conn):
        """An unknown run_id returns None, not an exception."""
        result = get_run(conn, "does-not-exist")
        assert result is None

    def test_get_run_deserializes_config(self, conn):
        """config_json is deserialized into a Python dict."""
        config = {"nested": {"list": [1, 2, 3], "string": "value"}}
        run_id = create_run(
            conn,
            config=config,
            parameters_version="abc123",
        )

        record = get_run(conn, run_id)
        assert record is not None
        assert isinstance(record.config, dict)
        assert record.config == config

    def test_get_run_with_finished_run(self, conn):
        """get_run retrieves finished_at and error_message if set."""
        run_id = create_run(
            conn,
            config={},
            parameters_version="abc123",
        )

        finished_at = "2026-09-20T12:00:00"
        update_run_status(
            conn,
            run_id,
            "succeeded",
            finished_at=finished_at,
        )

        record = get_run(conn, run_id)
        assert record is not None
        assert record.status == "succeeded"
        assert record.finished_at is not None

    def test_get_run_with_error_message(self, conn):
        """get_run retrieves error_message when set."""
        run_id = create_run(
            conn,
            config={},
            parameters_version="abc123",
        )

        error_msg = "Something went wrong"
        update_run_status(
            conn,
            run_id,
            "failed",
            finished_at="2026-09-20T12:00:00",
            error_message=error_msg,
        )

        record = get_run(conn, run_id)
        assert record is not None
        assert record.error_message == error_msg


class TestListRuns:
    """Tests for list_runs function."""

    def test_list_runs_newest_first(self, conn):
        """Runs are returned sorted by started_at descending."""
        config = {"key": "value"}
        params_version = "abc123"

        run_ids = []
        for i in range(3):
            run_id = create_run(conn, config=config, parameters_version=params_version)
            run_ids.append(run_id)
            time.sleep(0.01)  # Ensure different timestamps

        df = list_runs(conn, limit=50, offset=0)
        assert len(df) == 3

        # All runs should be present
        result_ids = set(df["run_id"])
        assert result_ids == set(run_ids)

        # Verify sorting is by started_at DESC (newest first)
        # With delays, started_at should be strictly increasing, so newest should be last created
        result_ids_ordered = list(df["run_id"])
        assert result_ids_ordered[0] == run_ids[2]  # Last created
        assert result_ids_ordered[1] == run_ids[1]  # Middle created
        assert result_ids_ordered[2] == run_ids[0]  # First created

    def test_list_runs_empty_database(self, conn):
        """No runs -> empty DataFrame with expected columns."""
        df = list_runs(conn)
        assert len(df) == 0
        expected_cols = ["run_id", "started_at", "finished_at", "status", "trigger_type", "candidate_count"]
        assert list(df.columns) == expected_cols

    def test_list_runs_pagination(self, conn):
        """limit and offset work correctly."""
        config = {"key": "value"}
        params_version = "abc123"

        run_ids = []
        for i in range(3):
            run_id = create_run(conn, config=config, parameters_version=params_version)
            run_ids.append(run_id)
            time.sleep(0.01)

        # Get the second-newest (offset=1, limit=1)
        df = list_runs(conn, limit=1, offset=1)
        assert len(df) == 1
        assert df["run_id"].iloc[0] == run_ids[1]  # The middle created run (second newest)

    def test_list_runs_offset_beyond_total(self, conn):
        """offset beyond the total row count returns an empty DataFrame."""
        config = {"key": "value"}
        params_version = "abc123"

        create_run(conn, config=config, parameters_version=params_version)
        create_run(conn, config=config, parameters_version=params_version)

        df = list_runs(conn, limit=50, offset=100)
        assert len(df) == 0
        expected_cols = ["run_id", "started_at", "finished_at", "status", "trigger_type", "candidate_count"]
        assert list(df.columns) == expected_cols

    def test_list_runs_candidate_count_zero(self, conn):
        """A run with status='pending' and zero games_enriched rows has candidate_count=0."""
        run_id = create_run(
            conn,
            config={"key": "value"},
            parameters_version="abc123",
        )

        df = list_runs(conn)
        assert len(df) == 1
        assert df["candidate_count"].iloc[0] == 0
        assert pd.notna(df["candidate_count"].iloc[0])

    def test_list_runs_with_games_enriched(self, conn):
        """list_runs correctly counts games_enriched rows."""
        run_id = create_run(
            conn,
            config={"key": "value"},
            parameters_version="abc123",
        )

        # Insert some enriched games
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO games_enriched (run_id, appid, parameters_version) VALUES (?, ?, ?)",
            (run_id, 1, "abc123"),
        )
        cursor.execute(
            "INSERT INTO games_enriched (run_id, appid, parameters_version) VALUES (?, ?, ?)",
            (run_id, 2, "abc123"),
        )
        conn.commit()

        df = list_runs(conn)
        assert len(df) == 1
        assert df["candidate_count"].iloc[0] == 2


class TestDeleteRun:
    """Tests for delete_run function."""

    def test_delete_run_cascades_to_all_tables(self, conn):
        """A fully populated synthetic run is fully removed after delete_run."""
        run_id = create_run(
            conn,
            config={"key": "value"},
            parameters_version="abc123",
        )

        # Insert some data into child tables
        cursor = conn.cursor()

        # raw_games
        cursor.execute(
            """
            INSERT INTO raw_games
            (run_id, appid, source, fetched_at, http_status, payload_json, payload_sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, 100, "steamspy_all", "2026-09-20T12:00:00", 200, "{}", "abc123"),
        )

        # games_enriched
        cursor.execute(
            "INSERT INTO games_enriched (run_id, appid, parameters_version) VALUES (?, ?, ?)",
            (run_id, 100, "abc123"),
        )

        # game_tags
        cursor.execute(
            "INSERT INTO game_tags (run_id, appid, tag) VALUES (?, ?, ?)",
            (run_id, 100, "Indie"),
        )

        # run_events
        cursor.execute(
            "INSERT INTO run_events (run_id, ts, stage, level, message) VALUES (?, ?, ?, ?, ?)",
            (run_id, "2026-09-20T12:00:00", "acquisition", "info", "test message"),
        )

        # analysis_results
        cursor.execute(
            """
            INSERT INTO analysis_results
            (run_id, analysis_type, created_at, parameters_version, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, "opportunity_matrix", "2026-09-20T12:00:00", "abc123", "{}"),
        )

        conn.commit()

        # Verify rows were inserted
        cursor.execute("SELECT COUNT(*) FROM raw_games WHERE run_id = ?", (run_id,))
        assert cursor.fetchone()[0] == 1

        # Delete the run
        delete_run(conn, run_id)

        # Verify all cascaded deletes
        cursor.execute("SELECT COUNT(*) FROM runs WHERE run_id = ?", (run_id,))
        assert cursor.fetchone()[0] == 0

        cursor.execute("SELECT COUNT(*) FROM raw_games WHERE run_id = ?", (run_id,))
        assert cursor.fetchone()[0] == 0

        cursor.execute("SELECT COUNT(*) FROM games_enriched WHERE run_id = ?", (run_id,))
        assert cursor.fetchone()[0] == 0

        cursor.execute("SELECT COUNT(*) FROM game_tags WHERE run_id = ?", (run_id,))
        assert cursor.fetchone()[0] == 0

        cursor.execute("SELECT COUNT(*) FROM run_events WHERE run_id = ?", (run_id,))
        assert cursor.fetchone()[0] == 0

        cursor.execute("SELECT COUNT(*) FROM analysis_results WHERE run_id = ?", (run_id,))
        assert cursor.fetchone()[0] == 0

    def test_delete_unknown_run_is_noop(self, conn):
        """Deleting a nonexistent run_id does not raise."""
        # Should not raise
        delete_run(conn, "does-not-exist")
        # And should be idempotent
        delete_run(conn, "does-not-exist")

    def test_delete_run_idempotent(self, conn):
        """Calling delete_run twice on the same run is a no-op."""
        run_id = create_run(
            conn,
            config={},
            parameters_version="abc123",
        )

        delete_run(conn, run_id)
        # Second call should not raise
        delete_run(conn, run_id)

        # Verify run is gone
        result = get_run(conn, run_id)
        assert result is None


class TestUpdateRunStatus:
    """Tests for update_run_status function."""

    def test_update_to_running_then_succeeded(self, conn):
        """Two sequential updates land correctly and finished_at is set on the second."""
        run_id = create_run(
            conn,
            config={},
            parameters_version="abc123",
        )

        # First update: pending -> running
        update_run_status(conn, run_id, "running")
        record = get_run(conn, run_id)
        assert record.status == "running"
        assert record.finished_at is None

        # Second update: running -> succeeded with finished_at
        finished_at = "2026-09-20T12:00:00Z"
        update_run_status(
            conn,
            run_id,
            "succeeded",
            finished_at=finished_at,
        )
        record = get_run(conn, run_id)
        assert record.status == "succeeded"
        assert record.finished_at is not None

    def test_unknown_run_id_raises(self, conn):
        """Updating a nonexistent run_id raises StorageError."""
        with pytest.raises(StorageError) as exc_info:
            update_run_status(conn, "does-not-exist", "running")
        assert "does not exist" in str(exc_info.value).lower()

    def test_invalid_status_raises(self, conn):
        """status='paused' raises StorageError."""
        run_id = create_run(
            conn,
            config={},
            parameters_version="abc123",
        )

        with pytest.raises(StorageError) as exc_info:
            update_run_status(conn, run_id, "paused")
        assert "status" in str(exc_info.value).lower()

    def test_update_status_with_error_message(self, conn):
        """status='failed' with error_message is stored."""
        run_id = create_run(
            conn,
            config={},
            parameters_version="abc123",
        )

        error_msg = "Database connection failed"
        update_run_status(
            conn,
            run_id,
            "failed",
            finished_at="2026-09-20T12:00:00Z",
            error_message=error_msg,
        )

        record = get_run(conn, run_id)
        assert record.status == "failed"
        assert record.error_message == error_msg

    def test_update_status_all_valid_states(self, conn):
        """All five valid status values can be set."""
        run_id = create_run(
            conn,
            config={},
            parameters_version="abc123",
        )

        for status in ["pending", "running", "succeeded", "failed", "cancelled"]:
            update_run_status(conn, run_id, status)
            record = get_run(conn, run_id)
            assert record.status == status

    def test_update_cancelled_status(self, conn):
        """status='cancelled' is accepted and stored."""
        run_id = create_run(
            conn,
            config={},
            parameters_version="abc123",
        )

        update_run_status(
            conn,
            run_id,
            "cancelled",
            finished_at="2026-09-20T12:00:00Z",
        )

        record = get_run(conn, run_id)
        assert record.status == "cancelled"


class TestCrossThreadDetection:
    """Tests for cross-thread connection usage detection."""

    def test_create_run_cross_thread_raises(self, conn):
        """Using a connection across threads raises StorageError."""
        import threading

        error_holder = []

        def use_conn_in_other_thread():
            try:
                create_run(
                    conn,
                    config={},
                    parameters_version="abc123",
                )
            except StorageError as e:
                error_holder.append(e)

        thread = threading.Thread(target=use_conn_in_other_thread)
        thread.start()
        thread.join()

        assert len(error_holder) == 1
        assert "cross-thread" in str(error_holder[0]).lower()


class TestUpdateRunStatusFinishedAt:
    """finished_at is auto-populated on terminal statuses."""

    def test_terminal_status_sets_finished_at_when_omitted(self, conn):
        run_id = create_run(conn, config={}, parameters_version="v1")
        update_run_status(conn, run_id, "succeeded")
        assert get_run(conn, run_id).finished_at is not None

    def test_running_status_leaves_finished_at_none(self, conn):
        run_id = create_run(conn, config={}, parameters_version="v1")
        update_run_status(conn, run_id, "running")
        assert get_run(conn, run_id).finished_at is None
