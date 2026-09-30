"""Exception hierarchy for orchestration module.

Defines three exception types used during pipeline execution: PipelineError
(base class for orchestration-level failures), PipelineCancelled (raised at
cooperative cancellation check-points), and PreflightError (raised when
configuration or pre-run validation fails).
"""


class PipelineError(Exception):
    """Base class for orchestration-level exceptions.

    Raised directly for invalid resume requests and other orchestration-level
    misuse. Not raised by a stage entry point itself, but used as the base
    class for other orchestration exceptions.
    """

    pass


class PipelineCancelled(PipelineError):
    """Raised when a pipeline run is cancelled at a check-point.

    Raised at exactly one of the seven enumerated cancellation check-points
    (CP1-CP7) during pipeline execution. Carries which stage it was raised in,
    since the run_pipeline finally block needs this to call finish_run_stage
    with the correct stage.

    Attributes:
        stage: The pipeline stage name where cancellation occurred. Must be
            one of PipelineStage's values ('acquisition', 'enrichment',
            'analysis').
    """

    def __init__(self, stage: str) -> None:
        """Initialize PipelineCancelled with the stage where it was raised.

        Args:
            stage: The name of the pipeline stage where cancellation occurred.
                Should be one of PipelineStage's values.
        """
        self.stage = stage
        super().__init__(f"pipeline cancelled in {stage} stage")


class PreflightError(PipelineError):
    """Raised when preflight validation fails before any stage begins.

    Raised when config.load_parameters raises ParameterError, or when the
    parameters.toml/FORMULATION.md consistency check fails. Wraps the original
    exception as cause so the underlying validation message is never lost.

    Raised after storage.create_run has already inserted the run row (so a
    preflight failure is still visible in the run list) but before any
    run_stages row exists.

    Attributes:
        message: Human-readable description of the validation failure.
        cause: The original exception that triggered this error, typically a
            config.ParameterError. May be None if the failure was a
            hand-written assertion or check with no underlying exception.
    """

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        """Initialize PreflightError with a message and optional cause.

        Args:
            message: Human-readable description of the validation failure.
            cause: Optional. The original exception (typically
                config.ParameterError) that triggered this error. When set,
                it is preserved for full logging even though only this
                PreflightError's message is truncated into runs.error_message.
        """
        self.message = message
        self.cause = cause
        super().__init__(message)
