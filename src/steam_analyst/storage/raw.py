"""
Raw payload storage: insert and query immutable HTTP response snapshots.

This module handles batched persistence of fetched payloads to the raw_games
table and their streaming retrieval without materializing the full result set
in memory.
"""

import json
import sqlite3
from datetime import datetime
from typing import Iterable, Iterator

from .connection import _check_same_thread
from .types import RawPayload, StorageError


def upsert_raw_payloads(
    conn: sqlite3.Connection, run_id: str, payloads: Iterable[RawPayload]
) -> int:
    """Write a batch of raw payloads.

    Args:
        conn: An open connection.
        run_id: The run these payloads belong to.
        payloads: An iterable of RawPayload. Consumed lazily and written in
            batches (e.g. 500 rows per executemany call) inside one surrounding
            transaction, so a crash mid-stream leaves the already-committed
            batches intact per the acquisition invariant 'payloads are persisted
            in batches as they stream in'.

    Returns:
        The number of rows written (post-deduplication if the same (appid,
        source) appeared twice in payloads, the later one wins).

    Raises:
        StorageError: If run_id does not exist.
    """
    _check_same_thread(conn)

    # Validate run_id exists
    cursor = conn.cursor()
    cursor.execute("SELECT run_id FROM runs WHERE run_id = ?", (run_id,))
    if cursor.fetchone() is None:
        raise StorageError(f"Run {run_id} does not exist")

    # Valid sources
    ALLOWED_SOURCES = {
        "steamspy_all",
        "steamspy_appdetails",
        "steam_appdetails",
        "steam_reviews",
    }

    rows_written = 0
    batch_size = 500
    batch = []

    try:
        for payload in payloads:
            # Validate source
            if payload.source not in ALLOWED_SOURCES:
                raise StorageError(
                    f"Invalid source '{payload.source}'; must be one of {ALLOWED_SOURCES}"
                )

            # payload_sha256 is computed by the caller (acquisition) over the
            # exact wire bytes received, before parsing -- storage stores it
            # verbatim as an opaque provenance value. It cannot be re-derived
            # here from payload.payload (an already-parsed dict): re-serializing
            # via json.dumps is not guaranteed byte-identical to the original
            # response body (key order, whitespace), so recomputing and
            # comparing would reject valid, correctly-hashed payloads.
            payload_json = json.dumps(payload.payload, separators=(",", ":"), sort_keys=True)

            # Add to batch
            batch.append(
                (
                    run_id,
                    payload.appid,
                    payload.source,
                    payload.fetched_at.isoformat(),
                    payload.http_status,
                    payload_json,
                    payload.payload_sha256,
                )
            )

            # If batch reaches the size limit, flush it
            if len(batch) >= batch_size:
                cursor.executemany(
                    """
                    INSERT OR IGNORE INTO raw_games
                    (run_id, appid, source, fetched_at, http_status, payload_json, payload_sha256)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    batch,
                )
                rows_written += cursor.rowcount
                batch = []

        # Flush remaining batch
        if batch:
            cursor.executemany(
                """
                INSERT OR IGNORE INTO raw_games
                (run_id, appid, source, fetched_at, http_status, payload_json, payload_sha256)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )
            rows_written += cursor.rowcount

        conn.commit()

    except StorageError:
        # Re-raise StorageError as-is
        conn.rollback()
        raise
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise StorageError(f"Integrity constraint violation during upsert: {e}") from e
    except sqlite3.Error as e:
        conn.rollback()
        raise StorageError(f"Database error during upsert_raw_payloads: {e}") from e
    except Exception as e:
        # Catch any other exception from payload iteration
        conn.rollback()
        raise

    return rows_written


def read_raw_payloads(
    conn: sqlite3.Connection, run_id: str, source: str
) -> Iterator[RawPayload]:
    """Stream raw payloads for one source.

    Args:
        conn: An open connection.
        run_id: The run to read.
        source: One of 'steamspy_all','steamspy_appdetails','steam_appdetails',
            'steam_reviews'.

    Yields:
        RawPayload instances, one per matching row, in an unspecified but
        stable-for-a-given-run order (typically appid ascending, via the
        idx_raw_games_run_source index).

    Raises:
        StorageError: If source is not one of the four allowed values.
    """
    _check_same_thread(conn)

    # Validate source immediately (before returning generator)
    ALLOWED_SOURCES = {
        "steamspy_all",
        "steamspy_appdetails",
        "steam_appdetails",
        "steam_reviews",
    }

    if source not in ALLOWED_SOURCES:
        raise StorageError(
            f"Invalid source '{source}'; must be one of {ALLOWED_SOURCES}"
        )

    # Define inner generator to handle lazy iteration
    def _stream_payloads():
        cursor = conn.cursor()
        try:
            # Use fetchmany pattern to avoid materializing the whole result set
            cursor.execute(
                """
                SELECT appid, source, fetched_at, http_status, payload_json, payload_sha256
                FROM raw_games
                WHERE run_id = ? AND source = ?
                ORDER BY appid
                """,
                (run_id, source),
            )

            # Fetch in batches of 500
            batch_size = 500
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break

                for row in rows:
                    # Deserialize payload_json
                    try:
                        payload = json.loads(row["payload_json"])
                    except (json.JSONDecodeError, ValueError) as e:
                        raise StorageError(
                            f"Corrupted payload_json for appid={row['appid']}, "
                            f"source={row['source']}: {e}"
                        ) from e

                    # Parse fetched_at timestamp
                    try:
                        fetched_at = datetime.fromisoformat(row["fetched_at"])
                    except (ValueError, TypeError) as e:
                        raise StorageError(
                            f"Corrupted fetched_at for appid={row['appid']}, "
                            f"source={row['source']}: {e}"
                        ) from e

                    yield RawPayload(
                        appid=row["appid"],
                        source=row["source"],
                        fetched_at=fetched_at,
                        http_status=row["http_status"],
                        payload=payload,
                        payload_sha256=row["payload_sha256"],
                    )

        except StorageError:
            raise
        except sqlite3.Error as e:
            raise StorageError(f"Database error during read_raw_payloads: {e}") from e

    return _stream_payloads()


def read_fetched_appids(conn: sqlite3.Connection, run_id: str, source: str) -> set[int]:
    """List appids already fetched and persisted for one run and source.

    Args:
        conn: An open connection.
        run_id: The run to check.
        source: One of 'steamspy_all', 'steamspy_appdetails', 'steam_appdetails',
            'steam_reviews'.

    Returns:
        A set of appids present in raw_games for that (run_id, source) pair.
        Empty set if none.

    Raises:
        StorageError: If source is not one of the four allowed values.
    """
    _check_same_thread(conn)

    # Validate source
    ALLOWED_SOURCES = {
        "steamspy_all",
        "steamspy_appdetails",
        "steam_appdetails",
        "steam_reviews",
    }

    if source not in ALLOWED_SOURCES:
        raise StorageError(
            f"Invalid source '{source}'; must be one of {ALLOWED_SOURCES}"
        )

    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT DISTINCT appid
            FROM raw_games
            WHERE run_id = ? AND source = ?
            """,
            (run_id, source),
        )

        rows = cursor.fetchall()
        return {row["appid"] for row in rows}

    except sqlite3.Error as e:
        raise StorageError(f"Database error during read_fetched_appids: {e}") from e
