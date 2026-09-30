"""
Orchestration module: pipeline execution, stage sequencing, and run management.

Sequences acquisition -> enrichment -> analysis for one run. Creates the run row,
runs parameter-consistency preflight, maintains per-stage status, emits progress
events, services cooperative cancellation, and translates every exception into
a terminal run status.

This module is the only place that knows the pipeline order. The three stage
modules (acquisition, enrichment, analysis) do not import each other and do not
import this module (ADR-009).
"""

from .errors import PipelineError, PipelineCancelled, PreflightError
from .events import make_event_sink
from .pipeline import run_pipeline
from .pipeline_config import PipelineConfig
from .results import PipelineResult
from .stages import PipelineStage, RUN_LEVEL_STAGE
from .runner import (
    start_pipeline_async,
    resume_run,
    cancel_run,
    is_running,
    active_run_ids,
    reconcile_orphaned_runs,
)

__all__ = [
    "PipelineError",
    "PipelineCancelled",
    "PreflightError",
    "PipelineStage",
    "RUN_LEVEL_STAGE",
    "make_event_sink",
    "PipelineConfig",
    "PipelineResult",
    "run_pipeline",
    "start_pipeline_async",
    "resume_run",
    "cancel_run",
    "is_running",
    "active_run_ids",
    "reconcile_orphaned_runs",
]
