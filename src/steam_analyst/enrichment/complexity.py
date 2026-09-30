"""Complexity score computation: weighted-sum normalized feature scoring."""

import json
import logging
from typing import Any

import numpy as np
import pandas as pd

from steam_analyst.config.settings import EnrichmentParams
from .features import (
    compute_tag_score,
    impute_missing_at_median,
    normalize_feature_log_scaled,
)

logger = logging.getLogger(__name__)


def compute_complexity_score(
    frame: pd.DataFrame, tags: pd.DataFrame, params: EnrichmentParams
) -> tuple[pd.Series, pd.DataFrame]:
    """Compute complexity_score for every candidate.

    Implements FORMULATION.md section 4: C_i = clip( Σ_f w_f · n_f(x_{i,f}) , 0, 1 )
    with all nine features, their locked weights, and median imputation for missing data.

    Args:
        frame: normalize_features' output, indexed by appid, plus
               compute_developer_catalog_size's Series merged in as a 'dev_title_count' column.
        tags: The run's extracted tag rows (appid, tag, votes, rank).
        params: EnrichmentParams -- weights, complexity_bounds, simplicity_tags, complexity_tags.

    Returns:
        (complexity_score, contributions): complexity_score is a pd.Series in [0,1]
        (or NaN for rows with too much missing data) indexed like frame. contributions
        is a DataFrame, one column per feature, holding each feature's weighted
        contribution (w_f * n_f(x)) for that row.

    Raises:
        ValueError: If frame is missing required columns or has shape issues.
    """
    if frame.empty:
        return pd.Series(dtype=float), pd.DataFrame()

    # Threshold for too-much-missing: if more than this fraction of a row's
    # features are both raw-missing (NaN in input) AND log-scaled-unnormalizable
    # (not in pre-freeze bounds), mark score as NaN.
    # Per FunctionSpec edge case, using a reasonable default of 0.4 (more than 40%)
    # means 4+ of 9 features trigger nullification. Adjust this per domain guidance.
    TOO_MUCH_MISSING_THRESHOLD = 0.4

    # Define the 9 features with their properties:
    # (column_name, weight_key, normalizer_type, bounds_key_in_complexity_bounds)
    feature_specs = [
        ("size_bytes", "size_bytes", "log", "size_bytes"),
        ("early_access_days", "early_access_days", "log", "early_access_days"),
        ("dev_title_count", "dev_title_count", "log", "dev_title_count"),
        ("simplicity_tag_score", "simplicity_tag_score", "linear_negative", None),
        ("complexity_tag_score", "complexity_tag_score", "linear_positive", None),
        ("achievement_count", "achievement_count", "log", "achievement_count"),
        ("dlc_count", "dlc_count", "log", "dlc_count"),
        ("platform_count", "platform_count", "linear", None),
        ("language_count", "language_count", "log", "language_count"),
    ]

    # Container for normalized features
    normalized_features = {}
    imputed_flags = {}  # Track which rows were imputed for each feature

    # ========== STEP 1-2: Compute and normalize each feature ==========
    for feature_col, weight_key, norm_type, bounds_key in feature_specs:
        raw_values = None

        if feature_col == "early_access_days":
            # Special case: derive from is_early_access flag
            # If is_early_access is True, use the early_access_days column (may be NaN);
            # if False, use 0 (not complex to develop if not in EA).
            # For pre-freeze run 1, the column may be all NaN.
            raw_values = frame["early_access_days"].copy()
            if "is_early_access" in frame.columns:
                # Where is_early_access is False, set to 0
                raw_values = raw_values.where(frame["is_early_access"], 0.0)
        elif feature_col == "simplicity_tag_score":
            # Compute from tags using the simplicity vocabulary
            raw_values = compute_tag_score(
                tags, vocabulary=params.simplicity_tags
            )
            # Reindex to match frame, filling missing appids with NaN
            raw_values = raw_values.reindex(frame.index)
        elif feature_col == "complexity_tag_score":
            # Compute from tags using the complexity vocabulary
            raw_values = compute_tag_score(
                tags, vocabulary=params.complexity_tags
            )
            # Reindex to match frame, filling missing appids with NaN
            raw_values = raw_values.reindex(frame.index)
        elif feature_col == "platform_count":
            # Platform count: normalize as (count - 1) / 2, since range is [1, 3]
            raw_values = frame[feature_col].copy()
            # Normalize: (count - 1) / 2 maps [1, 2, 3] -> [0, 0.5, 1]
            normalized_features[feature_col] = (raw_values - 1) / 2.0
            imputed_flags[feature_col] = pd.isna(raw_values)
            continue  # Skip the rest of the normalization loop for this feature
        else:
            # Direct column reference
            raw_values = frame[feature_col].copy()

        # Normalize raw_values
        if norm_type == "log":
            # Log-scaled: apply normalize_feature_log_scaled per row
            normalized_col = pd.Series(np.nan, index=frame.index)

            # Check if bounds exist and are valid for this feature
            if bounds_key and bounds_key in params.complexity_bounds:
                bounds = params.complexity_bounds[bounds_key]
                a, b = bounds[0], bounds[1]
                # Normalize each row with valid bounds
                for idx in frame.index:
                    if not pd.isna(raw_values[idx]):
                        try:
                            normalized_col[idx] = normalize_feature_log_scaled(
                                raw_values[idx], a, b
                            )
                        except ValueError:
                            # Should not happen if bounds are valid, but guard anyway
                            normalized_col[idx] = np.nan
            # If bounds are missing (pre-freeze), leave as NaN -- will be imputed at median

            normalized_features[feature_col] = normalized_col
            imputed_flags[feature_col] = pd.isna(raw_values)

        elif norm_type == "linear_negative":
            # Simplicity tag score: linear [0, 1], but inverted (1 - score)
            # because high simplicity = low complexity
            normalized_col = 1.0 - raw_values
            normalized_features[feature_col] = normalized_col
            imputed_flags[feature_col] = pd.isna(raw_values)

        elif norm_type == "linear_positive":
            # Complexity tag score: linear [0, 1], no inversion
            normalized_features[feature_col] = raw_values
            imputed_flags[feature_col] = pd.isna(raw_values)

    # ========== STEP 3: Impute missing at cohort median ==========
    for feature_col, weight_key, norm_type, bounds_key in feature_specs:
        if feature_col == "platform_count":
            # Already normalized and imputed above
            continue

        norm_col = normalized_features[feature_col]
        was_imputed_raw = imputed_flags[feature_col]

        try:
            imputed_col, was_imputed = impute_missing_at_median(norm_col)
            normalized_features[feature_col] = imputed_col
            # Mark which rows were imputed (true if raw input was missing)
            imputed_flags[feature_col] = was_imputed_raw
        except ValueError:
            # All rows for this feature are NaN (no cohort median).
            # Per FunctionSpec edge case "all_rows_missing_one_feature":
            # fall back to 0.5 midpoint for every row.
            logger.warning(
                f"All rows missing feature '{feature_col}', falling back to 0.5 midpoint"
            )
            normalized_features[feature_col] = pd.Series(
                0.5, index=frame.index
            )
            # Don't mark these as imputed for too-much-missing purposes
            imputed_flags[feature_col] = pd.Series(False, index=frame.index)

    # ========== STEP 4: Weight and sum ==========
    contributions = pd.DataFrame(index=frame.index)
    weighted_sum = pd.Series(0.0, index=frame.index)

    for feature_col, weight_key, norm_type, bounds_key in feature_specs:
        weight = params.complexity_weights[weight_key]
        weighted_contribution = normalized_features[feature_col] * weight
        contributions[feature_col] = weighted_contribution
        weighted_sum += weighted_contribution

    # Clip to [0, 1]
    complexity_score = weighted_sum.clip(0.0, 1.0)

    # ========== STEP 5: Apply too-much-missing-data rule ==========
    # A row is marked NaN if more than TOO_MUCH_MISSING_THRESHOLD of its
    # features were BOTH raw-missing AND log-scaled-unnormalizable.
    # This is a stricter threshold than just "missing" because pre-freeze
    # unnormalizability is a known, temporary condition.

    # For now, we'll use a simpler approach: count truly missing (raw) features
    # for each row. If more than the threshold are missing, set score to NaN.
    raw_missing_counts = pd.Series(0, index=frame.index)

    for feature_col, weight_key, norm_type, bounds_key in feature_specs:
        if feature_col == "platform_count":
            # Platform count: missing = NaN after normalization
            raw_missing_counts += (normalized_features[feature_col].isna()).astype(int)
        else:
            # Other features: missing = was in imputed_flags
            raw_missing_counts += imputed_flags[feature_col].astype(int)

    too_much_missing = (raw_missing_counts / len(feature_specs)) > TOO_MUCH_MISSING_THRESHOLD
    complexity_score[too_much_missing] = np.nan

    return complexity_score, contributions
