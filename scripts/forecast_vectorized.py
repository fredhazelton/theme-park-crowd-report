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

import numpy as np
import pandas as pd

try:
    import xgboost as xgb
except ImportError:
    xgb = None

# Constants
DEFAULT_WORKERS = 8
SLOTS_PER_DAY = 288  # 5-minute intervals
DEFAULT_FALLBACK_RATIO = 0.82

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
    """Generate all time slots for date range with V2 features."""
    dates = pd.date_range(start_date, end_date, freq='D')
    times = pd.date_range('00:00', '23:55', freq='5min').time
    
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
        
        for t in times:
            dt = datetime.combine(park_date, t)
            hour = dt.hour
            minute = dt.minute
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
        
        # Get estimated posted_time from aggregates for each row
        def get_posted_estimate(row):
            key = (entity_code, row['date_group_id'], row['time_slot_15min'])
            return agg_lookup.get(key, 30.0)  # Default 30 if no data
        
        df['posted_time'] = df.apply(get_posted_estimate, axis=1)
        
        # Get mins_since_open from park hours
        # Extract park code from entity (first 2 chars)
        park_code = entity_code[:2].upper()
        
        def get_mins_since_open(row):
            key = (park_code, row['park_date'])
            opening_mins = park_hours_lookup.get(key)
            if opening_mins is not None:
                current_mins = row['hour_of_day'] * 60 + (row['time_slot'].minute if hasattr(row['time_slot'], 'minute') else 0)
                return max(0, current_mins - opening_mins)
            return row['mins_since_6am']  # Fallback
        
        df['mins_since_open'] = df.apply(get_mins_since_open, axis=1)
        
        # Check for V2 model
        model_path = models_dir / entity_code / "model_julia_v2.json"
        
        if model_path.exists():
            # Load V2 model
            model = xgb.XGBRegressor()
            model.load_model(str(model_path))
            
            # V2 features
            feature_cols = [
                'posted_time', 'mins_since_6am', 'mins_since_open', 
                'hour_of_day', 'date_group_id_encoded', 
                'season_encoded', 'season_year_encoded'
            ]
            
            X = df[feature_cols].values.astype(np.float32)
            predictions = model.predict(X)
            predictions = np.clip(predictions, 0, 300)
            
            df['predicted_actual'] = np.round(predictions).astype(int)
            df['prediction_method'] = 'model_v2'
        else:
            # No model - use aggregate-based fallback
            def get_fallback(row):
                key = (entity_code, row['date_group_id'], row['time_slot_15min'])
                if key in agg_lookup:
                    return agg_lookup[key], 'aggregate'
                # Ultimate fallback: posted estimate × ratio
                return row['posted_time'] * fallback_ratio, 'fallback_ratio'
            
            results = df.apply(get_fallback, axis=1)
            df['predicted_actual'] = results.apply(lambda x: int(round(x[0])))
            df['prediction_method'] = results.apply(lambda x: x[1])
        
        # Cap predictions at entity's historical p95 posted wait
        if p95_cap is not None and p95_cap > 0:
            before_cap = df['predicted_actual'].max()
            df['predicted_actual'] = df['predicted_actual'].clip(upper=int(round(p95_cap)))
            if before_cap > p95_cap:
                cap_method = f" (capped at p95={int(round(p95_cap))})"
            else:
                cap_method = ""
        else:
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
    if oc_path.exists():
        try:
            oc_df = pd.read_parquet(oc_path)
            oc_df = oc_df[oc_df["is_operating"] == True]
            operating_set = set(
                zip(oc_df["entity_code"].astype(str).str.upper(), pd.to_datetime(oc_df["park_date"]).dt.date)
            )
            logger.info(f"Operating calendar: {len(operating_set):,} operating entity-dates")
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
    
    # Load park hours
    logger.info("Loading park hours...")
    park_hours_df = con.execute(f"""
        SELECT 
            park,
            CAST(date AS DATE) as park_date,
            EXTRACT(HOUR FROM CAST(opening_time AS TIMESTAMP)) * 60 + 
            EXTRACT(MINUTE FROM CAST(opening_time AS TIMESTAMP)) as opening_mins
        FROM read_csv_auto('{dim_dir}/dimparkhours.csv')
        WHERE opening_time IS NOT NULL
    """).fetchdf()
    
    park_hours_lookup = {}
    for _, row in park_hours_df.iterrows():
        key = (row['park'], pd.Timestamp(row['park_date']).date())
        park_hours_lookup[key] = int(row['opening_mins']) if pd.notna(row['opening_mins']) else None
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
    
    # Compute per-entity p95 posted wait cap from historical data
    logger.info("Computing per-entity historical p95 caps...")
    parquet_path = str((output_base / "fact_tables" / "parquet").resolve())
    p95_df = con.execute(f"""
        SELECT entity_code,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY wait_time_minutes) as p95_posted,
               MAX(wait_time_minutes) as max_posted,
               COUNT(*) as n_obs
        FROM read_parquet('{parquet_path}/*.parquet')
        WHERE wait_time_type = 'POSTED' AND wait_time_minutes > 0
        GROUP BY entity_code
    """).fetchdf()
    entity_p95_cap = dict(zip(p95_df['entity_code'], p95_df['p95_posted']))
    logger.info(f"  Computed p95 caps for {len(entity_p95_cap)} entities")
    
    # Get entity list
    logger.info("Getting entity list...")
    parquet_path = str((output_base / "fact_tables" / "parquet").resolve())
    entity_list = con.execute(f"""
        SELECT DISTINCT entity_code
        FROM read_parquet('{parquet_path}/*.parquet')
        WHERE wait_time_type = 'POSTED' AND wait_time_minutes > 0
    """).fetchdf()['entity_code'].tolist()
    
    con.close()
    
    # Count models
    entities_with_models = set()
    for d in models_dir.iterdir():
        if d.is_dir() and (d / "model_julia_v2.json").exists():
            entities_with_models.add(d.name)
    
    logger.info(f"Total entities: {len(entity_list)} ({len(entities_with_models)} with V2 models)")
    
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

    # Filter time grid per entity by operating calendar
    def get_entity_time_grid(entity_code: str):
        if not operating_set:
            return time_grid_full
        ec_upper = str(entity_code).upper()
        entity_dates = {d for (ec, d) in operating_set if ec == ec_upper}
        if not entity_dates:
            if ec_upper in all_calendar_entities:
                return None  # entity is in calendar but has NO operating dates = extinct/fully closed
            return time_grid_full  # entity not in calendar at all = assume operating
        return time_grid_full[time_grid_full["park_date"].isin(entity_dates)]

    # Process entities
    logger.info("Generating forecasts...")
    forecast_dir.mkdir(parents=True, exist_ok=True)

    # Build work items, skipping extinct/fully-closed entities
    work_items = []
    skipped_extinct = 0
    for entity in entities:
        grid = get_entity_time_grid(entity)
        if grid is None or (hasattr(grid, '__len__') and len(grid) == 0):
            skipped_extinct += 1
            continue
        work_items.append(
            (entity, grid, models_dir, DEFAULT_FALLBACK_RATIO, agg_lookup, park_hours_lookup, entity_p95_cap.get(entity))
        )
    if skipped_extinct:
        logger.info(f"Skipped {skipped_extinct} extinct/closed entities (no operating dates)")
    
    all_forecasts = []
    successful = 0
    failed = 0
    
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(forecast_entity, item): item[0] for item in work_items}
        
        for i, future in enumerate(as_completed(futures), 1):
            entity = futures[future]
            entity_code, result_df, msg = future.result()
            
            if result_df is not None:
                all_forecasts.append(result_df)
                successful += 1
            else:
                failed += 1
                logger.warning(f"  {entity_code}: {msg}")
            
            if i % 50 == 0 or i == len(entities):
                elapsed = time.time() - start_time
                rate = i / elapsed if elapsed > 0 else 0
                logger.info(f"  Progress: {i}/{len(entities)} ({rate:.1f} entities/sec)")
    
    # Combine and save
    logger.info("Combining forecasts...")
    if all_forecasts:
        combined = pd.concat(all_forecasts, ignore_index=True)

        output_file = forecast_dir / "all_forecasts.parquet"
        combined.to_parquet(output_file, index=False)
        
        # Stats
        method_counts = combined['prediction_method'].value_counts()
        
        logger.info(f"  Saved {len(combined):,} predictions to {output_file}")
        logger.info(f"  File size: {output_file.stat().st_size / 1024 / 1024:.1f} MB")
        logger.info("  By method:")
        for method, count in method_counts.items():
            logger.info(f"    {method}: {count:,}")
    
    elapsed = time.time() - start_time
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("FORECAST COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Total predictions: {len(combined) if all_forecasts else 0:,}")
    logger.info(f"Time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    logger.info("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
