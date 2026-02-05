#!/usr/bin/env python3
"""
Run Full Backfill - All Entities, All Dates

Discovers all unique dates from fact tables and runs backfill for all entities.
Outputs to /mnt/data/theme-park-pipeline/curves/backfill/ to save main drive space.
"""

import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
import json

# Configuration
FACT_TABLES_DIR = Path("/home/wilma/hazeydata/pipeline/fact_tables/clean")
OUTPUT_BASE = Path("/mnt/data/theme-park-pipeline")
REPO_DIR = Path("/home/wilma/theme-park-crowd-report")

def discover_date_range():
    """Discover min and max dates from fact table directory structure."""
    dates = []
    
    for month_dir in FACT_TABLES_DIR.iterdir():
        if not month_dir.is_dir():
            continue
        
        for csv_file in month_dir.glob("*.csv"):
            # Extract date from filename like "mk_2024-01-15.csv"
            name = csv_file.stem  # "mk_2024-01-15"
            parts = name.split("_")
            if len(parts) >= 2:
                date_str = parts[-1]  # "2024-01-15"
                try:
                    d = date.fromisoformat(date_str)
                    dates.append(d)
                except ValueError:
                    continue
    
    if not dates:
        return None, None
    
    return min(dates), max(dates)


def run_backfill_batch(start_date: date, end_date: date, entity: str = None):
    """Run backfill for a date range."""
    cmd = [
        sys.executable,
        str(REPO_DIR / "scripts" / "generate_backfill.py"),
        "--output-base", str(OUTPUT_BASE),
        "--start-date", start_date.isoformat(),
        "--end-date", end_date.isoformat(),
    ]
    
    if entity:
        cmd.extend(["--entity", entity])
    
    print(f"Running: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(REPO_DIR))


def main():
    print("=" * 60)
    print("FULL BACKFILL - All Entities, All Dates")
    print("=" * 60)
    
    # Ensure output directory exists
    OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
    
    # Copy necessary files to output base if not present
    source_base = Path("/home/wilma/hazeydata/pipeline")
    
    # Link or copy dimension tables, models, etc.
    for subdir in ["dimension_tables", "models", "state", "fact_tables"]:
        src = source_base / subdir
        dst = OUTPUT_BASE / subdir
        if src.exists() and not dst.exists():
            print(f"Symlinking {subdir}...")
            dst.symlink_to(src)
    
    # Discover date range
    print("\nDiscovering date range from fact tables...")
    min_date, max_date = discover_date_range()
    
    if not min_date or not max_date:
        print("ERROR: Could not discover date range")
        sys.exit(1)
    
    # Don't backfill future dates or today
    today = date.today()
    if max_date >= today:
        max_date = today - __import__('datetime').timedelta(days=1)
    
    print(f"Date range: {min_date} to {max_date}")
    total_days = (max_date - min_date).days + 1
    print(f"Total days: {total_days}")
    
    # Get entity count
    entity_index = OUTPUT_BASE / "state" / "entity_index.sqlite"
    if entity_index.exists():
        import sqlite3
        conn = sqlite3.connect(entity_index)
        cursor = conn.execute("SELECT COUNT(DISTINCT entity_code) FROM entity_index")
        entity_count = cursor.fetchone()[0]
        conn.close()
        print(f"Total entities: {entity_count}")
        print(f"Estimated entity-dates: {entity_count * total_days:,}")
    
    # Run backfill in yearly chunks to show progress
    print("\n" + "=" * 60)
    print("Starting backfill (yearly chunks)...")
    print("=" * 60)
    
    current_year = min_date.year
    while current_year <= max_date.year:
        year_start = date(current_year, 1, 1)
        year_end = date(current_year, 12, 31)
        
        # Clamp to actual range
        if year_start < min_date:
            year_start = min_date
        if year_end > max_date:
            year_end = max_date
        
        print(f"\n>>> Processing year {current_year}: {year_start} to {year_end}")
        
        result = run_backfill_batch(year_start, year_end)
        
        if result.returncode != 0:
            print(f"WARNING: Year {current_year} had errors (exit code {result.returncode})")
        
        current_year += 1
    
    print("\n" + "=" * 60)
    print("BACKFILL COMPLETE")
    print("=" * 60)
    print(f"Output: {OUTPUT_BASE / 'curves' / 'backfill'}")


if __name__ == "__main__":
    main()
