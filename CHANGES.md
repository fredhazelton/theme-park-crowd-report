# Change Log

This document tracks significant changes to the Theme Park Wait Time Data Pipeline.

## Recent Changes

### WTI Status Update (2026-02-07)

**Status** (`wti/wti.csv`):
- **34,905 total rows** — one WTI value per park per day
- **Historical**: 34,177 rows (2009-03-02 → 2026-02-06)
  - `historical_actual`: 22,244 rows
  - `historical_posted`: 11,930 rows
- **Future**: 728 rows (AK only, 2026-02-07 → 2028-02-04)

**Coverage by Park**:
| Park | Historical | Future | Notes |
|------|------------|--------|-------|
| AK | 5,859 ✅ | 728 ✅ | Complete |
| CA | 5,284 | 0 ❌ | Needs forecast |
| DL | 5,366 | 0 ❌ | Needs forecast |
| EP | 5,880 | 0 ❌ | Needs forecast |
| HS | 5,875 | 0 ❌ | Needs forecast |
| MK | 5,913 | 0 ❌ | Needs forecast |

**Gap**: Forecast curves only generated for AK. Other parks need forecast generation before WTI can include future dates.

---

### Julia Hybrid Pipeline (2026-02-07)

**Added** (`scripts/hybrid_pipeline.py`):
- New hybrid training pipeline using best tool for each step:
  - **Python/DuckDB** for matched pairs generation (vectorized SQL)
  - **Julia/XGBoost.jl** for model training (2-3x faster than Python)
  - **Python** for scoring (API integration)
- Command line options: `--skip-pairs`, `--skip-scoring`, `--score-hours N`

**Added** (`julia-ml/`):
- `train_only.jl` - Julia XGBoost training script
- `Project.toml` - Julia package dependencies

**Changed** (`scripts/run_daily_pipeline.sh`):
- Training step now uses `hybrid_pipeline.py --skip-scoring` instead of `train_batch_entities.py`
- Training time reduced from ~10 minutes to ~67 seconds

**Added** (`docs/HYBRID_PIPELINE.md`):
- Full documentation for hybrid pipeline architecture and usage

**Updated** (`docs/PIPELINE_TIMING_AND_PARALLELIZATION.md`):
- Reflects current hybrid architecture and performance

**Updated** (`docs/TRAINING_OPTIMIZATION.md`):
- Marked as completed with link to new hybrid docs

**Performance:**
| Metric | Before | After |
|--------|--------|-------|
| Training time | ~10 min (Python) | ~67s (Julia) |
| Models trained | 141 | 141 |
| Avg MAE | 6.79 min | 6.78 min |

**Why**: Julia XGBoost is significantly faster than Python for training. Combined with DuckDB for data prep, total training time dropped from 75+ minutes (original) to ~2.5 minutes.

---

### Stream dashboard: Daily curve real data, fallbacks, and API

**Changed** (`docs/stream/stream-dashboard.html`):
- **Daily Wait Time Curve**: When an attraction and single date are selected, the dashboard fetches `/api/actual-points/<park>?date=...&entity_code=...` and overlays raw ACTUAL observations (dark pink points). If the API returns no curve but has actual points, the main line is now built from those points (no placeholder) so real data is visible.
- **Property / Attraction fallbacks**: When the API returns empty properties or empty entities (e.g. local API without pipeline data), the dashboard uses hardcoded fallbacks so Property and Attraction dropdowns always have options (e.g. Magic Kingdom → Space Mountain MK01, etc.).
- **Example hint**: Under the curve subtitle, the dashboard fetches `/api/sample-actual-points` and shows “Example with data: Park X, Attraction Y, Date Z” when the API has fact data.
- **Chart styling**: Wait Time Index (lollipop) title reverted to cyan; lollipop sticks and X-axis white at 35% opacity; chart titles 22px; subtitles 12px; Y-axis labels hidden on lollipop chart; panel width/auto-width for lollipop improved (3fr max).
- **Fake curve flag**: `USE_FAKE_CURVE_DATA` (default false) allows one-off use of hardcoded curve + actual points for visual tinkering.
- **API base**: Commented option to use `http://localhost:8051/api` when running the API locally.

**Changed** (`dashboard/api.py`):
- **Actual points**: `GET /api/actual-points/<park>?date=YYYY-MM-DD&entity_code=MK01` returns raw ACTUAL observations from `fact_tables/clean` for that entity and date (`points: [{ time_slot, wait_time_minutes }]`).
- **Sample**: `GET /api/sample-actual-points` returns one `{ park_code, entity_code, date }` that has ACTUAL data for “try this combo” guidance.
- **Placeholder mode**: `PLACEHOLDER_DATA=true` env serves synthetic data from `dashboard/placeholder_data.py` for design testing; real data paths unchanged.

**Added** (`dashboard/placeholder_data.py`):
- Synthetic parks, properties, entities, wait times, stats, daily curve, crowd level, forecast, tip for ad hoc visual testing when `PLACEHOLDER_DATA=true`.

**Changed** (`dashboard/README_STREAM.md`):
- “Seeing real data” section: how to point dashboard at local API, use `/api/sample-actual-points` for an example, and select park/attraction/date. Documented `actual-points` and `sample-actual-points` endpoints.

**Changed** (`requirements.txt`):
- Added `flask>=3.0.0` and `flask-cors>=4.0.0` for the dashboard API.

**Why**: Stream dashboard can show real daily curve and actual observed points when pipeline data exists; works with local API and fallbacks when data is missing; optional placeholder data for UI testing.

### Stream dashboard: Wait by Park chart and layout

**Changed** (`docs/stream/stream-dashboard.html`):
- **Wait by Park chart**: Lollipop-style chart (dotted stems, value inside dot, park name stacked above). Sorted by value low→high. Park list filtered by Property slicer; when Property = Disney World (wdw), only four WDW parks shown. Fallback when API unreachable is property-aware (wdw → 4 parks, dlr → 2, etc.).
- **Panel width**: Wait by Park panel width matches Daily Wait Time Curve (2fr) when all parks shown; scales down with park count (min 0.5fr). When 4 or fewer parks, minimum width 1.15fr so 4-park view isn’t cramped.
- **Bar spacing**: `barPercentage` varies by park count: more gap when fewer parks (e.g. 4), minimum gap when 12 parks.
- **Labels**: Park names wrapped (one word per line), centered above dot; value in dot; larger fonts (14px park name, 16px bold value) for stream visibility. Top padding and gap tuned so labels aren’t clipped.
- **Clear all filters**: Button resets Property, Park, Attraction, date to today, Wait type to Actual.
- **Property change**: Changing Property refreshes Wait by Park (filtered parks) and panel width.

**Why**: Stream-ready overlay with readable Wait by Park; responsive to property selection and park count.

### Queue-Times scraper fixes (hours filter, robustness)

**Changed**:
- **dimparkhours column names**: The fetcher now looks for `opening_time`, `closing_time`, and `opening_time_with_emh` (in addition to `open`/`close`/`emh_open` etc.) when filtering parks by in-window hours. This matches the raw S3 dimparkhours layout and removes the “missing required columns” fallback when those columns exist.
- **`pd.Timestamp` / tz fix**: Replaced `pd.Timestamp(fetch_time_utc, tz="UTC")` with `pd.Timestamp(fetch_time_utc)` in the stale-`observed_at` audit. Pandas raises when the input is already timezone-aware and `tz=` is passed; the fetcher always passes UTC-aware datetimes.
- **Robustness**: JSON decode errors from the API are caught and logged instead of crashing. Per-park processing is wrapped in try/except so one bad park does not stop the run. The interval loop catches run failures, logs them, and continues (sleep then retry).
- **Proxy**: The fetcher always uses `proxies={}` so it runs in scheduled tasks, normal terminals, and environments with broken or missing proxy config.
- **Docs**: `scripts/README.md` documents the 5‑minute loop, proxy behaviour, and troubleshooting (lock file). Main `README` queue-times section updated to mention the 5‑min loop default.

**Why**: Restore reliable scraping after regressions; align with dimparkhours schema; improve resilience to API glitches and per-park errors.

### Metatable (dimMetatable) and Season (dimSeason)

**Added**:
- `src/get_metatable_from_s3.py` — Fetches `current_metatable.csv` from `s3://touringplans_stats/export/metatable/`, writes `dimension_tables/dimmetatable.csv`. Park-day metadata (extra magic hours, parades, closures, etc.). No transformation. Adapted from legacy Julia `run_dimMetatable.jl`. Logs: `logs/get_metatable_*.log`.
- `src/build_dimseason.py` — Reads `dimension_tables/dimdategroupid.csv`, assigns `season` and `season_year` from `date_group_id` patterns (CHRISTMAS_PEAK, holiday carry, Presidents+Mardi Gras combined window, seasonal buckets). Writes `dimension_tables/dimseason.csv`. Depends on dimdategroupid. Adapted from legacy Julia `run_dimSeason.jl`; always overwrites. Logs: `logs/build_dimseason_*.log`.
- Both added to `scripts/run_dimension_fetches.ps1` (6 AM job): metatable with S3 fetches, dimseason after dimdategroupid.

**Why**: Metatable for park-day metadata; season/season_year for modeling and cohort analysis.

### Date group ID (dimDateGroupID) build

**Added**:
- `src/build_dimdategroupid.py` — Builds `dimension_tables/dimdategroupid.csv` locally (no S3). Combines date spine (2005-01-01 through today + 2 years), holiday codes/names, and `date_group_id`. "Today" = Eastern park_day (6 AM rule). Adapted from legacy Julia `run_dimDate.jl`, `run_dimHolidays.jl`, `run_dimDateGroupID.jl`; always overwrites.
- Logs: `logs/build_dimdategroupid_*.log`
- Added to `scripts/run_dimension_fetches.ps1` (6 AM job).

**Why**: Single dimension table for date context, holidays, and date_group_id for modeling and cohort analysis.

### Schedule dimension table fetches (6 AM Eastern)

**Added**:
- **ThemeParkDimensionFetch_6am** — Daily at 6:00 AM Eastern. Runs `scripts/run_dimension_fetches.ps1`, which invokes entity, park-hours, events, metatable fetches from S3, then `build_dimdategroupid.py`, `build_dimseason.py`, in sequence.
- `scripts/run_dimension_fetches.ps1` — Runs `get_entity_table_from_s3.py`, `get_park_hours_from_s3.py`, `get_events_from_s3.py`, `get_metatable_from_s3.py`, `build_dimdategroupid.py`, `build_dimseason.py`; writes to **output/** under project root (`output/dimension_tables/`, `output/logs/`); exits on first failure.
- `scripts/register_scheduled_tasks.ps1` updated to register the 6 AM task.

**Why**: Keep dimension tables (dimentity, dimparkhours, dimeventdays, dimevents, dimmetatable, dimdategroupid, dimseason) updated daily without manual runs.

**Use output/dimension_tables**: Removed repo-root `dimension_tables/`; dimension fetch now uses `output/dimension_tables/` via `--output-base` (project `output/`). Aligns with existing `output/` layout.

### Events from S3

**Added**:
- `src/get_events_from_s3.py` — Fetches events dimension data from S3 and builds two dimension tables
- Source: `s3://touringplans_stats/export/events/` — `current_event_days.csv` (events by day, event codes), `current_events.csv` (event lookup)
- Writes `dimension_tables/dimeventdays.csv` and `dimension_tables/dimevents.csv` under output base
- Other export/events/ files (event_days_*.csv, events_*.csv) ignored; same S3/boto3 pattern as entity/park-hours
- Logs: `logs/get_events_*.log`

**Why**: Auxiliary events data for modeling, WTI, and joining with wait-time fact tables.

### Park hours from S3

**Added**:
- `src/get_park_hours_from_s3.py` — Fetches park-hours dimension data from S3 and builds `dimension_tables/dimparkhours.csv`
- Source: `s3://touringplans_stats/export/park_hours/` — files `dlr_park_hours.csv`, `tdr_park_hours.csv`, `uor_park_hours.csv`, `ush_park_hours.csv`, `wdw_park_hours.csv`
- Combines with union of columns; same S3 bucket and boto3 retry config as entity table
- Logs: `logs/get_park_hours_*.log`

**Why**: Auxiliary park-hours data for modeling, WTI, and joining with wait-time fact tables.

### Entity table from S3

**Added**:
- `src/get_entity_table_from_s3.py` — Fetches entity dimension data from S3 and builds `dimension_tables/dimentity.csv`
- Source: `s3://touringplans_stats/export/entities/` — files `current_dlr_entities.csv`, `current_tdr_entities.csv`, `current_uor_entities.csv`, `current_ush_entities.csv`, `current_wdw_entities.csv`
- Combines with union of columns; normalizes `land` column (add if missing, consistent type)
- Same S3 bucket and boto3 retry config as wait-time ETL; `--output-base` to match
- Logs: `logs/get_entity_table_*.log`

**Why**: Auxiliary entity data needed for modeling, WTI, and joining with wait-time fact tables.

**Entity table wrap-up**: `get_entity_table_from_s3.py` now includes extensive module docstring (PURPOSE, S3 SOURCE, OUTPUT, USAGE), section headers, step comments (STEP 1–4 in main), and inline descriptions. README, logs/README, and output docs updated.

### Wait Time DB Report

**Added**:
- `scripts/report_wait_time_db.py` — Easily consumable Markdown report of what's in the wait time fact table
- Summary: date range, parks, park-day count, total rows (or — with `--quick`)
- By-park table: files, rows, date range
- Recent-coverage grid: last N days × parks (✓/— or row counts)
- Report path: `reports/wait_time_db_report.md` under output base (overwritten each run)
- `--quick`: skip row counts; grid shows ✓/— only (faster on slow paths)
- `--lookback-days` (default 14), `--output-base`, `--report`

**Why**: Daily or ad-hoc visibility into coverage and freshness without querying raw CSVs.

**Report step wrap-up**: `report_wait_time_db.py` now includes extensive module docstring (PURPOSE, OUTPUT, MODES), section headers, and inline comments. README and `scripts/README` updated.

### Wait Time Validation Script

**Added**:
- `scripts/validate_wait_times.py` — Validates fact table CSVs (schema, ranges, outliers)
- **POSTED/ACTUAL**: valid 0–1000; outlier if ≥ 300
- **PRIORITY**: valid -100–2000 or 8888; outlier if &lt; -100 or &gt; 2000 and ≠ 8888
- JSON report to `validation/`; exit 1 on invalid rows
- `--lookback-days`, `--all`, `--output-base`, `--report`

**Why**: React quickly to missing or faulty data before downstream modeling and WTI.

### Script Documentation and Wrap-Up

**What changed**:
- Main ETL script (`get_tp_wait_time_data_from_s3.py`) fully documented with module docstring, section headers, and step-by-step comments (STEP 1–12 in `main()`)
- README, CHANGES, PROJECT_STRUCTURE, output/logs READMEs, and CONNECTION_ERROR_FIX updated for `failed_files.json`, `processing.lock`, and skip–old–repeatedly-failed behavior
- No temporary scripts present; `scripts/`, `temp/`, `work/` contain only READMEs

**Why**: Easier for new readers to understand each step; docs stay in sync with current behavior.

### Modular Refactoring (Current Version)

**What Changed**:
- Refactored into modular structure with separate parsers
- Ported proven Julia parsing logic to Python
- Added file type classification
- Changed output from single Parquet file to individual CSV files per park/date
- Added connection error retry logic

**Why**:
- Modular parsers are easier to test and maintain
- Julia logic was proven to work correctly
- CSV files per park/date are easier to work with than one large file
- Retry logic handles network issues automatically

**Key Files**:
- `src/parsers/wait_time_parsers.py`: New modular parsers
- `src/utils/file_identification.py`: File type classifier
- `src/get_tp_wait_time_data_from_s3.py`: Refactored main script

### Output Structure Change

**Before**: Single Parquet file per month
```
fact_tables/YYYY-MM/wait_time_fact_table.parquet
```

**After**: Individual CSV files per park and date
```
fact_tables/clean/YYYY-MM/mk_2024-01-15.csv
fact_tables/clean/YYYY-MM/epcot_2024-01-15.csv
```

**Why**: 
- CSV files are easier to inspect and work with
- One file per park/date makes it easy to work with specific data
- Appending to existing files handles multiple S3 files for same park/date

### Parser Improvements

**Old Fastpass Parser**:
- Fixed date parsing (was producing incorrect years like 2813)
- Now correctly reads headerless format (matches Julia: `header=false, skipto=2`)
- Handles sold-out detection correctly (FWINHR >= 8000 → 8888 minutes)

**New Fastpass Parser**:
- Added sold-out handling (was filtering them out, now keeps with 8888 minutes)
- Matches Julia logic exactly

**Standby Parser**:
- Verified to match Julia logic
- Correctly filters rows where both posted and actual are missing

**Why**: Ensures data accuracy and matches proven Julia implementation.

### Connection Error Handling

**Added**:
- Automatic retry logic with exponential backoff
- S3 client configured with adaptive retry mode
- Longer timeouts for large files
- Failed files are not marked as processed (will retry on next run)

**Why**: Network connections can be unstable. Retries handle transient errors automatically.

### Skip Old Repeatedly-Failed Files

**Added**:
- `state/failed_files.json` tracks files that fail (parse errors, connection errors, etc.)
- If a file has failed ≥3 times **and** its S3 last-modified is older than 600 days, we skip it on future runs
- Successfully processing a file clears its failure tracking

**Why**: Some files (e.g. 2014 Old Fastpass) cannot be parsed successfully. Retrying them every run wastes time. Old, repeatedly-failed files are skipped instead.

**Tunables**: `FAILED_SKIP_THRESHOLD` (default 3), `OLD_FILE_DAYS` (default 600) in `get_tp_wait_time_data_from_s3.py`.

## Previous Versions

### Incremental Processing (Earlier Version)

**What Changed**:
- Added incremental processing (only processes new files)
- Added persistent deduplication database
- Added processed files tracking
- Added file-based logging

**Why**:
- Much faster for daily runs
- Deduplication works across multiple runs
- Better monitoring and debugging

## Migration Notes

### From Old Version

If you have existing output from an older version:

1. **First run**: Use `--full-rebuild` to process everything with new logic
2. **Output location**: Defaults to Dropbox location, or specify with `--output-base`
3. **File format**: Old Parquet files are replaced with CSV files
4. **Structure**: New structure is `fact_tables/clean/YYYY-MM/{park}_{date}.csv`

### Reprocessing Files

- **Single file**: Remove from `state/processed_files.json` and run normally
- **All files**: Use `--full-rebuild` flag
- **Specific properties**: Use `--props wdw,dlr` to process only certain properties

## Performance Improvements

- **Chunked processing**: Processes files in chunks (250k rows default) to manage memory
- **Incremental runs**: Only processes new files, much faster for daily runs
- **SQLite deduplication**: Fast lookups, persistent across runs
- **Connection retries**: Handles transient network errors automatically

## Known Issues and Solutions

### Old Repeatedly-Failed Files Skipped

**Behavior**: Files that fail ≥3 times and are older than 600 days are skipped on future runs.

**To retry**: Remove the file key from `state/failed_files.json` and run normally.

### Connection Errors

**Issue**: Connection errors when reading large files from S3

**Solution**: Automatic retry logic with exponential backoff. Files that fail will be retried on next run.

### Large Dedupe Database

**Issue**: SQLite database grows over time

**Solution**: Database should remain manageable. If needed, delete `state/dedupe.sqlite` and run with `--full-rebuild` (note: this will allow duplicates until database is rebuilt).

## Future Improvements

Potential enhancements for future versions:
- Unit tests for parsers
- Data validation and quality checks
- Performance monitoring and metrics
- Support for additional data sources
