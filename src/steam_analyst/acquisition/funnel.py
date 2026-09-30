"""Acquisition stage funnel: catalog fetching, coarse filtering, per-app detail fetching."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Sequence

import pandas as pd

from steam_analyst.acquisition.errors import AcquisitionError, RequestBudgetExceeded
from steam_analyst.acquisition.steam_reviews_client import SteamReviewsClient
from steam_analyst.acquisition.steam_store_client import SteamStoreClient
from steam_analyst.acquisition.steamspy_client import SteamSpyClient
from steam_analyst.config import CoarseFilterCriteria
from steam_analyst.storage import EventSink, RawPayload


@dataclass(frozen=True)
class FunnelResult:
    """Outcome of one coarse_filter application.

    Attributes:
        candidates: Surviving rows, same columns as the input catalog frame.
        total_input: Row count of the catalog frame before filtering.
        rejected_by_reason: Maps each rejection reason string to a count; keys always
            present for every reason in the acquisition module's rejection-reason
            vocabulary, value 0 if that reason excluded nothing.
        criteria: The exact CoarseFilterCriteria applied, retained for the funnel_report
            analysis_results entry so a past run's exact band is reconstructable without
            re-reading parameters.toml.
    """

    candidates: pd.DataFrame
    total_input: int
    rejected_by_reason: dict[str, int]
    criteria: CoarseFilterCriteria


@dataclass(frozen=True)
class AcquisitionReport:
    """Summary object returned by run_acquisition.

    Attributes:
        run_id: The run this report belongs to.
        catalog_size: Total apps seen in the SteamSpy bulk catalog (FunnelResult.total_input).
        candidate_count: Survivors of coarse_filter (len(FunnelResult.candidates)).
        detail_fetched: appdetails fetches that returned success=true.
        detail_failed: appdetails fetches that returned success=false or a transport error.
        reviews_fetched: review-summary fetches that succeeded.
        reviews_failed: review-summary fetches that failed.
        requests_made: Total HTTP requests issued across all three sources (bulk pages +
            per-app details + per-app reviews).
        duration_seconds: Wall-clock time for the whole stage.
        funnel: The FunnelResult from coarse_filter.
    """

    run_id: str
    catalog_size: int
    candidate_count: int
    detail_fetched: int
    detail_failed: int
    reviews_fetched: int
    reviews_failed: int
    requests_made: int
    duration_seconds: float
    funnel: FunnelResult


def build_catalog_frame(payloads: Iterable[RawPayload]) -> pd.DataFrame:
    """Flatten bulk SteamSpy payloads into a catalog DataFrame.

    Args:
        payloads: RawPayload objects with source='steamspy_all', each representing one app.
            Typically from fetch_steamspy_catalog after persistence, or read back via
            storage.read_raw_payloads for a re-run of the coarse filter alone.

    Returns:
        A DataFrame with columns: appid, name, developer, publisher, positive, negative,
        owners_low, owners_high, price_usd, initialprice, discount, tags. One row per
        unique appid; if the same appid appears in more than one input payload (duplicate
        across pages), the later one in iteration order wins. The duplicate_appid count
        is stored as a DataFrame attribute ('_duplicate_appid_count').

    Postconditions:
        - appid column has no duplicate values in the output
        - price_usd and initialprice are floats in dollars (SteamSpy reports price in
          cents; this function divides by 100)
    """

    rows = []
    duplicate_count = 0
    seen_appids = set()

    for raw_payload in payloads:
        # Each RawPayload represents one app from steamspy_all
        appid = raw_payload.appid
        app_data = raw_payload.payload

        # Track duplicates: if we've seen this appid before, increment counter
        if appid in seen_appids:
            duplicate_count += 1
        seen_appids.add(appid)

        # Convert price from cents to dollars
        price_raw = app_data.get("price", 0)
        try:
            price_cents = float(price_raw) if price_raw is not None else 0.0
            price_usd = price_cents / 100.0
        except (ValueError, TypeError):
            price_usd = 0.0

        initialprice_raw = app_data.get("initialprice", 0)
        try:
            initialprice_cents = (
                float(initialprice_raw) if initialprice_raw is not None else 0.0
            )
            initialprice_usd = initialprice_cents / 100.0
        except (ValueError, TypeError):
            initialprice_usd = 0.0

        row = {
            "appid": appid,
            "name": app_data.get("name", ""),
            "developer": app_data.get("developer", ""),
            "publisher": app_data.get("publisher", ""),
            "positive": app_data.get("positive", 0),
            "negative": app_data.get("negative", 0),
            "owners_low": app_data.get("owners_low", 0),
            "owners_high": app_data.get("owners_high", 0),
            "price_usd": price_usd,
            "initialprice": initialprice_usd,
            "discount": app_data.get("discount", 0),
            "tags": app_data.get("tags", {}),
        }
        rows.append(row)

    # Create DataFrame, then deduplicate by appid (keeping the last occurrence)
    if rows:
        df = pd.DataFrame(rows)
        # Drop duplicates, keeping the last occurrence
        df = df.drop_duplicates(subset=["appid"], keep="last").reset_index(drop=True)
    else:
        # Empty DataFrame with the expected columns
        df = pd.DataFrame(
            columns=[
                "appid",
                "name",
                "developer",
                "publisher",
                "positive",
                "negative",
                "owners_low",
                "owners_high",
                "price_usd",
                "initialprice",
                "discount",
                "tags",
            ]
        )

    # Store duplicate count as a DataFrame attribute for caller's use
    df.attrs["_duplicate_appid_count"] = duplicate_count

    return df


def coarse_filter(catalog: pd.DataFrame, criteria: CoarseFilterCriteria) -> FunnelResult:
    """Apply the stage-one candidate band to the flattened catalog frame.

    Args:
        catalog: Output of build_catalog_frame.
        criteria: The band to apply (config.CoarseFilterCriteria), including
            publisher_blocklist.

    Returns:
        FunnelResult(candidates=<survivors>, total_input=len(catalog),
        rejected_by_reason=<dict>, criteria=criteria).

    The rejection order (a row is counted under the FIRST reason it fails):
    1. duplicate_appid (already resolved upstream in build_catalog_frame, tallied here
       via the _duplicate_appid_count attribute)
    2. missing_required_field (no appid or appid is null)
    3. review_count_below_floor
    4. review_count_above_ceiling (only when criteria.max_review_count is not None)
    5. free_to_play_excluded (only when criteria.include_free_to_play is False)
    6. price_above_max
    7. publisher_blocklisted (case-insensitive substring match)

    Note: release_date_outside_window is not checked here because SteamSpy's bulk
    payload does not reliably carry release dates. This check is deferred to after
    appdetails is fetched.
    """
    # Initialize rejection tallies with all known reasons, defaulting to 0
    rejection_reasons = [
        "duplicate_appid",
        "missing_required_field",
        "review_count_below_floor",
        "review_count_above_ceiling",
        "free_to_play_excluded",
        "price_above_max",
        "publisher_blocklisted",
    ]
    rejected_by_reason = {reason: 0 for reason in rejection_reasons}

    # Tally duplicates from build_catalog_frame's duplicate tracking
    rejected_by_reason["duplicate_appid"] = catalog.attrs.get("_duplicate_appid_count", 0)

    candidates = []

    for _, row in catalog.iterrows():
        # missing_required_field: no appid
        if pd.isna(row.get("appid")) or row.get("appid") is None:
            rejected_by_reason["missing_required_field"] += 1
            continue

        # Calculate review count
        positive = row.get("positive", 0) or 0
        negative = row.get("negative", 0) or 0
        review_count = positive + negative

        # review_count_below_floor
        if review_count < criteria.min_review_count:
            rejected_by_reason["review_count_below_floor"] += 1
            continue

        # review_count_above_ceiling (only if ceiling is set)
        if (
            criteria.max_review_count is not None
            and review_count > criteria.max_review_count
        ):
            rejected_by_reason["review_count_above_ceiling"] += 1
            continue

        # free_to_play_excluded (only if not including free-to-play)
        price_usd = row.get("price_usd", 0)
        if not criteria.include_free_to_play and price_usd == 0:
            rejected_by_reason["free_to_play_excluded"] += 1
            continue

        # price_above_max (only if max is set)
        if criteria.max_price_usd is not None and price_usd > criteria.max_price_usd:
            rejected_by_reason["price_above_max"] += 1
            continue

        # publisher_blocklisted (case-insensitive substring match)
        publisher = row.get("publisher", "") or ""
        # SteamSpy occasionally returns a non-string (e.g. an empty dict/list)
        # for this field on malformed catalog entries; treat anything that
        # isn't a real string as "no publisher info" rather than crashing the
        # whole acquisition stage over one malformed row.
        if not isinstance(publisher, str):
            publisher = ""
        is_blocklisted = False
        for blocklist_entry in criteria.publisher_blocklist:
            if blocklist_entry.lower() in publisher.lower():
                is_blocklisted = True
                break

        if is_blocklisted:
            rejected_by_reason["publisher_blocklisted"] += 1
            continue

        # Row survived all filters
        candidates.append(row)

    # Build candidates DataFrame from survivors
    if candidates:
        candidates_df = pd.DataFrame(candidates).reset_index(drop=True)
    else:
        candidates_df = catalog.iloc[:0].copy()

    return FunnelResult(
        candidates=candidates_df,
        total_input=len(catalog),
        rejected_by_reason=rejected_by_reason,
        criteria=criteria,
    )


def fetch_steamspy_catalog(
    client: SteamSpyClient, *, max_pages: int | None = None, on_event: EventSink
) -> Iterator[RawPayload]:
    """Stream the whole SteamSpy bulk catalog page by page.

    Args:
        client: A SteamSpyClient.
        max_pages: Optional cap on pages fetched, primarily for tests; None means fetch
            until pagination naturally stops.
        on_event: Progress/log sink; emits one 'fetch_page' event per page and a
            'warning' event if pagination stops due to an empty or repeated page.

    Yields:
        One RawPayload(source='steamspy_all', ...) per app encountered, in page order.

    Raises:
        AcquisitionError: If a page fetch returns a non-2xx status code persistently.

    Stops when:
        - A page returns an empty dict
        - A page's app-id set is identical to the immediately preceding page's
        - max_pages limit is reached (if specified)
    """
    page = 0
    previous_appids = set()

    while True:
        # Check max_pages limit
        if max_pages is not None and page >= max_pages:
            break

        # Fetch the page (caller is responsible for acquire() call)
        try:
            status_code, page_payload = client.fetch_all_page(page)
        except Exception as e:
            raise AcquisitionError(f"Failed to fetch SteamSpy catalog page {page}: {e}")

        # Check for successful HTTP response
        if status_code != 200:
            raise AcquisitionError(
                f"SteamSpy page {page} returned status {status_code}"
            )

        # Emit progress event
        on_event(stage="acquisition", level="info", message=f"Fetched SteamSpy page {page}")

        # Check for empty page (end of catalog)
        if not page_payload:
            on_event(
                stage="acquisition",
                level="warning",
                message=f"SteamSpy catalog ended with empty page at page {page}",
            )
            break

        # Check for repeated page (same appids as previous page)
        current_appids = set(page_payload.keys())
        if current_appids == previous_appids:
            on_event(
                stage="acquisition",
                level="warning",
                message=f"SteamSpy page {page} repeated the previous page's appids, stopping pagination",
            )
            break

        previous_appids = current_appids

        # Yield one RawPayload per app in this page
        fetched_at = datetime.utcnow()

        for appid_str, app_data in page_payload.items():
            try:
                appid = int(appid_str)
            except (ValueError, TypeError):
                continue

            # Create a RawPayload with individual app data
            import hashlib
            import json

            payload_json = json.dumps(app_data, sort_keys=True).encode("utf-8")
            payload_sha256 = hashlib.sha256(payload_json).hexdigest()

            yield RawPayload(
                appid=appid,
                source="steamspy_all",
                fetched_at=fetched_at,
                http_status=status_code,
                payload=app_data,
                payload_sha256=payload_sha256,
            )

        page += 1


def fetch_app_details(
    client: SteamStoreClient, appids: Sequence[int], *, on_event: EventSink
) -> Iterator[RawPayload]:
    """Fetch appdetails for every candidate appid.

    Args:
        client: A SteamStoreClient wrapping a RateLimiter-guarded HttpClient.
        appids: FunnelResult.candidates['appid'].tolist(), the survivors of coarse_filter.
        on_event: Progress sink; emits a 'fetch_progress' event roughly every N appids
            and a 'warning' event for each individual failed appid.

    Yields:
        One RawPayload(source='steam_appdetails', appid=..., http_status=..., payload=...)
        per appid attempted, including failures.

    Raises:
        RequestBudgetExceeded: If the rate limiter budget is exhausted.

    Note: A failed per-app fetch does not raise; it yields a RawPayload with the error
    payload and continues.
    """
    import hashlib
    import json

    if not appids:
        on_event(
            stage="acquisition",
            level="warning",
            message="No candidate appids to fetch; empty appdetails stage",
        )
        return

    appids_list = list(appids)
    fetched_at = datetime.utcnow()

    for i, appid in enumerate(appids_list):
        # Emit progress periodically
        if i > 0 and i % max(1, len(appids_list) // 10) == 0:
            progress = i / len(appids_list)
            on_event(
                stage="acquisition",
                level="info",
                message=f"Fetched appdetails for {i}/{len(appids_list)} apps",
                progress=progress,
            )

        try:
            status_code, payload = client.fetch_app_details(appid)
        except RequestBudgetExceeded:
            raise
        except Exception as e:
            # Transport error: create error payload
            payload = {
                "_raw_text": str(e),
                "_parse_error": True,
                "_transport_error": type(e).__name__,
            }
            status_code = 0

        # Check if this is a success=false response (a valid Steam response indicating
        # the app doesn't exist or failed to fetch)
        is_steam_failure = (
            isinstance(payload, dict)
            and appid in payload
            and isinstance(payload[appid], dict)
            and payload[appid].get("success") is False
        )

        if is_steam_failure or status_code != 200:
            on_event(
                stage="acquisition",
                level="warning",
                message=f"Failed to fetch appdetails for appid {appid}: status {status_code}",
            )

        payload_json = json.dumps(payload, sort_keys=True).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload_json).hexdigest()

        yield RawPayload(
            appid=appid,
            source="steam_appdetails",
            fetched_at=fetched_at,
            http_status=status_code,
            payload=payload,
            payload_sha256=payload_sha256,
        )

    on_event(
        stage="acquisition",
        level="info",
        message=f"Completed appdetails fetch for {len(appids_list)} apps",
        progress=1.0,
    )


def fetch_steamspy_details(
    client: SteamSpyClient, appids: Sequence[int], *, on_event: EventSink
) -> Iterator[RawPayload]:
    """Fetch SteamSpy's per-app detail endpoint for every candidate appid.

    Sources tags: SteamSpy's bulk 'all' payload does not carry a 'tags' field
    (discovered running the real pipeline, see ARCHITECTURE.md's Data Sources
    correction, 2026-09-23) -- this per-app call is what actually provides them.

    Args:
        client: A SteamSpyClient wrapping a RateLimiter-guarded HttpClient.
        appids: The final survivor set (post coarse_filter and release-date filter).
        on_event: Progress sink; emits a progress event roughly every 10% of appids
            and a 'warning' event for each individual failed appid.

    Yields:
        One RawPayload(source='steamspy_appdetails', appid=..., http_status=...,
        payload=...) per appid attempted, including failures.

    Note: A failed per-app fetch does not raise; it yields a RawPayload with the
    error payload and continues, matching fetch_app_details' own contract.
    """
    import hashlib
    import json

    if not appids:
        on_event(
            stage="acquisition",
            level="warning",
            message="No candidate appids to fetch; empty SteamSpy details stage",
        )
        return

    appids_list = list(appids)
    fetched_at = datetime.utcnow()

    for i, appid in enumerate(appids_list):
        if i > 0 and i % max(1, len(appids_list) // 10) == 0:
            progress = i / len(appids_list)
            on_event(
                stage="acquisition",
                level="info",
                message=f"Fetched SteamSpy details for {i}/{len(appids_list)} apps",
                progress=progress,
            )

        try:
            status_code, payload = client.fetch_app(appid)
        except RequestBudgetExceeded:
            raise
        except Exception as e:
            payload = {
                "_raw_text": str(e),
                "_parse_error": True,
                "_transport_error": type(e).__name__,
            }
            status_code = 0

        if status_code != 200:
            on_event(
                stage="acquisition",
                level="warning",
                message=f"Failed to fetch SteamSpy details for appid {appid}: status {status_code}",
            )

        payload_json = json.dumps(payload, sort_keys=True).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload_json).hexdigest()

        yield RawPayload(
            appid=appid,
            source="steamspy_appdetails",
            fetched_at=fetched_at,
            http_status=status_code,
            payload=payload,
            payload_sha256=payload_sha256,
        )

    on_event(
        stage="acquisition",
        level="info",
        message=f"Completed SteamSpy details fetch for {len(appids_list)} apps",
        progress=1.0,
    )


def fetch_review_summaries(
    client: SteamReviewsClient, appids: Sequence[int], *, on_event: EventSink
) -> Iterator[RawPayload]:
    """Fetch review summaries for every candidate appid.

    Args:
        client: A SteamReviewsClient.
        appids: The candidate appids (typically the same list passed to fetch_app_details).
        on_event: Progress sink, same event conventions as fetch_app_details.

    Yields:
        One RawPayload(source='steam_reviews', ...) per appid attempted, including failures.

    Raises:
        RequestBudgetExceeded: If the rate limiter budget is exhausted.
    """
    import hashlib
    import json

    if not appids:
        on_event(
            stage="acquisition",
            level="warning",
            message="No candidate appids to fetch; empty review-summary stage",
        )
        return

    appids_list = list(appids)
    fetched_at = datetime.utcnow()

    for i, appid in enumerate(appids_list):
        # Emit progress periodically
        if i > 0 and i % max(1, len(appids_list) // 10) == 0:
            progress = i / len(appids_list)
            on_event(
                stage="acquisition",
                level="info",
                message=f"Fetched review summaries for {i}/{len(appids_list)} apps",
                progress=progress,
            )

        try:
            status_code, payload = client.fetch_review_summary(appid)
        except RequestBudgetExceeded:
            raise
        except Exception as e:
            # Transport error
            payload = {
                "_raw_text": str(e),
                "_parse_error": True,
                "_transport_error": type(e).__name__,
            }
            status_code = 0

        # Check for failure
        if (
            isinstance(payload, dict)
            and (payload.get("success") == 0 or "_parse_error" in payload)
        ) or status_code != 200:
            on_event(
                stage="acquisition",
                level="warning",
                message=f"Failed to fetch review summary for appid {appid}: status {status_code}",
            )

        payload_json = json.dumps(payload, sort_keys=True).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload_json).hexdigest()

        yield RawPayload(
            appid=appid,
            source="steam_reviews",
            fetched_at=fetched_at,
            http_status=status_code,
            payload=payload,
            payload_sha256=payload_sha256,
        )

    on_event(
        stage="acquisition",
        level="info",
        message=f"Completed review summary fetch for {len(appids_list)} apps",
        progress=1.0,
    )
