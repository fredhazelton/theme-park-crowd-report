#!/usr/bin/env python3
"""
Hybrid Pipeline - Best of Both Worlds

Uses the fastest tool for each step:
1. Python/DuckDB → Matched pairs generation (vectorized SQL)
2. Julia/XGBoost.jl → Model training (faster than Python XGBoost)
3. Python → Scoring (loads any XGBoost format)

Usage:
    python scripts/hybrid_pipeline.py [--skip-pairs] [--skip-training] [--skip-scoring]
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import duckdb
from zoneinfo import ZoneInfo

# Constants
MATCH_WINDOW_MINUTES = 15
DEFAULT_MIN_OBS = 500
DEFAULT_FALLBACK_RATIO = 0.82
EASTERN = ZoneInfo("America/New_York")

# Paths
OUTPUT_BASE = Path("/home/wilma/hazeydata/pipeline")
PARQUET_DIR = OUTPUT_BASE / "fact_tables" / "parquet"
MATCHED_PAIRS_DIR = OUTPUT_BASE / "matched_pairs"
MODELS_DIR = OUTPUT_BASE / "models"
PREDICTIONS_DIR = OUTPUT_BASE / "predictions"
LOGS_DIR = OUTPUT_BASE / "logs"

PROJECT_ROOT = Path("/home/wilma/theme-park-crowd-report")
JULIA_TRAIN_SCRIPT = PROJECT_ROOT / "julia-ml" / "train_only.jl"
JULIA_BIN = Path.home() / "julia-1.10.2" / "bin" / "julia"


def setup_logging():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"hybrid_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
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
    """Use DuckDB to create all matched pairs (vectorized, instant)."""
    logger.info("=" * 60)
    logger.info("STEP 1: MATCHED PAIRS (Python/DuckDB)")
    logger.info("=" * 60)
    
    start = time.time()
    con = duckdb.connect()
    
    # Match ACTUAL with closest POSTED within 15-minute window
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
        )
        SELECT 
            entity_code,
            observed_at,
            observed_at_ts,
            park_date,
            actual_time,
            posted_time
        FROM best_match
        WHERE rn = 1
    """
    
    logger.info("Running DuckDB match query...")
    df = con.execute(query).fetchdf()
    logger.info(f"  Created {len(df):,} matched pairs")
    
    # Add features for training
    df["observed_at_ts"] = pd.to_datetime(df["observed_at_ts"])
    df["hour_of_day"] = df["observed_at_ts"].dt.hour
    df["mins_since_6am"] = (df["observed_at_ts"].dt.hour - 6) * 60 + df["observed_at_ts"].dt.minute
    df["day_of_week"] = df["observed_at_ts"].dt.dayofweek
    df["month"] = df["observed_at_ts"].dt.month
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    
    # Save to parquet
    output_path = MATCHED_PAIRS_DIR / "all_pairs.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    
    elapsed = time.time() - start
    logger.info(f"  Saved to: {output_path}")
    logger.info(f"  ⏱️  Matched pairs: {elapsed:.1f}s")
    
    con.close()
    return len(df)


def step2_train_julia(logger) -> tuple[int, float]:
    """Run Julia XGBoost training (faster than Python)."""
    logger.info("=" * 60)
    logger.info("STEP 2: TRAINING (Julia/XGBoost.jl)")
    logger.info("=" * 60)
    
    if not JULIA_TRAIN_SCRIPT.exists():
        logger.error(f"Julia script not found: {JULIA_TRAIN_SCRIPT}")
        return 0, 0.0
    
    start = time.time()
    
    # Run Julia training with 4 threads (with project environment)
    result = subprocess.run(
        [str(JULIA_BIN), f"--project={PROJECT_ROOT / 'julia-ml'}", "--threads=4", str(JULIA_TRAIN_SCRIPT)],
        cwd=str(PROJECT_ROOT / "julia-ml"),
        capture_output=True,
        text=True,
    )
    
    elapsed = time.time() - start
    
    if result.returncode != 0:
        logger.error(f"Julia training failed:\n{result.stderr}")
        return 0, elapsed
    
    # Parse output for stats
    output = result.stdout
    logger.info(output)
    
    # Extract successful count from output
    successful = 0
    for line in output.split("\n"):
        if "Successful:" in line:
            try:
                successful = int(line.split(":")[1].strip())
            except:
                pass
    
    logger.info(f"  ⏱️  Julia training: {elapsed:.1f}s ({successful} models)")
    return successful, elapsed


def step3_score_python(logger, hours: int = 24) -> int:
    """Score recent observations using trained models."""
    logger.info("=" * 60)
    logger.info("STEP 3: SCORING (Python)")
    logger.info("=" * 60)
    
    start = time.time()
    
    # Run the Python scoring script (use venv python)
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    result = subprocess.run(
        [str(venv_python), "scripts/score_fast.py", "--hours", str(hours)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    
    elapsed = time.time() - start
    
    if result.returncode != 0:
        logger.error(f"Scoring failed:\n{result.stderr}")
        return 0
    
    logger.info(result.stdout)
    
    # Parse scored count
    scored = 0
    for line in result.stdout.split("\n"):
        if "predictions" in line.lower() and "saved" in line.lower():
            try:
                # Extract number from line
                import re
                match = re.search(r'(\d+)', line)
                if match:
                    scored = int(match.group(1))
            except:
                pass
    
    logger.info(f"  ⏱️  Python scoring: {elapsed:.1f}s")
    return scored


def main():
    parser = argparse.ArgumentParser(description="Hybrid Pipeline - Julia training + Python ETL/scoring")
    parser.add_argument("--skip-pairs", action="store_true", help="Skip matched pairs generation")
    parser.add_argument("--skip-training", action="store_true", help="Skip Julia training")
    parser.add_argument("--skip-scoring", action="store_true", help="Skip Python scoring")
    parser.add_argument("--score-hours", type=int, default=24, help="Hours of data to score")
    args = parser.parse_args()
    
    logger = setup_logging()
    
    logger.info("=" * 60)
    logger.info("HYBRID PIPELINE - Best of Both Worlds")
    logger.info("=" * 60)
    logger.info("Python/DuckDB → Matched pairs (vectorized)")
    logger.info("Julia/XGBoost.jl → Training (fast)")
    logger.info("Python → Scoring")
    logger.info("=" * 60)
    
    total_start = time.time()
    results = {}
    
    # Step 1: Matched Pairs (Python/DuckDB)
    if not args.skip_pairs:
        results["pairs"] = step1_create_matched_pairs(logger)
    else:
        logger.info("Skipping matched pairs (--skip-pairs)")
    
    # Step 2: Training (Julia)
    if not args.skip_training:
        results["models"], results["train_time"] = step2_train_julia(logger)
    else:
        logger.info("Skipping training (--skip-training)")
    
    # Step 3: Scoring (Python)
    if not args.skip_scoring:
        results["scored"] = step3_score_python(logger, args.score_hours)
    else:
        logger.info("Skipping scoring (--skip-scoring)")
    
    total_elapsed = time.time() - total_start
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("HYBRID PIPELINE COMPLETE")
    logger.info("=" * 60)
    if "pairs" in results:
        logger.info(f"  Matched pairs: {results['pairs']:,}")
    if "models" in results:
        logger.info(f"  Models trained: {results['models']}")
    if "scored" in results:
        logger.info(f"  Predictions: {results['scored']:,}")
    logger.info(f"  ⏱️  Total time: {total_elapsed:.1f}s")
    logger.info("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
