"""
Unit tests for orchestration.stages module.

Tests the PipelineStage enum declaration and RUN_LEVEL_STAGE constant,
ensuring they match the storage schema constraints and maintain the
declared execution order.
"""

import pytest

from steam_analyst.orchestration.stages import PipelineStage, RUN_LEVEL_STAGE


class TestPipelineStageDeclaration:
    """Tests for PipelineStage enum structure and ordering."""

    def test_declaration_order_is_execution_order(self) -> None:
        """list(PipelineStage) matches the documented three-stage sequence.

        Verifies that the enum declaration order is exactly:
        ACQUISITION, ENRICHMENT, ANALYSIS.
        """
        stages = list(PipelineStage)
        expected = [
            PipelineStage.ACQUISITION,
            PipelineStage.ENRICHMENT,
            PipelineStage.ANALYSIS,
        ]
        assert stages == expected

    def test_values_match_run_stages_check_literals(self) -> None:
        """Every PipelineStage value is a run_stages CHECK-constrained literal.

        Verifies that each enum value corresponds to one of the literals
        allowed by the run_stages.stage CHECK constraint in storage schema:
        ('acquisition', 'enrichment', 'analysis').
        """
        # These are the CHECK constraint literals from storage schema
        check_literals = {"acquisition", "enrichment", "analysis"}

        stage_values = {stage.value for stage in PipelineStage}

        assert stage_values == check_literals
        assert PipelineStage.ACQUISITION.value == "acquisition"
        assert PipelineStage.ENRICHMENT.value == "enrichment"
        assert PipelineStage.ANALYSIS.value == "analysis"

    def test_run_level_stage_distinct_from_pipeline_stages(self) -> None:
        """RUN_LEVEL_STAGE is not equal to any PipelineStage member's value.

        Verifies that the run-level stage constant 'pipeline' is distinct
        from all executable stages, so it will never accidentally collide
        with a stage value and can never pass the run_stages CHECK constraint.
        """
        pipeline_stage_values = {stage.value for stage in PipelineStage}

        assert RUN_LEVEL_STAGE == "pipeline"
        assert RUN_LEVEL_STAGE not in pipeline_stage_values
        assert RUN_LEVEL_STAGE != PipelineStage.ACQUISITION.value
        assert RUN_LEVEL_STAGE != PipelineStage.ENRICHMENT.value
        assert RUN_LEVEL_STAGE != PipelineStage.ANALYSIS.value
