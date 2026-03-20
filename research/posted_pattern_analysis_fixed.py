#!/usr/bin/env python3
"""
POSTED Data Pattern Analysis - Research Tool

Since we don't have ACTUAL wait time data for training, this tool analyzes
patterns in POSTED wait times to identify potential indicators that could
predict when POSTED times are likely to be inaccurate.

Research Questions:
1. Can we detect when POSTED times are likely inflated/deflated?
2. What temporal patterns exist in POSTED time behavior?
3. Which attractions show the most volatile POSTED times?
4. Can we infer capacity constraints from POSTED time ceilings?
5. How do POSTED times correlate with park-wide congestion?

Innovation Opportunities:
- Anomaly detection for suspicious POSTED times
- Queue momentum analysis (rate of change)
- Park-wide congestion indicators
- Capacity constraint inference
- Seasonal pattern detection
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from collections import defaultdict
import glob


def load_staging_data(staging_dir: Path, days_back: int = 30) -> pd.DataFrame:
    """Load recent staging data for analysis."""
    
    # Find all CSV files in recent directories
    csv_files = []
    for year_month_dir in staging_dir.glob("*"):
        if year_month_dir.is_dir():
            csv_files.extend(year_month_dir.glob("*.csv"))
    
    # Sort by modification time, take most recent
    csv_files = sorted(csv_files, key=lambda x: x.stat().st_mtime, reverse=True)
    
    print(f"Found {len(csv_files)} CSV files")
    
    # Load data from multiple files
    dfs = []
    total_rows = 0
    
    for file_path in csv_files[:20]:  # Limit to 20 most recent files
        try:
            df = pd.read_csv(file_path)
            if len(df) > 0:
                dfs.append(df)
                total_rows += len(df)
                print(f"  {file_path.name}: {len(df):,} rows")
        except Exception as e:
            print(f"  Error reading {file_path}: {e}")
    
    if not dfs:
        return pd.DataFrame()
    
    combined_df = pd.concat(dfs, ignore_index=True)
    print(f"Total combined: {len(combined_df):,} rows")
    
    # Convert timestamps and filter to POSTED only
    combined_df['observed_at'] = pd.to_datetime(combined_df['observed_at'])
    posted_df = combined_df[
        (combined_df['wait_time_type'] == 'POSTED') &
        (combined_df['wait_time_minutes'].notna()) &
        (combined_df['wait_time_minutes'] >= 0)
    ].copy()
    
    return posted_df


def analyze_entity_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Analyze patterns by entity (attraction)."""
    
    entity_stats = df.groupby('entity_code').agg({
        'wait_time_minutes': ['count', 'mean', 'std', 'min', 'max'],
        'observed_at': ['min', 'max']
    }).round(2)
    
    entity_stats.columns = ['observations', 'mean_wait', 'std_wait', 'min_wait', 'max_wait', 'first_seen', 'last_seen']
    
    # Calculate additional metrics
    entity_stats['volatility'] = entity_stats['std_wait'] / (entity_stats['mean_wait'] + 1)  # Add 1 to avoid div by 0
    entity_stats['range_ratio'] = entity_stats['max_wait'] / (entity_stats['mean_wait'] + 1)
    
    # Sort by number of observations
    entity_stats = entity_stats.sort_values('observations', ascending=False)
    
    return entity_stats


def analyze_temporal_patterns(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Analyze temporal patterns in POSTED times."""
    
    df['hour'] = df['observed_at'].dt.hour
    df['dow'] = df['observed_at'].dt.day_name()
    df['date'] = df['observed_at'].dt.date
    
    patterns = {}
    
    # Hourly patterns
    hourly = df.groupby('hour')['wait_time_minutes'].agg(['mean', 'std', 'count']).round(2)
    patterns['hourly'] = hourly
    
    # Day of week patterns
    dow_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    daily = df.groupby('dow')['wait_time_minutes'].agg(['mean', 'std', 'count']).round(2)
    daily = daily.reindex(dow_order)
    patterns['daily'] = daily
    
    # Peak detection (top 10% of wait times)
    high_wait_threshold = df['wait_time_minutes'].quantile(0.9)
    peak_hours = df[df['wait_time_minutes'] >= high_wait_threshold]['hour'].value_counts().sort_index()
    patterns['peak_hours'] = peak_hours
    
    return patterns


def infer_capacity_constraints(df: pd.DataFrame) -> pd.DataFrame:
    """Infer capacity constraints from POSTED time ceilings."""
    
    capacity_analysis = []
    
    for entity_code in df['entity_code'].unique():
        entity_df = df[df['entity_code'] == entity_code].copy()
        
        if len(entity_df) < 20:  # Need sufficient data
            continue
        
        wait_times = entity_df['wait_time_minutes'].values
        
        # Statistical measures
        max_wait = np.max(wait_times)
        p95_wait = np.percentile(wait_times, 95)
        p90_wait = np.percentile(wait_times, 90)
        mean_wait = np.mean(wait_times)
        
        # Look for ceiling effects (many observations at or near maximum)
        ceiling_threshold = max_wait * 0.95
        ceiling_count = np.sum(wait_times >= ceiling_threshold)
        ceiling_ratio = ceiling_count / len(wait_times)
        
        # Look for common "round" maximum values (60, 90, 120, etc.)
        round_maxima = [60, 90, 120, 150, 180]
        likely_ceiling = None
        for ceiling in round_maxima:
            near_ceiling = np.sum(np.abs(wait_times - ceiling) <= 5)
            if near_ceiling >= 3 and ceiling >= p95_wait:
                likely_ceiling = ceiling
                break
        
        capacity_analysis.append({
            'entity_code': entity_code,
            'observations': len(wait_times),
            'max_wait': max_wait,
            'p95_wait': round(p95_wait, 1),
            'p90_wait': round(p90_wait, 1),
            'mean_wait': round(mean_wait, 1),
            'ceiling_ratio': round(ceiling_ratio, 3),
            'likely_ceiling': likely_ceiling,
            'ceiling_evidence': 'strong' if ceiling_ratio > 0.05 else 'weak'
        })
    
    return pd.DataFrame(capacity_analysis).sort_values('ceiling_ratio', ascending=False)


def main():
    print("="*60)
    print("POSTED DATA PATTERN ANALYSIS - RESEARCH TOOL")
    print("="*60)
    
    # Load data
    staging_dir = Path("pipeline_dev/staging/queue_times")
    
    if not staging_dir.exists():
        print(f"Staging directory not found: {staging_dir}")
        return
    
    print("Loading staging data...")
    df = load_staging_data(staging_dir)
    
    if len(df) == 0:
        print("No data loaded. Exiting.")
        return
    
    print(f"\nAnalyzing {len(df):,} POSTED observations")
    print(f"Date range: {df['observed_at'].min()} to {df['observed_at'].max()}")
    print(f"Unique entities: {df['entity_code'].nunique()}")
    print(f"Parks: {df['entity_code'].str[:2].nunique()}")
    
    # 1. Entity Pattern Analysis
    print("\n" + "="*40)
    print("ENTITY PATTERN ANALYSIS")
    print("="*40)
    
    entity_stats = analyze_entity_patterns(df)
    
    print("\nTop 10 most observed attractions:")
    print(entity_stats.head(10)[['observations', 'mean_wait', 'std_wait', 'volatility']])
    
    print("\nTop 10 most volatile attractions:")
    print(entity_stats.nlargest(10, 'volatility')[['observations', 'mean_wait', 'volatility', 'max_wait']])
    
    # 2. Temporal Patterns
    print("\n" + "="*40)
    print("TEMPORAL PATTERNS")
    print("="*40)
    
    temporal_patterns = analyze_temporal_patterns(df)
    
    print("\nHourly averages:")
    print(temporal_patterns['hourly']['mean'])
    
    print("\nDaily averages:")
    print(temporal_patterns['daily']['mean'])
    
    print("\nPeak hours (90th percentile wait times):")
    print(temporal_patterns['peak_hours'].head(5))
    
    # 3. Capacity Constraint Analysis
    print("\n" + "="*40)
    print("CAPACITY CONSTRAINT ANALYSIS")
    print("="*40)
    
    capacity_analysis = infer_capacity_constraints(df)
    
    print("\nTop 10 attractions with potential capacity ceilings:")
    print(capacity_analysis.head(10)[['entity_code', 'max_wait', 'p95_wait', 'ceiling_ratio', 'likely_ceiling', 'ceiling_evidence']])
    
    # Save results
    results_dir = Path("research/results")
    results_dir.mkdir(exist_ok=True)
    
    entity_stats.to_csv(results_dir / "entity_patterns.csv")
    capacity_analysis.to_csv(results_dir / "capacity_constraints.csv", index=False)
    
    print(f"\n" + "="*60)
    print("RESEARCH INSIGHTS & OPPORTUNITIES")
    print("="*60)
    
    # Key insights
    total_entities = len(entity_stats)
    high_volatility = len(entity_stats[entity_stats['volatility'] > 1.0])
    likely_ceilings = len(capacity_analysis[capacity_analysis['ceiling_evidence'] == 'strong'])
    
    print(f"\n🔍 Pattern Discovery:")
    print(f"  • {total_entities} unique attractions analyzed")
    print(f"  • {high_volatility} ({high_volatility/total_entities*100:.1f}%) show high volatility (>1.0)")
    print(f"  • {likely_ceilings} attractions show evidence of capacity ceilings")
    
    if len(temporal_patterns['hourly']) > 0:
        peak_hour = temporal_patterns['hourly']['mean'].idxmax()
        peak_wait = temporal_patterns['hourly']['mean'].max()
        print(f"  • Peak congestion: {peak_hour}:00 (avg {peak_wait:.1f} min wait)")
    
    print(f"\n🧠 ML Opportunities:")
    print(f"  • Volatility-based confidence scoring for POSTED times")
    print(f"  • Capacity ceiling detection for unrealistic predictions")
    print(f"  • Park-wide congestion indicators for context")
    print(f"  • Temporal pattern regularization in models")
    
    print(f"\n📊 Next Research Directions:")
    print(f"  • Historical comparison (are patterns stable over time?)")
    print(f"  • Weather correlation analysis")
    print(f"  • Special event impact detection")
    print(f"  • Cross-park pattern comparison")
    print(f"  • Queue momentum forecasting")
    
    print(f"\nResults saved to research/results/")
    print("="*60)


if __name__ == "__main__":
    main()