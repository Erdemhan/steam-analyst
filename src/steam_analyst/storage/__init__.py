"""
Storage module: SQLite schema, connection management, and data access.

This module owns the database schema, migrations, and all read/write paths
for runs, per-stage run status, raw payloads, enriched features, tags,
and analysis results. No other module issues SQL.
"""

from .analysis_results import read_analysis_result, write_analysis_result
from .connection import _check_same_thread, connect, get_connection
from .enriched import read_enriched, write_enriched
from .events import append_run_event, read_run_events
from .raw import read_fetched_appids, read_raw_payloads, upsert_raw_payloads
from .run_stages import begin_run_stage, finish_run_stage, read_run_stages
from .runs import create_run, delete_run, get_run, list_runs, update_run_status
from .schema import (
    CURRENT_SCHEMA_VERSION,
    current_schema_version,
    initialize_schema,
    migrate,
)
from .tags import read_tags, write_tags
from .types import (
    EventSink,
    RunEvent,
    RunRecord,
    RunStage,
    RawPayload,
    StorageError,
    TagRow,
)

__all__ = [
    # Connection management
    "get_connection",
    "connect",
    "_check_same_thread",
    # Schema management
    "CURRENT_SCHEMA_VERSION",
    "initialize_schema",
    "current_schema_version",
    "migrate",
    # Run management
    "create_run",
    "get_run",
    "list_runs",
    "delete_run",
    "update_run_status",
    # Run stage management
    "begin_run_stage",
    "finish_run_stage",
    "read_run_stages",
    # Event management
    "append_run_event",
    "read_run_events",
    # Raw payload management
    "upsert_raw_payloads",
    "read_raw_payloads",
    "read_fetched_appids",
    # Enriched feature management
    "write_enriched",
    "read_enriched",
    # Tag management
    "write_tags",
    "read_tags",
    # Analysis result management
    "write_analysis_result",
    "read_analysis_result",
    # Types
    "RunRecord",
    "RunStage",
    "RunEvent",
    "RawPayload",
    "TagRow",
    "EventSink",
    "StorageError",
]
