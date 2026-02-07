#!/usr/bin/env python3
"""
Vectorized Forecast Generation - FAST

Generates 2-year forecasts for all entities in minutes by:
1. Generating all time slots at once (vectorized)
2. Batch prediction with XGBoost
3. Single parquet output file

Usage:
    python scripts/forecast_vectorized.py [--workers N]
"""

import argparse
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import xgboost as xgb
except ImportError:
    xgb = None

# Constants
DEFAULT_WORKERS = 8
SLOTS_PER_DAY = 288  # 5-minute intervals
DEFAULT_FALLBACK_RATIO = 0.82

# Paths
OUTPUT_BASE = Path("/home/wilma/hazeydata/pipeline")
MODELS_DIR = OUTPUT_BASE / "models"
FORECAST_DIR = OUTPUT_BASE / "curves" / "forecast_parquet"
LOGS_DIR = OUTPUT_BASE / "logs"


def setup_logging():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"forecast_vectorized_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


def generate_time_grid(start_date: date, end_date: date) -> pd.DataFrame:
    """Generate all time slots for date range (vectorized)."""
    dates = pd.date_range(start_date, end_date, freq='D')
    times = pd.date_range('00:00', '23:55', freq='5min').time
    
    # Create grid
    rows = []
    for d in dates:
        for t in times:
            rows.append({
                'park_date': d.date(),
                'time_slot': t,
                'datetime': datetime.combine(d.date(), t),
            })
    
    df = pd.DataFrame(rows)
    
    # Add features (vectorized)
    df['hour_of_day'] = df['datetime'].dt.hour
    df['mins_since_6am'] = (df['datetime'].dt.hour - 6) * 60 + df['datetime'].dt.minute
    df['day_of_week'] = df['datetime'].dt.dayofweek
    df['month'] = df['datetime'].dt.month
    df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
    
    return df


def forecast_entity(args) -> tuple:
    """Generate forecast for single entity (worker function)."""
    entity_code, time_grid, models_dir, fallback_ratio, time_slot_lookup = args
    
    try:
        df = time_grid.copy()
        df['entity_code'] = entity_code
        
        # Check for model (Julia or Python)
        model_path = models_dir / entity_code / "model_julia.json"
        if not model_path.exists():
            model_path = models_dir / entity_code / "model.json"
        
        if model_path.exists():
            # Load model
            model = xgb.XGBRegressor()
            model.load_model(str(model_path))
            
            # Use features: mins_since_6am, hour_of_day, day_of_week, month, is_weekend
            feature_cols = ['mins_since_6am', 'hour_of_day', 'day_of_week', 'month', 'is_weekend']
            
            # Check if model was trained with posted_time
            try:
                # Try prediction with just time features
                X = df[feature_cols].values.astype(np.float32)
                predictions = model.predict(X)
            except Exception:
                # Model might expect posted_time - get time-slot specific average
                df['posted_time'] = df['time_slot'].apply(
                    lambda t: time_slot_lookup.get((entity_code, str(t)), 30.0)
                )
                feature_cols = ['posted_time', 'mins_since_6am', 'hour_of_day', 'day_of_week', 'month', 'is_weekend']
                X = df[feature_cols].values.astype(np.float32)
                predictions = model.predict(X)
            
            # Clip predictions to reasonable range
            predictions = np.clip(predictions, 0, 300)
            
            df['predicted_actual'] = predictions
            df['prediction_method'] = 'model'
        else:
            # No model - use 82% fallback rule with TIME-SLOT SPECIFIC average
            # Look up average posted for this entity + time slot
            df['avg_posted'] = df['time_slot'].apply(
                lambda t: time_slot_lookup.get((entity_code, str(t)), 30.0)
            )
            df['predicted_actual'] = df['avg_posted'] * fallback_ratio
            df['prediction_method'] = 'fallback'
        
        # Select output columns
        result = df[['entity_code', 'park_date', 'time_slot', 'predicted_actual', 'prediction_method']].copy()
        
        return entity_code, result, "OK"
    
    except Exception as e:
        return entity_code, None, str(e)[:200]


def main():
    parser = argparse.ArgumentParser(description="Vectorized forecast generation")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Parallel workers")
    parser.add_argument("--days", type=int, default=730, help="Days to forecast")
    parser.add_argument("--max-entities", type=int, help="Limit entities (testing)")
    parser.add_argument("--models-only", action="store_true", help="Only entities with models (skip fallback)")
    args = parser.parse_args()
    
    logger = setup_logging()
    
    logger.info("=" * 60)
    logger.info("VECTORIZED FORECAST GENERATION")
    logger.info("=" * 60)
    
    start_time = time.time()
    
    # Date range
    start_date = date.today() + timedelta(days=1)
    end_date = start_date + timedelta(days=args.days)
    
    logger.info(f"Date range: {start_date} to {end_date} ({args.days} days)")
    logger.info(f"Time slots per day: {SLOTS_PER_DAY}")
    logger.info(f"Workers: {args.workers}")
    
    # Generate time grid once (shared across all entities)
    logger.info("Generating time grid...")
    grid_start = time.time()
    time_grid = generate_time_grid(start_date, end_date)
    logger.info(f"  Grid: {len(time_grid):,} time slots in {time.time() - grid_start:.1f}s")
    
    # Get ALL entities from fact tables with their average posted times BY TIME SLOT
    import duckdb
    parquet_dir = OUTPUT_BASE / "fact_tables" / "parquet"
    
    logger.info("Getting all entities and time-slot averages from fact tables...")
    con = duckdb.connect()
    
    # Get entity list
    entity_list = con.execute(f"""
        SELECT DISTINCT entity_code
        FROM read_parquet('{parquet_dir}/*.parquet')
        WHERE wait_time_type = 'POSTED'
          AND wait_time_minutes > 0
    """).fetchdf()['entity_code'].tolist()
    
    # Get average posted by entity + time slot (5-min buckets)
    logger.info("  Computing average posted by entity + time slot...")
    time_slot_avgs = con.execute(f"""
        SELECT 
            entity_code,
            LPAD(CAST(EXTRACT(HOUR FROM observed_at_ts) AS VARCHAR), 2, '0') || ':' ||
            LPAD(CAST(FLOOR(EXTRACT(MINUTE FROM observed_at_ts) / 5) * 5 AS VARCHAR), 2, '0') || ':00' as time_slot,
            AVG(wait_time_minutes) as avg_posted
        FROM read_parquet('{parquet_dir}/*.parquet')
        WHERE wait_time_type = 'POSTED'
          AND wait_time_minutes > 0
        GROUP BY entity_code, time_slot
    """).fetchdf()
    con.close()
    
    # Create lookup dict: {(entity, time_slot): avg_posted}
    time_slot_lookup = {}
    for _, row in time_slot_avgs.iterrows():
        key = (row['entity_code'], row['time_slot'])
        time_slot_lookup[key] = row['avg_posted']
    
    logger.info(f"  Loaded {len(time_slot_lookup):,} entity-timeslot averages")
    
    all_entities = entity_list
    
    # Get entities with models
    entities_with_models = set()
    for d in MODELS_DIR.iterdir():
        if d.is_dir():
            if (d / "model_julia.json").exists() or (d / "model.json").exists():
                entities_with_models.add(d.name)
    
    if args.models_only:
        entities = sorted(entities_with_models)
        logger.info(f"Entities with models only: {len(entities)}")
    else:
        entities = sorted(all_entities)
        logger.info(f"Total entities: {len(entities)} ({len(entities_with_models)} with models, {len(entities) - len(entities_with_models)} fallback)")
    
    if args.max_entities:
        entities = entities[:args.max_entities]
    
    # Process entities in parallel
    logger.info("Generating forecasts...")
    
    FORECAST_DIR.mkdir(parents=True, exist_ok=True)
    
    work_items = [
        (entity, time_grid, MODELS_DIR, DEFAULT_FALLBACK_RATIO, time_slot_lookup)
        for entity in entities
    ]
    
    all_forecasts = []
    successful = 0
    failed = 0
    
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(forecast_entity, item): item[0] for item in work_items}
        
        for i, future in enumerate(as_completed(futures), 1):
            entity = futures[future]
            entity_code, result_df, msg = future.result()
            
            if result_df is not None:
                all_forecasts.append(result_df)
                successful += 1
            else:
                failed += 1
                logger.warning(f"  {entity_code}: {msg}")
            
            if i % 20 == 0 or i == len(entities):
                elapsed = time.time() - start_time
                rate = i / elapsed
                logger.info(f"  Progress: {i}/{len(entities)} ({rate:.1f} entities/sec)")
    
    # Combine and save
    logger.info("Combining forecasts...")
    if all_forecasts:
        combined = pd.concat(all_forecasts, ignore_index=True)
        
        # Save as single parquet file
        output_file = FORECAST_DIR / "all_forecasts.parquet"
        combined.to_parquet(output_file, index=False)
        
        logger.info(f"  Saved {len(combined):,} predictions to {output_file}")
        logger.info(f"  File size: {output_file.stat().st_size / 1024 / 1024:.1f} MB")
    
    elapsed = time.time() - start_time
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("FORECAST COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Total predictions: {len(combined) if all_forecasts else 0:,}")
    logger.info(f"Time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    logger.info("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
