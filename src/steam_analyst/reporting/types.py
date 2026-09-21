"""
Reporting module types: caveats, case study selection, availability markers, and funnel summaries.

This module defines the small, logic-free types used across the reporting pipeline:
- Caveat: An interpretive caveat tied to a known limitation.
- CaseStudySelection: The return type of select_case_studies, bundling a ranked list with metadata.
- ReportNotAvailable: Exception raised when a run_id does not exist.
- FunnelSummary: Funnel metrics (catalog size, coarse filter rejects, simple subset).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steam_analyst.reporting.case_studies import CaseStudy


@dataclass(frozen=True)
class Caveat:
    """One fixed interpretive caveat tied to a known limitation.

    Caveats mirror ARCHITECTURE.md 'Known Limitations' items 1-7, plus the
    dynamic 'archetype_cap_relaxed' caveat that select_case_studies may trigger.

    Attributes:
        key: Stable identifier (e.g., 'steamspy_owner_confidence', 'boxleiter_approximation').
             These keys are never renamed across code versions, since the UI may
             persist or reference them by key.
        title: Human-readable title for the caveat (shown in the UI).
        body: Full explanatory text of the caveat.
        severity: One of {'info', 'warning'}. The method-level limitations are all
                  informational rather than error-level; a severity of 'error' is not
                  produced by interpretive_caveats in v1.
    """
    key: str
    title: str
    body: str
    severity: str


@dataclass(frozen=True)
class CaseStudySelection:
    """Return type of select_case_studies, bundling ranked case studies with metadata.

    Attributes:
        case_studies: The ranked, diversity-capped list of case studies selected
                      for display.
        archetype_cap_relaxed: Boolean flag recording whether the one-time
                               max_per_archetype+1 relaxation fired during selection.
                               When True, load_run_report appends an extra
                               Caveat(key='archetype_cap_relaxed') to the report.
    """
    case_studies: list["CaseStudy"]
    archetype_cap_relaxed: bool


class ReportNotAvailable(Exception):
    """Raised when load_run_report is called with a run_id that does not exist.

    This exception is raised only when storage.get_run returns None,
    i.e., the run_id itself is unknown. A run that exists but has no
    analysis results yet is handled as a partial run, not an exception.

    The exception message names the run_id that was not found.
    """

    pass


@dataclass(frozen=True)
class FunnelSummary:
    """Presentation-ready funnel summary for one run.

    Exposes the coarse filter's hard boundary and per-app fetch coverage,
    making both visible in the UI per ARCHITECTURE.md limitation 7 and ADR-016.

    Attributes:
        catalog_size: Total apps in the Steam catalog at acquisition time
                      (from acquisition.FunnelResult.total_input, persisted via
                      storage.write_analysis_result in run_acquisition).
        candidate_count: Number of apps that survived the coarse filter
                         (acquisition.FunnelResult.candidate_count).
        detail_fetched: Number of candidate apps for which appdetails and
                        review-summary fetches succeeded.
        detail_failed: Number of candidate apps for which per-app fetches failed.
                       A large detail_failed relative to candidate_count signals
                       a degraded but still 'succeeded' acquisition.
        simple_subset_size: Number of candidates that passed the simplicity filter
                            (analysis.AnalysisReport.simple_subset_size).
        rejected_by_reason: Rejection counts per reason, with stage-specific prefix
                            keys (e.g., 'coarse_filter.review_count_below_floor' vs
                            'simplicity_filter.above_simplicity_threshold') so the
                            two funnel stages are not conflated.
    """
    catalog_size: int
    candidate_count: int
    detail_fetched: int
    detail_failed: int
    simple_subset_size: int
    rejected_by_reason: dict[str, int]
