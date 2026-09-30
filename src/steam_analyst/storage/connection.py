"""
SQLite connection management with required pragmas and thread-safety tagging.

This module provides get_connection for opening a configured connection and
connect as a context-manager wrapper that guarantees close() on exit.
"""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .types import StorageError

# Module-level registry: id(conn) -> thread_id_at_creation_time
# Used to detect and reject cross-thread connection reuse.
_THREAD_TAGS: dict[int, int] = {}


def _check_same_thread(conn: sqlite3.Connection) -> None:
    """Verify that conn was created in the current thread.

    Args:
        conn: An open sqlite3.Connection.

    Raises:
        StorageError: If the connection was created in a different thread.
    """
    conn_id = id(conn)
    if conn_id not in _THREAD_TAGS:
        # If not in registry, assume it's safe (shouldn't happen in normal flow)
        return

    creation_thread = _THREAD_TAGS[conn_id]
    current_thread = threading.get_ident()

    if creation_thread != current_thread:
        raise StorageError(
            f"cross-thread connection use: created in thread {creation_thread}, "
            f"but accessed from thread {current_thread}"
        )


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open a configured SQLite connection.

    Opens a connection to the SQLite database at db_path with the following
    configuration:
    - journal_mode = WAL (Write-Ahead Logging)
    - foreign_keys = ON
    - synchronous = NORMAL
    - row_factory = sqlite3.Row
    - Connection is tagged with threading.get_ident() for later cross-thread detection

    Args:
        db_path: Absolute path to the database file. Parent directories are
            created if missing.

    Returns:
        An open sqlite3.Connection with the above pragmas applied.

    Raises:
        StorageError: If parent directory creation fails (e.g., permission denied)
            or if the underlying sqlite3.connect call fails.
    """
    try:
        # Create parent directories if needed
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError) as e:
        raise StorageError(f"Failed to create database parent directory: {e}") from e

    try:
        conn = sqlite3.connect(str(db_path), isolation_level=None)
    except sqlite3.Error as e:
        raise StorageError(f"Failed to open database: {e}") from e

    try:
        # Set pragmas
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")

        # Set row factory for dict-like row access
        conn.row_factory = sqlite3.Row

        # Tag with thread ID for later cross-thread detection
        _THREAD_TAGS[id(conn)] = threading.get_ident()

        return conn
    except sqlite3.Error as e:
        conn.close()
        raise StorageError(f"Failed to configure database connection: {e}") from e


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Context manager for a configured SQLite connection.

    Opens a connection via get_connection and guarantees it is closed on exit,
    whether normally or via an exception.

    Args:
        db_path: Absolute path to the database file, passed to get_connection.

    Yields:
        An open sqlite3.Connection with the same pragmas and thread tagging
        as get_connection.

    Raises:
        StorageError: Propagated from get_connection if opening fails.
    """
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        # Clean up the thread tag registry
        _THREAD_TAGS.pop(id(conn), None)
        conn.close()
