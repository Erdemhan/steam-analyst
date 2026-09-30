"""Pipeline execution: run orchestration, stage sequencing, and exception mapping."""

import logging
import sqlite3
import threading
import traceback
from datetime import datetime
from typing import Optional

from steam_analyst.acquisition.pipeline import run_acquisition
from steam_analyst.analysis.pipeline import run_analysis
from steam_analyst.config.parameters import load_parameters, parameters_version
from steam_analyst.config.settings import load_settings, Settings
from steam_analyst.enrichment.pipeline import run_enrichment
from steam_analyst.storage import (
    append_run_event,
    begin_run_stage,
    finish_run_stage,
    initialize_schema,
    migrate,
    update_run_status,
)

from .errors import PipelineCancelled, PreflightError
from .events import make_event_sink
from .pipeline_config import PipelineConfig
from .results import PipelineResult
from .stages import PipelineStage, RUN_LEVEL_STAGE

logger = logging.getLogger(__name__)


def _map_exception_to_terminal_status(
    exc: BaseException, stage: str
) -> tuple[str, Optional[str], str]:
    """Map a raised exception to (run_status, stage_status, error_message).

    Args:
        exc: The exception caught by run_pipeline's handler.
        stage: The PipelineStage.value the exception occurred in, or RUN_LEVEL_STAGE
            if it occurred during preflight.

    Returns:
        A tuple (run_status, stage_status, error_message) per the terminal_status_mapping:
        - PipelineCancelled -> ('cancelled', 'cancelled', 'cancelled by user during {stage}')
        - KeyboardInterrupt/SystemExit -> ('cancelled', 'cancelled', 'interrupted during {stage}')
        - PreflightError -> ('failed', None, the wrapped message)
        - RequestBudgetExceeded -> ('failed', 'failed', budget message)
        - AcquisitionError/EnrichmentError/AnalysisError/StorageError/any other Exception
          -> ('failed', 'failed', '{stage}: {type}: {message}')

    The stage_status is None for PreflightError to signal that no finish_run_stage
    should be called (no run_stages row exists yet).
    """
    # Import here to avoid circular imports
    from steam_analyst.acquisition.errors import (
        AcquisitionError,
        RequestBudgetExceeded,
    )
    from steam_analyst.enrichment.errors import EnrichmentError
    from steam_analyst.analysis.errors import AnalysisError
    from steam_analyst.storage.types import StorageError

    if isinstance(exc, PipelineCancelled):
        return (
            "cancelled",
            "cancelled",
            f"cancelled by user during {exc.stage}",
        )

    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return (
            "cancelled",
            "cancelled",
            f"interrupted during {stage}",
        )

    if isinstance(exc, PreflightError):
        # No stage_status returned; finish_run_stage must not be called
        return (
            "failed",
            None,
            exc.message,
        )

    if isinstance(exc, RequestBudgetExceeded):
        # Extract budget and requests made from the exception message if possible
        return (
            "failed",
            "failed",
            str(exc),
        )

    if isinstance(exc, (AcquisitionError, EnrichmentError, AnalysisError, StorageError)):
        error_type = type(exc).__name__
        error_msg = str(exc)
        return (
            "failed",
            "failed",
            f"{stage}: {error_type}: {error_msg}",
        )

    # Catch-all for any other exception
    error_type = type(exc).__name__
    error_msg = str(exc)
    return (
        "failed",
        "failed",
        f"{stage}: {error_type}: {error_msg}",
    )


def run_pipeline(
    conn: sqlite3.Connection,
    run_id: str,
    config: PipelineConfig,
    *,
    settings: Optional[Settings] = None,
    cancel_token: Optional[threading.Event] = None,
) -> PipelineResult:
    """Execute (or resume) one run's pipeline stages.

    Args:
        conn: An open connection, owned and closed by the caller. run_pipeline never
            opens or closes a connection itself.
        run_id: An existing runs row (created by the caller before this call).
            run_pipeline itself does not call create_run.
        config: This call's PipelineConfig, in particular start_stage.
        settings: Loaded once by the caller if not given; passed through so a test
            can inject a stub Settings without touching the filesystem.
        cancel_token: Checked at CP1 and forwarded into stage entry points for CP2-CP7;
            None means cancellation is never observed.

    Returns:
        A PipelineResult on any path that reaches a terminal status normally.

    Raises:
        PreflightError: If config.load_parameters or the ADR-013 consistency check fails.
            Raised before any run_stages row is written.
        PipelineCancelled: Re-raised after the terminal status has been written.
        Any stage-specific exception: Re-raised after the terminal status has been written.

    Sequence:
        1. Preflight: load settings and parameters, run consistency check, initialize schema
        2. Create event sink
        3. For each PipelineStage from config.start_stage onward:
           a. Check cancel_token at CP1
           b. Call storage.begin_run_stage
           c. Call the stage entry point
           d. Call storage.finish_run_stage('succeeded')
           e. Append stage-complete event
        4. On any exception: map to status, write terminal status, re-raise
        5. On normal completion: update run status to 'succeeded', build and return PipelineResult
    """
    started_at = datetime.utcnow()
    stages_run = []
    reports = {}
    current_stage = None

    try:
        # === PREFLIGHT ===

        # (b) Load settings if not provided
        if settings is None:
            try:
                settings = load_settings()
            except Exception as e:
                raise PreflightError(f"Failed to load settings: {e}", cause=e)

        # (a) Compute parameters_version upfront (computable without config.load_parameters)
        try:
            parameters_version_value = parameters_version(settings.parameters_path)
        except Exception as e:
            raise PreflightError(f"Failed to compute parameters_version: {e}", cause=e)

        # (c) Load parameters
        try:
            acquisition_config, enrichment_params, analysis_params = load_parameters(
                settings.parameters_path
            )
        except Exception as e:
            raise PreflightError(f"Failed to load parameters: {e}", cause=e)

        # (d) Run ADR-013 parameters.toml / FORMULATION.md consistency check
        try:
            from scripts.verify_parameters_consistency import verify_parameters_consistency
            # FORMULATION.md lives at a fixed location relative to the project
            # root; parameters_path (config/parameters.toml) is two directories
            # below that same root (see ARCHITECTURE.md's Module Structure tree).
            formulation_path = (
                settings.parameters_path.parent.parent
                / ".claude"
                / "context"
                / "FORMULATION.md"
            )
            try:
                verify_parameters_consistency(formulation_path, settings.parameters_path)
            except Exception as e:
                raise PreflightError(
                    f"Parameters consistency check failed: {e}", cause=e
                )
        except ImportError:
            # Script not available in this environment; skip this check and log a warning
            append_run_event(
                conn,
                run_id,
                stage=RUN_LEVEL_STAGE,
                level="warning",
                message="verify_parameters_consistency script not available; skipping consistency check",
            )

        # (e) Initialize schema / migrate
        try:
            initialize_schema(conn)
            migrate(conn)
        except Exception as e:
            raise PreflightError(f"Failed to initialize/migrate schema: {e}", cause=e)

        # === EXECUTION ===

        # Create event sink
        sink = make_event_sink(conn, run_id)

        # Emit run started event
        append_run_event(
            conn,
            run_id,
            stage=RUN_LEVEL_STAGE,
            level="info",
            message="Pipeline starting",
        )

        # Create a list of stages in order for comparison
        # list(PipelineStage) is guaranteed to be in declaration order (Python 3.7+)
        all_stages = list(PipelineStage)
        start_stage_index = all_stages.index(config.start_stage)

        # For each stage from config.start_stage onward
        for stage_index, stage in enumerate(all_stages):
            # Skip stages before start_stage
            if stage_index < start_stage_index:
                continue

            current_stage = stage

            # CP1: Check cancellation before beginning the stage
            if cancel_token is not None and cancel_token.is_set():
                raise PipelineCancelled(stage.value)

            # Begin the stage
            begin_run_stage(conn, run_id, stage.value)
            stages_run.append(stage)

            # Call the stage entry point based on the stage
            if stage == PipelineStage.ACQUISITION:
                report = run_acquisition(
                    conn,
                    run_id,
                    acquisition_config,
                    settings,
                    on_event=sink,
                    max_catalog_pages=config.max_catalog_pages,
                )
                reports["acquisition"] = report

            elif stage == PipelineStage.ENRICHMENT:
                report = run_enrichment(
                    conn,
                    run_id,
                    enrichment_params,
                    parameters_version=parameters_version_value,
                    on_event=sink,
                )
                reports["enrichment"] = report

            elif stage == PipelineStage.ANALYSIS:
                report = run_analysis(
                    conn,
                    run_id,
                    analysis_params,
                    parameters_version=parameters_version_value,
                    on_event=sink,
                )
                reports["analysis"] = report

            # Finish the stage as succeeded
            finish_run_stage(conn, run_id, stage.value, "succeeded")

            # Append stage-complete event
            append_run_event(
                conn,
                run_id,
                stage=RUN_LEVEL_STAGE,
                level="info",
                message=f"Pipeline stage {stage.value} completed successfully",
            )

        # === SUCCESS ===

        # Update run status to succeeded
        update_run_status(conn, run_id, "succeeded")

        # Append run finished event
        append_run_event(
            conn,
            run_id,
            stage=RUN_LEVEL_STAGE,
            level="info",
            message="Pipeline completed successfully",
        )

        finished_at = datetime.utcnow()
        duration_seconds = (finished_at - started_at).total_seconds()

        return PipelineResult(
            run_id=run_id,
            status="succeeded",
            stages_run=stages_run,
            acquisition=reports.get("acquisition"),
            enrichment=reports.get("enrichment"),
            analysis=reports.get("analysis"),
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            error_message=None,
        )

    except BaseException as exc:
        # === EXCEPTION HANDLING ===

        finished_at = datetime.utcnow()
        duration_seconds = (finished_at - started_at).total_seconds()

        # Determine which stage the exception occurred in
        exception_stage = current_stage.value if current_stage is not None else RUN_LEVEL_STAGE

        # Map exception to terminal status
        run_status, stage_status, error_message = _map_exception_to_terminal_status(
            exc, exception_stage
        )

        # Write finish_run_stage if appropriate (not for PreflightError which has no stage row)
        if stage_status is not None and current_stage is not None:
            try:
                finish_run_stage(conn, run_id, exception_stage, stage_status)
            except Exception as storage_exc:
                # Log storage failure but preserve the original exception
                logger.exception(
                    "Failed to write finish_run_stage while handling %s: %s",
                    type(exc).__name__,
                    storage_exc,
                )

        # Write run status
        try:
            update_run_status(conn, run_id, run_status)
        except Exception as storage_exc:
            # Log storage failure but preserve the original exception
            logger.exception(
                "Failed to write run status while handling %s: %s",
                type(exc).__name__,
                storage_exc,
            )

        # Append error event with full traceback
        try:
            append_run_event(
                conn,
                run_id,
                stage=RUN_LEVEL_STAGE,
                level="error",
                message=f"Pipeline failed: {error_message}",
            )
            # Also append the full traceback as a separate error event
            tb_str = traceback.format_exc()
            append_run_event(
                conn,
                run_id,
                stage=RUN_LEVEL_STAGE,
                level="error",
                message=f"Full traceback:\n{tb_str}",
            )
        except Exception:
            # Silently ignore event logging failures
            pass

        # Build result with partial data
        return PipelineResult(
            run_id=run_id,
            status=run_status,
            stages_run=stages_run,
            acquisition=reports.get("acquisition"),
            enrichment=reports.get("enrichment"),
            analysis=reports.get("analysis"),
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            error_message=error_message,
        )
