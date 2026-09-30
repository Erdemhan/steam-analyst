"""Acquisition stage: SteamSpy bulk catalog, coarse filter, per-app Steam API fetches."""

from .errors import AcquisitionError, RequestBudgetExceeded
from .funnel import (
    AcquisitionReport,
    FunnelResult,
    build_catalog_frame,
    coarse_filter,
    fetch_app_details,
    fetch_review_summaries,
    fetch_steamspy_catalog,
)
from .http_client import HttpClient
from .pipeline import run_acquisition
from .rate_limiter import AcquisitionCancelled, RateLimiter
from .steam_reviews_client import SteamReviewsClient
from .steam_store_client import SteamStoreClient
from .steamspy_client import SteamSpyClient

__all__ = [
    "AcquisitionError",
    "RequestBudgetExceeded",
    "RateLimiter",
    "AcquisitionCancelled",
    "HttpClient",
    "SteamSpyClient",
    "SteamStoreClient",
    "SteamReviewsClient",
    "AcquisitionReport",
    "FunnelResult",
    "build_catalog_frame",
    "coarse_filter",
    "fetch_steamspy_catalog",
    "fetch_app_details",
    "fetch_review_summaries",
    "run_acquisition",
]
