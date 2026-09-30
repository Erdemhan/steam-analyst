"""Unit tests for orchestration.events module.

Tests the make_event_sink factory function and its throttling behavior.
"""

import logging
import sqlite3
import time
from unittest.mock import MagicMock, patch

import pytest

from steam_analyst.orchestration.events import (
    INFO_THROTTLE_INTERVAL_SECONDS,
    make_event_sink,
)
from steam_analyst.storage.events import append_run_event
from steam_analyst.storage.types import StorageError


@pytest.fixture
def test_db_with_run(tmp_path):
    """Create an in-memory SQLite database with runs and run_events tables."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Create the minimal schema needed for tests.
    conn.execute(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            parent_run_id TEXT,
            config_json TEXT NOT NULL,
            parameters_version TEXT NOT NULL,
            code_version TEXT,
            error_message TEXT,
            notes TEXT
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE run_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            stage TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            progress REAL,
            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        )
    """
    )

    # Insert a test run.
    conn.execute(
        """
        INSERT INTO runs (
            run_id, started_at, status, trigger_type, config_json, parameters_version
        ) VALUES (?, ?, ?, ?, ?, ?)
    """,
        (
            "test_run",
            "2026-09-22T00:00:00",
            "running",
            "manual",
            "{}",
            "v1.0",
        ),
    )
    conn.commit()

    yield conn, "test_run"

    conn.close()


class TestMakeEventSinkBasics:
    """Test basic functionality and protocol compliance."""

    def test_make_event_sink_returns_callable(self, test_db_with_run):
        """Test that make_event_sink returns a callable."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)
        assert callable(sink)

    def test_sink_matches_event_sink_protocol(self, test_db_with_run):
        """Test that the sink accepts keyword arguments matching EventSink protocol."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        # Should accept all EventSink parameters as keyword arguments.
        sink(
            stage="acquisition",
            level="info",
            message="Test message",
            progress=0.5,
        )

        # Verify the event was persisted.
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM run_events WHERE run_id = ?",
            (run_id,),
        )
        assert cursor.fetchone()["count"] >= 1

    def test_sink_with_progress_none(self, test_db_with_run):
        """Test that the sink accepts progress=None."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        # progress is optional per EventSink protocol.
        sink(
            stage="enrichment",
            level="info",
            message="No progress",
        )

        cursor = conn.cursor()
        cursor.execute(
            "SELECT progress FROM run_events WHERE run_id = ? ORDER BY event_id DESC LIMIT 1",
            (run_id,),
        )
        row = cursor.fetchone()
        assert row["progress"] is None


class TestErrorAndWarningNeverThrottled:
    """Test that error and warning level events bypass the throttle."""

    def test_error_level_never_throttled(self, test_db_with_run):
        """A burst of 100 'error'-level calls all result in 100 persisted run_events rows."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        # Call the sink 100 times with error level.
        for i in range(100):
            sink(
                stage="acquisition",
                level="error",
                message=f"Error message {i}",
            )

        # All 100 error events should be persisted.
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM run_events WHERE run_id = ? AND level = 'error'",
            (run_id,),
        )
        count = cursor.fetchone()["count"]
        assert count == 100, f"Expected 100 error events, got {count}"

    def test_warning_level_never_throttled(self, test_db_with_run):
        """A burst of 100 'warning'-level calls all result in 100 persisted run_events rows."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        # Call the sink 100 times with warning level.
        for i in range(100):
            sink(
                stage="enrichment",
                level="warning",
                message=f"Warning message {i}",
            )

        # All 100 warning events should be persisted.
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM run_events WHERE run_id = ? AND level = 'warning'",
            (run_id,),
        )
        count = cursor.fetchone()["count"]
        assert count == 100, f"Expected 100 warning events, got {count}"

    def test_error_not_affected_by_info_throttle(self, test_db_with_run):
        """Error events are written immediately regardless of throttle state."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        # First, send an info event to "warm up" the throttle.
        sink(
            stage="acquisition",
            level="info",
            message="First info event",
        )

        # Now immediately send an error (within throttle window).
        sink(
            stage="acquisition",
            level="error",
            message="Error message",
        )

        # Both should be persisted.
        cursor = conn.cursor()
        cursor.execute(
            "SELECT level FROM run_events WHERE run_id = ? ORDER BY event_id ASC",
            (run_id,),
        )
        levels = [row["level"] for row in cursor.fetchall()]
        assert "info" in levels
        assert "error" in levels


class TestInfoLevelThrottling:
    """Test throttling behavior for 'info'-level events."""

    def test_info_level_throttled_under_burst(self, test_db_with_run):
        """A burst of 1000 'info'-level calls results in fewer than 1000 persisted rows."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        # Rapidly call sink with info level (should be throttled).
        for i in range(1000):
            sink(
                stage="acquisition",
                level="info",
                message=f"Info message {i}",
            )

        # Count persisted info events.
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM run_events WHERE run_id = ? AND level = 'info'",
            (run_id,),
        )
        count = cursor.fetchone()["count"]

        # With throttling at ~2 seconds per event and 1000 rapid calls,
        # we should see far fewer than 1000 rows (likely 1-2 if calls are fast).
        assert count < 1000, f"Expected fewer than 1000 info events, got {count}"

    def test_info_events_allowed_after_throttle_window(self, test_db_with_run):
        """Info events are written again after the throttle window expires."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        # Send first info event (should persist).
        sink(
            stage="acquisition",
            level="info",
            message="First info event",
        )

        # Immediately send another info event (should be throttled).
        sink(
            stage="acquisition",
            level="info",
            message="Second info event (throttled)",
        )

        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM run_events WHERE run_id = ? AND level = 'info'",
            (run_id,),
        )
        count_before = cursor.fetchone()["count"]
        assert count_before == 1

        # Wait for throttle window to expire.
        time.sleep(INFO_THROTTLE_INTERVAL_SECONDS + 0.1)

        # Now send another info event (should persist).
        sink(
            stage="acquisition",
            level="info",
            message="Third info event (not throttled)",
        )

        cursor.execute(
            "SELECT COUNT(*) as count FROM run_events WHERE run_id = ? AND level = 'info'",
            (run_id,),
        )
        count_after = cursor.fetchone()["count"]
        assert count_after == 2, f"Expected 2 info events, got {count_after}"


class TestSinkNeverRaises:
    """Test that the sink never raises, even on internal failures."""

    def test_sink_never_raises_on_storage_failure(self, test_db_with_run):
        """With append_run_event stubbed to raise, calling the sink does not propagate."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        # Mock append_run_event to raise a StorageError.
        with patch("steam_analyst.orchestration.events.append_run_event") as mock_append:
            mock_append.side_effect = StorageError("Simulated storage failure")

            # The sink call should NOT raise.
            sink(
                stage="acquisition",
                level="error",
                message="This should not propagate",
            )

            # Verify the error was logged (indirectly by checking that mock was called).
            mock_append.assert_called_once()

    def test_sink_never_raises_on_generic_exception(self, test_db_with_run):
        """Generic exceptions from append_run_event are also caught and logged."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        with patch("steam_analyst.orchestration.events.append_run_event") as mock_append:
            mock_append.side_effect = RuntimeError("Unexpected error")

            # The sink call should NOT raise.
            sink(
                stage="enrichment",
                level="warning",
                message="Generic exception test",
            )

            mock_append.assert_called_once()

    def test_sink_exception_logged_to_logger(self, test_db_with_run, caplog):
        """Exceptions from append_run_event are logged via the logger."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        with patch("steam_analyst.orchestration.events.append_run_event") as mock_append:
            mock_append.side_effect = StorageError("Test error")

            with caplog.at_level(logging.ERROR):
                sink(
                    stage="analysis",
                    level="info",
                    message="Test message",
                )

            # Check that an error was logged.
            assert any("Failed to append run event" in record.message for record in caplog.records)

    def test_sink_never_raises_on_closed_database(self, test_db_with_run, caplog):
        """If the database connection is unexpectedly closed, the sink catches it and logs."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        # Close the connection to simulate unexpected closure.
        conn.close()

        # The sink call should NOT raise, despite the closed connection.
        with caplog.at_level(logging.ERROR):
            sink(
                stage="acquisition",
                level="error",
                message="After closed connection",
            )

        # Verify the error was logged.
        assert any("Failed to append run event" in record.message for record in caplog.records)


class TestMixedEventLevels:
    """Test behavior with mixed event levels."""

    def test_error_warning_interleaved_with_info(self, test_db_with_run):
        """Error/warning events are written immediately even among throttled info events."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        # Send info event (persists, sets throttle clock).
        sink(
            stage="acquisition",
            level="info",
            message="Info 1",
        )

        # Send many info events rapidly (should be throttled).
        for i in range(100):
            sink(
                stage="acquisition",
                level="info",
                message=f"Info {i+2}",
            )

        # Send error event (should persist even though throttle is active).
        sink(
            stage="acquisition",
            level="error",
            message="Error in the middle",
        )

        # Send more info events (should continue to be throttled).
        for i in range(100):
            sink(
                stage="acquisition",
                level="info",
                message=f"Info {i+102}",
            )

        # Verify: info events should be few, error should be present.
        cursor = conn.cursor()
        cursor.execute(
            "SELECT level, COUNT(*) as count FROM run_events WHERE run_id = ? GROUP BY level",
            (run_id,),
        )
        results = {row["level"]: row["count"] for row in cursor.fetchall()}

        info_count = results.get("info", 0)
        error_count = results.get("error", 0)

        assert info_count < 50, f"Info events should be heavily throttled, got {info_count}"
        assert error_count == 1, f"Error event should be present, got {error_count}"

    def test_throttle_independent_per_sink_instance(self, test_db_with_run):
        """Each sink instance has its own throttle state."""
        conn, run_id = test_db_with_run

        # Create two separate sink instances.
        sink1 = make_event_sink(conn, run_id)
        sink2 = make_event_sink(conn, run_id)

        # Send info event via sink1 (persists).
        sink1(
            stage="acquisition",
            level="info",
            message="Sink1 info",
        )

        # Send info event via sink2 immediately (should persist, independent throttle).
        sink2(
            stage="enrichment",
            level="info",
            message="Sink2 info",
        )

        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM run_events WHERE run_id = ? AND level = 'info'",
            (run_id,),
        )
        count = cursor.fetchone()["count"]

        # Both info events should have persisted (independent throttles).
        assert count == 2, f"Expected 2 info events (independent throttles), got {count}"


class TestEdgeCases:
    """Test edge cases from the spec."""

    def test_progress_not_monotonic(self, test_db_with_run):
        """Progress values are not required to be monotonic."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        # Send events with non-monotonic progress.
        sink(
            stage="acquisition",
            level="info",
            message="Progress 0.5",
            progress=0.5,
        )

        time.sleep(INFO_THROTTLE_INTERVAL_SECONDS + 0.1)

        sink(
            stage="acquisition",
            level="info",
            message="Progress 0.2",
            progress=0.2,
        )

        # Should not raise and both should be persisted (after throttle window).
        cursor = conn.cursor()
        cursor.execute(
            "SELECT progress FROM run_events WHERE run_id = ? ORDER BY event_id ASC",
            (run_id,),
        )
        progresses = [row["progress"] for row in cursor.fetchall()]
        assert 0.5 in progresses
        assert 0.2 in progresses

    def test_progress_transitions_from_value_to_none(self, test_db_with_run):
        """Progress can transition from a value to None."""
        conn, run_id = test_db_with_run
        sink = make_event_sink(conn, run_id)

        sink(
            stage="acquisition",
            level="info",
            message="With progress",
            progress=0.75,
        )

        time.sleep(INFO_THROTTLE_INTERVAL_SECONDS + 0.1)

        sink(
            stage="acquisition",
            level="info",
            message="Without progress",
            progress=None,
        )

        cursor = conn.cursor()
        cursor.execute(
            "SELECT progress FROM run_events WHERE run_id = ? ORDER BY event_id ASC",
            (run_id,),
        )
        rows = cursor.fetchall()
        progresses = [row["progress"] for row in rows]

        assert 0.75 in progresses
        assert None in progresses
