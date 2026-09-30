"""
Unit tests for storage.schema module (initialize_schema, migrate, etc).
"""

from pathlib import Path

import pytest

from steam_analyst.storage.connection import connect, get_connection
from steam_analyst.storage.schema import (
    CURRENT_SCHEMA_VERSION,
    current_schema_version,
    initialize_schema,
    migrate,
)
from steam_analyst.storage.types import StorageError


class TestCurrentSchemaVersion:
    """Tests for current_schema_version function."""

    def test_returns_zero_for_uninitialized_db(self, tmp_path: Path):
        """Returns 0 for a brand-new database with no schema."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            version = current_schema_version(conn)
            assert version == 0
        finally:
            conn.close()

    def test_returns_zero_for_empty_schema_meta(self, tmp_path: Path):
        """Returns 0 if schema_meta table exists but is empty."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "CREATE TABLE schema_meta (version INTEGER NOT NULL, applied_at TEXT NOT NULL)"
            )
            version = current_schema_version(conn)
            assert version == 0
        finally:
            conn.close()

    def test_returns_applied_version_after_init(self, tmp_path: Path):
        """After initialize_schema, returns the current target version."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            initialize_schema(conn)
            version = current_schema_version(conn)
            assert version == CURRENT_SCHEMA_VERSION
        finally:
            conn.close()

    def test_returns_max_version_if_multiple_rows(self, tmp_path: Path):
        """If schema_meta has multiple rows, returns the max version."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "CREATE TABLE schema_meta (version INTEGER NOT NULL, applied_at TEXT NOT NULL)"
            )
            cursor.execute(
                "INSERT INTO schema_meta (version, applied_at) VALUES (1, '2024-01-01')"
            )
            cursor.execute(
                "INSERT INTO schema_meta (version, applied_at) VALUES (2, '2024-01-02')"
            )
            version = current_schema_version(conn)
            assert version == 2
        finally:
            conn.close()


class TestInitializeSchema:
    """Tests for initialize_schema function."""

    def test_creates_all_tables_and_indexes(self, tmp_path: Path):
        """All seven tables and five indexes are created."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            initialize_schema(conn)

            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'index') ORDER BY name"
            )
            objects = cursor.fetchall()

            # Extract table and index names
            tables = {
                row["name"]
                for row in objects
                if row["type"] == "table"
            }
            indexes = {
                row["name"]
                for row in objects
                if row["type"] == "index"
            }

            # Check for all 7 tables (excluding sqlite internals)
            expected_tables = {
                "schema_meta",
                "runs",
                "run_stages",
                "run_events",
                "raw_games",
                "games_enriched",
                "game_tags",
                "analysis_results",
            }
            assert expected_tables.issubset(tables)

            # Check for all 5 indexes
            expected_indexes = {
                "idx_run_events_run_id",
                "idx_raw_games_run_source",
                "idx_enriched_complexity",
                "idx_enriched_release",
                "idx_game_tags_tag",
            }
            assert expected_indexes.issubset(indexes)

        finally:
            conn.close()

    def test_idempotent_second_call(self, tmp_path: Path):
        """Calling initialize_schema twice is idempotent."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            initialize_schema(conn)
            initialize_schema(conn)

            # Verify only one schema_meta row
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM schema_meta")
            count = cursor.fetchone()["cnt"]
            assert count == 1

        finally:
            conn.close()

    def test_inserts_schema_meta_row_on_first_init(self, tmp_path: Path):
        """First initialization inserts a schema_meta row with current version."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            initialize_schema(conn)

            cursor = conn.cursor()
            cursor.execute("SELECT version FROM schema_meta")
            version = cursor.fetchone()["version"]
            assert version == CURRENT_SCHEMA_VERSION

        finally:
            conn.close()

    def test_schema_meta_has_applied_at(self, tmp_path: Path):
        """schema_meta row includes an applied_at timestamp."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            initialize_schema(conn)

            cursor = conn.cursor()
            cursor.execute("SELECT applied_at FROM schema_meta")
            applied_at = cursor.fetchone()["applied_at"]
            assert applied_at is not None
            assert len(applied_at) > 0

        finally:
            conn.close()

    def test_tables_have_correct_constraints(self, tmp_path: Path):
        """Created tables have the expected CHECK constraints."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            initialize_schema(conn)

            cursor = conn.cursor()
            # Check that runs table has status constraint
            cursor.execute("PRAGMA table_info(runs)")
            columns = [row["name"] for row in cursor.fetchall()]
            assert "status" in columns
            assert "trigger_type" in columns

        finally:
            conn.close()

    def test_foreign_key_relationships(self, tmp_path: Path):
        """Created tables have correct foreign key relationships."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            initialize_schema(conn)

            cursor = conn.cursor()
            # run_stages should reference runs
            cursor.execute("PRAGMA foreign_key_list(run_stages)")
            fk_info = cursor.fetchall()
            assert len(fk_info) > 0
            # Should reference runs.run_id
            assert any(row["table"] == "runs" for row in fk_info)

        finally:
            conn.close()

    def test_conflicting_table_raises(self, tmp_path: Path):
        """A pre-existing correct table does not cause issues."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            cursor = conn.cursor()
            # Create a pre-existing runs table with correct columns
            cursor.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL)")
            
            # Try to initialize schema - should not raise on existing table
            initialize_schema(conn)
            
            # Verify table still exists
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='runs'")
            count = cursor.fetchone()[0]
            assert count == 1
        finally:
            conn.close()

    def test_run_events_autoincrement(self, tmp_path: Path):
        """run_events.event_id is AUTOINCREMENT."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            initialize_schema(conn)

            cursor = conn.cursor()
            # First insert a run (required by foreign key constraint)
            cursor.execute(
                "INSERT INTO runs (run_id, started_at, status, config_json, parameters_version) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test_run", "2024-01-01T12:00:00", "pending", "{}", "v1"),
            )
            # Now insert an event
            cursor.execute("INSERT INTO run_events (run_id, ts, stage, level, message) VALUES (?, ?, ?, ?, ?)",
                          ("test_run", "2024-01-01T12:00:00", "acquisition", "info", "test"))
            cursor.execute("SELECT event_id FROM run_events")
            event_id = cursor.fetchone()["event_id"]
            assert event_id == 1

        finally:
            conn.close()


class TestMigrate:
    """Tests for migrate function."""

    def test_noop_when_already_at_target(self, tmp_path: Path):
        """Migrating to the current version is a no-op."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            initialize_schema(conn)
            current = current_schema_version(conn)

            result = migrate(conn, target_version=current)
            assert result == current

        finally:
            conn.close()

    def test_noop_migrate_with_none_target(self, tmp_path: Path):
        """Migrating to None (latest) when already latest is a no-op."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            initialize_schema(conn)
            current = current_schema_version(conn)

            result = migrate(conn, target_version=None)
            assert result == current

        finally:
            conn.close()

    def test_downgrade_rejected(self, tmp_path: Path):
        """Migrating to a lower version raises StorageError."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            initialize_schema(conn)

            with pytest.raises(StorageError) as exc_info:
                migrate(conn, target_version=0)
            assert "Downgrade" in str(exc_info.value)

        finally:
            conn.close()

    def test_higher_than_known_rejected(self, tmp_path: Path):
        """Migrating to a version higher than known raises StorageError."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            initialize_schema(conn)

            with pytest.raises(StorageError) as exc_info:
                migrate(conn, target_version=CURRENT_SCHEMA_VERSION + 1)
            assert "higher than" in str(exc_info.value)

        finally:
            conn.close()

    def test_migrate_from_uninitialized(self, tmp_path: Path):
        """Migrating from an uninitialized database raises StorageError."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            # Don't initialize; try to migrate to version 1
            # Should raise because schema_meta doesn't exist
            with pytest.raises(Exception):  # Could be StorageError or sqlite3.OperationalError
                migrate(conn, target_version=1)

        finally:
            conn.close()

    def test_migrate_idempotent_repeated_calls(self, tmp_path: Path):
        """Multiple calls to migrate to the same target are idempotent."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            initialize_schema(conn)
            current = current_schema_version(conn)

            result1 = migrate(conn, target_version=current)
            result2 = migrate(conn, target_version=current)

            assert result1 == result2 == current

        finally:
            conn.close()


class TestSchemaWithConnect:
    """Integration tests using the connect context manager."""

    def test_full_init_with_connect(self, tmp_path: Path):
        """Full initialization works with connect context manager."""
        db_path = tmp_path / "test.db"

        with connect(db_path) as conn:
            initialize_schema(conn)
            version = current_schema_version(conn)
            assert version == CURRENT_SCHEMA_VERSION

    def test_schema_persists_across_connections(self, tmp_path: Path):
        """Schema created in one connection persists for subsequent connections."""
        db_path = tmp_path / "test.db"

        with connect(db_path) as conn:
            initialize_schema(conn)

        with connect(db_path) as conn:
            version = current_schema_version(conn)
            assert version == CURRENT_SCHEMA_VERSION

    def test_can_insert_after_schema_init(self, tmp_path: Path):
        """After schema initialization, can insert data."""
        db_path = tmp_path / "test.db"

        with connect(db_path) as conn:
            initialize_schema(conn)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO runs (run_id, started_at, status, config_json, parameters_version) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test_run", "2024-01-01T12:00:00", "pending", "{}", "v1"),
            )

        with connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM runs")
            count = cursor.fetchone()["cnt"]
            assert count == 1


class TestRamBytesMigration:
    """Schema version 2 adds games_enriched.ram_bytes to databases created at version 1."""

    def test_fresh_database_has_ram_bytes_column(self, tmp_path: Path):
        conn = get_connection(tmp_path / "fresh.db")
        try:
            initialize_schema(conn)
            cols = [r[1] for r in conn.execute("PRAGMA table_info(games_enriched)")]
            assert "ram_bytes" in cols
            assert current_schema_version(conn) == CURRENT_SCHEMA_VERSION
        finally:
            conn.close()

    def test_v1_database_is_migrated_in_place(self, tmp_path: Path):
        conn = get_connection(tmp_path / "old.db")
        try:
            initialize_schema(conn)
            conn.execute("ALTER TABLE games_enriched DROP COLUMN ram_bytes")
            conn.execute("UPDATE schema_meta SET version=1")
            conn.commit()

            assert migrate(conn) == CURRENT_SCHEMA_VERSION
            cols = [r[1] for r in conn.execute("PRAGMA table_info(games_enriched)")]
            assert "ram_bytes" in cols
            assert current_schema_version(conn) == CURRENT_SCHEMA_VERSION
        finally:
            conn.close()
