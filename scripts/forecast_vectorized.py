#!/usr/bin/env python3
"""
Vectorized Forecast Generation - V2

Generates 2-year forecasts for all entities using V2 models with:
- posted_time (estimated from aggregates)
- mins_since_6am, mins_since_open, hour_of_day
- date_group_id_encoded, season_encoded, season_year_encoded

Usage:
    python scripts/forecast_vectorized.py [--days N] [--workers N]
"""

import argparse
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

# Ensure src is on path for utils import
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from utils.park_code import entity_code_to_park_code
import pandas as pd

try:
    import xgboost as xgb
except ImportError:
    xgb = None

# Constants
DEFAULT_WORKERS = 8
SLOTS_PER_DAY = 288  # 5-minute intervals
DEFAULT_FALLBACK_RATIO = 0.678  # Fallback if ratios file missing; overridden by state/fallback_ratios.json

# Park code -> IANA timezone (for converting dimparkhours EST timestamps to local time)
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
OUTPUT_BASE = Path("/home/wilma/hazeydata/pipeline")
MODELS_DIR = OUTPUT_BASE / "models"
FORECAST_DIR = OUTPUT_BASE / "curves" / "forecast_parquet"
LOGS_DIR = OUTPUT_BASE / "logs"


def setup_logging(log_dir: Path | None = None):
    log_dir = log_dir or LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"forecast_vectorized_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


def generate_time_grid(start_date: date, end_date: date, date_features: dict, park_hours: dict) -> pd.DataFrame:
    """Generate time slots for date range, constrained to park operating hours.
    
    Only generates slots between earliest open (incl. early entry) and latest
    close (incl. evening extras/parties) for each park-date. Falls back to
    6am-midnight if park hours are unavailable for a date.
    
    park_hours: dict mapping (park_code, date) -> (open_mins, close_mins)
    """
    dates = pd.date_range(start_date, end_date, freq='D')
    all_times = pd.date_range('00:00', '23:55', freq='5min').time
    
    # Default fallback: 6am to midnight (conservative)
    DEFAULT_OPEN_MINS = 6 * 60    # 06:00
    DEFAULT_CLOSE_MINS = 24 * 60  # midnight
    
    rows = []
    for d in dates:
        park_date = d.date()
        
        # Get date features
        feat = date_features.get(park_date, {})
        date_group_id = feat.get('date_group_id', 'UNKNOWN')
        date_group_id_encoded = feat.get('date_group_id_encoded', 0)
        season = feat.get('season', 'UNKNOWN')
        season_encoded = feat.get('season_encoded', 0)
        season_year = feat.get('season_year', 'UNKNOWN')
        season_year_encoded = feat.get('season_year_encoded', 0)
        
        # Determine operating window across ALL parks for this date
        # (we use the widest window since entities from different parks 
        #  will be filtered by their own park's hours in forecast_entity)
        day_open = DEFAULT_OPEN_MINS
        day_close = DEFAULT_CLOSE_MINS
        
        # Find earliest open and latest close across all parks for this date
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
            
            # Skip time slots outside operating window
            if current_mins < day_open or current_mins > day_close:
                continue
            
            mins_since_6am = max(0, (hour - 6) * 60 + minute)
            
            # 15-min time slot for aggregate lookup
            time_slot_15min = hour * 4 + minute // 15
            
            rows.append({
                'park_date': park_date,
                'time_slot': t,
                'time_slot_15min': time_slot_15min,
                'hour_of_day': hour,
                'mins_since_6am': mins_since_6am,
                'date_group_id': date_group_id,
                'date_group_id_encoded': date_group_id_encoded,
                'season_encoded': season_encoded,
                'season_year_encoded': season_year_encoded,
            })
    
    return pd.DataFrame(rows)


def forecast_entity(args) -> tuple:
    """Generate forecast for single entity using V2 model."""
    (entity_code, time_grid, models_dir, fallback_ratio,
     agg_lookup, park_hours_lookup, p95_cap) = args

    try:
        df = time_grid.copy()
        df['entity_code'] = entity_code
        
        # Extract park code from entity (handles TDL, TDS, USH correctly)
        park_code = entity_code_to_park_code(entity_code)
        
        # Filter time grid to this park's operating hours per day
        def is_within_park_hours(row):
            key = (park_code, row['park_date'])
            hours_tuple = park_hours_lookup.get(key)
            if hours_tuple is not None:
                open_mins, close_mins = hours_tuple
                current_mins = row['hour_of_day'] * 60 + (row['time_slot'].minute if hasattr(row['time_slot'], 'minute') else 0)
                if open_mins is not None and close_mins is not None:
                    return open_mins <= current_mins <= close_mins
            return True  # Keep all slots if no park hours available
        
        mask = df.apply(is_within_park_hours, axis=1)
        df = df[mask].reset_index(drop=True)
        
        if len(df) == 0:
            return (entity_code, None, "no_operating_slots")
        
        # Get estimated posted_time from aggregates for each row
        def get_posted_estimate(row):
            key = (entity_code, row['date_group_id'], row['time_slot_15min'])
            return agg_lookup.get(key, 5.0)  # Default 5 if no data (sparse entities are low-wait)
        
        df['posted_time'] = df.apply(get_posted_estimate, axis=1)
        
        # Get mins_since_open from park hours
        def get_mins_since_open(row):
            key = (park_code, row['park_date'])
            hours_tuple = park_hours_lookup.get(key)
            if hours_tuple is not None:
                opening_mins = hours_tuple[0] if isinstance(hours_tuple, tuple) else hours_tuple
                if opening_mins is not None:
                    current_mins = row['hour_of_day'] * 60 + (row['time_slot'].minute if hasattr(row['time_slot'], 'minute') else 0)
                    return max(0, current_mins - opening_mins)
            return row['mins_since_6am']  # Fallback
        
        df['mins_since_open'] = df.apply(get_mins_since_open, axis=1)
        
        # Check for actuals-only model first (ACTUALS-FIRST), then V2
        actuals_model_path = models_dir / entity_code / "model_julia_actuals.json"
        v2_model_path = models_dir / entity_code / "model_julia_v2.json"

        if actuals_model_path.exists():
            # Actuals-only model: 5 features, NO posted_time
            model = xgb.XGBRegressor()
            model.load_model(str(actuals_model_path))
            import json as _json
            metadata_path = models_dir / entity_code / "metadata_julia_actuals.json"
            is_actuals_lite = False
            if metadata_path.exists():
                try:
                    with open(metadata_path) as _mf:
                        meta = _json.load(_mf)
                    is_actuals_lite = meta.get("model_label") == "XGBOOST_ACTUALS_LITE" or meta.get("version") == "actuals_lite"
                except Exception:
                    pass
            if is_actuals_lite:
                feature_cols = ['mins_since_6am', 'mins_since_open']
            else:
                feature_cols = ['mins_since_6am', 'mins_since_open', 'date_group_id_encoded', 'season_encoded', 'season_year_encoded']
            X = df[feature_cols].values.astype(np.float32)
            predictions = model.predict(X)
            predictions = np.clip(predictions, 0, 300)
            df['predicted_actual'] = np.round(predictions).astype(int)
            df['prediction_method'] = 'model_actuals'
        elif v2_model_path.exists():
            # V2 model: uses posted_time
            model = xgb.XGBRegressor()
            model.load_model(str(v2_model_path))
            import json as _json
            metadata_path = models_dir / entity_code / "metadata_julia_v2.json"
            is_lite = False
            if metadata_path.exists():
                try:
                    with open(metadata_path) as _mf:
                        meta = _json.load(_mf)
                    is_lite = meta.get("model_label") == "XGBOOST_LITE_MODEL" or meta.get("version") == "lite"
                except Exception:
                    pass
            if is_lite:
                feature_cols = ['posted_time', 'mins_since_6am', 'mins_since_open', 'hour_of_day']
                method_label = 'model_lite'
            else:
                feature_cols = [
                    'posted_time', 'mins_since_6am', 'mins_since_open',
                    'hour_of_day', 'date_group_id_encoded',
                    'season_encoded', 'season_year_encoded'
                ]
                method_label = 'model_v2'
            X = df[feature_cols].values.astype(np.float32)
            predictions = model.predict(X)
            predictions = np.clip(predictions, 0, 300)
            df['predicted_actual'] = np.round(predictions).astype(int)
            df['prediction_method'] = method_label
        else:
            # No model - use aggregate posted median × ratio to estimate actual
            def get_fallback(row):
                key = (entity_code, row['date_group_id'], row['time_slot_15min'])
                if key in agg_lookup:
                    # Aggregate median is a POSTED time — apply ratio to convert to predicted actual
                    return agg_lookup[key] * fallback_ratio, 'aggregate'
                # Ultimate fallback: default posted estimate × ratio
                return row['posted_time'] * fallback_ratio, 'fallback_ratio'
            
            results = df.apply(get_fallback, axis=1)
            df['predicted_actual'] = results.apply(lambda x: int(round(x[0])))
            df['prediction_method'] = results.apply(lambda x: x[1])
        
        # P95 cap REMOVED (2026-02-18, Fred's decision):
        # Models tend to underpredict, and XGBoost is impervious to outliers.
        # Capping at p95 was artificially limiting predictions on busy days.
        cap_method = ""
        
        # Select output columns
        result = df[['entity_code', 'park_date', 'time_slot', 'predicted_actual', 'prediction_method']].copy()
        
        return entity_code, result, f"OK{cap_method}"
    
    except Exception as e:
        import traceback
        return entity_code, None, f"{str(e)[:100]}\n{traceback.format_exc()[:200]}"


def main():
    parser = argparse.ArgumentParser(description="Vectorized forecast generation (V2)")
    parser.add_argument("--output-base", type=Path, default=OUTPUT_BASE, help="Pipeline output base")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Parallel workers")
    parser.add_argument("--days", type=int, default=730, help="Days to forecast")
    parser.add_argument("--max-entities", type=int, help="Limit entities (testing)")
    args = parser.parse_args()

    output_base = Path(args.output_base).resolve()
    models_dir = output_base / "models"
    forecast_dir = output_base / "curves" / "forecast_parquet"

    logger = setup_logging(output_base / "logs")

    logger.info("=" * 60)
    logger.info("VECTORIZED FORECAST GENERATION (V2)")
    logger.info("=" * 60)

    start_time = time.time()

    # Date range
    start_date = date.today() + timedelta(days=1)
    end_date = start_date + timedelta(days=args.days)

    logger.info(f"Output base: {output_base}")
    logger.info(f"Date range: {start_date} to {end_date} ({args.days} days)")
    logger.info(f"Workers: {args.workers}")

    import duckdb
    con = duckdb.connect()

    # Load operating calendar (graceful fallback: assume all operating if missing)
    oc_path = output_base / "operating_calendar" / "operating_calendar.parquet"
    operating_set = set()
    operating_by_entity = {}  # Pre-indexed: entity_code -> set of dates
    if oc_path.exists():
        try:
            oc_df = pd.read_parquet(oc_path)
            oc_df = oc_df[oc_df["is_operating"] == True]
            oc_df["entity_upper"] = oc_df["entity_code"].astype(str).str.upper()
            oc_df["date_val"] = pd.to_datetime(oc_df["park_date"]).dt.date
            operating_set = set(zip(oc_df["entity_upper"], oc_df["date_val"]))
            # Build per-entity index for fast lookup
            for ec, d in zip(oc_df["entity_upper"], oc_df["date_val"]):
                if ec not in operating_by_entity:
                    operating_by_entity[ec] = set()
                operating_by_entity[ec].add(d)
            logger.info(f"Operating calendar: {len(operating_set):,} operating entity-dates ({len(operating_by_entity)} entities)")
        except Exception as e:
            logger.warning(f"Could not load operating calendar: {e}; assuming all operating")
    else:
        logger.info("Operating calendar not found; assuming all entities operating")
    
    # Load encodings from matched pairs
    logger.info("Loading encodings from matched pairs...")
    matched_pairs_path = str((output_base / "matched_pairs" / "all_pairs_v2.parquet").resolve())

    # date_group_id encodings
    dgid_enc = con.execute(f"""
        SELECT DISTINCT date_group_id, date_group_id_encoded
        FROM read_parquet('{matched_pairs_path}')
    """).fetchdf()
    dgid_to_encoded = dict(zip(dgid_enc['date_group_id'], dgid_enc['date_group_id_encoded']))
    
    # season encodings
    season_enc = con.execute(f"""
        SELECT DISTINCT season, season_encoded
        FROM read_parquet('{matched_pairs_path}')
    """).fetchdf()
    season_to_encoded = dict(zip(season_enc['season'], season_enc['season_encoded']))
    
    # season_year encodings
    sy_enc = con.execute(f"""
        SELECT DISTINCT season_year, season_year_encoded
        FROM read_parquet('{matched_pairs_path}')
    """).fetchdf()
    sy_to_encoded = dict(zip(sy_enc['season_year'], sy_enc['season_year_encoded']))
    
    logger.info(f"  date_group_id encodings: {len(dgid_to_encoded)}")
    logger.info(f"  season encodings: {len(season_to_encoded)}")
    logger.info(f"  season_year encodings: {len(sy_to_encoded)}")
    
    # Load date features (date_group_id + season)
    logger.info("Loading date features...")
    dim_dir = str((output_base / "dimension_tables").resolve())
    date_features_df = con.execute(f"""
        SELECT 
            CAST(d.park_date AS DATE) as park_date,
            d.date_group_id,
            s.season,
            s.season_year
        FROM read_csv_auto('{dim_dir}/dimdategroupid.csv') d
        JOIN read_csv_auto('{dim_dir}/dimseason.csv') s
            ON d.park_date = s.park_date
    """).fetchdf()
    
    date_features = {}
    for _, row in date_features_df.iterrows():
        park_date = pd.Timestamp(row['park_date']).date()
        dgid = row['date_group_id']
        season = row['season']
        season_year = row['season_year']
        
        date_features[park_date] = {
            'date_group_id': dgid,
            'date_group_id_encoded': dgid_to_encoded.get(dgid, 0),
            'season': season,
            'season_encoded': season_to_encoded.get(season, 0),
            'season_year': season_year,
            'season_year_encoded': sy_to_encoded.get(season_year, 0),
        }
    logger.info(f"  Loaded features for {len(date_features)} dates")
    
    # Load park hours (earliest open with early entry, latest close with extras)
    # Timestamps in dimparkhours are stored as EST; convert to each park's local timezone
    # before extracting hour/minute (fixes Tokyo TDL/TDS which had wrong hour extraction)
    logger.info("Loading park hours...")
    park_hours_df = con.execute(f"""
        SELECT 
            park,
            CAST(date AS DATE) as park_date,
            opening_time_with_emh,
            closing_time_with_emh_or_party
        FROM read_csv_auto('{dim_dir}/dimparkhours.csv')
        WHERE opening_time_with_emh IS NOT NULL
    """).fetchdf()
    
    park_hours_lookup = {}
    for _, row in park_hours_df.iterrows():
        park_norm = str(row["park"]).strip().upper() if pd.notna(row["park"]) else ""
        park_date = pd.Timestamp(row["park_date"]).date()
        park_tz = PARK_TIMEZONE.get(park_norm, "America/New_York")
        zone = ZoneInfo(park_tz)
        open_mins = None
        close_mins = None
        # dimparkhours timestamps are EST; convert to park local before extracting
        est = ZoneInfo("America/New_York")
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
        # Handle midnight+ closing (closing_mins=0 means midnight, treat as 24*60)
        if close_mins is not None and close_mins == 0:
            close_mins = 24 * 60
        # Handle next-day close (e.g., 1am = 60 mins → should be 25*60=1500)
        if close_mins is not None and close_mins < 360 and open_mins is not None and open_mins > close_mins:
            close_mins += 24 * 60
        key = (park_norm, park_date)
        park_hours_lookup[key] = (open_mins, close_mins)
    logger.info(f"  Loaded {len(park_hours_lookup)} park-date hours")
    
    # Load model aggregates for posted_time estimates and fallback
    logger.info("Loading model aggregates...")
    agg_path = str((output_base / "aggregates" / "model_aggregates.parquet").resolve())
    agg_df = con.execute(f"""
        SELECT entity_code, date_group_id, time_slot, wait_median
        FROM read_parquet('{agg_path}')
        WHERE wait_median IS NOT NULL
    """).fetchdf()
    agg_df = agg_df.set_index(['entity_code', 'date_group_id', 'time_slot'])
    agg_lookup = agg_df['wait_median'].to_dict()
    logger.info(f"  Loaded {len(agg_lookup)} aggregate entries")
    
    # P95 cap removed (2026-02-18) — models underpredict, no need to cap
    
    # Get entity list (exclude fastpass_booth / Lightning Lane entities)
    logger.info("Getting entity list...")
    parquet_path = str((output_base / "fact_tables" / "parquet").resolve())
    dim_entity_path = str((output_base / "dimension_tables" / "dimentity.csv").resolve())
    entity_list = con.execute(f"""
        SELECT DISTINCT f.entity_code
        FROM read_parquet('{parquet_path}/*.parquet') f
        INNER JOIN read_csv_auto('{dim_entity_path}') d ON f.entity_code = d.code
        WHERE f.wait_time_type = 'POSTED' 
          AND f.wait_time_minutes > 0
          AND d.fastpass_booth = FALSE
    """).fetchdf()['entity_code'].tolist()
    logger.info(f"  Excluded FastPass/Lightning Lane booth entities (fastpass_booth=TRUE)")
    
    con.close()
    
    # Count models
    entities_with_models = set()
    for d in models_dir.iterdir():
        if d.is_dir() and (d / "model_julia_v2.json").exists():
            entities_with_models.add(d.name)
    
    logger.info(f"Total entities: {len(entity_list)} ({len(entities_with_models)} with V2 models)")

    # Load dynamic fallback ratios (per-entity + global)
    import json
    ratios_path = output_base / "state" / "fallback_ratios.json"
    if ratios_path.exists():
        with open(ratios_path) as f:
            fallback_ratios = json.load(f)
        global_ratio = fallback_ratios.pop("__global__", DEFAULT_FALLBACK_RATIO)
        logger.info(f"Loaded fallback ratios: {len(fallback_ratios)} per-entity, global={global_ratio:.3f}")
    else:
        fallback_ratios = {}
        global_ratio = DEFAULT_FALLBACK_RATIO
        logger.warning(f"No fallback_ratios.json found, using default {global_ratio}")
    
    entities = sorted(entity_list)
    if args.max_entities:
        entities = entities[:args.max_entities]
    
    # Generate time grid
    logger.info("Generating time grid...")
    time_grid_full = generate_time_grid(start_date, end_date, date_features, park_hours_lookup)
    logger.info(f"  Grid: {len(time_grid_full):,} time slots")

    # Build set of ALL entities in operating calendar (regardless of operating status)
    all_calendar_entities = set()
    if oc_path.exists():
        try:
            oc_all = pd.read_parquet(oc_path, columns=["entity_code"])
            all_calendar_entities = set(oc_all["entity_code"].astype(str).str.upper().unique())
            logger.info(f"Operating calendar covers {len(all_calendar_entities)} entities")
        except Exception as e:
            logger.warning(f"Could not load entity list from operating calendar: {e}")

    # Filter time grid per entity by operating calendar (uses pre-indexed dict)
    def get_entity_time_grid(entity_code: str):
        if not operating_by_entity:
            return time_grid_full
        ec_upper = str(entity_code).upper()
        entity_dates = operating_by_entity.get(ec_upper)
        if not entity_dates:
            if ec_upper in all_calendar_entities:
                return None  # entity is in calendar but has NO operating dates = extinct/fully closed
            return time_grid_full  # entity not in calendar at all = assume operating
        return time_grid_full[time_grid_full["park_date"].isin(entity_dates)]

    # Process entities
    logger.info("Generating forecasts...")
    forecast_dir.mkdir(parents=True, exist_ok=True)

    # Pre-filter entity list (skip extinct/closed) without building grids yet
    entity_queue = []
    skipped_extinct = 0
    for entity in entities:
        ec_upper = str(entity).upper()
        if operating_by_entity:
            entity_dates = operating_by_entity.get(ec_upper)
            if not entity_dates and ec_upper in all_calendar_entities:
                skipped_extinct += 1
                continue  # In calendar but no operating dates = extinct
        entity_queue.append(entity)
    if skipped_extinct:
        logger.info(f"Skipped {skipped_extinct} extinct/closed entities (no operating dates)")
    
    total_entities = len(entity_queue)
    logger.info(f"Processing {total_entities} entities in batches of 50...")
    
    # Process in batches to control memory — flush each batch to a temp parquet file
    BATCH_SIZE = 50
    temp_dir = forecast_dir / "_temp_batches"
    temp_dir.mkdir(parents=True, exist_ok=True)
    batch_files = []
    successful = 0
    failed = 0
    processed = 0
    
    for batch_start in range(0, total_entities, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, total_entities)
        batch_entities = entity_queue[batch_start:batch_end]
        
        # Build work items for this batch only (grids built lazily here)
        work_items = []
        for entity in batch_entities:
            grid = get_entity_time_grid(entity)
            if grid is None or (hasattr(grid, '__len__') and len(grid) == 0):
                continue
            entity_ratio = fallback_ratios.get(entity, global_ratio)
            work_items.append(
                (entity, grid, models_dir, entity_ratio, agg_lookup, park_hours_lookup, None)
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
                else:
                    failed += 1
                    logger.warning(f"  {entity_code}: {msg}")
        
        # Flush this batch to a temp parquet file
        if batch_results:
            batch_df = pd.concat(batch_results, ignore_index=True)
            batch_file = temp_dir / f"batch_{batch_start:04d}.parquet"
            batch_df.to_parquet(batch_file, index=False)
            batch_files.append(batch_file)
            del batch_df, batch_results
        
        # Free the grid references for this batch
        for i in range(batch_start, batch_end):
            entity_queue[i] = (entity_queue[i][0], None)  # Release grid memory
        
        processed += len(batch_entities)
        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        logger.info(f"  Progress: {processed}/{total_entities} ({rate:.1f} entities/sec, {elapsed/60:.1f} min)")
    
    # Combine batch files into final output
    logger.info(f"Combining {len(batch_files)} batch files...")
    if batch_files:
        chunks = [pd.read_parquet(f) for f in batch_files]
        combined = pd.concat(chunks, ignore_index=True)
        del chunks

        output_file = forecast_dir / "all_forecasts.parquet"
        combined.to_parquet(output_file, index=False)
        
        # Dual-write to DuckDB for bot + dashboard
        db_path = output_base / "tpcr_live.duckdb"
        if db_path.exists():
            try:
                import duckdb
                live_con = duckdb.connect(str(db_path))
                min_d = combined["park_date"].min()
                max_d = combined["park_date"].max()
                min_d = min_d.date() if hasattr(min_d, "date") else min_d
                max_d = max_d.date() if hasattr(max_d, "date") else max_d
                live_con.execute(
                    "DELETE FROM forecasts WHERE park_date >= ? AND park_date <= ?",
                    [min_d, max_d],
                )
                live_con.register("_fc_df", combined)
                live_con.execute("""
                    INSERT INTO forecasts (entity_code, park_date, time_slot, predicted_actual, prediction_method, updated_at)
                    SELECT entity_code, park_date::DATE, CAST(time_slot AS VARCHAR), predicted_actual,
                           COALESCE(prediction_method, 'model'), CURRENT_TIMESTAMP
                    FROM _fc_df
                """)
                live_con.execute("""
                    INSERT OR REPLACE INTO data_freshness (source, last_updated, row_count, notes)
                    VALUES ('forecasts', CURRENT_TIMESTAMP, (SELECT COUNT(*) FROM forecasts), 'pipeline')
                """)
                live_con.close()
                logger.info(f"  Wrote {len(combined):,} predictions to tpcr_live.duckdb")
            except Exception as e:
                logger.warning(f"  DuckDB write failed: {e}")
        
        # Stats
        method_counts = combined['prediction_method'].value_counts()
        total_predictions = len(combined)
        
        logger.info(f"  Saved {total_predictions:,} predictions to {output_file}")
        logger.info(f"  File size: {output_file.stat().st_size / 1024 / 1024:.1f} MB")
        logger.info("  By method:")
        for method, count in method_counts.items():
            logger.info(f"    {method}: {count:,}")
        
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
    logger.info("FORECAST COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Total predictions: {total_predictions:,}")
    logger.info(f"Time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    logger.info("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
