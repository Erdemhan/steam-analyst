"""
Analysis result persistence: write and read JSON payloads for analysis outputs.

Every function that uses a connection must call _check_same_thread at its start
to reject cross-thread misuse per ADR-002.
"""

import json
import sqlite3
from datetime import datetime

from .connection import _check_same_thread
from .types import StorageError

# Fixed set of valid analysis_type values (from schema.analysis_types)
ANALYSIS_TYPES = {
    "opportunity_matrix",
    "tag_summary",
    "tag_clusters",
    "tag_trends",
    "competition_density",
    "funnel_report",
    "case_studies",
}


def write_analysis_result(
    conn: sqlite3.Connection,
    run_id: str,
    analysis_type: str,
    payload: dict,
    *,
    parameters_version: str,
) -> None:
    """Write one analysis result blob.

    Upserts one analysis_results row for the given run_id and analysis_type.
    If a row already exists for this (run_id, analysis_type) pair, it is
    replaced entirely by the new payload.

    Args:
        conn: An open connection.
        run_id: The run this result belongs to.
        analysis_type: One of 'opportunity_matrix', 'tag_summary', 'tag_clusters',
            'tag_trends', 'competition_density', 'funnel_report', 'case_studies'.
        payload: A JSON-serializable dict; stored verbatim as payload_json.
        parameters_version: The parameter-set hash in effect when this result
            was produced.

    Returns:
        None.

    Raises:
        StorageError: If run_id does not exist, analysis_type is not one of the
            seven allowed values, or payload is not JSON-serializable (e.g.
            contains float('nan'), float('inf'), or other non-JSON types).

    Postcondition:
        read_analysis_result(conn, run_id, analysis_type) returns exactly
        payload (deep-equal) after a successful write.
    """
    _check_same_thread(conn)

    # Validate analysis_type
    if analysis_type not in ANALYSIS_TYPES:
        raise StorageError(
            f"analysis_type '{analysis_type}' not in allowed set: {sorted(ANALYSIS_TYPES)}"
        )

    # Validate payload is JSON-serializable (this also catches NaN/Infinity)
    # Use allow_nan=False to reject NaN/Infinity values as per spec requirement
    try:
        payload_json = json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise StorageError(
            f"payload is not JSON-serializable: {e}"
        ) from e

    # Verify run_id exists
    cursor = conn.cursor()
    cursor.execute("SELECT run_id FROM runs WHERE run_id = ?", (run_id,))
    if cursor.fetchone() is None:
        raise StorageError(f"Run {run_id} does not exist")

    # Get current UTC time as ISO-8601 string for created_at
    created_at = datetime.utcnow().isoformat()

    # Upsert: INSERT OR REPLACE (replacing on (run_id, analysis_type) conflict)
    try:
        cursor.execute(
            """
            INSERT OR REPLACE INTO analysis_results
            (run_id, analysis_type, created_at, parameters_version, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, analysis_type, created_at, parameters_version, payload_json),
        )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        raise StorageError(f"Failed to write analysis result: {e}") from e


def read_analysis_result(
    conn: sqlite3.Connection, run_id: str, analysis_type: str
) -> dict | None:
    """Read one analysis result blob.

    Retrieves and deserializes the payload_json for a given (run_id, analysis_type)
    pair. Returns None if no result exists for that pair (whether because the run
    does not exist, or because that analysis type has not been computed for this run).

    Args:
        conn: An open connection.
        run_id: The run to read.
        analysis_type: One of the seven allowed analysis_type values.

    Returns:
        The deserialized payload dict, or None if no row exists for that
        (run_id, analysis_type) pair.

    Postcondition:
        The returned dict is a fresh deserialization each call; mutating it
        never affects the stored row.
    """
    _check_same_thread(conn)

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT payload_json FROM analysis_results
        WHERE run_id = ? AND analysis_type = ?
        """,
        (run_id, analysis_type),
    )
    row = cursor.fetchone()

    if row is None:
        return None

    # Deserialize payload_json
    try:
        payload = json.loads(row[0])
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        raise StorageError(
            f"Corrupted payload_json for run {run_id}, analysis_type {analysis_type}: {e}"
        ) from e

    return payload
