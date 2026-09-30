"""Unit tests for orchestration.results module."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from steam_analyst.orchestration.results import PipelineResult
from steam_analyst.orchestration.stages import PipelineStage
from steam_analyst.acquisition.pipeline import AcquisitionReport
from steam_analyst.enrichment.pipeline import EnrichmentReport
from steam_analyst.analysis.pipeline import AnalysisReport


# Fixtures for common test data
@pytest.fixture
def mock_acquisition_report():
    """Create a mock AcquisitionReport for testing."""
    return AcquisitionReport(
        run_id="test_run_001",
        catalog_size=150000,
        candidate_count=5000,
        detail_fetched=4950,
        detail_failed=50,
        reviews_fetched=4900,
        reviews_failed=100,
        requests_made=10000,
        duration_seconds=3600.0,
        funnel=MagicMock(),
    )


@pytest.fixture
def mock_enrichment_report():
    """Create a mock EnrichmentReport for testing."""
    return EnrichmentReport(
        run_id="test_run_001",
        rows_written=4500,
        rows_dropped=400,
        dropped_by_reason={"non_game_app_type": 400},
        imputation_rate_by_feature={
            "size_bytes": 0.05,
            "achievement_count": 0.10,
            "dlc_count": 0.02,
        },
        unmatched_genre_count=50,
        free_to_play_count=200,
        duration_seconds=1200.0,
    )


@pytest.fixture
def mock_analysis_report():
    """Create a mock AnalysisReport for testing."""
    return AnalysisReport(
        run_id="test_run_001",
        candidates_in=4500,
        simple_subset_size=3500,
        rejected_by_reason={"too_complex": 1000},
        cluster_count=150,
        scored_cluster_count=120,
        clusters_below_min_size=30,
        duration_seconds=800.0,
    )


class TestPipelineResultSuccessful:
    """Tests for successful pipeline results."""

    def test_succeeded_result_has_no_error_message(
        self,
        mock_acquisition_report,
        mock_enrichment_report,
        mock_analysis_report,
    ):
        """A full successful run's PipelineResult has error_message=None and all reports populated."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 30, 0)

        result = PipelineResult(
            run_id="test_run_001",
            status="succeeded",
            stages_run=[
                PipelineStage.ACQUISITION,
                PipelineStage.ENRICHMENT,
                PipelineStage.ANALYSIS,
            ],
            acquisition=mock_acquisition_report,
            enrichment=mock_enrichment_report,
            analysis=mock_analysis_report,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=1800.0,
            error_message=None,
        )

        assert result.status == "succeeded"
        assert result.error_message is None
        assert result.acquisition is not None
        assert result.enrichment is not None
        assert result.analysis is not None
        assert result.run_id == "test_run_001"

    def test_succeeded_status_implies_no_error_message(
        self,
        mock_acquisition_report,
        mock_enrichment_report,
        mock_analysis_report,
    ):
        """When status is 'succeeded', error_message must be None."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 30, 0)

        result = PipelineResult(
            run_id="test_run_001",
            status="succeeded",
            stages_run=[
                PipelineStage.ACQUISITION,
                PipelineStage.ENRICHMENT,
                PipelineStage.ANALYSIS,
            ],
            acquisition=mock_acquisition_report,
            enrichment=mock_enrichment_report,
            analysis=mock_analysis_report,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=1800.0,
            error_message=None,
        )

        # Postcondition: status == 'succeeded' implies error_message is None
        if result.status == "succeeded":
            assert result.error_message is None

    def test_succeeded_status_implies_all_stages_have_reports(
        self,
        mock_acquisition_report,
        mock_enrichment_report,
        mock_analysis_report,
    ):
        """When status is 'succeeded', all stages in stages_run must have non-None reports."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 30, 0)

        result = PipelineResult(
            run_id="test_run_001",
            status="succeeded",
            stages_run=[
                PipelineStage.ACQUISITION,
                PipelineStage.ENRICHMENT,
                PipelineStage.ANALYSIS,
            ],
            acquisition=mock_acquisition_report,
            enrichment=mock_enrichment_report,
            analysis=mock_analysis_report,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=1800.0,
            error_message=None,
        )

        # Postcondition: status == 'succeeded' implies every stage in stages_run
        # has a non-None report
        if result.status == "succeeded":
            for stage in result.stages_run:
                if stage == PipelineStage.ACQUISITION:
                    assert result.acquisition is not None
                elif stage == PipelineStage.ENRICHMENT:
                    assert result.enrichment is not None
                elif stage == PipelineStage.ANALYSIS:
                    assert result.analysis is not None


class TestPipelineResultFailed:
    """Tests for failed pipeline results."""

    def test_failed_result_has_error_message_and_partial_reports(
        self, mock_acquisition_report
    ):
        """A run failing in enrichment has acquisition populated, enrichment/analysis None, and error_message set."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 20, 0)

        result = PipelineResult(
            run_id="test_run_001",
            status="failed",
            stages_run=[PipelineStage.ACQUISITION, PipelineStage.ENRICHMENT],
            acquisition=mock_acquisition_report,
            enrichment=None,
            analysis=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=1200.0,
            error_message="enrichment: EnrichmentError: Invalid feature value",
        )

        assert result.status == "failed"
        assert result.acquisition is not None
        assert result.enrichment is None
        assert result.analysis is None
        assert result.error_message is not None
        assert "enrichment" in result.error_message

    def test_failed_status_implies_error_message(self, mock_acquisition_report):
        """When status is not 'succeeded', error_message must be populated."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 20, 0)

        result = PipelineResult(
            run_id="test_run_001",
            status="failed",
            stages_run=[PipelineStage.ACQUISITION, PipelineStage.ENRICHMENT],
            acquisition=mock_acquisition_report,
            enrichment=None,
            analysis=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=1200.0,
            error_message="enrichment: EnrichmentError: Database connection lost",
        )

        # Postcondition: status != 'succeeded' implies error_message is not None
        if result.status != "succeeded":
            assert result.error_message is not None


class TestPipelineResultCancelled:
    """Tests for cancelled pipeline results."""

    def test_cancelled_result_during_acquisition(self):
        """A run cancelled during acquisition has partial or no data."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 5, 0)

        # Per spec edge case: a run cancelled during acquisition, before
        # enrichment ever begins. acquisition is None if the stage entry
        # point never returned normally (it raised PipelineCancelled), even
        # though partial raw_games rows were committed.
        result = PipelineResult(
            run_id="test_run_001",
            status="cancelled",
            stages_run=[PipelineStage.ACQUISITION],
            acquisition=None,
            enrichment=None,
            analysis=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=300.0,
            error_message="acquisition: PipelineCancelled: User cancelled the run",
        )

        assert result.status == "cancelled"
        assert result.error_message is not None
        assert result.acquisition is None

    def test_cancelled_status_implies_error_message(self):
        """When status is 'cancelled', error_message must be populated."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 5, 0)

        result = PipelineResult(
            run_id="test_run_001",
            status="cancelled",
            stages_run=[PipelineStage.ACQUISITION],
            acquisition=None,
            enrichment=None,
            analysis=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=300.0,
            error_message="acquisition: PipelineCancelled: User cancelled",
        )

        # Postcondition: status != 'succeeded' implies error_message is not None
        if result.status != "succeeded":
            assert result.error_message is not None


class TestPipelineResultResume:
    """Tests for resume scenarios."""

    def test_resume_starting_at_enrichment(
        self, mock_enrichment_report, mock_analysis_report
    ):
        """A resume call starting at ENRICHMENT that succeeds: acquisition is None even if run has earlier data."""
        started_at = datetime(2026, 9, 22, 15, 0, 0)
        finished_at = datetime(2026, 9, 22, 15, 45, 0)

        # Per spec edge case: a resume call starting at ENRICHMENT that
        # succeeds: stages_run == [PipelineStage.ENRICHMENT,
        # PipelineStage.ANALYSIS]; acquisition is None even though the run
        # overall does have acquisition data from the original call
        result = PipelineResult(
            run_id="test_run_001",
            status="succeeded",
            stages_run=[PipelineStage.ENRICHMENT, PipelineStage.ANALYSIS],
            acquisition=None,
            enrichment=mock_enrichment_report,
            analysis=mock_analysis_report,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=2700.0,
            error_message=None,
        )

        assert result.status == "succeeded"
        assert result.error_message is None
        assert result.acquisition is None
        assert result.enrichment is not None
        assert result.analysis is not None
        assert PipelineStage.ACQUISITION not in result.stages_run
        assert PipelineStage.ENRICHMENT in result.stages_run
        assert PipelineStage.ANALYSIS in result.stages_run


class TestPipelineResultTiming:
    """Tests for duration and timing calculations."""

    def test_duration_matches_timestamps(self):
        """duration_seconds should equal (finished_at - started_at).total_seconds()."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 30, 0)

        # Expected duration: 30 minutes = 1800 seconds
        expected_duration = (finished_at - started_at).total_seconds()
        assert expected_duration == 1800.0

        result = PipelineResult(
            run_id="test_run_001",
            status="succeeded",
            stages_run=[
                PipelineStage.ACQUISITION,
                PipelineStage.ENRICHMENT,
                PipelineStage.ANALYSIS,
            ],
            acquisition=MagicMock(spec=AcquisitionReport),
            enrichment=MagicMock(spec=EnrichmentReport),
            analysis=MagicMock(spec=AnalysisReport),
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=1800.0,
            error_message=None,
        )

        # Postcondition: duration_seconds equals (finished_at - started_at)
        # within floating-point tolerance
        actual_duration = (result.finished_at - result.started_at).total_seconds()
        assert abs(result.duration_seconds - actual_duration) < 1e-6

    def test_duration_with_microseconds(self):
        """duration_seconds should handle microsecond precision."""
        started_at = datetime(2026, 9, 22, 10, 0, 0, 500000)  # 0.5 seconds
        finished_at = datetime(2026, 9, 22, 10, 30, 0, 250000)  # 0.25 seconds

        expected_duration = (finished_at - started_at).total_seconds()
        # 30 minutes - 0.25 seconds = 1799.75 seconds

        result = PipelineResult(
            run_id="test_run_001",
            status="succeeded",
            stages_run=[PipelineStage.ACQUISITION],
            acquisition=MagicMock(spec=AcquisitionReport),
            enrichment=None,
            analysis=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=expected_duration,
            error_message=None,
        )

        actual_duration = (result.finished_at - result.started_at).total_seconds()
        assert abs(result.duration_seconds - actual_duration) < 1e-6

    def test_very_short_duration(self):
        """Tests a very short pipeline execution duration."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 0, 1)

        expected_duration = 1.0

        result = PipelineResult(
            run_id="test_run_001",
            status="failed",
            stages_run=[PipelineStage.ACQUISITION],
            acquisition=None,
            enrichment=None,
            analysis=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=expected_duration,
            error_message="acquisition: AcquisitionError: Immediate failure",
        )

        actual_duration = (result.finished_at - result.started_at).total_seconds()
        assert abs(result.duration_seconds - actual_duration) < 1e-6
        assert result.duration_seconds == 1.0


class TestPipelineResultImmutability:
    """Tests for frozen dataclass behavior."""

    def test_pipeline_result_is_frozen(self, mock_acquisition_report):
        """PipelineResult is a frozen dataclass and cannot be modified."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 30, 0)

        result = PipelineResult(
            run_id="test_run_001",
            status="failed",
            stages_run=[PipelineStage.ACQUISITION],
            acquisition=mock_acquisition_report,
            enrichment=None,
            analysis=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=1800.0,
            error_message="acquisition: AcquisitionError: Test error",
        )

        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            result.status = "succeeded"

        with pytest.raises(Exception):
            result.run_id = "different_run"

        with pytest.raises(Exception):
            result.error_message = None


class TestPipelineResultFields:
    """Tests for field types and values."""

    def test_all_fields_present(self, mock_acquisition_report):
        """All required fields must be present in PipelineResult."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 30, 0)

        result = PipelineResult(
            run_id="test_run_001",
            status="failed",
            stages_run=[PipelineStage.ACQUISITION],
            acquisition=mock_acquisition_report,
            enrichment=None,
            analysis=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=1800.0,
            error_message="acquisition: AcquisitionError: Test",
        )

        # Verify all fields exist and have expected types
        assert isinstance(result.run_id, str)
        assert isinstance(result.status, str)
        assert isinstance(result.stages_run, list)
        assert result.acquisition is not None
        assert result.enrichment is None
        assert result.analysis is None
        assert isinstance(result.started_at, datetime)
        assert isinstance(result.finished_at, datetime)
        assert isinstance(result.duration_seconds, float)
        assert isinstance(result.error_message, str) or result.error_message is None

    def test_stages_run_contains_pipeline_stages(self):
        """stages_run should contain only PipelineStage enum members."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 30, 0)

        result = PipelineResult(
            run_id="test_run_001",
            status="succeeded",
            stages_run=[
                PipelineStage.ACQUISITION,
                PipelineStage.ENRICHMENT,
                PipelineStage.ANALYSIS,
            ],
            acquisition=MagicMock(spec=AcquisitionReport),
            enrichment=MagicMock(spec=EnrichmentReport),
            analysis=MagicMock(spec=AnalysisReport),
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=1800.0,
            error_message=None,
        )

        for stage in result.stages_run:
            assert isinstance(stage, PipelineStage)
            assert stage in PipelineStage

    def test_empty_stages_run_list(self):
        """stages_run can be an empty list (though this should be rare)."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 0, 0)

        result = PipelineResult(
            run_id="test_run_001",
            status="cancelled",
            stages_run=[],
            acquisition=None,
            enrichment=None,
            analysis=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=0.0,
            error_message="pipeline: PipelineCancelled: Cancelled before any stage",
        )

        assert result.stages_run == []
        assert result.error_message is not None


class TestPipelineResultStatusValues:
    """Tests for valid status values."""

    def test_status_succeeded(self):
        """status can be 'succeeded'."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 30, 0)

        result = PipelineResult(
            run_id="test_run_001",
            status="succeeded",
            stages_run=[PipelineStage.ACQUISITION],
            acquisition=MagicMock(spec=AcquisitionReport),
            enrichment=None,
            analysis=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=1800.0,
            error_message=None,
        )

        assert result.status == "succeeded"

    def test_status_failed(self):
        """status can be 'failed'."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 30, 0)

        result = PipelineResult(
            run_id="test_run_001",
            status="failed",
            stages_run=[PipelineStage.ACQUISITION],
            acquisition=None,
            enrichment=None,
            analysis=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=1800.0,
            error_message="acquisition: AcquisitionError: Failed",
        )

        assert result.status == "failed"

    def test_status_cancelled(self):
        """status can be 'cancelled'."""
        started_at = datetime(2026, 9, 22, 10, 0, 0)
        finished_at = datetime(2026, 9, 22, 10, 30, 0)

        result = PipelineResult(
            run_id="test_run_001",
            status="cancelled",
            stages_run=[PipelineStage.ACQUISITION],
            acquisition=None,
            enrichment=None,
            analysis=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=1800.0,
            error_message="pipeline: PipelineCancelled: Cancelled",
        )

        assert result.status == "cancelled"
