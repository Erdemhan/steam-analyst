"""Unit tests for orchestration.errors exception hierarchy."""

import pytest

from steam_analyst.config.parameters import ParameterError
from steam_analyst.orchestration.errors import (
    PipelineError,
    PipelineCancelled,
    PreflightError,
)


class TestPipelineError:
    """Tests for the base PipelineError class."""

    def test_pipelineerror_is_exception(self):
        """PipelineError should be an Exception subclass."""
        exc = PipelineError("test error")
        assert isinstance(exc, Exception)

    def test_pipelineerror_basic_message(self):
        """PipelineError should accept and store a message."""
        exc = PipelineError("test message")
        assert str(exc) == "test message"


class TestPipelineCancelled:
    """Tests for PipelineCancelled exception."""

    def test_pipelinecancelled_carries_stage(self):
        """PipelineCancelled should store stage and include it in string representation."""
        exc = PipelineCancelled("enrichment")
        assert exc.stage == "enrichment"
        assert "enrichment" in str(exc)

    def test_pipelinecancelled_is_pipelineerror(self):
        """PipelineCancelled should be an instance of PipelineError."""
        exc = PipelineCancelled("acquisition")
        assert isinstance(exc, PipelineError)
        assert isinstance(exc, Exception)

    def test_pipelinecancelled_all_valid_stages(self):
        """PipelineCancelled should accept all three pipeline stage names."""
        for stage in ["acquisition", "enrichment", "analysis"]:
            exc = PipelineCancelled(stage)
            assert exc.stage == stage
            assert stage in str(exc)

    def test_pipelinecancelled_with_arbitrary_stage_name(self):
        """PipelineCancelled should accept any string stage name (not enforced at construction)."""
        # Note: The spec says PipelineCancelled is only ever raised from
        # within a stage's execution or from CP1/CP5 with real PipelineStage
        # values. But the class itself doesn't enforce this at construction
        # time (that's an orchestration-level contract, not a class-level one).
        exc = PipelineCancelled("pipeline")
        assert exc.stage == "pipeline"
        assert "pipeline" in str(exc)

    def test_pipelinecancelled_string_representation(self):
        """PipelineCancelled string representation should include stage name."""
        exc = PipelineCancelled("analysis")
        exc_str = str(exc)
        assert "cancelled" in exc_str.lower()
        assert "analysis" in exc_str


class TestPreflightError:
    """Tests for PreflightError exception."""

    def test_preflighterror_is_pipelineerror(self):
        """PreflightError should be an instance of PipelineError."""
        exc = PreflightError("bad configuration")
        assert isinstance(exc, PipelineError)
        assert isinstance(exc, Exception)

    def test_preflighterror_stores_message(self):
        """PreflightError should store and expose the message."""
        msg = "bad weights"
        exc = PreflightError(msg)
        assert exc.message == msg
        assert str(exc) == msg

    def test_preflighterror_wraps_cause(self):
        """PreflightError should wrap a ParameterError as cause."""
        param_error = ParameterError("weights sum to 0.95, expected 1.0")
        exc = PreflightError("bad weights", cause=param_error)
        assert exc.cause is param_error
        assert isinstance(exc.cause, ParameterError)

    def test_preflighterror_cause_is_optional(self):
        """PreflightError should allow cause=None (default)."""
        exc = PreflightError("manual validation failure")
        assert exc.cause is None

    def test_preflighterror_with_parameter_error_cause(self):
        """PreflightError should preserve ParameterError details when used as cause."""
        param_error = ParameterError(
            "missing key: analysis.simplicity_percentile",
            path=None,
            key="analysis.simplicity_percentile"
        )
        exc = PreflightError("preflight failed", cause=param_error)
        assert exc.cause is param_error
        assert exc.cause.key == "analysis.simplicity_percentile"

    def test_preflighterror_cause_with_different_exception_type(self):
        """PreflightError should wrap any Exception type as cause."""
        original_error = ValueError("some value is invalid")
        exc = PreflightError("preflight failed", cause=original_error)
        assert exc.cause is original_error
        assert isinstance(exc.cause, ValueError)

    def test_preflighterror_message_separate_from_cause(self):
        """PreflightError message and cause should be independent."""
        param_error = ParameterError("detailed validation error")
        exc = PreflightError("preflight validation failed", cause=param_error)
        assert exc.message == "preflight validation failed"
        assert str(exc) == "preflight validation failed"
        assert exc.cause.message == "detailed validation error"

    def test_preflighterror_inheritance_chain(self):
        """PreflightError should be properly in the exception hierarchy."""
        exc = PreflightError("test")
        assert isinstance(exc, PreflightError)
        assert isinstance(exc, PipelineError)
        assert isinstance(exc, Exception)


class TestExceptionInheritance:
    """Tests for the overall exception hierarchy."""

    def test_pipelinecancelled_and_preflighterror_are_pipelineerror(self):
        """Both PipelineCancelled and PreflightError should inherit from PipelineError."""
        cancelled = PipelineCancelled("acquisition")
        preflight = PreflightError("bad config")
        assert isinstance(cancelled, PipelineError)
        assert isinstance(preflight, PipelineError)

    def test_all_exceptions_are_exception_subclasses(self):
        """All three exception types should inherit from Exception."""
        assert issubclass(PipelineError, Exception)
        assert issubclass(PipelineCancelled, Exception)
        assert issubclass(PreflightError, Exception)

    def test_exception_catch_hierarchy(self):
        """PipelineError should catch both PipelineCancelled and PreflightError."""
        with pytest.raises(PipelineError):
            raise PipelineCancelled("enrichment")

        with pytest.raises(PipelineError):
            raise PreflightError("bad config")


class TestEdgeCases:
    """Tests for edge cases noted in the spec."""

    def test_pipelinecancelled_with_run_level_stage_not_enforced(self):
        """PipelineCancelled with RUN_LEVEL_STAGE ('pipeline') is technically possible.

        The spec notes this would be a caller bug (PipelineCancelled should
        only be raised with real PipelineStage values from CP1/CP5), but the
        exception class itself doesn't enforce this constraint at construction.
        This is an orchestration-level contract, not a class-level one.
        """
        # This is valid at the class level (though it would be a bug if actually raised)
        exc = PipelineCancelled("pipeline")
        assert exc.stage == "pipeline"

    def test_preflighterror_with_none_cause_is_valid(self):
        """PreflightError with cause=None is valid for hand-written assertions."""
        # This represents a validation failure with no underlying exception
        exc = PreflightError("hand-written assertion failed")
        assert exc.cause is None
        assert isinstance(exc, PipelineError)

    def test_preflighterror_explicit_none_cause(self):
        """PreflightError should accept explicit cause=None."""
        exc = PreflightError("validation failed", cause=None)
        assert exc.cause is None

    def test_pipelinecancelled_multiple_instances_independent(self):
        """Multiple PipelineCancelled instances should be independent."""
        exc1 = PipelineCancelled("acquisition")
        exc2 = PipelineCancelled("enrichment")
        assert exc1.stage != exc2.stage
        assert exc1 is not exc2

    def test_preflighterror_multiple_instances_independent(self):
        """Multiple PreflightError instances should be independent."""
        error1 = ParameterError("error 1")
        error2 = ParameterError("error 2")
        exc1 = PreflightError("msg1", cause=error1)
        exc2 = PreflightError("msg2", cause=error2)
        assert exc1.cause is error1
        assert exc2.cause is error2
        assert exc1 is not exc2
