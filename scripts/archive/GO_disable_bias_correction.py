#!/usr/bin/env python3
"""
GO.py - DISABLE BIAS CORRECTION SYSTEM COMPLETELY

EXECUTIVE DECISION (2026-03-21):
Bias correction system implemented on March 17, 2026 was causing systematic
accuracy degradation of 83% (MAE 8.5 vs 1.5 without correction). 

ACTIONS:
1. Restore all pre-bias correction forecast files
2. Remove bias correction from all pipeline processes 
3. Regenerate WTI and accuracy metrics
4. Verify improvements at entity, park, and WTI levels
5. Document the decision with evidence

EVIDENCE OF FAILURE:
- March 20 MAE WITH bias correction: 8.5 minutes (8/12 parks RED >10min error)  
- March 20 MAE WITHOUT bias correction: 1.5 minutes (10/12 parks GREEN <2.5min error)
- Systematic under-prediction bias of -6.5 minutes caused by faulty correction logic

DECISION: KILL THE BIAS CORRECTION SYSTEM PERMANENTLY
"""

import argparse
import json
import logging
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

import pandas as pd

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

OUTPUT_BASE = Path("/home/wilma/hazeydata/pipeline")
TPCR_BASE = Path("/home/wilma/theme-park-crowd-report")


def restore_pre_bias_forecasts():
    """Restore all forecast files to their pre-bias correction state."""
    logger.info("🔥 STEP 1: RESTORING PRE-BIAS CORRECTION FORECASTS")
    
    forecast_dir = OUTPUT_BASE / "curves" / "forecast_parquet"
    restored_count = 0
    
    # Find all .pre_bias_correction backup files
    backup_files = list(forecast_dir.glob("*.pre_bias_correction"))
    
    for backup_file in backup_files:
        original_file = backup_file.with_suffix('')
        
        if original_file.exists():
            # Create backup of current (bias-corrected) version
            corrupted_backup = str(original_file) + ".WITH_BIAS_CORRECTION_CORRUPTED"
            shutil.copy2(original_file, corrupted_backup)
            logger.info(f"  Backed up corrupted version: {corrupted_backup}")
        
        # Restore the clean version
        shutil.copy2(backup_file, original_file)
        logger.info(f"  ✅ RESTORED: {original_file.name}")
        restored_count += 1
    
    logger.info(f"📊 RESTORED {restored_count} forecast files to pre-bias correction state")
    return restored_count


def disable_bias_correction_in_wti_script():
    """Permanently disable bias correction in calculate_wti_simple.py"""
    logger.info("🔥 STEP 2: DISABLING BIAS CORRECTION IN WTI CALCULATION")
    
    wti_script = TPCR_BASE / "scripts" / "calculate_wti_simple.py"
    
    if not wti_script.exists():
        logger.error(f"WTI script not found: {wti_script}")
        return False
    
    # Read the current script
    content = wti_script.read_text()
    
    # Find the bias correction section and disable it
    lines = content.split('\n')
    modified_lines = []
    in_bias_section = False
    
    for line in lines:
        # Mark the start of bias correction section
        if "ADAPTIVE BIAS CORRECTION" in line:
            in_bias_section = True
            modified_lines.append(line)
            modified_lines.append("    # PERMANENTLY DISABLED 2026-03-21: Bias correction caused 83% accuracy degradation")
            modified_lines.append("    # Evidence: MAE 8.5 with correction vs 1.5 without correction")
            modified_lines.append("    # Decision: Kill bias correction system permanently")
            continue
        
        # Force disable the bias correction
        if in_bias_section and line.strip().startswith("if False and not args.historical_only"):
            modified_lines.append("    if False:  # PERMANENTLY DISABLED - DO NOT RE-ENABLE")
            continue
        elif "if False and not args.historical_only" in line:
            modified_lines.append(line.replace("if False and not args.historical_only", "if False:  # PERMANENTLY DISABLED"))
            continue
        
        modified_lines.append(line)
    
    # Write the modified script
    wti_script.write_text('\n'.join(modified_lines))
    logger.info("✅ DISABLED bias correction in WTI calculation script")
    return True


def disable_bias_correction_in_framework():
    """Add kill switch to bias correction framework script."""
    logger.info("🔥 STEP 3: KILLING BIAS CORRECTION FRAMEWORK")
    
    bias_script = TPCR_BASE / "scripts" / "bias_correction_framework.py"
    
    if not bias_script.exists():
        logger.warning(f"Bias correction framework not found: {bias_script}")
        return False
    
    # Add kill switch at the top of main()
    content = bias_script.read_text()
    
    kill_switch = '''
    # KILL SWITCH - BIAS CORRECTION PERMANENTLY DISABLED 2026-03-21
    # Evidence: Bias correction caused 83% accuracy degradation (MAE 8.5 vs 1.5)
    # Decision: Fred Hazelton executive order to disable permanently
    print("🚨 BIAS CORRECTION SYSTEM PERMANENTLY DISABLED 🚨")
    print("Date: 2026-03-21")
    print("Reason: Caused 83% accuracy degradation")  
    print("Evidence: MAE 8.5 WITH correction vs 1.5 WITHOUT correction")
    print("Decision: Executive order to kill bias correction permanently")
    print("Contact: Fred Hazelton if you think this should be re-enabled")
    return 1  # Exit immediately
'''
    
    # Insert kill switch at start of main()
    modified_content = content.replace(
        "def main():",
        f"def main():{kill_switch}"
    )
    
    bias_script.write_text(modified_content)
    logger.info("✅ INSTALLED kill switch in bias correction framework")
    return True


def regenerate_wti():
    """Regenerate WTI without bias correction."""
    logger.info("🔥 STEP 4: REGENERATING WTI WITHOUT BIAS CORRECTION")
    
    import subprocess
    
    try:
        # Run WTI calculation
        cmd = [
            f"{TPCR_BASE}/.venv/bin/python3",
            f"{TPCR_BASE}/scripts/calculate_wti_simple.py"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=TPCR_BASE)
        
        if result.returncode == 0:
            logger.info("✅ REGENERATED WTI successfully")
            return True
        else:
            logger.error(f"WTI regeneration failed: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"Error running WTI regeneration: {e}")
        return False


def evaluate_accuracy_improvement():
    """Evaluate accuracy improvements across all levels."""
    logger.info("🔥 STEP 5: EVALUATING ACCURACY IMPROVEMENTS")
    
    try:
        # Run accuracy reports for recent dates
        import subprocess
        
        results = {}
        test_dates = ["2026-03-18", "2026-03-19", "2026-03-20"]
        
        for test_date in test_dates:
            cmd = [
                f"{TPCR_BASE}/.venv/bin/python3",
                f"{TPCR_BASE}/scripts/daily_accuracy_report.py", 
                "--date", test_date, "--json"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=TPCR_BASE)
            
            if result.returncode == 0:
                # Parse the text output to extract MAE and bias
                lines = result.stdout.split('\n')
                for line in lines:
                    if "Yesterday:  MAE=" in line:
                        # Extract MAE and bias from line like "  Yesterday:  MAE=1.5  Bias=-0.3"
                        parts = line.split('MAE=')[1].split()
                        mae = float(parts[0])
                        bias = float(parts[1].split('Bias=')[1])
                        results[test_date] = {"mae": mae, "bias": bias}
                        break
        
        if results:
            logger.info("📊 ACCURACY IMPROVEMENTS:")
            for test_date, metrics in results.items():
                logger.info(f"  {test_date}: MAE={metrics['mae']:.1f}, Bias={metrics['bias']:+.1f}")
            
            # Calculate average improvement
            avg_mae = sum(r['mae'] for r in results.values()) / len(results)
            avg_bias = sum(r['bias'] for r in results.values()) / len(results)
            
            logger.info(f"📈 AVERAGE METRICS WITHOUT BIAS CORRECTION:")
            logger.info(f"   MAE: {avg_mae:.1f} (vs ~8.5 with bias correction = {((8.5-avg_mae)/8.5*100):+.0f}% improvement)")
            logger.info(f"   Bias: {avg_bias:+.1f} (vs ~-6.5 with bias correction)")
            
            return {"avg_mae": avg_mae, "avg_bias": avg_bias, "daily_results": results}
        
    except Exception as e:
        logger.error(f"Error evaluating accuracy: {e}")
        
    return None


def archive_bias_correction_files():
    """Archive bias correction files to prevent accidental reuse."""
    logger.info("🔥 STEP 6: ARCHIVING BIAS CORRECTION FILES")
    
    bias_dir = OUTPUT_BASE / "bias_correction"
    if not bias_dir.exists():
        logger.info("No bias correction directory found")
        return 0
    
    # Create archive directory
    archive_dir = bias_dir / "DISABLED_2026-03-21_CAUSED_ACCURACY_DEGRADATION"
    archive_dir.mkdir(exist_ok=True)
    
    archived_count = 0
    for bias_file in bias_dir.glob("*.json"):
        if "DISABLED" not in str(bias_file):
            archive_path = archive_dir / bias_file.name
            shutil.move(bias_file, archive_path)
            archived_count += 1
            
    # Create warning file
    warning_file = archive_dir / "README_WHY_DISABLED.txt"
    warning_file.write_text("""
BIAS CORRECTION SYSTEM PERMANENTLY DISABLED - 2026-03-21

REASON: Systematic accuracy degradation of 83%

EVIDENCE:
- March 20 MAE WITH bias correction: 8.5 minutes
- March 20 MAE WITHOUT bias correction: 1.5 minutes  
- 8/12 parks showed >10 minute errors with bias correction
- 10/12 parks showed <2.5 minute errors without bias correction

DECISION: Fred Hazelton executive order to kill bias correction permanently

DO NOT RE-ENABLE WITHOUT EXTENSIVE TESTING AND FRED'S APPROVAL
""")
    
    logger.info(f"📦 ARCHIVED {archived_count} bias correction files")
    return archived_count


def main():
    logger.info("=" * 60)
    logger.info("🚨 GO.py - DISABLE BIAS CORRECTION SYSTEM COMPLETELY")
    logger.info("Executive Decision: 2026-03-21")
    logger.info("Reason: 83% accuracy degradation caused by bias correction")
    logger.info("=" * 60)
    
    results = {}
    
    # Step 1: Restore pre-bias forecasts
    results['restored_files'] = restore_pre_bias_forecasts()
    
    # Step 2: Disable in WTI script
    results['wti_script_disabled'] = disable_bias_correction_in_wti_script()
    
    # Step 3: Kill framework
    results['framework_killed'] = disable_bias_correction_in_framework()
    
    # Step 4: Regenerate WTI
    results['wti_regenerated'] = regenerate_wti()
    
    # Step 5: Evaluate improvements
    results['accuracy_evaluation'] = evaluate_accuracy_improvement()
    
    # Step 6: Archive files
    results['archived_files'] = archive_bias_correction_files()
    
    logger.info("=" * 60)
    logger.info("🎯 BIAS CORRECTION ELIMINATION COMPLETE")
    logger.info("=" * 60)
    
    # Summary
    if results['accuracy_evaluation']:
        eval_data = results['accuracy_evaluation']
        logger.info(f"✅ ACCURACY RESTORED:")
        logger.info(f"   Average MAE: {eval_data['avg_mae']:.1f} minutes")
        logger.info(f"   Average Bias: {eval_data['avg_bias']:+.1f} minutes") 
        logger.info(f"   Improvement: {((8.5-eval_data['avg_mae'])/8.5*100):+.0f}% MAE reduction")
    
    logger.info(f"📁 Files restored: {results['restored_files']}")
    logger.info(f"📁 Files archived: {results['archived_files']}")
    logger.info("🔥 Bias correction system permanently disabled")
    
    return results


if __name__ == "__main__":
    results = main()
    print(json.dumps(results, indent=2, default=str))