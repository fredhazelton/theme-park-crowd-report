#!/usr/bin/env python3
"""
Fast Scoring Pipeline - Generate predictions using trained models.

Uses the pre-computed matched pairs and trained XGBoost models to score
recent POSTED wait times and generate ACTUAL predictions.
"""

import argparse
import json
import logging
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
DEFAULT_FALLBACK_RATIO = 0.82
DEFAULT_WORKERS = 5
EASTERN = ZoneInfo("America/New_York")


def setup_logging(output_base: Path):
    log_dir = output_base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / f"score_fast_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


def get_recent_posted(parquet_dir: Path, hours: int = 24) -> pd.DataFrame:
    """Get recent POSTED wait times from parquet files."""
    con = duckdb.connect()
    
    cutoff = datetime.now(ZoneInfo("UTC")) - timedelta(hours=hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    
    result = con.execute(f"""
        SELECT 
            entity_code,
            observed_at,
            observed_at_ts,
            park_date,
            wait_time_minutes as posted_time
        FROM read_parquet('{parquet_dir}/*.parquet')
        WHERE wait_time_type = 'POSTED'
          AND observed_at_ts >= '{cutoff_str}'
          AND wait_time_minutes IS NOT NULL
          AND wait_time_minutes > 0
        ORDER BY entity_code, observed_at_ts
    """).fetchdf()
    
    con.close()
    return result


def get_latest_posted_per_entity(parquet_dir: Path) -> pd.DataFrame:
    """Get the most recent POSTED wait time for each entity."""
    con = duckdb.connect()
    
    result = con.execute(f"""
        WITH ranked AS (
            SELECT 
                entity_code,
                observed_at,
                observed_at_ts,
                park_date,
                wait_time_minutes as posted_time,
                ROW_NUMBER() OVER (PARTITION BY entity_code ORDER BY observed_at_ts DESC) as rn
            FROM read_parquet('{parquet_dir}/*.parquet')
            WHERE wait_time_type = 'POSTED'
              AND wait_time_minutes IS NOT NULL
              AND wait_time_minutes > 0
        )
        SELECT entity_code, observed_at, observed_at_ts, park_date, posted_time
        FROM ranked
        WHERE rn = 1
    """).fetchdf()
    
    con.close()
    return result


def score_entity(args):
    """Score predictions for a single entity."""
    entity_code, posted_df, models_dir, fallback_ratio = args
    
    model_dir = models_dir / entity_code
    model_path = model_dir / "model.json"
    
    if not model_path.exists():
        # Use fallback ratio
        predictions = posted_df["posted_time"] * fallback_ratio
        return entity_code, predictions.tolist(), "fallback"
    
    try:
        # Load model
        model = xgb.XGBRegressor()
        model.load_model(str(model_path))
        
        # Load metadata for feature list
        with open(model_dir / "metadata.json") as f:
            metadata = json.load(f)
        
        feature_cols = metadata.get("features", ["posted_time"])
        
        # Prepare features
        df = posted_df.copy()
        df["observed_at_ts"] = pd.to_datetime(df["observed_at_ts"])
        df["hour_of_day"] = df["observed_at_ts"].dt.hour
        df["mins_since_6am"] = (df["observed_at_ts"].dt.hour - 6) * 60 + df["observed_at_ts"].dt.minute
        df["day_of_week"] = df["observed_at_ts"].dt.dayofweek
        df["month"] = df["observed_at_ts"].dt.month
        df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
        
        # Select features that exist
        available_features = [c for c in feature_cols if c in df.columns]
        X = df[available_features].fillna(-1)
        
        # Predict
        predictions = model.predict(X)
        predictions = np.clip(predictions, 0, None)  # No negative wait times
        
        return entity_code, predictions.tolist(), "model"
    
    except Exception as e:
        # Fallback on error
        predictions = posted_df["posted_time"] * fallback_ratio
        return entity_code, predictions.tolist(), f"error: {e}"


def main():
    parser = argparse.ArgumentParser(description="Fast scoring pipeline")
    parser.add_argument("--parquet-dir", default="/home/wilma/hazeydata/pipeline/fact_tables/parquet")
    parser.add_argument("--output-base", default="/home/wilma/hazeydata/pipeline")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--hours", type=int, default=24, help="Hours of recent data to score")
    parser.add_argument("--latest-only", action="store_true", help="Only score latest observation per entity")
    
    args = parser.parse_args()
    
    if xgb is None:
        print("ERROR: XGBoost not installed")
        sys.exit(1)
    
    parquet_dir = Path(args.parquet_dir)
    output_base = Path(args.output_base)
    models_dir = output_base / "models"
    predictions_dir = output_base / "predictions"
    predictions_dir.mkdir(parents=True, exist_ok=True)
    
    logger = setup_logging(output_base)
    
    logger.info("=" * 60)
    logger.info("FAST SCORING PIPELINE")
    logger.info("=" * 60)
    
    # Get recent POSTED data
    if args.latest_only:
        logger.info("Getting latest POSTED per entity...")
        posted_df = get_latest_posted_per_entity(parquet_dir)
    else:
        logger.info(f"Getting POSTED data from last {args.hours} hours...")
        posted_df = get_recent_posted(parquet_dir, args.hours)
    
    logger.info(f"  Found {len(posted_df):,} POSTED observations")
    
    if len(posted_df) == 0:
        logger.warning("No recent POSTED data found!")
        return
    
    # Group by entity
    entities = posted_df["entity_code"].unique()
    logger.info(f"  Across {len(entities)} entities")
    
    # Score in parallel
    logger.info(f"\n{'='*60}")
    logger.info(f"SCORING {len(entities)} ENTITIES")
    logger.info(f"{'='*60}")
    
    start = datetime.now()
    
    work_items = []
    for entity in entities:
        entity_df = posted_df[posted_df["entity_code"] == entity].copy()
        work_items.append((entity, entity_df, models_dir, DEFAULT_FALLBACK_RATIO))
    
    results = []
    model_count = 0
    fallback_count = 0
    
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(score_entity, item): item[0] for item in work_items}
        
        for future in as_completed(futures):
            entity = futures[future]
            entity_code, predictions, method = future.result()
            
            if method == "model":
                model_count += 1
            else:
                fallback_count += 1
            
            # Get the original data for this entity
            entity_df = posted_df[posted_df["entity_code"] == entity_code].copy()
            entity_df["predicted_actual"] = predictions
            entity_df["prediction_method"] = method
            results.append(entity_df)
    
    # Combine results
    all_predictions = pd.concat(results, ignore_index=True)
    
    elapsed = (datetime.now() - start).total_seconds()
    
    logger.info(f"\n{'='*60}")
    logger.info(f"SCORING COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"Total predictions: {len(all_predictions):,}")
    logger.info(f"Using models: {model_count}")
    logger.info(f"Using fallback: {fallback_count}")
    logger.info(f"Scoring time: {elapsed:.1f}s")
    
    # Save predictions
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Save as parquet
    parquet_path = predictions_dir / f"predictions_{timestamp}.parquet"
    all_predictions.to_parquet(parquet_path, index=False)
    logger.info(f"\nSaved predictions to: {parquet_path}")
    
    # Save latest as JSON for dashboard
    latest_predictions = all_predictions.sort_values("observed_at_ts").groupby("entity_code").last().reset_index()
    json_path = predictions_dir / "latest_predictions.json"
    
    # Convert to dashboard-friendly format
    dashboard_data = []
    for _, row in latest_predictions.iterrows():
        dashboard_data.append({
            "entity_code": row["entity_code"],
            "posted_time": int(row["posted_time"]),
            "predicted_actual": round(float(row["predicted_actual"]), 1),
            "observed_at": str(row["observed_at"]),
            "method": row["prediction_method"],
        })
    
    with open(json_path, "w") as f:
        json.dump({
            "generated_at": datetime.now(EASTERN).isoformat(),
            "predictions": dashboard_data,
        }, f, indent=2)
    
    logger.info(f"Saved latest predictions to: {json_path}")
    
    # Show sample predictions
    logger.info(f"\nSample predictions (first 10):")
    for item in dashboard_data[:10]:
        diff = item["predicted_actual"] - item["posted_time"]
        sign = "+" if diff > 0 else ""
        logger.info(f"  {item['entity_code']}: {item['posted_time']}min → {item['predicted_actual']:.0f}min ({sign}{diff:.0f}) [{item['method']}]")


if __name__ == "__main__":
    main()
