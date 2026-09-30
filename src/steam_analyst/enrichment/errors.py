"""Enrichment stage exceptions."""


class EnrichmentError(Exception):
    """Stage-fatal enrichment failure.

    Raised by parse_raw_bundle (unknown run_id), run_enrichment (missing steamspy_all rows),
    and estimate_sales (a genre_bucket value absent from boxleiter_multipliers, which should
    be structurally impossible if map_genre_bucket and config validation are both correct,
    but is guarded defensively as a programmer/config-drift signal). NOT raised for ordinary
    per-row data-quality issues (missing features, non-game app_type, F2P revenue) -- those
    are handled via imputation, dropping-and-counting, or NaN, per the module's core design.
    """

    pass
