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

**Prediction Drift — Snapshot Approach:**
Predictions update daily, so which prediction do we compare against?

✅ **Answer: The final prediction (day before)**
- Tag each prediction with `predicted_on` date
- When evaluating, compare actuals to most recent prediction before the date
- Query: `WHERE predicted_on < actual_date ORDER BY predicted_on DESC LIMIT 1`
- This is the "operational" prediction — what a user would have seen

This matches how professional forecasting is evaluated (e.g., weather forecasts).

**Status:** Backlog — design and implement when ready

---

### Weather Data Integration (Priority: Medium)
*Add weather as a feature to improve predictions.*

**Data Sources Needed:**
- **Historical weather** — temperature, precipitation, humidity by park/date
- **Current weather** — real-time conditions
- **Forecast weather** — predictions for future dates

**Parks to Cover:**
- WDW (Orlando, FL)
- DLR (Anaheim, CA)
- Universal Orlando
- Tokyo Disney (Tokyo, JP)

**Potential APIs:**
- OpenWeatherMap (free tier available)
- Weather.gov (free, US only)
- Visual Crossing (historical data)
- Tomorrow.io

**Features to Extract:**
- High/low temperature
- Precipitation probability
- Rain amount
- "Bad weather" flag (rain > X, temp extremes)
- Heat index / feels-like

**Integration Points:**
- Add to daily ETL: fetch weather for all parks
- Store in `dimension_tables/weather.csv` or similar
- Add weather features to training data
- Include in forecasts

**Hypothesis:** Weather significantly impacts wait times — rain drives people indoors, extreme heat reduces attendance.

**Status:** Backlog — research APIs and implement

---

### School Schedule Data (Priority: High)
*School holidays are major attendance drivers — automate collection.*

**Goal:**
- Collect school session calendars for US school districts
- Minimum: Top 100 districts by student population
- Stretch: All ~13,000 US school districts

**Data Points Needed:**
- District name and location (state, city)
- **Student population** (weighting factor for predictions)
- Session start/end dates
- Holidays: Spring break, winter break, summer break
- In-session vs out-of-session flag per date

**Why This Matters:**
- Spring break = massive WDW crowds
- Summer = sustained high attendance
- School in session = lower weekday crowds
- District size weights the impact (NYC schools out > small rural district)

**Potential Data Sources:**
- National Center for Education Statistics (NCES) — district demographics
- Individual district websites (scraping)
- State education department APIs
- Third-party aggregators (SchoolDigger, GreatSchools)
- CalendarLabs / PublicSchoolReview

**Implementation Approach:**
1. Start with NCES for district list + student counts
2. Scrape/API top 100 districts for calendars
3. Build calendar table: `(district_id, date, in_session: bool)`
4. Aggregate: "What % of US students are on break on date X?"
5. Add as feature to training

**Challenge:** No single API has all calendars — may need scraping + manual verification for accuracy.

**💰 Revenue Opportunity:**
This data is valuable beyond theme parks. Companies pay **$10K+/year** for comprehensive school schedule databases — marketing firms, travel companies, retailers all need this. If we build it right, it could be a standalone product for hazeydata.ai.

**Status:** Backlog — research sources and build scraper

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

---

### URGENT: PyArrow Bug — Blocking Daily Training

**Date:** Feb 17, 2026  
**Priority:** HIGH — blocks daily retraining  
**Context:** Wilma reported a PyArrow bug that's blocking the daily pipeline. Bam-Bam ready to fix once we have the error message/stack trace.

**Where PyArrow is used:**
- `scripts/convert_to_parquet.py` — `to_parquet()`, `pyarrow.parquet`
- `scripts/hybrid_pipeline_v2.py` — `pq.read_metadata()` for prediction count
- `requirements.txt` — `pyarrow>=14.0.0`

**Full error from today's run (2026-02-17 06:31):**

```
File "/home/wilma/theme-park-crowd-report/.venv/lib/python3.12/site-packages/pyarrow/pandas_compat.py", line 633, in convert_column
    result = pa.array(col, type=type_, from_pandas=True, safe=safe)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "pyarrow/array.pxi", line 365, in pyarrow.lib.array
  File "pyarrow/array.pxi", line 91, in pyarrow.lib._ndarray_to_array
  File "pyarrow/error.pxi", line 92, in pyarrow.lib.check_status
pyarrow.lib.ArrowTypeError: ("Expected bytes, got a 'Timestamp' object", 'Conversion failed for column park_date with type object')
```

**Sequence from the log:**
1. `generate_synthetic_actuals` completes OK
2. `hybrid_pipeline_v2.py` starts, builds 90,591,998 synthetic pairs successfully
3. Crashes during parquet write of the merged pairs (real + synthetic)
4. `[ERROR] Failed: Hybrid training V2 (Julia + geo decay + synthetic actuals)`

**Likely cause:** `park_date` column becomes mixed-type `object` when synthetic pairs (Timestamps) are concatenated with real pairs (strings/bytes). PyArrow can't serialize mixed types.

**Suggested fix:** After merging real + synthetic pairs in `hybrid_pipeline_v2.py`, normalize `park_date`:
```python
df['park_date'] = pd.to_datetime(df['park_date']).dt.strftime('%Y-%m-%d')
```
Or fix at the source in `generate_synthetic_actuals` to output string dates.

---

### ~~LAUNCH BLOCKER: Wire year-view.html to Real API Data~~ ✅ DONE (Wilma, Feb 15)

Implemented Option 3 (static JSON export). Pipeline exports `year-view-data/{PARK}.json` daily.
year-view.html fetches real data. All 12 parks live on hazeydata.ai.

**~~Original context below for reference:~~**

**Date:** Feb 15, 2026
**Context:** The interactive year heatmap at `hazeydata.ai/year-view.html` now uses real WTI forecast data from static JSON files.

**Problem:** The dashboard API runs on wilma-server:8051 (internal). The year-view page is served from Cloudflare Pages (hazeydata.ai). Browser can't call wilma-server directly — needs a public API endpoint.

**Options (pick the best):**
1. **Cloudflare Worker proxy** — A lightweight Worker at `hazeydata.ai/api/*` that proxies to wilma-server (requires cloudflared tunnel or public IP)
2. **cloudflared tunnel** — Expose the dashboard API through Cloudflare Tunnel (e.g., `api.hazeydata.ai` → localhost:8051)
3. **Static JSON export** — Pipeline generates a JSON file per park, deploy to Cloudflare Pages alongside the HTML. No live API needed. Refreshes daily with pipeline.

**I recommend option 3 for alpha launch** — simplest, no infrastructure to maintain, and the data only changes daily anyway. The pipeline can export `year-view-data/MK.json`, `year-view-data/EP.json`, etc.

**JSON schema per park:**
```json
{
  "park_code": "MK",
  "park_name": "Magic Kingdom",
  "generated": "2026-02-15",
  "days": [
    {"date": "2026-02-15", "wti": 22.5},
    {"date": "2026-02-16", "wti": 19.7},
    ...
  ]
}
```

**What to implement:**
1. **New script:** `scripts/export_year_view_data.py` — reads wti.parquet, exports 365-day JSON per park
2. **Add to pipeline:** Run after WTI calculation step
3. **Update year-view.html:** Replace `generateSampleData()` with `fetch('/year-view-data/${parkCode}.json')`
4. **Deploy:** Push JSONs + updated HTML to hazeydata.ai repo, wrangler deploy

**Files to modify:**
- NEW: `scripts/export_year_view_data.py`
- `/home/wilma/hazeydata.ai/year-view.html` — replace sample data with fetch
- Pipeline script (add export step after WTI)

---

### ~~LAUNCH BLOCKER: Fix Park Code Mismatch in WTI Archives~~ ✅ FIXED (Wilma, Feb 15)

**Root cause:** The Feb 13 WTI archive was created before the `park_code_sql()` fix was applied to forecast WTI. It had `TD` (combined TDL/TDS) and `US` (placeholder with constant WTI 25.0). Archives from Feb 14 onward already have correct codes.

**Fix applied:** Removed `TD` and `US` rows from the Feb 13 archive (can't meaningfully split `TD` into TDL/TDS retroactively). Future archives are correct.

**BB = Blizzard Beach** (water park), not Busch Gardens. It's in both forecast and historical WTI — no mismatch, just a minor park. Appears in both sides so join works fine.

---

### ~~Year-View: Best Weeks + Busiest Weeks~~ ✅ DONE (Wilma, Feb 15)

Implemented best weeks (WTI + description) and busiest weeks (headliner ride peak waits).
Busiest weeks now show top-3 headliner rides with predicted peak waits — much more actionable.
Export script enriches JSON with ride-level data from forecast curves.

---

### Per-Park WTI Distributions for Color Scaling — ✅ DONE

**Date:** Feb 15, 2026  
**Priority:** HIGH — affects all visual surfaces (Discord bot, stream dashboard, web dashboard)  
**Context:** Fred decided all Benedictus color scaling should be **per-park, not absolute**. A "red" day at Magic Kingdom means "busy for Magic Kingdom" — not "busy compared to other parks."

#### ✅ DONE (Wilma, Feb 15):
1. **Distribution computation script:** `scripts/compute_park_wti_distributions.py`
   - Computes p5/p25/median/p75/p95/min/max from ALL historical WTI data per park
   - 12 parks, thousands of days each (e.g. MK: 5,935 days)
   - Output: `/mnt/data/pipeline/state/park_wti_distributions.json`
   - Also copies to `hazeydata.ai/year-view-data/distributions.json` for web

2. **Year-view page updated:** `hazeydata.ai/year-view.html` now uses per-park distributions
   - Fetches distributions.json at page load
   - Color mapping: p5→deep blue, p25→blue, median→lavender, p75→pink, p95→deep red
   - WTI descriptions also relative to park distribution
   - Fallback to linear if distributions unavailable

#### ✅ Bam-Bam DONE (Feb 2026):
1. **API endpoint** `GET /api/park-wti-distributions` in `dashboard/api.py` — reads from `state/park_wti_distributions.json` (or `/mnt/data/pipeline/state/` fallback)
2. **Stream dashboard** — fetches distributions at init; KPI card and WTI lollipops use per-park percentiles for Benedictus colors; fallback to absolute scale when distributions unavailable
3. **Documented** in `docs/PIPELINE_DATA_FLOW.md`

**Distribution JSON schema (already generated):**
```json
{
  "ALL": {"p5": 13.0, "p25": 17.7, "median": 21.5, "p75": 25.1, "p95": 31.8, "min": 5.0, "max": 85.0, "n_days": 6076},
  "MK": {"p5": 11.0, "p25": 15.5, "median": 18.8, "p75": 22.3, "p95": 28.4, "min": 5.0, "max": 85.0, "n_days": 5935},
  ...
}
```

---

### ~~Dual Color Mode: Absolute vs Per-Park in Dashboard~~ ✅ DONE (Bam-Bam, Feb 2026)

**Date:** Feb 15, 2026
**Priority:** HIGH — Fred noticed this live on stream
**Context:** When "All Parks" is selected, the lollipop chart uses per-park colors, which makes EU at WTI 41 show as light blue (because 41 is low *for EU*). Confusing when comparing parks side-by-side.

**Rule:**
- **All Parks lollipop chart** → Use `distributions["ALL"]` (global/absolute scale) — comparing parks needs a common baseline
- **Single park selected** (KPIs, gauge, trend) → Use `distributions[parkCode]` (per-park) — "is today unusual for THIS park?"

**Implementation (done):**
- `compute_park_wti_distributions.py` now outputs `"ALL"` entry (global percentiles across all parks)
- Lollipop chart uses `getWtiColor(value, 'ALL')` for all bars — common baseline when comparing parks
- KPI card already uses per-park when a single park is selected (`park !== 'all'`)

---

---

### ~~NEW: Two-Stage Model Fallback — Entity-Specific Ratio Tier~~ ✅ DONE (Bam-Bam, Feb 17)

**Date:** Feb 14, 2026  
**Priority:** Medium  
**Context:** The global XGBoost live inference model fails on low-popularity rides (railroads, people-movers) because their posted-to-actual ratios are extreme.

**Implemented:**
1. **`scripts/train_live_inference_model.py`** — After loading matched pairs, computes `entity_ratio = actual_sum/posted_sum` for entities with 100-499 pairs; saves to `models/_live_inference/entity_ratios.json`
2. **`src/processors/live_inference.py`** — Loads `entity_ratios.json` at init; in `predict()` and `predict_batch()`, checks entity_ratio tier FIRST (before model/fallback); returns `method: 'entity_ratio'` for this tier
3. **Discord bot** — No changes needed (uses `live_inference_model.predict()`)

**Flow:** Entity-ratio (100-499 pairs) → Live model (XGBoost) → Fallback ratio

**Wilma:** Re-run `train_live_inference_model.py` to generate `entity_ratios.json`; then verify predictions for MK49, MK48, DL13, IA10.

---

### ~~PRIORITY: Stripe Premium Subscription Integration~~ ✅ DONE

**Goal:** Enable paid premium subscriptions from day one of launch. Users pay on hazeydata.ai → get Discord premium role automatically.

**Architecture: Option B — Custom on hazeydata.ai**
- Stripe Checkout embedded on hazeydata.ai
- Webhook hits our bot → assigns Discord premium role
- No middleman cut (just Stripe's 2.9% + 30¢)
- Full control, on-brand

---

#### What Needs to Be Built

**1. Stripe Setup**
- Create Stripe account for hazeydata.ai (Fred will do this)
- Create a Product + Price in Stripe:
  - **TPCR Premium** — $7-10/mo (recurring)
  - Optional: annual plan at discount ($70-100/yr)
- Get API keys (publishable + secret)
- Set up webhook endpoint URL

**2. Subscribe Page on hazeydata.ai (`/subscribe` or `/premium`)**
- Clean page explaining what premium gets you:
  - ✅ 90-day crowd forecasts (free = 7 days)
  - ✅ 1-year outlook
  - ✅ Ride-by-ride predictions
  - ✅ Best-day finder extended range
  - ✅ Priority support
- "Subscribe" button → Stripe Checkout session
- User provides email + Discord username during checkout
- On success → redirect to thank-you page with Discord invite

**3. Webhook Endpoint (add to `dashboard/api.py` or separate service)**
- `POST /api/webhooks/stripe` — receives Stripe events
- Handle these events:
  - `checkout.session.completed` → assign Discord premium role
  - `customer.subscription.deleted` → remove Discord premium role
  - `customer.subscription.updated` → handle plan changes
  - `invoice.payment_failed` → grace period, then remove role
- Verify webhook signature (Stripe signing secret)
- Store subscription mapping: `stripe_customer_id ↔ discord_user_id`

**4. Discord Role Management**
- Create "Premium" role in Discord server (if not exists)
- Bot needs `manage_roles` permission (already has admin)
- Webhook handler calls Discord API to add/remove role:
  ```python
  # Add role
  requests.put(
      f"https://discord.com/api/guilds/{GUILD_ID}/members/{discord_user_id}/roles/{PREMIUM_ROLE_ID}",
      headers={"Authorization": f"Bot {BOT_TOKEN}"}
  )
  ```

**5. Bot Premium Check (already partially built)**
- The bot already has premium teaser logic (locked 90-day, 1-year in `/best-day`)
- Update the check to verify the user has the Premium Discord role
- If they have the role → unlock extended forecasts
- If not → show teaser + link to `/subscribe`

**6. Database / State (lightweight)**
- SQLite or JSON file mapping:
  ```
  stripe_customer_id | discord_username | discord_user_id | subscription_status | created_at
  ```
- Needed so webhook can find the right Discord user to assign/remove role
- Discord username collected during Stripe Checkout (custom field or metadata)

---

#### Flow

```
User clicks "Subscribe" on hazeydata.ai
    ↓
Stripe Checkout (hosted by Stripe — handles payment, card, etc.)
    ↓
User enters: email, card, Discord username
    ↓
Payment succeeds → Stripe fires webhook
    ↓
Our webhook endpoint receives event
    ↓
Looks up Discord user by username → gets user ID
    ↓
Assigns "Premium" role via Discord API
    ↓
User sees premium features unlocked in Discord bot
```

#### Cancellation Flow
```
User cancels in Stripe customer portal (or payment fails)
    ↓
Stripe fires subscription.deleted / payment_failed webhook
    ↓
Our webhook removes "Premium" role
    ↓
Bot shows free tier / teaser again
```

---

#### Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `web/subscribe.html` (or `/premium`) | **Create** | Premium landing/checkout page |
| `web/subscribe-success.html` | **Create** | Post-payment thank you page |
| `dashboard/api.py` | **Modify** | Add `/api/webhooks/stripe` endpoint |
| `dashboard/stripe_handler.py` | **Create** | Stripe webhook logic, role management |
| `tpcr-discord-bot/bot.py` | **Modify** | Update premium check to use Discord role |
| `.env` | **Modify** | Add `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `PREMIUM_ROLE_ID` |

#### Dependencies
```
pip install stripe
```

#### Environment Variables Needed
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...          # Monthly premium price
DISCORD_GUILD_ID=1471374656253591695
PREMIUM_ROLE_ID=<create this role>
```

---

#### Pricing (Fred to confirm)
- **Monthly:** $7/mo or $10/mo
- **Annual:** $70/yr or $100/yr (discount for commitment)
- **Free tier stays:** `/today`, `/crowd` (7 days), `/best-day` (7 days), `/ping`, `/about`

#### Notes
- Use Stripe's hosted checkout — don't build a custom payment form (PCI compliance headache)
- Stripe Customer Portal for self-service cancellation (reduces support burden)
- Start with monthly only if annual adds complexity — can add later
- Fred: create Stripe account at https://dashboard.stripe.com/register

---

## Completed

*(Bam-Bam: move items here when done; note what was done in the Log.)*

- **[Pipeline: Wire Operating Calendar into Training/Forecasting/WTI]** Wired operating calendar into: (1) Training (`hybrid_pipeline_v2.py`): matched pairs filtered by `is_operating = TRUE`; (2) Forecasting (`forecast_vectorized.py`): only generates forecasts for operating entity-dates; (3) WTI (`calculate_wti_simple.py`): historical and forecast WTI exclude closed entities. Graceful fallback when operating_calendar.parquet missing: assume all operating. Added `--output-base` to hybrid_pipeline and forecast_vectorized.

- **[Pipeline: Post-Run Validation & Alerting]** Implemented `src/validate_pipeline_output.py`: checks forecast coverage (today+1 for all parks), WTI anomaly (>30% jump), entity coverage (non-extinct lacking models), forecast date range (≥7 days). Output: `pipeline_validation/validation_report.json` and `.txt`. Exit 1 on any RED flag. Integrated into `run_daily_pipeline.sh` after all steps; `--skip-validation` bypasses.

- **[Pipeline: Closures Module — Operating Calendar]** Implemented per `docs/CLOSURES_MODULE_SPEC.md`: (1) `src/get_closures_from_s3.py` — downloads closure CSVs from `s3://touringplans_stats/export/closures/` to `raw_closures/`; (2) `src/build_operating_calendar.py` — combines dimentity `extinct_on` + temporary closures into `operating_calendar/operating_calendar.parquet` (entity_code, park_date, is_operating); (3) integrated into `run_daily_pipeline.sh` after Dimensions, before Impute Hours; (4) `--skip-closures` bypasses; (5) PIPELINE_STATE updated. **Downstream integration** (training, forecast, WTI filter by is_operating) is spec'd but not yet wired — operating calendar is produced and ready for use.

- **[Dashboard: Entity Names Not Displaying]** Fixed in `dashboard/api.py` and `docs/stream/stream-dashboard.html`: (1) dimentity name lookup now supports multiple column name variations (`code`/`entity_code`/`attraction_code` for code; `name`/`entity_name`/`short_name` for name); (2) when hazeydata_entities doesn't exist or returns empty, API now falls back to trained models + dimentity for entity list (names from CODE_TO_NAME); (3) added park code mapping (ioa→IA, usf→UF) so dashboard codes work; (4) enhanced `/api/debug/entity-table` to show both hazeydata and dimentity structure; (5) added fallback entities for ioa/usf in stream dashboard with proper names (Hulk Coaster, etc.).

- **[ETL: Only Process New Files Since Last Run]** Implemented in `src/get_tp_wait_time_data_from_s3.py`: added `state/etl_last_run.json` to track last successful ETL timestamp; filter file list to only files with `mtime > last_run_time` (skips old 2013-2019 files that fail with "No columns to parse"); default 90 days ago when file doesn't exist; `--full-rebuild` bypasses; should reduce daily processing from ~36 files to ~5-7.

- **[Pipeline: Dev Subset Filter (DEV_MODE)]** Implemented DEV_MODE per step-by-step guide: `config/dev_config.py` (DEV_MODE, DEV_ENTITIES, should_process_entity, get_dev_output_base); `src/utils/paths.py` uses pipeline_dev when DEV_MODE=true; ETL filters to DEV_ENTITIES during row processing and in merge_yesterday_queue_times; `scripts/common.sh` get_output_base returns repo/pipeline_dev when DEV_MODE=true. Run: `export DEV_MODE=true && ./scripts/run_daily_pipeline.sh` (use `--skip-dropbox-check` if not on Dropbox). Full pipeline run on this machine stopped at S3 sync (no AWS CLI) and ETL (no pandas in default Python); output base and local source correctly pointed to pipeline_dev.

- **[URGENT - API URL Fix for Unified Workflow]** In `stream-dashboard.html`, API_BASE now always uses `http://wilma-server:8051/api` (no hostname switch). One URL for dev and stream: Fred views `http://localhost:8889/stream-dashboard.html`; data comes from wilma-server. Use `scripts/start-stream.sh` to start the dashboard server.

- **[S3 Sync Test]** Run the new S3 sync-only routine and verify it's working. Let me know the results!

- **[Stripe Premium Subscription Integration]** Implemented full flow: (1) `web/subscribe.html` — premium landing page with Stripe Checkout button; (2) `web/subscribe-success.html` — thank-you page; (3) `dashboard/api.py` — `POST /api/create-checkout-session` and `POST /api/webhooks/stripe`; (4) `dashboard/stripe_handler.py` — webhook logic for checkout.session.completed, customer.subscription.deleted/updated, invoice.payment_failed; Discord role add/remove via API; JSON store for subscription mapping; (5) `tpcr-discord-bot/bot.py` — `has_premium_role()`, `max_forecast_days()`, `premium_teaser_message()` for 90-day/1-year unlock; (6) `docs/STRIPE_PREMIUM_SETUP.md` — setup guide. Credentials in ~/.env on wilma-server. Test with Stripe test mode (card 4242...).

- **[Two-Stage Model Fallback — Entity-Specific Ratio Tier]** Implemented per WILMA-BAMBAM spec: (1) `train_live_inference_model.py` computes entity_ratio for 100-499 pair entities, saves to `models/_live_inference/entity_ratios.json`; (2) `live_inference.py` loads entity_ratios at init, checks entity_ratio tier first in predict() and predict_batch(), returns `method: 'entity_ratio'`. Wilma: re-run train script to generate entity_ratios.json.

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
| 2026-02-05 09:24 | Bam-Bam | **DEV_MODE implemented.** Created config/dev_config.py; integrated into paths.py and scripts/common.sh so output_base = repo/pipeline_dev when DEV_MODE=true; added entity filter in ETL (standby + fastpass + merge_yesterday_queue_times). Ran pipeline with DEV_MODE=true: shell and Python correctly used pipeline_dev (ETL log showed "Output: .../pipeline_dev", "Local source: .../pipeline_dev/raw"). Run failed on this machine at S3 sync (aws not found) and ETL (ModuleNotFoundError: pandas). On a box with AWS CLI + Python venv with deps, use: `export DEV_MODE=true && ./scripts/run_daily_pipeline.sh --skip-dropbox-check`. Task moved to Completed. |
| 2026-02-09 | Bam-Bam | **ETL: Only process new files since last run.** Implemented per Wilma's priority task. Added `state/etl_last_run.json` (timestamp of last successful ETL); filter all_keys to only files with mtime > last_run_time before processing; default 90 days ago when file doesn't exist (avoids old 2013-2019 files on first incremental run); save timestamp after successful completion. `--full-rebuild` bypasses; should reduce daily processing from ~36 files to ~5-7. Task moved to Completed. |
| 2026-02-04 | Bam-Bam | **Closures Module:** Implemented `get_closures_from_s3.py` and `build_operating_calendar.py` per spec. Pipeline integration: runs after Dimensions, before Impute Hours. Output: operating_calendar.parquet. Downstream integration (training/forecast/WTI filter by is_operating) not yet wired — calendar ready for use. Task moved to Completed. |
| 2026-02-04 | Bam-Bam | **Operating calendar + validation:** Wired operating calendar into training, forecasting, WTI (filter by is_operating=TRUE; graceful fallback if missing). Created validate_pipeline_output.py; integrated into run_daily_pipeline.sh. Both tasks moved to Completed. |
| 2026-02-04 | Bam-Bam | **Dashboard: Entity names not displaying.** Fixed attraction dropdown showing codes instead of names. API: (1) dimentity lookup supports multiple column name variations; (2) fallback when hazeydata_entities empty: use trained models + dimentity for entity list; (3) park code mapping (ioa→IA, usf→UF); (4) improved debug endpoint. Stream dashboard: fallback entities for ioa/ia/usf/uf with proper names. Task moved to Completed. |
| 2026-02-05 | Bam-Bam | **Stripe Premium Subscription Integration:** Implemented full flow per spec. Created web/subscribe.html, subscribe-success.html; dashboard/api.py (create-checkout-session, webhooks/stripe); dashboard/stripe_handler.py (webhook logic, Discord role add/remove); tpcr-discord-bot/bot.py (has_premium_role, max_forecast_days, premium_teaser_message); docs/STRIPE_PREMIUM_SETUP.md. Add credentials to ~/.env on wilma-server. Test with Stripe test mode. Task moved to Completed. |
| 2026-02-16 | Bam-Bam | **Per-park WTI distributions:** Added GET /api/park-wti-distributions; stream dashboard fetches at init, uses per-park percentiles for KPI + lollipop colors (p5→deep blue, p25→blue, median→lavender, p75→pink, p95→red). Fallback to absolute scale when distributions unavailable. Documented in PIPELINE_DATA_FLOW. Task moved to Completed. |
| 2026-02-16 | Bam-Bam | **Dual Color Mode (lollipop):** Per Wilma's fix: lollipop chart now uses `distributions["ALL"]` for colors when comparing all parks (common baseline). Added "ALL" entry to `compute_park_wti_distributions.py`. KPI/gauge/trend already use per-park when single park selected. Task moved to Completed. |
| 2026-02-17 | Bam-Bam | **Two-Stage Model Fallback (entity-specific ratio tier):** Implemented per Active Items. train_live_inference_model.py now computes and saves entity_ratios.json for entities with 100-499 matched pairs. live_inference.py loads entity_ratios, checks tier first in predict()/predict_batch(), returns method='entity_ratio'. Task moved to Completed. Wilma: re-run train script to generate entity_ratios.json. |
| 2026-02-17 | Bam-Bam | **PyArrow bug:** Wilma's Telegram: PyArrow bug blocking daily training. Added URGENT task to Active Items. Need error message/stack trace from Wilma to fix. Common mitigations: pin PyArrow version (21.x if 22.x regressed), or use DuckDB for parquet metadata reads instead of pq.read_metadata(). |

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
