#!/usr/bin/env python3
"""
Train Live Inference Model

Trains a global XGBoost model optimized for real-time inference of ACTUAL 
wait times from POSTED wait times. This is a simplified version of the 
conversion model that only uses features available at inference time.

Key differences from conversion model:
- NO rolling features (posted_delta_*, posted_rolling_*, posted_volatility_*)
- Only 7 features that can be computed from (entity_code, posted_time, observed_at)
- Optimized for fast prediction on live data

Features used:
- posted_time (the live posted wait time)
- entity_encoded (label-encoded entity_code)
- park_encoded (label-encoded park_code, derived from first 2 chars)
- hour_of_day (from observed_at)
- mins_since_6am (from observed_at)
- mins_since_open (from park hours)
- date_group_id_encoded (from dimdategroupid)
- season_encoded (from dimseason)

Output:
- models/_live_inference/model.json: XGBoost live inference model
- models/_live_inference/metadata.json: Metrics, encodings, and feature info

Usage:
    python scripts/train_live_inference_model.py
    python scripts/train_live_inference_model.py --output-base /mnt/data/pipeline
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from zoneinfo import ZoneInfo

try:
    import xgboost as xgb
except ImportError:
    xgb = None

# Add src to path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from processors.posted_to_actual import build_matched_pairs, _encode_categoricals, CONVERSION_XGB_PARAMS
from utils.paths import get_output_base


# Live inference features (NO rolling features)
LIVE_INFERENCE_FEATURES = [
    "posted_time",
    "entity_encoded", 
    "park_encoded",
    "hour_of_day",
    "mins_since_6am", 
    "mins_since_open",
    "date_group_id_encoded",
    "season_encoded",
]


def setup_logging(log_dir: Path) -> logging.Logger:
    """Set up file and console logging."""
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(ZoneInfo('UTC')).strftime('%Y%m%d_%H%M%S')
    log_file = log_dir / f"train_live_inference_{timestamp}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"Training live inference model - Log file: {log_file}")
    return logger


def train_live_inference_model(
    output_base: Path,
    logger: Optional[logging.Logger] = None,
) -> Dict:
    """
    Train the live inference model using only real-time available features.
    
    Reuses the same matched pairs and training methodology as the conversion model,
    but only uses features that can be computed at inference time without requiring
    historical rolling windows.
    
    Returns:
        Dictionary of test set metrics
    """
    if xgb is None:
        raise ImportError("XGBoost not installed")
    
    if logger:
        logger.info("Training live inference model...")
        logger.info("Features (NO rolling features for real-time inference):")
        for i, feat in enumerate(LIVE_INFERENCE_FEATURES, 1):
            logger.info(f"  {i}. {feat}")
    
    # Step 1: Load existing matched pairs (faster than rebuilding)
    matched_pairs_path = output_base / "matched_pairs" / "all_pairs_v2.parquet"
    if matched_pairs_path.exists():
        if logger:
            logger.info(f"Loading existing matched pairs from {matched_pairs_path}...")
        df = pd.read_parquet(matched_pairs_path)
        if logger:
            logger.info(f"  Loaded {len(df):,} matched pairs")
            logger.info(f"  Entities: {df['entity_code'].nunique()}")
            logger.info(f"  Date range: {df['park_date'].min()} to {df['park_date'].max()}")
        
        # Add park_code column if missing
        if 'park_code' not in df.columns:
            df['park_code'] = df['entity_code'].str[:2].str.upper()
            if logger:
                logger.info("  Added park_code column from entity_code")
    else:
        # Fallback to building pairs if file doesn't exist
        if logger:
            logger.info("Matched pairs file not found, building from scratch...")
        df = build_matched_pairs(output_base, logger)
    
    if len(df) < 100:
        raise ValueError(f"Not enough matched pairs ({len(df)}). Need at least 100.")
    
    # Step 1b: Compute entity-specific ratios for 100-499 pair tier
    # Entities with 100-499 pairs use simple ratio instead of global XGBoost (better for railroads, people-movers)
    entity_counts = df.groupby("entity_code").agg(
        count=("actual_time", "count"),
        actual_sum=("actual_time", "sum"),
        posted_sum=("posted_time", "sum"),
    ).reset_index()
    ratio_tier = entity_counts[
        (entity_counts["count"] >= 100) & (entity_counts["count"] < 500)
    ]
    entity_ratios = {}
    for _, row in ratio_tier.iterrows():
        if row["posted_sum"] > 0:
            entity_ratios[row["entity_code"]] = round(
                float(row["actual_sum"] / row["posted_sum"]), 4
            )
    model_dir = output_base / "models" / "_live_inference"
    model_dir.mkdir(parents=True, exist_ok=True)
    entity_ratios_path = model_dir / "entity_ratios.json"
    with open(entity_ratios_path, "w", encoding="utf-8") as f:
        json.dump(entity_ratios, f, indent=2)
    if logger:
        logger.info(f"  Entity-ratio tier (100-499 pairs): {len(entity_ratios)} entities")
        logger.info(f"  Saved to: {entity_ratios_path}")
    
    # Step 2: Encode categoricals
    if logger:
        logger.info("Encoding categorical features...")
    
    # Check if encoding already done
    if 'entity_encoded' not in df.columns:
        df, encodings = _encode_categoricals(df, logger)
    else:
        if logger:
            logger.info("  Categories already encoded, extracting encodings...")
        
        # Extract existing encodings from the data
        encodings = {}
        
        # Entity encoding
        entity_map = {}
        for entity in df['entity_code'].unique():
            encoded_val = df[df['entity_code'] == entity]['entity_encoded'].iloc[0]
            entity_map[entity] = int(encoded_val) if pd.notna(encoded_val) else 0
        encodings['entity_code'] = entity_map
        
        # Park encoding
        if 'park_encoded' in df.columns:
            park_map = {}
            for park in df['park_code'].unique():
                encoded_val = df[df['park_code'] == park]['park_encoded'].iloc[0] 
                park_map[park] = int(encoded_val) if pd.notna(encoded_val) else 0
            encodings['park_code'] = park_map
        else:
            # Create park encoding
            parks = sorted(df['park_code'].unique())
            park_map = {p: i for i, p in enumerate(parks)}
            df['park_encoded'] = df['park_code'].map(park_map)
            encodings['park_code'] = park_map
        
        # Date group encoding
        if 'date_group_id_encoded' in df.columns:
            dg_map = {}
            for dg_id in df['date_group_id'].unique():
                if pd.notna(dg_id):
                    encoded_val = df[df['date_group_id'] == dg_id]['date_group_id_encoded'].iloc[0]
                    dg_map[str(dg_id)] = int(encoded_val) if pd.notna(encoded_val) else 0
            encodings['date_group_id'] = dg_map
        else:
            # Create date group encoding
            dg = sorted([str(d) for d in df['date_group_id'].unique() if pd.notna(d)])
            dg_map = {d: i for i, d in enumerate(dg)}
            df['date_group_id_encoded'] = df['date_group_id'].astype(str).map(dg_map)
            encodings['date_group_id'] = dg_map
        
        # Season encoding
        if 'season_encoded' in df.columns:
            season_map = {}
            for season in df['season'].unique():
                if pd.notna(season):
                    encoded_val = df[df['season'] == season]['season_encoded'].iloc[0]
                    season_map[season] = int(encoded_val) if pd.notna(encoded_val) else 0
            encodings['season'] = season_map
        else:
            # Create season encoding
            seasons = sorted([s for s in df['season'].unique() if pd.notna(s)])
            season_map = {s: i for i, s in enumerate(seasons)}
            df['season_encoded'] = df['season'].map(season_map)
            encodings['season'] = season_map
        
        if logger:
            logger.info(f"  Extracted: {len(encodings['entity_code'])} entities, {len(encodings['park_code'])} parks, "
                         f"{len(encodings['date_group_id'])} date groups, {len(encodings['season'])} seasons")
    
    # Step 3: Handle missing values for mins_since_open
    if 'mins_since_open' in df.columns:
        df['mins_since_open'] = df['mins_since_open'].fillna(df['mins_since_6am'])
    
    # Step 4: Same chronological split as conversion model (70/15/15)
    unique_dates = sorted(df['park_date'].unique())
    n_dates = len(unique_dates)
    train_end = int(n_dates * 0.70)
    val_end = int(n_dates * 0.85)
    
    train_dates = set(unique_dates[:train_end])
    val_dates = set(unique_dates[train_end:val_end])
    test_dates = set(unique_dates[val_end:])
    
    train_df = df[df['park_date'].isin(train_dates)]
    val_df = df[df['park_date'].isin(val_dates)]
    test_df = df[df['park_date'].isin(test_dates)]
    
    if logger:
        logger.info(f"Chronological split:")
        logger.info(f"  Train: {len(train_df):,} samples ({min(train_dates)} to {max(train_dates)})")
        logger.info(f"  Val:   {len(val_df):,} samples ({min(val_dates)} to {max(val_dates)})")
        logger.info(f"  Test:  {len(test_df):,} samples ({min(test_dates)} to {max(test_dates)})")
    
    # Step 5: Prepare features and target (only live inference features)
    available_features = [c for c in LIVE_INFERENCE_FEATURES if c in df.columns]
    
    if len(available_features) != len(LIVE_INFERENCE_FEATURES):
        missing = set(LIVE_INFERENCE_FEATURES) - set(available_features)
        raise ValueError(f"Missing required features: {missing}")
    
    X_train = train_df[available_features].values
    y_train = train_df['actual_time'].values
    X_val = val_df[available_features].values
    y_val = val_df['actual_time'].values
    X_test = test_df[available_features].values
    y_test = test_df['actual_time'].values
    
    if logger:
        logger.info(f"Training features ({len(available_features)}): {available_features}")
    
    # Step 6: Train XGBoost with same params as conversion model
    if logger:
        logger.info("Training XGBoost live inference model...")
    
    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=available_features)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=available_features)
    dtest = xgb.DMatrix(X_test, label=y_test, feature_names=available_features)
    
    params = {k: v for k, v in CONVERSION_XGB_PARAMS.items() if k != 'n_estimators'}
    
    model = xgb.train(
        params=params,
        dtrain=dtrain,
        num_boost_round=CONVERSION_XGB_PARAMS['n_estimators'],
        evals=[(dtrain, 'train'), (dval, 'val')],
        early_stopping_rounds=50,
        verbose_eval=False,
    )
    
    best_round = getattr(model, 'best_iteration', CONVERSION_XGB_PARAMS['n_estimators'])
    if logger:
        logger.info(f"Best iteration: {best_round}")
    
    # Step 7: Evaluate on test set
    y_pred = model.predict(dtest)
    
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    r2 = r2_score(y_test, y_pred)
    correlation = np.corrcoef(y_test, y_pred)[0, 1]
    bias = float(np.mean(y_pred - y_test))
    
    metrics = {
        "mae": float(mae),
        "rmse": float(rmse),
        "r2": float(r2),
        "correlation": float(correlation),
        "bias": bias,
        "n_train": len(train_df),
        "n_val": len(val_df),
        "n_test": len(test_df),
        "n_total": len(df),
        "n_entities": int(df['entity_code'].nunique()),
        "best_iteration": int(best_round),
        "avg_posted_overestimation": float((df['posted_time'] - df['actual_time']).mean()),
    }
    
    if logger:
        logger.info("=" * 60)
        logger.info("LIVE INFERENCE MODEL RESULTS (test set)")
        logger.info("=" * 60)
        logger.info(f"MAE:         {mae:.2f} minutes")
        logger.info(f"RMSE:        {rmse:.2f} minutes")
        logger.info(f"R²:          {r2:.4f}")
        logger.info(f"Correlation: {correlation:.4f}")
        logger.info(f"Bias:        {bias:+.2f} minutes")
        logger.info(f"Pairs used:  {len(df):,} from {df['entity_code'].nunique()} entities")
        logger.info("")
        logger.info(f"Comparison to conversion model MAE (10.89):")
        logger.info(f"  Live inference MAE: {mae:.2f}")
        logger.info(f"  Difference: {mae - 10.89:+.2f} (cost of dropping rolling features)")
    
    # Step 8: Save model and metadata
    model_dir = output_base / "models" / "_live_inference"
    model_dir.mkdir(parents=True, exist_ok=True)
    
    model_path = model_dir / "model.json"
    model.save_model(str(model_path))
    
    metadata = {
        "created_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        "metrics": metrics,
        "feature_names": available_features,
        "encodings": encodings,
        "params": CONVERSION_XGB_PARAMS,
        "model_type": "live_inference",
        "description": "XGBoost model for real-time POSTED->ACTUAL conversion without rolling features",
    }
    
    metadata_path = model_dir / "metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False, default=str)
    
    if logger:
        logger.info(f"Saved model: {model_path}")
        logger.info(f"Saved metadata: {metadata_path}")
    
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Train live inference model")
    parser.add_argument(
        "--output-base",
        type=Path,
        default=get_output_base(),
        help="Output base directory (default: from config)",
    )
    
    args = parser.parse_args()
    
    output_base = args.output_base.resolve()
    log_dir = output_base / "logs"
    logger = setup_logging(log_dir)
    
    logger.info("=" * 60)
    logger.info("TRAIN LIVE INFERENCE MODEL")
    logger.info("=" * 60)
    logger.info(f"Output base: {output_base}")
    
    start_time = time.time()
    
    try:
        # Train the live inference model
        metrics = train_live_inference_model(output_base, logger)
        
        elapsed = time.time() - start_time
        
        logger.info("=" * 60)
        logger.info("TRAINING COMPLETE")
        logger.info("=" * 60)
        logger.info(f"⏱️  Training time: {elapsed:.1f} seconds")
        logger.info("")
        logger.info("Final Test Metrics:")
        logger.info(f"  MAE (Mean Absolute Error): {metrics['mae']:.2f} minutes")
        logger.info(f"  RMSE (Root Mean Squared Error): {metrics['rmse']:.2f} minutes")
        logger.info(f"  R² (Coefficient of Determination): {metrics['r2']:.3f}")
        logger.info(f"  Bias (Mean Signed Error): {metrics['bias']:.2f} minutes")
        logger.info(f"  Correlation: {metrics['correlation']:.3f}")
        logger.info("")
        logger.info("Training Data:")
        logger.info(f"  Training samples: {metrics['n_train']:,}")
        logger.info(f"  Validation samples: {metrics['n_val']:,}")
        logger.info(f"  Test samples: {metrics['n_test']:,}")
        logger.info("")
        logger.info("Model saved to:")
        logger.info(f"  {output_base}/models/_live_inference/model.json")
        logger.info(f"  {output_base}/models/_live_inference/metadata.json")
        logger.info("=" * 60)
        
        # Success
        sys.exit(0)
        
    except Exception as e:
        logger.exception(f"Training failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()