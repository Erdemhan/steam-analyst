"""
Run lifecycle management: create, query, update status, and delete runs.

Every function that uses a connection must call _check_same_thread at its start
to reject cross-thread misuse per ADR-002.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Iterator

import pandas as pd

from .connection import _check_same_thread
from .types import RunRecord, StorageError


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


def _generate_run_id() -> str:
    """Generate a lexicographically sortable, human-readable run_id.

    Format: YYYYMMDDTHHMMSSFFFZ-XXXXXX
    - Timestamp: UTC, YYYYMMDDTHHMMSSFFFZ where FFF is microseconds (000-999)
    - Suffix: 6 random hex chars for uniqueness within the same microsecond

    Returns:
        A run_id string (e.g. '20260920T143012123Z-a1b2c3').
    """
    now_utc = datetime.utcnow()
    # Format: YYYYMMDDTHHMMSSFFFZ where FFF is milliseconds
    timestamp = now_utc.strftime("%Y%m%dT%H%M%S")
    # Add milliseconds (microseconds / 1000)
    milliseconds = now_utc.microsecond // 1000
    timestamp = f"{timestamp}{milliseconds:03d}Z"
    suffix = uuid.uuid4().hex[:6]
    return f"{timestamp}-{suffix}"


def create_run(
    conn: sqlite3.Connection,
    *,
    config: dict,
    parameters_version: str,
    trigger_type: str = "manual",
    parent_run_id: str | None = None,
    code_version: str | None = None,
    notes: str | None = None,
) -> str:
    """Create a new run.

    Inserts a new runs row with status 'pending' and returns the generated run_id.

    Args:
        conn: An open connection.
        config: JSON-serializable dict of orchestration.PipelineConfig.to_dict().
            Contains only run-specific choices (start_stage, max_catalog_pages,
            request_budget_override, notes), NOT AcquisitionConfig/EnrichmentParams/AnalysisParams,
            which are reconstructable from parameters_version.
        parameters_version: Output of config.parameters_version(...), a content hash
            computed from parameters.toml file bytes.
        trigger_type: 'manual' or 'scheduled'. Defaults to 'manual'.
        parent_run_id: Reserved for future incremental re-crawls; None in v1.
        code_version: Optional identifier (e.g. short git hash) of the running code.
        notes: Optional free user text.

    Returns:
        The generated run_id: UTC-timestamp-prefixed, lexicographically sortable,
        human-readable (e.g. '20260920T143012Z-a1b2c3').

    Raises:
        StorageError: If config is not JSON-serializable, trigger_type is invalid,
            or parent_run_id references a nonexistent run_id.
    """
    _check_same_thread(conn)

    # Validate trigger_type
    if trigger_type not in {"manual", "scheduled"}:
        raise StorageError(
            f"trigger_type must be 'manual' or 'scheduled', got '{trigger_type}'"
        )

    # Validate config is JSON-serializable
    try:
        config_json = json.dumps(config)
    except (TypeError, ValueError) as e:
        raise StorageError(f"config is not JSON-serializable: {e}") from e

    # Generate run_id
    run_id = _generate_run_id()

    # Get current UTC time as ISO-8601 string
    started_at = datetime.utcnow().isoformat()

    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO runs (
                run_id, started_at, finished_at, status, trigger_type,
                parent_run_id, config_json, parameters_version,
                code_version, error_message, notes
            ) VALUES (?, ?, NULL, 'pending', ?, ?, ?, ?, ?, NULL, ?)
            """,
            (run_id, started_at, trigger_type, parent_run_id, config_json,
             parameters_version, code_version, notes),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise StorageError(f"Failed to create run: {e}") from e
    except sqlite3.Error as e:
        conn.rollback()
        raise StorageError(f"Database error during run creation: {e}") from e

    return run_id


def get_run(conn: sqlite3.Connection, run_id: str) -> RunRecord | None:
    """Fetch a single run.

    Args:
        conn: An open connection.
        run_id: The run to fetch.

    Returns:
        A RunRecord with config_json deserialized into config: dict,
        or None if run_id does not exist.

    Raises:
        StorageError: If config_json is corrupted/unparseable JSON
            (indicates database corruption).
    """
    _check_same_thread(conn)

    cursor = conn.cursor()
    cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()

    if row is None:
        return None

    # Deserialize config_json
    try:
        config = json.loads(row["config_json"])
    except (json.JSONDecodeError, ValueError) as e:
        raise StorageError(
            f"Corrupted config_json in run {run_id}: {e}"
        ) from e

    # Parse timestamps
    try:
        started_at = _parse_iso_timestamp(row["started_at"])
    except (ValueError, TypeError) as e:
        raise StorageError(f"Corrupted started_at in run {run_id}: {e}") from e

    finished_at = None
    if row["finished_at"]:
        try:
            finished_at = _parse_iso_timestamp(row["finished_at"])
        except (ValueError, TypeError) as e:
            raise StorageError(f"Corrupted finished_at in run {run_id}: {e}") from e

    return RunRecord(
        run_id=row["run_id"],
        started_at=started_at,
        finished_at=finished_at,
        status=row["status"],
        trigger_type=row["trigger_type"],
        parent_run_id=row["parent_run_id"],
        config=config,
        parameters_version=row["parameters_version"],
        code_version=row["code_version"],
        error_message=row["error_message"],
        notes=row["notes"],
    )


def list_runs(
    conn: sqlite3.Connection, *, limit: int = 50, offset: int = 0
) -> pd.DataFrame:
    """List runs newest-first with pagination.

    Args:
        conn: An open connection.
        limit: Maximum rows to return. Defaults to 50.
        offset: Rows to skip for pagination. Defaults to 0.

    Returns:
        A DataFrame with columns: run_id, started_at, finished_at, status,
        trigger_type, candidate_count. Sorted by started_at descending,
        ties broken by run_id descending.

    Note:
        candidate_count is the count of games_enriched rows for that run,
        0 if enrichment has not run yet.
    """
    _check_same_thread(conn)

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            r.run_id,
            r.started_at,
            r.finished_at,
            r.status,
            r.trigger_type,
            COALESCE(COUNT(e.appid), 0) AS candidate_count
        FROM runs r
        LEFT JOIN games_enriched e ON r.run_id = e.run_id
        GROUP BY r.run_id
        ORDER BY r.started_at DESC, r.run_id DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )

    rows = cursor.fetchall()
    if not rows:
        # Return empty DataFrame with correct columns
        return pd.DataFrame(
            columns=["run_id", "started_at", "finished_at", "status", "trigger_type", "candidate_count"]
        )

    # Convert rows to list of dicts
    data = []
    for row in rows:
        data.append({
            "run_id": row["run_id"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "status": row["status"],
            "trigger_type": row["trigger_type"],
            "candidate_count": row["candidate_count"],
        })

    df = pd.DataFrame(data)
    return df


def delete_run(conn: sqlite3.Connection, run_id: str) -> None:
    """Delete a run and all of its data.

    Args:
        conn: An open connection with foreign_keys=ON (guaranteed by get_connection).
        run_id: The run to delete.

    Returns:
        None.

    Note:
        A no-op, not an error, when run_id does not exist. Deletion cascades
        to all run-keyed tables via ON DELETE CASCADE foreign keys.
    """
    _check_same_thread(conn)

    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        raise StorageError(f"Failed to delete run: {e}") from e


def update_run_status(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
    *,
    finished_at: str | None = None,
    error_message: str | None = None,
) -> None:
    """Transition a run to a new status.

    Args:
        conn: An open connection.
        run_id: The run to update.
        status: One of 'pending', 'running', 'succeeded', 'failed', 'cancelled'.
        finished_at: ISO-8601 UTC timestamp string; typically provided when status
            is a terminal state ('succeeded', 'failed', 'cancelled').
        error_message: Populated when status='failed'.

    Returns:
        None.

    Raises:
        StorageError: If run_id does not exist, or status is not one of the
            five allowed values.

    Note:
        Per ADR-016 write-ordering, this must be the last write of the unit of work
        it describes. Committed immediately.
    """
    _check_same_thread(conn)

    # Validate status
    allowed_statuses = {"pending", "running", "succeeded", "failed", "cancelled"}
    if status not in allowed_statuses:
        raise StorageError(
            f"status must be one of {allowed_statuses}, got '{status}'"
        )

    # Verify run exists
    cursor = conn.cursor()
    cursor.execute("SELECT run_id FROM runs WHERE run_id = ?", (run_id,))
    if cursor.fetchone() is None:
        raise StorageError(f"Run {run_id} does not exist")

    if finished_at is None and status in {"succeeded", "failed", "cancelled"}:
        finished_at = datetime.utcnow().isoformat()

    # Update the run
    try:
        cursor.execute(
            """
            UPDATE runs
            SET status = ?, finished_at = ?, error_message = ?
            WHERE run_id = ?
            """,
            (status, finished_at, error_message, run_id),
        )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        raise StorageError(f"Failed to update run status: {e}") from e
