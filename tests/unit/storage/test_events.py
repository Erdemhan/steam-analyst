"""
Unit tests for storage.events module (append_run_event and read_run_events).

Tests cover all preconditions, postconditions, and edge cases specified in
the function specs, using real SQLite databases with schema initialization.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from steam_analyst.storage import connection, events, runs, schema
from steam_analyst.storage.types import RunEvent, StorageError


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Create and initialize a temporary SQLite database."""
    db_path = tmp_path / "test.db"
    conn = connection.get_connection(db_path)
    try:
        schema.initialize_schema(conn)
    finally:
        conn.close()
    return db_path


@pytest.fixture
def conn(tmp_db: Path) -> sqlite3.Connection:
    """Open a connection to the temporary database."""
    return connection.get_connection(tmp_db)


@pytest.fixture
def run_id(conn: sqlite3.Connection) -> str:
    """Create a test run and return its run_id."""
    rid = runs.create_run(
        conn,
        config={"test": True},
        parameters_version="v1.0",
        trigger_type="manual",
    )
    return rid


class TestAppendRunEvent:
    """Tests for append_run_event."""

    def test_append_and_read_back(self, conn: sqlite3.Connection, run_id: str) -> None:
        """An appended event is immediately visible via read_run_events."""
        # Append an event
        event_id = events.append_run_event(
            conn,
            run_id,
            stage="acquisition",
            level="info",
            message="starting",
            progress=0.0,
        )

        # Verify event_id is a positive integer
        assert isinstance(event_id, int)
        assert event_id > 0

        # Read it back
        result = events.read_run_events(conn, run_id)
        assert len(result) == 1
        assert result[0].event_id == event_id
        assert result[0].run_id == run_id
        assert result[0].stage == "acquisition"
        assert result[0].level == "info"
        assert result[0].message == "starting"
        assert result[0].progress == 0.0
        assert isinstance(result[0].ts, datetime)

    def test_invalid_level_raises(self, conn: sqlite3.Connection, run_id: str) -> None:
        """level='verbose' raises StorageError."""
        with pytest.raises(StorageError, match="level must be one of"):
            events.append_run_event(
                conn,
                run_id,
                stage="acquisition",
                level="verbose",
                message="test",
            )

    def test_progress_out_of_range_raises(
        self, conn: sqlite3.Connection, run_id: str
    ) -> None:
        """progress=1.5 raises StorageError."""
        with pytest.raises(StorageError, match="progress must be None or a float in"):
            events.append_run_event(
                conn,
                run_id,
                stage="acquisition",
                level="info",
                message="test",
                progress=1.5,
            )

    def test_unknown_run_id_raises(self, conn: sqlite3.Connection) -> None:
        """Appending to a nonexistent run_id raises StorageError."""
        with pytest.raises(StorageError, match="does not exist"):
            events.append_run_event(
                conn,
                "does-not-exist",
                stage="acquisition",
                level="info",
                message="test",
            )

    def test_progress_negative_raises(self, conn: sqlite3.Connection, run_id: str) -> None:
        """progress=-0.1 raises StorageError."""
        with pytest.raises(StorageError, match="progress must be None or a float in"):
            events.append_run_event(
                conn,
                run_id,
                stage="acquisition",
                level="info",
                message="test",
                progress=-0.1,
            )

    def test_progress_none_accepted(self, conn: sqlite3.Connection, run_id: str) -> None:
        """progress=None is accepted."""
        event_id = events.append_run_event(
            conn,
            run_id,
            stage="acquisition",
            level="info",
            message="test",
            progress=None,
        )
        result = events.read_run_events(conn, run_id)
        assert len(result) == 1
        assert result[0].progress is None

    def test_progress_boundary_0(self, conn: sqlite3.Connection, run_id: str) -> None:
        """progress=0.0 is accepted."""
        event_id = events.append_run_event(
            conn,
            run_id,
            stage="acquisition",
            level="info",
            message="test",
            progress=0.0,
        )
        result = events.read_run_events(conn, run_id)
        assert result[0].progress == 0.0

    def test_progress_boundary_1(self, conn: sqlite3.Connection, run_id: str) -> None:
        """progress=1.0 is accepted."""
        event_id = events.append_run_event(
            conn,
            run_id,
            stage="acquisition",
            level="info",
            message="test",
            progress=1.0,
        )
        result = events.read_run_events(conn, run_id)
        assert result[0].progress == 1.0

    def test_empty_message_accepted(self, conn: sqlite3.Connection, run_id: str) -> None:
        """Empty message is accepted -- storage does not enforce non-empty messages."""
        event_id = events.append_run_event(
            conn,
            run_id,
            stage="acquisition",
            level="info",
            message="",
        )
        result = events.read_run_events(conn, run_id)
        assert len(result) == 1
        assert result[0].message == ""

    def test_event_id_monotonically_increasing(
        self, conn: sqlite3.Connection, run_id: str
    ) -> None:
        """Event IDs are strictly increasing."""
        id1 = events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="first"
        )
        id2 = events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="second"
        )
        id3 = events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="third"
        )
        assert id1 < id2 < id3

    def test_all_valid_levels(self, conn: sqlite3.Connection, run_id: str) -> None:
        """All valid levels are accepted: debug, info, warning, error."""
        for level in ["debug", "info", "warning", "error"]:
            event_id = events.append_run_event(
                conn, run_id, stage="acquisition", level=level, message=f"test {level}"
            )
            assert event_id > 0

    def test_cross_thread_use_raises(
        self, tmp_db: Path
    ) -> None:
        """Cross-thread connection use raises StorageError."""
        import threading

        conn = connection.get_connection(tmp_db)
        run_id_val = runs.create_run(
            conn,
            config={"test": True},
            parameters_version="v1.0",
        )
        conn.close()

        # Try to use the connection from a different thread
        error_holder = []

        def thread_func() -> None:
            try:
                events.append_run_event(
                    conn,
                    run_id_val,
                    stage="acquisition",
                    level="info",
                    message="test",
                )
            except StorageError as e:
                error_holder.append(e)

        thread = threading.Thread(target=thread_func)
        thread.start()
        thread.join()

        assert len(error_holder) == 1
        assert "cross-thread" in str(error_holder[0]).lower()


class TestReadRunEvents:
    """Tests for read_run_events."""

    def test_read_full_history(self, conn: sqlite3.Connection, run_id: str) -> None:
        """since_event_id=0 returns all events for the run in insertion order."""
        # Append multiple events
        events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="first"
        )
        events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="second"
        )
        events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="third"
        )

        # Read all
        result = events.read_run_events(conn, run_id, since_event_id=0)
        assert len(result) == 3
        assert result[0].message == "first"
        assert result[1].message == "second"
        assert result[2].message == "third"
        # Verify ascending order by event_id
        assert result[0].event_id < result[1].event_id < result[2].event_id

    def test_read_since_last_seen(self, conn: sqlite3.Connection, run_id: str) -> None:
        """Polling with since_event_id equal to the last event's id returns only new events."""
        # Append initial events
        id1 = events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="first"
        )
        id2 = events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="second"
        )

        # Read since id2 (should return nothing)
        result = events.read_run_events(conn, run_id, since_event_id=id2)
        assert len(result) == 0

        # Append new events
        id3 = events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="third"
        )
        id4 = events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="fourth"
        )

        # Read since id2 (should return id3 and id4)
        result = events.read_run_events(conn, run_id, since_event_id=id2)
        assert len(result) == 2
        assert result[0].event_id == id3
        assert result[1].event_id == id4
        assert result[0].message == "third"
        assert result[1].message == "fourth"

    def test_unknown_run_returns_empty_list(
        self, conn: sqlite3.Connection
    ) -> None:
        """An unknown run_id returns []."""
        result = events.read_run_events(conn, "does-not-exist")
        assert result == []

    def test_run_with_no_events_returns_empty_list(
        self, conn: sqlite3.Connection, run_id: str
    ) -> None:
        """A run with no events returns []."""
        result = events.read_run_events(conn, run_id)
        assert result == []

    def test_since_event_id_greater_than_max(
        self, conn: sqlite3.Connection, run_id: str
    ) -> None:
        """since_event_id greater than the highest existing event_id returns an empty list."""
        events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="first"
        )
        events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="second"
        )

        # Read since a nonexistent high event_id
        result = events.read_run_events(conn, run_id, since_event_id=9999)
        assert len(result) == 0

    def test_events_ordered_ascending(self, conn: sqlite3.Connection, run_id: str) -> None:
        """Returned events are strictly ordered by event_id ascending."""
        for i in range(5):
            events.append_run_event(
                conn,
                run_id,
                stage="acquisition",
                level="info",
                message=f"event_{i}",
            )

        result = events.read_run_events(conn, run_id)
        for i in range(len(result) - 1):
            assert result[i].event_id < result[i + 1].event_id

    def test_event_id_strictly_greater_than_since(
        self, conn: sqlite3.Connection, run_id: str
    ) -> None:
        """Every returned event has event_id > since_event_id."""
        id1 = events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="first"
        )
        id2 = events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="second"
        )
        id3 = events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="third"
        )

        result = events.read_run_events(conn, run_id, since_event_id=id1)
        assert all(e.event_id > id1 for e in result)
        assert len(result) == 2  # id2 and id3

    def test_multiple_runs_isolated(
        self, conn: sqlite3.Connection
    ) -> None:
        """Events from different runs are isolated."""
        run1 = runs.create_run(
            conn, config={"test": True}, parameters_version="v1.0"
        )
        run2 = runs.create_run(
            conn, config={"test": True}, parameters_version="v1.0"
        )

        events.append_run_event(
            conn, run1, stage="acquisition", level="info", message="run1_event"
        )
        events.append_run_event(
            conn, run2, stage="acquisition", level="info", message="run2_event"
        )

        # Read run1 events
        result1 = events.read_run_events(conn, run1)
        assert len(result1) == 1
        assert result1[0].message == "run1_event"

        # Read run2 events
        result2 = events.read_run_events(conn, run2)
        assert len(result2) == 1
        assert result2[0].message == "run2_event"

    def test_runstage_preserved_in_events(self, conn: sqlite3.Connection, run_id: str) -> None:
        """Stage names from different pipeline stages are preserved."""
        for stage in ["acquisition", "enrichment", "analysis"]:
            events.append_run_event(
                conn, run_id, stage=stage, level="info", message=f"{stage}_event"
            )

        result = events.read_run_events(conn, run_id)
        assert len(result) == 3
        assert result[0].stage == "acquisition"
        assert result[1].stage == "enrichment"
        assert result[2].stage == "analysis"

    def test_all_levels_preserved(self, conn: sqlite3.Connection, run_id: str) -> None:
        """All log levels are preserved when read back."""
        for level in ["debug", "info", "warning", "error"]:
            events.append_run_event(
                conn, run_id, stage="acquisition", level=level, message=f"{level}_msg"
            )

        result = events.read_run_events(conn, run_id)
        assert len(result) == 4
        assert result[0].level == "debug"
        assert result[1].level == "info"
        assert result[2].level == "warning"
        assert result[3].level == "error"

    def test_timestamp_precision(self, conn: sqlite3.Connection, run_id: str) -> None:
        """Timestamps are preserved as datetime objects with ISO-8601 precision."""
        before = datetime.utcnow()
        event_id = events.append_run_event(
            conn, run_id, stage="acquisition", level="info", message="test"
        )
        after = datetime.utcnow()

        result = events.read_run_events(conn, run_id)
        assert len(result) == 1
        assert isinstance(result[0].ts, datetime)
        # Timestamp should be within reasonable bounds
        assert before <= result[0].ts <= after
