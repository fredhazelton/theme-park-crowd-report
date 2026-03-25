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
import os
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

OUTPUT_BASE = Path("/home/wilma/hazeydata/pipeline")


def setup_logging() -> logging.Logger:
    log_dir = OUTPUT_BASE / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"calculate_wti_simple_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    handlers = [logging.StreamHandler(sys.stdout)]
    # Only add file handler when NOT running under the pipeline's tee
    # (PIPELINE_LOG env var is set by run_daily_pipeline.sh)
    if not os.environ.get("PIPELINE_LOG"):
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
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

    # Load has_posted filter from dimentity
    dimentity_path = output_base / "dimension_tables" / "dimentity.csv"
    dimentity_str = str(dimentity_path.resolve()).replace("\\", "/")
    if dimentity_path.exists():
        # Build a set of entity codes with has_posted=True for SQL filtering
        has_posted_count = con.execute(
            f"SELECT COUNT(*) FROM read_csv_auto('{dimentity_str}') WHERE has_posted = TRUE"
        ).fetchone()[0]
        logger.info(f"Entity filter: has_posted=TRUE → {has_posted_count} entities (from dimentity)")
        # Create temp table for efficient joins
        con.execute(f"""
            CREATE TEMP TABLE posted_entities AS
            SELECT code as entity_code
            FROM read_csv_auto('{dimentity_str}')
            WHERE has_posted = TRUE
        """)
        use_posted_filter = True
    else:
        logger.warning("dimentity.csv not found — WTI will include ALL entities (no has_posted filter)")
        use_posted_filter = False

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
            
            # Combine two sources with weighting:
            # 1. Synthetic actuals (POSTED→converted) — weight 1.0
            # 2. Real ACTUAL observations — weight 3.5 (ground truth)
            # Weighted average per entity per day, matching training methodology
            
            REAL_ACTUAL_WEIGHT = 3.5
            SYNTHETIC_WEIGHT = 1.0
            
            # has_posted filter: only include entities that actually post wait times
            posted_join = "JOIN posted_entities pe ON all_obs.entity_code = pe.entity_code" if use_posted_filter else ""
            
            historical_sql = f"""
                WITH 
                -- Source 1: Synthetic actuals (converted from POSTED) — weight {SYNTHETIC_WEIGHT}
                synth AS (
                    SELECT 
                        {park_code_sql("entity_code")} as park_code,
                        CAST(park_date AS DATE) as park_date,
                        entity_code,
                        synthetic_actual as wait_minutes,
                        {SYNTHETIC_WEIGHT} as weight
                    FROM read_parquet('{synth_str}/*.parquet')
                    WHERE synthetic_actual > 0
                ),
                -- Source 2: Real ACTUAL observations — weight {REAL_ACTUAL_WEIGHT}
                real_actuals AS (
                    SELECT 
                        {pc_bare} as park_code,
                        CAST(park_date AS DATE) as park_date,
                        entity_code,
                        wait_time_minutes as wait_minutes,
                        {REAL_ACTUAL_WEIGHT} as weight
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
                -- Filter to has_posted entities only
                filtered_obs AS (
                    SELECT all_obs.* FROM all_obs
                    {posted_join}
                ),
                -- Weighted average per entity per day
                daily_entity_avg AS (
                    SELECT park_code, park_date, entity_code,
                        ROUND(SUM(wait_minutes * weight) / SUM(weight), 1) as entity_avg,
                        COUNT(*) as n_obs,
                        SUM(CASE WHEN weight = {REAL_ACTUAL_WEIGHT} THEN 1 ELSE 0 END) as n_actual,
                        SUM(CASE WHEN weight = {SYNTHETIC_WEIGHT} THEN 1 ELSE 0 END) as n_synthetic
                    FROM filtered_obs
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
            posted_join_fb = "JOIN posted_entities pe ON fact_data.entity_code = pe.entity_code" if use_posted_filter else ""
            historical_sql = f"""
                WITH fact_data AS (
                    SELECT {pc_bare} as park_code, CAST(park_date AS DATE) as park_date, entity_code, wait_time_type, wait_time_minutes
                    FROM read_parquet('{parquet_str}/*.parquet')
                    WHERE wait_time_minutes > 0
                ),
                filtered_facts AS (
                    SELECT fact_data.* FROM fact_data
                    {posted_join_fb}
                ),
                daily_entity_avg AS (
                    SELECT park_code, park_date, entity_code,
                        COALESCE(AVG(CASE WHEN wait_time_type = 'ACTUAL' THEN wait_time_minutes END), AVG(CASE WHEN wait_time_type = 'POSTED' THEN wait_time_minutes END)) as entity_avg
                    FROM filtered_facts
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

            posted_join_fc = "JOIN posted_entities pe ON f.entity_code = pe.entity_code" if use_posted_filter else ""
            posted_join_fc_bare = "JOIN posted_entities pe ON entity_code = pe.entity_code" if use_posted_filter else ""

            # Exclude fallback_ratio entities from WTI — they predict flat constants
            # (no trained model, no meaningful signal). Only include entities with
            # real predictive models (model_v2, model_actuals, aggregate, etc.)
            EXCLUDED_METHODS = "('fallback_ratio')"

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
                    {posted_join_fc}
                    WHERE f.predicted_actual > 0
                      AND oc.is_operating = TRUE
                      AND f.prediction_method NOT IN {EXCLUDED_METHODS}
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
                    {posted_join_fc_bare}
                    WHERE predicted_actual > 0
                      AND prediction_method NOT IN {EXCLUDED_METHODS}
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
                    {posted_join_fc_bare}
                    WHERE predicted_actual > 0
                      AND prediction_method NOT IN {EXCLUDED_METHODS}
                    GROUP BY {pc_bare}, park_date ORDER BY park_code, park_date
                """).fetchdf()
            
            logger.info(f"  Forecast WTI: {len(forecast_wti):,} park-dates (excluding fallback_ratio entities)")
            results.append(forecast_wti)
        else:
            logger.warning(f"  Forecast file not found: {forecast_file}")
    
    con.close()
    
    # =========================================================================
    # ADAPTIVE BIAS CORRECTION (DISABLED 2026-02-28)
    # PERMANENTLY DISABLED 2026-03-21: Bias correction caused 83% accuracy degradation
    # Evidence: MAE 8.5 with correction vs 1.5 without correction
    # Decision: Kill bias correction system permanently
    # =========================================================================
    # Disabled: season_year feature in XGBoost already captures short-term trends,
    # making external bias correction redundant (double-correction).
    # Raw MAE consistently outperformed adjusted MAE over 14-day evaluation window.
    # Keeping code intact for potential future use.
    if False:  # PERMANENTLY DISABLED - DO NOT RE-ENABLE
        wti_accuracy_path = output_base / "accuracy" / "wti_accuracy.parquet"
        entity_accuracy_path = output_base / "accuracy" / "entity_daily_accuracy.parquet"
        if wti_accuracy_path.exists():
            try:
                bias_con = duckdb.connect()
                
                # Per-park bias correction using last 14 days of accuracy data.
                # STRICT: Only use actuals-first (model_actuals) predictions.
                # No fallback to old methods — skip correction if insufficient data.
                
                has_actuals_data = False
                if entity_accuracy_path.exists():
                    actuals_check = bias_con.execute(f"""
                        SELECT COUNT(DISTINCT park_date) as n_dates
                        FROM read_parquet('{entity_accuracy_path}')
                        WHERE park_date::DATE >= CURRENT_DATE - INTERVAL '14 days'
                        AND prediction_method = 'model_actuals'
                    """).fetchone()
                    if actuals_check[0] >= 2:
                        has_actuals_data = True
                        logger.info(f"  Bias correction: using actuals-first predictions only ({actuals_check[0]} dates)")
                    else:
                        logger.info(f"  Bias correction: only {actuals_check[0]} actuals-first date(s) — need ≥2, skipping correction")
                
                if has_actuals_data:
                    # Compute per-park bias from entity-level accuracy, actuals-first only.
                    # Aggregate entity bias up to park level (weighted by slot count).
                    park_biases = bias_con.execute(f"""
                        SELECT 
                            LEFT(entity_code, 2) as park_code,
                            SUM(bias * n_slots) / SUM(n_slots) as avg_bias,
                            SUM(n_slots) as n_obs,
                            COUNT(DISTINCT park_date) as n_dates
                        FROM read_parquet('{entity_accuracy_path}')
                        WHERE park_date::DATE >= CURRENT_DATE - INTERVAL '14 days'
                        AND prediction_method = 'model_actuals'
                        GROUP BY LEFT(entity_code, 2)
                        HAVING COUNT(DISTINCT park_date) >= 2
                        ORDER BY park_code
                    """).fetchdf()
                    
                    overall_row = bias_con.execute(f"""
                        SELECT 
                            SUM(bias * n_slots) / SUM(n_slots) as avg_bias,
                            SUM(n_slots) as n_obs,
                            COUNT(DISTINCT park_date) as n_dates
                        FROM read_parquet('{entity_accuracy_path}')
                        WHERE park_date::DATE >= CURRENT_DATE - INTERVAL '14 days'
                        AND prediction_method = 'model_actuals'
                    """).fetchone()
                else:
                    park_biases = pd.DataFrame()
                bias_con.close()
                
                if len(park_biases) > 0:
                    # Build per-park correction dict: correction = -bias
                    # Conservative approach:
                    #   - Cap corrections at ±10 WTI points (prevent wild swings)
                    #   - Dampen by confidence factor based on n_dates (ramp 2→7 days)
                    #   - Parks with <5 dates get proportionally smaller corrections
                    MAX_CORRECTION = 10.0  # Cap: never adjust more than ±10 WTI points
                    FULL_CONFIDENCE_DATES = 7  # Need 7 dates for full correction strength
                    
                    park_corrections = {}
                    for _, row in park_biases.iterrows():
                        raw_correction = -row['avg_bias']
                        n_dates = row['n_dates']
                        # Confidence ramp: 2 dates = 28%, 3 = 43%, 5 = 71%, 7+ = 100%
                        confidence = min(1.0, n_dates / FULL_CONFIDENCE_DATES)
                        # Cap then dampen
                        capped = max(-MAX_CORRECTION, min(MAX_CORRECTION, raw_correction))
                        dampened = round(capped * confidence, 1)
                        park_corrections[row['park_code']] = dampened
                    
                    # Fallback: no correction for parks without enough data
                    # (was using overall bias, but that often made things worse)
                    overall_bias = overall_row[0] if overall_row[0] is not None else 0.0
                    fallback_correction = 0.0
                    
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
                    
                    logger.info(f"  Per-park bias corrections (capped ±{MAX_CORRECTION}, dampened by confidence):")
                    for park in sorted(park_corrections.keys()):
                        park_row = park_biases[park_biases['park_code'] == park].iloc[0]
                        raw_bias = park_row['avg_bias']
                        n_dates = park_row['n_dates']
                        confidence = min(1.0, n_dates / FULL_CONFIDENCE_DATES)
                        corr_val = park_corrections[park]
                        logger.info(f"    {park}: bias={raw_bias:+.1f}, correction={corr_val:+.1f} ({n_dates}d, {confidence:.0%} conf)")
                    logger.info(f"    Fallback (parks w/o data): {fallback_correction:+.1f} (no correction)")
                    logger.info(f"    Overall bias: {overall_bias:.1f} ({overall_row[1]} obs, {overall_row[2]} dates)")
                    logger.info(f"    Forecast WTI avg: {before_avg:.1f} → {after_avg:.1f}")
                else:
                    logger.info(f"  Bias correction: insufficient per-park data. Skipping.")
            except Exception as e:
                logger.warning(f"  Bias correction failed (non-fatal): {e}")
        else:
            logger.info("  Bias correction: no wti_accuracy.parquet yet. Will activate once accuracy data accumulates.")

    # =========================================================================
    # QUANTILE MAPPING — match forecast distribution to historical
    # =========================================================================
    # The XGBoost models compress predictions toward the mean, producing a
    # narrow forecast WTI range (~5-17) vs historical reality (~2-56).
    # Quantile mapping preserves the model's relative ordering (it knows which
    # days are busier) while stretching the scale to match historical variance.
    # This is a stopgap until NGBoost (heteroscedastic) models are deployed.
    
    if len(results) >= 2:  # need both historical and forecast
        try:
            historical_dfs = [df for df in results if (df['source'] == 'historical').any()]
            forecast_dfs_idx = [i for i, df in enumerate(results) if (df['source'] == 'forecast').any()]
            
            if historical_dfs and forecast_dfs_idx:
                # Build historical reference distribution per park
                hist_combined = pd.concat(historical_dfs, ignore_index=True)
                hist_combined = hist_combined[hist_combined['source'] == 'historical']
                
                parks_mapped = 0
                for idx in forecast_dfs_idx:
                    df = results[idx]
                    forecast_mask = df['source'] == 'forecast'
                    if not forecast_mask.any():
                        continue
                    
                    for park_code in df.loc[forecast_mask, 'park_code'].unique():
                        park_hist = hist_combined[hist_combined['park_code'] == park_code]['wti'].values
                        if len(park_hist) < 30:
                            continue  # not enough historical data
                        
                        park_forecast_mask = forecast_mask & (df['park_code'] == park_code)
                        forecast_vals = df.loc[park_forecast_mask, 'wti'].values
                        
                        if len(forecast_vals) == 0:
                            continue
                        
                        # Compute percentile rank of each forecast value within forecast distribution
                        from scipy import stats
                        forecast_percentiles = stats.rankdata(forecast_vals, method='average') / len(forecast_vals)
                        
                        # Clamp percentiles to [1st, 99th] to avoid extreme tail values
                        # The historical min/max are often one-off anomalies (e.g. Christmas 2009)
                        # that shouldn't be assigned to the single highest/lowest forecast day
                        PERCENTILE_FLOOR = 1.0   # P1
                        PERCENTILE_CAP = 99.0     # P99
                        clamped_percentiles = np.clip(
                            forecast_percentiles * 100,
                            PERCENTILE_FLOOR,
                            PERCENTILE_CAP
                        )
                        
                        # Map clamped percentiles to the historical distribution
                        mapped_vals = np.percentile(park_hist, clamped_percentiles)
                        
                        results[idx].loc[park_forecast_mask, 'wti'] = np.round(mapped_vals, 1)
                        parks_mapped += 1
                
                logger.info(f"  Quantile mapping: applied to {parks_mapped} park forecast series")
                logger.info(f"    Forecast WTI now matches historical distribution shape per park")
            else:
                logger.info("  Quantile mapping: skipped (missing historical or forecast data)")
        except Exception as e:
            logger.warning(f"  Quantile mapping failed (non-fatal): {e}")
    
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
        
        # Dual-write to DuckDB for bot + dashboard
        db_path = output_base / "tpcr_live.duckdb"
        if db_path.exists():
            try:
                live_con = duckdb.connect(str(db_path))
                min_d = combined["park_date"].min()
                max_d = combined["park_date"].max()
                live_con.execute(
                    "DELETE FROM wti WHERE park_date >= ? AND park_date <= ?",
                    [min_d, max_d],
                )
                live_con.register("_wti_df", combined)
                live_con.execute("""
                    INSERT INTO wti (park_code, park_date, time_slot, wti, source, updated_at)
                    SELECT park_code, park_date::DATE, 'daily', wti, COALESCE(source, 'forecast'), CURRENT_TIMESTAMP
                    FROM _wti_df
                """)
                live_con.execute("""
                    INSERT OR REPLACE INTO data_freshness (source, last_updated, row_count, notes)
                    VALUES ('wti', CURRENT_TIMESTAMP, (SELECT COUNT(*) FROM wti), 'pipeline')
                """)
                live_con.close()
                logger.info(f"  Wrote {len(combined)} rows to tpcr_live.duckdb")
            except Exception as e:
                logger.warning(f"  DuckDB write failed: {e}")
        
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
