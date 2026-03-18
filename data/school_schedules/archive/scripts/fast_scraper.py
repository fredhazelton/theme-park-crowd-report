#!/usr/bin/env python3
"""Fast School Calendar Scraper using Firecrawl Scrape API.

Uses the synchronous scrape API (1 credit, ~2s) instead of the async extract API
(23 credits, ~60s). Parses dates from markdown content.

Strategy:
1. Try common calendar URL patterns for each district
2. Parse dates from markdown using regex  
3. Validate dates against expected ranges
4. Fall back to Firecrawl Extract for high-priority failures

Usage:
    python fast_scraper.py --min-enrollment 10000
    python fast_scraper.py --min-enrollment 5000
    python fast_scraper.py --min-enrollment 2000 
    python fast_scraper.py --resume --min-enrollment 2000
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
from datetime import date, datetime, timedelta
from pathlib import Path
from collections import defaultdict

# --- Configuration ---
BASE_DIR = Path(__file__).parent
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
NCES_ALL_FILE = BASE_DIR / "nces_all_districts.csv"
RESULTS_FILE = BASE_DIR / "fast_scraper_results.json"
CONFIRMED_CSV_FILE = BASE_DIR / "newly_confirmed_fast.csv"
LOG_FILE = BASE_DIR / "fast_scraper.log"
RAW_DIR = BASE_DIR / "raw_scrapes"

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"

# Timing
REQUEST_DELAY = 0.5     # seconds between requests 
SAVE_INTERVAL = 25      # save every N districts
MAX_URLS_PER_DISTRICT = 3  # max URL patterns to try

# Calendar URL patterns to try (appended to base URL)
CALENDAR_PATHS = [
    "/calendar",
    "/calendars", 
    "/academic-calendar",
    "/page/academic-calendar",
    "/page/calendars",
    "/page/calendar",
    "/cms/one.aspx?pageId=calendar",
    "/about/calendar",
    "/parents/calendar",
    "/our-district/calendar",
    "/district/calendar",
    "/families/calendar",
    "/school-calendar",
    "/academic-calendars",
]

# Month name mappings
MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6, 'jul': 7, 'aug': 8,
    'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
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
    websites = {}
    with open(NCES_ALL_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            leaid = row.get("leaid", "").strip()
            website = row.get("website", "").strip()
            if leaid and website:
                # Normalize URL
                website = website.rstrip("/")
                if not website.startswith("http"):
                    website = "https://" + website
                # Upgrade http to https
                website = website.replace("http://", "https://")
                websites[leaid] = website
    return websites


def load_results() -> dict:
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {"confirmed": {}, "failed": {}, "credits_used": 0}


def save_results(results: dict):
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)


# --- Firecrawl Scrape API ---

def scrape_url(url: str) -> tuple[str, int]:
    """Scrape a URL and return (markdown, credits_used). Returns ('', 0) on failure."""
    payload = {
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
        "timeout": 15000,
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
        resp = urllib.request.urlopen(req, timeout=20)
        result = json.loads(resp.read())
        if result.get("success"):
            md = result.get("data", {}).get("markdown", "")
            return md, 1
        return "", 0
    except urllib.error.HTTPError as e:
        if e.code == 429:
            log("  Rate limited! Waiting 10s...")
            time.sleep(10)
        return "", 0
    except Exception:
        return "", 0


# --- Date Extraction from Markdown ---

def extract_school_year(md: str) -> str | None:
    """Detect which school year this content is about."""
    # Look for "2025-2026" or "2025-26"
    if re.search(r'2025\s*[-–]\s*2026|2025\s*[-–]\s*26', md):
        return "2025-2026"
    if re.search(r'2024\s*[-–]\s*2025|2024\s*[-–]\s*25', md):
        return "2024-2025"
    return None


def parse_month_day(month_str: str, day_str: str, year_hint: int = None) -> date | None:
    """Parse a month name and day number into a date."""
    month_str = month_str.lower().strip().rstrip('.')
    month = MONTHS.get(month_str)
    if not month:
        return None
    try:
        day = int(day_str.strip())
    except (ValueError, TypeError):
        return None
    
    if not (1 <= day <= 31):
        return None
    
    # Determine year based on month
    if year_hint:
        year = year_hint
    elif month >= 7:  # Jul-Dec = 2025
        year = 2025
    else:  # Jan-Jun = 2026
        year = 2026
    
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_dates_from_markdown(md: str) -> dict:
    """Extract school calendar dates from markdown content.
    
    Returns dict with keys: first_day, last_day, spring_break_start, spring_break_end,
    winter_break_start, winter_break_end.
    """
    result = {}
    md_lower = md.lower()
    
    # Check if this is 2025-2026 content
    school_year = extract_school_year(md)
    
    # Strategy 1: Look for table rows with calendar events
    # Pattern: "| Month Day | Event description |" or "Month Day - Event"
    
    # Table format: "| August 13 | First Day of School |"
    table_rows = re.findall(
        r'\|\s*(\w+)\s+(\d{1,2})(?:\s*[-–]?\s*(?:(\d{1,2}))?)?\s*\|[^|]*?([^|]+)\|',
        md, re.I
    )
    
    for month_str, day1, day2, event in table_rows:
        event_lower = event.lower().strip()
        d1 = parse_month_day(month_str, day1)
        
        if not d1:
            continue
            
        # First day of school
        if any(p in event_lower for p in ['first day of school', 'school begins', 'school starts', 'classes begin', 'students return']):
            if date(2025, 7, 1) <= d1 <= date(2025, 9, 30):
                result['first_day'] = d1.isoformat()
        
        # Last day of school
        if any(p in event_lower for p in ['last day of school', 'school ends', 'last day for students', 'end of school', 'early release']):
            if 'last day' in event_lower or 'end of school' in event_lower:
                if date(2026, 5, 1) <= d1 <= date(2026, 7, 15):
                    result['last_day'] = d1.isoformat()
        
        # Spring break
        if any(p in event_lower for p in ['spring break', 'spring holiday', 'spring recess']):
            if date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                if 'spring_break_start' not in result:
                    result['spring_break_start'] = d1.isoformat()
                    if day2:
                        d2 = parse_month_day(month_str, day2)
                        if d2:
                            result['spring_break_end'] = d2.isoformat()
                    else:
                        result['spring_break_end'] = d1.isoformat()  # Update later if multi-row
                else:
                    # Update end date
                    result['spring_break_end'] = d1.isoformat()
        
        # Winter/Christmas break
        if any(p in event_lower for p in ['winter break', 'christmas break', 'christmas holiday', 'winter holiday', 'winter recess']):
            if d1.month in (11, 12):
                if 'winter_break_start' not in result:
                    result['winter_break_start'] = d1.isoformat()
            elif d1.month == 1:
                result['winter_break_end'] = d1.isoformat()
    
    # Strategy 2: Look for "Month Day-Day" patterns in text
    # "March 16 - 20 Spring Break" or "Spring Break: March 16-20"
    text_patterns = [
        # "Spring Break March 16-20" or "March 16-20 Spring Break"
        (r'spring\s+break[:\s]*(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})', 'spring'),
        (r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\s*[|\s]*\**(?:no school)?[*\s]*spring\s+break', 'spring'),
        (r'spring\s+break[:\s]*(\w+)\s+(\d{1,2})\s*[-–through]*\s*(\w+)\s+(\d{1,2})', 'spring_cross'),
        # Winter break
        (r'winter\s+break[:\s]*(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})', 'winter'),
        (r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\s*[|\s]*\**(?:no school)?[*\s]*winter\s+break', 'winter'),
        # Christmas break  
        (r'christmas\s+break[:\s]*(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})', 'winter'),
    ]
    
    for pattern, break_type in text_patterns:
        matches = re.findall(pattern, md, re.I)
        for match in matches:
            if break_type == 'spring_cross' and len(match) == 4:
                d1 = parse_month_day(match[0], match[1])
                d2 = parse_month_day(match[2], match[3])
                if d1 and d2 and 'spring_break_start' not in result:
                    if date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                        result['spring_break_start'] = d1.isoformat()
                        result['spring_break_end'] = d2.isoformat()
            elif len(match) >= 3:
                month_str, day1, day2 = match[0], match[1], match[2]
                d1 = parse_month_day(month_str, day1)
                d2 = parse_month_day(month_str, day2)
                
                if break_type == 'spring' and d1 and 'spring_break_start' not in result:
                    if date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                        result['spring_break_start'] = d1.isoformat()
                        result['spring_break_end'] = (d2 or d1).isoformat()
                elif break_type == 'winter' and d1 and 'winter_break_start' not in result:
                    if d1.month in (11, 12):
                        result['winter_break_start'] = d1.isoformat()
                        if d2:
                            result['winter_break_end'] = d2.isoformat()
    
    # Strategy 3: Look for date range patterns with month names
    # "December 22 - January 2" for winter break
    cross_month = re.findall(
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\w+)\s+(\d{1,2})\s*[|\s]*[*]*(?:no school)?[*\s]*(?:winter|christmas)\s+break',
        md, re.I
    )
    if not cross_month:
        cross_month = re.findall(
            r'(?:winter|christmas)\s+break[:\s]*(\w+)\s+(\d{1,2})\s*[-–through]*\s*(\w+)\s+(\d{1,2})',
            md, re.I
        )
    for m1, d1, m2, d2 in cross_month:
        start = parse_month_day(m1, d1)
        end = parse_month_day(m2, d2)
        if start and end and 'winter_break_start' not in result:
            result['winter_break_start'] = start.isoformat()
            result['winter_break_end'] = end.isoformat()
    
    # Strategy 4: First/last day patterns in text
    first_day_patterns = [
        r'first\s+day\s+(?:of\s+)?school[:\s]*(\w+)\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})\s*[|\s]*\**(?:first\s+day\s+(?:of\s+)?school)',
        r'school\s+(?:starts|begins)[:\s]*(\w+)\s+(\d{1,2})',
        r'classes\s+begin[:\s]*(\w+)\s+(\d{1,2})',
        r'students\s+(?:return|report|first day)[:\s]*(\w+)\s+(\d{1,2})',
    ]
    for pattern in first_day_patterns:
        matches = re.findall(pattern, md, re.I)
        for month_str, day_str in matches:
            d = parse_month_day(month_str, day_str)
            if d and date(2025, 7, 1) <= d <= date(2025, 9, 30) and 'first_day' not in result:
                result['first_day'] = d.isoformat()
    
    last_day_patterns = [
        r'last\s+day\s+(?:of\s+)?(?:school|classes)[:\s]*(\w+)\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})\s*[|\s]*\**(?:last\s+day)',
        r'school\s+(?:ends|closes)[:\s]*(\w+)\s+(\d{1,2})',
    ]
    for pattern in last_day_patterns:
        matches = re.findall(pattern, md, re.I)
        for month_str, day_str in matches:
            d = parse_month_day(month_str, day_str)
            if d and date(2026, 5, 1) <= d <= date(2026, 7, 15) and 'last_day' not in result:
                result['last_day'] = d.isoformat()
    
    # Strategy 5: Numeric date patterns (MM/DD/YYYY or MM/DD)
    # "Spring Break 03/16/2026 - 03/20/2026"
    numeric_spring = re.findall(
        r'spring\s+break[:\s]*(\d{1,2})[/\-](\d{1,2})[/\-]?(\d{2,4})?\s*[-–]\s*(\d{1,2})[/\-](\d{1,2})',
        md, re.I
    )
    for match in numeric_spring:
        m1, d1 = int(match[0]), int(match[1])
        m2, d2 = int(match[3]), int(match[4])
        try:
            start = date(2026, m1, d1)
            end = date(2026, m2, d2)
            if date(2026, 2, 1) <= start <= date(2026, 5, 31) and 'spring_break_start' not in result:
                result['spring_break_start'] = start.isoformat()
                result['spring_break_end'] = end.isoformat()
        except ValueError:
            pass
    
    # Derive summer dates
    if 'first_day' in result and 'last_day' in result:
        result['summer_start'] = result['last_day']
        result['summer_end'] = result['first_day']
    
    return result


# --- Validation ---

def validate_dates(data: dict) -> dict | None:
    """Validate extracted dates. Returns cleaned dict or None."""
    if not data:
        return None
    
    has_spring = 'spring_break_start' in data and 'spring_break_end' in data
    has_year = 'first_day' in data and 'last_day' in data
    
    if not has_spring and not has_year:
        return None
    
    # Validate spring break
    if has_spring:
        try:
            sb_start = date.fromisoformat(data['spring_break_start'])
            sb_end = date.fromisoformat(data['spring_break_end'])
            duration = (sb_end - sb_start).days
            if not (0 <= duration <= 21):
                del data['spring_break_start']
                del data['spring_break_end']
                has_spring = False
            if not (date(2026, 2, 1) <= sb_start <= date(2026, 5, 31)):
                del data['spring_break_start']
                del data['spring_break_end']
                has_spring = False
        except (ValueError, KeyError):
            has_spring = False
    
    # Validate first/last day
    if has_year:
        try:
            first = date.fromisoformat(data['first_day'])
            last = date.fromisoformat(data['last_day'])
            cal_days = (last - first).days
            if not (240 <= cal_days <= 330):
                del data['first_day']
                del data['last_day']
                data.pop('summer_start', None)
                data.pop('summer_end', None)
                has_year = False
        except (ValueError, KeyError):
            has_year = False
    
    if not has_spring and not has_year:
        return None
    
    return data


# --- URL Generation ---

def generate_calendar_urls(base_url: str) -> list[str]:
    """Generate candidate calendar URLs for a district website."""
    base = base_url.rstrip("/")
    urls = []
    
    # Try common patterns
    for path in CALENDAR_PATHS:
        urls.append(base + path)
    
    return urls[:MAX_URLS_PER_DISTRICT]


def has_calendar_content(md: str) -> bool:
    """Check if markdown content likely contains calendar/schedule info."""
    md_lower = md.lower()
    calendar_keywords = [
        'spring break', 'winter break', 'christmas break',
        'first day of school', 'last day of school',
        'school calendar', 'academic calendar',
        'school year', 'grading period', 'semester',
        'teacher workday', 'student holiday', 'in-service',
        'early release', 'no school',
    ]
    keyword_count = sum(1 for kw in calendar_keywords if kw in md_lower)
    return keyword_count >= 2


# --- Main Processing ---

def get_uncovered_districts(districts: list[dict], nces_websites: dict,
                            min_enrollment: int = 0) -> list[dict]:
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


def process_district(district: dict) -> tuple[dict | None, str, int]:
    """Try to extract calendar data for a district.
    
    Returns (validated_dates, source_url, credits_used).
    """
    base_url = district["website"]
    urls = generate_calendar_urls(base_url)
    total_credits = 0
    best_result = None
    best_url = ""
    
    for url in urls:
        md, credits = scrape_url(url)
        total_credits += credits
        
        if not md or len(md) < 100:
            time.sleep(REQUEST_DELAY)
            continue
        
        if has_calendar_content(md):
            dates = extract_dates_from_markdown(md)
            validated = validate_dates(dates)
            if validated:
                # Score: prefer results with more fields
                score = len(validated)
                if best_result is None or score > len(best_result):
                    best_result = validated
                    best_url = url
                # If we have spring break + first/last day, good enough
                if 'spring_break_start' in validated and 'first_day' in validated:
                    return validated, url, total_credits
        
        time.sleep(REQUEST_DELAY)
    
    return best_result, best_url, total_credits


def run_batch(limit: int = 0, min_enrollment: int = 0, resume: bool = True, dry_run: bool = False):
    log("=" * 70)
    log("Fast Scraper — School Calendar Confirmation (Scrape + Parse)")
    log("=" * 70)
    
    if not FIRECRAWL_API_KEY and not dry_run:
        log("ERROR: Set FIRECRAWL_API_KEY")
        sys.exit(1)
    
    # Create raw scrapes dir
    RAW_DIR.mkdir(exist_ok=True)
    
    # Load data
    log("Loading data...")
    districts = load_comprehensive()
    nces_websites = load_nces_websites()
    results = load_results() if resume else {"confirmed": {}, "failed": {}, "credits_used": 0}
    
    already_done = set(results["confirmed"].keys()) | set(results["failed"].keys())
    log(f"Already processed: {len(already_done)} ({len(results['confirmed'])} confirmed, {len(results['failed'])} failed)")
    
    # Also skip districts already confirmed by the async scraper
    async_results_file = BASE_DIR / "firecrawl_async_results.json"
    if async_results_file.exists():
        with open(async_results_file) as f:
            async_results = json.load(f)
        async_confirmed = set(async_results.get("confirmed", {}).keys())
        already_done.update(async_confirmed)
        log(f"Also skipping {len(async_confirmed)} from async scraper")
    
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
    est_credits = len(uncovered) * 3  # ~3 URLs tried per district
    log(f"Estimated credits: ~{est_credits:,}")
    
    if dry_run:
        log("\n--- DRY RUN ---")
        for i, d in enumerate(uncovered[:30]):
            log(f"  {i+1}. {d['name']} ({d['state']}) — {d['enrollment']:,} — {d['website']}")
        return results
    
    # Process
    confirmed_count = 0
    failed_count = 0
    total_credits = results.get("credits_used", 0)
    
    for i, d in enumerate(uncovered):
        leaid = d["leaid"]
        name = d["name"]
        state = d["state"]
        enrollment = d["enrollment"]
        
        log(f"[{i+1}/{len(uncovered)}] {name} ({state}) — {enrollment:,}")
        
        validated, source_url, credits = process_district(d)
        total_credits += credits
        
        if validated:
            confirmed_count += 1
            results["confirmed"][leaid] = {
                "name": name, "state": state, "enrollment": enrollment,
                "dates": validated, "source_url": source_url,
                "confidence": "confirmed",
                "timestamp": datetime.now().isoformat(),
            }
            sb = validated.get("spring_break_start", "N/A")
            fd = validated.get("first_day", "N/A")
            log(f"  ✅ CONFIRMED: spring_break={sb}, first_day={fd} (from {source_url})")
        else:
            failed_count += 1
            results["failed"][leaid] = {
                "name": name, "state": state, "enrollment": enrollment,
                "reason": "no_calendar_found", "website": d["website"],
                "timestamp": datetime.now().isoformat(),
            }
            log(f"  ❌ No calendar found")
        
        results["credits_used"] = total_credits
        
        if (confirmed_count + failed_count) % SAVE_INTERVAL == 0:
            save_results(results)
            rate = confirmed_count / (confirmed_count + failed_count) * 100 if (confirmed_count + failed_count) else 0
            log(f"  --- Saved. {confirmed_count} confirmed, {failed_count} failed, {rate:.0f}% rate, {total_credits} credits ---")
    
    # Final save
    results["credits_used"] = total_credits
    results["stats"] = {
        "batch_size": len(uncovered),
        "min_enrollment": min_enrollment,
        "confirmed": confirmed_count,
        "failed": failed_count,
        "success_rate": confirmed_count / max(1, confirmed_count + failed_count) * 100,
        "total_credits": total_credits,
        "confirmed_enrollment": sum(r["enrollment"] for r in results["confirmed"].values()),
        "completed_at": datetime.now().isoformat(),
    }
    save_results(results)
    write_confirmed_csv(results)
    
    log("\n" + "=" * 70)
    log("BATCH COMPLETE")
    log(f"  Confirmed: {confirmed_count} ({sum(r['enrollment'] for r in results['confirmed'].values()):,} enrollment)")
    log(f"  Failed: {failed_count}")
    log(f"  Success rate: {results['stats']['success_rate']:.1f}%")
    log(f"  Credits used: {total_credits:,}")
    log("=" * 70)
    
    return results


def write_confirmed_csv(results: dict):
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-enrollment", type=int, default=0)
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
