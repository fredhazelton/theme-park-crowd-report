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
USAGE
================================================================================
  python scripts/train_global_model.py
  python scripts/train_global_model.py --output-base /path/to/pipeline
  python scripts/train_global_model.py --max-rows 1000000  # Limit for testing
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

from processors.encoding import encode_features, load_encoding_mappings, save_encoding_mappings
from processors.features import add_features, load_dims
from processors.training import (
    DEFAULT_XGB_PARAMS,
    EARLY_STOPPING_ROUNDS,
    evaluate_predictions,
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


def load_all_fact_data(output_base: Path, logger: logging.Logger, max_rows: Optional[int] = None) -> pd.DataFrame:
    """Load all fact table data from clean CSVs."""
    fact_dir = output_base / "fact_tables" / "clean"
    
    if not fact_dir.exists():
        logger.error(f"Fact tables directory not found: {fact_dir}")
        return pd.DataFrame()
    
    all_dfs = []
    total_rows = 0
    
    # Iterate through year-month directories
    for month_dir in sorted(fact_dir.iterdir()):
        if not month_dir.is_dir():
            continue
        
        for csv_file in sorted(month_dir.glob("*.csv")):
            try:
                df = pd.read_csv(csv_file)
                all_dfs.append(df)
                total_rows += len(df)
                
                if max_rows and total_rows >= max_rows:
                    logger.info(f"Reached max_rows limit ({max_rows}), stopping load")
                    break
            except Exception as e:
                logger.warning(f"Error reading {csv_file}: {e}")
        
        if max_rows and total_rows >= max_rows:
            break
    
    if not all_dfs:
        logger.error("No fact table data found")
        return pd.DataFrame()
    
    combined = pd.concat(all_dfs, ignore_index=True)
    
    if max_rows and len(combined) > max_rows:
        combined = combined.head(max_rows)
    
    logger.info(f"Loaded {len(combined):,} rows from fact tables")
    return combined


def train_global_model(
    df: pd.DataFrame,
    output_base: Path,
    logger: logging.Logger,
) -> dict:
    """Train global model on all entity data."""
    
    if xgb is None:
        logger.error("XGBoost not installed. Run: pip install xgboost")
        return {}
    
    logger.info(f"Training global model on {len(df):,} rows")
    
    # Prepare features
    logger.info("Adding features...")
    dims = load_dims(output_base, logger)
    df_features = add_features(df, output_base, dims=dims, logger=logger)
    
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
    
    # Prepare training data (ACTUAL target with POSTED as feature)
    logger.info("Preparing training data...")
    try:
        X, y, feature_names = prepare_training_data(
            df_encoded,
            include_posted=True,
            target_wait_type="ACTUAL",
            logger=logger,
        )
    except ValueError as e:
        logger.error(f"Failed to prepare training data: {e}")
        return {}
    
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
    y_pred = model.predict(X_test)
    metrics = evaluate_predictions(y_test.values, y_pred, logger)
    
    logger.info("Test set metrics:")
    for metric, value in metrics.items():
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
        "best_iteration": best_iteration,
        "features": feature_names,
        "metrics": metrics,
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
        help="Maximum rows to load (for testing)",
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
    
    # Load all fact data
    df = load_all_fact_data(output_base, logger, max_rows=args.max_rows)
    
    if df.empty:
        logger.error("No data to train on")
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
