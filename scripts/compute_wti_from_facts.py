#!/usr/bin/env python3
"""
Compute WTI (Wait Time Index) from fact tables for all parks.

WTI = daily average wait time across all attractions in a park.
- Uses ACTUAL when available, falls back to POSTED
- One WTI value per park per day
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# Add src to path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.paths import get_output_base


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger(__name__)


def compute_wti_for_park_date(df: pd.DataFrame) -> dict:
    """Compute WTI for a single park-date from fact data."""
    # Prefer ACTUAL, fall back to POSTED
    actual = df[df['wait_time_type'] == 'ACTUAL']
    posted = df[df['wait_time_type'] == 'POSTED']
    
    if not actual.empty:
        # Use ACTUAL - average across all observations
        wti = actual['wait_time_minutes'].mean()
        n_entities = actual['entity_code'].nunique()
        source = 'historical_actual'
    elif not posted.empty:
        # Fall back to POSTED
        wti = posted['wait_time_minutes'].mean()
        n_entities = posted['entity_code'].nunique()
        source = 'historical_posted'
    else:
        return None
    
    return {
        'wti': round(wti, 2),
        'n_entities': n_entities,
        'source': source,
    }


def main():
    parser = argparse.ArgumentParser(description="Compute WTI from fact tables")
    parser.add_argument("--output-base", type=str, help="Pipeline output base")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--parks", type=str, help="Comma-separated park codes (default: all)")
    args = parser.parse_args()
    
    logger = setup_logging()
    
    if args.output_base:
        output_base = Path(args.output_base)
    else:
        output_base = get_output_base()
    
    fact_dir = output_base / "fact_tables" / "clean"
    wti_dir = output_base / "wti"
    wti_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Computing WTI from: {fact_dir}")
    
    # Collect all park-date combinations
    results = []
    months = sorted([d for d in fact_dir.iterdir() if d.is_dir()])
    
    for month_dir in months:
        for fact_file in month_dir.glob("*.csv"):
            # Parse park and date from filename: {park}_{date}.csv
            parts = fact_file.stem.split('_')
            if len(parts) < 2:
                continue
            
            park_code = parts[0]
            park_date_str = parts[1]
            
            # Filter by park if specified
            if args.parks:
                allowed = [p.strip().lower() for p in args.parks.split(',')]
                if park_code.lower() not in allowed:
                    continue
            
            # Filter by date range
            try:
                park_date = date.fromisoformat(park_date_str)
            except ValueError:
                continue
            
            if args.start_date and park_date < date.fromisoformat(args.start_date):
                continue
            if args.end_date and park_date > date.fromisoformat(args.end_date):
                continue
            
            # Load and compute WTI
            try:
                df = pd.read_csv(fact_file)
                wti_data = compute_wti_for_park_date(df)
                
                if wti_data:
                    results.append({
                        'park_code': park_code,
                        'park_date': park_date_str,
                        **wti_data,
                    })
            except Exception as e:
                logger.warning(f"Error processing {fact_file}: {e}")
    
    if not results:
        logger.error("No WTI data computed")
        return
    
    # Create DataFrame and save
    wti_df = pd.DataFrame(results)
    wti_df = wti_df.sort_values(['park_code', 'park_date'])
    
    # Summary
    logger.info(f"\n=== WTI SUMMARY ===")
    logger.info(f"Total rows: {len(wti_df):,}")
    logger.info(f"Parks: {sorted(wti_df['park_code'].unique())}")
    logger.info(f"Date range: {wti_df['park_date'].min()} to {wti_df['park_date'].max()}")
    logger.info(f"\nBy source:")
    logger.info(wti_df['source'].value_counts().to_string())
    logger.info(f"\nBy park:")
    logger.info(wti_df.groupby('park_code').size().to_string())
    
    # Save
    wti_path = wti_dir / "wti.csv"
    wti_df.to_csv(wti_path, index=False)
    logger.info(f"\nSaved to: {wti_path}")


if __name__ == "__main__":
    main()
