#!/usr/bin/env python3
"""Phase C: Async Firecrawl Batch Extraction for School Calendar Confirmation.

Key fix over Barney's original: Firecrawl Extract API is ASYNC.
Submit job → get ID → poll until completed.

Strategy:
1. Load uncovered districts sorted by enrollment
2. Submit extract jobs in waves (to manage concurrency)
3. Poll for results
4. Validate dates
5. Save confirmed districts

Usage:
    python firecrawl_async_scraper.py --min-enrollment 10000 --limit 500
    python firecrawl_async_scraper.py --min-enrollment 5000
    python firecrawl_async_scraper.py --min-enrollment 2000
    python firecrawl_async_scraper.py --resume
    python firecrawl_async_scraper.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict

# --- Configuration ---
BASE_DIR = Path(__file__).parent
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
NCES_ALL_FILE = BASE_DIR / "nces_all_districts.csv"
RESULTS_FILE = BASE_DIR / "firecrawl_async_results.json"
CONFIRMED_CSV_FILE = BASE_DIR / "newly_confirmed_firecrawl.csv"
LOG_FILE = BASE_DIR / "firecrawl_scraper.log"

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_EXTRACT_URL = "https://api.firecrawl.dev/v1/extract"

# Timing
SUBMIT_DELAY = 1.0      # seconds between job submissions
POLL_DELAY = 5.0         # seconds between polls
POLL_MAX_ATTEMPTS = 30   # max poll attempts per job (150s total)
WAVE_SIZE = 5            # jobs to submit before polling wave
SAVE_INTERVAL = 10       # save results every N completed districts

# --- Extraction Schema ---
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
    "required": ["first_day_of_school", "last_day_of_school", "spring_break_start", "spring_break_end"]
}

EXTRACT_PROMPT = (
    "Extract the school calendar dates for the 2025-2026 school year. "
    "I need: first day of school, last day of school, spring break start and end dates, "
    "and winter/Christmas break start and end dates. "
    "Return ALL dates in YYYY-MM-DD format. "
    "Look for the academic calendar, school year calendar, or district calendar pages."
)


def log(msg: str):
    """Log to file and stdout."""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# --- Data Loading ---

def load_comprehensive() -> list[dict]:
    districts = []
    with open(COMPREHENSIVE_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            districts.append(row)
    return districts


def load_nces_websites() -> dict[str, str]:
    """Load website URLs from nces_all_districts.csv keyed by leaid."""
    websites = {}
    if not NCES_ALL_FILE.exists():
        log(f"WARNING: {NCES_ALL_FILE} not found")
        return websites
    with open(NCES_ALL_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            leaid = row.get("leaid", "").strip()
            website = row.get("website", "").strip()
            if leaid and website:
                if not website.startswith("http"):
                    website = "https://" + website
                websites[leaid] = website
    log(f"Loaded {len(websites)} website URLs from NCES")
    return websites


def load_results() -> dict:
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {"confirmed": {}, "failed": {}, "pending_jobs": {}, "credits_used": 0, "stats": {}}


def save_results(results: dict):
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)


# --- Firecrawl API (Async) ---

def submit_extract_job(url: str) -> str | None:
    """Submit an extract job. Returns job ID or None."""
    payload = {
        "urls": [url],
        "prompt": EXTRACT_PROMPT,
        "schema": EXTRACT_SCHEMA,
        "enableWebSearch": True,
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
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        if result.get("success") and result.get("id"):
            return result["id"]
        log(f"    Submit failed: {json.dumps(result)[:200]}")
        return None
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        log(f"    HTTP {e.code}: {body[:200]}")
        if e.code == 429:
            log("    Rate limited! Waiting 30s...")
            time.sleep(30)
        return None
    except Exception as e:
        log(f"    Submit error: {e}")
        return None


def poll_extract_job(job_id: str) -> tuple[str, dict | None, int]:
    """Poll for job completion. Returns (status, data, credits_used)."""
    req = urllib.request.Request(
        f"{FIRECRAWL_EXTRACT_URL}/{job_id}",
        headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}"},
    )

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        status = result.get("status", "unknown")
        credits = result.get("creditsUsed", 0)

        if status == "completed":
            return "completed", result.get("data", {}), credits
        elif status == "failed":
            return "failed", None, credits
        else:
            return "processing", None, 0
    except Exception as e:
        log(f"    Poll error: {e}")
        return "error", None, 0


# --- Date Validation ---

def parse_date(s: str) -> date | None:
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
    """Validate extracted dates. Returns cleaned dict or None."""
    first_day = parse_date(data.get("first_day_of_school", ""))
    last_day = parse_date(data.get("last_day_of_school", ""))
    spring_start = parse_date(data.get("spring_break_start", ""))
    spring_end = parse_date(data.get("spring_break_end", ""))
    winter_start = parse_date(data.get("winter_break_start", ""))
    winter_end = parse_date(data.get("winter_break_end", ""))

    # Must have at least spring break (that's our key metric)
    # OR first_day + last_day
    has_spring = spring_start and spring_end
    has_year = first_day and last_day

    if not has_spring and not has_year:
        return None

    result = {}

    # Validate first/last day
    if first_day and last_day:
        if (date(2025, 7, 1) <= first_day <= date(2025, 9, 30) and
                date(2026, 5, 1) <= last_day <= date(2026, 7, 15)):
            calendar_days = (last_day - first_day).days
            if 240 <= calendar_days <= 330:
                result["first_day"] = first_day.isoformat()
                result["last_day"] = last_day.isoformat()
                result["summer_start"] = last_day.isoformat()
                result["summer_end"] = first_day.isoformat()

    # Validate spring break
    if spring_start and spring_end:
        if (date(2026, 2, 1) <= spring_start <= date(2026, 5, 31) and
                date(2026, 2, 1) <= spring_end <= date(2026, 5, 31) and
                spring_end >= spring_start and
                1 <= (spring_end - spring_start).days <= 21):
            result["spring_break_start"] = spring_start.isoformat()
            result["spring_break_end"] = spring_end.isoformat()

    # Validate winter break
    if winter_start and winter_end:
        if (date(2025, 11, 15) <= winter_start <= date(2026, 1, 15) and
                date(2025, 12, 1) <= winter_end <= date(2026, 1, 15) and
                winter_end >= winter_start and
                3 <= (winter_end - winter_start).days <= 28):
            result["winter_break_start"] = winter_start.isoformat()
            result["winter_break_end"] = winter_end.isoformat()

    # Must have at least spring break or first/last day to be useful
    if "spring_break_start" not in result and "first_day" not in result:
        return None

    return result


# --- Main Batch Process ---

def get_uncovered_districts(districts: list[dict], nces_websites: dict,
                            min_enrollment: int = 0) -> list[dict]:
    """Get uncovered districts with URLs, sorted by enrollment desc."""
    uncovered = []
    for d in districts:
        if d.get("confidence") in ("confirmed", "high"):
            continue
        enrollment = int(d.get("enrollment", 0) or 0)
        if enrollment < min_enrollment:
            continue
        leaid = d.get("nces_leaid", "")
        website = nces_websites.get(leaid, "")
        if not website:
            continue
        uncovered.append({
            "leaid": leaid,
            "name": d["district_name"],
            "state": d["state"],
            "enrollment": enrollment,
            "website": website,
        })
    uncovered.sort(key=lambda x: -x["enrollment"])
    return uncovered


def run_batch(limit: int = 0, min_enrollment: int = 0, resume: bool = True, dry_run: bool = False):
    log("=" * 70)
    log("Firecrawl ASYNC Batch Extraction — School Calendar Confirmation")
    log("=" * 70)

    if not FIRECRAWL_API_KEY and not dry_run:
        log("ERROR: Set FIRECRAWL_API_KEY environment variable")
        sys.exit(1)

    # Load data
    log("Loading data...")
    districts = load_comprehensive()
    nces_websites = load_nces_websites()
    results = load_results() if resume else {"confirmed": {}, "failed": {}, "pending_jobs": {}, "credits_used": 0, "stats": {}}

    already_done = set(results["confirmed"].keys()) | set(results["failed"].keys())
    log(f"Already processed: {len(already_done)} ({len(results['confirmed'])} confirmed, {len(results['failed'])} failed)")

    # Get uncovered districts with URLs
    uncovered = get_uncovered_districts(districts, nces_websites, min_enrollment=min_enrollment)
    uncovered = [d for d in uncovered if d["leaid"] not in already_done]

    log(f"Uncovered districts with URLs: {len(uncovered)} (min enrollment: {min_enrollment:,})")

    if limit:
        uncovered = uncovered[:limit]
        log(f"Limited to top {len(uncovered)}")

    if not uncovered:
        log("Nothing to process!")
        return results

    total_enrollment = sum(d["enrollment"] for d in uncovered)
    log(f"Total enrollment in batch: {total_enrollment:,}")
    est_credits = len(uncovered) * 23
    log(f"Estimated credits needed: {est_credits:,}")
    log(f"Credits available: {86623 - results.get('credits_used', 0):,}")

    if dry_run:
        log("\n--- DRY RUN ---")
        for i, d in enumerate(uncovered[:30]):
            log(f"  {i+1}. {d['name']} ({d['state']}) — {d['enrollment']:,} — {d['website'][:60]}")
        # Enrollment tier breakdown
        tiers = [(10000, "10K+"), (5000, "5K-10K"), (2000, "2K-5K"), (1000, "1K-2K"), (0, "<1K")]
        for threshold, label in tiers:
            tier = [d for d in uncovered if d["enrollment"] >= threshold]
            if tier:
                log(f"\n  {label}: {len(tier)} districts, {sum(d['enrollment'] for d in tier):,} enrollment")
        return results

    # Process in sequential mode (submit → poll → next)
    confirmed_count = 0
    failed_count = 0
    total_credits = results.get("credits_used", 0)

    for i, d in enumerate(uncovered):
        leaid = d["leaid"]
        name = d["name"]
        state = d["state"]
        enrollment = d["enrollment"]
        url = d["website"]

        log(f"[{i+1}/{len(uncovered)}] {name} ({state}) — {enrollment:,} — {url}")

        # Submit extract job
        job_id = submit_extract_job(url)
        if not job_id:
            failed_count += 1
            results["failed"][leaid] = {
                "name": name, "state": state, "enrollment": enrollment,
                "reason": "submit_failed", "url": url,
                "timestamp": datetime.now().isoformat(),
            }
            time.sleep(SUBMIT_DELAY)
            continue

        log(f"  Job submitted: {job_id}")

        # Poll for results
        final_data = None
        final_credits = 0
        for attempt in range(POLL_MAX_ATTEMPTS):
            time.sleep(POLL_DELAY)
            status, data, credits = poll_extract_job(job_id)

            if status == "completed":
                final_data = data
                final_credits = credits
                break
            elif status == "failed":
                log(f"  Job failed")
                break
            # else still processing, continue polling

        if final_data:
            validated = validate_dates(final_data, state)
            if validated:
                confirmed_count += 1
                total_credits += final_credits
                results["confirmed"][leaid] = {
                    "name": name, "state": state, "enrollment": enrollment,
                    "dates": validated, "source_url": url,
                    "raw_data": final_data,
                    "credits": final_credits,
                    "confidence": "confirmed",
                    "timestamp": datetime.now().isoformat(),
                }
                sb = validated.get("spring_break_start", "N/A")
                fd = validated.get("first_day", "N/A")
                log(f"  ✅ CONFIRMED: spring_break={sb}, first_day={fd}")
            else:
                failed_count += 1
                results["failed"][leaid] = {
                    "name": name, "state": state, "enrollment": enrollment,
                    "reason": "validation_failed", "raw_data": final_data,
                    "url": url, "credits": final_credits,
                    "timestamp": datetime.now().isoformat(),
                }
                total_credits += final_credits
                log(f"  ❌ Validation failed: {final_data}")
        else:
            failed_count += 1
            results["failed"][leaid] = {
                "name": name, "state": state, "enrollment": enrollment,
                "reason": "no_data", "url": url, "job_id": job_id,
                "timestamp": datetime.now().isoformat(),
            }
            log(f"  ❌ No data returned")

        results["credits_used"] = total_credits

        # Periodic save
        if (confirmed_count + failed_count) % SAVE_INTERVAL == 0:
            save_results(results)
            rate = confirmed_count / (confirmed_count + failed_count) * 100 if (confirmed_count + failed_count) else 0
            log(f"  --- Saved. Confirmed: {confirmed_count}, Failed: {failed_count}, Rate: {rate:.0f}%, Credits: {total_credits:,} ---")

        time.sleep(SUBMIT_DELAY)

    # Final save
    results["credits_used"] = total_credits
    results["stats"] = {
        "batch_size": len(uncovered),
        "min_enrollment": min_enrollment,
        "confirmed": confirmed_count,
        "failed": failed_count,
        "success_rate": confirmed_count / (confirmed_count + failed_count) * 100 if (confirmed_count + failed_count) else 0,
        "total_credits_used": total_credits,
        "confirmed_enrollment": sum(r["enrollment"] for r in results["confirmed"].values()),
        "completed_at": datetime.now().isoformat(),
    }
    save_results(results)

    # Write confirmed CSV
    write_confirmed_csv(results)

    # Summary
    log("\n" + "=" * 70)
    log("BATCH COMPLETE")
    log(f"  Total processed: {confirmed_count + failed_count}")
    log(f"  Confirmed: {confirmed_count}")
    log(f"  Failed: {failed_count}")
    log(f"  Success rate: {results['stats']['success_rate']:.1f}%")
    log(f"  Credits used: {total_credits:,}")
    confirmed_enrollment = sum(r["enrollment"] for r in results["confirmed"].values())
    log(f"  Confirmed enrollment: {confirmed_enrollment:,}")
    log("=" * 70)

    return results


def write_confirmed_csv(results: dict):
    """Write confirmed districts to CSV for merge."""
    confirmed = results.get("confirmed", {})
    if not confirmed:
        return

    rows = []
    for leaid, r in confirmed.items():
        dates = r.get("dates", {})
        rows.append({
            "nces_leaid": leaid,
            "district_name": r["name"],
            "state": r["state"],
            "enrollment": r["enrollment"],
            "first_day": dates.get("first_day", ""),
            "last_day": dates.get("last_day", ""),
            "spring_break_start": dates.get("spring_break_start", ""),
            "spring_break_end": dates.get("spring_break_end", ""),
            "winter_break_start": dates.get("winter_break_start", ""),
            "winter_break_end": dates.get("winter_break_end", ""),
            "summer_start": dates.get("summer_start", ""),
            "summer_end": dates.get("summer_end", ""),
            "source_url": r.get("source_url", ""),
        })

    fieldnames = list(rows[0].keys())
    with open(CONFIRMED_CSV_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log(f"Wrote {len(rows)} confirmed districts to {CONFIRMED_CSV_FILE}")


def main():
    parser = argparse.ArgumentParser(description="Async Firecrawl batch extraction")
    parser.add_argument("--limit", type=int, default=0, help="Max districts to process (0=unlimited)")
    parser.add_argument("--min-enrollment", type=int, default=0, help="Min enrollment filter")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_batch(
        limit=args.limit,
        min_enrollment=args.min_enrollment,
        resume=args.resume,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
