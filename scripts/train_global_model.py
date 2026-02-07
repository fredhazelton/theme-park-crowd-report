#!/usr/bin/env python3
"""
Train Global Model (Cross-Entity)

================================================================================
PURPOSE
================================================================================
Trains a single XGBoost model on ALL entity data combined. This model learns
the relationship between POSTED → ACTUAL across all attractions, using
entity_code as a feature.

Use cases:
  - Fallback for entities with <500 observations (below entity-specific threshold)
  - New attractions with no historical data
  - Backup when entity-specific model fails

The global model is saved to: models/_global/model_with_posted.json

================================================================================
DATA FILTERING (Critical!)
================================================================================
Two filters are applied to limit the training set:

1. **Entity filter**: Only entities that:
   - Appear in dimEntity (have TouringPlans S3 mapping)
   - Have actual observations in fact tables
   - Have >= 500 ACTUAL observations

2. **Row filter**: Only rows that have BOTH:
   - ACTUAL wait time
   - Matching POSTED wait time (same entity + park_date)

This dramatically reduces the data volume and focuses training on useful data.

================================================================================
USAGE
================================================================================
  python scripts/train_global_model.py
  python scripts/train_global_model.py --output-base /path/to/pipeline
  python scripts/train_global_model.py --max-rows 1000000  # Limit for testing
  python scripts/train_global_model.py --min-observations 1000  # Stricter entity filter
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

# Add src to path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from processors.encoding import encode_features
from processors.entity_index import get_trainable_entities
from processors.features import add_features
from processors.training import (
    DEFAULT_XGB_PARAMS,
    EARLY_STOPPING_ROUNDS,
    evaluate_model,
    prepare_training_data,
)
from utils.paths import get_output_base

try:
    import xgboost as xgb
except ImportError:
    xgb = None


def setup_logging(output_base: Path) -> logging.Logger:
    """Set up logging to file and console."""
    log_dir = output_base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / f"train_global_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"Logging to: {log_file}")
    return logger


def load_training_data(
    output_base: Path,
    logger: logging.Logger,
    min_observations: int = 500,
    max_rows: Optional[int] = None,
) -> pd.DataFrame:
    """
    Load training data with entity and row filtering.
    
    Applies two filters:
    1. Entity filter: Only trainable entities (in dimEntity + have actual data)
    2. Row filter: Only rows with both ACTUAL and POSTED times
    
    Returns a DataFrame ready for feature engineering with columns:
    - entity_code, observed_at, park_date
    - observed_wait_time (ACTUAL)
    - posted_wait_time (matched POSTED)
    """
    # Step 1: Get trainable entities
    trainable_entities = get_trainable_entities(
        output_base,
        min_actual_count=min_observations,
        logger=logger,
    )
    
    if not trainable_entities:
        logger.error("No trainable entities found!")
        return pd.DataFrame()
    
    logger.info(f"Loading data for {len(trainable_entities)} trainable entities...")
    
    # Step 2: Load fact table data for trainable entities only
    fact_dir = output_base / "fact_tables" / "clean"
    
    if not fact_dir.exists():
        logger.error(f"Fact tables directory not found: {fact_dir}")
        return pd.DataFrame()
    
    actual_dfs = []
    posted_dfs = []
    total_actual = 0
    total_posted = 0
    
    # Iterate through year-month directories
    for month_dir in sorted(fact_dir.iterdir()):
        if not month_dir.is_dir():
            continue
        
        for csv_file in sorted(month_dir.glob("*.csv")):
            try:
                df = pd.read_csv(csv_file, low_memory=False)
                
                # Filter to trainable entities only
                df = df[df["entity_code"].str.upper().isin(trainable_entities)]
                
                if df.empty:
                    continue
                
                # Normalize entity_code to uppercase
                df["entity_code"] = df["entity_code"].str.upper()
                
                # Split into ACTUAL and POSTED
                df_actual = df[df["wait_time_type"] == "ACTUAL"].copy()
                df_posted = df[df["wait_time_type"] == "POSTED"].copy()
                
                if not df_actual.empty:
                    actual_dfs.append(df_actual)
                    total_actual += len(df_actual)
                
                if not df_posted.empty:
                    posted_dfs.append(df_posted)
                    total_posted += len(df_posted)
                
                # Check max_rows limit
                if max_rows and total_actual >= max_rows:
                    logger.info(f"Reached max_rows limit ({max_rows}), stopping load")
                    break
                    
            except Exception as e:
                logger.warning(f"Error reading {csv_file}: {e}")
        
        if max_rows and total_actual >= max_rows:
            break
    
    if not actual_dfs:
        logger.error("No ACTUAL data found for trainable entities")
        return pd.DataFrame()
    
    logger.info(f"Loaded {total_actual:,} ACTUAL rows, {total_posted:,} POSTED rows")
    
    # Combine data
    df_actual = pd.concat(actual_dfs, ignore_index=True)
    df_posted = pd.concat(posted_dfs, ignore_index=True) if posted_dfs else pd.DataFrame()
    
    if max_rows and len(df_actual) > max_rows:
        df_actual = df_actual.head(max_rows)
        logger.info(f"Limited to {max_rows:,} ACTUAL rows")
    
    # Step 3: Add park_date for joining
    df_actual["observed_at_dt"] = pd.to_datetime(df_actual["observed_at"], utc=True, errors="coerce")
    df_actual["park_date"] = df_actual["observed_at_dt"].dt.date
    
    if df_posted.empty:
        logger.error("No POSTED data found - cannot train with-POSTED model")
        return pd.DataFrame()
    
    df_posted["observed_at_dt"] = pd.to_datetime(df_posted["observed_at"], utc=True, errors="coerce")
    df_posted["park_date"] = df_posted["observed_at_dt"].dt.date
    
    # Step 4: Join POSTED to ACTUAL using 15-minute window matching
    # Any POSTED within 15 minutes of ACTUAL is a valid pair
    # If multiple POSTEDs within 15 min, keep all pairs (creates multiple training rows)
    logger.info("Joining POSTED values to ACTUAL rows (15-minute window)...")
    
    MATCH_WINDOW_MINUTES = 15
    match_window_ns = MATCH_WINDOW_MINUTES * 60 * 1e9  # nanoseconds
    
    # Build lookup dict for POSTED values
    posted_lookup = {}
    for (entity, park_date), group in df_posted.groupby(["entity_code", "park_date"]):
        times = group["observed_at_dt"].values  # numpy datetime64
        values = group["wait_time_minutes"].values
        posted_lookup[(entity, park_date)] = (times, values)
    
    # Match POSTED to each ACTUAL row - keep all matches within window
    matched_rows = []
    
    for idx, row in df_actual.iterrows():
        key = (row["entity_code"], row["park_date"])
        if key not in posted_lookup:
            continue
        
        posted_times, posted_vals = posted_lookup[key]
        actual_time = row["observed_at_dt"]
        
        if pd.isna(actual_time):
            continue
        
        # Find all POSTED times within 15-minute window
        actual_time_np = np.datetime64(actual_time)
        time_diffs = np.abs(posted_times.astype('datetime64[ns]') - actual_time_np.astype('datetime64[ns]'))
        time_diffs_ns = time_diffs.astype('timedelta64[ns]').astype(np.int64)
        
        # Get indices of POSTEDs within window
        within_window = np.where(time_diffs_ns <= match_window_ns)[0]
        
        if len(within_window) == 0:
            continue
        
        # Create a row for each valid POSTED match
        for posted_idx in within_window:
            posted_value = posted_vals[posted_idx]
            if pd.notna(posted_value) and posted_value > 0:
                new_row = row.copy()
                new_row["posted_wait_time"] = float(posted_value)
                matched_rows.append(new_row)
    
    if not matched_rows:
        logger.error("No ACTUAL/POSTED pairs found within 15-minute window")
        return pd.DataFrame()
    
    # Combine matched rows and deduplicate
    df_matched = pd.DataFrame(matched_rows)
    
    # Dedupe: keep unique combinations of entity_code, observed_at, posted_wait_time
    before_dedupe = len(df_matched)
    df_matched = df_matched.drop_duplicates(
        subset=["entity_code", "observed_at", "posted_wait_time"]
    )
    
    logger.info(f"Matched {len(df_matched):,} ACTUAL/POSTED pairs within {MATCH_WINDOW_MINUTES}-min window "
                f"(from {len(df_actual):,} ACTUAL rows, {before_dedupe - len(df_matched):,} dupes removed)")
    
    # Step 5: Prepare training dataset
    df_training = df_matched.reset_index(drop=True)  # Reset index for feature engineering
    
    logger.info(f"Training dataset: {len(df_training):,} rows with both ACTUAL and POSTED")
    
    if len(df_training) < 1000:
        logger.error(f"Not enough training data ({len(df_training)} rows, need at least 1000)")
        return pd.DataFrame()
    
    # Rename columns for compatibility with feature engineering
    df_training["observed_wait_time"] = df_training["wait_time_minutes"]
    
    # Clean up temporary columns
    df_training = df_training.drop(columns=["observed_at_dt"], errors="ignore")
    
    # Log entity distribution
    entity_counts = df_training["entity_code"].value_counts()
    logger.info(f"Data spans {len(entity_counts)} entities")
    logger.info(f"Top 5 entities by row count:")
    for entity, count in entity_counts.head().items():
        logger.info(f"  {entity}: {count:,} rows")
    
    return df_training


def train_global_model(
    df: pd.DataFrame,
    output_base: Path,
    logger: logging.Logger,
) -> dict:
    """Train global model on filtered training data."""
    
    if xgb is None:
        logger.error("XGBoost not installed. Run: pip install xgboost")
        return {}
    
    logger.info(f"Starting training with {len(df):,} rows...")
    
    # Add features
    logger.info("Adding features...")
    df_features = add_features(df, output_base, logger=logger)
    
    # Encode categorical features
    logger.info("Encoding features...")
    df_encoded, mappings = encode_features(
        df_features,
        output_base,
        strategy="label",
        handle_unknown="encode",
        save_mappings=True,
        logger=logger,
    )
    
    # Prepare training data
    # NOTE: We set include_posted=False because we already joined POSTED
    # We'll manually include posted_wait_time as a feature
    logger.info("Preparing training data...")
    try:
        X, y, feature_names = prepare_training_data(
            df_encoded,
            include_posted=False,  # We already joined POSTED manually
            target_wait_type="ACTUAL",
            logger=logger,
        )
    except ValueError as e:
        logger.error(f"Failed to prepare training data: {e}")
        return {}
    
    # Manually add posted_wait_time as a feature
    if "posted_wait_time" in df_encoded.columns:
        X["posted_wait_time"] = df_encoded.loc[X.index, "posted_wait_time"].values
        feature_names = list(feature_names) + ["posted_wait_time"]
    
    logger.info(f"Training data: {len(X):,} samples, {len(feature_names)} features")
    logger.info(f"Features: {feature_names}")
    
    # Remove rows with missing target
    valid_mask = y.notna()
    X = X[valid_mask]
    y = y[valid_mask]
    logger.info(f"After removing missing targets: {len(X):,} samples")
    
    if len(X) < 1000:
        logger.error("Not enough training data (need at least 1000 samples)")
        return {}
    
    # Chronological split (80/10/10)
    n = len(X)
    train_end = int(n * 0.8)
    val_end = int(n * 0.9)
    
    X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
    X_val, y_val = X.iloc[train_end:val_end], y.iloc[train_end:val_end]
    X_test, y_test = X.iloc[val_end:], y.iloc[val_end:]
    
    logger.info(f"Split: train={len(X_train):,}, val={len(X_val):,}, test={len(X_test):,}")
    
    # Train XGBoost
    logger.info("Training XGBoost model...")
    
    params = DEFAULT_XGB_PARAMS.copy()
    n_estimators = params.pop("n_estimators", 2000)
    
    model = xgb.XGBRegressor(
        n_estimators=n_estimators,
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        **params,
    )
    
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )
    
    best_iteration = model.best_iteration
    logger.info(f"Best iteration: {best_iteration} (of {n_estimators} max)")
    
    # Evaluate on test set
    metrics = evaluate_model(model, X_test, y_test, logger)
    
    logger.info("Test set metrics:")
    for metric, value in metrics.items():
        if value is not None:
            logger.info(f"  {metric}: {value:.4f}")
    
    # Save model
    model_dir = output_base / "models" / "_global"
    model_dir.mkdir(parents=True, exist_ok=True)
    
    model_path = model_dir / "model_with_posted.json"
    model.save_model(str(model_path))
    logger.info(f"Saved global model to: {model_path}")
    
    # Save metadata
    metadata = {
        "model_type": "global",
        "trained_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        "n_training_samples": len(X_train),
        "n_validation_samples": len(X_val),
        "n_test_samples": len(X_test),
        "n_entities": df["entity_code"].nunique(),
        "best_iteration": best_iteration,
        "features": feature_names,
        "metrics": metrics,
        "filters_applied": {
            "entity_filter": "dimEntity AND has_actual_observations",
            "row_filter": "has_both_actual_and_posted",
        },
    }
    
    metadata_path = model_dir / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"Saved metadata to: {metadata_path}")
    
    return metrics


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Train global model on all entity data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--output-base",
        type=str,
        help="Pipeline output base directory",
    )
    
    parser.add_argument(
        "--max-rows",
        type=int,
        help="Maximum ACTUAL rows to load (for testing)",
    )
    
    parser.add_argument(
        "--min-observations",
        type=int,
        default=500,
        help="Minimum ACTUAL observations per entity (default: 500)",
    )
    
    args = parser.parse_args()
    
    # Get output base
    if args.output_base:
        output_base = Path(args.output_base)
    else:
        output_base = get_output_base()
    
    logger = setup_logging(output_base)
    logger.info("=" * 60)
    logger.info("GLOBAL MODEL TRAINING")
    logger.info("=" * 60)
    logger.info(f"Output base: {output_base}")
    logger.info(f"Min observations per entity: {args.min_observations}")
    if args.max_rows:
        logger.info(f"Max rows: {args.max_rows}")
    
    # Load training data (with entity and row filtering)
    df = load_training_data(
        output_base,
        logger,
        min_observations=args.min_observations,
        max_rows=args.max_rows,
    )
    
    if df.empty:
        logger.error("No training data available")
        sys.exit(1)
    
    # Train global model
    metrics = train_global_model(df, output_base, logger)
    
    if metrics:
        logger.info("=" * 60)
        logger.info("GLOBAL MODEL TRAINING COMPLETE")
        logger.info(f"Model saved to: {output_base / 'models' / '_global'}")
        logger.info("=" * 60)
    else:
        logger.error("Global model training failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
