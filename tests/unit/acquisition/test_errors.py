"""Unit tests for acquisition.errors module."""

import pytest

from steam_analyst.acquisition.errors import AcquisitionError, RequestBudgetExceeded


class TestAcquisitionError:
    """Tests for the AcquisitionError exception class."""

    def test_acquisition_error_is_exception_subclass(self) -> None:
        """AcquisitionError inherits from Exception."""
        assert issubclass(AcquisitionError, Exception)

    def test_acquisition_error_can_be_instantiated(self) -> None:
        """AcquisitionError can be instantiated with a message."""
        exc = AcquisitionError("test message")
        assert isinstance(exc, Exception)
        assert str(exc) == "test message"

    def test_acquisition_error_can_be_raised_and_caught(self) -> None:
        """AcquisitionError can be raised and caught."""
        with pytest.raises(AcquisitionError) as exc_info:
            raise AcquisitionError("bulk fetch failed")
        assert "bulk fetch failed" in str(exc_info.value)

    def test_acquisition_error_without_message(self) -> None:
        """AcquisitionError can be instantiated without a message."""
        exc = AcquisitionError()
        assert isinstance(exc, Exception)


class TestRequestBudgetExceeded:
    """Tests for the RequestBudgetExceeded exception class."""

    def test_is_subclass_of_acquisition_error(self) -> None:
        """RequestBudgetExceeded is a subclass of AcquisitionError."""
        assert issubclass(RequestBudgetExceeded, AcquisitionError)

    def test_request_budget_exceeded_is_exception_subclass(self) -> None:
        """RequestBudgetExceeded transitively inherits from Exception."""
        assert issubclass(RequestBudgetExceeded, Exception)

    def test_isinstance_request_budget_exceeded_is_acquisition_error(self) -> None:
        """An instance of RequestBudgetExceeded is also an instance of AcquisitionError."""
        exc = RequestBudgetExceeded("budget exhausted")
        assert isinstance(exc, AcquisitionError)
        assert isinstance(exc, Exception)

    def test_request_budget_exceeded_can_be_instantiated(self) -> None:
        """RequestBudgetExceeded can be instantiated with a message."""
        exc = RequestBudgetExceeded("request budget exhausted after 5 requests")
        assert str(exc) == "request budget exhausted after 5 requests"

    def test_request_budget_exceeded_can_be_raised_and_caught_as_subclass(self) -> None:
        """RequestBudgetExceeded can be raised and caught specifically."""
        with pytest.raises(RequestBudgetExceeded) as exc_info:
            raise RequestBudgetExceeded("6th request would exceed budget")
        assert "6th request" in str(exc_info.value)

    def test_request_budget_exceeded_can_be_caught_as_acquisition_error(self) -> None:
        """RequestBudgetExceeded can be caught as an AcquisitionError."""
        with pytest.raises(AcquisitionError):
            raise RequestBudgetExceeded("budget limit reached")

    def test_acquisition_error_not_caught_by_request_budget_exceeded(self) -> None:
        """A generic AcquisitionError is not caught by except RequestBudgetExceeded."""
        with pytest.raises(AcquisitionError):
            with pytest.raises(RequestBudgetExceeded):
                raise AcquisitionError("some other error")

    def test_request_budget_exceeded_without_message(self) -> None:
        """RequestBudgetExceeded can be instantiated without a message."""
        exc = RequestBudgetExceeded()
        assert isinstance(exc, AcquisitionError)


class TestExceptionHierarchy:
    """Integration tests for the exception hierarchy."""

    def test_can_catch_acquisition_error_and_differentiate_budget(self) -> None:
        """Code can catch AcquisitionError and differentiate budget from other errors."""
        exceptions_to_test = [
            AcquisitionError("missing API key"),
            RequestBudgetExceeded("budget exceeded"),
        ]

        caught_types = []
        for exc in exceptions_to_test:
            try:
                raise exc
            except RequestBudgetExceeded:
                caught_types.append("budget_exceeded")
            except AcquisitionError:
                caught_types.append("acquisition_error")

        assert caught_types == ["acquisition_error", "budget_exceeded"]

    def test_exception_messages_preserved_in_hierarchy(self) -> None:
        """Exception messages are preserved when caught as parent class."""
        message = "request budget of 100 exhausted"
        try:
            raise RequestBudgetExceeded(message)
        except AcquisitionError as e:
            assert str(e) == message
