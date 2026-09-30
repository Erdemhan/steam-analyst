"""Pure statistical helper functions for complexity score and enrichment."""

import numpy as np
import pandas as pd


def normalize_feature_log_scaled(x: float, a: float, b: float) -> float:
    """Normalize one raw feature value to [0, 1] via a log10 scale.

    Implements FORMULATION.md section 4's log-scaled per-feature normalizer:
    n(x) = clip((log10(x + 1) - a) / (b - a), 0, 1).

    Args:
        x: Raw feature value, x >= 0 (a count or byte size; log10(x+1) keeps x=0 finite).
        a: Lower normalization bound (on the log10(x+1) scale), typically the run 1 empirical 5th percentile.
        b: Upper normalization bound, typically the run 1 empirical 95th percentile.

    Returns:
        Normalized value in [0.0, 1.0], monotonically non-decreasing in x.

    Raises:
        ValueError: If b == a (degenerate bounds would divide by zero) or x < 0.
    """
    if x < 0:
        raise ValueError(f"x must be >= 0, got {x}")
    if b == a:
        raise ValueError(f"Degenerate bounds: a == b == {a}")

    log_x = np.log10(x + 1)
    normalized = (log_x - a) / (b - a)
    return float(np.clip(normalized, 0.0, 1.0))


def impute_missing_at_median(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Impute NaN entries at the column's own median and flag which rows were imputed.

    Per FORMULATION.md section 4, 'Missing values' note: a feature absent from
    appdetails contributes its weight at the cohort median rather than at zero.

    Args:
        values: A single already-normalized-to-[0, 1] feature column for the candidate
                cohort, with NaN for rows where the raw input was missing or the feature
                was not yet normalizable.

    Returns:
        (imputed_values, was_imputed): imputed_values has every NaN replaced by
        nanmedian(values) computed over the non-NaN entries of THIS SAME candidate
        cohort; was_imputed is a boolean Series, True exactly where an original NaN
        was replaced.

    Raises:
        ValueError: If values is entirely NaN (no cohort median exists to impute from).
                    The caller must catch this and apply the documented 0.5 fallback.
    """
    if values.isna().all():
        raise ValueError("Cannot impute from an entirely NaN series; no median exists")

    was_imputed = values.isna()
    median_val = values.median()
    imputed_values = values.fillna(median_val)

    return imputed_values, was_imputed


def compute_tag_score(tags: pd.DataFrame, *, vocabulary: list[str]) -> pd.Series:
    """Compute a per-appid tag-match score against a fixed vocabulary.

    Computes the fraction of an app's retained tags that fall in the vocabulary.

    Args:
        tags: game_tags-shaped DataFrame (appid, tag, votes, rank), typically
              the output of extract_tags materialized into a frame or storage.read_tags.
        vocabulary: EnrichmentParams.simplicity_tags or .complexity_tags, a list of
                    tag strings. Comparison is case-insensitive.

    Returns:
        A pd.Series indexed by appid, one row per DISTINCT appid present in tags,
        giving the linear match score: count(matching tags) / count(this app's total
        retained tags), a value in [0, 1]. Appids not present in tags at all are
        absent from the returned Series (not present means unknown, not 0.0).

    Preconditions:
        - vocabulary entries should be lowercase-normalized for consistent comparison
        - tags has no duplicate (appid, tag) pairs (guaranteed by extract_tags)
    """
    # Normalize vocabulary to lowercase for case-insensitive matching
    vocab_lower = set(tag.lower() for tag in vocabulary)

    if tags.empty:
        # An empty frame has no columns with a real dtype to call .str on;
        # there are no appids to score, so return an empty Series directly.
        return pd.Series(dtype=float, name="matches_vocab")

    # Create lowercase tag column for matching
    tags_copy = tags.copy()
    tags_copy["tag_lower"] = tags_copy["tag"].astype(str).str.lower()

    # Mark which tags match the vocabulary
    tags_copy["matches_vocab"] = tags_copy["tag_lower"].isin(vocab_lower)

    # Group by appid and compute the fraction of matching tags per appid
    grouped = tags_copy.groupby("appid")
    match_counts = grouped["matches_vocab"].sum()
    total_counts = grouped.size()

    # Compute score as fraction of matching tags; exclude appids with zero tags
    score = match_counts / total_counts

    return score


def compute_developer_catalog_size(
    frame: pd.DataFrame, catalog: pd.DataFrame
) -> pd.Series:
    """Compute per-row developer catalog size.

    Counts other titles by the same developer, counted against the full SteamSpy
    catalog snapshot, not only the candidate set, so a prolific studio filtered
    out at stage one does not look like a first-time solo developer.

    Args:
        frame: The (candidate-scoped) normalized feature frame, indexed by appid,
               with a 'developer' column.
        catalog: The FULL bulk catalog frame (not just survivors), also with a
                 'developer' column.

    Returns:
        A pd.Series indexed like frame, giving count of OTHER apps (excluding the
        row's own appid) in catalog sharing the same developer string (exact,
        case-sensitive match on the raw developer field).

    Preconditions:
        - catalog contains every appid in frame (frame's candidates are a subset of catalog)
        - developer column is present in both frame and catalog

    Edge cases:
        - A developer with only one title in catalog returns 0 for that title
        - NaN/empty developer never matches another NaN/empty row
        - Case-sensitive: 'Team Cherry' != 'team cherry'
    """
    # Index catalog by appid for efficient lookups
    catalog_indexed = catalog.set_index("appid")

    # For each row in frame, count other apps by the same developer in catalog
    def count_other_titles(row):
        appid = row.name
        developer = row["developer"]

        # NaN developers never match anything
        if pd.isna(developer):
            return 0

        # Find all apps in catalog with the same developer
        same_dev_mask = catalog_indexed["developer"] == developer
        same_dev_count = same_dev_mask.sum()

        # Subtract 1 to exclude the app itself
        return max(0, same_dev_count - 1)

    result = frame.apply(count_other_titles, axis=1)
    return result
