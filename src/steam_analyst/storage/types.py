"""
Plain row-representation types and protocols for storage operations.

This module defines the data transfer objects (frozen dataclasses) for all
database operations, the EventSink callback protocol for progress/logging,
and the StorageError exception used across all storage functions.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class RunRecord:
    """One row of the runs table.

    Represents a complete pipeline run from creation through completion.

    Attributes:
        run_id: Unique identifier for the run.
        started_at: UTC datetime when the run was created.
        finished_at: UTC datetime when the run completed, or None if still running.
        status: One of {'pending','running','succeeded','failed','cancelled'}.
        trigger_type: One of {'manual','scheduled'}.
        parent_run_id: If a resumed/re-run, the run_id of the original run.
        config: Deserialized config_json (orchestration.PipelineConfig.to_dict()).
        parameters_version: Content hash of the config/parameters.toml at run time.
        code_version: Git commit hash or version tag at run time, or None.
        error_message: If status is 'failed', the top-level error message.
        notes: Optional user-provided notes about the run.
    """
    run_id: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    trigger_type: str
    parent_run_id: str | None
    config: dict
    parameters_version: str
    code_version: str | None
    error_message: str | None
    notes: str | None


@dataclass(frozen=True)
class RunStage:
    """One row of the run_stages table.

    Tracks the status and history of one stage (acquisition, enrichment,
    or analysis) within a single run.

    Attributes:
        run_id: Parent run ID.
        stage: One of {'acquisition','enrichment','analysis'}.
        status: One of {'pending','running','succeeded','failed','cancelled'}.
        started_at: UTC datetime when this stage attempt began, or None if not yet started.
        finished_at: UTC datetime when this stage attempt ended, or None if still running.
        attempt: Zero-indexed attempt count; incremented on each resume or retry.
        error_message: If status is 'failed', the stage-specific error message.
    """
    run_id: str
    stage: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    attempt: int
    error_message: str | None


@dataclass(frozen=True)
class RunEvent:
    """One row of the run_events table.

    Append-only log of progress and diagnostic events during pipeline execution.

    Attributes:
        event_id: Auto-incremented primary key.
        run_id: Parent run ID.
        ts: UTC datetime of the event.
        stage: Name of the stage reporting the event.
        level: One of {'debug','info','warning','error'}.
        message: Human-readable event description.
        progress: Optional fractional progress (0.0 to 1.0) reported by the stage.
    """
    event_id: int
    run_id: str
    ts: datetime
    stage: str
    level: str
    message: str
    progress: float | None


@dataclass(frozen=True)
class RawPayload:
    """One row of the raw_games table.

    Immutable snapshot of data fetched from an external source.

    Attributes:
        appid: Steam application ID.
        source: One of {'steamspy_all','steamspy_appdetails','steam_appdetails','steam_reviews'}.
        fetched_at: UTC datetime when this payload was fetched.
        http_status: HTTP status code (usually 200, but stored to diagnose partial fetches).
        payload: Parsed JSON body from the response.
        payload_sha256: Lowercase hex SHA256 digest of the raw bytes received (64 chars).
    """
    appid: int
    source: str
    fetched_at: datetime
    http_status: int
    payload: dict
    payload_sha256: str


@dataclass(frozen=True)
class TagRow:
    """One row of the game_tags table.

    A community tag associated with a game in a given run.

    Attributes:
        appid: Steam application ID.
        tag: The tag name (e.g., 'Indie', 'Adventure').
        votes: Number of votes for this tag, or None if not reported by the source.
        rank: Ordinal rank of this tag in the app's tag list (1-indexed), or None if not reported.
    """
    appid: int
    tag: str
    votes: int | None
    rank: int | None


class EventSink(Protocol):
    """Structural callback type for progress and diagnostic logging.

    Every stage entry point (acquisition.run_acquisition, enrichment.run_enrichment,
    analysis.run_analysis) type-hints its on_event parameter against this protocol.

    Concrete implementations are normally built by orchestration and wrap
    append_run_event. A simple recording lambda or list-appending closure
    also satisfies this protocol structurally (no explicit subclassing required).

    Any EventSink implementation that performs I/O must catch and locally handle
    its own errors, so a logging failure can never abort the pipeline stage
    it is reporting progress for.
    """

    def __call__(
        self, *, stage: str, level: str, message: str, progress: float | None = None
    ) -> None:
        """Report a progress or diagnostic event.

        Args:
            stage: The pipeline stage reporting the event.
            level: Event severity; one of {'debug','info','warning','error'}.
            message: Human-readable event description.
            progress: Optional fractional progress (0.0 to 1.0).
        """
        ...


class StorageError(Exception):
    """Raised for any storage layer error.

    Distinguishes storage-layer failures (schema violations, cross-thread
    misuse, unknown run_id where a contract requires an error, or ordering
    violations) from config.ParameterError and stage-specific errors
    (AcquisitionError, EnrichmentError, AnalysisError) raised by higher layers.
    """

    pass
