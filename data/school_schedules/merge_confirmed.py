#!/usr/bin/env python3
"""Merge newly confirmed districts into districts_comprehensive.csv.

After running firecrawl_batch_scraper.py, this script:
1. Reads the batch results (firecrawl_batch_results.json)
2. Updates districts_comprehensive.csv with confirmed dates
3. Recalculates coverage statistics
4. Produces an updated dataset ready for daily aggregate rebuild

Usage:
    python merge_confirmed.py
    python merge_confirmed.py --dry-run
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).parent
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
RESULTS_FILE = BASE_DIR / "firecrawl_batch_results.json"
OUTPUT_FILE = BASE_DIR / "districts_comprehensive_v3.csv"


def main():
    dry_run = "--dry-run" in sys.argv

    # Load batch results
    if not RESULTS_FILE.exists():
        print(f"No results file at {RESULTS_FILE}")
        sys.exit(1)

    with open(RESULTS_FILE) as f:
        results = json.load(f)

    confirmed = results.get("confirmed", {})
    print(f"Newly confirmed districts: {len(confirmed)}")

    if not confirmed:
        print("Nothing to merge.")
        return

    # Load current comprehensive
    districts = []
    with open(COMPREHENSIVE_FILE, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            districts.append(row)

    print(f"Current districts: {len(districts)}")

    # Merge
    updated_count = 0
    for d in districts:
        leaid = d.get("nces_leaid", "")
        if leaid in confirmed:
            new_data = confirmed[leaid]
            dates = new_data.get("dates", {})

            # Update calendar fields
            for field in ["first_day", "last_day", "spring_break_start", "spring_break_end",
                          "winter_break_start", "winter_break_end", "summer_start", "summer_end"]:
                if field in dates and dates[field]:
                    d[field] = dates[field]

            # Upgrade confidence and source
            d["confidence"] = "confirmed"
            d["source"] = f"firecrawl:{new_data.get('source_url', '')}"
            updated_count += 1

    print(f"Updated: {updated_count} districts")

    # Stats
    confidence_counts = defaultdict(lambda: {"count": 0, "enrollment": 0})
    for d in districts:
        conf = d.get("confidence", "unknown")
        enroll = int(d.get("enrollment", 0) or 0)
        confidence_counts[conf]["count"] += 1
        confidence_counts[conf]["enrollment"] += enroll

    total_enrollment = sum(v["enrollment"] for v in confidence_counts.values())
    print(f"\nConfidence breakdown after merge:")
    for conf, stats in sorted(confidence_counts.items(), key=lambda x: -x[1]["enrollment"]):
        pct = stats["enrollment"] / total_enrollment * 100 if total_enrollment else 0
        print(f"  {conf}: {stats['count']} districts, {stats['enrollment']:,} students ({pct:.1f}%)")

    if dry_run:
        print("\n--- DRY RUN — no files written ---")
        return

    # Write updated CSV
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(districts)

    print(f"\nWritten to {OUTPUT_FILE}")
    print(f"To promote: mv {OUTPUT_FILE} {COMPREHENSIVE_FILE}")


if __name__ == "__main__":
    main()
