"""
Unit tests for storage.types module (dataclasses, protocol, exception).
"""

import pytest
from datetime import datetime

from steam_analyst.storage.types import (
    RunRecord,
    RunStage,
    RunEvent,
    RawPayload,
    TagRow,
    EventSink,
    StorageError,
)


class TestRunRecord:
    """Tests for RunRecord dataclass."""

    def test_runrecord_construction(self):
        """RunRecord can be constructed with all fields."""
        record = RunRecord(
            run_id="run_20240101_abc123",
            started_at=datetime(2024, 1, 1, 12, 0, 0),
            finished_at=None,
            status="running",
            trigger_type="manual",
            parent_run_id=None,
            config={"start_stage": "acquisition"},
            parameters_version="v1.0",
            code_version="abc123",
            error_message=None,
            notes="Test run",
        )
        assert record.run_id == "run_20240101_abc123"
        assert record.status == "running"
        assert record.finished_at is None

    def test_runrecord_finished_at_none_for_running(self):
        """RunRecord with running status has None finished_at, not sentinel datetime."""
        record = RunRecord(
            run_id="test",
            started_at=datetime(2024, 1, 1),
            finished_at=None,
            status="running",
            trigger_type="manual",
            parent_run_id=None,
            config={},
            parameters_version="v1",
            code_version=None,
            error_message=None,
            notes=None,
        )
        assert record.finished_at is None

    def test_runrecord_frozen(self):
        """RunRecord is frozen and immutable."""
        record = RunRecord(
            run_id="test",
            started_at=datetime(2024, 1, 1),
            finished_at=None,
            status="pending",
            trigger_type="manual",
            parent_run_id=None,
            config={},
            parameters_version="v1",
            code_version=None,
            error_message=None,
            notes=None,
        )
        with pytest.raises(AttributeError):
            record.status = "running"


class TestRunStage:
    """Tests for RunStage dataclass."""

    def test_runstage_construction(self):
        """RunStage can be constructed with all fields."""
        stage = RunStage(
            run_id="run_123",
            stage="acquisition",
            status="running",
            started_at=datetime(2024, 1, 1, 12, 0, 0),
            finished_at=None,
            attempt=0,
            error_message=None,
        )
        assert stage.stage == "acquisition"
        assert stage.attempt == 0

    def test_runstage_frozen(self):
        """RunStage is frozen and immutable."""
        stage = RunStage(
            run_id="run_123",
            stage="acquisition",
            status="pending",
            started_at=None,
            finished_at=None,
            attempt=0,
            error_message=None,
        )
        with pytest.raises(AttributeError):
            stage.status = "running"


class TestRunEvent:
    """Tests for RunEvent dataclass."""

    def test_runevent_construction(self):
        """RunEvent can be constructed with all fields."""
        event = RunEvent(
            event_id=1,
            run_id="run_123",
            ts=datetime(2024, 1, 1, 12, 0, 0),
            stage="acquisition",
            level="info",
            message="Starting acquisition",
            progress=0.0,
        )
        assert event.event_id == 1
        assert event.level == "info"
        assert event.progress == 0.0

    def test_runevent_progress_none(self):
        """RunEvent progress can be None."""
        event = RunEvent(
            event_id=1,
            run_id="run_123",
            ts=datetime(2024, 1, 1, 12, 0, 0),
            stage="acquisition",
            level="info",
            message="Starting",
            progress=None,
        )
        assert event.progress is None

    def test_runevent_frozen(self):
        """RunEvent is frozen and immutable."""
        event = RunEvent(
            event_id=1,
            run_id="run_123",
            ts=datetime(2024, 1, 1),
            stage="acquisition",
            level="info",
            message="msg",
            progress=None,
        )
        with pytest.raises(AttributeError):
            event.message = "updated"


class TestRawPayload:
    """Tests for RawPayload dataclass."""

    def test_rawpayload_construction(self):
        """RawPayload can be constructed with all fields."""
        payload = RawPayload(
            appid=570,
            source="steamspy_all",
            fetched_at=datetime(2024, 1, 1, 12, 0, 0),
            http_status=200,
            payload={"appid": 570, "name": "Dota 2"},
            payload_sha256="a" * 64,
        )
        assert payload.appid == 570
        assert payload.http_status == 200

    def test_rawpayload_frozen(self):
        """RawPayload is frozen and immutable."""
        payload = RawPayload(
            appid=570,
            source="steamspy_all",
            fetched_at=datetime(2024, 1, 1),
            http_status=200,
            payload={},
            payload_sha256="a" * 64,
        )
        with pytest.raises(AttributeError):
            payload.http_status = 404


class TestTagRow:
    """Tests for TagRow dataclass."""

    def test_tagrow_with_votes_and_rank(self):
        """TagRow can be constructed with votes and rank."""
        tag = TagRow(appid=570, tag="Indie", votes=100, rank=1)
        assert tag.tag == "Indie"
        assert tag.votes == 100
        assert tag.rank == 1

    def test_tagrow_with_none_votes_and_rank(self):
        """TagRow can have None for votes and rank."""
        tag = TagRow(appid=570, tag="Indie", votes=None, rank=None)
        assert tag.votes is None
        assert tag.rank is None

    def test_tagrow_mixed_none(self):
        """TagRow can have mixed None values."""
        tag = TagRow(appid=570, tag="Indie", votes=50, rank=None)
        assert tag.votes == 50
        assert tag.rank is None

    def test_tagrow_frozen(self):
        """TagRow is frozen and immutable."""
        tag = TagRow(appid=570, tag="Indie", votes=100, rank=1)
        with pytest.raises(AttributeError):
            tag.votes = 200


class TestEventSink:
    """Tests for EventSink protocol."""

    def test_recording_fake_conforms_to_eventsink_protocol(self):
        """A simple recording lambda satisfies EventSink protocol."""
        events: list[tuple] = []

        def recording_sink(
            *, stage: str, level: str, message: str, progress: float | None = None
        ) -> None:
            events.append((stage, level, message, progress))

        # Call the sink as an EventSink
        recording_sink(
            stage="acquisition",
            level="info",
            message="Starting acquisition",
            progress=None,
        )

        assert len(events) == 1
        assert events[0] == ("acquisition", "info", "Starting acquisition", None)

    def test_lambda_eventsink_protocol(self):
        """A plain lambda works as EventSink."""
        recorded = []
        sink = lambda **kw: recorded.append(kw)

        sink(stage="test", level="info", message="msg", progress=0.5)
        assert len(recorded) == 1
        assert recorded[0]["message"] == "msg"


class TestStorageError:
    """Tests for StorageError exception."""

    def test_storageerror_message_present(self):
        """StorageError carries a message."""
        error = StorageError("cross-thread use")
        assert str(error) == "cross-thread use"

    def test_storageerror_with_context(self):
        """StorageError can be raised with a cause."""
        try:
            raise ValueError("original error")
        except ValueError as e:
            storage_error = StorageError(f"Failed: {e}")
            assert "original error" in str(storage_error)

    def test_storageerror_is_exception(self):
        """StorageError is an Exception subclass."""
        error = StorageError("test")
        assert isinstance(error, Exception)

    def test_storageerror_can_be_caught(self):
        """StorageError can be caught as Exception."""
        with pytest.raises(StorageError):
            raise StorageError("test error")
