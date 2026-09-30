"""SteamSpy API client for bulk catalog and per-app detail fetches."""

from .http_client import HttpClient


class SteamSpyClient:
    """Wraps SteamSpy API endpoints.

    Provides methods to fetch:
    - Paginated bulk catalog via the 'all' endpoint
    - Per-app detail summaries via the 'appdetails' endpoint

    Does not call RateLimiter.acquire() internally; callers are responsible
    for throttling. Returns (status_code, payload) tuples as-is from HttpClient.
    """

    BASE_URL = "https://steamspy.com/api.php"

    def __init__(self, http_client: HttpClient) -> None:
        """Initialize the SteamSpy client.

        Args:
            http_client: HttpClient instance to use for all requests.
        """
        self._http_client = http_client

    def fetch_all_page(self, page: int) -> tuple[int, dict]:
        """Fetch one page of the SteamSpy bulk catalog.

        Args:
            page: Zero-based page index, per SteamSpy's request=all&page=N convention.

        Returns:
            (status_code, payload) as returned by HttpClient.get_json. payload, on success,
            is a dict keyed by appid-as-string, each value containing SteamSpy's per-app
            summary fields (name, developer, publisher, positive, negative, owners, price,
            initialprice, discount, tags, ...).

        Note:
            Does not call RateLimiter.acquire() internally -- fetch_steamspy_catalog
            (the module-level orchestrating function) calls acquire() once per page before
            invoking this method, per AcquisitionConfig.steamspy_page_delay_seconds.
        """
        params = {"request": "all", "page": page}
        return self._http_client.get_json(self.BASE_URL, params=params)

    def fetch_app(self, appid: int) -> tuple[int, dict]:
        """Fetch SteamSpy's per-app detail endpoint for one appid.

        Args:
            appid: The Steam application id.

        Returns:
            (status_code, payload) from HttpClient.get_json.

        Note:
            REVISED 2026-09-23 (see ARCHITECTURE.md's Data Sources correction): a real
            end-to-end run showed SteamSpy's bulk 'all' payload does NOT carry a
            'tags' field at all, contradicting this project's earlier assumption.
            This method IS now invoked by run_acquisition, once per surviving
            candidate, specifically to source tags -- see
            acquisition.funnel.fetch_steamspy_details.
        """
        params = {"request": "appdetails", "appid": appid}
        return self._http_client.get_json(self.BASE_URL, params=params)
