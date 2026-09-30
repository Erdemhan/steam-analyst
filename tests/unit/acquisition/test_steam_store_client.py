"""Unit tests for SteamStoreClient."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from steam_analyst.acquisition.steam_store_client import (
    SteamStoreClient,
    COUNTRY_CODE,
    LANGUAGE,
    STEAM_APPDETAILS_URL,
)
from steam_analyst.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Create a test Settings instance."""
    return Settings(
        db_path=None,  # type: ignore
        steam_web_api_key=None,
        http_timeout_seconds=10.0,
        user_agent="Test-Agent/1.0",
        parameters_path=None,  # type: ignore
    )


@pytest.fixture
def mock_http_client() -> MagicMock:
    """Create a mocked HttpClient for testing."""
    return MagicMock()


@pytest.fixture
def steam_store_client(
    settings: Settings, mock_http_client: MagicMock
) -> SteamStoreClient:
    """Create a SteamStoreClient with mocked HttpClient."""
    return SteamStoreClient(settings=settings, http_client=mock_http_client)


@pytest.fixture
def appdetails_success_fixture() -> dict:
    """Load the appdetails success fixture from file."""
    fixture_path = (
        Path(__file__).parent.parent.parent
        / "fixtures"
        / "appdetails_success.json"
    )
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def appdetails_failure_fixture() -> dict:
    """Load the appdetails failure fixture from file."""
    fixture_path = (
        Path(__file__).parent.parent.parent / "fixtures" / "appdetails_failure.json"
    )
    with open(fixture_path) as f:
        return json.load(f)


class TestLocaleAlwaysPinned:
    """Tests that locale is always pinned to cc=us and l=english."""

    def test_always_requests_us_english_locale(
        self, steam_store_client: SteamStoreClient, mock_http_client: MagicMock
    ) -> None:
        """Inspecting the constructed request params shows cc=us and l=english.

        This test verifies that regardless of any configuration or input,
        the locale parameters are always pinned to the fixed values.
        """
        # Arrange
        appid = 123456
        mock_http_client.get_json.return_value = (200, {"123456": {"success": True}})

        # Act
        steam_store_client.fetch_app_details(appid)

        # Assert
        mock_http_client.get_json.assert_called_once()
        call_args = mock_http_client.get_json.call_args
        url = call_args[0][0]
        params = call_args[1]["params"]

        assert url == STEAM_APPDETAILS_URL
        assert params["cc"] == COUNTRY_CODE
        assert params["cc"] == "us"
        assert params["l"] == LANGUAGE
        assert params["l"] == "english"

    def test_locale_pinned_with_multiple_appids(
        self, steam_store_client: SteamStoreClient, mock_http_client: MagicMock
    ) -> None:
        """Locale is pinned regardless of appid value."""
        # Arrange
        appid = 999999  # Different appid
        mock_http_client.get_json.return_value = (200, {})

        # Act
        steam_store_client.fetch_app_details(appid)

        # Assert
        call_args = mock_http_client.get_json.call_args
        params = call_args[1]["params"]
        assert params["cc"] == "us"
        assert params["l"] == "english"

    def test_appid_in_params(
        self, steam_store_client: SteamStoreClient, mock_http_client: MagicMock
    ) -> None:
        """The appid is correctly included in request params as a string."""
        # Arrange
        appid = 12345
        mock_http_client.get_json.return_value = (200, {})

        # Act
        steam_store_client.fetch_app_details(appid)

        # Assert
        call_args = mock_http_client.get_json.call_args
        params = call_args[1]["params"]
        assert params["appids"] == str(appid)
        assert params["appids"] == "12345"


class TestPayloadPassthrough:
    """Tests that payloads are returned unchanged."""

    def test_success_false_payload_persisted_unchanged(
        self,
        steam_store_client: SteamStoreClient,
        mock_http_client: MagicMock,
        appdetails_failure_fixture: dict,
    ) -> None:
        """A success: false payload is returned unchanged.

        From the FunctionSpec edge case: appdetails returns
        {"<appid>": {"success": false}} — returned unchanged as
        (200, {...success: false...}); caller counts this as detail_failed
        but still persists it verbatim.
        """
        # Arrange
        appid = 123456
        expected_payload = appdetails_failure_fixture
        mock_http_client.get_json.return_value = (200, expected_payload)

        # Act
        status_code, payload = steam_store_client.fetch_app_details(appid)

        # Assert
        assert status_code == 200
        assert payload == expected_payload
        assert payload["123456"]["success"] is False

    def test_success_true_payload_persisted_unchanged(
        self,
        steam_store_client: SteamStoreClient,
        mock_http_client: MagicMock,
        appdetails_success_fixture: dict,
    ) -> None:
        """A success: true payload is returned unchanged.

        From the FunctionSpec: on success, payload is Steam's
        {"<appid>": {"success": true, "data": {...}}} shape,
        persisted verbatim with no post-processing.
        """
        # Arrange
        appid = 123456
        expected_payload = appdetails_success_fixture
        mock_http_client.get_json.return_value = (200, expected_payload)

        # Act
        status_code, payload = steam_store_client.fetch_app_details(appid)

        # Assert
        assert status_code == 200
        assert payload == expected_payload
        assert payload["123456"]["success"] is True
        assert "data" in payload["123456"]

    def test_returns_exact_tuple_from_http_client(
        self, steam_store_client: SteamStoreClient, mock_http_client: MagicMock
    ) -> None:
        """The method returns the exact tuple from HttpClient.get_json unchanged."""
        # Arrange
        appid = 123456
        expected_status = 200
        expected_payload = {"123456": {"success": True, "data": {}}}
        mock_http_client.get_json.return_value = (
            expected_status,
            expected_payload,
        )

        # Act
        status_code, payload = steam_store_client.fetch_app_details(appid)

        # Assert
        assert status_code == expected_status
        assert payload is expected_payload  # Same object reference


class TestEdgeCases:
    """Tests for edge cases specified in the FunctionSpec."""

    def test_non_game_app_type_returned_unchanged(
        self, steam_store_client: SteamStoreClient, mock_http_client: MagicMock
    ) -> None:
        """Non-game app types (dlc, demo, video, music, tool) are returned unchanged.

        From the FunctionSpec edge case: appid corresponds to a non-game app_type
        (dlc, demo, video, music, tool) — returned unchanged; exclusion by app_type
        happens in enrichment, not here, per the module's non_goals.
        """
        # Arrange
        appid = 123456
        dlc_payload = {
            "123456": {
                "success": True,
                "data": {"type": "dlc", "name": "Test DLC"},
            }
        }
        mock_http_client.get_json.return_value = (200, dlc_payload)

        # Act
        status_code, payload = steam_store_client.fetch_app_details(appid)

        # Assert
        assert status_code == 200
        assert payload == dlc_payload
        assert payload["123456"]["data"]["type"] == "dlc"

    def test_geo_blocking_scenario(
        self, steam_store_client: SteamStoreClient, mock_http_client: MagicMock
    ) -> None:
        """Geo-blocking scenarios return whatever Steam sends (e.g. success: false).

        From the FunctionSpec edge case: Steam Web API is temporarily
        geo-blocking the configured 'us' region for a specific title —
        returned as whatever status/payload Steam actually sends
        (e.g. success: false); not specially detected or retried differently.
        """
        # Arrange
        appid = 123456
        blocked_payload = {"123456": {"success": False}}
        mock_http_client.get_json.return_value = (200, blocked_payload)

        # Act
        status_code, payload = steam_store_client.fetch_app_details(appid)

        # Assert
        assert status_code == 200
        assert payload == blocked_payload
        # No special detection or retry happens

    def test_http_error_status_codes_returned_as_is(
        self, steam_store_client: SteamStoreClient, mock_http_client: MagicMock
    ) -> None:
        """HTTP error status codes are returned as-is without special handling."""
        # Arrange
        appid = 123456
        error_payload = {"error": "Not Found"}
        mock_http_client.get_json.return_value = (404, error_payload)

        # Act
        status_code, payload = steam_store_client.fetch_app_details(appid)

        # Assert
        assert status_code == 404
        assert payload == error_payload

    def test_zero_appid_request(
        self, steam_store_client: SteamStoreClient, mock_http_client: MagicMock
    ) -> None:
        """Even appid=0 is passed through (validation happens at caller level)."""
        # Arrange
        appid = 0
        mock_http_client.get_json.return_value = (200, {})

        # Act
        steam_store_client.fetch_app_details(appid)

        # Assert
        call_args = mock_http_client.get_json.call_args
        params = call_args[1]["params"]
        assert params["appids"] == "0"


class TestClientInitialization:
    """Tests for client initialization."""

    def test_client_stores_settings_and_http_client(
        self, settings: Settings, mock_http_client: MagicMock
    ) -> None:
        """Client correctly stores settings and http_client references."""
        # Act
        client = SteamStoreClient(settings=settings, http_client=mock_http_client)

        # Assert
        assert client.settings is settings
        assert client.http_client is mock_http_client

    def test_module_constants_correct(self) -> None:
        """Module-level locale constants have expected values."""
        # Assert
        assert COUNTRY_CODE == "us"
        assert LANGUAGE == "english"
        assert STEAM_APPDETAILS_URL == "https://store.steampowered.com/api/appdetails"


class TestURLConstruction:
    """Tests for URL construction."""

    def test_correct_url_used(
        self, steam_store_client: SteamStoreClient, mock_http_client: MagicMock
    ) -> None:
        """The correct Steam appdetails URL is used."""
        # Arrange
        appid = 123456
        mock_http_client.get_json.return_value = (200, {})

        # Act
        steam_store_client.fetch_app_details(appid)

        # Assert
        call_args = mock_http_client.get_json.call_args
        url = call_args[0][0]
        assert url == "https://store.steampowered.com/api/appdetails"
