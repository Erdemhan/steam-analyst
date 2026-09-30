"""
Unit tests for storage.connection module (get_connection and connect).
"""

import sqlite3
import threading
from pathlib import Path

import pytest

from steam_analyst.storage.connection import (
    _check_same_thread,
    connect,
    get_connection,
)
from steam_analyst.storage.types import StorageError


class TestGetConnection:
    """Tests for get_connection function."""

    def test_pragmas_applied(self, tmp_path: Path):
        """A fresh connection reports WAL mode and foreign_keys=1."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            cursor = conn.cursor()

            # Check journal_mode
            cursor.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode.lower() == "wal"

            # Check foreign_keys
            cursor.execute("PRAGMA foreign_keys")
            fk_enabled = cursor.fetchone()[0]
            assert fk_enabled == 1

            # Check synchronous
            cursor.execute("PRAGMA synchronous")
            sync_mode = cursor.fetchone()[0]
            assert sync_mode == 1  # NORMAL = 1

        finally:
            conn.close()

    def test_creates_missing_parent_directory(self, tmp_path: Path):
        """Parent directories are created if they do not exist."""
        db_path = tmp_path / "deeply" / "nested" / "dir" / "test.db"
        assert not db_path.parent.exists()

        conn = get_connection(db_path)
        try:
            assert db_path.parent.exists()
            assert db_path.exists()
        finally:
            conn.close()

    def test_row_factory_set(self, tmp_path: Path):
        """Connection has row_factory set to sqlite3.Row."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            assert conn.row_factory is sqlite3.Row
        finally:
            conn.close()

    def test_basic_operations_work(self, tmp_path: Path):
        """Connection can execute basic SQL operations."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
            cursor.execute("INSERT INTO test (name) VALUES ('Alice')")
            cursor.execute("SELECT * FROM test")
            rows = cursor.fetchall()
            assert len(rows) == 1
            assert rows[0]["name"] == "Alice"
        finally:
            conn.close()

    def test_creates_parent_deeply_nested(self, tmp_path: Path):
        """Deeply nested parent directories are created."""
        db_path = tmp_path / "a" / "b" / "c" / "d" / "e" / "test.db"
        conn = get_connection(db_path)
        try:
            assert db_path.exists()
            assert db_path.parent.exists()
        finally:
            conn.close()

    def test_isolation_level_none(self, tmp_path: Path):
        """Connection is opened in autocommit mode (isolation_level=None)."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            assert conn.isolation_level is None
        finally:
            conn.close()

    def test_multiple_connections_different_paths(self, tmp_path: Path):
        """Multiple connections to different databases can be opened."""
        db_path1 = tmp_path / "test1.db"
        db_path2 = tmp_path / "test2.db"

        conn1 = get_connection(db_path1)
        conn2 = get_connection(db_path2)

        try:
            assert conn1 is not conn2
            assert db_path1.exists()
            assert db_path2.exists()
        finally:
            conn1.close()
            conn2.close()


class TestConnect:
    """Tests for connect context manager."""

    def test_connection_closed_after_normal_exit(self, tmp_path: Path):
        """Connection is closed after normal exit of with-block."""
        db_path = tmp_path / "test.db"

        with connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE test (id INTEGER)")

        # After context exit, connection should be closed
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_connection_closed_after_exception(self, tmp_path: Path):
        """Connection is closed even when an exception is raised in with-block."""
        db_path = tmp_path / "test.db"
        caught_exception = None

        try:
            with connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("CREATE TABLE test (id INTEGER)")
                raise ValueError("Test exception")
        except ValueError as e:
            caught_exception = e

        # Exception should have been propagated
        assert caught_exception is not None
        assert str(caught_exception) == "Test exception"

        # Connection should still be closed
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_connect_cleans_up_on_error(self, tmp_path: Path):
        """Connection context manager works even when an error occurs."""
        db_path = tmp_path / "test.db"
        
        try:
            with connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("CREATE TABLE test (id INTEGER)")
                raise RuntimeError("Test error")
        except RuntimeError:
            pass  # Expected
        
        # Connection should be closed despite the error
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_connect_yields_same_pragmas(self, tmp_path: Path):
        """Connection from connect() has the same pragmas as get_connection()."""
        db_path = tmp_path / "test.db"

        with connect(db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode.lower() == "wal"

            cursor.execute("PRAGMA foreign_keys")
            fk = cursor.fetchone()[0]
            assert fk == 1

    def test_multiple_sequential_connections(self, tmp_path: Path):
        """Multiple sequential uses of connect work independently."""
        db_path = tmp_path / "test.db"

        # First use
        with connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE test (id INTEGER)")
            cursor.execute("INSERT INTO test VALUES (1)")

        # Second use on same database
        with connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM test")
            count = cursor.fetchone()[0]
            assert count == 1


class TestThreadSafety:
    """Tests for thread-safety tagging and checking."""

    def test_check_same_thread_passes_in_same_thread(self, tmp_path: Path):
        """_check_same_thread does not raise when called in the creation thread."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            # Should not raise
            _check_same_thread(conn)
        finally:
            conn.close()

    def test_check_same_thread_fails_in_different_thread(self, tmp_path: Path):
        """_check_same_thread raises StorageError when called from a different thread."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        error_raised = False
        error_msg = None

        def use_in_different_thread():
            nonlocal error_raised, error_msg
            try:
                _check_same_thread(conn)
            except StorageError as e:
                error_raised = True
                error_msg = str(e)

        thread = threading.Thread(target=use_in_different_thread)
        thread.start()
        thread.join()

        try:
            assert error_raised
            assert "cross-thread" in error_msg
        finally:
            conn.close()

    def test_context_manager_cleans_up_thread_tags(self, tmp_path: Path):
        """Thread tags are cleaned up after connect context exits."""
        db_path = tmp_path / "test.db"

        with connect(db_path) as conn:
            pass
        # After context, tag should be removed, but connection should still be closeable

        # Attempt to close already-closed connection should not raise
        # (sqlite3 allows close on already-closed connection)
        conn.close()


class TestEdgeCases:
    """Tests for edge cases in connection management."""

    def test_existing_database_can_be_opened(self, tmp_path: Path):
        """An existing database file can be opened without issues."""
        db_path = tmp_path / "existing.db"

        # Create a database
        with connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE test (id INTEGER)")
            cursor.execute("INSERT INTO test VALUES (42)")

        # Open the existing database again
        with connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM test")
            row = cursor.fetchone()
            assert row[0] == 42

    def test_in_memory_database(self):
        """In-memory database can be created with :memory:."""
        conn = get_connection(Path(":memory:"))
        try:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE test (id INTEGER)")
            assert True  # If we get here, it worked
        finally:
            conn.close()

    def test_multiple_paths_with_same_basename(self, tmp_path: Path):
        """Databases with same filename in different directories are distinct."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        path1 = dir1 / "test.db"
        path2 = dir2 / "test.db"

        conn1 = get_connection(path1)
        conn2 = get_connection(path2)

        try:
            # Both should exist and be different files
            assert path1.exists()
            assert path2.exists()
            assert path1 != path2
        finally:
            conn1.close()
            conn2.close()
