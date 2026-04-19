#!/usr/bin/env python3
"""Turbo School Calendar Scraper — Multi-threaded, multi-pass approach.

Pass 1: Brave Search descriptions only (fast, parallel-safe)
Pass 2: Web fetch top URLs from Pass 1 search results 
Pass 3: Firecrawl for JS-heavy sites (high-enrollment only)

Uses ThreadPoolExecutor for Brave searches (rate-limited to ~2/sec).
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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from collections import defaultdict, Counter

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
from confirmation_scraper import MONTHS, parse_month_day

# --- Configuration ---
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
RESULTS_FILE = BASE_DIR / "turbo_scraper_results.json"
LOG_FILE = BASE_DIR / "turbo_scraper.log"

BRAVE_API_KEY = ""
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"

SAVE_INTERVAL = 100

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

log_lock = threading.Lock()
results_lock = threading.Lock()


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with log_lock:
        print(line, flush=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")


# =============================================
# Date Extraction (comprehensive)
# =============================================

def enhanced_extract_dates(text: str) -> dict:
    """Extract school calendar dates from text."""
    result = {}
    
    has_2526 = bool(re.search(r'2025\s*[-–]\s*(?:20)?26', text))
    has_2627 = bool(re.search(r'2026\s*[-–]\s*(?:20)?27', text))
    if has_2627 and not has_2526:
        return {}
    
    DOW = r'(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s*)?'
    MONTH_PAT = r'(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)'
    
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        line_lower = line.lower()
        
        # FIRST DAY
        if 'first_day' not in result:
            if any(p in line_lower for p in ['first day of school', 'first day for students',
                                               'school begins', 'classes begin', 'students return',
                                               'first day of class', 'first student day',
                                               'students first day', 'school starts',
                                               'students report', 'student start']):
                m = re.search(DOW + MONTH_PAT + r'\.?\s+(\d{1,2}),?\s*(\d{4})', line, re.I)
                if m:
                    d = _make_date(m.group(1), m.group(2), int(m.group(3)))
                    if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
                        result['first_day'] = d.isoformat()
                if 'first_day' not in result:
                    m = re.search(DOW + MONTH_PAT + r'\.?\s+(\d{1,2})', line, re.I)
                    if m:
                        d = parse_month_day(m.group(1), m.group(2))
                        if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
                            result['first_day'] = d.isoformat()
                if 'first_day' not in result:
                    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', line)
                    if m:
                        d = _make_numeric_date(m.group(1), m.group(2), m.group(3))
                        if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
                            result['first_day'] = d.isoformat()
        
        # LAST DAY
        if 'last_day' not in result:
            if any(p in line_lower for p in ['last day of school', 'last day for students',
                                               'last day of class', 'end of school',
                                               'school ends', 'last student day',
                                               'students last day', 'last instructional']):
                m = re.search(DOW + MONTH_PAT + r'\.?\s+(\d{1,2}),?\s*(\d{4})', line, re.I)
                if m:
                    d = _make_date(m.group(1), m.group(2), int(m.group(3)))
                    if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
                        result['last_day'] = d.isoformat()
                if 'last_day' not in result:
                    m = re.search(DOW + MONTH_PAT + r'\.?\s+(\d{1,2})', line, re.I)
                    if m:
                        d = parse_month_day(m.group(1), m.group(2))
                        if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
                            result['last_day'] = d.isoformat()
                if 'last_day' not in result:
                    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', line)
                    if m:
                        d = _make_numeric_date(m.group(1), m.group(2), m.group(3))
                        if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
                            result['last_day'] = d.isoformat()
        
        # SPRING BREAK
        if 'spring_break_start' not in result:
            if any(p in line_lower for p in ['spring break', 'spring holiday', 'spring recess']):
                # Two date range: Month Day to Month Day
                m = re.search(
                    DOW + MONTH_PAT + r'\.?\s+(\d{1,2})\s*(?:,\s*\d{4})?\s*(?:to|-|–|through)\s*' +
                    DOW + MONTH_PAT + r'\.?\s+(\d{1,2})',
                    line, re.I
                )
                if m:
                    d1 = parse_month_day(m.group(1), m.group(2))
                    d2 = parse_month_day(m.group(3), m.group(4))
                    if d1 and d2 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                        result['spring_break_start'] = d1.isoformat()
                        result['spring_break_end'] = d2.isoformat()
                
                if 'spring_break_start' not in result:
                    m = re.search(MONTH_PAT + r'\.?\s+(\d{1,2})\s*[-–to]+\s*(\d{1,2})', line, re.I)
                    if m:
                        d1 = parse_month_day(m.group(1), m.group(2))
                        d2 = parse_month_day(m.group(1), m.group(3))
                        if d1 and d2 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                            result['spring_break_start'] = d1.isoformat()
                            result['spring_break_end'] = d2.isoformat()
                
                if 'spring_break_start' not in result:
                    # Numeric: 3/16/2026 - 3/20/2026  
                    m = re.search(r'(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\s*[-–to]+\s*(\d{1,2})/(\d{1,2})', line)
                    if m:
                        d1 = _make_numeric_date(m.group(1), m.group(2), '2026')
                        d2 = _make_numeric_date(m.group(3), m.group(4), '2026')
                        if d1 and d2 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                            result['spring_break_start'] = d1.isoformat()
                            result['spring_break_end'] = d2.isoformat()
                
                if 'spring_break_start' not in result:
                    # Single date
                    m = re.search(DOW + MONTH_PAT + r'\.?\s+(\d{1,2})', line, re.I)
                    if m:
                        d1 = parse_month_day(m.group(1), m.group(2))
                        if d1 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                            result['spring_break_start'] = d1.isoformat()
                            result['spring_break_end'] = d1.isoformat()
        
        # WINTER BREAK
        if 'winter_break_start' not in result:
            if any(p in line_lower for p in ['winter break', 'christmas break', 'christmas holiday',
                                               'winter holiday', 'winter recess', 'holiday break',
                                               'christmas/winter', 'winter/christmas']):
                m = re.search(
                    DOW + MONTH_PAT + r'\.?\s+(\d{1,2})\s*(?:,\s*\d{4})?\s*(?:to|-|–|through)\s*' +
                    DOW + MONTH_PAT + r'\.?\s+(\d{1,2})',
                    line, re.I
                )
                if m:
                    d1 = parse_month_day(m.group(1), m.group(2))
                    d2 = parse_month_day(m.group(3), m.group(4))
                    if d1 and d1.month in (11, 12):
                        result['winter_break_start'] = d1.isoformat()
                        if d2:
                            result['winter_break_end'] = d2.isoformat()
                
                if 'winter_break_start' not in result:
                    m = re.search(MONTH_PAT + r'\.?\s+(\d{1,2})\s*[-–to]+\s*(\d{1,2})', line, re.I)
                    if m:
                        d1 = parse_month_day(m.group(1), m.group(2))
                        d2 = parse_month_day(m.group(1), m.group(3))
                        if d1 and d1.month in (11, 12):
                            result['winter_break_start'] = d1.isoformat()
                            if d2:
                                result['winter_break_end'] = d2.isoformat()
    
    # Also run original extract_dates as fallback
    from confirmation_scraper import extract_dates as orig_extract
    orig_result = orig_extract(text)
    for key in ['first_day', 'last_day', 'spring_break_start', 'spring_break_end',
                'winter_break_start', 'winter_break_end']:
        if key not in result and key in orig_result:
            result[key] = orig_result[key]
    
    if 'first_day' in result and 'last_day' in result:
        result['summer_start'] = result['last_day']
        result['summer_end'] = result['first_day']
    
    return result


def _make_date(month_str: str, day_str: str, year: int) -> date | None:
    month_str = month_str.lower().strip().rstrip('.')
    month = MONTHS.get(month_str)
    if not month:
        return None
    try:
        return date(year, month, int(day_str))
    except (ValueError, TypeError):
        return None


def _make_numeric_date(m_str: str, d_str: str, y_str: str) -> date | None:
    try:
        month, day, year = int(m_str), int(d_str), int(y_str)
        if year < 100:
            year += 2000
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


def validate(data: dict) -> dict | None:
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
                for k in ['spring_break_start', 'spring_break_end']:
                    data.pop(k, None)
                has_spring = False
        except ValueError:
            for k in ['spring_break_start', 'spring_break_end']:
                data.pop(k, None)
            has_spring = False
    if has_year:
        try:
            first = date.fromisoformat(data['first_day'])
            last = date.fromisoformat(data['last_day'])
            if not (240 <= (last - first).days <= 330):
                for k in ['first_day', 'last_day', 'summer_start', 'summer_end']:
                    data.pop(k, None)
                has_year = False
        except ValueError:
            for k in ['first_day', 'last_day']:
                data.pop(k, None)
            has_year = False
    if not has_spring and not has_year:
        return None
    return data


# =============================================
# API Functions
# =============================================

brave_semaphore = threading.Semaphore(3)  # max 3 concurrent Brave requests

def brave_search(query: str) -> list[dict]:
    params = urllib.parse.urlencode({'q': query, 'count': 8})
    url = f"{BRAVE_SEARCH_URL}?{params}"
    req = urllib.request.Request(url, headers={
        'Accept': 'application/json',
        'X-Subscription-Token': BRAVE_API_KEY,
    })
    with brave_semaphore:
        for attempt in range(3):
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
                    time.sleep(5 * (attempt + 1))
                else:
                    return []
            except Exception:
                if attempt < 2:
                    time.sleep(1)
        return []


def web_fetch_raw(url: str, max_bytes: int = 80000) -> str:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=12)
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
        for entity, replacement in [('&amp;', '&'), ('&nbsp;', ' '), ('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"')]:
            text = text.replace(entity, replacement)
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
    except Exception:
        pass
    return ""


# =============================================
# Description Extraction
# =============================================

def extract_from_descriptions(search_results: list[dict]) -> dict:
    """Try to extract dates from search result descriptions and titles."""
    all_text = '\n'.join(
        r.get('description', '') + '\n' + r.get('title', '')
        for r in search_results
    )
    
    result = {}
    
    # Spring Break: various patterns
    sb_patterns = [
        r'spring\s+break[^.]*?(\w+)\s+(\d{1,2})\s*[-–to]+\s*(\d{1,2})',
        r'spring\s+break[^.]*?(\w+)\s+(\d{1,2})[^.]*?(?:to|-|–)\s*\w+\s*,?\s*(\w+)\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})[^.]*?spring\s+break',
    ]
    for pat in sb_patterns:
        m = re.search(pat, all_text, re.I)
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
    
    # First/Last day
    fd_pats = [
        r'first\s+day[:\s]+(?:\w+,?\s+)?(\w+)\s+(\d{1,2})',
        r'(?:school\s+(?:starts?|begins?))[:\s]+(?:\w+,?\s+)?(\w+)\s+(\d{1,2})',
    ]
    for pat in fd_pats:
        m = re.search(pat, all_text, re.I)
        if m:
            d = parse_month_day(m.group(1), m.group(2))
            if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
                result['first_day'] = d.isoformat()
                break
    
    ld_pats = [
        r'last\s+day[:\s]+(?:\w+,?\s+)?(\w+)\s+(\d{1,2})',
    ]
    for pat in ld_pats:
        m = re.search(pat, all_text, re.I)
        if m:
            d = parse_month_day(m.group(1), m.group(2))
            if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
                result['last_day'] = d.isoformat()
                break
    
    if 'first_day' in result and 'last_day' in result:
        result['summer_start'] = result['last_day']
        result['summer_end'] = result['first_day']
    
    # Also try enhanced extraction on all text
    enhanced = enhanced_extract_dates(all_text)
    for k in ['first_day', 'last_day', 'spring_break_start', 'spring_break_end',
              'winter_break_start', 'winter_break_end', 'summer_start', 'summer_end']:
        if k not in result and k in enhanced:
            result[k] = enhanced[k]
    
    return result


# =============================================
# URL Ranking
# =============================================

PRIORITY_DOMAINS = [
    'schoolcalendarguide.com', 'newschoolcalendar.com', 'schoolscalendar.com',
    'schoolcalendarinfo.com', 'schoolcalendarpoint.com', 'schoolcalendar.net',
]

def rank_urls(results: list[dict]) -> list[str]:
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
        score += len(re.findall(date_pat, desc, re.I)) * 5

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

        scored.append((score, r['url']))

    scored.sort(key=lambda x: -x[0])
    return [url for _, url in scored if _ > -10]


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
    return {"confirmed": {}, "failed": {}, "search_cache": {}, "stats": {}}


def save_results(results: dict):
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)


# =============================================
# Pass 1: Brave Search + Description Extraction
# =============================================

def pass1_search_and_descriptions(districts: list[dict], results: dict):
    """Brave search all districts, extract from descriptions."""
    log("=" * 70)
    log(f"PASS 1: Brave Search + Description Extraction ({len(districts)} districts)")
    log("=" * 70)
    
    confirmed = 0
    failed = 0
    start = time.time()
    
    for i, d in enumerate(districts):
        leaid = d['leaid']
        
        if leaid in results['confirmed'] or leaid in results.get('search_cache', {}):
            continue
        
        if i % 200 == 0 and i > 0:
            elapsed = time.time() - start
            rate = i / elapsed * 3600
            eta = (len(districts) - i) / (rate / 3600) if rate > 0 else 0
            c_total = len(results['confirmed'])
            log(f"  Pass 1 progress: {i}/{len(districts)} | "
                f"Confirmed so far: {c_total} | Rate: {rate:.0f}/hr | ETA: {eta/60:.0f}min")
        
        state_full = STATE_NAMES.get(d['state'], d['state'])
        clean_name = re.sub(r'\s*\(.*?\)', '', d['name'])
        query = f'{clean_name} {state_full} school calendar 2025-2026'
        
        search_results = brave_search(query)
        
        if not search_results:
            results.setdefault('search_cache', {})[leaid] = {'search_results': [], 'status': 'no_results'}
            failed += 1
            continue
        
        # Cache search results for Pass 2
        results.setdefault('search_cache', {})[leaid] = {
            'search_results': search_results,
            'status': 'searched',
        }
        
        # Try description extraction
        desc_dates = extract_from_descriptions(search_results)
        validated = validate(desc_dates)
        
        if validated:
            confirmed += 1
            results['confirmed'][leaid] = {
                'name': d['name'],
                'state': d['state'],
                'city': d['city'],
                'enrollment': d['enrollment'],
                'dates': validated,
                'source_url': search_results[0]['url'],
                'method': 'description',
                'pass': 1,
                'timestamp': datetime.now().isoformat(),
            }
            if confirmed % 50 == 0:
                log(f"  ✅ #{confirmed}: {d['name']} ({d['state']}) spring={validated.get('spring_break_start', 'N/A')}")
        else:
            failed += 1
        
        # Save periodically
        if (confirmed + failed) % SAVE_INTERVAL == 0:
            save_results(results)
    
    save_results(results)
    elapsed = time.time() - start
    log(f"Pass 1 done: {confirmed}✅ {failed}❌ in {elapsed/60:.1f}min")
    return confirmed


# =============================================
# Pass 2: Web Fetch from search results
# =============================================

def pass2_web_fetch(districts: list[dict], results: dict):
    """Fetch web pages for districts not confirmed in Pass 1."""
    remaining = [d for d in districts if d['leaid'] not in results['confirmed']]
    
    log("=" * 70)
    log(f"PASS 2: Web Fetch ({len(remaining)} districts)")
    log("=" * 70)
    
    confirmed = 0
    failed = 0
    start = time.time()
    
    for i, d in enumerate(remaining):
        leaid = d['leaid']
        
        if i % 200 == 0 and i > 0:
            elapsed = time.time() - start
            rate = i / elapsed * 3600
            c_total = len(results['confirmed'])
            log(f"  Pass 2 progress: {i}/{len(remaining)} | Total confirmed: {c_total} | Rate: {rate:.0f}/hr")
        
        # Get cached search results
        cache = results.get('search_cache', {}).get(leaid, {})
        search_results = cache.get('search_results', [])
        
        if not search_results:
            failed += 1
            continue
        
        # Rank and try top URLs
        urls = rank_urls(search_results)
        
        found = False
        for url in urls[:3]:
            if url.lower().endswith('.pdf'):
                continue
            
            content = web_fetch_raw(url)
            
            if content and len(content) > 300:
                dates = enhanced_extract_dates(content)
                validated = validate(dates)
                if validated:
                    confirmed += 1
                    results['confirmed'][leaid] = {
                        'name': d['name'],
                        'state': d['state'],
                        'city': d['city'],
                        'enrollment': d['enrollment'],
                        'dates': validated,
                        'source_url': url,
                        'method': 'web_fetch',
                        'pass': 2,
                        'timestamp': datetime.now().isoformat(),
                    }
                    if confirmed % 50 == 0:
                        log(f"  ✅ #{confirmed}: {d['name']} ({d['state']})")
                    found = True
                    break
            
            time.sleep(0.1)
        
        if not found:
            failed += 1
        
        if (confirmed + failed) % SAVE_INTERVAL == 0:
            save_results(results)
    
    save_results(results)
    elapsed = time.time() - start
    log(f"Pass 2 done: {confirmed}✅ {failed}❌ in {elapsed/60:.1f}min")
    return confirmed


# =============================================
# Pass 3: Firecrawl for high-enrollment failures
# =============================================

def pass3_firecrawl(districts: list[dict], results: dict, min_enrollment: int = 1000):
    """Use Firecrawl for remaining high-enrollment districts."""
    remaining = [d for d in districts 
                 if d['leaid'] not in results['confirmed']
                 and d['enrollment'] >= min_enrollment]
    
    log("=" * 70)
    log(f"PASS 3: Firecrawl ({len(remaining)} districts, enrollment >= {min_enrollment:,})")
    log("=" * 70)
    
    if not FIRECRAWL_API_KEY:
        log("No Firecrawl API key, skipping Pass 3")
        return 0
    
    confirmed = 0
    credits = 0
    start = time.time()
    
    for i, d in enumerate(remaining):
        leaid = d['leaid']
        
        if i % 50 == 0 and i > 0:
            c_total = len(results['confirmed'])
            log(f"  Pass 3 progress: {i}/{len(remaining)} | Total confirmed: {c_total} | Credits: {credits}")
        
        cache = results.get('search_cache', {}).get(leaid, {})
        search_results = cache.get('search_results', [])
        
        if not search_results:
            continue
        
        urls = rank_urls(search_results)
        
        found = False
        for url in urls[:2]:
            md = firecrawl_scrape(url)
            credits += 1
            
            if md and len(md) > 200:
                dates = enhanced_extract_dates(md)
                validated = validate(dates)
                if validated:
                    confirmed += 1
                    results['confirmed'][leaid] = {
                        'name': d['name'],
                        'state': d['state'],
                        'city': d['city'],
                        'enrollment': d['enrollment'],
                        'dates': validated,
                        'source_url': url,
                        'method': 'firecrawl',
                        'pass': 3,
                        'timestamp': datetime.now().isoformat(),
                    }
                    if confirmed % 20 == 0:
                        log(f"  ✅ #{confirmed}: {d['name']} ({d['state']})")
                    found = True
                    break
            
            time.sleep(0.3)
        
        if (confirmed + i) % 50 == 0:
            save_results(results)
    
    save_results(results)
    elapsed = time.time() - start
    log(f"Pass 3 done: {confirmed}✅ | Credits: {credits} | Time: {elapsed/60:.1f}min")
    return confirmed


# =============================================
# Merge into CSV
# =============================================

def merge_to_csv(results: dict):
    """Merge confirmed results into districts_comprehensive.csv."""
    log("Merging results into districts_comprehensive.csv...")
    
    confirmed = results.get('confirmed', {})
    
    # Also load other scraper results
    all_confirmed = dict(confirmed)
    for rfile in ['confirmation_results.json', 'brave_scraper_results.json', 'mass_scraper_v2_results.json']:
        try:
            with open(BASE_DIR / rfile) as f:
                r = json.load(f)
            for leaid, data in r.get('confirmed', {}).items():
                if leaid not in all_confirmed:
                    all_confirmed[leaid] = data
        except:
            pass
    
    with open(COMPREHENSIVE_FILE, encoding="utf-8-sig") as f:
        districts = list(csv.DictReader(f))
    
    fieldnames = list(districts[0].keys())
    updated = 0
    
    for d in districts:
        leaid = d['nces_leaid']
        if leaid in all_confirmed and d['confidence'] == 'medium':
            c = all_confirmed[leaid]
            dates = c.get('dates', {})
            for field in ['spring_break_start', 'spring_break_end', 'winter_break_start',
                         'winter_break_end', 'first_day', 'last_day', 'summer_start', 'summer_end']:
                if dates.get(field):
                    d[field] = dates[field]
            d['source'] = f"scraped_{c.get('method', 'unknown')}"
            d['confidence'] = 'confirmed'
            updated += 1
    
    with open(COMPREHENSIVE_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(districts)
    
    conf = sum(1 for d in districts if d['confidence'] == 'confirmed')
    med = sum(1 for d in districts if d['confidence'] == 'medium')
    log(f"Merged {updated} districts. Now: {conf} confirmed, {med} medium ({conf/len(districts)*100:.1f}% coverage)")


# =============================================
# Main
# =============================================

def run(skip_pass1: bool = False, skip_pass2: bool = False, skip_pass3: bool = False,
        pass3_min_enrollment: int = 1000, limit: int = 0):
    log("=" * 80)
    log("TURBO SCRAPER — All passes")
    log("=" * 80)
    
    all_medium = load_medium_districts()
    results = load_results()
    
    # Skip already confirmed in previous scrapers
    prev_confirmed = set()
    for rfile in ['confirmation_results.json', 'brave_scraper_results.json']:
        try:
            with open(BASE_DIR / rfile) as f:
                prev = json.load(f)
            prev_confirmed |= set(prev.get('confirmed', {}).keys())
        except:
            pass
    
    districts = [d for d in all_medium if d['leaid'] not in prev_confirmed]
    
    if limit:
        districts = districts[:limit]
    
    log(f"Total medium: {len(all_medium)}")
    log(f"Skip (prev confirmed): {len(prev_confirmed)}")
    log(f"To process: {len(districts)}")
    log(f"Already confirmed (this run): {len(results.get('confirmed', {}))}")
    
    if not skip_pass1:
        pass1_search_and_descriptions(districts, results)
    
    if not skip_pass2:
        pass2_web_fetch(districts, results)
    
    if not skip_pass3:
        pass3_firecrawl(districts, results, min_enrollment=pass3_min_enrollment)
    
    # Final stats
    total_confirmed = len(results.get('confirmed', {}))
    pass_stats = defaultdict(int)
    for c in results.get('confirmed', {}).values():
        pass_stats[c.get('pass', '?')] += 1
    
    log("\n" + "=" * 80)
    log("TURBO SCRAPER — FINAL REPORT")
    log(f"  Total confirmed (this run): {total_confirmed}")
    log(f"  By pass: {dict(pass_stats)}")
    log(f"  Still unconfirmed: {len(districts) - total_confirmed}")
    log("=" * 80)
    
    # Merge
    merge_to_csv(results)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-pass1", action="store_true")
    parser.add_argument("--skip-pass2", action="store_true")
    parser.add_argument("--skip-pass3", action="store_true")
    parser.add_argument("--pass3-min-enrollment", type=int, default=1000)
    parser.add_argument("--merge-only", action="store_true")
    args = parser.parse_args()
    
    if args.merge_only:
        results = load_results()
        merge_to_csv(results)
    else:
        run(
            skip_pass1=args.skip_pass1,
            skip_pass2=args.skip_pass2,
            skip_pass3=args.skip_pass3,
            pass3_min_enrollment=args.pass3_min_enrollment,
            limit=args.limit,
        )
