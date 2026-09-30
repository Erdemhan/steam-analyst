"""Steam reviews endpoint client."""

from steam_analyst.acquisition.http_client import HttpClient

# Locale pinning per ARCHITECTURE.md: all Steam Web API calls use this fixed locale.
STEAM_REVIEWS_LOCALE = "us"
STEAM_REVIEWS_LANGUAGE = "english"


class SteamReviewsClient:
    """Wraps the Steam reviews endpoint.

    Requests only the review summary (no review bodies) to keep payloads minimal.
    All requests are pinned to cc=us&l=english for locale consistency with storefront
    calls, per ARCHITECTURE.md.
    """

    def __init__(self, http_client: HttpClient) -> None:
        """Initialize the reviews client.

        Args:
            http_client: Shared HttpClient instance for making requests.
        """
        self.http_client = http_client

    def fetch_review_summary(self, appid: int) -> tuple[int, dict]:
        """Fetch the review summary for one appid.

        Args:
            appid: The Steam application id.

        Returns:
            (status_code, payload) from HttpClient.get_json. On success, payload
            contains query_summary with total_positive, total_negative, total_reviews,
            review_score, review_score_desc.

        Note (locale): pinned to cc=us&l=english (language filter on the reviews
        endpoint affects which review-language subset the summary counts are computed
        over on some Steam endpoints; 'english' is used consistently with appdetails
        per ARCHITECTURE.md's locale-pinning decision, so both figures are computed on
        the same basis).
        """
        url = f"https://store.steampowered.com/appreviews/{appid}"
        params = {
            "json": 1,
            "num_per_page": 0,  # Request only summary, no review bodies
            "cc": STEAM_REVIEWS_LOCALE,
            "l": STEAM_REVIEWS_LANGUAGE,
        }
        return self.http_client.get_json(url, params=params)
