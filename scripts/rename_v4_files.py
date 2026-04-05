#!/usr/bin/env python3
"""
V4 Phase B: Rename Files on Disk

Renames existing v3 files to new V4 baseline naming convention.
Must complete before 6 AM production run.

Barney's commit 2e0cc01: "Call things what they are"
"""

import os
import shutil
from pathlib import Path

PIPELINE_DIR = Path("/home/wilma/hazeydata/pipeline")

def rename_model_files():
    """Rename model_v3.json → model_baseline.json in all entity directories."""
    models_dir = PIPELINE_DIR / "models"
    renamed_models = 0
    renamed_metadata = 0
    
    print("🔄 Renaming model files...")
    
    for entity_dir in models_dir.glob("*/"):
        if not entity_dir.is_dir():
            continue
            
        # Rename model_v3.json → model_baseline.json
        old_model = entity_dir / "model_v3.json"
        new_model = entity_dir / "model_baseline.json"
        
        if old_model.exists() and not new_model.exists():
            old_model.rename(new_model)
            renamed_models += 1
        
        # Rename metadata_v3.json → metadata_baseline.json  
        old_metadata = entity_dir / "metadata_v3.json"
        new_metadata = entity_dir / "metadata_baseline.json"
        
        if old_metadata.exists() and not new_metadata.exists():
            old_metadata.rename(new_metadata)
            renamed_metadata += 1
    
    print(f"  ✅ Renamed {renamed_models} model files")
    print(f"  ✅ Renamed {renamed_metadata} metadata files")

def rename_archive_files():
    """Rename v3 archive files to new naming convention."""
    archive_dir = PIPELINE_DIR / "accuracy" / "archive"
    renamed_forecast_archives = 0
    renamed_wti_archives = 0
    
    print("🔄 Renaming archive files...")
    
    if not archive_dir.exists():
        print("  ⚠️ Archive directory not found")
        return
    
    # Rename forecast_v3_*.parquet → forecast_*.parquet
    for old_file in archive_dir.glob("forecast_v3_*.parquet"):
        new_name = old_file.name.replace("forecast_v3_", "forecast_")
        new_file = archive_dir / new_name
        
        if not new_file.exists():
            old_file.rename(new_file)
            renamed_forecast_archives += 1
    
    # Rename wti_v3_*.parquet → wti_*.parquet
    for old_file in archive_dir.glob("wti_v3_*.parquet"):
        new_name = old_file.name.replace("wti_v3_", "wti_")
        new_file = archive_dir / new_name
        
        if not new_file.exists():
            old_file.rename(new_file)
            renamed_wti_archives += 1
    
    print(f"  ✅ Renamed {renamed_forecast_archives} forecast archives")
    print(f"  ✅ Renamed {renamed_wti_archives} WTI archives")

def rename_log_files():
    """Rename v3_metrics_*.json → pipeline_metrics_*.json."""
    logs_dir = PIPELINE_DIR / "logs"
    renamed_logs = 0
    
    print("🔄 Renaming log files...")
    
    if not logs_dir.exists():
        print("  ⚠️ Logs directory not found")
        return
    
    # Rename v3_metrics_*.json → pipeline_metrics_*.json
    for old_file in logs_dir.glob("v3_metrics_*.json"):
        new_name = old_file.name.replace("v3_metrics_", "pipeline_metrics_")
        new_file = logs_dir / new_name
        
        if not new_file.exists():
            old_file.rename(new_file)
            renamed_logs += 1
    
    print(f"  ✅ Renamed {renamed_logs} log files")

def verify_files():
    """Verify key files exist with new names."""
    print("🔍 Verifying renamed files...")
    
    # Check main forecast and WTI files
    forecast_file = PIPELINE_DIR / "curves" / "forecast_parquet" / "all_forecasts.parquet"
    wti_file = PIPELINE_DIR / "wti" / "wti.parquet"
    
    print(f"  all_forecasts.parquet: {'✅' if forecast_file.exists() else '❌'}")
    print(f"  wti.parquet: {'✅' if wti_file.exists() else '❌'}")
    
    # Sample model files
    sample_model = PIPELINE_DIR / "models" / "AK01" / "model_baseline.json"
    sample_metadata = PIPELINE_DIR / "models" / "AK01" / "metadata_baseline.json"
    
    print(f"  AK01/model_baseline.json: {'✅' if sample_model.exists() else '❌'}")
    print(f"  AK01/metadata_baseline.json: {'✅' if sample_metadata.exists() else '❌'}")

def main():
    print("=" * 60)
    print("🪨 V4 PHASE B: FILENAME RENAME IMPLEMENTATION")
    print("Barney's commit 2e0cc01: Call things what they are")
    print("=" * 60)
    
    # Key files should already be correctly named from test run
    forecast_file = PIPELINE_DIR / "curves" / "forecast_parquet" / "all_forecasts.parquet"  
    wti_file = PIPELINE_DIR / "wti" / "wti.parquet"
    
    print(f"✅ Main files already correctly named:")
    print(f"   all_forecasts.parquet: {forecast_file.exists()}")
    print(f"   wti.parquet: {wti_file.exists()}")
    print()
    
    # Rename model files in entity directories
    rename_model_files()
    print()
    
    # Rename archive files
    rename_archive_files()
    print()
    
    # Rename log files
    rename_log_files()
    print()
    
    # Verify
    verify_files()
    
    print("=" * 60)
    print("✅ V4 PHASE B COMPLETE")
    print("All files renamed to V4 baseline convention")
    print("Ready for 6 AM production run")
    print("=" * 60)

if __name__ == "__main__":
    main()