#!/usr/bin/env python3
"""
Fast Challenger Prediction Script (XGBoost) — Optimized for speed.

Key optimizations:
1. Batch all dates into single feature matrix per entity
2. Vectorized time slot generation
3. Pre-load all date features once
4. Skip loading operating calendar (use defaults - good enough for competition)

Usage:
    python predict.py --model-dir <path> --challenger-config <path> [--dates YYYY-MM-DD,...]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

STANDARD_FEATURES = [
    "mins_since_6am",
    "mins_since_open",
    "date_group_id_encoded",
    "season_encoded",
    "season_year_encoded",
]

STATE_DIR = Path("/mnt/data/pipeline/state")
DIM_DIR = Path("/mnt/data/pipeline/dimension_tables")

SLOT_INTERVAL_MINUTES = 5
DEFAULT_OPEN_MINS = 7 * 60   # 7:00 AM
DEFAULT_CLOSE_MINS = 23 * 60  # 11:00 PM


def load_date_features_batch(prediction_dates: list[date]) -> dict:
    """Load date-level features for all dates at once."""
    encodings_path = STATE_DIR / "encoding_mappings.json"
    with open(encodings_path) as f:
        encodings = json.load(f)

    dgid_enc = encodings.get("date_group_id", {})
    season_enc = encodings.get("season", {})
    season_year_enc = encodings.get("season_year", {})

    dgid_df = pd.read_csv(DIM_DIR / "dimdategroupid.csv")
    season_df = pd.read_csv(DIM_DIR / "dimseason.csv")

    dgid_df["park_date"] = pd.to_datetime(dgid_df["park_date"]).dt.date
    season_df["park_date"] = pd.to_datetime(season_df["park_date"]).dt.date

    dgid_map = dict(zip(dgid_df["park_date"], dgid_df["date_group_id"]))
    season_map = dict(zip(season_df["park_date"], season_df["season"]))
    season_year_map = dict(zip(season_df["park_date"], season_df["season_year"]))

    date_features = {}
    for d in prediction_dates:
        dgid = dgid_map.get(d, "UNKNOWN")
        season = season_map.get(d, "UNKNOWN")
        season_year = season_year_map.get(d, "UNKNOWN")

        date_features[d] = {
            "date_group_id_encoded": dgid_enc.get(dgid, 0),
            "season_encoded": season_enc.get(season, 0),
            "season_year_encoded": season_year_enc.get(season_year, 0),
        }

    return date_features


def build_feature_matrix(dates: list[date], date_features: dict) -> tuple[np.ndarray, list[date]]:
    """
    Build a single feature matrix for all time slots across all dates.
    
    Returns: (X array of shape (n_slots * n_dates, 5), date index for each row)
    """
    all_rows = []
    date_index = []
    
    n_slots = (DEFAULT_CLOSE_MINS - DEFAULT_OPEN_MINS) // SLOT_INTERVAL_MINUTES
    
    for d in dates:
        df = date_features.get(d, {})
        dgid = df.get("date_group_id_encoded", 0)
        season = df.get("season_encoded", 0)
        season_year = df.get("season_year_encoded", 0)
        
        # Vectorized time slot generation
        mins = np.arange(DEFAULT_OPEN_MINS, DEFAULT_CLOSE_MINS, SLOT_INTERVAL_MINUTES)
        mins_since_6am = np.maximum(mins - 360, 0).astype(np.float32)
        mins_since_open = (mins - DEFAULT_OPEN_MINS).astype(np.float32)
        
        n = len(mins)
        rows = np.column_stack([
            mins_since_6am,
            mins_since_open,
            np.full(n, dgid, dtype=np.float32),
            np.full(n, season, dtype=np.float32),
            np.full(n, season_year, dtype=np.float32),
        ])
        
        all_rows.append(rows)
        date_index.extend([d] * n)
    
    return np.vstack(all_rows), date_index


def predict(model_dir: str, config: dict, prediction_dates: list[str] | None = None) -> pd.DataFrame:
    """Generate predictions for all entities with trained models."""
    start_time = time.time()
    model_path = Path(model_dir)
    features = config.get("features", STANDARD_FEATURES)

    if prediction_dates is None:
        today = date.today()
        prediction_dates = [today.isoformat()]

    dates = [date.fromisoformat(d) for d in prediction_dates]

    # Pre-load all date features
    logger.info(f"Loading date features for {len(dates)} dates...")
    date_features = load_date_features_batch(dates)

    # Pre-build feature matrix (same for all entities since we use default hours)
    logger.info("Building feature matrix...")
    X_all, date_index = build_feature_matrix(dates, date_features)
    n_slots_per_date = (DEFAULT_CLOSE_MINS - DEFAULT_OPEN_MINS) // SLOT_INTERVAL_MINUTES
    
    logger.info(f"Feature matrix: {X_all.shape[0]} rows ({len(dates)} dates × {n_slots_per_date} slots)")

    # Find all entity models
    entity_models = sorted(model_path.glob("*.json"))
    entity_models = [m for m in entity_models if m.stem != "training_summary"
                     and not m.stem.startswith("_")]

    if not entity_models:
        logger.warning(f"No entity models found in {model_path}")
        return pd.DataFrame(columns=["entity_code", "prediction_date", "predicted_actual"])

    logger.info(f"Predicting for {len(entity_models)} entities...")

    results = []
    for i, model_file in enumerate(entity_models):
        entity_code = model_file.stem

        try:
            model = xgb.XGBRegressor()
            model.load_model(str(model_file))
        except Exception as e:
            logger.warning(f"Failed to load model for {entity_code}: {e}")
            continue

        # Predict all time slots at once
        try:
            preds = model.predict(X_all)
            preds = np.maximum(preds, 0)  # clamp negatives

            # Compute daily means
            for j, d in enumerate(dates):
                start_idx = j * n_slots_per_date
                end_idx = start_idx + n_slots_per_date
                daily_mean = float(np.mean(preds[start_idx:end_idx]))

                results.append({
                    "entity_code": entity_code,
                    "prediction_date": d.isoformat(),
                    "predicted_actual": round(daily_mean, 2),
                })
        except Exception as e:
            logger.warning(f"Prediction failed for {entity_code}: {e}")

        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            logger.info(f"  [{i+1}/{len(entity_models)}] {elapsed:.1f}s elapsed")

    predictions = pd.DataFrame(results)

    # Save
    output_path = model_path / "latest_predictions.parquet"
    if not predictions.empty:
        predictions.to_parquet(output_path, index=False)
        elapsed = time.time() - start_time
        logger.info(f"Saved {len(predictions)} predictions to {output_path} ({elapsed:.1f}s)")

    return predictions


def main():
    parser = argparse.ArgumentParser(description="Generate challenger predictions")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--challenger-config", required=True)
    parser.add_argument("--dates", default=None)
    parser.add_argument("--entities", default=None)
    args = parser.parse_args()

    with open(args.challenger_config) as f:
        config = yaml.safe_load(f)

    dates = args.dates.split(",") if args.dates else None
    predictions = predict(args.model_dir, config, prediction_dates=dates)
    print(f"Generated {len(predictions)} predictions")


if __name__ == "__main__":
    main()
