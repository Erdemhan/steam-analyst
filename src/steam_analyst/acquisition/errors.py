"""Acquisition stage exceptions."""


class AcquisitionError(Exception):
    """Stage-fatal acquisition failure.

    Raised for: a persistent bulk-catalog page failure (fetch_steamspy_catalog),
    a missing STEAM_WEB_API_KEY where a called endpoint requires one, or any
    other condition where continuing the stage would produce a meaningless
    partial result. NOT raised for an individual candidate's failed appdetails
    or review fetch -- those are recorded and counted (detail_failed /
    reviews_failed), never raised, per the module's core invariant that a
    per-app failure degrades that app, not the run.
    """

    pass


class RequestBudgetExceeded(AcquisitionError):
    """Per-run HTTP request budget exhausted.

    Raised by RateLimiter.acquire() when remaining_budget() would go negative.
    Propagates up through whichever fetch_* function was mid-iteration, through
    run_acquisition, to orchestration, which marks the run 'failed'. Distinguished
    from the base AcquisitionError so callers/tests can specifically assert on
    budget exhaustion rather than any generic stage failure.
    """

    pass
