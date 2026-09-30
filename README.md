# Steam Analyst

Steam Analyst scans Steam's game catalog through official, documented APIs
(Steam Web API `appdetails`, Steam Reviews API, SteamSpy's bulk endpoint) to
identify low-complexity game archetypes — buildable by a solo developer or a
small team in a few weeks to months — that have a track record of commercial
success on Steam.

**Research question:** which low-complexity game archetypes have proven
commercially successful on Steam, and where do current opportunity gaps
(high demand, low competition) exist?

## How it works

Each analysis is a manually-triggered, single-process **run**:

1. **Acquisition** — a two-phase funnel. A coarse filter runs over SteamSpy's
   bulk catalog endpoint first (cheap, ~150k apps), narrowing the field to a
   few thousand candidates. Only those candidates get per-app calls
   (`appdetails`, reviews, SteamSpy per-app tags), keeping API usage an order
   of magnitude lower than fetching detail for the whole catalog.
2. **Enrichment** — normalizes raw API payloads into feature rows and
   extracts tags, independent of acquisition (stages only communicate through
   the database, never by importing each other).
3. **Analysis** — scores complexity, estimates historical sales (Boxleiter
   method), clusters by tag similarity, and computes an opportunity score.

Every run is persisted permanently to a local SQLite database
(`data/analyses.db`), so results are inspectable later, not just in the
moment the run finished. There is no scheduler — runs are triggered manually
from the Streamlit UI (see ADR-006 in `.claude/context/ARCHITECTURE.md`).

Only official, documented APIs are used. Scraping Steam Store HTML, SteamDB,
or SteamCharts is explicitly out of scope (see ADR-003).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

pip install -r requirements.txt

copy .env.example .env        # Windows
# cp .env.example .env        # Linux/macOS
```

`.env` variables are all optional with sane defaults — see
`src/steam_analyst/config/settings.py` for the full list.

## Running

Start the Streamlit UI and trigger a run from there:

```bash
streamlit run app.py
```

Run the test suite:

```bash
pytest
```

## Project layout

| Path | Role |
|---|---|
| `src/steam_analyst/acquisition/` | API clients, coarse filter, detail-fetch funnel |
| `src/steam_analyst/enrichment/` | Raw payload parsing, feature normalization, tagging |
| `src/steam_analyst/analysis/` | Complexity/opportunity scoring, clustering, trends |
| `src/steam_analyst/orchestration/` | Run lifecycle, stage sequencing, cancellation |
| `src/steam_analyst/reporting/` | Presentation-layer views built from stored run data |
| `src/steam_analyst/ui/` | Streamlit app |
| `src/steam_analyst/storage/` | SQLite schema and access layer |
| `src/steam_analyst/config/` | Settings, locked parameters (`config/parameters.toml`) |
| `.claude/context/FORMULATION.md` | Canonical formulas, symbols, and locked parameter values |
| `.claude/context/ARCHITECTURE.md` | Architecture decisions (ADR log), data model, known limitations |
| `scripts/` | One-off maintenance scripts (parameter freezing/consistency checks) |

## Known limitations

- SteamSpy's owner estimates have been low-reliability since 2018 policy
  changes; they are used only as a coarse ranking signal, never presented as
  exact sales figures.
- Several `appdetails` fields (`size_bytes`, `early_access_days`, etc.) are
  not reliably present in Steam's public API response and fall back to an
  imputed midpoint when missing.

See `.claude/context/ARCHITECTURE.md` for the full list and rationale.
