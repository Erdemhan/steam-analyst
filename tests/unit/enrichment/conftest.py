"""Pytest fixtures for enrichment tests."""

import pytest
import pandas as pd
from steam_analyst.config.settings import EnrichmentParams


@pytest.fixture
def mock_enrichment_params() -> EnrichmentParams:
    """Provide a mock EnrichmentParams with locked values from FORMULATION.md."""
    return EnrichmentParams(
        boxleiter_multipliers={
            "niche": (20, 27, 35),
            "mainstream": (30, 37, 45),
            "broad_audience": (40, 50, 65),
        },
        genre_bucket_map={
            "Strategy": "niche",
            "Simulation": "niche",
            "Puzzle": "mainstream",
            "RPG": "mainstream",
            "Horror": "mainstream",
            "Adventure": "mainstream",
            "Action": "broad_audience",
            "Arcade": "broad_audience",
            "FPS": "broad_audience",
            "Multiplayer": "broad_audience",
        },
        storefront_cut=0.30,
        discount_factor=0.0,
        refund_regional_factor=0.0,
        complexity_weights={
            "size_bytes": 0.20,
            "early_access_days": 0.15,
            "dev_title_count": 0.15,
            "simplicity_tag_score": 0.10,
            "complexity_tag_score": 0.10,
            "achievement_count": 0.10,
            "dlc_count": 0.10,
            "platform_count": 0.05,
            "language_count": 0.05,
        },
        complexity_bounds={},  # Provisional until run 1 data
        simplicity_tags=["Pixel Graphics", "2D", "Casual", "Short", "Singleplayer"],
        complexity_tags=["Open World", "Multiplayer", "Physics", "Procedural Generation"],
        effort_epsilon=0.05,
        tag_extraction_max_per_game=20,
        tag_extraction_min_votes=0,
    )
