"""
Pipeline stage declaration and constants.

This module declares the pipeline execution order and the special run-level
stage constant. It is the single place where the three-stage sequence
(acquisition, enrichment, analysis) is declared, and where that sequence
is kept synchronized with the storage schema constraints.

ADR-009: This module knows the pipeline order. The three stage modules
(acquisition, enrichment, analysis) do not import each other and do not
import this module.
"""

from enum import Enum
from typing import Final


class PipelineStage(str, Enum):
    """Declaration order is execution order.

    The three pipeline stages in the order they execute. Values are
    byte-identical to the run_events.stage and run_stages.stage columns
    and to the run_stages CHECK constraint literals ('acquisition',
    'enrichment', 'analysis'), so a stage's enum value can be written
    directly into either table with no translation layer.

    The list(PipelineStage) call returns the stages in execution order:
    [ACQUISITION, ENRICHMENT, ANALYSIS].
    """

    ACQUISITION = "acquisition"
    ENRICHMENT = "enrichment"
    ANALYSIS = "analysis"


RUN_LEVEL_STAGE: Final[str] = "pipeline"
"""The run_events.stage value for run-level records not tied to one stage.

Used for run-level events like preflight, run started, run finished, and
cancellation requested. Deliberately a plain string constant, not a
PipelineStage member, because it is not executable and must never be
accepted by begin_run_stage or finish_run_stage (which are constrained to
the three real stages by the run_stages CHECK constraint).
"""
