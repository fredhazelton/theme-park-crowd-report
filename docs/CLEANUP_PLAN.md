# Pipeline Cleanup Plan

**Date:** 2026-02-09  
**Status:** Ready for review

## Current Pipeline (KEEP)

### Shell Scripts (7)
```
scripts/run_daily_pipeline.sh     # Master orchestrator
scripts/run_etl.sh                # ETL step
scripts/run_dimension_fetches.sh  # Dimension fetches
scripts/run_queue_times_loop.sh   # Live queue-times collector
scripts/common.sh                 # Shared functions
```

### Python Scripts - Pipeline Core (12)
```
scripts/build_posted_aggregates_fast.py   # Posted aggregates
scripts/build_model_aggregates.py         # Model aggregates (fallback data)
scripts/calculate_wti_simple.py           # WTI calculation
scripts/forecast_vectorized.py            # Forecast generation
scripts/hybrid_pipeline_v2.py             # Training (matched pairs + Julia)
scripts/impute_park_hours.py              # Park hours imputation
scripts/pipeline_state.py                 # Skip-if-unchanged state tracking
scripts/report_wait_time_db.py            # DB coverage report
scripts/update_pipeline_status.py         # Status tracking
scripts/cleanup_logs.py                   # Log maintenance
scripts/check_prerequisites.py            # Dependency checks
scripts/convert_to_parquet.py             # CSV→Parquet conversion
```

### Python Scripts - ETL/Dimensions (src/) (9)
```
src/get_tp_wait_time_data_from_s3.py      # Main ETL
src/get_wait_times_from_queue_times.py    # Live queue-times
src/get_entity_table_from_s3.py           # Entity dimension
src/get_park_hours_from_s3.py             # Park hours dimension
src/get_events_from_s3.py                 # Events dimension
src/get_metatable_from_s3.py              # Metatable dimension
src/build_dimdategroupid.py               # Date group dimension
src/build_dimseason.py                    # Season dimension
src/__init__.py                           # Package init
```

### Julia (1)
```
julia-ml/train_v2.jl                      # V2 XGBoost training
```

### Config/Docs (KEEP)
```
config/config.json
docs/PIPELINE_DATA_FLOW.md
docs/README.md
```

---

## REMOVE - Legacy Scripts (30+)

### Old Training Scripts
```
scripts/hybrid_pipeline.py          # Replaced by hybrid_pipeline_v2.py
scripts/train_and_score_pipeline.py # Old pipeline
scripts/train_and_score_simple.py   # Old approach
scripts/train_batch_entities.py     # Old batch training
scripts/train_entity_model.py       # Old single-entity
scripts/train_fast.py               # Old fast training
scripts/train_global_model.py       # Abandoned approach
scripts/test_modeling_pipeline.py   # Old tests
```

### Old Forecast Scripts
```
scripts/generate_forecast.py        # Replaced by forecast_vectorized.py
scripts/generate_forecast_fast.py   # Replaced
scripts/generate_backfill.py        # One-time backfill
scripts/run_30day_backfill.py       # One-time
scripts/run_full_backfill.py        # One-time
```

### Old Scoring Scripts
```
scripts/score_fast.py               # Replaced by hybrid_pipeline_v2
scripts/score_historical.py         # Replaced
```

### Old Aggregate Scripts
```
scripts/build_posted_aggregates.py  # Replaced by _fast version (crashes)
```

### Old WTI Scripts
```
scripts/calculate_wti.py            # Replaced by calculate_wti_simple.py
scripts/compute_wti_from_facts.py   # Replaced
```

### Utility/Debug Scripts (evaluate case-by-case)
```
scripts/daily_pipeline_fast.py      # Old fast mode - replaced by --skip-if-unchanged
scripts/run_dev_pipeline.py         # Dev helper - may still be useful?
scripts/check_batch_status.py       # Debug
scripts/check_training_status.py    # Debug
scripts/find_entities_with_actual.py # One-time analysis
scripts/inspect_entity_index.py     # Debug
scripts/test_encoding.py            # Debug
scripts/test_features.py            # Debug
scripts/report_park_hours_donor_accuracy.py  # One-time
scripts/report_posted_accuracy.py   # One-time
scripts/report_queue_times_unmapped.py       # One-time
scripts/validate_wait_times.py      # One-time
scripts/fetch_figma_node.py         # UI helper
scripts/fix_peak_color.py           # One-time fix
```

---

## REMOVE - Legacy Directories

### pipeline_dev/
Old development output directory. All outputs now go to `/home/wilma/hazeydata/pipeline`.

### julia/
Old Julia directory. Replaced by `julia-ml/`.

### temp/
Empty temp directory.

### dimension_tables/
Old local dimension tables. Now in `/home/wilma/hazeydata/pipeline/dimension_tables`.

### data/
Only contains `school_schedules/` - evaluate if still needed.

---

## REMOVE - Legacy Julia Scripts

```
julia-ml/train_fast.jl              # Replaced by train_v2.jl
julia-ml/train_only.jl              # Replaced by train_v2.jl
```

---

## REMOVE - Legacy src/ Scripts

```
src/build_entity_index.py           # Not used
src/build_park_hours_donor.py       # Replaced by impute_park_hours.py
src/clean_all_dimensions.py         # Not used
src/clean_dimentity.py              # Not used
src/clean_dimeventdays.py           # Not used
src/clean_dimevents.py              # Not used
src/clean_dimmetatable.py           # Not used
src/clean_dimparkhours.py           # Not used
src/inspect_dimension_tables.py     # Debug
src/migrate_park_hours_to_versioned.py  # One-time migration
```

---

## Summary

| Category | Keep | Remove |
|----------|------|--------|
| Shell scripts | 5 | 0 |
| Python scripts (scripts/) | 12 | ~30 |
| Python scripts (src/) | 9 | ~10 |
| Julia scripts | 1 | 2 |
| Directories | 7 | 4 |

**Total files to remove:** ~46  
**Directories to remove:** 4 (pipeline_dev, julia, temp, dimension_tables)
