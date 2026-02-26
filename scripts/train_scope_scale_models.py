#!/usr/bin/env python3
"""
Train Scope-and-Scale Group Models for EU Entities

Pools all entities with the same scope_and_scale value into group-level
XGBoost models. These serve as fallbacks for EU entities that have
insufficient per-entity training data.

Models are saved to: models/_scope_scale_{scope_value}/
  - model_scope_scale_v2.json       (with posted_time)
  - model_scope_scale_actuals.json  (without posted_time, primary for forecasting)
  - entity_code_mapping.json        (entity_code -> integer encoding)
  - metadata_scope_scale_v2.json
  - metadata_scope_scale_actuals.json

Usage:
    python scripts/train_scope_scale_models.py --output-base /mnt/data/pipeline
"""

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

# Constants
GEO_DECAY_HALFLIFE_DAYS = 730  # 2 years, same as existing pipeline

# The 5 scope_and_scale values that EU entities belong to
EU_SCOPE_VALUES = [
    "Super Headliner",
    "Headliner",
    "Major Attraction",
    "Minor Attraction",
    "Diversion",
]

# XGBoost params (matching existing pipeline)
XGB_PARAMS = {
    "max_depth": 6,
    "learning_rate": 0.1,
    "n_estimators": 500,
    "min_child_weight": 10,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "objective": "reg:squarederror",
    "random_state": 42,
}

# Features
V2_FEATURES = [
    "posted_time",
    "mins_since_6am",
    "mins_since_open",
    "hour_of_day",
    "date_group_id_encoded",
    "season_encoded",
    "season_year_encoded",
    "entity_code_encoded",
]

ACTUALS_FEATURES = [
    "mins_since_6am",
    "mins_since_open",
    "date_group_id_encoded",
    "season_encoded",
    "season_year_encoded",
    "entity_code_encoded",
]


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"train_scope_scale_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


def compute_geo_decay_weights(park_dates: pd.Series) -> np.ndarray:
    """Compute geo decay weights: 0.5^(days_old / 730)"""
    today = pd.Timestamp(date.today())
    park_dates_ts = pd.to_datetime(park_dates)
    days_old = (today - park_dates_ts).dt.days.values.astype(np.float32)
    weights = np.power(0.5, days_old / GEO_DECAY_HALFLIFE_DAYS).astype(np.float32)
    return weights


def train_scope_model(
    scope_value: str,
    scope_df: pd.DataFrame,
    models_dir: Path,
    logger: logging.Logger,
    model_type: str = "actuals",
) -> dict:
    """Train a single scope_and_scale group model.
    
    model_type: 'actuals' (no posted_time) or 'v2' (with posted_time)
    """
    features = ACTUALS_FEATURES if model_type == "actuals" else V2_FEATURES
    
    # Build entity_code encoding
    unique_entities = sorted(scope_df["entity_code"].unique())
    entity_mapping = {code: idx for idx, code in enumerate(unique_entities)}
    scope_df = scope_df.copy()
    scope_df["entity_code_encoded"] = scope_df["entity_code"].map(entity_mapping).astype(np.float32)
    
    # Fill NaN mins_since_open with 0 (same as Julia scripts)
    scope_df["mins_since_open"] = scope_df["mins_since_open"].fillna(0.0)
    
    # Build feature matrix
    X = scope_df[features].values.astype(np.float32)
    y = scope_df["actual_time"].values.astype(np.float32)
    
    # Filter out invalid rows
    valid = ~np.isnan(y) & (y > 0) & np.all(~np.isnan(X), axis=1)
    X = X[valid]
    y = y[valid]
    
    # Compute geo decay weights
    weights = compute_geo_decay_weights(scope_df.loc[valid, "park_date"] if valid.any() else pd.Series())
    
    if len(y) < 100:
        logger.warning(f"  {scope_value} ({model_type}): only {len(y)} valid samples, skipping")
        return {}
    
    # Chronological train/val split (85/15)
    n = len(y)
    train_end = int(n * 0.85)
    
    X_train, y_train = X[:train_end], y[:train_end]
    X_val, y_val = X[train_end:], y[train_end:]
    weights_train = weights[:train_end] if len(weights) > 0 else None
    
    # Create XGBoost model
    model = xgb.XGBRegressor(
        **XGB_PARAMS,
        early_stopping_rounds=20,
        eval_metric="mae",
    )
    
    model.fit(
        X_train, y_train,
        sample_weight=weights_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )
    
    # Evaluate
    y_pred = model.predict(X_val)
    mae = float(np.mean(np.abs(y_val - y_pred)))
    
    # Save model
    scope_slug = scope_value.lower().replace(" ", "_")
    model_dir = models_dir / f"_scope_scale_{scope_slug}"
    model_dir.mkdir(parents=True, exist_ok=True)
    
    model_filename = f"model_scope_scale_{model_type}.json"
    model_path = model_dir / model_filename
    model.save_model(str(model_path))
    
    # Save entity code mapping
    mapping_path = model_dir / "entity_code_mapping.json"
    # Merge with existing mapping if present (so v2 and actuals share the same mapping)
    if mapping_path.exists():
        with open(mapping_path) as f:
            existing_mapping = json.load(f)
        # Keep the same mapping (both model types use same entity pool)
    else:
        existing_mapping = entity_mapping
    
    with open(mapping_path, "w") as f:
        json.dump(existing_mapping, f, indent=2)
    
    # Save metadata
    metadata = {
        "model_label": f"SCOPE_SCALE_{model_type.upper()}",
        "scope_and_scale": scope_value,
        "model_type": model_type,
        "trained_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "n_train": train_end,
        "n_val": n - train_end,
        "n_total": n,
        "n_entities": len(unique_entities),
        "mae": mae,
        "features": features,
        "uses_geo_decay_weights": True,
        "geo_decay_halflife_days": GEO_DECAY_HALFLIFE_DAYS,
        "hyperparameters": XGB_PARAMS,
        "entity_codes": unique_entities,
        "backend": "Python XGBoost",
    }
    
    metadata_path = model_dir / f"metadata_scope_scale_{model_type}.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    
    logger.info(
        f"  {scope_value} ({model_type}): {n:,} obs, {len(unique_entities)} entities, "
        f"MAE={mae:.2f}, best_iter={model.best_iteration}"
    )
    
    return {
        "scope": scope_value,
        "model_type": model_type,
        "n_obs": n,
        "n_entities": len(unique_entities),
        "mae": mae,
    }


def main():
    parser = argparse.ArgumentParser(description="Train scope-and-scale group models")
    parser.add_argument(
        "--output-base",
        type=Path,
        default=Path("/mnt/data/pipeline"),
        help="Pipeline output base directory",
    )
    args = parser.parse_args()
    
    output_base = args.output_base.resolve()
    models_dir = output_base / "models"
    dim_dir = output_base / "dimension_tables"
    matched_pairs_path = output_base / "matched_pairs" / "all_pairs_v2.parquet"
    
    logger = setup_logging(output_base / "logs")
    
    logger.info("=" * 60)
    logger.info("SCOPE-AND-SCALE GROUP MODEL TRAINING")
    logger.info("=" * 60)
    logger.info(f"Output base: {output_base}")
    
    start_time = time.time()
    
    # Load dimentity.csv to get scope_and_scale mapping
    dimentity_path = dim_dir / "dimentity.csv"
    if not dimentity_path.exists():
        logger.error(f"dimentity.csv not found: {dimentity_path}")
        return 1
    
    dimentity = pd.read_csv(dimentity_path)
    entity_to_scope = dict(zip(dimentity["code"], dimentity["scope_and_scale"]))
    logger.info(f"Loaded dimentity.csv: {len(entity_to_scope)} entities")
    
    # Load matched pairs
    if not matched_pairs_path.exists():
        logger.error(f"Matched pairs not found: {matched_pairs_path}")
        return 1
    
    logger.info("Loading matched pairs...")
    pairs_df = pd.read_parquet(matched_pairs_path)
    logger.info(f"  Loaded {len(pairs_df):,} matched pairs")
    
    # Add scope_and_scale to pairs
    pairs_df["scope_and_scale"] = pairs_df["entity_code"].map(entity_to_scope)
    
    # Train models for each scope value
    results = []
    
    for scope_value in EU_SCOPE_VALUES:
        logger.info(f"\n--- {scope_value} ---")
        
        # Pool all entities with this scope_and_scale
        scope_df = pairs_df[pairs_df["scope_and_scale"] == scope_value].copy()
        
        if len(scope_df) == 0:
            logger.warning(f"  No data for scope_and_scale={scope_value}")
            continue
        
        n_entities = scope_df["entity_code"].nunique()
        n_eu = scope_df[scope_df["entity_code"].str.startswith("EU")]["entity_code"].nunique()
        logger.info(f"  {len(scope_df):,} observations from {n_entities} entities ({n_eu} EU)")
        
        # Train actuals model (primary for forecasting)
        result = train_scope_model(scope_value, scope_df, models_dir, logger, model_type="actuals")
        if result:
            results.append(result)
        
        # Train V2 model (with posted_time)
        result = train_scope_model(scope_value, scope_df, models_dir, logger, model_type="v2")
        if result:
            results.append(result)
    
    elapsed = time.time() - start_time
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("SCOPE-AND-SCALE TRAINING COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Models trained: {len(results)}")
    for r in results:
        logger.info(f"  {r['scope']} ({r['model_type']}): {r['n_obs']:,} obs, {r['n_entities']} entities, MAE={r['mae']:.2f}")
    logger.info(f"Time: {elapsed:.1f}s")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
