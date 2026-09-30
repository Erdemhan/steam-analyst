"""Analysis stage: simplicity filtering, clustering, demand/competition measurement, and opportunity scoring."""

from steam_analyst.analysis.clustering import (
    TagClusterResult,
    cluster_tags,
    compute_jaccard_tag_distance,
    label_cluster,
)
from steam_analyst.analysis.errors import AnalysisError
from steam_analyst.analysis.pipeline import AnalysisReport, run_analysis
from steam_analyst.analysis.scoring import (
    build_opportunity_matrix,
    build_tag_summary,
    compute_competition_density,
    compute_demand,
    compute_zscore,
)
from steam_analyst.analysis.simplicity import apply_simplicity_filter
from steam_analyst.analysis.trends import compute_tag_trends

__all__ = [
    "AnalysisError",
    "apply_simplicity_filter",
    "TagClusterResult",
    "cluster_tags",
    "compute_jaccard_tag_distance",
    "label_cluster",
    "compute_tag_trends",
    "compute_zscore",
    "compute_demand",
    "compute_competition_density",
    "build_opportunity_matrix",
    "build_tag_summary",
    "AnalysisReport",
    "run_analysis",
]
