"""Step 6: Synthetic Actuals Generation — lean version.

Applies the lean 3-feature conversion model (posted_wait, log_posted_wait,
months_since_epoch) to ALL historical POSTED observations.

Because the conversion model is entity-agnostic, s06 is dramatically simpler:
- No dimEntity join needed
- No encoding map lookups for entity/park/scope
- No handling of unseen entities
- Just: load posted waits, compute 3 features, predict, write parquets

This also means much lower memory usage — no categorical encoding columns.

Shadow mode: runs fully — loads model from shadow dir, writes to shadow dir.
"""

from __future__ import annotations

import json
from datetime import date
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
from pipeline_v3.core.paths import conversion_model_path
from pipeline_v3.core.validation import ValidationError

TIME_EPOCH = date(2015, 1, 1)


def _get_model_dir(cfg: PipelineConfig) -> Path:
    """Get the correct conversion model directory."""
    if cfg.shadow and cfg.shadow_output_base:
        return cfg.shadow_output_base / "conversion_model"
    return cfg.output_base / "conversion_model"


def _get_synth_dir(cfg: PipelineConfig) -> Path:
    """Get the correct synthetic output directory."""
    if cfg.shadow and cfg.shadow_output_base:
        synth_dir = cfg.shadow_output_base / "synthetic_actuals"
    else:
        synth_dir = cfg.output_base / "synthetic_actuals"
    synth_dir.mkdir(parents=True, exist_ok=True)
    return synth_dir


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Generate synthetic actuals using the lean conversion model."""

    log.info("=" * 60)
    log.info(f"STEP 6: SYNTHETIC ACTUALS v2_lean {'(SHADOW)' if cfg.shadow else ''}")
    log.info("=" * 60)

    if xgb is None:
        raise ValidationError("XGBoost required for synthetic generation")

    # Load conversion model
    model_dir = _get_model_dir(cfg)
    model_path = model_dir / "conversion_model.json"

    if not model_path.exists():
        prod_model_path = conversion_model_path(cfg)
        if prod_model_path.exists():
            log.info(f"Shadow model not found, falling back to production: {prod_model_path}")
            model_path = prod_model_path
            model_dir = prod_model_path.parent
        else:
            log.warning("No conversion model found")
            return {"rows": 0, "action": "no_model"}

    encoding_path = model_dir / "conversion_encodings.json"
    if not encoding_path.exists():
        log.warning("No encoding maps found")
        return {"rows": 0, "action": "no_encodings"}

    model = xgb.Booster()
    model.load_model(str(model_path))
    log.info(f"Loaded conversion model from {model_path}")

    with open(encoding_path) as f:
        encodings = json.load(f)

    feature_cols = encodings.get("feature_cols")
    if not feature_cols:
        log.warning("Encoding maps missing feature_cols")
        return {"rows": 0, "action": "incompatible_encodings"}

    log.info(f"Features: {feature_cols}")

    # Load ALL posted observations — simple query, no dimEntity join needed
    with log.timed("load posted observations"):
        parquet_str = str(cfg.parquet_dir).replace("\\", "/")
        with read_connection() as con:
            df = con.execute(f"""
                SELECT entity_code,
                       park_date,
                       observed_at_ts as observed_at,
                       wait_time_minutes as posted_wait
                FROM read_parquet('{parquet_str}/*.parquet')
                WHERE wait_time_type = 'POSTED'
                  AND wait_time_minutes > 0
                  AND observed_at_ts IS NOT NULL
            """).fetchdf()

    if len(df) == 0:
        log.warning("No posted observations found")
        return {"rows": 0, "action": "no_data"}

    log.info(f"Posted observations: {len(df):,} rows, {df['entity_code'].nunique()} entities")

    # Build features — just 3, no encoding lookups
    with log.timed("feature engineering"):
        df["park_date_dt"] = pd.to_datetime(df["park_date"])
        df["posted_wait"] = df["posted_wait"].astype(np.float32)
        df["log_posted_wait"] = np.log1p(df["posted_wait"]).astype(np.float32)
        df["months_since_epoch"] = (
            (df["park_date_dt"].dt.year - TIME_EPOCH.year) * 12
            + (df["park_date_dt"].dt.month - TIME_EPOCH.month)
        ).astype(np.float32)

    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise ValidationError(f"Feature mismatch: s06 missing {missing}")

    # Apply conversion model — process per-park to control memory
    synth_dir = _get_synth_dir(cfg)
    df["park_code"] = df["entity_code"].str.extract(r'^([A-Z]{2,3})')[0]

    parks = sorted(df["park_code"].unique())
    parks_written = 0
    total_rows = 0

    with log.timed("generate + write synthetic actuals"):
        for park_code in parks:
            park_df = df[df["park_code"] == park_code].copy()
            if len(park_df) == 0:
                continue

            # Predict for this park
            X = park_df[feature_cols].values.astype(np.float32)
            dmatrix = xgb.DMatrix(X, feature_names=feature_cols)
            park_df["synthetic_actual"] = model.predict(dmatrix)
            park_df["synthetic_actual"] = park_df["synthetic_actual"].clip(lower=1.0)

            # Write
            output_cols = ["entity_code", "park_date", "observed_at", "synthetic_actual"]
            out_df = park_df[output_cols].copy()
            out_df["observed_at"] = out_df["observed_at"].astype(str)

            out_path = synth_dir / f"{park_code}.parquet"
            out_df.to_parquet(out_path, index=False)
            parks_written += 1
            total_rows += len(out_df)

            del park_df, out_df, X, dmatrix  # Release memory between parks

    log.info(f"Written {parks_written} park files to {synth_dir}")
    log.info(f"Total rows: {total_rows:,}")

    # Summary stats
    sample = df.head(100000)
    X_sample = sample[feature_cols].values.astype(np.float32)
    d_sample = xgb.DMatrix(X_sample, feature_names=feature_cols)
    sample_pred = model.predict(d_sample)
    mean_synth = float(np.mean(sample_pred))
    mean_posted = float(sample["posted_wait"].mean())

    log.info(f"Mean synthetic (sample): {mean_synth:.1f} min")
    log.info(f"Mean posted (sample): {mean_posted:.1f} min")
    log.info(f"Mean ratio: {mean_synth / mean_posted:.3f}")

    return {
        "rows": total_rows,
        "action": "generated",
        "parks": parks_written,
        "mean_synthetic": round(mean_synth, 1),
        "mean_posted": round(mean_posted, 1),
    }
