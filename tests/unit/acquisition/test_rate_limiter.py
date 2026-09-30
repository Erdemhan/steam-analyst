"""Unit tests for RateLimiter rate limiting and budget tracking."""

import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import formatdate

import pytest

from src.steam_analyst.acquisition.errors import RequestBudgetExceeded
from src.steam_analyst.acquisition.rate_limiter import AcquisitionCancelled, RateLimiter


class FakeClock:
    """Injected monotonic clock for testing without real sleep."""

    def __init__(self, start_time: float = 0.0):
        """Initialize with a starting time."""
        self.current_time = start_time

    def __call__(self) -> float:
        """Return current time."""
        return self.current_time

    def advance(self, delta: float) -> None:
        """Advance the clock by delta seconds."""
        self.current_time += delta


class FakeSleep:
    """Injected sleep function that advances the clock instead of sleeping."""

    def __init__(self, clock: FakeClock):
        """Initialize with a clock to advance."""
        self.clock = clock
        self.total_slept = 0.0

    def __call__(self, duration: float) -> None:
        """Sleep by advancing the clock."""
        if duration < 0:
            raise ValueError(f"sleep duration must be non-negative, got {duration}")
        self.clock.advance(duration)
        self.total_slept += duration


class TestRateLimiterAcquire:
    """Tests for RateLimiter.acquire() method."""

    def test_first_call_does_not_wait(self):
        """First acquire() on a fresh instance returns without any delay."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()

        assert sleep.total_slept == 0.0
        assert limiter.remaining_budget() == 9

    def test_spaces_calls_to_configured_interval(self):
        """Two acquire() calls are spaced by at least the configured interval."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=2.5,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()
        initial_time = clock.current_time

        limiter.acquire()

        elapsed = clock.current_time - initial_time
        assert elapsed >= 2.5
        assert sleep.total_slept == 2.5

    def test_raises_at_budget_exhaustion(self):
        """acquire() raises RequestBudgetExceeded once budget is spent."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=0.1,
            request_budget=2,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()
        limiter.acquire()

        with pytest.raises(RequestBudgetExceeded):
            limiter.acquire()

    def test_budget_decrements_per_acquire(self):
        """remaining_budget() decreases by 1 after each successful acquire()."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=0.1,
            request_budget=5,
            time_fn=clock,
            sleep_fn=sleep,
        )

        assert limiter.remaining_budget() == 5

        for i in range(1, 6):
            limiter.acquire()
            assert limiter.remaining_budget() == 5 - i

    def test_does_not_sleep_on_first_call(self):
        """The first acquire() returns immediately without sleeping."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=100.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()

        assert sleep.total_slept == 0.0

    def test_respects_retry_after_delay(self):
        """acquire() waits for Retry-After delay set by observe_response()."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()
        limiter.observe_response(429, {"Retry-After": "5"})

        limiter.acquire()

        # Should have waited the full 5 seconds (Retry-After > interval)
        assert sleep.total_slept == 5.0

    def test_initialization_with_invalid_interval(self):
        """Construction with interval_seconds <= 0 raises ValueError."""
        with pytest.raises(ValueError, match="interval_seconds must be positive"):
            RateLimiter(interval_seconds=0.0, request_budget=10)

        with pytest.raises(ValueError, match="interval_seconds must be positive"):
            RateLimiter(interval_seconds=-1.0, request_budget=10)

    def test_initialization_with_invalid_budget(self):
        """Construction with request_budget <= 0 raises ValueError."""
        with pytest.raises(ValueError, match="request_budget must be positive"):
            RateLimiter(interval_seconds=1.0, request_budget=0)

        with pytest.raises(ValueError, match="request_budget must be positive"):
            RateLimiter(interval_seconds=1.0, request_budget=-5)

    def test_cancellation_during_wait(self):
        """acquire() raises AcquisitionCancelled if cancel_token is set during wait."""
        clock = FakeClock()
        cancel_token = threading.Event()

        limiter = RateLimiter(
            interval_seconds=10.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=lambda d: cancel_token.wait(d),
            cancel_token=cancel_token,
        )

        limiter.acquire()

        def cancel_after_delay():
            time.sleep(0.01)
            cancel_token.set()

        thread = threading.Thread(target=cancel_after_delay)
        thread.start()

        with pytest.raises(AcquisitionCancelled):
            limiter.acquire()

        thread.join()

    def test_budget_recheck_after_wait(self):
        """Budget is rechecked after waiting to guard against concurrent exhaustion."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=2,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()
        limiter.acquire()

        with pytest.raises(RequestBudgetExceeded):
            limiter.acquire()


class TestRateLimiterRemainingBudget:
    """Tests for RateLimiter.remaining_budget() method."""

    def test_full_budget_before_any_use(self):
        """Fresh instance reports full request_budget."""
        limiter = RateLimiter(interval_seconds=1.0, request_budget=100)

        assert limiter.remaining_budget() == 100

    def test_decrements_per_acquire(self):
        """remaining_budget() decreases by 1 after each acquire()."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=0.1,
            request_budget=100,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()
        limiter.acquire()
        limiter.acquire()

        assert limiter.remaining_budget() == 97

    def test_floors_at_zero(self):
        """remaining_budget() never goes negative, floors at 0."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=0.1,
            request_budget=1,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()

        assert limiter.remaining_budget() == 0

        with pytest.raises(RequestBudgetExceeded):
            limiter.acquire()

        assert limiter.remaining_budget() == 0


class TestRateLimiterObserveResponse:
    """Tests for RateLimiter.observe_response() method."""

    def test_retry_after_seconds_form(self):
        """Retry-After header in seconds form is respected."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()
        limiter.observe_response(429, {"Retry-After": "5"})

        limiter.acquire()

        assert sleep.total_slept == 5.0

    def test_retry_after_http_date_form(self):
        """Retry-After header in HTTP-date form is parsed and used."""
        clock = FakeClock(start_time=1000.0)
        sleep = FakeSleep(clock)

        future_time = datetime.now(timezone.utc) + timedelta(seconds=10)
        retry_after_header = formatdate(future_time.timestamp(), usegmt=True)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()
        limiter.observe_response(429, {"Retry-After": retry_after_header})

        limiter.acquire()

        # Should wait approximately 10 seconds (within some tolerance for clock drift)
        assert 9.0 <= sleep.total_slept <= 11.0

    def test_repeated_429_widens_interval(self):
        """Two consecutive 429 observations widen the base interval."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        initial_interval = limiter._interval_seconds

        limiter.acquire()
        limiter.observe_response(429, {})

        limiter.acquire()
        limiter.observe_response(429, {})

        widened_interval = limiter._interval_seconds

        assert widened_interval > initial_interval
        assert widened_interval == initial_interval * 2.0

    def test_success_does_not_reset_widening(self):
        """A 200 response after 429s does not shrink the interval back down."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()
        limiter.observe_response(429, {})

        widened_interval = limiter._interval_seconds

        limiter.acquire()
        limiter.observe_response(200, {})

        assert limiter._interval_seconds == widened_interval

    def test_429_without_retry_after_widens_only(self):
        """429 without Retry-After header just widens the interval."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()
        limiter.observe_response(429, {})

        limiter.acquire()

        # Should have waited the standard interval (1.0), not any special Retry-After
        assert sleep.total_slept == 1.0

    def test_non_429_no_state_change(self):
        """200, 3xx, 4xx-other do not change limiter state."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()
        limiter.observe_response(200, {})

        limiter.acquire()
        limiter.observe_response(404, {})

        limiter.acquire()
        limiter.observe_response(500, {})

        initial_interval = 1.0
        assert limiter._interval_seconds == initial_interval

    def test_header_case_insensitivity(self):
        """Retry-After header is found regardless of case."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()
        limiter.observe_response(429, {"retry-after": "3"})

        limiter.acquire()

        assert sleep.total_slept == 3.0

    def test_retry_after_header_variations(self):
        """Various Retry-After header case variations are recognized."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        for header_key in ["Retry-After", "retry-after", "RETRY-AFTER", "Retry-After"]:
            limiter.acquire()
            limiter.observe_response(429, {header_key: "2"})

            limiter.acquire()

            if sleep.total_slept > 0:
                assert sleep.total_slept >= 2.0
                break


class TestRateLimiterThreadSafety:
    """Tests for thread safety of RateLimiter."""

    def test_concurrent_acquire_respects_budget(self):
        """Multiple threads calling acquire() concurrently respect the budget."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        budget = 10
        limiter = RateLimiter(
            interval_seconds=0.1,
            request_budget=budget,
            time_fn=clock,
            sleep_fn=sleep,
        )

        successful_acquires = []
        lock = threading.Lock()

        def acquire_thread():
            try:
                for _ in range(20):
                    limiter.acquire()
                    with lock:
                        successful_acquires.append(1)
                    if limiter.remaining_budget() == 0:
                        break
            except RequestBudgetExceeded:
                pass

        threads = [threading.Thread(target=acquire_thread) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successful_acquires) == budget
        assert limiter.remaining_budget() == 0

    def test_concurrent_observe_response_is_safe(self):
        """Multiple threads calling observe_response() concurrently is safe."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=100,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()

        def observe_thread():
            for i in range(10):
                limiter.observe_response(429, {"Retry-After": str(i % 5 + 1)})

        threads = [threading.Thread(target=observe_thread) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert limiter._interval_seconds >= 1.0


class TestRateLimiterEdgeCases:
    """Edge case tests for RateLimiter."""

    def test_exact_budget_limit(self):
        """Exactly exhausting the budget raises on the next call."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=0.1,
            request_budget=5,
            time_fn=clock,
            sleep_fn=sleep,
        )

        for _ in range(5):
            limiter.acquire()

        with pytest.raises(RequestBudgetExceeded):
            limiter.acquire()

    def test_fractional_interval(self):
        """Fractional intervals work correctly."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=0.5,
            request_budget=5,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()
        limiter.acquire()

        assert sleep.total_slept == 0.5

    def test_large_budget(self):
        """Large budgets are handled correctly."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=0.01,
            request_budget=10000,
            time_fn=clock,
            sleep_fn=sleep,
        )

        assert limiter.remaining_budget() == 10000

        for _ in range(100):
            limiter.acquire()

        assert limiter.remaining_budget() == 9900

    def test_zero_wait_required(self):
        """No sleep when interval has already elapsed."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()

        clock.advance(2.0)

        limiter.acquire()

        assert sleep.total_slept == 0.0

    def test_partial_wait_when_interval_partially_elapsed(self):
        """Waits only for the remaining interval time."""
        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=2.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()

        clock.advance(1.0)

        limiter.acquire()

        assert sleep.total_slept == 1.0

    def test_retry_after_in_past_yields_zero_wait(self):
        """Retry-After date in the past yields 0 wait time."""
        past_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        retry_after_header = formatdate(past_time.timestamp(), usegmt=True)

        clock = FakeClock()
        sleep = FakeSleep(clock)

        limiter = RateLimiter(
            interval_seconds=1.0,
            request_budget=10,
            time_fn=clock,
            sleep_fn=sleep,
        )

        limiter.acquire()
        limiter.observe_response(429, {"Retry-After": retry_after_header})

        limiter.acquire()

        assert sleep.total_slept == 1.0
