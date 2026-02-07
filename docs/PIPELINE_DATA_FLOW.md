# Pipeline Data Flow - Complete Documentation

**Created:** 2026-02-07  
**Author:** Wilma

This document describes the complete data flow through the theme park wait time prediction pipeline, with sample data at each stage.

---

## Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DATA FLOW PIPELINE                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. RAW DATA (S3 + Queue-Times)                                        │
│       ↓                                                                 │
│  2. FACT TABLES (Parquet) ─── POSTED + ACTUAL observations            │
│       ↓                                                                 │
│  3. MATCHED PAIRS ─────────── ACTUAL matched with nearest POSTED       │
│       ↓                                                                 │
│  4. MODEL TRAINING ────────── Julia XGBoost (entities with 500+ obs)   │
│       ↓                                                                 │
│  5. HISTORICAL PREDICTIONS ── Score all historical POSTED → ACTUAL     │
│       ↓                                                                 │
│  6. FUTURE FORECASTS ──────── Predict 2 years ahead at 5-min slots     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Stage 1: Raw Fact Tables

**Source:** S3 historical data + Queue-Times live scraper  
**Location:** `/home/wilma/hazeydata/pipeline/fact_tables/parquet/*.parquet`  
**Format:** Parquet (columnar, compressed)

### Columns

| Column | Type | Description |
|--------|------|-------------|
| `entity_code` | string | Attraction identifier (e.g., MK01, AK07) |
| `observed_at` | timestamp | When the observation was recorded |
| `observed_at_ts` | timestamp | UTC timestamp |
| `park_date` | date | Operating date (may differ from calendar date) |
| `wait_time_type` | string | `POSTED` or `ACTUAL` |
| `wait_time_minutes` | int | Wait time in minutes |

### Sample Data

```
entity_code               observed_at  park_date wait_time_type  wait_time_minutes
       MK01 2026-02-04T19:00:04-05:00 2026-02-05         POSTED                 55
       MK01 2026-02-04T19:03:03-05:00 2026-02-05         POSTED                 55
       MK01 2026-02-04T19:06:04-05:00 2026-02-05         POSTED                 55
       MK01 2026-02-04T19:09:03-05:00 2026-02-05         POSTED                 55
       MK01 2026-02-04T19:12:03-05:00 2026-02-05         POSTED                 55
```

### Statistics
- **Total rows:** ~120 million
- **Date range:** 2009-03-02 to present
- **POSTED rows:** ~90 million
- **ACTUAL rows:** ~2.5 million

---

## Stage 2: Matched Pairs

**Purpose:** Pair each ACTUAL observation with the closest POSTED observation within a 15-minute window.

**Location:** `/home/wilma/hazeydata/pipeline/matched_pairs/all_pairs.parquet`

### Process

1. Find all ACTUAL observations
2. For each ACTUAL, find all POSTED for same entity + park_date within ±15 minutes
3. Select the POSTED with smallest time difference
4. Add time-based features for training

### Columns

| Column | Type | Description |
|--------|------|-------------|
| `entity_code` | string | Attraction identifier |
| `observed_at` | timestamp | ACTUAL observation time |
| `park_date` | date | Operating date |
| `actual_time` | float | Actual wait time (target variable) |
| `posted_time` | float | Posted wait time (feature) |
| `hour_of_day` | int | Hour (0-23) |
| `mins_since_6am` | int | Minutes since 6 AM |
| `day_of_week` | int | Day of week (0=Monday) |
| `month` | int | Month (1-12) |
| `is_weekend` | int | 1 if Saturday/Sunday |

### Sample Data

```
entity_code  park_date  actual_time  posted_time  hour_of_day
       MK01 2022-11-20           50           60           10
       MK01 2023-01-29           45           35           13
       MK01 2023-02-26           23           30           21
       MK01 2023-02-26           10           30           15
       MK01 2023-03-06            7           60           11
       MK01 2023-03-30           72           65           18
       MK01 2023-04-27            3           10           22
       MK01 2023-05-12            3           25           21
```

### Statistics
- **Total pairs:** ~2.4 million
- **Entities with 500+ pairs:** 151 (eligible for model training)

---

## Stage 3: Model Training (Hybrid Pipeline)

**Purpose:** Train XGBoost models to predict ACTUAL from POSTED + time features.

**Tool:** Julia XGBoost.jl (faster than Python)  
**Script:** `scripts/hybrid_pipeline.py`  
**Models:** `/home/wilma/hazeydata/pipeline/models/{entity}/model_julia.json`

### Training Logic

```
For each entity with ≥500 matched pairs:
    1. Load matched pairs for entity
    2. Split 85% train / 15% validation (chronological)
    3. Train XGBoost regressor:
       - Features: posted_time, mins_since_6am, hour_of_day, day_of_week, month, is_weekend
       - Target: actual_time
       - Early stopping after 20 rounds without improvement
    4. Save model as JSON
```

### Performance
- **Entities trained:** 150
- **Training time:** ~67 seconds (Julia)
- **Average MAE:** 6.78 minutes

### Entities Without Models

Entities with <500 matched pairs don't get a dedicated model. Instead, they use the **82% fallback rule**.

---

## Stage 4: Historical Predictions

**Purpose:** Generate predicted ACTUAL for every historical POSTED observation.

**Location:** `/home/wilma/hazeydata/pipeline/predictions/historical_predictions.parquet`

### Prediction Logic

```
For each POSTED observation:
    IF entity has trained model:
        predicted_actual = model.predict(features)
        method = "model"
    ELSE:
        predicted_actual = posted_time × 0.82
        method = "fallback"
```

### Columns

| Column | Type | Description |
|--------|------|-------------|
| `entity_code` | string | Attraction identifier |
| `observed_at` | timestamp | Original POSTED observation time |
| `park_date` | date | Operating date |
| `posted_time` | float | Original posted wait time |
| `predicted_actual` | float | **Predicted** actual wait time |
| `prediction_method` | string | `model` or `fallback` |
| `hour_of_day` | float | Hour of day |
| ... | ... | Additional time features |

### Sample Data (Model Prediction)

```
entity_code  park_date  posted_time  predicted_actual prediction_method
       MK01 2026-02-05           55         43.306057             model
       MK01 2026-02-05           55         43.306057             model
       MK01 2026-02-05           55         43.589237             model
       MK01 2026-02-05           55         43.542458             model
       MK01 2026-02-05           55         43.672344             model
```

Note: Same posted_time (55) yields slightly different predictions based on time-of-day features.

### Sample Data (Fallback - 82% Rule)

```
entity_code  park_date  posted_time  predicted_actual prediction_method
       AK04 2021-11-27            5               4.1          fallback
       AK04 2022-02-26           55              45.1          fallback
       AK04 2022-05-09           60              49.2          fallback
       AK04 2022-07-21           45              36.9          fallback
       AK04 2022-10-08           10               8.2          fallback
```

Verification: `4.1 / 5 = 0.82`, `45.1 / 55 = 0.82`, etc.

### Statistics
- **Total predictions:** ~90 million
- **Date range:** 2009-03-02 to 2026-02-05
- **Model predictions:** ~70 million (from 150 entities)
- **Fallback predictions:** ~20 million (from 607 entities)

---

## Stage 5: Future Forecasts

**Purpose:** Generate 2-year forward predictions at 5-minute resolution.

**Location:** `/home/wilma/hazeydata/pipeline/curves/forecast_parquet/all_forecasts.parquet`  
**Script:** `scripts/forecast_vectorized.py`

### Forecast Logic

```
For each entity × each date × each 5-minute slot:
    IF entity has trained model:
        predicted_actual = model.predict(time_features)
        method = "model"
    ELSE:
        # Use historical average POSTED for this time slot
        avg_posted = AVERAGE(historical posted for entity + time_slot)
        predicted_actual = avg_posted × 0.82
        method = "fallback"
```

**Key distinction:** For fallback, we use the **time-slot-specific average** (e.g., average posted at 10:30 AM), not the overall entity average.

### Columns

| Column | Type | Description |
|--------|------|-------------|
| `entity_code` | string | Attraction identifier |
| `park_date` | date | Future date |
| `time_slot` | time | 5-minute slot (00:00:00, 00:05:00, ...) |
| `predicted_actual` | float | Predicted actual wait time |
| `prediction_method` | string | `model` or `fallback` |

### Sample Data (Model Forecast)

```
entity_code  park_date time_slot  predicted_actual prediction_method
       AK01 2026-02-08  00:00:00         23.806616             model
       AK01 2026-02-08  00:05:00         23.806616             model
       AK01 2026-02-08  00:10:00          3.613907             model
       AK01 2026-02-08  00:15:00          3.613907             model
       AK01 2026-02-08  00:20:00          3.613907             model
       AK01 2026-02-08  00:25:00         23.806616             model
```

Note: Predictions vary by time slot due to time-based features.

### Sample Data (Fallback Forecast)

```
entity_code  park_date time_slot  predicted_actual prediction_method
       AK04 2026-02-08  00:00:00              24.6          fallback
       AK04 2026-02-08  00:05:00              24.6          fallback
       AK04 2026-02-08  00:10:00              24.6          fallback
       AK04 2026-02-08  00:15:00              24.6          fallback
```

This is 82% of the historical average POSTED time for AK04 at those time slots.

### Statistics
- **Total predictions:** ~159 million
- **Date range:** 2026-02-08 to 2028-02-08 (731 days)
- **Entities:** 757
- **Time slots per day:** 288 (every 5 minutes)
- **Model forecasts:** 150 entities
- **Fallback forecasts:** 607 entities

---

## The 82% Fallback Rule

### Why 82%?

Historical analysis shows that **ACTUAL wait times are approximately 82% of POSTED wait times** on average. This ratio is used when:

1. An entity doesn't have enough data (< 500 observations) to train a model
2. We need a simple, robust fallback

### Application

| Scenario | What We Know | Calculation |
|----------|--------------|-------------|
| **Historical** (past) | Actual POSTED time observed | `predicted = posted × 0.82` |
| **Forecast** (future) | No POSTED yet | `predicted = avg_posted_for_timeslot × 0.82` |

### Time-Slot Specificity

For forecasts, we don't just use the overall average posted time. Instead:

1. Compute average POSTED for each (entity, time_slot) combination from history
2. For example, MK01 at 14:00 might average 45 min, while MK01 at 09:00 might average 25 min
3. Apply 82% to this time-slot-specific average

This preserves the natural daily pattern of wait times.

---

## Data Volumes Summary

| Stage | Rows | Size | Format |
|-------|------|------|--------|
| Fact Tables | 120M | 640 MB | Parquet |
| Matched Pairs | 2.4M | ~100 MB | Parquet |
| Historical Predictions | 90M | 1.4 GB | Parquet |
| Future Forecasts | 159M | 44 MB | Parquet |

---

## API Endpoints

All data is served via REST API at `http://localhost:8051`:

| Endpoint | Description |
|----------|-------------|
| `/api/predictions/<park>` | Historical predictions |
| `/api/predictions/<park>/daily-curve` | Historical curve for entity+date |
| `/api/forecast-summary` | Forecast statistics |
| `/api/forecast-detail/<park>` | Future forecast data |
| `/api/forecast-detail/<park>/daily-curve` | Future curve for entity+date |

---

## Scripts Reference

| Script | Purpose | Time |
|--------|---------|------|
| `scripts/hybrid_pipeline.py` | Matched pairs + Julia training | ~2.5 min |
| `scripts/score_historical.py` | Score all historical POSTED | ~2.5 min |
| `scripts/forecast_vectorized.py` | Generate 2-year forecasts | ~8 min |

---

## Entity Breakdown by Method

| Method | Entities | Criteria |
|--------|----------|----------|
| **Model** | 150 | ≥500 matched pairs, trained XGBoost |
| **Fallback** | 607 | <500 pairs, uses 82% rule |
| **Total** | 757 | All entities with POSTED data |

---

## See Also

- [HYBRID_PIPELINE.md](HYBRID_PIPELINE.md) - Julia training details
- [PREDICTIONS-API.md](PREDICTIONS-API.md) - API documentation
- [PIPELINE_TIMING_AND_PARALLELIZATION.md](PIPELINE_TIMING_AND_PARALLELIZATION.md) - Performance
