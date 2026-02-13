#!/usr/bin/env python3
"""
Calculate Wait Time Index (WTI) - Simplified Version

WTI = average predicted actual wait time per park per day.

Sources:
- Historical: from fact tables (ACTUAL preferred, POSTED fallback)
- Future: from forecast predictions

Output: wti/wti.parquet with columns:
  park_code, park_date, wti, n_entities, source
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

OUTPUT_BASE = Path("/home/wilma/hazeydata/pipeline")


def setup_logging() -> logging.Logger:
    log_dir = OUTPUT_BASE / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"calculate_wti_simple_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Calculate WTI (simplified)")
    parser.add_argument("--output-base", type=Path, default=OUTPUT_BASE)
    parser.add_argument("--historical-only", action="store_true", help="Only compute historical WTI")
    parser.add_argument("--forecast-only", action="store_true", help="Only compute forecast WTI")
    args = parser.parse_args()
    
    logger = setup_logging()
    output_base = args.output_base
    
    logger.info("=" * 60)
    logger.info("CALCULATE WTI (Simplified)")
    logger.info("=" * 60)
    
    wti_dir = output_base / "wti"
    wti_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()

    # SQL expression to derive park_code from entity_code
    # Handles multi-char prefixes: USH→UH, TDL→TD, TDS→TD
    # Everything else uses first 2 alpha chars
    def park_code_sql(col="entity_code"):
        """Return SQL CASE expression that maps entity_code to canonical park_code."""
        return f"""CASE
            WHEN {col} LIKE 'USH%' THEN 'UH'
            WHEN {col} LIKE 'TDL%' THEN 'TD'
            WHEN {col} LIKE 'TDS%' THEN 'TD'
            ELSE UPPER(LEFT({col}, 2))
        END"""

    # Operating calendar: filter to is_operating=TRUE; graceful fallback if missing
    oc_path = output_base / "operating_calendar" / "operating_calendar.parquet"
    use_oc = oc_path.exists()
    if use_oc:
        logger.info(f"Using operating calendar: {oc_path}")
    else:
        logger.info("Operating calendar not found; assuming all entities operating")

    oc_str = str(oc_path.resolve()).replace("\\", "/")
    parquet_str = str((output_base / "fact_tables" / "parquet").resolve()).replace("\\", "/")

    results = []

    # Pre-compute park_code SQL expressions for use in all queries
    pc_f = park_code_sql("f.entity_code")
    pc_bare = park_code_sql("entity_code")

    # =========================================================================
    # HISTORICAL WTI (from fact tables)
    # =========================================================================
    if not args.forecast_only:
        logger.info("Computing historical WTI from fact tables...")

        fact_join_oc = f"""
            FROM read_parquet('{parquet_str}/*.parquet') f
            JOIN read_parquet('{oc_str}') oc
                ON f.entity_code = oc.entity_code
                AND CAST(f.park_date AS DATE) = CAST(oc.park_date AS DATE)
            WHERE f.wait_time_minutes > 0
              AND oc.is_operating = TRUE
        """ if use_oc else f"""
            FROM read_parquet('{parquet_str}/*.parquet')
            WHERE wait_time_minutes > 0
        """
        fact_cols = f"f.entity_code, {pc_f} as park_code, CAST(f.park_date AS DATE) as park_date, f.wait_time_type, f.wait_time_minutes" if use_oc else f"{pc_bare} as park_code, CAST(park_date AS DATE) as park_date, entity_code, wait_time_type, wait_time_minutes"

        historical_sql = f"""
            WITH fact_data AS (
                SELECT {fact_cols}
                {fact_join_oc}
            ),
            daily_entity_avg AS (
                SELECT 
                    park_code, park_date, entity_code,
                    COALESCE(
                        AVG(CASE WHEN wait_time_type = 'ACTUAL' THEN wait_time_minutes END),
                        AVG(CASE WHEN wait_time_type = 'POSTED' THEN wait_time_minutes END)
                    ) as entity_avg,
                    CASE WHEN COUNT(CASE WHEN wait_time_type = 'ACTUAL' THEN 1 END) > 0 THEN 'actual' ELSE 'posted' END as wait_type_used
                FROM fact_data
                GROUP BY park_code, park_date, entity_code
            )
            SELECT park_code, park_date, ROUND(AVG(entity_avg), 1) as wti, COUNT(DISTINCT entity_code) as n_entities, 'historical' as source
            FROM daily_entity_avg
            WHERE entity_avg IS NOT NULL
            GROUP BY park_code, park_date
            ORDER BY park_code, park_date
        """
        try:
            historical_wti = con.execute(historical_sql).fetchdf()
        except Exception as e:
            logger.warning(f"Operating calendar query failed (fallback to no filter): {e}")
            historical_wti = con.execute(f"""
                WITH fact_data AS (
                    SELECT {pc_bare} as park_code, CAST(park_date AS DATE) as park_date, entity_code, wait_time_type, wait_time_minutes
                    FROM read_parquet('{parquet_str}/*.parquet')
                    WHERE wait_time_minutes > 0
                ),
                daily_entity_avg AS (
                    SELECT park_code, park_date, entity_code,
                        COALESCE(AVG(CASE WHEN wait_time_type = 'ACTUAL' THEN wait_time_minutes END), AVG(CASE WHEN wait_time_type = 'POSTED' THEN wait_time_minutes END)) as entity_avg,
                        CASE WHEN COUNT(CASE WHEN wait_time_type = 'ACTUAL' THEN 1 END) > 0 THEN 'actual' ELSE 'posted' END as wait_type_used
                    FROM fact_data
                    GROUP BY park_code, park_date, entity_code
                )
                SELECT park_code, park_date, ROUND(AVG(entity_avg), 1) as wti, COUNT(DISTINCT entity_code) as n_entities, 'historical' as source
                FROM daily_entity_avg WHERE entity_avg IS NOT NULL
                GROUP BY park_code, park_date ORDER BY park_code, park_date
            """).fetchdf()
        
        logger.info(f"  Historical WTI: {len(historical_wti):,} park-dates")
        results.append(historical_wti)
    
    # =========================================================================
    # FORECAST WTI (from predictions)
    # =========================================================================
    if not args.historical_only:
        forecast_file = output_base / "curves" / "forecast_parquet" / "all_forecasts.parquet"
        forecast_str = str(forecast_file.resolve()).replace("\\", "/")

        if forecast_file.exists():
            logger.info("Computing forecast WTI from predictions...")

            if use_oc:
                forecast_sql = f"""
                    SELECT 
                        {pc_f} as park_code,
                        f.park_date,
                        ROUND(AVG(f.predicted_actual), 1) as wti,
                        COUNT(DISTINCT f.entity_code) as n_entities,
                        'forecast' as source
                    FROM read_parquet('{forecast_str}') f
                    JOIN read_parquet('{oc_str}') oc
                        ON f.entity_code = oc.entity_code
                        AND CAST(f.park_date AS DATE) = CAST(oc.park_date AS DATE)
                    WHERE f.predicted_actual > 0
                      AND oc.is_operating = TRUE
                    GROUP BY {pc_f}, f.park_date
                    ORDER BY park_code, f.park_date
                """
            else:
                forecast_sql = f"""
                    SELECT 
                        {pc_bare} as park_code,
                        park_date,
                        ROUND(AVG(predicted_actual), 1) as wti,
                        COUNT(DISTINCT entity_code) as n_entities,
                        'forecast' as source
                    FROM read_parquet('{forecast_str}')
                    WHERE predicted_actual > 0
                    GROUP BY {pc_bare}, park_date
                    ORDER BY park_code, park_date
                """
            try:
                forecast_wti = con.execute(forecast_sql).fetchdf()
            except Exception as e:
                logger.warning(f"Forecast WTI with operating calendar failed (fallback): {e}")
                forecast_wti = con.execute(f"""
                    SELECT {pc_bare} as park_code, park_date,
                        ROUND(AVG(predicted_actual), 1) as wti, COUNT(DISTINCT entity_code) as n_entities, 'forecast' as source
                    FROM read_parquet('{forecast_str}')
                    WHERE predicted_actual > 0
                    GROUP BY {pc_bare}, park_date ORDER BY park_code, park_date
                """).fetchdf()
            
            logger.info(f"  Forecast WTI: {len(forecast_wti):,} park-dates")
            results.append(forecast_wti)
        else:
            logger.warning(f"  Forecast file not found: {forecast_file}")
    
    con.close()
    
    # =========================================================================
    # COMBINE AND SAVE
    # =========================================================================
    if results:
        combined = pd.concat(results, ignore_index=True)
        
        # For overlapping dates, prefer historical over forecast
        combined = combined.sort_values(['park_code', 'park_date', 'source'])
        combined = combined.drop_duplicates(subset=['park_code', 'park_date'], keep='first')
        combined = combined.sort_values(['park_code', 'park_date'])
        
        output_file = wti_dir / "wti.parquet"
        combined.to_parquet(output_file, index=False)
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("WTI COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Total park-dates: {len(combined):,}")
        logger.info(f"By source:")
        for source, count in combined['source'].value_counts().items():
            logger.info(f"  {source}: {count:,}")
        logger.info(f"Parks: {sorted(combined['park_code'].unique())}")
        logger.info(f"Date range: {combined['park_date'].min()} to {combined['park_date'].max()}")
        logger.info(f"Output: {output_file}")
        logger.info("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
