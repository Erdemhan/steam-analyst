"""Unit tests for steam_analyst.ui.session module."""

import pytest

from steam_analyst.ui.session import SESSION_KEYS


class TestSessionKeys:
    """Tests for SESSION_KEYS constant."""

    def test_exactly_three_keys_declared(self) -> None:
        """SESSION_KEYS has exactly the three documented entries, no more, no fewer."""
        assert len(SESSION_KEYS) == 3

    def test_session_keys_content(self) -> None:
        """SESSION_KEYS contains the exact expected tuple."""
        assert SESSION_KEYS == ('active_run_id', 'last_event_id', 'event_log')

    def test_session_keys_is_tuple(self) -> None:
        """SESSION_KEYS is a tuple."""
        assert isinstance(SESSION_KEYS, tuple)

    def test_session_keys_contains_active_run_id(self) -> None:
        """SESSION_KEYS contains the 'active_run_id' key."""
        assert 'active_run_id' in SESSION_KEYS

    def test_session_keys_contains_last_event_id(self) -> None:
        """SESSION_KEYS contains the 'last_event_id' key."""
        assert 'last_event_id' in SESSION_KEYS

    def test_session_keys_contains_event_log(self) -> None:
        """SESSION_KEYS contains the 'event_log' key."""
        assert 'event_log' in SESSION_KEYS

    def test_session_keys_order(self) -> None:
        """SESSION_KEYS has keys in the expected order."""
        assert SESSION_KEYS[0] == 'active_run_id'
        assert SESSION_KEYS[1] == 'last_event_id'
        assert SESSION_KEYS[2] == 'event_log'
