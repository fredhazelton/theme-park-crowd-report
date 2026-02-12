"""
Synthetic Actuals Generator

================================================================================
PURPOSE
================================================================================
Generates synthetic ACTUAL wait times from historical POSTED data using the
trained conversion model. Uses DuckDB for fast bulk processing (matching
hybrid_pipeline_v2 pattern).

================================================================================
OUTPUT
================================================================================
synthetic_actuals/{entity_code}.parquet — per-entity synthetic actuals with:
  entity_code, park_date, observed_at, synthetic_actual, source="synthetic"

================================================================================
USAGE
================================================================================
  from processors.synthetic_actuals import generate_all
  generate_all(output_base, logger, min_posted_obs=500)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, Optional

import duckdb
import numpy as np
import pandas as pd

try:
    import xgboost as xgb
except ImportError:
    xgb = None

from processors.posted_to_actual import load_conversion_model

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_MIN_POSTED_OBS = 500
MIN_REASONABLE_WAIT = 0
MAX_REASONABLE_WAIT = 300


# =============================================================================
# BULK GENERATION (DuckDB-based)
# =============================================================================

def generate_all(
    output_base: Path,
    logger: Optional[logging.Logger] = None,
    min_posted_obs: int = DEFAULT_MIN_POSTED_OBS,
) -> Dict:
    """
    Generate synthetic actuals for all eligible STANDBY entities using DuckDB.
    
    1. Load conversion model
    2. Bulk-load ALL POSTED data with rolling features via DuckDB
    3. Apply conversion model in batch
    4. Save per-entity parquet files
    
    Returns:
        Summary dict with counts and stats
    """
    if xgb is None:
        raise ImportError("XGBoost not installed")
    
    start = time.time()
    
    # Step 1: Load conversion model
    if logger:
        logger.info("Loading conversion model...")
    model, metadata = load_conversion_model(output_base)
    feature_names = metadata['feature_names']
    encodings = metadata['encodings']
    
    if logger:
        logger.info(f"  Model loaded. Features: {len(feature_names)}")
    
    # Step 2: Bulk-load all POSTED data with rolling features via DuckDB
    if logger:
        logger.info("Loading all POSTED data with rolling features via DuckDB...")
    
    con = duckdb.connect()
    
    parquet_dir = output_base / "fact_tables" / "parquet"
    dim_dir = output_base / "dimension_tables"
    dimentity_path = dim_dir / "dimentity.csv"
    dategroupid_path = dim_dir / "dimdategroupid.csv"
    season_path = dim_dir / "dimseason.csv"
    parkhours_path = dim_dir / "dimparkhours.csv"
    
    # Get STANDBY entity codes
    standby_entities = con.execute(f"""
        SELECT code FROM read_csv('{dimentity_path}', AUTO_DETECT=TRUE)
        WHERE fastpass_booth = FALSE
    """).fetchdf()["code"].tolist()
    
    if logger:
        logger.info(f"  Found {len(standby_entities)} STANDBY entities")
    
    # Find entities with enough POSTED observations
    entity_counts = con.execute(f"""
        SELECT entity_code, COUNT(*) as n_posted
        FROM read_parquet('{parquet_dir}/*.parquet')
        WHERE wait_time_type = 'POSTED'
          AND wait_time_minutes IS NOT NULL
          AND wait_time_minutes > 0
          AND entity_code IN (SELECT UNNEST({standby_entities}::VARCHAR[]))
        GROUP BY entity_code
        HAVING COUNT(*) >= {min_posted_obs}
        ORDER BY COUNT(*) DESC
    """).fetchdf()
    
    eligible_entities = entity_counts['entity_code'].tolist()
    con.close()
    
    if logger:
        logger.info(f"  Eligible entities (>= {min_posted_obs} POSTED obs): {len(eligible_entities)}")
        logger.info(f"  Total POSTED obs across eligible: {entity_counts['n_posted'].sum():,}")
    
    # Group eligible entities by park prefix for chunked processing
    # (90M rows in one query OOMs on 62GB; chunking by park keeps each batch manageable)
    entity_to_park = {e: e[:2].upper() for e in eligible_entities}
    parks = sorted(set(entity_to_park.values()))
    park_to_entities = {}
    for e, p in entity_to_park.items():
        park_to_entities.setdefault(p, []).append(e)
    
    if logger:
        logger.info(f"  Processing in {len(parks)} park chunks: {parks}")
    
    # Encoding maps from conversion model
    entity_map = encodings.get('entity_code', {})
    park_map = encodings.get('park_code', {})
    dg_map = {int(k) if k.isdigit() else k: v for k, v in encodings.get('date_group_id', {}).items()}
    season_map = encodings.get('season', {})
    
    output_dir = output_base / "synthetic_actuals"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_cols = ['entity_code', 'park_date', 'observed_at', 'posted_time',
                   'synthetic_actual', 'source']
    
    entities_saved = 0
    total_rows_saved = 0
    total_posted_sum = 0.0
    total_synth_sum = 0.0
    
    for park_idx, park_code in enumerate(parks, 1):
        chunk_entities = park_to_entities[park_code]
        
        if logger:
            logger.info(f"  [{park_idx}/{len(parks)}] Park {park_code}: {len(chunk_entities)} entities...")
        
        chunk_con = duckdb.connect()
        
        query = f"""
            WITH posted_raw AS (
                SELECT 
                    entity_code,
                    observed_at,
                    observed_at_ts,
                    park_date,
                    wait_time_minutes as posted_time,
                    UPPER(SUBSTRING(entity_code, 1, 2)) as park_code
                FROM read_parquet('{parquet_dir}/*.parquet')
                WHERE wait_time_type = 'POSTED'
                  AND wait_time_minutes IS NOT NULL
                  AND wait_time_minutes > 0
                  AND entity_code IN (SELECT UNNEST({chunk_entities}::VARCHAR[]))
            ),
            
            posted_with_rolling AS (
                SELECT 
                    *,
                    posted_time - LAG(posted_time, 3) OVER w as posted_delta_15m,
                    posted_time - LAG(posted_time, 6) OVER w as posted_delta_30m,
                    posted_time - LAG(posted_time, 12) OVER w as posted_delta_60m,
                    AVG(posted_time) OVER (
                        PARTITION BY entity_code, park_date 
                        ORDER BY observed_at_ts
                        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
                    ) as posted_rolling_mean_30m,
                    AVG(posted_time) OVER (
                        PARTITION BY entity_code, park_date 
                        ORDER BY observed_at_ts
                        ROWS BETWEEN 12 PRECEDING AND CURRENT ROW
                    ) as posted_rolling_mean_60m,
                    STDDEV_POP(posted_time) OVER (
                        PARTITION BY entity_code, park_date 
                        ORDER BY observed_at_ts
                        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
                    ) as posted_volatility_30m
                FROM posted_raw
                WINDOW w AS (PARTITION BY entity_code, park_date ORDER BY observed_at_ts)
            ),
            
            dategroupid AS (
                SELECT CAST(park_date AS DATE) as park_date, date_group_id
                FROM read_csv('{dategroupid_path}', AUTO_DETECT=TRUE)
            ),
            season AS (
                SELECT CAST(park_date AS DATE) as park_date, season, season_year
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
            )
            
            SELECT 
                p.entity_code,
                p.observed_at,
                p.park_date,
                p.posted_time,
                p.posted_delta_15m,
                p.posted_delta_30m,
                p.posted_delta_60m,
                p.posted_rolling_mean_30m,
                p.posted_rolling_mean_60m,
                p.posted_volatility_30m,
                p.park_code,
                dg.date_group_id,
                s.season,
                s.season_year,
                EXTRACT(HOUR FROM p.observed_at_ts) as hour_of_day,
                (EXTRACT(HOUR FROM p.observed_at_ts) - 6) * 60 
                    + EXTRACT(MINUTE FROM p.observed_at_ts) as mins_since_6am,
                CASE 
                    WHEN ph.open_hour IS NOT NULL THEN
                        (EXTRACT(HOUR FROM p.observed_at_ts) - ph.open_hour) * 60 
                        + (EXTRACT(MINUTE FROM p.observed_at_ts) - ph.open_minute)
                    ELSE NULL
                END as mins_since_open
            FROM posted_with_rolling p
            LEFT JOIN dategroupid dg ON p.park_date = dg.park_date
            LEFT JOIN season s ON p.park_date = s.park_date
            LEFT JOIN parkhours ph ON p.park_code = UPPER(ph.park) 
                                   AND p.park_date = ph.park_date
            WHERE dg.date_group_id IS NOT NULL
              AND s.season IS NOT NULL
        """
        
        df = chunk_con.execute(query).fetchdf()
        chunk_con.close()
        
        if len(df) == 0:
            if logger:
                logger.info(f"    No data after joins for park {park_code}, skipping")
            continue
        
        # Encode categoricals
        df['entity_encoded'] = df['entity_code'].map(entity_map).fillna(-1).astype(int)
        df['park_encoded'] = df['park_code'].map(park_map).fillna(-1).astype(int)
        df['date_group_id_encoded'] = df['date_group_id'].map(dg_map).fillna(-1).astype(int)
        df['season_encoded'] = df['season'].map(season_map).fillna(-1).astype(int)
        
        for col in ['posted_delta_15m', 'posted_delta_30m', 'posted_delta_60m',
                     'posted_rolling_mean_30m', 'posted_rolling_mean_60m', 'posted_volatility_30m']:
            if col in df.columns:
                df[col] = df[col].fillna(0)
        if 'mins_since_open' in df.columns:
            df['mins_since_open'] = df['mins_since_open'].fillna(df['mins_since_6am'])
        
        for col in feature_names:
            if col not in df.columns:
                df[col] = 0
        
        # Run inference
        X = df[feature_names].values
        dmatrix = xgb.DMatrix(X, feature_names=feature_names)
        predictions = model.predict(dmatrix)
        predictions = np.clip(predictions, MIN_REASONABLE_WAIT, MAX_REASONABLE_WAIT)
        df['synthetic_actual'] = predictions
        df['source'] = 'synthetic'
        
        total_posted_sum += df['posted_time'].sum()
        total_synth_sum += df['synthetic_actual'].sum()
        
        # Save per-entity parquet files
        for entity_code, entity_df in df.groupby('entity_code'):
            entity_path = output_dir / f"{entity_code}.parquet"
            entity_df[output_cols].to_parquet(entity_path, index=False)
            entities_saved += 1
            total_rows_saved += len(entity_df)
        
        if logger:
            logger.info(f"    {len(df):,} rows → {df['entity_code'].nunique()} entities saved")
        
        del df, X, dmatrix, predictions
    
    total_elapsed = time.time() - start
    
    avg_posted = total_posted_sum / total_rows_saved if total_rows_saved else 0
    avg_synth = total_synth_sum / total_rows_saved if total_rows_saved else 0
    
    summary = {
        "entities_processed": entities_saved,
        "total_synthetic_rows": total_rows_saved,
        "avg_synthetic_actual": float(avg_synth),
        "avg_posted_input": float(avg_posted),
        "avg_reduction_minutes": float(avg_posted - avg_synth),
        "elapsed_seconds": total_elapsed,
    }
    
    # Save summary
    summary_path = output_dir / "generation_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    
    if logger:
        logger.info("============================================================")
        logger.info("SYNTHETIC ACTUALS GENERATION COMPLETE")
        logger.info("============================================================")
        logger.info(f"  Entities: {entities_saved}")
        logger.info(f"  Total synthetic rows: {total_rows_saved:,}")
        logger.info(f"  Output: {output_dir}")
        logger.info(f"  ⏱️  Total time: {total_elapsed:.1f}s")
    
    return summary


def get_synthetic_summary(output_base: Path) -> Optional[Dict]:
    """Load the generation summary if it exists."""
    summary_path = output_base / "synthetic_actuals" / "generation_summary.json"
    if summary_path.exists():
        with open(summary_path) as f:
            return json.load(f)
    return None
