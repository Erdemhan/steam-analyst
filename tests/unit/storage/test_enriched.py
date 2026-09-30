"""
Unit tests for enriched data storage operations.

Tests both write_enriched and read_enriched across a wide range of scenarios,
including dtype preservation, NULL handling, transactional behavior, and
column validation.
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from steam_analyst.storage import schema, runs, enriched
from steam_analyst.storage.connection import get_connection
from steam_analyst.storage.types import StorageError


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create and initialize a temporary test database."""
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    try:
        schema.initialize_schema(conn)
    finally:
        conn.close()
    return db_path


@pytest.fixture
def conn_and_run(temp_db: Path) -> tuple[sqlite3.Connection, str]:
    """Create a connection with an initialized schema and a test run."""
    conn = get_connection(temp_db)
    run_id = runs.create_run(
        conn,
        config={"test": True},
        parameters_version="test_v1",
    )
    return conn, run_id


def _make_enriched_frame(
    appids: list[int],
    complexity_scores: list[float | None] = None,
    review_counts: list[int | None] = None,
) -> pd.DataFrame:
    """Create a minimal enriched DataFrame with required columns.

    All columns present but nullable columns filled with None/NaN as appropriate.
    """
    n = len(appids)

    # Default values: complexity_score NaN, review_count None
    if complexity_scores is None:
        complexity_scores = [float("nan")] * n
    if review_counts is None:
        review_counts = [None] * n

    data = {
        "appid": appids,
        "name": [f"Game {appid}" for appid in appids],
        "app_type": ["Application"] * n,
        "developer": ["Dev Corp"] * n,
        "publisher": ["Pub Corp"] * n,
        "release_date": ["2023-01-01"] * n,
        "price_usd": [9.99] * n,
        "is_free": [0] * n,
        "review_count": review_counts,
        "review_positive_pct": [75.5] * n,
        "owners_estimate_low": [1000] * n,
        "owners_estimate_mid": [5000] * n,
        "owners_estimate_high": [10000] * n,
        "size_bytes": [2000000000] * n,
        "ram_bytes": [4000000000] * n,
        "achievement_count": [50] * n,
        "language_count": [5] * n,
        "platform_count": [1] * n,
        "dlc_count": [3] * n,
        "dev_title_count": [5] * n,
        "is_early_access": [0] * n,
        "early_access_days": [None] * n,
        "deck_compat": ["Verified"] * n,
        "genres_json": ["[1, 2, 3]"] * n,
        "categories_json": ["[4, 5]"] * n,
        "complexity_score": complexity_scores,
        "imputed_features_json": ["{}"] * n,
        "estimated_sales_low": [100.0] * n,
        "estimated_sales_mid": [500.0] * n,
        "estimated_sales_high": [1000.0] * n,
        "estimated_revenue_gross_usd": [5000.0] * n,
        "estimated_revenue_net_usd": [3000.0] * n,
        "effort_adjusted_return": [0.5] * n,
        "parameters_version": ["test_v1"] * n,
    }

    return pd.DataFrame(data)


class TestWriteEnriched:
    """Tests for write_enriched function."""

    def test_write_then_read_preserves_dtypes_and_nulls(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """A frame with NaN complexity_score round-trips with None preserved."""
        conn, run_id = conn_and_run

        # Create frame with explicit NaN in complexity_score
        frame = _make_enriched_frame([123, 456], complexity_scores=[0.5, float("nan")])

        # Write
        n_written = enriched.write_enriched(conn, run_id, frame)
        assert n_written == 2

        # Read back
        result = enriched.read_enriched(conn, run_id)
        assert len(result) == 2

        # Check first row has the complexity_score value
        assert result[result["appid"] == 123]["complexity_score"].iloc[0] == 0.5

        # Check second row has None (SQL NULL becomes None in pandas)
        complexity_val = result[result["appid"] == 456]["complexity_score"].iloc[0]
        assert pd.isna(complexity_val), "NaN should round-trip as NA/None"

    def test_empty_frame_writes_zero_rows(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """An empty DataFrame with correct columns writes 0 rows."""
        conn, run_id = conn_and_run

        # Create empty frame with all required columns
        frame = _make_enriched_frame([])
        assert len(frame) == 0

        # Write empty frame
        n_written = enriched.write_enriched(conn, run_id, frame)
        assert n_written == 0

        # Read back
        result = enriched.read_enriched(conn, run_id)
        assert len(result) == 0

    def test_rerun_replaces_prior_rows(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """Writing a new frame for a run_id removes old rows entirely."""
        conn, run_id = conn_and_run

        # First write: 2 games
        frame1 = _make_enriched_frame([100, 200])
        n1 = enriched.write_enriched(conn, run_id, frame1)
        assert n1 == 2

        # Second write: 1 game (different app, overlaps with none of the first)
        frame2 = _make_enriched_frame([300])
        n2 = enriched.write_enriched(conn, run_id, frame2)
        assert n2 == 1

        # Read back: should have only the second frame's data
        result = enriched.read_enriched(conn, run_id)
        assert len(result) == 1
        assert result["appid"].iloc[0] == 300

        # Original appids should be gone
        assert 100 not in result["appid"].values
        assert 200 not in result["appid"].values

    def test_missing_column_raises(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """A frame lacking a required column raises StorageError."""
        conn, run_id = conn_and_run

        # Create frame and drop a required column
        frame = _make_enriched_frame([123])
        frame = frame.drop(columns=["complexity_score"])

        # Should raise StorageError
        with pytest.raises(StorageError, match="missing required columns"):
            enriched.write_enriched(conn, run_id, frame)

    def test_duplicate_appid_raises(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """A frame with duplicate appid values raises StorageError."""
        conn, run_id = conn_and_run

        # Create frame with duplicate appid
        frame = _make_enriched_frame([123, 123])
        assert frame["appid"].duplicated().any()

        # Should raise StorageError
        with pytest.raises(StorageError, match="duplicate appid"):
            enriched.write_enriched(conn, run_id, frame)

    def test_nonexistent_run_id_raises(
        self, temp_db: Path
    ) -> None:
        """Writing to a nonexistent run_id raises StorageError."""
        conn = get_connection(temp_db)
        try:
            schema.initialize_schema(conn)

            frame = _make_enriched_frame([123])

            # Should raise StorageError
            with pytest.raises(StorageError, match="does not exist"):
                enriched.write_enriched(conn, "nonexistent_run_id", frame)
        finally:
            conn.close()

    def test_multiple_games_preserves_all_values(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """Multiple games are written with all values preserved."""
        conn, run_id = conn_and_run

        # Create frame with specific values we can check
        frame = _make_enriched_frame(
            [123, 456, 789],
            complexity_scores=[0.2, 0.5, 0.9],
            review_counts=[100, None, 500],
        )

        n_written = enriched.write_enriched(conn, run_id, frame)
        assert n_written == 3

        # Read back all
        result = enriched.read_enriched(conn, run_id)
        assert len(result) == 3

        # Check each row's values
        for idx, (appid, complexity, reviews) in enumerate(
            [(123, 0.2, 100), (456, 0.5, None), (789, 0.9, 500)]
        ):
            row = result[result["appid"] == appid].iloc[0]
            assert row["complexity_score"] == complexity
            if reviews is None:
                assert pd.isna(row["review_count"])
            else:
                assert row["review_count"] == reviews


class TestReadEnriched:
    """Tests for read_enriched function."""

    def test_read_all_columns_default(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """columns=None returns every games_enriched column."""
        conn, run_id = conn_and_run

        # Write some data
        frame = _make_enriched_frame([123])
        enriched.write_enriched(conn, run_id, frame)

        # Read with no column spec
        result = enriched.read_enriched(conn, run_id, columns=None)

        # Should have all columns except run_id (which is implicit in the WHERE clause)
        # Actually, run_id is selected too; check what we expect
        expected_cols = [
            "run_id",
            "appid",
            "name",
            "app_type",
            "developer",
            "publisher",
            "release_date",
            "price_usd",
            "is_free",
            "review_count",
            "review_positive_pct",
            "owners_estimate_low",
            "owners_estimate_mid",
            "owners_estimate_high",
            "size_bytes",
            "ram_bytes",
            "achievement_count",
            "language_count",
            "platform_count",
            "dlc_count",
            "dev_title_count",
            "is_early_access",
            "early_access_days",
            "deck_compat",
            "genres_json",
            "categories_json",
            "complexity_score",
            "imputed_features_json",
            "estimated_sales_low",
            "estimated_sales_mid",
            "estimated_sales_high",
            "estimated_revenue_gross_usd",
            "estimated_revenue_net_usd",
            "effort_adjusted_return",
            "parameters_version",
        ]
        assert set(result.columns) == set(expected_cols)
        assert len(result) == 1

    def test_read_projected_columns(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """columns=['appid','complexity_score'] returns exactly those two columns."""
        conn, run_id = conn_and_run

        # Write some data
        frame = _make_enriched_frame([123, 456])
        enriched.write_enriched(conn, run_id, frame)

        # Read with specific columns
        result = enriched.read_enriched(
            conn, run_id, columns=["appid", "complexity_score"]
        )

        assert list(result.columns) == ["appid", "complexity_score"]
        assert len(result) == 2

    def test_where_filters_rows(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """where clause restricts the returned rows correctly."""
        conn, run_id = conn_and_run

        # Write data with different complexity scores
        frame = _make_enriched_frame(
            [100, 200, 300],
            complexity_scores=[0.2, 0.5, 0.9],
        )
        enriched.write_enriched(conn, run_id, frame)

        # Read with WHERE filter
        result = enriched.read_enriched(
            conn, run_id, where="complexity_score < 0.4"
        )

        assert len(result) == 1  # Only 0.2 < 0.4
        assert result["appid"].iloc[0] == 100

    def test_where_and_columns_together(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """WHERE and columns can be used together."""
        conn, run_id = conn_and_run

        # Write data
        frame = _make_enriched_frame(
            [100, 200, 300],
            complexity_scores=[0.2, 0.5, 0.9],
        )
        enriched.write_enriched(conn, run_id, frame)

        # Read with both WHERE and columns
        result = enriched.read_enriched(
            conn,
            run_id,
            columns=["appid", "name"],
            where="complexity_score >= 0.5",
        )

        assert list(result.columns) == ["appid", "name"]
        assert len(result) == 2  # 0.5 and 0.9
        appids = set(result["appid"].values)
        assert appids == {200, 300}

    def test_unknown_column_raises(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """An unknown column name in `columns` raises StorageError."""
        conn, run_id = conn_and_run

        # Try to read a nonexistent column
        with pytest.raises(StorageError, match="Unknown column"):
            enriched.read_enriched(conn, run_id, columns=["not_a_real_column"])

    def test_empty_run_returns_empty_dataframe(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """Reading a run with no enriched rows returns empty DataFrame."""
        conn, run_id = conn_and_run

        # Read without writing anything
        result = enriched.read_enriched(conn, run_id)

        assert len(result) == 0
        # Should have all columns
        assert "appid" in result.columns

    def test_column_order_preserved(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """Column order is preserved when projecting."""
        conn, run_id = conn_and_run

        # Write data
        frame = _make_enriched_frame([123])
        enriched.write_enriched(conn, run_id, frame)

        # Read with columns in specific order
        cols_requested = ["price_usd", "appid", "name"]
        result = enriched.read_enriched(conn, run_id, columns=cols_requested)

        assert list(result.columns) == cols_requested

    def test_where_with_column_not_in_projection(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """WHERE can filter on a column not in the projected output."""
        conn, run_id = conn_and_run

        # Write data
        frame = _make_enriched_frame(
            [100, 200, 300],
            complexity_scores=[0.2, 0.5, 0.9],
        )
        enriched.write_enriched(conn, run_id, frame)

        # Read: project name/appid, but filter on complexity_score
        result = enriched.read_enriched(
            conn,
            run_id,
            columns=["appid", "name"],
            where="complexity_score > 0.6",
        )

        # Should have only name and appid columns
        assert list(result.columns) == ["appid", "name"]
        # But should be filtered by complexity_score
        assert len(result) == 1
        assert result["appid"].iloc[0] == 300


class TestWriteReadRoundTrip:
    """Tests for complete write/read round-trip scenarios."""

    def test_null_handling_roundtrip(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """Various NULL scenarios round-trip correctly."""
        conn, run_id = conn_and_run

        # Create frame with specific NULL patterns
        data = {
            "appid": [1, 2, 3],
            "name": ["Game1", None, "Game3"],  # None in name
            "app_type": ["Application", "Application", "Application"],
            "developer": ["Dev1", "Dev2", "Dev3"],
            "publisher": ["Pub1", "Pub2", "Pub3"],
            "release_date": ["2023-01-01", None, "2023-03-01"],  # None in date
            "price_usd": [9.99, None, 19.99],  # None in price
            "is_free": [0, None, 0],
            "review_count": [100, 200, None],  # None in review_count
            "review_positive_pct": [75.5, None, 85.0],
            "owners_estimate_low": [1000, None, 3000],
            "owners_estimate_mid": [5000, None, 15000],
            "owners_estimate_high": [10000, None, 30000],
            "size_bytes": [2000000000, None, 3000000000],
            "ram_bytes": [2000000000, None, 3000000000],
            "achievement_count": [50, None, 100],
            "language_count": [5, None, 10],
            "platform_count": [1, None, 2],
            "dlc_count": [3, None, 5],
            "dev_title_count": [5, None, 10],
            "is_early_access": [0, None, 1],
            "early_access_days": [None, None, None],
            "deck_compat": ["Verified", None, "Unsupported"],
            "genres_json": ["[1,2]", None, "[3,4]"],
            "categories_json": ["[5]", None, "[6]"],
            "complexity_score": [0.5, None, 0.8],
            "imputed_features_json": ["{}", None, "{}"],
            "estimated_sales_low": [100.0, None, 300.0],
            "estimated_sales_mid": [500.0, None, 1500.0],
            "estimated_sales_high": [1000.0, None, 3000.0],
            "estimated_revenue_gross_usd": [5000.0, None, 15000.0],
            "estimated_revenue_net_usd": [3000.0, None, 9000.0],
            "effort_adjusted_return": [0.5, None, 0.7],
            "parameters_version": ["test_v1", "test_v1", "test_v1"],
        }
        frame = pd.DataFrame(data)

        # Write
        n_written = enriched.write_enriched(conn, run_id, frame)
        assert n_written == 3

        # Read
        result = enriched.read_enriched(conn, run_id)
        assert len(result) == 3

        # Verify each row's NULL values were preserved
        for app_id in [1, 2, 3]:
            row = result[result["appid"] == app_id].iloc[0]
            orig_row = frame[frame["appid"] == app_id].iloc[0]

            for col in frame.columns:
                if col == "appid":
                    continue
                orig_val = orig_row[col]
                read_val = row[col]

                if orig_val is None or (
                    isinstance(orig_val, float) and np.isnan(orig_val)
                ):
                    assert pd.isna(read_val), f"Column {col} for appid {app_id}: expected NA/None"
                else:
                    assert read_val == orig_val, f"Column {col} for appid {app_id}: value mismatch"

    def test_idempotence(
        self, conn_and_run: tuple[sqlite3.Connection, str]
    ) -> None:
        """Calling write_enriched twice with the same frame is idempotent."""
        conn, run_id = conn_and_run

        # Create frame
        frame = _make_enriched_frame([100, 200])

        # Write twice
        n1 = enriched.write_enriched(conn, run_id, frame)
        n2 = enriched.write_enriched(conn, run_id, frame)

        # Both should return the same count
        assert n1 == n2 == 2

        # Read result
        result = enriched.read_enriched(conn, run_id)

        # Should have exactly 2 rows
        assert len(result) == 2
        assert set(result["appid"].values) == {100, 200}
