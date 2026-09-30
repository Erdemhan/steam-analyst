"""Rate limiting for HTTP requests with token bucket and Retry-After support."""

import email.utils
import threading
import time
from collections.abc import Mapping
from typing import Callable

from .errors import RequestBudgetExceeded


class RateLimiter:
    """Token bucket rate limiter with per-run request budget and Retry-After support.

    Blocks acquire() calls to respect a configured minimum interval between requests
    and raises RequestBudgetExceeded when the per-run budget is exhausted. Honors
    HTTP 429 Retry-After headers and widens the base interval after repeated 429s
    to gracefully degrade under rate-limiting pressure.

    Thread-safe via internal locking.
    """

    def __init__(
        self,
        interval_seconds: float,
        request_budget: int,
        time_fn: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        cancel_token: threading.Event | None = None,
    ):
        """Initialize a rate limiter.

        Args:
            interval_seconds: Minimum delay (in seconds) between consecutive
                acquire() calls. Typically derived from
                AcquisitionConfig.steamspy_page_delay_seconds or computed from
                steam_requests_per_minute.
            request_budget: Maximum number of acquire() calls that will succeed
                before RequestBudgetExceeded is raised. A hard per-run cap on
                total requests.
            time_fn: Callable returning elapsed seconds (e.g., time.monotonic).
                Defaults to time.monotonic. Injected for testing so tests never
                block on real time.
            sleep_fn: Callable sleeping for N seconds. Defaults to time.sleep.
                Injected for testing.
            cancel_token: Optional threading.Event that signals cooperative
                cancellation. If set before acquire() completes its wait, raises
                an exception or returns early so no token is consumed. The caller
                (which has access to orchestration) is responsible for translating
                this to PipelineCancelled.
        """
        if interval_seconds <= 0:
            raise ValueError(f"interval_seconds must be positive, got {interval_seconds}")
        if request_budget <= 0:
            raise ValueError(f"request_budget must be positive, got {request_budget}")

        self._interval_seconds = interval_seconds
        self._base_interval_seconds = interval_seconds
        self._request_budget = request_budget
        self._remaining_budget = request_budget
        self._time_fn = time_fn or time.monotonic
        self._sleep_fn = sleep_fn or time.sleep
        self._cancel_token = cancel_token

        self._last_request_time: float | None = None
        self._retry_after_until: float = 0.0
        self._has_seen_429 = False
        self._lock = threading.Lock()
        self._widening_factor = 2.0

    def acquire(self) -> None:
        """Acquire permission to make one HTTP request.

        Blocks (via a monotonic-clock-based sleep, injectable in tests) until
        the configured interval since the last granted request has elapsed, then
        decrements the remaining request budget.

        On first call, returns immediately (no wait).
        Respects any Retry-After delay set by a prior observe_response(429, ...).
        If cancel_token is set during the wait, raises AcquisitionCancelled.

        Raises:
            RequestBudgetExceeded: If the per-run request_budget has already been
                fully consumed.
            AcquisitionCancelled: If the cancel_token is set during the wait.

        Postconditions:
            - No two acquire() calls on the same instance return less than the
              configured interval apart, as measured by the injected clock.
            - remaining_budget() decreases by exactly 1 on every successful call.
            - Once budget reaches 0, every subsequent call raises RequestBudgetExceeded
              without sleeping.
        """
        with self._lock:
            if self._remaining_budget <= 0:
                raise RequestBudgetExceeded(
                    f"Request budget exhausted (allowed {self._request_budget})"
                )

            if self._last_request_time is None:
                self._remaining_budget -= 1
                self._last_request_time = self._time_fn()
                return

            now = self._time_fn()
            time_since_last = now - self._last_request_time

            min_wait = max(self._interval_seconds, self._retry_after_until - now)
            wait_time = max(0.0, min_wait - time_since_last)

        if wait_time > 0:
            if self._cancel_token is not None:
                if self._cancel_token.wait(timeout=wait_time):
                    raise AcquisitionCancelled("Rate limiter wait cancelled")
            else:
                self._sleep_fn(wait_time)

        with self._lock:
            if self._remaining_budget <= 0:
                raise RequestBudgetExceeded(
                    f"Request budget exhausted (allowed {self._request_budget})"
                )

            now = self._time_fn()
            self._last_request_time = now
            self._remaining_budget -= 1

    def remaining_budget(self) -> int:
        """Return remaining request budget.

        Returns:
            The number of further acquire() calls that will succeed before the
            budget is exhausted. Never negative (floors at 0 once fully consumed).
        """
        with self._lock:
            return max(0, self._remaining_budget)

    def observe_response(self, status_code: int, headers: Mapping[str, str]) -> None:
        """Update limiter state from a response.

        On HTTP 429 with a parseable Retry-After header, the next acquire() call
        waits at least that many seconds. Additionally, observing a second 429
        within the same run widens the limiter's base interval for the remainder
        of the run (interval widening is monotonic and persists across successful
        responses).

        On 5xx status codes, observe_response does not perform widening (HttpClient's
        own backoff handles 5xx retries at the request level); it only tracks 429s
        for interval widening.

        On 2xx/3xx/4xx-other, no state change occurs beyond bookkeeping.

        Args:
            status_code: The HTTP status code received.
            headers: Response headers, checked case-insensitively for 'Retry-After'.
        """
        with self._lock:
            if status_code == 429:
                retry_after_value = self._get_header_value(headers, "Retry-After")
                if retry_after_value is not None:
                    try:
                        retry_after_seconds = int(retry_after_value)
                        self._retry_after_until = self._time_fn() + retry_after_seconds
                    except ValueError:
                        retry_after_datetime = email.utils.parsedate_to_datetime(
                            retry_after_value
                        )
                        if retry_after_datetime is not None:
                            retry_after_timestamp = retry_after_datetime.timestamp()
                            now_wall = time.time()
                            delta_seconds = max(0.0, retry_after_timestamp - now_wall)
                            self._retry_after_until = self._time_fn() + delta_seconds

                if self._has_seen_429:
                    self._interval_seconds *= self._widening_factor
                else:
                    self._has_seen_429 = True

    @staticmethod
    def _get_header_value(headers: Mapping[str, str], key: str) -> str | None:
        """Get a header value case-insensitively.

        Args:
            headers: HTTP headers mapping.
            key: Header name to look up.

        Returns:
            The header value, or None if not present.
        """
        key_lower = key.lower()
        for header_key, header_value in headers.items():
            if header_key.lower() == key_lower:
                return header_value
        return None


class AcquisitionCancelled(Exception):
    """Rate limiter wait was interrupted by cancellation.

    This is an internal acquisition-module exception raised by RateLimiter.acquire()
    when cancel_token is set. The caller (orchestration) which has access to
    PipelineCancelled should catch this and translate it.
    """

    pass
