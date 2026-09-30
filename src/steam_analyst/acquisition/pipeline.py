"""Acquisition stage orchestration: coordinating bulk fetch, filtering, and per-app enrichment."""

import sqlite3
import time
from datetime import date, datetime
from typing import Iterator

import pandas as pd

from steam_analyst.acquisition.errors import AcquisitionError, RequestBudgetExceeded
from steam_analyst.acquisition.funnel import (
    AcquisitionReport,
    FunnelResult,
    build_catalog_frame,
    coarse_filter,
    fetch_app_details,
    fetch_review_summaries,
    fetch_steamspy_catalog,
    fetch_steamspy_details,
)
from steam_analyst.acquisition.http_client import HttpClient
from steam_analyst.acquisition.rate_limiter import RateLimiter
from steam_analyst.acquisition.steam_reviews_client import SteamReviewsClient
from steam_analyst.acquisition.steam_store_client import SteamStoreClient
from steam_analyst.acquisition.steamspy_client import SteamSpyClient
from steam_analyst.config import AcquisitionConfig, Settings
from steam_analyst.storage import (
    EventSink,
    RawPayload,
    get_run,
    read_fetched_appids,
    read_raw_payloads,
    upsert_raw_payloads,
    write_analysis_result,
)


def run_acquisition(
    conn: sqlite3.Connection,
    run_id: str,
    config: AcquisitionConfig,
    settings: Settings,
    *,
    on_event: EventSink,
    max_catalog_pages: int | None = None,
) -> AcquisitionReport:
    """Run the full acquisition stage for one run.

    Args:
        conn: An open storage connection (this stage's own thread's connection, per ADR-006).
        run_id: The run to acquire data for; must already exist (created by storage.create_run before this is called).
        config: Acquisition tunables including the coarse-filter band.
        settings: Environment settings (API key, timeouts).
        on_event: Progress/log sink.
        max_catalog_pages: Optional cap on SteamSpy bulk pages fetched, from
            orchestration.PipelineConfig.max_catalog_pages. None (the default)
            means no limit -- fetch the entire catalog. Intended for smoke
            tests and manual verification runs, never for a real analysis run.

    Returns:
        An AcquisitionReport summarizing the stage.

    Raises:
        AcquisitionError: Propagated from any step that is stage-fatal (see AcquisitionError's own spec).
            A per-app failure within detail or review fetches is recorded, not raised.
    """
    stage_start_time = time.time()

    try:
        on_event(
            stage="acquisition",
            level="info",
            message="Acquisition stage starting",
        )

        # Step 1: Fetch SteamSpy catalog and persist
        on_event(
            stage="acquisition",
            level="info",
            message="Starting SteamSpy bulk catalog fetch",
        )
        steamspy_payloads = list(
            _fetch_and_persist_steamspy(
                conn, run_id, config, settings, on_event, max_pages=max_catalog_pages
            )
        )
        catalog_size = len(steamspy_payloads)

        # Step 2: Build catalog frame
        on_event(
            stage="acquisition",
            level="info",
            message=f"Building catalog frame from {catalog_size} apps",
        )
        catalog_df = build_catalog_frame(steamspy_payloads)

        # Step 3: Apply coarse filter
        on_event(
            stage="acquisition",
            level="info",
            message=f"Applying coarse filter to {len(catalog_df)} candidates",
        )
        funnel_result = coarse_filter(catalog_df, config.coarse_filter)
        candidate_appids = funnel_result.candidates["appid"].tolist()

        # Step 4: Write funnel report to analysis_results
        on_event(
            stage="acquisition",
            level="info",
            message=f"Coarse filter produced {len(candidate_appids)} candidates",
        )
        # Get parameters_version from run
        run_record = get_run(conn, run_id)
        parameters_version = run_record.parameters_version if run_record else ""
        _write_funnel_report(conn, run_id, funnel_result, parameters_version)

        # Early exit if no candidates
        if len(candidate_appids) == 0:
            on_event(
                stage="acquisition",
                level="warning",
                message="Coarse filter produced zero candidates; skipping detail/review fetches",
            )
            duration = time.time() - stage_start_time
            report = AcquisitionReport(
                run_id=run_id,
                catalog_size=catalog_size,
                candidate_count=0,
                detail_fetched=0,
                detail_failed=0,
                reviews_fetched=0,
                reviews_failed=0,
                requests_made=0,
                duration_seconds=duration,
                funnel=funnel_result,
            )
            on_event(
                stage="acquisition",
                level="info",
                message="Acquisition stage completed successfully with zero candidates",
            )
            return report

        # Step 5: Fetch app details and apply release-date filter
        on_event(
            stage="acquisition",
            level="info",
            message=f"Starting detail fetch for {len(candidate_appids)} candidates",
        )

        # Create shared rate limiter
        rate_limiter = _create_rate_limiter(config)

        # Fetch details, persist, and apply release-date filter
        detail_results = _fetch_and_filter_details(
            conn, run_id, config, settings, candidate_appids, rate_limiter, on_event
        )

        # Update funnel result with release-date rejections
        funnel_result_updated = FunnelResult(
            candidates=detail_results["candidates_after_date_filter"],
            total_input=funnel_result.total_input,
            rejected_by_reason=detail_results["updated_rejection_reasons"],
            criteria=funnel_result.criteria,
        )

        # Re-write funnel report with updated rejection counts and detail-fetch coverage
        _write_funnel_report(
            conn,
            run_id,
            funnel_result_updated,
            parameters_version,
            detail_fetched=detail_results["detail_fetched"],
            detail_failed=detail_results["detail_failed"],
        )

        # Check if we have a total failure: candidates_after_coarse > 0 but detail_fetched == 0
        if len(candidate_appids) > 0 and detail_results["detail_fetched"] == 0:
            raise AcquisitionError(
                f"Total acquisition failure: {len(candidate_appids)} candidates after coarse filter, "
                f"but detail_fetched == 0 (no successful detail fetches). "
                f"This suggests a persistent error in the detail fetch phase."
            )

        # Get candidates that survived the release-date filter
        survivors_after_date_filter = detail_results["candidates_after_date_filter"][
            "appid"
        ].tolist()

        # Step 6: Fetch review summaries
        on_event(
            stage="acquisition",
            level="info",
            message=f"Starting review fetch for {len(survivors_after_date_filter)} survivors",
        )
        review_results = _fetch_and_persist_reviews(
            conn, run_id, settings, config, survivors_after_date_filter, rate_limiter, on_event
        )

        # Step 7: Fetch SteamSpy per-app details (tags) for the same survivors.
        # SteamSpy's bulk payload has no tags field -- see ARCHITECTURE.md's
        # Data Sources correction, 2026-09-23.
        on_event(
            stage="acquisition",
            level="info",
            message=f"Starting SteamSpy tag fetch for {len(survivors_after_date_filter)} survivors",
        )
        steamspy_details_results = _fetch_and_persist_steamspy_details(
            conn, run_id, settings, config, survivors_after_date_filter, rate_limiter, on_event
        )

        # Prepare final report
        duration = time.time() - stage_start_time
        report = AcquisitionReport(
            run_id=run_id,
            catalog_size=catalog_size,
            candidate_count=len(survivors_after_date_filter),
            detail_fetched=detail_results["detail_fetched"],
            detail_failed=detail_results["detail_failed"],
            reviews_fetched=review_results["reviews_fetched"],
            reviews_failed=review_results["reviews_failed"],
            requests_made=detail_results["requests_made"]
            + review_results["requests_made"]
            + steamspy_details_results["requests_made"],
            duration_seconds=duration,
            funnel=funnel_result_updated,
        )

        on_event(
            stage="acquisition",
            level="info",
            message=f"Acquisition stage completed successfully: {len(survivors_after_date_filter)} candidates with details and reviews",
        )

        return report

    except RequestBudgetExceeded as e:
        on_event(
            stage="acquisition",
            level="error",
            message=f"Request budget exhausted: {e}",
        )
        raise AcquisitionError(f"Request budget exhausted: {e}") from e
    except AcquisitionError:
        raise
    except Exception as e:
        on_event(
            stage="acquisition",
            level="error",
            message=f"Unexpected error in acquisition stage: {e}",
        )
        raise AcquisitionError(f"Acquisition stage failed: {e}") from e


def _fetch_and_persist_steamspy(
    conn: sqlite3.Connection,
    run_id: str,
    config: AcquisitionConfig,
    settings: Settings,
    on_event: EventSink,
    *,
    max_pages: int | None = None,
) -> Iterator[RawPayload]:
    """Fetch SteamSpy catalog, persist in batches, and yield payloads.

    Args:
        conn: Database connection.
        run_id: The run ID to persist under.
        config: Acquisition config.
        settings: Environment settings.
        on_event: Event sink.
        max_pages: Optional cap forwarded to fetch_steamspy_catalog, for smoke tests.

    Yields:
        RawPayload objects as they are fetched.
    """
    http_client = HttpClient(
        settings,
        max_retries=config.max_retries,
        backoff_base_seconds=config.backoff_base_seconds,
        backoff_max_seconds=config.backoff_max_seconds,
    )
    steamspy_client = SteamSpyClient(http_client)

    # No rate limiting for SteamSpy in this context; fetch_steamspy_catalog
    # handles its own pacing via config.steamspy_page_delay_seconds
    payloads_to_persist = []
    batch_size = 500

    for payload in fetch_steamspy_catalog(
        steamspy_client, max_pages=max_pages, on_event=on_event
    ):
        payloads_to_persist.append(payload)
        yield payload

        # Persist in batches
        if len(payloads_to_persist) >= batch_size:
            upsert_raw_payloads(conn, run_id, payloads_to_persist)
            payloads_to_persist = []

    # Persist remaining
    if payloads_to_persist:
        upsert_raw_payloads(conn, run_id, payloads_to_persist)


def _create_rate_limiter(config: AcquisitionConfig) -> RateLimiter:
    """Create a rate limiter for the run.

    Args:
        config: Acquisition config.

    Returns:
        A RateLimiter instance with the configured limits.
    """
    # Compute interval from steam_requests_per_minute
    interval_seconds = 60.0 / config.steam_requests_per_minute
    return RateLimiter(
        interval_seconds=interval_seconds,
        request_budget=config.request_budget,
    )


def _fetch_and_filter_details(
    conn: sqlite3.Connection,
    run_id: str,
    config: AcquisitionConfig,
    settings: Settings,
    candidate_appids: list[int],
    rate_limiter: RateLimiter,
    on_event: EventSink,
) -> dict:
    """Fetch app details, persist, and apply release-date filter.

    Args:
        conn: Database connection.
        run_id: The run ID.
        config: Acquisition config (for release-date filter).
        settings: Environment settings.
        candidate_appids: List of appids to fetch.
        rate_limiter: Shared rate limiter.
        on_event: Event sink.

    Returns:
        A dict with:
        - detail_fetched: count of successful fetches
        - detail_failed: count of failures
        - requests_made: total requests issued
        - candidates_after_date_filter: DataFrame of survivors
        - updated_rejection_reasons: dict with release_date_outside_window count
    """
    http_client = HttpClient(
        settings,
        max_retries=config.max_retries,
        backoff_base_seconds=config.backoff_base_seconds,
        backoff_max_seconds=config.backoff_max_seconds,
    )
    store_client = SteamStoreClient(settings, http_client)

    # Check which appids we've already fetched to support resume
    already_fetched = read_fetched_appids(conn, run_id, "steam_appdetails")
    appids_to_fetch = [aid for aid in candidate_appids if aid not in already_fetched]

    on_event(
        stage="acquisition",
        level="info",
        message=f"Resuming: {len(already_fetched)} already fetched, {len(appids_to_fetch)} to fetch",
    )

    # Fetch and persist new details
    detail_fetched = 0
    detail_failed = 0
    requests_made = 0
    payloads_to_persist = []
    batch_size = 500

    for payload in fetch_app_details(store_client, appids_to_fetch, on_event=on_event):
        rate_limiter.acquire()
        requests_made += 1
        rate_limiter.observe_response(payload.http_status, {})

        payloads_to_persist.append(payload)

        # Count successes and failures
        if payload.http_status == 200:
            # Check if it's a success=true response
            appid_result = payload.payload.get(str(payload.appid), {})
            if isinstance(appid_result, dict) and appid_result.get("success") is True:
                detail_fetched += 1
            else:
                detail_failed += 1
        else:
            detail_failed += 1

        # Persist in batches
        if len(payloads_to_persist) >= batch_size:
            upsert_raw_payloads(conn, run_id, payloads_to_persist)
            payloads_to_persist = []

    # Persist remaining
    if payloads_to_persist:
        upsert_raw_payloads(conn, run_id, payloads_to_persist)

    # Re-read all details (including already-fetched ones)
    all_details = {}
    for raw_payload in read_raw_payloads(conn, run_id, "steam_appdetails"):
        all_details[raw_payload.appid] = raw_payload.payload

    # Apply release-date filter
    candidates_with_dates = []
    release_date_rejected = 0

    for appid in candidate_appids:
        if appid not in all_details:
            # Wasn't fetched or failed; exclude
            continue

        payload = all_details[appid]
        appid_data = payload.get(str(appid), {})

        # Check success
        if not isinstance(appid_data, dict) or appid_data.get("success") is not True:
            continue

        data = appid_data.get("data", {})

        # Parse release_date. Steam's real appdetails response nests this as
        # {"coming_soon": bool, "date": "21 Aug, 2012"}, not a plain string --
        # extract the "date" sub-field before handing it to the date parser.
        release_date_field = data.get("release_date", "")
        if isinstance(release_date_field, dict):
            release_date_str = release_date_field.get("date", "") or ""
        else:
            release_date_str = release_date_field or ""
        parsed_release_date = _parse_release_date(release_date_str)

        # Filter by date range
        if config.coarse_filter.earliest_release_date is not None:
            if parsed_release_date is None:
                # No valid date parsed; exclude conservatively
                release_date_rejected += 1
                continue

            if parsed_release_date < config.coarse_filter.earliest_release_date:
                release_date_rejected += 1
                continue

        if config.coarse_filter.latest_release_date is not None:
            if parsed_release_date is None:
                # No valid date parsed; exclude
                release_date_rejected += 1
                continue

            if parsed_release_date > config.coarse_filter.latest_release_date:
                release_date_rejected += 1
                continue

        # Survived date filter; add appid to survivors
        candidates_with_dates.append(appid)

    # Create a DataFrame of survivors with only appid column (for compatibility)
    candidates_after_date_filter = pd.DataFrame({"appid": candidates_with_dates})

    # Update rejection counts
    updated_rejection_reasons = dict(
        _get_initial_rejection_reasons()
    )  # Start with all zeros
    updated_rejection_reasons["release_date_outside_window"] = release_date_rejected

    return {
        "detail_fetched": detail_fetched,
        "detail_failed": detail_failed,
        "requests_made": requests_made,
        "candidates_after_date_filter": candidates_after_date_filter,
        "updated_rejection_reasons": updated_rejection_reasons,
    }


def _parse_release_date(date_str: str) -> date | None:
    """Parse a Steam release date string leniently.

    Attempts to parse various formats:
    - "2020-01-15" (ISO format)
    - "Jan 15, 2020" (US format)
    - "2020" (year only)
    - "Q1 2020" (quarter format)
    - "Coming Soon" (returns None)

    Args:
        date_str: The date string from Steam.

    Returns:
        A date object if parsing succeeds, None otherwise.
    """
    if not date_str or date_str.lower() == "coming soon":
        return None

    date_str = date_str.strip()

    # Try ISO format (YYYY-MM-DD)
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.date()
    except (ValueError, TypeError):
        pass

    # Try US format (Mon DD, YYYY or similar)

    date_formats = [
        "%b %d, %Y",  # Jan 15, 2020
        "%B %d, %Y",  # January 15, 2020
        "%d %b %Y",  # 15 Jan 2020
        "%d %B %Y",  # 15 January 2020
        "%Y-%m-%d",  # 2020-01-15
    ]

    for fmt in date_formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.date()
        except (ValueError, TypeError):
            pass

    # Try year-only (YYYY)
    try:
        year = int(date_str)
        if 1900 < year < 2100:
            return date(year, 1, 1)
    except (ValueError, TypeError):
        pass

    # Try quarter format (Q1 2020)
    if " " in date_str:
        parts = date_str.split()
        if len(parts) == 2:
            quarter_str, year_str = parts
            try:
                if quarter_str.upper().startswith("Q") and len(quarter_str) == 2:
                    quarter_num = int(quarter_str[1])
                    year = int(year_str)
                    if 1 <= quarter_num <= 4 and 1900 < year < 2100:
                        # Map quarter to month (Q1->1, Q2->4, Q3->7, Q4->10)
                        month = (quarter_num - 1) * 3 + 1
                        return date(year, month, 1)
            except (ValueError, TypeError):
                pass

    # Default: unable to parse
    return None


def _fetch_and_persist_reviews(
    conn: sqlite3.Connection,
    run_id: str,
    settings: Settings,
    config: AcquisitionConfig,
    appids: list[int],
    rate_limiter: RateLimiter,
    on_event: EventSink,
) -> dict:
    """Fetch review summaries and persist.

    Args:
        conn: Database connection.
        run_id: The run ID.
        settings: Environment settings.
        config: Acquisition config (for HttpClient retry/backoff settings).
        appids: List of appids to fetch reviews for.
        rate_limiter: Shared rate limiter.
        on_event: Event sink.

    Returns:
        A dict with:
        - reviews_fetched: count of successful fetches
        - reviews_failed: count of failures
        - requests_made: total requests issued
    """
    http_client = HttpClient(
        settings,
        max_retries=config.max_retries,
        backoff_base_seconds=config.backoff_base_seconds,
        backoff_max_seconds=config.backoff_max_seconds,
    )
    reviews_client = SteamReviewsClient(http_client)

    # Check which appids we've already fetched to support resume
    already_fetched = read_fetched_appids(conn, run_id, "steam_reviews")
    appids_to_fetch = [aid for aid in appids if aid not in already_fetched]

    on_event(
        stage="acquisition",
        level="info",
        message=f"Reviews resume: {len(already_fetched)} already fetched, {len(appids_to_fetch)} to fetch",
    )

    # Fetch and persist new reviews
    reviews_fetched = 0
    reviews_failed = 0
    requests_made = 0
    payloads_to_persist = []
    batch_size = 500

    for payload in fetch_review_summaries(
        reviews_client, appids_to_fetch, on_event=on_event
    ):
        rate_limiter.acquire()
        requests_made += 1
        rate_limiter.observe_response(payload.http_status, {})

        payloads_to_persist.append(payload)

        # Count successes and failures
        if payload.http_status == 200 and payload.payload.get("success") == 1:
            reviews_fetched += 1
        else:
            reviews_failed += 1

        # Persist in batches
        if len(payloads_to_persist) >= batch_size:
            upsert_raw_payloads(conn, run_id, payloads_to_persist)
            payloads_to_persist = []

    # Persist remaining
    if payloads_to_persist:
        upsert_raw_payloads(conn, run_id, payloads_to_persist)

    return {
        "reviews_fetched": reviews_fetched,
        "reviews_failed": reviews_failed,
        "requests_made": requests_made,
    }


def _fetch_and_persist_steamspy_details(
    conn: sqlite3.Connection,
    run_id: str,
    settings: Settings,
    config: AcquisitionConfig,
    appids: list[int],
    rate_limiter: RateLimiter,
    on_event: EventSink,
) -> dict:
    """Fetch SteamSpy per-app details (source of tags) and persist.

    SteamSpy's bulk 'all' payload has no 'tags' field (see ARCHITECTURE.md's
    Data Sources correction, 2026-09-23); this per-app call is the real tag
    source, mirroring _fetch_and_persist_reviews' own structure.

    Args:
        conn: Database connection.
        run_id: The run ID.
        settings: Environment settings.
        config: Acquisition config (for HttpClient retry/backoff settings).
        appids: List of appids to fetch SteamSpy details for (final survivors).
        rate_limiter: Shared rate limiter.
        on_event: Event sink.

    Returns:
        A dict with:
        - steamspy_details_fetched: count of successful fetches
        - steamspy_details_failed: count of failures
        - requests_made: total requests issued
    """
    http_client = HttpClient(
        settings,
        max_retries=config.max_retries,
        backoff_base_seconds=config.backoff_base_seconds,
        backoff_max_seconds=config.backoff_max_seconds,
    )
    steamspy_client = SteamSpyClient(http_client)

    already_fetched = read_fetched_appids(conn, run_id, "steamspy_appdetails")
    appids_to_fetch = [aid for aid in appids if aid not in already_fetched]

    on_event(
        stage="acquisition",
        level="info",
        message=f"SteamSpy details resume: {len(already_fetched)} already fetched, {len(appids_to_fetch)} to fetch",
    )

    steamspy_details_fetched = 0
    steamspy_details_failed = 0
    requests_made = 0
    payloads_to_persist = []
    batch_size = 500

    for payload in fetch_steamspy_details(
        steamspy_client, appids_to_fetch, on_event=on_event
    ):
        rate_limiter.acquire()
        requests_made += 1
        rate_limiter.observe_response(payload.http_status, {})

        payloads_to_persist.append(payload)

        if payload.http_status == 200:
            steamspy_details_fetched += 1
        else:
            steamspy_details_failed += 1

        if len(payloads_to_persist) >= batch_size:
            upsert_raw_payloads(conn, run_id, payloads_to_persist)
            payloads_to_persist = []

    if payloads_to_persist:
        upsert_raw_payloads(conn, run_id, payloads_to_persist)

    return {
        "steamspy_details_fetched": steamspy_details_fetched,
        "steamspy_details_failed": steamspy_details_failed,
        "requests_made": requests_made,
    }


def _write_funnel_report(
    conn: sqlite3.Connection,
    run_id: str,
    funnel_result: FunnelResult,
    parameters_version: str | None = None,
    *,
    detail_fetched: int = 0,
    detail_failed: int = 0,
) -> None:
    """Write the funnel report to analysis_results.

    Args:
        conn: Database connection.
        run_id: The run ID.
        funnel_result: The FunnelResult to persist.
        detail_fetched: Successful Steam appdetails fetches so far, for the
            "data" sub-object reporting.headline_metrics reads. 0 on the first
            call (before appdetails fetching), the real count on any later
            call for the same run.
        detail_failed: Failed Steam appdetails fetches so far, same timing note.

    Note: "data.simple_subset_size" is deliberately absent here -- it is only
    known once analysis.run_analysis' own simplicity filter has run, which
    merges it into this same stored row afterward rather than this function
    guessing or defaulting it. reporting.headline_metrics treats an absent
    simple_subset_size as 0, not as an error, for a run that hasn't reached
    the analysis stage yet.
    """
    import json

    # Serialize funnel result
    funnel_data = {
        "data": {
            "catalog_size": funnel_result.total_input,
            "candidate_count": len(funnel_result.candidates),
            "detail_fetched": detail_fetched,
            "detail_failed": detail_failed,
        },
        "rejected_by_reason": funnel_result.rejected_by_reason,
        "criteria": {
            "min_review_count": funnel_result.criteria.min_review_count,
            "max_review_count": funnel_result.criteria.max_review_count,
            "earliest_release_date": (
                funnel_result.criteria.earliest_release_date.isoformat()
                if funnel_result.criteria.earliest_release_date
                else None
            ),
            "latest_release_date": (
                funnel_result.criteria.latest_release_date.isoformat()
                if funnel_result.criteria.latest_release_date
                else None
            ),
            "include_free_to_play": funnel_result.criteria.include_free_to_play,
            "max_price_usd": funnel_result.criteria.max_price_usd,
            "publisher_blocklist": funnel_result.criteria.publisher_blocklist,
        },
    }

    write_analysis_result(
        conn, run_id, "funnel_report", funnel_data, parameters_version=parameters_version or ""
    )


def _get_initial_rejection_reasons() -> dict[str, int]:
    """Get the initial rejection reason counts (all zeros).

    Returns:
        A dict with all rejection reasons initialized to 0.
    """
    return {
        "duplicate_appid": 0,
        "missing_required_field": 0,
        "review_count_below_floor": 0,
        "review_count_above_ceiling": 0,
        "free_to_play_excluded": 0,
        "price_above_max": 0,
        "publisher_blocklisted": 0,
        "release_date_outside_window": 0,
    }
