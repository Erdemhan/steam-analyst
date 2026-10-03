"""Parameter loading, validation, and versioning.

Loads, validates and exposes all tunable parameters from config/parameters.toml
as typed dataclass instances. Provides stable content hashing for traceability.
"""

from datetime import date
from pathlib import Path
from typing import Any
import hashlib
import sys

# Use tomllib for Python 3.11+, tomli for earlier versions
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        raise ImportError(
            "tomli is required for Python < 3.11. "
            "Install it with: pip install tomli"
        )


class ParameterError(Exception):
    """Configuration/parameter validation failure.

    Raised for any invalid or missing configuration value encountered by
    load_settings, validate_parameters or load_parameters. The single error
    type all of config's fallible entry points raise, so callers (orchestration's
    startup assertion, scripts/verify_parameters_consistency.py) can catch one
    exception type.

    Attributes:
        message: Human-readable, English-language description of what was wrong.
        path: The file the error pertains to, if applicable (e.g. the missing or
            malformed parameters.toml).
        key: The dotted section.key path of the offending value, if applicable
            (e.g. 'enrichment.storefront_cut').
    """

    def __init__(
        self, message: str, *, path: Path | None = None, key: str | None = None
    ) -> None:
        """Initialize ParameterError with message and optional context.

        Args:
            message: Human-readable description of what was wrong.
            path: The file the error pertains to, if applicable.
            key: The dotted section.key path of the offending value, if applicable.
        """
        self.message = message
        self.path = path
        self.key = key
        super().__init__(str(self))

    def __str__(self) -> str:
        """Render error with all available context in a single readable line.

        Returns:
            A string including message, and path/key when provided.
        """
        if self.path is None and self.key is None:
            return self.message
        if self.path is not None and self.key is not None:
            return f"{self.message} ({self.path}: {self.key})"
        if self.path is not None:
            return f"{self.message} ({self.path})"
        return f"{self.message} ({self.key})"


def validate_parameters(raw: dict[str, Any]) -> None:
    """Validate the raw parsed contents of parameters.toml.

    Validates every invariant required by config's three parameter dataclasses
    before they are constructed. Factored out of load_parameters as its own
    function so each invalid-input case can be exercised directly against a
    plain dict fixture in tests, without needing a full TOML file per case.

    Args:
        raw: The dict produced by tomllib.load on config/parameters.toml (or an
            equivalent in-memory fixture dict in tests).

    Returns:
        None if every check passes.

    Raises:
        ParameterError: On the first violated invariant, with a message naming
            the offending section/key and the actual value. Checks run in a
            fixed order (missing section -> missing key -> out-of-range value ->
            weights-sum -> ordering) so error messages are deterministic.
    """
    # Check required top-level sections
    required_sections = ["acquisition", "enrichment", "analysis"]
    for section in required_sections:
        if section not in raw:
            raise ParameterError(f"missing section: {section}")

    # --- ACQUISITION VALIDATION ---
    acq = raw["acquisition"]
    acq_required_keys = [
        "steamspy_page_delay_seconds",
        "steam_requests_per_minute",
        "max_retries",
        "backoff_base_seconds",
        "backoff_max_seconds",
        "request_budget",
        "coarse_filter",
    ]
    for key in acq_required_keys:
        if key not in acq:
            raise ParameterError(f"missing key: acquisition.{key}")

    # Validate coarse_filter subsection
    cf = acq["coarse_filter"]
    cf_required_keys = [
        "min_review_count",
        "earliest_release_date",
        "include_free_to_play",
        "publisher_blocklist",
    ]
    for key in cf_required_keys:
        if key not in cf:
            raise ParameterError(f"missing key: acquisition.coarse_filter.{key}")

    # Note: max_review_count and latest_release_date are optional for coarse_filter
    # (no special handling needed, just don't require them)

    # --- ENRICHMENT VALIDATION ---
    enr = raw["enrichment"]

    # Check for enrichment subsections
    enr_subsections = ["boxleiter_multipliers", "genre_bucket_map", "revenue", "complexity_weights", "complexity_tags", "effort", "tag_extraction"]
    for subsection in enr_subsections:
        if subsection not in enr:
            raise ParameterError(f"missing section: enrichment.{subsection}")

    # Validate boxleiter_multipliers
    box = enr["boxleiter_multipliers"]
    bucket_names = ["niche", "mainstream", "broad_audience"]
    for bucket in bucket_names:
        if bucket not in box:
            raise ParameterError(
                f"missing bucket in enrichment.boxleiter_multipliers: {bucket}"
            )
        triple = box[bucket]
        if len(triple) != 3:
            raise ParameterError(
                f"multiplier triple for {bucket} has {len(triple)} values, expected 3"
            )
        low, mid, high = triple
        if not (low <= mid <= high):
            raise ParameterError(
                f"unordered multiplier triple for {bucket}: {triple} "
                f"(expected m_low <= m_mid <= m_high)"
            )

    # Validate genre_bucket_map (no specific validation, just presence)
    # (it's a dict that may be extended, so we don't validate bucket values here)

    # Validate revenue section
    rev = enr["revenue"]
    rev_required_keys = ["storefront_cut", "discount_factor", "refund_regional_factor"]
    for key in rev_required_keys:
        if key not in rev:
            raise ParameterError(f"missing key: enrichment.revenue.{key}")

    # Validate ratio values are in [0, 1]
    for key in ["storefront_cut", "discount_factor", "refund_regional_factor"]:
        val = rev[key]
        if not (0 <= val <= 1):
            raise ParameterError(
                f"out of range [0,1]: enrichment.revenue.{key}={val}"
            )

    # Validate complexity_weights
    weights = enr["complexity_weights"]
    expected_weight_keys = [
        "size_bytes",
        "ram_bytes",
        "early_access_days",
        "dev_title_count",
        "simplicity_tag_score",
        "complexity_tag_score",
        "achievement_count",
        "dlc_count",
        "platform_count",
        "language_count",
    ]
    for key in expected_weight_keys:
        if key not in weights:
            raise ParameterError(f"missing key: enrichment.complexity_weights.{key}")

    # Check weights sum to 1.0 (with small tolerance for floating point)
    weight_sum = sum(weights.values())
    if abs(weight_sum - 1.0) > 1e-6:
        raise ParameterError(
            f"complexity_weights sum to {weight_sum}, expected 1.0"
        )

    # Validate complexity_tags
    ctags = enr["complexity_tags"]
    if "simplicity_tags" not in ctags:
        raise ParameterError("missing key: enrichment.complexity_tags.simplicity_tags")
    if "complexity_tags" not in ctags:
        raise ParameterError("missing key: enrichment.complexity_tags.complexity_tags")

    # complexity_bounds is optional (unset until run 1)
    # (no validation needed if absent)

    # Validate effort section
    eff = enr["effort"]
    if "epsilon" not in eff:
        raise ParameterError("missing key: enrichment.effort.epsilon")

    # Validate tag_extraction section
    tag_ext = enr["tag_extraction"]
    for key in ["max_per_game", "min_votes"]:
        if key not in tag_ext:
            raise ParameterError(f"missing key: enrichment.tag_extraction.{key}")
    if tag_ext["max_per_game"] < 1:
        raise ParameterError(
            f"enrichment.tag_extraction.max_per_game must be >= 1, got {tag_ext['max_per_game']}"
        )
    if tag_ext["min_votes"] < 0:
        raise ParameterError(
            f"enrichment.tag_extraction.min_votes must be >= 0, got {tag_ext['min_votes']}"
        )

    # --- ANALYSIS VALIDATION ---
    ana = raw["analysis"]
    ana_required_keys = [
        "simplicity_percentile",
        "clustering_linkage",
        "trailing_window_months",
        "min_cluster_size",
        "min_tag_votes",
        "max_tags_per_game",
        "generic_tag_max_share",
        "opportunity_weights",
    ]
    for key in ana_required_keys:
        if key not in ana:
            raise ParameterError(f"missing key: analysis.{key}")

    # Validate simplicity_percentile is in (0, 1]
    sp = ana["simplicity_percentile"]
    if not (0 < sp <= 1):
        raise ParameterError(
            f"out of range (0,1]: analysis.simplicity_percentile={sp}"
        )

    # Validate generic_tag_max_share is in (0, 1]
    gts = ana["generic_tag_max_share"]
    if not (0 < gts <= 1):
        raise ParameterError(
            f"out of range (0,1]: analysis.generic_tag_max_share={gts}"
        )

    # Validate clustering_linkage is a known method
    cl = ana["clustering_linkage"]
    valid_linkages = ["single", "complete", "average", "weighted"]
    if cl not in valid_linkages:
        raise ParameterError(f"invalid clustering_linkage: {cl}")

    # Validate opportunity_weights
    opp_weights = ana["opportunity_weights"]
    expected_opp_keys = ["demand", "competition", "simplicity"]
    for key in expected_opp_keys:
        if key not in opp_weights:
            raise ParameterError(
                f"missing key: analysis.opportunity_weights.{key}"
            )

    # Check opportunity weights sum to 1.0
    opp_sum = sum(opp_weights.values())
    if abs(opp_sum - 1.0) > 1e-6:
        raise ParameterError(
            f"opportunity_weights sum to {opp_sum}, expected 1.0"
        )

    # Note: tag_distance_threshold is optional (None until run 1)


def parameters_version(path: Path) -> str:
    """Compute a stable content hash for the parameter file.

    Generates a short (first 12 hex characters), deterministic sha256 hash of
    the file's raw bytes. Using raw bytes rather than a re-serialization of
    the parsed dict means the hash also changes on a whitespace-only or
    comment-only edit, which is the more conservative (safer to
    over-invalidate) choice for traceability.

    Args:
        path: Absolute path to config/parameters.toml.

    Returns:
        A short (first 12 hex characters) deterministic sha256 hash of the
        file's raw bytes.

    Raises:
        ParameterError: If path does not exist or is not readable.
    """
    try:
        with open(path, "rb") as f:
            content = f.read()
    except FileNotFoundError as e:
        raise ParameterError(
            f"parameters file not found: {path}"
        ) from e
    except OSError as e:
        raise ParameterError(
            f"cannot read parameters file: {path}"
        ) from e

    # Compute sha256 hash and return first 12 hex characters
    full_hash = hashlib.sha256(content).hexdigest()
    return full_hash[:12]


def load_parameters(path: Path) -> tuple:
    """Load and validate the machine-readable mirror of FORMULATION.md.

    Parses config/parameters.toml with tomllib, validates it via
    validate_parameters, and constructs the three typed parameter dataclasses
    consumed by acquisition, enrichment and analysis.

    Args:
        path: Absolute path to config/parameters.toml (typically
            Settings.parameters_path).

    Returns:
        A (AcquisitionConfig, EnrichmentParams, AnalysisParams) tuple, fully
        validated.

    Raises:
        ParameterError: On a missing file, missing section/key, an out-of-range
            value, a weight set that does not sum to 1, or an unordered
            multiplier triple -- delegated to validate_parameters for
            everything past the missing-file check.
    """
    # Import here to avoid circular imports
    from steam_analyst.config.settings import (
        AcquisitionConfig,
        CoarseFilterCriteria,
        EnrichmentParams,
        AnalysisParams,
    )

    # Load the TOML file
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError as e:
        raise ParameterError(
            f"parameters file not found: {path}"
        ) from e
    except Exception as e:
        # Catch both tomllib.TOMLDecodeError and tomli.TOMLDecodeError
        if "TOMLDecodeError" in type(e).__name__:
            raise ParameterError(
                f"invalid TOML syntax in {path}: {e}"
            ) from e
        raise

    # Validate the raw dict
    validate_parameters(raw)

    # Extract sections
    acq_raw = raw["acquisition"]
    enr_raw = raw["enrichment"]
    ana_raw = raw["analysis"]

    # Build CoarseFilterCriteria
    cf_raw = acq_raw["coarse_filter"]
    earliest_date_str = cf_raw.get("earliest_release_date")
    earliest_date = (
        date.fromisoformat(earliest_date_str)
        if earliest_date_str
        else None
    )
    latest_date_str = cf_raw.get("latest_release_date")
    latest_date = (
        date.fromisoformat(latest_date_str)
        if latest_date_str
        else None
    )

    coarse_filter = CoarseFilterCriteria(
        min_review_count=cf_raw["min_review_count"],
        max_review_count=cf_raw.get("max_review_count"),  # Optional by design
        earliest_release_date=earliest_date,
        latest_release_date=latest_date,
        include_free_to_play=cf_raw["include_free_to_play"],
        max_price_usd=cf_raw.get("max_price_usd"),
        publisher_blocklist=cf_raw["publisher_blocklist"],
    )

    # Build AcquisitionConfig
    acquisition_config = AcquisitionConfig(
        steamspy_page_delay_seconds=acq_raw["steamspy_page_delay_seconds"],
        steam_requests_per_minute=acq_raw["steam_requests_per_minute"],
        max_retries=acq_raw["max_retries"],
        backoff_base_seconds=acq_raw["backoff_base_seconds"],
        backoff_max_seconds=acq_raw["backoff_max_seconds"],
        request_budget=acq_raw["request_budget"],
        coarse_filter=coarse_filter,
    )

    # Build EnrichmentParams
    # Convert boxleiter_multipliers lists to tuples
    box_mult = {}
    for bucket, triple in enr_raw["boxleiter_multipliers"].items():
        box_mult[bucket] = tuple(triple)

    enrichment_params = EnrichmentParams(
        boxleiter_multipliers=box_mult,
        genre_bucket_map=enr_raw["genre_bucket_map"],
        storefront_cut=enr_raw["revenue"]["storefront_cut"],
        discount_factor=enr_raw["revenue"]["discount_factor"],
        refund_regional_factor=enr_raw["revenue"]["refund_regional_factor"],
        complexity_weights=enr_raw["complexity_weights"],
        complexity_bounds=enr_raw.get("complexity_bounds", {}),  # Optional
        simplicity_tags=enr_raw["complexity_tags"]["simplicity_tags"],
        complexity_tags=enr_raw["complexity_tags"]["complexity_tags"],
        effort_epsilon=enr_raw["effort"]["epsilon"],
        tag_extraction_max_per_game=enr_raw["tag_extraction"]["max_per_game"],
        tag_extraction_min_votes=enr_raw["tag_extraction"]["min_votes"],
    )

    # Build AnalysisParams
    analysis_params = AnalysisParams(
        simplicity_percentile=ana_raw["simplicity_percentile"],
        trailing_window_months=ana_raw["trailing_window_months"],
        min_cluster_size=ana_raw["min_cluster_size"],
        opportunity_weights=ana_raw["opportunity_weights"],
        min_tag_votes=ana_raw["min_tag_votes"],
        max_tags_per_game=ana_raw["max_tags_per_game"],
        tag_distance_threshold=ana_raw.get("tag_distance_threshold"),  # Optional by design
        clustering_linkage=ana_raw["clustering_linkage"],
        generic_tag_max_share=ana_raw["generic_tag_max_share"],
    )

    return (acquisition_config, enrichment_params, analysis_params)
