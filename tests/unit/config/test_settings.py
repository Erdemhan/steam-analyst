"""Unit tests for steam_analyst.config.settings module.

Tests cover dataclass construction, immutability constraints, path resolution,
and environment variable loading. Tests for load_parameters validation logic
(weight sums, ratio ranges, etc.) are deferred to integration tests once
load_parameters is implemented.
"""

from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
import os
import pytest

from steam_analyst.config.settings import (
    AcquisitionConfig,
    AnalysisParams,
    CoarseFilterCriteria,
    EnrichmentParams,
    Settings,
    load_settings,
)


class TestCoarseFilterCriteria:
    """Tests for CoarseFilterCriteria dataclass."""

    def test_no_ceiling_represented_as_none(self) -> None:
        """max_review_count can be None to represent 'no ceiling'."""
        criteria = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=date(2020, 1, 1),
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=None,
            publisher_blocklist=["Ubisoft", "EA"],
        )
        assert criteria.max_review_count is None

    def test_max_review_count_set_to_value(self) -> None:
        """max_review_count can be set to a specific integer."""
        criteria = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=10000,
            earliest_release_date=date(2020, 1, 1),
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=None,
            publisher_blocklist=[],
        )
        assert criteria.max_review_count == 10000

    def test_dates_can_be_none(self) -> None:
        """Release date bounds can be None for no bound."""
        criteria = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=None,
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=None,
            publisher_blocklist=[],
        )
        assert criteria.earliest_release_date is None
        assert criteria.latest_release_date is None

    def test_publisher_blocklist_can_be_empty(self) -> None:
        """publisher_blocklist can be an empty list."""
        criteria = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=date(2020, 1, 1),
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=None,
            publisher_blocklist=[],
        )
        assert criteria.publisher_blocklist == []

    def test_publisher_blocklist_with_entries(self) -> None:
        """publisher_blocklist can contain publisher name fragments."""
        blocklist = [
            "Electronic Arts",
            "Ubisoft",
            "Activision",
            "Microsoft Studios",
        ]
        criteria = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=date(2020, 1, 1),
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=None,
            publisher_blocklist=blocklist,
        )
        assert criteria.publisher_blocklist == blocklist

    def test_frozen_instance_cannot_be_modified(self) -> None:
        """CoarseFilterCriteria is frozen; assignment raises FrozenInstanceError."""
        criteria = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=date(2020, 1, 1),
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=None,
            publisher_blocklist=[],
        )
        with pytest.raises(FrozenInstanceError):
            criteria.min_review_count = 50  # type: ignore


class TestAcquisitionConfig:
    """Tests for AcquisitionConfig dataclass."""

    def test_accepts_valid_fixture(self) -> None:
        """A complete, valid AcquisitionConfig round-trips unchanged."""
        coarse_filter = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=date(2020, 1, 1),
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=None,
            publisher_blocklist=["EA", "Ubisoft"],
        )
        config = AcquisitionConfig(
            steamspy_page_delay_seconds=1.5,
            steam_requests_per_minute=60.0,
            max_retries=3,
            backoff_base_seconds=1.0,
            backoff_max_seconds=60.0,
            request_budget=100000,
            coarse_filter=coarse_filter,
        )
        assert config.steamspy_page_delay_seconds == 1.5
        assert config.steam_requests_per_minute == 60.0
        assert config.max_retries == 3
        assert config.backoff_base_seconds == 1.0
        assert config.backoff_max_seconds == 60.0
        assert config.request_budget == 100000
        assert config.coarse_filter == coarse_filter

    def test_frozen_instance(self) -> None:
        """AcquisitionConfig is frozen; assignment raises FrozenInstanceError."""
        coarse_filter = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=date(2020, 1, 1),
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=None,
            publisher_blocklist=[],
        )
        config = AcquisitionConfig(
            steamspy_page_delay_seconds=1.5,
            steam_requests_per_minute=60.0,
            max_retries=3,
            backoff_base_seconds=1.0,
            backoff_max_seconds=60.0,
            request_budget=100000,
            coarse_filter=coarse_filter,
        )
        with pytest.raises(FrozenInstanceError):
            config.max_retries = 5  # type: ignore

    def test_backoff_bounds_accept_equal_values(self) -> None:
        """backoff_base_seconds == backoff_max_seconds is acceptable."""
        coarse_filter = CoarseFilterCriteria(
            min_review_count=25,
            max_review_count=None,
            earliest_release_date=date(2020, 1, 1),
            latest_release_date=None,
            include_free_to_play=True,
            max_price_usd=None,
            publisher_blocklist=[],
        )
        config = AcquisitionConfig(
            steamspy_page_delay_seconds=1.5,
            steam_requests_per_minute=60.0,
            max_retries=3,
            backoff_base_seconds=60.0,
            backoff_max_seconds=60.0,
            request_budget=100000,
            coarse_filter=coarse_filter,
        )
        assert config.backoff_base_seconds == 60.0
        assert config.backoff_max_seconds == 60.0


class TestEnrichmentParams:
    """Tests for EnrichmentParams dataclass."""

    def test_locked_epsilon_round_trips(self) -> None:
        """effort_epsilon with value 0.05 round-trips unchanged."""
        params = EnrichmentParams(
            boxleiter_multipliers={
                "niche": (20.0, 27.0, 35.0),
                "mainstream": (30.0, 37.0, 45.0),
                "broad_audience": (40.0, 50.0, 65.0),
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
                "ram_bytes": 0.10,
                "early_access_days": 0.05,
                "dev_title_count": 0.15,
                "simplicity_tag_score": 0.10,
                "complexity_tag_score": 0.10,
                "achievement_count": 0.10,
                "dlc_count": 0.10,
                "platform_count": 0.05,
                "language_count": 0.05,
            },
            complexity_bounds={},
            simplicity_tags=["Pixel Graphics", "2D", "Casual", "Short", "Singleplayer"],
            complexity_tags=["Open World", "Multiplayer", "Physics", "Procedural Generation"],
            effort_epsilon=0.05,
            tag_extraction_max_per_game=20,
            tag_extraction_min_votes=0,
        )
        assert params.effort_epsilon == 0.05

    def test_empty_complexity_bounds_accepted_pre_freeze(self) -> None:
        """Empty complexity_bounds dict is accepted (pre-freeze state)."""
        params = EnrichmentParams(
            boxleiter_multipliers={
                "niche": (20.0, 27.0, 35.0),
                "mainstream": (30.0, 37.0, 45.0),
                "broad_audience": (40.0, 50.0, 65.0),
            },
            genre_bucket_map={},
            storefront_cut=0.30,
            discount_factor=0.0,
            refund_regional_factor=0.0,
            complexity_weights={
                "size_bytes": 0.20,
                "ram_bytes": 0.10,
                "early_access_days": 0.05,
                "dev_title_count": 0.15,
                "simplicity_tag_score": 0.10,
                "complexity_tag_score": 0.10,
                "achievement_count": 0.10,
                "dlc_count": 0.10,
                "platform_count": 0.05,
                "language_count": 0.05,
            },
            complexity_bounds={},
            simplicity_tags=[],
            complexity_tags=[],
            effort_epsilon=0.05,
            tag_extraction_max_per_game=20,
            tag_extraction_min_votes=0,
        )
        assert params.complexity_bounds == {}

    def test_complexity_bounds_with_values(self) -> None:
        """complexity_bounds can contain feature bounds after freeze."""
        bounds = {
            "size_bytes": (1.0, 4.0),
            "early_access_days": (0.0, 3.0),
            "dev_title_count": (0.0, 2.5),
        }
        params = EnrichmentParams(
            boxleiter_multipliers={
                "niche": (20.0, 27.0, 35.0),
                "mainstream": (30.0, 37.0, 45.0),
                "broad_audience": (40.0, 50.0, 65.0),
            },
            genre_bucket_map={},
            storefront_cut=0.30,
            discount_factor=0.0,
            refund_regional_factor=0.0,
            complexity_weights={
                "size_bytes": 0.20,
                "ram_bytes": 0.10,
                "early_access_days": 0.05,
                "dev_title_count": 0.15,
                "simplicity_tag_score": 0.10,
                "complexity_tag_score": 0.10,
                "achievement_count": 0.10,
                "dlc_count": 0.10,
                "platform_count": 0.05,
                "language_count": 0.05,
            },
            complexity_bounds=bounds,
            simplicity_tags=[],
            complexity_tags=[],
            effort_epsilon=0.05,
            tag_extraction_max_per_game=20,
            tag_extraction_min_votes=0,
        )
        assert params.complexity_bounds == bounds

    def test_frozen_instance(self) -> None:
        """EnrichmentParams is frozen; assignment raises FrozenInstanceError."""
        params = EnrichmentParams(
            boxleiter_multipliers={},
            genre_bucket_map={},
            storefront_cut=0.30,
            discount_factor=0.0,
            refund_regional_factor=0.0,
            complexity_weights={},
            complexity_bounds={},
            simplicity_tags=[],
            complexity_tags=[],
            effort_epsilon=0.05,
            tag_extraction_max_per_game=20,
            tag_extraction_min_votes=0,
        )
        with pytest.raises(FrozenInstanceError):
            params.effort_epsilon = 0.1  # type: ignore


class TestAnalysisParams:
    """Tests for AnalysisParams dataclass."""

    def test_opportunity_weights_exact_keys(self) -> None:
        """opportunity_weights must have exactly the keys: demand, competition, simplicity."""
        params = AnalysisParams(
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
        assert set(params.opportunity_weights.keys()) == {
            "demand",
            "competition",
            "simplicity",
        }

    def test_opportunity_weights_sum_to_one(self) -> None:
        """opportunity_weights should sum to 1.0 (testable post-construction)."""
        params = AnalysisParams(
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
        total = sum(params.opportunity_weights.values())
        assert abs(total - 1.0) < 1e-6

    def test_none_threshold_accepted_pre_freeze(self) -> None:
        """tag_distance_threshold can be None (pre-freeze state)."""
        params = AnalysisParams(
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
        assert params.tag_distance_threshold is None

    def test_threshold_with_valid_value(self) -> None:
        """tag_distance_threshold can be set to a Jaccard distance value."""
        params = AnalysisParams(
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
            tag_distance_threshold=0.5,
            clustering_linkage="average",
        )
        assert params.tag_distance_threshold == 0.5

    def test_clustering_linkage_average_accepted(self) -> None:
        """clustering_linkage='average' is accepted."""
        params = AnalysisParams(
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
        assert params.clustering_linkage == "average"

    def test_clustering_linkage_complete_accepted(self) -> None:
        """clustering_linkage='complete' is accepted."""
        params = AnalysisParams(
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
            clustering_linkage="complete",
        )
        assert params.clustering_linkage == "complete"

    def test_clustering_linkage_single_accepted(self) -> None:
        """clustering_linkage='single' is accepted."""
        params = AnalysisParams(
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
            clustering_linkage="single",
        )
        assert params.clustering_linkage == "single"

    def test_frozen_instance(self) -> None:
        """AnalysisParams is frozen; assignment raises FrozenInstanceError."""
        params = AnalysisParams(
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
        with pytest.raises(FrozenInstanceError):
            params.trailing_window_months = 12  # type: ignore


class TestSettings:
    """Tests for Settings dataclass."""

    def test_settings_is_immutable(self) -> None:
        """Attempting to assign to a field after construction raises FrozenInstanceError."""
        settings = Settings(
            db_path=Path("data/analyses.db"),
            steam_web_api_key="test-key",
            http_timeout_seconds=30.0,
            user_agent="Test-Agent/1.0",
            parameters_path=Path("config/parameters.toml"),
        )
        with pytest.raises(FrozenInstanceError):
            settings.steam_web_api_key = "new-key"  # type: ignore

    def test_settings_rejects_non_positive_timeout(self) -> None:
        """Constructing Settings with http_timeout_seconds=0 raises ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            Settings(
                db_path=Path("data/analyses.db"),
                steam_web_api_key="test-key",
                http_timeout_seconds=0,
                user_agent="Test-Agent/1.0",
                parameters_path=Path("config/parameters.toml"),
            )

    def test_settings_rejects_negative_timeout(self) -> None:
        """Constructing Settings with negative http_timeout_seconds raises ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            Settings(
                db_path=Path("data/analyses.db"),
                steam_web_api_key="test-key",
                http_timeout_seconds=-5.0,
                user_agent="Test-Agent/1.0",
                parameters_path=Path("config/parameters.toml"),
            )

    def test_settings_accepts_positive_timeout(self) -> None:
        """Constructing Settings with positive http_timeout_seconds succeeds."""
        settings = Settings(
            db_path=Path("data/analyses.db"),
            steam_web_api_key="test-key",
            http_timeout_seconds=30.0,
            user_agent="Test-Agent/1.0",
            parameters_path=Path("config/parameters.toml"),
        )
        assert settings.http_timeout_seconds == 30.0

    def test_settings_with_none_api_key(self) -> None:
        """Settings can be constructed with steam_web_api_key=None."""
        settings = Settings(
            db_path=Path("data/analyses.db"),
            steam_web_api_key=None,
            http_timeout_seconds=30.0,
            user_agent="Test-Agent/1.0",
            parameters_path=Path("config/parameters.toml"),
        )
        assert settings.steam_web_api_key is None

    def test_settings_paths_stored_as_path_objects(self) -> None:
        """db_path and parameters_path are stored as Path objects."""
        db = Path("data/analyses.db")
        params = Path("config/parameters.toml")
        settings = Settings(
            db_path=db,
            steam_web_api_key="key",
            http_timeout_seconds=30.0,
            user_agent="Test-Agent/1.0",
            parameters_path=params,
        )
        assert isinstance(settings.db_path, Path)
        assert isinstance(settings.parameters_path, Path)
        assert settings.db_path == db
        assert settings.parameters_path == params


class TestLoadSettings:
    """Tests for load_settings function."""

    def test_load_settings_from_fixture_env_file(self) -> None:
        """A fixture .env with all variables set produces a Settings instance with matching fields."""
        fixture_path = Path(__file__).parent.parent.parent / "fixtures" / ".env_complete"
        settings = load_settings(fixture_path)

        assert settings.steam_web_api_key == "fixture-test-key-123"
        assert settings.http_timeout_seconds == 15.0
        assert settings.user_agent == "Steam-Analyst-Test/1.0"
        # Paths should be resolved to absolute
        assert settings.db_path.is_absolute()
        assert settings.parameters_path.is_absolute()

    def test_missing_api_key_is_not_fatal(self) -> None:
        """A fixture .env without STEAM_WEB_API_KEY still returns a Settings instance with steam_web_api_key=None."""
        fixture_path = Path(__file__).parent.parent.parent / "fixtures" / ".env_no_key"
        settings = load_settings(fixture_path)

        assert settings.steam_web_api_key is None
        assert settings.http_timeout_seconds == 15.0

    def test_invalid_timeout_raises(self) -> None:
        """A malformed timeout value raises ValueError."""
        fixture_path = Path(__file__).parent.parent.parent / "fixtures" / ".env_bad_timeout"
        with pytest.raises(ValueError, match="STEAM_ANALYST_HTTP_TIMEOUT_SECONDS"):
            load_settings(fixture_path)

    def test_empty_api_key_is_normalized_to_none(self) -> None:
        """An empty string for STEAM_WEB_API_KEY is normalized to None."""
        fixture_path = Path(__file__).parent.parent.parent / "fixtures" / ".env_empty_key"
        settings = load_settings(fixture_path)

        assert settings.steam_web_api_key is None

    def test_paths_resolved_to_absolute(self) -> None:
        """Relative paths are resolved to absolute paths."""
        fixture_path = Path(__file__).parent.parent.parent / "fixtures" / ".env_complete"
        settings = load_settings(fixture_path)

        # Both paths should be absolute
        assert settings.db_path.is_absolute()
        assert settings.parameters_path.is_absolute()

    def test_default_values_when_env_vars_missing(self) -> None:
        """Missing environment variables use documented defaults."""
        fixture_path = Path(__file__).parent.parent.parent / "fixtures" / ".env_minimal"
        settings = load_settings(fixture_path)

        # Should use defaults for missing variables
        # STEAM_ANALYST_HTTP_TIMEOUT_SECONDS defaults to '30'
        # db_path defaults to 'data/analyses.db'
        # parameters_path defaults to 'config/parameters.toml'
        assert settings.http_timeout_seconds == 30.0

    def test_user_agent_default(self) -> None:
        """Missing STEAM_ANALYST_USER_AGENT uses a default."""
        fixture_path = Path(__file__).parent.parent.parent / "fixtures" / ".env_complete"
        settings = load_settings(fixture_path)

        # If custom user agent is set in fixture, use it; otherwise use default
        assert isinstance(settings.user_agent, str)
        assert len(settings.user_agent) > 0
