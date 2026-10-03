"""Empirical parameter freezing for FORMULATION.md sections 4, 6, and 8.

Reads a completed run's games_enriched and game_tags data to compute the
empirical complexity-score normalization bounds and tag-clustering distance-cut
threshold that FORMULATION.md locks as 'derived from the first completed run'.
Per ADR-012, this script does NOT edit FORMULATION.md itself (that file is
user-locked); instead, it prints the exact text for a human to paste into both
sections 4/6 (prose record) and section 8 (machine-readable toml block).
"""

import argparse
import dataclasses
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from steam_analyst.analysis.clustering import cluster_tags
from steam_analyst.analysis.simplicity import apply_simplicity_filter
from steam_analyst.config.parameters import ParameterError, validate_parameters
from steam_analyst.config.settings import AnalysisParams
from steam_analyst.storage import get_run, read_enriched, read_tags


# Log-scaled features from FORMULATION.md section 4's table
LOG_SCALED_FEATURES = [
    "size_bytes",
    "ram_bytes",
    "early_access_days",
    "dev_title_count",
    "achievement_count",
    "dlc_count",
    "language_count",
]


@dataclass(frozen=True)
class FrozenBounds:
    """Empirically-frozen parameter values from a completed run.

    Attributes:
        complexity_bounds: Dict mapping feature name to (a, b) tuple of
            5th/95th percentile of log10(x+1) for each log-scaled feature.
        tag_distance_threshold: The Jaccard distance threshold for agglomerative
            clustering, chosen by the search procedure to keep at least 50% of
            resulting clusters at or above min_cluster_size.
        tag_distance_search_stats: Dict with keys 'cluster_count',
            'median_cluster_size', 'threshold_source' recording the outcome of
            the search.
        unfrozen_features: Log-scaled features with no observed values in the run
            (e.g. early_access_days, which the documented APIs do not provide);
            they receive no bounds.
    """

    complexity_bounds: dict[str, tuple[float, float]]
    tag_distance_threshold: float
    tag_distance_search_stats: dict
    unfrozen_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class FormulationSnippet:
    """Paste-ready text for FORMULATION.md sections 4, 6, and 8.

    Attributes:
        prose_record: Markdown text for sections 4 and 6's human-readable record.
        toml_block_update: TOML text to replace the unset placeholders in
            section 8's fenced block.
    """

    prose_record: str
    toml_block_update: str


def compute_frozen_bounds(
    conn: sqlite3.Connection, run_id: str, params: AnalysisParams
) -> FrozenBounds:
    """Compute empirically-frozen parameter values from a completed run.

    Args:
        conn: An open storage connection.
        run_id: The run whose data will fix the bounds (must be status='succeeded').
        params: The run's AnalysisParams (needed for min_cluster_size and
            clustering_linkage when re-deriving the distance threshold).

    Returns:
        FrozenBounds with complexity_bounds and tag_distance_threshold.

    Raises:
        ValueError: If the run's status is not 'succeeded', if games_enriched
            has too few rows for stable percentiles, or if any log-scaled
            feature has zero variance (5th == 95th percentile).
    """
    # Verify run status
    run_record = get_run(conn, run_id)
    if run_record.status != "succeeded":
        raise ValueError(
            f"Run {run_id} status is '{run_record.status}', expected 'succeeded'"
        )

    # Read enriched data
    enriched = read_enriched(conn, run_id)
    if len(enriched) < 30:
        raise ValueError(
            f"Run {run_id} has only {len(enriched)} enriched rows, "
            "expected at least 30 for stable percentiles"
        )

    # Compute complexity bounds: 5th/95th percentile of log10(x+1) for each feature
    complexity_bounds = {}
    unfrozen_features: list[str] = []
    for feature in LOG_SCALED_FEATURES:
        if feature not in enriched.columns:
            raise ValueError(f"Feature {feature} not found in enriched data")

        values = enriched[feature].dropna()
        if len(values) == 0:
            unfrozen_features.append(feature)
            continue

        log_values = np.log10(values + 1)
        p5 = np.percentile(log_values, 5)
        p95 = np.percentile(log_values, 95)

        # Check for zero variance
        if np.isclose(p5, p95):
            raise ValueError(
                f"Feature {feature} has zero variance (5th percentile {p5:.6f} == "
                f"95th percentile {p95:.6f}), cannot freeze bounds"
            )

        complexity_bounds[feature] = (float(p5), float(p95))

    # Compute tag distance threshold via cluster_tags with forced None threshold
    tags = read_tags(conn, run_id)
    if len(tags) == 0:
        # No tags; use a fallback threshold of 0.5
        tag_distance_threshold = 0.5
        tag_distance_search_stats = {
            "cluster_count": 0,
            "median_cluster_size": None,
            "threshold_source": "no_tags",
        }
    else:
        # Create a params copy with tag_distance_threshold forced to None
        # to trigger the search in cluster_tags
        params_for_search = dataclasses.replace(
            params, tag_distance_threshold=None  # Force search
        )

        # Call cluster_tags to perform the search
        # The analysis stage clusters the simple subset only (FORMULATION §6).
        simple_subset, _ = apply_simplicity_filter(enriched, params)
        result = cluster_tags(tags, simple_subset, params_for_search)

        # Extract threshold and search stats from result
        tag_distance_threshold = float(result.params_used["distance_threshold"])
        threshold_source = result.params_used["threshold_source"]

        # Compute cluster statistics
        cluster_sizes = [
            len(members) for members in result.cluster_members.values()
        ]
        if len(cluster_sizes) > 0:
            median_cluster_size = float(np.median(cluster_sizes))
            cluster_count = len(cluster_sizes)
        else:
            median_cluster_size = None
            cluster_count = 0

        tag_distance_search_stats = {
            "cluster_count": cluster_count,
            "median_cluster_size": median_cluster_size,
            "threshold_source": threshold_source,
        }

    return FrozenBounds(
        complexity_bounds=complexity_bounds,
        tag_distance_threshold=tag_distance_threshold,
        tag_distance_search_stats=tag_distance_search_stats,
        unfrozen_features=tuple(unfrozen_features),
    )


def write_parameters_toml_section(path: Path, bounds: FrozenBounds) -> None:
    """Write frozen bounds into parameters.toml.

    Uses tomlkit for round-trip TOML editing to preserve comments and formatting.

    Args:
        path: Path to config/parameters.toml.
        bounds: compute_frozen_bounds' output.

    Raises:
        ParameterError: If the resulting file would fail validate_parameters.
        FileNotFoundError: If path does not exist.
        ImportError: If tomlkit is not installed.
    """
    try:
        import tomlkit
    except ImportError:
        raise ImportError(
            "tomlkit is required for round-trip TOML editing. "
            "Install it with: pip install tomlkit"
        )

    # Read the existing TOML file with tomlkit (preserves formatting/comments)
    if not path.exists():
        raise FileNotFoundError(f"Parameters file not found: {path}")

    with open(path, "r") as f:
        doc = tomlkit.parse(f.read())

    # Update complexity_bounds in enrichment section
    if "enrichment" not in doc:
        doc["enrichment"] = tomlkit.table()
    if "complexity_bounds" not in doc["enrichment"]:
        doc["enrichment"]["complexity_bounds"] = tomlkit.table()

    for feature, (a, b) in bounds.complexity_bounds.items():
        doc["enrichment"]["complexity_bounds"][feature] = [a, b]

    # Update tag_distance_threshold in analysis section
    if "analysis" not in doc:
        doc["analysis"] = tomlkit.table()

    doc["analysis"]["tag_distance_threshold"] = bounds.tag_distance_threshold

    # Validate the result before writing
    try:
        validate_parameters(dict(doc))
    except ParameterError as e:
        raise ParameterError(
            f"Resulting parameters.toml would be invalid: {e.message}",
            path=path,
        ) from e

    # Write back to file
    with open(path, "w") as f:
        f.write(tomlkit.dumps(doc))


def format_formulation_snippet(
    run_id: str, computed_at: date, bounds: FrozenBounds
) -> FormulationSnippet:
    """Format paste-ready text for FORMULATION.md sections 4, 6, and 8.

    Args:
        run_id: The run the values were derived from.
        computed_at: Date this script was run.
        bounds: compute_frozen_bounds' output.

    Returns:
        FormulationSnippet with prose_record and toml_block_update.

    Raises:
        KeyError: If bounds.tag_distance_search_stats is missing expected keys.
    """
    # Verify required search stats keys
    required_stats_keys = ["cluster_count", "median_cluster_size", "threshold_source"]
    for key in required_stats_keys:
        if key not in bounds.tag_distance_search_stats:
            raise KeyError(
                f"tag_distance_search_stats missing required key: {key}"
            )

    # Format the prose record for FORMULATION.md sections 4 and 6
    bounds_records = []
    for feature in LOG_SCALED_FEATURES:
        if feature in bounds.complexity_bounds:
            a, b = bounds.complexity_bounds[feature]
            bounds_records.append(f"- `{feature}`: [{a:.6f}, {b:.6f}]")

    for feature in bounds.unfrozen_features:
        bounds_records.append(
            f"- `{feature}`: not frozen (no observed values in the run; the feature "
            "stays at the 0.5 midpoint fallback)"
        )

    bounds_str = "\n".join(bounds_records)

    cluster_count = bounds.tag_distance_search_stats["cluster_count"]
    median_cluster_size = bounds.tag_distance_search_stats["median_cluster_size"]
    threshold_source = bounds.tag_distance_search_stats["threshold_source"]

    iso_date = computed_at.isoformat()

    prose_record = f"""## Frozen Parameters (First Run)

Complexity score normalization bounds and tag-clustering threshold frozen from
run {run_id} on {iso_date}.

### Complexity Bounds (Section 4)

These bounds are the 5th and 95th percentiles of log10(x+1) for each log-scaled
feature, computed over the run's candidate set:

{bounds_str}

### Tag Distance Threshold (Section 6)

Tag-clustering distance-cut threshold: {bounds.tag_distance_threshold:.10f}

Search outcome: {cluster_count} clusters, median cluster size {median_cluster_size},
threshold source: {threshold_source}."""

    # Format the TOML block for FORMULATION.md section 8
    complexity_bounds_lines = []
    for feature in LOG_SCALED_FEATURES:
        if feature in bounds.complexity_bounds:
            a, b = bounds.complexity_bounds[feature]
            complexity_bounds_lines.append(f'{feature} = [{a}, {b}]')

    complexity_bounds_toml = "\n".join(complexity_bounds_lines)

    toml_block_update = f"""[enrichment.complexity_bounds]
{complexity_bounds_toml}

# tag_distance_threshold in [analysis] section
tag_distance_threshold = {bounds.tag_distance_threshold}"""

    return FormulationSnippet(prose_record=prose_record, toml_block_update=toml_block_update)


def main() -> None:
    """CLI entry point for freezing empirical parameters."""
    parser = argparse.ArgumentParser(
        description="Freeze empirical parameters from a completed run."
    )
    parser.add_argument("run_id", help="The run ID to compute bounds from")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to data/analyses.db (default: from config/settings.py)",
    )
    parser.add_argument(
        "--parameters-path",
        type=Path,
        default=None,
        help="Path to config/parameters.toml (default: from config/settings.py)",
    )

    args = parser.parse_args()

    # Determine DB path
    if args.db_path is None:
        from steam_analyst.config.settings import load_settings

        settings = load_settings()
        db_path = settings.db_path
        params_path = settings.parameters_path
    else:
        db_path = args.db_path
        params_path = args.parameters_path or Path("config/parameters.toml")

    # Load parameters
    from steam_analyst.config.parameters import load_parameters

    _, _, analysis_params = load_parameters(params_path)

    # Connect to database
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Compute frozen bounds
        bounds = compute_frozen_bounds(conn, args.run_id, analysis_params)

        # Write to parameters.toml
        write_parameters_toml_section(params_path, bounds)
        print("✓ Updated config/parameters.toml")

        # Format and print the snippet for manual FORMULATION.md update
        snippet = format_formulation_snippet(args.run_id, date.today(), bounds)

        print("\n" + "=" * 80)
        print("PASTE INTO FORMULATION.md SECTION 4 / 6 (Prose Record):")
        print("=" * 80)
        print(snippet.prose_record)

        print("\n" + "=" * 80)
        print("REPLACE IN FORMULATION.md SECTION 8 (TOML Block):")
        print("=" * 80)
        print(snippet.toml_block_update)
        print("=" * 80)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
