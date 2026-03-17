#!/usr/bin/env python3
"""Quality Gate for SSD Pipeline Integration.

Runs SSD quality validation and determines if data passes quality threshold
for production use. Designed to integrate into automated QA pipelines.

Usage:
  python3 run_quality_gate.py [--input data.json] [--threshold 0.8]
  
Exit codes:
  0: Data passes quality gate
  1: Data fails quality gate  
  2: Error running checks
"""

import argparse, json, sys, subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent
QUALITY_CHECK_SCRIPT = BASE_DIR / "ssd_quality_check.py"

def run_quality_gate(input_file: str, threshold: float = 0.8) -> int:
    """Run quality checks and return gate status."""
    
    print(f"🚪 SSD Quality Gate - Running validation...")
    print(f"   Input: {input_file}")
    print(f"   Threshold: {threshold}")
    print()
    
    try:
        # Run the quality check script
        result = subprocess.run([
            'python3', str(QUALITY_CHECK_SCRIPT),
            '--input', input_file
        ], capture_output=True, text=True)
        
        # Print the output from the quality check
        print(result.stdout)
        if result.stderr:
            print("Errors:", result.stderr)
        
        # Parse the quality report to get the score
        report_file = BASE_DIR / "ssd_quality_report.json" 
        if report_file.exists():
            with open(report_file) as f:
                report = json.load(f)
            
            quality_score = report['summary']['quality_score']
            
            if quality_score >= threshold:
                print(f"✅ QUALITY GATE PASSED: Score {quality_score:.3f} ≥ {threshold}")
                print(f"   Data is approved for production use.")
                return 0
            else:
                print(f"❌ QUALITY GATE FAILED: Score {quality_score:.3f} < {threshold}")
                print(f"   Data requires improvement before production use.")
                return 1
        else:
            print("❌ ERROR: Quality report not generated")
            return 2
            
    except Exception as e:
        print(f"❌ ERROR running quality checks: {e}")
        return 2

def main():
    parser = argparse.ArgumentParser(description="SSD Quality Gate")
    parser.add_argument('--input', default='llm_scraper_results.json',
                       help="Input data file to validate")
    parser.add_argument('--threshold', type=float, default=0.8,
                       help="Quality score threshold (default: 0.8)")
    
    args = parser.parse_args()
    
    # Resolve input path
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = BASE_DIR / input_path
    
    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}")
        return 2
    
    return run_quality_gate(str(input_path), args.threshold)

if __name__ == "__main__":
    sys.exit(main())