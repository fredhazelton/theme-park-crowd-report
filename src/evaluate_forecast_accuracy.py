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
    
    We look at ARCHIVED forecasts (not the current one) to find dates that:
    - Were predicted ahead of time (exist in archived forecast parquets)
    - Now have actual observations in the fact tables
    - Haven't been evaluated yet (not in existing accuracy table)
    """
    archive_dir = os.path.join(output_base, "accuracy", "archive")
    if not os.path.exists(archive_dir):
        log.warning("No archive directory found at %s", archive_dir)
        return []
    
    archive_files = sorted([
        os.path.join(archive_dir, f)
        for f in os.listdir(archive_dir)
        if f.startswith("forecast_") and f.endswith(".parquet")
    ])
    
    if not archive_files:
        log.warning("No archived forecasts found")
        return []
    
    # Get all dates that appear in ANY archived forecast
    archive_glob = "', '".join(archive_files)
    forecast_dates = con.execute(f"""
        SELECT DISTINCT park_date::VARCHAR as park_date
        FROM read_parquet(['{archive_glob}'])
        ORDER BY park_date
    """).fetchdf()["park_date"].tolist()
    
    if not forecast_dates:
        return []
    
    log.info("Archived forecasts cover %d unique dates (%s to %s)", 
             len(forecast_dates), forecast_dates[0], forecast_dates[-1])
    
    # Find which of these dates now have actual data
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
        SELECT DISTINCT park_date::VARCHAR as park_date
        FROM read_parquet(['{parquet_glob}'])
        WHERE wait_time_type = 'ACTUAL'
        AND park_date::VARCHAR >= '{forecast_dates[0]}'
    """).fetchdf()["park_date"].tolist()
    
    # Filter: only dates that appear in BOTH archived forecasts and actuals
    eval_dates = sorted(set(str(d) for d in forecast_dates) & set(str(d) for d in actual_dates))
    
    log.info("Dates with both forecast and actuals: %d", len(eval_dates))
    
    # Exclude dates already evaluated
    accuracy_path = os.path.join(output_base, "accuracy", "entity_daily_accuracy.parquet")
    if os.path.exists(accuracy_path):
        already_done = con.execute(f"""
            SELECT DISTINCT park_date::VARCHAR as park_date
            FROM read_parquet('{accuracy_path}')
        """).fetchdf()["park_date"].astype(str).tolist()
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
    
    # Also archive WTI predictions for these dates
    wti_path = os.path.join(output_base, "wti", "wti.parquet")
    wti_archive_path = os.path.join(output_base, "accuracy", "archive", f"wti_{run_date}.parquet")
    if os.path.exists(wti_path) and not os.path.exists(wti_archive_path):
        try:
            con.execute(f"""
                COPY (
                    SELECT park_code, park_date, wti, source,
                           '{run_date}' as wti_made_date
                    FROM read_parquet('{wti_path}')
                    WHERE source = 'forecast'
                    AND park_date <= '{cutoff}'
                ) TO '{wti_archive_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """)
            log.info("Archived WTI forecast for %s", run_date)
        except Exception as e:
            log.warning("Failed to archive WTI: %s", e)


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
    slot_df = None
    entity_df = None
    
    if eval_dates:
        # === SLOT-LEVEL AND ENTITY-LEVEL ACCURACY ===
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
        
        # Use the most recent archive that was made BEFORE the earliest eval date
        # (i.e., the forecast that was predicting these dates ahead of time)
        earliest_eval = min(eval_dates)
        valid_archives = [
            f for f in archive_files 
            if os.path.basename(f).replace("forecast_", "").replace(".parquet", "") < earliest_eval
        ]
        forecast_archive = valid_archives[-1] if valid_archives else archive_files[0]
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
        synth_dir = os.path.join(output_base, "synthetic_actuals")
        synth_glob = synth_dir.replace("\\", "/") + "/*.parquet"

        # actuals_raw: raw ACTUAL from fact tables
        # actuals_synth: synthetic actuals (POSTED→converted) — increases coverage
        # actuals_bucketed: prefer raw when available, else synthetic
        actuals_cte = f"""
            WITH actuals_raw AS (
                SELECT
                    entity_code,
                    park_date::VARCHAR as park_date,
                    TIME_BUCKET(INTERVAL '5 minutes',
                        (observed_at_ts::TIMESTAMP + INTERVAL '2 minutes 30 seconds'))::TIME as time_slot,
                    AVG(wait_time_minutes) as actual_wait,
                    COUNT(*) as n_obs
                FROM read_parquet(['{parquet_glob}'])
                WHERE wait_time_type = 'ACTUAL'
                AND park_date::VARCHAR IN ('{date_list}')
                GROUP BY entity_code, park_date, time_slot
            )"""
        synth_parquets = [f for f in (os.listdir(synth_dir) or []) if f.endswith(".parquet")] if os.path.exists(synth_dir) else []
        if synth_parquets:
            # Include synthetic actuals for slots without raw — dramatically increases coverage
            actuals_cte += f""",
            actuals_synth AS (
                SELECT
                    entity_code,
                    park_date::VARCHAR as park_date,
                    TIME_BUCKET(INTERVAL '5 minutes',
                        (CAST(observed_at AS TIMESTAMP) + INTERVAL '2 minutes 30 seconds'))::TIME as time_slot,
                    AVG(synthetic_actual) as actual_wait,
                    COUNT(*) as n_obs
                FROM read_parquet('{synth_glob}')
                WHERE park_date::VARCHAR IN ('{date_list}')
                AND synthetic_actual > 0
                GROUP BY entity_code, park_date, time_slot
            ),
            actuals_bucketed AS (
                SELECT
                    COALESCE(r.entity_code, s.entity_code) as entity_code,
                    COALESCE(r.park_date, s.park_date) as park_date,
                    COALESCE(r.time_slot, s.time_slot) as time_slot,
                    COALESCE(r.actual_wait, s.actual_wait) as actual_wait,
                    COALESCE(r.n_obs, 0) + COALESCE(s.n_obs, 0) as n_obs
                FROM actuals_raw r
                FULL OUTER JOIN actuals_synth s
                    ON r.entity_code = s.entity_code
                    AND r.park_date = s.park_date
                    AND r.time_slot = s.time_slot
            )"""
        else:
            actuals_cte += """,
            actuals_bucketed AS (
                SELECT entity_code, park_date, time_slot, actual_wait, n_obs FROM actuals_raw
            )"""

        # === SLOT-LEVEL ACCURACY ===
        slot_df = con.execute(f"""
            {actuals_cte},
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
            slot_df = None
        else:
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
    else:
        log.info("No new slot-level dates — skipping to WTI evaluation")
    
    # === WTI LEVEL ===
    # Compare ARCHIVED forecast WTI vs current historical WTI
    # The archived WTI contains what we predicted; historical WTI is computed from actuals
    #
    # NOTE: WTI eval tracks its own "already done" dates independently from slot-level eval.
    # This allows backfilling WTI accuracy for dates that were evaluated at slot level
    # but where WTI eval failed (e.g., no wti archive existed at that time).
    wti_path = os.path.join(output_base, "wti", "wti.parquet")
    wti_archive_dir = os.path.join(output_base, "accuracy", "archive")
    wti_archives = sorted([
        os.path.join(wti_archive_dir, f)
        for f in os.listdir(wti_archive_dir)
        if f.startswith("wti_") and f.endswith(".parquet")
    ]) if os.path.exists(wti_archive_dir) else []
    
    wti_df = None
    if wti_archives and os.path.exists(wti_path):
        # Build the full set of dates that need WTI evaluation:
        # 1. Current eval_dates (from slot-level eval)
        # 2. PLUS any dates that have entity accuracy but are missing WTI accuracy (backfill)
        wti_eval_dates = set(eval_dates)
        
        wti_accuracy_path = os.path.join(output_base, "accuracy", "wti_accuracy.parquet")
        entity_accuracy_path = os.path.join(output_base, "accuracy", "entity_daily_accuracy.parquet")
        if os.path.exists(entity_accuracy_path):
            try:
                all_entity_dates = set(
                    con.execute(f"""
                        SELECT DISTINCT park_date::DATE::VARCHAR as park_date
                        FROM read_parquet('{entity_accuracy_path}')
                    """).fetchdf()["park_date"].astype(str).tolist()
                )
                wti_done_dates = set()
                if os.path.exists(wti_accuracy_path):
                    wti_done_dates = set(
                        con.execute(f"""
                            SELECT DISTINCT park_date::DATE::VARCHAR as park_date
                            FROM read_parquet('{wti_accuracy_path}')
                        """).fetchdf()["park_date"].astype(str).tolist()
                    )
                wti_backfill_dates = all_entity_dates - wti_done_dates
                if wti_backfill_dates:
                    log.info("WTI backfill: %d dates have entity accuracy but missing WTI accuracy",
                             len(wti_backfill_dates))
                    wti_eval_dates = wti_eval_dates | wti_backfill_dates
            except Exception as e:
                log.warning("Failed to compute WTI backfill dates: %s", e)
        
        if not wti_eval_dates:
            log.info("No dates need WTI evaluation")
        else:
            wti_date_list = sorted(wti_eval_dates)
            log.info("WTI evaluation for %d dates: %s to %s", 
                     len(wti_date_list), wti_date_list[0], wti_date_list[-1])
            
            # For each eval date, find the best (most recent) archived WTI made before that date
            # and collect all forecast-vs-actual pairs
            all_wti_pairs = []
            for eval_d in wti_date_list:
                valid_wti_archives = [
                    f for f in wti_archives
                    if os.path.basename(f).replace("wti_", "").replace(".parquet", "") < eval_d
                ]
                if not valid_wti_archives:
                    continue
                best_archive = valid_wti_archives[-1]
                try:
                    pair_df = con.execute(f"""
                        WITH forecast_wti AS (
                            SELECT park_code, park_date::DATE::VARCHAR as park_date, wti as forecast_wti,
                                   wti_made_date
                            FROM read_parquet('{best_archive}')
                            WHERE park_date::DATE::VARCHAR = '{eval_d}'
                        ),
                        actual_wti AS (
                            SELECT park_code, park_date::DATE::VARCHAR as park_date, wti as actual_wti
                            FROM read_parquet('{wti_path}')
                            WHERE source = 'historical' AND park_date::DATE::VARCHAR = '{eval_d}'
                        )
                        SELECT
                            f.park_code,
                            f.park_date,
                            f.forecast_wti,
                            a.actual_wti,
                            f.wti_made_date,
                            (f.forecast_wti - a.actual_wti) as wti_error,
                            ABS(f.forecast_wti - a.actual_wti) as wti_abs_error,
                            '{run_date}' as evaluation_date
                        FROM forecast_wti f
                        INNER JOIN actual_wti a
                            ON f.park_code = a.park_code AND f.park_date = a.park_date
                    """).fetchdf()
                    if not pair_df.empty:
                        all_wti_pairs.append(pair_df)
                except Exception as e:
                    log.warning("WTI accuracy failed for date %s: %s", eval_d, e)
            
            if all_wti_pairs:
                wti_df = pd.concat(all_wti_pairs, ignore_index=True)
                log.info("WTI accuracy: %d park-dates across %d eval dates, avg WTI abs error=%.1f",
                         len(wti_df), wti_df["park_date"].nunique(), wti_df["wti_abs_error"].mean())
            else:
                log.info("No WTI forecast-vs-actual matches found for any eval dates")
                wti_df = None
    else:
        if not wti_archives:
            log.info("No archived WTI files yet — WTI accuracy will start tomorrow")
    
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
    
    # Add WTI-level accuracy if available
    wti_path = os.path.join(accuracy_dir, "wti_accuracy.parquet")
    if os.path.exists(wti_path):
        try:
            wti_summary = con.execute(f"""
                SELECT
                    COUNT(*) as wti_park_dates_evaluated,
                    COUNT(DISTINCT park_date) as wti_dates_evaluated,
                    AVG(wti_abs_error) as wti_mae,
                    AVG(wti_error) as wti_bias,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY wti_abs_error) as wti_median_ae,
                    MIN(park_date) as wti_first_eval_date,
                    MAX(park_date) as wti_last_eval_date
                FROM read_parquet('{wti_path}')
            """).fetchdf().to_dict(orient="records")[0]
            summary.update(wti_summary)
            log.info("WTI Summary: MAE=%.1f | bias=%.1f | median=%.1f | %d park-dates",
                     wti_summary.get("wti_mae", 0) or 0,
                     wti_summary.get("wti_bias", 0) or 0,
                     wti_summary.get("wti_median_ae", 0) or 0,
                     wti_summary.get("wti_park_dates_evaluated", 0) or 0)
        except Exception as e:
            log.warning("Failed to add WTI summary: %s", e)
    
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
    
    # Check if WTI backfill is needed even if no new slot-level dates
    wti_backfill_needed = False
    if not eval_dates:
        wti_accuracy_path = os.path.join(output_base, "accuracy", "wti_accuracy.parquet")
        entity_accuracy_path = os.path.join(output_base, "accuracy", "entity_daily_accuracy.parquet")
        if os.path.exists(entity_accuracy_path):
            try:
                all_entity_dates = set(
                    con.execute(f"""
                        SELECT DISTINCT park_date::DATE::VARCHAR as park_date
                        FROM read_parquet('{entity_accuracy_path}')
                    """).fetchdf()["park_date"].astype(str).tolist()
                )
                wti_done_dates = set()
                if os.path.exists(wti_accuracy_path):
                    wti_done_dates = set(
                        con.execute(f"""
                            SELECT DISTINCT park_date::DATE::VARCHAR as park_date
                            FROM read_parquet('{wti_accuracy_path}')
                        """).fetchdf()["park_date"].astype(str).tolist()
                    )
                wti_backfill_needed = bool(all_entity_dates - wti_done_dates)
                if wti_backfill_needed:
                    log.info("No new slot-level dates, but %d dates need WTI backfill",
                             len(all_entity_dates - wti_done_dates))
            except Exception:
                pass
    
    if not eval_dates and not wti_backfill_needed:
        log.info("No new dates to evaluate (forecast starts in the future, no overlap with actuals yet)")
        log.info("This is normal for the first run — tomorrow's run will evaluate today's forecast.")
        log.info("=" * 60)
        return
    
    if eval_dates:
        log.info("Evaluating %d dates: %s", len(eval_dates), eval_dates)
    
    # Step 3: Compare forecast vs actuals (also handles WTI backfill internally)
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
