"""
Case study selection and rationale building for the reporting layer.

This module produces the ranked list of case studies shown to the user and the
interpretive caveats that frame how to read them. All functions are pure,
relying only on stored data and fixed templates—no network calls or external
state.

Core responsibilities:
- CaseStudy: A dataclass for one case-study entry (a specific game).
- build_rationale: Template-filled sentence named by concrete signals.
- interpretive_caveats: Fixed caveat list mirroring ARCHITECTURE.md limitations.
- select_case_studies: Rank by effort_adjusted_return, enforce diversity caps.
"""

import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from steam_analyst.reporting.types import Caveat, CaseStudySelection


@dataclass(frozen=True)
class CaseStudy:
    """One case-study entry: a specific game presented as a plausibly-small-scope, commercially-notable example.

    Attributes:
        appid: Steam application ID.
        name: Game title.
        developer: Developer name (from games_enriched.developer).
        release_date: Release date string (ISO 8601 or similar, from games_enriched).
        price_usd: Current list price in USD.
        review_count: Total review count from Steam reviews API.
        review_positive_pct: Positive review percentage in [0, 1].
        estimated_sales_band: Tuple (low, mid, high) from Boxleiter estimation.
            Must be non-decreasing: band[0] <= band[1] <= band[2].
        estimated_revenue_net_usd: Estimated net revenue (after storefront cut).
            May be NaN for free-to-play titles; the UI renders NaN as 'unknown',
            never as $0.
        complexity_score: The game's own score in [0, 1].
        top_tags: Top few tags by vote from game_tags (fewer than 3 is valid).
        archetype_label: Cluster label for this game's assigned tag cluster.
        rationale: build_rationale's output for this row.
        complexity_drivers: Per-feature complexity contributions as [(feature_name, weight), ...]
            e.g. [('install_size', 0.15), ('achievement_count', 0.08)].
        store_url: Direct link to store page, f'https://store.steampowered.com/app/{appid}/'.
    """

    appid: int
    name: str
    developer: str
    release_date: str
    price_usd: float
    review_count: int
    review_positive_pct: float
    estimated_sales_band: tuple[float, float, float]
    estimated_revenue_net_usd: float
    complexity_score: float
    top_tags: list[str]
    archetype_label: str
    rationale: str
    complexity_drivers: list[tuple[str, float]]
    store_url: str


def build_rationale(row: pd.Series, archetype_label: str) -> str:
    """Build one case study's rationale sentence from concrete stored signals.

    Assembles a single sentence naming the concrete signals that put a game on the
    case-study list: review volume, positivity, price, install size, achievement
    count, and developer catalog size. Uses fixed templates and hedged wording only
    (e.g. 'plausibly small in scope', 'appears compact', 'signals suggest') — never
    unhedged development-time or cost claims like 'took two weeks to build'.

    Args:
        row: A single games_enriched row (as a Series) for the case study's appid.
        archetype_label: The game's assigned cluster's label.

    Returns:
        A single sentence assembled from a fixed template, never more than one
        sentence, containing only numeric values read directly from row.

    Edge cases handled:
        - dev_title_count is NaN: that clause is omitted entirely.
        - price_usd == 0: renders 'free-to-play' instead of '$0.00'.
        - review_positive_pct is NaN: the positivity parenthetical is omitted.
    """
    review_count = int(row["review_count"])
    price_usd = row["price_usd"]
    size_bytes = row.get("size_bytes", float("nan"))
    dev_title_count = row.get("dev_title_count", float("nan"))
    review_positive_pct = row.get("review_positive_pct", float("nan"))

    # Format price clause
    if price_usd == 0:
        price_clause = "free-to-play"
    else:
        price_clause = f"${price_usd:.2f}"

    # Format review clause with optional positivity
    if pd.isna(review_positive_pct):
        review_clause = f"With {review_count:,} reviews"
    else:
        positive_pct = review_positive_pct * 100
        review_clause = f"With {review_count:,} reviews ({positive_pct:.0f}% positive)"

    # Format size clause
    size_clause_parts = []
    if not pd.isna(size_bytes):
        if size_bytes >= 1e9:
            size_str = f"{size_bytes / 1e9:.1f}GB"
        else:
            size_str = f"{size_bytes / 1e6:.0f}MB"
        size_clause_parts.append(f"{size_str} install size")

    # Format developer clause
    developer_clause_parts = []
    if not pd.isna(dev_title_count):
        if dev_title_count == 1:
            developer_clause_parts.append("single prior release")
        else:
            developer_clause_parts.append(f"{int(dev_title_count)} prior releases")

    # Assemble the sentence
    parts = [
        review_clause,
        f"({price_clause})",
        f"at {archetype_label}",
    ]

    if size_clause_parts:
        parts.extend(size_clause_parts)

    if developer_clause_parts:
        parts.extend(developer_clause_parts)

    parts.append("suggest a plausibly small development scope.")

    # Join into one sentence (no line breaks)
    sentence = " ".join(parts)
    return sentence


def interpretive_caveats() -> list[Caveat]:
    """Return the fixed, run-independent caveat list.

    Produces exactly 8 Caveat entries: seven from ARCHITECTURE.md 'Known Limitations'
    items 1-7, plus one additional entry from FORMULATION.md section 2 documenting
    the Boxleiter accuracy limit.

    Returns:
        A list of exactly 8 Caveat entries with stable, unique keys across calls
        and code versions. The caveats cover:
        1. steamspy_owner_confidence (ARCHITECTURE.md limitation 1)
        2. boxleiter_approximation (ARCHITECTURE.md limitation 2)
        3. simplicity_proxy (ARCHITECTURE.md limitation 3)
        4. no_scraping_demand_gap (ARCHITECTURE.md limitation 4)
        5. survivorship_bias (ARCHITECTURE.md limitation 5)
        6. competition_historical (ARCHITECTURE.md limitation 6)
        7. coarse_filter_boundary (ARCHITECTURE.md limitation 7)
        8. boxleiter_accuracy_limit (FORMULATION.md §2 accuracy note)

    Takes no arguments and touches no database — this is a fixed code-authored
    list suitable for headless testing.
    """
    return [
        Caveat(
            key="steamspy_owner_confidence",
            title="SteamSpy Owner Estimates",
            body=(
                "SteamSpy owner estimates are low-confidence approximations. "
                "Valve restricted the underlying profile data in 2018; SteamSpy's owner "
                "figures have since been model-based. Treat them as a rough ordinal signal "
                "and never as ground truth."
            ),
            severity="info",
        ),
        Caveat(
            key="boxleiter_approximation",
            title="Boxleiter Sales Multiplier",
            body=(
                "The Boxleiter multiplier is an approximation. The review-to-sales ratio "
                "varies by genre, price point, release year, regional mix and review-prompt "
                "behaviour. The per-genre range used here is a documented assumption, not a "
                "verified conversion rate. Revenue figures are order-of-magnitude indicators."
            ),
            severity="info",
        ),
        Caveat(
            key="simplicity_proxy",
            title="Complexity is a Proxy for Scope",
            body=(
                "'Simple' is a proxy for scope, not for effort. Metadata cannot see art "
                "quality, game-feel iteration, marketing spend or how many prototypes preceded "
                "the release. A game with a low complexity score may still have taken a year "
                "of polish. Case studies must be read as 'plausibly small in scope and "
                "commercially successful', never as 'this took two weeks'."
            ),
            severity="info",
        ),
        Caveat(
            key="no_scraping_demand_gap",
            title="Missing Demand Signals",
            body=(
                "No scraping means missing demand signals. Wishlist counts, historical player "
                "counts, and price history are unavailable through official endpoints, so "
                "'demand' is reconstructed from review volume and owner estimates only."
            ),
            severity="info",
        ),
        Caveat(
            key="survivorship_bias",
            title="Survivorship Bias",
            body=(
                "Survivorship bias: the catalog only contains released, still-listed games. "
                "Delisted failures and abandoned projects are absent, which inflates the "
                "apparent success rate of any archetype."
            ),
            severity="info",
        ),
        Caveat(
            key="competition_historical",
            title="Competition is Historical",
            body=(
                "Competition density is measured on past releases. It describes the market "
                "a completed game entered, not the market a game started today would launch into."
            ),
            severity="info",
        ),
        Caveat(
            key="coarse_filter_boundary",
            title="Coarse Filter Hard Boundary",
            body=(
                "The coarse filter is a hard boundary. Anything excluded at the acquisition "
                "stage cannot appear anywhere downstream. Rejection counts per reason are "
                "stored per run so the boundary stays visible."
            ),
            severity="info",
        ),
        Caveat(
            key="boxleiter_accuracy_limit",
            title="Boxleiter Accuracy Limit",
            body=(
                "Per the Gamalytic test, only ~43% of games fall within ±30% of their true "
                "sales using the plain review-multiple method. Treat estimated sales as an "
                "ordinal ranking signal, not a point estimate a user should quote as fact."
            ),
            severity="info",
        ),
    ]


def select_case_studies(
    enriched: pd.DataFrame,
    assignments: pd.DataFrame,
    *,
    top_n: int = 15,
    max_per_archetype: int = 2,
    max_per_developer: int = 1,
) -> CaseStudySelection:
    """Select and rank case studies by effort-adjusted return with diversity caps.

    Ranks the simple/buildable subset by effort_adjusted_return descending, then
    enforces per-archetype and per-developer diversity caps applied greedily in
    rank order so the list does not collapse onto one studio or genre.

    Args:
        enriched: games_enriched rows for the run (already filtered to the simplicity
            filter's buildable subset). Games with NaN effort_adjusted_return
            (free-to-play or NULL complexity) are excluded from ranking entirely.
        assignments: cluster_tags' TagClusterResult.assignments DataFrame, with
            at minimum appid and cluster_id columns for archetype lookup.
        top_n: Target list size. Defaults to 15.
        max_per_archetype: Maximum entries per archetype (cluster). Defaults to 2.
        max_per_developer: Maximum entries per developer (exact name match).
            Defaults to 1. This cap is never relaxed.

    Returns:
        CaseStudySelection(case_studies, archetype_cap_relaxed).
            case_studies: Up to top_n CaseStudy objects, ranked by
                effort_adjusted_return descending, subject to caps.
            archetype_cap_relaxed: True iff the one-time relaxation of
                max_per_archetype fired to fill remaining slots.

    Relaxation rule:
        If applying both caps strictly cannot fill top_n slots (pool exhausted
        while candidates remain), max_per_archetype is relaxed by +1 ONCE
        (a single relaxation pass) and archetype_cap_relaxed is set True.
        The developer cap is never relaxed, only the archetype cap.

    Edge cases handled:
        - Fewer eligible candidates than top_n: returns fewer than top_n.
        - NaN effort_adjusted_return: excluded from ranking.
        - Diversity caps binding before top_n: returns as many as caps allow.
    """
    # Filter out rows with NaN effort_adjusted_return (F2P, NULL complexity)
    eligible = enriched[enriched["effort_adjusted_return"].notna()].copy()

    if len(eligible) == 0:
        return CaseStudySelection(case_studies=[], archetype_cap_relaxed=False)

    # Merge in archetype assignments (cluster_id -> label mapping)
    # assignments should have appid and cluster_id; we'll treat cluster_id as the grouping
    eligible = eligible.merge(
        assignments[["appid", "cluster_id"]],
        on="appid",
        how="left",
    )

    # If any appid lacks an assignment, filter it out
    eligible = eligible[eligible["cluster_id"].notna()]

    if len(eligible) == 0:
        return CaseStudySelection(case_studies=[], archetype_cap_relaxed=False)

    # Sort by effort_adjusted_return descending
    eligible = eligible.sort_values("effort_adjusted_return", ascending=False).reset_index(
        drop=True
    )

    case_studies_list = []
    archetype_counts: dict = {}
    developer_counts: dict = {}
    archetype_cap_relaxed = False
    relaxation_used = False

    for _, row in eligible.iterrows():
        appid = int(row["appid"])
        developer = row.get("developer", "Unknown")
        cluster_id = int(row["cluster_id"])
        archetype_label = str(row.get("archetype_label", f"Archetype {cluster_id}"))

        # Check archetype cap
        current_archetype_count = archetype_counts.get(cluster_id, 0)
        effective_archetype_cap = max_per_archetype
        if archetype_cap_relaxed and not relaxation_used:
            effective_archetype_cap = max_per_archetype + 1
            relaxation_used = True

        if current_archetype_count >= effective_archetype_cap:
            continue

        # Check developer cap
        current_developer_count = developer_counts.get(developer, 0)
        if current_developer_count >= max_per_developer:
            continue

        # Build the CaseStudy object
        case_study = _build_case_study(row, archetype_label)
        case_studies_list.append(case_study)

        # Update counts
        archetype_counts[cluster_id] = current_archetype_count + 1
        developer_counts[developer] = current_developer_count + 1

        # Check if we've reached top_n
        if len(case_studies_list) >= top_n:
            break

    # If we couldn't fill top_n with strict caps, consider relaxation
    if len(case_studies_list) < top_n and not archetype_cap_relaxed:
        archetype_cap_relaxed = True
        relaxation_used = False

        # Try again with the relaxed cap
        for _, row in eligible.iterrows():
            appid = int(row["appid"])
            developer = row.get("developer", "Unknown")
            cluster_id = int(row["cluster_id"])

            # Check if this row is already in the result
            if any(cs.appid == appid for cs in case_studies_list):
                continue

            archetype_label = str(row.get("archetype_label", f"Archetype {cluster_id}"))

            # Check archetype cap with relaxation
            current_archetype_count = archetype_counts.get(cluster_id, 0)
            effective_archetype_cap = max_per_archetype + 1
            if current_archetype_count >= effective_archetype_cap:
                continue

            # Check developer cap (never relaxed)
            current_developer_count = developer_counts.get(developer, 0)
            if current_developer_count >= max_per_developer:
                continue

            # Build and add
            case_study = _build_case_study(row, archetype_label)
            case_studies_list.append(case_study)

            # Update counts
            archetype_counts[cluster_id] = current_archetype_count + 1
            developer_counts[developer] = current_developer_count + 1

            if len(case_studies_list) >= top_n:
                break

    return CaseStudySelection(case_studies=case_studies_list, archetype_cap_relaxed=archetype_cap_relaxed)


def _safe_float(value, *, default: float) -> float:
    """Coerce a value to float, treating both a missing key and an explicit
    None value the same way -- ``row.get(key, default)`` alone only covers
    the missing-key case; a stored SQL NULL round-trips as None, which still
    reaches this function even when a default was passed to .get(). A value
    that is already a real (possibly NaN) float is returned as-is.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_case_study(row: pd.Series, archetype_label: str) -> CaseStudy:
    """Internal helper to construct a CaseStudy from an enriched row.

    Args:
        row: A single games_enriched row (as a Series).
        archetype_label: The assigned archetype label string.

    Returns:
        A CaseStudy instance with all fields populated from row and computed values.
    """
    appid = int(row["appid"])
    name = str(row.get("name", "Unknown"))
    developer = str(row.get("developer", "Unknown"))
    release_date = str(row.get("release_date", ""))
    price_usd = _safe_float(row.get("price_usd"), default=0.0)
    review_count = int(_safe_float(row.get("review_count"), default=0.0))
    review_positive_pct = _safe_float(row.get("review_positive_pct"), default=float("nan"))

    # Estimated sales band (low, mid, high)
    estimated_sales_low = _safe_float(row.get("estimated_sales_low"), default=float("nan"))
    estimated_sales_mid = _safe_float(row.get("estimated_sales_mid"), default=float("nan"))
    estimated_sales_high = _safe_float(row.get("estimated_sales_high"), default=float("nan"))
    estimated_sales_band = (estimated_sales_low, estimated_sales_mid, estimated_sales_high)

    estimated_revenue_net_usd = _safe_float(row.get("estimated_revenue_net_usd"), default=float("nan"))
    complexity_score = _safe_float(row.get("complexity_score"), default=float("nan"))

    # Extract top tags (placeholder; would be filled from game_tags in actual implementation)
    top_tags = row.get("top_tags", [])
    if isinstance(top_tags, str):
        top_tags = [t.strip() for t in top_tags.split(",")][:3]
    elif not isinstance(top_tags, list):
        top_tags = []

    # Build rationale
    rationale = build_rationale(row, archetype_label)

    # Complexity drivers (placeholder; would come from enrichment)
    complexity_drivers = row.get("complexity_drivers", [])
    if isinstance(complexity_drivers, list):
        complexity_drivers = complexity_drivers[:5]  # Top 5 by magnitude
    else:
        complexity_drivers = []

    store_url = f"https://store.steampowered.com/app/{appid}/"

    return CaseStudy(
        appid=appid,
        name=name,
        developer=developer,
        release_date=release_date,
        price_usd=price_usd,
        review_count=review_count,
        review_positive_pct=review_positive_pct,
        estimated_sales_band=estimated_sales_band,
        estimated_revenue_net_usd=estimated_revenue_net_usd,
        complexity_score=complexity_score,
        top_tags=top_tags,
        archetype_label=archetype_label,
        rationale=rationale,
        complexity_drivers=complexity_drivers,
        store_url=store_url,
    )
