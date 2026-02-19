#!/usr/bin/env python3
"""
Initialize the shared DuckDB database for bot + dashboard.

Creates tpcr_live.duckdb with schema and backfills from existing pipeline data.
Run once after pipeline has produced wti, forecasts, dimentity, and staging CSVs.

Usage:
    python scripts/init_live_duckdb.py [--output-base PATH]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
import pandas as pd

# Ensure src is on path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from utils import get_output_base
from utils.park_code import park_code_sql

DEFAULT_OUTPUT_BASE = Path("/home/wilma/hazeydata/pipeline")


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger(__name__)


def init(db_path: Path, output_base: Path, logger) -> bool:
    """Create schema and backfill from existing data."""
    db_path = db_path.resolve()
    output_base = output_base.resolve()

    staging_dir = output_base / "staging" / "queue_times"
    wti_path = output_base / "wti" / "wti.parquet"
    forecast_path = output_base / "curves" / "forecast_parquet" / "all_forecasts.parquet"
    dimentity_path = output_base / "dimension_tables" / "dimentity.csv"

    logger.info("=" * 60)
    logger.info("INIT LIVE DUCKDB")
    logger.info("=" * 60)
    logger.info(f"Output base: {output_base}")
    logger.info(f"DuckDB path: {db_path}")

    con = duckdb.connect(str(db_path))

    # --- Schema ---
    logger.info("Creating schema...")

    con.execute("""
        CREATE TABLE IF NOT EXISTS live_waits (
            entity_code     VARCHAR NOT NULL,
            observed_at     TIMESTAMP WITH TIME ZONE NOT NULL,
            wait_time_type  VARCHAR DEFAULT 'POSTED',
            wait_time_minutes INTEGER NOT NULL,
            park_date       DATE NOT NULL,
            inserted_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (entity_code, observed_at, wait_time_type)
        )
    """)

    try:
        con.execute("CREATE INDEX IF NOT EXISTS idx_live_waits_park_date ON live_waits (park_date, entity_code)")
    except duckdb.Error:
        pass  # Index may already exist

    con.execute("""
        CREATE TABLE IF NOT EXISTS wti (
            park_code       VARCHAR NOT NULL,
            park_date       DATE NOT NULL,
            time_slot       VARCHAR,
            wti             DOUBLE NOT NULL,
            source          VARCHAR DEFAULT 'forecast',
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (park_code, park_date, time_slot)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS forecasts (
            entity_code     VARCHAR NOT NULL,
            park_date       DATE NOT NULL,
            time_slot       VARCHAR NOT NULL,
            predicted_actual DOUBLE,
            predicted_posted DOUBLE,
            model_version   VARCHAR,
            prediction_method VARCHAR,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (entity_code, park_date, time_slot)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            entity_code     VARCHAR PRIMARY KEY,
            entity_name     VARCHAR,
            short_name      VARCHAR,
            park_code       VARCHAR,
            property_code   VARCHAR,
            category        VARCHAR,
            has_wait_times  BOOLEAN DEFAULT TRUE,
            wait_time_type  VARCHAR DEFAULT 'standby',
            is_extinct      BOOLEAN DEFAULT FALSE,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS data_freshness (
            source          VARCHAR PRIMARY KEY,
            last_updated     TIMESTAMP NOT NULL,
            row_count        INTEGER,
            notes            VARCHAR
        )
    """)

    # DuckDB supports concurrent readers by default; use read_only=True for bot/dashboard

    # --- Backfill live_waits from staging CSVs ---
    if staging_dir.exists():
        csv_files = list(staging_dir.glob("**/*.csv"))
        if csv_files:
            csv_pattern = str(staging_dir / "**" / "*.csv").replace("\\", "/")
            logger.info(f"Backfilling live_waits from {len(csv_files)} CSV files...")
            try:
                con.execute(f"""
                    INSERT OR IGNORE INTO live_waits 
                        (entity_code, observed_at, wait_time_type, wait_time_minutes, park_date)
                    SELECT 
                        entity_code,
                        observed_at::TIMESTAMPTZ,
                        COALESCE(wait_time_type, 'POSTED'),
                        wait_time_minutes::INTEGER,
                        observed_at::DATE
                    FROM read_csv_auto('{csv_pattern}')
                    WHERE wait_time_minutes > 0
                """)
                n = con.execute("SELECT COUNT(*) FROM live_waits").fetchone()[0]
                logger.info(f"  live_waits: {n:,} rows")
            except Exception as e:
                logger.warning(f"  live_waits backfill failed: {e}")
        else:
            logger.info("  live_waits: no CSV files found (skipped)")
    else:
        logger.info("  live_waits: staging dir not found (skipped)")

    # --- Backfill WTI from parquet ---
    if wti_path.exists():
        logger.info("Backfilling wti from parquet...")
        try:
            wti_str = str(wti_path).replace("\\", "/")
            con.execute(f"""
                INSERT OR IGNORE INTO wti 
                    (park_code, park_date, time_slot, wti, source, updated_at)
                SELECT 
                    park_code,
                    park_date::DATE,
                    COALESCE(CAST(time_slot AS VARCHAR), 'daily'),
                    wti,
                    COALESCE(source, 'forecast'),
                    CURRENT_TIMESTAMP
                FROM read_parquet('{wti_str}')
            """)
            n = con.execute("SELECT COUNT(*) FROM wti").fetchone()[0]
            logger.info(f"  wti: {n:,} rows")
        except Exception as e:
            logger.warning(f"  wti backfill failed: {e}")
    else:
        logger.info("  wti: parquet not found (skipped)")

    # --- Backfill entities from dimentity ---
    if dimentity_path.exists():
        logger.info("Backfilling entities from dimentity...")
        try:
            dim_str = str(dimentity_path).replace("\\", "/")
            # Detect columns: dimentity schema varies (code/entity_code, name/entity_name, etc.)
            cols_df = pd.read_csv(dimentity_path, nrows=0)
            col_names = {c.lower() for c in cols_df.columns}
            ec_col = "entity_code" if "entity_code" in col_names else "code"
            en_col = "entity_name" if "entity_name" in col_names else "name"
            pc_sql = park_code_sql(ec_col)
            short_sql = "short_name" if "short_name" in col_names else "NULL"
            prop_sql = "property_code" if "property_code" in col_names else "NULL"
            park_sql = f"COALESCE(park_code, ({pc_sql}))" if "park_code" in col_names else pc_sql
            con.execute(f"""
                INSERT OR REPLACE INTO entities 
                    (entity_code, entity_name, short_name, park_code, property_code, updated_at)
                SELECT 
                    {ec_col},
                    {en_col},
                    {short_sql},
                    {park_sql},
                    {prop_sql},
                    CURRENT_TIMESTAMP
                FROM read_csv_auto('{dim_str}')
            """)
            n = con.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            logger.info(f"  entities: {n:,} rows")
        except Exception as e:
            logger.warning(f"  entities backfill failed: {e}")
    else:
        logger.info("  entities: dimentity not found (skipped)")

    # --- Backfill forecasts from parquet ---
    if forecast_path.exists():
        logger.info("Backfilling forecasts from parquet...")
        try:
            fc_str = str(forecast_path).replace("\\", "/")
            con.execute(f"""
                INSERT OR IGNORE INTO forecasts 
                    (entity_code, park_date, time_slot, predicted_actual, prediction_method, updated_at)
                SELECT 
                    entity_code,
                    park_date::DATE,
                    CAST(time_slot AS VARCHAR),
                    predicted_actual,
                    COALESCE(prediction_method, 'model'),
                    CURRENT_TIMESTAMP
                FROM read_parquet('{fc_str}')
            """)
            n = con.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
            logger.info(f"  forecasts: {n:,} rows")
        except Exception as e:
            logger.warning(f"  forecasts backfill failed: {e}")
    else:
        logger.info("  forecasts: parquet not found (skipped)")

    # --- Initial data_freshness ---
    con.execute("""
        INSERT OR REPLACE INTO data_freshness (source, last_updated, row_count, notes)
        SELECT 'scraper', COALESCE(MAX(inserted_at), CURRENT_TIMESTAMP), COUNT(*), 'init'
        FROM live_waits
    """)
    con.execute("""
        INSERT OR REPLACE INTO data_freshness (source, last_updated, row_count, notes)
        SELECT 'wti', CURRENT_TIMESTAMP, (SELECT COUNT(*) FROM wti), 'init'
    """)
    con.execute("""
        INSERT OR REPLACE INTO data_freshness (source, last_updated, row_count, notes)
        SELECT 'forecasts', CURRENT_TIMESTAMP, (SELECT COUNT(*) FROM forecasts), 'init'
    """)
    con.execute("""
        INSERT OR REPLACE INTO data_freshness (source, last_updated, row_count, notes)
        SELECT 'entities', CURRENT_TIMESTAMP, (SELECT COUNT(*) FROM entities), 'init'
    """)

    con.close()

    logger.info("=" * 60)
    logger.info("DuckDB initialized successfully")
    logger.info("=" * 60)
    return True


def main():
    parser = argparse.ArgumentParser(description="Initialize shared DuckDB for bot + dashboard")
    parser.add_argument("--output-base", type=Path, default=None, help="Pipeline output base")
    args = parser.parse_args()

    output_base = (args.output_base or get_output_base()).resolve()
    db_path = output_base / "tpcr_live.duckdb"

    logger = setup_logging()
    success = init(db_path, output_base, logger)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
