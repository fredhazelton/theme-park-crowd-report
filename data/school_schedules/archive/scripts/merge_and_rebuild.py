#!/usr/bin/env python3
"""Merge new confirmations and rebuild daily aggregate.

Reads confirmation_results.json, updates districts_comprehensive.csv,
then rebuilds daily_aggregate_v3.csv.

Usage:
    python merge_and_rebuild.py            # merge and rebuild
    python merge_and_rebuild.py --dry-run  # show what would change
    python merge_and_rebuild.py --stats    # just show coverage stats
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).parent
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
RESULTS_FILE = BASE_DIR / "confirmation_results.json"
BACKUP_FILE = BASE_DIR / "districts_comprehensive_pre_merge.csv"


def load_results() -> dict:
    with open(RESULTS_FILE) as f:
        return json.load(f)


def main():
    dry_run = "--dry-run" in sys.argv
    stats_only = "--stats" in sys.argv

    # Load results
    results = load_results()
    confirmed = results.get("confirmed", {})
    failed = results.get("failed", {})
    
    print(f"Results: {len(confirmed)} confirmed, {len(failed)} failed")
    print(f"Credits used: {results.get('credits_used', 0):,}")
    
    if not confirmed and not stats_only:
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

    # Show current stats
    _print_stats("BEFORE merge", districts)

    if stats_only:
        return

    # Merge confirmed dates
    updated = 0
    for d in districts:
        leaid = d.get("nces_leaid", "")
        if leaid in confirmed:
            new_data = confirmed[leaid]
            dates = new_data.get("dates", {})

            # Map our date fields to CSV columns
            field_map = {
                "first_day": "first_day",
                "last_day": "last_day",
                "spring_break_start": "spring_break_start",
                "spring_break_end": "spring_break_end",
                "winter_break_start": "winter_break_start",
                "winter_break_end": "winter_break_end",
                "summer_start": "summer_start",
                "summer_end": "summer_end",
            }

            for src, dst in field_map.items():
                if src in dates and dates[src]:
                    d[dst] = dates[src]

            d["confidence"] = "confirmed"
            d["source"] = f"firecrawl:{new_data.get('source_url', '')}"
            updated += 1

    print(f"\nUpdated: {updated} districts")
    _print_stats("AFTER merge", districts)

    if dry_run:
        print("\n--- DRY RUN — no files written ---")
        return

    # Backup original
    import shutil
    if not BACKUP_FILE.exists():
        shutil.copy2(COMPREHENSIVE_FILE, BACKUP_FILE)
        print(f"Backed up to {BACKUP_FILE}")

    # Write updated CSV (overwrite in place)
    with open(COMPREHENSIVE_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(districts)

    print(f"Written updated {COMPREHENSIVE_FILE}")
    print("\nNext step: python3 build_daily_calendar_v3.py")


def _print_stats(label: str, districts: list[dict]):
    """Print coverage statistics."""
    print(f"\n--- {label} ---")
    
    conf_stats = defaultdict(lambda: {"count": 0, "enrollment": 0})
    total_enrollment = 0
    
    for d in districts:
        conf = d.get("confidence", "unknown")
        enroll = int(d.get("enrollment", 0) or 0)
        conf_stats[conf]["count"] += 1
        conf_stats[conf]["enrollment"] += enroll
        total_enrollment += enroll

    for conf in ["confirmed", "high", "medium", "inferred", "none"]:
        if conf in conf_stats:
            stats = conf_stats[conf]
            pct = stats["enrollment"] / total_enrollment * 100 if total_enrollment else 0
            print(f"  {conf}: {stats['count']:,} districts, {stats['enrollment']:,} students ({pct:.1f}%)")

    confirmed_enroll = conf_stats.get("confirmed", {}).get("enrollment", 0)
    confirmed_enroll += conf_stats.get("high", {}).get("enrollment", 0)
    pct = confirmed_enroll / total_enrollment * 100 if total_enrollment else 0
    print(f"\n  TOTAL CONFIRMED: {pct:.1f}% of enrollment")

    # State-level breakdown for confirmed
    state_stats = defaultdict(lambda: {"confirmed": 0, "total": 0})
    for d in districts:
        state = d.get("state", "??")
        enroll = int(d.get("enrollment", 0) or 0)
        state_stats[state]["total"] += enroll
        if d.get("confidence") in ("confirmed", "high"):
            state_stats[state]["confirmed"] += enroll
    
    print(f"\n  Top 10 states by enrollment gap:")
    gaps = [(s, v["total"] - v["confirmed"], v["total"], v["confirmed"]) 
            for s, v in state_stats.items()]
    gaps.sort(key=lambda x: -x[1])
    for state, gap, total, conf in gaps[:10]:
        pct = conf / total * 100 if total else 0
        print(f"    {state}: {conf:,}/{total:,} ({pct:.0f}%) — gap: {gap:,}")


if __name__ == "__main__":
    main()
