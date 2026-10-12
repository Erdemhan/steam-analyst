# TODO

Items 1, 3, 4, 5, 7, 8 and 9 are done, items 2 and 6 are largely done. What is left is optional (see their Status lines).

## 1. Make the complexity weights user-adjustable (done, commit 20ea092)

- Allow the complexity score weights (FORMULATION §4, `enrichment.complexity_weights.*`) to be overridden by the user at run time.
- When the user does not override them, the frozen defaults from `config/parameters.toml` must be used unchanged.
- Open points to settle before implementation:
  - Where the override is supplied (run configuration, UI form, or a separate TOML file).
  - Validation: overridden weights must still sum to 1.00 (or be renormalized, which needs a decision).
  - Whether the overridden weights are stored with the run so that results remain reproducible.
  - FORMULATION.md is user-locked, so the defaults stay there and overrides must not modify it.

## 2. Archetype labels are ambiguous (done apart from an optional label refinement)

- Observed on a 1000-game scan: an archetype reported as "Action, Multiplayer, Singleplayer" is unclear.
  It is not evident whether it means single-player only, multiplayer only, or games that support both.
- If the label means "both", it is unclear how contradictory tags can legitimately co-occur in one archetype.
  If it does not, the clustering puts contradictory tags into the same group, which would be a clustering problem.
- To investigate:
  - How cluster labels are derived from tags (which tags are shown, and on what criterion).
  - Whether mode tags (Singleplayer, Multiplayer, Co-op, etc.) should be separated from genre/mechanic tags
    in the distance measure and in the displayed label.
  - Whether the label should state explicitly how many member games carry each tag (for example, share of members per tag).
- Any change to tag distance or clustering affects FORMULATION §6 and needs user approval.
- Status: generic tags are excluded from clustering and each archetype reports its Singleplayer/Multiplayer/Co-op share.
  Remaining and optional: labels still use the three tags with the highest total co-occurrence, with no per-tag coverage shown.

## 3. Cap the rate limiter's 429 widening (done)

- `RateLimiter.observe_response` doubles the request interval on every 429 after the first, with no upper bound
  (`src/steam_analyst/acquisition/rate_limiter.py`).
- Observed on run 20261003T162937824Z-28423c: after six 429 responses the interval grew to tens of seconds and the
  run effectively stalled. It was resumed after lowering `steam_requests_per_minute` from 60 to 30.
- Add a ceiling on the widened interval and a cool-down/recovery rule, then re-check the 30 requests/minute default.
- Status: the widened interval is capped at 60 s and halves after 20 consecutive non-429 responses.
  The 30 requests/minute default produced no 429 over about 10000 requests, so it stays.

## 4. Freeze script must not write locked values without confirmation (done)

- `scripts/freeze_empirical_parameters.py` rewrites the complexity bounds and `tag_distance_threshold` in
  `config/parameters.toml` directly, although the module docstring says it only prints the text to paste (ADR-012).
- Observed: running it on a new run silently replaced already frozen bounds.
- Make writing opt-in (for example a `--write` flag), default to print-only, and reconcile the docstring with the behavior.
- Status: the script is print-only by default and writes `config/parameters.toml` only with `--write`; file I/O is explicit UTF-8.

## 5. Funnel report shows zero coarse-filter rejections (fixed for new runs)

- `funnel_report.rejected_by_reason` reports 0 for `review_count_below_floor` and `publisher_blocklisted`
  while only `release_date_outside_window` is non-zero (run 20261003T162937824Z-28423c, 3000 catalog apps, 713 candidates).
- The counts from the SteamSpy coarse filter (`acquisition/funnel.py`) do not appear to reach the stored report
  (`_get_initial_rejection_reasons` in `acquisition/pipeline.py` starts all at zero).
- Verify and merge the funnel's own counts into the stored report.
- Status: cause confirmed (the second report write replaced the coarse counts with zeros) and fixed; new runs keep both
  the coarse-filter and release-date counts. Reports already stored for earlier runs keep the old zeros.

## 6. Too few recent games in the sample for the opportunity matrix (addressed; no better data source exists within ADR-003)

- On run 20261003T162937824Z-28423c (3000 SteamSpy catalog apps, 713 candidates, 285 simple-subset games) only
  29 simple-subset games were released within the trailing window `W = 24` months, so at most 3 archetypes can
  reach the 5-games-in-window floor, each with exactly 5 games.
- The number of scorable archetypes is limited by the sample, not by the clustering threshold
  (see FORMULATION §6, frozen threshold paragraph).
- To investigate:
  - A larger scan (more SteamSpy catalog pages) and how many recent games it actually adds, since the catalog order
    may favor older apps.
  - A data source or query that targets recent releases, within the documented-API constraint of ADR-003.
  - Whether `W` or the 5-games floor should be revisited (FORMULATION §6 is user-locked, needs approval).
- Status: W was widened to 48 months and a 10-page scan was run; 18 archetypes are scored on run 20261003T204134704Z-d8d2b3.
  No alternative recency source within ADR-003 was found.
- Findings on run 20261003T162937824Z-28423c that bear on this item:
  - SteamSpy `all` is ordered by owners, descending, and the first three pages (3000 apps) end at the 200k-500k owner band.
  - The SteamSpy bulk payload has no release date, so the 2020+ release filter can only run after `appdetails`;
    1341 of the 2056 `appdetails` calls were spent on apps released before 2020.
  - Using the appid as a proxy for release recency does not work: 2025 releases in the sample have a median appid of
    about 1.48M, and an appid floor of 2.3M would keep only 24% of the games released within `W`.

## 7. Threshold search criterion degenerates as the sample grows (done)

- The pre-freeze search picks the smallest merge distance that maximizes the number of clusters with at least
  `min_cluster_size` games released within `W` (FORMULATION §6 amendment of 2026-10-03). It prefers finer partitions
  whenever more data is available.
- Observed on run 20261003T204134704Z-d8d2b3 (3002 enriched games, 1201 in the simple subset): the search gives
  0.32 for W = 48 (381 tag clusters) and 0.0 for W = 60, while the frozen 0.9367 yields 18 well-sized archetypes.
- Replace or bound the criterion (for example a cap on the number of tag clusters or a minimum within-cluster
  cohesion), then decide whether to re-freeze. Needs user approval since FORMULATION §6 is locked.
- Status: the search now picks the largest merge distance reached before one cluster holds more than
  `analysis.max_cluster_share = 0.15` of the clustered games. It reproduces the frozen 0.9367 on run 20261003T162937824Z-28423c
  and gives 0.9219 on run 20261003T204134704Z-d8d2b3, so nothing was re-frozen.

## 8. Request budget does not scale with the scan size (done)

- `acquisition.request_budget = 10000` is counted per invocation of `run_acquisition`, and a 10-page scan needs
  about 14000 requests (7827 appdetails + 3004 review summaries + 3004 SteamSpy details). Run
  20261003T204134704Z-d8d2b3 stopped with `RequestBudgetExceeded` and had to be resumed.
- A resume starts a fresh counter, so the cap does not bound the total spent by a run.
- Derive the budget from the planned scan size (or from `max_catalog_pages`) and track the total per run.
- Resume bug found on the same run and fixed in commit 8a551b4: totals now cover earlier invocations. The stored
  `funnel_report` of run 20261003T162937824Z-28423c still carries the old undercount (1555 instead of 2055 fetched).
- Status: the budget is now per run. It is the explicit override, else `request_budget`, raised to
  `request_budget_per_catalog_page` (1500) times `max_catalog_pages`, minus the requests already stored for the run, so resumes
  no longer get a fresh budget. The new-analysis form's budget field (`request_budget_override`) had no effect before; it is applied now.

## 9. Software-like archetype among games (done)

- The opportunity matrix of run 20261003T204134704Z-d8d2b3 contains "Utilities / Software / Design & Illustration"
  (5 games). All rows have `app_type = game`, so the coarse filter cannot separate such titles.
- Check whether Steam's `type` or the genre/category fields can exclude non-game software without scraping.
- Status: Steam types these apps as `game`, but their genres (Utilities, Animation & Modeling, Game Development, ...) mark them as
  software. Enrichment now drops apps with any genre in `enrichment.exclusions.software_genres` (FORMULATION §0). On run
  20261003T204134704Z-d8d2b3 this removed 35 of 3002 apps and the software archetype; the scored archetypes went from 18 to 14
  because several 5-7 game clusters fell under the 5-game floor. Run 20261003T162937824Z-28423c, the source of the frozen threshold,
  was left as it was.
