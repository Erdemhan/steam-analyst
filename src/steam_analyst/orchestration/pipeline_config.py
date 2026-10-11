"""Per-run pipeline configuration options."""

from dataclasses import dataclass
from steam_analyst.orchestration.stages import PipelineStage


@dataclass(frozen=True)
class PipelineConfig:
    """Per-run pipeline options, never a formulation parameter.

    Attributes:
        start_stage: Which stage to begin at. ACQUISITION for a fresh run; set to a later stage
            by resume_run (first non-succeeded stage) or by a deliberate stage re-run after a
            parameter change.
        max_catalog_pages: Smoke-test limiter forwarded to acquisition.fetch_steamspy_catalog
            (max_pages=...). None means no limit.
        request_budget_override: Overrides AcquisitionConfig.request_budget for this run only
            when set; None defers to the configured default.
        complexity_weights_override: Complexity weights (FORMULATION.md section 4) chosen for
            this run, a subset of the locked feature keys. None means the locked defaults.
            Unspecified features keep their default, then all ten are rescaled to sum to 1.0
            (config.resolve_complexity_weights). It changes the complexity score and therefore
            the simplicity split, so it is recorded in config_json and in the run's
            parameters_version.
        notes: Free user text, persisted to runs.notes verbatim (also duplicated into config_json
            for convenience, since config_json is the single JSON blob the UI reads back for
            the 'Run New Analysis' form's remembered values).

    to_dict / from_dict: Round-trip through runs.config_json. from_dict must accept a dict
    missing newer fields (loading an older run after a code change) by falling back to each
    field's own default rather than raising.
    """

    start_stage: PipelineStage = PipelineStage.ACQUISITION
    max_catalog_pages: int | None = None
    request_budget_override: int | None = None
    complexity_weights_override: dict[str, float] | None = None
    notes: str | None = None

    def to_dict(self) -> dict:
        """Convert to a dictionary suitable for JSON serialization.

        The start_stage enum is converted to its string value since JSON has no enum type.

        Returns:
            A dictionary with all fields, where start_stage is a string.
        """
        return {
            "start_stage": self.start_stage.value,
            "max_catalog_pages": self.max_catalog_pages,
            "request_budget_override": self.request_budget_override,
            "complexity_weights_override": self.complexity_weights_override,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineConfig":
        """Reconstruct a PipelineConfig from a dictionary.

        Tolerates:
        - Missing fields by falling back to class defaults
        - Unknown extra keys by ignoring them (forward compatibility)
        - start_stage as a string (from JSON) which is converted back to PipelineStage enum

        Args:
            data: Dictionary to reconstruct from (e.g., from runs.config_json).

        Returns:
            A PipelineConfig instance with values from data and defaults for missing fields.
        """
        # Extract fields with defaults if missing
        start_stage_value = data.get("start_stage", PipelineStage.ACQUISITION.value)

        # Convert string back to PipelineStage if necessary
        if isinstance(start_stage_value, str):
            start_stage = PipelineStage(start_stage_value)
        else:
            # Already a PipelineStage enum
            start_stage = start_stage_value

        max_catalog_pages = data.get("max_catalog_pages", None)
        request_budget_override = data.get("request_budget_override", None)
        complexity_weights_override = data.get("complexity_weights_override", None)
        notes = data.get("notes", None)

        return cls(
            start_stage=start_stage,
            max_catalog_pages=max_catalog_pages,
            request_budget_override=request_budget_override,
            complexity_weights_override=complexity_weights_override,
            notes=notes,
        )
