"""Entry point and routing for the Steam Analyst Streamlit application.

This module implements the Streamlit app's lifecycle management and navigation:
- main() handles startup (config, schema, migrations, reconciliation) and
  dispatcher (navigation dispatch to pages).
- build_navigation() constructs the st.navigation with the three pages.

Each page function (render_*_page) takes a connection and settings as arguments.
Since st.Page expects zero-argument callables, build_navigation() creates adapter
closures that open their own short-lived connections per ADR-017.

Key design (ADR-017, ADR-018):
- main() opens ONE connection for startup tasks, closes it, then calls nav.run().
- Each page render opens its OWN connection when dispatched, never reusing
  main's connection.
- Three pages: Run New Analysis (default, url_path='new'), Past Analyses
  (url_path='runs'), Analysis Detail (url_path='detail').
"""

import sqlite3
from typing import Callable

import streamlit as st

from steam_analyst import config, storage, orchestration
from steam_analyst.config import Settings
from .pages import (
    render_new_analysis_page,
    render_past_analyses_page,
    render_analysis_detail_page,
    register_nav_pages,
)


def main() -> None:
    """Entry point called by the three-line root app.py.

    Sequence:
    1. st.set_page_config(...).
    2. settings = config.load_settings().
    3. Open connection, run initialize_schema, migrate, reconcile_orphaned_runs.
       All three happen inside one short-lived connection that closes before
       navigation runs (per ADR-017).
    4. Build and run navigation (nav.run() dispatches to pages, each of which
       opens its OWN connection).

    Side effects:
    - Calls st.set_page_config (affects Streamlit's layout and metadata).
    - Initializes database schema on first run.
    - Reconciles orphaned runs from a previous process crash.
    """
    # 1. Configure the page
    st.set_page_config(
        page_title="Steam Analyst",
        page_icon="🎮",
        layout="wide",
        initial_sidebar_state="auto",
    )

    # 2. Load settings
    settings = config.load_settings()

    # 3. One-time startup tasks inside a single connection
    try:
        with storage.connect(settings.db_path) as conn:
            storage.initialize_schema(conn)
            storage.migrate(conn)
            orchestration.reconcile_orphaned_runs(conn)
    except Exception as e:
        st.error(f"Başlatma hatası: {e}")
        return

    # 4. Build and dispatch navigation
    nav = build_navigation(settings)
    nav.run()


def build_navigation(settings: Settings) -> st.navigation:
    """Build the navigation structure over three pages.

    Returns:
        st.navigation: A navigation object with three st.Page entries, each
        wrapping a page render function via a zero-argument adapter closure.
        'Run New Analysis' is marked as the default page.

    Adapter pattern:
        Each page function (render_new_analysis_page, etc.) requires
        (conn: sqlite3.Connection, settings: Settings). st.Page expects a
        zero-argument callable. The adapter closures created here open their
        own short-lived connection on dispatch and call the page function.
        This ensures no connection is cached or shared across pages (ADR-017).
    """

    def _page_adapter(
        render_func: Callable[[sqlite3.Connection, Settings], None]
    ) -> Callable[[], None]:
        """Create a zero-argument adapter wrapping a page render function.

        Args:
            render_func: A function with signature
                (conn: sqlite3.Connection, settings: Settings) -> None.

        Returns:
            A zero-argument callable that opens a connection, calls render_func,
            and closes the connection.
        """

        def _wrapped() -> None:
            with storage.connect(settings.db_path) as conn:
                render_func(conn, settings)

        return _wrapped

    # Build the three pages
    new_page = st.Page(
        _page_adapter(render_new_analysis_page),
        title="Yeni analiz",
        url_path="new",
        default=True,
    )
    past_page = st.Page(
        _page_adapter(render_past_analyses_page),
        title="Geçmiş analizler",
        url_path="runs",
    )
    detail_page = st.Page(
        _page_adapter(render_analysis_detail_page),
        title="Analiz ayrıntısı",
        url_path="detail",
    )
    register_nav_pages({"new": new_page, "past": past_page, "detail": detail_page})

    return st.navigation([new_page, past_page, detail_page])
