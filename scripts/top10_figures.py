"""Figure builders for the top-10 game report. Each function writes one PNG and returns its path."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

from top10_data import ReportData

# Okabe-Ito colour-blind-safe palette, assigned in a fixed order to the archetypes of the selection.
INK, INK2, GRID, BG = "#1f2328", "#59636e", "#e3e6ea", "#ffffff"
POS, NEG, MUTED = "#0072B2", "#D55E00", "#9aa4af"
CAT = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]

plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 9,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False,
})


def _short(name: str, n: int = 22) -> str:
    return name if len(name) <= n else name[: n - 1].rstrip() + "…"


def _usd(x: float, _pos=None) -> str:
    if x >= 1e6:
        return f"${x / 1e6:g}M"
    if x >= 1e3:
        return f"${x / 1e3:g}k"
    return f"${x:g}"


def _count(x: float, _pos=None) -> str:
    if x >= 1e6:
        return f"{x / 1e6:g}M"
    if x >= 1e3:
        return f"{x / 1e3:g}k"
    return f"{x:g}"


def _save(fig, out: Path, name: str) -> Path:
    path = out / name
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


# (dx, dy, ha) label offsets in points for crowded areas of the archetype map.
MAP_OFFSETS = {
    "Retro": (-8, 6, "right"), "Platformer": (8, 8, "left"), "Combat": (9, -12, "left"),
    "Survival": (6, -14, "left"), "FPS": (9, 4, "left"), "Female Protagonist": (6, -14, "left"),
    "Sexual Content": (8, 4, "left"),
}
# Overlapping grey bubbles in the lower-left corner; named in the figure note instead.
MAP_UNLABELLED = {"Tactical", "Character Customization"}

# (dx, dy, ha) label offsets by selection rank for the complexity/revenue scatter.
CX_OFFSETS = {1: (-8, -3, "right"), 4: (-7, 6, "right"), 7: (-8, -3, "right"), 8: (0, -15, "center"),
              9: (8, -2, "left")}


def archetype_colors(d: ReportData) -> dict[int, str]:
    ids = list(dict.fromkeys(d.top["cluster_id"].astype(int)))
    return {cid: CAT[i % len(CAT)] for i, cid in enumerate(ids)}


def fig_funnel(d: ReportData, out: Path) -> Path:
    labels = [f for f, _ in d.funnel][::-1]
    vals = [v for _, v in d.funnel][::-1]
    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.barh(labels, vals, color=POS, height=0.62)
    for i, v in enumerate(vals):
        ax.text(v + max(vals) * 0.01, i, f"{v:,}", va="center", color=INK, fontsize=9)
    ax.set_xlim(0, max(vals) * 1.12)
    ax.xaxis.set_major_formatter(FuncFormatter(_count))
    ax.grid(axis="y", visible=False)
    ax.set_title("Run'ın tamamından seçilen on oyuna")
    return _save(fig, out, "fig01_selection_funnel.png")


def fig_opportunity_map(d: ReportData, out: Path) -> Path:
    m = d.matrix.copy()
    colors = archetype_colors(d)
    fig, ax = plt.subplots(figsize=(8.6, 6))
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.axvline(0, color=MUTED, lw=0.8)
    for _, r in m.iterrows():
        cid = int(r.cluster_id)
        c = colors.get(cid, MUTED)
        selected = cid in colors
        ax.scatter(r.competition_z, r.demand_z, s=40 + r.n_games * 9, color=c,
                   alpha=0.9 if selected else 0.35, edgecolor=BG, linewidth=1.2, zorder=3)
        lab = r.label.split(" / ")[0]
        if lab in MAP_UNLABELLED:
            continue
        dx, dy, ha = MAP_OFFSETS.get(lab, (7, 5, "left"))
        ax.annotate(f"{lab} ({r.opportunity_score:+.2f})", (r.competition_z, r.demand_z),
                    xytext=(dx, dy), textcoords="offset points", fontsize=7.5, ha=ha,
                    color=INK if selected else INK2, zorder=4)
    ax.set_xlabel("Rekabet yoğunluğu K (z-skoru, düşük daha iyi)")
    ax.set_ylabel("Talep D (medyan tahmini satışın z-skoru)")
    ax.set_title("Arketip haritası: talep ve rekabet")
    fig.text(0.01, -0.03, "Balon alanı = arketipteki oyun sayısı. Renkli = seçilen oyun içeren arketipler. "
             "Etiket, ilk etiket tagini ve Ω değerini gösterir.\n"
             "Etiketsiz sol alt balonlar: " + ", ".join(sorted(MAP_UNLABELLED)) + ".",
             fontsize=7.5, color=INK2)
    ax.text(0.99, 0.97, "sol üst: yüksek talep,\ndüşük rekabet", transform=ax.transAxes, fontsize=8,
            color=POS, va="top", ha="right", style="italic")
    ax.set_xlim(-1.1, 3.4)
    return _save(fig, out, "fig02_archetype_map.png")


def fig_complexity_revenue(d: ReportData, out: Path) -> Path:
    colors = archetype_colors(d)
    pool = d.pool[d.pool["is_free"] == 0]
    top_ids = set(d.top["appid"])
    rest = pool[~pool["appid"].isin(top_ids)]
    fig, ax = plt.subplots(figsize=(8.6, 5.6))
    ax.scatter(rest["complexity_score"], rest["estimated_revenue_net_usd"], s=22, color=MUTED,
               alpha=0.5, edgecolor="none", label="Ω > 0 arketiplerdeki diğer oyunlar")
    for _, r in d.top.iterrows():
        ax.scatter(r.complexity_score, r.estimated_revenue_net_usd, s=70,
                   color=colors[int(r.cluster_id)], edgecolor=BG, linewidth=1.4, zorder=3)
        dx, dy, ha = CX_OFFSETS.get(int(r["rank"]), (6, 4, "left"))
        ax.annotate(f"{int(r['rank'])}. {_short(r['name'], 18)}", (r.complexity_score, r.estimated_revenue_net_usd),
                    xytext=(dx, dy), textcoords="offset points", fontsize=7.5, ha=ha, zorder=4)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(_usd))
    ax.set_xlabel("Karmaşıklık skoru C (düşük daha basit)")
    ax.set_ylabel("Tahmini net gelir R_net (log ölçek)")
    ax.set_title("Karmaşıklık ve tahmini net gelir")
    return _save(fig, out, "fig03_complexity_vs_revenue.png")


def fig_sales_ranges(d: ReportData, out: Path) -> Path:
    t = d.top.iloc[::-1]
    colors = archetype_colors(d)
    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    y = np.arange(len(t))
    for i, (_, r) in enumerate(t.iterrows()):
        c = colors[int(r.cluster_id)]
        ax.plot([r.estimated_sales_low, r.estimated_sales_high], [i + 0.13, i + 0.13], color=c, lw=3.2,
                solid_capstyle="round")
        ax.scatter(r.estimated_sales_mid, i + 0.13, color=c, s=34, zorder=3, edgecolor=BG, linewidth=1)
        if pd.notna(r.owners_lo):
            ax.plot([r.owners_lo, r.owners_hi], [i - 0.17, i - 0.17], color=INK2, lw=3.2, alpha=0.55,
                    solid_capstyle="butt")
    ax.set_yticks(y, [f"{int(r['rank'])}. {_short(r['name'], 24)}" for _, r in t.iterrows()])
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(_count))
    ax.set_xlabel("Adet (log ölçek)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Yorum tabanlı satış tahmini ve SteamSpy sahip bandı")
    ax.legend(handles=[
        Line2D([0], [0], color=POS, lw=3.2, marker="o", label="Boxleiter düşük–yüksek (nokta = orta)"),
        Line2D([0], [0], color=INK2, lw=3.2, alpha=0.55, label="SteamSpy sahip bandı (düşük güvenilirlik)"),
    ], loc="lower right", fontsize=8)
    return _save(fig, out, "fig04_sales_vs_owners.png")


def fig_sales_per_month(d: ReportData, out: Path) -> Path:
    t = d.top.sort_values("sales_per_month")
    colors = archetype_colors(d)
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.barh([f"{int(r['rank'])}. {_short(r['name'], 24)}" for _, r in t.iterrows()], t["sales_per_month"],
            color=[colors[int(c)] for c in t["cluster_id"]], height=0.62)
    for i, (_, r) in enumerate(t.iterrows()):
        ax.text(r.sales_per_month * 1.01, i, f"{r.sales_per_month:,.0f}  ({r.age_months:.0f} ay)",
                va="center", fontsize=8, color=INK)
    ax.set_xlim(0, t["sales_per_month"].max() * 1.25)
    ax.xaxis.set_major_formatter(FuncFormatter(_count))
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Tahmini orta satış / çıkıştan beri geçen ay (yaşam boyu ortalama, trend değil)")
    ax.set_title("Çıkıştan beri aylık ortalama tahmini adet")
    return _save(fig, out, "fig05_sales_per_month.png")


def fig_profile_heatmap(d: ReportData, out: Path) -> Path:
    """Percentile of each game inside the 76-game pool (Ω > 0 archetypes, simple, in window)."""
    pool = d.pool
    metrics = [
        ("complexity_score", "Karmaşıklık C (yüksek = karmaşık)", True),
        ("price_usd", "Fiyat", False),
        ("review_count", "Yorum sayısı", False),
        ("review_positive_pct", "Olumlu oran", False),
        ("estimated_sales_mid", "Tahmini satış", False),
        ("estimated_revenue_net_usd", "Tahmini net gelir", False),
        ("size_bytes", "Kurulum boyutu", False),
        ("language_count", "Dil sayısı", False),
    ]
    rows = []
    for _, r in d.top.iterrows():
        rows.append([float((pool[col].dropna() <= r[col]).mean()) * 100 if pd.notna(r[col]) else np.nan
                     for col, _, _ in metrics])
    arr = np.array(rows)
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    im = ax.imshow(arr, cmap="Blues", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(len(metrics)), [m[1] for m in metrics], rotation=30, ha="right")
    ax.set_yticks(range(len(d.top)), [f"{int(r['rank'])}. {_short(r['name'], 24)}" for _, r in d.top.iterrows()])
    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            v = arr[i, j]
            ax.text(j, i, "n/a" if np.isnan(v) else f"{v:.0f}", ha="center", va="center", fontsize=8,
                    color="white" if (not np.isnan(v) and v > 55) else INK)
    ax.grid(False)
    ax.spines[:].set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label(f"{len(pool)} oyunluk havuzdaki yüzdelik", color=INK2)
    ax.set_title("Seçilen oyunların havuzdaki konumu")
    return _save(fig, out, "fig06_percentile_profile.png")


def fig_archetype_trends(d: ReportData, out: Path) -> Path:
    colors = archetype_colors(d)
    ids = list(colors)
    labels = d.matrix.set_index("cluster_id")["label"]
    fig, axes = plt.subplots(2, 3, figsize=(10, 5.6), sharey=False)
    for ax, cid in zip(axes.ravel(), ids):
        sub = d.trends[(d.trends["cluster_id"] == cid) & d.trends["sub_window_index"].notna()].copy()
        sub["mid"] = (pd.to_datetime(sub["sub_window_start"]) + (pd.to_datetime(sub["sub_window_end"]) - pd.to_datetime(sub["sub_window_start"])) / 2)
        sub = sub[sub["median_estimated_sales_mid"] > 0].sort_values("mid")
        ax.scatter(sub["mid"], sub["median_estimated_sales_mid"], s=18 + sub["n_games"] * 14,
                   color=colors[cid], alpha=0.85, edgecolor=BG)
        ax.plot(sub["mid"], sub["median_estimated_sales_mid"], color=colors[cid], lw=1.2, alpha=0.6)
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(FuncFormatter(_count))
        ax.set_title(_short(labels[cid].split(" / ")[0], 26), fontsize=9.5)
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 7)))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        ax.tick_params(axis="x", labelrotation=30, labelsize=7.5)
        for _, r in sub.iterrows():
            ax.annotate(str(int(r.n_games)), (r.mid, r.median_estimated_sales_mid), xytext=(0, 6),
                        textcoords="offset points", ha="center", fontsize=6.5, color=INK2)
    for ax in axes.ravel()[len(ids):]:
        ax.set_visible(False)
    fig.suptitle("4 aylık çıkış alt pencerelerinde medyan tahmini satış (sayılar = alt penceredeki oyun sayısı)",
                 x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout()
    return _save(fig, out, "fig07_archetype_trends.png")


def fig_price_sales(d: ReportData, out: Path) -> Path:
    colors = archetype_colors(d)
    fig, ax = plt.subplots(figsize=(8.2, 5))
    for _, r in d.top.iterrows():
        ax.scatter(r.price_usd, r.estimated_sales_mid, s=r.estimated_revenue_net_usd / 6e4 + 25,
                   color=colors[int(r.cluster_id)], alpha=0.85, edgecolor=BG, linewidth=1.2)
        dx, dy = {1: (-14, -2), 7: (-7, 8), 8: (8, -11), 6: (-7, 8)}.get(int(r["rank"]), (7, 5))
        ax.annotate(f"{int(r['rank'])}. {_short(r['name'], 18)}", (r.price_usd, r.estimated_sales_mid),
                    xytext=(dx, dy), textcoords="offset points", fontsize=7.5,
                    ha="right" if dx < 0 else "left")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(_count))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:g}"))
    ax.set_xlabel("Liste fiyatı (USD)")
    ax.set_ylabel("Tahmini adet, orta (log ölçek)")
    ax.set_title("Fiyat ve tahmini hacim (balon alanı = tahmini net gelir)")
    return _save(fig, out, "fig08_price_vs_sales.png")


def fig_mode_shares(d: ReportData, out: Path) -> Path:
    colors = archetype_colors(d)
    m = d.matrix.set_index("cluster_id").loc[list(colors)]
    x = np.arange(len(m))
    w = 0.26
    fig, ax = plt.subplots(figsize=(8.4, 3.8))
    for k, (col, lab, c) in enumerate([("singleplayer_share", "Tek oyunculu", POS),
                                       ("multiplayer_share", "Çok oyunculu", NEG),
                                       ("coop_share", "Co-op", "#009E73")]):
        ax.bar(x + (k - 1) * w, m[col] * 100, w * 0.9, color=c, label=lab)
    ax.set_xticks(x, [_short(l.split(" / ")[0], 16) for l in m["label"]], rotation=15)
    ax.set_ylabel("Arketip oyunlarının payı (%)")
    ax.grid(axis="x", visible=False)
    ax.legend(ncol=3, loc="upper right", fontsize=8)
    ax.set_ylim(0, 105)
    ax.set_title(f"{len(m)} arketipin oyuncu modu dağılımı")
    return _save(fig, out, "fig09_mode_shares.png")


def build_all(d: ReportData, out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    return {
        "funnel": fig_funnel(d, out),
        "map": fig_opportunity_map(d, out),
        "cx_rev": fig_complexity_revenue(d, out),
        "ranges": fig_sales_ranges(d, out),
        "per_month": fig_sales_per_month(d, out),
        "heat": fig_profile_heatmap(d, out),
        "trends": fig_archetype_trends(d, out),
        "price": fig_price_sales(d, out),
        "modes": fig_mode_shares(d, out),
    }
