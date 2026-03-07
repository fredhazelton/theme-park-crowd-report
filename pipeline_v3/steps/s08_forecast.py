"""Step 8: Forecast Generation — Memory-safe by design.

The v2 forecast OOM'd at 49GB because it:
- Loaded all models at once
- Pickled agg_lookup to 8 workers (8 copies in RAM)
- Generated 730 days of time grids for all entities simultaneously

v3 approach:
- Process ONE PARK at a time
- Sequential (no multiprocessing) — each park takes ~45s, total ~10 min
- Load only that park's models, generate only that park's grid
- Flush to parquet between parks, release memory
- Peak memory: ~2-3GB (one park's worth)
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    import xgboost as xgb
except ImportError:
    xgb = None

from pipeline_v3.config import PipelineConfig
from pipeline_v3.core.db import read_connection
from pipeline_v3.core.logging import PipelineLogger
from pipeline_v3.core.park_codes import PARK_TIMEZONE, entity_to_park
from pipeline_v3.core.validation import ValidationError, require_file

# Feature columns for actuals-first model (v3 default)
FEATURES_ACTUALS = [
    "mins_since_6am", "mins_since_open",
    "date_group_id_encoded", "season_encoded", "season_year_encoded",
]
FEATURES_ACTUALS_LITE = ["mins_since_6am", "mins_since_open"]
FEATURES_V2 = [
    "posted_time", "mins_since_6am", "mins_since_open",
    "hour_of_day", "date_group_id_encoded", "season_encoded",
    "season_year_encoded",
]


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Generate forecasts for all parks, one park at a time."""

    if xgb is None:
        raise ValidationError("XGBoost is required for forecasting. pip install xgboost")

    log.info("=" * 60)
    log.info("STEP 8: FORECAST GENERATION (v3 — memory-safe)")
    log.info("=" * 60)

    start_date = date.today() + timedelta(days=1)
    end_date = start_date + timedelta(days=cfg.forecast_days)
    log.info(f"Forecast range: {start_date} to {end_date} ({cfg.forecast_days} days)")

    # Load shared data (small, loaded once)
    with log.timed("load shared data"):
        date_features = _load_date_features(cfg, log)
        park_hours = _load_park_hours(cfg, log)
        agg_lookup = _load_aggregates(cfg, log)
        entity_list = _load_entity_list(cfg, log)
        operating_calendar = _load_operating_calendar(cfg, log)
        fallback_ratios = _load_fallback_ratios(cfg, log)

    # Group entities by park
    park_entities: dict[str, list[str]] = {}
    for entity in entity_list:
        park = entity_to_park(entity)
        if park in cfg.ignore_parks:
            continue
        park_entities.setdefault(park, []).append(entity)

    log.info(f"Total entities: {len(entity_list)} across {len(park_entities)} parks")

    # Process one park at a time
    output_dir = cfg.forecast_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / "_v3_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    total_predictions = 0
    total_entities = 0
    failed_entities = 0
    batch_files = []

    for park_code in sorted(park_entities.keys()):
        entities = park_entities[park_code]
        with log.timed(f"park {park_code} ({len(entities)} entities)"):
            park_results = []

            # Generate time grid for this park
            park_tz = PARK_TIMEZONE.get(park_code, "America/New_York")
            time_grid = _generate_park_time_grid(
                start_date, end_date, date_features, park_hours, park_code, park_tz
            )

            if time_grid is None or len(time_grid) == 0:
                log.warning(f"  {park_code}: no time grid generated, skipping")
                continue

            for entity_code in entities:
                try:
                    result = _forecast_entity(
                        entity_code, park_code, time_grid,
                        cfg.models_dir, agg_lookup, park_hours,
                        fallback_ratios, operating_calendar,
                    )
                    if result is not None and len(result) > 0:
                        park_results.append(result)
                        total_entities += 1
                except Exception as e:
                    log.warning(f"  {entity_code}: failed — {e}")
                    failed_entities += 1

            # Flush this park to temp parquet
            if park_results:
                park_df = pd.concat(park_results, ignore_index=True)
                batch_file = temp_dir / f"{park_code}.parquet"
                park_df.to_parquet(batch_file, index=False)
                batch_files.append(batch_file)
                total_predictions += len(park_df)
                log.info(f"  {park_code}: {len(park_df):,} predictions from {len(park_results)} entities")
                del park_df, park_results  # Release memory

    # Combine all parks into final output
    if batch_files:
        with log.timed("combine park files"):
            chunks = [pd.read_parquet(f) for f in batch_files]
            combined = pd.concat(chunks, ignore_index=True)
            del chunks

            output_file = output_dir / "all_forecasts_v3.parquet"
            combined.to_parquet(output_file, index=False)

            # Log method breakdown
            method_counts = combined["prediction_method"].value_counts()
            for method, count in method_counts.items():
                log.info(f"  {method}: {count:,}")

            del combined

        # Cleanup temp files
        for f in batch_files:
            f.unlink()
        try:
            temp_dir.rmdir()
        except OSError:
            pass

    log.info("=" * 60)
    log.info("FORECAST COMPLETE")
    log.info(f"Entities: {total_entities} successful, {failed_entities} failed")
    log.info(f"Predictions: {total_predictions:,}")
    log.metric("forecast_predictions", total_predictions)
    log.metric("forecast_entities", total_entities)
    log.metric("forecast_failed", failed_entities)
    log.info("=" * 60)

    return {"rows": total_predictions, "entities": total_entities, "failed": failed_entities}


# =========================================================================
# Entity-level forecasting
# =========================================================================

def _forecast_entity(
    entity_code: str,
    park_code: str,
    time_grid: pd.DataFrame,
    models_dir: Path,
    agg_lookup: dict,
    park_hours: dict,
    fallback_ratios: dict,
    operating_calendar: set | None,
) -> pd.DataFrame | None:
    """Generate forecast for a single entity. Returns DataFrame or None."""

    df = time_grid.copy()
    df["entity_code"] = entity_code

    # Filter by operating calendar
    if operating_calendar is not None:
        ec_upper = entity_code.upper()
        operating_dates = {d for (e, d) in operating_calendar if e == ec_upper}
        if operating_dates:
            df = df[df["park_date"].isin(operating_dates)]
        elif any(e == ec_upper for e, _ in operating_calendar):
            return None  # Entity in calendar but zero operating dates = extinct

    if len(df) == 0:
        return None

    # Get posted_time estimates from aggregates
    def get_posted(row):
        key = (entity_code, row["date_group_id"], row["time_slot_15min"])
        return agg_lookup.get(key, 5.0)
    df["posted_time"] = df.apply(get_posted, axis=1)

    # Get mins_since_open
    def get_mins_open(row):
        key = (park_code, row["park_date"])
        hours_tuple = park_hours.get(key)
        if hours_tuple:
            opening = hours_tuple[0]
            if opening is not None:
                current = row["hour_of_day"] * 60 + (row["time_slot"].minute if hasattr(row["time_slot"], "minute") else 0)
                return max(0, current - opening)
        return row["mins_since_6am"]
    df["mins_since_open"] = df.apply(get_mins_open, axis=1)

    # Model selection: actuals model > v2 model > aggregate > fallback_ratio
    entity_dir = models_dir / entity_code
    actuals_path = entity_dir / "model_julia_actuals.json"
    v2_path = entity_dir / "model_julia_v2.json"

    # Also check for v3 models (when training step is implemented)
    v3_path = entity_dir / "model_v3.json"

    fallback_ratio = fallback_ratios.get(entity_code, fallback_ratios.get("__global__", 0.678))

    if v3_path.exists():
        # v3 model (future)
        model = xgb.XGBRegressor()
        model.load_model(str(v3_path))
        meta = _read_metadata(entity_dir, "metadata_v3.json")
        features = FEATURES_ACTUALS
        method = "model_v3"

    elif actuals_path.exists():
        model = xgb.XGBRegressor()
        model.load_model(str(actuals_path))
        meta = _read_metadata(entity_dir, "metadata_julia_actuals.json")
        is_lite = meta and (meta.get("model_label") == "XGBOOST_ACTUALS_LITE" or meta.get("version") == "actuals_lite")
        features = FEATURES_ACTUALS_LITE if is_lite else FEATURES_ACTUALS
        method = "model_actuals"

    elif v2_path.exists():
        model = xgb.XGBRegressor()
        model.load_model(str(v2_path))
        meta = _read_metadata(entity_dir, "metadata_julia_v2.json")
        is_lite = meta and (meta.get("model_label") == "XGBOOST_LITE_MODEL" or meta.get("version") == "lite")
        features = ["posted_time", "mins_since_6am", "mins_since_open", "hour_of_day"] if is_lite else FEATURES_V2
        method = "model_v2"

    else:
        # No model — use aggregate * fallback_ratio
        def get_fallback(row):
            key = (entity_code, row["date_group_id"], row["time_slot_15min"])
            if key in agg_lookup:
                return int(round(agg_lookup[key] * fallback_ratio))
            return int(round(row["posted_time"] * fallback_ratio))

        df["predicted_actual"] = df.apply(get_fallback, axis=1)
        df["prediction_method"] = "fallback_ratio"
        return df[["entity_code", "park_date", "time_slot", "predicted_actual", "prediction_method"]]

    # Run model prediction
    X = df[features].values.astype(np.float32)
    predictions = model.predict(X)
    predictions = np.clip(predictions, 0, 300)
    df["predicted_actual"] = np.round(predictions).astype(int)
    df["prediction_method"] = method

    return df[["entity_code", "park_date", "time_slot", "predicted_actual", "prediction_method"]]


# =========================================================================
# Data loading helpers (called once at start)
# =========================================================================

def _load_date_features(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Load date_group_id, season, season_year encodings."""
    dim_dir = str(cfg.dimension_dir).replace("\\", "/")
    pairs_path = cfg.output_base / "matched_pairs" / "all_pairs_v2.parquet"
    pairs_str = str(pairs_path).replace("\\", "/")

    with read_connection() as con:
        # Load encodings from matched pairs
        dgid_enc = dict(con.execute(f"""
            SELECT DISTINCT date_group_id, date_group_id_encoded
            FROM read_parquet('{pairs_str}')
        """).fetchdf().values)

        season_enc = dict(con.execute(f"""
            SELECT DISTINCT season, season_encoded
            FROM read_parquet('{pairs_str}')
        """).fetchdf().values)

        sy_enc = dict(con.execute(f"""
            SELECT DISTINCT season_year, season_year_encoded
            FROM read_parquet('{pairs_str}')
        """).fetchdf().values)

        # Load date features
        df = con.execute(f"""
            SELECT CAST(d.park_date AS DATE) as park_date,
                   d.date_group_id, s.season, s.season_year
            FROM read_csv_auto('{dim_dir}/dimdategroupid.csv') d
            JOIN read_csv_auto('{dim_dir}/dimseason.csv') s
                ON d.park_date = s.park_date
        """).fetchdf()

    features = {}
    for _, row in df.iterrows():
        park_date = pd.Timestamp(row["park_date"]).date()
        features[park_date] = {
            "date_group_id": row["date_group_id"],
            "date_group_id_encoded": dgid_enc.get(row["date_group_id"], 0),
            "season": row["season"],
            "season_encoded": season_enc.get(row["season"], 0),
            "season_year": row["season_year"],
            "season_year_encoded": sy_enc.get(row["season_year"], 0),
        }

    log.info(f"Date features loaded: {len(features)} dates")
    return features


def _load_park_hours(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Load park hours lookup: (park_code, date) -> (open_mins, close_mins)."""
    dim_dir = str(cfg.dimension_dir).replace("\\", "/")

    with read_connection() as con:
        df = con.execute(f"""
            SELECT park, CAST(date AS DATE) as park_date,
                   opening_time_with_emh, closing_time_with_emh_or_party
            FROM read_csv_auto('{dim_dir}/dimparkhours.csv')
            WHERE opening_time_with_emh IS NOT NULL
        """).fetchdf()

    lookup = {}
    est = ZoneInfo("America/New_York")

    for _, row in df.iterrows():
        park_norm = str(row["park"]).strip().upper() if pd.notna(row["park"]) else ""
        park_date = pd.Timestamp(row["park_date"]).date()
        park_tz = PARK_TIMEZONE.get(park_norm, "America/New_York")
        zone = ZoneInfo(park_tz)

        open_mins = close_mins = None
        try:
            open_ts = pd.to_datetime(row["opening_time_with_emh"])
            if open_ts.tzinfo is None:
                open_ts = open_ts.tz_localize(est)
            open_local = open_ts.astimezone(zone)
            open_mins = int(open_local.hour * 60 + open_local.minute)
        except Exception:
            pass
        try:
            close_ts = pd.to_datetime(row["closing_time_with_emh_or_party"])
            if close_ts.tzinfo is None:
                close_ts = close_ts.tz_localize(est)
            close_local = close_ts.astimezone(zone)
            close_mins = int(close_local.hour * 60 + close_local.minute)
        except Exception:
            pass

        if open_mins is None and close_mins is None:
            continue
        if close_mins is not None and close_mins == 0:
            close_mins = 24 * 60
        if close_mins is not None and open_mins is not None and close_mins < 360 and open_mins > close_mins:
            close_mins += 24 * 60

        lookup[(park_norm, park_date)] = (open_mins, close_mins)

    log.info(f"Park hours loaded: {len(lookup)} park-dates")
    return lookup


def _load_aggregates(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Load model aggregates for posted_time estimates."""
    agg_path = cfg.output_base / "aggregates" / "model_aggregates.parquet"
    if not agg_path.exists():
        log.warning(f"No aggregates file at {agg_path}")
        return {}

    with read_connection() as con:
        df = con.execute(f"""
            SELECT entity_code, date_group_id, time_slot, wait_median
            FROM read_parquet('{str(agg_path).replace(chr(92), "/")}')
            WHERE wait_median IS NOT NULL
        """).fetchdf()

    lookup = {}
    for _, row in df.iterrows():
        lookup[(row["entity_code"], row["date_group_id"], row["time_slot"])] = row["wait_median"]

    log.info(f"Aggregates loaded: {len(lookup):,} entries")
    return lookup


def _load_entity_list(cfg: PipelineConfig, log: PipelineLogger) -> list[str]:
    """Load list of forecastable entities."""
    parquet_str = str(cfg.parquet_dir).replace("\\", "/")
    dim_str = str(cfg.dimension_dir / "dimentity.csv").replace("\\", "/")

    with read_connection() as con:
        entities = con.execute(f"""
            SELECT DISTINCT f.entity_code
            FROM read_parquet('{parquet_str}/*.parquet') f
            INNER JOIN read_csv_auto('{dim_str}') d ON f.entity_code = d.code
            WHERE f.wait_time_type = 'POSTED'
              AND f.wait_time_minutes > 0
              AND d.fastpass_booth = FALSE
        """).fetchdf()["entity_code"].tolist()

        # Add EU entities with scope_and_scale (may not have POSTED data yet)
        eu_entities = con.execute(f"""
            SELECT code as entity_code FROM read_csv_auto('{dim_str}')
            WHERE code LIKE 'EU%' AND fastpass_booth = FALSE AND scope_and_scale IS NOT NULL
        """).fetchdf()["entity_code"].tolist()

    existing = set(entities)
    for e in eu_entities:
        if e not in existing:
            entities.append(e)

    log.info(f"Entity list: {len(entities)} entities")
    return sorted(entities)


def _load_operating_calendar(cfg: PipelineConfig, log: PipelineLogger) -> set | None:
    """Load operating calendar as set of (entity_code, date) tuples."""
    oc_path = cfg.output_base / "operating_calendar" / "operating_calendar.parquet"
    if not oc_path.exists():
        log.info("No operating calendar — assuming all entities operating")
        return None

    oc_df = pd.read_parquet(oc_path)
    oc_df = oc_df[oc_df["is_operating"] == True]
    result = set(zip(
        oc_df["entity_code"].astype(str).str.upper(),
        pd.to_datetime(oc_df["park_date"]).dt.date,
    ))
    log.info(f"Operating calendar: {len(result):,} entity-dates")
    return result


def _load_fallback_ratios(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Load per-entity and global fallback ratios."""
    ratios_path = cfg.state_dir / "fallback_ratios.json"
    if not ratios_path.exists():
        log.info("No fallback_ratios.json — using default 0.678")
        return {"__global__": 0.678}

    with open(ratios_path) as f:
        ratios = json.load(f)
    log.info(f"Fallback ratios: {len(ratios)} entries")
    return ratios


# =========================================================================
# Time grid generation
# =========================================================================

def _generate_park_time_grid(
    start_date: date,
    end_date: date,
    date_features: dict,
    park_hours: dict,
    park_code: str,
    park_tz: str,
) -> pd.DataFrame | None:
    """Generate time grid for a single park's operating hours."""
    all_times = pd.date_range("00:00", "23:55", freq="5min").time
    DEFAULT_OPEN = 6 * 60
    DEFAULT_CLOSE = 24 * 60

    rows = []
    current = start_date
    while current <= end_date:
        feat = date_features.get(current, {})
        hours_key = (park_code, current)
        hours_tuple = park_hours.get(hours_key)
        day_open = hours_tuple[0] if hours_tuple and hours_tuple[0] is not None else DEFAULT_OPEN
        day_close = hours_tuple[1] if hours_tuple and hours_tuple[1] is not None else DEFAULT_CLOSE

        for t in all_times:
            current_mins = t.hour * 60 + t.minute
            if current_mins < day_open or current_mins > day_close:
                continue

            rows.append({
                "park_date": current,
                "time_slot": t,
                "time_slot_15min": t.hour * 4 + t.minute // 15,
                "hour_of_day": t.hour,
                "mins_since_6am": max(0, (t.hour - 6) * 60 + t.minute),
                "date_group_id": feat.get("date_group_id", "UNKNOWN"),
                "date_group_id_encoded": feat.get("date_group_id_encoded", 0),
                "season_encoded": feat.get("season_encoded", 0),
                "season_year_encoded": feat.get("season_year_encoded", 0),
            })

        current += timedelta(days=1)

    if not rows:
        return None
    return pd.DataFrame(rows)


def _read_metadata(model_dir: Path, filename: str) -> dict | None:
    """Read model metadata JSON."""
    path = model_dir / filename
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None
