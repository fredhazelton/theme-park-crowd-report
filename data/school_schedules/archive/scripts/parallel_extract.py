#!/usr/bin/env python3
"""Parallel Firecrawl Extract for School Calendar Confirmation.

Submits extract jobs in parallel batches, polls all concurrently.
Much faster than sequential: processes ~10 districts per minute instead of 1.

Usage:
    python parallel_extract.py --min-enrollment 10000 --batch-size 10
    python parallel_extract.py --min-enrollment 5000 --resume
    python parallel_extract.py --min-enrollment 2000 --resume
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

BASE_DIR = Path(__file__).parent
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
NCES_ALL_FILE = BASE_DIR / "nces_all_districts.csv"
RESULTS_FILE = BASE_DIR / "confirmation_results.json"
CONFIRMED_CSV = BASE_DIR / "newly_confirmed.csv"
LOG_FILE = BASE_DIR / "parallel_extract.log"

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_EXTRACT_URL = "https://api.firecrawl.dev/v1/extract"

MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6, 'jul': 7, 'aug': 8,
    'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "first_day_of_school": {"type": "string", "description": "First day of school for the 2025-2026 school year in YYYY-MM-DD format"},
        "last_day_of_school": {"type": "string", "description": "Last day of school for the 2025-2026 school year in YYYY-MM-DD format"},
        "spring_break_start": {"type": "string", "description": "First day of spring break for the 2025-2026 school year in YYYY-MM-DD format"},
        "spring_break_end": {"type": "string", "description": "Last day of spring break for the 2025-2026 school year in YYYY-MM-DD format"},
        "winter_break_start": {"type": "string", "description": "First day of winter/Christmas break for the 2025-2026 school year in YYYY-MM-DD format"},
        "winter_break_end": {"type": "string", "description": "Last day of winter/Christmas break for the 2025-2026 school year in YYYY-MM-DD format"},
    },
    "required": ["spring_break_start", "spring_break_end"]
}


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_comprehensive() -> list[dict]:
    districts = []
    with open(COMPREHENSIVE_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            districts.append(row)
    return districts


def load_nces_websites() -> dict[str, str]:
    websites = {}
    with open(NCES_ALL_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            leaid = row.get("leaid", "").strip()
            website = row.get("website", "").strip()
            if leaid and website:
                if not website.startswith("http"):
                    website = "https://" + website
                websites[leaid] = website
    return websites


def load_results() -> dict:
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            data = json.load(f)
            if "confirmed" in data:
                return data
    return {"confirmed": {}, "failed": {}, "credits_used": 0}


def save_results(results: dict):
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)


# --- Firecrawl Extract API ---

def submit_extract(url: str) -> str | None:
    """Submit an extract job. Returns job ID."""
    payload = {
        "urls": [url],
        "prompt": (
            "Extract the school calendar dates for the 2025-2026 school year from this school district website. "
            "I need: first day of school, last day of school, spring break start and end dates, "
            "and winter/Christmas break start and end dates. Return ALL dates in YYYY-MM-DD format. "
            "Look for academic calendar, school year calendar, or district calendar."
        ),
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
        return None
    except urllib.error.HTTPError as e:
        if e.code == 429:
            log("  RATE LIMITED - waiting 30s")
            time.sleep(30)
        return None
    except Exception as e:
        return None


def poll_extract(job_id: str) -> tuple[str, dict | None, int]:
    """Poll for job completion. Returns (status, data, credits)."""
    req = urllib.request.Request(
        f"{FIRECRAWL_EXTRACT_URL}/{job_id}",
        headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        result = json.loads(resp.read())
        status = result.get("status", "unknown")
        credits = result.get("creditsUsed", 0)
        if status == "completed":
            return "completed", result.get("data", {}), credits
        elif status == "failed":
            return "failed", None, credits
        return "processing", None, 0
    except Exception:
        return "error", None, 0


# --- Date Validation ---

def parse_date_str(s: str) -> date | None:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def validate_dates(data: dict) -> dict | None:
    """Validate and normalize extracted dates."""
    if not data or not isinstance(data, dict):
        return None
    
    result = {}
    
    # Parse all dates
    fd = parse_date_str(data.get("first_day_of_school", ""))
    ld = parse_date_str(data.get("last_day_of_school", ""))
    sb_s = parse_date_str(data.get("spring_break_start", ""))
    sb_e = parse_date_str(data.get("spring_break_end", ""))
    wb_s = parse_date_str(data.get("winter_break_start", ""))
    wb_e = parse_date_str(data.get("winter_break_end", ""))
    
    # Validate first/last day
    if fd and ld:
        if (date(2025, 7, 1) <= fd <= date(2025, 9, 30) and
            date(2026, 5, 1) <= ld <= date(2026, 7, 15) and
            240 <= (ld - fd).days <= 330):
            result["first_day"] = fd.isoformat()
            result["last_day"] = ld.isoformat()
            result["summer_start"] = ld.isoformat()
            result["summer_end"] = fd.isoformat()
    
    # Validate spring break
    if sb_s and sb_e:
        if (date(2026, 2, 1) <= sb_s <= date(2026, 5, 31) and
            date(2026, 2, 1) <= sb_e <= date(2026, 5, 31) and
            sb_e >= sb_s and
            0 <= (sb_e - sb_s).days <= 21):
            result["spring_break_start"] = sb_s.isoformat()
            result["spring_break_end"] = sb_e.isoformat()
    
    # Validate winter break
    if wb_s and wb_e:
        if (date(2025, 11, 15) <= wb_s <= date(2026, 1, 15) and
            date(2025, 12, 1) <= wb_e <= date(2026, 1, 15) and
            wb_e >= wb_s and
            3 <= (wb_e - wb_s).days <= 28):
            result["winter_break_start"] = wb_s.isoformat()
            result["winter_break_end"] = wb_e.isoformat()
    
    # Must have spring break or first/last day
    if "spring_break_start" not in result and "first_day" not in result:
        return None
    
    return result


# --- Main ---

def get_uncovered(districts, nces_websites, min_enrollment):
    uncovered = []
    for d in districts:
        if d.get("confidence") in ("confirmed", "high"):
            continue
        e = int(d.get("enrollment", 0) or 0)
        if e < min_enrollment:
            continue
        leaid = d.get("nces_leaid", "")
        website = nces_websites.get(leaid, "")
        if not website:
            continue
        uncovered.append({
            "leaid": leaid, "name": d["district_name"],
            "state": d["state"], "enrollment": e, "website": website,
        })
    uncovered.sort(key=lambda x: -x["enrollment"])
    return uncovered


def run_batch(limit=0, min_enrollment=0, batch_size=10, resume=True, dry_run=False):
    log("=" * 70)
    log("Parallel Extract — School Calendar Confirmation")
    log(f"Batch size: {batch_size} | Min enrollment: {min_enrollment:,}")
    log("=" * 70)
    
    districts = load_comprehensive()
    nces_websites = load_nces_websites()
    results = load_results() if resume else {"confirmed": {}, "failed": {}, "credits_used": 0}
    
    already = set(results["confirmed"].keys()) | set(results["failed"].keys())
    log(f"Already: {len(results['confirmed'])} confirmed, {len(results['failed'])} failed")
    
    uncovered = get_uncovered(districts, nces_websites, min_enrollment)
    uncovered = [d for d in uncovered if d["leaid"] not in already]
    
    if limit:
        uncovered = uncovered[:limit]
    
    log(f"To process: {len(uncovered)} districts")
    total_enrollment = sum(d["enrollment"] for d in uncovered)
    log(f"Enrollment: {total_enrollment:,}")
    est_credits = len(uncovered) * 23
    log(f"Est credits: {est_credits:,} (available: {86623 - results.get('credits_used', 0):,})")
    
    if dry_run:
        for i, d in enumerate(uncovered[:30]):
            log(f"  {i+1}. {d['name']} ({d['state']}) — {d['enrollment']:,}")
        return results
    
    # Process in batches
    confirmed_count = len(results["confirmed"])
    failed_count = len(results["failed"])
    total_credits = results.get("credits_used", 0)
    batch_num = 0
    
    for batch_start in range(0, len(uncovered), batch_size):
        batch = uncovered[batch_start:batch_start + batch_size]
        batch_num += 1
        log(f"\n--- Batch {batch_num}: districts {batch_start+1}-{batch_start+len(batch)} ---")
        
        # Submit all jobs in this batch
        jobs = {}  # job_id -> district
        for d in batch:
            job_id = submit_extract(d["website"])
            if job_id:
                jobs[job_id] = d
                log(f"  Submitted: {d['name']} ({d['state']}) → {job_id[:12]}...")
            else:
                failed_count += 1
                results["failed"][d["leaid"]] = {
                    "name": d["name"], "state": d["state"], "enrollment": d["enrollment"],
                    "reason": "submit_failed", "website": d["website"],
                    "timestamp": datetime.now().isoformat(),
                }
                log(f"  SUBMIT FAILED: {d['name']}")
            time.sleep(0.5)  # Small delay between submissions
        
        if not jobs:
            continue
        
        # Poll for all jobs
        log(f"  Polling {len(jobs)} jobs...")
        pending = dict(jobs)
        max_polls = 30  # 30 * 5s = 150s max wait
        
        for poll_round in range(max_polls):
            if not pending:
                break
            time.sleep(5)
            
            done_ids = []
            for job_id, district in list(pending.items()):
                status, data, credits = poll_extract(job_id)
                
                if status == "completed":
                    total_credits += credits
                    validated = validate_dates(data)
                    if validated:
                        confirmed_count += 1
                        results["confirmed"][district["leaid"]] = {
                            "name": district["name"], "state": district["state"],
                            "enrollment": district["enrollment"],
                            "dates": validated, "source_url": district["website"],
                            "raw_data": data, "credits": credits,
                            "timestamp": datetime.now().isoformat(),
                        }
                        sb = validated.get("spring_break_start", "N/A")
                        log(f"  ✅ {district['name']}: spring={sb}")
                    else:
                        failed_count += 1
                        results["failed"][district["leaid"]] = {
                            "name": district["name"], "state": district["state"],
                            "enrollment": district["enrollment"],
                            "reason": "validation_failed", "raw_data": data,
                            "credits": credits,
                            "timestamp": datetime.now().isoformat(),
                        }
                        log(f"  ❌ {district['name']}: validation failed ({data})")
                    done_ids.append(job_id)
                    
                elif status == "failed":
                    total_credits += credits
                    failed_count += 1
                    results["failed"][district["leaid"]] = {
                        "name": district["name"], "state": district["state"],
                        "enrollment": district["enrollment"],
                        "reason": "extract_failed", "credits": credits,
                        "timestamp": datetime.now().isoformat(),
                    }
                    log(f"  ❌ {district['name']}: extract failed")
                    done_ids.append(job_id)
            
            for jid in done_ids:
                del pending[jid]
        
        # Any still pending after max polls → failed
        for job_id, district in pending.items():
            failed_count += 1
            results["failed"][district["leaid"]] = {
                "name": district["name"], "state": district["state"],
                "enrollment": district["enrollment"],
                "reason": "timeout",
                "timestamp": datetime.now().isoformat(),
            }
            log(f"  ❌ {district['name']}: timeout")
        
        results["credits_used"] = total_credits
        save_results(results)
        
        conf_e = sum(r["enrollment"] for r in results["confirmed"].values())
        total_e = sum(int(d.get("enrollment", 0) or 0) for d in load_comprehensive())
        pct = (18381367 + conf_e) / total_e * 100  # 18.38M already confirmed in base
        log(f"  Batch done: {confirmed_count} confirmed, {failed_count} failed | Credits: {total_credits:,}")
        log(f"  Total confirmed enrollment: {18381367 + conf_e:,} ({pct:.1f}% of {total_e:,})")
    
    # Write final CSV
    write_csv(results)
    
    conf_e = sum(r["enrollment"] for r in results["confirmed"].values())
    log("\n" + "=" * 70)
    log("COMPLETE")
    log(f"  Confirmed: {len(results['confirmed'])} new districts ({conf_e:,} enrollment)")
    log(f"  Failed: {len(results['failed'])}")
    log(f"  Credits used: {total_credits:,}")
    total_e = sum(int(d.get("enrollment", 0) or 0) for d in load_comprehensive())
    pct = (18381367 + conf_e) / total_e * 100
    log(f"  Total coverage: {pct:.1f}%")
    log("=" * 70)
    
    return results


def write_csv(results: dict):
    confirmed = results.get("confirmed", {})
    if not confirmed:
        return
    rows = []
    for leaid, r in confirmed.items():
        dates = r.get("dates", {})
        rows.append({
            "nces_leaid": leaid, "district_name": r["name"],
            "state": r["state"], "enrollment": r["enrollment"],
            "first_day": dates.get("first_day", ""),
            "last_day": dates.get("last_day", ""),
            "spring_break_start": dates.get("spring_break_start", ""),
            "spring_break_end": dates.get("spring_break_end", ""),
            "winter_break_start": dates.get("winter_break_start", ""),
            "winter_break_end": dates.get("winter_break_end", ""),
            "summer_start": dates.get("summer_start", ""),
            "summer_end": dates.get("summer_end", ""),
            "source": "firecrawl_extract",
        })
    fieldnames = list(rows[0].keys())
    with open(CONFIRMED_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log(f"Wrote {len(rows)} to {CONFIRMED_CSV}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-enrollment", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    
    run_batch(
        limit=args.limit,
        min_enrollment=args.min_enrollment,
        batch_size=args.batch_size,
        resume=args.resume,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
