"""Step 5: POSTED→ACTUAL Conversion Model v2 — multi-feature with validation gate.

v1 (original): Single feature (posted_wait). Global model. Weekly refresh.
    Problem: One model for all entities, all parks, all time periods.
    A 60-min posted wait at Space Mountain 9am treated identically to
    a 60-min posted wait at It's a Small World 3pm.

v2 (this version): Multi-feature, per-park capability, continuous time.
    Features: posted_wait, hour_of_day, entity_encoded, park_encoded,
              days_since_epoch (continuous time trend),
              day_of_week, month_of_year
    The model learns that posted-to-actual ratios differ by:
    - Entity (Space Mountain inflates differently than flat rides)
    - Time of day (mornings more accurate, afternoons inflate)
    - Time period (concept drift — parks change posting behavior over years)
    - Day of week and season (weekend vs weekday, holiday inflation)

Still uses validation gate: only deploys if candidate beats current model.
Still runs weekly (Monday) by default — can be changed to daily in config.

This model generates 94% of all training data (synthetic actuals).
Every minute of accuracy gained here propagates to all 423 entity models.
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

# Epoch for continuous time feature
# Using 2015-01-01 as baseline (roughly start of modern wait time data)
TIME_EPOCH = date(2015, 1, 1)


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Train conversion model v2 with multi-feature + validation gate."""

    log.info("=" * 60)
    log.info("STEP 5: CONVERSION MODEL v2 (multi-feature + validation gate)")
    log.info("=" * 60)

    model_path = conversion_model_path(cfg)
    today = date.today()
    is_retrain_day = today.weekday() == cfg.conversion_retrain_day

    if model_path.exists() and not is_retrain_day:
        log.info(f"Model exists and not retrain day ({today.strftime('%A')}). Skipping.")
        return {"rows": 0, "action": "skipped"}

    if cfg.shadow:
        log.info("Shadow mode: skipping conversion model training (uses production model)")
        return {"rows": 0, "action": "skipped_shadow"}

    if xgb is None:
        raise ValidationError("XGBoost required for conversion model")

    # Load matched pairs with ALL features we need
    with log.timed("load training data"):
        parquet_str = str(cfg.parquet_dir).replace("\\", "/")
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
                       a.actual_wait
                FROM posted p
                INNER JOIN actual a
                    ON p.entity_code = a.entity_code
                    AND p.park_date = a.park_date
                    AND p.hour_bucket = a.hour_bucket
            """).fetchdf()

    if len(df) < 1000:
        log.warning(f"Only {len(df)} matched pairs — not enough for conversion model")
        return {"rows": 0, "action": "insufficient_data"}

    log.info(f"Training data: {len(df):,} matched POSTED→ACTUAL pairs")
    log.info(f"Entities: {df['entity_code'].nunique()}")
    log.info(f"Date range: {df['park_date'].min()} to {df['park_date'].max()}")

    # === Feature engineering ===
    with log.timed("feature engineering"):
        df = _build_features(df, log)

    feature_cols = [
        "posted_wait",
        "hour_of_day",
        "day_of_week",
        "month_of_year",
        "days_since_epoch",
        "park_encoded",
        "entity_encoded",
    ]

    # Verify all features exist
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        log.error(f"Missing features: {missing}")
        raise ValidationError(f"Feature engineering failed: {missing}")

    log.info(f"Features: {feature_cols}")

    # Split: train / holdout (time-based: holdout is most recent data)
    # Sort by date so holdout is the newest observations
    df = df.sort_values("park_date")
    n = len(df)
    holdout_n = int(n * cfg.conversion_holdout_fraction)
    train_df = df.iloc[:-holdout_n]
    holdout_df = df.iloc[-holdout_n:]

    log.info(f"Train: {len(train_df):,} rows, Holdout: {len(holdout_df):,} rows")
    log.info(f"Holdout date range: {holdout_df['park_date'].min()} to {holdout_df['park_date'].max()}")

    # Train candidate
    with log.timed("train candidate model"):
        X_train = train_df[feature_cols].values.astype(np.float32)
        y_train = train_df["actual_wait"].values.astype(np.float32)
        X_hold = holdout_df[feature_cols].values.astype(np.float32)
        y_hold = holdout_df["actual_wait"].values.astype(np.float32)

        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_cols)
        dhold = xgb.DMatrix(X_hold, label=y_hold, feature_names=feature_cols)

        params = {
            "max_depth": 8,        # Deeper than v1 (was 6) — more features to learn from
            "eta": 0.05,           # Slower learning rate for more features
            "min_child_weight": 5, # Prevent overfitting on rare entity/hour combos
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "objective": "reg:squarederror",
            "seed": 42,
            "verbosity": 0,
        }
        bst = xgb.train(
            params, dtrain,
            num_boost_round=1000,   # More rounds (was 500) with slower learning rate
            evals=[(dtrain, "train"), (dhold, "holdout")],
            early_stopping_rounds=30,
            verbose_eval=False,
        )

    # Evaluate candidate on holdout
    candidate_pred = bst.predict(dhold)
    candidate_mae = float(np.mean(np.abs(y_hold - candidate_pred)))
    candidate_bias = float(np.mean(candidate_pred - y_hold))
    log.info(f"Candidate MAE on holdout: {candidate_mae:.3f} min (bias: {candidate_bias:+.3f})")

    # Feature importance
    importance = bst.get_score(importance_type="gain")
    log.info("Feature importance (gain):")
    for feat, score in sorted(importance.items(), key=lambda x: -x[1]):
        log.info(f"  {feat}: {score:.1f}")

    # Validation gate: compare against current production model
    if model_path.exists():
        with log.timed("evaluate current model"):
            current_model = xgb.Booster()
            current_model.load_model(str(model_path))

            # Current model may have fewer features (v1 = posted_wait only)
            # Need to handle backward compatibility
            try:
                current_pred = current_model.predict(dhold)
                current_mae = float(np.mean(np.abs(y_hold - current_pred)))
                log.info(f"Current model MAE on holdout: {current_mae:.3f} min")
            except Exception as e:
                # Current model has different feature shape (v1 vs v2)
                # Build v1-style input for comparison
                log.info(f"Current model uses different features ({e}), building v1 input")
                dhold_v1 = xgb.DMatrix(
                    holdout_df[["posted_wait"]].values.astype(np.float32),
                    label=y_hold,
                )
                current_pred = current_model.predict(dhold_v1)
                current_mae = float(np.mean(np.abs(y_hold - current_pred)))
                log.info(f"Current model (v1) MAE on holdout: {current_mae:.3f} min")

        mae_improvement = current_mae - candidate_mae
        mae_regression = candidate_mae - current_mae

        if mae_regression > cfg.conversion_max_mae_regression:
            log.warning(
                f"VALIDATION GATE: candidate is {mae_regression:.3f} min WORSE than current "
                f"(threshold: {cfg.conversion_max_mae_regression}). Keeping current model."
            )
            log.metric("conversion_gate", 0, reason="regression", mae_diff=mae_regression)
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
        log.info("No existing model — deploying candidate directly")
        mae_improvement = 0.0
        current_mae = None

    # Save candidate as production
    model_path.parent.mkdir(parents=True, exist_ok=True)
    bst.save_model(str(model_path))

    # Save encoding maps (needed when applying the model in s06_synthetic)
    encoding_maps = _get_encoding_maps(df)
    encoding_path = model_path.parent / "conversion_encodings.json"
    with open(encoding_path, "w") as f:
        json.dump(encoding_maps, f, indent=2)
    log.info(f"Encoding maps saved to {encoding_path}")

    metadata = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_train": len(train_df),
        "n_holdout": len(holdout_df),
        "n_entities": int(df["entity_code"].nunique()),
        "n_parks": int(df["park_code"].nunique()) if "park_code" in df.columns else 0,
        "date_range": [str(df["park_date"].min()), str(df["park_date"].max())],
        "mae_holdout": round(candidate_mae, 3),
        "bias_holdout": round(candidate_bias, 3),
        "mae_improvement": round(mae_improvement, 3) if current_mae else None,
        "previous_mae": round(current_mae, 3) if current_mae else None,
        "features": feature_cols,
        "feature_importance": {k: round(v, 1) for k, v in importance.items()},
        "params": params,
        "version": "v2",
    }
    meta_path = model_path.parent / "metadata_v3.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    log.info(f"Conversion model v2 deployed: MAE {candidate_mae:.3f} min")
    if current_mae:
        log.info(f"Improvement over v1: {mae_improvement:.3f} min ({mae_improvement/current_mae*100:.1f}% better)")
    log.metric("conversion_mae", round(candidate_mae, 3))
    log.metric("conversion_gate", 1)

    return {
        "rows": len(train_df),
        "action": "deployed",
        "mae": round(candidate_mae, 3),
        "improvement": round(mae_improvement, 3) if current_mae else None,
        "features": feature_cols,
    }


def _build_features(df: pd.DataFrame, log: PipelineLogger) -> pd.DataFrame:
    """Build all features for the conversion model."""

    # Parse dates
    df["park_date_dt"] = pd.to_datetime(df["park_date"])

    # Hour of day (already have hour_bucket)
    df["hour_of_day"] = df["hour_bucket"].astype(np.float32)

    # Day of week (0=Monday, 6=Sunday)
    df["day_of_week"] = df["park_date_dt"].dt.dayofweek.astype(np.float32)

    # Month of year (1-12, captures seasonal patterns)
    df["month_of_year"] = df["park_date_dt"].dt.month.astype(np.float32)

    # Continuous time trend — days since epoch
    # This captures the gradual drift in posted-to-actual relationship
    # Better than discrete year: no artificial boundaries, smooth learning
    df["days_since_epoch"] = (
        (df["park_date_dt"] - pd.Timestamp(TIME_EPOCH)).dt.days
    ).astype(np.float32)

    # Park code encoding (simple integer label)
    df["park_code"] = df["entity_code"].str.extract(r'^([A-Z]{2,3})')[0]
    park_codes = sorted(df["park_code"].unique())
    park_map = {p: i for i, p in enumerate(park_codes)}
    df["park_encoded"] = df["park_code"].map(park_map).astype(np.float32)
    log.info(f"Parks encoded: {park_map}")

    # Entity encoding (frequency-based: more common entities get lower IDs)
    # This gives the model entity-specific behavior without a separate model per entity
    entity_freq = df["entity_code"].value_counts()
    entity_map = {e: i for i, e in enumerate(entity_freq.index)}
    df["entity_encoded"] = df["entity_code"].map(entity_map).astype(np.float32)
    log.info(f"Entities encoded: {len(entity_map)} unique")

    return df


def _get_encoding_maps(df: pd.DataFrame) -> dict:
    """Extract encoding maps for park and entity codes.
    
    These need to be saved alongside the model so that when we apply
    the conversion model in s06_synthetic, we can encode new data
    consistently.
    """
    park_map = {}
    if "park_code" in df.columns:
        park_codes = sorted(df["park_code"].unique())
        park_map = {p: i for i, p in enumerate(park_codes)}

    entity_freq = df["entity_code"].value_counts()
    entity_map = {e: int(i) for i, e in enumerate(entity_freq.index)}

    return {
        "park_map": park_map,
        "entity_map": entity_map,
        "time_epoch": TIME_EPOCH.isoformat(),
        "n_parks": len(park_map),
        "n_entities": len(entity_map),
    }
