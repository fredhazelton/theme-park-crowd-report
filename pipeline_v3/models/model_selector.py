"""Multi-candidate model selection per entity.

Pillar 2 of v4 accuracy improvements.

For each entity, trains multiple model candidates with different feature sets
and picks the one with lowest holdout MAE. This fixes the UH regression where
v3's actuals-first model was 3-7x worse than Julia's v2-style model.

Candidates:
1. actuals_first: 5 features (mins_since_6am, mins_since_open, date_group_id_encoded,
   season_encoded, season_year_encoded) — current v3 default
2. full_feature: 7 features (adds posted_time, hour_of_day) — v2 style
3. lite: 2 features (mins_since_6am, mins_since_open) — low-data fallback

Note: calendar_aware candidate (school calendar features) is planned as a
separate experiment (Issue #8) after v4's three pillars are validated.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import xgboost as xgb
except ImportError:
    xgb = None

from pipeline_v3.config import PipelineConfig

# Candidate feature sets
CANDIDATES = {
    "actuals_first": [
        "mins_since_6am", "mins_since_open",
        "date_group_id_encoded", "season_encoded", "season_year_encoded",
    ],
    "full_feature": [
        "posted_time", "mins_since_6am", "mins_since_open",
        "hour_of_day", "date_group_id_encoded", "season_encoded",
        "season_year_encoded",
    ],
    "lite": [
        "mins_since_6am", "mins_since_open",
    ],
}


def train_best_model(
    entity_code: str,
    entity_df: pd.DataFrame,
    models_dir: Path,
    cfg: PipelineConfig,
    min_samples: int = 100,
) -> dict | None:
    """Train multiple candidates and deploy the best one.

    Returns {mae, n_samples, method} or None if all fail.
    """

    if len(entity_df) < min_samples:
        return None

    # Clean data once
    entity_df = entity_df.copy()
    for col in ["mins_since_6am", "mins_since_open", "date_group_id_encoded",
                "season_encoded", "season_year_encoded", "posted_time", "hour_of_day"]:
        if col in entity_df.columns:
            entity_df[col] = pd.to_numeric(entity_df[col], errors="coerce").fillna(0)
    entity_df["actual_time"] = pd.to_numeric(entity_df["actual_time"], errors="coerce")

    y_all = entity_df["actual_time"].values.astype(np.float32)
    valid_mask = ~np.isnan(y_all) & (y_all > 0)

    if valid_mask.sum() < min_samples:
        return None

    # Geo-decay weights
    today = date.today()
    park_dates = pd.to_datetime(entity_df["park_date"]).dt.date
    days_old = np.array([(today - d).days for d in park_dates], dtype=np.float32)
    weights = np.float32(0.5) ** (days_old / cfg.geo_decay_halflife_days)

    # Synthetic weighting
    if "is_synthetic" in entity_df.columns:
        is_synth = entity_df["is_synthetic"].values.astype(bool)
        n_real = int(np.sum(~is_synth))
        synth_mult = np.float32(1.0 / np.log2(n_real + 1)) if n_real > 0 else np.float32(1.0)
        weights = weights * np.where(is_synth, synth_mult, np.float32(1.0))

    valid_mask = valid_mask & ~np.isnan(weights)

    # Train/val split
    n_valid = valid_mask.sum()
    split = int(n_valid * 0.85)
    valid_indices = np.where(valid_mask)[0]
    train_idx = valid_indices[:split]
    val_idx = valid_indices[split:]

    if len(val_idx) < 10:
        return None

    y_val = y_all[val_idx]

    # Train each candidate
    best_mae = float("inf")
    best_method = None
    best_model = None
    best_features = None

    for method_name, feature_cols in CANDIDATES.items():
        # Check all features exist
        missing = [c for c in feature_cols if c not in entity_df.columns]
        if missing:
            continue

        X_all = entity_df[feature_cols].values.astype(np.float32)

        # Check for NaN in features
        feat_valid = ~np.any(np.isnan(X_all), axis=1)
        combined_valid = valid_mask & feat_valid
        combined_indices = np.where(combined_valid)[0]

        c_split = int(len(combined_indices) * 0.85)
        c_train = combined_indices[:c_split]
        c_val = combined_indices[c_split:]

        if len(c_train) < min_samples or len(c_val) < 10:
            continue

        X_train = X_all[c_train]
        y_train = y_all[c_train]
        w_train = weights[c_train]
        X_val_c = X_all[c_val]
        y_val_c = y_all[c_val]

        try:
            dtrain = xgb.DMatrix(X_train, label=y_train, weight=w_train)
            dval = xgb.DMatrix(X_val_c, label=y_val_c)

            is_lite = method_name == "lite"
            params = {
                "max_depth": 6 if is_lite else cfg.training_max_depth,
                "eta": cfg.training_eta,
                "min_child_weight": 3 if is_lite else 1,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "objective": "reg:squarederror",
                "seed": 42,
                "verbosity": 0,
            }

            bst = xgb.train(
                params, dtrain,
                num_boost_round=cfg.training_rounds,
                evals=[(dtrain, "train"), (dval, "eval")],
                early_stopping_rounds=cfg.training_early_stopping,
                verbose_eval=False,
            )

            pred = bst.predict(dval)
            mae = float(np.mean(np.abs(y_val_c - pred)))

            if mae < best_mae:
                best_mae = mae
                best_method = method_name
                best_model = bst
                best_features = feature_cols

        except Exception:
            continue

    if best_model is None:
        return None

    # Save best model
    model_dir = models_dir / entity_code
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "model_v3.json"
    best_model.save_model(str(model_path))

    metadata = {
        "model_label": f"PIPELINE_V4_{best_method.upper()}",
        "entity_code": entity_code,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": split,
        "n_val": n_valid - split,
        "mae": round(best_mae, 3),
        "features": best_features,
        "model_selection_method": best_method,
        "candidates_evaluated": list(CANDIDATES.keys()),
        "uses_geo_decay_weights": True,
        "geo_decay_halflife_days": cfg.geo_decay_halflife_days,
        "backend": "Python xgboost",
        "version": "v4",
    }
    meta_path = model_dir / "metadata_v3.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    return {"mae": best_mae, "n_samples": split, "method": best_method}
