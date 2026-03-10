"""Step 6: Synthetic Actuals Generation.

Applies the POSTED→ACTUAL conversion model to ALL historical POSTED
observations to produce synthetic actual wait times.

v1: Not implemented (TODO). Synthetic actuals were stale on disk.
v2: Full implementation. Applies the v2 conversion model with all features.
    Generates fresh synthetic actuals daily alongside the model refresh.

The conversion model (trained in s05) converts posted wait times to
estimated actual wait times. These synthetic actuals are the primary
training data for entity-level models (s07) — roughly 94% of all training.

Fresh synthetic actuals = better entity models = better predictions.
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

# Must match s05_conversion.py
TIME_EPOCH = date(2015, 1, 1)


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Generate synthetic actuals using the conversion model."""

    log.info("=" * 60)
    log.info("STEP 6: SYNTHETIC ACTUALS v2 (daily regeneration)")
    log.info("=" * 60)

    synth_dir = cfg.output_base / "synthetic_actuals"

    if cfg.shadow:
        log.info("Shadow mode: using production synthetic actuals")
        if synth_dir.exists():
            n_files = len(list(synth_dir.glob("*.parquet")))
            log.info(f"Found {n_files} synthetic actual parquet files")
            return {"rows": 0, "action": "validated", "files": n_files}
        else:
            log.warning("No synthetic actuals directory found")
            return {"rows": 0, "action": "missing"}

    # === Load conversion model ===
    model_path = conversion_model_path(cfg)
    if not model_path.exists():
        log.warning("No conversion model found — cannot generate synthetics")
        return {"rows": 0, "action": "no_model"}

    encoding_path = model_path.parent / "conversion_encodings.json"
    if not encoding_path.exists():
        log.warning("No encoding maps found — conversion model may be v1")
        return {"rows": 0, "action": "no_encodings"}

    if xgb is None:
        raise ValidationError("XGBoost required for synthetic generation")

    model = xgb.Booster()
    model.load_model(str(model_path))

    with open(encoding_path) as f:
        encodings = json.load(f)

    feature_cols = encodings.get("feature_cols")
    if not feature_cols:
        log.warning("Encoding maps missing feature_cols — cannot apply v2 model")
        return {"rows": 0, "action": "incompatible_encodings"}

    park_map = encodings["park_map"]
    entity_map = encodings["entity_map"]
    scope_map = encodings.get("scope_map", {})
    log.info(f"Loaded conversion model with {len(feature_cols)} features")
    log.info(f"Encodings: {len(entity_map)} entities, {len(park_map)} parks, {len(scope_map)} scopes")

    # === Load ALL posted observations ===
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

    # === Build features (must match s05 exactly) ===
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

        # Park encoding (unseen parks get -1)
        df["park_code"] = df["entity_code"].str.extract(r'^([A-Z]{2,3})')[0]
        df["park_encoded"] = df["park_code"].map(park_map).fillna(-1).astype(np.float32)

        # Entity encoding (unseen entities get the max+1 — rare/unknown bucket)
        unknown_entity = len(entity_map)
        df["entity_encoded"] = df["entity_code"].map(entity_map).fillna(unknown_entity).astype(np.float32)

        # Scope encoding
        df["scope_encoded"] = df["scope_and_scale"].map(scope_map).fillna(-1).astype(np.float32)

    # Verify features
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise ValidationError(f"Feature mismatch: s06 missing {missing}")

    # === Apply conversion model ===
    with log.timed("generate synthetic actuals"):
        X = df[feature_cols].values.astype(np.float32)
        dmatrix = xgb.DMatrix(X, feature_names=feature_cols)
        df["synthetic_actual"] = model.predict(dmatrix)

        # Floor at 1 minute (no negative or zero synthetic actuals)
        df["synthetic_actual"] = df["synthetic_actual"].clip(lower=1.0)

    log.info(f"Synthetic actuals generated: {len(df):,} rows")
    log.info(f"Mean synthetic: {df['synthetic_actual'].mean():.1f} min")
    log.info(f"Mean posted: {df['posted_wait'].mean():.1f} min")
    log.info(f"Mean ratio (synthetic/posted): {(df['synthetic_actual'] / df['posted_wait']).mean():.3f}")

    # === Write per-park parquet files ===
    with log.timed("write parquet files"):
        synth_dir.mkdir(parents=True, exist_ok=True)

        # Output columns: match existing synthetic parquet schema
        output_cols = ["entity_code", "park_date", "observed_at", "synthetic_actual"]

        parks_written = 0
        total_rows = 0
        for park_code in sorted(df["park_code"].unique()):
            park_df = df[df["park_code"] == park_code][output_cols].copy()
            if len(park_df) == 0:
                continue

            # Convert observed_at to string for parquet compatibility
            # (existing synthetics use VARCHAR observed_at, not TIMESTAMP)
            park_df["observed_at"] = park_df["observed_at"].astype(str)

            out_path = synth_dir / f"{park_code}.parquet"
            park_df.to_parquet(out_path, index=False)
            parks_written += 1
            total_rows += len(park_df)

        log.info(f"Written {parks_written} park files, {total_rows:,} total rows")

    return {
        "rows": total_rows,
        "action": "generated",
        "parks": parks_written,
        "mean_synthetic": round(float(df["synthetic_actual"].mean()), 1),
        "mean_posted": round(float(df["posted_wait"].mean()), 1),
    }
