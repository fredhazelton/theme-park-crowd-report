#!/usr/bin/env python3
"""
Forecast Accuracy Evaluation Module
====================================
Runs BEFORE the new forecast step in the daily pipeline.

Workflow:
1. Load the CURRENT forecast (from last run) for dates that now have actuals
2. Load fresh actuals from fact tables
3. Bucket actuals into 5-min slots to match forecast granularity
4. Join forecast vs actuals on (entity_code, park_date, time_slot)
5. Compute error metrics per entity-date and per park-date
6. Append results to accumulating accuracy tables
7. Archive the near-term forecast rows (next 7 days) for future comparison

Output files:
  - accuracy/slot_accuracy.parquet      (per entity, per 5-min slot)
  - accuracy/entity_daily_accuracy.parquet (per entity, per day - aggregated)
  - accuracy/wti_accuracy.parquet       (per park, per day - WTI level)
  - accuracy/archive/forecast_YYYY-MM-DD.parquet (archived forecasts)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta

import duckdb
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


def get_config(output_base: str) -> dict:
    """Load pipeline config."""
    config_path = os.path.join(output_base, "config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}


def ensure_dirs(output_base: str):
    """Create accuracy output directories."""
    os.makedirs(os.path.join(output_base, "accuracy"), exist_ok=True)
    os.makedirs(os.path.join(output_base, "accuracy", "archive"), exist_ok=True)


def get_evaluation_dates(output_base: str, con: duckdb.DuckDBPyConnection) -> list:
    """
    Determine which forecast dates now have actuals available.
    
    We look at the current forecast file and find dates that:
    - Were forecasted (exist in all_forecasts.parquet)
    - Now have actual observations in the fact tables
    - Haven't been evaluated yet (not in existing accuracy table)
    """
    forecast_path = os.path.join(output_base, "curves", "forecast_parquet", "all_forecasts.parquet")
    if not os.path.exists(forecast_path):
        log.warning("No forecast file found at %s", forecast_path)
        return []
    
    # Get the forecast date range (typically tomorrow through 2 years out)
    forecast_dates = con.execute(f"""
        SELECT DISTINCT park_date 
        FROM read_parquet('{forecast_path}')
        ORDER BY park_date
        LIMIT 30
    """).fetchdf()["park_date"].tolist()
    
    if not forecast_dates:
        return []
    
    # Find which of these dates now have actual data
    # We check the most recent fact table parquet files
    fact_dir = os.path.join(output_base, "fact_tables", "parquet")
    recent_parquets = sorted([
        os.path.join(fact_dir, f) 
        for f in os.listdir(fact_dir) 
        if f.endswith(".parquet") and f >= "2026-01"
    ])[-3:]  # Last 3 months of parquet files
    
    if not recent_parquets:
        log.warning("No recent fact table parquets found")
        return []
    
    parquet_glob = "', '".join(recent_parquets)
    
    # Dates with actual data
    actual_dates = con.execute(f"""
        SELECT DISTINCT park_date
        FROM read_parquet(['{parquet_glob}'])
        WHERE wait_time_type = 'ACTUAL'
        AND park_date >= '{forecast_dates[0]}'
    """).fetchdf()["park_date"].tolist()
    
    # Filter: only dates that appear in BOTH forecast and actuals
    eval_dates = sorted(set(str(d) for d in forecast_dates) & set(str(d) for d in actual_dates))
    
    # Exclude dates already evaluated
    accuracy_path = os.path.join(output_base, "accuracy", "entity_daily_accuracy.parquet")
    if os.path.exists(accuracy_path):
        already_done = con.execute(f"""
            SELECT DISTINCT target_date 
            FROM read_parquet('{accuracy_path}')
        """).fetchdf()["target_date"].astype(str).tolist()
        eval_dates = [d for d in eval_dates if d not in already_done]
    
    return eval_dates


def archive_forecast(output_base: str, con: duckdb.DuckDBPyConnection, run_date: str):
    """
    Archive the current near-term forecast (next 14 days) before it gets overwritten.
    This gives us something to compare against when those dates have actuals.
    """
    forecast_path = os.path.join(output_base, "curves", "forecast_parquet", "all_forecasts.parquet")
    archive_path = os.path.join(output_base, "accuracy", "archive", f"forecast_{run_date}.parquet")
    
    if os.path.exists(archive_path):
        log.info("Archive already exists for %s, skipping", run_date)
        return
    
    if not os.path.exists(forecast_path):
        log.warning("No forecast file to archive")
        return
    
    # Archive next 14 days of forecasts (manageable size)
    cutoff = (datetime.strptime(run_date, "%Y-%m-%d") + timedelta(days=14)).strftime("%Y-%m-%d")
    
    con.execute(f"""
        COPY (
            SELECT 
                entity_code,
                park_date,
                time_slot,
                predicted_actual,
                prediction_method,
                '{run_date}' as forecast_made_date
            FROM read_parquet('{forecast_path}')
            WHERE park_date <= '{cutoff}'
        ) TO '{archive_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    
    size_mb = os.path.getsize(archive_path) / 1024 / 1024
    log.info("Archived forecast for %s (next 14 days): %.1f MB", run_date, size_mb)


def evaluate_accuracy(
    output_base: str, 
    con: duckdb.DuckDBPyConnection, 
    eval_dates: list,
    run_date: str
):
    """
    Compare archived forecasts against actuals for the given dates.
    
    Returns:
        slot_df: per-slot accuracy (entity, date, 5-min slot)
        entity_df: per-entity-date accuracy (aggregated)
        wti_df: per-park-date WTI accuracy
    """
    if not eval_dates:
        return None, None, None
    
    # Find the archived forecast that would have predicted these dates
    archive_dir = os.path.join(output_base, "accuracy", "archive")
    archive_files = sorted([
        os.path.join(archive_dir, f)
        for f in os.listdir(archive_dir)
        if f.startswith("forecast_") and f.endswith(".parquet")
    ])
    
    if not archive_files:
        log.warning("No archived forecasts found — first run. Archiving current forecast.")
        return None, None, None
    
    # Use the most recent archive that was made BEFORE these eval dates
    # (i.e., the forecast that was predicting these dates ahead of time)
    forecast_archive = archive_files[-1]  # Most recent archive
    log.info("Using archived forecast: %s", os.path.basename(forecast_archive))
    
    # Load fact tables for eval dates
    fact_dir = os.path.join(output_base, "fact_tables", "parquet")
    recent_parquets = sorted([
        os.path.join(fact_dir, f)
        for f in os.listdir(fact_dir)
        if f.endswith(".parquet") and f >= "2026-01"
    ])[-3:]
    
    parquet_glob = "', '".join(recent_parquets)
    date_list = "', '".join(eval_dates)
    
    # === SLOT-LEVEL ACCURACY ===
    # Bucket actuals into 5-min slots and join with forecast
    slot_df = con.execute(f"""
        WITH actuals_bucketed AS (
            SELECT
                entity_code,
                park_date,
                -- Bucket observed_at_ts into 5-min slots
                TIME_BUCKET(INTERVAL '5 minutes', observed_at_ts::TIMESTAMP)::TIME as time_slot,
                AVG(wait_time_minutes) as actual_wait,
                COUNT(*) as n_obs
            FROM read_parquet(['{parquet_glob}'])
            WHERE wait_time_type = 'ACTUAL'
            AND park_date IN ('{date_list}')
            GROUP BY entity_code, park_date, time_slot
        ),
        forecasts AS (
            SELECT
                entity_code,
                park_date::VARCHAR as park_date,
                time_slot,
                predicted_actual as forecast_wait,
                prediction_method,
                forecast_made_date
            FROM read_parquet('{forecast_archive}')
            WHERE park_date::VARCHAR IN ('{date_list}')
        )
        SELECT
            f.entity_code,
            f.park_date,
            f.time_slot,
            f.forecast_wait,
            a.actual_wait,
            a.n_obs,
            f.prediction_method,
            f.forecast_made_date,
            -- Error metrics
            (f.forecast_wait - a.actual_wait) as signed_error,
            ABS(f.forecast_wait - a.actual_wait) as absolute_error,
            CASE WHEN a.actual_wait > 0 
                 THEN ABS(f.forecast_wait - a.actual_wait) / a.actual_wait * 100 
                 ELSE NULL END as pct_error,
            -- Horizon
            DATEDIFF('day', f.forecast_made_date::DATE, f.park_date::DATE) as horizon_days,
            '{run_date}' as evaluation_date
        FROM forecasts f
        INNER JOIN actuals_bucketed a
            ON f.entity_code = a.entity_code
            AND f.park_date = a.park_date
            AND f.time_slot = a.time_slot
    """).fetchdf()
    
    if slot_df.empty:
        log.warning("No matching forecast-actual pairs found for eval dates: %s", eval_dates)
        return None, None, None
    
    log.info("Slot-level matches: %d rows across %d entity-dates", 
             len(slot_df), slot_df.groupby(["entity_code", "park_date"]).ngroups)
    
    # === ENTITY-DATE LEVEL (aggregated) ===
    entity_df = con.execute("""
        SELECT
            entity_code,
            park_date,
            evaluation_date,
            forecast_made_date,
            horizon_days,
            prediction_method,
            COUNT(*) as n_slots,
            AVG(forecast_wait) as avg_forecast,
            AVG(actual_wait) as avg_actual,
            AVG(signed_error) as bias,
            AVG(absolute_error) as mae,
            SQRT(AVG(signed_error * signed_error)) as rmse,
            AVG(pct_error) as mape,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY absolute_error) as median_ae
        FROM slot_df
        GROUP BY entity_code, park_date, evaluation_date, forecast_made_date, 
                 horizon_days, prediction_method
    """).fetchdf()
    
    log.info("Entity-date accuracy: %d rows, MAE=%.1f min, bias=%.1f min, MAPE=%.1f%%",
             len(entity_df), entity_df["mae"].mean(), entity_df["bias"].mean(), 
             entity_df["mape"].mean())
    
    # === WTI LEVEL ===
    # Compare forecast WTI vs actual WTI
    wti_path = os.path.join(output_base, "wti", "wti.parquet")
    if os.path.exists(wti_path):
        wti_df = con.execute(f"""
            WITH forecast_wti AS (
                SELECT park_code, park_date::VARCHAR as park_date, wti as forecast_wti
                FROM read_parquet('{wti_path}')
                WHERE source = 'forecast' AND park_date::VARCHAR IN ('{date_list}')
            ),
            actual_wti AS (
                SELECT park_code, park_date::VARCHAR as park_date, wti as actual_wti
                FROM read_parquet('{wti_path}')
                WHERE source = 'historical' AND park_date::VARCHAR IN ('{date_list}')
            )
            SELECT
                f.park_code,
                f.park_date,
                f.forecast_wti,
                a.actual_wti,
                (f.forecast_wti - a.actual_wti) as wti_error,
                ABS(f.forecast_wti - a.actual_wti) as wti_abs_error,
                '{run_date}' as evaluation_date
            FROM forecast_wti f
            INNER JOIN actual_wti a
                ON f.park_code = a.park_code AND f.park_date = a.park_date
        """).fetchdf()
        
        if not wti_df.empty:
            log.info("WTI accuracy: %d park-dates, avg WTI error=%.1f min",
                     len(wti_df), wti_df["wti_abs_error"].mean())
        else:
            wti_df = None
    else:
        wti_df = None
    
    return slot_df, entity_df, wti_df


def save_results(output_base: str, slot_df, entity_df, wti_df):
    """Append results to accumulating accuracy tables."""
    accuracy_dir = os.path.join(output_base, "accuracy")
    
    for name, df in [("slot_accuracy", slot_df), 
                      ("entity_daily_accuracy", entity_df),
                      ("wti_accuracy", wti_df)]:
        if df is None or df.empty:
            continue
        
        path = os.path.join(accuracy_dir, f"{name}.parquet")
        
        if os.path.exists(path):
            # Append to existing
            existing = pd.read_parquet(path)
            combined = pd.concat([existing, df], ignore_index=True)
            # Deduplicate
            if name == "slot_accuracy":
                combined = combined.drop_duplicates(
                    subset=["entity_code", "park_date", "time_slot", "evaluation_date"]
                )
            elif name == "entity_daily_accuracy":
                combined = combined.drop_duplicates(
                    subset=["entity_code", "park_date", "evaluation_date"]
                )
            elif name == "wti_accuracy":
                combined = combined.drop_duplicates(
                    subset=["park_code", "park_date", "evaluation_date"]
                )
            combined.to_parquet(path, index=False)
            log.info("Updated %s: %d total rows (+%d new)", name, len(combined), len(df))
        else:
            df.to_parquet(path, index=False)
            log.info("Created %s: %d rows", name, len(df))


def generate_summary(output_base: str, con: duckdb.DuckDBPyConnection):
    """Generate a summary JSON for the dashboard API."""
    accuracy_dir = os.path.join(output_base, "accuracy")
    entity_path = os.path.join(accuracy_dir, "entity_daily_accuracy.parquet")
    
    if not os.path.exists(entity_path):
        return
    
    summary = con.execute(f"""
        SELECT
            COUNT(DISTINCT park_date) as dates_evaluated,
            COUNT(DISTINCT entity_code) as entities_evaluated,
            AVG(mae) as overall_mae,
            AVG(bias) as overall_bias,
            AVG(mape) as overall_mape,
            AVG(rmse) as overall_rmse,
            -- By horizon bucket
            AVG(CASE WHEN horizon_days <= 1 THEN mae END) as mae_1day,
            AVG(CASE WHEN horizon_days BETWEEN 2 AND 7 THEN mae END) as mae_7day,
            AVG(CASE WHEN horizon_days BETWEEN 8 AND 30 THEN mae END) as mae_30day,
            MIN(park_date) as first_eval_date,
            MAX(park_date) as last_eval_date,
            MAX(evaluation_date) as last_run
        FROM read_parquet('{entity_path}')
    """).fetchdf().to_dict(orient="records")[0]
    
    summary_path = os.path.join(accuracy_dir, "accuracy_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    
    log.info("Summary: MAE=%.1f min | bias=%.1f | MAPE=%.1f%% | %d dates evaluated",
             summary.get("overall_mae", 0) or 0,
             summary.get("overall_bias", 0) or 0,
             summary.get("overall_mape", 0) or 0,
             summary.get("dates_evaluated", 0) or 0)


def main():
    parser = argparse.ArgumentParser(description="Evaluate forecast accuracy")
    parser.add_argument("--output-base", default="/home/wilma/hazeydata/pipeline",
                        help="Pipeline output base directory")
    parser.add_argument("--run-date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="Current run date (YYYY-MM-DD)")
    args = parser.parse_args()
    
    output_base = args.output_base
    run_date = args.run_date
    
    log.info("=" * 60)
    log.info("FORECAST ACCURACY EVALUATION")
    log.info("=" * 60)
    log.info("Run date: %s | Output: %s", run_date, output_base)
    
    ensure_dirs(output_base)
    con = duckdb.connect()
    
    # Step 1: Archive current forecast before it gets overwritten
    log.info("Step 1: Archiving current forecast...")
    archive_forecast(output_base, con, run_date)
    
    # Step 2: Find dates to evaluate
    log.info("Step 2: Finding evaluation dates...")
    eval_dates = get_evaluation_dates(output_base, con)
    
    if not eval_dates:
        log.info("No new dates to evaluate (forecast starts in the future, no overlap with actuals yet)")
        log.info("This is normal for the first run — tomorrow's run will evaluate today's forecast.")
        log.info("=" * 60)
        return
    
    log.info("Evaluating %d dates: %s", len(eval_dates), eval_dates)
    
    # Step 3: Compare forecast vs actuals
    log.info("Step 3: Computing accuracy metrics...")
    slot_df, entity_df, wti_df = evaluate_accuracy(output_base, con, eval_dates, run_date)
    
    # Step 4: Save results
    log.info("Step 4: Saving results...")
    save_results(output_base, slot_df, entity_df, wti_df)
    
    # Step 5: Generate summary
    log.info("Step 5: Generating summary...")
    generate_summary(output_base, con)
    
    log.info("=" * 60)
    log.info("ACCURACY EVALUATION COMPLETE")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
