"""Unit tests for SteamSpyClient."""

from unittest.mock import MagicMock, patch

import pytest

from steam_analyst.acquisition.steamspy_client import SteamSpyClient
from steam_analyst.acquisition.http_client import HttpClient
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
def mock_http_client() -> HttpClient:
    """Create a test HttpClient with mocked session."""
    mock_session = MagicMock()
    settings = Settings(
        db_path=None,  # type: ignore
        steam_web_api_key=None,
        http_timeout_seconds=10.0,
        user_agent="Test-Agent/1.0",
        parameters_path=None,  # type: ignore
    )
    client = HttpClient(
        settings=settings,
        max_retries=2,
        backoff_base_seconds=0.01,
        backoff_max_seconds=0.1,
        session=mock_session,
    )
    return client


@pytest.fixture
def steamspy_client(mock_http_client: HttpClient) -> SteamSpyClient:
    """Create a test SteamSpyClient with mocked HttpClient."""
    return SteamSpyClient(mock_http_client)


class TestFetchAllPage:
    """Tests for SteamSpyClient.fetch_all_page."""

    def test_fetch_all_page_success(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test successful fetch of a SteamSpy bulk page."""
        # Arrange
        expected_data = {
            "263060": {
                "appid": 263060,
                "name": "Dishonored",
                "developer": "Arkane Studios",
                "publisher": "Bethesda Softworks",
                "positive": 12000,
                "negative": 500,
                "owners": "2000000",
                "price": 1999,
                "initialprice": 4999,
                "discount": 60,
                "tags": {"stealth": 100, "action": 95},
            },
            "570": {
                "appid": 570,
                "name": "Dota 2",
                "developer": "Valve",
                "publisher": "Valve",
                "positive": 500000,
                "negative": 100000,
                "owners": "50000000",
                "price": 0,
                "initialprice": 0,
                "discount": 0,
                "tags": {"moba": 100, "multiplayer": 99},
            },
        }
        mock_http_client.get_json = MagicMock(return_value=(200, expected_data))

        # Act
        status, payload = steamspy_client.fetch_all_page(0)

        # Assert
        assert status == 200
        assert payload == expected_data
        # Verify that get_json was called with correct parameters
        mock_http_client.get_json.assert_called_once_with(
            "https://steamspy.com/api.php", params={"request": "all", "page": 0}
        )

    def test_fetch_all_page_empty_dict_on_beyond_last_page(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test fetch beyond the last real page returns empty dict."""
        # Arrange: SteamSpy returns empty dict for pages beyond the catalog
        mock_http_client.get_json = MagicMock(return_value=(200, {}))

        # Act
        status, payload = steamspy_client.fetch_all_page(999)

        # Assert
        assert status == 200
        assert payload == {}
        mock_http_client.get_json.assert_called_once_with(
            "https://steamspy.com/api.php", params={"request": "all", "page": 999}
        )

    def test_fetch_all_page_rate_limited_429(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test fetch with rate-limiting (429) response."""
        # Arrange
        error_payload = {"error": "rate limited"}
        mock_http_client.get_json = MagicMock(return_value=(429, error_payload))

        # Act
        status, payload = steamspy_client.fetch_all_page(5)

        # Assert
        assert status == 429
        assert payload == error_payload

    def test_fetch_all_page_server_error_500(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test fetch with server error (500) response."""
        # Arrange
        error_payload = {"error": "internal server error"}
        mock_http_client.get_json = MagicMock(return_value=(500, error_payload))

        # Act
        status, payload = steamspy_client.fetch_all_page(3)

        # Assert
        assert status == 500
        assert payload == error_payload

    def test_fetch_all_page_zero_page(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test fetch with page=0 (first page)."""
        # Arrange
        expected_data = {"100": {"appid": 100, "name": "Game 1"}}
        mock_http_client.get_json = MagicMock(return_value=(200, expected_data))

        # Act
        status, payload = steamspy_client.fetch_all_page(0)

        # Assert
        assert status == 200
        assert payload == expected_data
        mock_http_client.get_json.assert_called_once_with(
            "https://steamspy.com/api.php", params={"request": "all", "page": 0}
        )

    def test_fetch_all_page_multiple_calls_independent(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test that multiple fetch_all_page calls are independent."""
        # Arrange
        data_page_0 = {"100": {"appid": 100}}
        data_page_1 = {"200": {"appid": 200}}
        mock_http_client.get_json = MagicMock()
        mock_http_client.get_json.side_effect = [(200, data_page_0), (200, data_page_1)]

        # Act
        status0, payload0 = steamspy_client.fetch_all_page(0)
        status1, payload1 = steamspy_client.fetch_all_page(1)

        # Assert
        assert status0 == 200
        assert payload0 == data_page_0
        assert status1 == 200
        assert payload1 == data_page_1
        assert mock_http_client.get_json.call_count == 2

    def test_fetch_all_page_preserves_exact_payload(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test that payload is returned unchanged without parsing."""
        # Arrange: Complex nested structure
        complex_payload = {
            "263060": {
                "appid": 263060,
                "name": "Dishonored",
                "tags": {
                    "stealth": 100,
                    "action": 95,
                    "indie": 50,
                },
                "platforms": {"windows": True, "mac": False, "linux": True},
            }
        }
        mock_http_client.get_json = MagicMock(return_value=(200, complex_payload))

        # Act
        status, payload = steamspy_client.fetch_all_page(0)

        # Assert - payload must be identical
        assert status == 200
        assert payload is complex_payload or payload == complex_payload


class TestFetchApp:
    """Tests for SteamSpyClient.fetch_app."""

    def test_fetch_app_success(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test successful fetch of app detail."""
        # Arrange
        appid = 123456
        expected_data = {
            "appid": appid,
            "name": "Test Game",
            "developer": "Test Developer",
            "publisher": "Test Publisher",
            "positive": 5000,
            "negative": 500,
            "owners": "1000000",
            "price": 1999,
            "initialprice": 1999,
            "discount": 0,
            "tags": {"action": 100, "adventure": 80},
        }
        mock_http_client.get_json = MagicMock(return_value=(200, expected_data))

        # Act
        status, payload = steamspy_client.fetch_app(appid)

        # Assert
        assert status == 200
        assert payload == expected_data
        mock_http_client.get_json.assert_called_once_with(
            "https://steamspy.com/api.php",
            params={"request": "appdetails", "appid": appid},
        )

    def test_fetch_app_nonexistent_returns_empty(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test fetch of nonexistent app returns near-empty dict."""
        # Arrange: SteamSpy returns 200 with default/empty values for nonexistent apps
        empty_data = {}
        mock_http_client.get_json = MagicMock(return_value=(200, empty_data))

        # Act
        status, payload = steamspy_client.fetch_app(999999999)

        # Assert
        assert status == 200
        assert payload == empty_data

    def test_fetch_app_delisted_returns_default_values(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test fetch of delisted app returns default-valued dict."""
        # Arrange: SteamSpy returns 200 with default values for delisted apps
        default_data = {
            "appid": 111111,
            "name": None,
            "positive": 0,
            "negative": 0,
            "owners": "0",
        }
        mock_http_client.get_json = MagicMock(return_value=(200, default_data))

        # Act
        status, payload = steamspy_client.fetch_app(111111)

        # Assert
        assert status == 200
        assert payload == default_data

    def test_fetch_app_various_appids(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test fetch with various appid values."""
        # Arrange
        appids_to_test = [1, 100, 123456, 999999999]
        expected_payload = {"appid": 1, "name": "Game"}
        mock_http_client.get_json = MagicMock(return_value=(200, expected_payload))

        # Act & Assert
        for appid in appids_to_test:
            status, payload = steamspy_client.fetch_app(appid)
            assert status == 200
            assert payload == expected_payload
            # Verify correct appid was passed
            call_args = mock_http_client.get_json.call_args
            assert call_args.kwargs["params"]["appid"] == appid

    def test_fetch_app_rate_limited_429(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test fetch with rate-limiting (429) response."""
        # Arrange
        error_payload = {"error": "rate limited"}
        mock_http_client.get_json = MagicMock(return_value=(429, error_payload))

        # Act
        status, payload = steamspy_client.fetch_app(123456)

        # Assert
        assert status == 429
        assert payload == error_payload

    def test_fetch_app_server_error_500(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test fetch with server error (500) response."""
        # Arrange
        error_payload = {"error": "internal server error"}
        mock_http_client.get_json = MagicMock(return_value=(500, error_payload))

        # Act
        status, payload = steamspy_client.fetch_app(123456)

        # Assert
        assert status == 500
        assert payload == error_payload

    def test_fetch_app_preserves_exact_payload(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test that payload is returned unchanged without parsing."""
        # Arrange: Complex nested structure
        complex_payload = {
            "appid": 123456,
            "name": "Complex Game",
            "tags": {
                "action": 100,
                "adventure": 80,
                "rpg": 70,
            },
            "platforms": {
                "windows": True,
                "mac": False,
                "linux": True,
            },
            "screenshots": [
                {"id": 1, "path_thumbnail": "/path/to/thumb1.jpg"},
                {"id": 2, "path_thumbnail": "/path/to/thumb2.jpg"},
            ],
        }
        mock_http_client.get_json = MagicMock(return_value=(200, complex_payload))

        # Act
        status, payload = steamspy_client.fetch_app(123456)

        # Assert - payload must be identical
        assert status == 200
        assert payload is complex_payload or payload == complex_payload


class TestClientInitialization:
    """Tests for SteamSpyClient initialization."""

    def test_client_initialization(self, mock_http_client: HttpClient) -> None:
        """Test that SteamSpyClient initializes correctly."""
        # Act
        client = SteamSpyClient(mock_http_client)

        # Assert
        assert client._http_client is mock_http_client
        assert client.BASE_URL == "https://steamspy.com/api.php"

    def test_client_base_url_is_constant(self) -> None:
        """Test that BASE_URL is set correctly."""
        # Assert
        assert SteamSpyClient.BASE_URL == "https://steamspy.com/api.php"


class TestIntegrationWithMockedHttpClient:
    """Integration-style tests using mocked HttpClient."""

    def test_multiple_operations_in_sequence(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test performing multiple operations in sequence."""
        # Arrange
        page_0_data = {
            "1": {"appid": 1, "name": "Game 1"},
            "2": {"appid": 2, "name": "Game 2"},
        }
        app_1_data = {"appid": 1, "name": "Game 1", "tags": {"action": 100}}
        app_2_data = {"appid": 2, "name": "Game 2", "tags": {"indie": 100}}

        mock_http_client.get_json = MagicMock()
        mock_http_client.get_json.side_effect = [
            (200, page_0_data),
            (200, app_1_data),
            (200, app_2_data),
        ]

        # Act
        status_page, payload_page = steamspy_client.fetch_all_page(0)
        status_1, payload_1 = steamspy_client.fetch_app(1)
        status_2, payload_2 = steamspy_client.fetch_app(2)

        # Assert
        assert status_page == 200
        assert payload_page == page_0_data
        assert status_1 == 200
        assert payload_1 == app_1_data
        assert status_2 == 200
        assert payload_2 == app_2_data
        assert mock_http_client.get_json.call_count == 3

    def test_error_handling_across_methods(
        self, steamspy_client: SteamSpyClient, mock_http_client: HttpClient
    ) -> None:
        """Test error handling across different methods."""
        # Arrange
        mock_http_client.get_json = MagicMock()
        mock_http_client.get_json.side_effect = [
            (200, {"1": {"appid": 1}}),  # Success
            (429, {"error": "rate limited"}),  # Error
            (500, {"error": "server error"}),  # Error
        ]

        # Act
        status1, payload1 = steamspy_client.fetch_all_page(0)
        status2, payload2 = steamspy_client.fetch_app(1)
        status3, payload3 = steamspy_client.fetch_app(2)

        # Assert
        assert status1 == 200
        assert status2 == 429
        assert status3 == 500
