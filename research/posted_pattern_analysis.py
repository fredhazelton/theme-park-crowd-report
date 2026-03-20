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


def detect_posted_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """Detect potentially anomalous POSTED times."""
    
    anomalies = []
    
    for entity_code in df['entity_code'].unique():
        entity_df = df[df['entity_code'] == entity_code].copy()
        
        if len(entity_df) < 10:  # Need sufficient data
            continue
        
        entity_df = entity_df.sort_values('observed_at')
        entity_df['prev_wait'] = entity_df['wait_time_minutes'].shift(1)
        entity_df['next_wait'] = entity_df['wait_time_minutes'].shift(-1)
        entity_df['wait_change'] = entity_df['wait_time_minutes'] - entity_df['prev_wait']
        
        # Calculate rolling statistics
        entity_df['rolling_mean'] = entity_df['wait_time_minutes'].rolling(window=5, center=True).mean()
        entity_df['rolling_std'] = entity_df['wait_time_minutes'].rolling(window=5, center=True).std()
        
        # Detect anomalies
        mean_wait = entity_df['wait_time_minutes'].mean()
        std_wait = entity_df['wait_time_minutes'].std()
        
        for _, row in entity_df.iterrows():
            wait_time = row['wait_time_minutes']
            rolling_mean = row['rolling_mean']
            rolling_std = row['rolling_std']
            
            # Different anomaly types
            anomaly_type = None
            severity = 0
            
            # Spike detection (much higher than recent average)
            if pd.notna(rolling_mean) and pd.notna(rolling_std) and rolling_std > 0:
                z_score = (wait_time - rolling_mean) / rolling_std
                if abs(z_score) > 3:
                    anomaly_type = 'spike' if z_score > 0 else 'drop'
                    severity = abs(z_score)
            
            # Sudden change detection
            if pd.notna(row['wait_change']) and abs(row['wait_change']) > 30:
                if anomaly_type is None or severity < 2:
                    anomaly_type = 'sudden_jump' if row['wait_change'] > 0 else 'sudden_drop'
                    severity = abs(row['wait_change']) / 10
            
            # Round number bias (posted times ending in 0 or 5)
            if wait_time > 0 and wait_time % 5 == 0 and wait_time % 10 != 0:
                if anomaly_type is None:
                    anomaly_type = 'round_5'
                    severity = 0.5
            elif wait_time > 0 and wait_time % 10 == 0:
                if anomaly_type is None:
                    anomaly_type = 'round_10'
                    severity = 1.0
            
            if anomaly_type and severity > 1:
                anomalies.append({
                    'entity_code': entity_code,
                    'observed_at': row['observed_at'],
                    'wait_time_minutes': wait_time,
                    'anomaly_type': anomaly_type,
                    'severity': round(severity, 1),
                    'rolling_mean': round(rolling_mean, 1) if pd.notna(rolling_mean) else None,
                    'prev_wait': row['prev_wait'],
                    'next_wait': row['next_wait']
                })
    
    return pd.DataFrame(anomalies)


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
        
        # Look for ceiling effects (many observations at or near maximum)\n        ceiling_threshold = max_wait * 0.95\n        ceiling_count = np.sum(wait_times >= ceiling_threshold)\n        ceiling_ratio = ceiling_count / len(wait_times)\n        \n        # Look for common \"round\" maximum values (60, 90, 120, etc.)\n        round_maxima = [60, 90, 120, 150, 180]\n        likely_ceiling = None\n        for ceiling in round_maxima:\n            near_ceiling = np.sum(np.abs(wait_times - ceiling) <= 5)\n            if near_ceiling >= 3 and ceiling >= p95_wait:\n                likely_ceiling = ceiling\n                break\n        \n        capacity_analysis.append({\n            'entity_code': entity_code,\n            'observations': len(wait_times),\n            'max_wait': max_wait,\n            'p95_wait': round(p95_wait, 1),\n            'p90_wait': round(p90_wait, 1),\n            'mean_wait': round(mean_wait, 1),\n            'ceiling_ratio': round(ceiling_ratio, 3),\n            'likely_ceiling': likely_ceiling,\n            'ceiling_evidence': 'strong' if ceiling_ratio > 0.05 else 'weak'\n        })\n    \n    return pd.DataFrame(capacity_analysis).sort_values('ceiling_ratio', ascending=False)


def calculate_park_congestion_index(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate park-wide congestion indicators."""\n    \n    df['park_code'] = df['entity_code'].str[:2]  # First 2 chars = park\n    df['hour'] = df['observed_at'].dt.hour\n    df['date'] = df['observed_at'].dt.date\n    \n    congestion_data = []\n    \n    for (park_code, date, hour), group in df.groupby(['park_code', 'date', 'hour']):\n        if len(group) < 3:  # Need multiple attractions\n            continue\n        \n        wait_times = group['wait_time_minutes'].values\n        \n        congestion_metrics = {\n            'park_code': park_code,\n            'date': date,\n            'hour': hour,\n            'avg_wait': round(np.mean(wait_times), 1),\n            'max_wait': np.max(wait_times),\n            'attractions_count': len(wait_times),\n            'high_wait_count': np.sum(wait_times >= 60),\n            'zero_wait_count': np.sum(wait_times == 0),\n            'congestion_score': round(np.mean(wait_times) * np.log(len(wait_times)), 1)\n        }\n        \n        congestion_data.append(congestion_metrics)\n    \n    congestion_df = pd.DataFrame(congestion_data)\n    \n    # Sort by congestion score\n    return congestion_df.sort_values('congestion_score', ascending=False)


def main():\n    print(\"=\"*60)\n    print(\"POSTED DATA PATTERN ANALYSIS - RESEARCH TOOL\")\n    print(\"=\"*60)\n    \n    # Load data\n    staging_dir = Path(\"pipeline_dev/staging/queue_times\")\n    \n    if not staging_dir.exists():\n        print(f\"Staging directory not found: {staging_dir}\")\n        return\n    \n    print(\"Loading staging data...\")\n    df = load_staging_data(staging_dir)\n    \n    if len(df) == 0:\n        print(\"No data loaded. Exiting.\")\n        return\n    \n    print(f\"\\nAnalyzing {len(df):,} POSTED observations\")\n    print(f\"Date range: {df['observed_at'].min()} to {df['observed_at'].max()}\")\n    print(f\"Unique entities: {df['entity_code'].nunique()}\")\n    print(f\"Parks: {df['entity_code'].str[:2].nunique()}\")\n    \n    # 1. Entity Pattern Analysis\n    print(\"\\n\" + \"=\"*40)\n    print(\"ENTITY PATTERN ANALYSIS\")\n    print(\"=\"*40)\n    \n    entity_stats = analyze_entity_patterns(df)\n    \n    print(\"\\nTop 10 most observed attractions:\")\n    print(entity_stats.head(10)[['observations', 'mean_wait', 'std_wait', 'volatility']])\n    \n    print(\"\\nTop 10 most volatile attractions:\")\n    print(entity_stats.nlargest(10, 'volatility')[['observations', 'mean_wait', 'volatility', 'max_wait']])\n    \n    # 2. Anomaly Detection\n    print(\"\\n\" + \"=\"*40)\n    print(\"ANOMALY DETECTION\")\n    print(\"=\"*40)\n    \n    anomalies = detect_posted_anomalies(df)\n    \n    if len(anomalies) > 0:\n        print(f\"\\nFound {len(anomalies):,} potential anomalies\")\n        \n        anomaly_summary = anomalies['anomaly_type'].value_counts()\n        print(\"\\nAnomaly types:\")\n        for anom_type, count in anomaly_summary.items():\n            print(f\"  {anom_type}: {count:,}\")\n        \n        print(\"\\nTop 10 most severe anomalies:\")\n        top_anomalies = anomalies.nlargest(10, 'severity')\n        for _, row in top_anomalies.iterrows():\n            print(f\"  {row['entity_code']}: {row['wait_time_minutes']} min ({row['anomaly_type']}, severity={row['severity']}) at {row['observed_at']}\")\n    else:\n        print(\"No significant anomalies detected\")\n    \n    # 3. Temporal Patterns\n    print(\"\\n\" + \"=\"*40)\n    print(\"TEMPORAL PATTERNS\")\n    print(\"=\"*40)\n    \n    temporal_patterns = analyze_temporal_patterns(df)\n    \n    print(\"\\nHourly averages:\")\n    print(temporal_patterns['hourly']['mean'])\n    \n    print(\"\\nDaily averages:\")\n    print(temporal_patterns['daily']['mean'])\n    \n    print(\"\\nPeak hours (90th percentile wait times):\")\n    print(temporal_patterns['peak_hours'].head(5))\n    \n    # 4. Capacity Constraint Analysis\n    print(\"\\n\" + \"=\"*40)\n    print(\"CAPACITY CONSTRAINT ANALYSIS\")\n    print(\"=\"*40)\n    \n    capacity_analysis = infer_capacity_constraints(df)\n    \n    print(\"\\nTop 10 attractions with potential capacity ceilings:\")\n    print(capacity_analysis.head(10)[['entity_code', 'max_wait', 'p95_wait', 'ceiling_ratio', 'likely_ceiling', 'ceiling_evidence']])\n    \n    # 5. Park Congestion Analysis\n    print(\"\\n\" + \"=\"*40)\n    print(\"PARK CONGESTION ANALYSIS\")\n    print(\"=\"*40)\n    \n    congestion_df = calculate_park_congestion_index(df)\n    \n    print(\"\\nTop 10 highest congestion periods:\")\n    print(congestion_df.head(10)[['park_code', 'date', 'hour', 'avg_wait', 'attractions_count', 'congestion_score']])\n    \n    # Save results\n    results_dir = Path(\"research/results\")\n    results_dir.mkdir(exist_ok=True)\n    \n    entity_stats.to_csv(results_dir / \"entity_patterns.csv\")\n    anomalies.to_csv(results_dir / \"detected_anomalies.csv\", index=False)\n    capacity_analysis.to_csv(results_dir / \"capacity_constraints.csv\", index=False)\n    congestion_df.to_csv(results_dir / \"park_congestion.csv\", index=False)\n    \n    print(f\"\\n\" + \"=\"*60)\n    print(\"RESEARCH INSIGHTS & OPPORTUNITIES\")\n    print(\"=\"*60)\n    \n    # Key insights\n    total_entities = len(entity_stats)\n    high_volatility = len(entity_stats[entity_stats['volatility'] > 1.0])\n    likely_ceilings = len(capacity_analysis[capacity_analysis['ceiling_evidence'] == 'strong'])\n    \n    print(f\"\\n🔍 Pattern Discovery:\")\n    print(f\"  • {total_entities} unique attractions analyzed\")\n    print(f\"  • {high_volatility} ({high_volatility/total_entities*100:.1f}%) show high volatility (>1.0)\")\n    print(f\"  • {likely_ceilings} attractions show evidence of capacity ceilings\")\n    print(f\"  • {len(anomalies)} potential posted time anomalies detected\")\n    \n    if len(temporal_patterns['hourly']) > 0:\n        peak_hour = temporal_patterns['hourly']['mean'].idxmax()\n        peak_wait = temporal_patterns['hourly']['mean'].max()\n        print(f\"  • Peak congestion: {peak_hour}:00 (avg {peak_wait:.1f} min wait)\")\n    \n    print(f\"\\n🧠 ML Opportunities:\")\n    print(f\"  • Volatility-based confidence scoring for POSTED times\")\n    print(f\"  • Capacity ceiling detection for unrealistic predictions\")\n    print(f\"  • Anomaly flagging for suspicious posted times\")\n    print(f\"  • Park-wide congestion indicators for context\")\n    print(f\"  • Temporal pattern regularization in models\")\n    \n    print(f\"\\n📊 Next Research Directions:\")\n    print(f\"  • Historical comparison (are patterns stable over time?)\")\n    print(f\"  • Weather correlation analysis\")\n    print(f\"  • Special event impact detection\")\n    print(f\"  • Cross-park pattern comparison\")\n    print(f\"  • Queue momentum forecasting\")\n    \n    print(f\"\\nResults saved to research/results/\")\n    print(\"=\"*60)\n\n\nif __name__ == \"__main__\":\n    main()