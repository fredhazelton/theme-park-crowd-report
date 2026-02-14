# Hybrid Pipeline V2 - Incremental & Cumulative

**Created:** 2026-02-07  
**Updated:** 2026-02-14 (incremental pairs, training, operating calendar)  
**Status:** Production (daily cron at 6am ET)

---

## Overview

The hybrid pipeline uses the fastest tool for each step:

| Step | Tool | Why |
|------|------|-----|
| **Matched Pairs** | Python + DuckDB | Vectorized SQL joins across 120M rows |
| **Training** | Julia + XGBoost.jl | 2-3x faster than Python XGBoost |
| **Scoring** | Python | Loads any XGBoost format, integrates with API |

---

## Core Principles (Updated 2026-02-14)

**Everything is incremental and cumulative:**
- **Matched pairs:** Only pair new ACTUAL observations; append to existing file
- **Training:** Only retrain entities with new data since last training
- **Operating calendar:** Only refresh recent window; historical dates are stable
- **Geo decay weights:** Computed at training time (not stored in pairs)

**Retraining trigger:** Any new observation for an entity → retrain. No minimum count threshold beyond the 500-pair eligibility gate. One new pair is enough.

---

## Performance

### Daily Incremental Run (typical)
| Step | Time | Notes |
|------|------|-------|
| Matched Pairs | ~6s | Only pairs new ACTUALs |
| Training | ~10-30s | Only dirty entities (~20-30 active) |
| **Total** | **~30-60s** | |

### Full Rebuild (first run or `--full-pairs`)
| Step | Time | Notes |
|------|------|-------|
| Matched Pairs | ~102s | All 2.4M pairs from scratch |
| Training | ~93s | All 142 eligible entities |
| **Total** | **~4 min** | |

---

## Usage

### Full Pipeline (daily cron)
```bash
cd ~/theme-park-crowd-report
.venv/bin/python scripts/hybrid_pipeline_v2.py --output-base /mnt/data/pipeline --skip-scoring
```

### Force Full Rebuild
```bash
# Rebuild all matched pairs from scratch
.venv/bin/python scripts/hybrid_pipeline_v2.py --full-pairs

# Skip specific steps
.venv/bin/python scripts/hybrid_pipeline_v2.py --skip-pairs --skip-scoring
```

---

## How It Works

### Step 1: Matched Pairs (Incremental)

**Script:** `scripts/hybrid_pipeline_v2.py` → `step1_create_matched_pairs()`

**First run:** Full rebuild — scans all parquet, pairs all ACTUALs with closest POSTED within 15-minute window.

**Subsequent runs:** Reads `state/matched_pairs_state.json` for `last_paired_at` timestamp. Only queries ACTUALs with `observed_at > last_paired_at`. Appends new pairs to existing `all_pairs_v2.parquet`.

**Encoding consistency:** Label encodings for `date_group_id`, `season`, `season_year` are loaded from `state/encoding_mappings.json` and extended (not rebuilt) with any new categories.

**Output:** `matched_pairs/all_pairs_v2.parquet` (cumulative, append-only)

**Key: No geo_decay_weight in pairs.** Pairs are static facts (this ACTUAL matched this POSTED at this time). Geo decay is a training concern, not a pairing concern.

### Step 2: Training (Incremental)

**Script:** `julia-ml/train_v2.jl` (called from `hybrid_pipeline_v2.py`)

**Dirty entity detection:**
1. Python queries `state/entity_index.sqlite` for entities where `latest_observed_at > last_modeled_at`
2. Writes dirty entity codes to `state/entities_to_train.txt`
3. Julia reads this file and intersects with eligible entities (≥500 pairs)
4. Only the intersection gets retrained

**Geo decay at training time:** Julia computes `weight = 0.5^(days_old / 730)` from `park_date` relative to today. Weights are always fresh.

**After training:** Python calls `mark_entity_modeled()` to set `last_modeled_at = now()` for each trained entity. They won't retrain until new data arrives.

**Output:** `models/{entity_code}/model_julia_v2.json` + `metadata_julia_v2.json`

### Step 3: Scoring (unchanged)

Python loads trained models and scores recent POSTED observations.  
Falls back to dynamic ratio (from `state/fallback_ratios.json`) for entities without models.

---

## Operating Calendar

**Script:** `src/build_operating_calendar.py`

**Purpose:** Tracks which entity-dates are operating (not permanently extinct or temporarily closed). Used by matched pairs to exclude closed entity-dates.

**Incremental mode (default):** Refreshes `today - 7 days` to `today + 365 days`. Merges with existing calendar. Historical dates are stable.

**Full rebuild:** `--full` flag or first run. Auto-detects earliest observation in fact tables.

**Sources:**
- `dimentity.csv` → `extinct_on` dates (permanent closures)
- `raw_closures/*.csv` → temporary closures

**Output:** `operating_calendar/operating_calendar.parquet` (~11M rows covering 2009 to 2027)

---

## State Files

| File | Purpose |
|------|---------|
| `state/entity_index.sqlite` | Tracks per-entity latest observation + last modeled timestamp |
| `state/matched_pairs_state.json` | `last_paired_at` for incremental pairing |
| `state/encoding_mappings.json` | Label encodings for categorical features |
| `state/fallback_ratios.json` | Dynamic ACTUAL/POSTED ratios per entity |
| `state/entities_to_train.txt` | Dirty entity list passed to Julia |

---

## Entity Eligibility

An entity gets a trained model when:
1. ✅ Exists in `dimentity.csv` (has TouringPlans S3 mapping)
2. ✅ Has ≥500 matched pairs (cumulative across all history)
3. ✅ Has new data since last training (dirty check)

Currently ~142 entities qualify. ~400+ use the fallback ratio instead.

---

## Integration with Daily Pipeline

Step 5 in `run_daily_pipeline.sh`:

```
ETL → Dimensions → Closures/Operating Calendar → Aggregates → Report → TRAINING → Forecast → WTI
```

The `--skip-if-unchanged` flag checks `pipeline_state.py` which queries dirty entity count. Training is skipped only if zero entities have new observations.

---

## Julia Setup

Julia 1.10.2 at `~/julia-1.10.2/bin/julia`

Dependencies (Project.toml): DataFrames, Parquet2, XGBoost, JSON3, OrderedCollections, Dates

```bash
cd ~/theme-park-crowd-report/julia-ml
~/julia-1.10.2/bin/julia --project=. -e 'using Pkg; Pkg.update()'
```

---

## Monitoring

Logs: `/mnt/data/pipeline/logs/hybrid_pipeline_v2_*.log`

Dashboard API health: `curl http://localhost:8051/api/health`

---

## Files

| File | Purpose |
|------|---------|
| `scripts/hybrid_pipeline_v2.py` | Main orchestrator (pairs + training + scoring) |
| `julia-ml/train_v2.jl` | Julia training (XGBoost with geo decay) |
| `src/build_operating_calendar.py` | Operating calendar (incremental) |
| `src/processors/entity_index.py` | Entity dirty tracking (SQLite) |
| `scripts/pipeline_state.py` | Skip-if-unchanged logic |
