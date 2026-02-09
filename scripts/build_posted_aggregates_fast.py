#!/usr/bin/env python3
"""
Build Posted Aggregates - FAST Version

Uses existing monthly parquet files (202 files, 611MB) instead of 50K CSVs (5.4GB).
Should complete in ~1-2 minutes instead of 30+ minutes.

Output: /home/wilma/hazeydata/pipeline/aggregates/posted_aggregates.parquet

Usage:
    python scripts/build_posted_aggregates_fast.py
    python scripts/build_posted_aggregates_fast.py --output-base /path/to/pipeline
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
    log_file = log_dir / f"build_posted_aggregates_fast_{datetime.now(ZoneInfo('UTC')).strftime('%Y%m%d_%H%M%S')}.log"

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


def build_aggregates_from_parquet(output_base: Path, logger: logging.Logger) -> int:
    """
    Build POSTED aggregates from monthly parquet fact tables.
    
    Uses fact_tables/parquet/*.parquet (202 files, 611MB) instead of
    fact_tables/clean/**/*.csv (50K files, 5.4GB).
    
    Returns number of aggregate rows created.
    """
    parquet_dir = output_base / "fact_tables" / "parquet"
    dim_dir = output_base / "dimension_tables"
    agg_dir = output_base / "aggregates"
    agg_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = agg_dir / "posted_aggregates.parquet"
    dimdategroupid_file = dim_dir / "dimdategroupid.csv"
    
    # Check inputs
    if not parquet_dir.exists():
        logger.error(f"Parquet fact tables not found: {parquet_dir}")
        logger.error("Run ETL first to generate monthly parquet files.")
        return 0
    
    if not dimdategroupid_file.exists():
        logger.error(f"dimdategroupid.csv not found: {dimdategroupid_file}")
        return 0
    
    parquet_glob = str(parquet_dir / "*.parquet")
    
    logger.info("=" * 60)
    logger.info("BUILD POSTED AGGREGATES (Fast Parquet Version)")
    logger.info("=" * 60)
    logger.info(f"Source: {parquet_dir}")
    logger.info(f"Output: {output_file}")
    
    start_time = time.time()
    con = duckdb.connect()
    
    # Count files
    file_count = con.execute(f"SELECT COUNT(*) FROM glob('{parquet_glob}')").fetchone()[0]
    logger.info(f"Found {file_count} monthly parquet files")
    
    # Get total size
    total_size = sum(f.stat().st_size for f in parquet_dir.glob("*.parquet"))
    logger.info(f"Total size: {total_size / (1024*1024):.1f} MB")
    
    # Load dimension table
    logger.info("Loading dimdategroupid...")
    con.execute(f"""
        CREATE TABLE dimdategroupid AS 
        SELECT 
            CAST(park_date AS DATE) as park_date,
            date_group_id
        FROM read_csv_auto('{dimdategroupid_file}')
    """)
    
    # Build aggregates
    logger.info("Computing aggregates...")
    
    con.execute(f"""
        COPY (
            SELECT 
                f.entity_code,
                COALESCE(d.date_group_id, 'UNKNOWN') as date_group_id,
                CAST(EXTRACT(HOUR FROM CAST(f.observed_at AS TIMESTAMP)) AS INTEGER) as hour,
                -- Weighted median (using percentile)
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.wait_time_minutes) as posted_median,
                -- Weighted mean with geo decay
                SUM(f.wait_time_minutes * POWER(0.5, DATEDIFF('day', CAST(f.park_date AS DATE), CURRENT_DATE) / 730.0)) 
                    / SUM(POWER(0.5, DATEDIFF('day', CAST(f.park_date AS DATE), CURRENT_DATE) / 730.0)) as posted_mean_weighted,
                -- Unweighted stats
                AVG(f.wait_time_minutes) as posted_mean,
                COUNT(*) as posted_count,
                MIN(CAST(f.park_date AS DATE)) as min_park_date,
                MAX(CAST(f.park_date AS DATE)) as max_park_date
            FROM read_parquet('{parquet_glob}') f
            LEFT JOIN dimdategroupid d ON CAST(f.park_date AS DATE) = d.park_date
            WHERE f.wait_time_type = 'POSTED'
              AND f.wait_time_minutes IS NOT NULL
              AND f.wait_time_minutes > 0
            GROUP BY f.entity_code, d.date_group_id, EXTRACT(HOUR FROM CAST(f.observed_at AS TIMESTAMP))
            ORDER BY f.entity_code, d.date_group_id, hour
        ) TO '{output_file}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    
    # Get stats
    stats = con.execute(f"""
        SELECT 
            COUNT(*) as row_count,
            COUNT(DISTINCT entity_code) as entity_count,
            COUNT(DISTINCT date_group_id) as date_group_count
        FROM read_parquet('{output_file}')
    """).fetchone()
    
    row_count, entity_count, date_group_count = stats
    
    elapsed = time.time() - start_time
    file_size_mb = output_file.stat().st_size / (1024 * 1024)
    
    logger.info("=" * 60)
    logger.info("AGGREGATES COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Parquet files scanned: {file_count}")
    logger.info(f"Entities: {entity_count:,}")
    logger.info(f"Date groups: {date_group_count:,}")
    logger.info(f"Aggregate rows: {row_count:,}")
    logger.info(f"Output size: {file_size_mb:.1f} MB")
    logger.info(f"⏱️  Time: {elapsed:.1f}s")
    logger.info("=" * 60)
    
    con.close()
    return row_count


def main() -> None:
    ap = argparse.ArgumentParser(description="Build POSTED aggregates (fast parquet version)")
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
        row_count = build_aggregates_from_parquet(base, logger)
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
