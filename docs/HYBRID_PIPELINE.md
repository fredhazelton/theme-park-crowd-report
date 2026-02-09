# Hybrid Pipeline - Best of Both Worlds

**Created:** 2026-02-07  
**Status:** Production (daily cron)

---

## Overview

The hybrid pipeline uses the fastest tool for each step:

| Step | Tool | Why |
|------|------|-----|
| **Matched Pairs** | Python + DuckDB | Vectorized SQL joins across 120M rows |
| **Training** | Julia + XGBoost.jl | 2-3x faster than Python XGBoost |
| **Scoring** | Python | Loads any XGBoost format, integrates with API |

**Total training time: ~2.5 minutes** (was 10+ minutes with Python-only, 75+ minutes before optimizations)

---

## Performance Comparison

| Approach | Matched Pairs | Training | Total |
|----------|---------------|----------|-------|
| **Legacy (sequential Python)** | N/A | 75+ min | 75+ min |
| **Fast Python (parallel)** | 78s | ~10 min | ~12 min |
| **Hybrid (Julia)** | 78s | 67s | **~2.5 min** |

---

## Usage

### Full Pipeline
```bash
cd ~/theme-park-crowd-report
.venv/bin/python scripts/hybrid_pipeline.py
```

### Skip Steps (if already done)
```bash
# Skip matched pairs (use cached)
.venv/bin/python scripts/hybrid_pipeline.py --skip-pairs

# Skip scoring (training only)
.venv/bin/python scripts/hybrid_pipeline.py --skip-scoring

# Training only (skip both)
.venv/bin/python scripts/hybrid_pipeline.py --skip-pairs --skip-scoring
```

### Scoring Hours
```bash
# Score last 48 hours instead of default 24
.venv/bin/python scripts/hybrid_pipeline.py --score-hours 48
```

---

## Integration with Daily Pipeline

The daily cron (`run_daily_pipeline.sh`) calls the hybrid pipeline for training:

```bash
# Step 5 in run_daily_pipeline.sh
run_step "Hybrid training (Julia)" $PYTHON scripts/hybrid_pipeline.py --skip-scoring
```

Full daily pipeline order:
1. ETL sync (S3 → Parquet)
2. Dimensions
3. Posted Aggregates
4. Report
5. **Hybrid Training** ← Julia XGBoost
6. Forecast
7. WTI Calculation

---

## Design Decision: Full Retrain Daily

At 2.5 minutes for a complete training run, **incremental model updates aren't worth the complexity**.

The daily cron does a full retrain every morning:
- Fresh matched pairs from all historical data
- All 141 models rebuilt from scratch
- No stale model drift, no incremental edge cases

**Simple > Clever** when the simple approach takes under 3 minutes.

---

## Why Julia is So Fast

The 67-second training time (vs 10+ minutes in Python) comes from several factors:

| Factor | Python XGBoost | Julia XGBoost |
|--------|----------------|---------------|
| **GIL** | Global Interpreter Lock blocks true parallelism | No GIL — real parallel execution |
| **Compilation** | Interpreted with C extension calls | JIT-compiles to native code |
| **XGBoost bindings** | scikit-learn wrapper adds overhead | Direct libxgboost bindings |
| **Loop overhead** | Python loops are slow | Loops run at C speed |

**The hybrid approach:** Each language does what it's best at:
- **Python/DuckDB** → SQL heavy-lifting (vectorized joins across 120M rows)
- **Julia/XGBoost.jl** → Training (parallel model fitting with no GIL)
- **Python** → Scoring & API (ecosystem integration)

This is why 141 models train in 67 seconds — Julia bypasses all the Python overhead and trains models truly in parallel.

---

## Technical Details

### Step 1: Matched Pairs (Python/DuckDB)

DuckDB runs a vectorized SQL query that:
1. Finds all ACTUAL observations
2. Finds all POSTED observations
3. Joins within 15-minute windows by entity + park_date
4. Picks the closest POSTED for each ACTUAL
5. Adds time-based features (hour, day_of_week, etc.)

**Output:** `/home/wilma/hazeydata/pipeline/matched_pairs/all_pairs.parquet`

**Time:** ~78 seconds for 2.4M matched pairs

### Step 2: Training (Julia/XGBoost.jl)

Julia loads the matched pairs parquet and trains one XGBoost model per entity:
- Minimum 500 observations required
- 85/15 train/validation split (chronological)
- Early stopping after 20 rounds without improvement
- Max 500 trees, depth 6, learning rate 0.1

**Output:** `/home/wilma/hazeydata/pipeline/models/{entity}/model_julia.json`

**Time:** ~67 seconds for 141 models (0.48s per entity)

### Step 3: Scoring (Python)

Python loads trained models and scores recent POSTED observations:
- Gets POSTED data from last N hours
- Loads model (Julia or Python format - both work)
- Predicts ACTUAL wait time
- Falls back to 82% ratio for entities without models

**Output:** Predictions served via API at `localhost:8051`

---

## Files

| File | Purpose |
|------|---------|
| `scripts/hybrid_pipeline.py` | Main orchestrator |
| `julia-ml/train_only.jl` | Julia training script |
| `julia-ml/Project.toml` | Julia dependencies |
| `scripts/score_fast.py` | Python scoring |

---

## Julia Setup

Julia 1.10.2 installed at `~/julia-1.10.2/bin/julia`

Dependencies (managed via Project.toml):
- DataFrames
- Parquet2
- XGBoost
- JSON3
- OrderedCollections

To update Julia packages:
```bash
cd ~/theme-park-crowd-report/julia-ml
~/julia-1.10.2/bin/julia --project=. -e 'using Pkg; Pkg.update()'
```

---

## Model Compatibility

Julia XGBoost saves models as JSON (`model_julia.json`). Python XGBoost can load these directly:

```python
import xgboost as xgb
model = xgb.XGBRegressor()
model.load_model("model_julia.json")  # Works!
```

Both model formats are interchangeable for scoring.

---

## Monitoring

Logs saved to: `/home/wilma/hazeydata/pipeline/logs/hybrid_pipeline_*.log`

Dashboard API health: `curl http://localhost:8051/api/health`

Training results summary printed at end:
```
============================================================
HYBRID PIPELINE COMPLETE
============================================================
  Matched pairs: 2,393,511
  Models trained: 141
  Predictions: 12,345
  ⏱️  Total time: 160.5s
============================================================
```
