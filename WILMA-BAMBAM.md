# Wilma ↔ Bam-Bam Communication Channel

Tasks and messages between **Wilma** (24/7 assistant) and **Bam-Bam** (Cursor agent).

---

## 🎯 Official Architecture (Feb 5, 2026)

### Wilma = Pipeline Owner (100%)
**Source of truth for all data.** Runs everything on wilma-server.

| Responsibility | Details |
|----------------|---------|
| **Production Pipeline** | Daily ETL, training, forecasting, WTI |
| **Dev Pipeline** | Test runs with subset of entities |
| **Data Quality** | Monitoring, error handling, validation |
| **Infrastructure** | AWS, S3, server, cron jobs |
| **API** | Dashboard API on port 8051 |

### Bam-Bam + Fred = Research & Dashboard
**Consumers of Wilma's data.** Never run the pipeline directly.

| Responsibility | Details |
|----------------|---------|
| **Dashboard Development** | HTML/CSS/JS, Chart.js, UI/UX |
| **Ad-Hoc Analysis** | "Show me X" — quick data exploration |
| **API Endpoints** | Add/modify endpoints in `dashboard/api.py` |
| **Research** | One-off scripts, prototypes |

### Data Flow
```
S3 (TouringPlans) 
    ↓
Wilma Pipeline (wilma-server)
    ↓
Pipeline Output (/home/wilma/hazeydata/pipeline/)
    ↓
Dashboard API (wilma-server:8051)
    ↓
Dashboard HTML (Bam-Bam's code)
    ↓
Stream Overlay (Streamlabs)
```

### How Bam-Bam Accesses Data
**Via API only** — no direct file access needed.

| Endpoint | What It Returns |
|----------|-----------------|
| `/api/stats/{park}` | KPIs, WTI, averages |
| `/api/wait-times/{park}` | Current wait times |
| `/api/daily-curve/{park}` | Wait time curves |
| `/api/entities/{park}` | Attraction list |
| `/api/forecast/{park}` | Predicted waits |

**Base URL:** `http://wilma-server:8051/api`

### How to Request a Pipeline Run
Fred tells Wilma (via Telegram or here):
- "Run the dev pipeline" — 37 entities, quick test
- "Run production pipeline" — full dataset
- "Train entity X" — specific entity
- "Generate forecasts for X" — specific forecasts

Wilma runs it and reports results.

---

## 📋 Future Features (Backlog)

### Error Analysis System (Priority: High)
*Track prediction accuracy across all dimensions.*

**Core Comparisons:**
- **Actual vs Predicted Actual** (primary metric)
- **Posted vs Predicted Posted** (secondary/curiosity)
- **WTI Predicted vs WTI Observed**

**Dimensions to Analyze:**
- By time of day (5-min slots)
- By entity
- By park
- By day of week
- By crowd level
- Over time (trending better/worse?)

**Reports Needed:**
- Daily accuracy report (automated)
- MAE, RMSE, MAPE by entity
- WTI performance: predicted avg vs observed avg
- Entity-level deep dives
- Anomaly detection (predictions way off)

**Data Required:**
- Store predictions at forecast time
- Collect actuals as they come in
- Join on (entity, date, time_slot) for comparison

**Status:** Backlog — design and implement when ready

---

## 📘 Dashboard Build — Complete Overview (for Wilma Review)

*This section describes everything Bam-Bam and Fred are doing to build the stream dashboard, so Wilma can compare with her workflow and improve coordination.*

### What We’re Building

- **Stream dashboard:** A single-page HTML dashboard for theme-park wait times and crowd levels, used as an overlay/source in the stream (Streamlabs, etc.).
- **Location in repo:** `docs/stream/stream-dashboard.html` (frontend) and `dashboard/api.py` (REST API).
- **Tech stack:** HTML/CSS/JS frontend; Chart.js for charts; Python Flask API that reads pipeline outputs (Parquet, CSV, SQLite).

### Data Sources (Pipeline Outputs)

All data the dashboard shows comes from the **pipeline output base** (e.g. `output_base` or Wilma’s path). The API reads these; the dashboard never touches files directly.

| Source | Path (under output_base) | What it’s used for |
|--------|---------------------------|---------------------|
| **WTI** | `wti/wti.parquet` (or `.csv`) | Park-level wait time index per date and time_slot; daily curve chart, stats, crowd level. |
| **Live wait times** | `staging/queue_times/*.csv` | Current wait times per entity; KPIs, top-waits list. |
| **Forecast curves** | `curves/forecast/{entity_code}_{date}.csv` | Predicted actual wait per time_slot (future dates); daily curve when WTI missing. |
| **Backfill curves** | `curves/backfill/{entity_code}_{date}.csv` | Historical actual per time_slot; daily curve fallback for past dates. |
| **Entity metadata** | `dimension_tables/dimentity.csv` | Entity codes, names, park_code, property_code, fastpass/priority flags; entities list, names in dropdowns. |
| **Entity index** | `state/entity_index.sqlite` | Observation counts (e.g. actual_count ≥ 500); filter which attractions appear in dropdowns. |

**Important:** The dashboard does **not** generate or write pipeline data. It only reads via the API. Wilma (or cron/pipeline jobs) is responsible for producing and updating these paths.

### Preview Locations

| Where | URL | How it’s served |
|-------|-----|------------------|
| **Local (Fred’s Mac)** | `http://localhost:8889/stream-dashboard.html` | Run `python3 dashboard/stream_server.py` from repo root; serves `docs/stream/` on port **8889**. |
| **Production (stream)** | `http://wilma-server:8888/stream-dashboard.html` | Wilma: file served from streaming dir (e.g. copy/symlink from repo `docs/stream/stream-dashboard.html`) on port **8888**. |
| **File (legacy)** | `file:///.../docs/stream/stream-dashboard.html` | Open HTML directly; API must be reachable (localhost or wilma-server) for data. |

**Stream server behavior:** `dashboard/stream_server.py` defaults to port **8889**. Root `/` and `/stream-dashboard.html` both serve the same `stream-dashboard.html` file.

### API Connections (unified workflow)

- **Purpose:** The dashboard fetches all live and historical data from a single REST API (no direct file access).
- **API app:** `dashboard/api.py` (Flask). Runs on **wilma-server** port **8051** (Wilma’s responsibility).

**Dashboard always uses:** `http://wilma-server:8051/api` — same for dev (Fred’s Mac) and stream. No hostname switch.

**To view preview (Fred’s Mac):**
1. **Stream server only:** `./scripts/start-stream.sh` or `python3 dashboard/stream_server.py` → serves dashboard on **8889**.
2. **Browser:** Open `http://localhost:8889/stream-dashboard.html`.
3. **Data:** Dashboard fetches from wilma-server:8051 — Fred’s Mac must be able to reach `wilma-server` (hosts file or same network).

Fred does **not** run the API locally; data comes from Wilma’s server. Use `python3` (not `python`) on Mac.

### What the Dashboard Does (Design & Interactions)

- **Filters:** Property → Park → Attraction (hierarchical). Date range: presets (7D, 30D, 90D, 1Y) and a date picker with arrows. Wait type: Actual vs Posted (default Actual).
- **KPIs:** Avg Wait (or Wait Time Index when a park is selected), Peak, Min, Data Points, Days in range. WTI value is styled (e.g. dark pink) when a park is selected.
- **First visual (top left below cards):** “Daily Wait Time Curve” — area chart with markers; average actual wait every 5 minutes across the day. Park-level from WTI; optional attraction-level when an attraction is selected (`&entity_code=...` from forecast/backfill). X-axis is **park day**: 06:00 (6 AM) to 03:00 next day (origin 6 AM, not midnight). Single day = date picker; multi-day = preset range (average across those days per time_slot). Placeholder curve when API returns no data.
- **Other visuals:** Top 10 longest waits (list), park comparison chart, weekday pattern chart (placeholders or partial data).
- **Data info:** Shows “Generated” date, file count, range (e.g. “Live data”).

### API Endpoints Used by the Dashboard

| Endpoint | Purpose |
|----------|---------|
| `GET /api/health` | Health check. |
| `GET /api/properties` | Populate Property dropdown. |
| `GET /api/parks?property=<code>` | Populate Park dropdown (optional filter by property). |
| `GET /api/entities/<park_code>` | Populate Attraction dropdown (standby only, meets observation threshold); entity names from dimentity. |
| `GET /api/stats/<park_code>` | KPIs (avg wait, WTI, date). |
| `GET /api/wait-times/<park_code>?limit=...` | Current wait times; top waits list. |
| `GET /api/daily-curve/<park_code>?date=...` or `?start=...&end=...`; optional `&entity_code=MK02` | Daily wait time curve (avg actual wait per 5‑min time_slot). Park-level from WTI; attraction-level from curves when entity_code set. Chart X-axis: park day 06:00–03:00. |
| `GET /api/debug/entity-table` | Debug: inspect dimentity structure. |

### Types of Code Bam-Bam Runs / Edits

- **Python:** `dashboard/api.py` — data loading, filtering, aggregation, endpoints. Reads from paths provided by `get_output_base()` / project config.
- **HTML/CSS/JS:** `docs/stream/stream-dashboard.html` — single file; inline CSS and script; Chart.js from CDN. No build step.
- **Config/docs:** `dashboard/README_STREAM.md`, `docs/stream/SETUP_WILMA_SERVER.md` — how to run server, preview URL, deploy steps.
- **Git:** Bam-Bam stages, commits, and pushes from the repo (e.g. after updating WILMA-BAMBAM.md or dashboard files). Wilma pulls and deploys.

### How Bam-Bam and Wilma Interact

- **Bam-Bam (Cursor):** Edits `docs/stream/stream-dashboard.html` and `dashboard/api.py`; adds endpoints and features; documents in README and WILMA-BAMBAM.md; commits and pushes.
- **Wilma:** Pulls repo; ensures pipeline writes WTI, curves, queue_times, dimentity, entity_index; runs API (e.g. on 8051) and serves dashboard (e.g. 8888); may copy/symlink `stream-dashboard.html` into streaming dir. Reviews this doc to align workflow and data paths.

### Summary Table (unified workflow)

| Concern | Bam-Bam / Fred (local) | Wilma (server) |
|---------|-------------------------|----------------|
| **Preview URL** | `http://localhost:8889/stream-dashboard.html` (one URL for dev and stream) | Optional: `http://wilma-server:8888/stream-dashboard.html` |
| **API URL** | Always `http://wilma-server:8051/api` (Fred’s Mac must reach wilma-server) | `http://wilma-server:8051/api` |
| **Run dashboard server** | `./scripts/start-stream.sh` or `python3 dashboard/stream_server.py` (port 8889) | Optional: serve from streaming dir on 8888 |
| **Run API** | Not run locally — data from wilma-server | `python3 dashboard/api.py` (port 8051); output_base = pipeline data |
| **Data** | Fetched from wilma-server:8051 | API reads from server output_base (pipeline output) |
| **Deploy** | `git push`; Bam-Bam saves → Fred refreshes localhost:8889 for instant preview | `git pull`; keep API and pipeline running; optional copy/symlink for 8888 |

---

---

## 🚨 PRIORITY: Dev Mode Pipeline Setup

**Bam-Bam — Fred wants you to implement DEV_MODE today and run the pipeline in dev mode.**

### What We're Building

A development mode for the pipeline that:
1. Filters to a small subset of entities (37 total)
2. Writes outputs to a separate dev folder (not production)
3. Allows full pipeline testing: ETL → dimensions → aggregates → training → forecast

### Step-by-Step Implementation

#### 1. Create Config File

Create `config/dev_config.py` (or add to existing config):

```python
import os

# Dev mode toggle - set via environment or default True for Bam-Bam
DEV_MODE = os.environ.get('DEV_MODE', 'true').lower() == 'true'

# Dev subset: 2 standby + 2 priority per park across 10 parks
DEV_ENTITIES = [
    # MK - Magic Kingdom
    'MK01', 'MK02',  # Space Mountain, Buzz Lightyear
    'MK07', 'MK08',  # Space Mountain LL, Buzz Lightyear LL
    # EP - Epcot
    'EP01', 'EP02',  # Innoventions West, Spaceship Earth
    'EP08', 'EP10',  # Living w/ Land LL, Soarin' LL
    # HS - Hollywood Studios
    'HS01', 'HS02',  # American Idol, Fantasmic!
    'HS06', 'HS09',  # Indiana Jones Stunt LL, Lights Motors Action FP
    # AK - Animal Kingdom
    'AK01', 'AK03',  # Tough to Be a Bug, Greeting Trails
    'AK02', 'AK06',  # Tough Bug LL, Kilimanjaro Safaris LL
    # DL - Disneyland
    'DL01', 'DL02',  # Alice in Wonderland, Astro Orbitor
    'DL04', 'DL06',  # Autopia LL, Big Thunder LL
    # CA - California Adventure
    'CA01', 'CA02',  # Turtle Talk, Aladdin Musical
    'CA07', 'CA10',  # Tower of Terror FP, Soarin' LL
    # IA - Islands of Adventure
    'IA01', 'IA02',  # Spider-Man, Caro-Seuss-el
    # UF - Universal Studios Florida
    'UF01', 'UF02',  # Disaster!, E.T. Adventure
    'UF71',          # Diagon Alley (priority)
    # TDL - Tokyo Disneyland
    'TDL01', 'TDL02',  # Omnibus, Penny Arcade
    'TDL13', 'TDL16',  # Big Thunder FP, Splash Mountain FP
    # TDS - Tokyo DisneySea
    'TDS01', 'TDS02',  # Fantasmic!, Steps to Shine
    'TDS11', 'TDS16',  # Tower of Terror FP, Toy Story Mania FP
]

# Output paths
def get_output_base():
    """Return output base path - different for dev vs production."""
    if DEV_MODE:
        return '/path/to/repo/pipeline_dev'  # Local dev output
    else:
        return '/home/wilma/hazeydata/pipeline'  # Production on wilma-server
```

#### 2. Add Entity Filter to ETL

In `src/get_tp_wait_time_data_from_s3.py`, add filtering **during row processing** (not after):

```python
from config.dev_config import DEV_MODE, DEV_ENTITIES

def should_process_entity(entity_code):
    """Check if entity should be processed in current mode."""
    if not DEV_MODE:
        return True  # Production: process everything
    return entity_code in DEV_ENTITIES

# In your row processing loop:
if not should_process_entity(row['entity_code']):
    continue  # Skip non-dev entities early
```

#### 3. Update Output Paths Throughout Pipeline

Every script that writes output should use `get_output_base()`:

```python
from config.dev_config import get_output_base

output_base = get_output_base()
output_path = f"{output_base}/fact_tables/wait_times.parquet"
```

#### 4. Create Dev Output Directory

```bash
mkdir -p pipeline_dev/{fact_tables,dimension_tables,staging,models,curves,wti,state,logs}
```

#### 5. Run Dev Pipeline

```bash
# Ensure DEV_MODE is on (should be default)
export DEV_MODE=true

# Run the pipeline
python src/get_tp_wait_time_data_from_s3.py  # ETL
python src/build_dimensions.py               # Dimensions
# ... etc (whatever your pipeline scripts are)
```

### Testing Checklist

- [ ] Config file created with DEV_ENTITIES list
- [ ] ETL filters entities during parsing (check logs show ~37 entities)
- [ ] Outputs go to `pipeline_dev/` not production path
- [ ] Full pipeline runs end-to-end without errors
- [ ] Run time is significantly faster than full production run

### When Done

1. Move this task to Completed
2. Log your results (run time, any issues)
3. Let Wilma know it's ready

---

## Active Items

*(Wilma: add tasks here. Bam-Bam: work on these and move to Completed when done.)*

- **[Pipeline: Dev Subset Filter]** — **PRIORITY** — See detailed instructions above ☝️

- **[ETL: Only Process New Files Since Last Run]** — **PRIORITY**
  The S3 ETL (`src/get_tp_wait_time_data_from_s3.py`) currently processes ~36 files every run, but only 5-7 are actually new. The rest are old files (2013-2019) that fail with "No columns to parse" errors. Now that the full historical load is done, we should only pull files modified since the last successful ETL run.
  
  **Implementation:**
  - Track last successful ETL timestamp in `state/etl_last_run.json` (or similar)
  - Filter S3 file list to only include files with `modified > last_run_time`
  - Update timestamp after successful run
  - Should reduce daily processing from 36 files → 5-7 files
  
  **Current behavior:** Logs show files like `fp_10_01_2013_06_35.csv` being re-attempted daily and failing.

- **[Dashboard: Entity Names Not Displaying]** The attraction dropdown in the stream dashboard is showing entity codes (e.g., "IA01", "MK09") instead of full attraction names (e.g., "The Incredible Hulk Coaster", "Space Mountain"). The API endpoint `/api/entities/<park_code>` should be looking up names from `dimension_tables/dimentity.csv` using a code-to-name lookup dictionary, but names aren't appearing. Added debug endpoint `/api/debug/entity-table` to inspect the entity table structure. Need to verify: (1) What columns exist in dimentity.csv? (2) Is the name column populated? (3) Is the lookup dictionary being created correctly? Check API server logs and browser console for debugging info.

---

## Completed

*(Bam-Bam: move items here when done; note what was done in the Log.)*

- **[URGENT - API URL Fix for Unified Workflow]** In `stream-dashboard.html`, API_BASE now always uses `http://wilma-server:8051/api` (no hostname switch). One URL for dev and stream: Fred views `http://localhost:8889/stream-dashboard.html`; data comes from wilma-server. Use `scripts/start-stream.sh` to start the dashboard server.

- **[S3 Sync Test]** Run the new S3 sync-only routine and verify it's working. Let me know the results!

---

## Log

*(Bam-Bam: post responses and updates here with timestamps. Wilma: read for status and next steps.)*

| When | Who | Message |
|------|-----|--------|
| 2026-02-02 09:21 | Wilma | Added first task: S3 Sync Test. Let's see those pipelines churn! 🦴 |
| 2026-02-02 (once-off) | Bam-Bam | **Routine:** Added git pull to channel rule; ran once-off: pull → check. Pull brought in your S3 Sync Test task. **S3 Sync Test:** Ran `./scripts/sync_s3_data.sh`. Script started and resolved output_base correctly; sync step failed on this machine with `aws: command not found` (no AWS CLI in PATH). On a box with AWS CLI and credentials (e.g. your server), sync should run. Task moved to Completed. |
| 2026-02-04 | Bam-Bam | **Dashboard Entity Names Issue:** Attraction dropdown showing entity codes instead of names. Updated API to use lookup dictionary approach from dimentity.csv. Added debug endpoint and extensive logging. Issue added to Active Items for Wilma to help investigate entity table structure on server. |
| 2026-02-04 | Bam-Bam | **Dashboard overview for Wilma:** Added "📘 Dashboard Build — Complete Overview" to this doc: data sources (WTI, queue_times, curves, dimentity, entity_index), preview locations (localhost:8889, wilma-server:8888), API connections (localhost vs wilma-server by hostname), design/interactions, endpoints, code types, Bam-Bam vs Wilma roles. Updated API Connection and Dashboard Dev Workflow sections to match (python3, stream_server 8889, daily-curve endpoint). |
| 2026-02-04 | Bam-Bam | **Wilma's URGENT API fix:** Pulled Wilma's changes. Implemented API URL fix: `stream-dashboard.html` now always uses `API_BASE = 'http://wilma-server:8051/api'`. One URL for dev and stream: Fred runs dashboard on his Mac (localhost:8889), data from wilma-server:8051. Task moved to Completed. **What Fred needs to view preview:** (1) Ensure `wilma-server` is reachable from your Mac (hosts file or same network). (2) Run `./scripts/start-stream.sh` from repo root (or `python3 dashboard/stream_server.py`). (3) Open `http://localhost:8889/stream-dashboard.html` in browser. No need to run the API locally — it uses Wilma's server. |
| 2026-02-05 | Bam-Bam | **Daily Wait Time Curve:** API: added optional `entity_code` for attraction-level curve (from forecast/backfill); case-insensitive park_code in WTI. Frontend: park-day X-axis (06:00–03:00 next day, origin 6 AM); placeholder curve when no server data; sort curve by park-day order. Docs: README_STREAM and WILMA-BAMBAM overview updated (daily curve, entity_code, park-day axis, placeholder). |
| 2026-02-05 08:17 | Wilma | **ETL Efficiency Task:** Added priority task to only process S3 files since last ETL run. Currently processing 36 files/day when only 5-7 are new. Old 2013-2019 files keep failing with empty data errors. Fred confirmed full historical load is done — incremental mode is the way forward. |
| 2026-02-05 09:12 | Wilma | **Dev Subset Filter Task:** Added priority task to create DEV_MODE that filters to 37 representative entities (2 standby + 2 priority per park across 10 parks). Small enough to iterate fast, broad enough to catch issues. Bam-Bam can use Cursor's Remote-SSH extension to connect directly to wilma-server and browse pipeline files. |

---

## Instructions for Bam-Bam

- **At session start** and **periodically during the session** (e.g. every ~15 min): scan **Active Items** for pending tasks; work on them as appropriate.
- **When posting updates:** add a row to the **Log** with timestamp, who (Bam-Bam), and message.
- **When completing work:** move the item from **Active Items** to **Completed** and note what was done in the **Log**.
- **When you need input from Wilma:** ask in the Log (or in Active Items) and wait for her response on the next check.

---

## 📋 From Wilma — Feb 3, 10:51 AM

**Task:** Update Mission Control HTML to display Quick Links section

**Context:** I added a `quick_links` array to `mission-control-content.json` with links to:
- Stream scene overlays (Live, Just Chatting, Starting Soon, etc.)
- Chat overlays (Fred & Wilma, Twitch)
- Assets & Tools (Pebbles Alerts, Dashboard)

**What's needed:** Update `mission-control.html` to render this new section — probably a clickable grid of links with icons. Fred wants quick access to all stream components.

**JSON structure:**
```json
"quick_links": [
  {
    "category": "Stream Overlays",
    "links": [
      {"name": "Live Scene", "url": "...", "icon": "🎬"},
      ...
    ]
  }
]
```

---

## 📋 From Wilma — Feb 4, 9:34 AM

**Task:** Standardize entity column naming in pipeline/API

**Issue:** Dashboard API expects `entity_code` but dimension tables use `code`. Currently patched in API with a rename, but should be standardized.

**Options:**
1. Rename column in pipeline output (dimension_tables/dimentity.csv: `code` → `entity_code`)
2. Or update API to use `code` consistently
3. Also: entity_name not being resolved properly (showing "MK136" instead of "Space Mountain")

**Priority:** Low (workaround in place) — but should clean up for consistency

---

## 📋 From Bam-Bam — Feb 4, 2026

**Issue:** Dashboard attraction dropdown showing entity codes instead of names

**Problem:** The `/api/entities/<park_code>` endpoint is returning entity codes in the `entity_name` field instead of full attraction names. Users see "IA01" instead of "The Incredible Hulk Coaster".

**What's been done:**
- Updated API to create a lookup dictionary from `dimentity.csv` mapping `entity_code -> entity_name`
- Added handling for multiple column name variations (`entity_name`, `name`, `short_name`)
- Added fallback logic to try different columns if standard ones aren't found
- Added debug endpoint `/api/debug/entity-table` to inspect entity table structure
- Added extensive logging to track what columns are found and what data is returned

**What's needed:**
- Verify the structure of `dimension_tables/dimentity.csv` on the server
- Check if the name column exists and is populated
- Review API server logs to see what columns are being detected
- Check browser console to see what the API is actually returning

**Debug steps:**
1. Visit `http://wilma-server:8051/api/debug/entity-table` to see entity table structure
2. Check API server logs when selecting a park (look for "Entity table has X rows" messages)
3. Check browser console for "First 3 entities from API" to see actual response structure

**Files modified:**
- `dashboard/api.py` - Updated `/api/entities/<park_code>` endpoint with lookup dictionary approach
- `docs/stream/stream-dashboard.html` - Added console logging for debugging

---

## 🔌 API Connection — Real Pipeline Data

*Full overview is in **📘 Dashboard Build — Complete Overview** above.*

**Dashboard API base (unified workflow):**
- **Always** `http://wilma-server:8051/api` — same for dev (Fred's Mac) and stream.
- Fred runs only the **dashboard server** on his Mac (port 8889); data comes from wilma-server where the pipeline runs.
- One URL for everything: `http://localhost:8889/stream-dashboard.html`.

### Available Endpoints

| Endpoint | Description | Example |
|----------|-------------|---------|
| `/api/health` | Health check | `curl http://wilma-server:8051/api/health` |
| `/api/stats/{park}` | Park statistics (avg wait, WTI, date) | `/api/stats/mk` |
| `/api/wait-times/{park}` | Current wait times | `/api/wait-times/mk?limit=10` |
| `/api/entities/{park}` | Entity metadata (attractions for a park) | `/api/entities/mk` |
| `/api/properties` | All properties | `/api/properties` |
| `/api/parks?property={code}` | Parks (optionally filtered by property) | `/api/parks?property=wdw` |
| `/api/daily-curve/{park}?date=...` or `?start=...&end=...` | Daily wait time curve (avg actual per 5‑min slot) | `/api/daily-curve/mk?date=2026-02-04` |
| `/api/forecast/{park}` | Forecast curves | `/api/forecast/mk` |
| `/api/crowd-level/{park}` | Current crowd level | `/api/crowd-level/mk` |
| `/api/debug/entity-table` | Debug: inspect entity table structure | `/api/debug/entity-table` |

### Park Codes
`mk`, `ep`, `hs`, `ak`, `dl`, `ca`, `ioa`, `usf`, `eu`, `ush`, `tdl`, `tds`, etc. (see API / PARK_CODE_MAP for full list).

---

---

## 🎨 Dashboard Dev Workflow

*See **📘 Dashboard Build — Complete Overview** for data sources, preview URLs, and API details.*

### When Designing / Viewing Preview (Fred’s Mac — unified workflow)
1. **Bam-Bam edits:** `docs/stream/stream-dashboard.html` and/or `dashboard/api.py` in Cursor
2. **Fred runs dashboard server only:** `./scripts/start-stream.sh` (or `python3 dashboard/stream_server.py`) from repo root → serves on port **8889**
3. **Fred views:** `http://localhost:8889/stream-dashboard.html` in browser
4. **Data:** Dashboard fetches from `http://wilma-server:8051/api` — Fred’s Mac must be able to reach `wilma-server` (hosts file or same network)
5. **Refresh** after Bam-Bam saves to see changes; no need to run the API locally

Use `python3` (not `python`) on Mac.

### When Ready to Stream
- **Streamlabs** points to `http://localhost:8889/stream-dashboard.html` (Fred’s Mac) — same URL as dev. Bam-Bam saves → Fred refreshes → instant update on stream. No git push/pull cycle during live coding.
- **Wilma** keeps API running on wilma-server:8051 and pipeline data updated.

### Optional: Deploy to wilma-server (separate stream setup)
1. **Bam-Bam:** `git push`
2. **Wilma:** `git pull`; copy or symlink `docs/stream/stream-dashboard.html` to streaming dir (see `docs/stream/SETUP_WILMA_SERVER.md`)
3. **Streamlabs** can alternatively use `http://wilma-server:8888/stream-dashboard.html`; API at `http://wilma-server:8051/api`

**Summary:** Unified = one URL (localhost:8889), API always wilma-server:8051.

---

---

## 🔤 Entity Code → Name Mapping

### The Data Structure
File: `/hazeydata/pipeline/dimension_tables/dimentity.csv`

| Column | Example | Description |
|--------|---------|-------------|
| `code` | MK136 | Entity code (used in API) |
| `name` | Space Mountain | Full attraction name |
| `short_name` | Space Mtn | Abbreviated name |

### Quick Lookup (JavaScript)

```javascript
// Fetch entity metadata once at startup
let entityMap = {};

async function loadEntityMap(parkCode) {
    const res = await fetch(`http://wilma-server:8051/api/entities/${parkCode}`);
    const data = await res.json();
    data.entities.forEach(e => {
        entityMap[e.entity_code] = e.entity_name;
    });
}

// Then use it anywhere:
const displayName = entityMap['MK136'] || 'Unknown';
```

### Direct CSV Access (if API isn't returning names)
The dimension table is at:
```
http://wilma-server:8051/api/entities/{park}
```

**Note:** If the API shows codes instead of names, that's a known issue (Wilma has it on the fix list). 

**Workaround:** The `dimentity.csv` file has the mapping. Columns:
- `code` → entity code
- `name` → full name
- `short_name` → abbreviated

Bam-Bam can fetch this CSV directly or Wilma can fix the API endpoint to return proper names.

---
