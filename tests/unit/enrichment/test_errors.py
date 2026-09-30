"""Unit tests for enrichment.errors module."""

import pytest

from steam_analyst.enrichment.errors import EnrichmentError


class TestEnrichmentError:
    """Tests for the EnrichmentError exception class."""

    def test_enrichment_error_is_exception_subclass(self) -> None:
        """EnrichmentError inherits from Exception."""
        assert issubclass(EnrichmentError, Exception)

    def test_enrichment_error_can_be_instantiated(self) -> None:
        """EnrichmentError can be instantiated with a message."""
        exc = EnrichmentError("test message")
        assert isinstance(exc, Exception)
        assert str(exc) == "test message"

    def test_enrichment_error_can_be_raised_and_caught(self) -> None:
        """EnrichmentError can be raised and caught."""
        with pytest.raises(EnrichmentError) as exc_info:
            raise EnrichmentError("enrichment stage failed")
        assert "enrichment stage failed" in str(exc_info.value)

    def test_enrichment_error_without_message(self) -> None:
        """EnrichmentError can be instantiated without a message."""
        exc = EnrichmentError()
        assert isinstance(exc, Exception)

    def test_missing_raw_data_raises(self) -> None:
        """Verify EnrichmentError can be raised for missing raw_games rows."""
        run_id = "run_2024_001"
        with pytest.raises(EnrichmentError):
            raise EnrichmentError(f"no steamspy_all rows for run {run_id}")

    def test_str_message_is_informative(self) -> None:
        """str(EnrichmentError) preserves the run_id in the message."""
        run_id = "run_2024_001"
        exc = EnrichmentError(f"no steamspy_all rows for run {run_id}")
        message = str(exc)
        assert run_id in message
        assert "steamspy_all" in message

    def test_enrichment_error_with_genre_bucket_context(self) -> None:
        """EnrichmentError preserves genre_bucket context in message."""
        exc = EnrichmentError("genre_bucket 'Action' not found in boxleiter_multipliers")
        assert "genre_bucket" in str(exc)
        assert "Action" in str(exc)
        assert "boxleiter_multipliers" in str(exc)

    def test_enrichment_error_preserves_message_on_catch(self) -> None:
        """Exception message is preserved when caught."""
        message = "no raw_games for run test_run_123"
        try:
            raise EnrichmentError(message)
        except EnrichmentError as e:
            assert str(e) == message

    def test_enrichment_error_multiple_instantiation(self) -> None:
        """Multiple EnrichmentError instances have independent messages."""
        exc1 = EnrichmentError("first error")
        exc2 = EnrichmentError("second error")
        assert str(exc1) == "first error"
        assert str(exc2) == "second error"
        assert str(exc1) != str(exc2)
