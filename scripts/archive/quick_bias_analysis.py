#!/usr/bin/env python3
"""
Quick Bias Analysis and Correction

Fast analysis of current bias patterns and application of corrections.
Focuses on park-level patterns identified in accuracy drift monitoring.
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

# Ensure src is in path for utilities
import sys
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.park_code import entity_code_to_park_code

OUTPUT_BASE = Path("/mnt/data/pipeline")
ACCURACY_FILE = OUTPUT_BASE / "accuracy" / "slot_accuracy.parquet"
FORECAST_FILE = OUTPUT_BASE / "curves" / "forecast_parquet" / "all_forecasts.parquet"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def analyze_current_bias():
    """Quick analysis of current bias patterns by park."""
    
    if not ACCURACY_FILE.exists():
        logger.error(f"Accuracy file not found: {ACCURACY_FILE}")
        return {}
    
    # Load recent accuracy data (last 14 days)
    df = pd.read_parquet(ACCURACY_FILE)
    
    # Filter to recent data
    recent_date = date.today() - timedelta(days=14)
    if df['park_date'].dtype == 'object':
        df['park_date'] = pd.to_datetime(df['park_date']).dt.date
    
    recent_df = df[df['park_date'] >= recent_date].copy()
    
    # Calculate bias (forecast - actual)
    recent_df['bias'] = recent_df['forecast_wait'] - recent_df['actual_wait']
    
    logger.info(f"Analyzing {len(recent_df)} recent accuracy records")
    
    # Group by entity and calculate bias stats
    entity_stats = recent_df.groupby('entity_code').agg({
        'bias': ['mean', 'std', 'count'],
        'absolute_error': 'mean'
    }).round(2)
    
    entity_stats.columns = ['bias_mean', 'bias_std', 'sample_count', 'mae']
    
    # Add park codes
    entity_stats['park_code'] = entity_stats.index.map(entity_code_to_park_code)
    
    # Filter entities with sufficient samples and significant bias
    significant_bias = entity_stats[
        (entity_stats['sample_count'] >= 10) & 
        (abs(entity_stats['bias_mean']) >= 2.0)
    ].sort_values('bias_mean', key=abs, ascending=False)
    
    logger.info(f"Found {len(significant_bias)} entities with significant bias")
    
    # Park-level summary
    park_stats = significant_bias.groupby('park_code').agg({
        'bias_mean': 'mean',
        'mae': 'mean',
        'sample_count': 'sum'
    }).round(2).sort_values('bias_mean', key=abs, ascending=False)
    
    logger.info(f"Park-level bias patterns ({len(park_stats)} parks):")
    for park, row in park_stats.iterrows():
        direction = "over-predicting" if row['bias_mean'] > 0 else "under-predicting"
        logger.info(f"  {park}: {direction} by {abs(row['bias_mean']):.1f} min "
                   f"(MAE: {row['mae']:.1f}, {row['sample_count']} samples)")
    
    return {
        'entity_bias': significant_bias.to_dict('index'),
        'park_bias': park_stats.to_dict('index'),
        'analysis_date': date.today().isoformat()
    }

def generate_corrections(bias_analysis):
    """Generate correction factors from bias analysis."""
    
    entity_corrections = {}
    
    for entity_code, stats in bias_analysis['entity_bias'].items():
        if abs(stats['bias_mean']) >= 2.0 and stats['sample_count'] >= 15:
            # Simple correction: subtract the bias
            correction = -stats['bias_mean']
            entity_corrections[entity_code] = {
                'correction_minutes': round(correction, 2),
                'original_bias': round(stats['bias_mean'], 2),
                'confidence': min(stats['sample_count'] / 50.0, 1.0),
                'park_code': stats['park_code']
            }
    
    logger.info(f"Generated {len(entity_corrections)} entity corrections")
    
    return entity_corrections

def apply_corrections_to_today():
    """Apply bias corrections to today's forecasts."""
    
    if not FORECAST_FILE.exists():
        logger.error(f"Forecast file not found: {FORECAST_FILE}")
        return False
    
    # Run analysis
    bias_analysis = analyze_current_bias()
    if not bias_analysis['entity_bias']:
        logger.info("No significant bias patterns found")
        return False
    
    # Generate corrections
    corrections = generate_corrections(bias_analysis)
    if not corrections:
        logger.info("No corrections to apply")
        return False
    
    # Load forecasts
    forecasts = pd.read_parquet(FORECAST_FILE)
    
    # Filter to today and tomorrow (most relevant for users)
    today = date.today()
    tomorrow = today + timedelta(days=1)
    
    target_dates = [today, tomorrow]
    date_mask = forecasts['park_date'].isin(target_dates)
    target_forecasts = forecasts[date_mask]
    
    if len(target_forecasts) == 0:
        logger.warning(f"No forecasts found for {target_dates}")
        return False
    
    logger.info(f"Found {len(target_forecasts)} forecasts for {target_dates}")
    
    # Apply corrections
    corrections_applied = 0
    correction_summary = []
    
    for entity_code, correction_info in corrections.items():
        correction = correction_info['correction_minutes']
        entity_mask = target_forecasts['entity_code'] == entity_code
        affected_rows = entity_mask.sum()
        
        if affected_rows > 0:
            # Apply correction
            forecasts.loc[
                date_mask & (forecasts['entity_code'] == entity_code),
                'predicted_actual'
            ] += correction
            
            corrections_applied += affected_rows
            correction_summary.append({
                'entity_code': entity_code,
                'park_code': correction_info['park_code'],
                'correction_minutes': correction,
                'original_bias': correction_info['original_bias'],
                'rows_affected': affected_rows
            })
            
            logger.info(f"Applied {correction:+.1f} min correction to {entity_code} "
                       f"({affected_rows} forecasts)")
    
    if corrections_applied > 0:
        # Save corrected forecasts
        backup_file = FORECAST_FILE.with_suffix('.parquet.pre_bias_correction')
        if not backup_file.exists():
            FORECAST_FILE.rename(backup_file)
            logger.info(f"Created backup: {backup_file}")
        
        forecasts.to_parquet(FORECAST_FILE, index=False)
        
        # Save correction log
        log_dir = OUTPUT_BASE / "bias_correction"
        log_dir.mkdir(exist_ok=True)
        
        correction_log = {
            'applied_at': pd.Timestamp.now().isoformat(),
            'target_dates': [d.isoformat() for d in target_dates],
            'total_corrections': corrections_applied,
            'entities_corrected': len(correction_summary),
            'corrections': correction_summary,
            'bias_analysis': bias_analysis
        }
        
        log_file = log_dir / f"correction_log_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_file, 'w') as f:
            json.dump(correction_log, f, indent=2, default=str)
        
        logger.info(f"Applied {corrections_applied} bias corrections")
        logger.info(f"Correction log saved to {log_file}")
        
        return True
    else:
        logger.info("No corrections were applied")
        return False

def main():
    """Main entry point."""
    success = apply_corrections_to_today()
    return 0 if success else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())