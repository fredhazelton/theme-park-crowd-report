"""
POSTED to ACTUAL Conversion Model

================================================================================
PURPOSE
================================================================================
Trains a global conversion model that transforms POSTED wait times to ACTUAL 
wait times. Uses matched (POSTED, ACTUAL) pairs from all STANDBY entities to
learn the systematic bias and lag patterns in posted wait times.

The model captures:
  - Disney's intentional overestimation buffer (POSTED > ACTUAL)
  - Human lag in updating posted times  
  - Trend dynamics (rising/falling queues affect bias)
  - Time-of-day and entity-specific patterns

================================================================================
ARCHITECTURE
================================================================================
Uses DuckDB + Parquet for fast bulk data loading (matching hybrid_pipeline_v2
pattern). Rolling features computed via DuckDB window functions.

Model: XGBoost with reg:absoluteerror (MAE objective).
Training: Global model pooled across all STANDBY entities.
Validation: Chronological split (70/15/15 by park_date).

================================================================================
USAGE
================================================================================
  # As module:
  from processors.posted_to_actual import train_conversion_model, load_conversion_model
  metrics = train_conversion_model(output_base, logger)
  model, metadata = load_conversion_model(output_base)

  # As CLI:
  python scripts/train_conversion_model.py --output-base /mnt/data/pipeline
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from zoneinfo import ZoneInfo

try:
    import xgboost as xgb
except ImportError:
    xgb = None


# =============================================================================
# CONFIGURATION
# =============================================================================

MATCH_WINDOW_MINUTES = 15
ROLLING_WINDOWS = [15, 30, 60]  # minutes

# XGBoost params (aligned with hybrid pipeline / Julia defaults)
CONVERSION_XGB_PARAMS = {
    "objective": "reg:absoluteerror",
    "tree_method": "hist",
    "max_depth": 6,
    "learning_rate": 0.1,
    "n_estimators": 2000,
    "subsample": 0.5,
    "colsample_bytree": 1.0,
    "min_child_weight": 10,
    "random_state": 42,
    "verbosity": 0,
}
EARLY_STOPPING_ROUNDS = 50

# Feature columns for the conversion model
FEATURE_COLS = [
    "posted_time",
    "posted_delta_15m",
    "posted_delta_30m",
    "posted_delta_60m",
    "posted_rolling_mean_30m",
    "posted_rolling_mean_60m",
    "posted_volatility_30m",
    "hour_of_day",
    "mins_since_6am",
    "mins_since_open",
    "entity_encoded",
    "park_encoded",
    "date_group_id_encoded",
    "season_encoded",
]


# =============================================================================
# DATA LOADING (DuckDB + Parquet, matching hybrid_pipeline_v2 pattern)
# =============================================================================

def build_matched_pairs(
    output_base: Path,
    logger: Optional[logging.Logger] = None,
) -> pd.DataFrame:
    """
    Build matched (POSTED, ACTUAL) pairs with rolling features using DuckDB.
    
    Follows the hybrid_pipeline_v2 pattern:
    - Reads from fact_tables/parquet/*.parquet
    - Joins dimension tables for date_group_id, season, park hours
    - Computes rolling POSTED features via window functions
    - Filters to STANDBY entities only
    
    Returns:
        DataFrame with matched pairs, rolling features, and dimension features
    """
    if logger:
        logger.info("Building matched (POSTED, ACTUAL) pairs via DuckDB...")
    
    start = time.time()
    con = duckdb.connect()
    
    parquet_dir = output_base / "fact_tables" / "parquet"
    dim_dir = output_base / "dimension_tables"
    dategroupid_path = dim_dir / "dimdategroupid.csv"
    season_path = dim_dir / "dimseason.csv"
    parkhours_path = dim_dir / "dimparkhours.csv"
    dimentity_path = dim_dir / "dimentity.csv"
    
    for p in [parquet_dir, dategroupid_path, season_path, dimentity_path]:
        if not p.exists():
            raise FileNotFoundError(f"Required path not found: {p}")
    
    # Step 1: Get STANDBY entity codes
    standby_entities = con.execute(f"""
        SELECT code FROM read_csv('{dimentity_path}', AUTO_DETECT=TRUE)
        WHERE fastpass_booth = FALSE
    """).fetchdf()["code"].tolist()
    
    if logger:
        logger.info(f"  Found {len(standby_entities)} STANDBY entities")
    
    # Step 2: Build matched pairs with rolling features in one DuckDB query
    # We do this in two stages:
    # (a) First get all POSTED data with rolling features via window functions
    # (b) Then match ACTUAL to nearest POSTED with features
    
    query = f"""
        -- Stage 1: All POSTED observations with rolling window features
        WITH posted_raw AS (
            SELECT 
                entity_code,
                observed_at_ts,
                park_date,
                wait_time_minutes as posted_time,
                UPPER(SUBSTRING(entity_code, 1, 2)) as park_code
            FROM read_parquet('{parquet_dir}/*.parquet')
            WHERE wait_time_type = 'POSTED'
              AND wait_time_minutes IS NOT NULL
              AND wait_time_minutes > 0
              AND entity_code IN (SELECT UNNEST({standby_entities}::VARCHAR[]))
        ),
        
        -- Add rolling features using window functions over POSTED time series
        posted_with_rolling AS (
            SELECT 
                *,
                -- Delta features (change over prior N minutes)
                posted_time - LAG(posted_time, 3) OVER w as posted_delta_15m,   -- ~3 obs * 5min = 15min
                posted_time - LAG(posted_time, 6) OVER w as posted_delta_30m,   -- ~6 obs * 5min = 30min
                posted_time - LAG(posted_time, 12) OVER w as posted_delta_60m,  -- ~12 obs * 5min = 60min
                
                -- Rolling mean (approximate via preceding rows at 5-min intervals)
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
                
                -- Rolling volatility (stddev)
                STDDEV_POP(posted_time) OVER (
                    PARTITION BY entity_code, park_date 
                    ORDER BY observed_at_ts
                    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
                ) as posted_volatility_30m
                
            FROM posted_raw
            WINDOW w AS (PARTITION BY entity_code, park_date ORDER BY observed_at_ts)
        ),
        
        -- Stage 2: ACTUAL observations
        actual AS (
            SELECT 
                entity_code,
                observed_at,
                observed_at_ts,
                park_date,
                wait_time_minutes as actual_time
            FROM read_parquet('{parquet_dir}/*.parquet')
            WHERE wait_time_type = 'ACTUAL'
              AND wait_time_minutes IS NOT NULL
              AND wait_time_minutes > 0
              AND entity_code IN (SELECT UNNEST({standby_entities}::VARCHAR[]))
        ),
        
        -- Stage 3: Match each ACTUAL to closest POSTED (within 15-min window)
        matched AS (
            SELECT 
                a.entity_code,
                a.observed_at,
                a.observed_at_ts,
                a.park_date,
                a.actual_time,
                p.posted_time,
                p.posted_delta_15m,
                p.posted_delta_30m,
                p.posted_delta_60m,
                p.posted_rolling_mean_30m,
                p.posted_rolling_mean_60m,
                p.posted_volatility_30m,
                p.park_code,
                ABS(EXTRACT(EPOCH FROM (a.observed_at_ts - p.observed_at_ts))) as time_diff_sec,
                ROW_NUMBER() OVER (
                    PARTITION BY a.entity_code, a.observed_at 
                    ORDER BY ABS(EXTRACT(EPOCH FROM (a.observed_at_ts - p.observed_at_ts)))
                ) as rn
            FROM actual a
            JOIN posted_with_rolling p 
              ON a.entity_code = p.entity_code 
              AND a.park_date = p.park_date
              AND ABS(EXTRACT(EPOCH FROM (a.observed_at_ts - p.observed_at_ts))) <= {MATCH_WINDOW_MINUTES * 60}
        ),
        
        -- Stage 4: Keep only best match per ACTUAL observation
        best_match AS (
            SELECT * FROM matched WHERE rn = 1
        ),
        
        -- Stage 5: Join dimension tables
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
            bm.entity_code,
            bm.observed_at,
            bm.park_date,
            bm.actual_time,
            bm.posted_time,
            bm.posted_delta_15m,
            bm.posted_delta_30m,
            bm.posted_delta_60m,
            bm.posted_rolling_mean_30m,
            bm.posted_rolling_mean_60m,
            bm.posted_volatility_30m,
            bm.park_code,
            dg.date_group_id,
            s.season,
            s.season_year,
            -- Time features
            EXTRACT(HOUR FROM bm.observed_at_ts) as hour_of_day,
            (EXTRACT(HOUR FROM bm.observed_at_ts) - 6) * 60 
                + EXTRACT(MINUTE FROM bm.observed_at_ts) as mins_since_6am,
            CASE 
                WHEN ph.open_hour IS NOT NULL THEN
                    (EXTRACT(HOUR FROM bm.observed_at_ts) - ph.open_hour) * 60 
                    + (EXTRACT(MINUTE FROM bm.observed_at_ts) - ph.open_minute)
                ELSE NULL
            END as mins_since_open
        FROM best_match bm
        LEFT JOIN dategroupid dg ON bm.park_date = dg.park_date
        LEFT JOIN season s ON bm.park_date = s.park_date
        LEFT JOIN parkhours ph ON bm.park_code = UPPER(ph.park) 
                               AND bm.park_date = ph.park_date
        WHERE dg.date_group_id IS NOT NULL
          AND s.season IS NOT NULL
    """
    
    if logger:
        logger.info("  Running DuckDB matched pairs query with rolling features...")
    
    df = con.execute(query).fetchdf()
    con.close()
    
    elapsed = time.time() - start
    
    if logger:
        logger.info(f"  Built {len(df):,} matched pairs in {elapsed:.1f}s")
        logger.info(f"  Entities with pairs: {df['entity_code'].nunique()}")
        logger.info(f"  Date range: {df['park_date'].min()} to {df['park_date'].max()}")
        
        # Stats on the POSTED→ACTUAL relationship
        bias = (df['posted_time'] - df['actual_time']).mean()
        logger.info(f"  Avg POSTED overestimation: {bias:.1f} minutes")
    
    return df


def _encode_categoricals(df: pd.DataFrame, logger: Optional[logging.Logger] = None) -> Tuple[pd.DataFrame, Dict]:
    """Label-encode categorical features and return encodings."""
    encodings = {}
    
    # Entity encoding
    entities = sorted(df['entity_code'].unique())
    entity_map = {e: i for i, e in enumerate(entities)}
    df['entity_encoded'] = df['entity_code'].map(entity_map)
    encodings['entity_code'] = entity_map
    
    # Park encoding
    parks = sorted(df['park_code'].unique())
    park_map = {p: i for i, p in enumerate(parks)}
    df['park_encoded'] = df['park_code'].map(park_map)
    encodings['park_code'] = park_map
    
    # Date group encoding
    dg = sorted(df['date_group_id'].unique())
    dg_map = {d: i for i, d in enumerate(dg)}
    df['date_group_id_encoded'] = df['date_group_id'].map(dg_map)
    encodings['date_group_id'] = {str(k): v for k, v in dg_map.items()}
    
    # Season encoding
    seasons = sorted(df['season'].unique())
    season_map = {s: i for i, s in enumerate(seasons)}
    df['season_encoded'] = df['season'].map(season_map)
    encodings['season'] = season_map
    
    if logger:
        logger.info(f"  Encoded: {len(entities)} entities, {len(parks)} parks, "
                     f"{len(dg)} date groups, {len(seasons)} seasons")
    
    return df, encodings


# =============================================================================
# MODEL TRAINING
# =============================================================================

def train_conversion_model(
    output_base: Path,
    logger: Optional[logging.Logger] = None,
) -> Dict:
    """
    Train the global POSTED→ACTUAL conversion model.
    
    1. Builds matched pairs via DuckDB (fast)
    2. Encodes categoricals
    3. Chronological train/val/test split
    4. Trains XGBoost model
    5. Saves model and metadata
    
    Returns:
        Dictionary of test set metrics
    """
    if xgb is None:
        raise ImportError("XGBoost not installed")
    
    if logger:
        logger.info("Training POSTED→ACTUAL conversion model...")
    
    # Step 1: Build matched pairs
    df = build_matched_pairs(output_base, logger)
    
    if len(df) < 100:
        raise ValueError(f"Not enough matched pairs ({len(df)}). Need at least 100.")
    
    # Step 2: Encode categoricals
    if logger:
        logger.info("Encoding categorical features...")
    df, encodings = _encode_categoricals(df, logger)
    
    # Step 3: Fill nulls in rolling features (first few rows per entity/date will have nulls)
    for col in ['posted_delta_15m', 'posted_delta_30m', 'posted_delta_60m',
                'posted_rolling_mean_30m', 'posted_rolling_mean_60m', 'posted_volatility_30m']:
        if col in df.columns:
            df[col] = df[col].fillna(0)
    
    if 'mins_since_open' in df.columns:
        df['mins_since_open'] = df['mins_since_open'].fillna(df['mins_since_6am'])
    
    # Step 4: Chronological split by park_date
    unique_dates = sorted(df['park_date'].unique())
    n_dates = len(unique_dates)
    train_end = int(n_dates * 0.70)
    val_end = int(n_dates * 0.85)
    
    train_dates = set(unique_dates[:train_end])
    val_dates = set(unique_dates[train_end:val_end])
    test_dates = set(unique_dates[val_end:])
    
    train_df = df[df['park_date'].isin(train_dates)]
    val_df = df[df['park_date'].isin(val_dates)]
    test_df = df[df['park_date'].isin(test_dates)]
    
    if logger:
        logger.info(f"  Split: train={len(train_df):,}, val={len(val_df):,}, test={len(test_df):,}")
        logger.info(f"  Train dates: {min(train_dates)} to {max(train_dates)}")
        logger.info(f"  Val dates:   {min(val_dates)} to {max(val_dates)}")
        logger.info(f"  Test dates:  {min(test_dates)} to {max(test_dates)}")
    
    # Step 5: Prepare features and target
    available_features = [c for c in FEATURE_COLS if c in df.columns]
    
    X_train = train_df[available_features].values
    y_train = train_df['actual_time'].values
    X_val = val_df[available_features].values
    y_val = val_df['actual_time'].values
    X_test = test_df[available_features].values
    y_test = test_df['actual_time'].values
    
    if logger:
        logger.info(f"  Features ({len(available_features)}): {available_features}")
    
    # Step 6: Train XGBoost
    if logger:
        logger.info("  Training XGBoost conversion model...")
    
    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=available_features)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=available_features)
    dtest = xgb.DMatrix(X_test, label=y_test, feature_names=available_features)
    
    params = {k: v for k, v in CONVERSION_XGB_PARAMS.items() if k != 'n_estimators'}
    
    model = xgb.train(
        params=params,
        dtrain=dtrain,
        num_boost_round=CONVERSION_XGB_PARAMS['n_estimators'],
        evals=[(dtrain, 'train'), (dval, 'val')],
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        verbose_eval=False,
    )
    
    best_round = getattr(model, 'best_iteration', CONVERSION_XGB_PARAMS['n_estimators'])
    if logger:
        logger.info(f"  Best iteration: {best_round}")
    
    # Step 7: Evaluate on test set
    y_pred = model.predict(dtest)
    
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    r2 = r2_score(y_test, y_pred)
    correlation = np.corrcoef(y_test, y_pred)[0, 1]
    bias = float(np.mean(y_pred - y_test))
    
    metrics = {
        "mae": float(mae),
        "rmse": float(rmse),
        "r2": float(r2),
        "correlation": float(correlation),
        "bias": bias,
        "n_train": len(train_df),
        "n_val": len(val_df),
        "n_test": len(test_df),
        "n_total": len(df),
        "n_entities": int(df['entity_code'].nunique()),
        "best_iteration": int(best_round),
        "avg_posted_overestimation": float((df['posted_time'] - df['actual_time']).mean()),
    }
    
    if logger:
        logger.info("  ============================================================")
        logger.info("  CONVERSION MODEL RESULTS (test set)")
        logger.info("  ============================================================")
        logger.info(f"  MAE:         {mae:.2f} minutes")
        logger.info(f"  RMSE:        {rmse:.2f} minutes")
        logger.info(f"  R²:          {r2:.4f}")
        logger.info(f"  Correlation: {correlation:.4f}")
        logger.info(f"  Bias:        {bias:+.2f} minutes")
        logger.info(f"  Pairs used:  {len(df):,} from {df['entity_code'].nunique()} entities")
    
    # Step 8: Save model and metadata
    model_dir = output_base / "models" / "_conversion"
    model_dir.mkdir(parents=True, exist_ok=True)
    
    model_path = model_dir / "model.json"
    model.save_model(str(model_path))
    
    metadata = {
        "created_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        "metrics": metrics,
        "feature_names": available_features,
        "encodings": encodings,
        "params": CONVERSION_XGB_PARAMS,
        "match_window_minutes": MATCH_WINDOW_MINUTES,
    }
    
    metadata_path = model_dir / "metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False, default=str)
    
    if logger:
        logger.info(f"  Saved model: {model_path}")
        logger.info(f"  Saved metadata: {metadata_path}")
    
    return metrics


# =============================================================================
# MODEL LOADING & INFERENCE
# =============================================================================

def load_conversion_model(output_base: Path) -> Tuple[xgb.Booster, Dict]:
    """Load the saved conversion model and metadata."""
    if xgb is None:
        raise ImportError("XGBoost not installed")
    
    model_dir = output_base / "models" / "_conversion"
    model_path = model_dir / "model.json"
    metadata_path = model_dir / "metadata.json"
    
    if not model_path.exists():
        raise FileNotFoundError(f"Conversion model not found: {model_path}")
    
    model = xgb.Booster()
    model.load_model(str(model_path))
    
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    
    return model, metadata


def convert_posted_to_actual(
    posted_df: pd.DataFrame,
    model: xgb.Booster,
    metadata: Dict,
) -> np.ndarray:
    """
    Apply the conversion model to predict ACTUAL from POSTED observations.
    
    Args:
        posted_df: DataFrame with the same feature columns used in training
        model: Loaded XGBoost Booster
        metadata: Model metadata (contains feature_names)
    
    Returns:
        numpy array of predicted ACTUAL wait times
    """
    feature_names = metadata['feature_names']
    
    # Ensure all features present, fill missing with 0
    for col in feature_names:
        if col not in posted_df.columns:
            posted_df[col] = 0
    
    X = posted_df[feature_names].values
    dmatrix = xgb.DMatrix(X, feature_names=feature_names)
    predictions = model.predict(dmatrix)
    
    # Clamp to reasonable range
    predictions = np.clip(predictions, 0, 300)
    
    return predictions
