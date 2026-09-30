"""Analysis pipeline orchestration.

Implements the stage entry point that wires together clustering, scoring,
and trend analysis modules to produce the complete opportunity matrix
and supporting analysis tables.
"""

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
import json

import pandas as pd
import numpy as np

from steam_analyst.analysis.clustering import cluster_tags
from steam_analyst.analysis.errors import AnalysisError
from steam_analyst.analysis.scoring import (
    build_opportunity_matrix,
    build_tag_summary,
    compute_competition_density,
    compute_demand,
    compute_zscore,
)
from steam_analyst.analysis.simplicity import apply_simplicity_filter
from steam_analyst.analysis.trends import compute_tag_trends
from steam_analyst.config.settings import AnalysisParams
from steam_analyst.storage import (
    EventSink,
    append_run_event,
    read_analysis_result,
    read_enriched,
    read_run_events,
    read_tags,
    write_analysis_result,
    get_run,
)


def _make_json_serializable(obj):
    """Recursively convert numpy/pandas types to JSON-serializable Python types.

    Args:
        obj: Any object that may contain numpy/pandas types.

    Returns:
        A version of obj with all numpy/pandas types converted to JSON-serializable
        Python native types (int, float, str, None). Integer dict keys are converted
        to strings since JSON requires string keys.
    """
    if isinstance(obj, dict):
        return {
            (str(k) if isinstance(k, (int, np.integer)) else k): _make_json_serializable(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, (list, tuple)):
        return [_make_json_serializable(v) for v in obj]
    elif isinstance(obj, (np.integer, np.int32, np.int64)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float32, np.float64)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    elif isinstance(obj, (pd.Timestamp, pd.Timedelta)):
        return str(obj)
    elif pd.isna(obj):
        return None
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    else:
        return obj


@dataclass(frozen=True)
class AnalysisReport:
    """Summary of one analysis stage run.

    Outcome of one analysis stage run.

    Attributes:
        run_id: The run analyzed.
        candidates_in: len(games_enriched) for the run.
        simple_subset_size: len(apply_simplicity_filter's buildable output).
        rejected_by_reason: apply_simplicity_filter's tally, merged with any
            release-date-unparseable exclusions from the trend/density computations.
        cluster_count: Total distinct clusters produced by cluster_tags, scored or not.
        scored_cluster_count: Clusters present in the final opportunity_matrix
            (n_games >= min_cluster_size).
        clusters_below_min_size: cluster_count - scored_cluster_count.
        duration_seconds: Wall-clock stage time.
    """

    run_id: str
    candidates_in: int
    simple_subset_size: int
    rejected_by_reason: dict[str, int]
    cluster_count: int
    scored_cluster_count: int
    clusters_below_min_size: int
    duration_seconds: float


def run_analysis(
    conn: sqlite3.Connection,
    run_id: str,
    params: AnalysisParams,
    *,
    parameters_version: str,
    on_event: EventSink,
) -> AnalysisReport:
    """Run the full analysis stage for one run.

    Args:
        conn: An open storage connection.
        run_id: The run to analyze; enrichment must have already completed.
        params: AnalysisParams.
        parameters_version: Stamped onto every written analysis_results row.
        on_event: Progress/log sink.

    Returns:
        An AnalysisReport summarizing the stage.

    Raises:
        AnalysisError: If run_id does not exist or games_enriched has zero rows
            for run_id and enrichment's own report indicates it should not be
            empty (distinguishing a legitimately empty candidate set, which is
            not an error, from enrichment never having run at all, which is).
    """
    start_time = time.time()

    try:
        # Step 0: Verify run exists
        run_record = get_run(conn, run_id)
        if run_record is None:
            raise AnalysisError(f"Run {run_id} does not exist")

        on_event(
            stage="analysis",
            level="info",
            message=f"Starting analysis for run {run_id}",
            progress=0.0,
        )

        # Step 1: Read enriched frame and tags
        on_event(
            stage="analysis",
            level="debug",
            message="Reading enriched frame and tags",
            progress=0.05,
        )

        frame = read_enriched(conn, run_id)
        tags = read_tags(conn, run_id, min_votes=params.min_tag_votes)

        # Convert release_date to release_date_parsed for scoring functions
        if "release_date" in frame.columns and "release_date_parsed" not in frame.columns:
            frame["release_date_parsed"] = pd.to_datetime(frame["release_date"], errors="coerce")
        elif "release_date_parsed" not in frame.columns:
            # If neither exists, create empty datetime column
            frame["release_date_parsed"] = pd.NaT

        # Determine if this is a legitimately empty candidate set vs. enrichment never ran
        candidates_in = len(frame)
        if candidates_in == 0:
            # Check if enrichment stage completed
            events = read_run_events(conn, run_id)
            enrichment_completed = any(
                e.stage == "enrichment" and e.level != "error" and "complete" in e.message.lower()
                for e in events
            )

            if not enrichment_completed:
                raise AnalysisError(
                    f"Enrichment has not completed for run {run_id}. "
                    "games_enriched is empty and no enrichment stage_complete event exists."
                )

            # Empty but legitimate case: return empty results
            on_event(
                stage="analysis",
                level="warning",
                message="Candidate set is empty (enrichment completed with zero results). "
                "Producing empty-but-well-formed analysis results.",
                progress=1.0,
            )

            empty_report = AnalysisReport(
                run_id=run_id,
                candidates_in=0,
                simple_subset_size=0,
                rejected_by_reason={},
                cluster_count=0,
                scored_cluster_count=0,
                clusters_below_min_size=0,
                duration_seconds=time.time() - start_time,
            )

            # Write empty but well-formed results
            _write_empty_analysis_results(conn, run_id, parameters_version)

            on_event(
                stage="analysis",
                level="info",
                message="Analysis stage completed with empty candidate set",
                progress=1.0,
            )

            # Emit stage_complete event via on_event
            on_event(
                stage="analysis",
                level="info",
                message="stage_complete",
                progress=1.0,
            )

            # Also write to database via append_run_event
            append_run_event(
                conn,
                run_id,
                stage="analysis",
                level="info",
                message="stage_complete",
            )

            return empty_report

        # Step 2: Apply simplicity filter
        on_event(
            stage="analysis",
            level="debug",
            message="Applying simplicity filter",
            progress=0.10,
        )

        buildable, rejected_by_reason = apply_simplicity_filter(frame, params)
        simple_subset_size = len(buildable)

        on_event(
            stage="analysis",
            level="info",
            message=f"Simplicity filter: {simple_subset_size} buildable out of {candidates_in} candidates",
            progress=0.15,
        )

        # Merge simple_subset_size into acquisition's already-written funnel_report
        # (never overwrite it wholesale -- that would lose catalog_size/candidate_count/
        # detail_fetched/detail_failed/criteria, which only acquisition knows).
        existing_funnel_report = read_analysis_result(conn, run_id, "funnel_report")
        if existing_funnel_report is not None:
            existing_funnel_report.setdefault("data", {})["simple_subset_size"] = simple_subset_size
            write_analysis_result(
                conn,
                run_id,
                "funnel_report",
                existing_funnel_report,
                parameters_version=parameters_version,
            )

        # Step 3: Cluster tags
        on_event(
            stage="analysis",
            level="debug",
            message="Clustering tags into archetypes",
            progress=0.20,
        )

        cluster_result = cluster_tags(tags, buildable, params)

        # Emit provisional threshold warning if using run-local search
        if (
            cluster_result.params_used.get("threshold_source")
            == "run_local_search"
        ):
            on_event(
                stage="analysis",
                level="info",
                message="Tag distance threshold is provisional (run-local search). "
                "Will be superseded by scripts/freeze_empirical_parameters.py. "
                "Tagging as run_local_search for tracking.",
                progress=0.25,
            )

        # Write tag_clusters result
        tag_clusters_payload = {
            "assignments": cluster_result.assignments.to_dict(orient="records"),
            "cluster_labels": cluster_result.cluster_labels,
            "cluster_members": cluster_result.cluster_members,
            "method": cluster_result.method,
            "params_used": cluster_result.params_used,
        }
        write_analysis_result(
            conn,
            run_id,
            "tag_clusters",
            _make_json_serializable(tag_clusters_payload),
            parameters_version=parameters_version,
        )

        on_event(
            stage="analysis",
            level="info",
            message=f"Clustered tags into {len(cluster_result.cluster_labels)} archetypes",
            progress=0.30,
        )

        # Step 4: Compute demand, competition, and simplicity
        on_event(
            stage="analysis",
            level="debug",
            message="Computing demand and competition metrics",
            progress=0.35,
        )

        demand = compute_demand(buildable, cluster_result.assignments, params)
        competition = compute_competition_density(
            buildable, cluster_result.assignments, params
        )

        # Compute simplicity: median complexity per cluster from windowed games
        # Join frame with assignments, filter to windowed releases, compute median complexity
        simplicity = _compute_simplicity_per_cluster(
            buildable, cluster_result.assignments, params
        )

        # Write competition_density result
        competition_payload = {
            "data": competition.reset_index().to_dict(orient="records")
        }
        write_analysis_result(
            conn,
            run_id,
            "competition_density",
            _make_json_serializable(competition_payload),
            parameters_version=parameters_version,
        )

        on_event(
            stage="analysis",
            level="debug",
            message=f"Computed metrics for {len(demand)} clusters with demand data",
            progress=0.50,
        )

        # Step 5: Build opportunity matrix
        on_event(
            stage="analysis",
            level="debug",
            message="Building opportunity matrix",
            progress=0.55,
        )

        matrix = build_opportunity_matrix(demand, competition, simplicity, params)

        # Add labels from cluster_result to matrix
        if len(matrix) > 0:
            matrix["label"] = matrix["cluster_id"].map(cluster_result.cluster_labels)

        # Write opportunity_matrix result
        matrix_payload = {
            "data": matrix.to_dict(orient="records")
        }
        write_analysis_result(
            conn,
            run_id,
            "opportunity_matrix",
            _make_json_serializable(matrix_payload),
            parameters_version=parameters_version,
        )

        scored_cluster_count = len(matrix)
        on_event(
            stage="analysis",
            level="info",
            message=f"Opportunity matrix: {scored_cluster_count} clusters meet min_cluster_size",
            progress=0.60,
        )

        # Step 6: Compute trends
        on_event(
            stage="analysis",
            level="debug",
            message="Computing release-date trends",
            progress=0.70,
        )

        trends = compute_tag_trends(buildable, cluster_result.assignments, params)

        # Write tag_trends result
        trends_payload = {
            "data": trends.to_dict(orient="records")
        }
        # Handle NaN/NaT serialization
        trends_payload["data"] = [
            {
                k: (None if (isinstance(v, float) and np.isnan(v))
                    or (pd.isna(v) and v is not pd.NaT)
                    or v is pd.NaT
                    else v)
                for k, v in row.items()
            }
            for row in trends_payload["data"]
        ]
        write_analysis_result(
            conn,
            run_id,
            "tag_trends",
            _make_json_serializable(trends_payload),
            parameters_version=parameters_version,
        )

        on_event(
            stage="analysis",
            level="debug",
            message=f"Computed trends for {len(trends['cluster_id'].unique())} clusters",
            progress=0.75,
        )

        # Step 7: Build tag summary
        on_event(
            stage="analysis",
            level="debug",
            message="Building per-tag summary",
            progress=0.85,
        )

        tag_summary = build_tag_summary(buildable, tags, params)

        # Write tag_summary result
        tag_summary_payload = {
            "data": tag_summary.to_dict(orient="records")
        }
        write_analysis_result(
            conn,
            run_id,
            "tag_summary",
            _make_json_serializable(tag_summary_payload),
            parameters_version=parameters_version,
        )

        on_event(
            stage="analysis",
            level="info",
            message=f"Generated tag summary for {len(tag_summary)} tags",
            progress=0.95,
        )

        # Step 8: Assemble and return AnalysisReport
        cluster_count = len(cluster_result.cluster_labels)
        clusters_below_min_size = cluster_count - scored_cluster_count

        report = AnalysisReport(
            run_id=run_id,
            candidates_in=candidates_in,
            simple_subset_size=simple_subset_size,
            rejected_by_reason=rejected_by_reason,
            cluster_count=cluster_count,
            scored_cluster_count=scored_cluster_count,
            clusters_below_min_size=clusters_below_min_size,
            duration_seconds=time.time() - start_time,
        )

        on_event(
            stage="analysis",
            level="info",
            message="Analysis stage completed",
            progress=1.0,
        )

        # Emit stage_complete event
        append_run_event(
            conn,
            run_id,
            stage="analysis",
            level="info",
            message="stage_complete",
        )

        return report

    except AnalysisError:
        # Re-raise AnalysisError as-is
        raise
    except Exception as e:
        # Convert any other exception to AnalysisError
        raise AnalysisError(f"Analysis stage failed: {str(e)}") from e


def _write_empty_analysis_results(
    conn: sqlite3.Connection, run_id: str, parameters_version: str
) -> None:
    """Write empty but well-formed analysis results for an empty candidate set.

    Writes all five analysis result types with empty data structures.

    Args:
        conn: An open storage connection.
        run_id: The run to write results for.
        parameters_version: Parameter version to stamp on results.
    """
    # Write empty tag_clusters
    write_analysis_result(
        conn,
        run_id,
        "tag_clusters",
        _make_json_serializable({
            "assignments": [],
            "cluster_labels": {},
            "cluster_members": {},
            "method": "agglomerative_jaccard_no_genre_anchor",
            "params_used": {},
        }),
        parameters_version=parameters_version,
    )

    # Write empty opportunity_matrix
    write_analysis_result(
        conn,
        run_id,
        "opportunity_matrix",
        _make_json_serializable({"data": []}),
        parameters_version=parameters_version,
    )

    # Write empty competition_density
    write_analysis_result(
        conn,
        run_id,
        "competition_density",
        _make_json_serializable({"data": []}),
        parameters_version=parameters_version,
    )

    # Write empty tag_trends
    write_analysis_result(
        conn,
        run_id,
        "tag_trends",
        _make_json_serializable({"data": []}),
        parameters_version=parameters_version,
    )

    # Write empty tag_summary
    write_analysis_result(
        conn,
        run_id,
        "tag_summary",
        _make_json_serializable({"data": []}),
        parameters_version=parameters_version,
    )


def _compute_simplicity_per_cluster(
    frame: pd.DataFrame,
    assignments: pd.DataFrame,
    params: AnalysisParams,
) -> pd.DataFrame:
    """Compute median complexity_score per cluster from windowed games.

    Args:
        frame: The full enriched frame.
        assignments: cluster_tags output (appid -> cluster_id).
        params: AnalysisParams with trailing_window_months.

    Returns:
        A DataFrame indexed by cluster_id with a median_complexity column,
        containing the median complexity_score of games in that cluster
        that have a parseable release date within the trailing window.
        Only clusters with at least one windowed game appear as rows.
    """
    from datetime import timedelta

    if len(frame) == 0 or len(assignments) == 0:
        return pd.DataFrame(columns=["cluster_id", "median_complexity"]).set_index(
            "cluster_id"
        )

    # Merge frame with assignments
    merged = frame.copy()
    merged = merged.merge(
        assignments[["appid", "cluster_id"]],
        on="appid",
        how="inner",
    )

    if len(merged) == 0:
        return pd.DataFrame(columns=["cluster_id", "median_complexity"]).set_index(
            "cluster_id"
        )

    # Filter to games with a parseable release_date within the trailing window
    today = datetime.now()
    window_start = today - timedelta(
        days=params.trailing_window_months * 30.44
    )

    # Ensure release_date is datetime
    merged["release_date"] = pd.to_datetime(merged["release_date"], errors="coerce")

    # Filter to games with a valid release date in the window
    valid_dates = merged[merged["release_date"].notna()].copy()

    if len(valid_dates) == 0:
        return pd.DataFrame(columns=["cluster_id", "median_complexity"]).set_index(
            "cluster_id"
        )

    windowed = valid_dates[
        valid_dates["release_date"] >= pd.Timestamp(window_start)
    ]

    if len(windowed) == 0:
        return pd.DataFrame(columns=["cluster_id", "median_complexity"]).set_index(
            "cluster_id"
        )

    # Group by cluster_id and compute median complexity
    simplicity_stats = []

    for cluster_id, group in windowed.groupby("cluster_id"):
        # Compute median of complexity_score (excluding NaN)
        complexity_values = group["complexity_score"].dropna()

        if len(complexity_values) == 0:
            # Skip clusters with no valid complexity scores
            continue

        median_complexity = complexity_values.median()

        simplicity_stats.append({
            "cluster_id": cluster_id,
            "median_complexity": median_complexity,
        })

    if len(simplicity_stats) == 0:
        return pd.DataFrame(columns=["cluster_id", "median_complexity"]).set_index(
            "cluster_id"
        )

    result = pd.DataFrame(simplicity_stats).set_index("cluster_id")
    return result
