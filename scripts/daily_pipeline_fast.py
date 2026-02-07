#!/usr/bin/env python3
"""
Daily Pipeline (Fast) - Morning refresh of ETL, training, and scoring.

Runs daily via cron to:
1. Sync new data from S3 → local CSVs → Parquet
2. Retrain models that have new data since last training
3. Score new observations since last scoring
4. Update forward-facing forecasts

Usage:
    python scripts/daily_pipeline_fast.py [--skip-etl] [--skip-training] [--force-retrain]
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd
import duckdb
from zoneinfo import ZoneInfo

try:
    import xgboost as xgb
except ImportError:
    xgb = None

# Constants
DEFAULT_WORKERS = 5
DEFAULT_FALLBACK_RATIO = 0.82
DEFAULT_MIN_OBS = 500
EASTERN = ZoneInfo("America/New_York")

# Paths
OUTPUT_BASE = Path("/home/wilma/hazeydata/pipeline")
PARQUET_DIR = OUTPUT_BASE / "fact_tables" / "parquet"
MODELS_DIR = OUTPUT_BASE / "models"
PREDICTIONS_DIR = OUTPUT_BASE / "predictions"
LOGS_DIR = OUTPUT_BASE / "logs"
STATE_FILE = OUTPUT_BASE / "pipeline_state.json"


def setup_logging():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"daily_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


def load_state() -> dict:
    """Load pipeline state (last run times, etc.)."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    """Save pipeline state."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def run_etl_sync(logger) -> bool:
    """Sync new data from S3 and convert to parquet."""
    logger.info("=" * 60)
    logger.info("STEP 1: ETL SYNC")
    logger.info("=" * 60)
    
    # Run S3 sync
    logger.info("Syncing from S3...")
    result = subprocess.run(
        ["python", "scripts/sync_s3_to_local.py"],
        cwd="/home/wilma/theme-park-crowd-report",
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        logger.error(f"S3 sync failed: {result.stderr}")
        return False
    
    logger.info("S3 sync complete")
    
    # Convert any new CSVs to parquet
    logger.info("Converting new CSVs to parquet...")
    result = subprocess.run(
        ["python", "scripts/convert_to_parquet.py", "--workers", "5"],
        cwd="/home/wilma/theme-park-crowd-report",
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        logger.warning(f"Parquet conversion warning: {result.stderr}")
    
    logger.info("ETL sync complete")
    return True


def get_entities_needing_retrain(logger, state: dict) -> list:
    """Find entities with new data since last training."""
    last_train = state.get("last_training")
    
    if not last_train:
        # First run - get all entities with enough data
        logger.info("First run - checking all entities")
        con = duckdb.connect()
        result = con.execute(f"""
            SELECT entity_code, COUNT(*) as cnt
            FROM read_parquet('{PARQUET_DIR}/*.parquet')
            WHERE wait_time_type = 'ACTUAL'
            GROUP BY entity_code
            HAVING cnt >= {DEFAULT_MIN_OBS}
        """).fetchdf()
        con.close()
        return result["entity_code"].tolist()
    
    # Find entities with new ACTUAL data since last training
    last_train_ts = datetime.fromisoformat(last_train)
    
    con = duckdb.connect()
    result = con.execute(f"""
        SELECT DISTINCT entity_code
        FROM read_parquet('{PARQUET_DIR}/*.parquet')
        WHERE wait_time_type = 'ACTUAL'
          AND observed_at_ts > '{last_train_ts.isoformat()}'
    """).fetchdf()
    con.close()
    
    return result["entity_code"].tolist()


def train_entity(args):
    """Train a single entity model."""
    entity_code, parquet_dir, models_dir, min_samples = args
    
    try:
        con = duckdb.connect()
        
        # Get matched pairs for this entity
        query = f"""
            WITH actual AS (
                SELECT entity_code, observed_at, observed_at_ts, park_date,
                       wait_time_minutes as actual_time
                FROM read_parquet('{parquet_dir}/*.parquet')
                WHERE entity_code = '{entity_code}'
                  AND wait_time_type = 'ACTUAL'
                  AND wait_time_minutes > 0
            ),
            posted AS (
                SELECT entity_code, observed_at_ts, park_date,
                       wait_time_minutes as posted_time
                FROM read_parquet('{parquet_dir}/*.parquet')
                WHERE entity_code = '{entity_code}'
                  AND wait_time_type = 'POSTED'
                  AND wait_time_minutes > 0
            ),
            matched AS (
                SELECT a.entity_code, a.observed_at, a.observed_at_ts, a.park_date,
                       a.actual_time, p.posted_time,
                       ABS(EXTRACT(EPOCH FROM (a.observed_at_ts - p.observed_at_ts))) as diff
                FROM actual a
                JOIN posted p ON a.entity_code = p.entity_code 
                  AND a.park_date = p.park_date
                  AND ABS(EXTRACT(EPOCH FROM (a.observed_at_ts - p.observed_at_ts))) <= 900
            ),
            best AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY entity_code, observed_at ORDER BY diff) as rn
                FROM matched
            )
            SELECT entity_code, observed_at, observed_at_ts, park_date, actual_time, posted_time
            FROM best WHERE rn = 1
        """
        
        df = con.execute(query).fetchdf()
        con.close()
        
        if len(df) < min_samples:
            return entity_code, None, f"Not enough samples ({len(df)})"
        
        # Add features
        df["observed_at_ts"] = pd.to_datetime(df["observed_at_ts"])
        df["hour_of_day"] = df["observed_at_ts"].dt.hour
        df["mins_since_6am"] = (df["observed_at_ts"].dt.hour - 6) * 60 + df["observed_at_ts"].dt.minute
        df["day_of_week"] = df["observed_at_ts"].dt.dayofweek
        df["month"] = df["observed_at_ts"].dt.month
        df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
        
        feature_cols = ["posted_time", "mins_since_6am", "hour_of_day", "day_of_week", "month", "is_weekend"]
        X = df[feature_cols].fillna(-1)
        y = df["actual_time"]
        
        # Train/val split
        n = len(X)
        train_end = int(n * 0.85)
        X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
        X_val, y_val = X.iloc[train_end:], y.iloc[train_end:]
        
        # Train
        model = xgb.XGBRegressor(
            n_estimators=500, max_depth=6, learning_rate=0.1,
            early_stopping_rounds=20, random_state=42,
        )
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        
        # Evaluate
        y_pred = model.predict(X_val)
        mae = np.mean(np.abs(y_val - y_pred))
        
        # Save
        model_dir = models_dir / entity_code
        model_dir.mkdir(parents=True, exist_ok=True)
        model.save_model(str(model_dir / "model.json"))
        
        metadata = {
            "entity_code": entity_code,
            "trained_at": datetime.now(ZoneInfo("UTC")).isoformat(),
            "n_samples": len(X_train),
            "mae": float(mae),
            "features": feature_cols,
        }
        with open(model_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)
        
        return entity_code, len(X_train), mae
    
    except Exception as e:
        return entity_code, None, str(e)


def run_training(logger, entities: list) -> int:
    """Train models for specified entities."""
    logger.info("=" * 60)
    logger.info(f"STEP 2: TRAINING ({len(entities)} entities)")
    logger.info("=" * 60)
    
    if not entities:
        logger.info("No entities need retraining")
        return 0
    
    work_items = [(e, PARQUET_DIR, MODELS_DIR, 100) for e in entities]
    
    successful = 0
    with ProcessPoolExecutor(max_workers=DEFAULT_WORKERS) as executor:
        futures = {executor.submit(train_entity, item): item[0] for item in work_items}
        
        for future in as_completed(futures):
            entity = futures[future]
            result = future.result()
            if result[1] is not None:
                successful += 1
                if successful % 20 == 0:
                    logger.info(f"  Trained {successful}/{len(entities)}...")
    
    logger.info(f"Training complete: {successful}/{len(entities)} successful")
    return successful


def run_scoring(logger, state: dict) -> int:
    """Score new observations since last scoring."""
    logger.info("=" * 60)
    logger.info("STEP 3: SCORING NEW OBSERVATIONS")
    logger.info("=" * 60)
    
    last_score = state.get("last_scoring")
    
    con = duckdb.connect()
    
    # Get new POSTED observations since last scoring
    if last_score:
        last_score_ts = datetime.fromisoformat(last_score)
        where_clause = f"observed_at_ts > '{last_score_ts.isoformat()}'"
        logger.info(f"Scoring observations since {last_score_ts}")
    else:
        # Score last 7 days if first run
        cutoff = datetime.now(ZoneInfo("UTC")) - timedelta(days=7)
        where_clause = f"observed_at_ts > '{cutoff.isoformat()}'"
        logger.info("First run - scoring last 7 days")
    
    # Load new POSTED data
    df = con.execute(f"""
        SELECT entity_code, observed_at, observed_at_ts, park_date,
               wait_time_minutes as posted_time
        FROM read_parquet('{PARQUET_DIR}/*.parquet')
        WHERE wait_time_type = 'POSTED'
          AND wait_time_minutes > 0
          AND {where_clause}
    """).fetchdf()
    con.close()
    
    if len(df) == 0:
        logger.info("No new observations to score")
        return 0
    
    logger.info(f"Found {len(df):,} new observations to score")
    
    # Add features
    df["observed_at_ts"] = pd.to_datetime(df["observed_at_ts"])
    df["hour_of_day"] = df["observed_at_ts"].dt.hour
    df["mins_since_6am"] = (df["observed_at_ts"].dt.hour - 6) * 60 + df["observed_at_ts"].dt.minute
    df["day_of_week"] = df["observed_at_ts"].dt.dayofweek
    df["month"] = df["observed_at_ts"].dt.month
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    
    # Score each entity
    results = []
    for entity in df["entity_code"].unique():
        entity_df = df[df["entity_code"] == entity].copy()
        model_path = MODELS_DIR / entity / "model.json"
        
        if model_path.exists():
            try:
                model = xgb.XGBRegressor()
                model.load_model(str(model_path))
                
                with open(MODELS_DIR / entity / "metadata.json") as f:
                    metadata = json.load(f)
                
                feature_cols = metadata.get("features", ["posted_time"])
                available = [c for c in feature_cols if c in entity_df.columns]
                X = entity_df[available].fillna(-1)
                
                entity_df["predicted_actual"] = np.clip(model.predict(X), 0, None)
                entity_df["prediction_method"] = "model"
            except Exception:
                entity_df["predicted_actual"] = entity_df["posted_time"] * DEFAULT_FALLBACK_RATIO
                entity_df["prediction_method"] = "fallback"
        else:
            entity_df["predicted_actual"] = entity_df["posted_time"] * DEFAULT_FALLBACK_RATIO
            entity_df["prediction_method"] = "fallback"
        
        results.append(entity_df)
    
    # Combine and save
    new_predictions = pd.concat(results, ignore_index=True)
    
    # Append to historical predictions
    hist_path = PREDICTIONS_DIR / "historical_predictions.parquet"
    if hist_path.exists():
        # Load existing and append
        existing = pd.read_parquet(hist_path)
        combined = pd.concat([existing, new_predictions], ignore_index=True)
        combined.to_parquet(hist_path, index=False)
        logger.info(f"Appended {len(new_predictions):,} predictions to historical file")
    else:
        new_predictions.to_parquet(hist_path, index=False)
        logger.info(f"Created historical file with {len(new_predictions):,} predictions")
    
    return len(new_predictions)


def main():
    parser = argparse.ArgumentParser(description="Daily pipeline")
    parser.add_argument("--skip-etl", action="store_true", help="Skip ETL sync")
    parser.add_argument("--skip-training", action="store_true", help="Skip training")
    parser.add_argument("--force-retrain", action="store_true", help="Retrain all models")
    
    args = parser.parse_args()
    
    if xgb is None:
        print("ERROR: XGBoost not installed")
        sys.exit(1)
    
    logger = setup_logging()
    state = load_state()
    
    logger.info("=" * 60)
    logger.info("DAILY PIPELINE (FAST)")
    logger.info(f"Started at: {datetime.now(EASTERN).isoformat()}")
    logger.info("=" * 60)
    
    start = datetime.now()
    
    # Step 1: ETL
    if not args.skip_etl:
        run_etl_sync(logger)
    else:
        logger.info("Skipping ETL sync")
    
    # Step 2: Training
    if not args.skip_training:
        if args.force_retrain:
            # Get all entities with enough data
            con = duckdb.connect()
            entities = con.execute(f"""
                SELECT entity_code FROM (
                    SELECT entity_code, COUNT(*) as cnt
                    FROM read_parquet('{PARQUET_DIR}/*.parquet')
                    WHERE wait_time_type = 'ACTUAL'
                    GROUP BY entity_code
                ) WHERE cnt >= {DEFAULT_MIN_OBS}
            """).fetchdf()["entity_code"].tolist()
            con.close()
        else:
            entities = get_entities_needing_retrain(logger, state)
        
        if entities:
            run_training(logger, entities)
            state["last_training"] = datetime.now(ZoneInfo("UTC")).isoformat()
    else:
        logger.info("Skipping training")
    
    # Step 3: Scoring
    scored = run_scoring(logger, state)
    state["last_scoring"] = datetime.now(ZoneInfo("UTC")).isoformat()
    
    # Save state
    save_state(state)
    
    elapsed = (datetime.now() - start).total_seconds()
    
    logger.info("=" * 60)
    logger.info("DAILY PIPELINE COMPLETE")
    logger.info(f"Total time: {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
