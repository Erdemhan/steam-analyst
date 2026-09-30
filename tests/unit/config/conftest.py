"""Pytest fixtures for config tests."""

import os
import pytest


@pytest.fixture(autouse=True)
def clean_env() -> None:
    """Clean environment variables related to steam_analyst before each test."""
    env_vars = [
        "STEAM_WEB_API_KEY",
        "STEAM_ANALYST_DB_PATH",
        "STEAM_ANALYST_PARAMETERS_PATH",
        "STEAM_ANALYST_HTTP_TIMEOUT_SECONDS",
        "STEAM_ANALYST_USER_AGENT",
    ]
    for var in env_vars:
        if var in os.environ:
            del os.environ[var]
    yield
