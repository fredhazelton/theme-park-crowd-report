# Stream Dashboard

Live data dashboard for theme park crowd levels, wait times, and forecasts.

## Quick Start (unified workflow)

**Preview on your Mac:** Run only the dashboard server. Data comes from wilma-server (API runs there).

### 1. Start the Dashboard Server

From the repo root:

```bash
./scripts/start-stream.sh
```

Or directly:

```bash
python3 dashboard/stream_server.py
```

- Serves on **http://localhost:8889**
- Preview: **http://localhost:8889/stream-dashboard.html**
- Use `python3` (not `python`) on Mac. Use `--port N` to override the default port.
- You can run it in the background (e.g. from your IDE or terminal); it works and keeps serving until you stop it (Ctrl+C or close the terminal).

### 2. Open the Preview

In your browser, go to **http://localhost:8889/stream-dashboard.html**. The dashboard fetches data from **http://wilma-server:8051/api** — your Mac must be able to reach `wilma-server`.

**Note:** You do not run the API locally for preview; the API runs on wilma-server where the pipeline data lives.

### 3. (Optional) Run the API locally

If you run the API on your Mac (e.g. `python3 dashboard/api.py` on port 8051), the dashboard must point at it. In **docs/stream/stream-dashboard.html**, set:

```javascript
const API_BASE = 'http://localhost:8051/api';
```

Reload **http://localhost:8889/stream-dashboard.html** so it uses your local API.

## Seeing real data (which date and entity to pick)

If the curve always looks the same (placeholder) no matter what you select:

1. **Check the API host**  
   The dashboard uses `API_BASE` (see above). If the API runs locally, use `http://localhost:8051/api`. Otherwise it uses `http://wilma-server:8051/api` — your machine must resolve and reach that host.

2. **Get an example that has data**  
   In your browser (or with curl), open:
   - **Local API:** `http://localhost:8051/api/sample-actual-points`
   - **Wilma API:** `http://wilma-server:8051/api/sample-actual-points`  
   You should see JSON like: `{ "sample": { "park_code": "mk", "entity_code": "MK01", "date": "2026-02-04" } }`.  
   If you see `"sample": null`, the pipeline has no fact data yet (run the pipeline so `fact_tables/clean` is populated).

3. **Use that example in the dashboard**  
   - **Property:** leave as-is or pick the one that contains the park (e.g. Disney World for `mk`).  
   - **Park:** select the `park_code` from the sample (e.g. **Magic Kingdom** for `mk`).  
   - **Attraction:** in the dropdown, pick the attraction whose **value** is that `entity_code` (e.g. **MK01** — the label may be the attraction name).  
   - **Date:** set the date picker to the `date` from the sample (e.g. **2026-02-04**).  
   - Use a **single date** (not 7D/30D) so the chart requests one day and can show actual points.

4. **What you’ll see**  
   - **Curve (line):** From WTI or forecast/backfill. If the API has no curve for that park/date, the line is the placeholder but the chart still loads.  
   - **Actual points (dark pink dots):** From `fact_tables/clean` for that entity and date. They appear only when an attraction and a single date are selected and the API has fact data for that combination.

If the API is unreachable, the sidebar will show “Error loading data” and the chart will show the placeholder. Check that the API process is running and that `API_BASE` matches where it’s running.

## Architecture

- **Backend API** (`dashboard/api.py`): REST API serving data from pipeline
- **Frontend** (`docs/stream/stream-dashboard.html`): HTML/CSS/JS dashboard
- **Server** (`dashboard/stream_server.py`): Serves the HTML at http://localhost:8889/stream-dashboard.html

## API Endpoints

- `GET /api/health` - Health check
- `GET /api/crowd-level/<park_code>` - Get crowd level (1-10) for a park
- `GET /api/wait-times/<park_code>?limit=5` - Get top wait times
- `GET /api/forecast/<park_code>?days=7` - Get 7-day forecast
- `GET /api/tip/<park_code>` - Get pro tip
- `GET /api/stats/<park_code>` - Get comprehensive stats
- `GET /api/entities/<park_code>` - Get all entities/attractions for a park
- `GET /api/properties` - Get all properties
- `GET /api/parks?property=<code>` - Get parks (optionally filtered by property)
- `GET /api/daily-curve/<park_code>?date=YYYY-MM-DD` or `?start=...&end=...` - Daily wait time curve: average actual wait every 5 min (time_slot → avg_wait). Single day or range (averaged across days). Optional `&entity_code=MK02` for attraction-level curve (from forecast/backfill curves). Park-level from WTI when no entity_code.
- `GET /api/actual-points/<park_code>?date=YYYY-MM-DD&entity_code=MK01` - Raw ACTUAL observations for one attraction on one park-date (from fact_tables/clean). Used by the Daily Wait Time Curve when an attraction and single date are selected; points are overlaid in dark pink.
- `GET /api/sample-actual-points` - Returns one `{ park_code, entity_code, date }` that has ACTUAL data in fact_tables/clean (for “try this park, attraction, date”).
- `GET /api/debug/entity-table` - Debug endpoint to inspect entity table structure

## Daily curve and actual points

When you select an **attraction** and a **single date**, the Daily Wait Time Curve also fetches raw ACTUAL observations for that entity and day from `fact_tables/clean` and overlays them as dark pink points. The line is the curve (from forecast/backfill or WTI); the points are the observed actual waits.

**Example entity with data:** Call `GET /api/sample-actual-points`. If the pipeline has fact data, the response gives one `park_code`, `entity_code`, and `date` to try (e.g. `mk`, `MK01`, `2026-02-04`). Or run `scripts/find_entities_with_actual.py` to list entities that have ACTUAL data; then pick a park and a date when the pipeline has written fact CSVs for that park (e.g. yesterday after the morning ETL).

## Park Codes

- `mk` - Magic Kingdom
- `ep` - EPCOT
- `hs` - Hollywood Studios
- `ak` - Animal Kingdom
- `ioa` - Islands of Adventure
- `usf` - Universal Studios Florida

## Daily Wait Time Curve (first chart)

- **Data:** Park-level from WTI (`wti/wti.parquet` with `time_slot`); attraction-level when an attraction is selected, from `curves/forecast/` or `curves/backfill/` for that entity over the date range.
- **X-axis (park day):** 06:00 (6 AM) to 03:00 next day — origin is 6 AM, not midnight. Time slots are sorted in park-day order (06:00–23:55, then 00:00–02:55).
- **Placeholder:** When the API returns no curve data, a placeholder curve is shown so the chart always renders; subtitle indicates "no server data".

## Data Sources

- **WTI**: `output_base/wti/wti.parquet`
- **Live Wait Times**: `output_base/staging/queue_times/`
- **Forecast Curves**: `output_base/curves/forecast/`
- **Backfill Curves**: `output_base/curves/backfill/`
- **Entity Metadata**: `output_base/dimension_tables/dimentity.csv`

## Storytelling Arc

The dashboard is arranged for a narrative flow:

1. **The Big Picture** - Hero card with overall crowd level
2. **The Details** - Top wait times (current reality)
3. **The Future** - 7-day forecast (what's coming)
4. **The Opportunity** - Pro tip (actionable advice)
5. **The Context** - Alert (important warnings)

## Auto-Refresh

Dashboard automatically refreshes every 5 minutes to match queue-times interval.

## Troubleshooting

### API not responding
- Check that `dashboard/api.py` is running
- Verify `output_base` path in config
- Check that WTI data exists: `output_base/wti/wti.parquet`

### No data showing
- Ensure pipeline has run and generated WTI data
- Check browser console for API errors
- Verify CORS is enabled (flask-cors installed)

### Park code errors
- Dashboard uses `ioa`/`usf`, pipeline uses `ia`/`uf`
- API handles mapping automatically

### Entity names not displaying
- Attraction dropdown shows entity codes (e.g., "IA01") instead of names (e.g., "The Incredible Hulk Coaster")
- Debug endpoint: `GET /api/debug/entity-table` to inspect entity table structure
- Check API server logs for column detection messages
- See WILMA-BAMBAM.md for full details and debugging steps
