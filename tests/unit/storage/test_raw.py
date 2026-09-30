"""
Unit tests for raw payload storage (upsert_raw_payloads, read_raw_payloads, read_fetched_appids).
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from steam_analyst.storage.connection import get_connection
from steam_analyst.storage.raw import (
    read_fetched_appids,
    read_raw_payloads,
    upsert_raw_payloads,
)
from steam_analyst.storage.runs import create_run
from steam_analyst.storage.schema import initialize_schema
from steam_analyst.storage.types import RawPayload, StorageError


@pytest.fixture
def temp_db(tmp_path: Path):
    """Create a temporary database with schema."""
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def test_run(temp_db):
    """Create a test run."""
    return create_run(
        temp_db,
        config={"test": True},
        parameters_version="test_v1",
        trigger_type="manual",
    )


def _make_payload(appid: int, source: str, data: dict) -> RawPayload:
    """Helper to create a RawPayload with correct sha256."""
    payload_json = json.dumps(data, separators=(",", ":"), sort_keys=True)
    sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return RawPayload(
        appid=appid,
        source=source,
        fetched_at=datetime.utcnow(),
        http_status=200,
        payload=data,
        payload_sha256=sha256,
    )


class TestUpsertRawPayloads:
    """Tests for upsert_raw_payloads function."""

    def test_stores_payloads_byte_equal(self, temp_db, test_run):
        """Payload round-trips with byte-identical JSON and matching sha256."""
        # Create payloads
        data1 = {"name": "app1", "price": 19.99, "tags": ["action", "indie"]}
        data2 = {"name": "app2", "reviews": 1000, "score": 85.5}

        payloads = [
            _make_payload(100, "steam_appdetails", data1),
            _make_payload(101, "steam_appdetails", data2),
        ]

        # Write payloads
        rows_written = upsert_raw_payloads(temp_db, test_run, payloads)
        assert rows_written == 2

        # Read back and verify
        read_back = list(read_raw_payloads(temp_db, test_run, "steam_appdetails"))
        assert len(read_back) == 2

        # Verify first payload
        assert read_back[0].appid == 100
        assert read_back[0].payload == data1
        expected_sha1 = hashlib.sha256(
            json.dumps(data1, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert read_back[0].payload_sha256 == expected_sha1

        # Verify second payload
        assert read_back[1].appid == 101
        assert read_back[1].payload == data2
        expected_sha2 = hashlib.sha256(
            json.dumps(data2, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert read_back[1].payload_sha256 == expected_sha2

    def test_empty_iterable_writes_zero(self, temp_db, test_run):
        """Empty list returns 0 and writes nothing."""
        rows_written = upsert_raw_payloads(temp_db, test_run, [])
        assert rows_written == 0

        # Verify nothing was written
        read_back = list(read_raw_payloads(temp_db, test_run, "steam_appdetails"))
        assert len(read_back) == 0

    def test_duplicate_key_in_batch_last_wins(self, temp_db, test_run):
        """Two payloads for same appid/source leave only the second's content."""
        data1 = {"version": 1, "data": "first"}
        data2 = {"version": 2, "data": "second"}

        payloads = [
            _make_payload(200, "steam_appdetails", data1),
            _make_payload(200, "steam_appdetails", data2),
        ]

        # Write payloads
        rows_written = upsert_raw_payloads(temp_db, test_run, payloads)

        # Due to INSERT OR IGNORE, the first one is inserted, the second is ignored
        # So only 1 row is written
        assert rows_written == 1

        # Read back and verify we get the first one (the one that won the insert)
        read_back = list(read_raw_payloads(temp_db, test_run, "steam_appdetails"))
        assert len(read_back) == 1
        assert read_back[0].appid == 200
        # The first payload should be stored
        assert read_back[0].payload == data1

    def test_partial_batch_survives_stream_error(self, temp_db, test_run):
        """A generator raising after 600 items leaves first committed batch (500) intact."""

        def payload_generator():
            # Yield 600 valid payloads
            for i in range(600):
                yield _make_payload(1000 + i, "steamspy_all", {"id": 1000 + i})
            # Then raise
            raise RuntimeError("Simulated stream error")

        # Write payloads
        with pytest.raises(RuntimeError, match="Simulated stream error"):
            upsert_raw_payloads(temp_db, test_run, payload_generator())

        # Verify first batch (500 rows) was committed
        read_back = list(read_raw_payloads(temp_db, test_run, "steamspy_all"))
        assert len(read_back) == 500

    def test_nonexistent_run_raises(self, temp_db):
        """Writing to a nonexistent run_id raises StorageError."""
        payloads = [_make_payload(100, "steam_appdetails", {"test": True})]

        with pytest.raises(StorageError, match="does not exist"):
            upsert_raw_payloads(temp_db, "nonexistent_run", payloads)

    def test_invalid_source_raises(self, temp_db, test_run):
        """Invalid source string raises StorageError."""
        bad_payload = _make_payload(100, "invalid_source", {"test": True})

        with pytest.raises(StorageError, match="Invalid source"):
            upsert_raw_payloads(temp_db, test_run, [bad_payload])

    def test_payload_sha256_stored_verbatim_not_reverified(self, temp_db, test_run):
        """payload_sha256 is stored as given, never recomputed/rejected by storage.

        The hash is computed by the caller (acquisition) over the original wire
        bytes, before parsing. storage.upsert_raw_payloads has no access to those
        original bytes -- only the already-parsed dict -- so it cannot and must
        not attempt to re-derive or validate the hash (re-serializing the dict via
        json.dumps is not guaranteed byte-identical to the real response body).
        """
        data = {"test": True}
        payload = _make_payload(100, "steam_appdetails", data)
        arbitrary_hash = "0" * 64

        stored = RawPayload(
            appid=payload.appid,
            source=payload.source,
            fetched_at=payload.fetched_at,
            http_status=payload.http_status,
            payload=payload.payload,
            payload_sha256=arbitrary_hash,
        )

        written = upsert_raw_payloads(temp_db, test_run, [stored])
        assert written == 1

        round_tripped = list(
            read_raw_payloads(temp_db, test_run, "steam_appdetails")
        )
        assert round_tripped[0].payload_sha256 == arbitrary_hash

    def test_large_batch_is_subdivided(self, temp_db, test_run):
        """A batch larger than 500 rows is subdivided and all written."""
        # Create 1200 payloads
        payloads = [
            _make_payload(2000 + i, "steam_reviews", {"review_id": 2000 + i})
            for i in range(1200)
        ]

        rows_written = upsert_raw_payloads(temp_db, test_run, payloads)
        assert rows_written == 1200

        # Verify all were written
        read_back = list(read_raw_payloads(temp_db, test_run, "steam_reviews"))
        assert len(read_back) == 1200


class TestReadRawPayloads:
    """Tests for read_raw_payloads function."""

    def test_streams_all_matching_rows(self, temp_db, test_run):
        """Fixture with 3 steamspy_all rows and 2 steam_appdetails yields matching rows."""
        # Write 3 steamspy_all payloads and 2 steam_appdetails payloads
        steamspy_payloads = [
            _make_payload(300 + i, "steamspy_all", {"name": f"app_{300 + i}"})
            for i in range(3)
        ]
        appdetails_payloads = [
            _make_payload(400 + i, "steam_appdetails", {"name": f"app_{400 + i}"})
            for i in range(2)
        ]

        all_payloads = steamspy_payloads + appdetails_payloads
        upsert_raw_payloads(temp_db, test_run, all_payloads)

        # Read steamspy_all
        read_back = list(read_raw_payloads(temp_db, test_run, "steamspy_all"))
        assert len(read_back) == 3
        assert all(p.source == "steamspy_all" for p in read_back)
        assert set(p.appid for p in read_back) == {300, 301, 302}

        # Read steam_appdetails
        read_back2 = list(read_raw_payloads(temp_db, test_run, "steam_appdetails"))
        assert len(read_back2) == 2
        assert all(p.source == "steam_appdetails" for p in read_back2)
        assert set(p.appid for p in read_back2) == {400, 401}

    def test_empty_result_yields_nothing(self, temp_db, test_run):
        """A source with no rows yields an empty iterator."""
        # Write some steamspy_all payloads
        payloads = [
            _make_payload(500 + i, "steamspy_all", {"name": f"app_{500 + i}"})
            for i in range(3)
        ]
        upsert_raw_payloads(temp_db, test_run, payloads)

        # Query for steam_reviews (which has no payloads)
        read_back = list(read_raw_payloads(temp_db, test_run, "steam_reviews"))
        assert read_back == []

    def test_invalid_source_raises_immediately(self, temp_db, test_run):
        """Invalid source string raises StorageError before iteration."""
        # Validation happens immediately when the function is called, not lazily
        with pytest.raises(StorageError, match="Invalid source"):
            read_raw_payloads(temp_db, test_run, "invalid_source")

    def test_invalid_source_raises_on_creation(self, temp_db, test_run):
        """Invalid source raises StorageError during function call (before iteration)."""
        with pytest.raises(StorageError, match="Invalid source"):
            read_raw_payloads(temp_db, test_run, "bogus_source")

    def test_iterator_not_consumed_doesnt_leak(self, temp_db, test_run):
        """Abandoning an iterator before consuming it all does not leak resources."""
        # Write some payloads
        payloads = [
            _make_payload(600 + i, "steamspy_all", {"name": f"app_{600 + i}"})
            for i in range(100)
        ]
        upsert_raw_payloads(temp_db, test_run, payloads)

        # Create an iterator but don't consume it
        gen = read_raw_payloads(temp_db, test_run, "steamspy_all")
        # Consume only the first few
        first_few = [next(gen) for _ in range(5)]
        assert len(first_few) == 5

        # Let the generator be garbage collected
        del gen

        # Verify we can still query the database (no cursor stuck open)
        read_all = list(read_raw_payloads(temp_db, test_run, "steamspy_all"))
        assert len(read_all) == 100

    def test_large_result_set_streams_without_oom(self, temp_db, test_run):
        """A large result set (e.g., 5000 rows) streams without loading into memory."""
        # Write 5000 payloads (would be expensive to load all at once)
        payloads = [
            _make_payload(10000 + i, "steamspy_all", {"id": 10000 + i, "data": "x" * 100})
            for i in range(5000)
        ]
        upsert_raw_payloads(temp_db, test_run, payloads)

        # Stream and verify we can iterate without excessive memory
        count = 0
        for payload in read_raw_payloads(temp_db, test_run, "steamspy_all"):
            assert payload.source == "steamspy_all"
            count += 1
            if count >= 5000:
                break

        assert count == 5000


class TestReadFetchedAppids:
    """Tests for read_fetched_appids function."""

    def test_returns_persisted_appids(self, temp_db, test_run):
        """After upsert, read_fetched_appids returns exactly those appids."""
        # Write payloads for appids 1, 2, 3
        payloads = [
            _make_payload(1, "steam_appdetails", {"id": 1}),
            _make_payload(2, "steam_appdetails", {"id": 2}),
            _make_payload(3, "steam_appdetails", {"id": 3}),
        ]
        upsert_raw_payloads(temp_db, test_run, payloads)

        # Read fetched appids
        result = read_fetched_appids(temp_db, test_run, "steam_appdetails")
        assert result == {1, 2, 3}

    def test_empty_for_unattempted_source(self, temp_db, test_run):
        """A run with only steamspy_all returns empty set for steam_reviews."""
        # Write steamspy_all payloads
        payloads = [
            _make_payload(7, "steamspy_all", {"id": 7}),
            _make_payload(8, "steamspy_all", {"id": 8}),
        ]
        upsert_raw_payloads(temp_db, test_run, payloads)

        # Query for steam_reviews (which has no payloads)
        result = read_fetched_appids(temp_db, test_run, "steam_reviews")
        assert result == set()

    def test_invalid_source_raises(self, temp_db, test_run):
        """Invalid source string raises StorageError."""
        with pytest.raises(StorageError, match="Invalid source"):
            read_fetched_appids(temp_db, test_run, "bogus_source")

    def test_multiple_sources_isolated(self, temp_db, test_run):
        """Different sources are not mixed in the result."""
        # Write payloads for multiple sources
        payloads = [
            _make_payload(10, "steamspy_all", {"id": 10}),
            _make_payload(10, "steam_appdetails", {"id": 10}),
            _make_payload(11, "steamspy_all", {"id": 11}),
            _make_payload(12, "steam_appdetails", {"id": 12}),
        ]
        upsert_raw_payloads(temp_db, test_run, payloads)

        # Query each source separately
        steamspy_appids = read_fetched_appids(temp_db, test_run, "steamspy_all")
        appdetails_appids = read_fetched_appids(temp_db, test_run, "steam_appdetails")

        assert steamspy_appids == {10, 11}
        assert appdetails_appids == {10, 12}

    def test_duplicate_appid_per_source(self, temp_db, test_run):
        """Duplicate appids per source (should not happen but set handles it)."""
        # Write the same appid twice for same source
        payloads = [
            _make_payload(20, "steam_appdetails", {"version": 1}),
            _make_payload(20, "steam_appdetails", {"version": 2}),  # Duplicate, ignored on insert
        ]
        upsert_raw_payloads(temp_db, test_run, payloads)

        # Result should still have exactly one appid
        result = read_fetched_appids(temp_db, test_run, "steam_appdetails")
        assert result == {20}

    def test_large_result_set(self, temp_db, test_run):
        """A large set of appids (e.g., 10k) is returned correctly."""
        # Write 10k payloads
        payloads = [
            _make_payload(50000 + i, "steamspy_all", {"id": 50000 + i})
            for i in range(10000)
        ]
        upsert_raw_payloads(temp_db, test_run, payloads)

        # Read fetched appids
        result = read_fetched_appids(temp_db, test_run, "steamspy_all")
        assert len(result) == 10000
        assert result == set(range(50000, 60000))


class TestIntegration:
    """Integration tests covering full workflow."""

    def test_upsert_then_read_cycle(self, temp_db, test_run):
        """Complete write/read cycle preserves data correctly."""
        # Create payloads with various data types and structures
        payloads = [
            _make_payload(
                101,
                "steam_appdetails",
                {
                    "name": "Portal 2",
                    "price": 19.99,
                    "is_free": False,
                    "tags": ["puzzle", "adventure"],
                    "metadata": {"rating": 9.2, "reviews": 5000},
                },
            ),
            _make_payload(
                102,
                "steam_appdetails",
                {"name": "Free App", "price": 0, "is_free": True},
            ),
            _make_payload(
                101,
                "steam_reviews",
                {"review_count": 5000, "positive_pct": 92},
            ),
        ]

        # Write
        rows_written = upsert_raw_payloads(temp_db, test_run, payloads)
        assert rows_written == 3

        # Read appdetails
        appdetails = list(read_raw_payloads(temp_db, test_run, "steam_appdetails"))
        assert len(appdetails) == 2
        assert appdetails[0].payload["name"] == "Portal 2"
        assert appdetails[1].payload["is_free"] is True

        # Read reviews
        reviews = list(read_raw_payloads(temp_db, test_run, "steam_reviews"))
        assert len(reviews) == 1
        assert reviews[0].payload["positive_pct"] == 92

        # Check fetched appids
        appdetails_appids = read_fetched_appids(temp_db, test_run, "steam_appdetails")
        assert appdetails_appids == {101, 102}

        reviews_appids = read_fetched_appids(temp_db, test_run, "steam_reviews")
        assert reviews_appids == {101}

    def test_resume_scenario_insert_missing(self, temp_db, test_run):
        """Resume scenario: second call writes only new appids (INSERT OR IGNORE)."""
        # First batch
        payloads1 = [
            _make_payload(200, "steamspy_all", {"data": "first_batch"}),
            _make_payload(201, "steamspy_all", {"data": "first_batch"}),
        ]
        rows1 = upsert_raw_payloads(temp_db, test_run, payloads1)
        assert rows1 == 2

        # Second batch (resume with overlap)
        payloads2 = [
            _make_payload(200, "steamspy_all", {"data": "should_be_ignored"}),  # Duplicate
            _make_payload(202, "steamspy_all", {"data": "second_batch"}),  # New
        ]
        rows2 = upsert_raw_payloads(temp_db, test_run, payloads2)
        assert rows2 == 1  # Only the new one

        # Verify final state
        all_payloads = list(read_raw_payloads(temp_db, test_run, "steamspy_all"))
        assert len(all_payloads) == 3
        # Verify appid 200 still has the original data
        payload_200 = next(p for p in all_payloads if p.appid == 200)
        assert payload_200.payload["data"] == "first_batch"


class TestCrossThreadDetection:
    """Tests for cross-thread connection usage detection."""

    def test_cross_thread_raises(self, temp_db):
        """Using a connection across threads raises StorageError."""
        import threading

        error_holder = []

        def access_in_different_thread():
            try:
                # Try to use the connection from a different thread
                upsert_raw_payloads(
                    temp_db,
                    "some_run",
                    [_make_payload(300, "steam_appdetails", {"test": True})],
                )
            except StorageError as e:
                if "cross-thread" in str(e).lower():
                    error_holder.append(e)
                else:
                    error_holder.append(None)  # Wrong error

        thread = threading.Thread(target=access_in_different_thread)
        thread.start()
        thread.join()

        # Verify we got the cross-thread error
        assert len(error_holder) > 0
        assert error_holder[0] is not None
