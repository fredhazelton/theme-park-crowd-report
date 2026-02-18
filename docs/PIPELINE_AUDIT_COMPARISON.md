# Pipeline Audit Comparison

**Date:** 2026-02-18 (updated after Wilma's 2026-02-18 doc refresh)  
**Author:** Barney (independent audit)  
**Purpose:** Compare audit of `run_daily_pipeline.sh` and codebase against Wilma's `PIPELINE_DATA_FLOW.md` to verify alignment.

---

## 1. Full Pipeline Order (from `run_daily_pipeline.sh`)

| # | Step | Script / Command | Notes |
|---|------|-----------------|-------|
| 0 | S3 Sync | `sync_s3_data.sh` | wait_times + fastpass_times → output_base/raw |
| 1 | ETL | `run_etl.sh` → `get_tp_wait_time_data_from_s3.py` | Reads from raw only (sync-only) |
| 1b | CSV→Parquet | `convert_to_parquet.py` | After ETL; needed by WTI, forecasts, posted aggregates |
| 2 | Dimension fetches | `run_dimension_fetches.sh` | 6 sub-scripts (entity, park hours, events, metatable, dimdategroupid, dimseason) |
| 2a | Closures | `get_closures_from_s3.py` + `build_operating_calendar.py` | S3 closures → operating_calendar.parquet |
| 2b | Impute park hours | `impute_park_hours.py` | Fills missing future hours from donor pool |
| 3 | Posted aggregates | `build_posted_aggregates_fast.py` | Monthly parquet, ~7s |
| 4 | Wait time DB report | `report_wait_time_db.py` | wait_time_db_report.md |
| 4b | Forecast accuracy evaluation | `evaluate_forecast_accuracy.py` | **BEFORE** new forecasts; compares prior forecast vs fresh actuals |
| 4c | Synthetic actuals | `generate_synthetic_actuals.py` | For dashboard curves; NOT used for training by default |
| 5 | Training | `hybrid_pipeline_v2.py --skip-scoring` | Matched pairs + Julia XGBoost |
| 6 | Forecast | `forecast_vectorized.py --days 730` | 2-year predictions |
| 7 | WTI | `calculate_wti_simple.py` | Park-level wait time index |
| — | Landing chart | `generate_landing_chart.py` | MK 7-day chart |
| — | Year-view export | `export_year_view_data.py` | Deploy to hazeydata.ai |
| — | Validation | `validate_pipeline_output.py` | Post-run data quality |
| — | Dashboard restart | Restart `dashboard/api.py` | Pick up new data |

---

## 2. Comparison: Wilma's Doc (2026-02-18) vs Actual Code

### ✅ Full Alignment

Wilma's latest doc (post-2026-02-18 audit) now documents:

| Item | Doc Section | Status |
|------|-------------|--------|
| CSV→Parquet conversion | Step 1b | ✅ |
| Closures module (get_closures + build_operating_calendar) | Step 2a | ✅ |
| Dimension fetches (all 6 sub-scripts) | Step 2 | ✅ |
| Forecast accuracy evaluation | Step 4b | ✅ |
| Synthetic actuals generation | Step 4c | ✅ |
| WTI: synthetic + real actuals (3.5:1 weighting) | Step 7 | ✅ |
| WTI fallback (COALESCE when no synthetic) | Step 7 | ✅ |
| Post-pipeline: landing chart, year-view, validation, API restart | Step 8 | ✅ |
| Forecast fallback ratio from `fallback_ratios.json` (~0.678) | Step 6, Dynamic Fallback | ✅ |
| Forecast timing (~8 min) | Pipeline Timing | ✅ |
| Skip-if-unchanged cascade | Dedicated section | ✅ |
| Model type detection (lite vs full V2) | Step 6 | ✅ |
| WTI adaptive bias correction | Step 7 | ✅ |
| WTI deduplication (historical wins) | Step 7 | ✅ |
| `daily_accuracy_report.py`, `entity_wti_diagnostics.py` | Utility scripts | ✅ |

### ⚠️ Minor Discrepancies

| Item | Doc | Code / Other Docs | Notes |
|------|-----|-------------------|-------|
| **Cron flags** | `--skip-dropbox-check --skip-if-unchanged --use-synthetic` | PIPELINE_STATE.md: `--skip-dropbox-check --skip-if-unchanged` (no `--use-synthetic`) | Doc says production uses `--use-synthetic`; PIPELINE_STATE doesn't list it. Verify which is correct for wilma-server. |
| **Operating Calendar timing table** | Lists "Operating Calendar \| build_operating_calendar.py \| ~9s" | Closures module = get_closures + build_operating_calendar | Naming is fine; get_closures is typically fast, build does the work. |

### 📋 Items Correctly Flagged as TODOs / Questions

The doc correctly identifies these as open items:

| Item | Doc Location |
|------|--------------|
| `build_model_aggregates.py` not in daily pipeline | TODO #1, Question #2 |
| `compute_park_wti_distributions.py` not in daily pipeline | TODO #4 |
| WTI fallback path (POSTED when no synthetic) — bootstrap vs remove? | Question #1 |
| Synthetic actuals weight (3.5×) — calibrated? | Question #6 |
| Conversion model retraining schedule | TODO #3, Question #5 |

---

## 3. Verification Summary

| Category | Count |
|----------|-------|
| Steps in doc matching `run_daily_pipeline.sh` | 17/17 |
| Previously identified gaps | 0 (all addressed) |
| Previously identified discrepancies | 0 (WTI, fallback ratio, timing all fixed) |
| Minor cross-doc inconsistencies | 1 (cron `--use-synthetic` vs PIPELINE_STATE) |
| Open TODOs / Questions | 8 (appropriately flagged) |

---

## 4. Conclusion

**Wilma's 2026-02-18 doc is now highly aligned with the codebase.** The pipeline flow, step order, scripts, WTI logic (synthetic+actual), forecast fallback, and post-pipeline outputs are all accurately documented. The Questions for Fred and TODOs sections appropriately capture remaining decisions and improvements.

**Recommended follow-up:** Confirm whether production cron uses `--use-synthetic` and update PIPELINE_STATE.md or PIPELINE_DATA_FLOW.md so they match.
