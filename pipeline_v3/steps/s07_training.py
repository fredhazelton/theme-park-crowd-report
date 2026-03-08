"""Step 7: Model Training — Python XGBoost, per-park chunking.

Replaces the Julia training pipeline with pure Python.
Same XGBoost algorithm (libxgboost), same hyperparameters,
but with explicit memory management and validation.

v3.1 fix: added .fillna() guards for NAType errors on UH entities.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import xgboost as xgb
except ImportError:
    xgb = None

from pipeline_v3.config import PipelineConfig
from pipeline_v3.core.logging import PipelineLogger
from pipeline_v3.core.park_codes import entity_to_park
from pipeline_v3.core.validation import ValidationError

# Feature columns (actuals-first, no posted_time)
FEATURE_COLS = [
    "mins_since_6am", "mins_since_open",
    "date_group_id_encoded", "season_encoded", "season_year_encoded",
]
FEATURE_COLS_LITE = ["mins_since_6am", "mins_since_open"]


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Train per-entity XGBoost models, one park at a time."""

    if xgb is None:
        raise ValidationError("XGBoost is required. pip install xgboost")

    log.info("=" * 60)
    log.info("STEP 7: MODEL TRAINING (v3.1 — Python XGBoost, per-park)")
    log.info("=" * 60)

    # Look for per-park training data (preferred) or single file
    actuals_dir = cfg.output_base / "matched_pairs" / "actuals_training_v2"
    actuals_single = cfg.output_base / "matched_pairs" / "actuals_training_v2.parquet"

    park_files = sorted(actuals_dir.glob("*.parquet")) if actuals_dir.is_dir() else []
    use_park_chunks = len(park_files) > 0

    if not use_park_chunks and not actuals_single.exists():
        raise ValidationError(
            f"No training data found at {actuals_dir} or {actuals_single}. "
            f"Run build_actuals_training_data.py first."
        )

    log.info(f"Training data: {'per-park chunks' if use_park_chunks else 'single file'}")
    log.info(f"Min observations: {cfg.training_min_obs} (full), {cfg.training_min_obs_lite} (lite)")

    # Scan entity counts
    with log.timed("scan entity counts"):
        entity_counts = _scan_entity_counts(park_files if use_park_chunks else [actuals_single])

    eligible_full = [e for e, c in entity_counts.items() if c >= cfg.training_min_obs]
    eligible_lite = [e for e, c in entity_counts.items() if cfg.training_min_obs_lite <= c < cfg.training_min_obs]

    log.info(f"Eligible: {len(eligible_full)} full, {len(eligible_lite)} lite")

    # Group by park
    park_entity_map: dict[str, list[str]] = {}
    for e in eligible_full + eligible_lite:
        park = entity_to_park(e)
        park_entity_map.setdefault(park, []).append(e)

    # Train
    successful = 0
    failed = 0
    total_mae = 0.0
    eligible_full_set = set(eligible_full)

    for park_code in sorted(park_entity_map.keys()):
        park_entities = park_entity_map[park_code]

        with log.timed(f"train park {park_code} ({len(park_entities)} entities)"):
            # Load park data
            if use_park_chunks:
                park_file = actuals_dir / f"{park_code}.parquet"
                if not park_file.exists():
                    log.warning(f"  No training data for park {park_code}")
                    continue
                park_df = pd.read_parquet(park_file)
            else:
                park_df = pd.read_parquet(actuals_single)
                park_df = park_df[park_df["entity_code"].isin(park_entities)]

            for entity_code in park_entities:
                try:
                    is_full = entity_code in eligible_full_set
                    features = FEATURE_COLS if is_full else FEATURE_COLS_LITE
                    min_obs = 100 if is_full else 50

                    result = _train_entity(
                        entity_code, park_df, cfg.models_dir, features,
                        min_obs, cfg, is_lite=not is_full,
                    )
                    if result is not None:
                        successful += 1
                        total_mae += result["mae"]
                    else:
                        failed += 1
                except Exception as e:
                    log.warning(f"  {entity_code}: {e}")
                    failed += 1

            del park_df  # Release memory

    avg_mae = total_mae / successful if successful > 0 else 0

    log.info("=" * 60)
    log.info("TRAINING COMPLETE")
    log.info(f"Successful: {successful}, Failed: {failed}")
    log.info(f"Average MAE: {avg_mae:.2f} min")
    log.metric("training_successful", successful)
    log.metric("training_failed", failed)
    log.metric("training_avg_mae", round(avg_mae, 2))
    log.info("=" * 60)

    return {"rows": successful, "successful": successful, "failed": failed, "avg_mae": round(avg_mae, 2)}


def _train_entity(
    entity_code: str,
    park_df: pd.DataFrame,
    models_dir: Path,
    feature_cols: list[str],
    min_samples: int,
    cfg: PipelineConfig,
    is_lite: bool = False,
) -> dict | None:
    """Train XGBoost model for a single entity. Returns {mae, n_samples} or None."""

    entity_df = park_df[park_df["entity_code"] == entity_code].copy()
    if len(entity_df) < min_samples:
        return None

    # v3.1: Fill NaN/NAType in feature columns and target BEFORE converting to numpy
    for col in feature_cols:
        if col in entity_df.columns:
            entity_df[col] = pd.to_numeric(entity_df[col], errors="coerce").fillna(0)
    entity_df["actual_time"] = pd.to_numeric(entity_df["actual_time"], errors="coerce")

    # Build feature matrix
    X = entity_df[feature_cols].values.astype(np.float32)
    y = entity_df["actual_time"].values.astype(np.float32)

    # Geo-decay weighting
    today = date.today()
    park_dates = pd.to_datetime(entity_df["park_date"]).dt.date
    days_old = np.array([(today - d).days for d in park_dates], dtype=np.float32)
    weights = np.float32(0.5) ** (days_old / cfg.geo_decay_halflife_days)

    # Inverse frequency weighting for synthetic data
    if "is_synthetic" in entity_df.columns:
        is_synth = entity_df["is_synthetic"].values.astype(bool)
        n_real = int(np.sum(~is_synth))
        synth_mult = np.float32(1.0 / np.log2(n_real + 1)) if n_real > 0 else np.float32(1.0)
        weights = weights * np.where(is_synth, synth_mult, np.float32(1.0))

    # Filter valid rows (no NaN in target or weights, target > 0)
    valid = ~np.isnan(y) & (y > 0) & ~np.isnan(weights)
    # Also filter NaN in features
    valid = valid & ~np.any(np.isnan(X), axis=1)
    X, y, weights = X[valid], y[valid], weights[valid]

    if len(y) < min_samples:
        return None

    # Train/val split (85/15)
    n = len(y)
    split = int(n * 0.85)
    X_train, y_train, w_train = X[:split], y[:split], weights[:split]
    X_val, y_val = X[split:], y[split:]

    # Train
    dtrain = xgb.DMatrix(X_train, label=y_train, weight=w_train)
    dval = xgb.DMatrix(X_val, label=y_val)

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

    # Evaluate
    y_pred = bst.predict(dval)
    mae = float(np.mean(np.abs(y_val - y_pred)))

    # Save model
    model_dir = models_dir / entity_code
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "model_v3.json"
    bst.save_model(str(model_path))

    # Save metadata
    metadata = {
        "model_label": "PIPELINE_V3" if not is_lite else "PIPELINE_V3_LITE",
        "entity_code": entity_code,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": split,
        "n_val": n - split,
        "mae": round(mae, 3),
        "features": feature_cols,
        "uses_geo_decay_weights": True,
        "geo_decay_halflife_days": cfg.geo_decay_halflife_days,
        "hyperparameters": params,
        "backend": "Python xgboost",
        "version": "v3.1",
    }
    meta_path = model_dir / "metadata_v3.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    return {"mae": mae, "n_samples": split}


def _scan_entity_counts(parquet_files: list[Path]) -> dict[str, int]:
    """Count observations per entity across parquet files."""
    counts: dict[str, int] = {}
    for path in parquet_files:
        if not path.exists():
            continue
        df = pd.read_parquet(path, columns=["entity_code"])
        for entity, count in df["entity_code"].value_counts().items():
            counts[entity] = counts.get(entity, 0) + count
    return counts
