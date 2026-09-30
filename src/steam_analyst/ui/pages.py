"""Streamlit page renderers for the Steam Analyst UI.

This module contains the five page-rendering functions that compose the
three-page navigation: Run New Analysis, Past Analyses, and Analysis Detail.
Each function is called by the three-page navigation in main() and receives
either a connection opened by the caller (main's short-lived context) or
opens its own connection (render_progress_panel as a fragment).

Key principles:
- No database connection is cached or reused across reruns (ADR-017).
- No SQL, HTTP, or computation happens here; all logic is in reporting/orchestration.
- Session state is limited to SESSION_KEYS only: active_run_id, last_event_id, event_log.
- The form exposes only PipelineConfig fields; FORMULATION.md-governed values
  are never editable from the UI.
- Every surface showing a revenue or complexity figure also renders the caveat panel.
"""

import sqlite3
from pathlib import Path
from typing import Sequence

import streamlit as st

from steam_analyst.config import Settings
from steam_analyst import orchestration, reporting, storage
from .session import SESSION_KEYS


def render_caveat_panel(caveats: Sequence[reporting.Caveat]) -> None:
    """Render a fixed expander listing every caveat.

    Args:
        caveats: Typically reporting.interpretive_caveats() plus, when applicable,
            reporting.partial_run_caveat(...) and the 'archetype_cap_relaxed' caveat
            already appended by reporting.load_run_report.

    Behavior:
        - An st.expander (collapsed by default, so it does not dominate the page,
          but always present and always labeled clearly).
        - Each Caveat rendered with its title, body, and a visual marker for severity.
        - Order: caveats are rendered in the order given, not re-sorted.
    """
    severity_icons = {"info": "ℹ️", "warning": "⚠️", "error": "❌"}
    caveat_count = len(caveats)
    with st.expander(f"Methodology notes and limitations ({caveat_count})"):
        if not caveats:
            st.write("No caveats to display.")
        else:
            for caveat in caveats:
                icon = severity_icons.get(caveat.severity, "ℹ️")
                st.write(f"**{icon} {caveat.title}**")
                st.write(caveat.body)


def render_new_analysis_page(conn: sqlite3.Connection, settings: Settings) -> None:
    """Render the run-trigger page.

    Args:
        conn: This page's own short-lived connection, opened by main/build_navigation's
            dispatch for this rerun only.
        settings: Loaded once in main and passed down.

    Behavior:
        - Shows the current parameters_version read-only, with a note that
          FORMULATION.md is where the actual values live.
        - A form exposing exactly PipelineConfig's fields: max_catalog_pages,
          request_budget_override, notes. start_stage is NOT exposed here.
        - The Start button is disabled while orchestration.active_run_ids() is
          non-empty (ADR-001: only one writer).
        - On Start: config = PipelineConfig(**form values); run_id =
          orchestration.start_pipeline_async(settings.db_path, config,
          settings=settings); sets st.session_state['active_run_id'], etc.
        - If st.session_state['active_run_id'] is set, render_progress_panel
          is called below the form.
    """
    st.header("Run New Analysis")

    # Display parameters_version read-only
    from steam_analyst.config.parameters import parameters_version

    current_version = parameters_version(settings.parameters_path)
    st.info(
        f"**Parameters version:** {current_version}\n\n"
        "All parameter values are defined in FORMULATION.md and cannot be edited "
        "from this UI. Only the run-specific overrides below may be customized."
    )

    # Check if a run is already active
    active_runs = orchestration.active_run_ids()
    can_start = len(active_runs) == 0

    # Form for PipelineConfig fields
    st.subheader("Configuration")
    with st.form("new_analysis_form"):
        max_catalog_pages = st.number_input(
            "Max Catalog Pages (optional)",
            min_value=1,
            value=None,
            help="Limit catalog fetch to this many pages (for smoke tests)",
        )
        request_budget_override = st.number_input(
            "Request Budget Override (optional)",
            min_value=1,
            value=None,
            help="Override the request budget limit",
        )
        notes = st.text_area(
            "Notes (optional)",
            value="",
            help="Internal notes for this run",
        )

        start_disabled_reason = None
        if not can_start:
            start_disabled_reason = (
                f"A run is already active (ADR-001 supports only one writer). "
                f"Wait for it to finish or cancel it from the Past Analyses page."
            )

        submitted = st.form_submit_button(
            "Start New Analysis",
            disabled=not can_start,
            help=start_disabled_reason or "Start the acquisition pipeline",
        )

        if submitted and can_start:
            try:
                # Build config from form values
                config = orchestration.PipelineConfig(
                    max_catalog_pages=max_catalog_pages if max_catalog_pages else None,
                    request_budget_override=request_budget_override
                    if request_budget_override
                    else None,
                    notes=notes if notes else None,
                    start_stage=orchestration.PipelineStage.ACQUISITION,
                )

                # Start the pipeline
                run_id = orchestration.start_pipeline_async(
                    settings.db_path, config, settings=settings
                )

                # Initialize session state
                st.session_state["active_run_id"] = run_id
                st.session_state["last_event_id"] = 0
                st.session_state["event_log"] = []

                st.success(f"Started run: {run_id}")
            except Exception as e:
                st.error(f"Failed to start pipeline: {e}")

    # Render progress panel if a run is active
    if st.session_state.get("active_run_id"):
        st.divider()
        render_progress_panel(settings.db_path, st.session_state["active_run_id"])


@st.fragment(run_every="2s")
def render_progress_panel(db_path: Path, run_id: str) -> None:
    """Render live progress for one run and poll for updates.

    Args:
        db_path: Opens its own short-lived connection inside this fragment call,
            per ADR-017.
        run_id: The run being watched.

    Behavior:
        - Opens connection, reads run, stages, and new events since last_event_id.
        - Updates session state event_log and advances last_event_id.
        - Renders stage list with status and latest progress value.
        - Cancel button disabled once clicked this session.
        - When run reaches terminal status, stops polling and calls st.rerun().
    """
    # Initialize session state if needed
    if "last_event_id" not in st.session_state:
        st.session_state["last_event_id"] = 0
    if "event_log" not in st.session_state:
        st.session_state["event_log"] = []
    if "_cancel_requested" not in st.session_state:
        st.session_state["_cancel_requested"] = False

    try:
        with storage.connect(db_path) as conn:
            run = storage.get_run(conn, run_id)
            if run is None:
                st.warning(f"Run {run_id} no longer found in database.")
                return

            stages = storage.read_run_stages(conn, run_id)
            new_events = storage.read_run_events(
                conn, run_id, since_event_id=st.session_state["last_event_id"]
            )

        # Update session state with new events
        if new_events:
            st.session_state["event_log"].extend(new_events)
            st.session_state["last_event_id"] = new_events[-1].event_id

    except Exception as e:
        st.error(f"Error reading run progress: {e}")
        return

    # Render stage status
    st.subheader("Pipeline Progress")
    stage_names = {"acquisition": "Acquisition", "enrichment": "Enrichment", "analysis": "Analysis"}
    for stage in stages:
        status_emoji = {"pending": "⏳", "running": "▶️", "succeeded": "✅", "failed": "❌"}[
            stage.status
        ]
        st.write(f"{status_emoji} {stage_names.get(stage.stage, stage.stage)}: {stage.status}")

    # Render latest progress from event log
    if st.session_state["event_log"]:
        latest_event = st.session_state["event_log"][-1]
        if latest_event.progress_value is not None:
            st.info(f"**Latest Progress:** {latest_event.progress_value}")

    # Render recent events (with bounded tail for long runs)
    st.subheader("Event Log")
    event_log = st.session_state["event_log"]
    if len(event_log) > 20:
        with st.expander(f"Full log ({len(event_log)} events)"):
            for event in event_log:
                st.write(f"{event.event_id}: {event.message}")
        st.write("**Recent events (last 20):**")
        for event in event_log[-20:]:
            st.write(f"{event.event_id}: {event.message}")
    else:
        for event in event_log:
            st.write(f"{event.event_id}: {event.message}")

    # Cancel button
    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Cancel Run",
            disabled=st.session_state["_cancel_requested"],
            key="cancel_button",
        ):
            st.session_state["_cancel_requested"] = True
            try:
                orchestration.cancel_run(run_id)
                st.info("Cancellation requested. The run may take a moment to stop.")
            except Exception as e:
                st.error(f"Failed to cancel run: {e}")

    # Check if terminal status reached
    if run.status in ("succeeded", "failed", "cancelled"):
        st.success(f"Run finished with status: {run.status}")
        st.rerun()


def render_past_analyses_page(conn: sqlite3.Connection, settings: Settings) -> None:
    """Render the list of past and current runs.

    Args:
        conn: This page's own short-lived connection.
        settings: For settings.db_path, passed to button actions.

    Behavior:
        - Table with run_id, started_at, status, stage completion, metrics, duration.
        - Per row: Open (sets query_params['run_id']), Resume (only for non-succeeded,
          non-active runs), Delete (with 2-step confirmation).
    """
    st.header("Past Analyses")

    try:
        runs_df = storage.list_runs(conn, limit=50)
    except Exception as e:
        st.error(f"Failed to load runs: {e}")
        return

    if runs_df.empty:
        st.info("No runs found.")
        return

    # Display the runs table
    st.subheader("Runs")
    active_run_ids = orchestration.active_run_ids()

    for idx, row in runs_df.iterrows():
        run_id = row["run_id"]
        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 2, 2])

            with col1:
                st.write(f"**Run ID:** {run_id}")
                st.write(f"**Started:** {row['started_at']}")
                st.write(f"**Status:** {row['status']}")
                if "candidate_count" in row and row["candidate_count"]:
                    st.write(f"**Candidates:** {row['candidate_count']}")

            with col2:
                st.write("**Stages:**")
                if "stage_completion" in row and row["stage_completion"]:
                    st.write(row["stage_completion"])
                if "duration" in row and row["duration"]:
                    st.write(f"**Duration:** {row['duration']}")

            with col3:
                st.write("**Actions:**")
                # Open button
                if st.button("Open", key=f"open_{run_id}"):
                    st.query_params["run_id"] = run_id

                # Resume button (only for non-succeeded, non-active runs)
                if row["status"] != "succeeded" and run_id not in active_run_ids:
                    if st.button("Resume", key=f"resume_{run_id}"):
                        try:
                            resume_run_id = orchestration.resume_run(
                                settings.db_path, run_id, settings=settings
                            )
                            st.session_state["active_run_id"] = resume_run_id
                            st.session_state["last_event_id"] = 0
                            st.session_state["event_log"] = []
                            st.success(f"Resumed run: {resume_run_id}")
                        except orchestration.PipelineError as e:
                            st.warning(f"Failed to resume: {e}")

                # Delete button with confirmation
                delete_key = f"delete_{run_id}"
                confirm_key = f"confirm_delete_{run_id}"

                if delete_key not in st.session_state:
                    st.session_state[delete_key] = False
                if confirm_key not in st.session_state:
                    st.session_state[confirm_key] = False

                if not st.session_state[delete_key]:
                    if st.button("Delete", key=f"delete_btn_{run_id}"):
                        st.session_state[delete_key] = True
                        st.rerun()
                else:
                    if not st.session_state[confirm_key]:
                        st.warning(f"Confirm deletion of run {run_id}?")
                        if st.button("Yes, Delete", key=f"yes_delete_{run_id}"):
                            st.session_state[confirm_key] = True
                            st.rerun()
                        if st.button("Cancel", key=f"cancel_delete_{run_id}"):
                            st.session_state[delete_key] = False
                            st.rerun()
                    else:
                        try:
                            storage.delete_run(conn, run_id)
                            st.success(f"Deleted run {run_id}")
                            st.session_state[delete_key] = False
                            st.session_state[confirm_key] = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to delete run: {e}")
                            st.session_state[delete_key] = False
                            st.session_state[confirm_key] = False


def render_analysis_detail_page(conn: sqlite3.Connection, settings: Settings) -> None:
    """Render one run's results.

    Args:
        conn: This page's own short-lived connection.
        settings: For settings.db_path, kept for signature consistency.

    Behavior:
        - Read run_id from query_params; show empty state if missing/unknown.
        - Load report once, render caveat panel, results, and progress if running.
        - Show 'not enough data' message for empty candidate sets.
    """
    run_id = st.query_params.get("run_id")

    if not run_id:
        st.header("Analysis Detail")
        st.info("No run selected. Please select a run from Past Analyses.")
        if st.button("Go to Past Analyses"):
            st.query_params.clear()
        return

    try:
        report = reporting.load_run_report(conn, run_id)
    except reporting.ReportNotAvailable:
        st.header("Analysis Detail")
        st.warning(f"Run {run_id} not found.")
        if st.button("Go to Past Analyses"):
            st.query_params.clear()
        return
    except Exception as e:
        st.error(f"Failed to load report: {e}")
        return

    st.header(f"Analysis Detail: {run_id}")

    # Render caveats near the top
    render_caveat_panel(report.caveats)

    # If partial, show partial_run_caveat and progress panel if running
    if report.is_partial:
        partial_caveat = reporting.partial_run_caveat(
            report.missing_stages, report.run
        )
        st.warning(
            f"**{partial_caveat.title}**\n\n{partial_caveat.body}"
        )

        if report.run.status == "running":
            st.divider()
            render_progress_panel(settings.db_path, run_id)

    # Render results
    st.divider()
    st.subheader("Results")

    # Check for empty candidate set
    if report.funnel.candidate_count == 0:
        st.info(
            "**Not enough data**: No games passed the coarse filter. "
            "Try adjusting the filter criteria or running a larger catalog scan."
        )
        return

    # Check if simplicity subset is too small
    if report.funnel.simple_subset_size == 0:
        st.info(
            "**Not enough data**: No games passed the simplicity filter. "
            "The candidate set may not contain games matching the target archetype complexity."
        )
        return

    # Opportunity matrix
    st.subheader("Opportunity Matrix")
    try:
        st.dataframe(report.opportunity_matrix)
    except Exception as e:
        st.warning(f"Could not render opportunity matrix: {e}")

    # Tag summary
    st.subheader("Tag Summary")
    try:
        st.dataframe(report.tag_summary)
    except Exception as e:
        st.warning(f"Could not render tag summary: {e}")

    # Tag trends
    st.subheader("Tag Trends")
    try:
        st.dataframe(report.tag_trends)
    except Exception as e:
        st.warning(f"Could not render tag trends: {e}")

    # Case studies
    st.subheader("Case Studies")
    if not report.case_studies:
        st.info("No case studies available.")
    else:
        for case_study in report.case_studies:
            with st.expander(f"{case_study.app_name} (app_id={case_study.app_id})"):
                if case_study.rationale:
                    st.write(f"**Rationale:** {case_study.rationale}")
                if case_study.archetype:
                    st.write(f"**Archetype:** {case_study.archetype}")
                if hasattr(case_study, 'complexity_drivers') and case_study.complexity_drivers:
                    st.write(f"**Complexity Drivers:** {case_study.complexity_drivers}")

    # Funnel visualization
    st.subheader("Funnel Summary")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Catalog Size", report.funnel.catalog_size)
    with col2:
        st.metric("Candidates", report.funnel.candidate_count)
    with col3:
        st.metric("Simple Subset", report.funnel.simple_subset_size)
