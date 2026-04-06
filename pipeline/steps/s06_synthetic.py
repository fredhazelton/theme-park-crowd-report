"""Step 6: Synthetic Actuals Generation — 9-feature, fully per-park chunked.

Applies the 9-feature conversion model to historical POSTED observations.
FULLY per-park chunked: load per park, build features, predict, write, free.

Previous version loaded ALL 92M rows into one DataFrame (30-50GB), built
features globally, then chunked only predict+write. The full DataFrame
stayed in memory the entire time.

This version: query DuckDB once per park, build features for that park only,
predict, write parquet, delete everything, next park. Peak memory should be
~5-8GB (one park's data + model + parquet writer) instead of 50GB.

Shadow mode: runs fully — loads model from shadow dir, writes to shadow dir.
"""

from __future__ import annotations

import gc
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import xgboost as xgb
except ImportError:
    xgb = None

from pipeline.config import PipelineConfig
from pipeline.core.db import read_connection
from pipeline.core.logging import PipelineLogger
from pipeline.core.paths import conversion_model_path
from pipeline.core.validation import ValidationError

TIME_EPOCH = date(2015, 1, 1)

# Global POSTED→ACTUAL hourly ratios — computed from 750K+ matched pairs across all parks
# with both POSTED and ACTUAL data. Used as fallback for parks without ACTUAL data
# (e.g., TDL, TDS, UH). Source: TPCR #462, verified Apr 5 2026.
HOURLY_RATIOS = {
    0: 0.521, 1: 0.555, 2: 0.490, 3: 0.438, 4: 0.566, 5: 0.473,
    6: 0.524, 7: 0.582, 8: 0.599, 9: 0.625, 10: 0.665, 11: 0.668,
    12: 0.682, 13: 0.688, 14: 0.687, 15: 0.672, 16: 0.667, 17: 0.665,
    18: 0.655, 19: 0.646, 20: 0.616, 21: 0.590, 22: 0.573, 23: 0.555,
}
GLOBAL_RATIO = 0.600



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
    """Generate synthetic actuals — fully per-park chunked."""

    log.info("=" * 60)
    log.info(f"STEP 6: SYNTHETIC ACTUALS v2 (fully per-park) {'(SHADOW)' if cfg.shadow else ''}")
    log.info("=" * 60)

    if xgb is None:
        raise ValidationError("XGBoost required for synthetic generation")

    # Load conversion model (small — stays in memory for all parks)
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
    unknown_entity = float(len(entity_map))
    log.info(f"Features: {feature_cols}")
    log.info(f"Encodings: {len(entity_map)} entities, {len(park_map)} parks, {len(scope_map)} scopes")

    # Get list of parks from fact tables
    parquet_str = str(cfg.parquet_dir).replace("\\", "/")
    dim_str = str(cfg.dimension_dir / "dimentity.csv").replace("\\", "/")

    with read_connection() as con:
        parks_df = con.execute(f"""
            SELECT DISTINCT LEFT(entity_code, 2) as park_code
            FROM read_parquet('{parquet_str}/*.parquet')
            WHERE wait_time_type = 'POSTED' AND wait_time_minutes > 0
            ORDER BY park_code
        """).fetchdf()

    parks = sorted(parks_df["park_code"].tolist())
    log.info(f"Parks to process: {len(parks)} — {parks}")

    synth_dir = _get_synth_dir(cfg)
    parks_written = 0
    total_rows = 0
    output_cols = ["entity_code", "park_date", "observed_at", "synthetic_actual"]

    # Process ONE PARK at a time — load, feature-engineer, predict, write, free
    for park_code in parks:
        with log.timed(f"park {park_code}"):
            # Load ONLY this park's data
            with read_connection() as con:
                park_df = con.execute(f"""
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
                      AND f.entity_code LIKE '{park_code}%'
                """).fetchdf()

            if len(park_df) == 0:
                log.info(f"  {park_code}: no posted data, skipping")
                continue

            # Build features for this park only
            park_df["park_date_dt"] = pd.to_datetime(park_df["park_date"])
            park_df["posted_wait"] = park_df["posted_wait"].astype(np.float32)
            park_df["log_posted_wait"] = np.log1p(park_df["posted_wait"]).astype(np.float32)
            park_df["hour_of_day"] = park_df["hour_bucket"].astype(np.float32)
            park_df["day_of_week"] = park_df["park_date_dt"].dt.dayofweek.astype(np.float32)
            park_df["month_of_year"] = park_df["park_date_dt"].dt.month.astype(np.float32)
            park_df["months_since_epoch"] = (
                (park_df["park_date_dt"].dt.year - TIME_EPOCH.year) * 12
                + (park_df["park_date_dt"].dt.month - TIME_EPOCH.month)
            ).astype(np.float32)
            # Check if this park has model encodings (was in training data)
            park_has_encoding = park_code in park_map

            if park_has_encoding:
                # Standard path: use XGBoost conversion model
                park_df["park_encoded"] = park_map.get(park_code, -1)
                park_df["entity_encoded"] = park_df["entity_code"].map(entity_map).fillna(unknown_entity).astype(np.float32)
                park_df["scope_encoded"] = park_df["scope_and_scale"].map(scope_map).fillna(-1).astype(np.float32)

                missing = [c for c in feature_cols if c not in park_df.columns]
                if missing:
                    log.warning(f"  {park_code}: missing features {missing}, skipping")
                    del park_df
                    gc.collect()
                    continue

                X = park_df[feature_cols].values.astype(np.float32)
                dmatrix = xgb.DMatrix(X, feature_names=feature_cols)
                park_df["synthetic_actual"] = model.predict(dmatrix)
                park_df["synthetic_actual"] = park_df["synthetic_actual"].clip(lower=1.0)
            else:
                # Fallback path: park has no ACTUAL data (e.g., TDL, TDS, UH)
                # Apply global hourly POSTED→ACTUAL ratio instead of model with unknown encodings
                log.info(f"  {park_code}: no model encoding — using hourly ratio fallback")
                park_df["hour_int"] = park_df["hour_bucket"].astype(int)
                park_df["ratio"] = park_df["hour_int"].map(HOURLY_RATIOS).fillna(GLOBAL_RATIO)
                park_df["synthetic_actual"] = (park_df["posted_wait"] * park_df["ratio"]).clip(lower=1.0).astype(np.float32)

            # Write immediately
            out_df = park_df[output_cols].copy()
            out_df["observed_at"] = out_df["observed_at"].astype(str)
            out_path = synth_dir / f"{park_code}.parquet"
            out_df.to_parquet(out_path, index=False)

            n_rows = len(out_df)
            parks_written += 1
            total_rows += n_rows
            log.info(f"  {park_code}: {n_rows:,} rows written")

            # Free ALL memory for this park
            del park_df, out_df
            if park_has_encoding:
                del X, dmatrix
            gc.collect()

    log.info(f"Written {parks_written} park files to {synth_dir}")
    log.info(f"Total rows: {total_rows:,}")

    return {
        "rows": total_rows,
        "action": "generated",
        "parks": parks_written,
    }
