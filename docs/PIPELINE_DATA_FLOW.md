# Pipeline Data Flow - Complete Documentation

**Created:** 2026-02-07  
**Updated:** 2026-02-07 (V2 with geo decay, date_group_id, season)  
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
│  2. FACT TABLES (Parquet) ─── POSTED + ACTUAL + PRIORITY observations │
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
| `wait_time_type` | string | `POSTED`, `ACTUAL`, or `PRIORITY` |
| `wait_time_minutes` | int | Wait time in minutes |

### Wait Time Types

| Type | Description | Use |
|------|-------------|-----|
| **POSTED** | Disney's displayed wait time | Primary input for predictions |
| **ACTUAL** | TouringPlans observed wait time | Training target (ground truth) |
| **PRIORITY** | Lightning Lane / Genie+ availability | Future feature (not yet used in models) |

### Sample Data

```
entity_code               observed_at  park_date wait_time_type  wait_time_minutes
       MK01 2026-02-04T19:00:04-05:00 2026-02-05         POSTED                 55
       MK01 2026-02-04T19:03:03-05:00 2026-02-05         POSTED                 55
       MK01 2026-02-01T08:20:57-05:00 2026-02-01         ACTUAL                 12
       MK01 2026-02-01T09:15:00-05:00 2026-02-01       PRIORITY                  0
```

### Statistics

| Metric | Count |
|--------|-------|
| Total rows | ~120 million |
| POSTED rows | ~90 million |
| ACTUAL rows | ~2.5 million |
| PRIORITY rows | ~25 million |
| Date range | 2009-03-02 to present |

---

## Stage 2: Matched Pairs (V2)

**Purpose:** Pair each ACTUAL observation with the closest POSTED observation within a 15-minute window, enriched with calendar features.
##TODO: For historical observtions this only needs to be perfomred once. Once we generate pairs of POSTED and ACTUAL, we do not need to pair the same obs in the next run. Only new observations will need to be paired.


**Location:** `/home/wilma/hazeydata/pipeline/matched_pairs/all_pairs_v2.parquet`  
**Script:** `scripts/hybrid_pipeline_v2.py`

### Process

1. Find all ACTUAL observations
2. For each ACTUAL, find all POSTED for same entity + park_date within ±15 minutes
3. Select the POSTED with smallest time difference (best temporal match)
4. Join with `dimdategroupid` and `dimseason` for calendar features
##TODO Join with dimparkhours for mins_since_open feature
5. Calculate geo decay weight based on observation age
6. Label-encode categorical features

### Columns

| Column | Type | Description |
|--------|------|-------------|
| `entity_code` | string | Attraction identifier |
| `observed_at` | timestamp | ACTUAL observation time |
| `park_date` | date | Operating date |
| `actual_time` | float | Actual wait time (target variable) |
| `posted_time` | float | Posted wait time (feature) |
| `date_group_id` | string | Calendar group (e.g., "JAN_WEEK1_MON", "THANKSGIVING") |
| `date_group_id_encoded` | int | Label-encoded date_group_id |
| `season` | string | Season (e.g., "WINTER", "CHRISTMAS_PEAK") |
| `season_encoded` | int | Label-encoded season |
| `season_year` | string | Season + year (e.g., "WINTER_2025") |
| `season_year_encoded` | int | Label-encoded season_year |
| `geo_decay_weight` | float | Training weight: `0.5^(days_old / 730)` |
| `hour_of_day` | int | Hour (0-23) |
| `mins_since_6am` | int | Minutes since 6 AM |
##TODO add mins_since_open 

### Geo Decay Weight Formula

```
geo_decay_weight = 0.5^(days_since_observed / 730)
```

- Half-life: 730 days (2 years)
- Recent data weighs more in training
- 1-year-old data: weight = 0.71
- 2-year-old data: weight = 0.50
- 4-year-old data: weight = 0.25

### Sample Data

```
entity_code  park_date  actual_time  posted_time  date_group_id    season  geo_decay_weight
       MK01 2024-01-15           50           60  JAN_WEEK3_MON    WINTER             0.71
       MK01 2025-11-28           45           35   THANKSGIVING  THANKSGIVING         0.93
       AK07 2023-07-04           72           65     JULY_4TH   SUMMER_PEAK          0.52
```

### Statistics

- **Total pairs:** 2,393,511
- **Entities with 500+ pairs:** 141 (eligible for model training)

---

## Stage 3: Model Training (V2 - XGBOOST_BASE_MODEL)

**Purpose:** Train XGBoost models to predict ACTUAL from POSTED + calendar features, weighted by recency.

**Tool:** Julia XGBoost.jl (faster than Python)  
**Script:** `scripts/hybrid_pipeline_v2.py` → `julia-ml/train_v2.jl`  
**Models:** `/home/wilma/hazeydata/pipeline/models/{entity}/model_julia_v2.json`  
**Model Label:** `XGBOOST_BASE_MODEL`

### Features (V2)

| Feature | Type | Description |
|---------|------|-------------|
| `posted_time` | float | Posted wait time (primary predictor) |
| `mins_since_6am` | int | Minutes since 6 AM |
| `hour_of_day` | int | Hour of day (0-23) |
| `date_group_id_encoded` | int | Calendar group (replaces day_of_week, month, is_weekend) |
| `season_encoded` | int | Season category |
| `season_year_encoded` | int | Season + year category |

### Hyperparameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `num_round` | 500 | Maximum boosting rounds | ##TODO I'd like to do MAX 2000 for accuracy 
| `max_depth` | 6 | Maximum tree depth | ##TODO MAX 10
| `eta` | 0.1 | Learning rate |
| `min_child_weight` | 1 | Minimum child weight |
| `subsample` | 0.8 | Row subsampling |
| `colsample_bytree` | 0.8 | Column subsampling |
| `objective` | reg:squarederror | Squared error loss |
| `early_stopping_rounds` | 20 | Early stopping patience |

### Training Logic
##TODO - Note that training also only needs to be done on entities with new data - but the WHOLE dataset of observations must be retrained for that entity
```
For each entity with ≥500 matched pairs:
    1. Load matched pairs for entity
    2. Split 85% train / 15% validation (chronological)
    3. Apply geo_decay_weight as sample weights
    4. Train XGBoost regressor with early stopping
    5. Save model as JSON with metadata
```

### Performance (V2) — Tested 2026-02-07

| Metric | Value |
|--------|-------|
| Entities trained | 141 |
| Training time | 69 seconds |
| Average MAE | 7.86 minutes |
| Uses geo decay | ✅ Yes |

### Full Pipeline Timing (V2)

| Step | Time | Output |
|------|------|--------|
| Matched Pairs (DuckDB) | 76s | 2,393,511 pairs |
| Training (Julia) | 83s | 141 models |
| Scoring (Python) | 179s | 89,942,244 predictions |
| **Total** | **338s (~5.6 min)** | ✅ |

### Model Versioning

Models are labeled for tracking:
- **Current:** `XGBOOST_BASE_MODEL` (V2 with geo decay)
- **Future alternates:** `XGBOOST_NO_GEODECAY`, `XGBOOST_DEEP`, etc.

Model metadata (`metadata_julia_v2.json`) includes:
- Model label
- Training timestamp
- Sample count
- MAE
- Feature list
- Hyperparameters
- Geo decay settings

### Entities Without Models

Entities with <500 matched pairs use the **82% fallback rule** (see below).

---

## Stage 4: Historical Predictions

**Purpose:** Generate predicted ACTUAL for every historical POSTED observation.

**Location:** `/home/wilma/hazeydata/pipeline/predictions/historical_predictions.parquet`

### Prediction Logic

```
For each POSTED observation:
    IF entity has trained model:
        predicted_actual = ROUND(model.predict(features))  # Integer
        method = "model"
    ELSE:
        predicted_actual = ROUND(posted_time × 0.82)  # Integer ##TODO we should calculate the ratio dynamically rather than using 82% hard coded
        method = "fallback"
```

**Note:** Predicted actuals are always rounded to the nearest integer.

### Columns

| Column | Type | Description |
|--------|------|-------------|
| `entity_code` | string | Attraction identifier |
| `observed_at` | timestamp | Original POSTED observation time |
| `park_date` | date | Operating date |
| `posted_time` | int | Original posted wait time |
| `predicted_actual` | int | **Predicted** actual wait time (integer) |
| `prediction_method` | string | `model` or `fallback` |
| `model_label` | string | `XGBOOST_BASE_MODEL` or `FALLBACK_82PCT` |

### Sample Data (Model Prediction)

```
entity_code  park_date  posted_time  predicted_actual prediction_method        model_label
       MK01 2026-02-05           55                44             model  XGBOOST_BASE_MODEL
       MK01 2026-02-05           55                44             model  XGBOOST_BASE_MODEL
       MK01 2026-02-05           60                48             model  XGBOOST_BASE_MODEL
```

### Sample Data (Fallback - 82% Rule) ##TODO we should calculate the ratio dynamically rather than using 82% hard coded

```
entity_code  park_date  posted_time  predicted_actual prediction_method      model_label
       AK04 2021-11-27            5                 4          fallback  FALLBACK_82PCT
       AK04 2022-02-26           55                45          fallback  FALLBACK_82PCT
       AK04 2022-05-09           60                49          fallback  FALLBACK_82PCT
```

### Statistics (as of 2026-02-07)

- **Total predictions:** 89,942,244
- **Model predictions:** 150 entities with models
- **Fallback predictions:** 607 entities using 82% rule
- **File size:** 1.4 GB (Parquet)
- **Date range:** 2009-03-02 to 2026-02-05

---

## Stage 5: Future Forecasts

**Purpose:** Generate 2-year forward predictions at 5-minute resolution.

**Location:** `/home/wilma/hazeydata/pipeline/curves/forecast_parquet/all_forecasts.parquet`  
**Script:** `scripts/forecast_vectorized.py`

### Forecast Logic

```
For each entity × each date × each 5-minute slot:
    1. Get park hours from dimparkhours for that date
    2. Build features (time slot, date_group_id, season, season_year)
    
    IF entity has trained model:
        predicted_actual = ROUND(model.predict(features))
        method = "model"
    ELSE:
        # Use historical average POSTED for (entity, time_slot, date_group_id)
        avg_posted = AVERAGE(historical posted for entity + time_slot + date_group_id)
        predicted_actual = ROUND(avg_posted × 0.82)
        method = "fallback"
```

**Key points:**
- Uses `dimparkhours` for park hours (can change daily)
- Fallback uses `(entity, time_slot, date_group_id)` for better estimates
- All predictions rounded to integers
- If date_group_id changes, re-scoring is triggered

### Columns

| Column | Type | Description |
|--------|------|-------------|
| `entity_code` | string | Attraction identifier |
| `park_date` | date | Future date |
| `time_slot` | time | 5-minute slot (00:00:00, 00:05:00, ...) |
| `predicted_actual` | int | Predicted actual wait time (integer) |
| `prediction_method` | string | `model` or `fallback` |
| `model_label` | string | Model used for prediction |

### Sample Data

```
entity_code  park_date time_slot  predicted_actual prediction_method        model_label
       AK01 2026-02-08  09:00:00                24             model  XGBOOST_BASE_MODEL
       AK01 2026-02-08  09:05:00                26             model  XGBOOST_BASE_MODEL
       AK04 2026-02-08  10:00:00                25          fallback     FALLBACK_82PCT
```

### Statistics

- **Total predictions:** ~159 million
- **Date range:** Tomorrow → +2 years (731 days)
- **Entities:** 757
- **Time slots per day:** 288 (every 5 minutes)

---

## The 82% Fallback Rule

### Why 82%?

Historical analysis shows that **ACTUAL wait times are approximately 82% of POSTED wait times** on average.

### Application by Scenario

| Scenario | What We Know | Calculation |
|----------|--------------|-------------|
| **Historical** | Actual POSTED observed | `predicted = ROUND(posted × 0.82)` |
| **Forecast** | No POSTED yet | `predicted = ROUND(avg_posted_for_slot_and_dategroupid × 0.82)` |

### Improved Fallback (V2)

For forecasts, we compute average POSTED using:
- **Entity** (attraction)
- **Time slot** (5-minute window)
- **date_group_id** (calendar pattern)

This preserves both the daily pattern AND the calendar pattern (holidays vs. regular days).

---

## Dimension Tables

### dimdategroupid.csv

**Purpose:** Calendar spine with date groupings for modeling.

| Column | Type | Example |
|--------|------|---------|
| `park_date` | date | 2026-02-07 |
| `date_group_id` | string | FEB_WEEK1_FRI |
| `holidaycode` | string | NONE |
| `holidayname` | string | None |
| `day_of_week_name` | string | Friday |

Special date_group_ids: `NEW_YEARS_DAY`, `THANKSGIVING`, `CHRISTMAS_DAY`, `JULY_4TH`, etc.

### dimseason.csv

**Purpose:** Season assignments for each date.

| Column | Type | Example |
|--------|------|---------|
| `park_date` | date | 2026-02-07 |
| `season` | string | WINTER |
| `season_year` | string | WINTER_2026 |

Seasons: `WINTER`, `SPRING`, `SUMMER`, `SUMMER_PEAK`, `FALL`, `THANKSGIVING`, `CHRISTMAS`, `CHRISTMAS_PEAK`

### dimparkhours.csv

**Purpose:** Park operating hours for each date (used for forecasts).

| Column | Type | Example |
|--------|------|---------|
| `park_date` | date | 2026-02-07 |
| `park_code` | string | MK |
| `opening_time` | string | 09:00 |
| `closing_time` | string | 22:00 |

**Note:** Park hours can change daily. Forecasts should be re-generated when hours change.

---

## Data Volumes Summary

| Stage | Rows | Size | Format |
|-------|------|------|--------|
| Fact Tables | 120M | 640 MB | Parquet |
| Matched Pairs (V2) | 2.4M | ~120 MB | Parquet |
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
| `scripts/hybrid_pipeline_v2.py` | Full V2 pipeline (pairs + training + scoring) | ~5.6 min |
| `scripts/hybrid_pipeline_v2.py --skip-scoring` | Pairs + training only | ~2.7 min |
| `scripts/score_historical.py` | Score all historical POSTED | ~3 min |
| `scripts/forecast_vectorized.py` | Generate 2-year forecasts | ~8 min |

**Daily cron (6am):** Runs `run_daily_pipeline.sh` which calls `hybrid_pipeline_v2.py`

---

## Entity Breakdown by Method

| Method | Entities | Criteria |
|--------|----------|----------|
| **Model (XGBOOST_BASE_MODEL)** | 141 | ≥500 matched pairs |
| **Fallback (FALLBACK_82PCT)** | 607 | <500 pairs |
| **Total** | 748 | All entities with POSTED data |

---

## Rounding Rules

| Prediction Type | Rounding |
|-----------------|----------|
| Predicted ACTUAL | Nearest integer |
| Predicted POSTED (if ever implemented) | Nearest 5 minutes |

---

## Re-scoring Triggers

The following changes should trigger a re-scoring of predictions:

1. **Park hours change** → Re-generate forecasts for affected dates
2. **date_group_id assignment change** → Re-score historical + forecasts
3. **Model retrain** → Re-score all predictions
4. **New entity added** → Score new entity only

---

## See Also

- [HYBRID_PIPELINE.md](HYBRID_PIPELINE.md) - Julia training details
- [PREDICTIONS-API.md](PREDICTIONS-API.md) - API documentation
- [PIPELINE_TIMING_AND_PARALLELIZATION.md](PIPELINE_TIMING_AND_PARALLELIZATION.md) - Performance
- [SCHEMAS.md](SCHEMAS.md) - Dimension table schemas
