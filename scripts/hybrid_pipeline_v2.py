#!/usr/bin/env python3
"""
Hybrid Pipeline V2 - With Improved Features

Changes from V1:
- Added date_group_id, season, season_year from dimension tables
- Added geo_decay weight: 0.5^(days_since_observed / 730)
- Removed day_of_week, month, is_weekend (replaced by date_group_id)
- Predictions rounded to integers

Uses the fastest tool for each step:
1. Python/DuckDB → Matched pairs generation (vectorized SQL)
2. Julia/XGBoost.jl → Model training (faster than Python XGBoost)
3. Python → Scoring (loads any XGBoost format)
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import duckdb
from zoneinfo import ZoneInfo

# Constants
MATCH_WINDOW_MINUTES = 15
DEFAULT_MIN_OBS = 500
DEFAULT_FALLBACK_RATIO = 0.82
GEO_DECAY_HALFLIFE_DAYS = 730  # 2 years
EASTERN = ZoneInfo("America/New_York")

# Paths
OUTPUT_BASE = Path("/home/wilma/hazeydata/pipeline")
PARQUET_DIR = OUTPUT_BASE / "fact_tables" / "parquet"
DIMENSION_DIR = OUTPUT_BASE / "dimension_tables"
MATCHED_PAIRS_DIR = OUTPUT_BASE / "matched_pairs"
MODELS_DIR = OUTPUT_BASE / "models"
PREDICTIONS_DIR = OUTPUT_BASE / "predictions"
LOGS_DIR = OUTPUT_BASE / "logs"

PROJECT_ROOT = Path("/home/wilma/theme-park-crowd-report")
JULIA_TRAIN_SCRIPT = PROJECT_ROOT / "julia-ml" / "train_v2.jl"
JULIA_BIN = Path.home() / "julia-1.10.2" / "bin" / "julia"


def setup_logging():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"hybrid_pipeline_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


def step1_create_matched_pairs(logger) -> int:
    """Use DuckDB to create all matched pairs with improved features."""
    logger.info("=" * 60)
    logger.info("STEP 1: MATCHED PAIRS V2 (Python/DuckDB)")
    logger.info("=" * 60)
    
    start = time.time()
    con = duckdb.connect()
    
    # Paths for dimension tables
    dategroupid_path = DIMENSION_DIR / "dimdategroupid.csv"
    season_path = DIMENSION_DIR / "dimseason.csv"
    parkhours_path = DIMENSION_DIR / "dimparkhours.csv"
    
    if not dategroupid_path.exists():
        logger.error(f"dimdategroupid.csv not found: {dategroupid_path}")
        return 0
    if not season_path.exists():
        logger.error(f"dimseason.csv not found: {season_path}")
        return 0
    if not parkhours_path.exists():
        logger.warning(f"dimparkhours.csv not found: {parkhours_path} - mins_since_open will be NULL")
    
    # Calculate reference date for geo decay
    today = date.today()
    
    # Match ACTUAL with closest POSTED within 15-minute window
    # Join with dimension tables for date_group_id, season, season_year
    query = f"""
        WITH actual AS (
            SELECT 
                entity_code,
                observed_at,
                observed_at_ts,
                park_date,
                wait_time_minutes as actual_time
            FROM read_parquet('{PARQUET_DIR}/*.parquet')
            WHERE wait_time_type = 'ACTUAL'
              AND wait_time_minutes IS NOT NULL
              AND wait_time_minutes > 0
        ),
        posted AS (
            SELECT 
                entity_code,
                observed_at_ts,
                park_date,
                wait_time_minutes as posted_time
            FROM read_parquet('{PARQUET_DIR}/*.parquet')
            WHERE wait_time_type = 'POSTED'
              AND wait_time_minutes IS NOT NULL
              AND wait_time_minutes > 0
        ),
        dategroupid AS (
            SELECT 
                CAST(park_date AS DATE) as park_date,
                date_group_id
            FROM read_csv('{dategroupid_path}', AUTO_DETECT=TRUE)
        ),
        season AS (
            SELECT 
                CAST(park_date AS DATE) as park_date,
                season,
                season_year
            FROM read_csv('{season_path}', AUTO_DETECT=TRUE)
        ),
        parkhours AS (
            SELECT 
                park,
                CAST(date AS DATE) as park_date,
                EXTRACT(HOUR FROM CAST(opening_time AS TIMESTAMP)) as open_hour,
                EXTRACT(MINUTE FROM CAST(opening_time AS TIMESTAMP)) as open_minute
            FROM read_csv('{parkhours_path}', AUTO_DETECT=TRUE)
            WHERE opening_time IS NOT NULL
        ),
        matched AS (
            SELECT 
                a.entity_code,
                a.observed_at,
                a.observed_at_ts,
                a.park_date,
                a.actual_time,
                p.posted_time,
                ABS(EXTRACT(EPOCH FROM (a.observed_at_ts - p.observed_at_ts))) as time_diff_sec
            FROM actual a
            JOIN posted p 
              ON a.entity_code = p.entity_code 
              AND a.park_date = p.park_date
              AND ABS(EXTRACT(EPOCH FROM (a.observed_at_ts - p.observed_at_ts))) <= {MATCH_WINDOW_MINUTES * 60}
        ),
        best_match AS (
            SELECT 
                entity_code,
                observed_at,
                observed_at_ts,
                park_date,
                actual_time,
                posted_time,
                ROW_NUMBER() OVER (
                    PARTITION BY entity_code, observed_at 
                    ORDER BY time_diff_sec
                ) as rn
            FROM matched
        ),
        with_dims AS (
            SELECT 
                bm.entity_code,
                bm.observed_at,
                bm.observed_at_ts,
                bm.park_date,
                bm.actual_time,
                bm.posted_time,
                dg.date_group_id,
                s.season,
                s.season_year,
                ph.open_hour,
                ph.open_minute,
                -- Geo decay: 0.5^(days_since / 730)
                POWER(0.5, (DATE '{today}' - CAST(bm.park_date AS DATE))::DOUBLE / {GEO_DECAY_HALFLIFE_DAYS}.0) as geo_decay_weight
            FROM best_match bm
            LEFT JOIN dategroupid dg ON bm.park_date = dg.park_date
            LEFT JOIN season s ON bm.park_date = s.park_date
            LEFT JOIN parkhours ph ON UPPER(SUBSTRING(bm.entity_code, 1, 2)) = UPPER(ph.park) 
                                   AND bm.park_date = ph.park_date
            WHERE bm.rn = 1
        )
        SELECT 
            entity_code,
            observed_at,
            observed_at_ts,
            park_date,
            actual_time,
            posted_time,
            date_group_id,
            season,
            season_year,
            geo_decay_weight,
            -- Time features
            EXTRACT(HOUR FROM observed_at_ts) as hour_of_day,
            (EXTRACT(HOUR FROM observed_at_ts) - 6) * 60 + EXTRACT(MINUTE FROM observed_at_ts) as mins_since_6am,
            -- Minutes since park open (NULL if no park hours data)
            CASE 
                WHEN open_hour IS NOT NULL THEN
                    (EXTRACT(HOUR FROM observed_at_ts) - open_hour) * 60 + 
                    (EXTRACT(MINUTE FROM observed_at_ts) - open_minute)
                ELSE NULL
            END as mins_since_open
        FROM with_dims
        WHERE date_group_id IS NOT NULL
          AND season IS NOT NULL
    """
    
    logger.info("Running DuckDB match query with dimension joins...")
    df = con.execute(query).fetchdf()
    logger.info(f"  Created {len(df):,} matched pairs")
    
    # Label encode categorical features
    logger.info("  Label encoding categorical features...")
    
    # date_group_id encoding
    dg_categories = df['date_group_id'].unique()
    dg_mapping = {cat: idx for idx, cat in enumerate(sorted(dg_categories))}
    df['date_group_id_encoded'] = df['date_group_id'].map(dg_mapping)
    
    # season encoding
    season_categories = df['season'].unique()
    season_mapping = {cat: idx for idx, cat in enumerate(sorted(season_categories))}
    df['season_encoded'] = df['season'].map(season_mapping)
    
    # season_year encoding
    sy_categories = df['season_year'].unique()
    sy_mapping = {cat: idx for idx, cat in enumerate(sorted(sy_categories))}
    df['season_year_encoded'] = df['season_year'].map(sy_mapping)
    
    # Save encodings for inference
    encodings = {
        'date_group_id': dg_mapping,
        'season': season_mapping,
        'season_year': sy_mapping,
    }
    encodings_path = OUTPUT_BASE / "state" / "encoding_mappings.json"
    encodings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(encodings_path, 'w') as f:
        json.dump(encodings, f, indent=2)
    logger.info(f"  Saved encodings to: {encodings_path}")
    
    # Save to parquet
    output_path = MATCHED_PAIRS_DIR / "all_pairs_v2.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    
    elapsed = time.time() - start
    # Calculate dynamic fallback ratios per entity
    logger.info("  Computing dynamic fallback ratios...")
    ratio_df = df.groupby('entity_code').agg(
        actual_sum=('actual_time', 'sum'),
        posted_sum=('posted_time', 'sum'),
        count=('actual_time', 'count')
    ).reset_index()
    
    # Global average ratio
    global_ratio = ratio_df['actual_sum'].sum() / ratio_df['posted_sum'].sum()
    
    # Per-entity ratio (use global if < 50 samples)
    ratio_df['fallback_ratio'] = ratio_df.apply(
        lambda row: row['actual_sum'] / row['posted_sum'] if row['count'] >= 50 else global_ratio,
        axis=1
    )
    
    # Save fallback ratios
    fallback_ratios = dict(zip(ratio_df['entity_code'], ratio_df['fallback_ratio']))
    fallback_ratios['__global__'] = global_ratio
    
    ratios_path = OUTPUT_BASE / "state" / "fallback_ratios.json"
    with open(ratios_path, 'w') as f:
        json.dump(fallback_ratios, f, indent=2)
    logger.info(f"  Global fallback ratio: {global_ratio:.3f}")
    logger.info(f"  Per-entity ratios: {len([r for r in ratio_df['count'] if r >= 50])} entities with ≥50 samples")
    logger.info(f"  Saved ratios to: {ratios_path}")
    
    logger.info(f"  Saved to: {output_path}")
    logger.info(f"  Features: posted_time, mins_since_6am, mins_since_open, hour_of_day, date_group_id, season, season_year")
    logger.info(f"  Weights: geo_decay_weight (half-life={GEO_DECAY_HALFLIFE_DAYS} days)")
    logger.info(f"  ⏱️  Matched pairs: {elapsed:.1f}s")
    
    con.close()
    return len(df)


def step2_train_julia(logger) -> tuple[int, float]:
    """Run Julia XGBoost training with geo decay weights."""
    logger.info("=" * 60)
    logger.info("STEP 2: TRAINING V2 (Julia/XGBoost.jl + geo decay)")
    logger.info("=" * 60)
    
    if not JULIA_TRAIN_SCRIPT.exists():
        logger.warning(f"Julia V2 script not found: {JULIA_TRAIN_SCRIPT}")
        logger.warning("Falling back to original train_only.jl")
        fallback_script = PROJECT_ROOT / "julia-ml" / "train_only.jl"
        if not fallback_script.exists():
            logger.error("No Julia training script found")
            return 0, 0.0
        script_to_run = fallback_script
    else:
        script_to_run = JULIA_TRAIN_SCRIPT
    
    start = time.time()
    
    # Run Julia training with 4 threads
    result = subprocess.run(
        [str(JULIA_BIN), f"--project={PROJECT_ROOT / 'julia-ml'}", "--threads=4", str(script_to_run)],
        cwd=str(PROJECT_ROOT / "julia-ml"),
        capture_output=True,
        text=True,
    )
    
    elapsed = time.time() - start
    
    if result.returncode != 0:
        logger.error(f"Julia training failed:\n{result.stderr}")
        return 0, elapsed
    
    output = result.stdout
    logger.info(output)
    
    # Extract successful count
    successful = 0
    for line in output.split("\n"):
        if "Successful:" in line:
            try:
                successful = int(line.split(":")[1].strip())
            except:
                pass
    
    logger.info(f"  ⏱️  Julia training: {elapsed:.1f}s ({successful} models)")
    return successful, elapsed


def step3_score_historical(logger) -> int:
    """Score all historical POSTED observations."""
    logger.info("=" * 60)
    logger.info("STEP 3: SCORING HISTORICAL (Python)")
    logger.info("=" * 60)
    
    # Import here to avoid circular deps
    start = time.time()
    
    try:
        # Use the existing scoring script
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "score_historical.py")],
            capture_output=True,
            text=True,
        )
        
        if result.returncode != 0:
            logger.error(f"Scoring failed:\n{result.stderr}")
            return 0
        
        logger.info(result.stdout)
        
        # Count predictions
        pred_path = PREDICTIONS_DIR / "historical_predictions.parquet"
        if pred_path.exists():
            import pyarrow.parquet as pq
            n_predictions = pq.read_metadata(pred_path).num_rows
        else:
            n_predictions = 0
        
        elapsed = time.time() - start
        logger.info(f"  ⏱️  Scoring: {elapsed:.1f}s ({n_predictions:,} predictions)")
        return n_predictions
        
    except Exception as e:
        logger.error(f"Scoring error: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Hybrid Pipeline V2")
    parser.add_argument("--skip-pairs", action="store_true", help="Skip matched pairs generation")
    parser.add_argument("--skip-training", action="store_true", help="Skip model training")
    parser.add_argument("--skip-scoring", action="store_true", help="Skip historical scoring")
    args = parser.parse_args()
    
    logger = setup_logging()
    
    logger.info("=" * 60)
    logger.info("HYBRID PIPELINE V2")
    logger.info("=" * 60)
    logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Features: posted_time, mins_since_6am, hour_of_day, date_group_id, season, season_year")
    logger.info(f"Weights: geo_decay (half-life={GEO_DECAY_HALFLIFE_DAYS} days)")
    logger.info("")
    
    total_start = time.time()
    
    # Step 1: Matched pairs
    if not args.skip_pairs:
        n_pairs = step1_create_matched_pairs(logger)
    else:
        logger.info("Skipping matched pairs generation")
        n_pairs = 0
    
    # Step 2: Training
    if not args.skip_training:
        n_models, train_time = step2_train_julia(logger)
    else:
        logger.info("Skipping training")
        n_models, train_time = 0, 0.0
    
    # Step 3: Scoring
    if not args.skip_scoring:
        n_predictions = step3_score_historical(logger)
    else:
        logger.info("Skipping scoring")
        n_predictions = 0
    
    total_elapsed = time.time() - total_start
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("PIPELINE V2 COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Matched pairs: {n_pairs:,}")
    logger.info(f"Models trained: {n_models}")
    logger.info(f"Predictions: {n_predictions:,}")
    logger.info(f"Total time: {total_elapsed:.1f}s")


if __name__ == "__main__":
    main()
