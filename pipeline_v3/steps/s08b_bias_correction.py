#!/usr/bin/env python3
"""
Step 8b: Bias Correction

Applies systematic bias corrections to forecasts based on recent accuracy patterns.
This corrects persistent over/under-prediction patterns that hurt user experience.

Input: all_forecasts.parquet (from s08_forecast)
Output: all_forecasts.parquet (corrected predictions)
"""

import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Any

import pandas as pd
import numpy as np

# Import bias analysis functionality
import sys
pipeline_scripts = Path(__file__).parent.parent.parent / "scripts"
if str(pipeline_scripts) not in sys.path:
    sys.path.insert(0, str(pipeline_scripts))

from quick_bias_analysis import analyze_current_bias


def run(cfg, log) -> Dict[str, Any]:
    """Apply bias corrections to forecasts."""
    
    log.info("Starting bias correction...")
    
    # Paths
    forecast_file = cfg.output_base / "curves" / "forecast_parquet" / "all_forecasts.parquet"
    accuracy_file = cfg.output_base / "accuracy" / "slot_accuracy.parquet"
    corrections_dir = cfg.output_base / "bias_correction"
    corrections_dir.mkdir(exist_ok=True)
    
    # Validate inputs
    if not forecast_file.exists():
        raise FileNotFoundError(f"Forecast file not found: {forecast_file}")
    
    if not accuracy_file.exists():
        log.warning(f"Accuracy file not found: {accuracy_file}. Skipping bias correction.")
        return {"status": "skipped", "reason": "no_accuracy_data"}
    
    # Load forecasts
    log.info(f"Loading forecasts from {forecast_file}")
    df = pd.read_parquet(forecast_file)
    original_rows = len(df)
    log.info(f"Loaded {original_rows:,} forecast rows")
    
    # Create backup
    backup_file = forecast_file.with_suffix('.parquet.pre_bias_correction')
    if not backup_file.exists():
        log.info(f"Creating backup at {backup_file}")
        shutil.copy2(forecast_file, backup_file)
    
    # Analyze bias patterns
    log.info("Analyzing entity bias patterns...")
    try:
        bias_analysis = analyze_current_bias()
    except Exception as e:
        log.error(f"Bias analysis failed: {e}")
        return {"status": "failed", "error": str(e)}
    
    entity_bias = bias_analysis.get('entity_bias', {})
    if not entity_bias:
        log.info("No significant bias patterns found")
        return {"status": "completed", "corrections_applied": 0}
    
    # Apply corrections
    corrections_applied = 0
    correction_log = []
    
    for entity_code, bias_info in entity_bias.items():
        bias_minutes = bias_info['bias_mean']
        sample_count = bias_info['sample_count']
        confidence = 0.8  # Default confidence - could be calculated from std
        
        # Only apply corrections for significant bias (>=2 min) with sufficient samples
        if abs(bias_minutes) >= 2.0 and sample_count >= 10 and confidence >= 0.7:
            # Find rows for this entity
            entity_mask = df['entity_code'] == entity_code
            entity_rows = entity_mask.sum()
            
            if entity_rows > 0:
                # Apply correction (subtract bias to correct over-predictions)
                correction = -bias_minutes
                
                # Only correct model-based predictions, not fallback
                model_mask = entity_mask & (df['prediction_method'] == 'model_v3')
                corrected_rows = model_mask.sum()
                
                if corrected_rows > 0:
                    df.loc[model_mask, 'predicted_actual'] = np.maximum(
                        1,  # Minimum wait time of 1 minute
                        df.loc[model_mask, 'predicted_actual'] + correction
                    ).round().astype(int)
                    
                    corrections_applied += corrected_rows
                    correction_log.append({
                        'entity_code': entity_code,
                        'bias_minutes': bias_minutes,
                        'correction_applied': correction,
                        'rows_corrected': corrected_rows,
                        'sample_count': sample_count,
                        'confidence': confidence
                    })
                    
                    log.info(f"  {entity_code}: {correction:+.1f} min correction applied to {corrected_rows} rows (bias: {bias_minutes:+.1f})")
    
    # Save corrected forecasts
    log.info(f"Saving corrected forecasts to {forecast_file}")
    df.to_parquet(forecast_file, index=False)
    
    # Save correction log
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = corrections_dir / f"correction_log_{timestamp}.json"
    
    correction_summary = {
        "timestamp": timestamp,
        "total_corrections": corrections_applied,
        "entities_corrected": len(correction_log),
        "original_rows": original_rows,
        "corrections": correction_log
    }
    
    with open(log_file, 'w') as f:
        json.dump(correction_summary, f, indent=2)
    
    log.info(f"Applied {corrections_applied:,} bias corrections to {len(correction_log)} entities")
    log.info(f"Correction log saved: {log_file}")
    
    return {
        "status": "completed",
        "corrections_applied": corrections_applied,
        "entities_corrected": len(correction_log),
        "correction_log_file": str(log_file)
    }


if __name__ == "__main__":
    # For testing
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config import load_config
    from core.logging import PipelineLogger
    
    cfg = load_config()
    log = PipelineLogger("s08b_bias_correction", cfg.logs_dir)
    
    result = run(cfg, log)
    print(json.dumps(result, indent=2))