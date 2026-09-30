"""Unit tests for the acquisition funnel module."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from steam_analyst.acquisition.errors import AcquisitionError, RequestBudgetExceeded
from steam_analyst.acquisition.funnel import (
    AcquisitionReport,
    FunnelResult,
    build_catalog_frame,
    coarse_filter,
    fetch_app_details,
    fetch_review_summaries,
    fetch_steamspy_catalog,
)
from steam_analyst.config import CoarseFilterCriteria
from steam_analyst.storage import EventSink, RawPayload


@pytest.fixture
def mock_event_sink() -> EventSink:
    """Create a mock event sink that records calls."""
    return Mock(spec=EventSink)


@pytest.fixture
def coarse_filter_criteria() -> CoarseFilterCriteria:
    """Create a standard coarse filter criteria for testing."""
    return CoarseFilterCriteria(
        min_review_count=25,
        max_review_count=None,
        earliest_release_date=None,
        latest_release_date=None,
        include_free_to_play=True,
        max_price_usd=None,
        publisher_blocklist=[],
    )


@pytest.fixture
def steamspy_raw_payloads() -> list[RawPayload]:
    """Load fixture steamspy page and create RawPayload objects."""
    fixture_path = Path(__file__).parent.parent.parent / "fixtures" / "steamspy_all_page0.json"
    with open(fixture_path, "r") as f:
        page_data = json.load(f)

    payloads = []
    for appid_str, app_data in page_data.items():
        appid = int(appid_str)
        payload_json = json.dumps(app_data, sort_keys=True).encode("utf-8")
        import hashlib
        payload_sha256 = hashlib.sha256(payload_json).hexdigest()

        payloads.append(
            RawPayload(
                appid=appid,
                source="steamspy_all",
                fetched_at=datetime.utcnow(),
                http_status=200,
                payload=app_data,
                payload_sha256=payload_sha256,
            )
        )

    return payloads


class TestBuildCatalogFrame:
    """Tests for build_catalog_frame."""

    def test_flattens_fixture_page_into_expected_columns(
        self, steamspy_raw_payloads: list[RawPayload]
    ) -> None:
        """Test that fixture page parses into the expected column set with correct dtypes."""
        df = build_catalog_frame(steamspy_raw_payloads)

        # Check that we have the expected columns
        expected_columns = {
            "appid",
            "name",
            "developer",
            "publisher",
            "positive",
            "negative",
            "owners_low",
            "owners_high",
            "price_usd",
            "initialprice",
            "discount",
            "tags",
        }
        assert set(df.columns) == expected_columns

        # Check that we have 3 rows (from the fixture)
        assert len(df) == 3

        # Check specific values
        dishonored = df[df["appid"] == 263060].iloc[0]
        assert dishonored["name"] == "Dishonored"
        assert dishonored["developer"] == "Arkane Studios"
        assert dishonored["price_usd"] == 19.99  # 1999 cents

    def test_price_cents_converted_to_dollars(
        self, steamspy_raw_payloads: list[RawPayload]
    ) -> None:
        """Test that price in cents is converted to dollars."""
        df = build_catalog_frame(steamspy_raw_payloads)

        # Dishonored: price 1999 cents -> 19.99 dollars
        dishonored = df[df["appid"] == 263060].iloc[0]
        assert dishonored["price_usd"] == 19.99

        # Dota 2: free-to-play, price 0 -> 0.0
        dota = df[df["appid"] == 570].iloc[0]
        assert dota["price_usd"] == 0.0

        # The Witcher 3: price 3999 cents -> 39.99 dollars
        witcher = df[df["appid"] == 291920].iloc[0]
        assert witcher["price_usd"] == 39.99

    def test_duplicate_appid_last_wins_and_counted(self) -> None:
        """Test that duplicate appids keep the last occurrence and count increments."""
        # Create two payloads with overlapping appid
        import hashlib

        app_data_v1 = {
            "263060": {
                "appid": 263060,
                "name": "Dishonored v1",
                "developer": "Arkane Studios",
                "publisher": "Bethesda",
                "positive": 1000,
                "negative": 100,
                "owners_low": 1000000,
                "owners_high": 2000000,
                "price": 1999,
                "initialprice": 4999,
                "discount": 60,
                "tags": {"stealth": 100},
            }
        }

        app_data_v2 = {
            "263060": {
                "appid": 263060,
                "name": "Dishonored v2",
                "developer": "Arkane Studios",
                "publisher": "Bethesda",
                "positive": 2000,
                "negative": 200,
                "owners_low": 1500000,
                "owners_high": 2500000,
                "price": 1999,
                "initialprice": 4999,
                "discount": 60,
                "tags": {"stealth": 100},
            }
        }

        payloads = []
        for app_data in [app_data_v1, app_data_v2]:
            payload_json = json.dumps(app_data["263060"], sort_keys=True).encode("utf-8")
            payload_sha256 = hashlib.sha256(payload_json).hexdigest()
            payloads.append(
                RawPayload(
                    appid=263060,
                    source="steamspy_all",
                    fetched_at=datetime.utcnow(),
                    http_status=200,
                    payload=app_data["263060"],
                    payload_sha256=payload_sha256,
                )
            )

        df = build_catalog_frame(payloads)

        # Should have only 1 row (the later one)
        assert len(df) == 1
        assert df.iloc[0]["name"] == "Dishonored v2"
        assert df.iloc[0]["positive"] == 2000

        # Duplicate count should be 1
        assert df.attrs.get("_duplicate_appid_count") == 1

    def test_empty_input_yields_empty_frame_with_columns(self) -> None:
        """Test that empty input returns DataFrame with correct columns."""
        df = build_catalog_frame([])

        # Should have all columns even when empty
        expected_columns = {
            "appid",
            "name",
            "developer",
            "publisher",
            "positive",
            "negative",
            "owners_low",
            "owners_high",
            "price_usd",
            "initialprice",
            "discount",
            "tags",
        }
        assert set(df.columns) == expected_columns
        assert len(df) == 0

    def test_missing_tags_field_becomes_empty_dict(self) -> None:
        """Test that missing 'tags' field becomes empty dict."""
        import hashlib

        app_data_no_tags = {
            "123456": {
                "appid": 123456,
                "name": "Game Without Tags",
                "developer": "Test Dev",
                "publisher": "Test Pub",
                "positive": 100,
                "negative": 10,
                "owners_low": 10000,
                "owners_high": 20000,
                "price": 999,
                "initialprice": 999,
                "discount": 0,
                # No tags field
            }
        }

        payload_json = json.dumps(app_data_no_tags["123456"], sort_keys=True).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload_json).hexdigest()

        payload = RawPayload(
            appid=123456,
            source="steamspy_all",
            fetched_at=datetime.utcnow(),
            http_status=200,
            payload=app_data_no_tags["123456"],
            payload_sha256=payload_sha256,
        )

        df = build_catalog_frame([payload])

        assert len(df) == 1
        assert df.iloc[0]["tags"] == {}


class TestCoarseFilter:
    """Tests for coarse_filter."""

    def test_tallies_each_rejection_reason_on_synthetic_catalog(
        self, coarse_filter_criteria: CoarseFilterCriteria, mock_event_sink: EventSink
    ) -> None:
        """Test that each rejection reason is tallied correctly."""
        # Create a DataFrame with rows that fail each rejection reason
        df = pd.DataFrame([
            # Missing appid
            {
                "appid": None,
                "name": "No ID",
                "developer": "Dev",
                "publisher": "Pub",
                "positive": 100,
                "negative": 10,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 9.99,
                "initialprice": 9.99,
                "discount": 0,
                "tags": {},
            },
            # Below review floor (25 minimum)
            {
                "appid": 100,
                "name": "Low Reviews",
                "developer": "Dev",
                "publisher": "Pub",
                "positive": 10,
                "negative": 5,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 9.99,
                "initialprice": 9.99,
                "discount": 0,
                "tags": {},
            },
            # Good app
            {
                "appid": 200,
                "name": "Good Game",
                "developer": "Dev",
                "publisher": "Pub",
                "positive": 100,
                "negative": 10,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 9.99,
                "initialprice": 9.99,
                "discount": 0,
                "tags": {},
            },
        ])

        result = coarse_filter(df, coarse_filter_criteria)

        # Should have 1 survivor
        assert len(result.candidates) == 1
        assert result.candidates.iloc[0]["appid"] == 200

        # Should have correct tallies
        assert result.rejected_by_reason["missing_required_field"] == 1
        assert result.rejected_by_reason["review_count_below_floor"] == 1
        assert result.total_input == 3
        assert sum(result.rejected_by_reason.values()) == 2  # 1 + 1 duplicates count

    def test_min_review_count_boundary_inclusive(
        self, mock_event_sink: EventSink
    ) -> None:
        """Test that min_review_count boundary is inclusive."""
        criteria = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=None,
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=None,
            publisher_blocklist=[],
        )

        df = pd.DataFrame([
            {
                "appid": 100,
                "name": "Exactly 25",
                "developer": "Dev",
                "publisher": "Pub",
                "positive": 20,
                "negative": 5,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 9.99,
                "initialprice": 9.99,
                "discount": 0,
                "tags": {},
            },
            {
                "appid": 101,
                "name": "Below 25",
                "developer": "Dev",
                "publisher": "Pub",
                "positive": 15,
                "negative": 9,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 9.99,
                "initialprice": 9.99,
                "discount": 0,
                "tags": {},
            },
        ])

        result = coarse_filter(df, criteria)

        # Exactly 25 should pass, 24 should fail
        assert len(result.candidates) == 1
        assert result.candidates.iloc[0]["appid"] == 100
        assert result.rejected_by_reason["review_count_below_floor"] == 1

    def test_no_ceiling_never_rejects(self) -> None:
        """Test that no ceiling means very high review counts pass."""
        criteria = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=None,
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=None,
            publisher_blocklist=[],
        )

        df = pd.DataFrame([
            {
                "appid": 100,
                "name": "Mega Game",
                "developer": "Dev",
                "publisher": "Pub",
                "positive": 9_000_000,
                "negative": 1_000_000,
                "owners_low": 100_000_000,
                "owners_high": 200_000_000,
                "price_usd": 29.99,
                "initialprice": 29.99,
                "discount": 0,
                "tags": {},
            },
        ])

        result = coarse_filter(df, criteria)

        # Should pass despite massive review count
        assert len(result.candidates) == 1
        assert result.rejected_by_reason["review_count_above_ceiling"] == 0

    def test_publisher_blocklist_case_insensitive_substring(self) -> None:
        """Test case-insensitive substring matching for publisher blocklist."""
        criteria = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=None,
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=None,
            publisher_blocklist=["Ubisoft", "Electronic Arts"],
        )

        df = pd.DataFrame([
            {
                "appid": 100,
                "name": "Ubisoft Game",
                "developer": "Dev",
                "publisher": "Ubisoft Entertainment SA",
                "positive": 100,
                "negative": 10,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 9.99,
                "initialprice": 9.99,
                "discount": 0,
                "tags": {},
            },
            {
                "appid": 101,
                "name": "EA Game",
                "developer": "Dev",
                "publisher": "ELECTRONIC ARTS",
                "positive": 100,
                "negative": 10,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 9.99,
                "initialprice": 9.99,
                "discount": 0,
                "tags": {},
            },
            {
                "appid": 102,
                "name": "Indie Game",
                "developer": "Dev",
                "publisher": "Small Indie Studio",
                "positive": 100,
                "negative": 10,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 9.99,
                "initialprice": 9.99,
                "discount": 0,
                "tags": {},
            },
        ])

        result = coarse_filter(df, criteria)

        # Only the indie game should survive
        assert len(result.candidates) == 1
        assert result.candidates.iloc[0]["appid"] == 102
        assert result.rejected_by_reason["publisher_blocklisted"] == 2

    def test_free_to_play_kept_when_included(self) -> None:
        """Test that free-to-play games are kept when include_free_to_play=True."""
        criteria = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=None,
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=None,
            publisher_blocklist=[],
        )

        df = pd.DataFrame([
            {
                "appid": 100,
                "name": "Free Game",
                "developer": "Dev",
                "publisher": "Pub",
                "positive": 100,
                "negative": 10,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 0.0,
                "initialprice": 0.0,
                "discount": 0,
                "tags": {},
            },
        ])

        result = coarse_filter(df, criteria)

        # Should keep the F2P game
        assert len(result.candidates) == 1
        assert result.rejected_by_reason["free_to_play_excluded"] == 0

    def test_free_to_play_excluded_when_not_included(self) -> None:
        """Test that free-to-play games are excluded when include_free_to_play=False."""
        criteria = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=None,
            latest_release_date=None,
            include_free_to_play=False,
            max_price_usd=None,
            publisher_blocklist=[],
        )

        df = pd.DataFrame([
            {
                "appid": 100,
                "name": "Free Game",
                "developer": "Dev",
                "publisher": "Pub",
                "positive": 100,
                "negative": 10,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 0.0,
                "initialprice": 0.0,
                "discount": 0,
                "tags": {},
            },
        ])

        result = coarse_filter(df, criteria)

        # Should exclude the F2P game
        assert len(result.candidates) == 0
        assert result.rejected_by_reason["free_to_play_excluded"] == 1

    def test_price_above_max_excluded(self) -> None:
        """Test that games above max_price_usd are excluded."""
        criteria = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=None,
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=19.99,
            publisher_blocklist=[],
        )

        df = pd.DataFrame([
            {
                "appid": 100,
                "name": "Cheap Game",
                "developer": "Dev",
                "publisher": "Pub",
                "positive": 100,
                "negative": 10,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 9.99,
                "initialprice": 9.99,
                "discount": 0,
                "tags": {},
            },
            {
                "appid": 101,
                "name": "Expensive Game",
                "developer": "Dev",
                "publisher": "Pub",
                "positive": 100,
                "negative": 10,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 29.99,
                "initialprice": 29.99,
                "discount": 0,
                "tags": {},
            },
        ])

        result = coarse_filter(df, criteria)

        # Only cheap game should survive
        assert len(result.candidates) == 1
        assert result.candidates.iloc[0]["appid"] == 100
        assert result.rejected_by_reason["price_above_max"] == 1

    def test_empty_catalog_returns_empty_result(
        self, coarse_filter_criteria: CoarseFilterCriteria
    ) -> None:
        """Test that empty catalog returns empty FunnelResult."""
        df = pd.DataFrame(
            columns=[
                "appid",
                "name",
                "developer",
                "publisher",
                "positive",
                "negative",
                "owners_low",
                "owners_high",
                "price_usd",
                "initialprice",
                "discount",
                "tags",
            ]
        )

        result = coarse_filter(df, coarse_filter_criteria)

        assert len(result.candidates) == 0
        assert result.total_input == 0
        assert all(count == 0 for count in result.rejected_by_reason.values())

    def test_counts_are_internally_consistent(
        self, coarse_filter_criteria: CoarseFilterCriteria
    ) -> None:
        """Test that candidates + rejections sum to total input."""
        df = pd.DataFrame([
            {
                "appid": i,
                "name": f"Game {i}",
                "developer": "Dev",
                "publisher": "Pub",
                "positive": 50 + i * 10 if i > 0 else 10,
                "negative": 5 + i if i > 0 else 1,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 9.99 + i,
                "initialprice": 9.99 + i,
                "discount": 0,
                "tags": {},
            }
            for i in range(50)
        ])

        result = coarse_filter(df, coarse_filter_criteria)

        # Consistency check: candidates + rejected should equal total
        rejected_total = sum(result.rejected_by_reason.values())
        assert len(result.candidates) + rejected_total == result.total_input


class TestFetchSteamspyCatalog:
    """Tests for fetch_steamspy_catalog."""

    def test_streams_two_pages_then_stops_on_empty(self, mock_event_sink: EventSink) -> None:
        """Test pagination stops when page returns empty dict."""
        page0_data = {
            "263060": {
                "appid": 263060,
                "name": "Game 0",
                "positive": 100,
                "negative": 10,
                "tags": {},
            },
            "570": {
                "appid": 570,
                "name": "Game 1",
                "positive": 100,
                "negative": 10,
                "tags": {},
            },
        }

        page1_data = {
            "291920": {
                "appid": 291920,
                "name": "Game 2",
                "positive": 100,
                "negative": 10,
                "tags": {},
            },
        }

        page2_data = {}  # Empty page signals end

        mock_client = MagicMock()
        mock_client.fetch_all_page.side_effect = [
            (200, page0_data),
            (200, page1_data),
            (200, page2_data),
        ]

        payloads = list(fetch_steamspy_catalog(mock_client, on_event=mock_event_sink))

        # Should have 3 apps total (2 from page 0, 1 from page 1)
        assert len(payloads) == 3
        appids = [p.appid for p in payloads]
        assert appids == [263060, 570, 291920]

        # Should have emitted a warning for the empty page
        warning_calls = [
            call for call in mock_event_sink.call_args_list if call[1]["level"] == "warning"
        ]
        assert len(warning_calls) > 0

    def test_stops_on_repeated_page(self, mock_event_sink: EventSink) -> None:
        """Test pagination stops when page repeats previous page's appids."""
        page0_data = {
            "263060": {
                "appid": 263060,
                "name": "Game 0",
                "positive": 100,
                "negative": 10,
                "tags": {},
            },
            "570": {
                "appid": 570,
                "name": "Game 1",
                "positive": 100,
                "negative": 10,
                "tags": {},
            },
        }

        page1_data = page0_data  # Same appids

        mock_client = MagicMock()
        mock_client.fetch_all_page.side_effect = [
            (200, page0_data),
            (200, page1_data),
        ]

        payloads = list(fetch_steamspy_catalog(mock_client, on_event=mock_event_sink))

        # Should yield only page 0's apps
        assert len(payloads) == 2

        # Should have emitted a warning for repeated page
        warning_calls = [
            call for call in mock_event_sink.call_args_list if call[1]["level"] == "warning"
        ]
        assert len(warning_calls) > 0
        assert any("repeated" in call[1]["message"].lower() for call in warning_calls)

    def test_max_pages_cap_respected(self, mock_event_sink: EventSink) -> None:
        """Test that max_pages parameter limits pagination."""
        page0_data = {
            "263060": {
                "appid": 263060,
                "name": "Game 0",
                "positive": 100,
                "negative": 10,
                "tags": {},
            },
        }

        page1_data = {
            "570": {
                "appid": 570,
                "name": "Game 1",
                "positive": 100,
                "negative": 10,
                "tags": {},
            },
        }

        mock_client = MagicMock()
        mock_client.fetch_all_page.side_effect = [
            (200, page0_data),
            (200, page1_data),
        ]

        payloads = list(
            fetch_steamspy_catalog(mock_client, max_pages=1, on_event=mock_event_sink)
        )

        # Should yield only page 0
        assert len(payloads) == 1
        assert payloads[0].appid == 263060

    def test_bulk_fetch_failure_raises(self, mock_event_sink: EventSink) -> None:
        """Test that non-200 status raises AcquisitionError."""
        mock_client = MagicMock()
        mock_client.fetch_all_page.return_value = (500, {"error": "server error"})

        with pytest.raises(AcquisitionError):
            list(fetch_steamspy_catalog(mock_client, on_event=mock_event_sink))

    def test_fetch_raises_with_exception(self, mock_event_sink: EventSink) -> None:
        """Test that client exceptions are wrapped in AcquisitionError."""
        mock_client = MagicMock()
        mock_client.fetch_all_page.side_effect = RuntimeError("Network error")

        with pytest.raises(AcquisitionError):
            list(fetch_steamspy_catalog(mock_client, on_event=mock_event_sink))


class TestFetchAppDetails:
    """Tests for fetch_app_details."""

    def test_yields_one_payload_per_appid_including_failures(
        self, mock_event_sink: EventSink
    ) -> None:
        """Test that one RawPayload is yielded per appid, including failures."""
        appdetails_success = {
            "123456": {
                "success": True,
                "data": {"name": "Game 1"},
            }
        }

        appdetails_failure = {
            "123457": {
                "success": False,
            }
        }

        mock_client = MagicMock()
        mock_client.fetch_app_details.side_effect = [
            (200, appdetails_success),
            (200, appdetails_failure),
        ]

        payloads = list(
            fetch_app_details(mock_client, [123456, 123457], on_event=mock_event_sink)
        )

        # Should have 2 payloads
        assert len(payloads) == 2

        # Both should have correct appids
        assert payloads[0].appid == 123456
        assert payloads[1].appid == 123457

        # Both should have source steam_appdetails
        assert all(p.source == "steam_appdetails" for p in payloads)

    def test_empty_appids_yields_nothing_without_raising(self, mock_event_sink: EventSink) -> None:
        """Test that empty appids list yields nothing and emits warning."""
        mock_client = MagicMock()

        payloads = list(fetch_app_details(mock_client, [], on_event=mock_event_sink))

        # Should yield nothing
        assert len(payloads) == 0

        # Should have emitted a warning
        warning_calls = [
            call for call in mock_event_sink.call_args_list if call[1]["level"] == "warning"
        ]
        assert len(warning_calls) > 0

    def test_budget_exhaustion_propagates(self, mock_event_sink: EventSink) -> None:
        """Test that RequestBudgetExceeded is propagated."""
        mock_client = MagicMock()
        mock_client.fetch_app_details.side_effect = [
            (200, {"123456": {"success": True}}),
            RequestBudgetExceeded("Budget exhausted"),
        ]

        with pytest.raises(RequestBudgetExceeded):
            list(fetch_app_details(mock_client, [123456, 123457], on_event=mock_event_sink))

    def test_transport_error_handled_gracefully(self, mock_event_sink: EventSink) -> None:
        """Test that transport errors result in error payloads."""
        mock_client = MagicMock()
        mock_client.fetch_app_details.side_effect = [
            RuntimeError("Connection timeout"),
        ]

        payloads = list(fetch_app_details(mock_client, [123456], on_event=mock_event_sink))

        # Should yield one payload with error markers
        assert len(payloads) == 1
        assert payloads[0].http_status == 0
        assert "_parse_error" in payloads[0].payload
        assert "_transport_error" in payloads[0].payload


class TestFetchReviewSummaries:
    """Tests for fetch_review_summaries."""

    def test_yields_one_payload_per_appid(self, mock_event_sink: EventSink) -> None:
        """Test that one RawPayload is yielded per appid."""
        review_summary = {
            "success": 1,
            "query_summary": {
                "total_reviews": 100,
                "total_positive": 85,
                "review_score": 0.85,
            },
        }

        mock_client = MagicMock()
        mock_client.fetch_review_summary.return_value = (200, review_summary)

        payloads = list(
            fetch_review_summaries(mock_client, [123456, 123457], on_event=mock_event_sink)
        )

        # Should have 2 payloads
        assert len(payloads) == 2

        # Both should have source steam_reviews
        assert all(p.source == "steam_reviews" for p in payloads)

    def test_empty_appids_yields_nothing(self, mock_event_sink: EventSink) -> None:
        """Test that empty appids list yields nothing."""
        mock_client = MagicMock()

        payloads = list(fetch_review_summaries(mock_client, [], on_event=mock_event_sink))

        assert len(payloads) == 0

    def test_budget_exhaustion_propagates(self, mock_event_sink: EventSink) -> None:
        """Test that RequestBudgetExceeded is propagated."""
        mock_client = MagicMock()
        mock_client.fetch_review_summary.side_effect = RequestBudgetExceeded(
            "Budget exhausted"
        )

        with pytest.raises(RequestBudgetExceeded):
            list(fetch_review_summaries(mock_client, [123456], on_event=mock_event_sink))

    def test_zero_reviews_is_valid(self, mock_event_sink: EventSink) -> None:
        """Test that zero reviews is valid data, not a failure."""
        review_summary = {
            "success": 1,
            "query_summary": {
                "total_reviews": 0,
                "total_positive": 0,
                "review_score": 0,
            },
        }

        mock_client = MagicMock()
        mock_client.fetch_review_summary.return_value = (200, review_summary)

        payloads = list(
            fetch_review_summaries(mock_client, [123456], on_event=mock_event_sink)
        )

        # Should yield one payload successfully
        assert len(payloads) == 1


class TestFunnelResult:
    """Tests for FunnelResult dataclass."""

    def test_counts_are_internally_consistent(
        self, coarse_filter_criteria: CoarseFilterCriteria
    ) -> None:
        """Test that FunnelResult counts are internally consistent."""
        df = pd.DataFrame([
            {
                "appid": i,
                "name": f"Game {i}",
                "developer": "Dev",
                "publisher": "Pub",
                "positive": 100,
                "negative": 10,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 9.99,
                "initialprice": 9.99,
                "discount": 0,
                "tags": {},
            }
            for i in range(100)
        ])

        result = coarse_filter(df, coarse_filter_criteria)

        # Verify the postcondition
        rejected_total = sum(result.rejected_by_reason.values())
        assert len(result.candidates) + rejected_total == result.total_input


class TestAcquisitionReport:
    """Tests for AcquisitionReport dataclass."""

    def test_counts_are_internally_consistent(
        self, coarse_filter_criteria: CoarseFilterCriteria
    ) -> None:
        """Test that per-app counters sum correctly."""
        # Create a funnel result
        df = pd.DataFrame([
            {
                "appid": i,
                "name": f"Game {i}",
                "developer": "Dev",
                "publisher": "Pub",
                "positive": 100,
                "negative": 10,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 9.99,
                "initialprice": 9.99,
                "discount": 0,
                "tags": {},
            }
            for i in range(20)
        ])

        funnel = coarse_filter(df, coarse_filter_criteria)

        # Create a report
        report = AcquisitionReport(
            run_id="test-run-1",
            catalog_size=100,
            candidate_count=len(funnel.candidates),
            detail_fetched=17,
            detail_failed=3,
            reviews_fetched=17,
            reviews_failed=3,
            requests_made=50,
            duration_seconds=10.5,
            funnel=funnel,
        )

        # Verify the postconditions
        assert report.detail_fetched + report.detail_failed == report.candidate_count
        assert report.reviews_fetched + report.reviews_failed == report.candidate_count
        assert report.duration_seconds >= 0

    def test_empty_candidate_set_report(
        self, coarse_filter_criteria: CoarseFilterCriteria
    ) -> None:
        """Test report when candidate_count is 0."""
        df = pd.DataFrame(
            columns=[
                "appid",
                "name",
                "developer",
                "publisher",
                "positive",
                "negative",
                "owners_low",
                "owners_high",
                "price_usd",
                "initialprice",
                "discount",
                "tags",
            ]
        )

        funnel = coarse_filter(df, coarse_filter_criteria)

        report = AcquisitionReport(
            run_id="test-run-empty",
            catalog_size=1000,
            candidate_count=0,
            detail_fetched=0,
            detail_failed=0,
            reviews_fetched=0,
            reviews_failed=0,
            requests_made=10,
            duration_seconds=5.0,
            funnel=funnel,
        )

        assert report.candidate_count == 0
        assert report.detail_fetched == 0
        assert report.detail_failed == 0
        assert report.reviews_fetched == 0
        assert report.reviews_failed == 0
