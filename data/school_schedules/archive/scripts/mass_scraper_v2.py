#!/usr/bin/env python3
"""Mass School Calendar Scraper v2 — Practical multi-strategy approach.

Strategies (in order):
1. Brave Search description extraction — fast, free (1 API call per district)
2. Web fetch from schoolcalendarguide.com — predictable URLs, good structured data
3. Web fetch from search results — follow top links
4. Firecrawl for JS-heavy sites — costs 1 credit per page

Key optimization: enhanced date parsing that handles more formats.
"""

from __future__ import annotations
import csv
import json
import os
import re
import sys
import time
import traceback
import urllib.request
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path
from collections import defaultdict, Counter

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
from confirmation_scraper import MONTHS, parse_month_day

# --- Configuration ---
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
NCES_ALL_FILE = BASE_DIR / "nces_all_districts.csv"
RESULTS_FILE = BASE_DIR / "mass_scraper_v2_results.json"
LOG_FILE = BASE_DIR / "mass_scraper_v2.log"

BRAVE_API_KEY = ""
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"

BRAVE_DELAY = 1.15
FETCH_DELAY = 0.3
SAVE_INTERVAL = 50

STATE_NAMES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
    'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia',
    'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
    'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri',
    'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire', 'NJ': 'New Jersey',
    'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio',
    'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont',
    'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
    'DC': 'District of Columbia',
}

TERRITORIES = {'AS', 'GU', 'PR', 'VI', 'MP'}


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# =============================================
# Enhanced Date Extraction (handles more formats)
# =============================================

def enhanced_extract_dates(text: str) -> dict:
    """Extract school calendar dates from text — handles many formats."""
    result = {}
    
    # Check school year context
    has_2526 = bool(re.search(r'2025\s*[-–]\s*(?:20)?26', text))
    has_2627 = bool(re.search(r'2026\s*[-–]\s*(?:20)?27', text))
    if has_2627 and not has_2526:
        return {}
    
    # Day-of-week abbreviations to strip
    DOW = r'(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s*)?'
    
    # Month pattern
    MONTH_PAT = r'(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)'
    
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        line_lower = line.lower()
        
        # ======= FIRST DAY OF SCHOOL =======
        if 'first_day' not in result:
            if any(p in line_lower for p in ['first day of school', 'first day for students',
                                               'school begins', 'classes begin', 'students return',
                                               'first day of class', 'first student day',
                                               'students first day', 'school starts']):
                # Try: DayOfWeek, Month Day Year
                m = re.search(DOW + MONTH_PAT + r'\s+(\d{1,2}),?\s*(\d{4})', line, re.I)
                if m:
                    d = _make_date(m.group(1), m.group(2), int(m.group(3)))
                    if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
                        result['first_day'] = d.isoformat()
                else:
                    # Try: Month Day (no year)
                    m = re.search(MONTH_PAT + r'\.?\s+(\d{1,2})', line, re.I)
                    if m:
                        d = parse_month_day(m.group(1), m.group(2))
                        if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
                            result['first_day'] = d.isoformat()
                    else:
                        # Try: Month/Day/Year numeric
                        m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', line)
                        if m:
                            d = _make_numeric_date(m.group(1), m.group(2), m.group(3))
                            if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
                                result['first_day'] = d.isoformat()
        
        # ======= LAST DAY OF SCHOOL =======
        if 'last_day' not in result:
            if any(p in line_lower for p in ['last day of school', 'last day for students',
                                               'last day of class', 'end of school year',
                                               'school ends', 'last student day', 'students last day']):
                m = re.search(DOW + MONTH_PAT + r'\s+(\d{1,2}),?\s*(\d{4})', line, re.I)
                if m:
                    d = _make_date(m.group(1), m.group(2), int(m.group(3)))
                    if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
                        result['last_day'] = d.isoformat()
                else:
                    m = re.search(MONTH_PAT + r'\.?\s+(\d{1,2})', line, re.I)
                    if m:
                        d = parse_month_day(m.group(1), m.group(2))
                        if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
                            result['last_day'] = d.isoformat()
                    else:
                        m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', line)
                        if m:
                            d = _make_numeric_date(m.group(1), m.group(2), m.group(3))
                            if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
                                result['last_day'] = d.isoformat()
        
        # ======= SPRING BREAK =======
        if 'spring_break_start' not in result:
            if any(p in line_lower for p in ['spring break', 'spring holiday', 'spring recess']):
                # Two dates: Mon, Mar 16 to Mon, Mar 23 2026
                m = re.search(
                    DOW + MONTH_PAT + r'\s+(\d{1,2})\s*(?:,\s*\d{4})?\s*(?:to|-|–|through)\s*' +
                    DOW + MONTH_PAT + r'\s+(\d{1,2})\s*(?:,?\s*(\d{4}))?',
                    line, re.I
                )
                if m:
                    d1 = parse_month_day(m.group(1), m.group(2))
                    d2 = parse_month_day(m.group(3), m.group(4))
                    if d1 and d2 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                        result['spring_break_start'] = d1.isoformat()
                        result['spring_break_end'] = d2.isoformat()
                else:
                    # Same month: March 16-20 or Mar 16 - 20
                    m = re.search(MONTH_PAT + r'\.?\s+(\d{1,2})\s*[-–to]+\s*(\d{1,2})', line, re.I)
                    if m:
                        d1 = parse_month_day(m.group(1), m.group(2))
                        d2 = parse_month_day(m.group(1), m.group(3))
                        if d1 and d2 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                            result['spring_break_start'] = d1.isoformat()
                            result['spring_break_end'] = d2.isoformat()
                    else:
                        # Single date
                        m = re.search(DOW + MONTH_PAT + r'\s+(\d{1,2})', line, re.I)
                        if m:
                            d1 = parse_month_day(m.group(1), m.group(2))
                            if d1 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                                result['spring_break_start'] = d1.isoformat()
                                result['spring_break_end'] = d1.isoformat()
                        else:
                            # Numeric: 3/16 - 3/20
                            m = re.search(r'(\d{1,2})/(\d{1,2})\s*[-–to]+\s*(\d{1,2})/(\d{1,2})', line)
                            if m:
                                d1 = _make_numeric_date(m.group(1), m.group(2), '2026')
                                d2 = _make_numeric_date(m.group(3), m.group(4), '2026')
                                if d1 and d2 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                                    result['spring_break_start'] = d1.isoformat()
                                    result['spring_break_end'] = d2.isoformat()
        
        # ======= WINTER/CHRISTMAS BREAK =======
        if 'winter_break_start' not in result:
            if any(p in line_lower for p in ['winter break', 'christmas break', 'christmas holiday',
                                               'winter holiday', 'winter recess', 'holiday break',
                                               'christmas/winter', 'winter/christmas']):
                # Two dates across months: Dec 22 to Jan 5
                m = re.search(
                    DOW + MONTH_PAT + r'\s+(\d{1,2})\s*(?:,\s*\d{4})?\s*(?:to|-|–|through)\s*' +
                    DOW + MONTH_PAT + r'\s+(\d{1,2})\s*(?:,?\s*(\d{4}))?',
                    line, re.I
                )
                if m:
                    d1 = parse_month_day(m.group(1), m.group(2))
                    d2 = parse_month_day(m.group(3), m.group(4))
                    if d1 and d1.month in (11, 12):
                        result['winter_break_start'] = d1.isoformat()
                        if d2:
                            result['winter_break_end'] = d2.isoformat()
                else:
                    # Same month: Dec 22-31
                    m = re.search(MONTH_PAT + r'\.?\s+(\d{1,2})\s*[-–to]+\s*(\d{1,2})', line, re.I)
                    if m:
                        d1 = parse_month_day(m.group(1), m.group(2))
                        d2 = parse_month_day(m.group(1), m.group(3))
                        if d1 and d1.month in (11, 12):
                            result['winter_break_start'] = d1.isoformat()
                            if d2:
                                result['winter_break_end'] = d2.isoformat()
    
    # Also run the original extract_dates as fallback for table/section-based formats
    from confirmation_scraper import extract_dates as orig_extract
    orig_result = orig_extract(text)
    
    # Merge: prefer our results, fill in from original
    for key in ['first_day', 'last_day', 'spring_break_start', 'spring_break_end',
                'winter_break_start', 'winter_break_end']:
        if key not in result and key in orig_result:
            result[key] = orig_result[key]
    
    # Derive summer dates
    if 'first_day' in result and 'last_day' in result:
        result['summer_start'] = result['last_day']
        result['summer_end'] = result['first_day']
    
    return result


def _make_date(month_str: str, day_str: str, year: int) -> date | None:
    """Make a date from month name, day string, year int."""
    month_str = month_str.lower().strip().rstrip('.')
    month = MONTHS.get(month_str)
    if not month:
        return None
    try:
        day = int(day_str)
    except (ValueError, TypeError):
        return None
    if not (1 <= day <= 31):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _make_numeric_date(m_str: str, d_str: str, y_str: str) -> date | None:
    """Make a date from numeric month/day/year strings."""
    try:
        month = int(m_str)
        day = int(d_str)
        year = int(y_str)
        if year < 100:
            year += 2000
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


def validate(data: dict) -> dict | None:
    """Validate extracted dates. Returns cleaned dict or None."""
    if not data:
        return None
    
    has_spring = 'spring_break_start' in data and 'spring_break_end' in data
    has_year = 'first_day' in data and 'last_day' in data
    
    if not has_spring and not has_year:
        return None
    
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


# =============================================
# API Functions
# =============================================

def brave_search(query: str, retries: int = 2) -> list[dict]:
    params = urllib.parse.urlencode({'q': query, 'count': 8})
    url = f"{BRAVE_SEARCH_URL}?{params}"
    req = urllib.request.Request(url, headers={
        'Accept': 'application/json',
        'X-Subscription-Token': BRAVE_API_KEY,
    })
    for attempt in range(retries + 1):
        try:
            resp = urllib.request.urlopen(req, timeout=12)
            data = json.loads(resp.read())
            results = []
            for r in data.get('web', {}).get('results', []):
                results.append({
                    'title': r.get('title', ''),
                    'url': r.get('url', ''),
                    'description': r.get('description', ''),
                })
            return results
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 15 * (attempt + 1)
                log(f"    Brave 429, waiting {wait}s...")
                time.sleep(wait)
            elif e.code == 403:
                log(f"    Brave 403 — daily limit reached")
                return []
            else:
                return []
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
    return []


def web_fetch_raw(url: str, max_bytes: int = 100000) -> str:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        content_type = resp.headers.get('Content-Type', '')
        if 'pdf' in content_type.lower():
            return ""
        raw = resp.read(max_bytes)
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('latin-1')
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.S)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.S)
        text = re.sub(r'<[^>]+>', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'&amp;', '&', text)
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'&lt;', '<', text)
        text = re.sub(r'&gt;', '>', text)
        text = re.sub(r'&#\d+;', '', text)
        return text.strip()
    except Exception:
        return ""


def firecrawl_scrape(url: str) -> str:
    if not FIRECRAWL_API_KEY:
        return ""
    payload = json.dumps({
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
        "timeout": 15000,
    }).encode()
    req = urllib.request.Request(
        FIRECRAWL_SCRAPE_URL,
        data=payload,
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
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(10)
    except Exception:
        pass
    return ""


# =============================================
# Description Extraction  
# =============================================

def extract_from_description(desc: str) -> dict:
    """Extract dates from Brave search result descriptions."""
    result = {}
    
    # Spring Break patterns
    sb_patterns = [
        # "Spring Break is from March 23-27, 2026"
        r'spring\s+break[^.]*?(\w+)\s+(\d{1,2})\s*[-–to]+\s*(\d{1,2})',
        # "Spring Break Mon, Mar 16 to Mon, Mar 23"
        r'spring\s+break[^.]*?(\w+)\s+(\d{1,2})[^.]*?to[^.]*?(\w+)\s+(\d{1,2})',
        # "March 16-20 Spring Break"
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})[^.]*?spring\s+break',
    ]
    for pat in sb_patterns:
        m = re.search(pat, desc, re.I)
        if m:
            g = m.groups()
            if len(g) == 3 and g[0].lower().rstrip('.') in MONTHS:
                d1 = parse_month_day(g[0], g[1])
                d2 = parse_month_day(g[0], g[2])
                if d1 and d2 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                    result['spring_break_start'] = d1.isoformat()
                    result['spring_break_end'] = d2.isoformat()
                    break
            elif len(g) == 4:
                d1 = parse_month_day(g[0], g[1])
                d2 = parse_month_day(g[2], g[3])
                if d1 and d2 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                    result['spring_break_start'] = d1.isoformat()
                    result['spring_break_end'] = d2.isoformat()
                    break
    
    # First day patterns
    fd_patterns = [
        r'first\s+day\s+(?:of\s+)?school[:\s]*(?:\w+,?\s+)?(\w+)\s+(\d{1,2})',
        r'school\s+(?:starts?|begins?)[:\s]*(?:\w+,?\s+)?(\w+)\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})[,\s]*(?:\d{4})?\s*[-–|]*\s*first\s+day',
    ]
    for pat in fd_patterns:
        m = re.search(pat, desc, re.I)
        if m:
            d = parse_month_day(m.group(1), m.group(2))
            if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
                result['first_day'] = d.isoformat()
                break
    
    # Last day patterns  
    ld_patterns = [
        r'last\s+day\s+(?:of\s+)?school[:\s]*(?:\w+,?\s+)?(\w+)\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})[,\s]*(?:\d{4})?\s*[-–|]*\s*last\s+day',
    ]
    for pat in ld_patterns:
        m = re.search(pat, desc, re.I)
        if m:
            d = parse_month_day(m.group(1), m.group(2))
            if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
                result['last_day'] = d.isoformat()
                break
    
    if 'first_day' in result and 'last_day' in result:
        result['summer_start'] = result['last_day']
        result['summer_end'] = result['first_day']
    
    return result


# =============================================
# URL Ranking
# =============================================

PRIORITY_DOMAINS = [
    'schoolcalendarguide.com', 'newschoolcalendar.com', 'schoolscalendar.com',
    'schoolcalendarinfo.com', 'educounty.net', 'texasschools.us',
]

def rank_urls(results: list[dict]) -> list[dict]:
    scored = []
    for r in results:
        url = r['url'].lower()
        desc = r.get('description', '').lower()
        title = r.get('title', '').lower()
        score = 0

        for domain in PRIORITY_DOMAINS:
            if domain in url:
                score += 30

        if '2025-2026' in url or '2025-26' in url:
            score += 15
        if 'calendar' in url:
            score += 10
        if 'calendar' in title:
            score += 8

        date_pat = r'(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}'
        date_matches = re.findall(date_pat, desc, re.I)
        score += len(date_matches) * 5

        if 'spring break' in desc:
            score += 10
        if 'first day' in desc:
            score += 8

        if url.endswith('.pdf'):
            score -= 15
        if '2024-2025' in url or '2023-2024' in url:
            score -= 20
        if any(w in url for w in ['employment', 'jobs', 'news', 'blog']):
            score -= 10

        scored.append((score, r))

    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored]


# =============================================
# Data Loading
# =============================================

def load_medium_districts() -> list[dict]:
    with open(COMPREHENSIVE_FILE, encoding="utf-8-sig") as f:
        districts = list(csv.DictReader(f))
    
    medium = []
    for d in districts:
        if d['confidence'] != 'medium':
            continue
        if d['state'] in TERRITORIES:
            continue
        enrollment = int(d.get('enrollment', 0) or 0)
        medium.append({
            'leaid': d['nces_leaid'],
            'name': d['district_name'],
            'state': d['state'],
            'city': d.get('city', ''),
            'enrollment': enrollment,
        })
    
    medium.sort(key=lambda x: -x['enrollment'])
    return medium


def load_results() -> dict:
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {
        "confirmed": {},
        "failed": {},
        "brave_daily_exhausted": False,
        "total_brave_calls": 0,
        "total_fetches": 0,
        "total_firecrawl_credits": 0,
    }


def save_results(results: dict):
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)


# =============================================
# Process Single District
# =============================================

def process_district(district: dict, results: dict) -> tuple[dict | None, str, str]:
    """
    Process one district. Returns (dates, source_url, method).
    """
    name = district['name']
    state = district['state']
    state_full = STATE_NAMES.get(state, state)
    
    clean_name = re.sub(r'\s*\(.*?\)', '', name)
    
    # --- Strategy 1: Brave Search ---
    if not results.get('brave_daily_exhausted'):
        query = f'{clean_name} {state_full} school calendar 2025-2026'
        search_results = brave_search(query)
        results['total_brave_calls'] = results.get('total_brave_calls', 0) + 1
        time.sleep(BRAVE_DELAY)
        
        if not search_results:
            # Check if Brave is exhausted
            if results.get('total_brave_calls', 0) > 50:
                # Try one more time with simpler query
                search_results = brave_search(f'{clean_name} {state} school calendar 2025-2026')
                results['total_brave_calls'] += 1
                time.sleep(BRAVE_DELAY)
                if not search_results:
                    results['brave_daily_exhausted'] = True
                    log("  ⚠️ Brave API appears exhausted")
        
        if search_results:
            # --- 1a: Extract from descriptions ---
            for sr in search_results:
                desc_dates = extract_from_description(sr.get('description', ''))
                validated = validate(desc_dates)
                if validated:
                    return validated, sr['url'], 'description'
            
            # Also try enhanced extraction on all descriptions
            all_text = '\n'.join(
                sr.get('description', '') + '\n' + sr.get('title', '')
                for sr in search_results
            )
            desc_dates = enhanced_extract_dates(all_text)
            validated = validate(desc_dates)
            if validated:
                return validated, search_results[0]['url'], 'description_enhanced'
            
            # --- 1b: Fetch top URLs ---
            ranked = rank_urls(search_results)
            
            for sr in ranked[:3]:
                url = sr['url']
                if url.lower().endswith('.pdf'):
                    continue
                
                # Try raw HTTP fetch
                content = web_fetch_raw(url)
                results['total_fetches'] = results.get('total_fetches', 0) + 1
                time.sleep(FETCH_DELAY)
                
                if content and len(content) > 300:
                    dates = enhanced_extract_dates(content)
                    validated = validate(dates)
                    if validated:
                        return validated, url, 'web_fetch'
                
                # Firecrawl fallback for empty/short content (JS-rendered)
                if (not content or len(content) < 300) and FIRECRAWL_API_KEY:
                    md = firecrawl_scrape(url)
                    results['total_firecrawl_credits'] = results.get('total_firecrawl_credits', 0) + 1
                    if md and len(md) > 200:
                        dates = enhanced_extract_dates(md)
                        validated = validate(dates)
                        if validated:
                            return validated, url, 'firecrawl'
    
    return None, '', 'all_failed'


# =============================================
# Merge Results into CSV
# =============================================

def merge_results_to_csv():
    """Merge all scraper results back into districts_comprehensive.csv."""
    log("Merging results into districts_comprehensive.csv...")
    
    # Collect all confirmed results from all scrapers
    all_confirmed = {}
    for rfile in ['mass_scraper_v2_results.json', 'confirmation_results.json', 'brave_scraper_results.json']:
        try:
            with open(BASE_DIR / rfile) as f:
                r = json.load(f)
            for leaid, data in r.get('confirmed', {}).items():
                if leaid not in all_confirmed:
                    all_confirmed[leaid] = data
        except:
            pass
    
    log(f"Total confirmed results to merge: {len(all_confirmed)}")
    
    # Load and update CSV
    with open(COMPREHENSIVE_FILE, encoding="utf-8-sig") as f:
        districts = list(csv.DictReader(f))
    
    fieldnames = list(districts[0].keys())
    updated = 0
    
    for d in districts:
        leaid = d['nces_leaid']
        if leaid in all_confirmed and d['confidence'] == 'medium':
            confirmed_data = all_confirmed[leaid]
            dates = confirmed_data.get('dates', {})
            
            if dates.get('spring_break_start'):
                d['spring_break_start'] = dates['spring_break_start']
            if dates.get('spring_break_end'):
                d['spring_break_end'] = dates['spring_break_end']
            if dates.get('winter_break_start'):
                d['winter_break_start'] = dates['winter_break_start']
            if dates.get('winter_break_end'):
                d['winter_break_end'] = dates['winter_break_end']
            if dates.get('first_day'):
                d['first_day'] = dates['first_day']
            if dates.get('last_day'):
                d['last_day'] = dates['last_day']
            if dates.get('summer_start'):
                d['summer_start'] = dates['summer_start']
            if dates.get('summer_end'):
                d['summer_end'] = dates['summer_end']
            
            method = confirmed_data.get('method', 'scraped')
            d['source'] = f'scraped_{method}'
            d['confidence'] = 'confirmed'
            updated += 1
    
    with open(COMPREHENSIVE_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(districts)
    
    log(f"Updated {updated} districts to confirmed")
    
    # Print final stats
    conf_count = sum(1 for d in districts if d['confidence'] == 'confirmed')
    med_count = sum(1 for d in districts if d['confidence'] == 'medium')
    log(f"Final: {conf_count} confirmed, {med_count} medium out of {len(districts)} total")
    log(f"Coverage: {conf_count/len(districts)*100:.1f}%")


# =============================================
# Main
# =============================================

def run(limit: int = 0, start_from: int = 0):
    log("=" * 80)
    log("MASS SCRAPER v2 — Processing medium-confidence districts")
    log("=" * 80)
    
    all_medium = load_medium_districts()
    results = load_results()
    
    already_done = set(results.get('confirmed', {}).keys()) | set(results.get('failed', {}).keys())
    
    # Also skip previously confirmed
    prev_confirmed = set()
    for rfile in ['confirmation_results.json', 'brave_scraper_results.json']:
        try:
            with open(BASE_DIR / rfile) as f:
                prev = json.load(f)
            prev_confirmed |= set(prev.get('confirmed', {}).keys())
        except:
            pass
    
    remaining = [d for d in all_medium if d['leaid'] not in already_done and d['leaid'] not in prev_confirmed]
    
    if start_from > 0:
        remaining = remaining[start_from:]
    if limit > 0:
        remaining = remaining[:limit]
    
    log(f"Total medium: {len(all_medium)}")
    log(f"Already done: {len(already_done)} (this scraper) + {len(prev_confirmed)} (prev scrapers)")
    log(f"Remaining to process: {len(remaining)}")
    log(f"Enrollment in remaining: {sum(d['enrollment'] for d in remaining):,}")
    
    if not remaining:
        log("Nothing to process!")
        return
    
    confirmed_count = 0
    failed_count = 0
    method_counts = defaultdict(int)
    start_time = time.time()
    
    for i, district in enumerate(remaining):
        leaid = district['leaid']
        
        if i % 100 == 0 and i > 0:
            elapsed = time.time() - start_time
            rate = i / elapsed * 3600
            eta_h = (len(remaining) - i) / rate if rate > 0 else 0
            total = confirmed_count + failed_count
            rate_pct = confirmed_count / total * 100 if total else 0
            log(f"\n--- Progress: {i}/{len(remaining)} ({i/len(remaining)*100:.1f}%) | "
                f"{confirmed_count}✅ {failed_count}❌ ({rate_pct:.0f}%) | "
                f"Rate: {rate:.0f}/hr | ETA: {eta_h:.1f}h ---\n")
        
        log(f"[{i+1}/{len(remaining)}] {district['name']} ({district['state']}) — {district['enrollment']:,}")
        
        try:
            dates, source_url, method = process_district(district, results)
        except Exception as e:
            log(f"  ERROR: {e}")
            traceback.print_exc()
            dates, source_url, method = None, '', f'error'
        
        if dates:
            confirmed_count += 1
            method_counts[method] += 1
            results['confirmed'][leaid] = {
                'name': district['name'],
                'state': district['state'],
                'city': district['city'],
                'enrollment': district['enrollment'],
                'dates': dates,
                'source_url': source_url,
                'method': method,
                'timestamp': datetime.now().isoformat(),
            }
            sb = dates.get('spring_break_start', 'N/A')
            fd = dates.get('first_day', 'N/A')
            log(f"  ✅ spring={sb}, first={fd} [{method}]")
        else:
            failed_count += 1
            method_counts[method] += 1
            results['failed'][leaid] = {
                'name': district['name'],
                'state': district['state'],
                'enrollment': district['enrollment'],
                'method': method,
                'timestamp': datetime.now().isoformat(),
            }
            log(f"  ❌ {method}")
        
        if (confirmed_count + failed_count) % SAVE_INTERVAL == 0:
            save_results(results)
            total = confirmed_count + failed_count
            rate_pct = confirmed_count / total * 100 if total else 0
            log(f"  --- SAVED: {confirmed_count}✅ {failed_count}❌ ({rate_pct:.0f}%) | "
                f"Brave: {results.get('total_brave_calls', 0)} | "
                f"FC: {results.get('total_firecrawl_credits', 0)} | "
                f"Methods: {dict(method_counts)} ---")
    
    # Final save
    save_results(results)
    
    elapsed = time.time() - start_time
    total = confirmed_count + failed_count
    rate_pct = confirmed_count / total * 100 if total else 0
    
    log("\n" + "=" * 80)
    log("MASS SCRAPER v2 COMPLETE")
    log(f"  Processed: {total}")
    log(f"  Confirmed: {confirmed_count} ({rate_pct:.1f}%)")
    log(f"  Failed: {failed_count}")
    log(f"  Methods: {dict(method_counts)}")
    log(f"  Brave calls: {results.get('total_brave_calls', 0)}")
    log(f"  Web fetches: {results.get('total_fetches', 0)}")
    log(f"  Firecrawl credits: {results.get('total_firecrawl_credits', 0)}")
    log(f"  Time: {elapsed/3600:.2f}h ({elapsed:.0f}s)")
    log("=" * 80)
    
    # Print cumulative stats
    total_confirmed_all = len(results.get('confirmed', {}))
    total_failed_all = len(results.get('failed', {}))
    log(f"\nCumulative: {total_confirmed_all} confirmed, {total_failed_all} failed")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start-from", type=int, default=0)
    parser.add_argument("--merge", action="store_true", help="Merge results into CSV")
    args = parser.parse_args()
    
    if args.merge:
        merge_results_to_csv()
    else:
        run(limit=args.limit, start_from=args.start_from)
