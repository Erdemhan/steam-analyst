"""
Game tag storage: read and write community tags for games in a run.

Every function that uses a connection must call _check_same_thread at its start
to reject cross-thread misuse.
"""

import sqlite3
from typing import Iterable

import pandas as pd

from .connection import _check_same_thread
from .types import StorageError, TagRow


def write_tags(
    conn: sqlite3.Connection, run_id: str, rows: Iterable[TagRow]
) -> int:
    """Replace a run's tag rows.

    Atomically deletes all prior game_tags rows for the run and inserts the new rows.
    Idempotent: re-running with the same rows is a no-op after the first call.

    Args:
        conn: An open connection.
        run_id: The run these tags belong to.
        rows: An iterable of TagRow. May contain multiple rows for the same appid
            (different tags) but not the same (appid, tag) pair twice.

    Returns:
        The number of rows written.

    Raises:
        StorageError: If run_id does not exist, or the same (appid, tag) pair
            appears twice in rows (indicating a caller-side deduplication bug).
    """
    _check_same_thread(conn)

    # Materialize rows to allow multiple passes (checking for duplicates, then inserting)
    rows_list = list(rows)

    # Verify run_id exists
    cursor = conn.cursor()
    cursor.execute("SELECT run_id FROM runs WHERE run_id = ?", (run_id,))
    if cursor.fetchone() is None:
        raise StorageError(f"Run {run_id} does not exist")

    # Check for duplicate (appid, tag) pairs within the input
    seen_pairs = set()
    for row in rows_list:
        pair = (row.appid, row.tag)
        if pair in seen_pairs:
            raise StorageError(
                f"Duplicate (appid, tag) pair in rows: ({row.appid}, {row.tag!r})"
            )
        seen_pairs.add(pair)

    # Delete all prior game_tags rows for this run and insert new ones in a transaction
    try:
        cursor.execute("DELETE FROM game_tags WHERE run_id = ?", (run_id,))

        # Insert new rows
        for row in rows_list:
            cursor.execute(
                """
                INSERT INTO game_tags (run_id, appid, tag, votes, rank)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, row.appid, row.tag, row.votes, row.rank),
            )

        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        raise StorageError(f"Failed to write tags for run {run_id}: {e}") from e

    return len(rows_list)


def read_tags(
    conn: sqlite3.Connection, run_id: str, *, min_votes: int = 0
) -> pd.DataFrame:
    """Read tags for a run.

    Args:
        conn: An open connection.
        run_id: The run to read.
        min_votes: Only tags with votes >= min_votes are returned. A row with
            votes=NULL is excluded whenever min_votes > 0 (NULL is treated as
            'unknown vote count', not as zero), and included whenever
            min_votes == 0. Defaults to 0.

    Returns:
        A DataFrame with columns appid, tag, votes, rank (in that order).
        Empty DataFrame with these columns if the run has no tags.

    Raises:
        StorageError: On database errors (e.g., cross-thread access).
    """
    _check_same_thread(conn)

    cursor = conn.cursor()

    # Build the query based on min_votes
    if min_votes == 0:
        # Include all rows, including those with votes=NULL
        query = """
            SELECT appid, tag, votes, rank
            FROM game_tags
            WHERE run_id = ?
            ORDER BY appid, tag
        """
        params = (run_id,)
    else:
        # Exclude rows where votes is NULL (NULL >= min_votes is never true in SQL's three-valued logic)
        # Only include rows where votes >= min_votes
        query = """
            SELECT appid, tag, votes, rank
            FROM game_tags
            WHERE run_id = ? AND votes IS NOT NULL AND votes >= ?
            ORDER BY appid, tag
        """
        params = (run_id, min_votes)

    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    except sqlite3.Error as e:
        raise StorageError(f"Failed to read tags for run {run_id}: {e}") from e

    # Convert to DataFrame
    if not rows:
        # Return empty DataFrame with correct columns and dtypes
        return pd.DataFrame(columns=["appid", "tag", "votes", "rank"])

    # Convert rows to list of dicts
    data = [
        {
            "appid": row["appid"],
            "tag": row["tag"],
            "votes": row["votes"],
            "rank": row["rank"],
        }
        for row in rows
    ]

    df = pd.DataFrame(data)
    return df
