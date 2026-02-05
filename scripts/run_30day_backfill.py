#!/usr/bin/env python3
"""
Run 30-Day Backfill - All Entities, Last 30 Days Only

Fallback script if the full backfill is too heavy.
"""

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_DIR = Path("/home/wilma/theme-park-crowd-report")
OUTPUT_BASE = Path("/mnt/data/theme-park-pipeline")

def main():
    print("=" * 60)
    print("30-DAY BACKFILL - All Entities, Last 30 Days")
    print("=" * 60)
    
    end_date = date.today() - timedelta(days=1)  # Yesterday
    start_date = end_date - timedelta(days=29)   # 30 days back
    
    print(f"Date range: {start_date} to {end_date}")
    
    cmd = [
        sys.executable,
        str(REPO_DIR / "scripts" / "generate_backfill.py"),
        "--output-base", str(OUTPUT_BASE),
        "--start-date", start_date.isoformat(),
        "--end-date", end_date.isoformat(),
    ]
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(REPO_DIR))
    
    print("\n" + "=" * 60)
    if result.returncode == 0:
        print("30-DAY BACKFILL COMPLETE")
    else:
        print(f"BACKFILL FINISHED WITH ERRORS (code {result.returncode})")
    print("=" * 60)
    print(f"Output: {OUTPUT_BASE / 'curves' / 'backfill'}")
    
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
