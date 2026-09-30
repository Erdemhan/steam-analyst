"""Raw payload parsing and feature extraction for enrichment stage.

This module converts immutable raw_games table rows into RawBundle grouped
by appid, then flattens the payloads into normalized feature rows and tag
entries.
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

import pandas as pd

from steam_analyst.storage import get_run, read_raw_payloads
from steam_analyst.storage.types import TagRow
from .errors import EnrichmentError


@dataclass(frozen=True)
class RawBundle:
    """Per-appid raw payload groups for one run.

    Attributes:
        run_id: The run these payloads belong to.
        steamspy: appid -> the app's SteamSpy bulk record (from source='steamspy_all').
            Does NOT carry tags -- SteamSpy's bulk 'all' payload has no 'tags' field
            (discovered running the real pipeline; see ARCHITECTURE.md's Data
            Sources correction, 2026-09-23).
        steamspy_appdetails: appid -> the app's SteamSpy per-app detail payload
            (from source='steamspy_appdetails'). This is the real tag source --
            extract_tags reads bundle.steamspy_appdetails[appid]['tags'], not
            bundle.steamspy[appid]['tags']. Keys are the candidate appids only.
        appdetails: appid -> the app's {"success":..., "data":{...}} Steam appdetails
            payload (from source='steam_appdetails'). Keys are the coarse_filter
            survivors that acquisition attempted a detail fetch for -- this is
            fetched BEFORE the release-date filter, so it is a superset of the
            final candidate set. normalize_features must intersect with
            steamspy_appdetails (or an equivalent final-survivor signal) before
            treating an appdetails entry as an in-scope game; see its is_game
            computation.
        reviews: appid -> the app's review-summary payload (from source='steam_reviews').

    An appid present in `steamspy` but absent from `steamspy_appdetails` /
    `appdetails` / `reviews` means that per-app fetch failed or was never attempted.
    An appid present in `appdetails` but absent from `steamspy_appdetails` means it
    was fetched as a coarse-filter candidate but rejected by the release-date
    filter (or steamspy_appdetails itself failed) before the final survivor set
    was established.
    """
    run_id: str
    steamspy: dict[int, dict]
    steamspy_appdetails: dict[int, dict]
    appdetails: dict[int, dict]
    reviews: dict[int, dict]


def parse_raw_bundle(conn: sqlite3.Connection, run_id: str) -> RawBundle:
    """Load and group a run's raw payloads.

    Args:
        conn: An open storage connection.
        run_id: The run to load.

    Returns:
        A RawBundle with steamspy, appdetails and reviews dicts populated from
        storage.read_raw_payloads for the three relevant source values.

    Raises:
        EnrichmentError: If run_id does not exist.
    """
    # Check that run_id exists
    run = get_run(conn, run_id)
    if run is None:
        raise EnrichmentError(f"Run {run_id} does not exist")

    steamspy = {}
    steamspy_appdetails = {}
    appdetails = {}
    reviews = {}

    # Stream steamspy_all payloads
    for payload in read_raw_payloads(conn, run_id, "steamspy_all"):
        steamspy[payload.appid] = payload.payload

    # Stream steamspy_appdetails payloads (the real tag source; steamspy_all
    # itself has no 'tags' field). SteamSpy's per-app endpoint returns the
    # record flat, not nested under the appid again, so no unwrap needed here.
    for payload in read_raw_payloads(conn, run_id, "steamspy_appdetails"):
        steamspy_appdetails[payload.appid] = payload.payload

    # Stream steam_appdetails payloads. Steam's real appdetails response
    # nests the {"success": ..., "data": ...} body one level down, keyed by
    # the app id AGAIN as a string: {"<appid>": {"success": ..., "data": ...}}.
    # Unwrap that here so every downstream consumer of bundle.appdetails[appid]
    # gets the clean {"success", "data"} dict directly.
    for payload in read_raw_payloads(conn, run_id, "steam_appdetails"):
        raw = payload.payload
        if isinstance(raw, dict) and str(payload.appid) in raw:
            appdetails[payload.appid] = raw[str(payload.appid)]
        else:
            appdetails[payload.appid] = raw

    # Stream steam_reviews payloads
    for payload in read_raw_payloads(conn, run_id, "steam_reviews"):
        reviews[payload.appid] = payload.payload

    return RawBundle(
        run_id=run_id,
        steamspy=steamspy,
        steamspy_appdetails=steamspy_appdetails,
        appdetails=appdetails,
        reviews=reviews,
    )


def normalize_features(bundle: RawBundle) -> pd.DataFrame:
    """Build the base feature frame from raw payloads.

    Args:
        bundle: Output of parse_raw_bundle.

    Returns:
        A DataFrame indexed by appid with columns for identity, price, review counts,
        owners band, size, achievement/language/platform/DLC counts, early-access
        fields, deck compatibility, genres, categories, and missing_fields_json.

    The DataFrame includes one row per appid in bundle.steamspy, preserving
    structure for density/competition analysis even if per-app details failed.
    """
    rows = []

    for appid in bundle.steamspy:
        steamspy_data = bundle.steamspy[appid]
        appdetails_payload = bundle.appdetails.get(appid, {})
        reviews_payload = bundle.reviews.get(appid, {})

        # Extract from appdetails
        appdetails_success = appdetails_payload.get("success", False) if appdetails_payload else False
        appdetails_data = appdetails_payload.get("data", {}) if appdetails_payload else {}

        # Build missing fields list
        missing_fields = []

        # Basic identity fields from appdetails
        name = appdetails_data.get("name") or steamspy_data.get("name")
        developer = appdetails_data.get("developers", [None])[0] if appdetails_data.get("developers") else steamspy_data.get("developer")
        publisher = appdetails_data.get("publishers", [None])[0] if appdetails_data.get("publishers") else steamspy_data.get("publisher")
        app_type = appdetails_data.get("type")
        # bundle.appdetails holds every appid acquisition fetched Steam appdetails
        # for, which is the PRE-release-date-filter candidate set (coarse_filter
        # survivors), not the final survivor set. bundle.steamspy_appdetails is
        # populated only for the final survivor set (Step 7 in
        # acquisition/pipeline.py runs after the release-date filter), so it is
        # the authoritative scope check here -- without it, appids rejected by
        # the release-date filter would still be scored and analyzed as valid
        # candidates.
        is_final_survivor = appid in bundle.steamspy_appdetails
        is_game = (app_type == "game" and is_final_survivor) if appdetails_success else False

        # Price fields
        price_overview = appdetails_data.get("price_overview", {}) if appdetails_success else {}
        price_usd = None
        is_free = None

        if appdetails_success:
            if price_overview:
                # Price is in cents in the API
                price_cents = price_overview.get("final")
                if price_cents is not None:
                    price_usd = price_cents / 100.0
            is_free = appdetails_data.get("is_free", False)

        if price_usd is None and not is_game:
            missing_fields.append("price_usd")

        # Review count: prefer Steam reviews, fallback to SteamSpy
        review_count = None
        review_count_source = None

        if reviews_payload and reviews_payload.get("success"):
            query_summary = reviews_payload.get("query_summary", {})
            review_count = query_summary.get("total_reviews")
            if review_count is not None:
                review_count_source = "steam_reviews"

        if review_count is None:
            # Fallback to SteamSpy positive + negative
            positive = steamspy_data.get("positive", 0)
            negative = steamspy_data.get("negative", 0)
            if positive or negative:
                review_count = positive + negative
                review_count_source = "steamspy_fallback"
            else:
                review_count_source = "steamspy_fallback"

        # Review positive percentage
        review_positive_pct = None
        if reviews_payload and reviews_payload.get("success"):
            query_summary = reviews_payload.get("query_summary", {})
            # review_score is Steam's 1-9 categorical rating, not a percentage.
            total_positive = query_summary.get("total_positive")
            total_reviews = query_summary.get("total_reviews")
            if (
                isinstance(total_positive, (int, float))
                and isinstance(total_reviews, (int, float))
                and total_reviews > 0
            ):
                review_positive_pct = total_positive / total_reviews

        # Owners band from SteamSpy
        owners_estimate_low = steamspy_data.get("owners_low")
        owners_estimate_mid = None  # Not provided by SteamSpy
        owners_estimate_high = steamspy_data.get("owners_high")

        # Size and achievement counts from appdetails
        size_bytes = None
        if appdetails_success:
            size = appdetails_data.get("size_bytes")
            if size is not None:
                try:
                    size_bytes = int(size)
                    if size_bytes < 0:
                        size_bytes = None
                        missing_fields.append("size_bytes")
                except (ValueError, TypeError):
                    missing_fields.append("size_bytes")
            else:
                missing_fields.append("size_bytes")

        achievement_count = None
        if appdetails_success:
            achievements = appdetails_data.get("achievements", {})
            if achievements and isinstance(achievements, dict):
                total = achievements.get("total")
                if total is not None:
                    try:
                        achievement_count = int(total)
                        if achievement_count < 0:
                            achievement_count = None
                            missing_fields.append("achievement_count")
                    except (ValueError, TypeError):
                        missing_fields.append("achievement_count")
            else:
                missing_fields.append("achievement_count")

        # Language count
        language_count = None
        if appdetails_success:
            languages = appdetails_data.get("supported_languages", "")
            if languages:
                # Count <strong>*</strong> tags and comma separators
                language_count = len([l.strip() for l in languages.replace("<strong>*</strong>", "").split(",") if l.strip()])
                if language_count <= 0:
                    language_count = None
                    missing_fields.append("language_count")
            else:
                missing_fields.append("language_count")

        # Platform count
        platform_count = None
        if appdetails_success:
            platforms = appdetails_data.get("platforms", {})
            if platforms and isinstance(platforms, dict):
                platform_count = sum(1 for v in platforms.values() if v)
                if platform_count <= 0:
                    platform_count = None
                    missing_fields.append("platform_count")
            else:
                missing_fields.append("platform_count")

        # DLC count
        dlc_count = None
        if appdetails_success:
            dlc = appdetails_data.get("dlc", [])
            if dlc and isinstance(dlc, list):
                dlc_count = len(dlc)
            else:
                dlc_count = 0

        # Early access
        is_early_access = None
        early_access_days = None
        if appdetails_success:
            is_early_access = appdetails_data.get("is_early_access", False)

        # Deck compatibility (SteamDeck)
        deck_compat = None
        if appdetails_success:
            steam_deck = appdetails_data.get("steam_deck_compat", {})
            if steam_deck and isinstance(steam_deck, dict):
                deck_compat = steam_deck.get("compat_category")

        # Release date
        release_date = None
        release_date_parsed = None
        if appdetails_success:
            release = appdetails_data.get("release_date", {})
            if release and isinstance(release, dict):
                release_date = release.get("date")

        # Genres and categories as JSON
        genres_json = "[]"
        if appdetails_success:
            genres = appdetails_data.get("genres", [])
            if genres and isinstance(genres, list):
                genre_strs = [g.get("description", "") for g in genres if isinstance(g, dict)]
                genres_json = json.dumps(genre_strs)

        categories_json = "[]"
        if appdetails_success:
            categories = appdetails_data.get("categories", [])
            if categories and isinstance(categories, list):
                category_strs = [c.get("description", "") for c in categories if isinstance(c, dict)]
                categories_json = json.dumps(category_strs)

        rows.append({
            "appid": int(appid),
            "name": name,
            "developer": developer,
            "publisher": publisher,
            "app_type": app_type,
            "is_game": is_game,
            "price_usd": price_usd,
            "is_free": is_free,
            "review_count": review_count,
            "review_count_source": review_count_source,
            "review_positive_pct": review_positive_pct,
            "owners_estimate_low": owners_estimate_low,
            "owners_estimate_mid": owners_estimate_mid,
            "owners_estimate_high": owners_estimate_high,
            "size_bytes": size_bytes,
            "achievement_count": achievement_count,
            "language_count": language_count,
            "platform_count": platform_count,
            "dlc_count": dlc_count,
            "is_early_access": is_early_access,
            "early_access_days": early_access_days,
            "deck_compat": deck_compat,
            "release_date": release_date,
            "release_date_parsed": release_date_parsed,
            "genres_json": genres_json,
            "categories_json": categories_json,
            "missing_fields_json": json.dumps(missing_fields),
        })

    df = pd.DataFrame(rows)
    if len(df) > 0:
        df = df.set_index("appid")

    return df


def extract_tags(bundle: RawBundle, *, max_tags_per_game: int, min_votes: int) -> list[TagRow]:
    """Extract tag rows from bundle.steamspy_appdetails' 'tags' field.

    NOTE: reads bundle.steamspy_appdetails, NOT bundle.steamspy -- SteamSpy's
    bulk 'all' payload (bundle.steamspy) has no 'tags' field at all (discovered
    running the real pipeline; see ARCHITECTURE.md's Data Sources correction,
    2026-09-23). Tags only exist in the per-app SteamSpy detail payload.

    Args:
        bundle: Output of parse_raw_bundle.
        max_tags_per_game: Cap on tags retained per app.
        min_votes: Tags with votes below this are dropped entirely.

    Returns:
        A list of TagRow(appid, tag, votes, rank), rank being the 1-based position
        within that app's tags after sorting by votes descending (ties broken
        alphabetically by tag name).
    """
    result = []

    for appid in sorted(bundle.steamspy_appdetails.keys()):
        steamspy_data = bundle.steamspy_appdetails[appid]
        tags_raw = steamspy_data.get("tags", {})

        # Handle case where tags is an empty list
        if isinstance(tags_raw, list):
            tags_dict = {}
        elif isinstance(tags_raw, dict):
            tags_dict = tags_raw
        else:
            tags_dict = {}

        # Filter by min_votes and sort by votes descending, then alphabetically
        filtered_tags = [
            (tag, votes)
            for tag, votes in tags_dict.items()
            if votes >= min_votes
        ]

        # Sort: first by votes descending, then by tag name alphabetically
        filtered_tags.sort(key=lambda x: (-x[1], x[0]))

        # Keep only top max_tags_per_game
        filtered_tags = filtered_tags[:max_tags_per_game]

        # Create TagRow entries
        for rank, (tag, votes) in enumerate(filtered_tags, start=1):
            result.append(TagRow(
                appid=int(appid),
                tag=tag,
                votes=votes,
                rank=rank,
            ))

    return result
