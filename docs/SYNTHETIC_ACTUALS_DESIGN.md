# Synthetic Actuals: Design Document

**Date:** 2026-02-11  
**Status:** Approved for implementation  
**Authors:** Fred & Wilma (brainstorming session)

---

## Problem Statement

Active rides have ~100-250 ACTUAL observations but 10K-14K+ POSTED observations. The 500 ACTUAL threshold means most active rides can't train entity-specific XGBoost models. The without-POSTED (forecast) models have near-zero R² because there isn't enough training data to learn seasonal, day-of-week, and time-of-day patterns.

## Solution: Synthetic Actuals

Build a POSTED→ACTUAL conversion model from matched pairs, then convert all historical POSTED observations to "synthetic actuals." Combine real + synthetic actuals (with sample weights) to train forecast models with 50x more training data.

## Domain Knowledge (from Fred)

1. **POSTED > ACTUAL almost always.** Disney intentionally overestimates as a guest satisfaction buffer.
2. **The padding isn't constant** — varies by ride, time of day, crowd level, cast member behavior.
3. **POSTED is a lagging indicator.** Cast members update manually, slow to react to queue changes.
4. **The trend matters:**
   - POSTED rising fast → queue filling faster than cast member reacts → ACTUAL closer to or above POSTED
   - POSTED falling → queue drained but cast member slow to reduce → ACTUAL well below POSTED
   - POSTED flat → cast member and reality converged → POSTED closest to ACTUAL

## Conversion Model Architecture

### Target
```
ACTUAL = f(POSTED, rolling_context, time_features, entity_features, date_features)
```

### Features

**Primary:**
- `posted_wait` — the matched POSTED value

**Rolling/Trend (captures lag dynamics):**
- `posted_delta_15m` — change in POSTED over prior 15 min
- `posted_delta_30m` — change in POSTED over prior 30 min
- `posted_delta_60m` — change in POSTED over prior 60 min
- `posted_rolling_mean_30m` — avg POSTED over prior 30 min
- `posted_rolling_mean_60m` — avg POSTED over prior 60 min
- `posted_volatility_30m` — std dev of POSTED over prior 30 min
- `posted_trend_direction` — categorical: rising / falling / flat
- `posted_acceleration` — is rate of change itself changing?

**Time Context:**
- `mins_since_park_open`
- `mins_since_6am`
- `hour_of_day`
- `is_peak_hours` (11am-3pm)

**Entity:**
- `entity_code` (categorical, label-encoded)
- `park_code`

**Date/Demand:**
- `dategroupid`
- `season`

### Model: XGBoost with `reg:absoluteerror` (MAE objective)

### Training: Global model across all entities, all matched pairs pooled.

**Why global, not per-entity?** (Documented 2026-03-04 per Fred's request)
- Many entities have <500 matched pairs — per-entity conversion models would be impossible for most
- The POSTED→ACTUAL relationship has shared structure across entities (Disney's overestimation buffer, lag patterns, time-of-day effects). A global model learns these shared patterns and then specializes via `entity_encoded` feature (272 unique values)
- Per-entity conversion models would be 272 separate models to maintain and retrain monthly
- The global model with entity as a feature effectively approximates per-entity behavior — XGBoost splits on entity when the ratio differs meaningfully between rides
- Alternative considered but not pursued: per-park models (9 models) could capture park-specific posting behaviors; may revisit if global model accuracy plateaus

### Validation: Chronological hold-out (most recent 20% of dates). Report MAE, bias, calibration by decile. Check per-entity, per-time-of-day.

## Sample Weighting in Forecast Training

When training the forecast model (without-POSTED) on combined data:
- Real ACTUAL observations: weight = 5.0
- Synthetic actuals: weight = 1.0

XGBoost supports `sample_weight` natively.

## Implementation Plan

### New Files
- `src/processors/posted_to_actual.py` — Conversion model module
- `src/processors/synthetic_actuals.py` — Generator module
- `scripts/train_conversion_model.py` — CLI wrapper
- `scripts/generate_synthetic_actuals.py` — CLI wrapper

### Modified Files
- `src/processors/training.py` — Add `use_synthetic` flag + sample weights

### Output Locations
- `models/_conversion/model.json` — Conversion model
- `models/_conversion/metadata.json` — Validation metrics
- `synthetic_actuals/{entity_code}.parquet` — Per-entity synthetic actuals

### Rollout Phases
1. Build & validate conversion model (standalone, zero pipeline risk)
2. Generate synthetic actuals & spot-check (zero pipeline risk)
3. A/B training comparison (minimal risk, flag-controlled)
4. Production toggle

## Competitive Advantage

No competitor (including TouringPlans) models the systematic bias in posted wait times. This methodology:
- Accounts for intentional overestimation buffer
- Accounts for human lag in updating posted times
- Uses rolling trend analysis for context-aware conversion
- Produces 50x more training data than raw ACTUAL observations alone

---

## Implementation Results (2026-02-11)

**Status:** Phase 1 & 2 COMPLETE ✅

### Architecture
Both modules use **DuckDB + Parquet** (matching `hybrid_pipeline_v2` pattern). Window functions compute rolling features in-database. No CSV loops.

### Phase 1: Conversion Model

**⚠️ UPDATED 2026-03-04:** Original model was retrained with improved hyperparameters and geo-decay weighting. See below for details.

**Original model (2026-02-11):**
- **2,394,589** matched (POSTED, ACTUAL) pairs across **272 entities**
- Date range: 2009-07-27 to 2026-02-11
- Chronological split: 70% train / 15% val / 15% test
- XGBoost with `reg:absoluteerror`, 2000 rounds, early stopping at 50
- ⚠️ **No geo-decay weighting** — all historical data weighted equally
- ⚠️ Over-regularized: `min_child_weight=10`, `subsample=0.5` → model stopped at only 19 trees

| Metric | Original (Feb 11) |
|--------|-------------------|
| MAE | 10.89 min |
| RMSE | 16.91 min |
| R² | 0.381 |
| Bias | -0.52 min |
| Trees used | **19 of 2000** |

Despite the near-zero test bias, the model systematically overestimated synthetic actuals in production. Root cause: the POSTED→ACTUAL ratio has shifted over time (0.72–0.82 historically vs 0.58–0.70 in recent years for many entities), and without geo-decay the model learned a blended average. Combined with extreme regularization (only 19 trees), it couldn't capture entity-specific or temporal patterns.

**Retrained model (2026-03-04):**
- Same matched pairs data, now with **geo-decay sample weights** (730-day half-life)
- Hyperparams aligned with per-entity models: `max_depth=8`, `min_child_weight=3`, `subsample=0.8`, `colsample_bytree=0.8`, `early_stopping=20`
- See `docs/XGBOOST_PARAMS.md` for full parameter comparison

### Phase 2: Synthetic Actuals Generation
- **433 entities** processed (all with ≥500 POSTED observations)
- **90,238,830 synthetic rows** generated
- Processing chunked by park (11 chunks) to stay within 62GB RAM
- Total output: 1.0 GB parquet

| Metric | Value |
|--------|-------|
| Avg POSTED input | 26.9 min |
| Avg synthetic actual | 18.6 min |
| Avg reduction | 8.3 min |
| Generation time | 481 seconds |

### Files
- `src/processors/posted_to_actual.py` — Conversion model (DuckDB)
- `src/processors/synthetic_actuals.py` — Generator (DuckDB, chunked by park)
- `scripts/train_conversion_model.py` — CLI wrapper
- `scripts/generate_synthetic_actuals.py` — CLI wrapper
- `src/processors/training.py` — Modified with `use_synthetic` flag + sample weights

### Output Locations
- `models/_conversion/model.json` — XGBoost conversion model
- `models/_conversion/metadata.json` — Metrics + encodings
- `synthetic_actuals/{entity_code}.parquet` — Per-entity synthetic actuals
- `synthetic_actuals/generation_summary.json` — Run summary

### Phase 3: TODO (Target: February 19, 2026)
- Collecting baseline accuracy data Feb 12-18 (current method without synthetic actuals)
- On Feb 19: integrate synthetic actuals into daily pipeline
- A/B comparison: retrain entity models with vs without synthetic actuals
- Measure forecast accuracy improvement against baseline
- Production toggle in `hybrid_pipeline_v2.py`

### Pre-Synthetic Baseline Fixes (2026-02-14)
Before switching to synthetic actuals, we fixed several issues in the current pipeline:
1. **FastPass/Lightning Lane filter:** 134 `fastpass_booth=TRUE` entities were being modeled as standby waits. Added `dimentity.csv` join + filter to forecast, training, and aggregate builder.
2. **Aggregate fallback applies ratio:** Was using raw posted median as predicted actual (over-predicts). Now applies `posted_median × entity_ratio` to convert posted → actual estimate.
3. **Default posted estimate:** Changed from 30 → 5 minutes for entities with zero aggregate data (sparse entities are low-wait).

These fixes establish a cleaner baseline for the Feb 19 synthetic actuals comparison.
