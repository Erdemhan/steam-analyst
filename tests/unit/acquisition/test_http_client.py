"""Unit tests for HttpClient."""

import json
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest
import requests

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
def http_client(settings: Settings) -> HttpClient:
    """Create a test HttpClient with mocked session."""
    # Create a mock session that we can control
    mock_session = MagicMock(spec=requests.Session)
    client = HttpClient(
        settings=settings,
        max_retries=2,
        backoff_base_seconds=0.01,  # Very short for testing
        backoff_max_seconds=0.1,
        session=mock_session,
    )
    return client


class TestHttpClientSuccess:
    """Tests for successful JSON responses."""

    def test_success_returns_parsed_json(self, http_client: HttpClient) -> None:
        """A 200 response with valid JSON body returns (200, <dict>)."""
        # Arrange
        expected_data = {"appid": 123, "name": "Test Game"}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = expected_data
        http_client.session.get.return_value = mock_response

        # Act
        status, payload = http_client.get_json("https://example.test/api/app/123")

        # Assert
        assert status == 200
        assert payload == expected_data
        http_client.session.get.assert_called_once()

    def test_success_with_params(self, http_client: HttpClient) -> None:
        """A 200 response with query parameters."""
        # Arrange
        expected_data = {"result": "ok"}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = expected_data
        http_client.session.get.return_value = mock_response

        # Act
        status, payload = http_client.get_json(
            "https://example.test/api",
            params={"key": "value", "count": "10"},
        )

        # Assert
        assert status == 200
        assert payload == expected_data
        # Verify params were passed to session.get
        http_client.session.get.assert_called_once()
        call_args = http_client.session.get.call_args
        assert call_args.kwargs["params"] == {"key": "value", "count": "10"}

    def test_user_agent_header_set(self, http_client: HttpClient) -> None:
        """Verify User-Agent header is set from settings."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        http_client.session.get.return_value = mock_response

        # Act
        http_client.get_json("https://example.test/api")

        # Assert
        call_args = http_client.session.get.call_args
        assert call_args.kwargs["headers"]["User-Agent"] == "Test-Agent/1.0"

    def test_timeout_seconds_passed_to_session(self, http_client: HttpClient) -> None:
        """Verify timeout_seconds is passed to session.get."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        http_client.session.get.return_value = mock_response

        # Act
        http_client.get_json("https://example.test/api")

        # Assert
        call_args = http_client.session.get.call_args
        assert call_args.kwargs["timeout"] == 10.0


class TestHttpClientNonJsonResponse:
    """Tests for non-JSON responses."""

    def test_non_json_body_wrapped(self, http_client: HttpClient) -> None:
        """A 200 response with HTML body returns raw-text wrapper."""
        # Arrange
        html_body = "<html><body>Error</body></html>"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html_body
        mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
        http_client.session.get.return_value = mock_response

        # Act
        status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 200
        assert payload["_raw_text"] == html_body
        assert payload["_parse_error"] is True
        assert "_transport_error" not in payload

    def test_4xx_non_json_response(self, http_client: HttpClient) -> None:
        """A 404 response with non-JSON body."""
        # Arrange
        error_body = "Not Found"
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = error_body
        mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
        http_client.session.get.return_value = mock_response

        # Act
        status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 404
        assert payload["_raw_text"] == error_body
        assert payload["_parse_error"] is True

    def test_5xx_with_json_error_body(self, http_client: HttpClient) -> None:
        """A 500 response with valid JSON error body (e.g. from SteamSpy)."""
        # Arrange
        error_data = {"error": "Internal Server Error", "code": 500}
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = error_data
        http_client.session.get.return_value = mock_response

        # Act
        status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 500
        assert payload == error_data
        assert "_parse_error" not in payload  # JSON was valid


class TestHttpClientRetry:
    """Tests for retry logic."""

    def test_retries_on_5xx_then_succeeds(self, http_client: HttpClient) -> None:
        """A 500 followed by 200 results in the 200 outcome after retry."""
        # Arrange
        success_data = {"status": "ok"}
        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500
        mock_response_500.json.return_value = {"error": "Server Error"}

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = success_data

        http_client.session.get.side_effect = [
            mock_response_500,
            mock_response_200,
        ]

        # Act
        with patch("steam_analyst.acquisition.http_client.time.sleep"):
            status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 200
        assert payload == success_data
        assert http_client.session.get.call_count == 2

    def test_exhausts_retries_on_persistent_5xx(
        self, http_client: HttpClient
    ) -> None:
        """A transport always returning 503 makes exactly max_retries+1 attempts."""
        # Arrange
        mock_response_503 = MagicMock()
        mock_response_503.status_code = 503
        mock_response_503.json.return_value = {"error": "Service Unavailable"}
        http_client.session.get.return_value = mock_response_503

        # Act
        with patch("steam_analyst.acquisition.http_client.time.sleep"):
            status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 503
        assert http_client.session.get.call_count == 3  # max_retries + 1

    def test_retries_on_timeout_then_succeeds(self, http_client: HttpClient) -> None:
        """A timeout followed by success results in the success outcome."""
        # Arrange
        success_data = {"result": "ok"}
        timeout_response = requests.exceptions.Timeout("Connection timeout")

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = success_data

        http_client.session.get.side_effect = [
            timeout_response,
            mock_response_200,
        ]

        # Act
        with patch("steam_analyst.acquisition.http_client.time.sleep"):
            status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 200
        assert payload == success_data
        assert http_client.session.get.call_count == 2

    def test_retries_on_connection_error_then_succeeds(
        self, http_client: HttpClient
    ) -> None:
        """A connection error followed by success."""
        # Arrange
        success_data = {"result": "ok"}
        connection_error = requests.exceptions.ConnectionError("Connection reset")

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = success_data

        http_client.session.get.side_effect = [
            connection_error,
            mock_response_200,
        ]

        # Act
        with patch("steam_analyst.acquisition.http_client.time.sleep"):
            status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 200
        assert payload == success_data
        assert http_client.session.get.call_count == 2


class TestHttpClientTransportErrors:
    """Tests for transport-level errors (timeout, connection error)."""

    def test_timeout_returns_sentinel_status(self, http_client: HttpClient) -> None:
        """A transport that always raises Timeout returns status_code=0."""
        # Arrange
        timeout_error = requests.exceptions.Timeout("Connection timeout")
        http_client.session.get.side_effect = timeout_error

        # Act
        with patch("steam_analyst.acquisition.http_client.time.sleep"):
            status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 0
        assert payload["_raw_text"] == ""
        assert payload["_parse_error"] is True
        assert payload["_transport_error"] == "timeout"
        # Should attempt max_retries + 1 times
        assert http_client.session.get.call_count == 3

    def test_connection_error_returns_sentinel_status(
        self, http_client: HttpClient
    ) -> None:
        """A transport that always raises ConnectionError returns status_code=0."""
        # Arrange
        connection_error = requests.exceptions.ConnectionError("Connection reset")
        http_client.session.get.side_effect = connection_error

        # Act
        with patch("steam_analyst.acquisition.http_client.time.sleep"):
            status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 0
        assert payload["_raw_text"] == ""
        assert payload["_parse_error"] is True
        assert payload["_transport_error"] == "connection"
        assert http_client.session.get.call_count == 3

    def test_request_exception_returns_sentinel_status(
        self, http_client: HttpClient
    ) -> None:
        """A RequestException (generic) returns sentinel status."""
        # Arrange
        request_error = requests.exceptions.RequestException("Request failed")
        http_client.session.get.side_effect = request_error

        # Act
        with patch("steam_analyst.acquisition.http_client.time.sleep"):
            status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 0
        assert payload["_parse_error"] is True
        assert payload["_transport_error"] == "connection"


class TestHttpClientBackoff:
    """Tests for exponential backoff with jitter."""

    def test_backoff_called_on_retry(self, http_client: HttpClient) -> None:
        """Backoff sleep is called between retries."""
        # Arrange
        timeout_error = requests.exceptions.Timeout("Timeout")
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"ok": True}

        http_client.session.get.side_effect = [
            timeout_error,
            timeout_error,
            success_response,
        ]

        # Act
        with patch("steam_analyst.acquisition.http_client.time.sleep") as mock_sleep:
            status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 200
        # Should have called sleep twice (after first and second attempts)
        assert mock_sleep.call_count == 2

    def test_backoff_respects_max_backoff(self, settings: Settings) -> None:
        """Backoff is capped at backoff_max_seconds."""
        # Arrange
        mock_session = MagicMock(spec=requests.Session)
        client = HttpClient(
            settings=settings,
            max_retries=5,  # Many retries
            backoff_base_seconds=1.0,
            backoff_max_seconds=2.0,  # Cap at 2 seconds
            session=mock_session,
        )

        timeout_error = requests.exceptions.Timeout("Timeout")
        mock_session.get.side_effect = timeout_error

        # Act
        with patch("steam_analyst.acquisition.http_client.time.sleep") as mock_sleep:
            status, payload = client.get_json("https://example.test/api")

        # Assert
        # Check that all sleep calls were at most max_backoff + jitter
        for call in mock_sleep.call_args_list:
            sleep_time = call[0][0]
            # Jitter is ±10%, so max possible is 2.0 + (2.0 * 0.1) = 2.2
            assert sleep_time <= 2.2 + 0.01  # Small epsilon for floating point

    def test_jitter_added_to_backoff(self, http_client: HttpClient) -> None:
        """Jitter is added to exponential backoff."""
        # Arrange
        timeout_error = requests.exceptions.Timeout("Timeout")
        http_client.session.get.side_effect = timeout_error

        # Act
        sleep_times = []

        def capture_sleep(t: float) -> None:
            sleep_times.append(t)

        with patch(
            "steam_analyst.acquisition.http_client.time.sleep", side_effect=capture_sleep
        ):
            http_client.get_json("https://example.test/api")

        # Assert
        # With jitter, successive backoff times should not be exact multiples
        assert len(sleep_times) >= 1
        # The sleep times should be positive (jitter can reduce but not eliminate)
        for t in sleep_times:
            assert t >= 0


class TestHttpClientNoRealNetworkCalls:
    """Verify that no test makes real network calls."""

    def test_no_network_calls_on_success(self, settings: Settings) -> None:
        """Even with a real session, mocking prevents network calls."""
        # Arrange: Use a real Session but with mocked get method
        real_session = requests.Session()
        with patch.object(real_session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_get.return_value = mock_response

            client = HttpClient(
                settings=settings,
                max_retries=2,
                backoff_base_seconds=0.01,
                backoff_max_seconds=0.1,
                session=real_session,
            )

            # Act
            status, payload = client.get_json("https://example.test/api")

            # Assert
            assert status == 200
            mock_get.assert_called_once()

    def test_no_network_calls_on_retry(self, settings: Settings) -> None:
        """Retries do not make real network calls."""
        # Arrange
        real_session = requests.Session()
        with patch.object(real_session, "get") as mock_get:
            timeout_error = requests.exceptions.Timeout("Timeout")
            success_response = MagicMock()
            success_response.status_code = 200
            success_response.json.return_value = {"ok": True}
            mock_get.side_effect = [timeout_error, success_response]

            client = HttpClient(
                settings=settings,
                max_retries=2,
                backoff_base_seconds=0.01,
                backoff_max_seconds=0.1,
                session=real_session,
            )

            # Act
            with patch("steam_analyst.acquisition.http_client.time.sleep"):
                status, payload = client.get_json("https://example.test/api")

            # Assert
            assert status == 200
            assert mock_get.call_count == 2


class TestHttpClientEdgeCases:
    """Tests for edge cases."""

    def test_empty_json_object(self, http_client: HttpClient) -> None:
        """An empty JSON object is valid."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        http_client.session.get.return_value = mock_response

        # Act
        status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 200
        assert payload == {}

    def test_nested_json_structure(self, http_client: HttpClient) -> None:
        """Nested JSON structures are preserved."""
        # Arrange
        nested_data = {
            "game": {
                "appid": 123,
                "details": {"tags": ["action", "adventure"]},
            }
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = nested_data
        http_client.session.get.return_value = mock_response

        # Act
        status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 200
        assert payload == nested_data

    def test_array_json_response(self, http_client: HttpClient) -> None:
        """JSON arrays are returned as-is."""
        # Arrange
        array_data = [{"id": 1}, {"id": 2}]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = array_data
        http_client.session.get.return_value = mock_response

        # Act
        status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 200
        assert payload == array_data

    def test_multiple_retries_with_mixed_errors(self, http_client: HttpClient) -> None:
        """Retries handle a mix of 5xx and connection errors."""
        # Arrange
        timeout_error = requests.exceptions.Timeout("Timeout")
        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500
        mock_response_500.json.return_value = {"error": "Server Error"}

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"ok": True}

        http_client.session.get.side_effect = [
            timeout_error,
            mock_response_500,
            success_response,
        ]

        # Act
        with patch("steam_analyst.acquisition.http_client.time.sleep"):
            status, payload = http_client.get_json("https://example.test/api")

        # Assert
        assert status == 200
        assert payload == {"ok": True}
        assert http_client.session.get.call_count == 3
