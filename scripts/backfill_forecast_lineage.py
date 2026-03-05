#!/usr/bin/env python3
"""
Backfill prediction lineage columns into archived forecast parquet files.

Reads archived forecasts from /mnt/data/pipeline/accuracy/archive/forecast_*.parquet
and enriches them with lineage columns based on current model metadata.

This is best-effort: we use the metadata currently on disk. For models that were
retrained between the forecast date and now, the metadata may not exactly match
what was active when the forecast was generated. But it's close enough for analysis.

Usage:
    python scripts/backfill_forecast_lineage.py [--output-base PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

DEFAULT_OUTPUT_BASE = Path("/mnt/data/pipeline")

# Feature set constants (matching forecast_vectorized.py)
FEATURES_ACTUALS_FULL = "mins_since_6am,mins_since_open,date_group_id_encoded,season_encoded,season_year_encoded"
FEATURES_ACTUALS_LITE = "mins_since_6am,mins_since_open"
FEATURES_V2_FULL = "posted_time,mins_since_6am,mins_since_open,hour_of_day,date_group_id_encoded,season_encoded,season_year_encoded"
FEATURES_V2_LITE = "posted_time,mins_since_6am,mins_since_open,hour_of_day"
FEATURES_SCOPE_SCALE = "mins_since_6am,mins_since_open,date_group_id_encoded,season_encoded,season_year_encoded,entity_code_encoded"


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger(__name__)


def _sanitize_scope_name(scope: str) -> str:
    return scope.lower().replace(" ", "_")


def load_metadata_cache(models_dir: Path) -> dict:
    """Pre-load all metadata files into a dict for fast lookup."""
    cache = {}
    
    for entity_dir in models_dir.iterdir():
        if not entity_dir.is_dir() or entity_dir.name.startswith("_"):
            continue
        entity_code = entity_dir.name
        cache[entity_code] = {}
        
        for fname in ("metadata_julia_actuals.json", "metadata_julia_v2.json"):
            path = entity_dir / fname
            if path.exists():
                try:
                    with open(path) as f:
                        cache[entity_code][fname] = json.load(f)
                except Exception:
                    pass
    
    # Load scope_scale metadata
    cache["_scope_scale"] = {}
    for scope_dir in models_dir.glob("_scope_scale_*"):
        for fname in ("metadata_scope_scale_actuals.json", "metadata.json"):
            path = scope_dir / fname
            if path.exists():
                try:
                    with open(path) as f:
                        meta = json.load(f)
                    scope_val = meta.get("scope_and_scale", scope_dir.name.replace("_scope_scale_", ""))
                    cache["_scope_scale"][scope_val] = meta
                    break
                except Exception:
                    pass
    
    # Conversion model
    conv_path = models_dir / "_conversion" / "metadata.json"
    if conv_path.exists():
        try:
            with open(conv_path) as f:
                cache["_conversion"] = json.load(f)
        except Exception:
            pass
    
    return cache


def enrich_row(prediction_method: str, entity_code: str, meta_cache: dict,
               entity_scope_map: dict, conversion_trained_at: str | None,
               fallback_ratios: dict, global_ratio: float) -> dict:
    """Determine lineage columns for a single entity+method combination."""
    lineage = {
        'entity_model_trained_at': None,
        'entity_model_version': None,
        'feature_set': None,
        'n_training_samples': None,
        'model_mae_at_training': None,
        'geo_decay_halflife': None,
        'uses_geo_decay': None,
        'training_data_type': None,
        'conversion_model_trained_at': conversion_trained_at,
        'fallback_ratio_used': fallback_ratios.get(entity_code, global_ratio),
        'uses_quantile_mapping': None,
        'hyperparameter_hash': None,
        'notes': None,
    }
    
    entity_meta = meta_cache.get(entity_code, {})
    
    if prediction_method == 'model_actuals':
        actuals_meta = entity_meta.get("metadata_julia_actuals.json", {})
        is_lite = actuals_meta.get("model_label") == "XGBOOST_ACTUALS_LITE" or actuals_meta.get("version") == "actuals_lite"
        if is_lite:
            lineage['entity_model_version'] = 'actuals_lite'
            lineage['feature_set'] = FEATURES_ACTUALS_LITE
        else:
            lineage['entity_model_version'] = 'julia_actuals'
            lineage['feature_set'] = FEATURES_ACTUALS_FULL
        if actuals_meta:
            lineage['entity_model_trained_at'] = actuals_meta.get('trained_at')
            lineage['n_training_samples'] = actuals_meta.get('n_samples')
            lineage['model_mae_at_training'] = actuals_meta.get('mae')
            lineage['geo_decay_halflife'] = actuals_meta.get('geo_decay_halflife_days')
            lineage['uses_geo_decay'] = actuals_meta.get('uses_geo_decay_weights')
        lineage['training_data_type'] = 'actuals_first'
        
    elif prediction_method == 'model_v2':
        v2_meta = entity_meta.get("metadata_julia_v2.json", {})
        lineage['entity_model_version'] = 'julia_v2'
        lineage['feature_set'] = FEATURES_V2_FULL
        if v2_meta:
            lineage['entity_model_trained_at'] = v2_meta.get('trained_at')
            lineage['n_training_samples'] = v2_meta.get('n_samples')
            lineage['model_mae_at_training'] = v2_meta.get('mae')
            lineage['geo_decay_halflife'] = v2_meta.get('geo_decay_halflife_days')
            lineage['uses_geo_decay'] = v2_meta.get('uses_geo_decay_weights')
        lineage['training_data_type'] = 'posted_first'
        
    elif prediction_method == 'model_lite':
        v2_meta = entity_meta.get("metadata_julia_v2.json", {})
        lineage['entity_model_version'] = 'julia_lite'
        lineage['feature_set'] = FEATURES_V2_LITE
        if v2_meta:
            lineage['entity_model_trained_at'] = v2_meta.get('trained_at')
            lineage['n_training_samples'] = v2_meta.get('n_samples')
            lineage['model_mae_at_training'] = v2_meta.get('mae')
            lineage['geo_decay_halflife'] = v2_meta.get('geo_decay_halflife_days')
            lineage['uses_geo_decay'] = v2_meta.get('uses_geo_decay_weights')
        lineage['training_data_type'] = 'posted_first'
        
    elif prediction_method == 'model_scope_scale':
        scope_val = entity_scope_map.get(entity_code)
        if scope_val and scope_val in meta_cache.get("_scope_scale", {}):
            scope_meta = meta_cache["_scope_scale"][scope_val]
            lineage['entity_model_trained_at'] = scope_meta.get('trained_at')
            lineage['n_training_samples'] = scope_meta.get('n_train') or scope_meta.get('n_samples')
            lineage['model_mae_at_training'] = scope_meta.get('mae') or scope_meta.get('actuals_mae')
            lineage['geo_decay_halflife'] = scope_meta.get('geo_decay_halflife_days')
            lineage['uses_geo_decay'] = scope_meta.get('uses_geo_decay_weights', True)
        lineage['entity_model_version'] = 'scope_scale'
        lineage['feature_set'] = FEATURES_SCOPE_SCALE
        lineage['training_data_type'] = 'scope_scale'
        
    elif prediction_method in ('aggregate', 'fallback_ratio'):
        lineage['entity_model_version'] = 'fallback'
        lineage['training_data_type'] = 'none'
    
    return lineage


def main():
    parser = argparse.ArgumentParser(description="Backfill forecast lineage columns")
    parser.add_argument("--output-base", type=Path, default=DEFAULT_OUTPUT_BASE)
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    args = parser.parse_args()
    
    logger = setup_logging()
    output_base = args.output_base.resolve()
    models_dir = output_base / "models"
    archive_dir = output_base / "accuracy" / "archive"
    
    logger.info("=" * 60)
    logger.info("BACKFILL FORECAST LINEAGE")
    logger.info("=" * 60)
    
    # Load metadata
    logger.info("Loading metadata cache...")
    meta_cache = load_metadata_cache(models_dir)
    logger.info(f"  Loaded metadata for {len(meta_cache) - 2} entities")  # minus _scope_scale and _conversion
    
    # Conversion metadata
    conv_meta = meta_cache.get("_conversion", {})
    conversion_trained_at = conv_meta.get("created_at")
    
    # Load entity scope map
    entity_scope_map = {}
    dim_path = output_base / "dimension_tables" / "dimentity.csv"
    if dim_path.exists():
        try:
            dim_df = pd.read_csv(dim_path)
            entity_scope_map = {
                code: ss for code, ss in zip(dim_df["code"], dim_df["scope_and_scale"])
                if pd.notna(ss)
            }
        except Exception as e:
            logger.warning(f"Could not load entity scope map: {e}")
    
    # Load fallback ratios
    ratios_path = output_base / "state" / "fallback_ratios.json"
    fallback_ratios = {}
    global_ratio = 0.678
    if ratios_path.exists():
        with open(ratios_path) as f:
            fallback_ratios = json.load(f)
        global_ratio = fallback_ratios.pop("__global__", global_ratio)
    
    # Process archive files
    archive_files = sorted(archive_dir.glob("forecast_*.parquet"))
    logger.info(f"Found {len(archive_files)} archive files")
    
    lineage_cols = [
        'entity_model_trained_at', 'entity_model_version', 'feature_set',
        'n_training_samples', 'model_mae_at_training',
        'geo_decay_halflife', 'uses_geo_decay', 'training_data_type',
        'conversion_model_trained_at', 'pipeline_run_date', 'fallback_ratio_used',
        'uses_quantile_mapping', 'hyperparameter_hash', 'notes',
    ]
    
    processed = 0
    skipped = 0
    
    for archive_file in archive_files:
        try:
            df = pd.read_parquet(archive_file)
        except Exception as e:
            logger.warning(f"  Could not read {archive_file.name}: {e}")
            skipped += 1
            continue
        
        # Skip if already has lineage columns
        if 'entity_model_version' in df.columns and df['entity_model_version'].notna().any():
            logger.info(f"  {archive_file.name}: already has lineage, skipping")
            skipped += 1
            continue
        
        # Extract forecast_made_date for pipeline_run_date
        if 'forecast_made_date' in df.columns:
            pipeline_run_date = str(df['forecast_made_date'].iloc[0])
        else:
            # Extract from filename: forecast_2026-03-02.parquet
            pipeline_run_date = archive_file.stem.replace("forecast_", "")
        
        # Build lineage per (entity_code, prediction_method) combo
        combos = df[['entity_code', 'prediction_method']].drop_duplicates()
        lineage_map = {}
        for _, row in combos.iterrows():
            ec = row['entity_code']
            pm = row['prediction_method']
            lineage_map[(ec, pm)] = enrich_row(
                pm, ec, meta_cache, entity_scope_map,
                conversion_trained_at, fallback_ratios, global_ratio
            )
        
        # Apply lineage
        for col in lineage_cols:
            if col == 'pipeline_run_date':
                df[col] = pipeline_run_date
            else:
                df[col] = df.apply(
                    lambda r: lineage_map.get((r['entity_code'], r['prediction_method']), {}).get(col),
                    axis=1
                )
        
        if args.dry_run:
            logger.info(f"  {archive_file.name}: would enrich {len(df):,} rows ({len(combos)} entity-method combos)")
            sample = df[['entity_code', 'prediction_method', 'entity_model_version', 'feature_set', 'pipeline_run_date']].head(3)
            logger.info(f"    Sample:\n{sample.to_string()}")
        else:
            df.to_parquet(archive_file, index=False)
            logger.info(f"  {archive_file.name}: enriched {len(df):,} rows")
        
        processed += 1
    
    logger.info("=" * 60)
    logger.info(f"Processed: {processed}, Skipped: {skipped}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
