#!/usr/bin/env python3
"""
FAST Training Pipeline - Parquet + DuckDB + Parallel

Uses:
1. Parquet files for 10-50x faster reads
2. DuckDB for instant aggregations
3. Pre-computed matched pairs (saved to disk)
4. Parallel training across entities
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

import numpy as np
import pandas as pd
import duckdb
from zoneinfo import ZoneInfo

# Add src to path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import xgboost as xgb
except ImportError:
    xgb = None

# Constants
MATCH_WINDOW_MINUTES = 15
DEFAULT_MIN_OBS = 500
DEFAULT_FALLBACK_RATIO = 0.82
DEFAULT_WORKERS = 8

PREDICTOR_COLUMNS = [
    "mins_since_6am",
    "hour_of_day",
    "day_of_week",
    "month",
    "is_weekend",
]


def setup_logging(output_base: Path):
    log_dir = output_base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / f"train_fast_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


def get_entity_counts_duckdb(parquet_dir: Path, logger) -> dict:
    """Use DuckDB to instantly count ACTUAL observations per entity."""
    logger.info("Counting ACTUAL observations with DuckDB (fast!)...")
    
    con = duckdb.connect()
    
    result = con.execute(f"""
        SELECT 
            entity_code,
            COUNT(*) as actual_count
        FROM read_parquet('{parquet_dir}/*.parquet')
        WHERE wait_time_type = 'ACTUAL'
        GROUP BY entity_code
        ORDER BY actual_count DESC
    """).fetchdf()
    
    counts = dict(zip(result["entity_code"], result["actual_count"]))
    logger.info(f"  Found {len(counts)} entities with ACTUAL data")
    
    con.close()
    return counts


def create_all_matched_pairs_duckdb(parquet_dir: Path, output_path: Path, logger) -> int:
    """Use DuckDB to create all matched pairs at once (vectorized, fast!)."""
    logger.info("Creating matched pairs with DuckDB (vectorized, fast!)...")
    
    con = duckdb.connect()
    
    # This query matches ACTUAL with closest POSTED within 15-minute window
    query = f"""
        WITH actual AS (
            SELECT 
                entity_code,
                observed_at,
                observed_at_ts,
                park_date,
                wait_time_minutes as actual_time
            FROM read_parquet('{parquet_dir}/*.parquet')
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
            FROM read_parquet('{parquet_dir}/*.parquet')
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
    
    # Execute and save to parquet
    logger.info("  Running match query...")
    df = con.execute(query).fetchdf()
    
    logger.info(f"  Created {len(df):,} matched pairs")
    
    # Add simple features
    df["observed_at_ts"] = pd.to_datetime(df["observed_at_ts"])
    df["hour_of_day"] = df["observed_at_ts"].dt.hour
    df["mins_since_6am"] = (df["observed_at_ts"].dt.hour - 6) * 60 + df["observed_at_ts"].dt.minute
    df["day_of_week"] = df["observed_at_ts"].dt.dayofweek
    df["month"] = df["observed_at_ts"].dt.month
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    
    # Save to parquet
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    logger.info(f"  Saved matched pairs to: {output_path}")
    
    con.close()
    return len(df)


def train_single_entity(args):
    """Train model for a single entity (called in parallel)."""
    entity_code, matched_pairs_path, models_dir, min_samples = args
    
    try:
        # Load matched pairs for this entity
        df = pd.read_parquet(
            matched_pairs_path,
            filters=[("entity_code", "==", entity_code)]
        )
        
        if len(df) < min_samples:
            return entity_code, None, f"Not enough samples ({len(df)})"
        
        # Prepare features
        feature_cols = ["posted_time"] + [c for c in PREDICTOR_COLUMNS if c in df.columns]
        X = df[feature_cols].fillna(-1)
        y = df["actual_time"]
        
        # Remove invalid rows
        valid = y.notna() & (y > 0)
        X = X[valid]
        y = y[valid]
        
        if len(X) < min_samples:
            return entity_code, None, f"Not enough valid samples ({len(X)})"
        
        # Train/val split (chronological)
        n = len(X)
        train_end = int(n * 0.85)
        
        X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
        X_val, y_val = X.iloc[train_end:], y.iloc[train_end:]
        
        # Train XGBoost
        model = xgb.XGBRegressor(
            n_estimators=500,
            max_depth=6,
            learning_rate=0.1,
            early_stopping_rounds=20,
            random_state=42,
        )
        
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        
        # Evaluate
        y_pred = model.predict(X_val)
        mae = np.mean(np.abs(y_val - y_pred))
        
        # Save model
        model_dir = models_dir / entity_code
        model_dir.mkdir(parents=True, exist_ok=True)
        model.save_model(str(model_dir / "model.json"))
        
        # Save metadata
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


def main():
    parser = argparse.ArgumentParser(description="Fast training pipeline")
    parser.add_argument("--parquet-dir", default="/home/wilma/hazeydata/pipeline/fact_tables/parquet")
    parser.add_argument("--output-base", default="/home/wilma/hazeydata/pipeline")
    parser.add_argument("--min-obs", type=int, default=DEFAULT_MIN_OBS)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--skip-matching", action="store_true", help="Use existing matched pairs")
    
    args = parser.parse_args()
    
    if xgb is None:
        print("ERROR: XGBoost not installed")
        sys.exit(1)
    
    parquet_dir = Path(args.parquet_dir)
    output_base = Path(args.output_base)
    models_dir = output_base / "models"
    matched_pairs_path = output_base / "matched_pairs" / "all_pairs.parquet"
    
    logger = setup_logging(output_base)
    
    logger.info("=" * 60)
    logger.info("FAST TRAINING PIPELINE")
    logger.info("=" * 60)
    logger.info(f"Parquet dir: {parquet_dir}")
    logger.info(f"Min observations: {args.min_obs}")
    logger.info(f"Workers: {args.workers}")
    
    # Step 1: Get entity counts
    start = datetime.now()
    entity_counts = get_entity_counts_duckdb(parquet_dir, logger)
    logger.info(f"  Counting took {(datetime.now() - start).total_seconds():.1f}s")
    
    # Split by threshold
    entities_to_train = [e for e, c in entity_counts.items() if c >= args.min_obs]
    entities_fallback = [e for e, c in entity_counts.items() if c < args.min_obs]
    
    logger.info(f"\nEntities with >= {args.min_obs} ACTUAL: {len(entities_to_train)}")
    logger.info(f"Entities with < {args.min_obs} ACTUAL: {len(entities_fallback)} (82% ratio)")
    
    # Show top entities
    sorted_counts = sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)
    logger.info(f"\nTop 20 entities:")
    for e, c in sorted_counts[:20]:
        logger.info(f"  {e}: {c:,}")
    
    # Step 2: Create matched pairs (if needed)
    if not args.skip_matching or not matched_pairs_path.exists():
        start = datetime.now()
        n_pairs = create_all_matched_pairs_duckdb(parquet_dir, matched_pairs_path, logger)
        logger.info(f"  Matching took {(datetime.now() - start).total_seconds():.1f}s")
    else:
        logger.info(f"\nUsing existing matched pairs: {matched_pairs_path}")
    
    # Step 3: Train models in parallel
    logger.info(f"\n{'='*60}")
    logger.info(f"TRAINING {len(entities_to_train)} ENTITY MODELS (parallel)")
    logger.info(f"{'='*60}")
    
    start = datetime.now()
    
    work_items = [
        (entity, matched_pairs_path, models_dir, 100)
        for entity in entities_to_train
    ]
    
    successful = 0
    failed = 0
    
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(train_single_entity, item): item[0] for item in work_items}
        
        for future in as_completed(futures):
            entity = futures[future]
            result = future.result()
            
            if result[1] is not None:
                successful += 1
                if successful % 20 == 0:
                    logger.info(f"  Trained {successful}/{len(entities_to_train)} models...")
            else:
                failed += 1
                logger.warning(f"  {entity}: {result[2]}")
    
    elapsed = (datetime.now() - start).total_seconds()
    
    logger.info(f"\n{'='*60}")
    logger.info(f"TRAINING COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Training time: {elapsed:.1f}s ({elapsed/len(entities_to_train):.2f}s per entity)")
    logger.info(f"Models saved to: {models_dir}")


if __name__ == "__main__":
    main()
