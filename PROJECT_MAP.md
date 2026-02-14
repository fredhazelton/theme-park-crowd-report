# PROJECT MAP

**Read this at the start of every session.** This is the index to the project — where things live, what's canonical, and what NOT to duplicate.

Last updated: 2026-02-14

---

## Canonical Documentation

**One doc per concern. Update the canonical doc, not a secondary one.**

| Topic | Canonical Doc | Notes |
|-------|---------------|-------|
| **Full pipeline data flow** | `docs/PIPELINE_DATA_FLOW.md` | ⭐ MASTER DOC. All stages, schemas, timing, TODOs. Update HERE first. |
| **Methodology & WTI** | `docs/MODELING_AND_WTI_METHODOLOGY.md` | Statistical methodology, WTI formula, design decisions |
| **Architecture & data access** | `docs/ARCHITECTURE.md` | DuckDB patterns, file layout, "how to read data" |
| **Entity system** | `docs/ENTITY_SYSTEM.md` | Entity codes, park mappings, canonical entity list |
| **Entity index (dirty tracking)** | `docs/ENTITY_INDEX.md` | SQLite schema, dirty detection, mark_entity_modeled |
| **Closures & operating calendar** | `docs/CLOSURES_MODULE_SPEC.md` | Closure sources, operating calendar build logic |
| **Pipeline skip logic** | `docs/PIPELINE_STATE.md` | --skip-if-unchanged, dirty entity cascade |
| **Column naming** | `docs/COLUMN_NAMING_STANDARD.md` | Standard column names across all tables |
| **Schemas** | `docs/SCHEMAS.md` | Fact table, prediction, forecast schemas |
| **Predictions API** | `docs/PREDICTIONS-API.md` | API endpoints, request/response format |
| **XGBoost params** | `docs/XGBOOST_PARAMS.md` | Hyperparameters and rationale |
| **Synthetic actuals** | `docs/SYNTHETIC_ACTUALS_DESIGN.md` | POSTED→ACTUAL conversion model design |
| **Park hours** | `docs/PARK_HOURS_VERSIONING.md` | Versioned park hours system |
| **Stream overlay** | `docs/stream/STREAM-OVERLAY-SPECS.md` | Twitch/YouTube stream overlay layout |

## Before Changing Code

1. **Check for TODOs:** `grep -rn "TODO\|FIXME\|future optimization" docs/` for anything related to your change
2. **Update the canonical doc** listed above — not a secondary file
3. **If a TODO is resolved**, mark it ✅ with date in the doc

## Key Scripts

| Script | Purpose | Called by |
|--------|---------|----------|
| `scripts/run_daily_pipeline.sh` | Master daily orchestrator | Cron (6am ET) |
| `scripts/hybrid_pipeline_v2.py` | Matched pairs + training | run_daily_pipeline.sh step 5 |
| `julia-ml/train_v2.jl` | Julia XGBoost training | hybrid_pipeline_v2.py |
| `src/build_operating_calendar.py` | Operating calendar (incremental) | run_daily_pipeline.sh step 2a |
| `src/processors/entity_index.py` | Entity dirty tracking (SQLite) | ETL + training |
| `scripts/pipeline_state.py` | Skip-if-unchanged decisions | run_daily_pipeline.sh |
| `scripts/forecast_vectorized.py` | Generate forecasts | run_daily_pipeline.sh step 6 |
| `scripts/calculate_wti_simple.py` | WTI calculation | run_daily_pipeline.sh step 7 |

## Key Data Locations

| What | Path | Format |
|------|------|--------|
| Fact tables | `/mnt/data/pipeline/fact_tables/parquet/` | Monthly parquet |
| Matched pairs | `/mnt/data/pipeline/matched_pairs/all_pairs_v2.parquet` | Single parquet (cumulative) |
| Models | `/mnt/data/pipeline/models/{entity}/model_julia_v2.json` | XGBoost JSON |
| Operating calendar | `/mnt/data/pipeline/operating_calendar/operating_calendar.parquet` | Single parquet |
| State | `/mnt/data/pipeline/state/` | SQLite + JSON |
| Logs | `/mnt/data/pipeline/logs/` | Daily logs |
| Forecasts | `/mnt/data/pipeline/forecasts/` | Parquet |

## State Files (Pipeline Memory)

| File | Purpose |
|------|---------|
| `state/entity_index.sqlite` | Per-entity: latest observation, last modeled, row counts |
| `state/matched_pairs_state.json` | `last_paired_at` for incremental pairing |
| `state/encoding_mappings.json` | Label encodings for categorical features |
| `state/fallback_ratios.json` | Dynamic ACTUAL/POSTED ratios per entity |
| `state/entities_to_train.txt` | Dirty entity list (written by Python, read by Julia) |

## Docs NOT to Create

These topics are already covered. Don't create new files for them:
- Pipeline timing → `PIPELINE_DATA_FLOW.md` (timing tables section)
- Training details → `PIPELINE_DATA_FLOW.md` (Stage 3)
- Matched pairs → `PIPELINE_DATA_FLOW.md` (Stage 2)
- Skip logic → `PIPELINE_STATE.md`
- Hybrid pipeline → Deleted. Merged into `PIPELINE_DATA_FLOW.md`

## Docs Likely Stale (Review Before Trusting)

| Doc | Why |
|-----|-----|
| `TRAINING_OPTIMIZATION.md` | Written pre-V2, may have outdated recommendations |
| `PIPELINE_TIMING_AND_PARALLELIZATION.md` | Timing numbers from pre-incremental era |
| `LEGACY_PIPELINE_CRITICAL_REVIEW.md` | About old Attraction-IO pipeline |
| `CLEANUP_PLAN.md` | May have completed items not checked off |
| `REFRESH_READINESS.md` | Snapshot from a specific date |

---

## For Wilma: Session Startup Checklist

Every session involving pipeline work:
1. Read this file
2. If changing code: `grep -rn "TODO\|FIXME" docs/` for related items
3. Update `PIPELINE_DATA_FLOW.md` if any pipeline behavior changes
4. If you're unsure which doc to update → it's `PIPELINE_DATA_FLOW.md`
