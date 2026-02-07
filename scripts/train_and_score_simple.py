#!/usr/bin/env python3
"""
Simple Train and Score Pipeline

================================================================================
PURPOSE
================================================================================
Simplified pipeline that:
1. Trains entity-specific models ONLY for entities with 500+ ACTUAL observations
2. Uses 82% ratio fallback for all other entities (predicted = posted * 0.82)
3. Scores all historical data and generates future predictions

================================================================================
OUTPUT
================================================================================
predictions/
  historical/{entity_code}.csv  - All historical observations with predictions
  future/{entity_code}.csv      - Future date predictions

================================================================================
USAGE
================================================================================
  python scripts/train_and_score_simple.py
  python scripts/train_and_score_simple.py --min-obs 500
  python scripts/train_and_score_simple.py --fallback-ratio 0.82
"""

from __future__ import annotations

import argparse
import json
import logging
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

from processors.encoding import encode_features
from processors.features import add_features
from processors.training import DEFAULT_XGB_PARAMS, EARLY_STOPPING_ROUNDS

try:
    import xgboost as xgb
except ImportError:
    xgb = None

# Constants
MATCH_WINDOW_MINUTES = 15
DEFAULT_MIN_OBS = 500
DEFAULT_FALLBACK_RATIO = 0.82
DEFAULT_FUTURE_DAYS = 30

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
    """Set up logging."""
    log_dir = output_base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / f"train_score_simple_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
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


def get_entities_by_actual_count(output_base: Path, min_count: int, logger: logging.Logger) -> tuple[set, set]:
    """
    Get entities split by ACTUAL observation count.
    
    Counts directly from fact tables (not the stale entity_index).
    
    Returns (entities_with_enough, entities_without_enough)
    """
    from collections import defaultdict
    
    fact_dir = output_base / "fact_tables" / "clean"
    if not fact_dir.exists():
        logger.error(f"Fact tables not found: {fact_dir}")
        return set(), set()
    
    logger.info("Counting ACTUAL observations directly from fact tables...")
    
    actual_counts = defaultdict(int)
    file_count = 0
    
    for month_dir in sorted(fact_dir.iterdir()):
        if not month_dir.is_dir():
            continue
        
        for csv_file in month_dir.glob("*.csv"):
            try:
                df = pd.read_csv(csv_file, usecols=["entity_code", "wait_time_type"], low_memory=False)
                actual = df[df["wait_time_type"] == "ACTUAL"]
                for entity in actual["entity_code"].str.upper().unique():
                    actual_counts[entity] += len(actual[actual["entity_code"].str.upper() == entity])
                file_count += 1
            except Exception:
                continue
        
        if file_count % 5000 == 0 and file_count > 0:
            logger.info(f"  Scanned {file_count} files...")
    
    logger.info(f"  Scanned {file_count} total files")
    
    enough = set()
    not_enough = set()
    
    for entity, count in actual_counts.items():
        if count >= min_count:
            enough.add(entity)
        else:
            not_enough.add(entity)
    
    # Log top entities
    sorted_counts = sorted(actual_counts.items(), key=lambda x: x[1], reverse=True)
    logger.info(f"\nEntities with >= {min_count} ACTUAL: {len(enough)}")
    logger.info(f"Entities with < {min_count} ACTUAL: {len(not_enough)} (will use {DEFAULT_FALLBACK_RATIO:.0%} ratio)")
    
    logger.info(f"\nTop 20 entities by ACTUAL count:")
    for e, c in sorted_counts[:20]:
        marker = "✓ MODEL" if c >= min_count else ""
        logger.info(f"  {e}: {c:,} {marker}")
    
    return enough, not_enough


def load_entity_data(entity_code: str, output_base: Path, logger: logging.Logger) -> pd.DataFrame:
    """Load all fact data for a single entity."""
    from processors.entity_index import _get_park_code_from_entity
    
    park_code = _get_park_code_from_entity(entity_code)
    fact_dir = output_base / "fact_tables" / "clean"
    
    dfs = []
    for csv_path in fact_dir.rglob("*.csv"):
        if csv_path.stem.startswith(f"{park_code}_"):
            try:
                df = pd.read_csv(csv_path, low_memory=False)
                df["entity_code"] = df["entity_code"].str.upper()
                entity_df = df[df["entity_code"] == entity_code.upper()]
                if not entity_df.empty:
                    dfs.append(entity_df)
            except Exception:
                continue
    
    if not dfs:
        return pd.DataFrame()
    
    return pd.concat(dfs, ignore_index=True)


def create_matched_pairs_for_entity(df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """Match ACTUAL/POSTED pairs for a single entity's data."""
    
    df["observed_at_dt"] = pd.to_datetime(df["observed_at"], utc=True, errors="coerce")
    df["park_date"] = df["observed_at_dt"].dt.date
    
    df_actual = df[df["wait_time_type"] == "ACTUAL"].copy()
    df_posted = df[df["wait_time_type"] == "POSTED"].copy()
    
    if df_actual.empty or df_posted.empty:
        return pd.DataFrame()
    
    # Build lookup by date
    posted_lookup = {}
    for park_date, group in df_posted.groupby("park_date"):
        posted_lookup[park_date] = (
            group["observed_at_dt"].values,
            group["wait_time_minutes"].values,
        )
    
    match_window_ns = MATCH_WINDOW_MINUTES * 60 * 1e9
    matched_rows = []
    
    for _, row in df_actual.iterrows():
        if row["park_date"] not in posted_lookup:
            continue
        
        posted_times, posted_vals = posted_lookup[row["park_date"]]
        actual_time = row["observed_at_dt"]
        
        if pd.isna(actual_time):
            continue
        
        actual_time_np = np.datetime64(actual_time).astype('datetime64[ns]')
        time_diffs = np.abs((posted_times.astype('datetime64[ns]') - actual_time_np).astype(np.int64))
        within_window = np.where(time_diffs <= match_window_ns)[0]
        
        if len(within_window) == 0:
            continue
        
        best_idx = within_window[np.argmin(time_diffs[within_window])]
        
        matched_rows.append({
            "entity_code": row["entity_code"],
            "observed_at": row["observed_at"],
            "park_date": row["park_date"],
            "observed_actual_time": row["wait_time_minutes"],
            "observed_posted_time": posted_vals[best_idx],
        })
    
    if not matched_rows:
        return pd.DataFrame()
    
    df_matched = pd.DataFrame(matched_rows)
    df_matched = df_matched.drop_duplicates(subset=["observed_at"])
    
    return df_matched


def train_entity_model(
    df_matched: pd.DataFrame,
    entity_code: str,
    output_base: Path,
    logger: logging.Logger,
) -> Optional[xgb.XGBRegressor]:
    """Train model for a single entity."""
    
    if len(df_matched) < 100:
        logger.warning(f"  {entity_code}: Not enough matched pairs ({len(df_matched)})")
        return None
    
    # Add features
    df = df_matched.copy().reset_index(drop=True)  # Reset index for feature engineering
    df["wait_time_minutes"] = df["observed_actual_time"]
    df["wait_time_type"] = "ACTUAL"
    
    try:
        df = add_features(df, output_base, logger=None)
        df, _ = encode_features(df, output_base, strategy="label", 
                                handle_unknown="encode", save_mappings=False, logger=None)
    except Exception as e:
        import traceback
        logger.warning(f"  {entity_code}: Feature engineering failed: {type(e).__name__}: {e}")
        logger.warning(f"  Traceback: {traceback.format_exc()}")
        return None
    
    # Prepare features
    feature_cols = [c for c in PREDICTOR_COLUMNS if c in df.columns]
    feature_cols.append("observed_posted_time")
    
    X = df[feature_cols].copy().fillna(-1)
    y = df["observed_actual_time"]
    
    valid_mask = y.notna() & (y > 0)
    X = X[valid_mask]
    y = y[valid_mask]
    
    if len(X) < 100:
        logger.warning(f"  {entity_code}: Not enough valid training data ({len(X)})")
        return None
    
    # Split
    n = len(X)
    train_end = int(n * 0.8)
    
    X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
    X_val, y_val = X.iloc[train_end:], y.iloc[train_end:]
    
    if len(X_val) < 10:
        X_val, y_val = X_train.iloc[-50:], y_train.iloc[-50:]
    
    # Train
    params = DEFAULT_XGB_PARAMS.copy()
    n_estimators = params.pop("n_estimators", 1000)
    
    model = xgb.XGBRegressor(
        n_estimators=n_estimators,
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        **params,
    )
    
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    
    # Evaluate
    y_pred = model.predict(X_val)
    mae = np.mean(np.abs(y_val - y_pred))
    
    logger.info(f"  {entity_code}: Trained on {len(X_train)} samples, MAE={mae:.2f}")
    
    # Save model
    model_dir = output_base / "models" / entity_code
    model_dir.mkdir(parents=True, exist_ok=True)
    model.save_model(str(model_dir / "model_with_posted.json"))
    
    # Save metadata
    metadata = {
        "entity_code": entity_code,
        "trained_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        "n_training_samples": len(X_train),
        "mae": float(mae),
        "features": feature_cols,
    }
    with open(model_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    
    return model


def score_entity_historical(
    entity_code: str,
    df_facts: pd.DataFrame,
    model: Optional[xgb.XGBRegressor],
    fallback_ratio: float,
    output_base: Path,
    logger: logging.Logger,
) -> None:
    """Score historical data for an entity."""
    
    pred_dir = output_base / "predictions" / "historical"
    pred_dir.mkdir(parents=True, exist_ok=True)
    
    if df_facts.empty:
        return
    
    # Get posted and actual values
    df_posted = df_facts[df_facts["wait_time_type"] == "POSTED"].copy()
    df_actual = df_facts[df_facts["wait_time_type"] == "ACTUAL"].copy()
    
    if df_posted.empty:
        return
    
    # Build actual lookup
    actual_map = df_actual.set_index("observed_at")["wait_time_minutes"].to_dict()
    
    # Start with posted observations
    df_out = df_posted[["entity_code", "observed_at", "wait_time_minutes"]].copy()
    df_out = df_out.rename(columns={"wait_time_minutes": "observed_posted_time"})
    df_out["observed_actual_time"] = df_out["observed_at"].map(actual_map)
    
    if model is not None:
        # Use model to predict
        df_out["wait_time_minutes"] = df_out["observed_posted_time"]
        df_out["wait_time_type"] = "POSTED"
        
        try:
            df_features = add_features(df_out.copy(), output_base, logger=None)
            df_features, _ = encode_features(df_features, output_base, strategy="label",
                                             handle_unknown="encode", save_mappings=False, logger=None)
            
            feature_cols = [c for c in PREDICTOR_COLUMNS if c in df_features.columns]
            feature_cols.append("observed_posted_time")
            
            X = df_features[feature_cols].fillna(-1)
            df_out["predicted_actual_time"] = model.predict(X)
        except Exception as e:
            # Fall back to ratio if model prediction fails
            df_out["predicted_actual_time"] = df_out["observed_posted_time"] * fallback_ratio
    else:
        # Use fallback ratio
        df_out["predicted_actual_time"] = df_out["observed_posted_time"] * fallback_ratio
    
    # Clean up and save
    df_out = df_out[["entity_code", "observed_at", "observed_posted_time", 
                     "observed_actual_time", "predicted_actual_time"]]
    df_out = df_out.drop_duplicates(subset=["observed_at"]).sort_values("observed_at")
    
    output_path = pred_dir / f"{entity_code}.csv"
    df_out.to_csv(output_path, index=False)


def generate_entity_future(
    entity_code: str,
    model: Optional[xgb.XGBRegressor],
    fallback_ratio: float,
    future_days: int,
    output_base: Path,
    logger: logging.Logger,
) -> None:
    """Generate future predictions for an entity."""
    
    pred_dir = output_base / "predictions" / "future"
    pred_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate timestamps
    today = datetime.now(ZoneInfo("America/New_York")).date()
    future_dates = [today + timedelta(days=d) for d in range(1, future_days + 1)]
    
    times_per_day = []
    for hour in range(8, 23):
        for minute in [0, 15, 30, 45]:
            times_per_day.append(f"{hour:02d}:{minute:02d}:00")
    
    rows = []
    for date in future_dates:
        for time_str in times_per_day:
            rows.append({
                "entity_code": entity_code,
                "observed_at": f"{date}T{time_str}-05:00",
                "observed_posted_time": None,
                "observed_actual_time": None,
            })
    
    df_out = pd.DataFrame(rows)
    
    # For future, we can't use posted (it's null), so just use a baseline
    # With no posted time, model can still predict based on time/date features
    if model is not None:
        df_out["wait_time_minutes"] = 30  # Placeholder
        df_out["wait_time_type"] = "POSTED"
        df_out["observed_posted_time"] = -1  # Signal null
        
        try:
            df_features = add_features(df_out.copy(), output_base, logger=None)
            df_features, _ = encode_features(df_features, output_base, strategy="label",
                                             handle_unknown="encode", save_mappings=False, logger=None)
            
            feature_cols = [c for c in PREDICTOR_COLUMNS if c in df_features.columns]
            feature_cols.append("observed_posted_time")
            
            X = df_features[feature_cols].fillna(-1)
            df_out["predicted_actual_time"] = model.predict(X)
        except Exception:
            df_out["predicted_actual_time"] = None
    else:
        df_out["predicted_actual_time"] = None
    
    df_out = df_out[["entity_code", "observed_at", "observed_posted_time",
                     "observed_actual_time", "predicted_actual_time"]]
    
    output_path = pred_dir / f"{entity_code}.csv"
    df_out.to_csv(output_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple train and score pipeline")
    parser.add_argument("--output-base", type=str, default="/home/wilma/hazeydata/pipeline")
    parser.add_argument("--min-obs", type=int, default=DEFAULT_MIN_OBS)
    parser.add_argument("--fallback-ratio", type=float, default=DEFAULT_FALLBACK_RATIO)
    parser.add_argument("--future-days", type=int, default=DEFAULT_FUTURE_DAYS)
    parser.add_argument("--skip-scoring", action="store_true")
    parser.add_argument("--skip-future", action="store_true")
    
    args = parser.parse_args()
    
    if xgb is None:
        print("ERROR: XGBoost not installed")
        sys.exit(1)
    
    output_base = Path(args.output_base)
    logger = setup_logging(output_base)
    
    logger.info("=" * 60)
    logger.info("SIMPLE TRAIN AND SCORE PIPELINE")
    logger.info("=" * 60)
    logger.info(f"Min observations for model: {args.min_obs}")
    logger.info(f"Fallback ratio: {args.fallback_ratio:.0%}")
    
    # Get entity lists
    entities_to_model, entities_fallback = get_entities_by_actual_count(
        output_base, args.min_obs, logger
    )
    
    if not entities_to_model:
        logger.error("No entities meet the minimum observation threshold")
        sys.exit(1)
    
    # Train models for qualifying entities
    logger.info("=" * 60)
    logger.info("TRAINING ENTITY MODELS")
    logger.info("=" * 60)
    
    entity_models = {}
    
    for entity in sorted(entities_to_model):
        logger.info(f"Processing {entity}...")
        
        # Load data
        df_facts = load_entity_data(entity, output_base, logger)
        if df_facts.empty:
            logger.warning(f"  {entity}: No data found")
            continue
        
        # Create matched pairs
        df_matched = create_matched_pairs_for_entity(df_facts, logger)
        if df_matched.empty:
            logger.warning(f"  {entity}: No matched pairs")
            continue
        
        logger.info(f"  {entity}: {len(df_matched)} matched pairs")
        
        # Train model
        model = train_entity_model(df_matched, entity, output_base, logger)
        if model is not None:
            entity_models[entity] = model
        
        # Score historical
        if not args.skip_scoring:
            score_entity_historical(entity, df_facts, model, args.fallback_ratio, output_base, logger)
        
        # Generate future
        if not args.skip_future:
            generate_entity_future(entity, model, args.fallback_ratio, args.future_days, output_base, logger)
    
    logger.info(f"\nTrained {len(entity_models)} entity models")
    
    # Score fallback entities (just historical, using ratio)
    if not args.skip_scoring and entities_fallback:
        logger.info("=" * 60)
        logger.info(f"SCORING FALLBACK ENTITIES ({args.fallback_ratio:.0%} ratio)")
        logger.info("=" * 60)
        
        for i, entity in enumerate(sorted(entities_fallback)):
            if i > 0 and i % 50 == 0:
                logger.info(f"  Processed {i}/{len(entities_fallback)} fallback entities...")
            
            df_facts = load_entity_data(entity, output_base, logger)
            if not df_facts.empty:
                score_entity_historical(entity, df_facts, None, args.fallback_ratio, output_base, logger)
    
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"Models trained: {len(entity_models)}")
    logger.info(f"Fallback entities: {len(entities_fallback)}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
