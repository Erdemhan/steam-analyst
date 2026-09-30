# Formulation Record — Steam Analyst

> **STATUS: DRAFT — NOT YET USER-LOCKED.**
>
> This file is the canonical record of every equation, symbol and numeric constant
> used to derive results. Once the user approves it, it becomes user-locked: no agent
> may change an equation or a parameter value without explicit, direct user approval,
> and if code and this record disagree, the code is what gets corrected.
>
> **Until the user approves, every value below marked `PROPOSED` is a placeholder.**
> No implementation may hard-code these numbers; they are read from
> `config/parameters.toml`, which must mirror this file exactly.
>
> Why this project needs a formulation record: the two central quantities
> (`estimated_revenue` and `complexity_score`) are not measurements. They are modelled
> constructs whose constants decide which games appear "successful" and which appear
> "simple", and therefore decide the tool's entire conclusion. They must be auditable
> and stable across runs.

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

**⚠ Values not yet set.** `m_low`, `m_mid`, `m_high` per genre are **deliberately left
empty**. They must be filled from a citable source that the user selects, with the
publication year recorded, because a multiplier taken from a different era of the
storefront silently biases every revenue figure the tool produces.

| Genre bucket | `m_low` | `m_mid` | `m_high` | Source (required before locking) |
|---|---|---|---|---|
| Casual / Puzzle | TBD | TBD | TBD | TBD |
| Action / Arcade | TBD | TBD | TBD | TBD |
| Strategy / Simulation | TBD | TBD | TBD | TBD |
| RPG | TBD | TBD | TBD | TBD |
| Horror | TBD | TBD | TBD | TBD |
| Multiplayer-heavy | TBD | TBD | TBD | TBD |
| Default (unmatched genre) | TBD | TBD | TBD | TBD |

Open question for the user (see also ARCHITECTURE.md open item 2): how should
free-to-play titles (`P_i = 0`) be handled? Options — (a) exclude from the candidate
set entirely, (b) keep them but report revenue as unknown rather than zero. Option (b)
is recommended, because F2P archetypes are still informative for demand and competition
even when their revenue cannot be modelled this way.

---

## 3. Estimated Revenue

```
R_i^gross = S_i · P_i · (1 − δ)
R_i^net   = R_i^gross · (1 − τ) · (1 − ρ)
```

- `τ = 0.30` — the standard storefront revenue share tier. Higher-revenue tiers are
  ignored because the candidate set is, by construction, not at that scale.
- `δ` — PROPOSED, accounts for the fact that a large share of units sell at a discount
  rather than at list price. A single scalar is a crude stand-in for an unavailable
  price history.
- `ρ` — PROPOSED, lumps refunds, regional price differences and VAT into one shrinkage
  term.

Both `δ` and `ρ` are blunt corrections. If the user prefers, they can be set to 0 and
only `R^gross` reported, which is more honest but overstates take-home revenue by a
large and unstated factor. This choice needs an explicit decision.

---

## 4. Complexity Score

A weighted sum of normalized features, clipped to [0, 1]. Higher means more complex,
that is, less suitable for a solo or two-person build.

```
C_i = clip( Σ_f w_f · n_f(x_{i,f}) , 0, 1 )      with  Σ_f w_f = 1
```

`n_f` is a per-feature normalizer mapping a raw value to [0, 1]; log-scaled features
use `n(x) = clip( (log10(x + 1) − a) / (b − a), 0, 1 )`.

| Feature `f` | Raw value | Normalizer | Weight `w_f` | Rationale |
|---|---|---|---|---|
| Install size | `size_bytes` | log-scaled | PROPOSED | Asset volume proxy; strongest single scope signal available |
| Achievement count | count | log-scaled | PROPOSED | Content-surface proxy |
| Supported languages | count | log-scaled | PROPOSED | Localization budget proxy |
| Platform count | 1–3 | linear | PROPOSED | Porting effort |
| DLC count | count | log-scaled | PROPOSED | Post-launch content pipeline |
| Developer catalog size | other titles by same dev | log-scaled | PROPOSED | Studio capacity proxy |
| Early-access duration | days | log-scaled | PROPOSED | Development-time proxy where observable |
| Simplicity tag score | tag match | linear, negative | PROPOSED | Pixel-art / 2D / casual / short / singleplayer reduce complexity |
| Complexity tag score | tag match | linear, positive | PROPOSED | Open-world / multiplayer / physics / procedural raise it |

Normalization bounds `a`, `b` per feature: **PROPOSED, not set.** They should be
derived empirically from the candidate-set distribution of the first completed run
(for example the 5th and 95th percentiles) rather than guessed, and then frozen so
scores stay comparable across runs. The run that fixes them must be recorded here.

Missing values: a feature absent from `appdetails` contributes its weight at the
cohort median rather than at zero, and the row records which features were imputed.

---

## 5. Effort-Adjusted Return

```
E_i = R_i^net / ( C_i + ε )        with ε = PROPOSED small constant to bound C_i → 0
```

This quantity is ordinal only. It ranks candidates; its magnitude has no monetary
interpretation because `C_i` is dimensionless.

---

## 6. Archetype Demand, Competition and Opportunity

An archetype `k` is a tag/genre cluster produced by `analysis.cluster_tags`, not a
single tag.

```
D_k = z( median_{i∈k} S_i^mid  over releases in the trailing window W )
K_k = z( count of releases in k within W , adjusted for catalog growth )
Σ_k = z( 1 − median_{i∈k} C_i )                          (simplicity)

Ω_k = w_D · D_k − w_K · K_k + w_Σ · Σ_k
```

- `W` — trailing window for trend and density. PROPOSED, candidate values 24 or 36
  months. Shorter reacts faster but is noisier for small archetypes.
- `w_D`, `w_K`, `w_Σ` — PROPOSED weights, must sum to 1.
- Minimum cluster size before an archetype is scored at all: PROPOSED. Without it,
  a two-game cluster with one hit dominates the ranking.

Trend detection over release dates reports the slope of median `S^mid` per archetype
across sub-windows of `W`; it is descriptive, so no significance claim is attached to
it unless the sample size per sub-window is reported alongside.

---

## 7. Approval Checklist

Nothing below is settled. Each line needs an explicit user decision before any
implementation reads it:

- [ ] Boxleiter multiplier source (publication + year) and the per-genre `m` table
- [ ] Genre bucketing used for `m(g)` (the table in §2 is a straw man)
- [ ] Free-to-play handling: exclude, or keep with revenue marked unknown
- [ ] Whether `δ` and `ρ` are used at all, and their values if so
- [ ] Complexity feature weights `w_f`
- [ ] Complexity normalization bounds: empirical from run 1, or fixed a priori
- [ ] Coarse-filter band: review-count floor and ceiling, release-date window
- [ ] Simplicity threshold that defines the "simple enough to build" subset
- [ ] Opportunity weights `w_D`, `w_K`, `w_Σ`, window `W`, minimum cluster size
