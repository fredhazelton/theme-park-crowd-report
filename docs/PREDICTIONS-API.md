# Predictions API Documentation

## Overview

The predictions API provides access to historical and predicted wait times for theme park attractions. It's available on the same API server as other dashboard endpoints (`http://wilma-server:8051`).

## Endpoints

### 1. Get Predictions (Filtered)

```
GET /api/predictions/<park_code>
```

**Parameters:**
- `entity_code` - Filter by entity (e.g., `MK23`)
- `date` - Filter by date (`YYYY-MM-DD`)
- `start_date`, `end_date` - Date range filter
- `limit` - Max results (default: 1000)

**Example:**
```bash
curl "http://localhost:8051/api/predictions/mk?entity_code=MK23&date=2026-02-05&limit=5"
```

**Response:**
```json
{
  "park_code": "mk",
  "count": 5,
  "predictions": [
    {
      "entity_code": "MK23",
      "observed_at": "2026-02-05T10:00:00-05:00",
      "park_date": "2026-02-05",
      "posted_time": 45,
      "predicted_actual": 28.5,
      "prediction_method": "model",
      "hour_of_day": 10
    }
  ]
}
```

---

### 2. Get Daily Curve

```
GET /api/predictions/<park_code>/daily-curve
```

**Parameters:**
- `entity_code` - Required. Entity code (e.g., `MK23`)
- `date` - Date for curve (default: today)

**Example:**
```bash
curl "http://localhost:8051/api/predictions/mk/daily-curve?entity_code=MK23&date=2026-02-05"
```

**Response:**
```json
{
  "entity_code": "MK23",
  "date": "2026-02-05",
  "method": "model",
  "curve": [
    {
      "time": "2026-02-05T09:00:00-05:00",
      "hour": 9,
      "posted": 30,
      "predicted": 18.5,
      "method": "model"
    }
  ]
}
```

---

### 3. List Entities with Predictions

```
GET /api/predictions/entities
```

**Parameters:**
- `park` - Filter by park code (e.g., `mk`, `ep`, `hs`, `ak`)

**Example:**
```bash
curl "http://localhost:8051/api/predictions/entities?park=mk"
```

**Response:**
```json
{
  "count": 89,
  "entities": [
    {
      "entity_code": "MK05",
      "prediction_count": 715878,
      "first_date": "2009-03-04",
      "last_date": "2026-02-05",
      "avg_posted": 53.3,
      "avg_predicted": 32.9,
      "method": "model"
    }
  ]
}
```

---

## Data Sources

### Historical Predictions File
- **Location:** `/home/wilma/hazeydata/pipeline/predictions/historical_predictions.parquet`
- **Size:** ~1.4 GB
- **Rows:** 90 million predictions
- **Date Range:** 2009-03-02 to present
- **Updated:** Daily at 6 AM via cron

### Columns in Predictions Data
| Column | Type | Description |
|--------|------|-------------|
| `entity_code` | string | Attraction code (e.g., MK23) |
| `observed_at` | timestamp | When the observation was recorded |
| `observed_at_ts` | timestamp | UTC timestamp |
| `park_date` | date | Operating date |
| `posted_time` | int | Posted wait time (minutes) |
| `predicted_actual` | float | Predicted actual wait (minutes) |
| `prediction_method` | string | "model" or "fallback" |
| `hour_of_day` | int | Hour (0-23) |

---

## Models

### Training
- **150 entity models** trained with XGBoost
- **Minimum 500 ACTUAL observations** required for model
- **607 entities** use 82% fallback ratio (not enough data)

### Features Used
- `posted_time` - The posted wait time
- `mins_since_6am` - Minutes since 6 AM
- `hour_of_day` - Hour of day (0-23)
- `day_of_week` - Day (0=Mon, 6=Sun)
- `month` - Month (1-12)
- `is_weekend` - Weekend flag (0/1)

### Model Location
- `/home/wilma/hazeydata/pipeline/models/<entity_code>/model.json`
- `/home/wilma/hazeydata/pipeline/models/<entity_code>/metadata.json`

---

## Daily Pipeline

Runs at **6 AM daily** via cron:

1. **ETL Sync** - Pulls new data from S3, converts to Parquet
2. **Retrain** - Retrains models with new ACTUAL data
3. **Score** - Scores new POSTED observations
4. **Update** - Appends to historical predictions

**Script:** `scripts/daily_pipeline_fast.py`

---

## Visualization

### Daily Curve Prototype
- **URL:** `http://wilma-server:8888/daily-curve.html`
- **Source:** `dashboard/static/daily-curve.html`

### Visual Elements
- 🟢 **Green area** - Observed ACTUAL wait times
- 🔵 **Blue area** - Predicted ACTUAL wait times  
- ⚫ **Gray dots** - Posted wait times (subtle)

---

## Performance

| Operation | Time |
|-----------|------|
| Count all entities | 0.2 seconds |
| Train 150 models | ~10 minutes |
| Score 90M predictions | ~2.5 minutes |
| Daily curve query | <1 second |

The speed comes from:
- **Parquet** format (87% smaller than CSV)
- **DuckDB** for fast analytical queries
- **Parallel processing** (5 workers)
