#!/usr/bin/env python3
"""
Operating Calendar Builder

================================================================================
PURPOSE
================================================================================
Combines permanent closures (extinct_on from dimentity) and temporary closures
(from raw_closures/*.csv) into a single operating calendar. Used by training,
forecasting, and WTI to exclude closed attractions.

Input: dimentity.csv, raw_closures/*.csv
Output: operating_calendar/operating_calendar.parquet

================================================================================
USAGE
================================================================================
  python src/build_operating_calendar.py
  python src/build_operating_calendar.py --output-base /path --start-date 2025-01-01 --end-date 2026-12-31
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from utils import get_output_base

# Sentinel dates per spec
SENTINEL_UNKNOWN_START = "1900-01-01"
SENTINEL_OPEN_END = "9999-12-31"

# =============================================================================
# LOGGING
# =============================================================================
def setup_logging(log_dir: Path) -> logging.Logger:
    from datetime import datetime
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"build_operating_calendar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger(__name__)
    logger.info("Log file: %s", log_file)
    return logger


# =============================================================================
# MAIN
# =============================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description="Build operating calendar from dimentity + closures")
    ap.add_argument("--output-base", type=Path, default=get_output_base())
    ap.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date YYYY-MM-DD (default: today - 30)",
    )
    ap.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date YYYY-MM-DD (default: today + 365)",
    )
    ap.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = ap.parse_args()

    base = args.output_base.resolve()
    log_dir = base / "logs"
    logger = setup_logging(log_dir)

    today = date.today()
    start_date = args.start_date or (today - timedelta(days=30)).isoformat()
    end_date = args.end_date or (today + timedelta(days=365)).isoformat()

    logger.info("=" * 60)
    logger.info("Operating calendar build")
    logger.info("=" * 60)
    logger.info("Output base: %s", base)
    logger.info("Date range: %s to %s", start_date, end_date)

    dim_path = base / "dimension_tables" / "dimentity.csv"
    raw_closures_dir = base / "raw_closures"
    out_dir = base / "operating_calendar"

    if not dim_path.exists():
        logger.error("dimentity.csv not found at %s", dim_path)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / "operating_calendar.parquet"
    csv_path = out_dir / "operating_calendar.csv"

    # Always rebuild — closures can change daily. --force kept for back-compat.
    if parquet_path.exists():
        logger.info("Overwriting existing calendar: %s", parquet_path)

    con = duckdb.connect()
    dim_str = str(dim_path).replace("\\", "/")

    # Resolve entity code column
    dim_sample = con.execute(f"SELECT * FROM read_csv('{dim_str}', AUTO_DETECT=TRUE) LIMIT 1").fetchdf()
    code_col = "code" if "code" in dim_sample.columns else "entity_code" if "entity_code" in dim_sample.columns else None
    extinct_col = "extinct_on" if "extinct_on" in dim_sample.columns else None

    if not code_col:
        logger.error("dimentity has no 'code' or 'entity_code' column")
        sys.exit(1)

    # Step 1: Load entities with extinct_on
    extinct_expr = f"COALESCE({extinct_col}, '{SENTINEL_OPEN_END}')" if extinct_col else f"'{SENTINEL_OPEN_END}'"
    entities_sql = f"""
        SELECT {code_col} as entity_code, {extinct_expr} as extinct_on
        FROM read_csv('{dim_str}', AUTO_DETECT=TRUE)
    """
    entities = con.execute(entities_sql).fetchdf()
    logger.info("Loaded %d entities from dimentity", len(entities))

    # Step 2: Load temporary closures (if any)
    closure_files = list(raw_closures_dir.glob("*.csv")) if raw_closures_dir.exists() else []
    if closure_files:
        paths = [str(p).replace("\\", "/") for p in closure_files]
        paths_str = ", ".join(f"'{p}'" for p in paths)
        # object_type filter: only attractions; if column missing, include all
        try:
            sample = con.execute(f"SELECT * FROM read_csv([{paths_str}], AUTO_DETECT=TRUE) LIMIT 1").fetchdf()
            type_filter = "WHERE object_type = 'attraction'" if "object_type" in sample.columns else ""
        except Exception:
            type_filter = ""
        closures_sql = f"""
            SELECT object_code as entity_code,
                   COALESCE(start_date, '{SENTINEL_UNKNOWN_START}') as closure_start,
                   COALESCE(finish_date, '{SENTINEL_OPEN_END}') as closure_end
            FROM read_csv([{paths_str}], AUTO_DETECT=TRUE)
            {type_filter}
        """
        try:
            closures = con.execute(closures_sql).fetchdf()
            logger.info("Loaded %d temporary closure records", len(closures))
        except Exception as e:
            logger.warning("Could not load closures (using empty): %s", e)
            closures = pd.DataFrame(columns=["entity_code", "closure_start", "closure_end"])
    else:
        logger.info("No raw_closures/*.csv found; using permanent closures only")
        closures = pd.DataFrame(columns=["entity_code", "closure_start", "closure_end"])

    # Register as DuckDB tables
    con.register("entities_df", entities)
    con.register("closures_df", closures)

    # Step 3: Build calendar
    # Permanent: closed if park_date >= extinct_on
    # Temporary: closed if park_date in [closure_start, closure_end] for ANY closure
    # Combined: operating = permanent_operating AND temporary_operating
    calendar = con.execute(f"""
        WITH date_range AS (
            SELECT unnest(generate_series(DATE '{start_date}'::DATE, DATE '{end_date}'::DATE, INTERVAL '1 day'))::DATE as park_date
        ),
        entity_dates AS (
            SELECT e.entity_code, d.park_date
            FROM entities_df e
            CROSS JOIN date_range d
        ),
        permanent AS (
            SELECT ed.entity_code, ed.park_date,
                   (ed.park_date < CAST(e.extinct_on AS DATE)) as is_perm
            FROM entity_dates ed
            JOIN entities_df e ON ed.entity_code = e.entity_code
        ),
        temp_closed AS (
            SELECT ed.entity_code, ed.park_date,
                   BOOL_OR(ed.park_date >= CAST(c.closure_start AS DATE)
                          AND ed.park_date <= CAST(c.closure_end AS DATE)) as is_closed
            FROM entity_dates ed
            LEFT JOIN closures_df c ON ed.entity_code = c.entity_code
            GROUP BY ed.entity_code, ed.park_date
        ),
        combined AS (
            SELECT p.entity_code, p.park_date,
                   p.is_perm AND COALESCE(NOT t.is_closed, TRUE) as is_operating
            FROM permanent p
            LEFT JOIN temp_closed t ON p.entity_code = t.entity_code AND p.park_date = t.park_date
        )
        SELECT entity_code, park_date, is_operating FROM combined ORDER BY entity_code, park_date
    """).fetchdf()

    logger.info("Calendar: %d rows", len(calendar))

    closed_pct = (1 - calendar["is_operating"].mean()) * 100
    if closed_pct > 20:
        logger.warning("> %.1f%% of entity-days are closed; verify data", closed_pct)

    calendar.to_parquet(parquet_path, index=False)
    logger.info("Wrote %s", parquet_path)

    calendar.to_csv(csv_path, index=False)
    logger.info("Wrote %s (debug backup)", csv_path)

    logger.info("Done.")


if __name__ == "__main__":
    main()
