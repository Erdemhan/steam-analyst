"""Build rapor.md (top-10 game report) and its figures from the stored run.

Usage:
    python scripts/build_top10_report.py --db data/analyses.db

The report is derived from ``games_enriched``, ``tag_clusters``, ``opportunity_matrix`` and
``tag_trends`` of one stored run. Nothing is fetched from the network. The per-game
commentary lives in ``scripts/top10_notes.py`` and is the only hand-written part.
Requires matplotlib (not part of requirements.txt, report-only dependency).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import top10_data as t
import top10_figures as figs
from top10_notes import GAME_NOTES

ROOT = Path(__file__).resolve().parents[1]


def usd(x: float) -> str:
    if pd.isna(x):
        return "n/a"
    if abs(x) >= 1e6:
        return f"${x / 1e6:,.2f}M"
    if abs(x) >= 1e3:
        return f"${x / 1e3:,.0f}k"
    return f"${x:,.2f}"


def units(x: float) -> str:
    if pd.isna(x):
        return "n/a"
    return f"{x / 1e6:.2f}M" if x >= 1e6 else f"{x / 1e3:,.0f}k"


def size_txt(b: float) -> str:
    if pd.isna(b):
        return "n/a"
    return f"{b / 1e9:.1f} GB" if b >= 1e9 else f"{b / 1e6:,.0f} MB"


def ordinal(x: float) -> str:
    n = max(1, int(round(x)))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def join_names(names: list[str]) -> str:
    return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else (names[0] if names else "no game")


def short_label(label: str) -> str:
    return label.split(" / ")[0]


def band_position(mid: float, lo: float, hi: float) -> str:
    if pd.isna(lo):
        return "n/a"
    if mid < lo:
        return "below"
    if mid > hi:
        return "above"
    return "within"


def label_tags(d: t.ReportData, appid: int, label: str) -> str:
    tg = d.tags[d.tags["appid"] == appid].set_index("tag")["votes"]
    parts = []
    for name in label.split(" / "):
        parts.append(f"{name} ({int(tg[name])})" if name in tg.index else f"{name} (not in stored tags)")
    return ", ".join(parts)


def top_tags(d: t.ReportData, appid: int, n: int = 8) -> str:
    tg = d.tags[d.tags["appid"] == appid].sort_values("votes", ascending=False).head(n)
    return ", ".join(f"{a} ({int(b)})" for a, b in zip(tg["tag"], tg["votes"]))


def early_access_variant(d: t.ReportData) -> pd.DataFrame:
    p = d.pool
    p = p[(p["is_free"] == 0) & (p["review_positive_pct"] >= t.MIN_POSITIVE_SHARE)]
    p = p.sort_values("effort_adjusted_return", ascending=False)
    return p.groupby("cluster_id", sort=False).head(t.MAX_PER_ARCHETYPE).head(t.TOP_N)


def game_section(d: t.ReportData, r: pd.Series, simple_pool: pd.DataFrame) -> str:
    cat = json.loads(r["categories_json"]) if isinstance(r["categories_json"], str) else []
    modes = [m for m in ("Single-player", "Multi-player", "Co-op", "PvP", "Online PvP", "Online Co-op") if m in cat]
    imputed = json.loads(r["imputed_features_json"]) if isinstance(r["imputed_features_json"], str) else []
    c_pct = float((simple_pool["complexity_score"] <= r["complexity_score"]).mean()) * 100
    c_pool_pct = float((d.pool["complexity_score"] <= r["complexity_score"]).mean()) * 100
    band = band_position(r["estimated_sales_mid"], r["owners_lo"], r["owners_hi"])
    arche = d.matrix[d.matrix["cluster_id"] == r["cluster_id"]].iloc[0]
    n = GAME_NOTES[r["appid"]]
    lines = [
        f"### {int(r['rank'])}. {r['name']}",
        "",
        "| | | | |",
        "|---|---|---|---|",
        f"| Developer / publisher | {r['developer']} / {r['publisher']} | Release | {r['release_date']} ({r['age_months']:.0f} months before the run) |",
        f"| Archetype (Ω) | {short_label(r['label'])} ({r['opportunity_score']:+.2f}, {int(arche['n_games'])} games) | List price | ${r['price_usd']:.2f} |",
        f"| Reviews / positive share | {int(r['review_count']):,} / {r['review_positive_pct'] * 100:.1f}% | Estimated units low / mid / high | {units(r['estimated_sales_low'])} / {units(r['estimated_sales_mid'])} / {units(r['estimated_sales_high'])} |",
        f"| Estimated net revenue | {usd(r['estimated_revenue_net_usd'])} | Effort-adjusted return E | {r['effort_adjusted_return'] / 1e6:,.1f}M |",
        f"| Complexity score C | {r['complexity_score']:.3f} ({ordinal(c_pct)} percentile of the 1,201 simple games, {ordinal(c_pool_pct)} of the 76-game pool) | SteamSpy owners | {r['steamspy_owners'] or 'n/a'}, Boxleiter mid is **{band}** the band |",
        f"| Average units per month | {r['sales_per_month']:,.0f} | Install size / minimum RAM | {size_txt(r['size_bytes'])} / {size_txt(r['ram_bytes'])} |",
        f"| Languages / achievements / DLC / platforms | {int(r['language_count'])} / {'n/a' if pd.isna(r['achievement_count']) else int(r['achievement_count'])} / {int(r['dlc_count'])} / {int(r['platform_count'])} | Player modes (Steam categories) | {', '.join(modes) or 'n/a'} |",
        "",
        f"Most-voted tags: {top_tags(d, int(r['appid']))}.",
        "",
        f"Archetype label tags carried by this game: {label_tags(d, int(r['appid']), r['label'])}."
        + (f" Imputed complexity inputs: {', '.join(imputed)}." if imputed else ""),
        "",
    ]
    lines += [f"- {x}" for x in n["observations"]]
    lines += ["", f"**Reading for a small team.** {n['reading']}", ""]
    return "\n".join(lines)


def build(db: Path, out_md: Path, assets: Path) -> None:
    d = t.load(db)
    f = figs.build_all(d, assets)
    top = d.top
    rel = lambda p: f"{assets.name}/{p.name}"  # noqa: E731
    simple_pool = d.games[d.games["complexity_score"] <= d.simple_threshold]

    arche_ids = list(dict.fromkeys(top["cluster_id"].astype(int)))
    am = d.matrix.set_index("cluster_id").loc[arche_ids]

    ea_variant = early_access_variant(d)
    ea_added = ea_variant[~ea_variant["appid"].isin(top["appid"])]
    ea_removed = top[~top["appid"].isin(ea_variant["appid"])]

    band_counts = top.apply(lambda r: band_position(r["estimated_sales_mid"], r["owners_lo"], r["owners_hi"]), axis=1).value_counts()
    self_pub = int((top["developer"] == top["publisher"]).sum())
    one_lang = int((top["language_count"] == 1).sum())

    overview = ["| # | Game | Archetype | Release | Price | Reviews (pos.) | Est. units (mid) | Est. net revenue | C | E (M) |",
                "|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in top.iterrows():
        overview.append(
            f"| {int(r['rank'])} | {r['name']} | {short_label(r['label'])} | {r['release'].strftime('%Y-%m')} | ${r['price_usd']:.2f} | "
            f"{int(r['review_count']):,} ({r['review_positive_pct'] * 100:.0f}%) | {units(r['estimated_sales_mid'])} | "
            f"{usd(r['estimated_revenue_net_usd'])} | {r['complexity_score']:.3f} | {r['effort_adjusted_return'] / 1e6:,.1f} |")

    arche_rows = ["| Archetype | Games | D | K | Σ | Ω | Median est. units | Median C | Singleplayer / Multiplayer / Co-op share | Selected games |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
    for cid, r in am.iterrows():
        picked = ", ".join(top[top["cluster_id"] == cid]["name"])
        arche_rows.append(
            f"| {r['label']} | {int(r['n_games'])} | {r['demand_z']:+.2f} | {r['competition_z']:+.2f} | {r['simplicity_z']:+.2f} | "
            f"{r['opportunity_score']:+.2f} | {r['median_estimated_sales_mid']:,.0f} | {r['median_complexity']:.3f} | "
            f"{r['singleplayer_share'] * 100:.0f}% / {r['multiplayer_share'] * 100:.0f}% / {r['coop_share'] * 100:.0f}% | {picked} |")

    outside = ["| Game | Archetype (Ω) | Est. units (mid) | Est. net revenue | C | E (M) | Early Access |", "|---|---|---|---|---|---|---|"]
    for _, r in d.outside_hits.iterrows():
        outside.append(
            f"| {r['name']} | {short_label(r['label'])} ({r['opportunity_score']:+.2f}) | {units(r['estimated_sales_mid'])} | "
            f"{usd(r['estimated_revenue_net_usd'])} | {r['complexity_score']:.3f} | {r['effort_adjusted_return'] / 1e6:,.1f} | {'yes' if r['is_early_access'] else 'no'} |")

    mp = am[am["multiplayer_share"] > 0.10]
    mp_names = [f"{short_label(l)} ({s * 100:.0f}%)" for l, s in zip(mp["label"], mp["multiplayer_share"])]
    mp_text = ("Only " + (", ".join(mp_names[:-1]) + " and " + mp_names[-1] if len(mp_names) > 1 else mp_names[0])
               + " show a multiplayer share above 10%.") if len(mp) else "None shows a multiplayer share above 10%."
    ea_prices = join_names([f"{n} (${p:.2f})" for n, p in zip(ea_added["name"], ea_added["price_usd"])])

    total_mid = top["estimated_sales_mid"].sum()
    total_rev = top["estimated_revenue_net_usd"].sum()
    pt = top.iloc[0]
    pt_share = pt["estimated_revenue_net_usd"] / total_rev * 100
    med_price = top["price_usd"].median()
    med_c = top["complexity_score"].median()
    pool_med_c = d.pool["complexity_score"].median()

    md = f"""# Top 10 Games Under the Current Analysis

Report generated from stored run `{t.RUN_ID}` ({d.run['notes']}), started {d.run['started_at'][:10]} and finished {d.run['finished_at'][:10]}.
All figures are derived from the stored data. No new network requests were made. Regenerate with
`python scripts/build_top10_report.py --db data/analyses.db`.

## 1. Summary

The ten games were chosen from the {d.funnel[1][1]:,}-game simple subset of the run (complexity score C in the bottom 40%).
Each of them was released within the 48-month window, belongs to an archetype with a positive opportunity score Ω,
is paid, has left Early Access, and has at least 80% positive reviews. They were ranked by the effort-adjusted return E
of FORMULATION §5, with at most two games per archetype.

- The selection covers six archetypes: {', '.join(short_label(l) for l in am['label'])}. The two archetypes with the largest Ω are Comedy ({am.loc[70, 'opportunity_score']:+.2f}) and Stylized ({am.loc[86, 'opportunity_score']:+.2f}).
- Together the ten games account for roughly {units(total_mid)} estimated units and {usd(total_rev)} estimated net revenue. {pt['name']} alone contributes {pt_share:.0f}% of that revenue, so the totals are dominated by one title.
- The median list price of the selection is ${med_price:.2f} and the median C is {med_c:.3f}, against a median C of {pool_med_c:.3f} for the 76-game pool the selection was drawn from.
- {self_pub} of the 10 are self-published (developer and publisher fields are identical) and {one_lang} list a single language, which may suggest that wide localization was not a precondition for these results.
- The review-based unit estimate falls within the SteamSpy owner band for {int(band_counts.get('within', 0))} games, above it for {int(band_counts.get('above', 0))} and below it for {int(band_counts.get('below', 0))}. The estimates are therefore consistent with an ordinal ranking and should not be quoted as sales figures (§7).
- The archetypes behind the selection are small (5 to 23 games each). Their Ω values may change noticeably with a larger sample, so the archetype-level conclusions are weaker than the game-level observations.

## 2. Data and Selection Rule

The run scanned {d.funnel[0][1]:,} enriched games. SteamSpy's bulk list is ordered by owner count, and the 10 catalog pages
used here end in the 50,000–100,000 owner band. Every game in the run is therefore already a game that reached at least
that audience size, which matters for how the demand scores can be read (§7).

![Selection funnel]({rel(f['funnel'])})

The selection rule uses only quantities already produced by the pipeline.

1. **Simple subset.** C at or below the 40th percentile of the run ({d.simple_threshold:.3f}), as locked in FORMULATION §3a.
2. **Recent.** Released on or after {d.window_start.date()} (48 months before the run start, the window W of FORMULATION §6).
3. **Scored archetype with Ω > 0.** The software-like cluster "Utilities / Software / Design & Illustration" is removed (todo.md item 9).
4. **Paid, finished, well received.** Free-to-play titles have no revenue estimate, Early Access titles are unfinished, and a positive review share below 80% is treated as weak evidence of product quality.
5. **Ranking.** Effort-adjusted return E = R_net / (C + 0.05). At most {t.MAX_PER_ARCHETYPE} games per archetype so that one archetype does not fill the list.

Restricting the pool to archetypes with Ω > 0 follows the research question of the project, which asks where demand is
high and competition is low. The strongest games of the other archetypes are listed in §6 so that they are not lost.

## 3. Archetype Context

![Archetype map]({rel(f['map'])})

{chr(10).join(arche_rows)}

D, K and Σ are z-scores of median estimated units, release count in the window and one minus median C. Ω = 0.40·D − 0.30·K + 0.30·Σ (FORMULATION §6).

![Player-mode shares]({rel(f['modes'])})

The archetypes of this selection are mostly single-player. {mp_text}

![Archetype sales trend]({rel(f['trends'])})

Each point is the median of at most six games, so the lines are descriptive only. FORMULATION §6 states that no significance claim is attached to these slopes.

## 4. The Ten Games at a Glance

{chr(10).join(overview)}

![Complexity against revenue]({rel(f['cx_rev'])})

![Percentile profile]({rel(f['heat'])})

The percentile columns compare each game with the 76 games of the pool. For the complexity column a high percentile means a more complex game.

![Price against volume]({rel(f['price'])})

![Average units per month]({rel(f['per_month'])})

The monthly average divides lifetime estimated units by months since release. It hides the usual launch-heavy sales curve, so older games look slower than their current rate.

![Sales estimate against owner band]({rel(f['ranges'])})

## 5. Game-by-Game Analysis

{chr(10).join(game_section(d, r, simple_pool) for _, r in top.iterrows())}

## 6. Sensitivity and Games Outside the Selection

**Early Access.** If Early Access titles were allowed, {join_names(list(ea_added['name']))} would enter the list
and {join_names(list(ea_removed['name']))} would leave it. The Early Access titles that would enter are priced at {ea_prices or 'n/a'}, which is above the median price of the current selection.

**Games with high E in archetypes with Ω ≤ 0.** These games have not been selected because their archetypes are crowded or have lower demand
by the run's own measure. Several of them are large commercial results, so the table is informative about what is possible even where the
archetype score is unfavourable.

{chr(10).join(outside)}

The complexity score is built from metadata such as install size, achievement count and developer catalog size. For some of these titles it may understate
the effort of building them. Dwarf Fortress, for example, is a long-running project whose Steam release is a later edition, and DELTARUNE continues a franchise with an existing audience.
These two remarks come from general knowledge of the titles and not from the pipeline data.

## 7. Limitations

1. **Unit estimates.** Units are review counts multiplied by genre-bucket factors (FORMULATION §2). The source cited there reports that only about 43% of games fall within ±30% of true sales under this method. Net revenue also applies no discount or refund shrinkage (δ = ρ = 0), so it probably overstates take-home revenue.
2. **SteamSpy owner bands.** The bands are coarse and have low reliability after 2018 (ARCHITECTURE.md, limitation 1). They are shown only as a plausibility check.
3. **Complexity score.** C is a proxy based on store metadata. It does not measure development time. Animal Well has an install size at the 1st percentile of the pool, which lowers its C, and this is unlikely to reflect its production effort.
4. **Sample selected on outcome.** All games already fall in a SteamSpy owner band of at least 50,000 owners. Archetype demand is therefore conditional on commercial survival, and no failure rate can be derived from this run.
5. **Archetype assignment.** Games are assigned to an archetype by plurality vote over non-generic tags. Games with different design (Pseudoregalia and Nodebuster in the Minimalist archetype, Pizza Tower in Comedy) can share an archetype, and the label describes the three most co-occurring tags, not the game.
6. **Small groups.** Archetypes hold 5 to 23 games in the window. The minimum of 5 is the floor of the scoring rule, and Minimalist sits exactly on it.
7. **Parameters.** `parameters_version` of all rows is `aec07e849037`. The run's window and clustering threshold were changed after earlier runs (todo.md items 6 and 7), so Ω values may not be comparable with earlier runs.
8. **Single run.** The result describes one scan taken on {d.run['started_at'][:10]}. A later scan can change the ranking.

## 8. Files

- `rapor.md` is this report and `rapor_assets/` holds the nine figures.
- `scripts/top10_data.py` applies the selection rule, `scripts/top10_figures.py` draws the figures, `scripts/top10_notes.py` holds the per-game commentary and `scripts/build_top10_report.py` assembles the report.
"""
    out_md.write_text(md, encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "analyses.db")
    ap.add_argument("--out", type=Path, default=ROOT / "rapor.md")
    ap.add_argument("--assets", type=Path, default=ROOT / "rapor_assets")
    a = ap.parse_args()
    build(a.db, a.out, a.assets)
    print(f"wrote {a.out}")
