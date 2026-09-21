"""Simplicity filter implementation.

Splits the enriched candidate set into the "buildable" subset (bottom 40th
percentile of complexity_score within the run's own distribution) and a
rejection tally, per FORMULATION.md section 3a.
"""

import pandas as pd

from steam_analyst.config.settings import AnalysisParams


def apply_simplicity_filter(
    frame: pd.DataFrame, params: AnalysisParams
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Split candidates into the simple/buildable subset and the rest.

    Implements FORMULATION.md section 3a: splits the enriched frame into the
    'buildable' subset (bottom 40th percentile of C_i within the run's own
    candidate set) and a rejection tally.

    Args:
        frame: games_enriched-shaped DataFrame for the run (storage.read_enriched
            output), including rows with NULL complexity_score.
        params: AnalysisParams with simplicity_percentile field (locked to 0.40),
            a percentile cutoff in (0, 1], NOT an absolute complexity_score
            ceiling.

    Returns:
        (buildable, rejected_by_reason): buildable contains rows whose
        complexity_score is non-null AND <= the run-local percentile cutoff.
        rejected_by_reason is a dict with keys:
        - 'above_simplicity_threshold': count of rows excluded for having
            complexity_score > cutoff
        - 'null_complexity_score': count of rows with NULL complexity_score

    Postconditions:
        len(buildable) + rejected_by_reason['above_simplicity_threshold'] +
        rejected_by_reason['null_complexity_score'] == len(frame)

        The percentile cutoff is computed fresh from THIS run's own non-null
        complexity_score distribution every call -- never carried over from
        another run or hard-coded.

    Edge cases:
        - A row exactly at the computed percentile cutoff is included in
          buildable (inclusive boundary, <=).
        - Every row with NULL complexity_score is excluded from buildable but
          counted under null_complexity_score.
        - All-NULL complexity_score frame returns an empty buildable without
          raising (pandas quantile on an empty non-null series is handled by
          short-circuiting to an empty buildable frame).
        - Empty (zero-row) frame returns empty buildable and all-zero tallies.
    """
    # Initialize rejection tallies
    rejected_by_reason = {"above_simplicity_threshold": 0, "null_complexity_score": 0}

    # Handle empty frame
    if len(frame) == 0:
        return pd.DataFrame(columns=frame.columns), rejected_by_reason

    # Separate rows with NULL complexity_score
    non_null_frame = frame[frame["complexity_score"].notna()]
    null_count = len(frame) - len(non_null_frame)
    rejected_by_reason["null_complexity_score"] = null_count

    # Handle all-NULL case: return empty buildable
    if len(non_null_frame) == 0:
        return pd.DataFrame(columns=frame.columns), rejected_by_reason

    # Compute percentile cutoff from this run's own non-null distribution
    # params.simplicity_percentile is in (0, 1], convert to percentile (0, 100]
    percentile_value = params.simplicity_percentile * 100
    cutoff = non_null_frame["complexity_score"].quantile(percentile_value / 100)

    # Split: buildable includes rows with complexity_score <= cutoff (inclusive)
    buildable = non_null_frame[non_null_frame["complexity_score"] <= cutoff]
    rejected_by_reason["above_simplicity_threshold"] = len(non_null_frame) - len(
        buildable
    )

    return buildable, rejected_by_reason
