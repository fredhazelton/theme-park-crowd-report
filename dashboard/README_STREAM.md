# Stream Dashboard

Live data dashboard for theme park crowd levels, wait times, and forecasts.

## Quick Start

### 1. Start the API Server

```bash
python dashboard/api.py
```

Runs on **http://localhost:8051**

### 2. Start the Dashboard Server

```bash
python dashboard/stream_server.py
```

Preview at **http://localhost:8889/stream-dashboard.html** (default port 8889; use `--port N` to override).

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
- `GET /api/debug/entity-table` - Debug endpoint to inspect entity table structure

## Park Codes

- `mk` - Magic Kingdom
- `ep` - EPCOT
- `hs` - Hollywood Studios
- `ak` - Animal Kingdom
- `ioa` - Islands of Adventure
- `usf` - Universal Studios Florida

## Data Sources

- **WTI**: `output_base/wti/wti.parquet`
- **Live Wait Times**: `output_base/staging/queue_times/`
- **Forecast Curves**: `output_base/curves/forecast/`
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
