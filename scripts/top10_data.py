"""Data preparation for the top-10 game report (read-only on the run database).

The selection rule is deliberately simple and uses only quantities that already
exist in the pipeline output (FORMULATION.md §3a, §5, §6):

1. Simple subset: ``complexity_score`` at or below the 40th percentile of the run.
2. Released within the trailing window ``W`` (48 months before the run start).
3. Member of a scored archetype whose opportunity score ``Ω_k`` is positive.
4. Paid (revenue is known), not Early Access, positive review share >= 0.80.
5. Ranked by effort-adjusted return ``E_i``; at most ``MAX_PER_ARCHETYPE`` per archetype.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

RUN_ID = "20261003T204134704Z-d8d2b3"
WINDOW_MONTHS = 48
SIMPLE_PERCENTILE = 0.40
MIN_POSITIVE_SHARE = 0.80
MAX_PER_ARCHETYPE = 2
TOP_N = 10
SOFTWARE_CLUSTER_ID = 15  # "Utilities / Software / Design & Illustration", see todo.md item 9


@dataclass
class ReportData:
    """Everything the figure and markdown builders need."""

    run: dict
    games: pd.DataFrame  # all enriched games of the run with cluster columns
    pool: pd.DataFrame  # steps 1-3 (before paid / EA / review filters)
    eligible: pd.DataFrame  # steps 1-4, ranked by E_i
    top: pd.DataFrame  # final selection
    funnel: list[tuple[str, int]]
    matrix: pd.DataFrame
    trends: pd.DataFrame
    cluster_members: dict
    tags: pd.DataFrame
    simple_threshold: float
    window_start: pd.Timestamp
    outside_hits: pd.DataFrame  # strong E_i games in non-positive archetypes


def _payload(con: sqlite3.Connection, kind: str):
    row = con.execute(
        "select payload_json from analysis_results where run_id=? and analysis_type=?",
        (RUN_ID, kind),
    ).fetchone()
    return json.loads(row[0])


def _steamspy_owners(con: sqlite3.Connection, appids: list[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for appid in appids:
        row = con.execute(
            "select payload_json from raw_games where run_id=? and appid=? and source='steamspy_all'",
            (RUN_ID, appid),
        ).fetchone()
        if row:
            j = json.loads(row[0])
            out[appid] = {"owners_text": j.get("owners"), "ccu": j.get("ccu")}
    return out


def _owner_bounds(text: str | None) -> tuple[float, float] | tuple[None, None]:
    if not text:
        return None, None
    lo, hi = (int(p.replace(",", "").strip()) for p in text.split(".."))
    return float(lo), float(hi)


def load(db_path: Path) -> ReportData:
    """Load the run, apply the selection rule and return all derived tables."""
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    run = dict(
        zip(
            ["run_id", "started_at", "finished_at", "status", "notes"],
            con.execute(
                "select run_id, started_at, finished_at, status, notes from runs where run_id=?",
                (RUN_ID,),
            ).fetchone(),
        )
    )
    g = pd.read_sql("select * from games_enriched where run_id=?", con, params=(RUN_ID,))
    g["release"] = pd.to_datetime(g["release_date"], format="%b %d, %Y", errors="coerce")
    g["name"] = g["name"].str.replace("�", "'", regex=False)
    g["developer"] = g["developer"].fillna("").str.replace("�", "ö", regex=False)

    clusters = _payload(con, "tag_clusters")
    assign = pd.DataFrame(clusters["assignments"])
    matrix = pd.DataFrame(_payload(con, "opportunity_matrix")["data"])
    trends = pd.DataFrame(_payload(con, "tag_trends")["data"])
    g = g.merge(assign, on="appid", how="left")

    run_start = pd.Timestamp(run["started_at"][:10])
    window_start = run_start - pd.DateOffset(months=WINDOW_MONTHS)
    thr = float(g["complexity_score"].quantile(SIMPLE_PERCENTILE))

    simple = g[g["complexity_score"] <= thr]
    in_window = simple[simple["release"] >= window_start]
    scored = in_window.merge(
        matrix[["cluster_id", "label", "opportunity_score", "demand_z", "competition_z", "simplicity_z"]],
        on="cluster_id",
    )
    scored = scored[scored["cluster_id"] != SOFTWARE_CLUSTER_ID]
    positive = scored[scored["opportunity_score"] > 0]

    paid = positive[positive["is_free"] == 0]
    not_ea = paid[paid["is_early_access"] == 0]
    eligible = not_ea[not_ea["review_positive_pct"] >= MIN_POSITIVE_SHARE].sort_values(
        "effort_adjusted_return", ascending=False
    )
    top = eligible.groupby("cluster_id", sort=False).head(MAX_PER_ARCHETYPE).head(TOP_N).copy()

    top["age_months"] = (run_start - top["release"]).dt.days / 30.4375
    top["sales_per_month"] = top["estimated_sales_mid"] / top["age_months"]
    top["rank"] = range(1, len(top) + 1)

    owners = _steamspy_owners(con, top["appid"].tolist())
    top["steamspy_owners"] = top["appid"].map(lambda a: owners.get(a, {}).get("owners_text"))
    top["owners_lo"] = top["steamspy_owners"].map(lambda t: _owner_bounds(t)[0])
    top["owners_hi"] = top["steamspy_owners"].map(lambda t: _owner_bounds(t)[1])

    tags = pd.read_sql(
        "select appid, tag, votes, rank from game_tags where run_id=?", con, params=(RUN_ID,)
    )

    # Strong games that the opportunity-set rule leaves out (negative-Ω archetypes).
    neg = g[(g["complexity_score"] <= thr) & (g["release"] >= window_start)].merge(
        matrix[["cluster_id", "label", "opportunity_score"]], on="cluster_id"
    )
    neg = neg[
        (neg["opportunity_score"] <= 0)
        & (neg["is_free"] == 0)
        & (neg["review_positive_pct"] >= MIN_POSITIVE_SHARE)
    ].sort_values("effort_adjusted_return", ascending=False)

    funnel = [
        ("Enriched games in the run", len(g)),
        ("Simple subset (C ≤ P40)", len(simple)),
        ("Released within W = 48 months", len(in_window)),
        ("In a scored archetype (software cluster removed)", len(scored)),
        ("In an archetype with Ω > 0", len(positive)),
        ("Paid, not Early Access, ≥ 80% positive", len(eligible)),
        ("Final selection (≤ 2 per archetype)", len(top)),
    ]
    return ReportData(
        run=run,
        games=g,
        pool=positive,
        eligible=eligible,
        top=top,
        funnel=funnel,
        matrix=matrix,
        trends=trends,
        cluster_members=clusters["cluster_members"],
        tags=tags,
        simple_threshold=thr,
        window_start=window_start,
        outside_hits=neg.head(8),
    )


if __name__ == "__main__":
    import sys

    pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_colwidth", 30)
    d = load(Path(sys.argv[1]))
    print(d.funnel, d.simple_threshold, d.window_start)
    cols = ["rank", "name", "label", "release", "price_usd", "review_count", "review_positive_pct",
            "complexity_score", "estimated_sales_mid", "estimated_revenue_net_usd",
            "effort_adjusted_return", "age_months", "sales_per_month", "steamspy_owners"]
    print(d.top[cols])
    print(d.outside_hits[["name", "label", "effort_adjusted_return", "is_early_access"]])
