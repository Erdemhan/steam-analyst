"""Unit tests for analysis.errors module."""

import pytest

from steam_analyst.analysis.errors import AnalysisError


class TestAnalysisError:
    """Tests for AnalysisError exception."""

    def test_is_exception_subclass(self):
        """AnalysisError is a subclass of Exception."""
        assert issubclass(AnalysisError, Exception)

    def test_can_be_raised(self):
        """AnalysisError can be raised and caught."""
        with pytest.raises(AnalysisError):
            raise AnalysisError()

    def test_can_be_raised_with_message(self):
        """AnalysisError preserves message when raised."""
        message = "run_id does not exist"
        with pytest.raises(AnalysisError, match=message):
            raise AnalysisError(message)

    def test_has_docstring(self):
        """AnalysisError has a descriptive docstring."""
        assert AnalysisError.__doc__ is not None
        assert "stage-fatal" in AnalysisError.__doc__.lower()

    def test_multiple_args(self):
        """AnalysisError can accept multiple arguments."""
        msg = "Enrichment incomplete"
        with pytest.raises(AnalysisError) as exc_info:
            raise AnalysisError(msg, "additional context")
        assert msg in str(exc_info.value)

    def test_empty_initialization(self):
        """AnalysisError can be instantiated without arguments."""
        error = AnalysisError()
        assert isinstance(error, Exception)
        assert str(error) == ""

    def test_string_representation(self):
        """AnalysisError string representation includes message."""
        message = "games_enriched is empty and enrichment never completed"
        error = AnalysisError(message)
        assert message in str(error)
