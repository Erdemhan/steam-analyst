"""
SQLite schema initialization, versioning, and migration management.

This module handles creation of the complete database schema, tracking the
schema version via the schema_meta table, and applying ordered migrations.
"""

import sqlite3
from datetime import datetime

from .types import StorageError

# The current schema version this codebase expects.
# Increment this when the schema changes and add a corresponding migration.
CURRENT_SCHEMA_VERSION = 2


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create the full schema if it does not already exist.

    Idempotent: safe to call on every process start. Creates all seven tables
    (schema_meta, runs, run_stages, run_events, raw_games, games_enriched,
    game_tags, analysis_results) and five indexes if absent, then stamps
    schema_meta with the current version if this is the first initialization.

    Args:
        conn: An open connection from get_connection.

    Raises:
        StorageError: If table creation fails for a reason other than
            'already exists' (e.g., a conflicting, incompatible table
            already present under the same name with a different shape).
    """
    cursor = conn.cursor()

    try:
        # schema_meta: version tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_meta (
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL
            )
        """)

        # runs: main run records
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL CHECK(status IN ('pending','running','succeeded','failed','cancelled')),
                trigger_type TEXT NOT NULL DEFAULT 'manual' CHECK(trigger_type IN ('manual','scheduled')),
                parent_run_id TEXT REFERENCES runs(run_id),
                config_json TEXT NOT NULL,
                parameters_version TEXT NOT NULL,
                code_version TEXT,
                error_message TEXT,
                notes TEXT
            )
        """)

        # run_stages: per-stage status tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS run_stages (
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                stage TEXT NOT NULL CHECK(stage IN ('acquisition','enrichment','analysis')),
                status TEXT NOT NULL CHECK(status IN ('pending','running','succeeded','failed','cancelled')),
                started_at TEXT,
                finished_at TEXT,
                attempt INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                PRIMARY KEY (run_id, stage)
            )
        """)

        # run_events: append-only event log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS run_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                ts TEXT NOT NULL,
                stage TEXT NOT NULL,
                level TEXT NOT NULL CHECK(level IN ('debug','info','warning','error')),
                message TEXT NOT NULL,
                progress REAL
            )
        """)

        # raw_games: immutable fetched payloads
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_games (
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                appid INTEGER NOT NULL,
                source TEXT NOT NULL CHECK(source IN ('steamspy_all','steamspy_appdetails','steam_appdetails','steam_reviews')),
                fetched_at TEXT NOT NULL,
                http_status INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                PRIMARY KEY (run_id, appid, source)
            )
        """)

        # games_enriched: post-enrichment features
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS games_enriched (
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                appid INTEGER NOT NULL,
                name TEXT,
                app_type TEXT,
                developer TEXT,
                publisher TEXT,
                release_date TEXT,
                price_usd REAL,
                is_free INTEGER,
                review_count INTEGER,
                review_positive_pct REAL,
                owners_estimate_low INTEGER,
                owners_estimate_mid INTEGER,
                owners_estimate_high INTEGER,
                size_bytes INTEGER,
                ram_bytes INTEGER,
                achievement_count INTEGER,
                language_count INTEGER,
                platform_count INTEGER,
                dlc_count INTEGER,
                dev_title_count INTEGER,
                is_early_access INTEGER,
                early_access_days INTEGER,
                deck_compat TEXT,
                genres_json TEXT,
                categories_json TEXT,
                complexity_score REAL,
                imputed_features_json TEXT,
                estimated_sales_low REAL,
                estimated_sales_mid REAL,
                estimated_sales_high REAL,
                estimated_revenue_gross_usd REAL,
                estimated_revenue_net_usd REAL,
                effort_adjusted_return REAL,
                parameters_version TEXT NOT NULL,
                PRIMARY KEY (run_id, appid)
            )
        """)

        # game_tags: community tags
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_tags (
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                appid INTEGER NOT NULL,
                tag TEXT NOT NULL,
                votes INTEGER,
                rank INTEGER,
                PRIMARY KEY (run_id, appid, tag)
            )
        """)

        # analysis_results: analysis outputs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_results (
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                analysis_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                parameters_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (run_id, analysis_type)
            )
        """)

        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_run_events_run_id
            ON run_events(run_id, event_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_raw_games_run_source
            ON raw_games(run_id, source)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_enriched_complexity
            ON games_enriched(run_id, complexity_score)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_enriched_release
            ON games_enriched(run_id, release_date)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_game_tags_tag
            ON game_tags(run_id, tag)
        """)

        # Initialize schema_meta if empty
        cursor.execute("SELECT COUNT(*) as cnt FROM schema_meta")
        row = cursor.fetchone()
        if row is None or row[0] == 0:
            # First initialization
            now = datetime.utcnow().isoformat()
            cursor.execute(
                "INSERT INTO schema_meta (version, applied_at) VALUES (?, ?)",
                (CURRENT_SCHEMA_VERSION, now),
            )

        conn.commit()

    except sqlite3.DatabaseError as e:
        conn.rollback()
        raise StorageError(f"Schema initialization failed: {e}") from e
    except Exception as e:
        conn.rollback()
        raise StorageError(f"Unexpected error during schema initialization: {e}") from e


def current_schema_version(conn: sqlite3.Connection) -> int:
    """Return the schema version currently applied to this database.

    Reads the most recent schema version from the schema_meta table.
    If schema_meta does not exist or is empty, returns 0 (indicating
    a database that has never been initialized).

    If schema_meta has multiple rows (which should not normally happen),
    returns the maximum version present.

    Args:
        conn: An open connection.

    Returns:
        An integer >= 0. Returns 0 if schema_meta is missing or empty.
    """
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT MAX(version) FROM schema_meta")
        row = cursor.fetchone()
        if row is None or row[0] is None:
            return 0
        return row[0]
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        return 0


def migrate(conn: sqlite3.Connection, target_version: int | None = None) -> int:
    """Apply pending migrations in order.

    Reads the current schema version and applies all migrations up to
    target_version (or CURRENT_SCHEMA_VERSION if target_version is None).
    Each migration step runs in its own transaction; if a step fails,
    that transaction is rolled back but earlier steps remain committed.

    Args:
        conn: An open connection.
        target_version: Version to migrate to. None means the latest version
            this codebase knows about (CURRENT_SCHEMA_VERSION).

    Returns:
        The resulting schema version after all applicable migrations.

    Raises:
        StorageError: If target_version is lower than the current version
            (downgrade unsupported), if target_version is higher than
            CURRENT_SCHEMA_VERSION, or if any individual migration step fails.
    """
    if target_version is None:
        target_version = CURRENT_SCHEMA_VERSION

    current = current_schema_version(conn)

    if target_version < current:
        raise StorageError(
            f"Downgrade unsupported: current version is {current}, "
            f"cannot migrate to {target_version}"
        )

    if target_version > CURRENT_SCHEMA_VERSION:
        raise StorageError(
            f"Target version {target_version} is higher than the latest known version "
            f"{CURRENT_SCHEMA_VERSION}"
        )

    if target_version == current:
        # Already at target, no-op
        return current

    # Define migration steps: version -> SQL statements to apply
    # Version 1 is the initial schema; version 2 adds games_enriched.ram_bytes.
    migrations = {
        2: [
            "ALTER TABLE games_enriched ADD COLUMN ram_bytes INTEGER",
            "UPDATE schema_meta SET version=2, applied_at=datetime('now')",
        ],
    }

    # Apply each migration in order
    for version in range(current + 1, target_version + 1):
        if version not in migrations:
            # If no migration defined for this version and it's beyond current,
            # just update the schema version
            cursor = conn.cursor()
            try:
                now = datetime.utcnow().isoformat()
                cursor.execute(
                    "UPDATE schema_meta SET version=?, applied_at=?",
                    (version, now),
                )
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                raise StorageError(f"Migration to version {version} failed: {e}") from e
        else:
            # Apply the migration steps for this version
            cursor = conn.cursor()
            try:
                for sql in migrations[version]:
                    cursor.execute(sql)
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                raise StorageError(f"Migration to version {version} failed: {e}") from e

    return target_version
