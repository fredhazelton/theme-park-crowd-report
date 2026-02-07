#!/usr/bin/env python3
"""
Train and Score Pipeline - Complete Actual Wait Time Prediction

================================================================================
PURPOSE
================================================================================
End-to-end pipeline that:
1. Matches all ACTUAL/POSTED pairs within 15-minute window
2. Trains entity-specific models for entities with 500+ ACTUAL observations
3. Trains a global model on 25% sample from ALL entities with any ACTUAL
4. Scores all historical POSTED observations with predicted actual times
5. Generates future predictions for upcoming dates

================================================================================
OUTPUT STRUCTURE
================================================================================
predictions/
  historical/
    {entity_code}.csv  - All historical observations with predictions
  future/
    {entity_code}.csv  - Future date predictions

Historical file columns:
  - entity_code
  - observed_at (timestamp)
  - observed_posted_time (nullable)
  - observed_actual_time (nullable)
  - predicted_actual_time (always populated)
  - [all predictor columns]

Future file columns:
  - Same structure, but observed values are null

================================================================================
USAGE
================================================================================
  python scripts/train_and_score_pipeline.py
  python scripts/train_and_score_pipeline.py --sample-rate 0.25  # Global model sample rate
  python scripts/train_and_score_pipeline.py --min-entity-obs 500  # Entity model threshold
  python scripts/train_and_score_pipeline.py --future-days 30  # Days ahead to predict
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

# Add src to path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from processors.encoding import encode_features, load_encoding_mappings
from processors.features import add_features
from processors.training import DEFAULT_XGB_PARAMS, EARLY_STOPPING_ROUNDS, evaluate_model
from utils.paths import get_output_base

try:
    import xgboost as xgb
except ImportError:
    xgb = None

# Constants
MATCH_WINDOW_MINUTES = 15
DEFAULT_SAMPLE_RATE = 0.25
DEFAULT_MIN_ENTITY_OBS = 500
DEFAULT_FUTURE_DAYS = 30

# Feature columns for training (will be populated during feature engineering)
PREDICTOR_COLUMNS = [
    "pred_mins_since_6am",
    "pred_dategroupid",
    "pred_season",
    "pred_season_year",
    "park_code",
    "pred_mins_since_park_open",
    "pred_park_open_hour",
    "pred_park_close_hour",
    "pred_park_hours_open",
    "pred_emh_morning",
    "pred_emh_evening",
]


def setup_logging(output_base: Path) -> logging.Logger:
    """Set up logging to file and console."""
    log_dir = output_base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / f"train_score_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
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


def load_all_fact_data(output_base: Path, logger: logging.Logger) -> pd.DataFrame:
    """
    Load all fact table data from CSVs.
    
    Returns DataFrame with columns:
    - entity_code, observed_at, wait_time_type, wait_time_minutes
    """
    fact_dir = output_base / "fact_tables" / "clean"
    
    if not fact_dir.exists():
        logger.error(f"Fact tables directory not found: {fact_dir}")
        return pd.DataFrame()
    
    logger.info("Loading all fact table CSVs...")
    
    dfs = []
    csv_count = 0
    
    for month_dir in sorted(fact_dir.iterdir()):
        if not month_dir.is_dir():
            continue
        
        for csv_file in month_dir.glob("*.csv"):
            try:
                df = pd.read_csv(csv_file, low_memory=False)
                df["entity_code"] = df["entity_code"].str.upper()
                dfs.append(df)
                csv_count += 1
            except Exception as e:
                logger.warning(f"Error reading {csv_file}: {e}")
        
        if csv_count % 1000 == 0 and csv_count > 0:
            logger.info(f"  Loaded {csv_count} CSVs...")
    
    if not dfs:
        logger.error("No fact data found")
        return pd.DataFrame()
    
    df = pd.concat(dfs, ignore_index=True)
    logger.info(f"Loaded {len(df):,} rows from {csv_count} CSVs")
    
    return df


def create_matched_pairs(
    df: pd.DataFrame,
    logger: logging.Logger,
) -> pd.DataFrame:
    """
    Match ACTUAL and POSTED observations within 15-minute window.
    
    For each ACTUAL observation, find all POSTED observations for the same
    entity within the time window.
    
    Returns DataFrame with:
    - entity_code, observed_at, observed_actual_time, observed_posted_time
    """
    logger.info("Creating matched ACTUAL/POSTED pairs (15-minute window)...")
    
    # Parse timestamps
    df["observed_at_dt"] = pd.to_datetime(df["observed_at"], utc=True, errors="coerce")
    df["park_date"] = df["observed_at_dt"].dt.date
    
    # Split by wait type
    df_actual = df[df["wait_time_type"] == "ACTUAL"].copy()
    df_posted = df[df["wait_time_type"] == "POSTED"].copy()
    
    logger.info(f"  ACTUAL rows: {len(df_actual):,}")
    logger.info(f"  POSTED rows: {len(df_posted):,}")
    
    if df_actual.empty or df_posted.empty:
        logger.error("Missing ACTUAL or POSTED data")
        return pd.DataFrame()
    
    # Build lookup dict for POSTED by (entity, date)
    posted_lookup = {}
    for (entity, park_date), group in df_posted.groupby(["entity_code", "park_date"]):
        posted_lookup[(entity, park_date)] = (
            group["observed_at_dt"].values,
            group["wait_time_minutes"].values,
            group["observed_at"].values,
        )
    
    # Match each ACTUAL to POSTED within window
    match_window_ns = MATCH_WINDOW_MINUTES * 60 * 1e9
    
    matched_rows = []
    entities_matched = set()
    
    total_actual = len(df_actual)
    for i, (idx, row) in enumerate(df_actual.iterrows()):
        if i > 0 and i % 50000 == 0:
            logger.info(f"  Processed {i:,}/{total_actual:,} ACTUAL rows, {len(matched_rows):,} pairs...")
        
        key = (row["entity_code"], row["park_date"])
        if key not in posted_lookup:
            continue
        
        posted_times, posted_vals, posted_obs_at = posted_lookup[key]
        actual_time = row["observed_at_dt"]
        
        if pd.isna(actual_time):
            continue
        
        # Find POSTED within window
        actual_time_np = np.datetime64(actual_time).astype('datetime64[ns]')
        time_diffs = np.abs((posted_times.astype('datetime64[ns]') - actual_time_np).astype(np.int64))
        within_window = np.where(time_diffs <= match_window_ns)[0]
        
        if len(within_window) == 0:
            continue
        
        # Keep best match (closest in time)
        best_idx = within_window[np.argmin(time_diffs[within_window])]
        
        matched_rows.append({
            "entity_code": row["entity_code"],
            "observed_at": row["observed_at"],
            "observed_at_dt": actual_time,
            "park_date": row["park_date"],
            "observed_actual_time": row["wait_time_minutes"],
            "observed_posted_time": posted_vals[best_idx],
        })
        entities_matched.add(row["entity_code"])
    
    if not matched_rows:
        logger.error("No matched pairs found")
        return pd.DataFrame()
    
    df_matched = pd.DataFrame(matched_rows)
    
    # Dedupe
    before_dedupe = len(df_matched)
    df_matched = df_matched.drop_duplicates(subset=["entity_code", "observed_at"])
    
    logger.info(f"Created {len(df_matched):,} matched pairs across {len(entities_matched)} entities")
    if before_dedupe > len(df_matched):
        logger.info(f"  Removed {before_dedupe - len(df_matched):,} duplicates")
    
    return df_matched


def prepare_training_features(
    df: pd.DataFrame,
    output_base: Path,
    logger: logging.Logger,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Add predictor features and encode categoricals.
    
    Returns (encoded_df, feature_names)
    """
    logger.info("Adding features...")
    
    # Rename for compatibility with add_features
    df = df.copy()
    df["wait_time_minutes"] = df["observed_actual_time"]  # Target
    df["wait_time_type"] = "ACTUAL"
    
    # Add features
    df_features = add_features(df, output_base, logger=logger)
    
    # Encode categoricals
    logger.info("Encoding features...")
    df_encoded, _ = encode_features(
        df_features,
        output_base,
        strategy="label",
        handle_unknown="encode",
        save_mappings=True,
        logger=logger,
    )
    
    # Build feature list
    feature_cols = [c for c in PREDICTOR_COLUMNS if c in df_encoded.columns]
    
    # Add entity_code as feature (for global model)
    if "entity_code" in df_encoded.columns:
        feature_cols.append("entity_code")
    
    # Add posted time as feature
    feature_cols.append("observed_posted_time")
    
    logger.info(f"Features: {feature_cols}")
    
    return df_encoded, feature_cols


def train_entity_model(
    df: pd.DataFrame,
    entity_code: str,
    feature_cols: list[str],
    output_base: Path,
    logger: logging.Logger,
) -> Optional[xgb.XGBRegressor]:
    """Train model for a single entity."""
    
    df_entity = df[df["entity_code"] == entity_code].copy()
    
    if len(df_entity) < 100:
        logger.warning(f"  {entity_code}: Not enough data ({len(df_entity)} rows)")
        return None
    
    # Prepare X and y
    feature_cols_no_entity = [c for c in feature_cols if c != "entity_code"]
    X = df_entity[feature_cols_no_entity].copy()
    y = df_entity["observed_actual_time"]
    
    # Handle missing values
    X = X.fillna(-1)
    
    # Remove rows with missing target
    valid_mask = y.notna()
    X = X[valid_mask]
    y = y[valid_mask]
    
    if len(X) < 100:
        logger.warning(f"  {entity_code}: Not enough valid data ({len(X)} rows)")
        return None
    
    # Chronological split
    n = len(X)
    train_end = int(n * 0.8)
    val_end = int(n * 0.9)
    
    X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
    X_val, y_val = X.iloc[train_end:val_end], y.iloc[train_end:val_end]
    
    if len(X_val) < 10:
        # Not enough validation data, use all for training
        X_train, y_train = X, y
        X_val, y_val = X.iloc[-50:], y.iloc[-50:]
    
    # Train
    params = DEFAULT_XGB_PARAMS.copy()
    n_estimators = params.pop("n_estimators", 1000)
    
    model = xgb.XGBRegressor(
        n_estimators=n_estimators,
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        **params,
    )
    
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    
    return model


def train_global_model(
    df: pd.DataFrame,
    feature_cols: list[str],
    sample_rate: float,
    output_base: Path,
    logger: logging.Logger,
) -> Optional[xgb.XGBRegressor]:
    """Train global model on sampled data from all entities."""
    
    logger.info(f"Training global model (sample rate: {sample_rate:.0%})...")
    
    # Sample data
    if sample_rate < 1.0:
        df_sample = df.sample(frac=sample_rate, random_state=42)
    else:
        df_sample = df
    
    logger.info(f"  Training on {len(df_sample):,} samples from {df_sample['entity_code'].nunique()} entities")
    
    # Prepare X and y (include entity_code for global model)
    X = df_sample[feature_cols].copy()
    y = df_sample["observed_actual_time"]
    
    # Encode entity_code as numeric
    if "entity_code" in X.columns:
        entity_map = {e: i for i, e in enumerate(X["entity_code"].unique())}
        X["entity_code"] = X["entity_code"].map(entity_map)
    
    # Handle missing values
    X = X.fillna(-1)
    
    # Remove rows with missing target
    valid_mask = y.notna()
    X = X[valid_mask]
    y = y[valid_mask]
    
    # Chronological split
    n = len(X)
    train_end = int(n * 0.8)
    val_end = int(n * 0.9)
    
    X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
    X_val, y_val = X.iloc[train_end:val_end], y.iloc[train_end:val_end]
    X_test, y_test = X.iloc[val_end:], y.iloc[val_end:]
    
    logger.info(f"  Split: train={len(X_train):,}, val={len(X_val):,}, test={len(X_test):,}")
    
    # Train
    params = DEFAULT_XGB_PARAMS.copy()
    n_estimators = params.pop("n_estimators", 2000)
    
    model = xgb.XGBRegressor(
        n_estimators=n_estimators,
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        **params,
    )
    
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    
    # Evaluate
    y_pred = model.predict(X_test)
    mae = np.mean(np.abs(y_test - y_pred))
    rmse = np.sqrt(np.mean((y_test - y_pred) ** 2))
    
    logger.info(f"  Global model metrics: MAE={mae:.2f}, RMSE={rmse:.2f}")
    
    # Save model
    model_dir = output_base / "models" / "_global"
    model_dir.mkdir(parents=True, exist_ok=True)
    model.save_model(str(model_dir / "model_with_posted.json"))
    
    # Save entity mapping
    if "entity_code" in df_sample.columns:
        entity_map = {e: i for i, e in enumerate(df["entity_code"].unique())}
        with open(model_dir / "entity_mapping.json", "w") as f:
            json.dump(entity_map, f)
    
    logger.info(f"  Saved global model to {model_dir}")
    
    return model


def score_historical_data(
    df_facts: pd.DataFrame,
    df_matched: pd.DataFrame,
    entity_models: dict,
    global_model: xgb.XGBRegressor,
    feature_cols: list[str],
    output_base: Path,
    logger: logging.Logger,
) -> None:
    """
    Score all historical data and write per-entity CSVs.
    
    Output columns:
    - entity_code, observed_at, observed_posted_time, observed_actual_time,
      predicted_actual_time, [predictor columns]
    """
    logger.info("Scoring historical data...")
    
    pred_dir = output_base / "predictions" / "historical"
    pred_dir.mkdir(parents=True, exist_ok=True)
    
    # Get all unique entities
    entities = df_facts["entity_code"].unique()
    logger.info(f"  Scoring {len(entities)} entities...")
    
    # Load entity mapping for global model
    entity_map_path = output_base / "models" / "_global" / "entity_mapping.json"
    entity_map = {}
    if entity_map_path.exists():
        with open(entity_map_path) as f:
            entity_map = json.load(f)
    
    feature_cols_no_entity = [c for c in feature_cols if c != "entity_code"]
    
    for i, entity in enumerate(sorted(entities)):
        if i > 0 and i % 50 == 0:
            logger.info(f"  Processed {i}/{len(entities)} entities...")
        
        # Get entity data
        df_entity = df_facts[df_facts["entity_code"] == entity].copy()
        
        if df_entity.empty:
            continue
        
        # Prepare features (need to add features to raw data)
        df_entity["wait_time_type"] = "POSTED"  # For feature engineering
        df_entity = add_features(df_entity, output_base, logger=None)
        
        # Encode
        df_entity, _ = encode_features(
            df_entity, output_base, strategy="label", 
            handle_unknown="encode", save_mappings=False, logger=None
        )
        
        # Get posted times from original data
        posted_map = df_facts[
            (df_facts["entity_code"] == entity) & 
            (df_facts["wait_time_type"] == "POSTED")
        ].set_index("observed_at")["wait_time_minutes"].to_dict()
        
        actual_map = df_facts[
            (df_facts["entity_code"] == entity) & 
            (df_facts["wait_time_type"] == "ACTUAL")
        ].set_index("observed_at")["wait_time_minutes"].to_dict()
        
        # Add observed values
        df_entity["observed_posted_time"] = df_entity["observed_at"].map(posted_map)
        df_entity["observed_actual_time"] = df_entity["observed_at"].map(actual_map)
        
        # Select model
        if entity in entity_models:
            model = entity_models[entity]
            use_entity_feature = False
        else:
            model = global_model
            use_entity_feature = True
        
        # Prepare X for prediction
        if use_entity_feature and "entity_code" in feature_cols:
            X = df_entity[feature_cols].copy()
            X["entity_code"] = entity_map.get(entity, -1)
        else:
            X = df_entity[feature_cols_no_entity].copy()
        
        X = X.fillna(-1)
        
        # Predict
        df_entity["predicted_actual_time"] = model.predict(X)
        
        # Select output columns
        output_cols = [
            "entity_code", "observed_at", "observed_posted_time", 
            "observed_actual_time", "predicted_actual_time"
        ]
        # Add predictor columns that exist
        for col in PREDICTOR_COLUMNS:
            if col in df_entity.columns:
                output_cols.append(col)
        
        # Dedupe and sort
        df_out = df_entity[output_cols].drop_duplicates(subset=["observed_at"])
        df_out = df_out.sort_values("observed_at")
        
        # Write CSV
        output_path = pred_dir / f"{entity}.csv"
        df_out.to_csv(output_path, index=False)
    
    logger.info(f"  Wrote historical predictions to {pred_dir}")


def generate_future_predictions(
    entities: list[str],
    entity_models: dict,
    global_model: xgb.XGBRegressor,
    feature_cols: list[str],
    future_days: int,
    output_base: Path,
    logger: logging.Logger,
) -> None:
    """
    Generate predictions for future dates.
    
    Creates a row for each (entity, future_datetime) combination with null 
    observed values and predicted actual time.
    """
    logger.info(f"Generating future predictions ({future_days} days)...")
    
    pred_dir = output_base / "predictions" / "future"
    pred_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate future timestamps (every 15 minutes during park hours 8am-11pm)
    today = datetime.now(ZoneInfo("America/New_York")).date()
    future_dates = [today + timedelta(days=d) for d in range(1, future_days + 1)]
    
    # Create timestamp grid (8am to 11pm every 15 min)
    times_per_day = []
    for hour in range(8, 23):
        for minute in [0, 15, 30, 45]:
            times_per_day.append(f"{hour:02d}:{minute:02d}:00")
    
    # Load entity mapping for global model
    entity_map_path = output_base / "models" / "_global" / "entity_mapping.json"
    entity_map = {}
    if entity_map_path.exists():
        with open(entity_map_path) as f:
            entity_map = json.load(f)
    
    feature_cols_no_entity = [c for c in feature_cols if c != "entity_code"]
    
    for entity in sorted(entities):
        # Build future timestamps
        rows = []
        for date in future_dates:
            for time_str in times_per_day:
                dt_str = f"{date}T{time_str}-05:00"  # EST
                rows.append({
                    "entity_code": entity,
                    "observed_at": dt_str,
                    "observed_posted_time": None,
                    "observed_actual_time": None,
                })
        
        df_future = pd.DataFrame(rows)
        
        # Add features
        df_future["wait_time_type"] = "POSTED"
        df_future["wait_time_minutes"] = 0  # Placeholder
        df_future = add_features(df_future, output_base, logger=None)
        
        # Encode
        df_future, _ = encode_features(
            df_future, output_base, strategy="label",
            handle_unknown="encode", save_mappings=False, logger=None
        )
        
        # Select model
        if entity in entity_models:
            model = entity_models[entity]
            use_entity_feature = False
        else:
            model = global_model
            use_entity_feature = True
        
        # Prepare X
        if use_entity_feature and "entity_code" in feature_cols:
            X = df_future[feature_cols].copy()
            X["entity_code"] = entity_map.get(entity, -1)
        else:
            X = df_future[feature_cols_no_entity].copy()
        
        # Set posted_time to -1 for future (null)
        if "observed_posted_time" in X.columns:
            X["observed_posted_time"] = -1
        
        X = X.fillna(-1)
        
        # Predict
        df_future["predicted_actual_time"] = model.predict(X)
        
        # Select output columns
        output_cols = [
            "entity_code", "observed_at", "observed_posted_time",
            "observed_actual_time", "predicted_actual_time"
        ]
        for col in PREDICTOR_COLUMNS:
            if col in df_future.columns:
                output_cols.append(col)
        
        df_out = df_future[output_cols]
        
        # Write CSV
        output_path = pred_dir / f"{entity}.csv"
        df_out.to_csv(output_path, index=False)
    
    logger.info(f"  Wrote future predictions to {pred_dir}")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Train and score pipeline")
    parser.add_argument("--output-base", type=str, help="Pipeline output directory")
    parser.add_argument("--sample-rate", type=float, default=DEFAULT_SAMPLE_RATE,
                        help=f"Global model sample rate (default: {DEFAULT_SAMPLE_RATE})")
    parser.add_argument("--min-entity-obs", type=int, default=DEFAULT_MIN_ENTITY_OBS,
                        help=f"Min observations for entity model (default: {DEFAULT_MIN_ENTITY_OBS})")
    parser.add_argument("--future-days", type=int, default=DEFAULT_FUTURE_DAYS,
                        help=f"Days ahead to predict (default: {DEFAULT_FUTURE_DAYS})")
    parser.add_argument("--skip-historical", action="store_true",
                        help="Skip historical scoring (train only)")
    parser.add_argument("--skip-future", action="store_true",
                        help="Skip future predictions")
    
    args = parser.parse_args()
    
    if xgb is None:
        print("ERROR: XGBoost not installed. Run: pip install xgboost")
        sys.exit(1)
    
    # Get output base
    if args.output_base:
        output_base = Path(args.output_base)
    else:
        output_base = get_output_base()
    
    logger = setup_logging(output_base)
    
    logger.info("=" * 70)
    logger.info("TRAIN AND SCORE PIPELINE")
    logger.info("=" * 70)
    logger.info(f"Output base: {output_base}")
    logger.info(f"Global model sample rate: {args.sample_rate:.0%}")
    logger.info(f"Entity model min observations: {args.min_entity_obs}")
    logger.info(f"Future prediction days: {args.future_days}")
    
    # Step 1: Load all fact data
    df_facts = load_all_fact_data(output_base, logger)
    if df_facts.empty:
        sys.exit(1)
    
    # Step 2: Create matched pairs
    df_matched = create_matched_pairs(df_facts, logger)
    if df_matched.empty:
        sys.exit(1)
    
    # Step 3: Add features and encode
    df_encoded, feature_cols = prepare_training_features(df_matched, output_base, logger)
    
    # Step 4: Train entity-specific models
    logger.info("=" * 70)
    logger.info("TRAINING ENTITY-SPECIFIC MODELS")
    logger.info("=" * 70)
    
    entity_counts = df_encoded.groupby("entity_code").size()
    entities_for_model = entity_counts[entity_counts >= args.min_entity_obs].index.tolist()
    
    logger.info(f"Training models for {len(entities_for_model)} entities with {args.min_entity_obs}+ observations")
    
    entity_models = {}
    for entity in entities_for_model:
        model = train_entity_model(df_encoded, entity, feature_cols, output_base, logger)
        if model is not None:
            entity_models[entity] = model
            # Save entity model
            model_dir = output_base / "models" / entity
            model_dir.mkdir(parents=True, exist_ok=True)
            model.save_model(str(model_dir / "model_with_posted.json"))
            logger.info(f"  {entity}: Trained and saved")
    
    logger.info(f"Trained {len(entity_models)} entity-specific models")
    
    # Step 5: Train global model
    logger.info("=" * 70)
    logger.info("TRAINING GLOBAL MODEL")
    logger.info("=" * 70)
    
    global_model = train_global_model(
        df_encoded, feature_cols, args.sample_rate, output_base, logger
    )
    
    if global_model is None:
        logger.error("Failed to train global model")
        sys.exit(1)
    
    # Step 6: Score historical data
    if not args.skip_historical:
        logger.info("=" * 70)
        logger.info("SCORING HISTORICAL DATA")
        logger.info("=" * 70)
        
        score_historical_data(
            df_facts, df_matched, entity_models, global_model,
            feature_cols, output_base, logger
        )
    
    # Step 7: Generate future predictions
    if not args.skip_future:
        logger.info("=" * 70)
        logger.info("GENERATING FUTURE PREDICTIONS")
        logger.info("=" * 70)
        
        all_entities = df_facts["entity_code"].unique().tolist()
        generate_future_predictions(
            all_entities, entity_models, global_model,
            feature_cols, args.future_days, output_base, logger
        )
    
    logger.info("=" * 70)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
