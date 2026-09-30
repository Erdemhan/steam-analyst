"""Run report assembly and headline metrics extraction.

This module assembles the complete RunReport for the Analysis Detail UI page,
including decision whether a run is partial and what caveats to display.

Core responsibilities:
- RunReport: dataclass bundling all data for the detail page.
- is_partial_run: Single canonical definition of partial (ADR-016).
- partial_run_caveat: Caveat describing partial run with error message if present.
- load_run_report: Main entry point assembling all data from storage.
- headline_metrics: Extract summary for run list UI.
"""

import sqlite3
from dataclasses import dataclass
from typing import Any, Sequence

import pandas as pd

from steam_analyst.reporting.case_studies import (
    CaseStudy,
    interpretive_caveats,
    select_case_studies,
)
from steam_analyst.reporting.types import Caveat, CaseStudySelection, FunnelSummary, ReportNotAvailable
from steam_analyst.reporting.views import build_opportunity_matrix_view, build_tag_summary_table
from steam_analyst.storage import (
    RunRecord,
    RunStage,
    get_run,
    read_analysis_result,
    read_enriched,
    read_run_stages,
)


@dataclass(frozen=True)
class RunReport:
    """Everything the Analysis Detail page needs for one run.

    Attributes:
        run_id: The run identifier.
        run: storage.RunRecord for context (status, timestamps, config snapshot).
        stages: storage.read_run_stages(conn, run_id) verbatim, in pipeline order.
        missing_stages: The subset of ('acquisition', 'enrichment', 'analysis')
            absent from stages or not status='succeeded' in stages, in pipeline order.
            Empty when the run succeeded cleanly.
        opportunity_matrix: build_opportunity_matrix_view output DataFrame.
        tag_summary: build_tag_summary_table output DataFrame.
        tag_trends: The raw tag_trends analysis_results payload (DataFrame-like).
        case_studies: select_case_studies' output (CaseStudySelection.case_studies, unwrapped).
        funnel: FunnelSummary.
        headline_metrics: headline_metrics(self) output dict.
        caveats: interpretive_caveats(), plus additional caveats for partial runs
            and archetype_cap_relaxed.
        is_partial: is_partial_run(stages) -- canonical definition per ADR-016.
    """

    run_id: str
    run: RunRecord
    stages: list[RunStage]
    missing_stages: list[str]
    opportunity_matrix: pd.DataFrame
    tag_summary: pd.DataFrame
    tag_trends: pd.DataFrame
    case_studies: list[CaseStudy]
    funnel: FunnelSummary
    headline_metrics: dict[str, Any]
    caveats: list[Caveat]
    is_partial: bool


def is_partial_run(stages: Sequence[RunStage]) -> bool:
    """Determine whether a run's stage set counts as partial.

    The single, canonical definition of 'partial' for a run, independent of runs.status.
    Every other place that needs to know whether a run is partial calls this (ADR-016).

    Args:
        stages: storage.read_run_stages(conn, run_id) output, in any order.

    Returns:
        True unless stages contains a 'succeeded' entry for all three of
        'acquisition', 'enrichment' and 'analysis'. Equivalently: False iff
        {s.stage for s in stages if s.status == 'succeeded'} == {'acquisition', 'enrichment', 'analysis'}.

    Postconditions:
        Result depends only on stages, never on any runs.status value.
        A stage present with a non-'succeeded' status counts the same as a stage
        entirely absent -- both make the result True.
    """
    succeeded_stages = {s.stage for s in stages if s.status == "succeeded"}
    required_stages = {"acquisition", "enrichment", "analysis"}
    return not required_stages.issubset(succeeded_stages)


def partial_run_caveat(missing_stages: Sequence[str], run: RunRecord) -> Caveat:
    """Build the caveat describing why a report is partial.

    Args:
        missing_stages: The stages that did not succeed, in pipeline order.
            Never empty -- callers only invoke this when is_partial_run(...) is True.
        run: The RunRecord for status and error_message.

    Returns:
        A Caveat with key='partial_run', a title naming the run's status, a body listing
        missing_stages plus run.error_message when present, and severity: 'error' when
        run.status == 'failed', 'warning' when run.status in {'running', 'cancelled'}.

    Preconditions:
        missing_stages is non-empty.

    Postconditions:
        The returned Caveat.body names every entry of missing_stages, in the order given.
        severity == 'error' if and only if run.status == 'failed'.
        When run.error_message is not None, it appears verbatim in the body.
    """
    if not missing_stages:
        raise ValueError("missing_stages must be non-empty")

    # Determine severity and title based on run status
    if run.status == "failed":
        severity = "error"
        title = "Run Failed"
        status_desc = "This run did not complete successfully."
    elif run.status == "cancelled":
        severity = "warning"
        title = "Run Was Cancelled"
        status_desc = "This run was deliberately stopped by the user."
    else:  # 'running' or other
        severity = "warning"
        title = "Run Still In Progress"
        status_desc = "This run has not yet finished."

    # Build body with missing stages
    missing_stages_str = ", ".join(missing_stages)
    body_lines = [
        status_desc,
        f"Stages not yet complete: {missing_stages_str}.",
    ]

    # Add error message if present
    if run.error_message is not None:
        body_lines.append(f"Error: {run.error_message}")

    body = "\n".join(body_lines)

    return Caveat(
        key="partial_run",
        title=title,
        body=body,
        severity=severity,
    )


def load_run_report(conn: sqlite3.Connection, run_id: str) -> RunReport:
    """Assemble a full run report.

    Args:
        conn: An open storage connection.
        run_id: The run to report on.

    Returns:
        A fully populated RunReport.

    Raises:
        ReportNotAvailable: If run_id does not exist (storage.get_run returns None).

    Steps:
        1. run_record = storage.get_run(conn, run_id); raise ReportNotAvailable if None.
        2. stages = storage.read_run_stages(conn, run_id).
        3. Determine missing_stages in pipeline order.
        4. is_partial = is_partial_run(stages).
        5. Read each analysis_results type; any missing type becomes an empty, correctly-columned frame.
        6. Build opportunity_matrix/tag_summary views, select case studies, build funnel.
        7. Build caveats: interpretive_caveats() + partial_run_caveat if partial + archetype_cap_relaxed caveat.
    """
    # Step 1: Get the run record
    run_record = get_run(conn, run_id)
    if run_record is None:
        raise ReportNotAvailable(f"Run {run_id} not found")

    # Step 2: Read stages
    stages = read_run_stages(conn, run_id)

    # Step 3: Determine missing stages in pipeline order
    succeeded_stage_names = {s.stage for s in stages if s.status == "succeeded"}
    missing_stages = [s for s in ("acquisition", "enrichment", "analysis") if s not in succeeded_stage_names]

    # Step 4: Check if partial
    is_partial = is_partial_run(stages)

    # Step 5: Read analysis results
    # Read each analysis_results type, provide empty but well-formed frames if missing
    opportunity_matrix_data = read_analysis_result(
        conn, run_id=run_id, analysis_type="opportunity_matrix"
    )
    opportunity_matrix = _payload_to_dataframe(
        opportunity_matrix_data,
        expected_columns=[
            "cluster_id",
            "label",
            "n_games",
            "demand_z",
            "competition_z",
            "simplicity_z",
            "opportunity_score",
            "median_estimated_sales_mid",
            "median_complexity",
            "releases_in_window",
        ],
    )

    tag_summary_data = read_analysis_result(conn, run_id=run_id, analysis_type="tag_summary")
    tag_summary = _payload_to_dataframe(
        tag_summary_data,
        expected_columns=[
            "tag",
            "n_games",
            "median_complexity_score",
            "median_estimated_sales_mid",
            "median_review_positive_pct",
            "median_price_usd",
        ],
    )

    tag_trends_data = read_analysis_result(conn, run_id=run_id, analysis_type="tag_trends")
    tag_trends = _payload_to_dataframe(
        tag_trends_data,
        expected_columns=["tag", "period", "n_games", "median_review_positive_pct"],
    )

    tag_clusters_data = read_analysis_result(
        conn, run_id=run_id, analysis_type="tag_clusters"
    )
    if tag_clusters_data is None:
        tag_clusters_data = {}
    tag_clusters_assignments = tag_clusters_data.get("assignments", [])
    # Convert assignments list to DataFrame
    if tag_clusters_assignments:
        tag_clusters_df = pd.DataFrame(tag_clusters_assignments)
    else:
        tag_clusters_df = pd.DataFrame(
            columns=["appid", "cluster_id"]
        )

    # Step 6: Build views and select case studies
    # Build opportunity_matrix view
    if len(opportunity_matrix) > 0:
        opportunity_matrix_view = build_opportunity_matrix_view(opportunity_matrix)
    else:
        opportunity_matrix_view = opportunity_matrix

    # Build tag_summary view
    if len(tag_summary) > 0:
        tag_summary_view = build_tag_summary_table(tag_summary)
    else:
        tag_summary_view = tag_summary

    # Select case studies
    enriched = read_enriched(conn, run_id)
    if len(enriched) > 0 and len(tag_clusters_df) > 0:
        selection = select_case_studies(enriched, tag_clusters_df)
    else:
        selection = CaseStudySelection(case_studies=[], archetype_cap_relaxed=False)

    case_studies_list = selection.case_studies

    # Build funnel summary
    funnel_report_data = read_analysis_result(
        conn, run_id=run_id, analysis_type="funnel_report"
    )
    if funnel_report_data is None:
        funnel_report_data = {}

    # funnel_report's "data" sub-object carries catalog_size/candidate_count/
    # detail_fetched/detail_failed (written by acquisition._write_funnel_report)
    # and simple_subset_size (merged in afterward by analysis.run_analysis,
    # once the simplicity filter has actually run) -- see both writers for the
    # exact shape this must match.
    rejected_by_reason = funnel_report_data.get("rejected_by_reason", {})
    funnel_data = funnel_report_data.get("data", {})
    catalog_size = funnel_data.get("catalog_size", 0)
    candidate_count = funnel_data.get("candidate_count", 0)
    detail_fetched = funnel_data.get("detail_fetched", 0)
    detail_failed = funnel_data.get("detail_failed", 0)
    simple_subset_size = funnel_data.get("simple_subset_size", 0)

    funnel = FunnelSummary(
        catalog_size=catalog_size,
        candidate_count=candidate_count,
        detail_fetched=detail_fetched,
        detail_failed=detail_failed,
        simple_subset_size=simple_subset_size,
        rejected_by_reason=rejected_by_reason,
    )

    # Step 7: Build caveats
    caveats = interpretive_caveats()
    if is_partial:
        caveats.append(partial_run_caveat(missing_stages, run_record))
    if selection.archetype_cap_relaxed:
        caveats.append(
            Caveat(
                key="archetype_cap_relaxed",
                title="Case-study diversity cap relaxed",
                body=(
                    "Too few distinct archetypes were available to fill the case-study list "
                    "without repeating one archetype more than the configured cap; the "
                    "per-archetype cap was relaxed by one for this run only."
                ),
                severity="info",
            )
        )

    # Compute headline metrics
    metrics = headline_metrics_impl(
        opportunity_matrix_view, run_record, catalog_size, candidate_count, simple_subset_size
    )

    return RunReport(
        run_id=run_id,
        run=run_record,
        stages=stages,
        missing_stages=missing_stages,
        opportunity_matrix=opportunity_matrix_view,
        tag_summary=tag_summary_view,
        tag_trends=tag_trends,
        case_studies=case_studies_list,
        funnel=funnel,
        headline_metrics=metrics,
        caveats=caveats,
        is_partial=is_partial,
    )


def headline_metrics(report: RunReport) -> dict[str, Any]:
    """Extract a small headline summary from a RunReport.

    Args:
        report: A RunReport.

    Returns:
        {'catalog_size': int, 'candidate_count': int, 'simple_subset_size': int,
         'top_archetype_label': str | None, 'top_opportunity_score': float | None,
         'run_duration_seconds': float | None, 'status': str}.
        top_archetype_label/top_opportunity_score are None when opportunity_matrix
        is empty (no scored archetypes).
        run_duration_seconds is None when the run has not finished (finished_at is None).

    Postconditions:
        Never raises for a RunReport with empty frames; returns None for the fields
        that cannot be computed rather than raising or fabricating a value.
    """
    return headline_metrics_impl(
        report.opportunity_matrix,
        report.run,
        report.funnel.catalog_size,
        report.funnel.candidate_count,
        report.funnel.simple_subset_size,
    )


def headline_metrics_impl(
    opportunity_matrix: pd.DataFrame,
    run_record: RunRecord,
    catalog_size: int,
    candidate_count: int,
    simple_subset_size: int,
) -> dict[str, Any]:
    """Internal implementation of headline metrics extraction.

    Args:
        opportunity_matrix: The display-ready opportunity matrix DataFrame.
        run_record: The RunRecord for status and timing info.
        catalog_size: Total apps in the catalog.
        candidate_count: Apps that survived coarse filter.
        simple_subset_size: Apps that passed simplicity filter.

    Returns:
        Dictionary with headline metrics.
    """
    # Determine top archetype if opportunity_matrix is non-empty
    top_archetype_label = None
    top_opportunity_score = None

    if len(opportunity_matrix) > 0:
        # The opportunity_matrix should be sorted by opportunity_score descending
        # Try both original column name and display name
        opp_col = None
        for col in ["opportunity_score", "Opportunity Score"]:
            if col in opportunity_matrix.columns:
                opp_col = col
                break

        if opp_col is not None:
            top_row = opportunity_matrix.iloc[0]
            # Try both original column name and display name for label
            label_col = None
            for col in ["label", "Archetype"]:
                if col in opportunity_matrix.columns:
                    label_col = col
                    break

            if label_col is not None:
                top_archetype_label = str(top_row[label_col])
            top_opportunity_score = float(top_row[opp_col])

    # Compute run duration if finished
    run_duration_seconds = None
    if run_record.finished_at is not None and run_record.started_at is not None:
        # Handle both timezone-naive and timezone-aware datetimes
        from datetime import timezone as tz
        
        started = run_record.started_at
        finished = run_record.finished_at
        
        # Ensure both are timezone-aware for subtraction
        if started.tzinfo is None:
            started = started.replace(tzinfo=tz.utc)
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=tz.utc)
        
        delta = finished - started
        run_duration_seconds = delta.total_seconds()

    return {
        "catalog_size": catalog_size,
        "candidate_count": candidate_count,
        "simple_subset_size": simple_subset_size,
        "top_archetype_label": top_archetype_label,
        "top_opportunity_score": top_opportunity_score,
        "run_duration_seconds": run_duration_seconds,
        "status": run_record.status,
    }


def _payload_to_dataframe(
    payload: dict | None, expected_columns: list[str]
) -> pd.DataFrame:
    """Convert analysis_result payload to a DataFrame.

    Args:
        payload: The deserialized analysis_result payload (or None if missing).
        expected_columns: Expected column names for validation.

    Returns:
        A DataFrame with the expected columns. If payload is None or has no 'data',
        returns an empty DataFrame with the expected columns.
    """
    if payload is None:
        return pd.DataFrame(columns=expected_columns)

    # Extract data field (most payloads have a 'data' key with list of records)
    data = payload.get("data", [])
    if not data:
        return pd.DataFrame(columns=expected_columns)

    # Convert to DataFrame
    df = pd.DataFrame(data)

    # Ensure all expected columns exist, filling missing ones with NaN
    for col in expected_columns:
        if col not in df.columns:
            df[col] = float("nan")

    return df
