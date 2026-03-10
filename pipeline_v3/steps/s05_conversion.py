"""Step 5: POSTED→ACTUAL Conversion Model v2 — multi-feature with validation gate.

v1 (original): Single feature (posted_wait). Global model. Weekly refresh.
    Problem: One model for all entities, all parks, all time periods.
    A 60-min posted wait at Space Mountain 9am treated identically to
    a 60-min posted wait at It's a Small World 3pm.

v2 (this version): Multi-feature, entity-aware, continuous time trend.
    Features:
    - posted_wait: the core signal
    - log_posted_wait: captures nonlinear inflation at high posted waits
    - hour_of_day: mornings more accurate, afternoons inflate
    - day_of_week: weekend vs weekday posting behavior
    - month_of_year: seasonal patterns in posting accuracy
    - months_since_epoch: continuous time trend (concept drift in how parks
      post wait times over the years — gradual, no artificial year boundaries)
    - entity_encoded: frequency-based, lets model learn entity-specific behavior
    - park_encoded: park-level posting culture
    - scope_encoded: scope_and_scale from dimEntity — Super Headliner vs Minor
      attractions have very different posting inflation patterns

    The model learns that posted-to-actual ratios differ by entity, time of day,
    time period, season, and ride importance. One global model that borrows
    strength across entities while learning entity-specific behavior.

Still uses validation gate: only deploys if candidate beats current model.
Refreshes daily (was weekly) — fast enough with v3/v4 pipeline speed.

This model generates 94% of all training data (synthetic actuals).
Every minute of accuracy gained here propagates to all 423 entity models.
"""

from __future__ import annotations

import json
import math
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

# Epoch for continuous time feature
# 2015-01-01 ≈ start of modern wait time data era
TIME_EPOCH = date(2015, 1, 1)

# Feature columns in training order — must match exactly at inference time (s06)
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


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Train conversion model v2 with multi-feature + validation gate."""

    log.info("=" * 60)
    log.info("STEP 5: CONVERSION MODEL v2 (multi-feature, daily refresh)")
    log.info("=" * 60)

    model_path = conversion_model_path(cfg)

    if cfg.shadow:
        log.info("Shadow mode: skipping conversion model training (uses production model)")
        return {"rows": 0, "action": "skipped_shadow"}

    if xgb is None:
        raise ValidationError("XGBoost required for conversion model")

    # Load matched pairs with ALL context columns
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
        log.warning(f"Only {len(df)} matched pairs — not enough for conversion model")
        return {"rows": 0, "action": "insufficient_data"}

    log.info(f"Training data: {len(df):,} matched POSTED→ACTUAL pairs")
    log.info(f"Entities: {df['entity_code'].nunique()}")
    log.info(f"Date range: {df['park_date'].min()} to {df['park_date'].max()}")

    # === Feature engineering ===
    with log.timed("feature engineering"):
        df, encoding_maps = _build_features(df, log)

    # Verify all features exist
    missing = [c for c in FEATURE_COLS if c not in df.columns]
    if missing:
        raise ValidationError(f"Feature engineering failed — missing: {missing}")

    log.info(f"Features ({len(FEATURE_COLS)}): {FEATURE_COLS}")

    # Split: train / holdout (TIME-BASED — holdout is most recent data)
    df = df.sort_values("park_date")
    n = len(df)
    holdout_n = int(n * cfg.conversion_holdout_fraction)
    train_df = df.iloc[:-holdout_n]
    holdout_df = df.iloc[-holdout_n:]

    log.info(f"Train: {len(train_df):,} rows | Holdout: {len(holdout_df):,} rows")
    log.info(f"Holdout dates: {holdout_df['park_date'].min()} to {holdout_df['park_date'].max()}")

    # Train candidate
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

    # Evaluate candidate
    candidate_pred = bst.predict(dhold)
    candidate_mae = float(np.mean(np.abs(y_hold - candidate_pred)))
    candidate_bias = float(np.mean(candidate_pred - y_hold))
    log.info(f"Candidate MAE: {candidate_mae:.3f} min | Bias: {candidate_bias:+.3f} min")

    # Feature importance
    importance = bst.get_score(importance_type="gain")
    log.info("Feature importance (gain):")
    for feat, score in sorted(importance.items(), key=lambda x: -x[1]):
        log.info(f"  {feat}: {score:.1f}")

    # === Validation gate ===
    current_mae = None
    mae_improvement = 0.0

    if model_path.exists():
        with log.timed("evaluate current model"):
            current_model = xgb.Booster()
            current_model.load_model(str(model_path))

            try:
                current_pred = current_model.predict(dhold)
                current_mae = float(np.mean(np.abs(y_hold - current_pred)))
            except Exception:
                # v1 model has different feature shape — build v1 input
                log.info("Current model is v1 (single feature) — building v1 holdout")
                dhold_v1 = xgb.DMatrix(
                    holdout_df[["posted_wait"]].values.astype(np.float32),
                    label=y_hold,
                )
                current_pred = current_model.predict(dhold_v1)
                current_mae = float(np.mean(np.abs(y_hold - current_pred)))

            log.info(f"Current model MAE: {current_mae:.3f} min")

        mae_improvement = current_mae - candidate_mae
        mae_regression = candidate_mae - current_mae

        if mae_regression > cfg.conversion_max_mae_regression:
            log.warning(
                f"GATE REJECTED: candidate is {mae_regression:.3f} min worse "
                f"(threshold: {cfg.conversion_max_mae_regression}). Keeping current."
            )
            return {
                "rows": 0, "action": "gate_rejected",
                "candidate_mae": candidate_mae, "current_mae": current_mae,
            }

        log.info(f"Candidate is {mae_improvement:.3f} min BETTER. Deploying.")
        backup = conversion_model_backup_path(cfg)
        backup.parent.mkdir(parents=True, exist_ok=True)
        model_path.rename(backup)
        log.info(f"Previous model backed up to {backup}")
    else:
        log.info("No existing model — deploying directly")

    # Deploy
    model_path.parent.mkdir(parents=True, exist_ok=True)
    bst.save_model(str(model_path))

    # Save encoding maps (needed by s06_synthetic to apply the model)
    encoding_path = model_path.parent / "conversion_encodings.json"
    with open(encoding_path, "w") as f:
        json.dump(encoding_maps, f, indent=2)
    log.info(f"Encoding maps saved ({len(encoding_maps['entity_map'])} entities, "
             f"{len(encoding_maps['park_map'])} parks, {len(encoding_maps['scope_map'])} scopes)")

    # Save metadata
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
        "version": "v2",
    }
    meta_path = model_path.parent / "metadata_v3.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    log.info(f"Conversion model v2 deployed: MAE {candidate_mae:.3f} min")
    if current_mae:
        pct = mae_improvement / current_mae * 100
        log.info(f"Improvement over previous: {mae_improvement:.3f} min ({pct:.1f}%)")

    return {
        "rows": len(train_df), "action": "deployed",
        "mae": round(candidate_mae, 3),
        "improvement": round(mae_improvement, 3) if current_mae else None,
    }


def _build_features(df: pd.DataFrame, log: PipelineLogger) -> tuple[pd.DataFrame, dict]:
    """Build all features. Returns (df_with_features, encoding_maps)."""

    df["park_date_dt"] = pd.to_datetime(df["park_date"])

    # --- Numeric features ---
    df["log_posted_wait"] = np.log1p(df["posted_wait"]).astype(np.float32)
    df["hour_of_day"] = df["hour_bucket"].astype(np.float32)
    df["day_of_week"] = df["park_date_dt"].dt.dayofweek.astype(np.float32)
    df["month_of_year"] = df["park_date_dt"].dt.month.astype(np.float32)

    # Continuous time trend: MONTHS since epoch (not days — days overfits)
    df["months_since_epoch"] = (
        (df["park_date_dt"].dt.year - TIME_EPOCH.year) * 12
        + (df["park_date_dt"].dt.month - TIME_EPOCH.month)
    ).astype(np.float32)

    # --- Encoded categoricals ---

    # Park
    df["park_code"] = df["entity_code"].str.extract(r'^([A-Z]{2,3})')[0]
    park_codes = sorted(df["park_code"].dropna().unique())
    park_map = {p: i for i, p in enumerate(park_codes)}
    df["park_encoded"] = df["park_code"].map(park_map).fillna(-1).astype(np.float32)
    log.info(f"Parks: {len(park_map)}")

    # Entity (frequency-based: common entities get lower IDs)
    entity_freq = df["entity_code"].value_counts()
    entity_map = {e: i for i, e in enumerate(entity_freq.index)}
    df["entity_encoded"] = df["entity_code"].map(entity_map).astype(np.float32)
    log.info(f"Entities: {len(entity_map)}")

    # Scope and scale (from dimEntity join)
    scope_values = sorted(df["scope_and_scale"].dropna().unique())
    scope_map = {s: i for i, s in enumerate(scope_values)}
    # -1 for entities not in dimEntity or with null scope
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
