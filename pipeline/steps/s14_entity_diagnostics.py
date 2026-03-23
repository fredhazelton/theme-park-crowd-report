"""Step 14: Entity-Level Diagnostics for Daily Report.

Reads entity accuracy data and produces structured diagnostics for inclusion
in the daily #wti-pipeline report. Provides entity-level insights into prediction
performance and identifies problematic entities.

Output:
  - accuracy/entity_diagnostics.json

Diagnostics included:
  - Worst 20 entities by MAE (with entity names)
  - Entity MAE distribution buckets
  - Worst bias entities (over/under-predictors)
  - Coverage summary (baseline vs fallback models)
  - Daily movers (entities with significant MAE changes)
  - Park-level rollup from entity data

Critical rule: Every entity code MUST be shown with entity name.
Example: "Space Mountain (MK01)" never just "MK01"
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.config import PipelineConfig
from pipeline.core.logging import PipelineLogger


def _load_entity_names(cfg: PipelineConfig) -> pd.DataFrame:
    """Load entity dimension table for name mappings."""
    dimentity_path = cfg.dimension_dir / "dimentity.csv"
    
    if not dimentity_path.exists():
        raise FileNotFoundError(f"Dimension table not found: {dimentity_path}")
    
    # Load only the columns we need
    df = pd.read_csv(dimentity_path, usecols=['code', 'name'])
    df = df.rename(columns={'code': 'entity_code'})
    
    # Clean up entity names - remove extra whitespace
    df['name'] = df['name'].astype(str).str.strip()
    
    return df


def _get_recent_accuracy(cfg: PipelineConfig, days_back: int = 1) -> pd.DataFrame:
    """Load recent entity accuracy data."""
    accuracy_path = cfg.accuracy_dir / "entity_daily_accuracy.parquet"
    
    if not accuracy_path.exists():
        raise FileNotFoundError(f"Entity accuracy data not found: {accuracy_path}")
    
    df = pd.read_parquet(accuracy_path)
    
    # Filter to recent evaluation dates
    cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    df = df[df['evaluation_date'] >= cutoff_date].copy()
    
    return df


def _get_historical_accuracy(cfg: PipelineConfig, days_back: int = 7) -> pd.DataFrame:
    """Load historical entity accuracy for comparison (7-day rolling average)."""
    accuracy_path = cfg.accuracy_dir / "entity_daily_accuracy.parquet"
    
    if not accuracy_path.exists():
        return pd.DataFrame()  # Return empty if no historical data
    
    df = pd.read_parquet(accuracy_path)
    
    # Filter to historical window for rolling averages
    end_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days_back + 2)).strftime('%Y-%m-%d')
    
    df = df[(df['evaluation_date'] >= start_date) & 
            (df['evaluation_date'] <= end_date)].copy()
    
    return df


def _calculate_distribution(recent_df: pd.DataFrame) -> dict:
    """Calculate MAE distribution across entities."""
    if recent_df.empty:
        return {
            "0-5": 0, "5-10": 0, "10-15": 0, 
            "15-20": 0, "20+": 0, "total": 0
        }
    
    # Take latest MAE per entity
    latest = recent_df.sort_values('evaluation_date').groupby('entity_code')['mae'].last()
    
    distribution = {
        "0-5": int((latest < 5).sum()),
        "5-10": int(((latest >= 5) & (latest < 10)).sum()),
        "10-15": int(((latest >= 10) & (latest < 15)).sum()),
        "15-20": int(((latest >= 15) & (latest < 20)).sum()),
        "20+": int((latest >= 20).sum()),
        "total": int(len(latest))
    }
    
    return distribution


def _find_worst_entities(recent_df: pd.DataFrame, entity_names: pd.DataFrame, 
                        metric: str = 'mae', n: int = 20) -> list[dict]:
    """Find worst performing entities by specified metric."""
    if recent_df.empty:
        return []
    
    # Take latest metric per entity
    latest = recent_df.sort_values('evaluation_date').groupby('entity_code').last()
    
    # Sort by metric (descending for MAE, absolute value for bias)
    if metric == 'bias':
        latest['abs_bias'] = latest['bias'].abs()
        worst = latest.nlargest(n, 'abs_bias')
    else:
        worst = latest.nlargest(n, metric)
    
    # Join with entity names
    worst_with_names = worst.reset_index().merge(
        entity_names, on='entity_code', how='left'
    )
    
    results = []
    for _, row in worst_with_names.iterrows():
        entity_code = row['entity_code']
        entity_name = row.get('name', 'Unknown')
        park_code = entity_code[:2] if len(entity_code) >= 2 else '??'
        
        result = {
            'entity_code': entity_code,
            'entity_name': entity_name,
            'display_name': f"{entity_name} ({entity_code})",
            'park_code': park_code,
            metric: round(float(row[metric]), 1)
        }
        
        if metric == 'mae':
            result['bias'] = round(float(row['bias']), 1)
        
        results.append(result)
    
    return results


def _find_bias_outliers(recent_df: pd.DataFrame, entity_names: pd.DataFrame,
                       n: int = 10) -> dict:
    """Find entities with extreme over/under-prediction bias."""
    if recent_df.empty:
        return {'over_predictors': [], 'under_predictors': []}
    
    # Take latest bias per entity
    latest = recent_df.sort_values('evaluation_date').groupby('entity_code').last()
    
    # Sort by bias (positive = over-prediction, negative = under-prediction)
    over_predictors = latest.nlargest(n, 'bias')
    under_predictors = latest.nsmallest(n, 'bias')
    
    def format_bias_entities(df: pd.DataFrame) -> list[dict]:
        with_names = df.reset_index().merge(entity_names, on='entity_code', how='left')
        results = []
        for _, row in with_names.iterrows():
            entity_code = row['entity_code']
            entity_name = row.get('name', 'Unknown')
            results.append({
                'entity_code': entity_code,
                'entity_name': entity_name,
                'display_name': f"{entity_name} ({entity_code})",
                'bias': round(float(row['bias']), 1),
                'mae': round(float(row['mae']), 1)
            })
        return results
    
    return {
        'over_predictors': format_bias_entities(over_predictors),
        'under_predictors': format_bias_entities(under_predictors)
    }


def _find_daily_movers(recent_df: pd.DataFrame, historical_df: pd.DataFrame,
                      entity_names: pd.DataFrame, threshold: float = 0.5) -> list[dict]:
    """Find entities with significant MAE changes vs 7-day average."""
    if recent_df.empty or historical_df.empty:
        return []
    
    # Calculate 7-day rolling average MAE per entity
    historical_avg = historical_df.groupby('entity_code')['mae'].mean()
    
    # Get latest MAE per entity
    recent_mae = recent_df.sort_values('evaluation_date').groupby('entity_code')['mae'].last()
    
    # Find entities with significant changes
    comparison = pd.DataFrame({
        'recent_mae': recent_mae,
        'historical_avg': historical_avg
    }).dropna()
    
    # Calculate percent change
    comparison['pct_change'] = (
        (comparison['recent_mae'] - comparison['historical_avg']) / 
        comparison['historical_avg']
    )
    
    # Find movers above threshold
    significant_movers = comparison[
        comparison['pct_change'].abs() >= threshold
    ].copy()
    
    if significant_movers.empty:
        return []
    
    # Add entity names and format
    movers_with_names = significant_movers.reset_index().merge(
        entity_names, on='entity_code', how='left'
    )
    
    results = []
    for _, row in movers_with_names.iterrows():
        entity_code = row['entity_code']
        entity_name = row.get('name', 'Unknown')
        pct_change = row['pct_change']
        
        direction = "↑" if pct_change > 0 else "↓"
        change_str = f"{direction} {abs(pct_change)*100:.0f}%"
        
        results.append({
            'entity_code': entity_code,
            'entity_name': entity_name,
            'display_name': f"{entity_name} ({entity_code})",
            'recent_mae': round(float(row['recent_mae']), 1),
            'historical_avg': round(float(row['historical_avg']), 1),
            'pct_change': round(float(pct_change), 3),
            'change_description': change_str,
            'direction': 'worsening' if pct_change > 0 else 'improving'
        })
    
    # Sort by absolute percent change, descending
    results.sort(key=lambda x: abs(x['pct_change']), reverse=True)
    
    return results[:10]  # Return top 10 movers


def _calculate_park_rollup(recent_df: pd.DataFrame) -> list[dict]:
    """Calculate park-level MAE from entity data."""
    if recent_df.empty:
        return []
    
    # Extract park code from entity code
    recent_df = recent_df.copy()
    recent_df['park_code'] = recent_df['entity_code'].str[:2]
    
    # Get latest MAE per entity, then average by park
    latest = recent_df.sort_values('evaluation_date').groupby('entity_code').last()
    latest['park_code'] = latest.index.str[:2]
    
    park_stats = latest.groupby('park_code').agg({
        'mae': ['mean', 'count'],
        'bias': 'mean'
    }).round(1)
    
    results = []
    for park_code in park_stats.index:
        results.append({
            'park_code': park_code,
            'avg_mae': float(park_stats.loc[park_code, ('mae', 'mean')]),
            'avg_bias': float(park_stats.loc[park_code, ('bias', 'mean')]),
            'entity_count': int(park_stats.loc[park_code, ('mae', 'count')])
        })
    
    # Sort by average MAE, descending
    results.sort(key=lambda x: x['avg_mae'], reverse=True)
    
    return results


def _estimate_coverage(cfg: PipelineConfig) -> dict:
    """Estimate baseline vs fallback model coverage by counting model files."""
    models_dir = cfg.models_dir
    
    if not models_dir.exists():
        return {'baseline_count': 0, 'fallback_count': 0, 'total_count': 0}
    
    # Count entity directories with baseline models
    baseline_count = 0
    fallback_count = 0
    
    for entity_dir in models_dir.iterdir():
        if entity_dir.is_dir() and not entity_dir.name.startswith('_'):
            baseline_model = entity_dir / "model_baseline.json"
            if baseline_model.exists():
                baseline_count += 1
            else:
                # Check for legacy models
                legacy_models = [
                    entity_dir / "model_v3.json",
                    entity_dir / "model_julia_actuals.json",
                    entity_dir / "model_julia_v2.json"
                ]
                if any(m.exists() for m in legacy_models):
                    baseline_count += 1  # Count legacy as baseline for coverage
                else:
                    fallback_count += 1  # No model at all = fallback
    
    total_count = baseline_count + fallback_count
    
    return {
        'baseline_count': baseline_count,
        'fallback_count': fallback_count, 
        'total_count': total_count
    }


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Generate entity-level diagnostics for daily reporting."""
    
    log.info("=" * 60)
    log.info("STEP 14: ENTITY-LEVEL DIAGNOSTICS")
    log.info("=" * 60)
    
    try:
        # Load supporting data
        log.info("Loading entity names and accuracy data...")
        entity_names = _load_entity_names(cfg)
        recent_accuracy = _get_recent_accuracy(cfg)
        historical_accuracy = _get_historical_accuracy(cfg)
        
        log.info(f"Loaded {len(entity_names)} entity names")
        log.info(f"Recent accuracy records: {len(recent_accuracy)}")
        log.info(f"Historical accuracy records: {len(historical_accuracy)}")
        
        # Generate diagnostics
        diagnostics = {
            'generated_at': datetime.now().isoformat(),
            'data_date': recent_accuracy['evaluation_date'].max() if not recent_accuracy.empty else None,
            
            # Core diagnostics
            'worst_entities': _find_worst_entities(recent_accuracy, entity_names, 'mae', 20),
            'distribution': _calculate_distribution(recent_accuracy),
            'bias_outliers': _find_bias_outliers(recent_accuracy, entity_names),
            'daily_movers': _find_daily_movers(recent_accuracy, historical_accuracy, entity_names),
            'park_rollup': _calculate_park_rollup(recent_accuracy),
            'coverage': _estimate_coverage(cfg),
            
            # Summary stats
            'summary': {
                'total_entities': len(recent_accuracy['entity_code'].unique()) if not recent_accuracy.empty else 0,
                'avg_mae': round(recent_accuracy['mae'].mean(), 1) if not recent_accuracy.empty else 0,
                'median_mae': round(recent_accuracy['mae'].median(), 1) if not recent_accuracy.empty else 0,
                'worst_mae': round(recent_accuracy['mae'].max(), 1) if not recent_accuracy.empty else 0,
                'best_mae': round(recent_accuracy['mae'].min(), 1) if not recent_accuracy.empty else 0,
            }
        }
        
        # Save to JSON
        output_path = cfg.accuracy_dir / "entity_diagnostics.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(diagnostics, f, indent=2)
        
        log.info(f"Entity diagnostics saved to {output_path}")
        log.info(f"Coverage: {diagnostics['coverage']['baseline_count']} baseline, {diagnostics['coverage']['fallback_count']} fallback")
        log.info(f"Worst entity: {diagnostics['worst_entities'][0]['display_name']} "
                f"(MAE {diagnostics['worst_entities'][0]['mae']})" 
                if diagnostics['worst_entities'] else "No entities found")
        
        return {
            'entities_analyzed': diagnostics['summary']['total_entities'],
            'worst_mae': diagnostics['summary']['worst_mae'],
            'avg_mae': diagnostics['summary']['avg_mae'],
            'baseline_models': diagnostics['coverage']['baseline_count'],
            'fallback_models': diagnostics['coverage']['fallback_count']
        }
        
    except Exception as e:
        log.error(f"Entity diagnostics failed: {e}")
        # Create minimal fallback diagnostics
        fallback_diagnostics = {
            'generated_at': datetime.now().isoformat(),
            'error': str(e),
            'worst_entities': [],
            'distribution': {'0-5': 0, '5-10': 0, '10-15': 0, '15-20': 0, '20+': 0, 'total': 0},
            'bias_outliers': {'over_predictors': [], 'under_predictors': []},
            'daily_movers': [],
            'park_rollup': [],
            'coverage': {'baseline_count': 0, 'fallback_count': 0, 'total_count': 0},
            'summary': {'total_entities': 0, 'avg_mae': 0, 'median_mae': 0, 'worst_mae': 0, 'best_mae': 0}
        }
        
        output_path = cfg.accuracy_dir / "entity_diagnostics.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(fallback_diagnostics, f, indent=2)
        
        raise