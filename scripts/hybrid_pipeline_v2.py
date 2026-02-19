#!/usr/bin/env python3
"""
Hybrid Pipeline V2 - With Improved Features

Changes from V1:
- Added date_group_id, season, season_year from dimension tables
- Added geo_decay weight: 0.5^(days_since_observed / 730)
- Removed day_of_week, month, is_weekend (replaced by date_group_id)
- Predictions rounded to integers

Uses the fastest tool for each step:
1. Python/DuckDB → Matched pairs generation (vectorized SQL)
2. Julia/XGBoost.jl → Model training (faster than Python XGBoost)
3. Python → Scoring (loads any XGBoost format)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import duckdb
from zoneinfo import ZoneInfo

# Ensure src is on path for utils import
if str(Path(__file__).resolve().parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from utils.park_code import park_code_sql

# Constants
MATCH_WINDOW_MINUTES = 15
DEFAULT_MIN_OBS = 500
DEFAULT_FALLBACK_RATIO = 0.82
GEO_DECAY_HALFLIFE_DAYS = 730  # 2 years
EASTERN = ZoneInfo("America/New_York")

# Paths (defaults; overridden by --output-base in main)
OUTPUT_BASE = Path("/home/wilma/hazeydata/pipeline")
PARQUET_DIR = OUTPUT_BASE / "fact_tables" / "parquet"
DIMENSION_DIR = OUTPUT_BASE / "dimension_tables"
MATCHED_PAIRS_DIR = OUTPUT_BASE / "matched_pairs"
MODELS_DIR = OUTPUT_BASE / "models"
PREDICTIONS_DIR = OUTPUT_BASE / "predictions"
LOGS_DIR = OUTPUT_BASE / "logs"

PROJECT_ROOT = Path("/home/wilma/theme-park-crowd-report")
JULIA_TRAIN_SCRIPT = PROJECT_ROOT / "julia-ml" / "train_v2.jl"
JULIA_BIN = Path.home() / "julia-1.10.2" / "bin" / "julia"


def setup_logging(log_dir: Path | None = None):
    log_dir = log_dir or LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"hybrid_pipeline_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


def step1_create_matched_pairs(logger, output_base: Path | None = None, full_rebuild: bool = False) -> int:
    """Create matched pairs incrementally. Only pairs new ACTUAL observations; appends to existing file.
    
    Geo decay weights are NOT stored in pairs (computed at training time instead).
    On first run (no existing pairs file), does a full build.
    Use --full-pairs to force a complete rebuild.
    """
    base = output_base or OUTPUT_BASE
    parquet_dir = base / "fact_tables" / "parquet"
    dim_dir = base / "dimension_tables"
    matched_dir = base / "matched_pairs"
    oc_path = base / "operating_calendar" / "operating_calendar.parquet"
    state_dir = base / "state"
    pairs_state_path = state_dir / "matched_pairs_state.json"

    logger.info("=" * 60)
    logger.info("STEP 1: MATCHED PAIRS V2 (Incremental)")
    logger.info("=" * 60)

    start = time.time()
    con = duckdb.connect()

    # Paths for dimension tables
    dategroupid_path = dim_dir / "dimdategroupid.csv"
    season_path = dim_dir / "dimseason.csv"
    parkhours_path = dim_dir / "dimparkhours.csv"
    entity_path = dim_dir / "dimentity.csv"

    if not dategroupid_path.exists():
        logger.error(f"dimdategroupid.csv not found: {dategroupid_path}")
        return 0
    if not season_path.exists():
        logger.error(f"dimseason.csv not found: {season_path}")
        return 0
    if not parkhours_path.exists():
        logger.warning(f"dimparkhours.csv not found: {parkhours_path} - mins_since_open will be NULL")
    if not entity_path.exists():
        logger.warning(f"dimentity.csv not found: {entity_path} - cannot filter fastpass_booth entities")

    # Operating calendar: filter to is_operating=TRUE; graceful fallback if missing
    use_operating_calendar = oc_path.exists()
    if use_operating_calendar:
        logger.info(f"Using operating calendar: {oc_path} (excluding closed entity-dates)")
    else:
        logger.info("Operating calendar not found; assuming all entities operating")

    oc_str = str(oc_path).replace("\\", "/")
    parquet_str = str(parquet_dir).replace("\\", "/")

    # Optional filter for operating calendar
    if use_operating_calendar:
        operating_filter = f"""
        operating AS (
            SELECT entity_code, CAST(park_date AS DATE) as park_date
            FROM read_parquet('{oc_str}')
            WHERE is_operating = TRUE
        ),
        """
        actual_filter = "AND EXISTS (SELECT 1 FROM operating o WHERE o.entity_code = a.entity_code AND o.park_date = CAST(a.park_date AS DATE))"
        posted_filter = "AND EXISTS (SELECT 1 FROM operating o WHERE o.entity_code = p.entity_code AND o.park_date = CAST(p.park_date AS DATE))"
    else:
        operating_filter = ""
        actual_filter = ""
        posted_filter = ""

    # Determine incremental vs full rebuild
    output_path = matched_dir / "all_pairs_v2.parquet"
    existing_pairs = None
    last_paired_at = None

    if not full_rebuild and output_path.exists() and pairs_state_path.exists():
        try:
            with open(pairs_state_path) as f:
                pairs_state = json.load(f)
            last_paired_at = pairs_state.get("last_paired_at")
            if last_paired_at:
                logger.info(f"  Incremental mode: pairing ACTUALs observed after {last_paired_at}")
        except Exception as e:
            logger.warning(f"  Could not read pairs state ({e}), doing full rebuild")
    elif full_rebuild:
        logger.info("  Full rebuild requested (--full-pairs)")

    if last_paired_at:
        # Incremental: only pair new ACTUALs, restrict POSTED to same park_dates
        actual_time_filter = f"AND a.observed_at > '{last_paired_at}'"
        # We'll join POSTED only for park_dates that have new ACTUALs (handled in query)
        mode = "incremental"
    else:
        actual_time_filter = ""
        mode = "full"

    # Match ACTUAL with closest POSTED within 15-minute window
    # Join with dimension tables for date_group_id, season, season_year
    # NOTE: geo_decay_weight is NOT computed here — it's computed at training time
    # Filter out fastpass_booth entities (Lightning Lane return times, not standby waits)
    entity_filter_str = str(entity_path).replace("\\", "/")
    query = f"""
        WITH {operating_filter}
        valid_entities AS (
            SELECT code as entity_code
            FROM read_csv_auto('{entity_filter_str}')
            WHERE fastpass_booth = FALSE
        ),
        actual AS (
            SELECT 
                a.entity_code,
                a.observed_at,
                a.observed_at_ts,
                a.park_date,
                a.wait_time_minutes as actual_time
            FROM read_parquet('{parquet_str}/*.parquet') a
            INNER JOIN valid_entities ve ON a.entity_code = ve.entity_code
            WHERE a.wait_time_type = 'ACTUAL'
              AND a.wait_time_minutes IS NOT NULL
              AND a.wait_time_minutes > 0
              {actual_filter}
              {actual_time_filter}
        ),
        posted AS (
            SELECT 
                p.entity_code,
                p.observed_at_ts,
                p.park_date,
                p.wait_time_minutes as posted_time
            FROM read_parquet('{parquet_str}/*.parquet') p
            INNER JOIN valid_entities ve ON p.entity_code = ve.entity_code
            WHERE p.wait_time_type = 'POSTED'
              AND p.wait_time_minutes IS NOT NULL
              AND p.wait_time_minutes > 0
              {posted_filter}
        ),
        dategroupid AS (
            SELECT 
                CAST(park_date AS DATE) as park_date,
                date_group_id
            FROM read_csv('{dategroupid_path}', AUTO_DETECT=TRUE)
        ),
        season AS (
            SELECT 
                CAST(park_date AS DATE) as park_date,
                season,
                season_year
            FROM read_csv('{season_path}', AUTO_DETECT=TRUE)
        ),
        parkhours AS (
            SELECT 
                park,
                CAST(date AS DATE) as park_date,
                EXTRACT(HOUR FROM CAST(opening_time AS TIMESTAMP)) as open_hour,
                EXTRACT(MINUTE FROM CAST(opening_time AS TIMESTAMP)) as open_minute
            FROM read_csv('{parkhours_path}', AUTO_DETECT=TRUE)
            WHERE opening_time IS NOT NULL
        ),
        matched AS (
            SELECT 
                a.entity_code,
                a.observed_at,
                a.observed_at_ts,
                a.park_date,
                a.actual_time,
                p.posted_time,
                ABS(EXTRACT(EPOCH FROM (a.observed_at_ts - p.observed_at_ts))) as time_diff_sec
            FROM actual a
            JOIN posted p 
              ON a.entity_code = p.entity_code 
              AND a.park_date = p.park_date
              AND ABS(EXTRACT(EPOCH FROM (a.observed_at_ts - p.observed_at_ts))) <= {MATCH_WINDOW_MINUTES * 60}
        ),
        best_match AS (
            SELECT 
                entity_code,
                observed_at,
                observed_at_ts,
                park_date,
                actual_time,
                posted_time,
                ROW_NUMBER() OVER (
                    PARTITION BY entity_code, observed_at 
                    ORDER BY time_diff_sec
                ) as rn
            FROM matched
        ),
        with_dims AS (
            SELECT 
                bm.entity_code,
                bm.observed_at,
                bm.observed_at_ts,
                bm.park_date,
                bm.actual_time,
                bm.posted_time,
                dg.date_group_id,
                s.season,
                s.season_year,
                ph.open_hour,
                ph.open_minute
            FROM best_match bm
            LEFT JOIN dategroupid dg ON bm.park_date = dg.park_date
            LEFT JOIN season s ON bm.park_date = s.park_date
            LEFT JOIN parkhours ph ON (
                ({park_code_sql("bm.entity_code")}) = UPPER(ph.park)
                OR (bm.entity_code LIKE 'USH%' AND UPPER(ph.park) IN ('UH', 'USH'))
            )
            AND bm.park_date = ph.park_date
            WHERE bm.rn = 1
        )
        SELECT 
            entity_code,
            observed_at,
            observed_at_ts,
            park_date,
            actual_time,
            posted_time,
            date_group_id,
            season,
            season_year,
            -- Time features
            EXTRACT(HOUR FROM observed_at_ts) as hour_of_day,
            (EXTRACT(HOUR FROM observed_at_ts) - 6) * 60 + EXTRACT(MINUTE FROM observed_at_ts) as mins_since_6am,
            -- Minutes since park open (NULL if no park hours data)
            CASE 
                WHEN open_hour IS NOT NULL THEN
                    (EXTRACT(HOUR FROM observed_at_ts) - open_hour) * 60 + 
                    (EXTRACT(MINUTE FROM observed_at_ts) - open_minute)
                ELSE NULL
            END as mins_since_open
        FROM with_dims
        WHERE date_group_id IS NOT NULL
          AND season IS NOT NULL
    """
    
    logger.info(f"  Running DuckDB match query ({mode})...")
    new_df = con.execute(query).fetchdf()
    logger.info(f"  New matched pairs: {len(new_df):,}")

    # Load existing encoding mappings (extend rather than rebuild)
    encodings_path = state_dir / "encoding_mappings.json"
    if encodings_path.exists():
        with open(encodings_path) as f:
            encodings = json.load(f)
        dg_mapping = encodings.get("date_group_id", {})
        season_mapping = encodings.get("season", {})
        sy_mapping = encodings.get("season_year", {})
    else:
        dg_mapping = {}
        season_mapping = {}
        sy_mapping = {}

    def extend_encoding(existing: dict, new_values) -> dict:
        """Add new categories to an encoding mapping, preserving existing assignments."""
        mapping = dict(existing)  # copy
        next_idx = max(mapping.values(), default=-1) + 1
        for val in sorted(set(str(v) for v in new_values)):
            if val not in mapping:
                mapping[val] = next_idx
                next_idx += 1
        return mapping

    if len(new_df) > 0:
        # Extend encodings with any new categories from new pairs
        dg_mapping = extend_encoding(dg_mapping, new_df['date_group_id'].dropna().unique())
        season_mapping = extend_encoding(season_mapping, new_df['season'].dropna().unique())
        sy_mapping = extend_encoding(sy_mapping, new_df['season_year'].dropna().unique())

        # Encode new pairs
        new_df['date_group_id_encoded'] = new_df['date_group_id'].astype(str).map(dg_mapping)
        new_df['season_encoded'] = new_df['season'].astype(str).map(season_mapping)
        new_df['season_year_encoded'] = new_df['season_year'].astype(str).map(sy_mapping)

    # Save updated encodings
    encodings = {
        'date_group_id': dg_mapping,
        'season': season_mapping,
        'season_year': sy_mapping,
    }
    encodings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(encodings_path, 'w') as f:
        json.dump(encodings, f, indent=2)

    # Merge with existing pairs (incremental) or write fresh (full)
    if mode == "incremental" and output_path.exists() and len(new_df) > 0:
        existing_df = pd.read_parquet(output_path)
        # Drop geo_decay_weight from old pairs if present (migrating to training-time computation)
        if 'geo_decay_weight' in existing_df.columns:
            existing_df = existing_df.drop(columns=['geo_decay_weight'])
            logger.info("  Migrated: dropped geo_decay_weight from existing pairs (now computed at training time)")
        all_df = pd.concat([existing_df, new_df], ignore_index=True)
        logger.info(f"  Appended: {len(existing_df):,} existing + {len(new_df):,} new = {len(all_df):,} total")
    elif mode == "incremental" and len(new_df) == 0:
        # No new pairs — keep existing file as-is
        logger.info("  No new pairs to append")
        # Still need to load existing for fallback ratio computation
        all_df = pd.read_parquet(output_path)
        if 'geo_decay_weight' in all_df.columns:
            all_df = all_df.drop(columns=['geo_decay_weight'])
            all_df.to_parquet(output_path, index=False)
            logger.info("  Migrated: dropped geo_decay_weight from existing pairs")
    else:
        all_df = new_df
        logger.info(f"  Full build: {len(all_df):,} pairs")

    # Save pairs
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if len(new_df) > 0 or not output_path.exists():
        all_df.to_parquet(output_path, index=False)

    # Save pairing state (max observed_at from ALL data for next incremental run)
    max_observed_at = str(all_df['observed_at'].max()) if len(all_df) > 0 else last_paired_at
    if max_observed_at:
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(pairs_state_path, 'w') as f:
            json.dump({"last_paired_at": max_observed_at, "total_pairs": len(all_df)}, f, indent=2)

    elapsed = time.time() - start

    # Calculate dynamic fallback ratios from full cumulative pairs
    logger.info("  Computing dynamic fallback ratios...")
    ratio_df = all_df.groupby('entity_code').agg(
        actual_sum=('actual_time', 'sum'),
        posted_sum=('posted_time', 'sum'),
        count=('actual_time', 'count')
    ).reset_index()
    
    # Global average ratio
    global_ratio = ratio_df['actual_sum'].sum() / ratio_df['posted_sum'].sum()
    
    # Per-entity ratio (use global if < 50 samples)
    ratio_df['fallback_ratio'] = ratio_df.apply(
        lambda row: row['actual_sum'] / row['posted_sum'] if row['count'] >= 50 else global_ratio,
        axis=1
    )
    
    # Save fallback ratios
    fallback_ratios = dict(zip(ratio_df['entity_code'], ratio_df['fallback_ratio']))
    fallback_ratios['__global__'] = global_ratio
    
    ratios_path = base / "state" / "fallback_ratios.json"
    with open(ratios_path, 'w') as f:
        json.dump(fallback_ratios, f, indent=2)
    logger.info(f"  Global fallback ratio: {global_ratio:.3f}")
    logger.info(f"  Per-entity ratios: {len([r for r in ratio_df['count'] if r >= 50])} entities with ≥50 samples")
    logger.info(f"  Saved ratios to: {ratios_path}")
    
    logger.info(f"  Saved to: {output_path}")
    logger.info(f"  Features: posted_time, mins_since_6am, mins_since_open, hour_of_day, date_group_id, season, season_year")
    logger.info(f"  Geo decay: computed at training time (half-life={GEO_DECAY_HALFLIFE_DAYS} days)")
    logger.info(f"  ⏱️  Matched pairs ({mode}): {elapsed:.1f}s")
    
    con.close()
    return len(all_df)


def step2_train_actuals(logger, output_base: Path | None = None) -> tuple[int, float]:
    """Run Julia actuals-only training (ACTUALS-FIRST methodology)."""
    base = output_base or OUTPUT_BASE
    logger.info("=" * 60)
    logger.info("STEP 2: TRAINING ACTUALS-ONLY (Julia/XGBoost.jl, no posted_time)")
    logger.info("=" * 60)

    train_script = PROJECT_ROOT / "julia-ml" / "train_actuals_v2.jl"
    if not train_script.exists():
        logger.error(f"Actuals training script not found: {train_script}")
        return 0, 0.0

    # Build actuals training data first
    logger.info("Building actuals training data...")
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "build_actuals_training_data.py"),
         "--output-base", str(base)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"Build actuals training data failed:\n{result.stderr}")
        return 0, 0.0
    logger.info(result.stdout)

    start = time.time()
    env = dict(os.environ)
    env["OUTPUT_BASE"] = str(base)

    result = subprocess.run(
        [str(JULIA_BIN), f"--project={PROJECT_ROOT / 'julia-ml'}", "--threads=4", str(train_script)],
        cwd=str(PROJECT_ROOT / "julia-ml"),
        capture_output=True,
        text=True,
        env=env,
    )
    elapsed = time.time() - start

    if result.returncode != 0:
        logger.error(f"Julia actuals training failed:\n{result.stderr}")
        return 0, elapsed

    logger.info(result.stdout)
    successful = 0
    for line in result.stdout.split("\n"):
        if "Successful:" in line:
            try:
                successful = int(line.split(":")[1].strip())
            except Exception:
                pass
    logger.info(f"  ⏱️  Actuals training: {elapsed:.1f}s ({successful} models)")
    return successful, elapsed


def step2_train_julia(logger, use_synthetic: bool = False) -> tuple[int, float]:
    """Run Julia XGBoost training with geo decay weights."""
    logger.info("=" * 60)
    if use_synthetic:
        logger.info("STEP 2: TRAINING V2 (Julia/XGBoost.jl + geo decay + synthetic actuals)")
    else:
        logger.info("STEP 2: TRAINING V2 (Julia/XGBoost.jl + geo decay)")
    logger.info("=" * 60)
    
    if not JULIA_TRAIN_SCRIPT.exists():
        logger.warning(f"Julia V2 script not found: {JULIA_TRAIN_SCRIPT}")
        logger.warning("Falling back to original train_only.jl")
        fallback_script = PROJECT_ROOT / "julia-ml" / "train_only.jl"
        if not fallback_script.exists():
            logger.error("No Julia training script found")
            return 0, 0.0
        script_to_run = fallback_script
    else:
        script_to_run = JULIA_TRAIN_SCRIPT
    
    # Combine real and synthetic pairs if requested
    if use_synthetic:
        logger.info("  Combining real and synthetic pairs for training...")
        real_pairs_path = MATCHED_PAIRS_DIR / "all_pairs_v2.parquet"
        synthetic_pairs_path = MATCHED_PAIRS_DIR / "synthetic_pairs_v2.parquet"
        combined_pairs_path = MATCHED_PAIRS_DIR / "combined_pairs_v2.parquet"
        
        if not real_pairs_path.exists():
            logger.error(f"Real pairs not found: {real_pairs_path}")
            return 0, 0.0
            
        if not synthetic_pairs_path.exists():
            logger.error(f"Synthetic pairs not found: {synthetic_pairs_path}")
            logger.error("Run build_synthetic_pairs.py first")
            return 0, 0.0
        
        # Load and combine pairs
        real_df = pd.read_parquet(real_pairs_path)
        synthetic_df = pd.read_parquet(synthetic_pairs_path)
        
        # Add is_synthetic column to real pairs
        real_df['is_synthetic'] = False
        
        # Ensure columns match exactly
        real_columns = set(real_df.columns)
        synthetic_columns = set(synthetic_df.columns)
        
        if real_columns != synthetic_columns:
            logger.error(f"Column mismatch between real and synthetic pairs!")
            logger.error(f"Real: {sorted(real_columns)}")
            logger.error(f"Synthetic: {sorted(synthetic_columns)}")
            return 0, 0.0
        
        # Combine dataframes
        combined_df = pd.concat([real_df, synthetic_df], ignore_index=True)
        
        # Normalize park_date to string (synthetic has Timestamps, real has strings; PyArrow fails on mixed types)
        combined_df['park_date'] = pd.to_datetime(combined_df['park_date']).dt.strftime('%Y-%m-%d')
        
        # Save combined pairs for Julia
        combined_df.to_parquet(combined_pairs_path, index=False)
        
        logger.info(f"  Real pairs: {len(real_df):,}")
        logger.info(f"  Synthetic pairs: {len(synthetic_df):,}")
        logger.info(f"  Combined pairs: {len(combined_df):,}")
        logger.info(f"  Saved to: {combined_pairs_path}")
        
        # Update Julia script path to use combined pairs (will be handled in Julia script)
    
    # Write dirty entity list for Julia (only entities with new data since last training)
    try:
        _src = str(Path(__file__).resolve().parent.parent / "src")
        if _src not in sys.path:
            sys.path.insert(0, _src)
        from processors.entity_index import get_entities_needing_modeling
        
        entity_index_db = OUTPUT_BASE / "state" / "entity_index.sqlite"
        entity_filter_path = OUTPUT_BASE / "state" / "entities_to_train.txt"
        
        if entity_index_db.exists():
            dirty = get_entities_needing_modeling(entity_index_db, logger=logger)
            dirty_codes = [row[0] for row in dirty]
            entity_filter_path.parent.mkdir(parents=True, exist_ok=True)
            entity_filter_path.write_text("\n".join(dirty_codes) + "\n")
            logger.info(f"  Dirty entities (new data since last training): {len(dirty_codes)}")
        else:
            # No index = train everything (filter file won't exist)
            if entity_filter_path.exists():
                entity_filter_path.unlink()
            logger.info("  No entity index found — Julia will train all eligible entities")
    except Exception as e:
        logger.warning(f"  Could not write entity filter (Julia will train all): {e}")
    
    start = time.time()
    
    # Run Julia training with 4 threads
    result = subprocess.run(
        [str(JULIA_BIN), f"--project={PROJECT_ROOT / 'julia-ml'}", "--threads=4", str(script_to_run)],
        cwd=str(PROJECT_ROOT / "julia-ml"),
        capture_output=True,
        text=True,
    )
    
    elapsed = time.time() - start
    
    if result.returncode != 0:
        logger.error(f"Julia training failed:\n{result.stderr}")
        return 0, elapsed
    
    output = result.stdout
    logger.info(output)
    
    # Extract successful count
    successful = 0
    for line in output.split("\n"):
        if "Successful:" in line:
            try:
                successful = int(line.split(":")[1].strip())
            except:
                pass
    
    logger.info(f"  ⏱️  Julia training: {elapsed:.1f}s ({successful} models)")

    # Mark all successfully trained entities in entity_index
    # This resets their "dirty" state so they won't trigger unnecessary retraining
    if successful > 0:
        try:
            _src = str(Path(__file__).resolve().parent.parent / "src")
            if _src not in sys.path:
                sys.path.insert(0, _src)
            from processors.entity_index import mark_entity_modeled

            entity_index_db = OUTPUT_BASE / "state" / "entity_index.sqlite"
            # Find entities that actually have V2 models on disk
            trained_entities = [
                d.name for d in MODELS_DIR.iterdir()
                if d.is_dir() and (d / "model_julia_v2.json").exists()
            ]
            for entity_code in trained_entities:
                mark_entity_modeled(entity_code, entity_index_db)
            logger.info(f"  Marked {len(trained_entities)} entities as modeled in entity_index")
        except Exception as e:
            logger.warning(f"  Failed to mark entities as modeled: {e}")

    return successful, elapsed


def step3_score_historical(logger) -> int:
    """Score all historical POSTED observations."""
    logger.info("=" * 60)
    logger.info("STEP 3: SCORING HISTORICAL (Python)")
    logger.info("=" * 60)
    
    # Import here to avoid circular deps
    start = time.time()
    
    try:
        # Use the existing scoring script
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "score_historical.py")],
            capture_output=True,
            text=True,
        )
        
        if result.returncode != 0:
            logger.error(f"Scoring failed:\n{result.stderr}")
            return 0
        
        logger.info(result.stdout)
        
        # Count predictions
        pred_path = PREDICTIONS_DIR / "historical_predictions.parquet"
        if pred_path.exists():
            import pyarrow.parquet as pq
            n_predictions = pq.read_metadata(pred_path).num_rows
        else:
            n_predictions = 0
        
        elapsed = time.time() - start
        logger.info(f"  ⏱️  Scoring: {elapsed:.1f}s ({n_predictions:,} predictions)")
        return n_predictions
        
    except Exception as e:
        logger.error(f"Scoring error: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Hybrid Pipeline V2")
    parser.add_argument("--output-base", type=Path, default=OUTPUT_BASE, help="Pipeline output base")
    parser.add_argument("--skip-pairs", action="store_true", help="Skip matched pairs generation")
    parser.add_argument("--full-pairs", action="store_true", help="Force full rebuild of matched pairs (ignore incremental state)")
    parser.add_argument("--skip-training", action="store_true", help="Skip model training")
    parser.add_argument("--skip-scoring", action="store_true", help="Skip historical scoring")
    parser.add_argument("--use-synthetic", action="store_true", help="Include synthetic actuals in training")
    parser.add_argument("--actuals-only", action="store_true",
                       help="ACTUALS-FIRST: train on actuals only (no posted_time). Uses synthetic+real actuals.")
    args = parser.parse_args()

    output_base = args.output_base.resolve()

    logger = setup_logging(output_base / "logs")

    logger.info("=" * 60)
    logger.info("HYBRID PIPELINE V2")
    logger.info("=" * 60)
    logger.info(f"Output base: {output_base}")
    logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Features: posted_time, mins_since_6am, hour_of_day, date_group_id, season, season_year")
    logger.info(f"Weights: geo_decay (half-life={GEO_DECAY_HALFLIFE_DAYS} days)")
    logger.info("")

    total_start = time.time()

    # Step 1: Matched pairs
    if not args.skip_pairs:
        n_pairs = step1_create_matched_pairs(logger, output_base, full_rebuild=args.full_pairs)
    else:
        logger.info("Skipping matched pairs generation")
        n_pairs = 0
    
    # Step 2: Training
    if not args.skip_training:
        if args.actuals_only:
            # ACTUALS-FIRST: train on actuals only (no posted_time)
            n_models, train_time = step2_train_actuals(logger, output_base)
        elif args.use_synthetic:
            logger.info("Building synthetic pairs...")
            import subprocess
            result = subprocess.run([
                sys.executable, 
                str(PROJECT_ROOT / "scripts" / "build_synthetic_pairs.py"),
                "--output-base", str(output_base)
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"Synthetic pairs building failed:\n{result.stderr}")
                logger.info("Continuing with real pairs only...")
                n_models, train_time = step2_train_julia(logger, use_synthetic=False)
            else:
                logger.info(result.stdout)
                n_models, train_time = step2_train_julia(logger, use_synthetic=True)
        else:
            n_models, train_time = step2_train_julia(logger, use_synthetic=False)
    else:
        logger.info("Skipping training")
        n_models, train_time = 0, 0.0
    
    # Step 3: Scoring
    if not args.skip_scoring:
        n_predictions = step3_score_historical(logger)
    else:
        logger.info("Skipping scoring")
        n_predictions = 0
    
    total_elapsed = time.time() - total_start
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("PIPELINE V2 COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Matched pairs: {n_pairs:,}")
    logger.info(f"Models trained: {n_models}")
    logger.info(f"Predictions: {n_predictions:,}")
    logger.info(f"Total time: {total_elapsed:.1f}s")


if __name__ == "__main__":
    main()
