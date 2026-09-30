"""Unit tests for scripts/verify_parameters_consistency.py."""

import pytest
from pathlib import Path
from scripts.verify_parameters_consistency import (
    ParameterConsistencyError,
    verify_parameters_consistency,
    extract_toml_block_from_formulation,
    parse_toml_string,
    parse_toml_file,
    compare_toml_dicts,
)


# ============================================================================
# Fixtures: Representative §8 section and parameters.toml
# ============================================================================


@pytest.fixture
def formulation_md_minimal_section_8() -> str:
    """Minimal but realistic §8 content from FORMULATION.md.

    Based on actual §8 structure with essential locked values.
    """
    return """## 8. Machine-Readable Summary

This block is a **derived convenience copy** of the values already locked in
sections 0-6 above.

```toml
# --- coarse_filter (FORMULATION.md §0) ---
[coarse_filter]
min_review_count = 25
earliest_release_date = "2020-01-01"
include_free_to_play = true
publisher_blocklist = [
  "Electronic Arts", "Ubisoft", "Activision", "Activision Blizzard",
  "Take-Two Interactive", "Rockstar Games", "2K", "Bethesda Softworks",
  "ZeniMax", "Square Enix", "Capcom", "Sega", "Bandai Namco", "Konami",
  "Sony Interactive Entertainment", "Microsoft Studios", "Xbox Game Studios",
  "Warner Bros Games", "Epic Games", "Devolver Digital",
]

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
```

This block mirrors config/parameters.toml exactly.
"""


@pytest.fixture
def parameters_toml_matching(formulation_md_minimal_section_8: str) -> str:
    """A parameters.toml that matches the formulation §8 content."""
    return """# Configuration for steam-analyst

# --- coarse_filter (FORMULATION.md §0) ---
[acquisition.coarse_filter]
min_review_count = 25
earliest_release_date = "2020-01-01"
include_free_to_play = true
publisher_blocklist = [
  "Electronic Arts", "Ubisoft", "Activision", "Activision Blizzard",
  "Take-Two Interactive", "Rockstar Games", "2K", "Bethesda Softworks",
  "ZeniMax", "Square Enix", "Capcom", "Sega", "Bandai Namco", "Konami",
  "Sony Interactive Entertainment", "Microsoft Studios", "Xbox Game Studios",
  "Warner Bros Games", "Epic Games", "Devolver Digital",
]

# --- acquisition rate limiting (operational, not in §8) ---
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


@pytest.fixture
def parameters_toml_with_mismatches(parameters_toml_matching: str) -> str:
    """A parameters.toml with two deliberately mismatched values."""
    # Change min_review_count from 25 to 20 and epsilon from 0.05 to 0.10
    modified = parameters_toml_matching.replace(
        "min_review_count = 25", "min_review_count = 20"
    ).replace("epsilon = 0.05", "epsilon = 0.10")
    return modified


@pytest.fixture
def formulation_md_missing_fence() -> str:
    """A FORMULATION.md §8 with the toml fence missing."""
    return """## 8. Machine-Readable Summary

This block is missing the fence markers.

# (This should have been ```toml but it's not)

Some content here but no proper toml block.
"""


@pytest.fixture
def formulation_md_with_optional_absent() -> str:
    """FORMULATION.md §8 that legitimately omits optional keys."""
    return """## 8. Machine-Readable Summary

```toml
# --- coarse_filter (FORMULATION.md §0) ---
[coarse_filter]
min_review_count = 25
earliest_release_date = "2020-01-01"
include_free_to_play = true
publisher_blocklist = [
  "Electronic Arts", "Ubisoft", "Activision", "Activision Blizzard",
  "Take-Two Interactive", "Rockstar Games", "2K", "Bethesda Softworks",
  "ZeniMax", "Square Enix", "Capcom", "Sega", "Bandai Namco", "Konami",
  "Sony Interactive Entertainment", "Microsoft Studios", "Xbox Game Studios",
  "Warner Bros Games", "Epic Games", "Devolver Digital",
]
# Note: max_review_count is legitimately absent

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

[enrichment.revenue]
storefront_cut = 0.30
discount_factor = 0.0
refund_regional_factor = 0.0

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

[enrichment.effort]
epsilon = 0.05

[enrichment.tag_extraction]
max_per_game = 20
min_votes = 0

[analysis]
simplicity_percentile = 0.40
clustering_linkage = "average"
trailing_window_months = 24
min_cluster_size = 5
min_tag_votes = 0
max_tags_per_game = 20
# Note: tag_distance_threshold is legitimately absent

[analysis.opportunity_weights]
demand = 0.40
competition = 0.30
simplicity = 0.30
```
"""


@pytest.fixture
def parameters_toml_with_optional_absent() -> str:
    """parameters.toml that also omits the optional keys."""
    return """# Configuration for steam-analyst

[acquisition.coarse_filter]
min_review_count = 25
earliest_release_date = "2020-01-01"
include_free_to_play = true
publisher_blocklist = [
  "Electronic Arts", "Ubisoft", "Activision", "Activision Blizzard",
  "Take-Two Interactive", "Rockstar Games", "2K", "Bethesda Softworks",
  "ZeniMax", "Square Enix", "Capcom", "Sega", "Bandai Namco", "Konami",
  "Sony Interactive Entertainment", "Microsoft Studios", "Xbox Game Studios",
  "Warner Bros Games", "Epic Games", "Devolver Digital",
]

[acquisition]
steamspy_page_delay_seconds = 0.5
steam_requests_per_minute = 60.0
max_retries = 3
backoff_base_seconds = 1.0
backoff_max_seconds = 60.0
request_budget = 10000

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

[enrichment.revenue]
storefront_cut = 0.30
discount_factor = 0.0
refund_regional_factor = 0.0

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

[enrichment.effort]
epsilon = 0.05

[enrichment.tag_extraction]
max_per_game = 20
min_votes = 0

[analysis]
simplicity_percentile = 0.40
clustering_linkage = "average"
trailing_window_months = 24
min_cluster_size = 5
min_tag_votes = 0
max_tags_per_game = 20

[analysis.opportunity_weights]
demand = 0.40
competition = 0.30
simplicity = 0.30
"""


# ============================================================================
# Test Cases
# ============================================================================


def test_matching_files_pass(
    tmp_path: Path,
    formulation_md_minimal_section_8: str,
    parameters_toml_matching: str,
) -> None:
    """Test that matching FORMULATION.md and parameters.toml passes without raising.

    This is the happy path: both files are in sync.
    """
    # Write fixture files to temp directory
    formulation_path = tmp_path / "FORMULATION.md"
    parameters_path = tmp_path / "parameters.toml"

    formulation_path.write_text(formulation_md_minimal_section_8, encoding="utf-8")
    parameters_path.write_text(parameters_toml_matching, encoding="utf-8")

    # Should not raise
    verify_parameters_consistency(formulation_path, parameters_path)


def test_mismatched_value_raises_naming_all_offenders(
    tmp_path: Path,
    formulation_md_minimal_section_8: str,
    parameters_toml_with_mismatches: str,
) -> None:
    """Test that mismatched values raise ParameterConsistencyError naming all.

    The fixture has two mismatches: coarse_filter.min_review_count and
    enrichment.effort.epsilon. The error message must name both.
    """
    formulation_path = tmp_path / "FORMULATION.md"
    parameters_path = tmp_path / "parameters.toml"

    formulation_path.write_text(formulation_md_minimal_section_8, encoding="utf-8")
    parameters_path.write_text(parameters_toml_with_mismatches, encoding="utf-8")

    # Should raise with both keys named
    with pytest.raises(ParameterConsistencyError) as exc_info:
        verify_parameters_consistency(formulation_path, parameters_path)

    error_msg = str(exc_info.value)
    # Check that the error message is about parameter mismatch (not missing fence)
    assert "mismatch" in error_msg.lower()
    # Check that both offending keys are named
    assert "coarse_filter.min_review_count" in error_msg
    assert "enrichment.effort.epsilon" in error_msg


def test_missing_toml_fence_raises_distinct_error(
    tmp_path: Path,
    formulation_md_missing_fence: str,
) -> None:
    """Test that a missing toml fence raises a distinct error (not value mismatch).

    This error should have a different message than a value mismatch, so a
    maintainer can tell what went wrong.
    """
    formulation_path = tmp_path / "FORMULATION.md"
    parameters_path = tmp_path / "parameters.toml"

    formulation_path.write_text(formulation_md_missing_fence, encoding="utf-8")
    # parameters.toml doesn't matter since we error on the formulation side
    parameters_path.write_text("[dummy]\nvalue = 1\n", encoding="utf-8")

    with pytest.raises(ParameterConsistencyError) as exc_info:
        verify_parameters_consistency(formulation_path, parameters_path)

    error_msg = str(exc_info.value)
    # The error should mention the missing fence or §8 issue, not "mismatch"
    assert ("fence" in error_msg.lower() or
            "§8" in error_msg or
            "missing" in error_msg.lower() or
            "unclosed" in error_msg.lower())


def test_both_absent_optional_key_not_flagged(
    tmp_path: Path,
    formulation_md_with_optional_absent: str,
    parameters_toml_with_optional_absent: str,
) -> None:
    """Test that coarse_filter.max_review_count absent in both is OK.

    This is the special case: both files legitimately omit an optional key,
    so it should not be flagged as a mismatch.
    """
    formulation_path = tmp_path / "FORMULATION.md"
    parameters_path = tmp_path / "parameters.toml"

    formulation_path.write_text(formulation_md_with_optional_absent, encoding="utf-8")
    parameters_path.write_text(parameters_toml_with_optional_absent, encoding="utf-8")

    # Should not raise — both absent is the expected state
    verify_parameters_consistency(formulation_path, parameters_path)


def test_missing_formulation_file(tmp_path: Path) -> None:
    """Test that a missing FORMULATION.md raises ParameterConsistencyError."""
    formulation_path = tmp_path / "nonexistent_FORMULATION.md"
    parameters_path = tmp_path / "parameters.toml"
    parameters_path.write_text("[dummy]\nvalue = 1\n", encoding="utf-8")

    with pytest.raises(ParameterConsistencyError) as exc_info:
        verify_parameters_consistency(formulation_path, parameters_path)

    assert "not found" in str(exc_info.value).lower()


def test_missing_parameters_file(
    tmp_path: Path,
    formulation_md_minimal_section_8: str,
) -> None:
    """Test that a missing parameters.toml raises ParameterConsistencyError."""
    formulation_path = tmp_path / "FORMULATION.md"
    parameters_path = tmp_path / "nonexistent_parameters.toml"

    formulation_path.write_text(formulation_md_minimal_section_8, encoding="utf-8")

    with pytest.raises(ParameterConsistencyError) as exc_info:
        verify_parameters_consistency(formulation_path, parameters_path)

    assert "not found" in str(exc_info.value).lower()


def test_missing_section_8_heading(tmp_path: Path) -> None:
    """Test that FORMULATION.md without the §8 heading raises distinct error."""
    formulation_path = tmp_path / "FORMULATION.md"
    parameters_path = tmp_path / "parameters.toml"

    # FORMULATION.md without §8 heading
    formulation_path.write_text(
        "# Formulation\n\nNo section 8 here.", encoding="utf-8"
    )
    parameters_path.write_text("[dummy]\nvalue = 1\n", encoding="utf-8")

    with pytest.raises(ParameterConsistencyError) as exc_info:
        verify_parameters_consistency(formulation_path, parameters_path)

    error_msg = str(exc_info.value)
    # Should mention missing heading, not value mismatch
    assert ("8" in error_msg or "missing" in error_msg.lower() or
            "heading" in error_msg.lower())


def test_parse_toml_string_invalid_syntax() -> None:
    """Test that parse_toml_string raises on invalid TOML syntax."""
    invalid_toml = """
    [section
    key = value
    # Missing closing bracket
    """
    with pytest.raises(ParameterConsistencyError) as exc_info:
        parse_toml_string(invalid_toml, "test")

    assert "syntax" in str(exc_info.value).lower()


def test_extract_toml_block_from_formulation_complete_structure(
    tmp_path: Path,
    formulation_md_minimal_section_8: str,
) -> None:
    """Test that extract_toml_block_from_formulation correctly parses the block."""
    formulation_path = tmp_path / "FORMULATION.md"
    formulation_path.write_text(formulation_md_minimal_section_8, encoding="utf-8")

    toml_block = extract_toml_block_from_formulation(formulation_path)

    # The block should be valid TOML
    parsed = parse_toml_string(toml_block, "extracted block")

    # Check that key sections are present
    assert "coarse_filter" in parsed
    assert "enrichment" in parsed
    assert "analysis" in parsed

    # Check specific values
    assert parsed["coarse_filter"]["min_review_count"] == 25
    assert parsed["enrichment"]["revenue"]["storefront_cut"] == 0.30
    assert parsed["analysis"]["simplicity_percentile"] == 0.40
