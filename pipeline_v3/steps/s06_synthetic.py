"""Step 6: Synthetic Actuals Generation.

Applies the POSTED→ACTUAL conversion model to ALL historical POSTED
observations to produce synthetic actual wait times.

v1: Not implemented (TODO). Synthetic actuals were stale on disk.
v2: Full implementation. Applies the v2 conversion model with all features.

Shadow mode: NOW RUNS FULLY — loads conversion model from shadow dir
(written by s05), generates synthetics to shadow dir. Previously skipped.
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
    """Get the correct conversion model directory (shadow or production)."""
    if cfg.shadow and cfg.shadow_output_base:
        return cfg.shadow_output_base / "conversion_model"
    return cfg.output_base / "conversion_model"


def _get_synth_dir(cfg: PipelineConfig) -> Path:
    """Get the correct synthetic output directory (shadow or production)."""
    if cfg.shadow and cfg.shadow_output_base:
        synth_dir = cfg.shadow_output_base / "synthetic_actuals"
    else:
        synth_dir = cfg.output_base / "synthetic_actuals"
    synth_dir.mkdir(parents=True, exist_ok=True)
    return synth_dir


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Generate synthetic actuals using the conversion model."""

    log.info("=" * 60)
    log.info(f"STEP 6: SYNTHETIC ACTUALS v2 {'(SHADOW)' if cfg.shadow else ''}")
    log.info("=" * 60)

    if xgb is None:
        raise ValidationError("XGBoost required for synthetic generation")

    # Load conversion model from the correct directory
    # In shadow mode: use the model s05 just trained to shadow dir
    # In production: use the production model
    model_dir = _get_model_dir(cfg)
    model_path = model_dir / "conversion_model.json"

    # Fallback: if shadow model doesn't exist yet, try production model path
    if not model_path.exists():
        prod_model_path = conversion_model_path(cfg)
        if prod_model_path.exists():
            log.info(f"Shadow model not found, falling back to production: {prod_model_path}")
            model_path = prod_model_path
            model_dir = prod_model_path.parent
        else:
            log.warning("No conversion model found — cannot generate synthetics")
            return {"rows": 0, "action": "no_model"}

    encoding_path = model_dir / "conversion_encodings.json"
    if not encoding_path.exists():
        log.warning("No encoding maps found — conversion model may be v1")
        return {"rows": 0, "action": "no_encodings"}

    model = xgb.Booster()
    model.load_model(str(model_path))
    log.info(f"Loaded conversion model from {model_path}")

    with open(encoding_path) as f:
        encodings = json.load(f)

    feature_cols = encodings.get("feature_cols")
    if not feature_cols:
        log.warning("Encoding maps missing feature_cols — cannot apply v2 model")
        return {"rows": 0, "action": "incompatible_encodings"}

    park_map = encodings["park_map"]
    entity_map = encodings["entity_map"]
    scope_map = encodings.get("scope_map", {})
    log.info(f"Encodings: {len(entity_map)} entities, {len(park_map)} parks, {len(scope_map)} scopes")

    # Load ALL posted observations
    with log.timed("load posted observations"):
        parquet_str = str(cfg.parquet_dir).replace("\\", "/")
        dim_str = str(cfg.dimension_dir / "dimentity.csv").replace("\\", "/")
        with read_connection() as con:
            df = con.execute(f"""
                SELECT f.entity_code,
                       f.park_date,
                       EXTRACT(HOUR FROM f.observed_at_ts) as hour_bucket,
                       f.observed_at_ts as observed_at,
                       f.wait_time_minutes as posted_wait,
                       d.scope_and_scale
                FROM read_parquet('{parquet_str}/*.parquet') f
                LEFT JOIN read_csv_auto('{dim_str}') d
                    ON f.entity_code = d.code
                WHERE f.wait_time_type = 'POSTED'
                  AND f.wait_time_minutes > 0
                  AND f.observed_at_ts IS NOT NULL
            """).fetchdf()

    if len(df) == 0:
        log.warning("No posted observations found")
        return {"rows": 0, "action": "no_data"}

    log.info(f"Posted observations: {len(df):,} rows, {df['entity_code'].nunique()} entities")

    # Build features (must match s05 exactly)
    with log.timed("feature engineering"):
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
        df["park_encoded"] = df["park_code"].map(park_map).fillna(-1).astype(np.float32)

        unknown_entity = len(entity_map)
        df["entity_encoded"] = df["entity_code"].map(entity_map).fillna(unknown_entity).astype(np.float32)

        df["scope_encoded"] = df["scope_and_scale"].map(scope_map).fillna(-1).astype(np.float32)

    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise ValidationError(f"Feature mismatch: s06 missing {missing}")

    # Apply conversion model
    with log.timed("generate synthetic actuals"):
        X = df[feature_cols].values.astype(np.float32)
        dmatrix = xgb.DMatrix(X, feature_names=feature_cols)
        df["synthetic_actual"] = model.predict(dmatrix)
        df["synthetic_actual"] = df["synthetic_actual"].clip(lower=1.0)

    log.info(f"Synthetic actuals generated: {len(df):,} rows")
    log.info(f"Mean synthetic: {df['synthetic_actual'].mean():.1f} min")
    log.info(f"Mean posted: {df['posted_wait'].mean():.1f} min")
    log.info(f"Mean ratio (synthetic/posted): {(df['synthetic_actual'] / df['posted_wait']).mean():.3f}")

    # Write per-park parquet files to correct directory
    synth_dir = _get_synth_dir(cfg)
    with log.timed("write parquet files"):
        output_cols = ["entity_code", "park_date", "observed_at", "synthetic_actual"]

        parks_written = 0
        total_rows = 0
        for park_code in sorted(df["park_code"].unique()):
            park_df = df[df["park_code"] == park_code][output_cols].copy()
            if len(park_df) == 0:
                continue

            park_df["observed_at"] = park_df["observed_at"].astype(str)

            out_path = synth_dir / f"{park_code}.parquet"
            park_df.to_parquet(out_path, index=False)
            parks_written += 1
            total_rows += len(park_df)

        log.info(f"Written {parks_written} park files to {synth_dir}")
        log.info(f"Total rows: {total_rows:,}")

    return {
        "rows": total_rows,
        "action": "generated",
        "parks": parks_written,
        "mean_synthetic": round(float(df["synthetic_actual"].mean()), 1),
        "mean_posted": round(float(df["posted_wait"].mean()), 1),
    }
