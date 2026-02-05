#!/usr/bin/env python3
"""
DEV Pipeline Runner - Runs full pipeline with 2 test entities and snapshots at each step.

Usage: DEV_MODE=true python scripts/run_dev_pipeline.py
"""
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

# Ensure we're in the right directory
PROJECT_ROOT = Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

# Force DEV_MODE
os.environ['DEV_MODE'] = 'true'

import pandas as pd

# Dev output base
DEV_OUTPUT = PROJECT_ROOT / 'pipeline_dev'
PROD_OUTPUT = Path('/home/wilma/hazeydata/pipeline')

# Test entities - 2 with trained models
TEST_ENTITIES = ['AK01', 'AK06']  # It's Tough to Be a Bug + Kilimanjaro Safaris

def print_header(step_name):
    print("\n" + "="*70)
    print(f"  STEP: {step_name}")
    print("="*70 + "\n")

def print_snapshot(title, df, rows=15):
    """Print a snapshot of a dataframe"""
    print(f"\n📊 {title}")
    print("-" * 50)
    if df is None or len(df) == 0:
        print("  (no data)")
    else:
        print(f"  Shape: {df.shape[0]} rows × {df.shape[1]} cols")
        print(df.head(rows).to_string())
    print()

def run_step_1_etl():
    """Step 1: ETL - Pull data from S3, filter to test entities"""
    print_header("1. ETL - Extract from S3")
    
    # For dev mode, we'll copy a subset of existing fact table data
    # rather than hitting S3 (since that takes time)
    
    fact_tables_src = PROD_OUTPUT / 'fact_tables' / 'clean'
    fact_tables_dst = DEV_OUTPUT / 'fact_tables' / 'clean'
    fact_tables_dst.mkdir(parents=True, exist_ok=True)
    
    # Find recent fact table files and filter to test entities
    all_data = []
    
    # Look for recent month's data
    for month_dir in sorted(fact_tables_src.glob('202*'))[-3:]:  # Last 3 months
        for csv_file in month_dir.glob('ak_*.csv'):  # AK park only for test (lowercase filename)
            try:
                df = pd.read_csv(csv_file)
                # Filter to test entities
                df = df[df['entity_code'].isin(TEST_ENTITIES)]
                if len(df) > 0:
                    all_data.append(df)
            except Exception as e:
                print(f"  Warning: Could not read {csv_file}: {e}")
    
    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        # Save to dev output
        output_file = fact_tables_dst / 'dev_fact_table.csv'
        combined.to_csv(output_file, index=False)
        print(f"✅ Extracted {len(combined)} rows for entities {TEST_ENTITIES}")
        print_snapshot("Fact Table Sample (wait times)", combined)
        return combined
    else:
        print("⚠️ No data found in production fact tables. Checking staging...")
        return None

def run_step_2_dimensions():
    """Step 2: Build dimension tables"""
    print_header("2. DIMENSIONS - Entity metadata")
    
    # Copy dimension tables from production
    dim_src = PROD_OUTPUT / 'dimension_tables'
    dim_dst = DEV_OUTPUT / 'dimension_tables'
    dim_dst.mkdir(parents=True, exist_ok=True)
    
    # Copy and filter dimentity
    if (dim_src / 'dimentity.csv').exists():
        df = pd.read_csv(dim_src / 'dimentity.csv')
        # Filter to test entities for a cleaner view
        df_filtered = df[df['code'].isin(TEST_ENTITIES)]
        df_filtered.to_csv(dim_dst / 'dimentity_dev.csv', index=False)
        # Also copy full version
        df.to_csv(dim_dst / 'dimentity.csv', index=False)
        print(f"✅ Dimension table: {len(df)} total entities, {len(df_filtered)} test entities")
        print_snapshot("Entity Dimensions (test entities)", df_filtered[['code', 'name', 'short_name', 'fastpass_booth']])
        return df_filtered
    return None

def run_step_3_aggregates():
    """Step 3: Build aggregates"""
    print_header("3. AGGREGATES - Posted wait time stats")
    
    # Check if aggregates exist in production
    agg_src = PROD_OUTPUT / 'aggregates'
    agg_dst = DEV_OUTPUT / 'aggregates'
    agg_dst.mkdir(parents=True, exist_ok=True)
    
    if agg_src.exists():
        for csv_file in agg_src.glob('*.csv'):
            df = pd.read_csv(csv_file)
            # Filter if it has entity_code column
            if 'entity_code' in df.columns:
                df = df[df['entity_code'].isin(TEST_ENTITIES)]
            df.to_csv(agg_dst / csv_file.name, index=False)
            print(f"✅ Copied aggregate: {csv_file.name} ({len(df)} rows)")
            if len(df) > 0:
                print_snapshot(f"Aggregate: {csv_file.name}", df)
                break  # Just show first one
        return True
    print("⚠️ No aggregates found in production")
    return None

def run_step_4_training():
    """Step 4: Train models"""
    print_header("4. TRAINING - Model training")
    
    models_src = PROD_OUTPUT / 'models'
    models_dst = DEV_OUTPUT / 'models'
    models_dst.mkdir(parents=True, exist_ok=True)
    
    trained = 0
    for entity in TEST_ENTITIES:
        entity_src = models_src / entity
        entity_dst = models_dst / entity
        if entity_src.exists():
            entity_dst.mkdir(parents=True, exist_ok=True)
            # Copy model files
            for f in entity_src.glob('*'):
                import shutil
                shutil.copy2(f, entity_dst / f.name)
            trained += 1
            
            # Show model metadata if exists
            metadata_file = entity_dst / 'metadata_without_posted.json'
            if metadata_file.exists():
                import json
                with open(metadata_file) as f:
                    meta = json.load(f)
                print(f"✅ Model for {entity}:")
                print(f"   Observations: {meta.get('n_observations', 'N/A')}")
                print(f"   R²: {meta.get('r2', 'N/A'):.3f}" if isinstance(meta.get('r2'), (int, float)) else f"   R²: N/A")
    
    print(f"\n✅ Copied models for {trained}/{len(TEST_ENTITIES)} entities")
    return trained > 0

def run_step_5_forecast():
    """Step 5: Generate forecasts (backfill + forward)"""
    print_header("5. FORECAST - Generate wait time curves")
    
    curves_src = PROD_OUTPUT / 'curves'
    curves_dst = DEV_OUTPUT / 'curves'
    
    # Copy backfill curves
    backfill_src = curves_src / 'backfill'
    backfill_dst = curves_dst / 'backfill'
    backfill_dst.mkdir(parents=True, exist_ok=True)
    
    copied = 0
    sample_df = None
    for entity in TEST_ENTITIES:
        for curve_file in sorted(backfill_src.glob(f'{entity}_*.csv'))[-5:]:  # Last 5 dates
            import shutil
            shutil.copy2(curve_file, backfill_dst / curve_file.name)
            copied += 1
            if sample_df is None:
                sample_df = pd.read_csv(curve_file)
    
    print(f"✅ Copied {copied} backfill curve files")
    if sample_df is not None:
        print_snapshot("Sample Backfill Curve (predicted actual wait by time of day)", sample_df)
    
    # Copy forecast curves
    forecast_src = curves_src / 'forecast'
    forecast_dst = curves_dst / 'forecast'
    forecast_dst.mkdir(parents=True, exist_ok=True)
    
    copied = 0
    for entity in TEST_ENTITIES:
        for curve_file in sorted(forecast_src.glob(f'{entity}_*.csv'))[:5]:  # Next 5 dates
            import shutil
            shutil.copy2(curve_file, forecast_dst / curve_file.name)
            copied += 1
    
    print(f"✅ Copied {copied} forecast curve files")
    return True

def run_step_6_wti():
    """Step 6: Calculate Wait Time Index"""
    print_header("6. WTI - Wait Time Index")
    
    wti_src = PROD_OUTPUT / 'wti'
    wti_dst = DEV_OUTPUT / 'wti'
    wti_dst.mkdir(parents=True, exist_ok=True)
    
    # Copy WTI file
    for wti_file in wti_src.glob('wti.*'):
        import shutil
        shutil.copy2(wti_file, wti_dst / wti_file.name)
        
        # Read and show sample
        if wti_file.suffix == '.csv':
            df = pd.read_csv(wti_file)
        elif wti_file.suffix == '.parquet':
            df = pd.read_parquet(wti_file)
        else:
            continue
            
        # Filter to AK park for test entities
        if 'park_code' in df.columns:
            df = df[df['park_code'] == 'AK']
        
        print(f"✅ WTI file: {wti_file.name}")
        print_snapshot("Wait Time Index (AK park, recent dates)", df.tail(15))
        return df
    
    print("⚠️ No WTI file found")
    return None


def main():
    print("\n" + "🚀"*35)
    print("\n  DEV PIPELINE RUN - 2 ENTITY TEST")
    print(f"  Entities: {TEST_ENTITIES}")
    print(f"  Output: {DEV_OUTPUT}")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n" + "🚀"*35)
    
    # Run each step
    run_step_1_etl()
    run_step_2_dimensions()
    run_step_3_aggregates()
    run_step_4_training()
    run_step_5_forecast()
    run_step_6_wti()
    
    print("\n" + "="*70)
    print("  ✅ DEV PIPELINE COMPLETE")
    print("="*70)
    print(f"\nOutput location: {DEV_OUTPUT}")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # List output files
    print("\n📁 Output files created:")
    for subdir in ['fact_tables', 'dimension_tables', 'aggregates', 'models', 'curves', 'wti']:
        path = DEV_OUTPUT / subdir
        if path.exists():
            count = sum(1 for _ in path.rglob('*') if _.is_file())
            print(f"   {subdir}/: {count} files")


if __name__ == '__main__':
    main()
