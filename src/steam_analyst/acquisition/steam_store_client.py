"""Steam storefront appdetails API client.

Wraps the Steam Web API / storefront appdetails endpoint with locale pinning
to cc=us&l=english (ARCHITECTURE.md Data Sources: Locale pinning, user-approved
2026-09-20). Locale is not configurable per request; it is a fixed acquisition-stage
setting applied to all calls.
"""

from steam_analyst.acquisition.http_client import HttpClient
from steam_analyst.config import Settings

# Module-level locale constants (fixed, not configurable per request)
COUNTRY_CODE = "us"
LANGUAGE = "english"

# Steam appdetails endpoint base URL
STEAM_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"


class SteamStoreClient:
    """Client for Steam storefront appdetails endpoint.

    Fetches app metadata (genres, categories, release date, price, languages,
    platforms, DLC count, disk space, Deck compatibility) for a single appid.
    Locale is pinned to cc=us&l=english and is not configurable.

    Attributes:
        settings: Configuration object with API key, timeout, and User-Agent.
        http_client: Underlying HttpClient for making HTTP requests.
    """

    def __init__(self, settings: Settings, http_client: HttpClient) -> None:
        """Initialize the Steam Store client.

        Args:
            settings: Configuration object with API key, timeout, and User-Agent.
            http_client: Underlying HttpClient for making rate-limited HTTP requests.
        """
        self.settings = settings
        self.http_client = http_client

    def fetch_app_details(self, appid: int) -> tuple[int, dict]:
        """Fetch appdetails for one appid, pinned to cc=us&l=english.

        Args:
            appid: The Steam application id.

        Returns:
            (status_code, payload) from HttpClient.get_json. On success, payload is
            Steam's {"<appid>": {"success": true, "data": {...}}} shape, persisted
            verbatim.

        Preconditions:
            appid > 0
            self.settings.steam_web_api_key is not required for appdetails
            (it is a public, unauthenticated storefront endpoint) -- only the
            reviews endpoint and certain Steam Web API calls require a key.

        Postconditions:
            Every call requests exactly cc=us and l=english, regardless of any
            run-level configuration.
            Returns the tuple as-is from HttpClient.get_json, with no
            post-processing (parsing happens in enrichment.normalize_features, not here).

        Edge cases:
            - success: false payloads are returned unchanged
            - Non-game app types (dlc, demo, video, music, tool) are returned
              unchanged; exclusion by app_type happens in enrichment, not here
            - Geo-blocking scenarios return whatever Steam actually sends
              (e.g. success: false)
        """
        params = {
            "appids": str(appid),
            "cc": COUNTRY_CODE,
            "l": LANGUAGE,
        }

        status_code, payload = self.http_client.get_json(
            STEAM_APPDETAILS_URL,
            params=params,
        )

        return status_code, payload
