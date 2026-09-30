"""Unit tests for SteamReviewsClient."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from steam_analyst.acquisition.http_client import HttpClient
from steam_analyst.acquisition.steam_reviews_client import (
    STEAM_REVIEWS_LANGUAGE,
    STEAM_REVIEWS_LOCALE,
    SteamReviewsClient,
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
def mock_http_client(settings: Settings) -> HttpClient:
    """Create a mock HttpClient for testing."""
    mock_session = MagicMock()
    client = HttpClient(
        settings=settings,
        max_retries=2,
        backoff_base_seconds=0.01,
        backoff_max_seconds=0.1,
        session=mock_session,
    )
    return client


@pytest.fixture
def reviews_client(mock_http_client: HttpClient) -> SteamReviewsClient:
    """Create a SteamReviewsClient with mocked HttpClient."""
    return SteamReviewsClient(http_client=mock_http_client)


@pytest.fixture
def reviews_summary_fixture() -> dict:
    """Load the reviews_summary.json fixture."""
    fixture_path = Path(__file__).parent.parent.parent / "fixtures" / "reviews_summary.json"
    with open(fixture_path) as f:
        return json.load(f)


class TestFetchReviewSummaryFixture:
    """Test that fetch_review_summary correctly parses fixtures."""

    def test_fetch_review_summary_parses_fixture(
        self, reviews_client: SteamReviewsClient, reviews_summary_fixture: dict
    ) -> None:
        """Test that a fixture response is returned unchanged as payload.

        This tests the scenario from the spec: tests/fixtures/reviews_summary.json
        is returned unchanged as (200, <fixture content>).
        """
        # Arrange
        appid = 123456
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = reviews_summary_fixture
        reviews_client.http_client.session.get.return_value = mock_response

        # Act
        status, payload = reviews_client.fetch_review_summary(appid)

        # Assert
        assert status == 200
        assert payload == reviews_summary_fixture
        assert payload["query_summary"]["total_positive"] == 15420
        assert payload["query_summary"]["total_negative"] == 2108
        assert payload["query_summary"]["total_reviews"] == 17528
        assert payload["query_summary"]["review_score"] == 0.88


class TestZeroReviewsNotError:
    """Test edge case: appid with zero reviews."""

    def test_zero_reviews_not_an_error(
        self, reviews_client: SteamReviewsClient
    ) -> None:
        """A stubbed zero-review response returns (200, {...total_reviews: 0...}).

        Edge case from spec: appid with zero reviews at all should return 200
        with total_reviews=0, total_positive=0, total_negative=0 -- not an error.
        """
        # Arrange
        appid = 999999
        zero_review_response = {
            "success": 1,
            "query_summary": {
                "total_positive": 0,
                "total_negative": 0,
                "total_reviews": 0,
                "review_score": 0.0,
                "review_score_desc": "No Reviews",
            },
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = zero_review_response
        reviews_client.http_client.session.get.return_value = mock_response

        # Act
        status, payload = reviews_client.fetch_review_summary(appid)

        # Assert
        assert status == 200
        assert payload["query_summary"]["total_reviews"] == 0
        assert payload["query_summary"]["total_positive"] == 0
        assert payload["query_summary"]["total_negative"] == 0


class TestLocalePinning:
    """Test that locale pinning is always included in requests."""

    def test_locale_pinning_in_request_params(
        self, reviews_client: SteamReviewsClient
    ) -> None:
        """Verify that every request includes cc=us&l=english pinning."""
        # Arrange
        appid = 123456
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": 1, "query_summary": {}}
        reviews_client.http_client.session.get.return_value = mock_response

        # Act
        reviews_client.fetch_review_summary(appid)

        # Assert: Verify the correct URL and locale parameters were used
        call_args = reviews_client.http_client.session.get.call_args
        assert call_args is not None
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url")
        params = call_args.kwargs.get("params", {})

        assert f"https://store.steampowered.com/appreviews/{appid}" in url
        assert params["cc"] == STEAM_REVIEWS_LOCALE
        assert params["l"] == STEAM_REVIEWS_LANGUAGE
        assert params["cc"] == "us"
        assert params["l"] == "english"

    def test_locale_pinning_constant_values(self) -> None:
        """Verify that locale constants are set to expected values."""
        # This ensures the constants are not accidentally changed
        assert STEAM_REVIEWS_LOCALE == "us"
        assert STEAM_REVIEWS_LANGUAGE == "english"


class TestRequestParameters:
    """Test that correct request parameters are sent."""

    def test_request_has_json_parameter(
        self, reviews_client: SteamReviewsClient
    ) -> None:
        """Verify that json=1 parameter is included."""
        # Arrange
        appid = 123456
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": 1, "query_summary": {}}
        reviews_client.http_client.session.get.return_value = mock_response

        # Act
        reviews_client.fetch_review_summary(appid)

        # Assert
        call_args = reviews_client.http_client.session.get.call_args
        params = call_args.kwargs.get("params", {})
        assert params["json"] == 1

    def test_request_has_num_per_page_zero(
        self, reviews_client: SteamReviewsClient
    ) -> None:
        """Verify that num_per_page=0 to request only summary."""
        # Arrange: Postcondition check from spec - requests zero review bodies
        appid = 123456
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": 1, "query_summary": {}}
        reviews_client.http_client.session.get.return_value = mock_response

        # Act
        reviews_client.fetch_review_summary(appid)

        # Assert
        call_args = reviews_client.http_client.session.get.call_args
        params = call_args.kwargs.get("params", {})
        assert params["num_per_page"] == 0


class TestReturnValue:
    """Test that return value format matches specification."""

    def test_returns_tuple_from_http_client(
        self, reviews_client: SteamReviewsClient
    ) -> None:
        """Verify that the method returns exactly what HttpClient.get_json returns."""
        # Arrange
        appid = 123456
        expected_payload = {
            "success": 1,
            "query_summary": {
                "total_positive": 100,
                "total_negative": 10,
                "total_reviews": 110,
                "review_score": 0.90,
                "review_score_desc": "Very Positive",
            },
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = expected_payload
        reviews_client.http_client.session.get.return_value = mock_response

        # Act
        result = reviews_client.fetch_review_summary(appid)

        # Assert: Postcondition - returns tuple as-is from HttpClient.get_json
        assert isinstance(result, tuple)
        assert len(result) == 2
        status, payload = result
        assert status == 200
        assert payload == expected_payload


class TestDelistedApp:
    """Test edge case: appid does not exist or was delisted."""

    def test_delisted_app_returns_success_with_zero_counts(
        self, reviews_client: SteamReviewsClient
    ) -> None:
        """Edge case from spec: delisted app returns 200 with success=1 and zero counts.

        Steam's reviews endpoint typically still returns 200 with a success=1
        and zero counts, or success=0; returned unchanged either way.
        """
        # Arrange
        appid = 999999
        delisted_response = {
            "success": 1,
            "query_summary": {
                "total_positive": 0,
                "total_negative": 0,
                "total_reviews": 0,
                "review_score": 0.0,
                "review_score_desc": "No Reviews",
            },
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = delisted_response
        reviews_client.http_client.session.get.return_value = mock_response

        # Act
        status, payload = reviews_client.fetch_review_summary(appid)

        # Assert: Returned unchanged either way per spec
        assert status == 200
        assert payload == delisted_response
        assert payload["success"] == 1

    def test_delisted_app_returns_success_zero(
        self, reviews_client: SteamReviewsClient
    ) -> None:
        """Test delisted app with success=0 in response."""
        # Arrange
        appid = 999999
        delisted_response = {"success": 0}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = delisted_response
        reviews_client.http_client.session.get.return_value = mock_response

        # Act
        status, payload = reviews_client.fetch_review_summary(appid)

        # Assert: Returned unchanged
        assert status == 200
        assert payload == delisted_response
        assert payload["success"] == 0


class TestPreconditions:
    """Test preconditions from spec."""

    def test_positive_appid_required(
        self, reviews_client: SteamReviewsClient
    ) -> None:
        """Precondition: appid > 0."""
        # This is documented as a precondition, so valid positive appids should work.
        # We test with various positive appids.
        appid = 1  # Smallest positive appid

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": 1, "query_summary": {}}
        reviews_client.http_client.session.get.return_value = mock_response

        # Act & Assert: Should not raise for valid appid
        status, _ = reviews_client.fetch_review_summary(appid)
        assert status == 200


class TestInitialization:
    """Test client initialization."""

    def test_init_with_http_client(self, mock_http_client: HttpClient) -> None:
        """Verify SteamReviewsClient can be initialized with HttpClient."""
        # Act
        client = SteamReviewsClient(http_client=mock_http_client)

        # Assert
        assert client.http_client is mock_http_client

    def test_init_stores_http_client_reference(
        self, mock_http_client: HttpClient
    ) -> None:
        """Verify the client stores a reference to the provided HttpClient."""
        # Act
        client = SteamReviewsClient(http_client=mock_http_client)

        # Assert
        assert hasattr(client, "http_client")
        assert client.http_client is mock_http_client
