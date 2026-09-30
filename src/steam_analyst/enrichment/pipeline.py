"""Enrichment stage orchestration: pure transformation and database integration.

This module wires together the enrichment sub-functions (normalize_features,
map_genre_bucket, estimate_sales, estimate_revenue, compute_complexity_score,
compute_effort_adjusted_return) and manages their output: one feature-complete
row per game, tagged and scored for analysis.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from time import time
from typing import Any

import pandas as pd
import numpy as np

from steam_analyst.acquisition.funnel import build_catalog_frame
from steam_analyst.config.settings import EnrichmentParams
from steam_analyst.storage import (
    EventSink,
    read_raw_payloads,
    write_enriched,
    write_tags,
)
from steam_analyst.storage.types import TagRow

from .errors import EnrichmentError
from .parsing import parse_raw_bundle, normalize_features, extract_tags
from .features import compute_developer_catalog_size
from .revenue import (
    map_genre_bucket,
    estimate_sales,
    estimate_revenue,
    compute_effort_adjusted_return,
)
from .complexity import compute_complexity_details

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnrichmentReport:
    """Outcome of one enrichment stage run.

    Attributes:
        run_id: The run this report describes.
        rows_written: Number of games_enriched rows written.
        rows_dropped: Candidates excluded from games_enriched (currently only reason: non-'game' app_type).
        dropped_by_reason: Dict mapping drop reason to count, e.g. {'non_game_app_type': N}.
        imputation_rate_by_feature: Dict mapping feature name to fraction of rows imputed at cohort median.
        unmatched_genre_count: Rows whose genre list matched no key in genre_bucket_map.
        free_to_play_count: Rows with NaN revenue due to F2P policy.
        duration_seconds: Wall-clock stage time.
    """

    run_id: str
    rows_written: int
    rows_dropped: int
    dropped_by_reason: dict[str, int]
    imputation_rate_by_feature: dict[str, float]
    unmatched_genre_count: int
    free_to_play_count: int
    duration_seconds: float


def build_enriched_frame(
    bundle: "RawBundle", catalog: pd.DataFrame, params: EnrichmentParams
) -> tuple[pd.DataFrame, list[TagRow]]:
    """Run the full enrichment transformation in memory.

    Composes the enrichment pipeline: normalize_features -> extract_tags ->
    compute_developer_catalog_size -> drop non-game rows -> map_genre_bucket ->
    compute_complexity_score -> estimate_sales -> estimate_revenue ->
    compute_effort_adjusted_return, producing one row per appid with every
    games_enriched column populated.

    Args:
        bundle: parse_raw_bundle's output.
        catalog: The full bulk catalog frame (acquisition.build_catalog_frame's output
                 for the whole run), needed by compute_developer_catalog_size.
        params: EnrichmentParams.

    Returns:
        (enriched_frame, tag_rows): enriched_frame has exactly the columns
        games_enriched expects, including complexity_score, estimated_sales_low/mid/high,
        estimated_revenue_gross_usd/net_usd, effort_adjusted_return, imputed_features_json.
        parameters_version is NOT set here (it is stamped by run_enrichment, the caller).
        tag_rows is extract_tags' output.

        Every row in the output has app_type == 'game' (non-game rows are dropped entirely).

    Postconditions:
        - Calling build_enriched_frame twice with identical (bundle, catalog, params)
          produces byte-identical output frames (idempotence invariant).
        - Every row in the output has app_type == 'game'.
    """
    # Handle empty bundle
    if not bundle.steamspy:
        empty_frame = pd.DataFrame(
            columns=[
                "appid",
                "name",
                "app_type",
                "developer",
                "publisher",
                "release_date",
                "price_usd",
                "is_free",
                "review_count",
                "review_positive_pct",
                "owners_estimate_low",
                "owners_estimate_mid",
                "owners_estimate_high",
                "size_bytes",
                "ram_bytes",
                "achievement_count",
                "language_count",
                "platform_count",
                "dlc_count",
                "dev_title_count",
                "is_early_access",
                "early_access_days",
                "deck_compat",
                "genres_json",
                "categories_json",
                "complexity_score",
                "imputed_features_json",
                "estimated_sales_low",
                "estimated_sales_mid",
                "estimated_sales_high",
                "estimated_revenue_gross_usd",
                "estimated_revenue_net_usd",
                "effort_adjusted_return",
            ]
        )
        return empty_frame, []

    # Step 1: Normalize raw features
    frame = normalize_features(bundle)

    # Step 2: Extract tags (using locked constants from EnrichmentParams)
    tag_rows = extract_tags(
        bundle,
        max_tags_per_game=params.tag_extraction_max_per_game,
        min_votes=params.tag_extraction_min_votes,
    )

    # Convert tag_rows to DataFrame for compute_complexity_score
    if tag_rows:
        tags_df = pd.DataFrame([
            {"appid": tr.appid, "tag": tr.tag, "votes": tr.votes, "rank": tr.rank}
            for tr in tag_rows
        ])
    else:
        tags_df = pd.DataFrame(columns=["appid", "tag", "votes", "rank"])

    # Step 3: Compute developer catalog size
    dev_title_count = compute_developer_catalog_size(frame, catalog)
    frame["dev_title_count"] = dev_title_count

    # Step 4: Drop non-game rows
    frame = frame[frame["is_game"] == True]

    # Handle case where all rows were dropped
    if frame.empty:
        empty_frame = pd.DataFrame(
            columns=[
                "appid",
                "name",
                "app_type",
                "developer",
                "publisher",
                "release_date",
                "price_usd",
                "is_free",
                "review_count",
                "review_positive_pct",
                "owners_estimate_low",
                "owners_estimate_mid",
                "owners_estimate_high",
                "size_bytes",
                "ram_bytes",
                "achievement_count",
                "language_count",
                "platform_count",
                "dlc_count",
                "dev_title_count",
                "is_early_access",
                "early_access_days",
                "deck_compat",
                "genres_json",
                "categories_json",
                "complexity_score",
                "imputed_features_json",
                "estimated_sales_low",
                "estimated_sales_mid",
                "estimated_sales_high",
                "estimated_revenue_gross_usd",
                "estimated_revenue_net_usd",
                "effort_adjusted_return",
            ]
        )
        return empty_frame, tag_rows

    # Step 5: Parse genres from JSON and map to genre buckets
    frame["genres"] = frame["genres_json"].apply(
        lambda x: json.loads(x) if isinstance(x, str) else []
    )
    genre_bucket = map_genre_bucket(frame["genres"], params)

    # Step 6: Estimate sales
    sales_df = estimate_sales(frame["review_count"], genre_bucket, params)

    # Step 7: Estimate revenue
    revenue_df = estimate_revenue(sales_df, frame["price_usd"], params)

    # Step 8: Compute complexity score
    complexity_score, _contributions, imputed_features_df = compute_complexity_details(
        frame, tags_df, params
    )

    # Step 9: Compute effort-adjusted return
    effort_adjusted_return = compute_effort_adjusted_return(
        revenue_df["estimated_revenue_net_usd"], complexity_score, params
    )

    # Step 10: Assemble final frame
    # Start with the base features
    result = frame[[
        "name",
        "app_type",
        "developer",
        "publisher",
        "release_date",
        "price_usd",
        "is_free",
        "review_count",
        "review_positive_pct",
        "owners_estimate_low",
        "owners_estimate_mid",
        "owners_estimate_high",
        "size_bytes",
        "ram_bytes",
        "achievement_count",
        "language_count",
        "platform_count",
        "dlc_count",
        "dev_title_count",
        "is_early_access",
        "early_access_days",
        "deck_compat",
        "genres_json",
        "categories_json",
    ]].copy()

    # Add derived columns
    result["complexity_score"] = complexity_score

    # Serialize imputed features as JSON
    imputed_json_list = []
    for appid in result.index:
        imputed_names = [
            col for col in imputed_features_df.columns if bool(imputed_features_df.loc[appid, col])
        ]
        imputed_json_list.append(json.dumps(imputed_names))
    result["imputed_features_json"] = imputed_json_list

    # Add sales and revenue columns
    result["estimated_sales_low"] = sales_df["estimated_sales_low"].values
    result["estimated_sales_mid"] = sales_df["estimated_sales_mid"].values
    result["estimated_sales_high"] = sales_df["estimated_sales_high"].values
    result["estimated_revenue_gross_usd"] = revenue_df["estimated_revenue_gross_usd"].values
    result["estimated_revenue_net_usd"] = revenue_df["estimated_revenue_net_usd"].values

    # Add effort-adjusted return
    result["effort_adjusted_return"] = effort_adjusted_return.values

    # Reset index to make appid a column (not the index)
    result = result.reset_index()

    # Ensure all required columns are present in the correct order
    required_columns = [
        "appid",
        "name",
        "app_type",
        "developer",
        "publisher",
        "release_date",
        "price_usd",
        "is_free",
        "review_count",
        "review_positive_pct",
        "owners_estimate_low",
        "owners_estimate_mid",
        "owners_estimate_high",
        "size_bytes",
        "ram_bytes",
        "achievement_count",
        "language_count",
        "platform_count",
        "dlc_count",
        "dev_title_count",
        "is_early_access",
        "early_access_days",
        "deck_compat",
        "genres_json",
        "categories_json",
        "complexity_score",
        "imputed_features_json",
        "estimated_sales_low",
        "estimated_sales_mid",
        "estimated_sales_high",
        "estimated_revenue_gross_usd",
        "estimated_revenue_net_usd",
        "effort_adjusted_return",
    ]

    result = result[required_columns]

    return result, tag_rows


def run_enrichment(
    conn: sqlite3.Connection,
    run_id: str,
    params: EnrichmentParams,
    *,
    parameters_version: str,
    on_event: EventSink,
) -> EnrichmentReport:
    """Run the full enrichment stage for one run.

    Reads raw_games for the run, calls build_enriched_frame, writes games_enriched
    and game_tags, emits progress events.

    Args:
        conn: An open storage connection.
        run_id: The run to enrich; acquisition must have already completed
                (or at least written some raw_games rows).
        params: EnrichmentParams.
        parameters_version: config.parameters_version(...) for the parameters.toml
                            in effect; stamped onto every written row.
        on_event: Progress/log sink.

    Returns:
        An EnrichmentReport summarizing the stage.

    Raises:
        EnrichmentError: If run_id does not exist, or if raw_games has zero
                         steamspy_all rows for the run (acquisition never completed
                         even its bulk stage).
    """
    start_time = time()

    on_event(stage="enrichment", level="info", message=f"Starting enrichment for run {run_id}")
    try:
        # Step 1: Load raw bundle
        bundle = parse_raw_bundle(conn, run_id)

        # Step 2: Load the full catalog from steamspy_all
        steamspy_payloads = read_raw_payloads(conn, run_id, "steamspy_all")
        catalog = build_catalog_frame(steamspy_payloads)

        if catalog.empty:
            raise EnrichmentError(
                f"Run {run_id} has no steamspy_all rows; acquisition never completed "
                "its bulk stage and enrichment cannot proceed without the full catalog"
            )

        on_event(stage="enrichment", level="info", message="Loaded raw payloads and catalog")
        # Step 3: Call build_enriched_frame
        enriched_frame, tag_rows = build_enriched_frame(bundle, catalog, params)

        on_event(
            stage="enrichment",
            level="info",
            message=f"Built enriched frame with {len(enriched_frame)} rows from {len(bundle.steamspy)} candidates",
        )

        # Step 4: Stamp parameters_version
        enriched_frame["parameters_version"] = parameters_version

        # Step 5: Write to storage
        rows_written = write_enriched(conn, run_id, enriched_frame)
        on_event(stage="enrichment", level="info", message=f"Wrote {rows_written} enriched rows")
        rows_tags_written = write_tags(conn, run_id, tag_rows)
        on_event(stage="enrichment", level="info", message=f"Wrote {rows_tags_written} tag rows")
        # Step 6: Compute report statistics
        rows_dropped = len(bundle.steamspy) - rows_written

        # Count drops by reason (currently only non_game_app_type)
        dropped_by_reason = {}
        if rows_dropped > 0:
            # Count non-game rows by checking normalized frame
            frame = normalize_features(bundle)
            non_game_count = (~frame["is_game"]).sum()
            if non_game_count > 0:
                dropped_by_reason["non_game_app_type"] = int(non_game_count)

        # Compute imputation rates from complexity score computation
        imputation_rate_by_feature: dict[str, float] = {}

        if rows_written > 0:
            # For each complexity feature, compute the imputation rate
            feature_list = [
                "size_bytes",
                "ram_bytes",
                "early_access_days",
                "dev_title_count",
                "achievement_count",
                "dlc_count",
                "language_count",
            ]

            frame = normalize_features(bundle)
            frame["dev_title_count"] = compute_developer_catalog_size(frame, catalog)
            frame = frame[frame["is_game"] == True]

            for feature_name in feature_list:
                if not frame.empty and feature_name in frame.columns:
                    missing_count = frame[feature_name].isna().sum()
                    imputation_rate_by_feature[feature_name] = (
                        float(missing_count) / len(frame)
                    )
                else:
                    imputation_rate_by_feature[feature_name] = 0.0

            # For tag-based features, estimate imputation rate
            imputation_rate_by_feature["simplicity_tag_score"] = 0.0
            imputation_rate_by_feature["complexity_tag_score"] = 0.0
            imputation_rate_by_feature["platform_count"] = 0.0
        else:
            # Empty result set
            for feature_name in [
                "size_bytes",
                "ram_bytes",
                "early_access_days",
                "dev_title_count",
                "achievement_count",
                "dlc_count",
                "language_count",
                "simplicity_tag_score",
                "complexity_tag_score",
                "platform_count",
            ]:
                imputation_rate_by_feature[feature_name] = 0.0

        # Count unmatched genres
        unmatched_genre_count = 0
        if rows_written > 0:
            for genre_json in enriched_frame["genres_json"]:
                try:
                    genres = json.loads(genre_json)
                    if genres:
                        # Check if the first genre is in the map
                        first_genre = genres[0]
                        if first_genre not in params.genre_bucket_map:
                            unmatched_genre_count += 1
                except (json.JSONDecodeError, TypeError, IndexError):
                    pass

        # Count F2P rows
        free_to_play_count = int(enriched_frame["estimated_revenue_net_usd"].isna().sum())

        # Compute duration
        duration_seconds = time() - start_time

        # Create report
        report = EnrichmentReport(
            run_id=run_id,
            rows_written=rows_written,
            rows_dropped=rows_dropped,
            dropped_by_reason=dropped_by_reason,
            imputation_rate_by_feature=imputation_rate_by_feature,
            unmatched_genre_count=unmatched_genre_count,
            free_to_play_count=free_to_play_count,
            duration_seconds=duration_seconds,
        )

        on_event(stage="enrichment", level="info", message=f"Enrichment complete: {report}")
        return report

    except Exception as e:
        duration_seconds = time() - start_time
        on_event(stage="enrichment", level="error", message=f"Enrichment failed: {e}")
        raise
