#!/usr/bin/env python3
"""
REGENERATE CLEAN ARCHIVES - Fix Bias Correction Contamination

Regenerates accuracy archive files using clean pre-bias correction forecasts.
This fixes the archive contamination that occurred from March 18+ when the 
daily pipeline archived bias-corrected predictions.

Evidence: Archives from March 18-19 contain predictions modified by bias 
correction factors of ±32 minutes, causing 83% accuracy degradation.

Solution: Use clean .pre_bias_correction backup to regenerate what the 
archives should have contained.
"""

import pandas as pd
import numpy as np
from datetime import datetime, date
from pathlib import Path

OUTPUT_BASE = Path("/mnt/data/pipeline")
ARCHIVE_DIR = OUTPUT_BASE / "accuracy" / "archive"

def extract_park_code(entity_code):
    """Extract park code from entity code."""
    if entity_code.startswith('USH'):
        return 'UH'
    elif entity_code.startswith('TDL'):
        return 'TDL' 
    elif entity_code.startswith('TDS'):
        return 'TDS'
    else:
        return entity_code[:2]

def regenerate_forecast_archive(clean_forecast_file, target_date_str, output_file):
    """Regenerate a forecast archive from clean data."""
    print(f"🔄 Regenerating {output_file.name} for {target_date_str}...")
    
    # Load clean forecasts
    df = pd.read_parquet(clean_forecast_file)
    print(f"   Loaded {len(df):,} clean predictions")
    
    # Filter for target date
    target_forecasts = df[df['park_date'].astype(str) == target_date_str].copy()
    print(f"   Found {len(target_forecasts):,} predictions for {target_date_str}")
    
    if len(target_forecasts) == 0:
        print(f"   ⚠️ No predictions found for {target_date_str}")
        return False
    
    # Save clean archive
    target_forecasts.to_parquet(output_file, index=False)
    print(f"   ✅ Saved clean archive: {len(target_forecasts):,} rows")
    return True

def regenerate_wti_archive(clean_forecast_file, target_date_str, output_file):
    """Regenerate a WTI archive from clean data."""
    print(f"🔄 Regenerating WTI {output_file.name} for {target_date_str}...")
    
    # Load clean forecasts 
    df = pd.read_parquet(clean_forecast_file)
    
    # Filter for target date
    target_forecasts = df[df['park_date'].astype(str) == target_date_str].copy()
    
    if len(target_forecasts) == 0:
        print(f"   ⚠️ No predictions found for {target_date_str}")
        return False
    
    # Extract park codes
    target_forecasts['park_code'] = target_forecasts['entity_code'].apply(extract_park_code)
    
    # Calculate park-level WTI (same logic as calculate_wti_simple.py)
    park_wti = target_forecasts.groupby(['park_code', 'park_date']).agg({
        'predicted_actual': 'mean',
        'entity_code': 'nunique'
    }).round(1)
    park_wti.columns = ['wti', 'n_entities']
    park_wti = park_wti.reset_index()
    park_wti['source'] = 'forecast'
    
    print(f"   Calculated WTI for {len(park_wti)} parks")
    for _, row in park_wti.iterrows():
        print(f"     {row.park_code}: {row.wti}")
    
    # Save clean WTI archive
    park_wti.to_parquet(output_file, index=False)
    print(f"   ✅ Saved clean WTI archive: {len(park_wti)} parks")
    return True

def main():
    print("=" * 60)
    print("🧹 REGENERATING CLEAN ARCHIVES")
    print("Fixing bias correction contamination from March 18+")
    print("=" * 60)
    
    # Use the most recent clean backup
    clean_backup = OUTPUT_BASE / "curves" / "forecast_parquet" / "all_forecasts_v3.parquet.pre_bias_correction"
    
    if not clean_backup.exists():
        print(f"❌ Clean backup not found: {clean_backup}")
        return 1
    
    print(f"📁 Using clean backup: {clean_backup}")
    backup_date = datetime.fromtimestamp(clean_backup.stat().st_mtime)
    print(f"   Backup created: {backup_date}")
    
    # Contaminated archive files to regenerate
    contaminated_files = [
        ("2026-03-18", "forecast_v3_2026-03-18.parquet"),
        ("2026-03-19", "forecast_v3_2026-03-19.parquet"),
        ("2026-03-18", "wti_v3_2026-03-18.parquet"),
        ("2026-03-19", "wti_v3_2026-03-19.parquet"),
    ]
    
    success_count = 0
    
    for target_date_str, filename in contaminated_files:
        archive_file = ARCHIVE_DIR / filename
        
        # Backup contaminated version
        if archive_file.exists():
            backup_path = archive_file.with_suffix('.parquet.CONTAMINATED_BACKUP')
            archive_file.rename(backup_path)
            print(f"📦 Backed up contaminated file: {backup_path.name}")
        
        # Regenerate clean version
        if filename.startswith('wti_'):
            success = regenerate_wti_archive(clean_backup, target_date_str, archive_file)
        else:
            success = regenerate_forecast_archive(clean_backup, target_date_str, archive_file)
        
        if success:
            success_count += 1
        print()
    
    print("=" * 60)
    print(f"✅ ARCHIVE REGENERATION COMPLETE")
    print(f"Files processed: {success_count}/{len(contaminated_files)}")
    print("Contaminated archives backed up with .CONTAMINATED_BACKUP extension")
    print("Clean archives ready for accuracy evaluation")
    print("=" * 60)
    
    return 0

if __name__ == "__main__":
    exit(main())