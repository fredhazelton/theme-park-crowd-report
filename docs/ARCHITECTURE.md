# Pipeline Architecture Guide

## ⚠️ MANDATORY: Data Access Patterns

This project has ONE correct way to access bulk wait time data. Follow it.

### ✅ CORRECT: DuckDB + Parquet

All new code MUST use DuckDB to read from parquet files:

```python
import duckdb

con = duckdb.connect()
parquet_dir = output_base / "fact_tables" / "parquet"

df = con.execute(f"""
    SELECT entity_code, observed_at_ts, park_date, wait_time_minutes, wait_time_type
    FROM read_parquet('{parquet_dir}/*.parquet')
    WHERE entity_code = 'MK01'
      AND wait_time_type = 'POSTED'
""").fetchdf()
con.close()
```

**Why:** Fast (seconds for millions of rows), memory-efficient, supports window functions for rolling features.

**Reference implementation:** `scripts/hybrid_pipeline_v2.py`

### ❌ DEPRECATED: CSV-based entity loading

Do NOT use these functions for new code:
- `entity_index.load_entity_data()` — Reads individual CSVs, extremely slow
- `features.add_features()` — Designed for CSV DataFrames, not bulk processing

These still exist for backward compatibility with the main pipeline loop but should NOT be used in new modules.

**If you find yourself calling `load_entity_data()` in a loop over entities — STOP. Use DuckDB.**

### ❌ NEVER: Raw CSV glob patterns

```python
# NEVER DO THIS
for f in glob("fact_tables/*.csv"):
    df = pd.read_csv(f)
```

### Dimension Tables

Dimension tables are small CSVs — read them via DuckDB too:

```python
dategroupid = con.execute(f"""
    SELECT CAST(park_date AS DATE) as park_date, date_group_id
    FROM read_csv('{dim_dir}/dimdategroupid.csv', AUTO_DETECT=TRUE)
""").fetchdf()
```

Or via pandas if you're doing a quick lookup (they're small).

## Memory Guidelines

**Server:** 62GB RAM (wilma-server)

| Data Size | Approach |
|-----------|----------|
| < 10M rows | Single DuckDB query, fetchdf() |
| 10M-30M rows | Single query OK, but monitor |
| > 30M rows | **Chunk by park prefix** (11 parks) |
| > 100M rows | Chunk by park × year or stream results |

The synthetic actuals generator processes 90M rows chunked by park, max ~19M rows per chunk (~19GB peak).

## File Layout

```
src/processors/
├── encoding.py       — Label encoding (used by hybrid_pipeline_v2)
├── entity_index.py   — Entity index + DEPRECATED load_entity_data
├── features.py       — Feature engineering (DEPRECATED for bulk use)
├── posted_to_actual.py  — POSTED→ACTUAL conversion model (DuckDB)
├── synthetic_actuals.py — Synthetic actuals generator (DuckDB, chunked)
├── training.py       — XGBoost training (called per-entity by pipeline)
└── ...

scripts/
├── hybrid_pipeline_v2.py  — Main production pipeline (DuckDB + Julia XGBoost)
├── train_conversion_model.py — Train POSTED→ACTUAL model
├── generate_synthetic_actuals.py — Generate synthetic actuals
└── ...
```

## For AI Coding Agents (Cursor, Sub-agents)

When writing new data processing code for this project:

1. **Always use DuckDB** for reading parquet/CSV data
2. **Never loop over entities** loading data one-by-one
3. **Use window functions** for rolling/lag features (not pandas rolling)
4. **Chunk large operations** by park if total rows > 30M
5. **Reference `hybrid_pipeline_v2.py`** as the canonical pattern
6. **Check this file** before writing any data access code
