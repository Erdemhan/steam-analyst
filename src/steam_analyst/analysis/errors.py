"""Exceptions for the analysis stage."""


class AnalysisError(Exception):
    """Stage-fatal analysis failure.

    Raised by run_analysis when run_id does not exist, or when games_enriched
    is empty AND no prior enrichment stage_complete event exists for the run
    (distinguishing this from a legitimately empty candidate set that enrichment
    itself completed successfully with zero rows). NOT raised for a small-but-nonzero
    candidate set, a degenerate clustering, or any single-archetype/zero-variance
    condition -- those are handled and reported, not raised, per the module's own design.
    """

    pass
