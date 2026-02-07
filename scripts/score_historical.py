#!/usr/bin/env python3
"""
Score Historical Data - Generate predictions for all historical POSTED times.

This creates a complete dataset of predicted ACTUAL wait times that can be
used to visualize daily wait time curves.
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
    
    log_file = log_dir / f"score_historical_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


def load_model_and_metadata(models_dir: Path, entity_code: str):
    """Load model and its metadata."""
    model_dir = models_dir / entity_code
    model_path = model_dir / "model.json"
    
    if not model_path.exists():
        return None, None
    
    model = xgb.XGBRegressor()
    model.load_model(str(model_path))
    
    with open(model_dir / "metadata.json") as f:
        metadata = json.load(f)
    
    return model, metadata


def score_entity_historical(args):
    """Score all historical data for a single entity."""
    entity_code, parquet_dir, models_dir, fallback_ratio = args
    
    try:
        # Load all POSTED data for this entity
        con = duckdb.connect()
        df = con.execute(f"""
            SELECT 
                entity_code,
                observed_at,
                observed_at_ts,
                park_date,
                wait_time_minutes as posted_time
            FROM read_parquet('{parquet_dir}/*.parquet')
            WHERE entity_code = '{entity_code}'
              AND wait_time_type = 'POSTED'
              AND wait_time_minutes IS NOT NULL
              AND wait_time_minutes > 0
            ORDER BY observed_at_ts
        """).fetchdf()
        con.close()
        
        if len(df) == 0:
            return entity_code, None, "no data"
        
        # Load model
        model, metadata = load_model_and_metadata(models_dir, entity_code)
        
        if model is None:
            # Use fallback
            df["predicted_actual"] = df["posted_time"] * fallback_ratio
            df["prediction_method"] = "fallback"
            return entity_code, df, "fallback"
        
        # Prepare features
        df["observed_at_ts"] = pd.to_datetime(df["observed_at_ts"])
        df["hour_of_day"] = df["observed_at_ts"].dt.hour
        df["mins_since_6am"] = (df["observed_at_ts"].dt.hour - 6) * 60 + df["observed_at_ts"].dt.minute
        df["day_of_week"] = df["observed_at_ts"].dt.dayofweek
        df["month"] = df["observed_at_ts"].dt.month
        df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
        
        feature_cols = metadata.get("features", ["posted_time"])
        available_features = [c for c in feature_cols if c in df.columns]
        X = df[available_features].fillna(-1)
        
        # Predict
        predictions = model.predict(X)
        predictions = np.clip(predictions, 0, None)
        
        df["predicted_actual"] = predictions
        df["prediction_method"] = "model"
        
        return entity_code, df, "model"
    
    except Exception as e:
        return entity_code, None, f"error: {e}"


def main():
    parser = argparse.ArgumentParser(description="Score historical data")
    parser.add_argument("--parquet-dir", default="/home/wilma/hazeydata/pipeline/fact_tables/parquet")
    parser.add_argument("--output-base", default="/home/wilma/hazeydata/pipeline")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--days", type=int, default=None, help="Only score last N days")
    
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
    logger.info("HISTORICAL SCORING PIPELINE")
    logger.info("=" * 60)
    
    # Get list of entities
    con = duckdb.connect()
    entities = con.execute(f"""
        SELECT DISTINCT entity_code
        FROM read_parquet('{parquet_dir}/*.parquet')
        WHERE wait_time_type = 'POSTED'
        ORDER BY entity_code
    """).fetchdf()["entity_code"].tolist()
    con.close()
    
    logger.info(f"Found {len(entities)} entities to score")
    
    # Score in parallel
    start = datetime.now()
    
    work_items = [
        (entity, parquet_dir, models_dir, DEFAULT_FALLBACK_RATIO)
        for entity in entities
    ]
    
    all_results = []
    model_count = 0
    fallback_count = 0
    error_count = 0
    
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(score_entity_historical, item): item[0] for item in work_items}
        
        completed = 0
        for future in as_completed(futures):
            entity = futures[future]
            entity_code, df, method = future.result()
            
            completed += 1
            if completed % 100 == 0:
                logger.info(f"  Scored {completed}/{len(entities)} entities...")
            
            if df is not None:
                all_results.append(df)
                if method == "model":
                    model_count += 1
                else:
                    fallback_count += 1
            else:
                error_count += 1
    
    # Combine all results
    if all_results:
        combined = pd.concat(all_results, ignore_index=True)
        
        elapsed = (datetime.now() - start).total_seconds()
        
        logger.info(f"\n{'='*60}")
        logger.info(f"SCORING COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"Total predictions: {len(combined):,}")
        logger.info(f"Using models: {model_count}")
        logger.info(f"Using fallback: {fallback_count}")
        logger.info(f"Errors: {error_count}")
        logger.info(f"Scoring time: {elapsed:.1f}s")
        
        # Save to parquet
        output_path = predictions_dir / "historical_predictions.parquet"
        combined.to_parquet(output_path, index=False)
        logger.info(f"\nSaved to: {output_path}")
        logger.info(f"File size: {output_path.stat().st_size / 1e6:.1f} MB")
        
        # Show date range
        combined["observed_at_ts"] = pd.to_datetime(combined["observed_at_ts"])
        min_date = combined["observed_at_ts"].min()
        max_date = combined["observed_at_ts"].max()
        logger.info(f"Date range: {min_date.date()} to {max_date.date()}")
    else:
        logger.error("No results to save!")


if __name__ == "__main__":
    main()
