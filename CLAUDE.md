# Theme Park Crowd Report — AI Agent Guide

## Critical: Read Before Writing Code

**Read `docs/ARCHITECTURE.md` first.** It defines the mandatory data access pattern.

## The #1 Rule

**All data access uses DuckDB + Parquet.** Never use CSV loops or `load_entity_data()`.

```python
import duckdb
con = duckdb.connect()
df = con.execute(f"""
    SELECT * FROM read_parquet('{output_base}/fact_tables/parquet/*.parquet')
    WHERE entity_code = 'MK01'
""").fetchdf()
```

## Project Overview

- **What:** Theme park wait time predictions (Disney, Universal)
- **Stack:** Python + DuckDB + XGBoost (Julia for production training)
- **Data:** Parquet fact tables in `/mnt/data/pipeline/fact_tables/parquet/`
- **Dimensions:** CSV in `/mnt/data/pipeline/dimension_tables/`
- **Models:** Per-entity XGBoost in `/mnt/data/pipeline/models/{entity_code}/`

## Key Files

- `scripts/hybrid_pipeline_v2.py` — **Main pipeline** (reference for patterns)
- `src/processors/training.py` — Per-entity model training
- `src/processors/encoding.py` — Label encoding
- `src/processors/posted_to_actual.py` — POSTED→ACTUAL conversion (DuckDB)
- `src/processors/synthetic_actuals.py` — Synthetic actuals generator (DuckDB)
- `docs/MODELING_AND_WTI_METHODOLOGY.md` — Full methodology docs

## Memory Limits

Server: 62GB RAM. Chunk by park prefix if processing > 30M rows.
