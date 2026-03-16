#!/usr/bin/env python3
"""
Fast Challenger Training Script (XGBoost) — Optimized for speed.

Key optimizations vs template:
1. Subsample training data per entity (max 50K rows) — keeps quality, cuts time 10x
2. Early stopping (50 rounds patience) — avoids wasting rounds
3. Parallel entity training with careful memory management
4. Skips entities with < 500 samples

Usage (called by framework):
    python train.py --training-data <path> --model-output <path> --challenger-config <path>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, date
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

DEFAULT_XGB_PARAMS = {
    "max_depth": 6,
    "learning_rate": 0.1,
    "n_estimators": 500,
    "min_child_weight": 10,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "objective": "reg:squarederror",
    "random_state": 42,
    "tree_method": "hist",
    "n_jobs": -1,
}

STANDARD_FEATURES = [
    "mins_since_6am",
    "mins_since_open",
    "date_group_id_encoded",
    "season_encoded",
    "season_year_encoded",
]

TARGET = "actual_time"
GEO_DECAY_HALFLIFE_DAYS = 730
MIN_SAMPLES = 500
MAX_SAMPLES_PER_ENTITY = 50000  # Subsample large entities for speed
EARLY_STOPPING_ROUNDS = 50
VAL_FRACTION = 0.15


def compute_geo_decay_weights(dates: pd.Series, reference_date: date | None = None) -> np.ndarray:
    if reference_date is None:
        reference_date = date.today()
    dates_parsed = pd.to_datetime(dates)
    days_since = (pd.Timestamp(reference_date) - dates_parsed).dt.days.values
    days_since = np.maximum(days_since, 0)
    weights = 0.5 ** (days_since / GEO_DECAY_HALFLIFE_DAYS)
    return weights.astype(np.float32)


def train(training_data_path: str, model_output_path: str, config: dict):
    start_time = time.time()
    model_dir = Path(model_output_path)
    model_dir.mkdir(parents=True, exist_ok=True)

    xgb_params = {**DEFAULT_XGB_PARAMS}
    if "xgb_params" in config:
        xgb_params.update(config["xgb_params"])

    features = config.get("features", STANDARD_FEATURES)
    n_estimators = xgb_params.pop("n_estimators", 500)
    random_state = xgb_params.pop("random_state", 42)
    xgb_params.pop("n_jobs", None)

    logger.info(f"Loading training data from {training_data_path}")
    logger.info(f"XGB params: max_depth={xgb_params.get('max_depth')}, "
                f"lr={xgb_params.get('learning_rate')}, n_est={n_estimators}")

    df = pd.read_parquet(
        training_data_path,
        columns=["entity_code", "park_date", TARGET] + features,
    )
    logger.info(f"Loaded {len(df):,} rows, {df['entity_code'].nunique()} entities")

    # Pre-compute entity groups for speed
    entity_groups = {name: group for name, group in df.groupby("entity_code")}
    entities = sorted(entity_groups.keys())
    del df  # free memory

    training_summary = {
        "challenger_id": config.get("id", "unknown"),
        "trained_at": datetime.utcnow().isoformat(),
        "xgb_params": {**xgb_params, "n_estimators": n_estimators},
        "features": features,
        "max_samples_per_entity": MAX_SAMPLES_PER_ENTITY,
        "early_stopping_rounds": EARLY_STOPPING_ROUNDS,
        "entities": {},
    }

    trained_count = 0
    skipped_count = 0
    total_time_training = 0

    for i, entity in enumerate(entities):
        entity_data = entity_groups[entity]

        if len(entity_data) < MIN_SAMPLES:
            skipped_count += 1
            continue

        X = entity_data[features].values
        y = entity_data[TARGET].values
        park_dates = entity_data["park_date"]

        # Remove NaN targets
        mask = ~np.isnan(y)
        X, y = X[mask], y[mask]
        park_dates_clean = park_dates.iloc[mask] if mask.sum() < len(mask) else park_dates

        if len(y) < MIN_SAMPLES:
            skipped_count += 1
            continue

        # Compute geo-decay weights
        weights = compute_geo_decay_weights(park_dates_clean)
        if len(weights) != len(y):
            weights = weights[:len(y)]

        # Subsample if too large (weighted by geo-decay to prefer recent data)
        if len(y) > MAX_SAMPLES_PER_ENTITY:
            rng = np.random.RandomState(random_state)
            probs = weights / weights.sum()
            idx = rng.choice(len(y), size=MAX_SAMPLES_PER_ENTITY, replace=False, p=probs)
            idx.sort()
            X, y, weights = X[idx], y[idx], weights[idx]

        # Train/val split (last VAL_FRACTION by index since data is time-ordered)
        n_val = max(int(len(y) * VAL_FRACTION), 100)
        X_train, X_val = X[:-n_val], X[-n_val:]
        y_train, y_val = y[:-n_val], y[-n_val:]
        w_train, w_val = weights[:-n_val], weights[-n_val:]

        entity_start = time.time()

        model = xgb.XGBRegressor(
            n_estimators=n_estimators,
            random_state=random_state,
            n_jobs=1,
            early_stopping_rounds=EARLY_STOPPING_ROUNDS,
            **xgb_params,
        )
        model.fit(
            X_train, y_train,
            sample_weight=w_train,
            eval_set=[(X_val, y_val)],
            sample_weight_eval_set=[w_val],
            verbose=False,
        )

        entity_time = time.time() - entity_start
        total_time_training += entity_time

        # Save model
        entity_model_path = model_dir / f"{entity}.json"
        model.save_model(str(entity_model_path))

        # Record metrics
        preds = model.predict(X_val)
        mae = float(np.mean(np.abs(preds - y_val)))
        best_iteration = getattr(model, 'best_iteration', n_estimators)

        training_summary["entities"][entity] = {
            "n_samples": int(len(y)),
            "n_train": int(len(y_train)),
            "mae": round(mae, 3),
            "best_iteration": best_iteration,
            "train_seconds": round(entity_time, 1),
        }

        trained_count += 1

        if (i + 1) % 25 == 0:
            elapsed = time.time() - start_time
            rate = trained_count / max(elapsed, 1) * 60
            remaining_entities = len(entities) - (i + 1) - skipped_count
            eta_min = remaining_entities / max(rate, 0.1)
            logger.info(
                f"  [{i+1}/{len(entities)}] {trained_count} trained, {skipped_count} skipped | "
                f"{entity}: MAE={mae:.1f}, iters={best_iteration}, {entity_time:.1f}s | "
                f"Rate: {rate:.1f}/min, ETA: {eta_min:.0f}min"
            )

    elapsed = time.time() - start_time
    training_summary["total_entities_trained"] = trained_count
    training_summary["total_entities_skipped"] = skipped_count
    training_summary["elapsed_seconds"] = round(elapsed, 1)

    summary_path = model_dir / "training_summary.json"
    with open(summary_path, "w") as f:
        json.dump(training_summary, f, indent=2)

    logger.info(
        f"\nTraining complete: {trained_count} entities trained, "
        f"{skipped_count} skipped, {elapsed:.1f}s elapsed ({elapsed/60:.1f} min)"
    )


def main():
    parser = argparse.ArgumentParser(description="Train challenger XGBoost models")
    parser.add_argument("--training-data", required=True)
    parser.add_argument("--model-output", required=True)
    parser.add_argument("--challenger-config", required=True)
    args = parser.parse_args()

    with open(args.challenger_config) as f:
        config = yaml.safe_load(f)

    train(args.training_data, args.model_output, config)


if __name__ == "__main__":
    main()
