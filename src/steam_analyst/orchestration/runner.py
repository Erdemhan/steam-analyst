"""Background run execution and run management.

This module starts and manages long-running pipeline stages on background worker
threads, decoupled from the Streamlit UI script thread. It implements cooperative
cancellation through a module-level registry and handles process-restart recovery
through orphaned-run reconciliation.

Key design principles (ADR-006, ADR-014, ADR-015, ADR-017):
- No connection ever crosses a thread boundary.
- start_pipeline_async and resume_run take a Path, never a connection.
- Each worker thread opens and closes its own connection.
- Cancellation is cooperative, signalled by a threading.Event.
- reconcile_orphaned_runs is called once at UI startup.
"""

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from steam_analyst.config.parameters import parameters_version
from steam_analyst.config.settings import Settings, load_settings
from steam_analyst.storage import (
    append_run_event,
    connect,
    create_run,
    get_run,
    list_runs,
    update_run_status,
    finish_run_stage,
    read_run_stages,
)

from .errors import PipelineError
from .pipeline import run_pipeline
from .pipeline_config import PipelineConfig
from .stages import PipelineStage, RUN_LEVEL_STAGE

logger = logging.getLogger(__name__)

# Module-level cancellation registry: maps run_id -> (threading.Event, db_path).
# The db_path is stored alongside the Event so cancel_run can open a short-lived
# connection to append a run_event without requiring a db_path argument.
# Guarded by _CANCEL_REGISTRY_LOCK.
_CANCEL_REGISTRY: dict[str, tuple[threading.Event, Path]] = {}
_CANCEL_REGISTRY_LOCK = threading.Lock()


def start_pipeline_async(
    db_path: Path,
    config: PipelineConfig,
    *,
    settings: Optional[Settings] = None,
) -> str:
    """Start a new run in the background and return its id immediately.

    Creates the run row synchronously on the calling thread using a short-lived
    connection, registers a cancellation token, starts a non-daemon worker thread,
    and returns the run_id so the UI can begin polling without blocking.

    Args:
        db_path: Path to the SQLite database file. Never a connection (ADR-017).
        config: This run's PipelineConfig (start_stage is normally ACQUISITION).
        settings: Loaded via config.load_settings() if not given.

    Returns:
        The new run_id, available immediately for polling.

    Raises:
        Any exception from storage.create_run propagates directly (e.g. if
        db_path is unwritable), before the worker thread starts.

    Sequence:
        1. Load settings if not provided.
        2. Compute parameters_version (cheap file hash).
        3. Open a short-lived connection, call storage.create_run, close it.
        4. Register (cancel_event, db_path) in _CANCEL_REGISTRY.
        5. Start a non-daemon worker thread.
        6. Return run_id immediately.
    """
    # Step 1: Load settings if not provided
    if settings is None:
        settings = load_settings()

    # Step 2: Compute parameters_version (cheap hash, doesn't require load_parameters)
    parameters_version_value = parameters_version(settings.parameters_path)

    # Step 3: Create run row on calling thread
    with connect(db_path) as conn:
        run_id = create_run(
            conn,
            config=config.to_dict(),
            parameters_version=parameters_version_value,
            trigger_type="manual",
            notes=config.notes,
        )

    # Step 4: Register cancellation token and db_path
    cancel_event = threading.Event()
    with _CANCEL_REGISTRY_LOCK:
        _CANCEL_REGISTRY[run_id] = (cancel_event, db_path)

    # Step 5: Start worker thread (non-daemon)
    def worker_target() -> None:
        """Worker thread target: open connection, run pipeline, clean up."""
        try:
            # Open connection for this thread
            with connect(db_path) as conn:
                try:
                    run_pipeline(
                        conn,
                        run_id,
                        config,
                        settings=settings,
                        cancel_token=cancel_event,
                    )
                except Exception as exc:
                    # run_pipeline already wrote terminal status before raising,
                    # so this outer catch only prevents silent thread death.
                    logger.exception(
                        "Unexpected exception in run_pipeline for run %s: %s",
                        run_id,
                        exc,
                    )
        finally:
            # Remove run_id from registry
            with _CANCEL_REGISTRY_LOCK:
                _CANCEL_REGISTRY.pop(run_id, None)

    worker = threading.Thread(target=worker_target, daemon=False)
    worker.start()

    # Step 6: Return run_id immediately
    return run_id


def resume_run(
    db_path: Path,
    run_id: str,
    *,
    settings: Optional[Settings] = None,
) -> str:
    """Resume an existing run from its first non-succeeded stage.

    Reads the run's run_stages, finds the first stage in pipeline order whose
    status is not 'succeeded', and restarts from there. No new run row is
    created; parent_run_id is not written.

    Args:
        db_path: Path to the SQLite database file.
        run_id: An existing run to resume.
        settings: Loaded via config.load_settings() if not given.

    Returns:
        The same run_id (unchanged).

    Raises:
        PipelineError:
        - If run_id is unknown.
        - If is_running(run_id) is True (already has a live worker).
        - If all three stages already succeeded (user should start a new run instead).
    """
    # Load settings if not provided
    if settings is None:
        settings = load_settings()

    # Read the existing run and its stages
    with connect(db_path) as conn:
        run = get_run(conn, run_id)
        if run is None:
            raise PipelineError(f"Unknown run_id: {run_id}")

        # Check if already running
        if is_running(run_id):
            raise PipelineError(f"Run {run_id} is already running")

        # Read run_stages and check if all succeeded
        stages = read_run_stages(conn, run_id)
        succeeded_stages = {s.stage for s in stages if s.status == "succeeded"}

        if succeeded_stages == {"acquisition", "enrichment", "analysis"}:
            raise PipelineError(
                f"Run {run_id} has all stages succeeded; start a new run instead"
            )

        # Find first non-succeeded stage in pipeline order
        all_stages = list(PipelineStage)
        start_stage = None
        for stage in all_stages:
            if stage.value not in succeeded_stages:
                start_stage = stage
                break

        # If no stage found (shouldn't happen if not all succeeded), start from acquisition
        if start_stage is None:
            start_stage = PipelineStage.ACQUISITION

        # Rebuild config with computed start_stage
        resumed_config = PipelineConfig.from_dict(run.config)
        resumed_config = PipelineConfig(
            start_stage=start_stage,
            max_catalog_pages=resumed_config.max_catalog_pages,
            request_budget_override=resumed_config.request_budget_override,
            notes=resumed_config.notes,
        )

    # Register and start worker (same as start_pipeline_async, but reusing run_id)
    cancel_event = threading.Event()
    with _CANCEL_REGISTRY_LOCK:
        _CANCEL_REGISTRY[run_id] = (cancel_event, db_path)

    def worker_target() -> None:
        """Worker thread target: open connection, run pipeline, clean up."""
        try:
            with connect(db_path) as conn:
                try:
                    run_pipeline(
                        conn,
                        run_id,
                        resumed_config,
                        settings=settings,
                        cancel_token=cancel_event,
                    )
                except Exception as exc:
                    logger.exception(
                        "Unexpected exception in run_pipeline for resumed run %s: %s",
                        run_id,
                        exc,
                    )
        finally:
            with _CANCEL_REGISTRY_LOCK:
                _CANCEL_REGISTRY.pop(run_id, None)

    worker = threading.Thread(target=worker_target, daemon=False)
    worker.start()

    return run_id


def cancel_run(run_id: str) -> bool:
    """Signal a live run to stop at its next cancellation check-point.

    Sets the cooperative cancellation Event for the run and appends a
    RUN_LEVEL_STAGE run_event recording the cancellation request. Does not
    block waiting for the worker to stop and does not itself change runs.status.

    Args:
        run_id: The run to cancel.

    Returns:
        True if a live worker was registered and the Event was set.
        False if no live worker is registered (unknown run, already finished,
        or never started in this process).

    Idempotent: a second call on an already-cancelled live run also returns True.
    """
    with _CANCEL_REGISTRY_LOCK:
        entry = _CANCEL_REGISTRY.get(run_id)

    if entry is None:
        return False

    cancel_event, db_path = entry

    # Set the cancellation event (idempotent: already-set stays set)
    cancel_event.set()

    # Append a run_event recording the cancellation request
    # Use a short-lived connection; if the append fails, log it but still return True
    # (the Event being set is what matters, not the audit trail)
    try:
        with connect(db_path) as conn:
            append_run_event(
                conn,
                run_id,
                stage=RUN_LEVEL_STAGE,
                level="info",
                message="Cancellation requested by user",
            )
    except Exception as e:
        logger.exception(
            "Failed to append cancellation event for run %s (but Event is set): %s",
            run_id,
            e,
        )

    return True


def is_running(run_id: str) -> bool:
    """Check if a run has a live worker in this process.

    True iff run_id is currently registered in _CANCEL_REGISTRY.

    Args:
        run_id: The run to check.

    Returns:
        True if a live worker is registered for run_id.
    """
    with _CANCEL_REGISTRY_LOCK:
        return run_id in _CANCEL_REGISTRY


def active_run_ids() -> list[str]:
    """Return all run_ids with live workers in this process.

    Provides a snapshot of the current state; the returned list is a copy
    and mutating it has no effect on the registry.

    Returns:
        A list of run_ids (possibly empty).
    """
    with _CANCEL_REGISTRY_LOCK:
        return list(_CANCEL_REGISTRY.keys())


def reconcile_orphaned_runs(conn: sqlite3.Connection) -> list[str]:
    """Mark any run left 'running' by a dead process as failed.

    Called once at UI startup. Makes a run killed by a process restart
    resumable rather than permanently stuck in 'running'.

    Args:
        conn: An open connection, used only for the duration of this call.

    Returns:
        The run_ids that were reconciled (marked failed). Empty list if
        none were orphaned.

    Sequence:
        1. Find all runs with status in ('pending', 'running').
        2. For each not in active_run_ids(), mark it failed.
        3. Also mark its running run_stages as failed.
        4. Return the list of reconciled run_ids.
    """
    # Get all runs as a DataFrame
    all_runs_df = list_runs(conn, limit=10000)

    # Filter to pending/running only
    if len(all_runs_df) == 0:
        return []

    candidates_df = all_runs_df[all_runs_df["status"].isin(["pending", "running"])]

    # Get the set of genuinely live run_ids
    live = set(active_run_ids())

    # Reconcile orphaned ones
    reconciled = []
    for _, row in candidates_df.iterrows():
        run_id = row["run_id"]
        if run_id not in live:
            # Mark run as failed
            update_run_status(
                conn,
                run_id,
                "failed",
                error_message="process terminated before completion",
            )

            # Mark any running run_stages as failed
            stages = read_run_stages(conn, run_id)
            for stage in stages:
                if stage.status == "running":
                    finish_run_stage(
                        conn,
                        run_id,
                        stage.stage,
                        "failed",
                        error_message="process terminated before completion",
                    )

            reconciled.append(run_id)

    return reconciled
