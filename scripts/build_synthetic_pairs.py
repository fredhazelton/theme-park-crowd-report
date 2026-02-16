#!/usr/bin/env python3
"""
Build Synthetic Pairs - Create training pairs from synthetic actuals

Reads synthetic actuals from /mnt/data/pipeline/synthetic_actuals/*.parquet,
joins with dimension tables, computes features, and outputs training-ready
synthetic pairs with the same schema as real matched pairs.

Output: synthetic_pairs_v2.parquet
Schema: entity_code, observed_at, observed_at_ts, park_date, actual_time, posted_time,
        date_group_id, season, season_year, hour_of_day, mins_since_6am, mins_since_open,
        date_group_id_encoded, season_encoded, season_year_encoded, is_synthetic

Where:
- actual_time = synthetic_actual (renamed)
- is_synthetic = True (distinguishes from real pairs)
- Encodings match exactly what real pairs use (from encoding_mappings.json)
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
from zoneinfo import ZoneInfo

# Constants
EASTERN = ZoneInfo("America/New_York")
DEFAULT_OUTPUT_BASE = Path("/home/wilma/hazeydata/pipeline")

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    return logging.getLogger(__name__)

def load_encoding_mappings(state_dir: Path) -> dict:
    """Load existing encoding mappings from real pairs builder."""
    encodings_path = state_dir / "encoding_mappings.json"
    
    if not encodings_path.exists():
        raise FileNotFoundError(f"Encoding mappings not found: {encodings_path}")
    
    with open(encodings_path) as f:
        return json.load(f)

def build_synthetic_pairs(logger, output_base: Path) -> int:
    """Build synthetic training pairs from synthetic actuals."""
    
    synthetic_actuals_dir = output_base / "synthetic_actuals"
    dim_dir = output_base / "dimension_tables" 
    state_dir = output_base / "state"
    output_dir = output_base / "matched_pairs"
    
    logger.info("=" * 60)
    logger.info("BUILDING SYNTHETIC PAIRS")
    logger.info("=" * 60)
    
    start_time = time.time()
    
    # Check required paths
    if not synthetic_actuals_dir.exists():
        logger.error(f"Synthetic actuals directory not found: {synthetic_actuals_dir}")
        return 0
        
    synthetic_files = list(synthetic_actuals_dir.glob("*.parquet"))
    if not synthetic_files:
        logger.error(f"No synthetic actuals files found in {synthetic_actuals_dir}")
        return 0
    
    logger.info(f"Found {len(synthetic_files)} synthetic actuals files")
    
    # Required dimension tables
    dategroupid_path = dim_dir / "dimdategroupid.csv"
    season_path = dim_dir / "dimseason.csv"  
    parkhours_path = dim_dir / "dimparkhours.csv"
    
    for path in [dategroupid_path, season_path]:
        if not path.exists():
            logger.error(f"Required dimension table not found: {path}")
            return 0
    
    if not parkhours_path.exists():
        logger.warning(f"Park hours not found: {parkhours_path} - mins_since_open will be NULL")
        
    # Load encoding mappings from real pairs
    logger.info("Loading encoding mappings from real pairs...")
    try:
        encodings = load_encoding_mappings(state_dir)
        dg_mapping = encodings['date_group_id']
        season_mapping = encodings['season']  
        sy_mapping = encodings['season_year']
        logger.info(f"Loaded encodings: {len(dg_mapping)} date_groups, {len(season_mapping)} seasons, {len(sy_mapping)} season_years")
    except Exception as e:
        logger.error(f"Failed to load encoding mappings: {e}")
        return 0
    
    # Build synthetic pairs using DuckDB
    logger.info("Processing synthetic actuals with DuckDB...")
    con = duckdb.connect()
    
    # Convert file paths to strings for DuckDB
    synthetic_pattern = str(synthetic_actuals_dir / "*.parquet").replace("\\", "/")
    dg_path = str(dategroupid_path).replace("\\", "/")
    season_path_str = str(season_path).replace("\\", "/")
    ph_path = str(parkhours_path).replace("\\", "/")
    
    # Park hours join condition - graceful fallback if missing
    if parkhours_path.exists():
        parkhours_cte = f"""
        parkhours AS (
            SELECT 
                park,
                CAST(date AS DATE) as park_date,
                EXTRACT(HOUR FROM CAST(opening_time AS TIMESTAMP)) as open_hour,
                EXTRACT(MINUTE FROM CAST(opening_time AS TIMESTAMP)) as open_minute
            FROM read_csv('{ph_path}', AUTO_DETECT=TRUE)
            WHERE opening_time IS NOT NULL
        ),"""
        
        parkhours_join = """
        LEFT JOIN parkhours ph ON UPPER(SUBSTRING(syn.entity_code, 1, 2)) = UPPER(ph.park) 
                               AND syn.park_date = ph.park_date"""
        
        parkhours_select = "ph.open_hour, ph.open_minute,"
        
        mins_since_open_calc = """
        CASE 
            WHEN open_hour IS NOT NULL THEN
                (EXTRACT(HOUR FROM observed_at_ts) - open_hour) * 60 + 
                (EXTRACT(MINUTE FROM observed_at_ts) - open_minute)
            ELSE NULL
        END as mins_since_open"""
    else:
        parkhours_cte = ""
        parkhours_join = ""
        parkhours_select = "NULL as open_hour, NULL as open_minute,"
        mins_since_open_calc = "NULL as mins_since_open"
    
    query = f"""
        WITH synthetic AS (
            SELECT 
                entity_code,
                CAST(park_date AS DATE) as park_date,
                observed_at,
                CAST(observed_at AS TIMESTAMP) as observed_at_ts,
                posted_time,
                synthetic_actual
            FROM read_parquet('{synthetic_pattern}')
        ),
        dategroupid AS (
            SELECT 
                CAST(park_date AS DATE) as park_date,
                date_group_id
            FROM read_csv('{dg_path}', AUTO_DETECT=TRUE)
        ),
        season AS (
            SELECT 
                CAST(park_date AS DATE) as park_date,
                season,
                season_year
            FROM read_csv('{season_path_str}', AUTO_DETECT=TRUE)
        ),
        {parkhours_cte}
        joined AS (
            SELECT 
                syn.entity_code,
                syn.observed_at,
                syn.observed_at_ts,
                syn.park_date,
                syn.synthetic_actual as actual_time,
                syn.posted_time,
                dg.date_group_id,
                s.season,
                s.season_year,
                {parkhours_select}
                syn.observed_at_ts as syn_ts
            FROM synthetic syn
            LEFT JOIN dategroupid dg ON syn.park_date = dg.park_date
            LEFT JOIN season s ON syn.park_date = s.park_date
            {parkhours_join}
            WHERE dg.date_group_id IS NOT NULL
              AND s.season IS NOT NULL
              AND syn.synthetic_actual > 0
              AND syn.posted_time > 0
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
            -- Time features (matching real pairs exactly)
            EXTRACT(HOUR FROM observed_at_ts) as hour_of_day,
            (EXTRACT(HOUR FROM observed_at_ts) - 6) * 60 + EXTRACT(MINUTE FROM observed_at_ts) as mins_since_6am,
            {mins_since_open_calc},
            TRUE as is_synthetic
        FROM joined
        ORDER BY entity_code, observed_at
    """
    
    logger.info("Executing DuckDB query...")
    df = con.execute(query).fetchdf()
    con.close()
    
    if len(df) == 0:
        logger.error("No synthetic pairs generated - check dimension table joins")
        return 0
        
    logger.info(f"Generated {len(df):,} synthetic pairs before encoding")
    
    # Apply categorical encodings (matching real pairs exactly)
    logger.info("Applying categorical encodings...")
    
    df['date_group_id_encoded'] = df['date_group_id'].astype(str).map(dg_mapping)
    df['season_encoded'] = df['season'].astype(str).map(season_mapping)  
    df['season_year_encoded'] = df['season_year'].astype(str).map(sy_mapping)
    
    # Check for unmapped categories (should be rare if dimensions are consistent)
    unmapped_dg = df['date_group_id_encoded'].isna().sum()
    unmapped_s = df['season_encoded'].isna().sum()
    unmapped_sy = df['season_year_encoded'].isna().sum()
    
    if unmapped_dg > 0:
        logger.warning(f"Unmapped date_group_ids: {unmapped_dg} rows")
    if unmapped_s > 0:
        logger.warning(f"Unmapped seasons: {unmapped_s} rows")
    if unmapped_sy > 0:
        logger.warning(f"Unmapped season_years: {unmapped_sy} rows")
    
    # Remove rows with unmapped categories (to match real pairs behavior)
    before_filter = len(df)
    df = df.dropna(subset=['date_group_id_encoded', 'season_encoded', 'season_year_encoded'])
    after_filter = len(df)
    
    if before_filter > after_filter:
        logger.info(f"Filtered out {before_filter - after_filter:,} rows with unmapped categories")
    
    if len(df) == 0:
        logger.error("No synthetic pairs remain after encoding")
        return 0
    
    # Ensure integer encoding columns
    df['date_group_id_encoded'] = df['date_group_id_encoded'].astype(int)
    df['season_encoded'] = df['season_encoded'].astype(int)
    df['season_year_encoded'] = df['season_year_encoded'].astype(int)
    
    # Final column order (matching real pairs exactly)
    final_columns = [
        'entity_code', 'observed_at', 'observed_at_ts', 'park_date',
        'actual_time', 'posted_time', 'date_group_id', 'season', 'season_year',
        'hour_of_day', 'mins_since_6am', 'mins_since_open',
        'date_group_id_encoded', 'season_encoded', 'season_year_encoded', 'is_synthetic'
    ]
    
    df = df[final_columns]
    
    # Save synthetic pairs
    output_path = output_dir / "synthetic_pairs_v2.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Saving to {output_path}...")
    df.to_parquet(output_path, index=False)
    
    elapsed = time.time() - start_time
    
    logger.info("=" * 60)
    logger.info("SYNTHETIC PAIRS BUILD COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Output: {output_path}")
    logger.info(f"Rows: {len(df):,}")
    logger.info(f"Entities: {df['entity_code'].nunique()}")
    logger.info(f"Date range: {df['park_date'].min()} to {df['park_date'].max()}")
    logger.info(f"Features: {', '.join(final_columns)}")
    logger.info(f"Build time: {elapsed:.1f}s")
    logger.info(f"All synthetic pairs have is_synthetic=True")
    
    return len(df)

def main():
    parser = argparse.ArgumentParser(description="Build synthetic training pairs")
    parser.add_argument("--output-base", type=Path, default=DEFAULT_OUTPUT_BASE,
                        help="Pipeline output base directory")
    args = parser.parse_args()
    
    logger = setup_logging()
    
    output_base = args.output_base.resolve()
    logger.info(f"Output base: {output_base}")
    
    n_pairs = build_synthetic_pairs(logger, output_base)
    
    if n_pairs == 0:
        logger.error("Failed to build synthetic pairs")
        sys.exit(1)
    else:
        logger.info(f"Success: Built {n_pairs:,} synthetic pairs")

if __name__ == "__main__":
    main()