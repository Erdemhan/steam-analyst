"""Enrichment stage: normalize raw payloads and compute derived features."""

from .complexity import compute_complexity_score
from .errors import EnrichmentError
from .features import (
    compute_developer_catalog_size,
    compute_tag_score,
    impute_missing_at_median,
    normalize_feature_log_scaled,
)
from .parsing import RawBundle, extract_tags, normalize_features, parse_raw_bundle
from .pipeline import EnrichmentReport, build_enriched_frame, run_enrichment
from .revenue import (
    compute_effort_adjusted_return,
    estimate_revenue,
    estimate_sales,
    map_genre_bucket,
)

__all__ = [
    "EnrichmentError",
    "RawBundle",
    "extract_tags",
    "normalize_features",
    "parse_raw_bundle",
    "compute_complexity_score",
    "compute_developer_catalog_size",
    "compute_tag_score",
    "impute_missing_at_median",
    "normalize_feature_log_scaled",
    "map_genre_bucket",
    "estimate_sales",
    "estimate_revenue",
    "compute_effort_adjusted_return",
    "EnrichmentReport",
    "build_enriched_frame",
    "run_enrichment",
]
