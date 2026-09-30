"""Display formatting and presentation layer for reporting."""

from .case_studies import (
    CaseStudy,
    build_rationale,
    interpretive_caveats,
    select_case_studies,
)
from .report import (
    RunReport,
    headline_metrics,
    is_partial_run,
    load_run_report,
    partial_run_caveat,
)
from .types import Caveat, CaseStudySelection, FunnelSummary, ReportNotAvailable
from .views import build_opportunity_matrix_view, build_tag_summary_table

__all__ = [
    "FunnelSummary",
    "Caveat",
    "CaseStudySelection",
    "ReportNotAvailable",
    "build_opportunity_matrix_view",
    "build_tag_summary_table",
    "CaseStudy",
    "build_rationale",
    "interpretive_caveats",
    "select_case_studies",
    "RunReport",
    "is_partial_run",
    "partial_run_caveat",
    "load_run_report",
    "headline_metrics",
]
