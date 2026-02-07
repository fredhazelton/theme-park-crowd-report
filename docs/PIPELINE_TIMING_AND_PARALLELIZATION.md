# Pipeline Timing and Parallelization

**Last Updated:** 2026-02-07  
**Status:** Optimized - Hybrid pipeline in production

---

## Current Performance (Hybrid Pipeline)

| Step | Tool | Time |
|------|------|------|
| ETL Sync | Python/boto3 | ~5 min |
| Dimensions | Python | ~2 min |
| Posted Aggregates | Python/DuckDB | ~1 min |
| Report | Python | ~1 min |
| **Matched Pairs** | DuckDB | ~78s |
| **Training** | Julia XGBoost | ~67s |
| Scoring | Python | ~30s |
| Forecast | Python | ~5 min |
| WTI | Python | ~1 min |
| **TOTAL** | | **~15-20 min** |

**Training bottleneck eliminated.** What used to take 75+ minutes (or 30+ hours sequential) now takes ~2.5 minutes.

---

## Historical Context

### Before Optimization (Jan 2026)
- Sequential Python training: **30+ hours** for all entities
- No parallelization, no early stopping
- 2000 XGBoost trees per model

### After Python Optimization (Feb 6, 2026)
- Parallel training with 5 workers
- Early stopping (50 rounds)
- DuckDB for aggregations
- Training time: **~10 minutes**

### After Julia Hybrid (Feb 7, 2026)
- Julia XGBoost.jl for training
- Python/DuckDB for data prep
- Training time: **~2.5 minutes**
- **4x faster** than Python-only

---

## Why Julia is Faster

1. **JIT Compilation** - Julia compiles to native code
2. **No GIL** - True parallelism without Python's Global Interpreter Lock
3. **XGBoost.jl** - Optimized bindings, less overhead than Python wrapper
4. **Memory Layout** - Julia's column-major arrays match XGBoost expectations

Benchmark (141 entity models):
- Python XGBoost (parallel): ~10 min
- Julia XGBoost: ~67s
- **Speedup: ~9x**

---

## Current Architecture

```
┌─────────────────────────────────────────────────┐
│              Daily Pipeline (6 AM)              │
├─────────────────────────────────────────────────┤
│  1. ETL Sync (S3 → Parquet)      [Python]      │
│  2. Dimensions                    [Python]      │
│  3. Posted Aggregates             [DuckDB]      │
│  4. Report                        [Python]      │
├─────────────────────────────────────────────────┤
│  5. HYBRID TRAINING                             │
│     ├─ Matched Pairs              [DuckDB]     │
│     └─ XGBoost Training           [Julia]      │
├─────────────────────────────────────────────────┤
│  6. Forecast                      [Python]      │
│  7. WTI Calculation               [Python]      │
└─────────────────────────────────────────────────┘
```

---

## Key Scripts

| Script | Purpose | Language |
|--------|---------|----------|
| `run_daily_pipeline.sh` | Master orchestrator | Bash |
| `hybrid_pipeline.py` | Training pipeline | Python + Julia |
| `julia-ml/train_only.jl` | XGBoost training | Julia |
| `score_fast.py` | Model scoring | Python |
| `train_fast.py` | Python training (backup) | Python |

---

## Parallelization Strategy

### Training (Julia)
- Single-threaded per model (Julia handles internal parallelism)
- 4 Julia threads for XGBoost tree building
- Sequential entity loop (fast enough at 0.48s/entity)

### Data Prep (DuckDB)
- Automatic parallelization across all cores
- Vectorized operations on parquet files
- Memory-mapped file access

### Scoring (Python)
- ProcessPoolExecutor with 5 workers
- Parallel across entities

---

## Memory Usage

| Component | RAM |
|-----------|-----|
| DuckDB matched pairs query | ~10 GB peak |
| Julia training | ~1.5 GB |
| Python scoring | ~2 GB |
| **Total peak** | **~12 GB** |

Machine has 64 GB - plenty of headroom.

---

## Cron Schedule

```bash
# Daily pipeline at 6 AM ET
0 6 * * * cd /home/wilma/theme-park-crowd-report && ./scripts/run_daily_pipeline.sh --skip-dropbox-check >> /home/wilma/hazeydata/pipeline/logs/daily_pipeline_$(date +\%Y-\%m-\%d).log 2>&1
```

Pipeline completes well before next day's run - no overlap issues.

---

## Troubleshooting

### Julia not found
```bash
# Check Julia installation
ls ~/julia-1.10.2/bin/julia

# Or use juliaup
~/.juliaup/bin/julia --version
```

### DuckDB out of memory
Reduce concurrent queries or add swap:
```bash
sudo fallocate -l 8G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### Training failures
Check logs: `/home/wilma/hazeydata/pipeline/logs/hybrid_pipeline_*.log`

---

## See Also

- [HYBRID_PIPELINE.md](HYBRID_PIPELINE.md) - Detailed hybrid pipeline docs
- [PREDICTIONS-API.md](PREDICTIONS-API.md) - Scoring API endpoints
- [PIPELINE_STATE.md](PIPELINE_STATE.md) - Current pipeline configuration
