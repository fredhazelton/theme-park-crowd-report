# Pipeline Audit Comparison

**Date:** 2026-02-18  
**Author:** Barney (independent audit)  
**Purpose:** Compare audit of `run_daily_pipeline.sh` and codebase against Wilma's `PIPELINE_DATA_FLOW.md` to verify alignment.

---

## 1. Full Pipeline Order (from `run_daily_pipeline.sh`)

| # | Step | Script / Command | Notes |
|---|------|-----------------|-------|
| 0 | S3 Sync | `sync_s3_data.sh` | wait_times + fastpass_times → output_base/raw |
| 1 | ETL | `run_etl.sh` → `get_tp_wait_time_data_from_s3.py` | Reads from raw only (sync-only) |
| 1b | **CSV→Parquet** | `convert_to_parquet.py` | After ETL; needed by WTI, forecasts, posted aggregates |
| 2 | Dimension fetches | `run_dimension_fetches.sh` | get_entity, get_park_hours, get_events, get_metatable, build_dimdategroupid, build_dimseason |
| 2a | **Closures** | `get_closures_from_s3.py` + `build_operating_calendar.py` | S3 closures → operating_calendar.parquet |
| 2b | Impute park hours | `impute_park_hours.py` | Fills missing future hours from donor pool |
| 3 | Posted aggregates | `build_posted_aggregates_fast.py` | Monthly parquet, ~7s |
| 4 | Wait time DB report | `report_wait_time_db.py` | wait_time_db_report.md |
| 4b | **Forecast accuracy evaluation** | `evaluate_forecast_accuracy.py` | **BEFORE** new forecasts; compares prior forecast vs fresh actuals |
| 4c | **Synthetic actuals** | `generate_synthetic_actuals.py` | For dashboard curves; NOT used for training yet |
| 5 | Training | `hybrid_pipeline_v2.py --skip-scoring` | Matched pairs + Julia XGBoost |
| 6 | Forecast | `forecast_vectorized.py --days 730` | 2-year predictions |
| 7 | WTI | `calculate_wti_simple.py` | Park-level wait time index |
| — | Landing chart | `generate_landing_chart.py` | MK 7-day chart |
| — | Year-view export | `export_year_view_data.py` | Deploy to hazeydata.ai |
| — | Validation | `validate_pipeline_output.py` | Post-run data quality |
| — | Dashboard restart | Restart `dashboard/api.py` | Pick up new data |

---

## 2. Comparison: Wilma's Doc vs Actual Code

### ✅ Matches (accurate)

| Item | Status |
|------|--------|
| S3 sync, ETL, dimensions, impute park hours, aggregates, report, training, forecast, WTI order | ✅ Correct |
| `sync_s3_data.sh` PATH fix for AWS CLI | ✅ Documented |
| `build_posted_aggregates_fast.py` vs deprecated `build_posted_aggregates.py` | ✅ Documented |
| `forecast_vectorized.py` vs deprecated `generate_forecast.py` | ✅ Documented |
| `hybrid_pipeline_v2.py` vs V1 | ✅ Documented |
| Incremental matched pairs, training (dirty only), encoding mappings | ✅ Documented |
| Geo decay at training time (not in pairs) | ✅ Documented |
| Skip-if-unchanged cascade (training → forecast → WTI) | ✅ Documented |
| Dimension tables (dimdategroupid, dimseason, dimparkhours) | ✅ Documented |
| Model aggregates, fallback priority (model → aggregate → ratio) | ✅ Documented |
| Data volumes, API endpoints, scripts reference | ✅ Generally accurate |

### ⚠️ Gaps (missing from Wilma's doc)

| Gap | Detail |
|-----|--------|
| **CSV→Parquet conversion** | Step 1b runs after ETL. Not mentioned in pipeline flow or daily cron table. |
| **Closures module** | Doc mentions "Operating Calendar" but not `get_closures_from_s3.py` (runs before `build_operating_calendar.py`). |
| **Forecast accuracy evaluation** | Runs at step 4b, before new forecasts. Compares prior forecast vs actuals; writes to `accuracy/`. Not documented. |
| **Synthetic actuals in pipeline** | Runs at step 4c. Doc mentions synthetic actuals in Stage 4c text but not in the daily cron / pipeline flow table. |
| **Landing chart + year-view export** | Run after WTI; not in pipeline flow. |
| **Validation + dashboard restart** | Post-run steps; not in pipeline flow. |
| **Dimension fetches breakdown** | Doc says "Dimensions" but doesn't list the 6 scripts: get_entity, get_park_hours, get_events, get_metatable, build_dimdategroupid, build_dimseason. |

### ⚠️ Discrepancies (doc differs from code)

| Item | Wilma's Doc | Actual Code |
|------|-------------|-------------|
| **WTI historical source** | "ACTUAL preferred, POSTED fallback" | **Synthetic actuals + real ACTUAL** (weighted: real=3.5, synth=1.0). Falls back to COALESCE(ACTUAL, POSTED) only if synthetic_actuals unavailable. |
| **Forecast fallback ratio** | "posted_estimate × 0.82" | Uses `state/fallback_ratios.json` → `__global__` (typically **0.678**). `DEFAULT_FALLBACK_RATIO = 0.678` in code. |
| **Forecast script timing** | "~8 min" | Doc also says "~40 min" in Scripts Reference table (line 533). Inconsistent. |

### 📋 New scripts (from latest pull, not in doc)

| Script | Purpose |
|--------|---------|
| `daily_accuracy_report.py` | Daily accuracy report (standalone) |
| `entity_wti_diagnostics.py` | Entity-level WTI diagnostics (standalone) |

---

## 3. Recommendations for PIPELINE_DATA_FLOW.md

1. **Add missing steps to daily cron / pipeline flow:**
   - CSV→Parquet (after ETL)
   - Closures: get_closures_from_s3 + build_operating_calendar
   - Forecast accuracy evaluation (before forecast)
   - Synthetic actuals generation
   - Landing chart, year-view export, validation, dashboard restart

2. **Update WTI section:**
   - Historical WTI: synthetic actuals + real actuals (weighted) when available; fallback to ACTUAL/POSTED from fact tables.

3. **Fix forecast fallback ratio:**
   - Change "0.82" to "from fallback_ratios.json (__global__ typically 0.678)".

4. **Reconcile forecast timing:**
   - Use single value (~8 min for 159M predictions) and remove "~40 min" from Scripts Reference.

5. **Optional:** Add "Other scripts" subsection for `daily_accuracy_report.py` and `entity_wti_diagnostics.py` (diagnostic tools, not in daily pipeline).

---

## 4. Summary

Wilma's doc is **substantially accurate** for the core data flow (fact tables → matched pairs → training → forecast → WTI) and the critical "use this / don't use that" guidance. The main gaps are:

- **Pipeline flow completeness:** Several steps (CSV→Parquet, closures, forecast accuracy, synthetic actuals, landing chart, year-view, validation) are not in the documented flow.
- **WTI logic:** The doc describes the old ACTUAL/POSTED fallback; the code now uses synthetic+actual blend.
- **Minor:** Fallback ratio (0.82 vs 0.678) and forecast timing inconsistency.

No major logic errors were found. The pipeline does what the doc describes for the core path; the doc needs updates to reflect recent additions and WTI changes.
