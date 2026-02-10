# Pipeline Data Flow - Complete Documentation

**Created:** 2026-02-07  
**Updated:** 2026-02-09 (V2 models, aggregates, imputation, WTI fix)  
**Author:** Wilma

---

## ⚠️ DAILY CRON - CRITICAL INFO (READ THIS FIRST!)

The daily cron runs at **6:00 AM ET** via `run_daily_pipeline.sh`.

### ✅ Correct Scripts for Each Step

| Step | Script | Time | Notes |
|------|--------|------|-------|
| S3 Sync | `sync_s3_data.sh` | ~10s | Has `export PATH="$HOME/.local/bin:$PATH"` for AWS CLI |
| Aggregates | **`build_posted_aggregates_fast.py`** | **~7s** | Uses monthly parquet files (NOT CSVs!) |
| Training | `hybrid_pipeline_v2.py --skip-scoring` | ~80s | Julia XGBoost |
| Forecast | **`forecast_vectorized.py --days 730`** | **~8 min** | 159M predictions |

### ❌ DO NOT USE — These are slow/broken:

| Script | Problem | Use Instead |
|--------|---------|-------------|
| `generate_forecast.py` | Non-vectorized, takes hours | `forecast_vectorized.py` |
| `build_posted_aggregates.py` | Scans 50K CSVs, crashes/takes 30+ min | `build_posted_aggregates_fast.py` |
| `hybrid_pipeline.py` | V1, outdated | `hybrid_pipeline_v2.py` |

### Known Issues (2026-02-08)
~~1. **WTI step fails** — Looks for curves in wrong location. Needs path fix. (Non-critical)~~
✅ Fixed 2026-02-09: Created `calculate_wti_simple.py` that works with current data structures.

### Fixes Applied (2026-02-08)
1. ✅ **AWS CLI PATH** — Added `export PATH="$HOME/.local/bin:$PATH"` to `sync_s3_data.sh`
2. ✅ **Aggregates** — Switched to `build_posted_aggregates_fast.py` (reads 202 parquet files, not 50K CSVs)
3. ✅ **Forecast** — Switched to `forecast_vectorized.py` (159M predictions in 8 min)

### Full Pipeline Timing (Production)

| Step | Script | Time |
|------|--------|------|
| S3 Sync | `sync_s3_data.sh` | ~10s |
| ETL | (incremental) | ~1 min |
| Dimensions | (incremental) | ~30s |
| **Impute Park Hours** | `impute_park_hours.py` | **~1s** |
| Aggregates | `build_posted_aggregates_fast.py` | **7s** |
| Report | | ~1s |
| Training | `hybrid_pipeline_v2.py` | **80s** |
| Forecast | `forecast_vectorized.py` | **8 min** |
| **TOTAL** | | **~10-12 min** |

*Previously took 8+ hours before optimizations.*

---

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

### Storage Locations (TWO FORMATS!)

| Format | Location | Size | Files | Use For |
|--------|----------|------|-------|---------|
| **Parquet (monthly)** | `fact_tables/parquet/*.parquet` | 611 MB | 202 | ✅ Aggregates, fast queries |
| CSV (daily) | `fact_tables/clean/{YYYY-MM}/*.csv` | 5.4 GB | 50K | ETL output, raw backup |

**⚠️ IMPORTANT:** Always use the parquet files for queries. Scanning 50K CSVs is slow and crashes.

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
**TODO:** For historical observations this only needs to be performed once. Once we generate pairs of POSTED and ACTUAL, we do not need to pair the same obs in the next run. Only new observations will need to be paired. (Currently, the full matched pairs are regenerated each run; incremental pairing is a future optimization.)


**Location:** `/home/wilma/hazeydata/pipeline/matched_pairs/all_pairs_v2.parquet`  
**Script:** `scripts/hybrid_pipeline_v2.py`

### Process

1. Find all ACTUAL observations
2. For each ACTUAL, find all POSTED for same entity + park_date within ±15 minutes
3. Select the POSTED with smallest time difference (best temporal match)
4. Join with `dimdategroupid` and `dimseason` for calendar features
5. Join with `dimparkhours` for park opening time
6. Calculate geo decay weight based on observation age
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
| `mins_since_open` | int | Minutes since park opened (from dimparkhours) |

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
| `num_round` | 2000 | Maximum boosting rounds |
| `max_depth` | 10 | Maximum tree depth |
| `eta` | 0.1 | Learning rate |
| `min_child_weight` | 1 | Minimum child weight |
| `subsample` | 0.8 | Row subsampling |
| `colsample_bytree` | 0.8 | Column subsampling |
| `objective` | reg:squarederror | Squared error loss |
| `early_stopping_rounds` | 20 | Early stopping patience |

### Training Logic
**Note:** Training currently retrains ALL eligible entities each run. The `--skip-if-unchanged` flag skips the entire training step if no entities have new data. Per-entity selective training (only retrain dirty entities) is a future optimization — the full dataset must be retrained for each entity since matched pairs include the full history.
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
| Training time | 83 seconds |
| Average MAE | 7.89 minutes |
| Uses geo decay | ✅ Yes |

### Full Pipeline Timing (V2)

| Step | Time | Output |
|------|------|--------|
| Matched Pairs (DuckDB) | 78s | 2,393,511 pairs |
| Training (Julia) | 97s | 141 models |
| Scoring (Python) | 179s | 89,942,244 predictions |
| **Total** | **354s (~5.9 min)** | ✅ |

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

Entities with <500 matched pairs use the **dynamic fallback rule** (see below).

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
        # Use per-entity ratio if ≥50 samples, else global ratio (0.678)
        ratio = entity_ratio if entity_samples >= 50 else global_ratio
        predicted_actual = ROUND(posted_time × ratio)  # Integer
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

### Sample Data (Fallback - Dynamic Ratio)

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

## Stage 5: Future Forecasts (V2)

**Purpose:** Generate 2-year forward predictions at 5-minute resolution using V2 models.

**Location:** `/home/wilma/hazeydata/pipeline/curves/forecast_parquet/all_forecasts.parquet`  
**Script:** `scripts/forecast_vectorized.py`

### V2 Model Features

The V2 forecast uses the same features as V2 training:

| Feature | Type | Description |
|---------|------|-------------|
| `posted_time` | float | Estimated from model aggregates |
| `mins_since_6am` | int | Minutes since 6 AM |
| `mins_since_open` | int | Minutes since park opening |
| `hour_of_day` | int | Hour (0-23) |
| `date_group_id_encoded` | int | Encoded calendar group |
| `season_encoded` | int | Encoded season |
| `season_year_encoded` | int | Encoded season+year |

### Forecast Logic (V2)

```
For each entity × each date × each 5-minute slot:
    1. Get park hours from dimparkhours
    2. Get date_group_id, season, season_year from dimensions
    3. Encode features using mappings from matched_pairs_v2.parquet
    4. Estimate posted_time from model_aggregates.parquet
    
    IF entity has V2 model (model_julia_v2.json):
        predicted_actual = ROUND(model.predict(features))
        method = "model_v2"
    ELIF aggregate exists for (entity, date_group_id, time_slot):
        predicted_actual = wait_median from aggregates
        method = "aggregate"
    ELSE:
        predicted_actual = ROUND(posted_estimate × 0.82)
        method = "fallback_ratio"
```

### Columns

| Column | Type | Description |
|--------|------|-------------|
| `entity_code` | string | Attraction identifier |
| `park_date` | date | Future date |
| `time_slot` | time | 5-minute slot (00:00:00, 00:05:00, ...) |
| `predicted_actual` | int | Predicted actual wait time (integer) |
| `prediction_method` | string | `model_v2`, `aggregate`, or `fallback_ratio` |

### Sample Data

```
entity_code  park_date time_slot  predicted_actual prediction_method
       AK01 2026-02-10  09:00:00                24          model_v2
       AK01 2026-02-10  09:05:00                26          model_v2
       AK04 2026-02-15  09:45:00                10         aggregate
       AK08 2026-02-10  10:00:00                25    fallback_ratio
```

### Statistics

- **Total predictions:** ~159 million
- **Date range:** Tomorrow → +2 years (731 days)
- **Entities:** 757 (141 with V2 models, 616 using fallback)
- **Time slots per day:** 288 (every 5 minutes)

---

## Model Aggregates (for Fallback Predictions)

**Purpose:** Provide historical wait time statistics for entities without trained models.

**Script:** `scripts/build_model_aggregates.py`  
**Location:** `/home/wilma/hazeydata/pipeline/aggregates/model_aggregates.parquet`

### Grouping

Aggregates are computed at:
- **Entity** (attraction)
- **date_group_id** (calendar pattern - holidays, weekdays, etc.)
- **time_slot** (15-minute intervals, 0-95)

### Columns

| Column | Type | Description |
|--------|------|-------------|
| `entity_code` | string | Attraction identifier |
| `date_group_id` | string | Calendar group (e.g., "FEB_WEEK2_TUE") |
| `time_slot` | int | 15-min slot (0-95, where 0=00:00, 36=09:00) |
| `hour_of_day` | int | Hour (0-23) |
| `wait_median` | float | Median wait time |
| `wait_mean` | float | Mean wait time |
| `wait_mean_weighted` | float | Geo-decay weighted mean (2yr half-life) |
| `wait_p25`, `wait_p75` | float | 25th/75th percentiles |
| `wait_std` | float | Standard deviation |
| `sample_count` | int | Number of observations |
| `date_count` | int | Number of unique dates |

### Statistics

| Metric | Value |
|--------|-------|
| Total rows | 6,446,321 |
| Entities | 757 |
| Date groups | 387 |
| Time slots | 96 (15-min intervals) |
| Build time | ~72s |
| File size | 85 MB |

### Usage in Forecasts

For entities without V2 models, the forecast script uses:
```
(entity, date_group_id, time_slot) → wait_median
```

If no aggregate match exists, falls back to ratio-based method.

---

## The Dynamic Fallback Rule (Legacy)

**Note:** The V2 forecast now uses model aggregates as the primary fallback. The ratio-based method below is the ultimate fallback when no aggregate data exists.

### How It Works

Fallback ratios are calculated dynamically from matched pairs data:
- **Per-entity ratio**: If entity has ≥50 matched pairs, use `actual_sum / posted_sum`
- **Global ratio**: If entity has <50 pairs, use global average (currently **0.678**)

The global ratio of 0.678 means ACTUAL wait times are approximately **68% of POSTED** on average.

### Application by Scenario

| Scenario | What We Know | Calculation |
|----------|--------------|-------------|
| **Historical** | Actual POSTED observed | `predicted = ROUND(posted × entity_ratio)` |
| **Forecast** | No POSTED yet | `predicted = ROUND(avg_posted × entity_ratio)` |

### Fallback Ratios File

Ratios are stored in `state/fallback_ratios.json`:
```json
{
  "MK01": 0.72,
  "AK07": 0.65,
  "__global__": 0.678
}
```

### Fallback Priority (V2 Forecast)

1. **V2 Model** — If `model_julia_v2.json` exists, use it
2. **Aggregate Lookup** — `(entity, date_group_id, time_slot)` → `wait_median`
3. **Ratio Fallback** — `posted_estimate × 0.82`

**Statistics (2026-02-09):**
- 141 entities with V2 models
- 616 entities using aggregate/ratio fallback

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
| `donor_date` | date | 2025-02-07 |

**Note:** Park hours can change daily. Forecasts should be re-generated when hours change.

#### Park Hours Imputation

**Script:** `scripts/impute_park_hours.py`  
**Runs after:** Dimension fetches (needs dimparkhours + dimdategroupid)

Future dates often lack official park hours. The imputation process fills these gaps:

1. **Primary method (date_group_id match):**
   - Find all historical dates with same `date_group_id` that have park hours
   - Weight by recency: ≤1 year = 1.0, 2-4 years = 0.8→0.4, 5+ years = 0.1
   - Select the weighted mode (most common hours combo)
   - Store the donor date for tracking

2. **Fallback (12-month mode):**
   - For dates with no matching date_group_id donors
   - Use the mode park hours from the last 12 months for that park

**Outputs:**
- `dimparkhours.csv` — Updated with imputed hours (donor_date populated)
- `parkhours_donations.csv` — Accuracy tracking log

**Accuracy tracking:** When official hours become available, compare against donated hours to measure imputation accuracy.

| Metric | Value |
|--------|-------|
| Typical imputed rows | ~10,000 |
| Processing time | ~0.6s |

---

## Data Volumes Summary

| Stage | Rows | Size | Format | Notes |
|-------|------|------|--------|-------|
| Fact Tables (parquet) | 120M | 611 MB | Parquet | ✅ 202 monthly files |
| Fact Tables (CSV) | 120M | 5.4 GB | CSV | ⚠️ 50K files, don't scan |
| Matched Pairs (V2) | 2.4M | ~120 MB | Parquet | ✅ Single file |
| Historical Predictions | 90M | 1.4 GB | Parquet | ✅ |
| Future Forecasts | 159M | 44 MB | Parquet | ✅ Single file |
| Posted Aggregates | 1.7M | 19 MB | Parquet | ✅ 7s rebuild |
| **Model Aggregates** | 6.4M | 85 MB | Parquet | ✅ 72s rebuild |
| **WTI** | 48K+ | ~1 MB | Parquet | ✅ 2s rebuild |

---

## Wait Time Index (WTI)

**Purpose:** Daily average wait time per park for crowd level analysis.

**Script:** `scripts/calculate_wti_simple.py`  
**Location:** `/home/wilma/hazeydata/pipeline/wti/wti.parquet`

### Calculation

| Source | Method |
|--------|--------|
| **Historical** | Average of entity wait times from fact tables (ACTUAL preferred, POSTED fallback) |
| **Forecast** | Average of predicted_actual from forecast file |

### Columns

| Column | Type | Description |
|--------|------|-------------|
| `park_code` | string | Park identifier (MK, AK, EP, etc.) |
| `park_date` | date | Date |
| `wti` | float | Wait Time Index (avg wait across entities) |
| `n_entities` | int | Number of entities included |
| `source` | string | `historical` or `forecast` |

### Statistics

| Metric | Value |
|--------|-------|
| Historical park-dates | ~48,000 |
| Parks | 13 |
| Date range | 2009 to present + 2 years |
| Build time | ~2s |

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

### ✅ Production Scripts (USE THESE)

| Script | Purpose | Time |
|--------|---------|------|
| `scripts/impute_park_hours.py` | Fill missing future park hours from donor pool | **~1s** |
| `scripts/build_posted_aggregates_fast.py` | Build posted aggregates (hourly) | **~7s** |
| `scripts/build_model_aggregates.py` | Build model aggregates (15-min, for fallback) | **~72s** |
| `scripts/hybrid_pipeline_v2.py --skip-scoring` | Matched pairs + Julia training | **~2.5 min** |
| `scripts/forecast_vectorized.py --days 730` | Generate 2-year forecasts (V2 models) | **~40 min** |
| `scripts/calculate_wti_simple.py` | Calculate Wait Time Index | **~2s** |

### ❌ DO NOT USE (Slow/Broken)

| Script | Problem |
|--------|---------|
| `build_posted_aggregates.py` | Scans 50K CSVs, crashes |
| `generate_forecast.py` | Non-vectorized, takes hours |
| `hybrid_pipeline.py` | V1, use V2 instead |

### Other Scripts

| Script | Purpose | Time | Notes |
|--------|---------|------|-------|
| `scripts/hybrid_pipeline_v2.py` | Full V2 pipeline (pairs + training + scoring) | ~5.6 min | |
| `scripts/score_historical.py` | Score all historical POSTED | ~3 min | |
| `scripts/generate_forecast.py` | ❌ SLOW forecast | Hours | **DO NOT USE in cron** |

### Daily Cron (6:00 AM ET)

**File:** `scripts/run_daily_pipeline.sh`

```bash
# Order of operations:
1. S3 Sync             # sync_s3_data.sh (needs PATH fix for AWS CLI)
2. ETL                 # Incremental parquet updates
3. Dimensions          # dimdategroupid, dimseason, dimparkhours
4. Impute Park Hours   # impute_park_hours.py - fills missing future hours
5. Posted Aggregates   # build_posted_aggregates_fast.py (~7s)
6. Report              # wait_time_db_report.md
7. Training            # hybrid_pipeline_v2.py --skip-scoring (Julia, ~80s)
8. Forecast            # forecast_vectorized.py --days 730 (~8 min)
9. WTI                 # calculate_wti_simple.py (~2s)
```

**Total time:** ~10-12 minutes

| Step | Time |
|------|------|
| S3 Sync | ~10s |
| ETL | ~1 min |
| Dimensions | ~30s |
| **Impute Park Hours** | **~1s** |
| **Aggregates (fast)** | **~7s** |
| Training (Julia) | ~80s |
| Forecast (vectorized) | ~8 min |

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

## Skip-If-Unchanged Logic (Data-Driven Cascade)

**Flag:** `--skip-if-unchanged` on `run_daily_pipeline.sh`  
**Script:** `scripts/pipeline_state.py`  
**State:** `state/pipeline_state.json` (persistent) + `state/run_manifest.json` (per-run)

### Problem Solved

Previously, skip decisions compared output file hashes/mtimes. This broke when
training produced identical model files (same weights) — downstream steps saw
"files unchanged" and skipped, even though new observations existed.

### How It Works Now

Skip decisions are driven by **data changes**, not output file comparisons:

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────┐
│     ETL      │────▶│   Training   │────▶│   Forecast   │────▶│   WTI    │
│              │     │              │     │              │     │          │
│ Updates      │     │ Skip if NO   │     │ Skip if      │     │ Skip if  │
│ entity_index │     │ dirty        │     │ training     │     │ forecast │
│ .sqlite      │     │ entities     │     │ was skipped  │     │ was      │
│              │     │              │     │ this run     │     │ skipped  │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────┘
                           │                     │                   │
                     entity_index           run manifest         run manifest
                     (data-driven)          (cascade)            (cascade)
```

### Decision Rules

| Step | Skip When | Data Source |
|------|-----------|-------------|
| **Training** | No entities have `latest_observed_at > last_modeled_at` | `entity_index.sqlite` |
| **Forecast** | Training did NOT run this pipeline run | `run_manifest.json` |
| **WTI** | Forecast did NOT run this pipeline run | `run_manifest.json` |

### Entity Index Tracking

The `entity_index.sqlite` database (maintained by ETL) tracks per-entity:

| Column | Purpose |
|--------|---------|
| `latest_observed_at` | Timestamp of newest observation from ETL |
| `last_modeled_at` | Timestamp when we last trained a model for this entity |

An entity is **dirty** (needs remodeling) when:
- `last_modeled_at IS NULL` (never modeled), OR
- `latest_observed_at > last_modeled_at` (new data since last model)

After training completes, `hybrid_pipeline_v2.py` calls `mark_entity_modeled()`
for each successfully trained entity, resetting their dirty state.

### Run Manifest

Each pipeline run creates `state/run_manifest.json` tracking which steps actually executed:

```json
{
  "run_id": "2026-02-10T07:24:46",
  "started_at": "2026-02-10T07:24:46",
  "steps": {
    "training": { "ran": true, "reason": "42 entities have new observations" },
    "forecast": { "ran": true, "reason": "training ran this run" },
    "wti":      { "ran": true, "reason": "forecast ran this run" }
  }
}
```

Downstream steps check the manifest: if the upstream step didn't run, they skip too.

### CLI Commands

```bash
# Check dirty entities
python3 scripts/pipeline_state.py dirty-entities

# Check what a step would do
python3 scripts/pipeline_state.py check training
python3 scripts/pipeline_state.py check forecast
python3 scripts/pipeline_state.py check wti

# View current run manifest
python3 scripts/pipeline_state.py show-manifest

# Force full rebuild (clears all state + marks all entities dirty)
python3 scripts/pipeline_state.py clear
```

### Without --skip-if-unchanged

When the flag is NOT set (default), all steps always run unconditionally.
The manifest and entity_index are still updated, but never consulted for skip decisions.

---

## Re-scoring Triggers

The following changes should trigger a re-scoring of predictions:

1. **Park hours change** → Re-generate forecasts for affected dates
2. **date_group_id assignment change** → Re-score historical + forecasts
3. **Model retrain** → Re-score all predictions (handled automatically by skip logic)
4. **New entity added** → Score new entity only

---

## See Also

- [HYBRID_PIPELINE.md](HYBRID_PIPELINE.md) - Julia training details
- [PREDICTIONS-API.md](PREDICTIONS-API.md) - API documentation
- [PIPELINE_TIMING_AND_PARALLELIZATION.md](PIPELINE_TIMING_AND_PARALLELIZATION.md) - Performance
- [SCHEMAS.md](SCHEMAS.md) - Dimension table schemas
