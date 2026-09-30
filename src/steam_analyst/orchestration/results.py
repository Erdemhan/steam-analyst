"""Pipeline result dataclass: outcome of one run_pipeline call.

This module defines PipelineResult, which encapsulates the outcome of a
single pipeline execution call, including terminal status, stage execution
history, individual stage reports, and timing information.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from steam_analyst.acquisition.pipeline import AcquisitionReport
from steam_analyst.enrichment.pipeline import EnrichmentReport
from steam_analyst.analysis.pipeline import AnalysisReport
from .stages import PipelineStage


@dataclass(frozen=True)
class PipelineResult:
    """Outcome of one run_pipeline call.

    This dataclass represents the complete result of a single pipeline
    execution. It is always returned (never raised as an exception),
    capturing success, failure, or cancellation along with stage-specific
    reports and timing information.

    Attributes:
        run_id: The run identifier for this execution.
        status: The terminal runs.status value written for this call
            ('succeeded', 'failed', or 'cancelled'). run_pipeline always ends
            in one of these three states, never 'pending' or 'running'.
        stages_run: The PipelineStage members actually attempted this call,
            in execution order. For a resume starting at ENRICHMENT, this
            excludes ACQUISITION even though the overall run has an
            acquisition stage from an earlier call.
        acquisition: The acquisition stage's own report object if that stage
            was attempted and returned normally this call, else None. A None
            here does not necessarily mean failure -- it may simply mean this
            call's start_stage skipped it.
        enrichment: The enrichment stage's own report object if that stage
            was attempted and returned normally this call, else None.
        analysis: The analysis stage's own report object if that stage was
            attempted and returned normally this call, else None.
        started_at: The wall-clock datetime when this call began.
        finished_at: The wall-clock datetime when this call ended.
        duration_seconds: Wall-clock time for this call only, not the run's
            cumulative time across a crash and a resume. Should equal
            (finished_at - started_at).total_seconds() within floating-point
            tolerance.
        error_message: Populated only when status != 'succeeded', formatted
            per orchestration's fixed '{stage}: {ExceptionType}: {message}'
            convention. None when status == 'succeeded'.

    Postconditions:
        - status == 'succeeded' implies error_message is None and every stage
          in stages_run has a non-None report.
        - status != 'succeeded' implies error_message is not None.
        - finished_at - started_at, in seconds, equals duration_seconds
          within floating-point tolerance.
    """

    run_id: str
    status: str
    stages_run: list[PipelineStage]
    acquisition: Optional[AcquisitionReport]
    enrichment: Optional[EnrichmentReport]
    analysis: Optional[AnalysisReport]
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    error_message: Optional[str]
