#!/usr/bin/env python3
"""
Impute Park Hours - Fill missing future park hours using donor pool

For any date without park hours:
1. Find all dates with same date_group_id that have park hours
2. Weight by recency (recent years = high, 5+ years = very low)
3. Select weighted mode for opening/closing times
4. Mark as donated (donor_date field)

Uses DuckDB for fast vectorized processing.

Runs after: dimparkhours and dimdategroupid are created
Output: Updates dimparkhours.csv with imputed hours

Usage:
    python scripts/impute_park_hours.py
    python scripts/impute_park_hours.py --output-base /path/to/pipeline
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
import pandas as pd

# Add src to path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.paths import get_output_base


def setup_logging(log_dir: Path) -> logging.Logger:
    """Set up file and console logging."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"impute_park_hours_{datetime.now(ZoneInfo('UTC')).strftime('%Y%m%d_%H%M%S')}.log"

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


def impute_park_hours(output_base: Path, logger: logging.Logger) -> int:
    """
    Impute missing park hours using donor pool method with DuckDB.
    
    Returns number of hours imputed.
    """
    dim_dir = output_base / "dimension_tables"
    
    parkhours_file = dim_dir / "dimparkhours.csv"
    dategroupid_file = dim_dir / "dimdategroupid.csv"
    donations_file = dim_dir / "parkhours_donations.csv"
    
    if not parkhours_file.exists():
        logger.error(f"dimparkhours.csv not found: {parkhours_file}")
        return 0
    
    if not dategroupid_file.exists():
        logger.error(f"dimdategroupid.csv not found: {dategroupid_file}")
        return 0
    
    logger.info("=" * 60)
    logger.info("IMPUTE PARK HOURS (DuckDB)")
    logger.info("=" * 60)
    
    start_time = time.time()
    current_year = datetime.now().year
    
    con = duckdb.connect()
    
    # Load data
    logger.info("Loading dimension tables...")
    
    con.execute(f"""
        CREATE TABLE parkhours AS
        SELECT * FROM read_csv_auto('{parkhours_file}', all_varchar=true)
    """)
    
    con.execute(f"""
        CREATE TABLE dategroupid AS
        SELECT 
            CAST(park_date AS DATE) as park_date,
            date_group_id
        FROM read_csv_auto('{dategroupid_file}')
    """)
    
    # Count missing
    missing_count = con.execute("""
        SELECT COUNT(*) FROM parkhours WHERE opening_time IS NULL OR opening_time = ''
    """).fetchone()[0]
    
    total_count = con.execute("SELECT COUNT(*) FROM parkhours").fetchone()[0]
    
    logger.info(f"Total park-days: {total_count:,}")
    logger.info(f"Missing hours: {missing_count:,}")
    
    if missing_count == 0:
        logger.info("No imputation needed!")
        con.close()
        return 0
    
    # Build imputed hours using weighted mode
    # Weight: recent years (0-1) = 1.0, 2-4 years = 0.8-0.4, 5+ years = 0.1
    logger.info("Computing weighted donor hours...")
    
    con.execute(f"""
        CREATE TABLE imputed AS
        WITH 
        -- Add date_group_id to park hours
        hours_with_group AS (
            SELECT 
                p.*,
                CAST(p.date AS DATE) as date_parsed,
                YEAR(CAST(p.date AS DATE)) as year,
                d.date_group_id
            FROM parkhours p
            LEFT JOIN dategroupid d ON CAST(p.date AS DATE) = d.park_date
        ),
        -- Rows needing imputation
        needs_impute AS (
            SELECT park, date_parsed, date_group_id
            FROM hours_with_group
            WHERE (opening_time IS NULL OR opening_time = '')
              AND date_group_id IS NOT NULL
        ),
        -- Donor pool: rows with hours
        donors AS (
            SELECT 
                park,
                date_parsed as donor_date,
                date_group_id,
                opening_time,
                opening_time_with_emh,
                closing_time,
                closing_time_with_emh_or_party,
                emh_morning,
                emh_evening,
                year,
                -- Recency weight
                CASE 
                    WHEN {current_year} - year <= 1 THEN 1.0
                    WHEN {current_year} - year <= 4 THEN 1.0 - ({current_year} - year - 1) * 0.2
                    ELSE 0.1
                END as weight
            FROM hours_with_group
            WHERE opening_time IS NOT NULL 
              AND opening_time != ''
              AND date_group_id IS NOT NULL
        ),
        -- For each (park, date_group_id), find weighted mode of opening_time
        weighted_modes AS (
            SELECT 
                park,
                date_group_id,
                opening_time,
                opening_time_with_emh,
                closing_time,
                closing_time_with_emh_or_party,
                emh_morning,
                emh_evening,
                SUM(weight) as total_weight,
                MAX(donor_date) as best_donor_date,
                COUNT(*) as donor_count
            FROM donors
            GROUP BY park, date_group_id, opening_time, opening_time_with_emh, 
                     closing_time, closing_time_with_emh_or_party, emh_morning, emh_evening
        ),
        -- Pick the opening_time combo with highest weight for each (park, date_group_id)
        best_hours AS (
            SELECT DISTINCT ON (park, date_group_id)
                park,
                date_group_id,
                opening_time,
                opening_time_with_emh,
                closing_time,
                closing_time_with_emh_or_party,
                emh_morning,
                emh_evening,
                best_donor_date,
                donor_count
            FROM weighted_modes
            ORDER BY park, date_group_id, total_weight DESC
        )
        -- Join back to get imputed values for each target date
        SELECT 
            n.park,
            n.date_parsed as target_date,
            n.date_group_id,
            b.opening_time,
            b.opening_time_with_emh,
            b.closing_time,
            b.closing_time_with_emh_or_party,
            b.emh_morning,
            b.emh_evening,
            b.best_donor_date as donor_date,
            b.donor_count
        FROM needs_impute n
        JOIN best_hours b ON n.park = b.park AND n.date_group_id = b.date_group_id
    """)
    
    imputed_count = con.execute("SELECT COUNT(*) FROM imputed").fetchone()[0]
    logger.info(f"Imputed rows (date_group match): {imputed_count:,}")
    
    # Fallback: for any still missing, use mode from last 12 months for that park
    logger.info("Checking for remaining missing (fallback to 12-month mode)...")
    
    con.execute(f"""
        CREATE TABLE fallback_imputed AS
        WITH 
        -- Rows still needing imputation after first pass
        still_missing AS (
            SELECT 
                p.park,
                CAST(p.date AS DATE) as date_parsed
            FROM parkhours p
            LEFT JOIN imputed i ON p.park = i.park AND CAST(p.date AS DATE) = i.target_date
            WHERE (p.opening_time IS NULL OR p.opening_time = '')
              AND i.target_date IS NULL
        ),
        -- Last 12 months of hours per park
        recent_hours AS (
            SELECT 
                park,
                CAST(date AS DATE) as donor_date,
                opening_time,
                opening_time_with_emh,
                closing_time,
                closing_time_with_emh_or_party,
                emh_morning,
                emh_evening
            FROM parkhours
            WHERE opening_time IS NOT NULL 
              AND opening_time != ''
              AND CAST(date AS DATE) >= CURRENT_DATE - INTERVAL '12 months'
        ),
        -- Mode hours per park (most common combo in last 12 months)
        park_mode AS (
            SELECT 
                park,
                opening_time,
                opening_time_with_emh,
                closing_time,
                closing_time_with_emh_or_party,
                emh_morning,
                emh_evening,
                COUNT(*) as cnt,
                MAX(donor_date) as best_donor_date
            FROM recent_hours
            GROUP BY park, opening_time, opening_time_with_emh, closing_time, 
                     closing_time_with_emh_or_party, emh_morning, emh_evening
        ),
        best_park_mode AS (
            SELECT DISTINCT ON (park)
                park,
                opening_time,
                opening_time_with_emh,
                closing_time,
                closing_time_with_emh_or_party,
                emh_morning,
                emh_evening,
                best_donor_date
            FROM park_mode
            ORDER BY park, cnt DESC
        )
        SELECT 
            m.park,
            m.date_parsed as target_date,
            'FALLBACK_12M' as date_group_id,
            b.opening_time,
            b.opening_time_with_emh,
            b.closing_time,
            b.closing_time_with_emh_or_party,
            b.emh_morning,
            b.emh_evening,
            b.best_donor_date as donor_date,
            0 as donor_count
        FROM still_missing m
        JOIN best_park_mode b ON m.park = b.park
    """)
    
    fallback_count = con.execute("SELECT COUNT(*) FROM fallback_imputed").fetchone()[0]
    logger.info(f"Fallback imputed rows: {fallback_count:,}")
    
    # Merge fallback into imputed
    if fallback_count > 0:
        con.execute("INSERT INTO imputed SELECT * FROM fallback_imputed")
        imputed_count = con.execute("SELECT COUNT(*) FROM imputed").fetchone()[0]
    
    if imputed_count == 0:
        logger.info("No matches found")
        con.close()
        return 0
    
    # Update original park hours
    logger.info("Updating park hours...")
    
    con.execute("""
        UPDATE parkhours p
        SET 
            opening_time = i.opening_time,
            opening_time_with_emh = i.opening_time_with_emh,
            closing_time = i.closing_time,
            closing_time_with_emh_or_party = i.closing_time_with_emh_or_party,
            emh_morning = i.emh_morning,
            emh_evening = i.emh_evening,
            donor_date = CAST(i.donor_date AS VARCHAR),
            is_official = FALSE
        FROM imputed i
        WHERE p.park = i.park 
          AND CAST(p.date AS DATE) = i.target_date
    """)
    
    # Save updated park hours
    logger.info("Saving updated dimparkhours.csv...")
    con.execute(f"COPY parkhours TO '{parkhours_file}' (HEADER, DELIMITER ',')")
    
    # Save donations log
    logger.info("Saving donations log...")
    con.execute(f"""
        COPY (
            SELECT 
                park,
                CAST(target_date AS VARCHAR) as target_date,
                date_group_id,
                CAST(donor_date AS VARCHAR) as donor_date,
                opening_time as donated_opening,
                closing_time as donated_closing,
                donor_count as donor_pool_size,
                '{datetime.now().isoformat()}' as imputed_at
            FROM imputed
        ) TO '{donations_file}' (HEADER, DELIMITER ',')
    """)
    
    # Summary by park
    summary = con.execute("""
        SELECT park, COUNT(*) as count 
        FROM imputed 
        GROUP BY park 
        ORDER BY park
    """).fetchdf()
    
    elapsed = time.time() - start_time
    
    logger.info("=" * 60)
    logger.info("IMPUTATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Hours imputed: {imputed_count:,}")
    logger.info(f"By park:")
    for _, row in summary.iterrows():
        logger.info(f"  {row['park']}: {row['count']:,}")
    logger.info(f"⏱️  Time: {elapsed:.1f}s")
    logger.info("=" * 60)
    
    con.close()
    return imputed_count


def main() -> None:
    ap = argparse.ArgumentParser(description="Impute missing park hours")
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
        count = impute_park_hours(base, logger)
        logger.info("Success!")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
