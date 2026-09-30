"""
Unit tests for storage.tags module (write_tags, read_tags).
"""

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from steam_analyst.storage.connection import get_connection
from steam_analyst.storage.runs import create_run
from steam_analyst.storage.schema import initialize_schema
from steam_analyst.storage.tags import read_tags, write_tags
from steam_analyst.storage.types import StorageError, TagRow


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create a temporary database file."""
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path: Path):
    """Create a database connection with initialized schema."""
    connection = get_connection(db_path)
    initialize_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def run_id(conn: sqlite3.Connection) -> str:
    """Create a test run and return its ID."""
    return create_run(
        conn,
        config={"key": "value"},
        parameters_version="test_v1",
    )


class TestWriteTags:
    """Tests for write_tags function."""

    def test_write_then_read_tags(self, conn, run_id):
        """Written rows are exactly readable back via read_tags."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=50, rank=1),
            TagRow(appid=100, tag="Adventure", votes=30, rank=2),
            TagRow(appid=200, tag="Action", votes=100, rank=1),
        ]

        count = write_tags(conn, run_id, rows)
        assert count == 3

        # Read back and verify
        df = read_tags(conn, run_id)
        assert len(df) == 3

        # Verify columns
        assert list(df.columns) == ["appid", "tag", "votes", "rank"]

        # Verify data (should be sorted by appid, tag)
        expected = [
            {"appid": 100, "tag": "Adventure", "votes": 30, "rank": 2},
            {"appid": 100, "tag": "Indie", "votes": 50, "rank": 1},
            {"appid": 200, "tag": "Action", "votes": 100, "rank": 1},
        ]
        for i, exp in enumerate(expected):
            assert df.iloc[i]["appid"] == exp["appid"]
            assert df.iloc[i]["tag"] == exp["tag"]
            assert df.iloc[i]["votes"] == exp["votes"]
            assert df.iloc[i]["rank"] == exp["rank"]

    def test_write_tags_with_null_votes(self, conn, run_id):
        """A TagRow with votes=None is stored as SQL NULL and round-trips correctly."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=None, rank=1),
            TagRow(appid=100, tag="Adventure", votes=50, rank=2),
        ]

        count = write_tags(conn, run_id, rows)
        assert count == 2

        # Read back with min_votes=0 (default) to include NULL
        df = read_tags(conn, run_id, min_votes=0)
        assert len(df) == 2

        # Find the row with NULL votes
        null_vote_row = df[df["tag"] == "Indie"].iloc[0]
        assert pd.isna(null_vote_row["votes"])
        assert null_vote_row["rank"] == 1

    def test_write_tags_with_null_rank(self, conn, run_id):
        """A TagRow with rank=None is stored as SQL NULL and round-trips correctly."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=50, rank=None),
            TagRow(appid=100, tag="Adventure", votes=30, rank=2),
        ]

        count = write_tags(conn, run_id, rows)
        assert count == 2

        df = read_tags(conn, run_id)
        assert len(df) == 2

        # Find the row with NULL rank
        null_rank_row = df[df["tag"] == "Indie"].iloc[0]
        assert null_rank_row["votes"] == 50
        assert pd.isna(null_rank_row["rank"])

    def test_write_tags_with_null_votes_and_rank(self, conn, run_id):
        """A TagRow with both votes=None and rank=None round-trips correctly."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=None, rank=None),
        ]

        count = write_tags(conn, run_id, rows)
        assert count == 1

        df = read_tags(conn, run_id, min_votes=0)
        assert len(df) == 1

        row = df.iloc[0]
        assert row["appid"] == 100
        assert row["tag"] == "Indie"
        assert pd.isna(row["votes"])
        assert pd.isna(row["rank"])

    def test_duplicate_pair_raises(self, conn, run_id):
        """Two TagRow entries with the same (appid, tag) raise StorageError."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=50, rank=1),
            TagRow(appid=100, tag="Indie", votes=60, rank=2),
        ]

        with pytest.raises(StorageError) as exc_info:
            write_tags(conn, run_id, rows)
        assert "duplicate" in str(exc_info.value).lower()
        assert "appid" in str(exc_info.value).lower()

    def test_empty_iterable_writes_zero(self, conn, run_id):
        """No rows given writes zero and returns 0."""
        count = write_tags(conn, run_id, [])
        assert count == 0

        # Verify no rows were written
        df = read_tags(conn, run_id)
        assert len(df) == 0

    def test_write_tags_unknown_run_id_raises(self, conn):
        """write_tags with an unknown run_id raises StorageError."""
        rows = [TagRow(appid=100, tag="Indie", votes=50, rank=1)]

        with pytest.raises(StorageError) as exc_info:
            write_tags(conn, "does-not-exist", rows)
        assert "does not exist" in str(exc_info.value).lower()

    def test_write_tags_replaces_prior_rows(self, conn, run_id):
        """Writing tags a second time atomically replaces prior rows."""
        # First write
        rows1 = [
            TagRow(appid=100, tag="Indie", votes=50, rank=1),
            TagRow(appid=100, tag="Adventure", votes=30, rank=2),
        ]
        write_tags(conn, run_id, rows1)

        # Second write (replaces)
        rows2 = [
            TagRow(appid=100, tag="Action", votes=80, rank=1),
        ]
        write_tags(conn, run_id, rows2)

        # Verify only new rows are present
        df = read_tags(conn, run_id)
        assert len(df) == 1
        assert df.iloc[0]["tag"] == "Action"
        assert df.iloc[0]["votes"] == 80

    def test_write_tags_multiple_tags_per_appid(self, conn, run_id):
        """Multiple rows for the same appid but different tags are allowed."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=50, rank=1),
            TagRow(appid=100, tag="Adventure", votes=30, rank=2),
            TagRow(appid=100, tag="2D", votes=20, rank=3),
        ]

        count = write_tags(conn, run_id, rows)
        assert count == 3

        df = read_tags(conn, run_id)
        assert len(df) == 3
        assert len(df[df["appid"] == 100]) == 3

    def test_write_tags_large_vote_count(self, conn, run_id):
        """Large vote counts are stored and retrieved correctly."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=1_000_000, rank=1),
        ]

        write_tags(conn, run_id, rows)

        df = read_tags(conn, run_id)
        assert df.iloc[0]["votes"] == 1_000_000


class TestReadTags:
    """Tests for read_tags function."""

    def test_min_votes_filters_correctly(self, conn, run_id):
        """Tags below min_votes threshold are excluded."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=5, rank=1),
            TagRow(appid=100, tag="Adventure", votes=15, rank=2),
            TagRow(appid=100, tag="Action", votes=25, rank=3),
        ]
        write_tags(conn, run_id, rows)

        # Read with min_votes=10
        df = read_tags(conn, run_id, min_votes=10)
        assert len(df) == 2

        # Verify we got the 15 and 25 rows
        votes = set(df["votes"])
        assert votes == {15, 25}
        assert 5 not in votes

    def test_default_returns_all_including_null_votes(self, conn, run_id):
        """min_votes=0 (default) includes a row with votes=NULL."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=None, rank=1),
            TagRow(appid=100, tag="Adventure", votes=50, rank=2),
            TagRow(appid=100, tag="Action", votes=100, rank=3),
        ]
        write_tags(conn, run_id, rows)

        # Read with default min_votes=0
        df = read_tags(conn, run_id)
        assert len(df) == 3

        # Verify the NULL-vote row is present
        null_vote_rows = df[pd.isna(df["votes"])]
        assert len(null_vote_rows) == 1
        assert null_vote_rows.iloc[0]["tag"] == "Indie"

    def test_min_votes_excludes_null_votes(self, conn, run_id):
        """min_votes=10 excludes rows with votes=NULL."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=None, rank=1),
            TagRow(appid=100, tag="Adventure", votes=50, rank=2),
            TagRow(appid=100, tag="Action", votes=5, rank=3),
        ]
        write_tags(conn, run_id, rows)

        # Read with min_votes=10
        df = read_tags(conn, run_id, min_votes=10)
        assert len(df) == 1

        # Verify only the 50-vote row is present
        assert df.iloc[0]["tag"] == "Adventure"
        assert df.iloc[0]["votes"] == 50

        # Verify NULL-vote row is excluded
        null_vote_rows = df[pd.isna(df["votes"])]
        assert len(null_vote_rows) == 0

    def test_empty_result_for_untagged_run(self, conn, run_id):
        """A run with zero game_tags rows returns an empty DataFrame."""
        df = read_tags(conn, run_id)
        assert len(df) == 0
        assert list(df.columns) == ["appid", "tag", "votes", "rank"]

    def test_read_tags_unknown_run_id(self, conn):
        """read_tags with an unknown run_id returns an empty DataFrame."""
        df = read_tags(conn, "does-not-exist")
        assert len(df) == 0
        assert list(df.columns) == ["appid", "tag", "votes", "rank"]

    def test_read_tags_dataframe_dtypes(self, conn, run_id):
        """DataFrame has correct column types."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=50, rank=1),
            TagRow(appid=200, tag="Adventure", votes=None, rank=2),
        ]
        write_tags(conn, run_id, rows)

        df = read_tags(conn, run_id, min_votes=0)

        # Verify columns exist and are in correct order
        assert list(df.columns) == ["appid", "tag", "votes", "rank"]

    def test_read_tags_sorted_by_appid_then_tag(self, conn, run_id):
        """Results are sorted by appid then tag."""
        rows = [
            TagRow(appid=200, tag="Zebra", votes=50, rank=1),
            TagRow(appid=100, tag="Adventure", votes=50, rank=1),
            TagRow(appid=100, tag="Indie", votes=50, rank=1),
            TagRow(appid=200, tag="Action", votes=50, rank=1),
        ]
        write_tags(conn, run_id, rows)

        df = read_tags(conn, run_id)

        # Verify sorting
        expected_order = [
            (100, "Adventure"),
            (100, "Indie"),
            (200, "Action"),
            (200, "Zebra"),
        ]
        for i, (exp_appid, exp_tag) in enumerate(expected_order):
            assert df.iloc[i]["appid"] == exp_appid
            assert df.iloc[i]["tag"] == exp_tag

    def test_read_tags_with_min_votes_zero(self, conn, run_id):
        """Explicit min_votes=0 includes all rows including NULL votes."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=None, rank=1),
            TagRow(appid=100, tag="Adventure", votes=0, rank=2),
        ]
        write_tags(conn, run_id, rows)

        # Explicit min_votes=0
        df = read_tags(conn, run_id, min_votes=0)
        assert len(df) == 2

        # Verify both rows are included
        tags = set(df["tag"])
        assert tags == {"Indie", "Adventure"}

    def test_read_tags_with_min_votes_one(self, conn, run_id):
        """min_votes=1 excludes votes=0 and votes=NULL."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=None, rank=1),
            TagRow(appid=100, tag="Adventure", votes=0, rank=2),
            TagRow(appid=100, tag="Action", votes=1, rank=3),
        ]
        write_tags(conn, run_id, rows)

        # Read with min_votes=1
        df = read_tags(conn, run_id, min_votes=1)
        assert len(df) == 1

        # Only the 1-vote row should be included
        assert df.iloc[0]["tag"] == "Action"

    def test_read_tags_empty_dataframe_has_correct_columns_and_dtypes(self, conn, run_id):
        """Empty DataFrame has correct column names."""
        df = read_tags(conn, run_id)
        assert list(df.columns) == ["appid", "tag", "votes", "rank"]
        assert len(df) == 0

    def test_read_tags_multiple_appids(self, conn, run_id):
        """Tags from multiple appids are returned correctly."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=50, rank=1),
            TagRow(appid=200, tag="Action", votes=60, rank=1),
            TagRow(appid=300, tag="Adventure", votes=70, rank=1),
        ]
        write_tags(conn, run_id, rows)

        df = read_tags(conn, run_id)
        assert len(df) == 3

        appids = set(df["appid"])
        assert appids == {100, 200, 300}


class TestWriteTagsEdgeCases:
    """Additional edge case tests for write_tags."""

    def test_write_tags_with_special_characters_in_tag(self, conn, run_id):
        """Tag strings with special characters are stored and retrieved correctly."""
        rows = [
            TagRow(appid=100, tag="2D", votes=50, rank=1),
            TagRow(appid=100, tag="co-op", votes=40, rank=2),
            TagRow(appid=100, tag="RPG/Action", votes=30, rank=3),
        ]

        count = write_tags(conn, run_id, rows)
        assert count == 3

        df = read_tags(conn, run_id)
        assert len(df) == 3

        tags = set(df["tag"])
        assert tags == {"2D", "co-op", "RPG/Action"}

    def test_write_tags_is_idempotent(self, conn, run_id):
        """Writing the same tags twice produces the same result."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=50, rank=1),
        ]

        count1 = write_tags(conn, run_id, rows)
        count2 = write_tags(conn, run_id, rows)

        assert count1 == 1
        assert count2 == 1

        df = read_tags(conn, run_id)
        assert len(df) == 1

    def test_duplicate_pair_three_times_raises(self, conn, run_id):
        """Even if the same pair appears three times, StorageError is raised."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=50, rank=1),
            TagRow(appid=100, tag="Indie", votes=60, rank=2),
            TagRow(appid=100, tag="Indie", votes=70, rank=3),
        ]

        with pytest.raises(StorageError):
            write_tags(conn, run_id, rows)


class TestReadTagsEdgeCases:
    """Additional edge case tests for read_tags."""

    def test_read_tags_multiple_runs_isolated(self, conn):
        """Tags from different runs are properly isolated."""
        run_id_1 = create_run(conn, config={}, parameters_version="v1")
        run_id_2 = create_run(conn, config={}, parameters_version="v1")

        rows_1 = [TagRow(appid=100, tag="Indie", votes=50, rank=1)]
        rows_2 = [TagRow(appid=200, tag="Action", votes=60, rank=1)]

        write_tags(conn, run_id_1, rows_1)
        write_tags(conn, run_id_2, rows_2)

        df_1 = read_tags(conn, run_id_1)
        df_2 = read_tags(conn, run_id_2)

        assert len(df_1) == 1
        assert df_1.iloc[0]["appid"] == 100

        assert len(df_2) == 1
        assert df_2.iloc[0]["appid"] == 200

    def test_read_tags_with_zero_vote_and_min_votes_zero(self, conn, run_id):
        """A tag with votes=0 and min_votes=0 is included."""
        rows = [TagRow(appid=100, tag="Indie", votes=0, rank=1)]
        write_tags(conn, run_id, rows)

        df = read_tags(conn, run_id, min_votes=0)
        assert len(df) == 1
        assert df.iloc[0]["votes"] == 0

    def test_read_tags_with_high_min_votes(self, conn, run_id):
        """All tags below a high min_votes threshold are excluded."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=10, rank=1),
            TagRow(appid=100, tag="Adventure", votes=20, rank=2),
            TagRow(appid=100, tag="Action", votes=30, rank=3),
        ]
        write_tags(conn, run_id, rows)

        # Read with min_votes=1000 (all votes below this)
        df = read_tags(conn, run_id, min_votes=1000)
        assert len(df) == 0

    def test_read_tags_all_null_votes_with_min_votes_zero(self, conn, run_id):
        """When all votes are NULL and min_votes=0, all rows are returned."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=None, rank=1),
            TagRow(appid=100, tag="Adventure", votes=None, rank=2),
            TagRow(appid=100, tag="Action", votes=None, rank=3),
        ]
        write_tags(conn, run_id, rows)

        df = read_tags(conn, run_id, min_votes=0)
        assert len(df) == 3

        # Verify all have NULL votes
        assert pd.isna(df["votes"]).all()

    def test_read_tags_all_null_votes_with_min_votes_one(self, conn, run_id):
        """When all votes are NULL and min_votes>0, no rows are returned."""
        rows = [
            TagRow(appid=100, tag="Indie", votes=None, rank=1),
            TagRow(appid=100, tag="Adventure", votes=None, rank=2),
        ]
        write_tags(conn, run_id, rows)

        df = read_tags(conn, run_id, min_votes=1)
        assert len(df) == 0


class TestCrossThreadDetection:
    """Tests for cross-thread connection usage detection."""

    def test_write_tags_cross_thread_raises(self, conn, run_id):
        """Using a connection across threads raises StorageError."""
        import threading

        error_holder = []
        rows = [TagRow(appid=100, tag="Indie", votes=50, rank=1)]

        def use_conn_in_other_thread():
            try:
                write_tags(conn, run_id, rows)
            except StorageError as e:
                error_holder.append(e)

        thread = threading.Thread(target=use_conn_in_other_thread)
        thread.start()
        thread.join()

        assert len(error_holder) == 1
        assert "cross-thread" in str(error_holder[0]).lower()

    def test_read_tags_cross_thread_raises(self, conn, run_id):
        """Using a connection across threads raises StorageError."""
        import threading

        error_holder = []

        def use_conn_in_other_thread():
            try:
                read_tags(conn, run_id)
            except StorageError as e:
                error_holder.append(e)

        thread = threading.Thread(target=use_conn_in_other_thread)
        thread.start()
        thread.join()

        assert len(error_holder) == 1
        assert "cross-thread" in str(error_holder[0]).lower()
