"""
Append-only progress and diagnostic event logging for runs.

This module provides event recording and retrieval for pipeline progress tracking
and status updates. Events are written to disk immediately (no batching/deferral)
per ADR-016, so concurrent readers can observe them via WAL snapshots.
"""

import sqlite3
from datetime import datetime

from .connection import _check_same_thread
from .types import RunEvent, StorageError


def append_run_event(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    stage: str,
    level: str,
    message: str,
    progress: float | None = None,
) -> int:
    """Append one progress/log event.

    Args:
        conn: An open connection (the pipeline's own connection, per ADR-006's
            'one connection per thread' rule).
        run_id: The run this event belongs to.
        stage: Pipeline stage name, e.g. 'acquisition', 'enrichment', 'analysis'.
        level: One of 'debug', 'info', 'warning', 'error'.
        message: Human-readable, English-language event text.
        progress: Fractional completion in [0.0, 1.0], or None.

    Returns:
        The generated event_id (monotonically increasing per database).

    Raises:
        StorageError: If run_id does not exist, level is invalid, or progress
            is outside [0.0, 1.0].

    Note:
        The row is committed to disk before the function returns (no batching/deferred
        commit), so a concurrent reader immediately sees it under WAL. Event IDs are
        strictly increasing across the whole database, not just per run.
    """
    _check_same_thread(conn)

    # Validate level
    valid_levels = {"debug", "info", "warning", "error"}
    if level not in valid_levels:
        raise StorageError(
            f"level must be one of {valid_levels}, got '{level}'"
        )

    # Validate progress
    if progress is not None:
        if not isinstance(progress, (int, float)) or progress < 0.0 or progress > 1.0:
            raise StorageError(
                f"progress must be None or a float in [0.0, 1.0], got {progress}"
            )

    # Verify run_id exists
    cursor = conn.cursor()
    cursor.execute("SELECT run_id FROM runs WHERE run_id = ?", (run_id,))
    if cursor.fetchone() is None:
        raise StorageError(f"Run {run_id} does not exist")

    # Generate current timestamp as ISO-8601 string
    ts = datetime.utcnow().isoformat()

    # Insert the event
    try:
        cursor.execute(
            """
            INSERT INTO run_events (
                run_id, ts, stage, level, message, progress
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, ts, stage, level, message, progress),
        )
        conn.commit()

        # Retrieve the generated event_id
        event_id = cursor.lastrowid
        return event_id
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise StorageError(f"Failed to append event: {e}") from e
    except sqlite3.Error as e:
        conn.rollback()
        raise StorageError(f"Database error during event append: {e}") from e


def read_run_events(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    since_event_id: int = 0,
) -> list[RunEvent]:
    """Read events for a run.

    Args:
        conn: An open connection.
        run_id: The run to read events for.
        since_event_id: Only events with event_id strictly greater than this are
            returned; 0 returns the full history.

    Returns:
        A list of RunEvent ordered by event_id ascending (oldest first, matching
        how a log/progress feed is naturally consumed). Returns an empty list for
        a run_id with no events yet or an unknown run_id.

    Note:
        Returned events are strictly ordered by event_id ascending and every
        returned event has event_id > since_event_id.
    """
    _check_same_thread(conn)

    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT event_id, run_id, ts, stage, level, message, progress
            FROM run_events
            WHERE run_id = ? AND event_id > ?
            ORDER BY event_id ASC
            """,
            (run_id, since_event_id),
        )
        rows = cursor.fetchall()
    except sqlite3.Error as e:
        raise StorageError(f"Database error reading events: {e}") from e

    # Convert rows to RunEvent objects
    events = []
    for row in rows:
        # Parse timestamp
        try:
            ts = _parse_iso_timestamp(row["ts"])
        except (ValueError, TypeError) as e:
            raise StorageError(f"Corrupted timestamp in event {row['event_id']}: {e}") from e

        event = RunEvent(
            event_id=row["event_id"],
            run_id=row["run_id"],
            ts=ts,
            stage=row["stage"],
            level=row["level"],
            message=row["message"],
            progress=row["progress"],
        )
        events.append(event)

    return events


def _parse_iso_timestamp(timestamp_str: str) -> datetime:
    """Parse an ISO-8601 timestamp string, handling the 'Z' suffix.

    Args:
        timestamp_str: An ISO-8601 timestamp string, potentially with 'Z' suffix.

    Returns:
        A datetime object.

    Raises:
        ValueError: If the timestamp cannot be parsed.
    """
    # Handle 'Z' suffix by converting to '+00:00'
    if timestamp_str.endswith('Z'):
        timestamp_str = timestamp_str[:-1] + '+00:00'
    return datetime.fromisoformat(timestamp_str)
