# Formulation Record — Steam Analyst

> **STATUS: USER-LOCKED as of 2026-09-20.**
>
> This file is the canonical record of every equation, symbol and numeric constant
> used to derive results. It is now user-locked: no agent may change an equation or a
> parameter value without explicit, direct user approval, and if code and this record
> disagree, the code is what gets corrected.
>
> Every value below is approved. No implementation may hard-code these numbers; they
> are read from `config/parameters.toml`, which must mirror this file exactly and is
> the input `@module-planner` and `@worker-coder` implement against.
>
> Why this project needs a formulation record: the two central quantities
> (`estimated_revenue` and `complexity_score`) are not measurements. They are modelled
> constructs whose constants decide which games appear "successful" and which appear
> "simple", and therefore decide the tool's entire conclusion. They must be auditable
> and stable across runs.

---

## 0. Coarse Filter Parameters (Acquisition Stage)

These are not equations, but they gate which apps ever reach the formulas below —
anything excluded here is invisible to every later stage (ARCHITECTURE.md limitation
7), so they are recorded and locked here too.

**✅ LOCKED (user-approved 2026-09-20).**

| Parameter | Value | Rationale |
|---|---|---|
| Review-count floor | 25 | Below this, the Boxleiter estimate is dominated by small-N noise |
| Review-count ceiling | none | A hard ceiling would systematically exclude exactly the cases this tool most wants to surface — solo/small-team breakout hits (e.g. Vampire Survivors, Balatro, Lethal Company) routinely exceed six-figure review counts |
| Release-date window | 2020-01-01 onward | Avoids mixing pre-/post- October 2019 review-prompt behaviour into one multiplier, see §2 |
| AAA/large-publisher exclusion | publisher name blocklist (not a review-count ceiling) | Distinguishes "large-budget" from "organically viral," which review count alone cannot do |

**Publisher blocklist — extended 2026-09-30 (user-approved).** The list in §8 adds
large-budget publishers and studios that appeared among the heavy, high-complexity
candidates of run 20260930T194128376Z-197441 (e.g. CD PROJEKT, Larian Studios, Game
Science, PlayStation Publishing, Blizzard, Amazon Game Studios, Deep Silver, Paradox
Interactive, Techland, NetEase, NEXON, KRAFTON, Valve), plus a few well-known
publishers of the same scale. Matching is a case-insensitive substring match, so
"Warner Bros Games" was shortened to "Warner Bros" (Steam writes "Warner Bros.
Games", which the old entry never matched). The list remains non-exhaustive.

Original starting list (kept for reference): Electronic Arts,
Ubisoft, Activision, Activision Blizzard, Take-Two Interactive, Rockstar Games, 2K,
Bethesda Softworks, ZeniMax, Square Enix, Capcom, Sega, Bandai Namco, Konami, Sony
Interactive Entertainment, Microsoft Studios / Xbox Game Studios, Warner Bros Games,
Epic Games (publishing arm), Tencent-owned publishing labels, Devolver Digital
(borderline — mid-size, included cautiously since it publishes rather than only the
original developer). This list is maintained in `config/parameters.toml` as data, not
code, so it can be extended without a code change; `acquisition.coarse_filter` must
log how many candidates each blocklist entry actually removed, so an overly broad
entry is visible and correctable.

---

## 1. Symbols

| Symbol | Meaning | Unit | Source |
|---|---|---|---|
| `r_i` | Review count of app `i` | count | Steam reviews API (authoritative), SteamSpy (fallback) |
| `p_i` | Positive review fraction of app `i` | ratio in [0, 1] | Steam reviews API |
| `P_i` | Current list price of app `i` | USD | Steam `appdetails` |
| `O_i` | SteamSpy owner estimate midpoint of app `i` | count | SteamSpy (low confidence, see ARCHITECTURE.md limitation 1) |
| `g_i` | Primary genre of app `i` | categorical | Steam `appdetails` |
| `m(g)` | Boxleiter sales multiplier for genre `g` | dimensionless | PROPOSED, see §2 |
| `S_i` | Estimated lifetime unit sales of app `i` | units | derived, §2 |
| `R_i^gross` | Estimated gross revenue of app `i` | USD | derived, §3 |
| `R_i^net` | Estimated revenue net of storefront cut | USD | derived, §3 |
| `C_i` | Complexity score of app `i` | ratio in [0, 1], higher = more complex | derived, §4 |
| `E_i` | Effort-adjusted return of app `i` | USD-equivalent per complexity unit | derived, §5 |
| `D_k` | Demand score of archetype `k` | z-score | derived, §6 |
| `K_k` | Competition density of archetype `k` | z-score | derived, §6 |
| `Ω_k` | Opportunity score of archetype `k` | z-score | derived, §6 |
| `τ` | Storefront revenue cut | ratio | 0.30, Valve's published standard tier |
| `δ` | Effective average discount factor | ratio in [0, 1] | PROPOSED, §3 |
| `ρ` | Refund + regional pricing shrinkage factor | ratio in [0, 1] | PROPOSED, §3 |

---

## 2. Estimated Sales (Boxleiter Method)

```
S_i = r_i · m(g_i)
```

with a low / mid / high band rather than a point estimate:

```
S_i^low  = r_i · m_low(g_i)
S_i^mid  = r_i · m_mid(g_i)
S_i^high = r_i · m_high(g_i)
```

**Method provenance.** The review-count-to-sales ratio approach is commonly called the
Boxleiter method after the developer who first published the observation, and it was
subsequently popularised and periodically re-estimated by game-industry analysts. The
ratio is not published by Valve and is not stable over time — reported estimates have
trended downward as review prompting and storefront behaviour changed.

**✅ LOCKED (user-approved 2026-09-20).** A three-bucket scheme is used instead of the
original seven-genre table, because per-genre evidence beyond these three bands was
inconsistent or absent across sources at the time of research. `Horror` and `RPG` are
mapped to the "mainstream indie" bucket as a neutral default in the absence of
dedicated data; this is a deliberate simplification, not a measured value for those
genres specifically.

| Bucket | `m_low` | `m_mid` | `m_high` | Genres mapped here |
|---|---|---|---|---|
| Niche / highly-engaged | 20 | 27 | 35 | Strategy, Simulation |
| Mainstream indie | 30 | 37 | 45 | Puzzle, RPG, Horror, Adventure, unmatched/default |
| Broad-audience / low-price | 40 | 50 | 65 | Action, Arcade, FPS, Multiplayer-heavy |

**Sources** (retrieved 2026-09-20): Simon Carless / Jake Birkett's original Boxleiter
method; Mike Rose, "Using Steam reviews to estimate sales," *Game Developer*
(gamedeveloper.com/business/using-steam-reviews-to-estimate-sales) — documents the
pre-/post-2019 shift and genre observations; Gamalytic, "How to accurately estimate
Steam game sales" (gamalytic.com/blog/how-to-accurately-estimate-steam-sales, 2023) —
data-driven test over ~120 games, median ratio ≈35x; Steam Page Analyzer, "Boxleiter
Method: Steam Sales Multipliers Explained" (steampageanalyzer.com/blog/boxleiter-method-explained,
2026) — current 20x-60x consensus range and genre/price qualitative drivers.

**Known accuracy limit** (record verbatim in `reporting.interpretive_caveats`):
per the Gamalytic test, only ~43% of games fall within ±30% of their true sales using
the plain review-multiple method. Treat `S_i` as an ordinal ranking signal, not a
point estimate a user should quote as fact.

**Historical discontinuity.** Valve added a "Would you like to review this?" prompt
in October 2019, which measurably increased review rates and therefore lowered the
true review-to-sales ratio going forward. Pre-2019 and post-2019 games are not
comparable under one multiplier. **Resolution (locked 2026-09-20)**: the coarse
filter's release-date window (§7 checklist item) is restricted to apps released
2020-01-01 or later, so this discontinuity does not need a separate correction term.

**✅ LOCKED (user-approved 2026-09-20).** Free-to-play titles (`P_i = 0`) are kept in
the candidate set for demand/competition analysis, but `S_i`, `R_i^gross` and
`R_i^net` are all recorded as `NULL` (rendered as "unknown", never as 0) rather than
computed from a zero price.

---

## 3. Estimated Revenue

**✅ LOCKED (user-approved 2026-09-20).** `δ = 0` and `ρ = 0`. Only the storefront cut
`τ` is applied. This is the deliberately more conservative-on-assumptions choice: it
avoids stacking an unverified discount/refund/regional shrinkage guess on top of an
already-approximate `S_i`. The trade-off, which must be surfaced in the UI caveat
panel, is that `R_i^net` still overstates true take-home revenue (list-price sales
are the exception, not the rule, on Steam).

```
R_i^gross = S_i · P_i
R_i^net   = R_i^gross · (1 − τ)
```

- `τ = 0.30` — the standard storefront revenue share tier. Higher-revenue tiers are
  ignored because the candidate set is, by construction, not at that scale.
- F2P titles (`P_i` undefined as a sale price): `R_i^gross` and `R_i^net` are `NULL`
  ("unknown"), per §2.

---

## 3a. Simplicity Threshold

**✅ LOCKED (user-approved 2026-09-20).** "Simple enough to build" is defined as the
bottom 40th percentile of `C_i` within the same run's candidate set, not a fixed
absolute score — consistent with `C_i` itself being normalized from that run's
empirical distribution (§4). The percentile is stored in `config/parameters.toml`
and may be retuned after the first run without touching this formula.

## 4. Complexity Score

A weighted sum of normalized features, clipped to [0, 1]. Higher means more complex,
that is, less suitable for a solo or two-person build.

```
C_i = clip( Σ_f w_f · n_f(x_{i,f}) , 0, 1 )      with  Σ_f w_f = 1
```

`n_f` is a per-feature normalizer mapping a raw value to [0, 1]; log-scaled features
use `n(x) = clip( (log10(x + 1) − a) / (b − a), 0, 1 )`.

**✅ LOCKED (user-approved 2026-09-20).**

| Feature `f` | Raw value | Normalizer | Weight `w_f` | Rationale |
|---|---|---|---|---|
| Install size | `size_bytes` | log-scaled | 0.20 | Asset volume proxy; strongest single scope signal available |
| Early-access duration | days | log-scaled | 0.15 | Development-time proxy where observable |
| Developer catalog size | other titles by same dev | log-scaled | 0.15 | Studio capacity proxy |
| Simplicity tag score | tag match | linear, negative | 0.10 | Pixel-art / 2D / casual / short / singleplayer reduce complexity |
| Complexity tag score | tag match | linear, positive | 0.10 | Open-world / multiplayer / physics / procedural raise it |
| Achievement count | count | log-scaled | 0.10 | Content-surface proxy |
| DLC count | count | log-scaled | 0.10 | Post-launch content pipeline |
| Platform count | 1–3 | linear | 0.05 | Porting effort (cheap with modern engines) |
| Supported languages | count | log-scaled | 0.05 | Weak signal; often community-translated, not build effort |

Weights sum to 1.00.

**✅ LOCKED (user-approved 2026-09-20).** Normalization bounds `a`, `b` per feature
are derived empirically from the candidate-set distribution of the first completed
run (5th and 95th percentiles), not guessed a priori, then frozen so scores stay
comparable across subsequent runs. The run that fixes them must be recorded here
once it exists (run ID, date, and the resulting `a`/`b` per feature).

Missing values: a feature absent from `appdetails` contributes its weight at the
cohort median rather than at zero, and the row records which features were imputed.

**Frozen bounds (run 20260930T194128376Z-197441, 2026-09-30).** The bounds are the 5th
and 95th percentiles of `log10(x + 1)` over the 203 enriched candidates of this run
(one SteamSpy page, the top 1000 applications by owners, filtered to releases from
2020-01-01 onward):

| Feature | `a` | `b` |
|---|---|---|
| `size_bytes` | 8.660245 | 10.965682 |
| `dev_title_count` | 0.000000 | 0.602060 |
| `achievement_count` | 1.134863 | 2.211565 |
| `dlc_count` | 0.000000 | 1.342423 |
| `language_count` | 0.301030 | 1.431364 |
| `early_access_days` | not frozen | not frozen |

`early_access_days` could not be frozen because the documented APIs do not expose the
early-access duration, so the feature remains at the 0.5 midpoint fallback. The sample
is restricted to high-owner applications, so the bounds may sit higher than those of
the full candidate population. `size_bytes` is parsed from the `pc_requirements` text
(storage line), not from a dedicated API field.

---

## 5. Effort-Adjusted Return

```
E_i = R_i^net / ( C_i + ε )        with ε = 0.05
```

**✅ LOCKED (user-approved 2026-09-20).** `ε = 0.05` (5% of the normalized `C_i`
range) — just large enough to keep the ratio finite and non-explosive as `C_i → 0`,
without materially changing the ranking for typical `C_i` values.

This quantity is ordinal only. It ranks candidates; its magnitude has no monetary
interpretation because `C_i` is dimensionless.

---

## 6. Archetype Demand, Competition and Opportunity

An archetype `k` is a tag cluster produced by `analysis.cluster_tags`, not a single
tag and not a fixed Steam genre category.

**Scope (user-approved 2026-09-30).** Clustering, `D_k`, `K_k`, `Σ_k`, the trend
slopes and the tag summary are all computed over the simple subset of §3a (bottom
40th percentile of `C_i`), not over the whole candidate set. Earlier drafts used the
whole candidate set, which let large-budget titles that the simplicity filter itself
rejects inflate the demand of the archetypes they fall into. Every "candidate set"
reference below therefore means the simple subset.

**✅ LOCKED (user-approved 2026-09-20) — clustering method.** Archetypes are formed by
agglomerative hierarchical clustering over a Jaccard tag-distance matrix built from
tag co-occurrence across the candidate set, with **no genre anchor** — consistent
with this project's open-ended-discovery framing (ARCHITECTURE.md system driver 1)
rather than pre-partitioning by Steam's own genre taxonomy. The distance-cut
threshold that decides where clusters split is **not fixed a priori**: like the
complexity-score normalization bounds (§4), it is derived empirically from the first
completed run (chosen to keep the median cluster size in a reasonable range, e.g.
tuned so at least half of clusters clear the minimum-cluster-size rule below) and then
frozen for comparability across later runs. The run that fixes it must be recorded
here once it exists (run ID, date, resulting threshold, resulting cluster-count and
median cluster size).

**Frozen threshold (run 20260930T194128376Z-197441, 2026-09-30).** Distance-cut
threshold = 0.9444444444 (run-local search), giving 52 clusters with a median cluster
size of 5.0. Only 2 of the 52 clusters cleared the minimum-cluster-size rule within `W`
in this run, which is consistent with the small 203-game sample.

```
D_k = z( median_{i∈k} S_i^mid  over releases in the trailing window W )
K_k = z( count of releases in k within W , adjusted for catalog growth )
Σ_k = z( 1 − median_{i∈k} C_i )                          (simplicity)

Ω_k = w_D · D_k − w_K · K_k + w_Σ · Σ_k
```

**✅ LOCKED (user-approved 2026-09-20).**

- `W = 24` months — favours reacting to current trends over historical averaging;
  the noise risk this introduces for small archetypes is bounded by the minimum
  cluster size rule below.
- `w_D = 0.40`, `w_K = 0.30`, `w_Σ = 0.30` — demand weighted slightly above
  competition and simplicity, since a simple, low-competition archetype nobody
  wants is not an opportunity.
- Minimum cluster size = **5 games**. An archetype with fewer than 5 games in the
  candidate set within `W` is not scored at all, so one breakout hit cannot
  single-handedly define an archetype's opportunity score.

Trend detection over release dates reports the slope of median `S^mid` per archetype
across sub-windows of `W`; it is descriptive, so no significance claim is attached to
it unless the sample size per sub-window is reported alongside.

---

## 7. Approval Checklist

Nothing below is settled. Each line needs an explicit user decision before any
implementation reads it:

- [x] Boxleiter multiplier source and the per-genre `m` table — locked 2026-09-20, §2
- [x] Genre bucketing used for `m(g)` — locked 2026-09-20 as a 3-bucket scheme, §2
- [x] Coarse-filter release-date window — locked 2026-09-20: apps released
      2020-01-01 or later only (post review-prompt discontinuity), §2
- [x] Free-to-play handling — locked 2026-09-20: kept in candidate set, revenue NULL, §2
- [x] Whether `δ` and `ρ` are used — locked 2026-09-20: both 0, gross/net differ only by `τ`, §3
- [x] Complexity feature weights `w_f` — locked 2026-09-20, §4
- [x] Complexity normalization bounds approach — locked 2026-09-20: empirical from run 1, §4
- [x] Coarse-filter band — locked 2026-09-20: floor 25, no ceiling, publisher
      blocklist instead, §0
- [x] Simplicity threshold — locked 2026-09-20: bottom 40th percentile of `C_i`, §3a
- [x] Opportunity weights and window — locked 2026-09-20: `w_D=0.40, w_K=0.30,
      w_Σ=0.30`, `W=24` months, minimum cluster size 5, §6

**All items locked as of 2026-09-20.** See the STATUS line at the top of this file.

---

## 8. Machine-Readable Summary (for `scripts/verify_parameters_consistency.py`)

This block is a **derived convenience copy** of the values already locked in
sections 0-6 above. It changes no number and carries no independent authority — if
it and the prose above ever disagree, the prose sections above win and this block is
the one that's wrong. It exists solely so a script can parse locked values without
scraping Markdown prose. Field names match `config`'s `AcquisitionConfig`,
`CoarseFilterCriteria`, `EnrichmentParams` and `AnalysisParams` dataclasses
(`.claude/specs/00_config.module_spec.json`) exactly, and this block is what
`config/parameters.toml` mirrors.

**TOML has no null literal.** A key here written as `# unset` is deliberately
*absent* from `config/parameters.toml`, and `config.load_parameters` treats absence
of exactly these two keys — `coarse_filter.max_review_count` and
`analysis.tag_distance_threshold` — as `None` by design. Every other key is
required; a missing one is `ParameterError`, never a silent default.

```toml
# --- coarse_filter (FORMULATION.md §0) ---
[coarse_filter]
min_review_count = 25
# max_review_count: unset by design (no ceiling; publisher blocklist is used instead)
earliest_release_date = "2020-01-01"
# latest_release_date: unset (no upper bound)
include_free_to_play = true
publisher_blocklist = [
  "Electronic Arts", "Ubisoft", "Activision", "Activision Blizzard",
  "Take-Two Interactive", "Rockstar Games", "2K", "Bethesda Softworks",
  "ZeniMax", "Square Enix", "Capcom", "Sega", "Bandai Namco", "Konami",
  "Sony Interactive Entertainment", "Microsoft Studios", "Xbox Game Studios",
  "Warner Bros", "Epic Games", "Devolver Digital",
  "CD PROJEKT", "Larian Studios", "Game Science", "PlayStation Publishing",
  "Sony", "Microsoft", "Blizzard", "Amazon Game Studios", "Deep Silver",
  "Focus Entertainment", "Paradox Interactive", "Techland", "Remedy Entertainment",
  "IO Interactive", "NetEase", "NEXON", "KRAFTON", "Cygames", "Perfect World",
  "Quantic Dream", "Prime Matter", "Valve", "Tencent", "Koei Tecmo", "Embracer",
  "THQ Nordic", "Riot Games", "Gearbox",
]

# --- enrichment: Boxleiter multipliers (FORMULATION.md §2) ---
[enrichment.boxleiter_multipliers]
niche = [20, 27, 35]
mainstream = [30, 37, 45]
broad_audience = [40, 50, 65]

[enrichment.genre_bucket_map]
Strategy = "niche"
Simulation = "niche"
Puzzle = "mainstream"
RPG = "mainstream"
Horror = "mainstream"
Adventure = "mainstream"
Action = "broad_audience"
Arcade = "broad_audience"
FPS = "broad_audience"
Multiplayer = "broad_audience"
default = "mainstream"

# --- enrichment: revenue (FORMULATION.md §3) ---
[enrichment.revenue]
storefront_cut = 0.30
discount_factor = 0.0
refund_regional_factor = 0.0

# --- enrichment: complexity score (FORMULATION.md §4) ---
[enrichment.complexity_weights]
size_bytes = 0.20
early_access_days = 0.15
dev_title_count = 0.15
simplicity_tag_score = 0.10
complexity_tag_score = 0.10
achievement_count = 0.10
dlc_count = 0.10
platform_count = 0.05
language_count = 0.05

[enrichment.complexity_tags]
simplicity_tags = ["Pixel Graphics", "2D", "Casual", "Short", "Singleplayer"]
complexity_tags = ["Open World", "Multiplayer", "Physics", "Procedural Generation"]

# complexity_bounds: frozen from run 20260930T194128376Z-197441 (ADR-012).
# early_access_days has no observable values and is intentionally absent.
[enrichment.complexity_bounds]
size_bytes = [8.660244515301235, 10.965681882084198]
dev_title_count = [0.0, 0.6020599913279624]
achievement_count = [1.1348633964982475, 2.211565253290689]
dlc_count = [0.0, 1.3424226808222062]
language_count = [0.3010299956639812, 1.4313637641589874]

# --- enrichment: effort-adjusted return (FORMULATION.md §5) ---
[enrichment.effort]
epsilon = 0.05

# --- enrichment: tag extraction (pre-clustering table-size knobs, distinct
# from analysis.min_tag_votes / analysis.max_tags_per_game below, which are
# independently re-applied inside analysis.cluster_tags) ---
[enrichment.tag_extraction]
max_per_game = 20
min_votes = 0

# --- analysis: simplicity threshold (FORMULATION.md §3a) ---
[analysis]
simplicity_percentile = 0.40
# tag_distance_threshold: frozen from run 20260930T194128376Z-197441 (ADR-012)
tag_distance_threshold = 0.9444444444444445
clustering_linkage = "average"
trailing_window_months = 24
min_cluster_size = 5
min_tag_votes = 0
max_tags_per_game = 20

# --- analysis: opportunity score (FORMULATION.md §6) ---
[analysis.opportunity_weights]
demand = 0.40
competition = 0.30
simplicity = 0.30
```

**Locale pinning** (ARCHITECTURE.md, not itself a `FORMULATION.md` constant but
listed here for the consistency script's completeness): every Steam Web API /
storefront call is fixed to `cc=us&l=english`. This is not a `parameters.toml` key —
it is hard-coded in `acquisition`'s HTTP clients since it is not meant to ever vary
per run.
