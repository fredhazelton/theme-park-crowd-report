# Dashboard Analysis & Integration Plan

## Overview

The `docs/stream/dashboard.html` is a **live data dashboard** for displaying theme park crowd levels, wait times, and forecasts. It's designed as a beautiful, modern web interface that will consume data from the pipeline.

**Current State:** Static HTML with demo data  
**Target State:** Dynamic dashboard connected to live pipeline data

---

## Dashboard Structure

### 1. **Park Selector**
- Tabs for 6 parks:
  - 🏰 Magic Kingdom (`mk`)
  - 🌐 EPCOT (`ep`)
  - 🎬 Hollywood Studios (`hs`)
  - 🦁 Animal Kingdom (`ak`)
  - 🦖 Islands of Adventure (`ioa` → `ia`)
  - 🎥 Universal Studios (`usf` → `uf`)

### 2. **Hero Crowd Level Card**
- **Large number display** (1-10 scale) - This is **WTI** (Wait Time Index)
- **Visual progress bar** with marker
- **Stats row:**
  - Avg Wait (average ACTUAL across all entities)
  - Capacity (percentage - needs calculation)
  - vs Yesterday (WTI comparison)
  - Best Time (time slot with lowest predicted wait)

### 3. **Top Wait Times List**
- Shows top 5 attractions by current wait
- Color-coded bars (green → cyan → yellow → orange → red)
- Trend indicators (↑↓)
- **Data source:** Latest POSTED from `staging/queue_times/` or `fact_tables/clean/`

### 4. **7-Day Forecast**
- Daily crowd level predictions (WTI forecast)
- Weather icons (optional - not in pipeline yet)
- Visual bars showing forecast intensity
- **Data source:** `wti/wti.parquet` (future dates)

### 5. **Alert Card**
- Important notices (weather, capacity, etc.)
- **Data source:** Could be from `dimmetatable.csv` or custom alerts

### 6. **Pro Tip Card**
- Actionable advice based on data
- **Data source:** Calculated from forecast curves (e.g., "Seven Dwarfs drops to 45 min at 8 PM")

---

## Data Integration Points

### Available Data Sources

#### 1. **WTI (Wait Time Index)**
- **Location:** `output_base/wti/wti.parquet` or `wti/wti.csv`
- **Format:**
  ```python
  # Columns: park_code, park_date, time_slot, wti, n_entities, min_actual, max_actual
  # For dashboard: Need daily aggregate (average WTI across all time slots for a date)
  ```
- **Usage:**
  - Hero card: Current day's WTI (scale 1-10, but WTI is in minutes - need conversion)
  - 7-day forecast: Future dates' WTI
  - vs Yesterday: Compare today's WTI to yesterday's

#### 2. **Live Wait Times**
- **Location:** `output_base/staging/queue_times/YYYY-MM/{park}_{YYYY-MM-DD}.csv`
- **Format:**
  ```python
  # Columns: entity_code, observed_at, wait_time_type, wait_time_minutes
  # Filter: wait_time_type == "POSTED", latest observed_at per entity
  ```
- **Usage:**
  - Top Wait Times list: Latest POSTED per entity, sorted descending
  - Current wait display: Most recent observation

#### 3. **Forecast Curves**
- **Location:** `output_base/curves/forecast/{entity_code}_{YYYY-MM-DD}.csv`
- **Format:**
  ```python
  # Columns: time_slot, actual_predicted, posted_predicted
  # Time slots: 5-minute intervals during park operating hours
  ```
- **Usage:**
  - Pro Tip: Find time slot with lowest predicted wait for an attraction
  - Best Time: Time slot with lowest average wait across all entities

#### 4. **Entity Metadata**
- **Location:** `output_base/dimension_tables/dimentity.csv`
- **Format:**
  ```python
  # Columns: entity_code, entity_name, park_code, ...
  # Used for: Display names, filtering by park
  ```

#### 5. **Park Hours**
- **Location:** `output_base/dimension_tables/dimparkhours_with_donor.csv`
- **Format:**
  ```python
  # Columns: park_code, park_date, opening_time, closing_time, ...
  # Used for: Determining if park is open, operating window
  ```

#### 6. **Historical Fact Tables**
- **Location:** `output_base/fact_tables/clean/YYYY-MM/{park}_{YYYY-MM-DD}.csv`
- **Format:**
  ```python
  # Columns: entity_code, observed_at, wait_time_type, wait_time_minutes
  # Used for: Historical comparisons, "vs Yesterday"
  ```

---

## Data Processing Requirements

### 1. **WTI to Crowd Level (1-10 scale)**
WTI is in **minutes** (average ACTUAL wait time). Need to convert to 1-10 scale:

```python
# Strategy: Use historical WTI percentiles
# Example mapping (needs calibration):
# WTI 0-15 min → 1-2 (Very Low)
# WTI 15-30 min → 3-4 (Low)
# WTI 30-45 min → 5-6 (Moderate)
# WTI 45-60 min → 7-8 (High)
# WTI 60+ min → 9-10 (Very High)

# Or use percentile-based:
# Calculate percentiles from historical WTI data
# Map current WTI to percentile → scale 1-10
```

### 2. **Current Day WTI**
For "today", need to:
- Load WTI for today's date
- If not available (park hasn't opened yet), use forecast
- If park is open, could use incremental WTI (average of time slots so far)

### 3. **Top Wait Times**
```python
# Algorithm:
# 1. Load latest staging/queue_times files for selected park
# 2. Filter: wait_time_type == "POSTED"
# 3. Group by entity_code, take max(observed_at) per entity
# 4. Sort by wait_time_minutes descending
# 5. Take top 5
# 6. Join with dimentity for display names
```

### 4. **7-Day Forecast**
```python
# Algorithm:
# 1. Load wti/wti.parquet
# 2. Filter: park_code == selected_park
# 3. Filter: park_date >= today, park_date <= today + 7 days
# 4. Group by park_date, calculate average WTI across time slots
# 5. Convert WTI to 1-10 scale
# 6. Sort by park_date
```

### 5. **Pro Tip Generation**
```python
# Algorithm:
# 1. For selected park, load forecast curves for today
# 2. For each entity, find time slot with minimum actual_predicted
# 3. Rank entities by improvement (max wait - min wait)
# 4. Generate tip: "Entity X typically drops to Y min around Z PM"
```

---

## Technical Implementation

### Backend API (New)

Create a Flask/FastAPI backend to serve data:

```python
# dashboard/api.py (new file)
# Endpoints:
# - GET /api/wti/{park_code}?date=YYYY-MM-DD
# - GET /api/wait-times/{park_code}?limit=5
# - GET /api/forecast/{park_code}?days=7
# - GET /api/tip/{park_code}
# - GET /api/crowd-level/{park_code}?date=YYYY-MM-DD
```

### Frontend Updates

1. **Replace static data** with API calls
2. **Add loading states** while fetching
3. **Auto-refresh** every 5 minutes (match queue-times interval)
4. **Error handling** for missing data

### Data Refresh Strategy

- **Live wait times:** Every 5 minutes (queue-times interval)
- **WTI/forecast:** Once daily (after morning pipeline)
- **Cache:** Use browser localStorage or service worker for offline viewing

---

## Park Code Mapping

Dashboard uses different codes than pipeline:

| Dashboard | Pipeline | Entity Prefix |
|-----------|----------|---------------|
| `mk` | `mk` | `MK` |
| `ep` | `ep` | `EP` |
| `hs` | `hs` | `HS` |
| `ak` | `ak` | `AK` |
| `ioa` | `ia` | `IA` |
| `usf` | `uf` | `UF` |

**Note:** Dashboard uses `ioa` and `usf`, but pipeline uses `ia` and `uf`. Need mapping.

---

## Missing Features / Enhancements

1. **Weather icons:** Not in pipeline - could add from external API or skip
2. **Capacity calculation:** Need to define what "87% capacity" means
3. **Historical comparison:** "vs Yesterday" needs yesterday's WTI
4. **Best time calculation:** Need to analyze forecast curves to find optimal time slot
5. **Alert generation:** Need logic to generate alerts from metadata/weather
6. **Entity filtering:** Only show "major" attractions in top wait times? Or all?

---

## Next Steps

1. **Create backend API** (`dashboard/api.py`) to serve data
2. **Update frontend** to fetch from API instead of static data
3. **Implement WTI → 1-10 scale conversion** (calibrate with historical data)
4. **Add park code mapping** (`ioa` → `ia`, `usf` → `uf`)
5. **Test with real data** from pipeline
6. **Add error handling** and loading states
7. **Deploy** alongside existing `dashboard/app.py` (pipeline status dashboard)

---

## File Structure

```
dashboard/
├── app.py              # Existing: Pipeline status dashboard (Dash)
├── api.py              # NEW: REST API for stream dashboard
├── stream_server.py    # NEW: Serves dashboard.html with API integration
└── README.md           # Update with new dashboard info

docs/stream/
├── dashboard.html      # Frontend (needs API integration)
├── main-dashboard.html # Stream overlay (separate, already reviewed)
└── DASHBOARD_ANALYSIS.md # This file
```

---

## Questions / Decisions Needed

1. **WTI scale conversion:** Use percentile-based or fixed thresholds?
2. **Capacity metric:** How to calculate "87% capacity"?
3. **Top wait times:** Show all entities or filter to "major" attractions?
4. **Refresh interval:** Match queue-times (5 min) or different?
5. **Deployment:** Same server as pipeline dashboard or separate?
6. **Authentication:** Add auth like pipeline dashboard?
