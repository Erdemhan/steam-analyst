"""Display-ready transformations of analysis output DataFrames.

Rounds numeric columns to sensible precision, renames columns to human-readable form,
applies filters and sorting, and ensures sample sizes are always visible.
"""

import pandas as pd


# Column name mappings for opportunity matrix
OPPORTUNITY_MATRIX_COLUMN_MAPPING = {
    "cluster_id": "Cluster ID",
    "label": "Archetype",
    "n_games": "N",
    "demand_z": "Demand (z)",
    "competition_z": "Competition (z)",
    "simplicity_z": "Simplicity (z)",
    "opportunity_score": "Opportunity Score",
    "median_estimated_sales_mid": "Est. Sales (band mid)",
    "median_complexity": "Complexity",
    "releases_in_window": "Releases in Window",
}

# Column name mappings for tag summary
TAG_SUMMARY_COLUMN_MAPPING = {
    "tag": "Tag",
    "n_games": "N",
    "median_complexity_score": "Complexity",
    "median_estimated_sales_mid": "Est. Sales (band mid)",
    "median_review_positive_pct": "Positive %",
    "median_price_usd": "Price ($)",
}

# Rounding specifications: column_name -> decimal places
# Z-scores to 2 decimals
# Dollar figures to 0 decimals
# Complexity to 2 decimals
ROUNDING_SPECS = {
    "demand_z": 2,
    "competition_z": 2,
    "simplicity_z": 2,
    "opportunity_score": 2,
    "median_estimated_sales_mid": 0,
    "median_complexity": 2,
    "median_complexity_score": 2,
    "median_review_positive_pct": 2,
    "median_price_usd": 0,
    # n_games is never rounded
}


def build_opportunity_matrix_view(
    matrix: pd.DataFrame,
    *,
    min_n: int | None = None,
    sort_by: str = "opportunity_score",
) -> pd.DataFrame:
    """Build the display-ready opportunity matrix.

    Args:
        matrix: analysis_results['opportunity_matrix'] deserialized back into a DataFrame.
        min_n: Optional additional display-side filter on n_games, for a user who wants to
            further restrict beyond the analysis stage's own min_cluster_size (e.g. only show
            archetypes with n_games >= 10). None applies no additional filter.
        sort_by: Column to sort by, descending; must be one of matrix's own columns.

    Returns:
        A DataFrame with human-readable column headers (e.g. 'opportunity_score' ->
        'Opportunity Score'), numeric columns rounded to a fixed, sensible precision
        (z-scores to 2 decimals, dollar figures to 0 decimals, complexity/simplicity to
        2 decimals), and n_games always present and never rounded away.

    Raises:
        ValueError: If sort_by is not a valid column name in the input matrix.
    """
    # Make a copy to avoid modifying the input
    result = matrix.copy()

    # Validate sort_by column
    if sort_by not in result.columns:
        raise ValueError(
            f"sort_by column '{sort_by}' not found in matrix columns: {list(result.columns)}"
        )

    # Apply min_n filter if specified
    if min_n is not None:
        result = result[result["n_games"] >= min_n].copy()

    # Round numeric columns according to the spec
    for col, decimals in ROUNDING_SPECS.items():
        if col in result.columns and col != "n_games":
            result[col] = result[col].round(decimals)

    # Sort by the specified column (descending)
    result = result.sort_values(by=sort_by, ascending=False, na_position="last")

    # Rename columns to human-readable names
    # Only rename columns that exist in the dataframe
    rename_map = {
        old: new
        for old, new in OPPORTUNITY_MATRIX_COLUMN_MAPPING.items()
        if old in result.columns
    }
    result = result.rename(columns=rename_map)

    # Reorder columns to put renamed columns in a sensible order
    # Keep all columns that exist, in the order they appear in the mapping
    final_cols = []
    for col in matrix.columns:
        if col in OPPORTUNITY_MATRIX_COLUMN_MAPPING:
            # Map to new column name
            new_col = OPPORTUNITY_MATRIX_COLUMN_MAPPING[col]
            if new_col in result.columns:
                final_cols.append(new_col)
        else:
            # Keep unmapped columns if they exist
            if col in result.columns:
                final_cols.append(col)

    result = result[final_cols]

    return result


def build_tag_summary_table(
    tag_summary: pd.DataFrame, *, top_n: int = 100
) -> pd.DataFrame:
    """Build the display-ready tag summary table.

    Args:
        tag_summary: analysis_results['tag_summary'] deserialized back into a DataFrame.
        top_n: Maximum rows to return, selected by n_games descending (most-represented tags
            first) -- a display convenience since a run's full tag vocabulary can be large.

    Returns:
        A DataFrame limited to top_n rows sorted by n_games descending, with rounded/
        human-readable columns as in build_opportunity_matrix_view.

    Raises:
        ValueError: If top_n is not positive.
    """
    if top_n <= 0:
        raise ValueError(f"top_n must be positive, got {top_n}")

    # Make a copy to avoid modifying the input
    result = tag_summary.copy()

    # Sort by n_games descending to get the most-represented tags first
    result = result.sort_values(by="n_games", ascending=False, na_position="last")

    # Limit to top_n rows (return all if fewer than top_n)
    result = result.head(top_n)

    # Round numeric columns according to the spec
    for col, decimals in ROUNDING_SPECS.items():
        if col in result.columns and col != "n_games":
            result[col] = result[col].round(decimals)

    # Rename columns to human-readable names
    rename_map = {
        old: new
        for old, new in TAG_SUMMARY_COLUMN_MAPPING.items()
        if old in result.columns
    }
    result = result.rename(columns=rename_map)

    # Reorder columns to put renamed columns in a sensible order
    final_cols = []
    for col in tag_summary.columns:
        if col in TAG_SUMMARY_COLUMN_MAPPING:
            # Map to new column name
            new_col = TAG_SUMMARY_COLUMN_MAPPING[col]
            if new_col in result.columns:
                final_cols.append(new_col)
        else:
            # Keep unmapped columns if they exist
            if col in result.columns:
                final_cols.append(col)

    result = result[final_cols]

    return result
