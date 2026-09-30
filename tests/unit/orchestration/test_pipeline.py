"""Unit tests for orchestration.pipeline: run_pipeline and _map_exception_to_terminal_status."""

import pandas as pd
import pytest
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from steam_analyst.acquisition.errors import (
    AcquisitionError,
    RequestBudgetExceeded,
)
from steam_analyst.acquisition.pipeline import AcquisitionReport
from steam_analyst.analysis.errors import AnalysisError
from steam_analyst.analysis.pipeline import AnalysisReport
from steam_analyst.config.settings import (
    AcquisitionConfig,
    AnalysisParams,
    EnrichmentParams,
    CoarseFilterCriteria,
    Settings,
)
from steam_analyst.enrichment.errors import EnrichmentError
from steam_analyst.enrichment.pipeline import EnrichmentReport
from steam_analyst.orchestration.errors import PipelineCancelled, PreflightError
from steam_analyst.orchestration.pipeline import (
    _map_exception_to_terminal_status,
    run_pipeline,
)
from steam_analyst.orchestration.pipeline_config import PipelineConfig
from steam_analyst.orchestration.stages import PipelineStage, RUN_LEVEL_STAGE
from steam_analyst.storage import (
    connect,
    create_run,
    initialize_schema,
    read_run_stages,
)
from steam_analyst.storage.types import StorageError


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary SQLite database."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    initialize_schema(conn)
    conn.close()
    return db_path


@pytest.fixture
def conn_for_test(temp_db: Path) -> sqlite3.Connection:
    """Open a connection to the temporary database."""
    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def settings() -> Settings:
    """Create a mock Settings object."""
    return Settings(
        db_path=Path("/tmp/test.db"),
        steam_web_api_key="fake_key",
        http_timeout_seconds=30.0,
        user_agent="Test-Agent",
        parameters_path=Path("/fake/parameters.toml"),
    )


@pytest.fixture
def pipeline_config() -> PipelineConfig:
    """Create a default PipelineConfig."""
    return PipelineConfig(start_stage=PipelineStage.ACQUISITION)


def _create_test_run(conn: sqlite3.Connection, run_id: str, config: PipelineConfig) -> str:
    """Helper to create a run row for testing."""
    return create_run(
        conn,
        config=config.to_dict(),
        parameters_version="test_version_abc123",
    )


def _make_acq_report(run_id: str) -> AcquisitionReport:
    """Create a minimal AcquisitionReport for testing."""
    funnel = MagicMock()
    funnel.total_input = 1000
    funnel.candidates = pd.DataFrame({"appid": [1, 2, 3]})
    funnel.rejected_by_reason = {}
    return AcquisitionReport(
        run_id=run_id,
        catalog_size=1000,
        candidate_count=100,
        detail_fetched=95,
        detail_failed=5,
        reviews_fetched=95,
        reviews_failed=0,
        requests_made=200,
        duration_seconds=10.0,
        funnel=funnel,
    )


def _make_enr_report(run_id: str) -> EnrichmentReport:
    """Create a minimal EnrichmentReport for testing."""
    return EnrichmentReport(
        run_id=run_id,
        rows_written=95,
        rows_dropped=0,
        dropped_by_reason={},
        imputation_rate_by_feature={},
        unmatched_genre_count=0,
        free_to_play_count=0,
        duration_seconds=5.0,
    )


def _make_ana_report(run_id: str) -> AnalysisReport:
    """Create a minimal AnalysisReport for testing."""
    return AnalysisReport(
        run_id=run_id,
        candidates_in=95,
        simple_subset_size=85,
        rejected_by_reason={},
        cluster_count=10,
        scored_cluster_count=8,
        clusters_below_min_size=2,
        duration_seconds=3.0,
    )


# ============================================================================
# Tests for _map_exception_to_terminal_status
# ============================================================================


class TestMapExceptionToTerminalStatus:
    """Tests for the _map_exception_to_terminal_status function."""

    def test_pipeline_cancelled_maps_to_cancelled(self):
        """PipelineCancelled maps to ('cancelled', 'cancelled', message with stage)."""
        exc = PipelineCancelled("enrichment")
        run_status, stage_status, error_message = _map_exception_to_terminal_status(
            exc, "enrichment"
        )
        assert run_status == "cancelled"
        assert stage_status == "cancelled"
        assert "cancelled by user during enrichment" in error_message

    def test_keyboard_interrupt_maps_to_cancelled(self):
        """KeyboardInterrupt maps to ('cancelled', 'cancelled', ...)."""
        exc = KeyboardInterrupt()
        run_status, stage_status, error_message = _map_exception_to_terminal_status(
            exc, "acquisition"
        )
        assert run_status == "cancelled"
        assert stage_status == "cancelled"
        assert "interrupted during acquisition" in error_message

    def test_system_exit_maps_to_cancelled(self):
        """SystemExit maps to ('cancelled', 'cancelled', ...)."""
        exc = SystemExit(1)
        run_status, stage_status, error_message = _map_exception_to_terminal_status(
            exc, "analysis"
        )
        assert run_status == "cancelled"
        assert stage_status == "cancelled"
        assert "interrupted during analysis" in error_message

    def test_preflight_error_maps_to_failed_with_no_stage_status(self):
        """PreflightError maps to ('failed', None, message)."""
        exc = PreflightError("invalid weights", cause=None)
        run_status, stage_status, error_message = _map_exception_to_terminal_status(
            exc, RUN_LEVEL_STAGE
        )
        assert run_status == "failed"
        assert stage_status is None  # Signal: no finish_run_stage call
        assert error_message == "invalid weights"

    def test_request_budget_exceeded_maps_to_failed(self):
        """RequestBudgetExceeded maps to ('failed', 'failed', ...)."""
        exc = RequestBudgetExceeded("budget exceeded: 1000 requests made")
        run_status, stage_status, error_message = _map_exception_to_terminal_status(
            exc, "acquisition"
        )
        assert run_status == "failed"
        assert stage_status == "failed"
        assert "budget exceeded" in error_message

    def test_acquisition_error_maps_to_failed(self):
        """AcquisitionError maps to ('failed', 'failed', '{stage}: AcquisitionError: ...')."""
        exc = AcquisitionError("fetch failed")
        run_status, stage_status, error_message = _map_exception_to_terminal_status(
            exc, "acquisition"
        )
        assert run_status == "failed"
        assert stage_status == "failed"
        assert "acquisition: AcquisitionError:" in error_message
        assert "fetch failed" in error_message

    def test_enrichment_error_maps_to_failed(self):
        """EnrichmentError maps to ('failed', 'failed', ...)."""
        exc = EnrichmentError("enrichment failed")
        run_status, stage_status, error_message = _map_exception_to_terminal_status(
            exc, "enrichment"
        )
        assert run_status == "failed"
        assert stage_status == "failed"
        assert "enrichment: EnrichmentError:" in error_message

    def test_analysis_error_maps_to_failed(self):
        """AnalysisError maps to ('failed', 'failed', ...)."""
        exc = AnalysisError("analysis failed")
        run_status, stage_status, error_message = _map_exception_to_terminal_status(
            exc, "analysis"
        )
        assert run_status == "failed"
        assert stage_status == "failed"
        assert "analysis: AnalysisError:" in error_message

    def test_storage_error_maps_to_failed(self):
        """StorageError maps to ('failed', 'failed', ...)."""
        exc = StorageError("storage failed")
        run_status, stage_status, error_message = _map_exception_to_terminal_status(
            exc, "enrichment"
        )
        assert run_status == "failed"
        assert stage_status == "failed"
        assert "enrichment: StorageError:" in error_message

    def test_generic_exception_maps_to_failed(self):
        """An unrecognized exception falls through to generic mapping."""
        exc = ValueError("something went wrong")
        run_status, stage_status, error_message = _map_exception_to_terminal_status(
            exc, "enrichment"
        )
        assert run_status == "failed"
        assert stage_status == "failed"
        assert "enrichment: ValueError: something went wrong" in error_message

    def test_all_nine_terminal_status_mapping_rows_covered(self):
        """Verify all nine rows of the terminal_status_mapping table are represented."""
        test_cases = [
            (PipelineCancelled("acquisition"), "acquisition", "cancelled", "cancelled"),
            (KeyboardInterrupt(), "acquisition", "cancelled", "cancelled"),
            (PreflightError("test"), RUN_LEVEL_STAGE, "failed", None),
            (RequestBudgetExceeded("budget exceeded"), "acquisition", "failed", "failed"),
            (AcquisitionError("error"), "acquisition", "failed", "failed"),
            (EnrichmentError("error"), "enrichment", "failed", "failed"),
            (AnalysisError("error"), "analysis", "failed", "failed"),
            (StorageError("error"), "enrichment", "failed", "failed"),
            (RuntimeError("unknown"), "analysis", "failed", "failed"),
        ]

        for exc, stage, expected_run_status, expected_stage_status in test_cases:
            run_status, stage_status, error_message = _map_exception_to_terminal_status(
                exc, stage
            )
            assert (
                run_status == expected_run_status
            ), f"Failed for {type(exc).__name__}"
            assert (
                stage_status == expected_stage_status
            ), f"Failed for {type(exc).__name__}"
            assert error_message is not None or stage_status is None


# ============================================================================
# Tests for run_pipeline
# ============================================================================


class TestRunPipeline:
    """Tests for the run_pipeline function."""

    def test_full_run_all_stages_succeed(
        self, conn_for_test: sqlite3.Connection, settings: Settings
    ):
        """A full run with all stages succeeding returns PipelineResult with status='succeeded'."""
        # Create the run row
        run_id = _create_test_run(conn_for_test, "test-run-001", PipelineConfig())

        # Create mock reports
        acq_report = _make_acq_report(run_id)
        enr_report = _make_enr_report(run_id)
        ana_report = _make_ana_report(run_id)

        # Stub stage entry points
        with patch("steam_analyst.orchestration.pipeline.run_acquisition") as mock_acq, \
             patch("steam_analyst.orchestration.pipeline.run_enrichment") as mock_enr, \
             patch("steam_analyst.orchestration.pipeline.run_analysis") as mock_ana, \
             patch("steam_analyst.orchestration.pipeline.load_parameters") as mock_load_params, \
             patch("steam_analyst.orchestration.pipeline.parameters_version") as mock_params_ver, \
             patch("steam_analyst.orchestration.pipeline.load_settings") as mock_load_settings, patch("scripts.verify_parameters_consistency.verify_parameters_consistency") as mock_verify:

            mock_acq.return_value = acq_report
            mock_enr.return_value = enr_report
            mock_ana.return_value = ana_report
            mock_load_params.return_value = (
                MagicMock(spec=AcquisitionConfig),
                MagicMock(spec=EnrichmentParams),
                MagicMock(spec=AnalysisParams),
            )
            mock_params_ver.return_value = "abc123def456"
            mock_load_settings.return_value = settings

            config = PipelineConfig(start_stage=PipelineStage.ACQUISITION)
            result = run_pipeline(conn_for_test, run_id, config, settings=settings)

            assert result.status == "succeeded"
            assert result.error_message is None
            assert len(result.stages_run) == 3
            assert result.acquisition is not None
            assert result.enrichment is not None
            assert result.analysis is not None
            assert result.duration_seconds > 0

    def test_start_stage_enrichment_skips_acquisition(
        self, conn_for_test: sqlite3.Connection, settings: Settings
    ):
        """With start_stage=ENRICHMENT, acquisition is never called."""
        # Create the run row
        config = PipelineConfig(start_stage=PipelineStage.ENRICHMENT)
        run_id = _create_test_run(conn_for_test, "test-run-002", config)

        enr_report = _make_enr_report(run_id)
        ana_report = _make_ana_report(run_id)

        with patch("steam_analyst.orchestration.pipeline.run_acquisition") as mock_acq, \
             patch("steam_analyst.orchestration.pipeline.run_enrichment") as mock_enr, \
             patch("steam_analyst.orchestration.pipeline.run_analysis") as mock_ana, \
             patch("steam_analyst.orchestration.pipeline.load_parameters") as mock_load_params, \
             patch("steam_analyst.orchestration.pipeline.parameters_version") as mock_params_ver, \
             patch("steam_analyst.orchestration.pipeline.load_settings") as mock_load_settings, patch("scripts.verify_parameters_consistency.verify_parameters_consistency") as mock_verify:

            mock_enr.return_value = enr_report
            mock_ana.return_value = ana_report
            mock_load_params.return_value = (
                MagicMock(spec=AcquisitionConfig),
                MagicMock(spec=EnrichmentParams),
                MagicMock(spec=AnalysisParams),
            )
            mock_params_ver.return_value = "abc123def456"
            mock_load_settings.return_value = settings

            result = run_pipeline(conn_for_test, run_id, config, settings=settings)

            # Verify acquisition was never called
            mock_acq.assert_not_called()
            assert result.status == "succeeded"
            assert PipelineStage.ACQUISITION not in result.stages_run
            assert PipelineStage.ENRICHMENT in result.stages_run
            assert PipelineStage.ANALYSIS in result.stages_run

    def test_cancellation_at_cp1_before_first_stage(
        self, conn_for_test: sqlite3.Connection, settings: Settings
    ):
        """A pre-set cancel_token raises PipelineCancelled before any run_stages row exists."""
        config = PipelineConfig()
        run_id = _create_test_run(conn_for_test, "test-run-003", config)

        cancel_token = threading.Event()
        cancel_token.set()  # Pre-set the token

        with patch("steam_analyst.orchestration.pipeline.load_parameters") as mock_load_params, \
             patch("steam_analyst.orchestration.pipeline.parameters_version") as mock_params_ver, \
             patch("steam_analyst.orchestration.pipeline.load_settings") as mock_load_settings, patch("scripts.verify_parameters_consistency.verify_parameters_consistency") as mock_verify:

            mock_load_params.return_value = (
                MagicMock(spec=AcquisitionConfig),
                MagicMock(spec=EnrichmentParams),
                MagicMock(spec=AnalysisParams),
            )
            mock_params_ver.return_value = "abc123def456"
            mock_load_settings.return_value = settings

            result = run_pipeline(
                conn_for_test, run_id, config, settings=settings, cancel_token=cancel_token
            )

            # Cancellation should have occurred at CP1
            assert result.status == "cancelled"
            assert len(result.stages_run) == 0  # No stages started
            # Check that run_stages has no rows (or all are empty)
            stages = read_run_stages(conn_for_test, run_id)
            assert len(stages) == 0

    def test_preflighterror_leaves_no_stage_rows(
        self, conn_for_test: sqlite3.Connection, settings: Settings
    ):
        """A ParameterError from load_parameters produces PreflightError with no stage rows."""
        config = PipelineConfig()
        run_id = _create_test_run(conn_for_test, "test-run-004", config)

        with patch("steam_analyst.orchestration.pipeline.load_parameters") as mock_load_params, \
             patch("steam_analyst.orchestration.pipeline.parameters_version") as mock_params_ver, \
             patch("steam_analyst.orchestration.pipeline.load_settings") as mock_load_settings, patch("scripts.verify_parameters_consistency.verify_parameters_consistency") as mock_verify:

            mock_params_ver.return_value = "abc123def456"
            mock_load_settings.return_value = settings
            # Simulate load_parameters raising ParameterError
            from steam_analyst.config.parameters import ParameterError
            mock_load_params.side_effect = ParameterError("bad weights")

            result = run_pipeline(conn_for_test, run_id, config, settings=settings)

            assert result.status == "failed"
            assert result.error_message is not None
            # Check that no run_stages rows were created
            stages = read_run_stages(conn_for_test, run_id)
            assert len(stages) == 0

    def test_exception_during_stage_writes_terminal_status(
        self, conn_for_test: sqlite3.Connection, settings: Settings
    ):
        """An exception during a stage writes terminal status and re-raises."""
        config = PipelineConfig()
        run_id = _create_test_run(conn_for_test, "test-run-005", config)

        with patch("steam_analyst.orchestration.pipeline.run_acquisition") as mock_acq, \
             patch("steam_analyst.orchestration.pipeline.run_enrichment") as mock_enr, \
             patch("steam_analyst.orchestration.pipeline.run_analysis") as mock_ana, \
             patch("steam_analyst.orchestration.pipeline.load_parameters") as mock_load_params, \
             patch("steam_analyst.orchestration.pipeline.parameters_version") as mock_params_ver, \
             patch("steam_analyst.orchestration.pipeline.load_settings") as mock_load_settings, patch("scripts.verify_parameters_consistency.verify_parameters_consistency") as mock_verify:

            mock_acq.side_effect = AcquisitionError("fetch failed")
            mock_load_params.return_value = (
                MagicMock(spec=AcquisitionConfig),
                MagicMock(spec=EnrichmentParams),
                MagicMock(spec=AnalysisParams),
            )
            mock_params_ver.return_value = "abc123def456"
            mock_load_settings.return_value = settings

            result = run_pipeline(conn_for_test, run_id, config, settings=settings)

            # Should have failed status
            assert result.status == "failed"
            assert result.error_message is not None
            assert "AcquisitionError" in result.error_message
            # Acquisition stage should have a failed status
            stages = read_run_stages(conn_for_test, run_id)
            acq_stage = next((s for s in stages if s.stage == "acquisition"), None)
            assert acq_stage is not None
            assert acq_stage.status == "failed"

    def test_keyboard_interrupt_is_remapped(
        self, conn_for_test: sqlite3.Connection, settings: Settings
    ):
        """KeyboardInterrupt is mapped to 'cancelled' status."""
        config = PipelineConfig()
        run_id = _create_test_run(conn_for_test, "test-run-006", config)

        with patch("steam_analyst.orchestration.pipeline.run_acquisition") as mock_acq, \
             patch("steam_analyst.orchestration.pipeline.load_parameters") as mock_load_params, \
             patch("steam_analyst.orchestration.pipeline.parameters_version") as mock_params_ver, \
             patch("steam_analyst.orchestration.pipeline.load_settings") as mock_load_settings, patch("scripts.verify_parameters_consistency.verify_parameters_consistency") as mock_verify:

            mock_acq.side_effect = KeyboardInterrupt()
            mock_load_params.return_value = (
                MagicMock(spec=AcquisitionConfig),
                MagicMock(spec=EnrichmentParams),
                MagicMock(spec=AnalysisParams),
            )
            mock_params_ver.return_value = "abc123def456"
            mock_load_settings.return_value = settings

            result = run_pipeline(conn_for_test, run_id, config, settings=settings)

            # Status should be 'cancelled'
            assert result.status == "cancelled"
            assert "interrupted" in result.error_message.lower()

    def test_result_duration_matches_timestamps(
        self, conn_for_test: sqlite3.Connection, settings: Settings
    ):
        """PipelineResult.duration_seconds should match (finished_at - started_at).total_seconds()."""
        config = PipelineConfig()
        run_id = _create_test_run(conn_for_test, "test-run-007", config)

        acq_report = _make_acq_report(run_id)
        enr_report = _make_enr_report(run_id)
        ana_report = _make_ana_report(run_id)

        with patch("steam_analyst.orchestration.pipeline.run_acquisition") as mock_acq, \
             patch("steam_analyst.orchestration.pipeline.run_enrichment") as mock_enr, \
             patch("steam_analyst.orchestration.pipeline.run_analysis") as mock_ana, \
             patch("steam_analyst.orchestration.pipeline.load_parameters") as mock_load_params, \
             patch("steam_analyst.orchestration.pipeline.parameters_version") as mock_params_ver, \
             patch("steam_analyst.orchestration.pipeline.load_settings") as mock_load_settings, patch("scripts.verify_parameters_consistency.verify_parameters_consistency") as mock_verify:

            mock_acq.return_value = acq_report
            mock_enr.return_value = enr_report
            mock_ana.return_value = ana_report
            mock_load_params.return_value = (
                MagicMock(spec=AcquisitionConfig),
                MagicMock(spec=EnrichmentParams),
                MagicMock(spec=AnalysisParams),
            )
            mock_params_ver.return_value = "abc123def456"
            mock_load_settings.return_value = settings

            result = run_pipeline(conn_for_test, run_id, config, settings=settings)

            expected_duration = (result.finished_at - result.started_at).total_seconds()
            assert abs(result.duration_seconds - expected_duration) < 0.01  # Allow 10ms tolerance


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
