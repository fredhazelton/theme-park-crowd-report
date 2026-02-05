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
- `GET /api/debug/entity-table` - Debug endpoint to inspect entity table structure

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
