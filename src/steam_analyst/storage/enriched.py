"""
Read/write enriched feature data for games.

Handles transactional replacement of enriched rows per run and flexible
read access with optional column projection and filtering.
"""

import sqlite3
from typing import Sequence

import pandas as pd
import numpy as np

from .connection import _check_same_thread
from .types import StorageError


# Define the full schema of the games_enriched table, in order.
# run_id is added by write_enriched; appid and all others come from the frame.
_GAMES_ENRICHED_COLUMNS = [
    "run_id",
    "appid",
    "name",
    "app_type",
    "developer",
    "publisher",
    "release_date",
    "price_usd",
    "is_free",
    "review_count",
    "review_positive_pct",
    "owners_estimate_low",
    "owners_estimate_mid",
    "owners_estimate_high",
    "size_bytes",
    "ram_bytes",
    "achievement_count",
    "language_count",
    "platform_count",
    "dlc_count",
    "dev_title_count",
    "is_early_access",
    "early_access_days",
    "deck_compat",
    "genres_json",
    "categories_json",
    "complexity_score",
    "imputed_features_json",
    "estimated_sales_low",
    "estimated_sales_mid",
    "estimated_sales_high",
    "estimated_revenue_gross_usd",
    "estimated_revenue_net_usd",
    "effort_adjusted_return",
    "parameters_version",
]

# Columns that should be present in the input frame (all except run_id).
_FRAME_REQUIRED_COLUMNS = [col for col in _GAMES_ENRICHED_COLUMNS if col != "run_id"]


def write_enriched(
    conn: sqlite3.Connection, run_id: str, frame: pd.DataFrame
) -> int:
    """Replace the enriched-feature rows for a run.

    Deletes all existing games_enriched rows for this run_id and inserts
    the new rows from frame in a single transaction, ensuring atomicity.
    NaN values are converted to SQL NULL, never 0 or empty string.

    Args:
        conn: An open connection.
        run_id: The run these rows belong to.
        frame: A DataFrame whose columns match games_enriched's non-key columns
            exactly (appid plus every derived/raw feature column listed in the
            schema). NULL/NaN values are written as SQL NULL, never coerced to
            0 or an empty string.

    Returns:
        The number of rows written (len(frame)).

    Raises:
        StorageError: If frame is missing a required column, if frame contains
            duplicate appid values (since (run_id, appid) is the primary key),
            or if run_id does not exist in the runs table.
    """
    _check_same_thread(conn)

    # Handle empty frame
    if len(frame) == 0:
        return 0

    # Verify that run_id exists
    cursor = conn.cursor()
    cursor.execute("SELECT run_id FROM runs WHERE run_id = ?", (run_id,))
    if cursor.fetchone() is None:
        raise StorageError(f"Run {run_id} does not exist")

    # Validate that all required columns are present
    missing_cols = set(_FRAME_REQUIRED_COLUMNS) - set(frame.columns)
    if missing_cols:
        raise StorageError(
            f"Frame is missing required columns: {', '.join(sorted(missing_cols))}"
        )

    # Check for duplicate appid values
    if frame["appid"].duplicated().any():
        raise StorageError("Frame contains duplicate appid values")

    # Start transaction (autocommit is off, so explicit BEGIN)
    try:
        cursor.execute("BEGIN TRANSACTION")

        # Delete existing rows for this run
        cursor.execute("DELETE FROM games_enriched WHERE run_id = ?", (run_id,))

        # Insert new rows
        # Build the VALUES clause with placeholders for all columns
        placeholders = ", ".join(["?"] * len(_GAMES_ENRICHED_COLUMNS))
        insert_sql = f"""
            INSERT INTO games_enriched ({", ".join(_GAMES_ENRICHED_COLUMNS)})
            VALUES ({placeholders})
        """

        # Prepare rows: add run_id at the start of each row
        rows_to_insert = []
        for _, row in frame.iterrows():
            # Start with run_id
            values = [run_id]
            # Add values for each column in _FRAME_REQUIRED_COLUMNS
            for col in _FRAME_REQUIRED_COLUMNS:
                val = row[col]
                # Convert NaN to None (which SQLite stores as NULL)
                if isinstance(val, float) and np.isnan(val):
                    values.append(None)
                elif pd.isna(val):
                    values.append(None)
                else:
                    values.append(val)
            rows_to_insert.append(tuple(values))

        cursor.executemany(insert_sql, rows_to_insert)
        conn.commit()

    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise StorageError(f"Integrity error writing enriched rows: {e}") from e
    except sqlite3.Error as e:
        conn.rollback()
        raise StorageError(f"Database error writing enriched rows: {e}") from e

    return len(frame)


def read_enriched(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    columns: Sequence[str] | None = None,
    where: str | None = None,
) -> pd.DataFrame:
    """Read enriched rows for a run.

    Optionally projects to a column subset and filters with a raw SQL WHERE
    fragment. The WHERE clause is trusted, non-user-facing input intended
    for internal use by analysis and reporting modules, never for end-user
    strings (no SQL injection protection beyond basic type checking).

    Args:
        conn: An open connection.
        run_id: The run to read.
        columns: Column subset to select; None selects all columns. Must be
            valid column names if specified.
        where: An optional raw SQL boolean expression (column references only,
            e.g. "complexity_score IS NOT NULL") appended after `WHERE run_id = ?`.
            Callers are internal modules passing static code-authored fragments.

    Returns:
        A DataFrame with SQL NULL mapped to pandas NA/NaN, one row per
        matching game. Column order matches the requested `columns` order
        when given, or the schema's natural column order otherwise.

    Raises:
        StorageError: If columns contains an unknown column name, raised
            before querying the database.
    """
    _check_same_thread(conn)

    # Determine which columns to select
    if columns is None:
        select_cols = _GAMES_ENRICHED_COLUMNS
    else:
        select_cols = list(columns)

        # Validate that all requested columns exist
        unknown_cols = set(select_cols) - set(_GAMES_ENRICHED_COLUMNS)
        if unknown_cols:
            raise StorageError(
                f"Unknown column names: {', '.join(sorted(unknown_cols))}"
            )

    # Build the SQL query
    select_clause = ", ".join(select_cols)
    query = f"SELECT {select_clause} FROM games_enriched WHERE run_id = ?"
    params = [run_id]

    if where:
        query += f" AND {where}"

    # Execute query
    cursor = conn.cursor()
    cursor.execute(query, params)

    # Fetch all rows
    rows = cursor.fetchall()

    # Convert to DataFrame
    if not rows:
        # Return empty DataFrame with correct columns
        return pd.DataFrame(columns=select_cols)

    # Convert sqlite3.Row objects to dictionaries
    data = [dict(row) for row in rows]
    df = pd.DataFrame(data)

    # Ensure column order matches the requested order
    df = df[select_cols]

    return df
