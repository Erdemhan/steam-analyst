# Architecture — Steam Analyst

> Status: architecture approved, no implementation code exists yet.
> Last updated: 2026-09-20 (orchestration and ui modules detailed; ADR-014 to ADR-018 added).

## System Overview

Steam Analyst is a single-machine, manually triggered analysis tool that answers one
question: **which low-complexity game archetypes (genre / tag / mechanic combinations)
have demonstrated commercial success on Steam, and where do high demand and low
competition currently intersect?**

The system performs open-ended discovery across the whole Steam catalog rather than
inspecting a pre-selected set of genres. A single execution is called a **run**. A run
pulls catalog-wide data from documented APIs, narrows the catalog down to a tractable
candidate set, derives "how simple was this to build" and "how well did it sell"
proxy features, and produces an opportunity view that ranks archetypes by demand,
competition density and estimated build effort.

Every run is persisted in full (raw HTTP payloads, enriched features, analysis
outputs) inside one SQLite file, keyed by `run_id`. Nothing is recomputed from the
network when a past run is reopened, so historical analyses remain browsable and
reproducible from stored raw data.

Architectural drivers, in priority order:

1. **Terms-of-service safety** — official / documented endpoints only, conservative
   rate limiting, no HTML scraping.
2. **Bounded API cost** — a coarse filter on cheap bulk data precedes any per-app
   request, keeping per-app calls in the low thousands instead of ~150k.
3. **Reproducibility** — raw responses are stored immutably per run; enrichment and
   analysis are pure re-runnable transformations over stored raw data.
4. **Operational simplicity** — one Python process, one database file, no scheduler,
   no service split.

## Module Structure

```
steam-analyst/
├── app.py                                  # Streamlit entry point (thin; calls ui.main)
├── requirements.txt
├── .env.example                            # STEAM_WEB_API_KEY placeholder, no secrets
├── config/
│   └── parameters.toml                     # machine-readable mirror of FORMULATION.md
├── data/
│   └── analyses.db                         # SQLite, git-ignored
├── src/steam_analyst/
│   ├── config/                             # settings loading, parameter dataclasses
│   ├── storage/                            # schema, migrations, DAO (shared by all)
│   ├── acquisition/                        # API clients, rate limiting, coarse filter
│   ├── enrichment/                         # derived features (complexity, revenue)
│   ├── analysis/                           # simplicity filter, clustering, opportunity
│   ├── reporting/                          # read-model for the UI (tables, case studies)
│   ├── orchestration/                      # pipeline stage sequencing, progress events
│   └── ui/                                 # Streamlit pages
├── scripts/
│   ├── freeze_empirical_parameters.py      # ADR-012
│   └── verify_parameters_consistency.py    # ADR-013
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/                           # recorded API payload samples
└── .claude/
    ├── context/{ARCHITECTURE.md, FORMULATION.md, context.db}
    └── specs/*.module_spec.json
```

### Dependency Direction

```
ui ──► orchestration ──► acquisition ──► storage ──► (sqlite3, pandas)
 │            │       ──► enrichment  ──► storage
 │            │       ──► analysis    ──► storage
 └──► reporting ─────────────────────────► storage
                 all modules ──► config
```

Rules enforced by this layout:

- `storage` and `config` are leaves; they import no other project module.
- `acquisition`, `enrichment`, `analysis` never import each other. They communicate
  only through database tables, which makes each stage independently re-runnable.
- The stage modules never import `orchestration` either. The `EventSink` protocol they
  type-hint their `on_event` parameter against is therefore declared in `storage`, not
  in `orchestration`, so the progress callback contract does not invert the arrows.
- `reporting` is read-only. It depends on `storage` but not on `analysis`, so the UI
  can render any historical run even if analysis logic later changes shape.
- `ui` contains no business logic — only widget layout and calls into
  `orchestration` / `reporting`.

## Data Model (SQLite — `data/analyses.db`)

Single database file. All non-meta tables are keyed by `run_id` so runs never
overwrite each other.

| Table | Key | Purpose |
|---|---|---|
| `schema_meta` | `version` | Single row; migration bookkeeping. |
| `runs` | `run_id` | One row per execution: timestamps, status, config snapshot, trigger type. |
| `run_stages` | `(run_id, stage)` | Per-stage status for one run. The checkpoint that makes stage-granular resume possible (ADR-014). |
| `run_events` | `event_id` | Append-only progress/log stream per run; the UI polls this for progress. |
| `raw_games` | `(run_id, appid, source)` | Verbatim JSON payloads per source. Immutable once written. |
| `games_enriched` | `(run_id, appid)` | Derived feature row per candidate app. |
| `game_tags` | `(run_id, appid, tag)` | Normalized tag/vote pairs; supports tag clustering and density queries without JSON parsing. |
| `analysis_results` | `(run_id, analysis_type)` | JSON blobs for opportunity matrix, tag summary, trends, case-study selections. |

Key columns:

- `runs`: `run_id TEXT PK`, `started_at`, `finished_at`, `status`
  (`pending|running|succeeded|failed|cancelled`), `trigger_type`
  (`manual|scheduled` — `scheduled` unused today, reserved), `parent_run_id`
  (reserved for future incremental re-crawls), `config_json`, `parameters_version`,
  `code_version`, `error_message`, `notes`.
- `run_stages`: `stage` ∈ `{acquisition, enrichment, analysis}`, `status` drawn from
  the same vocabulary as `runs.status`, plus `started_at`, `finished_at`, `attempt`
  and `error_message`. Rows are created lazily on first attempt of a stage, so a
  stage that was never started has no row at all — "not started" and "started but
  pending" stay distinguishable. `attempt` increments on every re-attempt, which is
  how a resume or a deliberate stage re-run after a parameter change is auditable.
- `raw_games`: `source` ∈ `{steamspy_all, steamspy_appdetails, steam_appdetails,
  steam_reviews}`, plus `fetched_at`, `http_status`, `payload_json`, `payload_sha256`.
- `games_enriched`: identity (`name`, `developer`, `publisher`, `release_date`,
  `app_type`), raw signals (`price_usd`, `review_count`, `review_positive_pct`,
  `owners_estimate_low/mid/high`, `size_bytes`, `achievement_count`,
  `language_count`, `platform_count`, `dlc_count`, `dev_title_count`,
  `is_early_access`, `early_access_days`, `deck_compat`), derived scores
  (`complexity_score`, `estimated_sales`, `estimated_revenue_gross_usd`,
  `estimated_revenue_net_usd`, `effort_adjusted_return`), and
  `params_version` identifying which parameter set produced the derived columns.

Forward compatibility for a future scheduler: `runs.trigger_type` and
`runs.parent_run_id` exist now and are populated with `manual` / `NULL`. Adding a
scheduler later requires no schema migration, only a new trigger path that calls the
existing `orchestration.run_pipeline`.

Retention: runs are never auto-deleted. Deletion is an explicit user action
(`storage.delete_run`) that cascades across all run-keyed tables, `run_stages`
included.

## Data Sources and Acquisition Funnel

Only documented endpoints are used. No Steam Store HTML, SteamDB or SteamCharts
scraping (see ADR-003).

| Source | Endpoint class | Used for | Cost profile |
|---|---|---|---|
| SteamSpy | bulk `all` (paginated) | catalog-wide review counts, owner bands, price | few dozen requests, heavily rate limited per page |
| SteamSpy | per-app `appdetails` | **tags** (community tag/vote data) | 1 request per surviving app |
| Steam Web API / storefront | `appdetails` | genres, categories, release date, price, languages, platforms, DLC, required disk space, Deck compatibility | 1 request per surviving app |
| Steam Web API | reviews summary | review count, positive percentage, review language split | 1 request per surviving app |
| Steam Web API | app list | appid ↔ name reconciliation, catalog size sanity check | 1 request |

**Correction (2026-09-23, from a real end-to-end run against live APIs).** ADR-004's
original design assumed SteamSpy's bulk `all` payload carries tag data, to avoid a
second per-app SteamSpy call. Running the real pipeline against live data showed
this is false: SteamSpy's bulk endpoint returns only `appid, name, developer,
publisher, positive, negative, owners, price, initialprice, discount, ccu,
average_forever, average_2weeks, median_forever, median_2weeks, score_rank,
userscore` — no `tags` field at all. Tags are only available via SteamSpy's
per-app `request=appdetails&appid=N` endpoint (`SteamSpyClient.fetch_app`, already
implemented but previously marked "not invoked in v1" on the wrong assumption).
`run_acquisition` now calls this per surviving candidate, alongside the existing
Steam Web API `appdetails`/reviews calls, persisted under `raw_games.source =
'steamspy_appdetails'` (a source value the schema already reserved for this).
`enrichment.RawBundle` gained a `steamspy_appdetails: dict[int, dict]` field, and
`enrichment.extract_tags` reads tags from there instead of from `steamspy` (the
bulk payload). This roughly doubles per-candidate request count (three per-app
calls instead of two: SteamSpy appdetails, Steam appdetails, Steam reviews), which
is still bounded by ADR-004's "low thousands of candidates" funnel design, not the
full ~150k catalog.

Funnel:

```
SteamSpy bulk (entire catalog, ~150k apps)
        │  coarse filter: review-count band, release window, price sanity,
        │  exclude near-zero-signal and viral/AAA-scale outliers
        ▼
candidate set (target: low thousands)
        │  per-app: appdetails + reviews summary, rate limited, cached raw
        ▼
raw_games  ──► enrichment ──► games_enriched ──► analysis ──► analysis_results ──► UI
```

The coarse filter runs on already-persisted bulk data, so its thresholds can be
re-tuned and the filter re-executed without re-fetching, as long as a new candidate
app was already inside the stored bulk snapshot.

**Locale pinning (user-approved 2026-09-20).** Every Steam Web API / storefront call
is pinned to `cc=us&l=english`. All prices, review summaries and revenue estimates
are therefore on a single consistent basis instead of mixing regional price points,
matching the convention SteamSpy and most third-party revenue calculators already
use. This is a fixed acquisition-stage setting, not a per-run option.

Rate limiting: a single shared token-bucket limiter per host with conservative
defaults, `Retry-After` support, exponential backoff with jitter on HTTP 429/5xx, and
a hard per-run request budget that fails the run loudly instead of hammering the API.
Published limits for these endpoints are inconsistently documented; defaults are
deliberately pessimistic and are treated as tunable configuration, not as verified
facts.

**Raw payload cache scope.** The cache is keyed by `(run_id, appid, source)` and there
is no cross-run lookup path in v1. A new `run_id` therefore re-fetches the entire
catalog; only a re-attempt *within the same run* reuses what is already stored. This
is what makes resume worth having (ADR-014) and it is the reason
`acquisition.run_acquisition` consults `storage.read_fetched_appids` before issuing
any request.

## Module Specifications

Machine-readable specs live in `.claude/specs/*.module_spec.json` and are the input
for `@module-planner`.

### Module: config
- **Responsibility**: Load settings (`.env`, `config/parameters.toml`) into typed,
  validated dataclasses; expose the parameter set version used to stamp derived rows.
- **Dependencies**: none (leaf).
- **Public Interface**: `load_settings()`, `load_parameters()`, `Settings`,
  `AcquisitionConfig`, `EnrichmentParams`, `AnalysisParams`, `parameters_version()`.
- **Status**: Planned.

### Module: storage
- **Responsibility**: Own the SQLite schema, migrations and every read/write path.
  No other module issues SQL.
- **Dependencies**: config.
- **Public Interface**: `get_connection`, `connect`, `initialize_schema`, `migrate`,
  `create_run`, `update_run_status`, `list_runs`, `get_run`, `delete_run`,
  `begin_run_stage`, `finish_run_stage`, `read_run_stages`, `append_run_event`,
  `read_run_events`, `EventSink`, `upsert_raw_payloads`, `read_raw_payloads`,
  `read_fetched_appids`, `write_enriched`, `read_enriched`, `write_tags`, `read_tags`,
  `write_analysis_result`, `read_analysis_result`.
- **Status**: Planned.

### Module: acquisition
- **Responsibility**: Fetch SteamSpy bulk data, apply the coarse filter, fetch
  `appdetails` and review summaries for survivors, rate limit, and persist verbatim
  payloads into `raw_games`.
- **Dependencies**: storage, config.
- **Public Interface**: `SteamSpyClient`, `SteamStoreClient`, `SteamReviewsClient`,
  `RateLimiter`, `fetch_steamspy_catalog`, `coarse_filter`, `fetch_app_details`,
  `fetch_review_summaries`, `run_acquisition`.
- **Status**: Planned.

### Module: enrichment
- **Responsibility**: Transform stored raw payloads into one feature row per app:
  parse/normalize fields, then compute `complexity_score`, `estimated_sales`
  (Boxleiter), `estimated_revenue_*` and `effort_adjusted_return`.
- **Dependencies**: storage, config.
- **Public Interface**: `parse_raw_bundle`, `compute_complexity_score`,
  `estimate_sales`, `estimate_revenue`, `compute_effort_adjusted_return`,
  `build_enriched_frame`, `run_enrichment`.
- **Status**: Planned.
- **Note**: All constants live in `FORMULATION.md` / `config/parameters.toml`, never
  inline in code.

### Module: analysis
- **Responsibility**: Apply simplicity thresholds, cluster tag co-occurrence into
  archetypes, detect release-date trends per archetype, compute competition density,
  and assemble the opportunity matrix (demand × competition × simplicity).
- **Dependencies**: storage, config.
- **Public Interface**: `apply_simplicity_filter`, `cluster_tags`,
  `compute_tag_trends`, `compute_competition_density`, `build_opportunity_matrix`,
  `run_analysis`.
- **Status**: Planned.

### Module: reporting
- **Responsibility**: Read-only assembly of a run's presentation model — opportunity
  matrix view, genre/tag summary table, top-N case studies with a short rationale, and
  the fixed interpretive caveat list. Returns objects, writes no files.
- **Dependencies**: storage, config.
- **Public Interface**: `load_run_report`, `is_partial_run`,
  `build_opportunity_matrix_view`, `build_tag_summary_table`, `select_case_studies`,
  `interpretive_caveats`, `partial_run_caveat`.
- **Status**: Planned.
- **Note**: `is_partial` is derived from `run_stages`, not from `runs.status`
  (ADR-016).

### Module: orchestration

- **Responsibility**: Sequence acquisition → enrichment → analysis for one run. Create
  the run row, run the parameter-consistency preflight, maintain per-stage status in
  `run_stages`, emit `run_events` progress records, service cooperative cancellation,
  translate every exception into a terminal run status, and keep all of that off the
  Streamlit script thread.
- **Dependencies**: acquisition, enrichment, analysis, storage, config.
- **Status**: Planned.

**Public interface.**

| Name | Kind | Contract |
|---|---|---|
| `PipelineStage` | `StrEnum` | Exactly `ACQUISITION = "acquisition"`, `ENRICHMENT = "enrichment"`, `ANALYSIS = "analysis"`. Declaration order is execution order, so `list(PipelineStage)` *is* the pipeline. Values are byte-identical to the `run_events.stage` / `run_stages.stage` strings. |
| `RUN_LEVEL_STAGE` | constant | `"pipeline"`. The `run_events.stage` value for run-level records (preflight, run started, run finished, cancellation requested). Deliberately not an enum member, because it is not executable and must never reach `run_stages`. |
| `PipelineConfig` | dataclass | `start_stage: PipelineStage = ACQUISITION`, `max_catalog_pages: int \| None = None`, `request_budget_override: int \| None = None`, `notes: str \| None = None`. Serialized into `runs.config_json`. |
| `PipelineResult` | dataclass | `run_id`, `status`, `stages_run`, the three stage reports (nullable), timestamps, `duration_seconds`, `error_message`. |
| `run_pipeline` | function | `(conn, run_id, config, *, settings=None, cancel_token=None) -> PipelineResult`. Synchronous, on the caller's thread, using the caller's connection. Records terminal status, then re-raises. |
| `start_pipeline_async` | function | `(db_path: Path, config, *, settings=None) -> str`. Creates the run row on the calling thread, starts a worker, returns `run_id` immediately. Never takes or returns a connection. |
| `resume_run` | function | `(db_path: Path, run_id: str, *, settings=None) -> str`. Resumes in place, returns the *same* `run_id`. |
| `cancel_run` | function | `(run_id: str) -> bool`. Sets the cooperative cancellation flag. `False` when no live worker is registered. |
| `is_running` / `active_run_ids` | functions | Liveness queries used by the UI to decide between Cancel and Resume. |
| `reconcile_orphaned_runs` | function | `(conn) -> list[str]`. Startup repair for runs orphaned by a process kill. |
| `make_event_sink` | function | Builds the concrete `storage.EventSink` handed to every stage; the single place that decides event granularity and throttling. |
| `PipelineError`, `PipelineCancelled`, `PreflightError` | exceptions | See the status mapping below. |

**`PipelineConfig` scope.** It carries only what varies per run *and* is not a
formulation parameter. Everything in `FORMULATION.md` reaches the pipeline through
`config/parameters.toml` and is not settable here or from the UI. `start_stage` drives
both resume and a deliberate stage re-run after a parameter change.
`max_catalog_pages` is the smoke-test limiter already present in
`acquisition.fetch_steamspy_catalog`. `request_budget_override` supersedes
`AcquisitionConfig.request_budget` when set. `notes` populates the existing
`runs.notes` column. No `stop_after_stage` field exists, because nothing needs it:
re-running enrichment after a formula change implies re-running analysis anyway.

**Per-stage execution sequence.** For each stage from `config.start_stage` onward:
check cancellation (CP1) → `begin_run_stage` (status `running`, attempt incremented,
committed) → call the stage entry point with the shared `EventSink` and the cancel
token → the stage commits its own data → `finish_run_stage('succeeded')` → append the
stage-complete event, last of all.

**Preflight**, in order: `create_run` (so the run row exists before anything that can
fail) → `load_settings` / `load_parameters` → the ADR-013 consistency check → schema
`initialize_schema` / `migrate`. The consistency check runs on resume as well, so a
resumed run cannot silently continue against a hand-edited `parameters.toml`.

**Cooperative cancellation** is detailed in ADR-015; the **exception → status
mapping** in ADR-016; the **thread and connection contract** in ADR-017.

### Module: ui

- **Responsibility**: Streamlit presentation shell. "Run New Analysis" (parameter form,
  trigger, live progress, cancel), "Past Analyses" (run list with status and headline
  metrics, resume and delete), "Analysis Detail" (opportunity matrix, tag table, case
  studies, caveats). Widget layout and routing only.
- **Dependencies**: orchestration, reporting, storage, config.
- **Public Interface**: `main`, `build_navigation`, `render_new_analysis_page`,
  `render_progress_panel`, `render_past_analyses_page`, `render_analysis_detail_page`,
  `render_caveat_panel`, `SESSION_KEYS`.
- **Status**: Planned.
- **Out of scope for v1**: cross-run comparison view (see ADR-011).

**Routing** uses `st.navigation` over `st.Page` objects built from functions (ADR-018),
not the `pages/` directory convention. The Analysis Detail page is addressed by
`st.query_params["run_id"]`, so it is refresh-safe and linkable.

**Session state** is exactly three keys:

| Key | Type | Why it is needed |
|---|---|---|
| `active_run_id` | `str \| None` | The run the progress panel is watching. |
| `last_event_id` | `int` | High-water mark for incremental `read_run_events`, so each poll transfers only new rows. |
| `event_log` | `list[RunEvent]` | Accumulates events across polls. Required precisely because the read is incremental; without it each poll would render only the newest slice. |

The selected run for the detail page is *not* a session key — it lives in the query
parameter. Form values are not session keys either, since Streamlit widgets already
retain their own state by key.

**Progress polling** happens only inside `render_progress_panel`, decorated
`@st.fragment(run_every="2s")`, so the rest of the page does not rerun on every tick.
When the watched run reaches a terminal status the fragment stops polling and triggers
one full rerun.

## Architectural Decision Log (ADR)

### ADR-001: SQLite as the single persistence store
- **Context**: A run produces raw JSON payloads, a wide derived feature table and
  aggregate analysis outputs. The tool is single-user and single-machine, and past
  runs must stay browsable indefinitely.
- **Decision**: One SQLite file, `data/analyses.db`, holds raw, enriched and analysis
  data, all keyed by `run_id`. All SQL lives in the `storage` module.
- **Consequences**: Zero-setup persistence, transactional per-stage writes, trivial
  backup. The file grows monotonically (raw JSON dominates); mitigations are payload
  compression and explicit run deletion rather than a different engine. Concurrent
  writers are not supported, which is acceptable because only one pipeline runs at a
  time; WAL mode is used so the UI can read while the pipeline writes.

### ADR-002: Streamlit as a single-process UI
- **Context**: The user needs a browsable UI for triggering runs and reading results,
  without operating a separate frontend and backend.
- **Decision**: Streamlit, with `app.py` as entry point and all business logic behind
  the `reporting` / `orchestration` modules.
- **Consequences**: Minimal surface area and no API layer to maintain. Streamlit's
  rerun-on-interaction model means long work cannot block the script thread, which
  forces ADR-006. The UI is not multi-user or authenticated; it is a local tool.

### ADR-003: Official and documented APIs only — no scraping
- **Context**: Steam Store pages, SteamDB and SteamCharts carry the richest data, but
  scraping them violates their terms and risks IP bans.
- **Decision**: Restrict data acquisition to the Steam Web API / storefront
  `appdetails`, the Steam reviews endpoint, and the SteamSpy API. No HTML parsing of
  any Valve or third-party property.
- **Consequences**: Legally and operationally safe, at the cost of coarser data —
  notably no wishlist data, no historical price/player-count series, and owner
  estimates only via SteamSpy. Several desirable features (wishlist-based demand,
  concurrent-player trends) are therefore unavailable and must not be faked.

### ADR-004: Two-stage acquisition funnel (bulk first, per-app second)
- **Context**: The catalog holds roughly 150k apps. One `appdetails` call each is
  infeasible under any acceptable rate limit.
- **Decision**: Pull SteamSpy's paginated bulk endpoint for the whole catalog, apply a
  coarse filter on review count, release window and price sanity to isolate
  "modest indie success" candidates, and only then issue per-app `appdetails` and
  review-summary calls for the survivors.
- **Consequences**: Per-app requests drop by roughly two orders of magnitude. The
  trade-off is that the candidate set inherits SteamSpy's coverage gaps and the coarse
  filter's threshold choices; anything filtered out at stage one is invisible to the
  rest of the pipeline. The filter must therefore record rejection counts per reason so
  the funnel remains auditable, and thresholds are configuration, not constants in code.

### ADR-005: Immutable raw payload cache per run
- **Context**: Re-running analysis after a formula or threshold change must not
  re-hit the APIs, and results must be reproducible after the fact.
- **Decision**: Store every HTTP response body verbatim in `raw_games` with its source,
  fetch timestamp and status. Enrichment and analysis read only from the database.
  Raw rows are never updated in place; a corrected fetch creates a new run.
- **Consequences**: Full offline re-analysis and reproducibility; enrichment/analysis
  become pure functions of stored data and are unit-testable from fixtures. Storage
  cost grows with run count, accepted under ADR-001.
- **Clarification (2026-09-20)**: "never updated in place" constrains *overwrites*, not
  *insert-missing*. Re-attempting acquisition for the same `run_id` inserts only the
  appids not yet stored for that run (`INSERT OR IGNORE` on the primary key) and never
  rewrites an existing payload. This is what ADR-014 relies on. The cache is scoped to
  a single `run_id`; no code path reads another run's payloads.

### ADR-006: Manual run model with DB-mediated progress
- **Context**: Runs are triggered by hand and take minutes to hours. Streamlit reruns
  its script on every interaction, so in-memory progress state is unreliable.
- **Decision**: No scheduler. `orchestration` executes the pipeline on a background
  worker thread and reports progress by appending to `run_events`; the UI polls that
  table. Run identity is a `run_id` plus timestamp, and history is permanent.
- **Consequences**: Progress survives page refreshes and is replayable as a run log
  after completion. Cost is polling latency and the need for careful SQLite connection
  handling across threads (one connection per thread, WAL mode), spelled out concretely
  in ADR-017. A scheduler can be added later on top of the same entry point without
  touching the schema.

### ADR-007: Boxleiter-style revenue estimation with a per-genre multiplier range
- **Context**: Steam publishes no sales figures. The standard public proxy is the
  Boxleiter method: estimated units ≈ review count × a multiplier.
- **Decision**: Use `estimated_sales = review_count × multiplier(genre)`, where the
  multiplier is a per-genre range rather than one global constant, and propagate a
  low/mid/high estimate instead of a single number. Revenue is reported both gross and
  net of the storefront cut. All constants are recorded in `FORMULATION.md`.
- **Consequences**: Results are ordinal signals, not financial figures. Every surface
  that shows revenue must show the estimate band and the caveat. The multiplier values
  were sourced and locked in `FORMULATION.md` §2 on 2026-09-20 as a three-bucket
  scheme; that record, not this ADR, is canonical for the numbers.

### ADR-008: "Simplicity" as a composite metadata proxy score
- **Context**: Development effort is not in any API. The user's constraint is a solo or
  two-person team, one to a few months, 2D or light 3D.
- **Decision**: Compute `complexity_score` as a weighted, normalized combination of
  install size, achievement count, supported language count, platform count, DLC count,
  developer catalog size, early-access duration and simplicity-indicating tags
  (for example pixel-art, 2D, casual, short, singleplayer). Thresholds are calibrated
  broadly across 2D and light 3D rather than 2D-only.
- **Consequences**: Gives a catalog-wide, cheap effort ranking. It systematically
  misses art polish, marketing spend, content volume and iteration time, so a low score
  means "plausibly small in scope", not "cheap to make". This caveat is rendered
  alongside every case study.

### ADR-009: Stage isolation through the database, not through imports
- **Context**: Enrichment formulas and analysis thresholds will change often; refetching
  must never be a prerequisite for re-running them.
- **Decision**: Each pipeline stage reads its input from and writes its output to
  SQLite. `acquisition`, `enrichment` and `analysis` do not import one another.
- **Consequences**: Any stage can be re-executed alone for an existing `run_id`, and
  each stage is testable from database fixtures. The cost is an extra serialization
  round-trip per stage and explicit `params_version` stamping so derived rows can be
  matched to the parameter set that produced them. ADR-014 is the mechanism that makes
  the re-execution claim verifiable rather than merely possible.

### ADR-010: Secrets and tunables outside the repository
- **Context**: The Steam Web API key must never be committed, and the estimation
  constants must be auditable.
- **Decision**: Secrets come from `.env` (git-ignored), documented by a committed
  `.env.example`. Estimation and threshold values live in `config/parameters.toml`,
  which is committed and must mirror `FORMULATION.md` exactly.
- **Consequences**: Clean separation between secret, tunable and derived data. A
  consistency check between `parameters.toml` and `FORMULATION.md` is required in CI or
  as a startup assertion, otherwise the two records can silently drift.

### ADR-011: Cross-run comparison deferred
- **Context**: Comparing two runs (what changed in demand or competition) is valuable
  only once several runs exist, and the diffing semantics are non-trivial.
- **Decision**: Build single-run browsing only. The schema already supports comparison
  because every run is fully retained and `parent_run_id` exists.
- **Consequences**: Smaller v1. Adding comparison later is additive — a new page plus a
  new reporting function, with no data migration.

### ADR-012: Empirical parameters are frozen by a dedicated script, not by hand

- **Context**: `FORMULATION.md` locks complexity-score normalization bounds and the
  tag-clustering distance threshold to be *derived empirically from the first
  completed run*, rather than guessed. Someone has to compute those values from
  `run 1`'s stored data and get them into `config/parameters.toml`, which `config`
  itself is explicitly barred from writing (see its `non_goals`).
- **Decision**: A standalone script, `scripts/freeze_empirical_parameters.py`, reads
  a given run's `games_enriched` data, computes the 5th/95th-percentile bounds per
  complexity feature and the tag-distance-cut threshold, writes them into
  `config/parameters.toml`, and prints the exact Markdown snippet (run ID, date,
  resulting values) for a human to paste into `FORMULATION.md`. It does not edit
  `FORMULATION.md` itself — that file's content is user-approved prose, and the
  paste step is a deliberate human checkpoint even though the numbers themselves
  are a mechanical consequence of a method the user already locked.
- **Consequences**: Removes manual arithmetic/transcription error for the numeric
  values, while keeping a human in the loop for the one file that is explicitly
  user-locked. `run 1` cannot produce a final, comparable `complexity_score` or
  tag clusters until this script has been run once; earlier runs' derived scores
  are provisional until then.

### ADR-013: Parameter-consistency check as a standalone script

- **Context**: ADR-010 requires that `config/parameters.toml` and `FORMULATION.md`
  never silently drift apart, but didn't say how that gets checked.
- **Decision**: `scripts/verify_parameters_consistency.py` parses both files and
  fails loudly on any mismatch. It runs in CI and again as a startup assertion in
  `orchestration.run_pipeline`, so a run cannot proceed against a stale or
  hand-edited `parameters.toml`.
- **Consequences**: One more moving part to maintain, but the alternative — a run
  silently using parameters that no longer match the approved record — would
  invalidate the run without anyone noticing. The check runs on the resume path too
  (ADR-014), otherwise resume would be a hole in the guarantee.

### ADR-014: Resume is stage-granular and in place, backed by `run_stages`

- **Context**: A run can stop part-way for mundane reasons — a NaN in enrichment, a
  transient API outage, a user cancelling, the process being killed. Two designs were
  considered. The simpler one drops per-stage state entirely: "resume" becomes "start a
  new run", with `parent_run_id` recording lineage. The other adds a per-stage
  checkpoint so a run can continue from the stage that failed.

  The simpler option is only attractive if a from-scratch re-run is cheap, so the
  premise was checked against the existing design rather than assumed. It does not
  hold. `raw_games` is keyed by `(run_id, appid, source)` and no read path consults
  another run's payloads; `acquisition`'s non-goals state plainly that there is no
  incremental fetch against a previous run in v1. A new `run_id` therefore re-fetches
  the entire SteamSpy bulk catalog (~150k apps over dozens of heavily rate-limited
  pages) plus two requests for each of several thousand candidates. Re-paying that
  because enrichment divided by zero is a direct violation of driver 2 (bounded API
  cost) and needlessly increases exposure under driver 1.

  A second problem rules out deriving stage completion from the data itself.
  `acquisition`'s own invariant is that payloads are persisted in batches so "a crash
  mid-stage leaves usable partial data". The presence of `raw_games` rows therefore
  cannot distinguish a completed acquisition from one that died halfway. Without an
  explicit marker, ADR-009's promise that "any stage can be re-executed alone" is not
  checkable.
- **Decision**: Resume is stage-granular and happens **in place on the same
  `run_id`**. A `run_stages(run_id, stage)` table records `status`, `started_at`,
  `finished_at`, `attempt` and `error_message` per stage. `orchestration.resume_run`
  reads it, finds the first stage in pipeline order that is not `succeeded`, and
  restarts from there using the `PipelineConfig` stored in `runs.config_json`. No new
  run row is created, no new `run_id` is issued, and `parent_run_id` is not written —
  it stays reserved for the future incremental re-crawl of ADR-011/ADR-004 scope.

  Granularity stops at the stage boundary: a stage is either complete or it re-runs
  from its own start. Within acquisition, the re-run is still cheap because
  `run_acquisition` consults `storage.read_fetched_appids` and skips appids already
  persisted *for that run*. That is an insert-missing operation, not an overwrite, so
  ADR-005 immutability is untouched (see its clarification note).

  Because no implementation code exists yet, `run_stages` is part of schema v1 and no
  migration is required.
- **Alternative rejected**: deriving stage state from `run_events` message text. That
  turns a log into a string-typed state machine, and a wording change silently breaks
  resume.
- **Consequences**: One small table and three accessors
  (`begin_run_stage`, `finish_run_stage`, `read_run_stages`). In exchange: a failed run
  costs one stage to recover instead of a full re-crawl; a run killed by a process
  restart becomes resumable after `reconcile_orphaned_runs`; the UI gets stage-level
  progress for free; and `reporting.is_partial` acquires a precise definition (ADR-016)
  instead of being inferred. The cost is that a resumed run can carry two
  `parameters_version` values across its derived rows if `parameters.toml` changed
  between attempts — surfaced as a warning event rather than blocked, since the ADR-013
  preflight still guarantees the file matches `FORMULATION.md` at the moment of resume.

### ADR-015: Cooperative cancellation at enumerated check-points

- **Context**: A run takes minutes to hours and the user must be able to stop it. A
  thread cannot be killed safely: an abort in the wrong place can leave a consumed rate
  limiter token unspent, a half-read HTTP response pinned in the connection pool, or a
  batch of payloads written without the status that describes them.
- **Decision**: Cancellation is cooperative, signalled by a `threading.Event` held in a
  module-level registry in `orchestration` keyed by `run_id`. In-process state is
  sufficient, because ADR-002 and ADR-006 put the UI and the pipeline in one process;
  if the process dies the run dies with it and `reconcile_orphaned_runs` cleans up at
  next startup.

  The flag is polled at exactly seven points, and nowhere else:

  | # | Location | Exact moment |
  |---|---|---|
  | CP1 | `run_pipeline` | Before each stage begins, after the previous stage's `run_stages` row is committed |
  | CP2 | SteamSpy bulk loop | After each page's payloads are persisted and committed, before the next `RateLimiter.acquire()` |
  | CP3 | `appdetails` loop | After each batch of appids is persisted and committed, before the next batch's first `acquire()` |
  | CP4 | reviews-summary loop | Identical placement to CP3 |
  | CP5 | inside `RateLimiter.acquire()` | Its wait is `cancel_token.wait(remaining_interval)`; waking because of cancellation raises `PipelineCancelled` before a token is consumed and before any socket is opened |
  | CP6 | enrichment | Between processed chunks of the feature frame |
  | CP7 | analysis | Between named sub-steps: simplicity filter, `cluster_tags`, `compute_demand`, `compute_competition_density`, `compute_tag_trends`, `build_opportunity_matrix` |

  Three rules keep those points safe. Cancellation is never checked between
  `acquire()` returning and the request being issued, so a consumed token is always
  spent on a real request. An in-flight request is never aborted and its body is always
  read to completion, so the pooled connection is returned clean. CP5 is the only
  interruptible wait, and it raises before any request exists.
- **Consequences**: Worst-case latency from pressing Cancel to the worker unwinding is
  one in-flight request timeout plus one batch persist — bounded by
  `Settings.http_timeout_seconds` and the batch size, so the UI can state a bound
  instead of an indefinite wait. `PipelineCancelled` propagates to `run_pipeline`,
  whose `finally` writes `finish_run_stage(stage, 'cancelled')` and
  `update_run_status(run_id, 'cancelled')`. Committed partial data is kept, never
  rolled back, so a cancelled run is resumable under ADR-014. `cancel_run` on an
  unknown or already-finished run is an idempotent no-op returning `False`.

### ADR-016: Terminal status vocabulary stays fixed; partial completion is `is_partial`

- **Context**: A run can end in more shades than "worked" and "broke": cancelled
  mid-acquisition, failed in analysis with usable enriched data, or succeeded with a
  large share of per-app fetches having failed. The temptation is a new `runs.status`
  value such as `partial`.
- **Decision**: The vocabulary stays `pending | running | succeeded | failed |
  cancelled`. The UI-visible partial/complete distinction is `reporting.is_partial`,
  which already existed in the reporting spec, now with one precise definition:

  ```
  is_partial = {s.stage for s in run_stages if s.status == 'succeeded'}
               != {'acquisition', 'enrichment', 'analysis'}
  ```

  A run reaches `succeeded` only when all three `run_stages` rows are `succeeded`.
  Every exception maps to a terminal status:

  | Exception | Source | `runs.status` | `run_stages.status` | Partial data |
  |---|---|---|---|---|
  | `PipelineCancelled` | cancellation check-point | `cancelled` | `cancelled` | kept |
  | `KeyboardInterrupt` / `SystemExit` | process signal | `cancelled`, then re-raised | `cancelled` | kept |
  | `PreflightError` (wraps `ParameterError` or an ADR-013 mismatch) | config | `failed` | no stage row exists | none |
  | `RequestBudgetExceeded` | acquisition | `failed` | `failed` | kept |
  | `AcquisitionError` (other) | acquisition | `failed` | `failed` | kept |
  | `EnrichmentError` | enrichment | `failed` | `failed` | kept, `raw_games` intact |
  | `AnalysisError` | analysis | `failed` | `failed` | kept |
  | `StorageError` | storage | `failed`, best effort | `failed`, best effort | as committed |
  | any other `Exception` | anywhere | `failed` | `failed` | kept |

  `error_message` has a fixed format, `"{stage}: {ExceptionType}: {message}"`,
  truncated; the full traceback is appended as an `error`-level `run_event` rather than
  squeezed into the column. Degraded-but-complete outcomes stay `succeeded`: per-app
  fetch failures inside a successful acquisition are reported numerically through
  `AcquisitionReport.detail_failed` and `reporting.FunnelSummary`, not by failing the
  run. The one exception is `candidate_count > 0` with `detail_fetched == 0`, which is
  total acquisition failure rather than an empty result and raises `AcquisitionError`.
  An empty candidate set after the coarse filter is a legitimate `succeeded` run with
  empty downstream results and a warning event.

  A companion write-ordering rule makes the whole mapping observable: **the data of a
  unit of work is committed before the `run_events` row or `run_stages` / `runs` status
  that announces it.** Status and event writes are always last. Without this, WAL would
  faithfully deliver a "stage complete" event whose data is not yet committed.
- **Consequences**: No schema change to `runs.status`, no migration, and no second
  place where "did this run finish" is decided. `reporting` gains `stages` and
  `missing_stages` on `RunReport` so the UI can name which stage is absent, and a
  `partial_run_caveat` that carries `runs.error_message` into the caveat panel. The
  cost is that "partial" is no longer visible from the `runs` table alone; a consumer
  must join `run_stages`, which is why `is_partial_run` has exactly one implementation.

### ADR-017: Thread and connection lifecycle

- **Context**: ADR-006 says "one connection per thread, WAL mode" and stops there. The
  Streamlit script thread and the pipeline worker thread both touch the same database
  file, and `storage` raises on cross-thread connection use, so the ownership rules
  have to be explicit or the first implementation will guess wrong.
- **Decision**:
  - A `sqlite3.Connection` never crosses a thread boundary. `start_pipeline_async` and
    `resume_run` take a `Path`, never a connection, and never return one.
  - `start_pipeline_async` opens a short-lived connection **on the calling thread** to
    create the run row, commits, closes it, and only then starts the worker. This is
    what lets it return a `run_id` the UI can poll immediately.
  - The worker thread's target opens **its own** connection with `storage.connect()` as
    its very first statement and closes it in a `finally`, around the `run_pipeline`
    call. Workers are non-daemon, so interpreter shutdown waits for a clean unwind and a
    terminal status write.
  - `run_pipeline` itself is connection-agnostic and thread-agnostic: it uses whatever
    connection it is handed. That is what makes the entire pipeline testable
    synchronously with no threads at all.
  - The UI opens **one short-lived connection per Streamlit rerun**, inside a context
    manager in `ui.main`, closed before the script ends. `st.cache_resource` is never
    used for a connection: it would share one object across ScriptRunner threads and
    trip `storage`'s cross-thread guard.
- **Read consistency**: WAL is necessary but not sufficient. It gives the poller a
  snapshot of the last commit and keeps readers and the writer from blocking each
  other, but two further rules are required. On the reader side, connections are
  autocommit (`isolation_level=None`) and short-lived; a long-lived open read
  transaction would pin a stale snapshot and polling would never advance. On the writer
  side, the ordering rule from ADR-016 applies — data commits before the event or
  status that announces it. Together these give the UI a property it can rely on: any
  stage reported as `succeeded` has all of its data already visible to a new reader.
- **Consequences**: Connection churn is real but negligible for a local SQLite file.
  Cancellation state is in-process only, which is deliberate under ADR-002 and is
  cleaned up by `reconcile_orphaned_runs`. Two workers for the same `run_id` are
  impossible by construction, because registration into the cancellation registry
  happens under a lock before the thread starts.

### ADR-018: Streamlit routing via `st.navigation`, not a `pages/` directory

- **Context**: Streamlit offers two multi-page patterns: a `pages/` directory of
  top-level scripts discovered by convention, and `st.navigation` over `st.Page`
  objects that can wrap plain functions. The Analysis Detail view needs a `run_id`, and
  the project's own rules require every unit to be testable.
- **Decision**: `app.py` stays a three-line entry point calling `ui.main()`, which
  builds `st.navigation` over three `st.Page` objects wrapping functions in
  `ui/pages.py`. The detail view is addressed by `st.query_params["run_id"]` rather
  than by session state, so it is refresh-safe and linkable. Session state is limited
  to three keys (`active_run_id`, `last_event_id`, `event_log`), asserted by a test.
  Progress polling lives only in a `@st.fragment(run_every="2s")` panel, so a two-second
  tick does not rerun the whole page.
- **Alternatives rejected**: the `pages/` directory requires top-level scripts that
  cannot take arguments and cannot be imported into a test, which would place the UI
  outside the project's testing rules. A single script with a sidebar radio and manual
  `if/elif` routing reimplements routing by hand for no benefit and loses URL
  addressability.
- **Consequences**: Pages are ordinary functions, so `streamlit.testing.v1.AppTest` can
  drive them with `orchestration` and `reporting` stubbed, and no UI test starts a
  thread or touches the network. This is a solo-developer local tool, so the decision is
  deliberately small: no auth, no theming layer, no custom components, no router
  abstraction.

## Known Limitations

These are properties of the method, not defects to be fixed in code. They must appear
verbatim in the UI's caveat panel (`reporting.interpretive_caveats`).

1. **SteamSpy owner estimates are low-confidence.** Valve restricted the underlying
   profile data in 2018; SteamSpy's owner figures have since been model-based
   approximations. Treat them as a rough ordinal signal and never as ground truth, and
   never present them as a sales count.
2. **The Boxleiter multiplier is an approximation.** The review-to-sales ratio varies by
   genre, price point, release year, regional mix and review-prompt behaviour. The
   per-genre range used here is a documented assumption, not a verified conversion rate.
   Revenue figures are order-of-magnitude indicators.
3. **"Simple" is a proxy for scope, not for effort.** Metadata cannot see art quality,
   game-feel iteration, marketing spend or how many prototypes preceded the release. A
   game with a low `complexity_score` may still have taken a year of polish. Case
   studies must be read as "plausibly small in scope and commercially successful",
   never as "this took two weeks".
4. **No scraping means missing demand signals.** Wishlist counts, historical player
   counts, and price history are unavailable through official endpoints, so "demand" is
   reconstructed from review volume and owner estimates only.
5. **Survivorship bias.** The catalog only contains released, still-listed games.
   Delisted failures and abandoned projects are absent, which inflates the apparent
   success rate of any archetype.
6. **Competition density is measured on past releases.** It describes the market a
   completed game entered, not the market a game started today would launch into.
7. **The coarse filter is a hard boundary.** Anything excluded at stage one cannot
   appear anywhere downstream. Rejection counts per reason are stored per run so the
   boundary stays visible.

## Open Items Requiring User Approval

1. Rate-limit defaults per host; published figures for these endpoints are not
   authoritative, so the initial values are deliberately conservative guesses.
2. Clustering method for `analysis.cluster_tags` is locked in `FORMULATION.md` §6
   (agglomerative over a Jaccard tag-distance matrix, no genre anchor), but the
   catalog-growth adjustment for competition density is still open: normalize by total
   releases in the same window, or by a fitted growth curve.
3. Whether `owners_estimate` feeds any derived score at all, given its low confidence,
   or remains a display-only column.
4. Event throttling granularity in `orchestration.make_event_sink`, which decides how
   fast `run_events` grows on a multi-thousand-app run.
5. Whether `raw_games.payload_json` is zlib-compressed from the start or only past a
   database size threshold.

> All numeric constants in `FORMULATION.md` were locked by the user on 2026-09-20 and
> are no longer open items. The normalization bounds (§4) and the tag distance cut (§6)
> are locked *as a method* — their values are produced empirically by `run 1` through
> `scripts/freeze_empirical_parameters.py` (ADR-012) and pasted back by a human.
