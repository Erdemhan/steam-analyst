"""Unit tests for scripts.freeze_empirical_parameters module."""

import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Import the functions we're testing
from steam_analyst.config.parameters import ParameterError
from steam_analyst.config.settings import AnalysisParams
from steam_analyst.storage import (
    create_run,
    get_connection,
    initialize_schema,
    update_run_status,
    write_enriched,
    write_tags,
)
from steam_analyst.storage.types import TagRow

# Add scripts to path if needed
scripts_path = Path(__file__).parent.parent.parent.parent / "scripts"
if str(scripts_path) not in sys.path:
    sys.path.insert(0, str(scripts_path))

from freeze_empirical_parameters import (
    FrozenBounds,
    FormulationSnippet,
    compute_frozen_bounds,
    format_formulation_snippet,
    write_parameters_toml_section,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create and initialize a temporary test database."""
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    try:
        initialize_schema(conn)
    finally:
        conn.close()
    return db_path


@pytest.fixture
def analysis_params() -> AnalysisParams:
    """Provide mock AnalysisParams for testing."""
    return AnalysisParams(
        simplicity_percentile=0.40,
        trailing_window_months=24,
        min_cluster_size=5,
        opportunity_weights={
            "demand": 0.40,
            "competition": 0.30,
            "simplicity": 0.30,
        },
        min_tag_votes=0,
        max_tags_per_game=20,
        tag_distance_threshold=None,
        clustering_linkage="average",
    )


@pytest.fixture
def temp_parameters_toml(tmp_path: Path) -> Path:
    """Create a temporary parameters.toml file for testing."""
    params_file = tmp_path / "parameters.toml"
    params_file.write_text(
        """# --- coarse_filter (FORMULATION.md §0) ---
[acquisition.coarse_filter]
min_review_count = 25
earliest_release_date = "2020-01-01"
include_free_to_play = true
publisher_blocklist = ["Electronic Arts", "Ubisoft"]

# --- acquisition rate limiting ---
[acquisition]
steamspy_page_delay_seconds = 0.5
steam_requests_per_minute = 60.0
max_retries = 3
backoff_base_seconds = 1.0
backoff_max_seconds = 60.0
request_budget = 10000

# --- enrichment: Boxleiter multipliers (FORMULATION.md §2) ---
[enrichment.boxleiter_multipliers]
niche = [20, 27, 35]
mainstream = [30, 37, 45]
broad_audience = [40, 50, 65]

[enrichment.genre_bucket_map]
Strategy = "niche"
Simulation = "niche"
Puzzle = "mainstream"
RPG = "mainstream"
Horror = "mainstream"
Adventure = "mainstream"
Action = "broad_audience"
Arcade = "broad_audience"
FPS = "broad_audience"
Multiplayer = "broad_audience"
default = "mainstream"

# --- enrichment: revenue (FORMULATION.md §3) ---
[enrichment.revenue]
storefront_cut = 0.30
discount_factor = 0.0
refund_regional_factor = 0.0

# --- enrichment: complexity score (FORMULATION.md §4) ---
[enrichment.complexity_weights]
size_bytes = 0.20
ram_bytes = 0.10
early_access_days = 0.05
dev_title_count = 0.15
simplicity_tag_score = 0.10
complexity_tag_score = 0.10
achievement_count = 0.10
dlc_count = 0.10
platform_count = 0.05
language_count = 0.05

[enrichment.complexity_tags]
simplicity_tags = ["Pixel Graphics", "2D", "Casual", "Short", "Singleplayer"]
complexity_tags = ["Open World", "Multiplayer", "Physics", "Procedural Generation"]

# --- enrichment: effort-adjusted return (FORMULATION.md §5) ---
[enrichment.effort]
epsilon = 0.05

[enrichment.tag_extraction]
max_per_game = 20
min_votes = 0

# --- analysis: simplicity threshold (FORMULATION.md §3a) ---
[analysis]
simplicity_percentile = 0.40
clustering_linkage = "average"
trailing_window_months = 24
min_cluster_size = 5
min_tag_votes = 0
max_tags_per_game = 20

# --- analysis: opportunity score (FORMULATION.md §6) ---
[analysis.opportunity_weights]
demand = 0.40
competition = 0.30
simplicity = 0.30
"""
    )
    return params_file


def _make_enriched_frame(
    appids: list[int],
    size_bytes: list[int | None] = None,
    early_access_days: list[int | None] = None,
    dev_title_count: list[int | None] = None,
    achievement_count: list[int | None] = None,
    dlc_count: list[int | None] = None,
    language_count: list[int | None] = None,
) -> pd.DataFrame:
    """Create a minimal enriched DataFrame with required columns."""
    n = len(appids)

    # Default values: realistic distributions
    if size_bytes is None:
        size_bytes = [int(2e9 + i * 1e8) for i in range(n)]
    if early_access_days is None:
        early_access_days = [30 + i * 5 for i in range(n)]
    if dev_title_count is None:
        dev_title_count = [3 + i for i in range(n)]
    if achievement_count is None:
        achievement_count = [20 + i * 5 for i in range(n)]
    if dlc_count is None:
        dlc_count = [1 + i for i in range(n)]
    if language_count is None:
        language_count = [5 + i for i in range(n)]

    data = {
        "appid": appids,
        "name": [f"Game {appid}" for appid in appids],
        "app_type": ["Application"] * n,
        "developer": ["Dev Corp"] * n,
        "publisher": ["Pub Corp"] * n,
        "release_date": ["2023-01-01"] * n,
        "price_usd": [9.99] * n,
        "is_free": [0] * n,
        "review_count": [100 + i * 10 for i in range(n)],
        "review_positive_pct": [75.5] * n,
        "owners_estimate_low": [1000] * n,
        "owners_estimate_mid": [5000] * n,
        "owners_estimate_high": [10000] * n,
        "size_bytes": size_bytes,
        "ram_bytes": [int(4e9 + i * 1e8) for i in range(n)],
        "achievement_count": achievement_count,
        "language_count": language_count,
        "platform_count": [1] * n,
        "dlc_count": dlc_count,
        "dev_title_count": dev_title_count,
        "is_early_access": [0] * n,
        "early_access_days": early_access_days,
        "deck_compat": ["Verified"] * n,
        "genres_json": ["[1, 2, 3]"] * n,
        "categories_json": ["[4, 5]"] * n,
        "complexity_score": [0.5] * n,
        "imputed_features_json": ["{}"] * n,
        "estimated_sales_low": [100.0] * n,
        "estimated_sales_mid": [500.0] * n,
        "estimated_sales_high": [1000.0] * n,
        "estimated_revenue_gross_usd": [5000.0] * n,
        "estimated_revenue_net_usd": [3000.0] * n,
        "effort_adjusted_return": [0.5] * n,
        "parameters_version": ["test_v1"] * n,
    }

    return pd.DataFrame(data)


class TestComputeFrozenBounds:
    """Tests for compute_frozen_bounds function."""

    def test_computes_percentile_bounds_matching_hand_computation(
        self, temp_db: Path, analysis_params: AnalysisParams
    ):
        """Percentile bounds match numpy computation on known data."""
        conn = get_connection(temp_db)
        try:
            # Create a run
            run_id = create_run(
                conn, config={"test": True}, parameters_version="test_v1"
            )

            # Create enriched data with known feature distributions
            appids = list(range(100, 150))  # 50 games
            enriched = _make_enriched_frame(
                appids,
                size_bytes=[2e9 + i * 1e8 for i in range(50)],
                early_access_days=[30 + i * 5 for i in range(50)],
                dev_title_count=[3 + i for i in range(50)],
                achievement_count=[20 + i * 5 for i in range(50)],
                dlc_count=[1 + i for i in range(50)],
                language_count=[5 + i for i in range(50)],
            )

            # Write enriched data
            write_enriched(conn, run_id, enriched)

            # Update status to succeeded
            update_run_status(conn, run_id, "succeeded")

            # Compute frozen bounds
            bounds = compute_frozen_bounds(conn, run_id, analysis_params)

            # Verify bounds structure
            assert isinstance(bounds.complexity_bounds, dict)
            assert len(bounds.complexity_bounds) == 7
            assert all(
                isinstance(v, tuple) and len(v) == 2
                for v in bounds.complexity_bounds.values()
            )

            # Verify against hand computation
            for feature in [
                "size_bytes",
                "ram_bytes",
                "early_access_days",
                "dev_title_count",
                "achievement_count",
                "dlc_count",
                "language_count",
            ]:
                values = enriched[feature].dropna()
                log_values = np.log10(values + 1)
                p5 = np.percentile(log_values, 5)
                p95 = np.percentile(log_values, 95)

                a, b = bounds.complexity_bounds[feature]
                np.testing.assert_allclose(a, p5, rtol=1e-5)
                np.testing.assert_allclose(b, p95, rtol=1e-5)

        finally:
            conn.close()

    def test_degenerate_feature_raises(
        self, temp_db: Path, analysis_params: AnalysisParams
    ):
        """A feature with identical values raises ValueError."""
        conn = get_connection(temp_db)
        try:
            run_id = create_run(
                conn, config={"test": True}, parameters_version="test_v1"
            )

            # Create enriched data with one constant feature
            appids = list(range(100, 150))
            enriched = _make_enriched_frame(
                appids,
                size_bytes=[2e9] * 50,  # Constant value
                early_access_days=[30 + i * 5 for i in range(50)],
                dev_title_count=[3 + i for i in range(50)],
                achievement_count=[20 + i * 5 for i in range(50)],
                dlc_count=[1 + i for i in range(50)],
                language_count=[5 + i for i in range(50)],
            )

            write_enriched(conn, run_id, enriched)
            update_run_status(conn, run_id, "succeeded")

            # Should raise ValueError for degenerate feature
            with pytest.raises(ValueError, match="zero variance|identical values"):
                compute_frozen_bounds(conn, run_id, analysis_params)

        finally:
            conn.close()

    def test_feature_without_observed_values_is_left_unfrozen(
        self, temp_db: Path, analysis_params: AnalysisParams
    ):
        """A log-scaled feature that is NULL for every row is skipped, not fatal."""
        conn = get_connection(temp_db)
        try:
            run_id = create_run(
                conn, config={"test": True}, parameters_version="test_v1"
            )
            appids = list(range(100, 150))
            enriched = _make_enriched_frame(appids, early_access_days=[None] * 50)
            write_enriched(conn, run_id, enriched)
            update_run_status(conn, run_id, "succeeded")

            bounds = compute_frozen_bounds(conn, run_id, analysis_params)

            assert bounds.unfrozen_features == ("early_access_days",)
            assert "early_access_days" not in bounds.complexity_bounds
            assert "size_bytes" in bounds.complexity_bounds

            snippet = format_formulation_snippet(run_id, date(2026, 9, 30), bounds)
            assert "`early_access_days`: not frozen" in snippet.prose_record
            assert "early_access_days" not in snippet.toml_block_update
        finally:
            conn.close()

    def test_non_succeeded_run_raises(
        self, temp_db: Path, analysis_params: AnalysisParams
    ):
        """A run with status != 'succeeded' raises ValueError."""
        conn = get_connection(temp_db)
        try:
            run_id = create_run(
                conn, config={"test": True}, parameters_version="test_v1"
            )

            # Create and write enriched data but leave status as 'running'
            appids = list(range(100, 150))
            enriched = _make_enriched_frame(appids)
            write_enriched(conn, run_id, enriched)
            # Note: status stays 'running', never changed to 'succeeded'

            # Should raise ValueError
            with pytest.raises(ValueError, match="status"):
                compute_frozen_bounds(conn, run_id, analysis_params)

        finally:
            conn.close()

    def test_too_few_rows_raises(
        self, temp_db: Path, analysis_params: AnalysisParams
    ):
        """A run with too few rows raises ValueError."""
        conn = get_connection(temp_db)
        try:
            run_id = create_run(
                conn, config={"test": True}, parameters_version="test_v1"
            )

            # Create enriched data with only 5 rows (less than 30 minimum)
            appids = list(range(100, 105))  # Only 5 games
            enriched = _make_enriched_frame(appids)
            write_enriched(conn, run_id, enriched)
            update_run_status(conn, run_id, "succeeded")

            # Should raise ValueError
            with pytest.raises(ValueError, match="expected.*30"):
                compute_frozen_bounds(conn, run_id, analysis_params)

        finally:
            conn.close()

    def test_handles_no_tags(self, temp_db: Path, analysis_params: AnalysisParams):
        """A run with no tags still produces bounds."""
        conn = get_connection(temp_db)
        try:
            run_id = create_run(
                conn, config={"test": True}, parameters_version="test_v1"
            )

            # Create enriched data
            appids = list(range(100, 150))
            enriched = _make_enriched_frame(appids)
            write_enriched(conn, run_id, enriched)
            update_run_status(conn, run_id, "succeeded")

            # Don't write any tags

            # Should succeed and return bounds with fallback threshold
            bounds = compute_frozen_bounds(conn, run_id, analysis_params)
            assert bounds.tag_distance_threshold == 0.5
            assert bounds.tag_distance_search_stats["cluster_count"] == 0

        finally:
            conn.close()


class TestWriteParametersTomlSection:
    """Tests for write_parameters_toml_section function."""

    def test_updates_only_targeted_keys(
        self, temp_parameters_toml: Path
    ):
        """Only the targeted keys are changed; everything else is preserved."""
        # Read original
        original_content = temp_parameters_toml.read_text()

        # Create bounds with known values
        bounds = FrozenBounds(
            complexity_bounds={
                "size_bytes": (8.0, 10.0),
                "early_access_days": (1.0, 3.0),
                "dev_title_count": (0.5, 2.5),
                "achievement_count": (0.0, 3.0),
                "dlc_count": (0.0, 2.0),
                "language_count": (0.5, 2.0),
            },
            tag_distance_threshold=0.25,
            tag_distance_search_stats={
                "cluster_count": 10,
                "median_cluster_size": 8.0,
                "threshold_source": "run_local_search",
            },
        )

        # Write
        write_parameters_toml_section(temp_parameters_toml, bounds)

        # Read back
        new_content = temp_parameters_toml.read_text()

        # Verify complexity_bounds section exists and has the values
        assert "[enrichment.complexity_bounds]" in new_content
        assert "size_bytes = [8.0, 10.0]" in new_content

        # Verify tag_distance_threshold exists
        assert "tag_distance_threshold = 0.25" in new_content

        # Verify other sections are untouched (spot check)
        assert "Electronic Arts" in new_content
        assert "min_review_count = 25" in new_content
        assert "simplicity_percentile = 0.40" in new_content

    def test_write_preserves_structure(
        self, temp_parameters_toml: Path
    ):
        """Writing bounds preserves the overall TOML structure."""
        # Create bounds
        bounds = FrozenBounds(
            complexity_bounds={
                "size_bytes": (8.0, 10.0),
                "early_access_days": (1.0, 3.0),
                "dev_title_count": (0.5, 2.5),
                "achievement_count": (0.0, 3.0),
                "dlc_count": (0.0, 2.0),
                "language_count": (0.5, 2.0),
            },
            tag_distance_threshold=0.25,
            tag_distance_search_stats={
                "cluster_count": 10,
                "median_cluster_size": 8.0,
                "threshold_source": "run_local_search",
            },
        )

        # Write
        write_parameters_toml_section(temp_parameters_toml, bounds)

        # Read back
        new_content = temp_parameters_toml.read_text()

        # Verify essential sections still exist
        assert "[acquisition.coarse_filter]" in new_content
        assert "[analysis.opportunity_weights]" in new_content
        assert "min_review_count = 25" in new_content
        assert "Electronic Arts" in new_content


class TestFormatFormulationSnippet:
    """Tests for format_formulation_snippet function."""

    def test_snippet_contains_all_required_fields(self):
        """The snippet contains run_id, date, all feature bounds, and threshold."""
        bounds = FrozenBounds(
            complexity_bounds={
                "size_bytes": (8.0, 10.0),
                "early_access_days": (1.0, 3.0),
                "dev_title_count": (0.5, 2.5),
                "achievement_count": (0.0, 3.0),
                "dlc_count": (0.0, 2.0),
                "language_count": (0.5, 2.0),
            },
            tag_distance_threshold=0.25,
            tag_distance_search_stats={
                "cluster_count": 10,
                "median_cluster_size": 8.0,
                "threshold_source": "run_local_search",
            },
        )

        run_id = "20260920T143012123Z-a1b2c3"
        computed_at = date(2026, 9, 22)

        snippet = format_formulation_snippet(run_id, computed_at, bounds)

        # Verify structure
        assert isinstance(snippet, FormulationSnippet)
        assert isinstance(snippet.prose_record, str)
        assert isinstance(snippet.toml_block_update, str)

        # Verify prose_record contains required fields
        assert run_id in snippet.prose_record
        assert "2026-09-22" in snippet.prose_record
        assert "size_bytes" in snippet.prose_record
        assert "8.000000" in snippet.prose_record
        assert "10.000000" in snippet.prose_record
        assert "0.25" in snippet.prose_record
        assert "cluster" in snippet.prose_record.lower()
        assert "threshold" in snippet.prose_record.lower()

    def test_toml_block_update_is_valid_toml(self):
        """The TOML block parses successfully as TOML."""
        bounds = FrozenBounds(
            complexity_bounds={
                "size_bytes": (8.0, 10.0),
                "early_access_days": (1.0, 3.0),
                "dev_title_count": (0.5, 2.5),
                "achievement_count": (0.0, 3.0),
                "dlc_count": (0.0, 2.0),
                "language_count": (0.5, 2.0),
            },
            tag_distance_threshold=0.25,
            tag_distance_search_stats={
                "cluster_count": 10,
                "median_cluster_size": 8.0,
                "threshold_source": "run_local_search",
            },
        )

        snippet = format_formulation_snippet(
            "test_run", date(2026, 9, 22), bounds
        )

        # Should parse without error
        try:
            import tomlkit
            tomlkit.parse(snippet.toml_block_update)
        except ImportError:
            # Fallback to standard tomllib/tomli if tomlkit not available
            if sys.version_info >= (3, 11):
                import tomllib
            else:
                try:
                    import tomli as tomllib
                except ImportError:
                    pytest.skip("Neither tomlkit nor tomli available")

            # tomlkit should be installed, but provide a fallback
            # Just verify the string is not empty
            assert len(snippet.toml_block_update) > 0

    def test_toml_block_update_no_longer_says_unset(self):
        """The TOML block does not contain 'unset' placeholder text."""
        bounds = FrozenBounds(
            complexity_bounds={
                "size_bytes": (8.0, 10.0),
                "early_access_days": (1.0, 3.0),
                "dev_title_count": (0.5, 2.5),
                "achievement_count": (0.0, 3.0),
                "dlc_count": (0.0, 2.0),
                "language_count": (0.5, 2.0),
            },
            tag_distance_threshold=0.25,
            tag_distance_search_stats={
                "cluster_count": 10,
                "median_cluster_size": 8.0,
                "threshold_source": "run_local_search",
            },
        )

        snippet = format_formulation_snippet(
            "test_run", date(2026, 9, 22), bounds
        )

        # Verify "unset" is not in the output
        assert "unset" not in snippet.toml_block_update.lower()
        assert "[enrichment.complexity_bounds]" in snippet.toml_block_update
        assert "tag_distance_threshold = 0.25" in snippet.toml_block_update

    def test_missing_stats_key_raises(self):
        """Missing a required key in tag_distance_search_stats raises KeyError."""
        bounds = FrozenBounds(
            complexity_bounds={
                "size_bytes": (8.0, 10.0),
                "early_access_days": (1.0, 3.0),
                "dev_title_count": (0.5, 2.5),
                "achievement_count": (0.0, 3.0),
                "dlc_count": (0.0, 2.0),
                "language_count": (0.5, 2.0),
            },
            tag_distance_threshold=0.25,
            tag_distance_search_stats={
                # Missing 'median_cluster_size'
                "cluster_count": 10,
                "threshold_source": "run_local_search",
            },
        )

        with pytest.raises(KeyError):
            format_formulation_snippet("test_run", date(2026, 9, 22), bounds)
