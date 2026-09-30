"""Revenue estimation functions (FORMULATION.md sections 2-5).

Implements Boxleiter sales estimation with three-bucket genre scheme (low/mid/high bands),
gross/net revenue with storefront cut (F2P handling: NULL not zero), and effort-adjusted
return ranking.
"""

import pandas as pd
import numpy as np

from steam_analyst.config.settings import EnrichmentParams
from steam_analyst.enrichment.errors import EnrichmentError


def map_genre_bucket(genres: pd.Series, params: EnrichmentParams) -> pd.Series:
    """Map genre lists to multiplier buckets.

    Args:
        genres: A pd.Series of genre lists (already json.loads'd from genres_json),
                one list per appid, in the order Steam's appdetails API reports them
                (Steam's first-listed genre is generally its primary/marketing genre).
        params: EnrichmentParams with genre_bucket_map, mapping an individual genre
                string to a bucket key.

    Returns:
        A pd.Series of bucket key strings ('niche' | 'mainstream' |
        'broad_audience'), one per appid. Bucket selection rule: use the FIRST
        genre in the row's list that has an entry in genre_bucket_map (in list order,
        i.e. respecting Steam's primary-genre-first convention); if none of the row's
        genres match any key in genre_bucket_map, or the genre list is empty, fall back
        to 'mainstream' (the documented default bucket, per FORMULATION.md section 2).

    Preconditions:
        Every value in genres is a list[str] (possibly empty), never None.

    Postconditions:
        Every returned value is one of the three bucket keys present in
        params.boxleiter_multipliers. An unmatched or empty genre list always maps
        to 'mainstream', never raises.
    """
    default_bucket = "mainstream"

    def _map_row(genre_list):
        """Map a single row's genre list to a bucket key."""
        if not isinstance(genre_list, list) or len(genre_list) == 0:
            return default_bucket

        # Iterate through genres in order (respecting Steam's primary-genre-first)
        for genre in genre_list:
            if genre in params.genre_bucket_map:
                return params.genre_bucket_map[genre]

        # No matching genre found; fall back to default
        return default_bucket

    return genres.apply(_map_row)


def estimate_sales(
    review_count: pd.Series, genre_bucket: pd.Series, params: EnrichmentParams
) -> pd.DataFrame:
    """Compute estimated sales bands.

    Implements FORMULATION.md section 2 (Boxleiter method, three-bucket scheme,
    low/mid/high band).

    Args:
        review_count: r_i per appid (review count).
        genre_bucket: map_genre_bucket's output per appid.
        params: EnrichmentParams.boxleiter_multipliers, keyed by bucket name.

    Returns:
        A DataFrame with columns estimated_sales_low, estimated_sales_mid,
        estimated_sales_high, computed as review_count * m_low/mid/high(genre_bucket)
        respectively.

    Preconditions:
        review_count >= 0 for every row. Every genre_bucket value has a corresponding
        entry in params.boxleiter_multipliers.

    Postconditions:
        estimated_sales_low <= estimated_sales_mid <= estimated_sales_high for every
        row. review_count == 0 produces all three sales columns == 0.0.

    Edge cases:
        - review_count == 0: all three sales columns are exactly 0.0
        - unknown genre_bucket: raises EnrichmentError (programmer/config-drift condition)
        - very large review_count: no ceiling applied
    """
    result_data = {"estimated_sales_low": [], "estimated_sales_mid": [], "estimated_sales_high": []}

    for rc, bucket in zip(review_count, genre_bucket):
        if bucket not in params.boxleiter_multipliers:
            raise EnrichmentError(
                f"genre_bucket '{bucket}' not found in boxleiter_multipliers; "
                f"this indicates a config-drift or map_genre_bucket error"
            )

        m_low, m_mid, m_high = params.boxleiter_multipliers[bucket]
        result_data["estimated_sales_low"].append(float(rc * m_low))
        result_data["estimated_sales_mid"].append(float(rc * m_mid))
        result_data["estimated_sales_high"].append(float(rc * m_high))

    return pd.DataFrame(result_data, index=review_count.index)


def estimate_revenue(
    sales: pd.DataFrame, price_usd: pd.Series, params: EnrichmentParams
) -> pd.DataFrame:
    """Compute gross and net revenue bands.

    Implements FORMULATION.md section 3. Gross/net revenue with delta=rho=0 locked,
    storefront cut tau=0.30 applied, and the locked F2P policy (kept, revenue NULL)
    enforced.

    Args:
        sales: estimate_sales' output (estimated_sales_low/mid/high).
        price_usd: P_i per appid; 0 for free-to-play titles.
        params: EnrichmentParams.storefront_cut (tau), discount_factor (delta, locked 0.0),
                refund_regional_factor (rho, locked 0.0).

    Returns:
        A DataFrame with estimated_revenue_gross_usd and estimated_revenue_net_usd
        (single columns, computed from the MID sales estimate only, per the
        games_enriched schema which has one gross/net column pair, not per-band --
        the low/high bands remain available via estimated_sales_low/high for any
        caller that wants to derive a revenue range itself). gross = sales_mid * price_usd;
        net = gross * (1 - tau). Free-to-play rows (price_usd == 0, or more precisely
        the row's is_free flag) get NaN (rendered 'unknown', never 0) for both columns,
        per FORMULATION.md section 2's locked F2P policy.

    Preconditions:
        params.discount_factor == 0.0 and params.refund_regional_factor == 0.0 (locked).
        0 <= params.storefront_cut <= 1.

    Postconditions:
        F2P rows (price_usd == 0) have NaN in both revenue columns, never 0.0.
        For a non-F2P row, estimated_revenue_net_usd == estimated_revenue_gross_usd * (1 - tau) exactly.

    Edge cases:
        - price_usd == 0 for a title: treated as F2P, NaN is used regardless of is_free flag
        - price_usd > 0 and sales.estimated_sales_mid == 0: gross and net both 0.0, not NaN
        - storefront_cut == 0: net == gross exactly
    """
    gross_list = []
    net_list = []

    for price, sales_mid in zip(price_usd, sales["estimated_sales_mid"]):
        # F2P handling: price_usd == 0 means no revenue estimate is possible
        if price == 0:
            gross_list.append(np.nan)
            net_list.append(np.nan)
        else:
            # Non-F2P: compute gross and net revenue
            gross = sales_mid * price
            net = gross * (1 - params.storefront_cut)
            gross_list.append(float(gross))
            net_list.append(float(net))

    return pd.DataFrame(
        {
            "estimated_revenue_gross_usd": gross_list,
            "estimated_revenue_net_usd": net_list,
        },
        index=price_usd.index,
    )


def compute_effort_adjusted_return(
    net_revenue: pd.Series, complexity: pd.Series, params: EnrichmentParams
) -> pd.Series:
    """Compute effort-adjusted return.

    Implements FORMULATION.md section 5: E_i = R_i^net / (C_i + epsilon), epsilon
    locked to 0.05. Ordinal only, no monetary interpretation.

    Args:
        net_revenue: R_i^net per appid (may be NaN for F2P rows).
        complexity: C_i per appid (may be NaN for rows with too much missing complexity data).
        params: EnrichmentParams.effort_epsilon (locked 0.05).

    Returns:
        A pd.Series: net_revenue / (complexity + epsilon). NaN propagates from either
        input -- a F2P row (net_revenue NaN) or a too-much-missing-data row
        (complexity NaN) yields NaN here too, never a fabricated 0 or a computed value
        from a partially-undefined formula.

    Preconditions:
        params.effort_epsilon > 0.

    Postconditions:
        Result is finite for every row where both inputs are non-NaN, since
        complexity + epsilon is always > 0 (complexity is clipped to [0,1] and
        epsilon > 0). Result is NaN wherever either input is NaN.

    Edge cases:
        - complexity == 0.0 exactly: denominator is exactly epsilon; result stays finite
        - net_revenue is NaN (F2P row): NaN
        - complexity is NaN (excluded row): NaN
        - net_revenue == 0.0 (zero-review, non-F2P row): 0.0 exactly, not NaN
    """
    result = net_revenue / (complexity + params.effort_epsilon)
    return result
