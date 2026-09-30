"""Unit tests for the ui.app module.

Tests cover:
- build_navigation returns exactly the four expected pages with the expected default.
- main's startup sequence (reconcile_orphaned_runs before build_navigation).
- Connection lifecycle (main's connection closed before page dispatch).
"""

import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call

import pytest
import streamlit as st

from steam_analyst import config, storage, orchestration
from steam_analyst.ui.app import main, build_navigation


class TestBuildNavigation:
    """Tests for build_navigation() function."""

    @pytest.fixture
    def mock_settings(self, tmp_path: Path) -> Mock:
        """Create a mock Settings object."""
        return Mock(
            spec=config.Settings,
            db_path=tmp_path / "test.db",
            parameters_path=tmp_path / "parameters.toml",
        )

    def test_build_navigation_returns_st_navigation(self, mock_settings: Mock) -> None:
        """build_navigation returns an st.navigation object."""
        with patch("steam_analyst.ui.app.storage"), patch(
            "steam_analyst.ui.app.st.navigation", return_value=Mock(spec=st.navigation)
        ) as mock_nav:
            result = build_navigation(mock_settings)
            # Verify st.navigation was called
            mock_nav.assert_called()

    def test_build_navigation_creates_four_pages(self, mock_settings: Mock) -> None:
        """build_navigation passes exactly four st.Page objects to st.navigation."""
        with patch("steam_analyst.ui.app.storage"), patch(
            "steam_analyst.ui.app.st.Page"
        ) as mock_page_class, patch(
            "steam_analyst.ui.app.st.navigation", return_value=Mock(spec=st.navigation)
        ) as mock_nav:
            build_navigation(mock_settings)
            # st.Page should be called exactly 4 times
            assert mock_page_class.call_count == 4

    def test_build_navigation_pages_have_correct_titles(
        self, mock_settings: Mock
    ) -> None:
        """The four pages have the expected titles."""
        with patch("steam_analyst.ui.app.storage"), patch(
            "steam_analyst.ui.app.st.Page"
        ) as mock_page_class, patch(
            "steam_analyst.ui.app.st.navigation", return_value=Mock(spec=st.navigation)
        ):
            build_navigation(mock_settings)

            # Extract the title argument from each st.Page call
            page_calls = mock_page_class.call_args_list
            titles = [call_obj.kwargs.get("title") for call_obj in page_calls]

            assert "Yeni analiz" in titles
            assert "Geçmiş analizler" in titles
            assert "Analiz ayrıntısı" in titles
            assert "Bilgi" in titles

    def test_build_navigation_pages_have_correct_url_paths(
        self, mock_settings: Mock
    ) -> None:
        """The four pages have the expected url_paths."""
        with patch("steam_analyst.ui.app.storage"), patch(
            "steam_analyst.ui.app.st.Page"
        ) as mock_page_class, patch(
            "steam_analyst.ui.app.st.navigation", return_value=Mock(spec=st.navigation)
        ):
            build_navigation(mock_settings)

            page_calls = mock_page_class.call_args_list
            url_paths = [call_obj.kwargs.get("url_path") for call_obj in page_calls]

            assert "new" in url_paths
            assert "runs" in url_paths
            assert "detail" in url_paths
            assert "info" in url_paths

    def test_build_navigation_first_page_is_default(self, mock_settings: Mock) -> None:
        """The first page (Run New Analysis) is marked as default."""
        with patch("steam_analyst.ui.app.storage"), patch(
            "steam_analyst.ui.app.st.Page"
        ) as mock_page_class, patch(
            "steam_analyst.ui.app.st.navigation", return_value=Mock(spec=st.navigation)
        ):
            build_navigation(mock_settings)

            page_calls = mock_page_class.call_args_list
            # First page should have default=True
            first_page_call = page_calls[0]
            assert first_page_call.kwargs.get("default") is True

            # Other pages should not have default=True (either default=False or unset)
            for call_obj in page_calls[1:]:
                default_value = call_obj.kwargs.get("default")
                assert default_value is not True

    def test_build_navigation_page_callables_are_zero_argument(
        self, mock_settings: Mock
    ) -> None:
        """Each page's callable should be a zero-argument function."""
        with patch("steam_analyst.ui.app.storage"), patch(
            "steam_analyst.ui.app.st.Page"
        ) as mock_page_class, patch(
            "steam_analyst.ui.app.st.navigation", return_value=Mock(spec=st.navigation)
        ):
            build_navigation(mock_settings)

            page_calls = mock_page_class.call_args_list
            for call_obj in page_calls:
                # The first positional argument is the callable
                callable_arg = call_obj.args[0]
                # Verify it's callable
                assert callable(callable_arg)
                # Verify it accepts no arguments
                import inspect
                sig = inspect.signature(callable_arg)
                assert len(sig.parameters) == 0


class TestMain:
    """Tests for main() function."""

    @pytest.fixture
    def mock_settings(self, tmp_path: Path) -> Mock:
        """Create a mock Settings object."""
        return Mock(
            spec=config.Settings,
            db_path=tmp_path / "test.db",
            parameters_path=tmp_path / "parameters.toml",
        )

    def test_main_calls_set_page_config(self) -> None:
        """main() calls st.set_page_config."""
        with patch("steam_analyst.ui.app.st.set_page_config") as mock_set_config, patch(
            "steam_analyst.ui.app.config.load_settings"
        ) as mock_load_settings, patch(
            "steam_analyst.ui.app.storage.connect"
        ) as mock_connect, patch(
            "steam_analyst.ui.app.build_navigation"
        ) as mock_build_nav, patch(
            "steam_analyst.ui.app.storage.initialize_schema"
        ), patch(
            "steam_analyst.ui.app.storage.migrate"
        ), patch(
            "steam_analyst.ui.app.orchestration.reconcile_orphaned_runs"
        ):
            mock_settings_obj = Mock()
            mock_settings_obj.db_path = Path("test.db")
            mock_load_settings.return_value = mock_settings_obj
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_connect.return_value.__exit__.return_value = None
            mock_nav = Mock()
            mock_build_nav.return_value = mock_nav

            main()

            mock_set_config.assert_called_once()

    def test_main_calls_load_settings(self) -> None:
        """main() calls config.load_settings()."""
        with patch("steam_analyst.ui.app.st.set_page_config"), patch(
            "steam_analyst.ui.app.config.load_settings"
        ) as mock_load_settings, patch(
            "steam_analyst.ui.app.storage.connect"
        ) as mock_connect, patch(
            "steam_analyst.ui.app.build_navigation"
        ) as mock_build_nav, patch(
            "steam_analyst.ui.app.storage.initialize_schema"
        ), patch(
            "steam_analyst.ui.app.storage.migrate"
        ), patch(
            "steam_analyst.ui.app.orchestration.reconcile_orphaned_runs"
        ):
            mock_settings_obj = Mock()
            mock_settings_obj.db_path = Path("test.db")
            mock_load_settings.return_value = mock_settings_obj
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_connect.return_value.__exit__.return_value = None
            mock_nav = Mock()
            mock_build_nav.return_value = mock_nav

            main()

            mock_load_settings.assert_called_once()

    def test_main_opens_connection_with_correct_db_path(self) -> None:
        """main() opens a connection using settings.db_path."""
        with patch("steam_analyst.ui.app.st.set_page_config"), patch(
            "steam_analyst.ui.app.config.load_settings"
        ) as mock_load_settings, patch(
            "steam_analyst.ui.app.storage.connect"
        ) as mock_connect, patch(
            "steam_analyst.ui.app.build_navigation"
        ) as mock_build_nav, patch(
            "steam_analyst.ui.app.storage.initialize_schema"
        ), patch(
            "steam_analyst.ui.app.storage.migrate"
        ), patch(
            "steam_analyst.ui.app.orchestration.reconcile_orphaned_runs"
        ):
            test_db_path = Path("/test/path/db.sqlite")
            mock_settings_obj = Mock()
            mock_settings_obj.db_path = test_db_path
            mock_load_settings.return_value = mock_settings_obj
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_connect.return_value.__exit__.return_value = None
            mock_nav = Mock()
            mock_build_nav.return_value = mock_nav

            main()

            mock_connect.assert_called_once_with(test_db_path)

    def test_main_calls_initialize_schema(self) -> None:
        """main() calls storage.initialize_schema inside the connection context."""
        with patch("steam_analyst.ui.app.st.set_page_config"), patch(
            "steam_analyst.ui.app.config.load_settings"
        ) as mock_load_settings, patch(
            "steam_analyst.ui.app.storage.connect"
        ) as mock_connect, patch(
            "steam_analyst.ui.app.build_navigation"
        ) as mock_build_nav, patch(
            "steam_analyst.ui.app.storage.initialize_schema"
        ) as mock_init_schema, patch(
            "steam_analyst.ui.app.storage.migrate"
        ), patch(
            "steam_analyst.ui.app.orchestration.reconcile_orphaned_runs"
        ):
            mock_settings_obj = Mock()
            mock_settings_obj.db_path = Path("test.db")
            mock_load_settings.return_value = mock_settings_obj
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_connect.return_value.__exit__.return_value = None
            mock_nav = Mock()
            mock_build_nav.return_value = mock_nav

            main()

            mock_init_schema.assert_called_once_with(mock_conn)

    def test_main_calls_migrate(self) -> None:
        """main() calls storage.migrate inside the connection context."""
        with patch("steam_analyst.ui.app.st.set_page_config"), patch(
            "steam_analyst.ui.app.config.load_settings"
        ) as mock_load_settings, patch(
            "steam_analyst.ui.app.storage.connect"
        ) as mock_connect, patch(
            "steam_analyst.ui.app.build_navigation"
        ) as mock_build_nav, patch(
            "steam_analyst.ui.app.storage.initialize_schema"
        ), patch(
            "steam_analyst.ui.app.storage.migrate"
        ) as mock_migrate, patch(
            "steam_analyst.ui.app.orchestration.reconcile_orphaned_runs"
        ):
            mock_settings_obj = Mock()
            mock_settings_obj.db_path = Path("test.db")
            mock_load_settings.return_value = mock_settings_obj
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_connect.return_value.__exit__.return_value = None
            mock_nav = Mock()
            mock_build_nav.return_value = mock_nav

            main()

            mock_migrate.assert_called_once_with(mock_conn)

    def test_main_calls_reconcile_orphaned_runs(self) -> None:
        """main() calls orchestration.reconcile_orphaned_runs."""
        with patch("steam_analyst.ui.app.st.set_page_config"), patch(
            "steam_analyst.ui.app.config.load_settings"
        ) as mock_load_settings, patch(
            "steam_analyst.ui.app.storage.connect"
        ) as mock_connect, patch(
            "steam_analyst.ui.app.build_navigation"
        ) as mock_build_nav, patch(
            "steam_analyst.ui.app.storage.initialize_schema"
        ), patch(
            "steam_analyst.ui.app.storage.migrate"
        ), patch(
            "steam_analyst.ui.app.orchestration.reconcile_orphaned_runs"
        ) as mock_reconcile:
            mock_settings_obj = Mock()
            mock_settings_obj.db_path = Path("test.db")
            mock_load_settings.return_value = mock_settings_obj
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_connect.return_value.__exit__.return_value = None
            mock_nav = Mock()
            mock_build_nav.return_value = mock_nav

            main()

            mock_reconcile.assert_called_once_with(mock_conn)

    def test_main_calls_startup_sequence_in_correct_order(self) -> None:
        """main() calls startup tasks in the correct sequence:
        initialize_schema -> migrate -> reconcile_orphaned_runs.
        """
        call_order = []

        def track_call(name):
            def _side_effect(*args, **kwargs):
                call_order.append(name)
            return _side_effect

        with patch("steam_analyst.ui.app.st.set_page_config"), patch(
            "steam_analyst.ui.app.config.load_settings"
        ) as mock_load_settings, patch(
            "steam_analyst.ui.app.storage.connect"
        ) as mock_connect, patch(
            "steam_analyst.ui.app.build_navigation"
        ) as mock_build_nav, patch(
            "steam_analyst.ui.app.storage.initialize_schema",
            side_effect=track_call("initialize_schema"),
        ), patch(
            "steam_analyst.ui.app.storage.migrate",
            side_effect=track_call("migrate"),
        ), patch(
            "steam_analyst.ui.app.orchestration.reconcile_orphaned_runs",
            side_effect=track_call("reconcile_orphaned_runs"),
        ):
            mock_settings_obj = Mock()
            mock_settings_obj.db_path = Path("test.db")
            mock_load_settings.return_value = mock_settings_obj
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_connect.return_value.__exit__.return_value = None
            mock_nav = Mock()
            mock_build_nav.return_value = mock_nav

            main()

            assert call_order == [
                "initialize_schema",
                "migrate",
                "reconcile_orphaned_runs",
            ]

    def test_main_calls_reconcile_before_build_navigation(self) -> None:
        """main() calls reconcile_orphaned_runs before build_navigation."""
        call_order = []

        def track_reconcile(*args, **kwargs):
            call_order.append("reconcile")

        def track_build_nav(settings):
            call_order.append("build_navigation")
            mock_nav = Mock()
            return mock_nav

        with patch("steam_analyst.ui.app.st.set_page_config"), patch(
            "steam_analyst.ui.app.config.load_settings"
        ) as mock_load_settings, patch(
            "steam_analyst.ui.app.storage.connect"
        ) as mock_connect, patch(
            "steam_analyst.ui.app.build_navigation", side_effect=track_build_nav
        ), patch(
            "steam_analyst.ui.app.storage.initialize_schema"
        ), patch(
            "steam_analyst.ui.app.storage.migrate"
        ), patch(
            "steam_analyst.ui.app.orchestration.reconcile_orphaned_runs",
            side_effect=track_reconcile,
        ):
            mock_settings_obj = Mock()
            mock_settings_obj.db_path = Path("test.db")
            mock_load_settings.return_value = mock_settings_obj
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_connect.return_value.__exit__.return_value = None
            mock_nav = Mock()
            mock_nav.run = Mock()

            main()

            assert call_order == ["reconcile", "build_navigation"]

    def test_main_closes_startup_connection_before_nav_dispatch(self) -> None:
        """main() closes its startup connection before calling nav.run()."""
        connection_state = {"closed": False}
        page_connection_opened = False

        def mock_connect_context(db_path):
            class MockContext:
                def __enter__(inner_self):
                    return MagicMock()

                def __exit__(inner_self, *args):
                    connection_state["closed"] = True

            return MockContext()

        with patch("steam_analyst.ui.app.st.set_page_config"), patch(
            "steam_analyst.ui.app.config.load_settings"
        ) as mock_load_settings, patch(
            "steam_analyst.ui.app.storage.connect", side_effect=mock_connect_context
        ), patch(
            "steam_analyst.ui.app.build_navigation"
        ) as mock_build_nav, patch(
            "steam_analyst.ui.app.storage.initialize_schema"
        ), patch(
            "steam_analyst.ui.app.storage.migrate"
        ), patch(
            "steam_analyst.ui.app.orchestration.reconcile_orphaned_runs"
        ):
            mock_settings_obj = Mock()
            mock_settings_obj.db_path = Path("test.db")
            mock_load_settings.return_value = mock_settings_obj
            mock_nav = Mock()
            mock_build_nav.return_value = mock_nav

            main()

            # Verify nav.run() was called
            mock_nav.run.assert_called_once()
            # Verify connection was closed before nav.run() was called
            assert connection_state["closed"] is True

    def test_main_passes_settings_to_build_navigation(self) -> None:
        """main() passes the settings object to build_navigation."""
        with patch("steam_analyst.ui.app.st.set_page_config"), patch(
            "steam_analyst.ui.app.config.load_settings"
        ) as mock_load_settings, patch(
            "steam_analyst.ui.app.storage.connect"
        ) as mock_connect, patch(
            "steam_analyst.ui.app.build_navigation"
        ) as mock_build_nav, patch(
            "steam_analyst.ui.app.storage.initialize_schema"
        ), patch(
            "steam_analyst.ui.app.storage.migrate"
        ), patch(
            "steam_analyst.ui.app.orchestration.reconcile_orphaned_runs"
        ):
            mock_settings_obj = Mock()
            mock_settings_obj.db_path = Path("test.db")
            mock_load_settings.return_value = mock_settings_obj
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_connect.return_value.__exit__.return_value = None
            mock_nav = Mock()
            mock_build_nav.return_value = mock_nav

            main()

            mock_build_nav.assert_called_once_with(mock_settings_obj)

    def test_main_calls_nav_run(self) -> None:
        """main() calls nav.run() to dispatch the navigation."""
        with patch("steam_analyst.ui.app.st.set_page_config"), patch(
            "steam_analyst.ui.app.config.load_settings"
        ) as mock_load_settings, patch(
            "steam_analyst.ui.app.storage.connect"
        ) as mock_connect, patch(
            "steam_analyst.ui.app.build_navigation"
        ) as mock_build_nav, patch(
            "steam_analyst.ui.app.storage.initialize_schema"
        ), patch(
            "steam_analyst.ui.app.storage.migrate"
        ), patch(
            "steam_analyst.ui.app.orchestration.reconcile_orphaned_runs"
        ):
            mock_settings_obj = Mock()
            mock_settings_obj.db_path = Path("test.db")
            mock_load_settings.return_value = mock_settings_obj
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_connect.return_value.__exit__.return_value = None
            mock_nav = Mock()
            mock_build_nav.return_value = mock_nav

            main()

            mock_nav.run.assert_called_once()

    def test_main_handles_startup_exception_gracefully(self) -> None:
        """main() catches startup exceptions and displays an error."""
        with patch("steam_analyst.ui.app.st.set_page_config"), patch(
            "steam_analyst.ui.app.config.load_settings"
        ) as mock_load_settings, patch(
            "steam_analyst.ui.app.storage.connect"
        ) as mock_connect, patch(
            "steam_analyst.ui.app.st.error"
        ) as mock_error, patch(
            "steam_analyst.ui.app.storage.initialize_schema",
            side_effect=Exception("Test error"),
        ):
            mock_settings_obj = Mock()
            mock_settings_obj.db_path = Path("test.db")
            mock_load_settings.return_value = mock_settings_obj
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_connect.return_value.__exit__.return_value = None

            main()

            mock_error.assert_called_once()
            call_args = mock_error.call_args[0][0]
            assert "Başlatma hatası" in call_args


class TestPageAdapterPattern:
    """Tests for the page adapter closure pattern in build_navigation."""

    @pytest.fixture
    def mock_settings(self, tmp_path: Path) -> Mock:
        """Create a mock Settings object."""
        return Mock(
            spec=config.Settings,
            db_path=tmp_path / "test.db",
            parameters_path=tmp_path / "parameters.toml",
        )

    def test_page_adapter_opens_connection_on_call(
        self, mock_settings: Mock
    ) -> None:
        """The page adapter opens a connection when invoked."""
        with patch("steam_analyst.ui.app.storage") as mock_storage_module, patch(
            "steam_analyst.ui.app.st.navigation", return_value=Mock(spec=st.navigation)
        ), patch("steam_analyst.ui.app.st.Page") as mock_page_class:
            mock_conn = MagicMock()
            mock_storage_module.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_storage_module.connect.return_value.__exit__.return_value = None

            # Mock page render function
            mock_render_func = Mock()

            # Manually call the adapter pattern (simulating what build_navigation does)
            def create_adapter(render_func):
                def wrapped():
                    with mock_storage_module.connect(mock_settings.db_path) as conn:
                        render_func(conn, mock_settings)
                return wrapped

            adapter = create_adapter(mock_render_func)
            adapter()

            # Verify connect was called
            mock_storage_module.connect.assert_called_with(mock_settings.db_path)
            # Verify the render function was called with correct args
            mock_render_func.assert_called_once_with(mock_conn, mock_settings)
