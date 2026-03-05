# Pipeline Methodology Audit — 2026-02-19

**Auditor:** Wilma (subagent)  
**Requested by:** Fred  
**Scope:** Trace all inputs and outputs of the latest pipeline version and verify against methodology docs  
**Date of data inspection:** 2026-02-19  

---

## Table of Contents

1. [Audit Summary](#1-audit-summary)
2. [Pipeline Step-by-Step Trace](#2-pipeline-step-by-step-trace)
3. [Key Methodology Verifications](#3-key-methodology-verifications)
4. [Discrepancies and Findings](#4-discrepancies-and-findings)
5. [Data File Verification](#5-data-file-verification)
6. [Recommendations](#6-recommendations)

---

## 1. Audit Summary

| Category | Count |
|----------|-------|
| ✅ Methodology matches | 28 |
| ⚠️ Discrepancies / concerns | 7 |
| 🔴 Issues requiring attention | 3 |

### Critical Findings

| # | Severity | Finding |
|---|----------|---------|
| 1 | 🔴 | **WTI has NO forecast data** — `wti.parquet` contains only `historical` source (50,123 rows through 2026-02-18). Forecast WTI is not being generated even though `all_forecasts.parquet` exists with 22.8M rows through 2027-02-18. The WTI script (`calculate_wti_simple.py`) appears correct, but the latest pipeline run did not produce forecast WTI. |
| 2 | 🔴 | **XGBoost hyperparameters diverged from XGBOOST_PARAMS.md** — The doc says `max_depth=6`, `subsample=0.5`, `min_child_weight=10`, `objective=reg:absoluteerror`, no early stopping, `colsample_bytree=1.0`. Julia V2 code actually uses `max_depth=10`, `subsample=0.8`, `min_child_weight=1`, `objective=reg:squarederror`, early stopping=20, `colsample_bytree=0.8`. The metadata on disk confirms the code's values. |
| 3 | 🔴 | **XGBOOST_PARAMS.md is stale** — The doc describes Python `training.py` params, but `training.py` no longer exists. All production training is in Julia (`train_v2.jl`, `train_actuals_v2.jl`). The doc is entirely outdated and misleading. |

---

## 2. Pipeline Step-by-Step Trace

### Step 0: S3 Sync (`sync_s3_data.sh`)

| Item | Details |
|------|---------|
| **Inputs** | S3 bucket `touringplans_stats`: `export/wait_times/`, `export/fastpass_times/` |
| **Processing** | `aws s3 sync` to local — only downloads new/changed files |
| **Outputs** | `{output_base}/raw/export/wait_times/`, `{output_base}/raw/export/fastpass_times/` |
| **Methodology match** | ✅ Matches PIPELINE_DATA_FLOW.md Step 0 |

### Step 1: ETL (`run_etl.sh` → `get_tp_wait_time_data_from_s3.py`)

| Item | Details |
|------|---------|
| **Inputs** | `{output_base}/raw/export/` + `staging/queue_times/` |
| **Processing** | Parse raw S3 files, merge staged queue-times, classify POSTED/ACTUAL/PRIORITY, deduplicate via SQLite |
| **Outputs** | `fact_tables/clean/YYYY-MM/{park}_{YYYY-MM-DD}.csv` — 4 columns: entity_code, observed_at, wait_time_type, wait_time_minutes |
| **Methodology match** | ✅ Matches SCHEMAS.md fact table schema exactly |

### Step 1b: CSV → Parquet (`convert_to_parquet.py`)

| Item | Details |
|------|---------|
| **Inputs** | `fact_tables/clean/YYYY-MM/*.csv` |
| **Processing** | Combines monthly CSVs into single parquet files, adds `observed_at_ts`, `park_date`, `park_code` |
| **Outputs** | `fact_tables/parquet/YYYY-MM.parquet` |
| **Methodology match** | ✅ All downstream steps read parquet per ARCHITECTURE.md |

### Step 2: Dimension Fetches (`run_dimension_fetches.sh`)

| Item | Details |
|------|---------|
| **Inputs** | S3 dimension exports |
| **Processing** | Fetches entity table, park hours, events, metatable; builds dimdategroupid, dimseason |
| **Outputs** | `dimension_tables/dimentity.csv`, `dimparkhours.csv`, `dimdategroupid.csv`, `dimseason.csv`, `dimeventdays.csv`, `dimevents.csv`, `dimmetatable.csv` |
| **Methodology match** | ✅ All dimension tables listed in SCHEMAS.md are produced |

**Verified on disk:**
- `dimentity.csv`: 341.7 KB, 1707 entities (134 fastpass_booth=TRUE, 1573 FALSE)
- `dimdategroupid.csv`: 1253.6 KB
- `dimseason.csv`: 279.5 KB
- `dimparkhours.csv`: 14969.9 KB (includes imputed future hours)

### Step 2a: Closures Module (`get_closures_from_s3.py` + `build_operating_calendar.py`)

| Item | Details |
|------|---------|
| **Inputs** | S3 closure CSVs (WDW, DLR, UOR, TDR, USH) + `dimentity.csv` (extinct_on dates) |
| **Processing** | Combines permanent closures (extinct_on) and temporary closures; generates is_operating per entity-date |
| **Outputs** | `operating_calendar/operating_calendar.parquet` |
| **Methodology match** | ✅ Matches CLOSURES_MODULE_SPEC.md |

**Verified on disk:**
- 11,203,041 rows, 1707 entities
- is_operating distribution: TRUE=9,293,036 / FALSE=1,910,005
- ✅ Boolean is_operating column (no nulls per spec)

### Step 2b: Impute Park Hours (`impute_park_hours.py`)

| Item | Details |
|------|---------|
| **Inputs** | `dimparkhours.csv` + `dimdategroupid.csv` |
| **Processing** | Fills missing future park hours using weighted-mode of historical donors (2-year recency decay) |
| **Outputs** | Updated `dimparkhours.csv` with imputed rows + `parkhours_donations.csv` tracking |
| **Methodology match** | ✅ Matches PIPELINE_DATA_FLOW.md Step 2b |

⚠️ **Note:** PIPELINE_DATA_FLOW.md mentions outlier donor filtering (reject openings after 9:30 AM, closings before 5 PM) as a TODO. Not verified if implemented.

### Step 3: Posted Aggregates (`build_posted_aggregates_fast.py`)

| Item | Details |
|------|---------|
| **Inputs** | `fact_tables/parquet/*.parquet` + `dimdategroupid.csv` |
| **Processing** | Computes per (entity, date_group_id, hour): median POSTED, mean with geo-decay, count |
| **Outputs** | `aggregates/posted_aggregates.parquet` (~1.7M rows) |
| **Methodology match** | ✅ Matches MODELING_AND_WTI_METHODOLOGY.md §3.3 "POSTED aggregate job" |

Also: `build_model_aggregates.py` produces `model_aggregates.parquet` at 15-minute resolution for forecast fallback.

### Step 4: Wait Time DB Report (`report_wait_time_db.py`)

| Item | Details |
|------|---------|
| **Outputs** | `reports/wait_time_db_report.md` |
| **Methodology match** | ✅ Informational only, not used by downstream steps |

### Step 4b: Forecast Accuracy Evaluation (`evaluate_forecast_accuracy.py`)

| Item | Details |
|------|---------|
| **Inputs** | Previous forecast (archived), current fact tables (ACTUAL + synthetic actuals), WTI archives |
| **Processing** | Archives current forecast (next 14 days), compares archived forecast vs actuals in 5-min slots, computes MAE/bias/MAPE/RMSE per entity-date and per park-date WTI |
| **Outputs** | `accuracy/slot_accuracy.parquet`, `accuracy/entity_daily_accuracy.parquet`, `accuracy/wti_accuracy.parquet`, `accuracy/accuracy_summary.json`, `accuracy/archive/forecast_*.parquet` |
| **Methodology match** | ✅ Runs BEFORE new forecasts (critical ordering preserved in pipeline) |
| | ✅ Includes synthetic actuals as ground truth (FULL OUTER JOIN) per Fred's 2026-02-18 decision |

### Step 4c: Synthetic Actuals Generation (`generate_synthetic_actuals.py`)

| Item | Details |
|------|---------|
| **Inputs** | `fact_tables/parquet/*.parquet` (POSTED only, STANDBY only), conversion model from `models/_conversion/`, dimension tables |
| **Processing** | Runs every historical POSTED through global XGBoost conversion model with rolling features (delta 15/30/60m, rolling mean, volatility) |
| **Outputs** | `synthetic_actuals/{entity_code}.parquet` per entity |
| **Methodology match** | ✅ Matches SYNTHETIC_ACTUALS_DESIGN.md |

**Filtering:**
- ✅ Only STANDBY entities (fastpass_booth=FALSE)
- ✅ Only entities with ≥500 POSTED observations
- ✅ Chunked by park for OOM safety (90M+ rows)

### Step 5a: Matched Pairs (`hybrid_pipeline_v2.py` step 1)

| Item | Details |
|------|---------|
| **Inputs** | `fact_tables/parquet/*.parquet` (ACTUAL + POSTED), `dimentity.csv`, `dimdategroupid.csv`, `dimseason.csv`, `dimparkhours.csv`, `operating_calendar.parquet` |
| **Processing** | For each ACTUAL, find closest POSTED within ±15-min window on same entity+park_date. Join dimensions. Encode categoricals. Compute fallback ratios. |
| **Outputs** | `matched_pairs/all_pairs_v2.parquet`, `state/encoding_mappings.json`, `state/fallback_ratios.json` |

**Verified on disk:**
- 2,396,008 rows, date range 2009-07-27 to 2026-02-18
- Columns: `entity_code, observed_at, observed_at_ts, park_date, actual_time, posted_time, date_group_id, season, season_year, hour_of_day, mins_since_6am, mins_since_open, date_group_id_encoded, season_encoded, season_year_encoded`
- ✅ No `geo_decay_weight` column (computed at training time per methodology)
- ✅ Incremental mode (appends new pairs only)
- ✅ Excludes fastpass_booth=TRUE entities
- ✅ Excludes is_operating=FALSE entity-dates

**Methodology match:**
- ✅ Operating calendar filter on training data (MODELING_AND_WTI_METHODOLOGY.md §2.2C)
- ✅ FastPass/Lightning Lane exclusion (implemented 2026-02-14 per SYNTHETIC_ACTUALS_DESIGN.md)

### Step 5b: V2 Model Training (Julia `train_v2.jl`)

| Item | Details |
|------|---------|
| **Inputs** | `matched_pairs/all_pairs_v2.parquet` (or `combined_pairs_v2.parquet` if --use-synthetic) |
| **Features (7)** | `posted_time, mins_since_6am, mins_since_open, hour_of_day, date_group_id_encoded, season_encoded, season_year_encoded` |
| **Target** | `actual_time` |
| **Weights** | `geo_decay = 0.5^(days_old / 730)` × synthetic weight (real=3.5x, synthetic=1.0x) |
| **Split** | 85% train / 15% validation (chronological) |
| **Outputs** | `models/{entity}/model_julia_v2.json` + `metadata_julia_v2.json` per entity |

**Verified on disk:**
- 430 V2 models on disk (including 17 LITE models)
- MK01 metadata confirms: `XGBOOST_BASE_MODEL`, 7 features, geo_decay=true, half-life=730

**XGBoost Hyperparameters (actual code in `train_v2.jl`):**

| Parameter | Code Value | XGBOOST_PARAMS.md Value | Match? |
|-----------|-----------|------------------------|--------|
| `num_round` | 2000 | 2000 | ✅ |
| `max_depth` | **10** | **6** | 🔴 MISMATCH |
| `eta` | 0.1 | 0.1 | ✅ |
| `subsample` | **0.8** | **0.5** | 🔴 MISMATCH |
| `colsample_bytree` | **0.8** | **1.0** | 🔴 MISMATCH |
| `min_child_weight` | **1** | **10** | 🔴 MISMATCH |
| `objective` | **reg:squarederror** | **reg:absoluteerror** | 🔴 MISMATCH |
| `early_stopping_rounds` | **20** | **None** | 🔴 MISMATCH |

**Lite Model Hyperparameters (entities with 100-499 pairs):**
- `max_depth=6`, `min_child_weight=3`, `subsample=0.8`, `colsample_bytree=0.8`
- 4 features only: `posted_time, mins_since_6am, mins_since_open, hour_of_day`

### Step 5c: Actuals-First Model Training (Julia `train_actuals_v2.jl`)

| Item | Details |
|------|---------|
| **Inputs** | `matched_pairs/actuals_training_v2/` (per-park parquets) built by `build_actuals_training_data.py` |
| **Features (5)** | `mins_since_6am, mins_since_open, date_group_id_encoded, season_encoded, season_year_encoded` — **NO posted_time** |
| **Target** | `actual_time` (from synthetic actuals weight=1.0 + real actuals weight=3.5) |
| **Weights** | `geo_decay × (3.5 if real, 1.0 if synthetic)` |
| **Outputs** | `models/{entity}/model_julia_actuals.json` + `metadata_julia_actuals.json` |

**Verified on disk:**
- 58 actuals models
- 92,964,464 actuals training rows (12 park files)
- Training data columns include `is_synthetic` for weight computation
- ✅ 3.5x weight for real actuals (confirmed in `train_actuals_v2.jl` line: `weights = geo_weights .* ifelse.(entity_df.is_synthetic, 1.0f0, 3.5f0)`)

**Methodology match:**
- ✅ 5 features (no posted_time) per PIPELINE_DATA_FLOW.md "Actuals-First" section
- ✅ Separation of concerns: POSTED → conversion model → synthetic actuals → forecasting on actuals only
- ✅ Same hyperparameters as V2 (`max_depth=10, eta=0.1, subsample=0.8, colsample_bytree=0.8`)

⚠️ **Note:** XGBOOST_PARAMS.md does not document actuals-first parameters at all.

### Step 5d: Build Actuals Training Data (`build_actuals_training_data.py`)

| Item | Details |
|------|---------|
| **Inputs** | `synthetic_actuals/*.parquet` (weight 1.0) + `fact_tables/parquet/*.parquet` ACTUAL (weight 3.5) + dimensions + operating calendar |
| **Processing** | Combines synthetic and real actuals, joins dimensions, computes time features, encodes categoricals |
| **Outputs** | `matched_pairs/actuals_training_v2/` (per-park parquet for OOM safety) + `matched_pairs/actuals_training_v2.parquet` (combined) |
| **Methodology match** | ✅ Matches SYNTHETIC_ACTUALS_DESIGN.md "Sample Weighting" |

⚠️ **Note:** The SYNTHETIC_ACTUALS_DESIGN.md says weight ratio should be 5.0:1.0 (real:synthetic), but the actual implementation uses **3.5:1.0** per Fred's 2026-02-18 decision in PIPELINE_DATA_FLOW.md. This is a doc inconsistency, not a code bug.

### Step 6: Forecast Generation (`forecast_vectorized.py`)

| Item | Details |
|------|---------|
| **Inputs** | Models (`model_julia_actuals.json` preferred, `model_julia_v2.json` fallback), `model_aggregates.parquet`, `dimparkhours.csv`, `operating_calendar.parquet`, `all_pairs_v2.parquet` (encodings), `fallback_ratios.json` |
| **Processing** | For each entity × future date × 5-min slot within park hours: predict actual wait time |
| **Outputs** | `curves/forecast_parquet/all_forecasts.parquet` |

**Prediction Fallback Chain:**

| Priority | Method | Entities | Condition |
|----------|--------|----------|-----------|
| 1 | `model_actuals` | 58 | `model_julia_actuals.json` exists (5 features, no posted_time) |
| 2 | `model_v2` | ~372 | `model_julia_v2.json` exists (7 features with posted_time) |
| 3 | `model_lite` | ~17 | V2 model with LITE label (4 features) |
| 4 | `aggregate` | ~varies | No model, but model_aggregates has data for (entity, dgid, slot) |
| 5 | `fallback_ratio` | ~varies | No model, no aggregate — uses posted_estimate × entity ratio (or global 0.678) |

**Verified on disk:**
- 22,806,103 forecast rows, date range 2026-02-20 to 2027-02-18
- Method distribution: model_v2=15,568,597, fallback_ratio=4,596,881, model_actuals=2,466,492, model_lite=161,811, aggregate=12,322
- ✅ 0 FastPass/Lightning Lane entities in forecast
- Forecast date range starts tomorrow (2026-02-20), ends at +365 days

**Methodology match:**
- ✅ Actuals model preferred over V2 per PIPELINE_DATA_FLOW.md "Actuals-First" method
- ✅ FastPass/Lightning Lane exclusion working (0 overlap)
- ✅ Park hours filtering (only generates slots within park operating hours)
- ✅ P95 cap REMOVED (confirmed: code has comment "P95 cap REMOVED (2026-02-18, Fred's decision)")
- ✅ Operating calendar filters out extinct/closed entities
- ✅ Aggregate fallback applies posted-to-actual ratio (not raw posted median)
- ✅ Default posted estimate = 5 minutes (for sparse entities)

⚠️ **Concern:** Forecast only goes to 2027-02-18 (364 days). Pipeline runs with `--days 730` but forecasts cover ~1 year, not 2 years. This appears to be because park hours are only available/imputed ~1 year out. The time grid only generates slots within park hours, so dates without park hours get no forecast. PIPELINE_DATA_FLOW.md says "2-year forecasts" but reality is ~1 year based on park hours availability.

### Step 7: WTI Calculation (`calculate_wti_simple.py`)

| Item | Details |
|------|---------|
| **Inputs** | `synthetic_actuals/*.parquet`, `fact_tables/parquet/*.parquet` (real actuals), `curves/forecast_parquet/all_forecasts.parquet`, `operating_calendar.parquet`, `accuracy/wti_accuracy.parquet` |
| **Processing** | Historical: weighted avg of synthetic (1.0) + real actuals (3.5) per entity per day → avg across entities. Forecast: avg predicted_actual per park per day (filtered by operating calendar). Adaptive per-park bias correction on forecast WTI. Historical wins on overlapping dates. |
| **Outputs** | `wti/wti.parquet` |

**Verified on disk:**
- 50,123 rows — **ALL historical, NO forecast WTI**
- Parks: AK, CA, DL, EP, EU, HS, IA, MK, TDL, TDS, UF, UH
- Date range: 2009-03-02 to 2026-02-18
- WTI last modified: 2026-02-18 08:27 (before the latest forecast file at 2026-02-19 00:25)

🔴 **This means the latest pipeline run generated forecasts but did NOT re-run WTI.** The skip-if-unchanged cascade likely caused this: WTI runs only if forecast ran in the same pipeline execution. If the forecast was regenerated in a separate run or manually, WTI would be stale.

**WTI Schema match:**
- ✅ `park_code, park_date, wti, n_entities, source` matches PIPELINE_DATA_FLOW.md
- ✅ 3.5x weight on real actuals (code: `REAL_ACTUAL_WEIGHT = 3.5`)
- ✅ Adaptive per-park bias correction using last 14 days
- ✅ Historical wins over forecast on dedup (sort by source, keep first)

**WTI Methodology match:**
- ✅ WTI = mean(actual) across all entities per park-day (MODELING_AND_WTI_METHODOLOGY.md §1.4)
- ✅ All entities included (no maintained "core" list) per §6
- ✅ Closed → null (excluded from mean) via operating calendar JOIN
- ⚠️ PIPELINE_DATA_FLOW.md has a TODO to remove the COALESCE fallback to raw POSTED (still present in code as fallback when no synthetic actuals)

### Step 8: Post-Pipeline

| Step | Status |
|------|--------|
| Landing chart generation | ✅ `generate_landing_chart.py` |
| Year-view data export + deploy | ✅ `export_year_view_data.py` → Cloudflare Pages |
| Pipeline validation | ✅ `validate_pipeline_output.py` |
| Dashboard API restart | ✅ Conditional restart if running |

---

## 3. Key Methodology Verifications

### 3.1 Training Features

| Model | Doc says | Code says | Match? |
|-------|----------|-----------|--------|
| V2 (with posted) | 7 features: posted_time, mins_since_6am, mins_since_open, hour_of_day, date_group_id, season, season_year | Same 7 features (encoded versions of last 3) | ✅ |
| Actuals-first (no posted) | 5 features: mins_since_6am, mins_since_open, date_group_id, season, season_year | Same 5 features (encoded versions of last 3) | ✅ |
| V2 Lite | 4 features: posted_time, mins_since_6am, mins_since_open, hour_of_day | Same 4 features | ✅ |
| Actuals Lite | 2 features: mins_since_6am, mins_since_open | Same 2 features | ✅ |

### 3.2 Operating Calendar Integration

| Use Case | Expected Behavior | Code Behavior | Match? |
|----------|-------------------|---------------|--------|
| Training pairs | Exclude is_operating=FALSE | `AND EXISTS (SELECT 1 FROM operating o WHERE ... is_operating = TRUE)` in DuckDB query | ✅ |
| Forecasting | Skip closed entity-dates | Operating calendar loaded, extinct entities skipped, per-date filtering | ✅ |
| WTI (forecast) | Only include operating rides | `JOIN operating_calendar WHERE is_operating = TRUE` | ✅ |
| WTI (historical) | N/A (uses all observations that exist) | No operating calendar filter on synthetic/actual observations | ⚠️ See §4 |

### 3.3 Synthetic Actuals Methodology

| Feature | SYNTHETIC_ACTUALS_DESIGN.md | Code | Match? |
|---------|---------------------------|------|--------|
| Target | ACTUAL = f(POSTED, rolling_context, time, entity, date) | ✅ Same | ✅ |
| Rolling features | delta_15/30/60m, rolling_mean_30/60m, volatility_30m | ✅ Computed via DuckDB window functions | ✅ |
| Model type | XGBoost global, reg:absoluteerror | ✅ (conversion model uses MAE) | ✅ |
| Geo-decay weights | 730-day half-life (added 2026-03-04) | ✅ `GEO_DECAY_HALF_LIFE_DAYS = 730` | ✅ |
| Standby only filter | fastpass_booth=FALSE | ✅ `WHERE fastpass_booth = FALSE` | ✅ |
| Min observations | ≥500 | ✅ Default 500 | ✅ |
| Output range | Clipped 0-300 | ✅ `np.clip(predictions, 0, 300)` in processor | ✅ |

### 3.4 WTI Computation

| Feature | MODELING_AND_WTI_METHODOLOGY.md | Code | Match? |
|---------|-------------------------------|------|--------|
| Definition | mean(actual) over (entity, time_slot) where actual is not null | ✅ AVG(entity_avg) across entities | ✅ |
| Entity set | All attractions (no core list) | ✅ No maintained list, all entities included | ✅ |
| Closed → null | Exclude closed entity-time_slots | ✅ Operating calendar JOIN for forecast WTI | ✅ |
| Historical source | Observed + predicted actual | ✅ Synthetic actuals (1.0) + real actuals (3.5) | ✅ |
| Forecast source | Features-only model predicted actual | ✅ AVG(predicted_actual) from forecast file | ✅ |
| Predicted POSTED in WTI | NOT used in WTI | ✅ Not referenced in WTI code | ✅ |

### 3.5 Forecast Fallback Chain

| Priority | PIPELINE_DATA_FLOW.md says | Code does | Match? |
|----------|---------------------------|-----------|--------|
| 1 | Actuals model | ✅ Checks `model_julia_actuals.json` first | ✅ |
| 2 | V2 model | ✅ Checks `model_julia_v2.json` second | ✅ |
| 3 | Aggregate × fallback ratio | ✅ `agg_lookup[key] * fallback_ratio` | ✅ |
| 4 | Posted estimate × fallback ratio | ✅ `row['posted_time'] * fallback_ratio` | ✅ |

### 3.6 3.5x Weight for Real Actuals

| Location | Expected | Actual | Match? |
|----------|----------|--------|--------|
| `train_v2.jl` | 3.5x real, 1.0x synthetic | `ifelse.(is_synthetic, 1.0f0, 3.5f0)` | ✅ |
| `train_actuals_v2.jl` | 3.5x real, 1.0x synthetic | `ifelse.(entity_df.is_synthetic, 1.0f0, 3.5f0)` | ✅ |
| `calculate_wti_simple.py` | 3.5x real, 1.0x synthetic | `REAL_ACTUAL_WEIGHT = 3.5`, `SYNTHETIC_WEIGHT = 1.0` | ✅ |
| `build_actuals_training_data.py` | N/A (labels only) | `is_synthetic` column stored, weights applied at training time | ✅ |

### 3.7 P95 Cap Removal

| File | Expected | Actual | Match? |
|------|----------|--------|--------|
| `forecast_vectorized.py` | Removed | `p95_cap` parameter passed as `None`; comment "P95 cap REMOVED (2026-02-18)" | ✅ |
| Forecast data | No cap applied | Predictions clipped 0-300 only (sanity bound, not p95) | ✅ |

### 3.8 FastPass/Lightning Lane Exclusion

| Pipeline Step | Expected | Actual | Match? |
|---------------|----------|--------|--------|
| Matched pairs | Exclude fastpass_booth=TRUE | `INNER JOIN valid_entities ... WHERE fastpass_booth = FALSE` | ✅ |
| Forecast | Exclude fastpass_booth=TRUE | `INNER JOIN ... WHERE d.fastpass_booth = FALSE` | ✅ |
| Synthetic actuals | Exclude fastpass_booth=TRUE | ✅ Standby-only filter | ✅ |
| Verified in data | 0 FP entities in forecast | ✅ Confirmed: 0 overlap | ✅ |

---

## 4. Discrepancies and Findings

### 🔴 Finding 1: WTI Missing Forecast Data

**Severity:** HIGH  
**Location:** `wti/wti.parquet`  
**Issue:** WTI file contains only historical data (50,123 rows through 2026-02-18). No forecast WTI for future dates despite forecast file existing (22.8M rows through 2027-02-18).

**Root cause:** The WTI file was last modified 2026-02-18 08:27, but the forecast was regenerated 2026-02-19 00:25. The skip-if-unchanged logic or a manual forecast regeneration caused the WTI step to not re-run after the latest forecast. The forecast data goes up to 2027-02-18, but without running WTI on that data, the pipeline outputs are incomplete.

**Impact:** All downstream consumers (hazeydata.ai, Discord bot, API) cannot show future crowd predictions. Historical analysis works.

**Fix:** Re-run `python scripts/calculate_wti_simple.py --output-base /mnt/data/pipeline` to pick up the latest forecast and generate future WTI.

### 🔴 Finding 2: XGBOOST_PARAMS.md is Stale and Misleading

**Severity:** HIGH  
**Location:** `docs/XGBOOST_PARAMS.md`  
**Issue:** The doc claims to document current Python training parameters aligned with Julia legacy. However:

1. `src/processors/training.py` (the file it references) **no longer exists** — all training is in Julia
2. The parameters listed do NOT match the actual Julia training code
3. Key differences:

| Parameter | Doc says | Julia V2 actual | Julia Actuals actual |
|-----------|----------|-----------------|---------------------|
| `max_depth` | 6 | **10** | **10** |
| `subsample` | 0.5 | **0.8** | **0.8** |
| `colsample_bytree` | 1.0 | **0.8** | **0.8** |
| `min_child_weight` | 10 | **1** | **1** |
| `objective` | reg:absoluteerror | **reg:squarederror** | **reg:squarederror** |
| `early_stopping` | None | **20 rounds** | **20 rounds** |

**Impact:** Anyone reading XGBOOST_PARAMS.md would get wrong information about the models in production. The document gives false confidence about parameter alignment.

**Fix:** Rewrite XGBOOST_PARAMS.md to reflect actual Julia parameters for V2 and Actuals models.

### 🔴 Finding 3: Objective Function Mismatch vs Original Methodology

**Severity:** MEDIUM-HIGH  
**Location:** Julia training scripts  
**Issue:** MODELING_AND_WTI_METHODOLOGY.md §3.4 says "Use `reg:squarederror` or `reg:absoluteerror`" (either acceptable), and XGBOOST_PARAMS.md says `reg:absoluteerror` (MAE). The actual Julia code uses `reg:squarederror` (MSE/RMSE).

This is a deliberate parameter choice, not a bug, but it's undocumented. `reg:squarederror` will be more sensitive to outliers than `reg:absoluteerror`. Given Fred's decision to remove the P95 cap (because models underpredict), using squarederror may actually help — it penalizes large underpredictions more.

**Impact:** Models may behave differently than expected if someone assumes MAE objective. No action needed on the models themselves, but docs should be updated.

### ⚠️ Finding 4: SYNTHETIC_ACTUALS_DESIGN.md Weight Ratio Inconsistency

**Severity:** LOW  
**Location:** `docs/SYNTHETIC_ACTUALS_DESIGN.md` says 5.0:1.0 (real:synthetic), code uses 3.5:1.0  
**Issue:** Fred's 2026-02-18 decision set the ratio to 3.5x (documented in PIPELINE_DATA_FLOW.md), but SYNTHETIC_ACTUALS_DESIGN.md was never updated.

**Fix:** Update SYNTHETIC_ACTUALS_DESIGN.md §"Sample Weighting" from 5.0 to 3.5.

### ⚠️ Finding 5: Forecast Range is ~1 Year, Not 2 Years

**Severity:** MEDIUM  
**Location:** `forecast_vectorized.py`  
**Issue:** Pipeline runs with `--days 730` (2 years), but actual forecast only covers 364 dates (2026-02-20 to 2027-02-18). The time grid only generates slots within park operating hours, and park hours are only available ~1 year out.

**Root cause:** Park hours imputation extends 365 days into the future (configured in `impute_park_hours.py`), and the pipeline passes `--days 730` but dates without park hours get zero time slots and thus zero forecasts.

**Impact:** PIPELINE_DATA_FLOW.md and MODELING_AND_WTI_METHODOLOGY.md both say "2-year forecasts" but reality is ~1 year. Users expecting 2-year coverage will be disappointed.

**Fix:** Either extend park hours imputation to +730 days, or update docs to say "1-year forecasts."

### ⚠️ Finding 6: Historical WTI Doesn't Filter by Operating Calendar

**Severity:** LOW  
**Location:** `calculate_wti_simple.py` historical WTI computation  
**Issue:** The historical WTI section does NOT join with the operating calendar. It uses ALL synthetic actuals and real actuals regardless of whether the entity was operating on that date. The operating calendar is only used for forecast WTI.

**Impact:** If a ride had spurious data on a closed date (e.g., a 0-minute wait recorded as operating), it would be included in historical WTI. In practice, this is rare because closed rides generally have no observations. Low risk.

**Fix:** Optionally add operating calendar join to historical WTI. Low priority.

### ⚠️ Finding 7: WTI POSTED Fallback Still Present in Code

**Severity:** LOW  
**Location:** `calculate_wti_simple.py` lines with `COALESCE(... ACTUAL ... , ... POSTED ...)`  
**Issue:** PIPELINE_DATA_FLOW.md (Decision #1, 2026-02-18) says "Remove WTI fallback to raw POSTED." The fallback path still exists in the `if not synth_available:` branch. This is the `COALESCE` path that uses raw POSTED when synthetic actuals aren't available.

**Impact:** In production, synthetic actuals ARE available, so this branch is never hit. It's dead code. No practical impact, but it should be cleaned up per Fred's decision.

**Fix:** Remove the `if not synth_available:` fallback or make it raise an error instead.

### ⚠️ Bonus Finding: Conversion Model Metadata Incomplete

**Severity:** LOW  
**Location:** `models/_conversion/metadata.json`  
**Issue:** The conversion model metadata file lacks standard fields (objective, test metrics). When I tried to read it, the fields `objective`, `test_mae`, `test_r2` were all missing.

---

## 5. Data File Verification

### Models Directory

| Type | Count | Notes |
|------|-------|-------|
| V2 models (model_julia_v2.json) | 430 | Includes 17 LITE models |
| Actuals models (model_julia_actuals.json) | 58 | ACTUALS-FIRST methodology |
| Total entity directories | 547 | |
| Entities with BOTH V2 and Actuals | ≤58 | Actuals preferred in forecast |

### Matched Pairs

| File | Rows | Date Range | Notes |
|------|------|------------|-------|
| all_pairs_v2.parquet | 2,396,008 | 2009-07-27 to 2026-02-18 | Primary training data |
| combined_pairs_v2.parquet | Present | — | Real + synthetic combined |
| synthetic_pairs_v2.parquet | Present | — | Synthetic only |
| actuals_training_v2.parquet | 92,964,464 | — | ACTUALS-FIRST training |

### Forecast

| File | Rows | Date Range | Methods |
|------|------|------------|---------|
| all_forecasts.parquet | 22,806,103 | 2026-02-20 to 2027-02-18 | model_v2: 68%, fallback_ratio: 20%, model_actuals: 11%, model_lite: <1%, aggregate: <0.1% |

### WTI

| File | Rows | Date Range | Sources |
|------|------|------------|---------|
| wti.parquet | 50,123 | 2009-03-02 to 2026-02-18 | **100% historical** (🔴 no forecast) |

### Operating Calendar

| File | Rows | Entities | Operating Rate |
|------|------|----------|----------------|
| operating_calendar.parquet | 11,203,041 | 1707 | 83% operating / 17% closed |

### Dimension Tables

| File | Size | Status |
|------|------|--------|
| dimentity.csv | 342 KB | ✅ 1707 entities (134 fastpass_booth) |
| dimparkhours.csv | 14,970 KB | ✅ Includes imputed future hours |
| dimdategroupid.csv | 1,254 KB | ✅ |
| dimseason.csv | 280 KB | ✅ |
| dimeventdays.csv | 457 KB | ✅ |
| dimevents.csv | 5 KB | ✅ |
| dimmetatable.csv | 9,420 KB | ✅ |

### State Files

| File | Status | Notes |
|------|--------|-------|
| fallback_ratios.json | ✅ | 272 per-entity + global=0.678 |
| encoding_mappings.json | ✅ | date_group_id, season, season_year mappings |
| entity_index.sqlite | ✅ | Per-entity dirty tracking |
| matched_pairs_state.json | ✅ | Incremental pairing state |

---

## 6. Recommendations

### Immediate Actions

1. **Re-run WTI** to pick up the latest forecast data:
   ```bash
   cd ~/theme-park-crowd-report && source .venv/bin/activate
   python scripts/calculate_wti_simple.py --output-base /mnt/data/pipeline
   ```

2. **Update XGBOOST_PARAMS.md** to reflect actual Julia parameters:
   - V2: max_depth=10, subsample=0.8, colsample_bytree=0.8, min_child_weight=1, objective=reg:squarederror, early_stopping=20
   - Actuals: same as V2
   - Lite: max_depth=6, min_child_weight=3, same others
   - Remove references to `src/processors/training.py` (no longer exists)

3. **Update SYNTHETIC_ACTUALS_DESIGN.md** weight ratio from 5.0 to 3.5.

### Short-Term Improvements

4. **Investigate forecast date range limitation** — Currently ~1 year due to park hours availability. Either extend imputation to +730 days or update all docs saying "2-year forecasts" to "1-year forecasts."

5. **Remove dead POSTED fallback in WTI** — The `if not synth_available:` COALESCE path is dead code per Fred's 2026-02-18 decision. Clean it up.

6. **Add operating calendar filter to historical WTI** — Low priority but would be more methodologically consistent.

### Documentation Cleanup

7. **PIPELINE_DATA_FLOW.md Step 5b** says training hyperparameters are `max_depth=10, eta=0.1, subsample=0.8, colsample_bytree=0.8, early_stopping=20` — this DOES match the actual code. Good. But it conflicts with XGBOOST_PARAMS.md.

8. **PIPELINE_AUDIT_COMPARISON.md** (Barney's audit from 2026-02-18) says "Wilma's doc is highly aligned." This audit confirms that assessment for the data flow, but identifies that the XGBoost params doc is a blind spot.

---

## Verification Checklist Summary

| Item | Status | Notes |
|------|--------|-------|
| Training features: V2 = 7 features | ✅ | posted_time, mins_since_6am, mins_since_open, hour_of_day, date_group_id_encoded, season_encoded, season_year_encoded |
| Training features: Actuals = 5 features | ✅ | No posted_time |
| XGBoost hyperparameters match docs | 🔴 | XGBOOST_PARAMS.md is stale; PIPELINE_DATA_FLOW.md is correct |
| Operating calendar: training filters is_operating=TRUE | ✅ | |
| Operating calendar: forecasting skips closed dates | ✅ | |
| Synthetic actuals methodology | ✅ | Matches SYNTHETIC_ACTUALS_DESIGN.md |
| WTI computation | ✅ | Matches MODELING_AND_WTI_METHODOLOGY.md |
| Forecast fallback chain | ✅ | actuals → V2 → aggregate → fallback_ratio |
| 3.5x weight for real actuals | ✅ | In training AND WTI |
| Park hours filtering in forecasts | ✅ | |
| P95 cap REMOVED | ✅ | Confirmed in code and data |
| FastPass/LL entities excluded | ✅ | 0 in forecast, confirmed |
| Geo decay weight = 0.5^(days/730) | ✅ | Computed at training time |
| Chronological train/val split (85/15) | ✅ | In all Julia scripts |
| Incremental matched pairs | ✅ | Appends new only |
| Label encodings preserved across runs | ✅ | extend_encoding() pattern |
| WTI has forecast data | 🔴 | Missing — needs re-run |
| Forecast covers 2 years | ⚠️ | Only ~1 year due to park hours |
| WTI POSTED fallback removed | ⚠️ | Dead code still present |

---

**End of Audit**  
*Generated 2026-02-19 by Wilma (pipeline methodology audit subagent)*
