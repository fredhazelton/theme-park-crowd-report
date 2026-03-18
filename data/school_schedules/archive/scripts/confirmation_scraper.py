#!/usr/bin/env python3
"""School Calendar Confirmation Scraper — Map + Scrape + Parse approach.

Strategy:
1. Use Firecrawl Map API to find calendar pages on district websites (1 credit)
2. Pick the best link (prefer 2025-2026 calendar URLs)
3. Scrape with Firecrawl (1 credit) to get markdown
4. Parse dates from markdown with robust regex patterns
5. Validate and save

Cost: ~2-3 credits per district (map + 1-2 scrapes)
Speed: ~3-5 seconds per district (synchronous APIs)

Usage:
    python confirmation_scraper.py --min-enrollment 10000
    python confirmation_scraper.py --min-enrollment 5000 --resume
    python confirmation_scraper.py --min-enrollment 2000 --resume
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
from collections import defaultdict

# --- Configuration ---
BASE_DIR = Path(__file__).parent
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
NCES_ALL_FILE = BASE_DIR / "nces_all_districts.csv"
RESULTS_FILE = BASE_DIR / "confirmation_results.json"
CONFIRMED_CSV = BASE_DIR / "newly_confirmed.csv"
LOG_FILE = BASE_DIR / "confirmation_scraper.log"

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_MAP_URL = "https://api.firecrawl.dev/v1/map"
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"
FIRECRAWL_EXTRACT_URL = "https://api.firecrawl.dev/v1/extract"

REQUEST_DELAY = 0.3
SAVE_INTERVAL = 20

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
                website = website.rstrip("/")
                if not website.startswith("http"):
                    website = "https://" + website
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


# --- Firecrawl APIs ---

def firecrawl_map(base_url: str) -> list[str]:
    """Find calendar-related pages on a district website."""
    payload = {
        "url": base_url,
        "search": "school calendar 2025-2026 academic calendar spring break",
        "limit": 10,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        FIRECRAWL_MAP_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        result = json.loads(resp.read())
        return result.get("links", [])
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(10)
        return []
    except Exception:
        return []


def firecrawl_scrape(url: str) -> str:
    """Scrape a URL and return markdown content."""
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
        resp = urllib.request.urlopen(req, timeout=25)
        result = json.loads(resp.read())
        if result.get("success"):
            return result.get("data", {}).get("markdown", "")
        return ""
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(10)
        return ""
    except Exception:
        return ""


def firecrawl_extract_async(url: str) -> dict | None:
    """Use Extract API (async) as a fallback for high-value districts."""
    payload = {
        "urls": [url],
        "prompt": (
            "Extract the school calendar dates for the 2025-2026 school year. "
            "I need: first day of school, last day of school, spring break start and end dates, "
            "and winter/Christmas break start and end dates. Return dates in YYYY-MM-DD format."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "first_day_of_school": {"type": "string"},
                "last_day_of_school": {"type": "string"},
                "spring_break_start": {"type": "string"},
                "spring_break_end": {"type": "string"},
                "winter_break_start": {"type": "string"},
                "winter_break_end": {"type": "string"},
            },
        },
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
            job_id = result["id"]
            # Poll for result
            for _ in range(24):
                time.sleep(5)
                poll_req = urllib.request.Request(
                    f"{FIRECRAWL_EXTRACT_URL}/{job_id}",
                    headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}"},
                )
                poll_resp = urllib.request.urlopen(poll_req, timeout=20)
                poll_result = json.loads(poll_resp.read())
                if poll_result.get("status") == "completed":
                    return poll_result.get("data", {})
                elif poll_result.get("status") == "failed":
                    return None
            return None
    except Exception:
        return None


# --- Link Selection ---

def select_best_calendar_link(links: list[str], base_url: str) -> list[str]:
    """Select the best calendar links from map results, prioritized."""
    scored = []
    for link in links:
        link_lower = link.lower()
        score = 0
        
        # Prefer 2025-2026 content
        if '2025-2026' in link_lower or '2025-26' in link_lower or '25-26' in link_lower:
            score += 20
        if '2026-2027' in link_lower or '2026-27' in link_lower or '26-27' in link_lower:
            score -= 10  # Wrong year
        if '2024-2025' in link_lower or '2024-25' in link_lower or '24-25' in link_lower:
            score -= 10  # Wrong year
        
        # Prefer calendar pages
        if 'calendar' in link_lower:
            score += 10
        if 'academic' in link_lower:
            score += 5
        if 'school-calendar' in link_lower or 'academiccalendar' in link_lower:
            score += 8
        
        # Prefer HTML over PDFs slightly (easier to parse, but PDFs work too)
        if link_lower.endswith('.pdf'):
            score += 3  # PDFs often have the complete calendar
        
        # Penalize non-calendar pages
        if any(w in link_lower for w in ['events', 'announcements', 'news', 'blog', 'staff', 'employment']):
            score -= 5
        
        # Prefer same domain
        base_domain = base_url.split("//")[-1].split("/")[0].replace("www.", "")
        link_domain = link.split("//")[-1].split("/")[0].replace("www.", "")
        if base_domain in link_domain:
            score += 3
        
        # Prefer shorter paths (more likely to be main calendar page)
        path_parts = link.split("//")[-1].split("/")
        if len(path_parts) <= 4:
            score += 2
        
        scored.append((score, link))
    
    scored.sort(key=lambda x: -x[0])
    return [link for _, link in scored[:3]]


# --- Date Parsing ---

def parse_month_day(month_str: str, day_str: str) -> date | None:
    """Parse month name + day into a date for the 2025-2026 school year."""
    month_str = month_str.lower().strip().rstrip('.')
    month = MONTHS.get(month_str)
    if not month:
        return None
    try:
        day = int(re.search(r'\d+', day_str).group())
    except (ValueError, TypeError, AttributeError):
        return None
    if not (1 <= day <= 31):
        return None
    year = 2025 if month >= 7 else 2026
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_dates(md: str) -> dict:
    """Extract school calendar dates from markdown content."""
    result = {}
    
    # --- Detect school year context ---
    # If content mentions 2026-2027 prominently and not 2025-2026, skip
    has_2526 = bool(re.search(r'2025\s*[-–]\s*(?:20)?26', md))
    has_2627 = bool(re.search(r'2026\s*[-–]\s*(?:20)?27', md))
    if has_2627 and not has_2526:
        return {}  # Wrong year
    
    # --- Track current month context for section-based parsing ---
    current_month = None
    
    for line in md.split('\n'):
        line_stripped = line.strip()
        line_lower = line_stripped.lower()
        
        # Detect month headers: "August 2025", "## March 2026", "| March 2026 |"
        month_header = re.search(
            r'(?:^|\|)\s*#*\s*(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})\s*(?:\||\s*$)',
            line_lower
        )
        if month_header:
            m_name = month_header.group(1)
            m_year = int(month_header.group(2))
            if m_name in MONTHS and m_year in (2025, 2026):
                current_month = (MONTHS[m_name], m_year)
            continue
        
        # --- Table format: "| Day | Event |" or "| Month Day | Event |" ---
        # Pattern: "| August 13 | First Day of School |"
        table_match = re.search(
            r'\|\s*(\w+)\s+(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s*\|([^|]+)',
            line_stripped
        )
        if table_match:
            month_str = table_match.group(1)
            day1 = table_match.group(2)
            day2 = table_match.group(3)
            event = table_match.group(4).lower()
            
            d1 = parse_month_day(month_str, day1)
            if d1:
                _process_event(d1, day2, month_str, event, result)
                continue
        
        # Pattern: "| Day(DayOfWeek) | Event |" when in month context
        if current_month:
            ctx_match = re.search(r'\|\s*(\d{1,2})\s*(?:\([A-Za-z]+\))?\s*\|([^|]+)', line_stripped)
            if ctx_match:
                day_str = ctx_match.group(1)
                event = ctx_match.group(2).lower()
                try:
                    d1 = date(current_month[1], current_month[0], int(day_str))
                    _process_event(d1, None, None, event, result)
                    continue
                except ValueError:
                    pass
        
        # --- Text patterns ---
        # "Aug 11 First Day" / "First Day of School August 11"
        _extract_first_day(line_stripped, result)
        _extract_last_day(line_stripped, result)
        _extract_spring_break(line_stripped, result)
        _extract_winter_break(line_stripped, result)
        
        # --- Section-based: "20 First day of School" in a month section ---
        if current_month and not table_match:
            day_event = re.search(r'^\s*(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s+(.+)', line_stripped)
            if day_event:
                day1 = day_event.group(1)
                day2 = day_event.group(2)
                event = day_event.group(3).lower()
                try:
                    d1 = date(current_month[1], current_month[0], int(day1))
                    _process_event(d1, day2, None, event, result)
                except ValueError:
                    pass
    
    # Derive summer dates
    if 'first_day' in result and 'last_day' in result:
        result['summer_start'] = result['last_day']
        result['summer_end'] = result['first_day']
    
    return result


def _process_event(d1: date, day2_str: str | None, month_str: str | None, event: str, result: dict):
    """Process a calendar event line to extract dates."""
    event = re.sub(r'[*_\\]', '', event).strip().lower()
    
    # First day of school
    if any(p in event for p in ['first day of school', 'first day for students',
                                 'school begins', 'classes begin', 'students return',
                                 'first day of class', 'first day  school']):
        if date(2025, 7, 1) <= d1 <= date(2025, 9, 30) and 'first_day' not in result:
            result['first_day'] = d1.isoformat()
    
    # Last day of school
    if any(p in event for p in ['last day of school', 'last day for students', 
                                 'last day of class', 'end of school year',
                                 'school ends', 'last student day']):
        if date(2026, 5, 1) <= d1 <= date(2026, 7, 15) and 'last_day' not in result:
            result['last_day'] = d1.isoformat()
    
    # Spring break
    if any(p in event for p in ['spring break', 'spring holiday', 'spring recess']):
        if date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
            if 'spring_break_start' not in result:
                result['spring_break_start'] = d1.isoformat()
                if day2_str and month_str:
                    d2 = parse_month_day(month_str, day2_str)
                    if d2:
                        result['spring_break_end'] = d2.isoformat()
                elif day2_str:
                    try:
                        d2 = date(d1.year, d1.month, int(day2_str))
                        result['spring_break_end'] = d2.isoformat()
                    except ValueError:
                        pass
                if 'spring_break_end' not in result:
                    result['spring_break_end'] = d1.isoformat()
            elif d1.isoformat() > result.get('spring_break_end', ''):
                # Extend spring break end
                result['spring_break_end'] = d1.isoformat()
    
    # Winter/Christmas break
    if any(p in event for p in ['winter break', 'christmas break', 'christmas holiday',
                                 'winter holiday', 'winter recess', 'holiday break']):
        if d1.month in (11, 12) and d1.year == 2025:
            if 'winter_break_start' not in result:
                result['winter_break_start'] = d1.isoformat()
                if day2_str:
                    try:
                        d2 = date(d1.year, d1.month, int(day2_str))
                        result['winter_break_end'] = d2.isoformat()
                    except ValueError:
                        pass
        elif d1.month == 1 and d1.year == 2026:
            result['winter_break_end'] = d1.isoformat()
            if day2_str:
                try:
                    d2 = date(2026, 1, int(day2_str))
                    result['winter_break_end'] = d2.isoformat()
                except ValueError:
                    pass


def _extract_first_day(line: str, result: dict):
    """Extract first day of school from free text."""
    if 'first_day' in result:
        return
    patterns = [
        r'first\s+day\s+(?:of\s+)?(?:school|class)[:\s]*(\w+)\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})[,\s]*[-–|]*[*\s]*first\s+day\s+(?:of\s+)?(?:school|class)',
        r'school\s+(?:starts|begins)[:\s]*(\w+)\s+(\d{1,2})',
        r'classes\s+begin[:\s]*(\w+)\s+(\d{1,2})',
        r'students\s+(?:return|report|first day)[:\s]*(\w+)\s+(\d{1,2})',
    ]
    for pat in patterns:
        m = re.search(pat, line, re.I)
        if m:
            d = parse_month_day(m.group(1), m.group(2))
            if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
                result['first_day'] = d.isoformat()
                return


def _extract_last_day(line: str, result: dict):
    """Extract last day of school from free text."""
    if 'last_day' in result:
        return
    patterns = [
        r'last\s+day\s+(?:of\s+)?(?:school|class)[:\s]*(\w+)\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})[,\s]*[-–|]*[*\s]*last\s+day\s+(?:of\s+)?(?:school|class)',
    ]
    for pat in patterns:
        m = re.search(pat, line, re.I)
        if m:
            d = parse_month_day(m.group(1), m.group(2))
            if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
                result['last_day'] = d.isoformat()
                return


def _extract_spring_break(line: str, result: dict):
    """Extract spring break from free text."""
    if 'spring_break_start' in result:
        return
    patterns = [
        # "Spring Break: March 16-20" / "March 16-20 Spring Break"
        r'spring\s+break[:\s]*(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})',
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\s*[|\s]*[*]*(?:no school)?[*\s]*spring\s+break',
        # "Mar 8-12 Spring Break"
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\s+spring\s+break',
        # "Spring Break March 16 - March 20"
        r'spring\s+break[:\s]*(\w+)\s+(\d{1,2})\s*[-–through]+\s*\w+\s+(\d{1,2})',
        # "3-10 Spring Break" in month context
        r'(\d{1,2})\s*[-–]\s*(\d{1,2})\s+spring\s+break',
    ]
    for pat in patterns:
        m = re.search(pat, line, re.I)
        if m:
            groups = m.groups()
            if len(groups) == 3 and groups[0].isalpha():
                d1 = parse_month_day(groups[0], groups[1])
                d2 = parse_month_day(groups[0], groups[2])
            elif len(groups) == 3 and groups[0].isdigit():
                # No month name — would need context
                continue
            elif len(groups) == 2:
                continue
            else:
                continue
            if d1 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                result['spring_break_start'] = d1.isoformat()
                result['spring_break_end'] = (d2 or d1).isoformat()
                return


def _extract_winter_break(line: str, result: dict):
    """Extract winter break from free text."""
    if 'winter_break_start' in result:
        return
    patterns = [
        r'(?:winter|christmas)\s+(?:break|holiday)[:\s]*(\w+)\s+(\d{1,2})\s*[-–]\s*(\w+)\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\w+)\s+(\d{1,2})\s*[|\s]*[*]*(?:no school)?[*\s]*(?:winter|christmas)\s+(?:break|holiday)',
        r'(?:winter|christmas)\s+(?:break|holiday)[:\s]*(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})',
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\s+(?:winter|christmas)\s+(?:break|holiday)',
    ]
    for pat in patterns:
        m = re.search(pat, line, re.I)
        if m:
            groups = m.groups()
            if len(groups) == 4:
                d1 = parse_month_day(groups[0], groups[1])
                d2 = parse_month_day(groups[2], groups[3])
            elif len(groups) == 3:
                d1 = parse_month_day(groups[0], groups[1])
                d2 = parse_month_day(groups[0], groups[2])
            else:
                continue
            if d1 and d1.month in (11, 12):
                result['winter_break_start'] = d1.isoformat()
                if d2:
                    result['winter_break_end'] = d2.isoformat()
                return


# --- Validation ---

def validate(data: dict) -> dict | None:
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
            dur = (sb_end - sb_start).days
            if not (0 <= dur <= 21 and date(2026, 2, 1) <= sb_start <= date(2026, 5, 31)):
                data.pop('spring_break_start', None)
                data.pop('spring_break_end', None)
                has_spring = False
        except ValueError:
            data.pop('spring_break_start', None)
            data.pop('spring_break_end', None)
            has_spring = False
    
    # Validate first/last day
    if has_year:
        try:
            first = date.fromisoformat(data['first_day'])
            last = date.fromisoformat(data['last_day'])
            cal_days = (last - first).days
            if not (240 <= cal_days <= 330):
                data.pop('first_day', None)
                data.pop('last_day', None)
                data.pop('summer_start', None)
                data.pop('summer_end', None)
                has_year = False
        except ValueError:
            data.pop('first_day', None)
            data.pop('last_day', None)
            has_year = False
    
    if not has_spring and not has_year:
        return None
    
    return data


# --- Main Processing ---

def get_uncovered(districts: list[dict], nces_websites: dict, min_enrollment: int) -> list[dict]:
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


def process_district(district: dict, use_extract_fallback: bool = False) -> tuple[dict | None, str, int]:
    """Process a single district. Returns (dates, source_url, credits)."""
    base_url = district["website"]
    credits = 0
    
    # Step 1: Map to find calendar pages
    links = firecrawl_map(base_url)
    credits += 1
    time.sleep(REQUEST_DELAY)
    
    if not links:
        return None, "", credits
    
    # Step 2: Select best links
    best_links = select_best_calendar_link(links, base_url)
    
    # Step 3: Scrape and parse
    for url in best_links:
        md = firecrawl_scrape(url)
        credits += 1
        time.sleep(REQUEST_DELAY)
        
        if not md or len(md) < 50:
            continue
        
        dates = extract_dates(md)
        validated = validate(dates)
        
        if validated:
            return validated, url, credits
    
    # Step 4: Extract API fallback for high-value districts
    if use_extract_fallback and district["enrollment"] >= 20000:
        log(f"    Trying Extract API fallback...")
        extract_data = firecrawl_extract_async(base_url)
        credits += 23
        if extract_data:
            # Map extract API fields to our format
            mapped = {}
            fd = extract_data.get("first_day_of_school", "")
            ld = extract_data.get("last_day_of_school", "")
            sb_s = extract_data.get("spring_break_start", "")
            sb_e = extract_data.get("spring_break_end", "")
            wb_s = extract_data.get("winter_break_start", "")
            wb_e = extract_data.get("winter_break_end", "")
            if fd:
                mapped['first_day'] = fd
            if ld:
                mapped['last_day'] = ld
            if sb_s:
                mapped['spring_break_start'] = sb_s
            if sb_e:
                mapped['spring_break_end'] = sb_e
            if wb_s:
                mapped['winter_break_start'] = wb_s
            if wb_e:
                mapped['winter_break_end'] = wb_e
            if 'first_day' in mapped and 'last_day' in mapped:
                mapped['summer_start'] = mapped['last_day']
                mapped['summer_end'] = mapped['first_day']
            validated = validate(mapped)
            if validated:
                return validated, base_url, credits
    
    return None, "", credits


def run_batch(limit: int = 0, min_enrollment: int = 0, resume: bool = True,
              dry_run: bool = False, use_extract: bool = False):
    log("=" * 70)
    log("Confirmation Scraper — Map + Scrape + Parse")
    log("=" * 70)
    
    if not FIRECRAWL_API_KEY and not dry_run:
        log("ERROR: Set FIRECRAWL_API_KEY")
        sys.exit(1)
    
    # Load data
    log("Loading data...")
    districts = load_comprehensive()
    nces_websites = load_nces_websites()
    results = load_results() if resume else {"confirmed": {}, "failed": {}, "credits_used": 0}
    
    already_done = set(results["confirmed"].keys()) | set(results["failed"].keys())
    log(f"Already processed: {len(already_done)} ({len(results['confirmed'])} confirmed, {len(results['failed'])} failed)")
    
    uncovered = get_uncovered(districts, nces_websites, min_enrollment)
    uncovered = [d for d in uncovered if d["leaid"] not in already_done]
    
    log(f"To process: {len(uncovered)} districts (min enrollment: {min_enrollment:,})")
    
    if limit:
        uncovered = uncovered[:limit]
        log(f"Limited to {len(uncovered)}")
    
    if not uncovered:
        log("Nothing to process!")
        return results
    
    total_enrollment = sum(d["enrollment"] for d in uncovered)
    log(f"Enrollment in batch: {total_enrollment:,}")
    
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
        log(f"[{i+1}/{len(uncovered)}] {d['name']} ({d['state']}) — {d['enrollment']:,}")
        
        dates, source_url, credits = process_district(d, use_extract_fallback=use_extract)
        total_credits += credits
        
        if dates:
            confirmed_count += 1
            results["confirmed"][leaid] = {
                "name": d["name"], "state": d["state"], "enrollment": d["enrollment"],
                "dates": dates, "source_url": source_url,
                "timestamp": datetime.now().isoformat(),
            }
            sb = dates.get("spring_break_start", "N/A")
            fd = dates.get("first_day", "N/A")
            log(f"  ✅ spring={sb}, first={fd} [{source_url}]")
        else:
            failed_count += 1
            results["failed"][leaid] = {
                "name": d["name"], "state": d["state"], "enrollment": d["enrollment"],
                "website": d["website"],
                "timestamp": datetime.now().isoformat(),
            }
            log(f"  ❌ No dates found")
        
        results["credits_used"] = total_credits
        
        if (confirmed_count + failed_count) % SAVE_INTERVAL == 0:
            save_results(results)
            total = confirmed_count + failed_count
            rate = confirmed_count / total * 100 if total else 0
            conf_enroll = sum(r["enrollment"] for r in results["confirmed"].values())
            log(f"  --- Save: {confirmed_count}✅ {failed_count}❌ ({rate:.0f}%) | {total_credits} credits | {conf_enroll:,} enrollment ---")
    
    # Final save
    results["credits_used"] = total_credits
    results["stats"] = {
        "batch_size": len(uncovered),
        "min_enrollment": min_enrollment,
        "confirmed": confirmed_count,
        "failed": failed_count,
        "success_rate": confirmed_count / max(1, confirmed_count + failed_count) * 100,
        "credits_used": total_credits,
        "confirmed_enrollment": sum(r["enrollment"] for r in results["confirmed"].values()),
        "completed_at": datetime.now().isoformat(),
    }
    save_results(results)
    write_csv(results)
    
    log("\n" + "=" * 70)
    log("BATCH COMPLETE")
    conf_e = sum(r["enrollment"] for r in results["confirmed"].values())
    log(f"  Confirmed: {len(results['confirmed'])} districts ({conf_e:,} enrollment)")
    log(f"  Failed: {len(results['failed'])}")
    log(f"  Rate: {results['stats']['success_rate']:.1f}%")
    log(f"  Credits: {total_credits:,}")
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
    with open(CONFIRMED_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log(f"Wrote {len(rows)} to {CONFIRMED_CSV}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-enrollment", type=int, default=0)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--use-extract", action="store_true", help="Use Extract API fallback for failures >20K enrollment")
    args = parser.parse_args()
    
    run_batch(
        limit=args.limit,
        min_enrollment=args.min_enrollment,
        resume=args.resume,
        dry_run=args.dry_run,
        use_extract=args.use_extract,
    )


if __name__ == "__main__":
    main()
