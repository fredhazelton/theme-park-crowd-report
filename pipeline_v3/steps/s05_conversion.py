"""Step 5: POSTED→ACTUAL Conversion Model v2 — 9 features, validated best MAE.

v1: Single feature (posted_wait). MAE 10.124. Weekly refresh.
v2: Nine features. MAE 9.952. Daily refresh. Shadow mode enabled.

Shadow test results (2026-03-10):
  9-feature MAE: 9.952  ← BEST (deployed)
  3-feature MAE: 10.319 ← worse than v1, rejected
  v1 MAE:        10.124

Feature importance (gain) from shadow test:
  log_posted_wait:     301,444  ← dominant
  posted_wait:         183,864
  months_since_epoch:   10,421
  hour_of_day:           6,781
  entity_encoded:        6,633
  scope_encoded:         6,524
  park_encoded:          6,076
  month_of_year:         2,969  ← weak but contributes
  day_of_week:           2,555  ← weak but contributes

Note: We tested a lean 3-feature model (Fred's separation-of-concerns
idea) but it produced higher MAE (10.319) than even v1. The entity and
temporal features, while individually weak, collectively contribute
enough to matter. The data spoke — 9 features wins.

Monitoring: check monthly for park-specific conversion drift. If one
park's entities cluster on the synthetic bias threshold, consider
per-park conversion models (architecture supports this via s06
per-park chunking).

Shadow mode: runs fully — trains to shadow dir, not skipped.
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
from pipeline_v3.core.db import read_connection
from pipeline_v3.core.logging import PipelineLogger
from pipeline_v3.core.paths import conversion_model_path, conversion_model_backup_path
from pipeline_v3.core.validation import ValidationError

TIME_EPOCH = date(2015, 1, 1)

FEATURE_COLS = [
    "posted_wait",
    "log_posted_wait",
    "hour_of_day",
    "day_of_week",
    "month_of_year",
    "months_since_epoch",
    "entity_encoded",
    "park_encoded",
    "scope_encoded",
]


def _get_model_dir(cfg: PipelineConfig) -> Path:
    if cfg.shadow and cfg.shadow_output_base:
        model_dir = cfg.shadow_output_base / "conversion_model"
    else:
        model_dir = cfg.output_base / "conversion_model"
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Train conversion model v2 (9 features) with validation gate."""

    log.info("=" * 60)
    log.info(f"STEP 5: CONVERSION MODEL v2 (9-feature) {'(SHADOW)' if cfg.shadow else ''}")
    log.info("=" * 60)

    if xgb is None:
        raise ValidationError("XGBoost required for conversion model")

    model_dir = _get_model_dir(cfg)
    model_path = model_dir / "conversion_model.json"
    prod_model_path = conversion_model_path(cfg)

    # Load matched pairs with context columns
    with log.timed("load training data"):
        parquet_str = str(cfg.parquet_dir).replace("\\", "/")
        dim_str = str(cfg.dimension_dir / "dimentity.csv").replace("\\", "/")
        with read_connection() as con:
            df = con.execute(f"""
                WITH posted AS (
                    SELECT entity_code, park_date,
                           EXTRACT(HOUR FROM observed_at_ts) as hour_bucket,
                           AVG(wait_time_minutes) as posted_wait
                    FROM read_parquet('{parquet_str}/*.parquet')
                    WHERE wait_time_type = 'POSTED' AND wait_time_minutes > 0
                      AND observed_at_ts IS NOT NULL
                    GROUP BY entity_code, park_date, hour_bucket
                ),
                actual AS (
                    SELECT entity_code, park_date,
                           EXTRACT(HOUR FROM observed_at_ts) as hour_bucket,
                           AVG(wait_time_minutes) as actual_wait
                    FROM read_parquet('{parquet_str}/*.parquet')
                    WHERE wait_time_type = 'ACTUAL' AND wait_time_minutes > 0
                      AND observed_at_ts IS NOT NULL
                    GROUP BY entity_code, park_date, hour_bucket
                )
                SELECT p.entity_code,
                       p.park_date,
                       p.hour_bucket,
                       p.posted_wait,
                       a.actual_wait,
                       d.scope_and_scale
                FROM posted p
                INNER JOIN actual a
                    ON p.entity_code = a.entity_code
                    AND p.park_date = a.park_date
                    AND p.hour_bucket = a.hour_bucket
                LEFT JOIN read_csv_auto('{dim_str}') d
                    ON p.entity_code = d.code
            """).fetchdf()

    if len(df) < 1000:
        log.warning(f"Only {len(df)} matched pairs — not enough")
        return {"rows": 0, "action": "insufficient_data"}

    log.info(f"Training data: {len(df):,} matched POSTED→ACTUAL pairs")
    log.info(f"Entities: {df['entity_code'].nunique()}")
    log.info(f"Date range: {df['park_date'].min()} to {df['park_date'].max()}")

    # Feature engineering
    with log.timed("feature engineering"):
        df, encoding_maps = _build_features(df, log)

    missing = [c for c in FEATURE_COLS if c not in df.columns]
    if missing:
        raise ValidationError(f"Feature engineering failed — missing: {missing}")

    log.info(f"Features ({len(FEATURE_COLS)}): {FEATURE_COLS}")

    # Time-based split
    df = df.sort_values("park_date")
    holdout_n = int(len(df) * cfg.conversion_holdout_fraction)
    train_df = df.iloc[:-holdout_n]
    holdout_df = df.iloc[-holdout_n:]

    log.info(f"Train: {len(train_df):,} | Holdout: {len(holdout_df):,}")
    log.info(f"Holdout dates: {holdout_df['park_date'].min()} to {holdout_df['park_date'].max()}")

    # Train
    with log.timed("train candidate model"):
        X_train = train_df[FEATURE_COLS].values.astype(np.float32)
        y_train = train_df["actual_wait"].values.astype(np.float32)
        X_hold = holdout_df[FEATURE_COLS].values.astype(np.float32)
        y_hold = holdout_df["actual_wait"].values.astype(np.float32)

        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_COLS)
        dhold = xgb.DMatrix(X_hold, label=y_hold, feature_names=FEATURE_COLS)

        params = {
            "max_depth": 8,
            "eta": 0.05,
            "min_child_weight": 5,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "objective": "reg:squarederror",
            "seed": 42,
            "verbosity": 0,
        }
        bst = xgb.train(
            params, dtrain,
            num_boost_round=1000,
            evals=[(dtrain, "train"), (dhold, "holdout")],
            early_stopping_rounds=30,
            verbose_eval=False,
        )

    candidate_pred = bst.predict(dhold)
    candidate_mae = float(np.mean(np.abs(y_hold - candidate_pred)))
    candidate_bias = float(np.mean(candidate_pred - y_hold))
    log.info(f"Candidate MAE: {candidate_mae:.3f} min | Bias: {candidate_bias:+.3f} min")

    importance = bst.get_score(importance_type="gain")
    log.info("Feature importance (gain):")
    for feat, score in sorted(importance.items(), key=lambda x: -x[1]):
        log.info(f"  {feat}: {score:.1f}")

    # Validation gate
    current_mae = None
    mae_improvement = 0.0

    if prod_model_path.exists():
        with log.timed("evaluate production model"):
            current_model = xgb.Booster()
            current_model.load_model(str(prod_model_path))
            try:
                current_pred = current_model.predict(dhold)
                current_mae = float(np.mean(np.abs(y_hold - current_pred)))
            except Exception:
                log.info("Production model is v1 (single feature)")
                dhold_v1 = xgb.DMatrix(
                    holdout_df[["posted_wait"]].values.astype(np.float32),
                    label=y_hold,
                )
                current_pred = current_model.predict(dhold_v1)
                current_mae = float(np.mean(np.abs(y_hold - current_pred)))
            log.info(f"Production model MAE: {current_mae:.3f} min")

        mae_improvement = current_mae - candidate_mae
        mae_regression = candidate_mae - current_mae

        if mae_regression > cfg.conversion_max_mae_regression:
            log.warning(f"GATE REJECTED: candidate {mae_regression:.3f} min worse.")
            return {"rows": 0, "action": "gate_rejected",
                    "candidate_mae": candidate_mae, "current_mae": current_mae}

        log.info(f"Candidate is {mae_improvement:.3f} min BETTER than production.")
        if not cfg.shadow:
            backup = conversion_model_backup_path(cfg)
            backup.parent.mkdir(parents=True, exist_ok=True)
            prod_model_path.rename(backup)
    else:
        log.info("No existing production model — deploying directly")

    bst.save_model(str(model_path))
    log.info(f"Model saved to {model_path}")

    encoding_path = model_dir / "conversion_encodings.json"
    with open(encoding_path, "w") as f:
        json.dump(encoding_maps, f, indent=2)
    log.info(f"Encoding maps saved ({len(encoding_maps['entity_map'])} entities, "
             f"{len(encoding_maps['park_map'])} parks, {len(encoding_maps['scope_map'])} scopes)")

    metadata = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_train": len(train_df),
        "n_holdout": len(holdout_df),
        "n_entities": int(df["entity_code"].nunique()),
        "date_range": [str(df["park_date"].min()), str(df["park_date"].max())],
        "mae_holdout": round(candidate_mae, 3),
        "bias_holdout": round(candidate_bias, 3),
        "mae_improvement": round(mae_improvement, 3) if current_mae else None,
        "previous_mae": round(current_mae, 3) if current_mae else None,
        "features": FEATURE_COLS,
        "feature_importance": {k: round(v, 1) for k, v in importance.items()},
        "params": params,
        "best_iteration": bst.best_iteration,
        "shadow_mode": cfg.shadow,
        "version": "v2",
    }
    meta_path = model_dir / "metadata_v3.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    log.info(f"Conversion model v2 deployed: MAE {candidate_mae:.3f} min")
    if current_mae:
        pct = mae_improvement / current_mae * 100
        log.info(f"Improvement: {mae_improvement:.3f} min ({pct:.1f}%)")

    return {"rows": len(train_df), "action": "deployed",
            "mae": round(candidate_mae, 3),
            "improvement": round(mae_improvement, 3) if current_mae else None}


def _build_features(df: pd.DataFrame, log: PipelineLogger) -> tuple[pd.DataFrame, dict]:
    df["park_date_dt"] = pd.to_datetime(df["park_date"])
    df["log_posted_wait"] = np.log1p(df["posted_wait"]).astype(np.float32)
    df["hour_of_day"] = df["hour_bucket"].astype(np.float32)
    df["day_of_week"] = df["park_date_dt"].dt.dayofweek.astype(np.float32)
    df["month_of_year"] = df["park_date_dt"].dt.month.astype(np.float32)
    df["months_since_epoch"] = (
        (df["park_date_dt"].dt.year - TIME_EPOCH.year) * 12
        + (df["park_date_dt"].dt.month - TIME_EPOCH.month)
    ).astype(np.float32)

    df["park_code"] = df["entity_code"].str.extract(r'^([A-Z]{2,3})')[0]
    park_codes = sorted(df["park_code"].dropna().unique())
    park_map = {p: i for i, p in enumerate(park_codes)}
    df["park_encoded"] = df["park_code"].map(park_map).fillna(-1).astype(np.float32)
    log.info(f"Parks: {len(park_map)}")

    entity_freq = df["entity_code"].value_counts()
    entity_map = {e: i for i, e in enumerate(entity_freq.index)}
    df["entity_encoded"] = df["entity_code"].map(entity_map).astype(np.float32)
    log.info(f"Entities: {len(entity_map)}")

    scope_values = sorted(df["scope_and_scale"].dropna().unique())
    scope_map = {s: i for i, s in enumerate(scope_values)}
    df["scope_encoded"] = df["scope_and_scale"].map(scope_map).fillna(-1).astype(np.float32)
    log.info(f"Scope categories: {scope_map}")

    encoding_maps = {
        "park_map": park_map,
        "entity_map": {e: int(i) for e, i in entity_map.items()},
        "scope_map": scope_map,
        "time_epoch": TIME_EPOCH.isoformat(),
        "feature_cols": FEATURE_COLS,
    }
    return df, encoding_maps
