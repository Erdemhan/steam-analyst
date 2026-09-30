"""
Run stage management: track acquisition, enrichment, and analysis progress per run.

Every function that uses a connection must call _check_same_thread at its start
to reject cross-thread misuse per ADR-002.
"""

import sqlite3
from datetime import datetime

from .connection import _check_same_thread
from .types import RunStage, StorageError


# Canonical ordering of pipeline stages
_STAGE_ORDER = {"acquisition": 0, "enrichment": 1, "analysis": 2}
_VALID_STAGES = {"acquisition", "enrichment", "analysis"}
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


def begin_run_stage(conn: sqlite3.Connection, run_id: str, stage: str) -> int:
    """Transition one run_stages row to 'running', creating it if absent.

    Args:
        conn: An open connection.
        run_id: The run this stage belongs to. Must already exist in runs.
        stage: One of 'acquisition', 'enrichment', 'analysis'.

    Returns:
        The new attempt number (1 for a first attempt, incremented on every
        subsequent call for the same run_id/stage).

    Raises:
        StorageError: If run_id does not exist, or stage is not one of the
            three allowed values.

    Note:
        Per ADR-016, the write is committed before begin_run_stage returns
        so that the UI (a concurrent reader) observes the transition without
        waiting for the stage itself to finish.

        Per ADR-014, calling begin_run_stage on a stage that already has
        status='succeeded' is legal (resume or re-run): attempt increments,
        status resets to 'running', and finished_at and error_message are cleared.
    """
    _check_same_thread(conn)

    # Validate stage before any writes
    if stage not in _VALID_STAGES:
        raise StorageError(
            f"stage must be one of {_VALID_STAGES}, got '{stage}'"
        )

    # Verify run_id exists
    cursor = conn.cursor()
    cursor.execute("SELECT run_id FROM runs WHERE run_id = ?", (run_id,))
    if cursor.fetchone() is None:
        raise StorageError(f"Run {run_id} does not exist")

    # Get current UTC time as ISO-8601 string
    started_at = datetime.utcnow().isoformat()

    # Upsert the run_stages row: insert if not exists, or update if exists
    try:
        cursor.execute(
            """
            INSERT INTO run_stages (run_id, stage, status, started_at, finished_at, attempt, error_message)
            VALUES (?, ?, 'running', ?, NULL, 1, NULL)
            ON CONFLICT(run_id, stage) DO UPDATE SET
                status = 'running',
                started_at = ?,
                finished_at = NULL,
                attempt = attempt + 1,
                error_message = NULL
            """,
            (run_id, stage, started_at, started_at),
        )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        raise StorageError(f"Failed to begin run stage: {e}") from e

    # Fetch the current attempt number after the upsert
    cursor.execute(
        "SELECT attempt FROM run_stages WHERE run_id = ? AND stage = ?",
        (run_id, stage),
    )
    row = cursor.fetchone()
    if row is None:
        raise StorageError(
            f"Failed to retrieve attempt number for {run_id}/{stage}"
        )

    return int(row["attempt"])


def finish_run_stage(
    conn: sqlite3.Connection,
    run_id: str,
    stage: str,
    status: str,
    *,
    error_message: str | None = None,
) -> None:
    """Transition a running stage to a terminal status.

    Args:
        conn: An open connection.
        run_id: The run this stage belongs to.
        stage: One of 'acquisition', 'enrichment', 'analysis'.
        status: One of 'succeeded', 'failed', 'cancelled'. Not 'pending'
            or 'running' -- those are begin_run_stage's job.
        error_message: Populated when status is 'failed' or 'cancelled' with
            a cause; ignored (but not rejected) for 'succeeded'.

    Returns:
        None.

    Raises:
        StorageError: If run_id/stage has no row at all (finish before begin),
            or status is not one of the three terminal values.

    Note:
        Per ADR-016, the caller must have already committed that stage's own
        data (e.g. write_enriched for the enrichment stage) before calling
        this, since a reader polling run_stages must never observe a 'succeeded'
        stage whose data isn't there yet.

        Per ADR-016, the write is committed before finish_run_stage returns.
    """
    _check_same_thread(conn)

    # Validate status before any writes
    if status not in _TERMINAL_STATUSES:
        raise StorageError(
            f"status must be one of {_TERMINAL_STATUSES}, got '{status}'"
        )

    # Verify run_id/stage row exists
    cursor = conn.cursor()
    cursor.execute(
        "SELECT run_id FROM run_stages WHERE run_id = ? AND stage = ?",
        (run_id, stage),
    )
    if cursor.fetchone() is None:
        raise StorageError(
            f"Stage {stage} of run {run_id} was never begun (no row exists)"
        )

    # Get current UTC time as ISO-8601 string
    finished_at = datetime.utcnow().isoformat()

    # Update the row with terminal status and finished_at
    try:
        cursor.execute(
            """
            UPDATE run_stages
            SET status = ?, finished_at = ?, error_message = ?
            WHERE run_id = ? AND stage = ?
            """,
            (status, finished_at, error_message, run_id, stage),
        )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        raise StorageError(f"Failed to finish run stage: {e}") from e


def read_run_stages(conn: sqlite3.Connection, run_id: str) -> list[RunStage]:
    """Read every attempted stage's status for a run.

    Args:
        conn: An open connection.
        run_id: The run to read stages for. Does not need to exist -- see
            edge cases.

    Returns:
        A list of RunStage, ordered acquisition, enrichment, analysis
        regardless of insertion order. Stages never attempted are simply
        absent from the list.

    Raises:
        StorageError: Only for cross-thread misuse (detected at start).

    Note:
        read_run_stages does not validate that run_id exists, mirroring
        read_run_events' and read_enriched's own tolerant-read contracts.
        A caller wanting existence validation calls get_run separately.

        A run with all three stages succeeded returns exactly three RunStage
        entries, each status='succeeded'. A run with no stages attempted
        returns an empty list, not an error.
    """
    _check_same_thread(conn)

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT run_id, stage, status, started_at, finished_at, attempt, error_message
        FROM run_stages
        WHERE run_id = ?
        """,
        (run_id,),
    )

    rows = cursor.fetchall()
    if not rows:
        return []

    # Convert each row to a RunStage, parsing timestamps
    stages = []
    for row in rows:
        started_at = None
        if row["started_at"]:
            try:
                started_at = datetime.fromisoformat(row["started_at"])
            except (ValueError, TypeError):
                # Tolerate malformed timestamps by leaving as None
                pass

        finished_at = None
        if row["finished_at"]:
            try:
                finished_at = datetime.fromisoformat(row["finished_at"])
            except (ValueError, TypeError):
                # Tolerate malformed timestamps by leaving as None
                pass

        stages.append(
            RunStage(
                run_id=row["run_id"],
                stage=row["stage"],
                status=row["status"],
                started_at=started_at,
                finished_at=finished_at,
                attempt=row["attempt"],
                error_message=row["error_message"],
            )
        )

    # Sort by canonical stage order
    stages.sort(key=lambda s: _STAGE_ORDER.get(s.stage, 999))

    return stages
