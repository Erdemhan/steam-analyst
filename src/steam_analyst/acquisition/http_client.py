"""Shared HTTP GET client with retry logic, rate-limiting support and safe error handling."""

import json
import random
import time
from collections.abc import Mapping
from typing import Any

import requests

from steam_analyst.config import Settings


class HttpClient:
    """Shared base HTTP GET client for all acquisition endpoints.

    Provides: session reuse, per-request timeout, custom User-Agent, exponential
    backoff with jitter on 5xx/timeout, bounded retries. Returns (status_code, payload)
    tuples rather than raising on HTTP errors so callers can persist failures verbatim.
    Does not itself call RateLimiter.acquire() -- callers must throttle before
    calling get_json, so retries do not each re-throttle the rate limiter.

    Attributes:
        timeout_seconds: Per-request timeout, from Settings.http_timeout_seconds.
        user_agent: Custom User-Agent header, from Settings.user_agent.
        max_retries: Bounded retry count on 5xx/timeout from AcquisitionConfig.
        backoff_base_seconds: Initial exponential backoff interval.
        backoff_max_seconds: Backoff interval ceiling.
    """

    def __init__(
        self,
        settings: Settings,
        max_retries: int,
        backoff_base_seconds: float,
        backoff_max_seconds: float,
        session: requests.Session | None = None,
    ) -> None:
        """Initialize the HTTP client.

        Args:
            settings: Configuration container with http_timeout_seconds and user_agent.
            max_retries: Maximum number of retries on 5xx/timeout.
            backoff_base_seconds: Initial exponential backoff interval (seconds).
            backoff_max_seconds: Maximum backoff interval (seconds).
            session: Optional requests.Session for dependency injection (test use).
                Defaults to a fresh requests.Session().
        """
        self.timeout_seconds = settings.http_timeout_seconds
        self.user_agent = settings.user_agent
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self.session = session or requests.Session()

    def get_json(
        self, url: str, params: Mapping[str, Any] | None = None
    ) -> tuple[int, dict]:
        """Perform a rate-limited-by-caller HTTP GET and parse the JSON body.

        Never raises for non-2xx status or JSON parse errors; returns a tuple
        of (status_code, payload) so callers can persist failures verbatim.
        Retries up to max_retries times on 5xx status or connection errors,
        using exponential backoff with jitter.

        Args:
            url: Absolute request URL.
            params: Query parameters (dict-like).

        Returns:
            (status_code, payload). payload is a dict parsed from the response body,
            or a wrapper dict if the response is not valid JSON:
            - On success (2xx with valid JSON): (status_code, <parsed dict>)
            - On non-JSON body: (status_code, {'_raw_text': <body>, '_parse_error': True})
            - On connection error (timeout, reset, DNS): (0, {'_raw_text': '', '_parse_error': True, '_transport_error': '<error type>'})
            Status code 0 is a sentinel indicating no HTTP response was received at all.

        Preconditions:
            url is an absolute http(s) URL.
            self.timeout_seconds > 0 (enforced by Settings.__post_init__).

        Postconditions:
            Always returns a (int, dict) tuple; never raises for well-formed URLs.
            On success, status_code is the status of the final attempt, payload is
            from that final attempt.
            Retries never exceed max_retries additional attempts beyond the first.
        """
        headers = {"User-Agent": self.user_agent}

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
                # Successfully got an HTTP response. Try to parse JSON.
                try:
                    payload = response.json()
                except (json.JSONDecodeError, ValueError):
                    # Body is not valid JSON; wrap it.
                    payload = {
                        "_raw_text": response.text,
                        "_parse_error": True,
                    }

                # Check if we should retry on 5xx status code.
                if 500 <= response.status_code < 600:
                    if attempt < self.max_retries:
                        # Retry with backoff.
                        self._sleep_with_backoff(attempt)
                        continue
                    # Final attempt is 5xx; return it.
                    return response.status_code, payload

                # Non-5xx response (success or 4xx); return immediately.
                return response.status_code, payload

            except requests.exceptions.Timeout:
                # Connection timed out.
                if attempt < self.max_retries:
                    # Retry with backoff.
                    self._sleep_with_backoff(attempt)
                    continue
                # Final attempt failed with timeout.
                return 0, {
                    "_raw_text": "",
                    "_parse_error": True,
                    "_transport_error": "timeout",
                }

            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.RequestException,
            ):
                # Connection reset, DNS failure, or other transport error.
                if attempt < self.max_retries:
                    # Retry with backoff.
                    self._sleep_with_backoff(attempt)
                    continue
                # Final attempt failed with connection error.
                return 0, {
                    "_raw_text": "",
                    "_parse_error": True,
                    "_transport_error": "connection",
                }

    def _sleep_with_backoff(self, attempt: int) -> None:
        """Sleep with exponential backoff plus jitter before a retry.

        Args:
            attempt: Zero-indexed attempt number (0, 1, 2, ...).
        """
        # Exponential backoff: base * (2 ** attempt)
        backoff = min(
            self.backoff_base_seconds * (2 ** attempt),
            self.backoff_max_seconds,
        )
        # Add random jitter: ±10% of the backoff interval
        jitter = random.uniform(-0.1 * backoff, 0.1 * backoff)
        sleep_time = max(0, backoff + jitter)
        time.sleep(sleep_time)
