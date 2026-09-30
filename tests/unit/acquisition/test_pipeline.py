"""Unit tests for the acquisition pipeline stage."""

import hashlib
import json
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from steam_analyst.acquisition.errors import AcquisitionError, RequestBudgetExceeded
from steam_analyst.acquisition.funnel import AcquisitionReport, FunnelResult
from steam_analyst.acquisition.pipeline import (
    _fetch_and_filter_details,
    _fetch_and_persist_reviews,
    _fetch_and_persist_steamspy,
    _parse_release_date,
    run_acquisition,
)
from steam_analyst.config import AcquisitionConfig, CoarseFilterCriteria, Settings
from steam_analyst.storage import (
    RawPayload,
    create_run,
    initialize_schema,
    read_analysis_result,
    read_fetched_appids,
)


def compute_payload_sha256(payload: dict) -> str:
    """Compute SHA256 the same way storage.upsert_raw_payloads does."""
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        yield conn
        conn.close()


@pytest.fixture
def run_id(temp_db):
    """Create a test run."""
    run_id = create_run(
        temp_db,
        trigger_type="manual",
        config={},
        parameters_version="test-v1",
    )
    return run_id


@pytest.fixture
def settings(tmp_path):
    """Create test settings."""
    return Settings(
        db_path=tmp_path / "test.db",
        steam_web_api_key="test-key",
        http_timeout_seconds=5.0,
        user_agent="TestAgent/1.0",
        parameters_path=tmp_path / "parameters.toml",
    )


@pytest.fixture
def coarse_filter_criteria():
    """Create a standard coarse filter criteria."""
    return CoarseFilterCriteria(
        min_review_count=25,
        max_review_count=None,
        earliest_release_date=date(2020, 1, 1),
        latest_release_date=None,
        include_free_to_play=True,
        max_price_usd=None,
        publisher_blocklist=[],
    )


@pytest.fixture
def acquisition_config(coarse_filter_criteria):
    """Create an acquisition config."""
    return AcquisitionConfig(
        steamspy_page_delay_seconds=0.01,
        steam_requests_per_minute=60.0,
        max_retries=2,
        backoff_base_seconds=0.1,
        backoff_max_seconds=1.0,
        request_budget=1000,
        coarse_filter=coarse_filter_criteria,
    )


@pytest.fixture
def mock_event_sink():
    """Create a mock event sink."""
    return Mock()


class TestRunAcquisitionFullSuccess:
    """Test a full successful acquisition run."""

    def test_run_acquisition_full_success(
        self, temp_db, run_id, settings, acquisition_config, mock_event_sink
    ):
        """Test a complete successful acquisition run with all stages."""
        # Mock the fetch functions
        with patch(
            "steam_analyst.acquisition.pipeline.fetch_steamspy_catalog"
        ) as mock_steamspy, patch(
            "steam_analyst.acquisition.pipeline.build_catalog_frame"
        ) as mock_build_catalog, patch(
            "steam_analyst.acquisition.pipeline.coarse_filter"
        ) as mock_coarse, patch(
            "steam_analyst.acquisition.pipeline.fetch_app_details"
        ) as mock_details, patch(
            "steam_analyst.acquisition.pipeline.fetch_review_summaries"
        ) as mock_reviews, patch(
            "steam_analyst.acquisition.pipeline.HttpClient"
        ):
            # Setup SteamSpy payloads
            app_data = {"appid": 1, "name": "Game 1"}
            steamspy_payloads = [
                RawPayload(
                    appid=1,
                    source="steamspy_all",
                    fetched_at=datetime.utcnow(),
                    http_status=200,
                    payload=app_data,
                    payload_sha256=compute_payload_sha256(app_data),
                ),
            ]
            mock_steamspy.return_value = iter(steamspy_payloads)

            # Setup catalog frame
            catalog_df = pd.DataFrame({"appid": [1], "positive": [50], "negative": [10]})
            mock_build_catalog.return_value = catalog_df

            # Setup coarse filter (1 survivor)
            funnel_result = FunnelResult(
                candidates=pd.DataFrame({"appid": [1]}),
                total_input=1,
                rejected_by_reason={
                    "duplicate_appid": 0,
                    "missing_required_field": 0,
                    "review_count_below_floor": 0,
                    "review_count_above_ceiling": 0,
                    "free_to_play_excluded": 0,
                    "price_above_max": 0,
                    "publisher_blocklisted": 0,
                },
                criteria=acquisition_config.coarse_filter,
            )
            mock_coarse.return_value = funnel_result

            # Setup app details (successful fetch with valid release date)
            details_payload = {
                "1": {
                    "success": True,
                    "data": {
                        "release_date": "Jan 15, 2020",
                        "genres": [{"id": 1, "description": "Action"}],
                    },
                }
            }
            details_raw = RawPayload(
                appid=1,
                source="steam_appdetails",
                fetched_at=datetime.utcnow(),
                http_status=200,
                payload=details_payload,
                payload_sha256=compute_payload_sha256(details_payload),
            )
            mock_details.return_value = iter([details_raw])

            # Setup review summaries
            reviews_payload = {
                "success": 1,
                "query_summary": {"total_reviews": 60, "total_positive": 50},
            }
            reviews_raw = RawPayload(
                appid=1,
                source="steam_reviews",
                fetched_at=datetime.utcnow(),
                http_status=200,
                payload=reviews_payload,
                payload_sha256=compute_payload_sha256(reviews_payload),
            )
            mock_reviews.return_value = iter([reviews_raw])

            # Run acquisition
            report = run_acquisition(
                temp_db,
                run_id,
                acquisition_config,
                settings,
                on_event=mock_event_sink,
            )

            # Assert report
            assert report.run_id == run_id
            assert report.catalog_size == 1
            assert report.candidate_count == 1  # Should be 1 (survived release-date filter)
            assert report.detail_fetched == 1
            assert report.detail_failed == 0
            assert report.reviews_fetched == 1
            assert report.reviews_failed == 0

            # Assert funnel report was written
            funnel_report = read_analysis_result(temp_db, run_id, "funnel_report")
            assert funnel_report is not None
            assert funnel_report["data"]["catalog_size"] == 1
            assert funnel_report["data"]["candidate_count"] == 1
            assert funnel_report["data"]["detail_fetched"] == 1
            assert funnel_report["data"]["detail_failed"] == 0


class TestReleaseDateFilter:
    """Test release-date filtering."""

    def test_release_date_filter_excludes_pre_2020(
        self, temp_db, run_id, settings, acquisition_config, mock_event_sink
    ):
        """Test that apps released before 2020-01-01 are excluded."""
        with patch(
            "steam_analyst.acquisition.pipeline.fetch_steamspy_catalog"
        ) as mock_steamspy, patch(
            "steam_analyst.acquisition.pipeline.build_catalog_frame"
        ) as mock_build_catalog, patch(
            "steam_analyst.acquisition.pipeline.coarse_filter"
        ) as mock_coarse, patch(
            "steam_analyst.acquisition.pipeline.fetch_app_details"
        ) as mock_details, patch(
            "steam_analyst.acquisition.pipeline.fetch_review_summaries"
        ) as mock_reviews, patch(
            "steam_analyst.acquisition.pipeline.HttpClient"
        ):
            # Setup SteamSpy payloads (2 apps)
            app_data_1 = {"appid": 1, "name": "Old Game"}
            app_data_2 = {"appid": 2, "name": "New Game"}
            steamspy_payloads = [
                RawPayload(
                    appid=1,
                    source="steamspy_all",
                    fetched_at=datetime.utcnow(),
                    http_status=200,
                    payload=app_data_1,
                    payload_sha256=compute_payload_sha256(app_data_1),
                ),
                RawPayload(
                    appid=2,
                    source="steamspy_all",
                    fetched_at=datetime.utcnow(),
                    http_status=200,
                    payload=app_data_2,
                    payload_sha256=compute_payload_sha256(app_data_2),
                ),
            ]
            mock_steamspy.return_value = iter(steamspy_payloads)

            # Setup catalog frame
            catalog_df = pd.DataFrame(
                {"appid": [1, 2], "positive": [50, 50], "negative": [10, 10]}
            )
            mock_build_catalog.return_value = catalog_df

            # Setup coarse filter (both survive coarse filter)
            funnel_result = FunnelResult(
                candidates=pd.DataFrame({"appid": [1, 2]}),
                total_input=2,
                rejected_by_reason={
                    "duplicate_appid": 0,
                    "missing_required_field": 0,
                    "review_count_below_floor": 0,
                    "review_count_above_ceiling": 0,
                    "free_to_play_excluded": 0,
                    "price_above_max": 0,
                    "publisher_blocklisted": 0,
                },
                criteria=acquisition_config.coarse_filter,
            )
            mock_coarse.return_value = funnel_result

            # Setup app details (one pre-2020, one post-2020)
            details_payload_1 = {
                "1": {"success": True, "data": {"release_date": "Dec 15, 2019"}}
            }
            details_payload_2 = {
                "2": {"success": True, "data": {"release_date": "Jan 15, 2020"}}
            }
            details_payloads = [
                RawPayload(
                    appid=1,
                    source="steam_appdetails",
                    fetched_at=datetime.utcnow(),
                    http_status=200,
                    payload=details_payload_1,
                    payload_sha256=compute_payload_sha256(details_payload_1),
                ),
                RawPayload(
                    appid=2,
                    source="steam_appdetails",
                    fetched_at=datetime.utcnow(),
                    http_status=200,
                    payload=details_payload_2,
                    payload_sha256=compute_payload_sha256(details_payload_2),
                ),
            ]
            mock_details.return_value = iter(details_payloads)

            # Setup review summaries (only for the surviving app)
            reviews_payload = {"success": 1, "query_summary": {"total_reviews": 60}}
            reviews_raw = RawPayload(
                appid=2,
                source="steam_reviews",
                fetched_at=datetime.utcnow(),
                http_status=200,
                payload=reviews_payload,
                payload_sha256=compute_payload_sha256(reviews_payload),
            )
            mock_reviews.return_value = iter([reviews_raw])

            # Run acquisition
            report = run_acquisition(
                temp_db,
                run_id,
                acquisition_config,
                settings,
                on_event=mock_event_sink,
            )

            # Assert: only app 2 should survive (1 was pre-2020)
            assert report.catalog_size == 2
            assert report.candidate_count == 1  # Only app 2
            assert report.detail_fetched == 2

            # Assert funnel report shows 1 release_date rejection
            funnel_report = read_analysis_result(temp_db, run_id, "funnel_report")
            assert funnel_report["rejected_by_reason"]["release_date_outside_window"] == 1


class TestTotalFailureCase:
    """Test the total failure case: candidates_count > 0 but detail_fetched == 0."""

    def test_candidate_count_gt_zero_but_detail_fetched_zero_raises(
        self, temp_db, run_id, settings, acquisition_config, mock_event_sink
    ):
        """Test that candidate_count > 0 with detail_fetched == 0 raises AcquisitionError."""
        with patch(
            "steam_analyst.acquisition.pipeline.fetch_steamspy_catalog"
        ) as mock_steamspy, patch(
            "steam_analyst.acquisition.pipeline.build_catalog_frame"
        ) as mock_build_catalog, patch(
            "steam_analyst.acquisition.pipeline.coarse_filter"
        ) as mock_coarse, patch(
            "steam_analyst.acquisition.pipeline.fetch_app_details"
        ) as mock_details, patch(
            "steam_analyst.acquisition.pipeline.HttpClient"
        ):
            # Setup SteamSpy payloads
            app_data = {"appid": 1, "name": "Game 1"}
            steamspy_payloads = [
                RawPayload(
                    appid=1,
                    source="steamspy_all",
                    fetched_at=datetime.utcnow(),
                    http_status=200,
                    payload=app_data,
                    payload_sha256=compute_payload_sha256(app_data),
                ),
            ]
            mock_steamspy.return_value = iter(steamspy_payloads)

            # Setup catalog frame
            catalog_df = pd.DataFrame({"appid": [1], "positive": [50], "negative": [10]})
            mock_build_catalog.return_value = catalog_df

            # Setup coarse filter (1 survivor)
            funnel_result = FunnelResult(
                candidates=pd.DataFrame({"appid": [1]}),
                total_input=1,
                rejected_by_reason={
                    "duplicate_appid": 0,
                    "missing_required_field": 0,
                    "review_count_below_floor": 0,
                    "review_count_above_ceiling": 0,
                    "free_to_play_excluded": 0,
                    "price_above_max": 0,
                    "publisher_blocklisted": 0,
                },
                criteria=acquisition_config.coarse_filter,
            )
            mock_coarse.return_value = funnel_result

            # Setup app details (all failures)
            error_payload = {"error": "Internal Server Error"}
            details_raw = RawPayload(
                appid=1,
                source="steam_appdetails",
                fetched_at=datetime.utcnow(),
                http_status=500,  # Error response
                payload=error_payload,
                payload_sha256=compute_payload_sha256(error_payload),
            )
            mock_details.return_value = iter([details_raw])

            # Run acquisition and expect AcquisitionError
            with pytest.raises(AcquisitionError) as exc_info:
                run_acquisition(
                    temp_db,
                    run_id,
                    acquisition_config,
                    settings,
                    on_event=mock_event_sink,
                )

            assert "Total acquisition failure" in str(exc_info.value)
            assert "detail_fetched == 0" in str(exc_info.value)


class TestZeroCandidatesSuccess:
    """Test the zero-candidates case (legitimate success)."""

    def test_zero_candidates_after_coarse_filter_succeeds(
        self, temp_db, run_id, settings, acquisition_config, mock_event_sink
    ):
        """Test that candidate_count == 0 after coarse filter is a legitimate success."""
        with patch(
            "steam_analyst.acquisition.pipeline.fetch_steamspy_catalog"
        ) as mock_steamspy, patch(
            "steam_analyst.acquisition.pipeline.build_catalog_frame"
        ) as mock_build_catalog, patch(
            "steam_analyst.acquisition.pipeline.coarse_filter"
        ) as mock_coarse, patch(
            "steam_analyst.acquisition.pipeline.HttpClient"
        ):
            # Setup SteamSpy payloads
            app_data = {"appid": 1, "name": "Low-Review Game"}
            steamspy_payloads = [
                RawPayload(
                    appid=1,
                    source="steamspy_all",
                    fetched_at=datetime.utcnow(),
                    http_status=200,
                    payload=app_data,
                    payload_sha256=compute_payload_sha256(app_data),
                ),
            ]
            mock_steamspy.return_value = iter(steamspy_payloads)

            # Setup catalog frame
            catalog_df = pd.DataFrame({"appid": [1], "positive": [5], "negative": [2]})
            mock_build_catalog.return_value = catalog_df

            # Setup coarse filter (0 survivors due to low review count)
            funnel_result = FunnelResult(
                candidates=pd.DataFrame({"appid": []}),
                total_input=1,
                rejected_by_reason={
                    "duplicate_appid": 0,
                    "missing_required_field": 0,
                    "review_count_below_floor": 1,  # Rejected
                    "review_count_above_ceiling": 0,
                    "free_to_play_excluded": 0,
                    "price_above_max": 0,
                    "publisher_blocklisted": 0,
                },
                criteria=acquisition_config.coarse_filter,
            )
            mock_coarse.return_value = funnel_result

            # Run acquisition
            report = run_acquisition(
                temp_db,
                run_id,
                acquisition_config,
                settings,
                on_event=mock_event_sink,
            )

            # Assert: this should succeed with 0 candidates
            assert report.catalog_size == 1
            assert report.candidate_count == 0
            assert report.detail_fetched == 0
            assert report.detail_failed == 0
            assert report.reviews_fetched == 0
            assert report.reviews_failed == 0


class TestResumeLogic:
    """Test resume support (skipping already-fetched appids)."""

    def test_resume_skips_already_fetched_appids(
        self, temp_db, run_id, settings, acquisition_config, mock_event_sink
    ):
        """Test that resume skips appids already in raw_games."""
        from steam_analyst.storage import upsert_raw_payloads

        with patch(
            "steam_analyst.acquisition.pipeline.fetch_steamspy_catalog"
        ) as mock_steamspy, patch(
            "steam_analyst.acquisition.pipeline.build_catalog_frame"
        ) as mock_build_catalog, patch(
            "steam_analyst.acquisition.pipeline.coarse_filter"
        ) as mock_coarse, patch(
            "steam_analyst.acquisition.pipeline.fetch_app_details"
        ) as mock_details, patch(
            "steam_analyst.acquisition.pipeline.fetch_review_summaries"
        ) as mock_reviews, patch(
            "steam_analyst.acquisition.pipeline.HttpClient"
        ):
            # Pre-populate raw_games with app 1 (already fetched)
            existing_payload = {
                "1": {"success": True, "data": {"release_date": "Jan 15, 2020"}}
            }
            existing_raw = RawPayload(
                appid=1,
                source="steam_appdetails",
                fetched_at=datetime.utcnow(),
                http_status=200,
                payload=existing_payload,
                payload_sha256=compute_payload_sha256(existing_payload),
            )
            upsert_raw_payloads(temp_db, run_id, [existing_raw])

            # Setup SteamSpy payloads (2 apps)
            app_data_1 = {"appid": 1, "name": "Game 1"}
            app_data_2 = {"appid": 2, "name": "Game 2"}
            steamspy_payloads = [
                RawPayload(
                    appid=1,
                    source="steamspy_all",
                    fetched_at=datetime.utcnow(),
                    http_status=200,
                    payload=app_data_1,
                    payload_sha256=compute_payload_sha256(app_data_1),
                ),
                RawPayload(
                    appid=2,
                    source="steamspy_all",
                    fetched_at=datetime.utcnow(),
                    http_status=200,
                    payload=app_data_2,
                    payload_sha256=compute_payload_sha256(app_data_2),
                ),
            ]
            mock_steamspy.return_value = iter(steamspy_payloads)

            # Setup catalog frame
            catalog_df = pd.DataFrame(
                {"appid": [1, 2], "positive": [50, 50], "negative": [10, 10]}
            )
            mock_build_catalog.return_value = catalog_df

            # Setup coarse filter (both survivors)
            funnel_result = FunnelResult(
                candidates=pd.DataFrame({"appid": [1, 2]}),
                total_input=2,
                rejected_by_reason={
                    "duplicate_appid": 0,
                    "missing_required_field": 0,
                    "review_count_below_floor": 0,
                    "review_count_above_ceiling": 0,
                    "free_to_play_excluded": 0,
                    "price_above_max": 0,
                    "publisher_blocklisted": 0,
                },
                criteria=acquisition_config.coarse_filter,
            )
            mock_coarse.return_value = funnel_result

            # Setup app details: only fetch app 2 (app 1 already exists)
            details_payload_2 = {
                "2": {"success": True, "data": {"release_date": "Jan 15, 2020"}}
            }
            details_raw = RawPayload(
                appid=2,
                source="steam_appdetails",
                fetched_at=datetime.utcnow(),
                http_status=200,
                payload=details_payload_2,
                payload_sha256=compute_payload_sha256(details_payload_2),
            )
            mock_details.return_value = iter([details_raw])

            # Setup review summaries: only for app 2
            reviews_payload = {"success": 1}
            reviews_raw = RawPayload(
                appid=2,
                source="steam_reviews",
                fetched_at=datetime.utcnow(),
                http_status=200,
                payload=reviews_payload,
                payload_sha256=compute_payload_sha256(reviews_payload),
            )
            mock_reviews.return_value = iter([reviews_raw])

            # Run acquisition
            report = run_acquisition(
                temp_db,
                run_id,
                acquisition_config,
                settings,
                on_event=mock_event_sink,
            )

            # Assert: 2 candidates survived (1 and 2)
            assert report.catalog_size == 2
            assert report.candidate_count == 2


class TestParseReleaseDate:
    """Test the _parse_release_date helper."""

    def test_parse_iso_format(self):
        """Test parsing ISO format dates."""
        result = _parse_release_date("2020-01-15")
        assert result == date(2020, 1, 15)

    def test_parse_us_format(self):
        """Test parsing US format dates."""
        result = _parse_release_date("Jan 15, 2020")
        assert result == date(2020, 1, 15)

    def test_parse_year_only(self):
        """Test parsing year-only dates."""
        result = _parse_release_date("2020")
        assert result == date(2020, 1, 1)

    def test_parse_quarter_format(self):
        """Test parsing quarter format dates."""
        result = _parse_release_date("Q1 2020")
        assert result == date(2020, 1, 1)

        result = _parse_release_date("Q2 2020")
        assert result == date(2020, 4, 1)

    def test_parse_coming_soon(self):
        """Test parsing 'Coming Soon' returns None."""
        result = _parse_release_date("Coming Soon")
        assert result is None

    def test_parse_empty_string(self):
        """Test parsing empty string returns None."""
        result = _parse_release_date("")
        assert result is None

    def test_parse_invalid_format(self):
        """Test parsing invalid format returns None."""
        result = _parse_release_date("Invalid Date Xyz")
        assert result is None
