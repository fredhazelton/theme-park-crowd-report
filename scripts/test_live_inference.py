#!/usr/bin/env python3
"""
Test Live Inference Model

Tests the live inference model against today's queue-times staging data.
This validates that the model can work on real live data and provides
insights into prediction accuracy and distribution.

Process:
1. Load the trained live inference model
2. Read today's queue-times staging data (POSTED observations)
3. Run live inference on each POSTED observation
4. Output summary statistics and sample predictions
5. If ACTUAL data exists in fact tables, compare against ground truth

Usage:
    python scripts/test_live_inference.py
    python scripts/test_live_inference.py --output-base /mnt/data/pipeline --date 2026-02-14
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import numpy as np
from zoneinfo import ZoneInfo

# Add src to path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from processors.live_inference import LiveInferenceModel
from utils.paths import get_output_base


def setup_logging() -> logging.Logger:
    """Set up console logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    
    logger = logging.getLogger(__name__)
    return logger


def find_todays_staging_files(staging_dir: Path, target_date: date) -> List[Path]:
    """Find today's queue-times staging files."""
    
    # Look for files matching the date pattern
    date_str = target_date.strftime("%Y-%m-%d")
    year_month = target_date.strftime("%Y-%m")
    
    pattern_dir = staging_dir / "queue_times" / year_month
    
    if not pattern_dir.exists():
        return []
    
    # Find files with today's date in the name
    matching_files = list(pattern_dir.glob(f"*{date_str}*"))
    
    return sorted(matching_files)


def load_staging_data(files: List[Path], logger: logging.Logger) -> pd.DataFrame:
    """Load and combine staging data from multiple files."""
    
    if not files:
        return pd.DataFrame()
    
    logger.info(f"Loading staging data from {len(files)} files:")
    for f in files:
        logger.info(f"  {f}")
    
    dfs = []
    total_rows = 0
    
    for file_path in files:
        try:
            df = pd.read_csv(file_path)
            dfs.append(df)
            total_rows += len(df)
            logger.info(f"    {len(df):,} rows")
        except Exception as e:
            logger.warning(f"    Error reading {file_path}: {e}")
    
    if not dfs:
        return pd.DataFrame()
    
    combined_df = pd.concat(dfs, ignore_index=True)
    logger.info(f"Total combined: {len(combined_df):,} rows")
    
    return combined_df


def load_actual_data_for_comparison(output_base: Path, target_date: date, logger: logging.Logger) -> Optional[pd.DataFrame]:
    """Load actual wait times from fact tables for comparison if available."""
    
    try:
        # Look for parquet files in fact_tables
        fact_dir = output_base / "fact_tables" / "parquet"
        
        if not fact_dir.exists():
            logger.info("No fact tables directory found for comparison")
            return None
        
        # Find parquet files (usually named by date/batch)
        parquet_files = list(fact_dir.glob("*.parquet"))
        
        if not parquet_files:
            logger.info("No parquet files found for comparison")
            return None
        
        # Read all parquet files and filter for today + ACTUAL
        import duckdb
        con = duckdb.connect()
        
        date_str = target_date.strftime("%Y-%m-%d")
        
        query = f"""
        SELECT entity_code, observed_at, wait_time_minutes as actual_time
        FROM read_parquet('{fact_dir}/*.parquet')
        WHERE wait_time_type = 'ACTUAL'
          AND wait_time_minutes IS NOT NULL
          AND wait_time_minutes > 0
          AND DATE(observed_at) = '{date_str}'
        """
        
        actual_df = con.execute(query).fetchdf()
        con.close()
        
        if len(actual_df) > 0:
            actual_df['observed_at'] = pd.to_datetime(actual_df['observed_at'], utc=True)
            logger.info(f"Found {len(actual_df):,} ACTUAL observations for comparison")
            return actual_df
        else:
            logger.info("No ACTUAL observations found for today")
            return None
            
    except Exception as e:
        logger.warning(f"Could not load actual data for comparison: {e}")
        return None


def match_actual_to_predictions(predictions_df: pd.DataFrame, actual_df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """Match ACTUAL observations to predictions for accuracy measurement."""
    
    matches = []
    
    for _, actual_row in actual_df.iterrows():
        entity_code = actual_row['entity_code']
        actual_time = actual_row['actual_time']
        actual_observed = actual_row['observed_at']
        
        # Find predictions for same entity
        entity_preds = predictions_df[predictions_df['entity_code'] == entity_code].copy()
        
        if len(entity_preds) == 0:
            continue
        
        # Find closest prediction in time (within 30 minutes)
        entity_preds['time_diff'] = abs((pd.to_datetime(entity_preds['observed_at']) - actual_observed).dt.total_seconds())
        entity_preds = entity_preds[entity_preds['time_diff'] <= 1800]  # 30 minutes
        
        if len(entity_preds) > 0:
            # Take closest match
            closest_match = entity_preds.loc[entity_preds['time_diff'].idxmin()]
            
            matches.append({
                'entity_code': entity_code,
                'actual_time': actual_time,
                'predicted_actual': closest_match['predicted_actual'],
                'posted_time': closest_match['posted_time'],
                'adjustment': closest_match['adjustment'],
                'method': closest_match['method'],
                'time_diff': closest_match['time_diff']
            })
    
    if matches:
        matches_df = pd.DataFrame(matches)
        logger.info(f"Matched {len(matches_df):,} predictions to actual observations")
        return matches_df
    else:
        logger.info("No matches found between predictions and actual observations")
        return pd.DataFrame()


def analyze_predictions(predictions_df: pd.DataFrame, matches_df: Optional[pd.DataFrame], logger: logging.Logger):
    """Analyze and report on prediction results."""
    
    logger.info("=" * 60)
    logger.info("LIVE INFERENCE TEST RESULTS")
    logger.info("=" * 60)
    
    if len(predictions_df) == 0:
        logger.warning("No predictions to analyze")
        return
    
    # Overall stats
    logger.info(f"Total predictions: {len(predictions_df):,}")
    logger.info(f"Unique entities: {predictions_df['entity_code'].nunique()}")
    logger.info(f"Time range: {predictions_df['observed_at'].min()} to {predictions_df['observed_at'].max()}")
    logger.info("")
    
    # Method breakdown
    method_counts = predictions_df['method'].value_counts()
    logger.info("Method breakdown:")
    for method, count in method_counts.items():
        pct = 100 * count / len(predictions_df)
        logger.info(f"  {method}: {count:,} ({pct:.1f}%)")
    logger.info("")
    
    # Per-park stats
    predictions_df['park_code'] = predictions_df['entity_code'].str[:6]
    park_stats = predictions_df.groupby('park_code').agg({
        'posted_time': ['count', 'mean'],
        'predicted_actual': 'mean',
        'adjustment': 'mean'
    }).round(1)
    
    logger.info("Per-park summary:")
    logger.info("Park      | Count  | Avg Posted | Avg Predicted | Avg Adjustment")
    logger.info("----------|--------|------------|---------------|---------------")
    for park in park_stats.index:
        count = int(park_stats.loc[park, ('posted_time', 'count')])
        avg_posted = park_stats.loc[park, ('posted_time', 'mean')]
        avg_predicted = park_stats.loc[park, ('predicted_actual', 'mean')]
        avg_adj = park_stats.loc[park, ('adjustment', 'mean')]
        logger.info(f"{park:<9} | {count:6,} | {avg_posted:10.1f} | {avg_predicted:13.1f} | {avg_adj:+13.1f}")
    logger.info("")
    
    # Adjustment distribution
    adjustments = predictions_df['adjustment']
    logger.info("Adjustment distribution:")
    logger.info(f"  Mean: {adjustments.mean():+.1f} minutes")
    logger.info(f"  Median: {adjustments.median():+.1f} minutes")
    logger.info(f"  Std: {adjustments.std():.1f} minutes")
    logger.info(f"  Min: {adjustments.min():+.0f} minutes")
    logger.info(f"  Max: {adjustments.max():+.0f} minutes")
    
    # Percentiles
    percentiles = [5, 25, 50, 75, 95]
    pct_values = np.percentile(adjustments, percentiles)
    logger.info("  Percentiles: " + " | ".join([f"P{p}={v:+.0f}" for p, v in zip(percentiles, pct_values)]))
    logger.info("")
    
    # Sample predictions
    logger.info("Sample predictions:")
    sample_size = min(10, len(predictions_df))
    sample = predictions_df.sample(sample_size).sort_values('posted_time', ascending=False)
    
    logger.info("Entity           | Posted | Predicted | Adj | Method")
    logger.info("-----------------|--------|-----------|-----|------------")
    for _, row in sample.iterrows():
        entity = row['entity_code'][:16]
        posted = int(row['posted_time'])
        predicted = int(row['predicted_actual'])
        adj = int(row['adjustment'])
        method = row['method'][:12]
        logger.info(f"{entity:<16} | {posted:6} | {predicted:9} | {adj:+3} | {method}")
    logger.info("")
    
    # Accuracy vs actual if available
    if matches_df is not None and len(matches_df) > 0:
        logger.info("ACCURACY AGAINST ACTUAL WAIT TIMES:")
        logger.info("=" * 40)
        
        mae = np.mean(abs(matches_df['predicted_actual'] - matches_df['actual_time']))
        rmse = np.sqrt(np.mean((matches_df['predicted_actual'] - matches_df['actual_time'])**2))
        bias = np.mean(matches_df['predicted_actual'] - matches_df['actual_time'])
        correlation = np.corrcoef(matches_df['predicted_actual'], matches_df['actual_time'])[0, 1]
        
        logger.info(f"Matches: {len(matches_df):,}")
        logger.info(f"MAE: {mae:.2f} minutes")
        logger.info(f"RMSE: {rmse:.2f} minutes")
        logger.info(f"Bias: {bias:+.2f} minutes")
        logger.info(f"Correlation: {correlation:.3f}")
        logger.info("")
        
        # Sample comparisons
        logger.info("Sample actual vs predicted:")
        sample_matches = matches_df.sample(min(8, len(matches_df))).sort_values('actual_time', ascending=False)
        
        logger.info("Entity           | Posted | Predicted | Actual | Error | Method")
        logger.info("-----------------|--------|-----------|--------|-------|--------")
        for _, row in sample_matches.iterrows():
            entity = row['entity_code'][:16]
            posted = int(row['posted_time'])
            predicted = int(row['predicted_actual'])
            actual = int(row['actual_time'])
            error = predicted - actual
            method = row['method'][:8]
            logger.info(f"{entity:<16} | {posted:6} | {predicted:9} | {actual:6} | {error:+5} | {method}")
        logger.info("")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test live inference model on today's data")
    parser.add_argument(
        "--output-base",
        type=Path,
        default=get_output_base(),
        help="Output base directory (default: from config)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date to test (YYYY-MM-DD format, default: today)",
    )
    
    args = parser.parse_args()
    
    output_base = args.output_base.resolve()
    logger = setup_logging()
    
    # Parse target date
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"Invalid date format: {args.date}. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        target_date = date.today()
    
    logger.info("=" * 60)
    logger.info("TEST LIVE INFERENCE MODEL")
    logger.info("=" * 60)
    logger.info(f"Output base: {output_base}")
    logger.info(f"Target date: {target_date}")
    logger.info("")
    
    try:
        # Step 1: Load the live inference model
        logger.info("Loading live inference model...")
        model = LiveInferenceModel(output_base)
        logger.info("")
        
        # Step 2: Find and load today's staging data
        logger.info("Loading today's staging data...")
        staging_dir = output_base / "staging"
        staging_files = find_todays_staging_files(staging_dir, target_date)
        
        if not staging_files:
            logger.warning(f"No staging files found for {target_date}")
            sys.exit(1)
        
        staging_df = load_staging_data(staging_files, logger)
        
        if len(staging_df) == 0:
            logger.warning("No staging data loaded")
            sys.exit(1)
        
        logger.info("")
        
        # Step 3: Filter to POSTED observations and prepare for inference
        logger.info("Preparing data for inference...")
        
        # Filter to POSTED observations
        posted_df = staging_df[
            (staging_df['wait_time_type'] == 'POSTED') &
            (staging_df['wait_time_minutes'].notna()) &
            (staging_df['wait_time_minutes'] > 0)
        ].copy()
        
        if len(posted_df) == 0:
            logger.warning("No POSTED observations found")
            sys.exit(1)
        
        # Convert observed_at to datetime
        posted_df['observed_at'] = pd.to_datetime(posted_df['observed_at'], utc=True)
        
        logger.info(f"Found {len(posted_df):,} POSTED observations")
        logger.info(f"Entities: {posted_df['entity_code'].nunique()}")
        logger.info(f"Time range: {posted_df['observed_at'].min()} to {posted_df['observed_at'].max()}")
        logger.info("")
        
        # Step 4: Run live inference
        logger.info("Running live inference...")
        
        observations = []
        for _, row in posted_df.iterrows():
            observations.append({
                'entity_code': row['entity_code'],
                'posted_time': float(row['wait_time_minutes']),
                'observed_at': row['observed_at'].to_pydatetime()
            })
        
        # Batch predict
        predictions = model.predict_batch(observations)
        
        # Convert back to DataFrame for analysis
        predictions_df = pd.DataFrame(predictions)
        predictions_df['observed_at'] = posted_df['observed_at'].values
        
        logger.info(f"Generated {len(predictions_df):,} predictions")
        logger.info("")
        
        # Step 5: Load actual data for comparison if available
        logger.info("Looking for ACTUAL data for comparison...")
        actual_df = load_actual_data_for_comparison(output_base, target_date, logger)
        
        matches_df = None
        if actual_df is not None:
            matches_df = match_actual_to_predictions(predictions_df, actual_df, logger)
        
        logger.info("")
        
        # Step 6: Analyze and report results
        analyze_predictions(predictions_df, matches_df, logger)
        
        logger.info("=" * 60)
        logger.info("TEST COMPLETE")
        logger.info("=" * 60)
        
        # Success
        sys.exit(0)
        
    except Exception as e:
        logger.exception(f"Test failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()