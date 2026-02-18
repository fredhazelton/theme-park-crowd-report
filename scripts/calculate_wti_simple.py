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
        """Return SQL CASE expression that maps entity_code to canonical park_code.
        
        Handles 3-char prefixes that would otherwise be truncated to 2 chars:
        - USH* → UH (Universal Studios Hollywood, alternate prefix)
        - TDL* → TDL (Tokyo Disneyland, kept as 3-char)
        - TDS* → TDS (Tokyo DisneySea, kept as 3-char)
        """
        return f"""CASE
            WHEN {col} LIKE 'USH%' THEN 'UH'
            WHEN {col} LIKE 'TDL%' THEN 'TDL'
            WHEN {col} LIKE 'TDS%' THEN 'TDS'
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
    # HISTORICAL WTI (from synthetic actuals + real actuals)
    # =========================================================================
    # Policy: NEVER use raw POSTED times. All POSTED observations are converted
    # to synthetic actuals via the conversion model. Real ACTUAL observations are
    # used alongside synthetic actuals. This ensures apples-to-apples comparison
    # with forecast predictions (which also predict actuals).
    if not args.forecast_only:
        synth_dir = output_base / "synthetic_actuals"
        synth_str = str(synth_dir.resolve()).replace("\\", "/")
        synth_available = synth_dir.exists() and any(synth_dir.glob("*.parquet"))
        
        if synth_available:
            logger.info("Computing historical WTI from synthetic actuals + real actuals...")
            
            # Combine two sources:
            # 1. Synthetic actuals (POSTED→converted) from synthetic_actuals/*.parquet
            # 2. Real ACTUAL observations from fact tables
            # Average all together per entity per day
            
            historical_sql = f"""
                WITH 
                -- Source 1: Synthetic actuals (converted from POSTED)
                synth AS (
                    SELECT 
                        {park_code_sql("entity_code")} as park_code,
                        CAST(park_date AS DATE) as park_date,
                        entity_code,
                        synthetic_actual as wait_minutes,
                        'synthetic' as obs_type
                    FROM read_parquet('{synth_str}/*.parquet')
                    WHERE synthetic_actual > 0
                ),
                -- Source 2: Real ACTUAL observations
                real_actuals AS (
                    SELECT 
                        {pc_bare} as park_code,
                        CAST(park_date AS DATE) as park_date,
                        entity_code,
                        wait_time_minutes as wait_minutes,
                        'actual' as obs_type
                    FROM read_parquet('{parquet_str}/*.parquet')
                    WHERE wait_time_type = 'ACTUAL'
                      AND wait_time_minutes > 0
                ),
                -- Combine both sources
                all_obs AS (
                    SELECT * FROM synth
                    UNION ALL
                    SELECT * FROM real_actuals
                ),
                -- Average per entity per day
                daily_entity_avg AS (
                    SELECT park_code, park_date, entity_code,
                        ROUND(AVG(wait_minutes), 1) as entity_avg,
                        COUNT(*) as n_obs,
                        COUNT(CASE WHEN obs_type = 'actual' THEN 1 END) as n_actual,
                        COUNT(CASE WHEN obs_type = 'synthetic' THEN 1 END) as n_synthetic
                    FROM all_obs
                    GROUP BY park_code, park_date, entity_code
                )
                SELECT park_code, park_date, 
                    ROUND(AVG(entity_avg), 1) as wti, 
                    COUNT(DISTINCT entity_code) as n_entities, 
                    'historical' as source
                FROM daily_entity_avg
                WHERE entity_avg IS NOT NULL
                GROUP BY park_code, park_date
                ORDER BY park_code, park_date
            """
            try:
                historical_wti = con.execute(historical_sql).fetchdf()
                logger.info(f"  Historical WTI (synth+actual): {len(historical_wti):,} park-dates")
            except Exception as e:
                logger.error(f"  Synthetic actuals WTI query failed: {e}")
                logger.info("  Falling back to fact-table-only WTI...")
                synth_available = False
        
        if not synth_available:
            # Fallback: original method (COALESCE actual/posted) for dates without synthetic actuals
            logger.info("Computing historical WTI from fact tables (no synthetic actuals available)...")
            historical_sql = f"""
                WITH fact_data AS (
                    SELECT {pc_bare} as park_code, CAST(park_date AS DATE) as park_date, entity_code, wait_time_type, wait_time_minutes
                    FROM read_parquet('{parquet_str}/*.parquet')
                    WHERE wait_time_minutes > 0
                ),
                daily_entity_avg AS (
                    SELECT park_code, park_date, entity_code,
                        COALESCE(AVG(CASE WHEN wait_time_type = 'ACTUAL' THEN wait_time_minutes END), AVG(CASE WHEN wait_time_type = 'POSTED' THEN wait_time_minutes END)) as entity_avg
                    FROM fact_data
                    GROUP BY park_code, park_date, entity_code
                )
                SELECT park_code, park_date, ROUND(AVG(entity_avg), 1) as wti, COUNT(DISTINCT entity_code) as n_entities, 'historical' as source
                FROM daily_entity_avg WHERE entity_avg IS NOT NULL
                GROUP BY park_code, park_date ORDER BY park_code, park_date
            """
            historical_wti = con.execute(historical_sql).fetchdf()
            logger.info(f"  Historical WTI (fallback): {len(historical_wti):,} park-dates")
        
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
    # ADAPTIVE BIAS CORRECTION (forecast WTI only)
    # =========================================================================
    # Compare recent archived forecast WTI vs actual historical WTI to compute
    # per-park rolling correction factors. As models improve, corrections shrink to zero.
    if not args.historical_only and len(results) >= 1:
        wti_accuracy_path = output_base / "accuracy" / "wti_accuracy.parquet"
        if wti_accuracy_path.exists():
            try:
                bias_con = duckdb.connect()
                
                # Per-park bias correction using last 14 days of accuracy data
                park_biases = bias_con.execute(f"""
                    SELECT 
                        park_code,
                        AVG(wti_error) as avg_bias,
                        COUNT(*) as n_obs,
                        COUNT(DISTINCT park_date) as n_dates
                    FROM read_parquet('{wti_accuracy_path}')
                    WHERE park_date::DATE >= CURRENT_DATE - INTERVAL '14 days'
                    GROUP BY park_code
                    HAVING COUNT(DISTINCT park_date) >= 2
                    ORDER BY park_code
                """).fetchdf()
                
                # Also get overall stats for logging
                overall_row = bias_con.execute(f"""
                    SELECT 
                        AVG(wti_error) as avg_bias,
                        COUNT(*) as n_obs,
                        COUNT(DISTINCT park_date) as n_dates
                    FROM read_parquet('{wti_accuracy_path}')
                    WHERE park_date::DATE >= CURRENT_DATE - INTERVAL '14 days'
                """).fetchone()
                bias_con.close()
                
                if len(park_biases) > 0:
                    # Build per-park correction dict: correction = -bias
                    park_corrections = {}
                    for _, row in park_biases.iterrows():
                        park_corrections[row['park_code']] = round(-row['avg_bias'], 1)
                    
                    # Fallback for parks without enough data: use overall bias
                    overall_bias = overall_row[0] if overall_row[0] is not None else 0.0
                    fallback_correction = round(-overall_bias, 1)
                    
                    # Apply per-park corrections to forecast WTI dataframes only
                    before_avg = None
                    after_avg = None
                    for i, df in enumerate(results):
                        mask = df['source'] == 'forecast'
                        if mask.any():
                            before_avg = df.loc[mask, 'wti'].mean()
                            # Apply per-park correction, fallback to overall for unknown parks
                            corrections = df.loc[mask, 'park_code'].map(
                                lambda pc: park_corrections.get(pc, fallback_correction)
                            )
                            results[i].loc[mask, 'wti'] = (df.loc[mask, 'wti'] + corrections).round(1)
                            # Floor at 5 — WTI shouldn't go below a reasonable minimum
                            results[i].loc[mask, 'wti'] = results[i].loc[mask, 'wti'].clip(lower=5.0)
                            after_avg = results[i].loc[mask, 'wti'].mean()
                    
                    logger.info(f"  Per-park bias corrections applied:")
                    for park in sorted(park_corrections.keys()):
                        bias_val = -park_corrections[park]  # original bias
                        corr_val = park_corrections[park]
                        logger.info(f"    {park}: bias={bias_val:+.1f}, correction={corr_val:+.1f}")
                    logger.info(f"    Fallback (parks w/o data): {fallback_correction:+.1f}")
                    logger.info(f"    Overall bias: {overall_bias:.1f} ({overall_row[1]} obs, {overall_row[2]} dates)")
                    logger.info(f"    Forecast WTI avg: {before_avg:.1f} → {after_avg:.1f}")
                else:
                    logger.info(f"  Bias correction: insufficient per-park data. Skipping.")
            except Exception as e:
                logger.warning(f"  Bias correction failed (non-fatal): {e}")
        else:
            logger.info("  Bias correction: no wti_accuracy.parquet yet. Will activate once accuracy data accumulates.")

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
