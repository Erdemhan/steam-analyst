"""Configuration and settings management.

This module loads, validates and exposes all runtime settings: secrets from the
environment and tunable parameters from config/parameters.toml. Provides typed
parameter objects to every other module so that no numeric constant is ever
hard-coded in logic.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
import os


@dataclass(frozen=True)
class CoarseFilterCriteria:
    """Stage-one funnel band (FORMULATION.md section 0).

    Attributes:
        min_review_count: Review-count floor. Locked value: 25.
        max_review_count: Review-count ceiling, or None for no ceiling. Locked
            value: None -- a hard ceiling would systematically exclude the
            solo/small-team breakout hits the tool most wants to surface. Kept
            as int | None (not a bare int) precisely so 'no ceiling' is
            representable without a magic sentinel like -1 or sys.maxsize.
        earliest_release_date: Locked value: date(2020, 1, 1), the post
            review-prompt-discontinuity boundary (FORMULATION.md section 2).
        latest_release_date: Optional upper release-date bound; None means no
            upper bound (i.e. up to the moment the run's bulk snapshot was
            fetched).
        include_free_to_play: Locked value: True -- F2P titles are kept for
            demand/competition analysis, with revenue fields set NULL
            downstream in enrichment (FORMULATION.md section 2).
        max_price_usd: Optional price sanity ceiling; None means no price-based
            exclusion.
        publisher_blocklist: Case-insensitive publisher-name fragments used to
            exclude AAA/large-publisher titles (FORMULATION.md section 0).
            Loaded as data from config/parameters.toml, not hard-coded, so it
            can be extended without a code change.
    """

    min_review_count: int
    max_review_count: int | None
    earliest_release_date: date | None
    latest_release_date: date | None
    include_free_to_play: bool
    max_price_usd: float | None
    publisher_blocklist: list[str]


@dataclass(frozen=True)
class AcquisitionConfig:
    """Acquisition-stage tunables (ARCHITECTURE.md Data Sources / Rate limiting).

    Attributes:
        steamspy_page_delay_seconds: Minimum delay between consecutive SteamSpy
            'all' page requests.
        steam_requests_per_minute: Token-bucket refill rate for Steam Web API /
            storefront requests.
        max_retries: Bounded retry count for HttpClient on 5xx/timeout before
            marking a request failed.
        backoff_base_seconds: Initial exponential-backoff interval.
        backoff_max_seconds: Backoff interval ceiling.
        request_budget: Hard per-run request cap; RateLimiter.acquire raises
            RequestBudgetExceeded once spent, per ADR-004/006 'fail loudly
            rather than hammer the API'.
        coarse_filter: Nested CoarseFilterCriteria band.
    """

    steamspy_page_delay_seconds: float
    steam_requests_per_minute: float
    max_retries: int
    backoff_base_seconds: float
    backoff_max_seconds: float
    request_budget: int
    coarse_filter: CoarseFilterCriteria


@dataclass(frozen=True)
class EnrichmentParams:
    """Enrichment-stage constants (FORMULATION.md sections 2-5).

    Attributes:
        boxleiter_multipliers: Keyed by the three FORMULATION.md section 2
            bucket names ('niche', 'mainstream', 'broad_audience'); each value
            is (m_low, m_mid, m_high). Locked values: (20,27,35), (30,37,45),
            (40,50,65) respectively.
        genre_bucket_map: Maps a Steam genre string to one of the three bucket
            keys above. Unmatched genres fall to 'mainstream' (the documented
            default bucket, includes Horror and RPG per FORMULATION.md
            section 2).
        storefront_cut: tau. Locked value: 0.30.
        discount_factor: delta. Locked value: 0.0 (FORMULATION.md section 3 --
            deliberately conservative-on-assumptions choice).
        refund_regional_factor: rho. Locked value: 0.0.
        complexity_weights: Nine feature weights from FORMULATION.md section 4,
            summing to 1.0 (install_size=0.20, early_access_duration=0.15,
            dev_catalog_size=0.15, simplicity_tag_score=0.10,
            complexity_tag_score=0.10, achievement_count=0.10, dlc_count=0.10,
            platform_count=0.05, language_count=0.05).
        complexity_bounds: Per-feature (a, b) log-scale normalization bounds.
            PROVISIONAL until scripts/freeze_empirical_parameters.py has run
            once against run 1's data (ADR-012); load_parameters must accept a
            placeholder/empty dict here without failing so run 1 itself can
            execute, but compute_complexity_score must then treat a missing
            feature's bounds as 'not yet frozen' and impute at the cohort
            median for that feature rather than dividing by an undefined
            (b - a).
        simplicity_tags: Tag strings that reduce complexity_tag_score
            negatively (pixel-art, 2D, casual, short, singleplayer, ...).
        complexity_tags: Tag strings that raise complexity_tag_score positively
            (open-world, multiplayer, physics, procedural, ...).
        effort_epsilon: epsilon in E_i = R_i^net / (C_i + epsilon). Locked
            value: 0.05.
        tag_extraction_max_per_game: Cap on tags retained per app in
            enrichment.extract_tags, keeping only the top-voted N. Locked
            value: 20. Deliberately a separate knob from
            AnalysisParams.max_tags_per_game even though both are currently
            20 -- this one controls game_tags table size at write time,
            the other re-filters independently inside analysis.cluster_tags
            (see enrichment.extract_tags' own FunctionSpec for the rationale).
        tag_extraction_min_votes: Tags with votes below this are dropped
            entirely by enrichment.extract_tags, before analysis ever sees
            them. Locked value: 0. Deliberately a separate knob from
            AnalysisParams.min_tag_votes for the same reason as above.
    """

    boxleiter_multipliers: dict[str, tuple[float, float, float]]
    genre_bucket_map: dict[str, str]
    storefront_cut: float
    discount_factor: float
    refund_regional_factor: float
    complexity_weights: dict[str, float]
    complexity_bounds: dict[str, tuple[float, float]]
    simplicity_tags: list[str]
    complexity_tags: list[str]
    effort_epsilon: float
    tag_extraction_max_per_game: int
    tag_extraction_min_votes: int


@dataclass(frozen=True)
class AnalysisParams:
    """Analysis-stage constants (FORMULATION.md sections 3a and 6).

    Attributes:
        simplicity_percentile: Percentile cutoff in (0, 1] for 'simple enough
            to build' games. FORMULATION.md section 3a defines this as the
            bottom 40th percentile of C_i (complexity score) within the same
            run's candidate set, not a fixed absolute complexity ceiling.
            apply_simplicity_filter computes the actual C_i cutoff value per
            run from this percentile. Locked value: 0.40.
        trailing_window_months: W. Locked value: 24.
        min_cluster_size: Locked value: 5 games.
        opportunity_weights: {'demand': 0.40, 'competition': 0.30,
            'simplicity': 0.30} -- w_D, w_K, w_Sigma.
        min_tag_votes: Tags below this vote count are excluded before
            clustering.
        max_tags_per_game: Cap on tags retained per app in extract_tags.
        tag_distance_threshold: The empirically-frozen Jaccard distance-cut
            threshold for agglomerative clustering (FORMULATION.md section 6).
            None until scripts/freeze_empirical_parameters.py has run once
            against run 1's data (ADR-012); cluster_tags must fall back to a
            locally-computed threshold search when this is None, and use the
            frozen value verbatim once present, never re-deriving it silently
            on a run where a frozen value already exists.
        clustering_linkage: Agglomerative-clustering linkage criterion, e.g.
            'average' or 'complete'. Locked to 'average' (FORMULATION.md §6).
    """

    simplicity_percentile: float
    trailing_window_months: int
    min_cluster_size: int
    opportunity_weights: dict[str, float]
    min_tag_votes: int
    max_tags_per_game: int
    tag_distance_threshold: float | None
    clustering_linkage: str


@dataclass(frozen=True)
class Settings:
    """Immutable, environment-derived settings for one process invocation.

    Attributes:
        db_path: Absolute path to the SQLite database file (data/analyses.db by
            default). Resolved with pathlib so it is correct on both the
            Windows development machine and any Linux execution host.
        steam_web_api_key: Value of STEAM_WEB_API_KEY, or None if unset.
            Absence is not fatal at construction time -- it is validated lazily
            by acquisition.SteamStoreClient / SteamReviewsClient, the first
            callers that actually need it.
        http_timeout_seconds: Per-request timeout applied by
            acquisition.HttpClient.
        user_agent: Custom User-Agent string identifying this tool to
            Steam/SteamSpy, per ARCHITECTURE.md's terms-of-service-safety
            driver.
        parameters_path: Absolute path to config/parameters.toml, passed to
            load_parameters.
    """

    db_path: Path
    steam_web_api_key: str | None
    http_timeout_seconds: float
    user_agent: str
    parameters_path: Path

    def __post_init__(self) -> None:
        """Validate that http_timeout_seconds is positive.

        Raises:
            ValueError: If http_timeout_seconds <= 0.
        """
        if self.http_timeout_seconds <= 0:
            raise ValueError(
                f"http_timeout_seconds must be positive, got {self.http_timeout_seconds}"
            )


def load_settings(env_path: Path | None = None) -> Settings:
    """Load environment-derived settings.

    Args:
        env_path: Explicit path to a .env file. If None, python-dotenv's
            default discovery (cwd and parents) is used. Tests always pass an
            explicit fixture path so discovery never touches a developer's
            real .env.

    Returns:
        A populated, frozen Settings instance with all paths resolved to
        absolute pathlib.Path objects.

    Raises:
        ValueError: If STEAM_ANALYST_DB_PATH or STEAM_ANALYST_PARAMETERS_PATH
            resolve to a value that is not a valid path string, or if
            http_timeout_seconds (from STEAM_ANALYST_HTTP_TIMEOUT_SECONDS,
            default '30') cannot be parsed as a positive float.
    """
    if env_path is not None:
        load_dotenv(env_path, override=True)
    else:
        load_dotenv()

    # Load path variables and resolve to absolute paths
    db_path_str = os.getenv("STEAM_ANALYST_DB_PATH", "data/analyses.db")
    db_path = Path(db_path_str).resolve()

    params_path_str = os.getenv(
        "STEAM_ANALYST_PARAMETERS_PATH", "config/parameters.toml"
    )
    parameters_path = Path(params_path_str).resolve()

    # Load timeout and user agent
    timeout_str = os.getenv("STEAM_ANALYST_HTTP_TIMEOUT_SECONDS", "30")
    try:
        http_timeout_seconds = float(timeout_str)
    except ValueError as e:
        raise ValueError(
            f"STEAM_ANALYST_HTTP_TIMEOUT_SECONDS must be a valid float, "
            f"got '{timeout_str}'"
        ) from e

    user_agent = os.getenv(
        "STEAM_ANALYST_USER_AGENT",
        "Steam-Analyst/1.0 (research; +https://github.com/...)",
    )

    # Load and normalize API key (empty string → None)
    api_key = os.getenv("STEAM_WEB_API_KEY")
    if api_key == "":
        api_key = None

    return Settings(
        db_path=db_path,
        steam_web_api_key=api_key,
        http_timeout_seconds=http_timeout_seconds,
        user_agent=user_agent,
        parameters_path=parameters_path,
    )
