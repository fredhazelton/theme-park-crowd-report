"""Step 5: POSTED→ACTUAL Conversion Model — with validation gate.

Trains a global model that converts POSTED wait times to estimated ACTUAL.
Used to generate synthetic actuals from historical POSTED observations.

v3 improvement: VALIDATION GATE
- Train candidate model on fresh data
- Evaluate on holdout set
- Compare MAE against current production model
- Only deploy if candidate is better (or within tolerance)
- Keep previous model as automatic rollback

Runs weekly (Monday) or if model is missing.

v3.1 fix: removed time_slot from GROUP BY — raw parquet doesn't have
a time_slot column. Match on entity_code + park_date + hour bucket instead.
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


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Train conversion model with validation gate."""

    log.info("=" * 60)
    log.info("STEP 5: CONVERSION MODEL (v3.1 — with validation gate)")
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

    # Load matched pairs where we have both POSTED and ACTUAL
    # v3.1: match on entity_code + park_date + hour (no time_slot column in raw parquet)
    with log.timed("load training data"):
        parquet_str = str(cfg.parquet_dir).replace("\\", "/")
        with read_connection() as con:
            df = con.execute(f"""
                WITH posted AS (
                    SELECT entity_code, park_date,
                           EXTRACT(HOUR FROM time_slot_start) as hour_bucket,
                           AVG(wait_time_minutes) as posted_wait
                    FROM read_parquet('{parquet_str}/*.parquet')
                    WHERE wait_time_type = 'POSTED' AND wait_time_minutes > 0
                      AND time_slot_start IS NOT NULL
                    GROUP BY entity_code, park_date, hour_bucket
                ),
                actual AS (
                    SELECT entity_code, park_date,
                           EXTRACT(HOUR FROM time_slot_start) as hour_bucket,
                           AVG(wait_time_minutes) as actual_wait
                    FROM read_parquet('{parquet_str}/*.parquet')
                    WHERE wait_time_type = 'ACTUAL' AND wait_time_minutes > 0
                      AND time_slot_start IS NOT NULL
                    GROUP BY entity_code, park_date, hour_bucket
                )
                SELECT p.posted_wait, a.actual_wait
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

    # Split: train / holdout
    n = len(df)
    holdout_n = int(n * cfg.conversion_holdout_fraction)
    train_df = df.iloc[:-holdout_n]
    holdout_df = df.iloc[-holdout_n:]

    # Train candidate
    with log.timed("train candidate model"):
        X_train = train_df[["posted_wait"]].values.astype(np.float32)
        y_train = train_df["actual_wait"].values.astype(np.float32)
        X_hold = holdout_df[["posted_wait"]].values.astype(np.float32)
        y_hold = holdout_df["actual_wait"].values.astype(np.float32)

        dtrain = xgb.DMatrix(X_train, label=y_train)
        dhold = xgb.DMatrix(X_hold, label=y_hold)

        params = {
            "max_depth": 6,
            "eta": 0.1,
            "objective": "reg:squarederror",
            "seed": 42,
            "verbosity": 0,
        }
        bst = xgb.train(
            params, dtrain,
            num_boost_round=500,
            evals=[(dhold, "holdout")],
            early_stopping_rounds=20,
            verbose_eval=False,
        )

    # Evaluate candidate on holdout
    candidate_pred = bst.predict(dhold)
    candidate_mae = float(np.mean(np.abs(y_hold - candidate_pred)))
    log.info(f"Candidate MAE on holdout: {candidate_mae:.3f} min")

    # Validation gate: compare against current production model
    if model_path.exists():
        with log.timed("evaluate current model"):
            current_model = xgb.Booster()
            current_model.load_model(str(model_path))
            current_pred = current_model.predict(dhold)
            current_mae = float(np.mean(np.abs(y_hold - current_pred)))
            log.info(f"Current model MAE on holdout: {current_mae:.3f} min")

        mae_regression = candidate_mae - current_mae
        if mae_regression > cfg.conversion_max_mae_regression:
            log.warning(
                f"VALIDATION GATE: candidate is {mae_regression:.3f} min WORSE than current "
                f"(threshold: {cfg.conversion_max_mae_regression}). Keeping current model."
            )
            log.metric("conversion_gate", 0, reason="regression", mae_diff=mae_regression)
            return {"rows": 0, "action": "gate_rejected", "candidate_mae": candidate_mae, "current_mae": current_mae}

        log.info(f"Candidate is {-mae_regression:.3f} min better. Deploying.")
        backup = conversion_model_backup_path(cfg)
        backup.parent.mkdir(parents=True, exist_ok=True)
        model_path.rename(backup)
        log.info(f"Previous model backed up to {backup}")
    else:
        log.info("No existing model — deploying candidate directly")

    # Save candidate as production
    model_path.parent.mkdir(parents=True, exist_ok=True)
    bst.save_model(str(model_path))

    metadata = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_train": len(train_df),
        "n_holdout": len(holdout_df),
        "mae_holdout": round(candidate_mae, 3),
        "version": "v3.1",
    }
    meta_path = model_path.parent / "metadata_v3.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    log.info(f"Conversion model deployed: MAE {candidate_mae:.3f} min")
    log.metric("conversion_mae", round(candidate_mae, 3))
    log.metric("conversion_gate", 1)

    return {"rows": len(train_df), "action": "deployed", "mae": round(candidate_mae, 3)}
