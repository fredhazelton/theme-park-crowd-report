#!/usr/bin/env python3
"""
Build Model Aggregates - For prediction model without posted times

Groups by: entity_code, date_group_id, time_slot (15-min intervals)

Features aligned with model:
- time_slot: 15-min intervals (0-95)
- hour_of_day: 0-23

Join with dimension tables separately for:
- season, season_year (via date_group_id → date → dimseason)
- mins_since_open (via park hours)

Output: /home/wilma/hazeydata/pipeline/aggregates/model_aggregates.parquet

Usage:
    python scripts/build_model_aggregates.py
    python scripts/build_model_aggregates.py --output-base /path/to/pipeline
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

# Add src to path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.paths import get_output_base


def setup_logging(log_dir: Path) -> logging.Logger:
    """Set up file and console logging."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"build_model_aggregates_{datetime.now(ZoneInfo('UTC')).strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized. Log file: {log_file}")
    return logger


def build_model_aggregates(output_base: Path, logger: logging.Logger) -> int:
    """
    Build model aggregates with 15-minute time slots.
    
    Groups by: entity_code, date_group_id, time_slot
    
    Simplified approach:
    - Join dimdategroupid for date_group_id
    - Compute time_slot from observed_at
    - Aggregate wait times
    - Additional dimension lookups done at prediction time
    
    Returns number of aggregate rows created.
    """
    parquet_dir = output_base / "fact_tables" / "parquet"
    dim_dir = output_base / "dimension_tables"
    agg_dir = output_base / "aggregates"
    agg_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = agg_dir / "model_aggregates.parquet"
    dim_dategroupid_file = dim_dir / "dimdategroupid.csv"
    dim_entity_file = dim_dir / "dimentity.csv"
    
    # Check inputs
    if not parquet_dir.exists():
        logger.error(f"Parquet fact tables not found: {parquet_dir}")
        return 0
    
    if not dim_dategroupid_file.exists():
        logger.error(f"Dimension file not found: {dim_dategroupid_file}")
        return 0
    
    parquet_glob = str(parquet_dir / "*.parquet")
    
    logger.info("=" * 60)
    logger.info("BUILD MODEL AGGREGATES (15-min time slots)")
    logger.info("=" * 60)
    logger.info(f"Source: {parquet_dir}")
    logger.info(f"Output: {output_file}")
    
    start_time = time.time()
    con = duckdb.connect()
    
    # Set memory limit to avoid OOM
    con.execute("SET memory_limit='16GB'")
    con.execute("SET threads=4")
    
    # Count files
    file_count = con.execute(f"SELECT COUNT(*) FROM glob('{parquet_glob}')").fetchone()[0]
    logger.info(f"Found {file_count} monthly parquet files")
    
    # Load dimension tables
    logger.info("Loading dimdategroupid...")
    con.execute(f"""
        CREATE TABLE dimdategroupid AS 
        SELECT 
            CAST(park_date AS DATE) as park_date,
            date_group_id
        FROM read_csv_auto('{dim_dategroupid_file}')
    """)
    
    logger.info("Loading dimentity (for fastpass_booth filter)...")
    con.execute(f"""
        CREATE TABLE dimentity AS 
        SELECT code as entity_code, fastpass_booth
        FROM read_csv_auto('{dim_entity_file}')
    """)
    
    # Build aggregates with 15-minute time slots
    # Simplified: only join date_group_id, compute time_slot
    logger.info("Computing model aggregates (15-min slots)...")
    
    con.execute(f"""
        COPY (
            SELECT 
                f.entity_code,
                COALESCE(d.date_group_id, 'UNKNOWN') as date_group_id,
                -- 15-minute time slot (0-95 for 24h)
                CAST(EXTRACT(HOUR FROM CAST(f.observed_at AS TIMESTAMP)) * 4 + 
                     FLOOR(EXTRACT(MINUTE FROM CAST(f.observed_at AS TIMESTAMP)) / 15) AS INTEGER) as time_slot,
                -- Hour of day (for quick access)
                CAST(EXTRACT(HOUR FROM CAST(f.observed_at AS TIMESTAMP)) AS INTEGER) as hour_of_day,
                -- Wait time aggregates
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.wait_time_minutes) as wait_median,
                AVG(f.wait_time_minutes) as wait_mean,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY f.wait_time_minutes) as wait_p25,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY f.wait_time_minutes) as wait_p75,
                STDDEV(f.wait_time_minutes) as wait_std,
                MIN(f.wait_time_minutes) as wait_min,
                MAX(f.wait_time_minutes) as wait_max,
                -- Weighted mean with geo decay (half-life 2 years)
                SUM(f.wait_time_minutes * POWER(0.5, DATEDIFF('day', CAST(f.park_date AS DATE), CURRENT_DATE) / 730.0)) 
                    / NULLIF(SUM(POWER(0.5, DATEDIFF('day', CAST(f.park_date AS DATE), CURRENT_DATE) / 730.0)), 0) as wait_mean_weighted,
                -- Sample counts
                COUNT(*) as sample_count,
                COUNT(DISTINCT CAST(f.park_date AS DATE)) as date_count,
                MIN(CAST(f.park_date AS DATE)) as min_park_date,
                MAX(CAST(f.park_date AS DATE)) as max_park_date
            FROM read_parquet('{parquet_glob}') f
            LEFT JOIN dimdategroupid d ON CAST(f.park_date AS DATE) = d.park_date
            INNER JOIN dimentity e ON f.entity_code = e.entity_code
            WHERE f.wait_time_type = 'POSTED'
              AND f.wait_time_minutes IS NOT NULL
              AND f.wait_time_minutes > 0
              AND e.fastpass_booth = FALSE
            GROUP BY 
                f.entity_code, 
                d.date_group_id, 
                EXTRACT(HOUR FROM CAST(f.observed_at AS TIMESTAMP)) * 4 + FLOOR(EXTRACT(MINUTE FROM CAST(f.observed_at AS TIMESTAMP)) / 15),
                EXTRACT(HOUR FROM CAST(f.observed_at AS TIMESTAMP))
            ORDER BY f.entity_code, d.date_group_id, time_slot
        ) TO '{output_file}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    
    # Get stats
    stats = con.execute(f"""
        SELECT 
            COUNT(*) as row_count,
            COUNT(DISTINCT entity_code) as entity_count,
            COUNT(DISTINCT date_group_id) as date_group_count,
            COUNT(DISTINCT time_slot) as time_slot_count
        FROM read_parquet('{output_file}')
    """).fetchone()
    
    row_count, entity_count, date_group_count, time_slot_count = stats
    
    # Sample output
    sample = con.execute(f"""
        SELECT entity_code, date_group_id, time_slot, hour_of_day, 
               wait_median, wait_mean, sample_count
        FROM read_parquet('{output_file}')
        WHERE entity_code = 'MK01'
        LIMIT 5
    """).fetchdf()
    
    elapsed = time.time() - start_time
    file_size_mb = output_file.stat().st_size / (1024 * 1024)
    
    logger.info("=" * 60)
    logger.info("MODEL AGGREGATES COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Parquet files scanned: {file_count}")
    logger.info(f"Entities: {entity_count:,}")
    logger.info(f"Date groups: {date_group_count:,}")
    logger.info(f"Time slots: {time_slot_count} (15-min intervals)")
    logger.info(f"Aggregate rows: {row_count:,}")
    logger.info(f"Output size: {file_size_mb:.1f} MB")
    logger.info(f"⏱️  Time: {elapsed:.1f}s")
    logger.info("")
    logger.info("Sample output (MK01):")
    logger.info(sample.to_string())
    logger.info("=" * 60)
    
    con.close()
    return row_count


def main() -> None:
    ap = argparse.ArgumentParser(description="Build model aggregates (15-min time slots)")
    ap.add_argument(
        "--output-base",
        type=Path,
        default=get_output_base(),
        help="Output base directory",
    )
    args = ap.parse_args()

    base = args.output_base.resolve()
    log_dir = base / "logs"
    logger = setup_logging(log_dir)

    try:
        row_count = build_model_aggregates(base, logger)
        if row_count > 0:
            logger.info("Success!")
            sys.exit(0)
        else:
            logger.error("No aggregates created")
            sys.exit(1)
    except Exception as e:
        logger.exception(f"Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
