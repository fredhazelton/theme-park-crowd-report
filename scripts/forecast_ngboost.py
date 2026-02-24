#!/usr/bin/env python3
"""
NGBoost Forecast Generation

Generates forecasts using NGBoost heteroscedastic models. Outputs both
predicted_wait (mean) AND predicted_std (uncertainty) for each entity
at each time slot.

Output: /mnt/data/pipeline/curves/forecast_parquet/ngboost_forecasts.parquet
Schema: entity_code, park_date, time_slot, predicted_wait, predicted_std, prediction_method

Usage:
    python scripts/forecast_ngboost.py
    python scripts/forecast_ngboost.py --entities MK01 MK05 MK191
    python scripts/forecast_ngboost.py --days 30 --workers 4
"""

import argparse
import json
import logging
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# Ensure src is on path
if str(Path(__file__).resolve().parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils.forecast_horizon import get_forecast_end_date
from utils.park_code import entity_code_to_park_code

# Constants
DEFAULT_WORKERS = 8
BATCH_SIZE = 50

# Park code -> timezone (same as forecast_vectorized.py)
PARK_TIMEZONE: dict[str, str] = {
    "TDL": "Asia/Tokyo",
    "TDS": "Asia/Tokyo",
    "MK": "America/New_York",
    "EP": "America/New_York",
    "HS": "America/New_York",
    "AK": "America/New_York",
    "BB": "America/New_York",
    "TL": "America/New_York",
    "DL": "America/Los_Angeles",
    "CA": "America/Los_Angeles",
    "IA": "America/New_York",
    "UF": "America/New_York",
    "EU": "America/New_York",
    "UH": "America/Los_Angeles",
}

# Paths
OUTPUT_BASE = Path("/mnt/data/pipeline")
MODELS_DIR = OUTPUT_BASE / "models"
FORECAST_DIR = OUTPUT_BASE / "curves" / "forecast_parquet"
LOGS_DIR = OUTPUT_BASE / "logs"


def setup_logging(log_dir: Path | None = None) -> logging.Logger:
    log_dir = log_dir or LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"forecast_ngboost_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


def generate_time_grid(
    start_date: date,
    end_date: date,
    date_features: dict,
    park_hours: dict,
) -> pd.DataFrame:
    """Generate 5-minute time slots for date range, same as forecast_vectorized.py."""
    dates = pd.date_range(start_date, end_date, freq="D")
    all_times = pd.date_range("00:00", "23:55", freq="5min").time

    DEFAULT_OPEN_MINS = 6 * 60
    DEFAULT_CLOSE_MINS = 24 * 60

    rows = []
    for d in dates:
        park_date = d.date()
        feat = date_features.get(park_date, {})
        date_group_id = feat.get("date_group_id", "UNKNOWN")
        date_group_id_encoded = feat.get("date_group_id_encoded", 0)
        season_encoded = feat.get("season_encoded", 0)
        season_year_encoded = feat.get("season_year_encoded", 0)

        # Widest operating window across all parks for this date
        day_open = DEFAULT_OPEN_MINS
        day_close = DEFAULT_CLOSE_MINS
        park_opens = []
        park_closes = []
        for (park, pd_date), (open_m, close_m) in park_hours.items():
            if pd_date == park_date:
                if open_m is not None:
                    park_opens.append(open_m)
                if close_m is not None:
                    park_closes.append(close_m)
        if park_opens:
            day_open = max(0, min(park_opens))
        if park_closes:
            day_close = min(24 * 60, max(park_closes))

        for t in all_times:
            dt = datetime.combine(park_date, t)
            hour = dt.hour
            minute = dt.minute
            current_mins = hour * 60 + minute

            if current_mins < day_open or current_mins > day_close:
                continue

            mins_since_6am = max(0, (hour - 6) * 60 + minute)
            time_slot_15min = hour * 4 + minute // 15

            rows.append(
                {
                    "park_date": park_date,
                    "time_slot": t,
                    "time_slot_15min": time_slot_15min,
                    "hour_of_day": hour,
                    "mins_since_6am": mins_since_6am,
                    "date_group_id": date_group_id,
                    "date_group_id_encoded": date_group_id_encoded,
                    "season_encoded": season_encoded,
                    "season_year_encoded": season_year_encoded,
                }
            )

    return pd.DataFrame(rows)


def forecast_entity(args) -> tuple:
    """Generate NGBoost forecast for a single entity."""
    (
        entity_code,
        time_grid,
        models_dir,
        agg_lookup,
        park_hours_lookup,
    ) = args

    try:
        # Load model and metadata
        entity_dir = models_dir / entity_code
        model_path = entity_dir / "ngboost_model.pkl"
        metadata_path = entity_dir / "ngboost_metadata.json"

        if not model_path.exists():
            return (entity_code, None, "no_ngboost_model")

        with open(model_path, "rb") as f:
            model = pickle.load(f)

        with open(metadata_path) as f:
            metadata = json.load(f)

        features = metadata["features"]
        uses_posted = metadata.get("uses_posted_time", "posted_time" in features)

        df = time_grid.copy()
        df["entity_code"] = entity_code

        park_code = entity_code_to_park_code(entity_code)

        # Filter to this park's operating hours
        def is_within_park_hours(row):
            key = (park_code, row["park_date"])
            hours_tuple = park_hours_lookup.get(key)
            if hours_tuple is not None:
                open_mins, close_mins = hours_tuple
                current_mins = (
                    row["hour_of_day"] * 60
                    + (row["time_slot"].minute if hasattr(row["time_slot"], "minute") else 0)
                )
                if open_mins is not None and close_mins is not None:
                    return open_mins <= current_mins <= close_mins
            return True

        mask = df.apply(is_within_park_hours, axis=1)
        df = df[mask].reset_index(drop=True)

        if len(df) == 0:
            return (entity_code, None, "no_operating_slots")

        # Get posted_time estimates from aggregates if needed
        if uses_posted:

            def get_posted_estimate(row):
                key = (entity_code, row["date_group_id"], row["time_slot_15min"])
                return agg_lookup.get(key, 5.0)

            df["posted_time"] = df.apply(get_posted_estimate, axis=1)

        # Get mins_since_open
        def get_mins_since_open(row):
            key = (park_code, row["park_date"])
            hours_tuple = park_hours_lookup.get(key)
            if hours_tuple is not None:
                opening_mins = hours_tuple[0] if isinstance(hours_tuple, tuple) else hours_tuple
                if opening_mins is not None:
                    current_mins = (
                        row["hour_of_day"] * 60
                        + (
                            row["time_slot"].minute
                            if hasattr(row["time_slot"], "minute")
                            else 0
                        )
                    )
                    return max(0, current_mins - opening_mins)
            return row["mins_since_6am"]

        df["mins_since_open"] = df.apply(get_mins_since_open, axis=1)

        # Build feature matrix
        X = df[features].values.astype(np.float32)

        # Predict distribution
        y_dist = model.pred_dist(X)
        y_mean = y_dist.mean()
        y_std = y_dist.std()

        # Clip predictions
        y_mean = np.clip(y_mean, 0, 300)
        y_std = np.clip(y_std, 0.1, 200)  # Floor std at 0.1 to avoid zeros

        result = pd.DataFrame(
            {
                "entity_code": entity_code,
                "park_date": df["park_date"],
                "time_slot": df["time_slot"],
                "predicted_wait": np.round(y_mean, 1),
                "predicted_std": np.round(y_std, 2),
                "predicted_actual": np.round(y_mean).astype(int),  # Compat column
                "prediction_method": "ngboost",
            }
        )

        return (entity_code, result, "OK")

    except Exception as e:
        import traceback

        return (entity_code, None, f"{str(e)[:100]}\n{traceback.format_exc()[:200]}")


def main():
    parser = argparse.ArgumentParser(description="NGBoost forecast generation")
    parser.add_argument("--output-base", type=Path, default=OUTPUT_BASE)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--days", type=int, default=None, help="Days to forecast")
    parser.add_argument("--entities", nargs="+", help="Forecast only these entities")
    parser.add_argument("--max-entities", type=int, help="Limit entities (testing)")
    args = parser.parse_args()

    output_base = args.output_base.resolve()
    models_dir = output_base / "models"
    forecast_dir = output_base / "curves" / "forecast_parquet"

    logger = setup_logging(output_base / "logs")

    logger.info("=" * 60)
    logger.info("NGBOOST FORECAST GENERATION")
    logger.info("=" * 60)

    start_time = time.time()

    # Date range
    start_date = date.today() + timedelta(days=1)
    if args.days is not None:
        end_date = start_date + timedelta(days=args.days)
        logger.info(f"Date range: {start_date} to {end_date} ({args.days} days, CLI override)")
    else:
        end_date = get_forecast_end_date()
        forecast_days = (end_date - start_date).days
        logger.info(f"Date range: {start_date} to {end_date} ({forecast_days} days, global horizon)")
    logger.info(f"Workers: {args.workers}")

    import duckdb

    con = duckdb.connect()

    # Load operating calendar
    oc_path = output_base / "operating_calendar" / "operating_calendar.parquet"
    operating_by_entity: dict[str, set] = {}
    all_calendar_entities: set[str] = set()
    if oc_path.exists():
        try:
            oc_df = pd.read_parquet(oc_path)
            oc_operating = oc_df[oc_df["is_operating"] == True]
            for ec, d in zip(
                oc_operating["entity_code"].astype(str).str.upper(),
                pd.to_datetime(oc_operating["park_date"]).dt.date,
            ):
                operating_by_entity.setdefault(ec, set()).add(d)
            all_calendar_entities = set(oc_df["entity_code"].astype(str).str.upper().unique())
            logger.info(
                f"Operating calendar: {len(operating_by_entity)} entities with operating dates"
            )
        except Exception as e:
            logger.warning(f"Could not load operating calendar: {e}")
    else:
        logger.info("Operating calendar not found; assuming all operating")

    # Load encodings
    logger.info("Loading encodings...")
    matched_pairs_path = str(
        (output_base / "matched_pairs" / "all_pairs_v2.parquet").resolve()
    )

    dgid_enc = con.execute(
        f"SELECT DISTINCT date_group_id, date_group_id_encoded FROM read_parquet('{matched_pairs_path}')"
    ).fetchdf()
    dgid_to_encoded = dict(zip(dgid_enc["date_group_id"], dgid_enc["date_group_id_encoded"]))

    season_enc = con.execute(
        f"SELECT DISTINCT season, season_encoded FROM read_parquet('{matched_pairs_path}')"
    ).fetchdf()
    season_to_encoded = dict(zip(season_enc["season"], season_enc["season_encoded"]))

    sy_enc = con.execute(
        f"SELECT DISTINCT season_year, season_year_encoded FROM read_parquet('{matched_pairs_path}')"
    ).fetchdf()
    sy_to_encoded = dict(zip(sy_enc["season_year"], sy_enc["season_year_encoded"]))

    # Load date features
    logger.info("Loading date features...")
    dim_dir = str((output_base / "dimension_tables").resolve())
    date_features_df = con.execute(
        f"""
        SELECT
            CAST(d.park_date AS DATE) as park_date,
            d.date_group_id,
            s.season,
            s.season_year
        FROM read_csv_auto('{dim_dir}/dimdategroupid.csv') d
        JOIN read_csv_auto('{dim_dir}/dimseason.csv') s
            ON d.park_date = s.park_date
    """
    ).fetchdf()

    date_features = {}
    for _, row in date_features_df.iterrows():
        park_date = pd.Timestamp(row["park_date"]).date()
        dgid = row["date_group_id"]
        season = row["season"]
        season_year = row["season_year"]
        date_features[park_date] = {
            "date_group_id": dgid,
            "date_group_id_encoded": dgid_to_encoded.get(dgid, 0),
            "season": season,
            "season_encoded": season_to_encoded.get(season, 0),
            "season_year": season_year,
            "season_year_encoded": sy_to_encoded.get(season_year, 0),
        }
    logger.info(f"  Loaded features for {len(date_features)} dates")

    # Load park hours
    logger.info("Loading park hours...")
    park_hours_df = con.execute(
        f"""
        SELECT
            park,
            CAST(date AS DATE) as park_date,
            opening_time_with_emh,
            closing_time_with_emh_or_party
        FROM read_csv_auto('{dim_dir}/dimparkhours.csv')
        WHERE opening_time_with_emh IS NOT NULL
    """
    ).fetchdf()

    park_hours_lookup = {}
    est = ZoneInfo("America/New_York")
    for _, row in park_hours_df.iterrows():
        park_norm = str(row["park"]).strip().upper() if pd.notna(row["park"]) else ""
        park_date = pd.Timestamp(row["park_date"]).date()
        park_tz = PARK_TIMEZONE.get(park_norm, "America/New_York")
        zone = ZoneInfo(park_tz)
        open_mins = None
        close_mins = None
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
        if (
            close_mins is not None
            and close_mins < 360
            and open_mins is not None
            and open_mins > close_mins
        ):
            close_mins += 24 * 60
        park_hours_lookup[(park_norm, park_date)] = (open_mins, close_mins)
    logger.info(f"  Loaded {len(park_hours_lookup)} park-date hours")

    # Load aggregates for posted_time estimates
    logger.info("Loading model aggregates...")
    agg_path = str((output_base / "aggregates" / "model_aggregates.parquet").resolve())
    agg_df = con.execute(
        f"SELECT entity_code, date_group_id, time_slot, wait_median FROM read_parquet('{agg_path}') WHERE wait_median IS NOT NULL"
    ).fetchdf()
    agg_df = agg_df.set_index(["entity_code", "date_group_id", "time_slot"])
    agg_lookup = agg_df["wait_median"].to_dict()
    logger.info(f"  Loaded {len(agg_lookup)} aggregate entries")

    # Get entity list: entities with NGBoost models
    if args.entities:
        entities = sorted(args.entities)
        logger.info(f"CLI entity filter: {entities}")
    else:
        # Find all entities with ngboost_model.pkl
        entities = sorted(
            d.name
            for d in models_dir.iterdir()
            if d.is_dir() and (d / "ngboost_model.pkl").exists()
        )
        logger.info(f"Found {len(entities)} entities with NGBoost models")

    con.close()

    if args.max_entities:
        entities = entities[: args.max_entities]
        logger.info(f"Limited to {len(entities)} entities (--max-entities)")

    # Generate time grid
    logger.info("Generating time grid...")
    time_grid_full = generate_time_grid(start_date, end_date, date_features, park_hours_lookup)
    logger.info(f"  Grid: {len(time_grid_full):,} time slots")

    def get_entity_time_grid(entity_code: str):
        if not operating_by_entity:
            return time_grid_full
        ec_upper = str(entity_code).upper()
        entity_dates = operating_by_entity.get(ec_upper)
        if not entity_dates:
            if ec_upper in all_calendar_entities:
                return None
            return time_grid_full
        return time_grid_full[time_grid_full["park_date"].isin(entity_dates)]

    # Process entities in batches
    forecast_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = forecast_dir / "_temp_ngboost_batches"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Pre-filter extinct entities
    entity_queue = []
    skipped_extinct = 0
    for entity in entities:
        ec_upper = str(entity).upper()
        if operating_by_entity:
            entity_dates = operating_by_entity.get(ec_upper)
            if not entity_dates and ec_upper in all_calendar_entities:
                skipped_extinct += 1
                continue
        entity_queue.append(entity)

    if skipped_extinct:
        logger.info(f"Skipped {skipped_extinct} extinct/closed entities")

    total_entities = len(entity_queue)
    logger.info(f"Processing {total_entities} entities...")

    batch_files = []
    successful = 0
    failed = 0
    no_model = 0
    processed = 0

    for batch_start in range(0, total_entities, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, total_entities)
        batch_entities = entity_queue[batch_start:batch_end]

        work_items = []
        for entity in batch_entities:
            grid = get_entity_time_grid(entity)
            if grid is None or (hasattr(grid, "__len__") and len(grid) == 0):
                continue
            work_items.append(
                (entity, grid, models_dir, agg_lookup, park_hours_lookup)
            )

        batch_results = []
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(forecast_entity, item): item[0] for item in work_items}

            for future in as_completed(futures):
                entity = futures[future]
                entity_code, result_df, msg = future.result()

                if result_df is not None:
                    batch_results.append(result_df)
                    successful += 1
                elif msg == "no_ngboost_model":
                    no_model += 1
                else:
                    failed += 1
                    logger.warning(f"  {entity_code}: {msg}")

        if batch_results:
            batch_df = pd.concat(batch_results, ignore_index=True)
            batch_file = temp_dir / f"batch_{batch_start:04d}.parquet"
            batch_df.to_parquet(batch_file, index=False)
            batch_files.append(batch_file)
            del batch_df, batch_results

        processed += len(batch_entities)
        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        logger.info(
            f"  Progress: {processed}/{total_entities} "
            f"({rate:.1f} entities/sec, {elapsed / 60:.1f} min)"
        )

    # Combine batch files
    logger.info(f"Combining {len(batch_files)} batch files...")
    if batch_files:
        chunks = [pd.read_parquet(f) for f in batch_files]
        combined = pd.concat(chunks, ignore_index=True)
        del chunks

        output_file = forecast_dir / "ngboost_forecasts.parquet"
        combined.to_parquet(output_file, index=False)

        # Stats
        total_predictions = len(combined)
        logger.info(f"  Saved {total_predictions:,} predictions to {output_file}")
        logger.info(f"  File size: {output_file.stat().st_size / 1024 / 1024:.1f} MB")
        logger.info(
            f"  predicted_wait: "
            f"mean={combined['predicted_wait'].mean():.1f}, "
            f"std={combined['predicted_wait'].std():.1f}, "
            f"min={combined['predicted_wait'].min():.1f}, "
            f"max={combined['predicted_wait'].max():.1f}"
        )
        logger.info(
            f"  predicted_std:  "
            f"mean={combined['predicted_std'].mean():.2f}, "
            f"median={combined['predicted_std'].median():.2f}, "
            f"min={combined['predicted_std'].min():.2f}, "
            f"max={combined['predicted_std'].max():.2f}"
        )

        del combined

        # Clean up temp files
        for f in batch_files:
            f.unlink()
        temp_dir.rmdir()
    else:
        total_predictions = 0

    elapsed = time.time() - start_time

    logger.info("")
    logger.info("=" * 60)
    logger.info("NGBOOST FORECAST COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Successful: {successful}")
    logger.info(f"No model: {no_model}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Total predictions: {total_predictions:,}")
    logger.info(f"Time: {elapsed:.1f}s ({elapsed / 60:.1f} min)")
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
