#!/usr/bin/env python3
"""Mass School Calendar Scraper — Process all 7,278 medium-confidence districts.

Multi-pass approach:
  Pass 0: State education department calendars (bulk state-level data)
  Pass 1: Brave Search + description extraction
  Pass 2: Web Fetch top results
  Pass 3: Firecrawl scrape for JS-heavy sites
  Pass 4: Firecrawl Extract for high-enrollment remainders
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

# Import proven date parsing from confirmation_scraper
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
from confirmation_scraper import extract_dates, validate, MONTHS, parse_month_day

# --- Configuration ---
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
NCES_ALL_FILE = BASE_DIR / "nces_all_districts.csv"
RESULTS_FILE = BASE_DIR / "mass_scraper_results.json"
LOG_FILE = BASE_DIR / "mass_scraper.log"

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"

BRAVE_DELAY = 1.15   # Brave free tier: 1 req/sec
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
# Data Loading
# =============================================

def load_medium_districts() -> list[dict]:
    """Load all medium-confidence districts, sorted by enrollment desc."""
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


def load_nces_websites() -> dict[str, str]:
    """Load NCES website URLs keyed by leaid."""
    websites = {}
    try:
        with open(NCES_ALL_FILE, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                leaid = row.get("leaid", "").strip()
                website = row.get("website", "").strip()
                if leaid and website:
                    website = website.rstrip("/")
                    if not website.startswith("http"):
                        website = "https://" + website
                    websites[leaid] = website
    except FileNotFoundError:
        pass
    return websites


def load_results() -> dict:
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {
        "confirmed": {},
        "failed": {},
        "pass_stats": {},
        "total_brave_calls": 0,
        "total_fetches": 0,
        "total_firecrawl_credits": 0,
    }


def save_results(results: dict):
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)


# =============================================
# Brave Search
# =============================================

def brave_search(query: str, retries: int = 2) -> list[dict]:
    """Search Brave and return results with title, url, description."""
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
                wait = 10 * (attempt + 1)
                log(f"    Brave 429, waiting {wait}s...")
                time.sleep(wait)
            elif e.code == 403:
                log(f"    Brave 403 — daily limit hit?")
                return []
            else:
                log(f"    Brave HTTP {e.code}")
                return []
        except Exception as e:
            log(f"    Brave error: {e}")
            if attempt < retries:
                time.sleep(3)
    return []


# =============================================
# Web Fetch
# =============================================

def web_fetch_raw(url: str, max_bytes: int = 100000) -> str:
    """Fetch a URL and return raw text (HTML tags stripped)."""
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
        # Strip HTML
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


# =============================================
# Firecrawl
# =============================================

def firecrawl_scrape(url: str) -> str:
    """Scrape a URL via Firecrawl. Returns markdown."""
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
    """Try to extract dates directly from Brave search descriptions."""
    result = {}
    
    # Spring Break: "March 23-27" or "March 23 - March 27"
    patterns_sb = [
        r'spring\s+break[^.]*?(\w+)\s+(\d{1,2})\s*[-–to]+\s*(\d{1,2})',
        r'spring\s+break[^.]*?(\w+)\s+(\d{1,2})\s*[-–to]+\s*\w+\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})[,\s]*(?:\d{4})?\s*[|\s]*spring\s+break',
    ]
    for pat in patterns_sb:
        m = re.search(pat, desc, re.I)
        if m:
            g = m.groups()
            if g[0].lower() in MONTHS:
                d1 = parse_month_day(g[0], g[1])
                d2 = parse_month_day(g[0], g[2])
                if d1 and d2 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                    result['spring_break_start'] = d1.isoformat()
                    result['spring_break_end'] = d2.isoformat()
                    break

    # First day
    patterns_fd = [
        r'first\s+day\s+(?:of\s+)?school[:\s]+(\w+)\s+(\d{1,2})',
        r'school\s+(?:starts?|begins?)[:\s]+(\w+)\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})[,\s]*(?:\d{4})?\s*[-|]*\s*first\s+day',
    ]
    for pat in patterns_fd:
        m = re.search(pat, desc, re.I)
        if m:
            d = parse_month_day(m.group(1), m.group(2))
            if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
                result['first_day'] = d.isoformat()
                break

    # Last day
    patterns_ld = [
        r'last\s+day\s+(?:of\s+)?school[:\s]+(\w+)\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})[,\s]*(?:\d{4})?\s*[-|]*\s*last\s+day',
    ]
    for pat in patterns_ld:
        m = re.search(pat, desc, re.I)
        if m:
            d = parse_month_day(m.group(1), m.group(2))
            if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
                result['last_day'] = d.isoformat()
                break
    
    # Derive summer dates
    if 'first_day' in result and 'last_day' in result:
        result['summer_start'] = result['last_day']
        result['summer_end'] = result['first_day']

    return result


# =============================================
# URL Ranking
# =============================================

PRIORITY_DOMAINS = [
    'educounty.net', 'schoolcalendarinfo.com', 'texasschools.us',
    'publicschoolreview.com', 'schooldigger.com',
]

def rank_urls(results: list[dict], district_name: str = '') -> list[dict]:
    """Rank search results by likelihood of having calendar data."""
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
        elif '2025' in url and '2026' in url:
            score += 10
        if 'calendar' in url:
            score += 10
        if 'calendar' in title:
            score += 8

        # Date mentions in description (gold!)
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
        if '2024-25' in url or '2023-24' in url:
            score -= 20
        if any(w in url for w in ['employment', 'jobs', 'news', 'blog', 'staff']):
            score -= 10

        scored.append((score, r))

    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored]


# =============================================
# Process Single District
# =============================================

def process_district_brave(district: dict, results: dict) -> tuple[dict | None, str, str]:
    """
    Process a district using Brave Search.
    Returns (dates_dict, source_url, method) or (None, '', 'failed_reason').
    """
    name = district['name']
    state = district['state']
    state_full = STATE_NAMES.get(state, state)
    
    # Clean district name for search
    clean_name = re.sub(r'\s*\(.*?\)', '', name)
    clean_name = re.sub(r'\s+Schools?\s*$', '', clean_name, flags=re.I)
    
    # Search query
    query = f'{clean_name} {state_full} school calendar 2025-2026'
    
    search_results = brave_search(query)
    results['total_brave_calls'] = results.get('total_brave_calls', 0) + 1
    time.sleep(BRAVE_DELAY)
    
    if not search_results:
        return None, '', 'no_search_results'
    
    # --- Step 1: Extract from descriptions ---
    for sr in search_results:
        desc_dates = extract_from_description(sr.get('description', ''))
        validated = validate(desc_dates)
        if validated:
            return validated, sr['url'], 'description'
    
    # --- Also try full text extraction from all descriptions combined ---
    all_desc = '\n'.join(sr.get('description', '') + ' ' + sr.get('title', '') for sr in search_results)
    desc_dates = extract_dates(all_desc)
    validated = validate(desc_dates)
    if validated:
        return validated, search_results[0]['url'], 'description_combined'
    
    # --- Step 2: Rank URLs and fetch ---
    ranked = rank_urls(search_results, name)
    
    for sr in ranked[:3]:
        url = sr['url']
        if url.lower().endswith('.pdf'):
            continue
        
        content = web_fetch_raw(url)
        results['total_fetches'] = results.get('total_fetches', 0) + 1
        time.sleep(FETCH_DELAY)
        
        if content and len(content) > 200:
            dates = extract_dates(content)
            validated = validate(dates)
            if validated:
                return validated, url, 'web_fetch'
    
    # --- Step 3: Firecrawl fallback for top URL ---
    if FIRECRAWL_API_KEY and district['enrollment'] >= 500:
        for sr in ranked[:1]:
            url = sr['url']
            md = firecrawl_scrape(url)
            results['total_firecrawl_credits'] = results.get('total_firecrawl_credits', 0) + 1
            if md and len(md) > 200:
                dates = extract_dates(md)
                validated = validate(dates)
                if validated:
                    return validated, url, 'firecrawl'
    
    return None, '', 'parse_failed'


# =============================================
# State-Level Bulk Scraping (educounty.net)
# =============================================

def scrape_educounty_state(state: str, state_full: str) -> dict[str, dict]:
    """Try to scrape educounty.net for a whole state at once.
    Returns dict of {district_name_lower: dates_dict}"""
    results = {}
    state_slug = state_full.lower().replace(' ', '-')
    
    # educounty.net has pages like:
    # https://www.educounty.net/school-calendar/{state}/
    urls_to_try = [
        f"https://www.educounty.net/school-calendar/{state_slug}/",
        f"https://www.educounty.net/{state_slug}-school-calendar-2025-2026/",
    ]
    
    for url in urls_to_try:
        content = web_fetch_raw(url, max_bytes=200000)
        if content and len(content) > 500:
            # Parse district-level calendars from the page
            # educounty.net typically lists districts with their calendars
            lines = content.split('\n')
            current_district = None
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                # Look for district headers
                district_match = re.match(r'^(.+?(?:School District|Schools|Public Schools|Unified School District|ISD|USD|SD))\s*$', line, re.I)
                if district_match:
                    current_district = district_match.group(1).strip().lower()
                
                if current_district:
                    dates = extract_dates(line)
                    if dates:
                        validated = validate(dates)
                        if validated:
                            results[current_district] = validated
            
            if results:
                return results
        time.sleep(FETCH_DELAY)
    
    return results


# =============================================
# Main Orchestrator
# =============================================

def run():
    log("=" * 80)
    log("MASS SCRAPER — Processing all medium-confidence districts")
    log("=" * 80)
    
    # Load data
    log("Loading districts...")
    all_medium = load_medium_districts()
    nces_websites = load_nces_websites()
    results = load_results()
    
    # Skip already processed
    already_done = set(results.get('confirmed', {}).keys()) | set(results.get('failed', {}).keys())
    
    # Also check previous scraper results
    prev_confirmed = set()
    for rfile in ['confirmation_results.json', 'brave_scraper_results.json']:
        try:
            with open(BASE_DIR / rfile) as f:
                prev = json.load(f)
            prev_confirmed |= set(prev.get('confirmed', {}).keys())
        except:
            pass
    
    remaining = [d for d in all_medium if d['leaid'] not in already_done and d['leaid'] not in prev_confirmed]
    
    log(f"Total medium districts: {len(all_medium)}")
    log(f"Already processed (this scraper): {len(already_done)}")
    log(f"Previously confirmed (other scrapers): {len(prev_confirmed)}")
    log(f"Remaining to process: {len(remaining)}")
    log(f"Remaining total enrollment: {sum(d['enrollment'] for d in remaining):,}")
    
    if not remaining:
        log("Nothing to process!")
        return
    
    # Stats
    confirmed_count = 0
    failed_count = 0
    method_counts = defaultdict(int)
    start_time = time.time()
    
    for i, district in enumerate(remaining):
        leaid = district['leaid']
        enrollment = district['enrollment']
        
        if i % 100 == 0 and i > 0:
            elapsed = time.time() - start_time
            rate = i / elapsed * 3600
            eta_h = (len(remaining) - i) / rate if rate > 0 else 0
            log(f"\n--- Progress: {i}/{len(remaining)} ({i/len(remaining)*100:.1f}%) | "
                f"{confirmed_count}✅ {failed_count}❌ | "
                f"Rate: {rate:.0f}/hr | ETA: {eta_h:.1f}h ---\n")
        
        log(f"[{i+1}/{len(remaining)}] {district['name']} ({district['state']}) — {enrollment:,}")
        
        try:
            dates, source_url, method = process_district_brave(district, results)
        except Exception as e:
            log(f"  ERROR: {e}")
            dates, source_url, method = None, '', f'error:{str(e)[:50]}'
        
        if dates:
            confirmed_count += 1
            method_counts[method] += 1
            results['confirmed'][leaid] = {
                'name': district['name'],
                'state': district['state'],
                'city': district['city'],
                'enrollment': enrollment,
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
                'enrollment': enrollment,
                'method': method,
                'timestamp': datetime.now().isoformat(),
            }
            log(f"  ❌ {method}")
        
        # Save periodically
        if (confirmed_count + failed_count) % SAVE_INTERVAL == 0:
            save_results(results)
            total = confirmed_count + failed_count
            rate_pct = confirmed_count / total * 100 if total else 0
            log(f"  --- SAVED: {confirmed_count}✅ {failed_count}❌ ({rate_pct:.0f}%) | "
                f"Brave: {results.get('total_brave_calls', 0)} | "
                f"Methods: {dict(method_counts)} ---")
    
    # Final save
    elapsed = time.time() - start_time
    results['pass_stats']['pass1_brave'] = {
        'confirmed': confirmed_count,
        'failed': failed_count,
        'methods': dict(method_counts),
        'elapsed_seconds': elapsed,
        'completed_at': datetime.now().isoformat(),
    }
    save_results(results)
    
    log("\n" + "=" * 80)
    log("MASS SCRAPER COMPLETE")
    log(f"  Confirmed: {confirmed_count}")
    log(f"  Failed: {failed_count}")
    rate_pct = confirmed_count / max(1, confirmed_count + failed_count) * 100
    log(f"  Rate: {rate_pct:.1f}%")
    log(f"  Methods: {dict(method_counts)}")
    log(f"  Brave API calls: {results.get('total_brave_calls', 0)}")
    log(f"  Web fetches: {results.get('total_fetches', 0)}")
    log(f"  Firecrawl credits: {results.get('total_firecrawl_credits', 0)}")
    log(f"  Time: {elapsed/3600:.1f}h")
    log("=" * 80)


if __name__ == "__main__":
    run()
