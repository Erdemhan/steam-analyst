# TODO

Items recorded for later. None of these are started.

## 1. Make the complexity weights user-adjustable

- Allow the complexity score weights (FORMULATION §4, `enrichment.complexity_weights.*`) to be overridden by the user at run time.
- When the user does not override them, the frozen defaults from `config/parameters.toml` must be used unchanged.
- Open points to settle before implementation:
  - Where the override is supplied (run configuration, UI form, or a separate TOML file).
  - Validation: overridden weights must still sum to 1.00 (or be renormalized, which needs a decision).
  - Whether the overridden weights are stored with the run so that results remain reproducible.
  - FORMULATION.md is user-locked, so the defaults stay there and overrides must not modify it.

## 2. Archetype labels are ambiguous

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

## 3. Cap the rate limiter's 429 widening

- `RateLimiter.observe_response` doubles the request interval on every 429 after the first, with no upper bound
  (`src/steam_analyst/acquisition/rate_limiter.py`).
- Observed on run 20261003T162937824Z-28423c: after six 429 responses the interval grew to tens of seconds and the
  run effectively stalled. It was resumed after lowering `steam_requests_per_minute` from 60 to 30.
- Add a ceiling on the widened interval and a cool-down/recovery rule, then re-check the 30 requests/minute default.

## 4. Freeze script must not write locked values without confirmation

- `scripts/freeze_empirical_parameters.py` rewrites the complexity bounds and `tag_distance_threshold` in
  `config/parameters.toml` directly, although the module docstring says it only prints the text to paste (ADR-012).
- Observed: running it on a new run silently replaced already frozen bounds.
- Make writing opt-in (for example a `--write` flag), default to print-only, and reconcile the docstring with the behavior.

## 5. Funnel report shows zero coarse-filter rejections

- `funnel_report.rejected_by_reason` reports 0 for `review_count_below_floor` and `publisher_blocklisted`
  while only `release_date_outside_window` is non-zero (run 20261003T162937824Z-28423c, 3000 catalog apps, 713 candidates).
- The counts from the SteamSpy coarse filter (`acquisition/funnel.py`) do not appear to reach the stored report
  (`_get_initial_rejection_reasons` in `acquisition/pipeline.py` starts all at zero).
- Verify and merge the funnel's own counts into the stored report.

## 6. Too few recent games in the sample for the opportunity matrix

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
- Findings on run 20261003T162937824Z-28423c that bear on this item:
  - SteamSpy `all` is ordered by owners, descending, and the first three pages (3000 apps) end at the 200k-500k owner band.
  - The SteamSpy bulk payload has no release date, so the 2020+ release filter can only run after `appdetails`;
    1341 of the 2056 `appdetails` calls were spent on apps released before 2020.
  - Using the appid as a proxy for release recency does not work: 2025 releases in the sample have a median appid of
    about 1.48M, and an appid floor of 2.3M would keep only 24% of the games released within `W`.
