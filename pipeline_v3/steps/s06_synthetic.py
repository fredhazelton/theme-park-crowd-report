"""Step 6: Synthetic Actuals Generation — 9-feature with per-park chunking.

Applies the 9-feature conversion model to ALL historical POSTED observations.
Per-park chunking for predict+write to control memory and I/O time.

Shadow test showed:
  - XGBoost predict on 92M rows: 68 seconds (fast)
  - Writing 92M rows to parquet: 1,393 seconds (23 min — the bottleneck!)
  - Peak memory: 50GB (dangerous on 64GB server)

Per-park chunking fixes both: predict per park (~7M rows), write immediately,
free memory, next park. Predicted speedup: 23 min → ~5 min for writes.

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
    if cfg.shadow and cfg.shadow_output_base:
        return cfg.shadow_output_base / "conversion_model"
    return cfg.output_base / "conversion_model"


def _get_synth_dir(cfg: PipelineConfig) -> Path:
    if cfg.shadow and cfg.shadow_output_base:
        synth_dir = cfg.shadow_output_base / "synthetic_actuals"
    else:
        synth_dir = cfg.output_base / "synthetic_actuals"
    synth_dir.mkdir(parents=True, exist_ok=True)
    return synth_dir


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Generate synthetic actuals — 9-feature model, per-park chunking."""

    log.info("=" * 60)
    log.info(f"STEP 6: SYNTHETIC ACTUALS v2 (per-park chunked) {'(SHADOW)' if cfg.shadow else ''}")
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

    park_map = encodings.get("park_map", {})
    entity_map = encodings.get("entity_map", {})
    scope_map = encodings.get("scope_map", {})
    log.info(f"Features: {feature_cols}")
    log.info(f"Encodings: {len(entity_map)} entities, {len(park_map)} parks, {len(scope_map)} scopes")

    # Load ALL posted observations with dimEntity join for scope
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

    # Build ALL features once (cheap — 9 columns on existing data)
    with log.timed("feature engineering"):
        df["park_date_dt"] = pd.to_datetime(df["park_date"])
        df["posted_wait"] = df["posted_wait"].astype(np.float32)
        df["log_posted_wait"] = np.log1p(df["posted_wait"]).astype(np.float32)
        df["hour_of_day"] = df["hour_bucket"].astype(np.float32)
        df["day_of_week"] = df["park_date_dt"].dt.dayofweek.astype(np.float32)
        df["month_of_year"] = df["park_date_dt"].dt.month.astype(np.float32)
        df["months_since_epoch"] = (
            (df["park_date_dt"].dt.year - TIME_EPOCH.year) * 12
            + (df["park_date_dt"].dt.month - TIME_EPOCH.month)
        ).astype(np.float32)

        # Park encoding
        df["park_code"] = df["entity_code"].str.extract(r'^([A-Z]{2,3})')[0]
        df["park_encoded"] = df["park_code"].map(park_map).fillna(-1).astype(np.float32)

        # Entity encoding (unseen entities get max+1)
        unknown_entity = float(len(entity_map))
        df["entity_encoded"] = df["entity_code"].map(entity_map).fillna(unknown_entity).astype(np.float32)

        # Scope encoding
        df["scope_encoded"] = df["scope_and_scale"].map(scope_map).fillna(-1).astype(np.float32)

    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise ValidationError(f"Feature mismatch: s06 missing {missing}")

    # Per-park predict + write to control memory and I/O
    # Shadow test: predict=68s, monolithic write=1393s (23 min!)
    # Per-park: predict per park, write immediately, free memory
    synth_dir = _get_synth_dir(cfg)
    parks = sorted(df["park_code"].unique())
    parks_written = 0
    total_rows = 0
    output_cols = ["entity_code", "park_date", "observed_at", "synthetic_actual"]

    with log.timed("generate + write synthetic actuals (per-park chunked)"):
        for park_code in parks:
            park_mask = df["park_code"] == park_code
            park_df = df.loc[park_mask, feature_cols + ["entity_code", "park_date", "observed_at"]].copy()

            if len(park_df) == 0:
                continue

            # Predict for this park only
            X = park_df[feature_cols].values.astype(np.float32)
            dmatrix = xgb.DMatrix(X, feature_names=feature_cols)
            park_df["synthetic_actual"] = model.predict(dmatrix)
            park_df["synthetic_actual"] = park_df["synthetic_actual"].clip(lower=1.0)

            # Write immediately
            out_df = park_df[output_cols].copy()
            out_df["observed_at"] = out_df["observed_at"].astype(str)
            out_path = synth_dir / f"{park_code}.parquet"
            out_df.to_parquet(out_path, index=False)

            n_rows = len(out_df)
            parks_written += 1
            total_rows += n_rows
            log.info(f"  {park_code}: {n_rows:,} rows written")

            del park_df, out_df, X, dmatrix  # Free memory

    log.info(f"Written {parks_written} park files to {synth_dir}")
    log.info(f"Total rows: {total_rows:,}")

    # Summary stats from sample
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
