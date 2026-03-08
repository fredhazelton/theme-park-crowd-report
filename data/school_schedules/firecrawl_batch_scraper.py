#!/usr/bin/env python3
"""Phase C: Firecrawl Batch Extraction for School Calendar Confirmation.

Batch-scrapes district websites using Firecrawl Extract API to confirm
calendar dates for uncovered districts. Uses NCES CCD district website
URLs as starting points.

Requires:
    - FIRECRAWL_API_KEY env var
    - districts_comprehensive.csv (current dataset with confidence tiers)
    - enrollment_by_district.csv (NCES enrollment data)
    - nces_websites.csv (NCES CCD with WEBSITE field — download first)

Usage:
    # Extract top N uncovered districts by enrollment
    python firecrawl_batch_scraper.py --limit 500

    # Extract all uncovered districts with 10K+ students
    python firecrawl_batch_scraper.py --min-enrollment 10000

    # Resume from where we left off
    python firecrawl_batch_scraper.py --resume

    # Dry run (show what would be scraped, don't scrape)
    python firecrawl_batch_scraper.py --dry-run --limit 50

Cost: ~24 credits per district on Firecrawl Standard ($99/month = 100K credits)
       100K / 24 = ~4,166 districts per month
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import date, datetime
from pathlib import Path

# --- Configuration ---
BASE_DIR = Path(__file__).parent
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
NCES_WEBSITES_FILE = BASE_DIR / "nces_websites.csv"
RESULTS_FILE = BASE_DIR / "firecrawl_batch_results.json"
CONFIRMED_FILE = BASE_DIR / "newly_confirmed_districts.csv"
FAILED_FILE = BASE_DIR / "firecrawl_failures.json"

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_EXTRACT_URL = "https://api.firecrawl.dev/v1/extract"
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"

# Rate limiting
REQUEST_DELAY = 1.0  # seconds between requests
SAVE_INTERVAL = 25   # save results every N districts

# Extraction schema for Firecrawl
EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "first_day_of_school": {
            "type": "string",
            "description": "First day of school for the 2025-2026 school year in YYYY-MM-DD format"
        },
        "last_day_of_school": {
            "type": "string",
            "description": "Last day of school for the 2025-2026 school year in YYYY-MM-DD format"
        },
        "spring_break_start": {
            "type": "string",
            "description": "First day of spring break for the 2025-2026 school year in YYYY-MM-DD format"
        },
        "spring_break_end": {
            "type": "string",
            "description": "Last day of spring break for the 2025-2026 school year in YYYY-MM-DD format"
        },
        "winter_break_start": {
            "type": "string",
            "description": "First day of winter/Christmas break for the 2025-2026 school year in YYYY-MM-DD format"
        },
        "winter_break_end": {
            "type": "string",
            "description": "Last day of winter/Christmas break for the 2025-2026 school year in YYYY-MM-DD format"
        },
    },
    "required": ["first_day_of_school", "last_day_of_school"]
}


# --- Data Loading ---

def load_comprehensive() -> list[dict]:
    """Load districts_comprehensive.csv."""
    districts = []
    with open(COMPREHENSIVE_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            districts.append(row)
    return districts


def load_nces_websites() -> dict[str, str]:
    """Load NCES website URLs keyed by LEAID."""
    websites = {}
    if not NCES_WEBSITES_FILE.exists():
        print(f"WARNING: {NCES_WEBSITES_FILE} not found. Will search for URLs instead.")
        return websites
    with open(NCES_WEBSITES_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            leaid = row.get("LEAID", row.get("leaid", ""))
            website = row.get("WEBSITE", row.get("website", "")).strip()
            if leaid and website:
                if not website.startswith("http"):
                    website = "https://" + website
                websites[leaid] = website
    print(f"Loaded {len(websites)} district website URLs from NCES")
    return websites


def load_results() -> dict:
    """Load previous results for resume."""
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {"confirmed": {}, "failed": {}, "stats": {}}


def save_results(results: dict):
    """Save results to JSON."""
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)


# --- Firecrawl API ---

def firecrawl_extract(url: str, prompt: str = None) -> dict | None:
    """Call Firecrawl Extract API to get structured calendar data."""
    if not FIRECRAWL_API_KEY:
        print("ERROR: FIRECRAWL_API_KEY not set")
        return None

    payload = {
        "urls": [url + "/*"],
        "prompt": prompt or (
            "Extract the school calendar dates for the 2025-2026 school year. "
            "I need: first day of school, last day of school, spring break start and end dates, "
            "and winter/Christmas break start and end dates. Return dates in YYYY-MM-DD format."
        ),
        "schema": EXTRACT_SCHEMA,
    }

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        FIRECRAWL_EXTRACT_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=120)
        result = json.loads(resp.read())

        if result.get("success") and result.get("data"):
            return result["data"]
        return None
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"    HTTP {e.code}: {body[:200]}")
        return None
    except Exception as e:
        print(f"    Error: {e}")
        return None


def firecrawl_scrape(url: str) -> str | None:
    """Scrape a single URL and return text content (for Claude post-processing)."""
    if not FIRECRAWL_API_KEY:
        return None

    payload = {
        "url": url,
        "formats": ["markdown"],
    }

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        FIRECRAWL_SCRAPE_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read())
        if result.get("success") and result.get("data"):
            return result["data"].get("markdown", "")
        return None
    except Exception as e:
        print(f"    Scrape error: {e}")
        return None


# --- Date Validation ---

def parse_date(s: str) -> date | None:
    """Parse various date formats to date object."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()

    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def validate_dates(data: dict, state: str) -> dict | None:
    """Validate extracted dates against expected ranges.

    Returns cleaned dict with YYYY-MM-DD strings, or None if invalid.
    """
    first_day = parse_date(data.get("first_day_of_school", ""))
    last_day = parse_date(data.get("last_day_of_school", ""))
    spring_start = parse_date(data.get("spring_break_start", ""))
    spring_end = parse_date(data.get("spring_break_end", ""))
    winter_start = parse_date(data.get("winter_break_start", ""))
    winter_end = parse_date(data.get("winter_break_end", ""))

    # Must have at least first_day and last_day
    if not first_day or not last_day:
        return None

    # First day: Jul 2025 - Sep 2025
    if not (date(2025, 7, 1) <= first_day <= date(2025, 9, 30)):
        return None

    # Last day: May 2026 - Jun 2026
    if not (date(2026, 5, 1) <= last_day <= date(2026, 7, 15)):
        return None

    # School year must be 140-210 days
    school_days = (last_day - first_day).days
    if not (140 <= school_days <= 210):
        return None

    result = {
        "first_day": first_day.isoformat(),
        "last_day": last_day.isoformat(),
        "summer_start": last_day.isoformat(),
        "summer_end": first_day.isoformat(),
    }

    # Spring break: Feb-May 2026
    if spring_start and spring_end:
        if (date(2026, 2, 1) <= spring_start <= date(2026, 5, 15) and
                date(2026, 2, 1) <= spring_end <= date(2026, 5, 15) and
                1 <= (spring_end - spring_start).days <= 21):
            result["spring_break_start"] = spring_start.isoformat()
            result["spring_break_end"] = spring_end.isoformat()

    # Winter break: Nov 2025 - Jan 2026
    if winter_start and winter_end:
        if (date(2025, 11, 15) <= winter_start <= date(2026, 1, 15) and
                date(2025, 12, 1) <= winter_end <= date(2026, 1, 15) and
                3 <= (winter_end - winter_start).days <= 28):
            result["winter_break_start"] = winter_start.isoformat()
            result["winter_break_end"] = winter_end.isoformat()

    return result


# --- Main Batch Process ---

def get_uncovered_districts(districts: list[dict], min_enrollment: int = 0) -> list[dict]:
    """Get districts that need confirmation, sorted by enrollment."""
    uncovered = []
    for d in districts:
        confidence = d.get("confidence", "")
        if confidence in ("confirmed", "high"):
            continue
        enrollment = int(d.get("enrollment", 0) or 0)
        if enrollment < min_enrollment:
            continue
        uncovered.append(d)

    uncovered.sort(key=lambda x: -int(x.get("enrollment", 0) or 0))
    return uncovered


def find_district_url(district: dict, nces_websites: dict) -> str | None:
    """Find the website URL for a district."""
    leaid = district.get("nces_leaid", "")

    # Try NCES website first
    if leaid in nces_websites:
        return nces_websites[leaid]

    # Fallback: construct a search-friendly URL
    # (would need Firecrawl search or Tavily for this)
    return None


def run_batch(
    limit: int = 500,
    min_enrollment: int = 0,
    resume: bool = True,
    dry_run: bool = False,
):
    """Run batch extraction on uncovered districts."""
    print("=" * 60)
    print("Firecrawl Batch Extraction — School Calendar Confirmation")
    print("=" * 60)

    if not FIRECRAWL_API_KEY and not dry_run:
        print("ERROR: Set FIRECRAWL_API_KEY environment variable")
        sys.exit(1)

    # Load data
    print("\nLoading data...")
    districts = load_comprehensive()
    nces_websites = load_nces_websites()
    results = load_results() if resume else {"confirmed": {}, "failed": {}, "stats": {}}

    already_done = set(results["confirmed"].keys()) | set(results["failed"].keys())
    print(f"Already processed: {len(already_done)} districts")

    # Get uncovered districts
    uncovered = get_uncovered_districts(districts, min_enrollment=min_enrollment)
    # Filter out already-processed
    uncovered = [d for d in uncovered if d.get("nces_leaid", "") not in already_done]

    print(f"Uncovered districts to process: {len(uncovered)}")
    if limit:
        uncovered = uncovered[:limit]
        print(f"Processing top {len(uncovered)} by enrollment")

    if not uncovered:
        print("Nothing to process!")
        return

    # Show enrollment breakdown
    total_enrollment = sum(int(d.get("enrollment", 0) or 0) for d in uncovered)
    print(f"Total enrollment of batch: {total_enrollment:,}")

    if dry_run:
        print("\n--- DRY RUN ---")
        for i, d in enumerate(uncovered[:20]):
            url = find_district_url(d, nces_websites)
            print(f"  {i+1}. {d['district_name']} ({d['state']}) — {int(d.get('enrollment', 0)):,} students — URL: {url or 'NO URL'}")
        url_count = sum(1 for d in uncovered if find_district_url(d, nces_websites))
        print(f"\n{url_count}/{len(uncovered)} have NCES website URLs ({url_count/len(uncovered)*100:.0f}%)")
        print(f"Estimated credits: {len(uncovered) * 24:,}")
        return

    # Process districts
    confirmed_count = 0
    failed_count = 0
    no_url_count = 0
    newly_confirmed = []

    for i, d in enumerate(uncovered):
        leaid = d.get("nces_leaid", "")
        name = d.get("district_name", "")
        state = d.get("state", "")
        enrollment = int(d.get("enrollment", 0) or 0)

        url = find_district_url(d, nces_websites)
        if not url:
            no_url_count += 1
            results["failed"][leaid] = {
                "name": name, "state": state, "enrollment": enrollment,
                "reason": "no_url", "timestamp": datetime.now().isoformat()
            }
            if (i + 1) % 50 == 0:
                print(f"  [{i+1}/{len(uncovered)}] {name} ({state}): NO URL")
            continue

        print(f"  [{i+1}/{len(uncovered)}] {name} ({state}) — {enrollment:,} students")
        print(f"    URL: {url}")

        # Try Firecrawl extract
        data = firecrawl_extract(url)
        if data:
            validated = validate_dates(data, state)
            if validated:
                confirmed_count += 1
                results["confirmed"][leaid] = {
                    "name": name, "state": state, "enrollment": enrollment,
                    "dates": validated, "source_url": url,
                    "confidence": "confirmed",
                    "timestamp": datetime.now().isoformat(),
                }
                newly_confirmed.append({**validated, "nces_leaid": leaid, "district_name": name, "state": state, "enrollment": enrollment})
                print(f"    ✅ CONFIRMED: first={validated['first_day']}, spring={validated.get('spring_break_start', 'N/A')}")
            else:
                failed_count += 1
                results["failed"][leaid] = {
                    "name": name, "state": state, "enrollment": enrollment,
                    "reason": "validation_failed", "raw_data": data,
                    "timestamp": datetime.now().isoformat(),
                }
                print(f"    ❌ Validation failed: {data}")
        else:
            failed_count += 1
            results["failed"][leaid] = {
                "name": name, "state": state, "enrollment": enrollment,
                "reason": "extract_failed", "url": url,
                "timestamp": datetime.now().isoformat(),
            }
            print(f"    ❌ Extract failed")

        # Rate limit
        time.sleep(REQUEST_DELAY)

        # Periodic save
        if (i + 1) % SAVE_INTERVAL == 0:
            save_results(results)
            print(f"  --- Saved. Confirmed: {confirmed_count}, Failed: {failed_count}, No URL: {no_url_count} ---")

    # Final save
    results["stats"] = {
        "batch_size": len(uncovered),
        "confirmed": confirmed_count,
        "failed": failed_count,
        "no_url": no_url_count,
        "confirmed_enrollment": sum(
            r["enrollment"] for r in results["confirmed"].values()
        ),
        "completed_at": datetime.now().isoformat(),
    }
    save_results(results)

    # Write newly confirmed CSV
    if newly_confirmed:
        fieldnames = [
            "nces_leaid", "district_name", "state", "enrollment",
            "first_day", "last_day", "spring_break_start", "spring_break_end",
            "winter_break_start", "winter_break_end", "summer_start", "summer_end",
        ]
        with open(CONFIRMED_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(newly_confirmed)
        print(f"\nNewly confirmed districts written to {CONFIRMED_FILE}")

    # Summary
    print("\n" + "=" * 60)
    print("BATCH COMPLETE")
    print(f"  Processed: {len(uncovered)}")
    print(f"  Confirmed: {confirmed_count}")
    print(f"  Failed: {failed_count}")
    print(f"  No URL: {no_url_count}")
    total_confirmed_enrollment = sum(r["enrollment"] for r in results["confirmed"].values())
    print(f"  Total confirmed enrollment added: {total_confirmed_enrollment:,}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Firecrawl batch extraction for school calendars")
    parser.add_argument("--limit", type=int, default=500, help="Max districts to process")
    parser.add_argument("--min-enrollment", type=int, default=0, help="Min enrollment to include")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from previous run")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Start fresh")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be scraped")
    args = parser.parse_args()

    run_batch(
        limit=args.limit,
        min_enrollment=args.min_enrollment,
        resume=args.resume,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
