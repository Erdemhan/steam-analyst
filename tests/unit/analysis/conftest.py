"""Pytest fixtures for analysis tests."""

import pytest

from steam_analyst.config.settings import AnalysisParams


@pytest.fixture
def mock_analysis_params() -> AnalysisParams:
    """Provide a mock AnalysisParams with locked values from FORMULATION.md."""
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
        tag_distance_threshold=None,  # Provisional until run 1 data
        clustering_linkage="average",
    )
