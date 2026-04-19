#!/usr/bin/env python3
"""Mega School Calendar Scraper v2 — Practical multi-strategy approach.

Phase 1: educounty.net bulk scraping (use fast name matching)
Phase 2: Brave Search for remaining (batch by state)
Phase 3: State median inference for the long tail

Target: 95% coverage (~12,750 confirmed out of 13,418)
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
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from collections import defaultdict

# --- Configuration ---
BASE_DIR = Path(__file__).parent
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
NCES_ALL_FILE = BASE_DIR / "nces_all_districts.csv"
MEGA_RESULTS_FILE = BASE_DIR / "mega_scraper_results.json"
LOG_FILE = BASE_DIR / "mega_scraper.log"

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
BRAVE_SEARCH_URL = "https://api.brave.com/res/v1/web/search"

BRAVE_DELAY = 1.1
FETCH_DELAY = 0.3
SAVE_INTERVAL = 50

MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6, 'jul': 7, 'aug': 8,
    'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ============================================================
# Date Parsing
# ============================================================

def parse_month_day(month_str: str, day_str: str) -> date | None:
    month_str = month_str.lower().strip().rstrip('.')
    month = MONTHS.get(month_str)
    if not month:
        return None
    try:
        day = int(re.search(r'\d+', str(day_str)).group())
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
    """Extract school calendar dates from text content."""
    result = {}
    
    has_2526 = bool(re.search(r'2025\s*[-–]\s*(?:20)?26', md))
    has_2627 = bool(re.search(r'2026\s*[-–]\s*(?:20)?27', md))
    if has_2627 and not has_2526:
        return {}
    
    current_month = None
    
    for line in md.split('\n'):
        line_stripped = line.strip()
        line_lower = line_stripped.lower()
        
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
        
        # Table format: "| Month Day | Event |"
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
        
        _extract_first_day(line_stripped, result)
        _extract_last_day(line_stripped, result)
        _extract_spring_break(line_stripped, result)
        _extract_winter_break(line_stripped, result)
        
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
    
    # Also try "Month Day, Year" formats
    for line in md.split('\n'):
        ll = line.lower()
        if 'first day' in ll and 'first_day' not in result:
            m = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s*(?:20\d{2})?', ll)
            if m:
                d = parse_month_day(m.group(1), m.group(2))
                if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
                    result['first_day'] = d.isoformat()
        if 'last day' in ll and 'last_day' not in result:
            m = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s*(?:20\d{2})?', ll)
            if m:
                d = parse_month_day(m.group(1), m.group(2))
                if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
                    result['last_day'] = d.isoformat()
    
    if 'first_day' in result and 'last_day' in result:
        result['summer_start'] = result['last_day']
        result['summer_end'] = result['first_day']
    
    return result


def _process_event(d1, day2_str, month_str, event, result):
    event = re.sub(r'[*_\\]', '', event).strip().lower()
    
    if any(p in event for p in ['first day of school', 'first day for students',
                                 'school begins', 'classes begin', 'students return',
                                 'first day of class', 'first day  school',
                                 'first day of instruction']):
        if date(2025, 7, 1) <= d1 <= date(2025, 9, 30) and 'first_day' not in result:
            result['first_day'] = d1.isoformat()
    
    if any(p in event for p in ['last day of school', 'last day for students', 
                                 'last day of class', 'end of school year',
                                 'school ends', 'last student day',
                                 'last day of instruction', 'last day  school']):
        if date(2026, 5, 1) <= d1 <= date(2026, 7, 15) and 'last_day' not in result:
            result['last_day'] = d1.isoformat()
    
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
                result['spring_break_end'] = d1.isoformat()
    
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


def _extract_first_day(line, result):
    if 'first_day' in result:
        return
    patterns = [
        r'first\s+day\s+(?:of\s+)?(?:school|class|instruction)[:\s]*(\w+)\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})[,\s]*[-–|]*[*\s]*first\s+day\s+(?:of\s+)?(?:school|class)',
        r'school\s+(?:starts|begins)[:\s]*(\w+)\s+(\d{1,2})',
        r'classes\s+begin[:\s]*(\w+)\s+(\d{1,2})',
    ]
    for pat in patterns:
        m = re.search(pat, line, re.I)
        if m:
            d = parse_month_day(m.group(1), m.group(2))
            if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
                result['first_day'] = d.isoformat()
                return


def _extract_last_day(line, result):
    if 'last_day' in result:
        return
    patterns = [
        r'last\s+day\s+(?:of\s+)?(?:school|class|instruction)[:\s]*(\w+)\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})[,\s]*[-–|]*[*\s]*last\s+day\s+(?:of\s+)?(?:school|class)',
    ]
    for pat in patterns:
        m = re.search(pat, line, re.I)
        if m:
            d = parse_month_day(m.group(1), m.group(2))
            if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
                result['last_day'] = d.isoformat()
                return


def _extract_spring_break(line, result):
    if 'spring_break_start' in result:
        return
    ll = line.lower()
    if 'spring break' not in ll and 'spring recess' not in ll and 'spring holiday' not in ll:
        return
    
    patterns = [
        # "Spring Break: March 16-20" or "Spring Break March 16-20, 2026"
        r'spring\s+(?:break|recess|holiday)[:\s]*(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})',
        # "March 16-20 Spring Break" or "| March 16-20, 2026 | | Spring Break |"
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2}),?\s*(?:\d{4})?\s*[|\s]*[*]*(?:no school)?[*\s]*spring\s+(?:break|recess)',
        # "Spring Break is from March 16-20"
        r'spring\s+(?:break|recess)\s+(?:is\s+)?(?:from\s+)?(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})',
        # "spring break ... from March 16-20, 2026" (with stuff in between)
        r'spring\s+(?:break|recess).{0,80}?(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})',
        # "March 16 - March 20 Spring Break"
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*\w+\s+(\d{1,2})\s*.*?spring\s+(?:break|recess)',
        # "Spring Break March 16 through March 20"
        r'spring\s+(?:break|recess)[:\s]*(\w+)\s+(\d{1,2})\s*[-–through]+\s*\w+\s+(\d{1,2})',
    ]
    for pat in patterns:
        m = re.search(pat, line, re.I)
        if m:
            groups = m.groups()
            if len(groups) == 3 and groups[0].isalpha():
                d1 = parse_month_day(groups[0], groups[1])
                d2 = parse_month_day(groups[0], groups[2])
            else:
                continue
            if d1 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                result['spring_break_start'] = d1.isoformat()
                result['spring_break_end'] = (d2 or d1).isoformat()
                return


def _extract_winter_break(line, result):
    if 'winter_break_start' in result:
        return
    ll = line.lower()
    if not any(w in ll for w in ['winter break', 'christmas break', 'winter holiday', 'christmas holiday', 'holiday break', 'winter recess']):
        return
    
    patterns = [
        # "Winter Break: December 22 - January 2"
        r'(?:winter|christmas)\s+(?:break|holiday|vacation|recess)[:\s]*(\w+)\s+(\d{1,2})\s*[-–]\s*(\w+)\s+(\d{1,2})',
        # "December 22 - January 2 Winter Break"
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\w+)\s+(\d{1,2}),?\s*(?:\d{4})?\s*[|\s]*[*]*(?:no school)?[*\s]*(?:winter|christmas)\s+(?:break|holiday)',
        # "Winter Break December 22-January 2, 2026" 
        r'(?:winter|christmas)\s+(?:break|holiday|vacation|recess).{0,40}?(\w+)\s+(\d{1,2}),?\s*(?:\d{4})?\s*[-–to]+\s*(\w+)\s+(\d{1,2})',
        # "December 22-January 2, 2026 | | Winter Break"
        r'(\w+)\s+(\d{1,2}),?\s*(?:\d{4})?\s*[-–]\s*(\w+)\s+(\d{1,2}),?\s*(?:\d{4})?.{0,40}?(?:winter|christmas)\s+(?:break|holiday)',
        # Same-month: "December 22-31 Winter Break"
        r'(?:winter|christmas)\s+(?:break|holiday|vacation)[:\s]*(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})',
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\s*,?\s*(?:\d{4})?\s*.*?(?:winter|christmas)\s+(?:break|holiday)',
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
            if sb_end < sb_start or (sb_end - sb_start).days > 21:
                return None
            if sb_start < date(2026, 2, 1) or sb_start > date(2026, 5, 31):
                return None
        except (ValueError, TypeError):
            has_spring = False
    if has_year:
        try:
            fd = date.fromisoformat(data['first_day'])
            ld = date.fromisoformat(data['last_day'])
            if fd > ld or fd < date(2025, 7, 1) or fd > date(2025, 9, 30):
                return None
            if ld < date(2026, 4, 1) or ld > date(2026, 7, 15):
                return None
        except (ValueError, TypeError):
            has_year = False
    if not has_spring and not has_year:
        return None
    return data


# ============================================================
# HTTP Helpers
# ============================================================

def fetch_url(url: str, timeout: int = 20) -> str | None:
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.read().decode('utf-8', errors='replace')
    except Exception:
        return None


def html_to_text(html: str) -> str:
    """Simple HTML to text conversion for date extraction."""
    text = html
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.S|re.I)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.S|re.I)
    text = re.sub(r'</?tr[^>]*>', '\n', text, flags=re.I)
    text = re.sub(r'</?td[^>]*>', ' | ', text, flags=re.I)
    text = re.sub(r'</?th[^>]*>', ' | ', text, flags=re.I)
    text = re.sub(r'<(?:h[1-6]|p|div|br|li)[^>]*>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&#8211;', '–').replace('&#8212;', '—').replace('&nbsp;', ' ')
    text = re.sub(r'&[a-z]+;', ' ', text)
    text = re.sub(r'&#\d+;', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n', text)
    return text


def scrape_page_for_dates(url: str) -> dict | None:
    """Fetch and parse a page for school calendar dates."""
    html = fetch_url(url)
    if not html:
        return None
    text = html_to_text(html)
    dates = extract_dates(text)
    return validate(dates)


def brave_search(query: str) -> list[dict]:
    params = urllib.parse.urlencode({'q': query, 'count': 10})
    url = f"{BRAVE_SEARCH_URL}?{params}"
    req = urllib.request.Request(url, headers={
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip',
        'X-Subscription-Token': BRAVE_API_KEY,
    })
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = resp.read()
        if resp.headers.get('Content-Encoding') == 'gzip':
            import gzip
            data = gzip.decompress(data)
        result = json.loads(data)
        return result.get('web', {}).get('results', [])
    except Exception as e:
        log(f"Brave search error: {e}")
        return []


def extract_dates_from_description(desc: str) -> dict:
    """Extract dates from search result descriptions."""
    result = {}
    
    # Spring Break patterns
    for pat in [
        r'spring\s+break\s+(?:is\s+)?(?:from\s+)?(\w+)\s+(\d{1,2})\s*[-–to]+\s*(?:(\w+)\s+)?(\d{1,2})',
        r'spring\s+break[:\s]+(\w+)\s+(\d{1,2})\s*[-–]\s*(\w+)?\s*(\d{1,2})',
    ]:
        m = re.search(pat, desc, re.I)
        if m:
            month1 = m.group(1)
            day1 = m.group(2)
            month2 = m.group(3) or month1
            day2 = m.group(4)
            d1 = parse_month_day(month1, day1)
            d2 = parse_month_day(month2, day2)
            if d1 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                result['spring_break_start'] = d1.isoformat()
                result['spring_break_end'] = (d2 or d1).isoformat()
                break
    
    # First day
    m = re.search(r'(?:first\s+day\s+(?:of\s+)?school|school\s+(?:starts?|begins?))[:\s]+(\w+)\s+(\d{1,2})', desc, re.I)
    if m:
        d = parse_month_day(m.group(1), m.group(2))
        if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
            result['first_day'] = d.isoformat()
    
    # Last day
    m = re.search(r'(?:last\s+day\s+(?:of\s+)?school|school\s+(?:ends?))[:\s]+(\w+)\s+(\d{1,2})', desc, re.I)
    if m:
        d = parse_month_day(m.group(1), m.group(2))
        if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
            result['last_day'] = d.isoformat()
    
    # Winter break
    m = re.search(r'(?:winter|christmas)\s+break[:\s]+(\w+)\s+(\d{1,2})\s*[-–to]+\s*(\w+)\s+(\d{1,2})', desc, re.I)
    if m:
        d1 = parse_month_day(m.group(1), m.group(2))
        d2 = parse_month_day(m.group(3), m.group(4))
        if d1 and d1.month in (11, 12):
            result['winter_break_start'] = d1.isoformat()
            if d2:
                result['winter_break_end'] = d2.isoformat()
    
    return result


# ============================================================
# Phase 1: educounty.net via sitemap
# ============================================================

def normalize_name(name: str) -> str:
    """Normalize district name for matching."""
    name = name.lower().strip()
    # Remove common suffixes
    name = re.sub(r'\s*(unified |consolidated |independent |joint |union |elementary |high |central )?school\s*dist(rict)?\s*$', '', name)
    name = re.sub(r'\s*(public schools?|city schools?|area schools?|community schools?)\s*$', '', name)
    name = re.sub(r'\s*(isd|cisd|csd|usd|cusd|sd|ps)\s*$', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def extract_slug_name(url: str) -> str:
    """Extract district name from educounty URL slug."""
    slug = url.rstrip('/').split('/')[-1]
    # Remove calendar/date suffixes from the end
    slug = re.sub(r'-(calendar|school-calendar|schools-calendar|cal|25-26|2025-26|2025-2026|26-27|pdf|revised|updates?|teachers?).*$', '', slug)
    # Remove prefix abbreviations (like kcsd-, gisd-, sdpc-)
    # But keep them — they can help match
    return slug.replace('-', ' ').strip().lower()


def phase1_educounty(districts: list[dict], already_confirmed: set) -> dict:
    """Phase 1: Scrape all educounty.net calendar pages, match to districts."""
    log("=" * 60)
    log("PHASE 1: educounty.net bulk scraping")
    log("=" * 60)
    
    # Step 1: Get all calendar URLs from sitemaps
    all_urls = []
    for i in range(1, 35):
        sm_url = f"https://www.educounty.net/post-sitemap{i}.xml"
        xml_text = fetch_url(sm_url, timeout=30)
        if not xml_text:
            log(f"  Failed: {sm_url}")
            continue
        try:
            root = ET.fromstring(xml_text)
            ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            for url_elem in root.findall('.//ns:url/ns:loc', ns):
                url = url_elem.text.strip()
                url_lower = url.lower()
                if 'calendar' in url_lower or '25-26' in url_lower:
                    all_urls.append(url)
        except ET.ParseError:
            pass
        time.sleep(0.2)
    
    log(f"Found {len(all_urls)} calendar URLs from educounty.net")
    
    # Step 2: Build MULTIPLE lookup keys per district
    name_lookup = defaultdict(list)  # key -> [(leaid, state, enrollment)]
    
    for d in districts:
        if d['nces_leaid'] in already_confirmed:
            continue
        leaid = d['nces_leaid']
        state = d['state']
        try:
            enroll = int(d.get('enrollment', 0) or 0)
        except:
            enroll = 0
        info = (leaid, state, enroll)
        
        name = d['district_name'].lower().strip()
        
        # Key 1: Full name normalized
        norm = normalize_name(name)
        name_lookup[norm].append(info)
        
        # Key 2: Original name lowered (e.g., "austin isd")
        name_dashed = name.replace(',', '').strip()
        name_lookup[name_dashed].append(info)
        
        # Key 3: Name with common suffixes stripped differently
        for pat in [
            r'\s*(unified |consolidated |independent )?school\s*dist(rict)?\s*$',
            r'\s*(public schools?|city schools?|area schools?|community schools?)\s*$',
            r'\s*(isd|cisd|csd|usd|cusd|sd|ps|schools?)\s*$',
        ]:
            stripped = re.sub(pat, '', name, flags=re.I).strip()
            if stripped and stripped != name:
                name_lookup[stripped].append(info)
        
        # Key 4: "X County" variations
        county_match = re.search(r'(\w[\w\s]*?)\s+county', name, re.I)
        if county_match:
            base = county_match.group(1).strip()
            name_lookup[base + ' county'].append(info)
            name_lookup[base].append(info)
        
        # Key 5: Just the city/district prefix (e.g., "austin" from "austin isd")
        short = re.sub(r'\s+(isd|cisd|csd|usd|cusd|sd|county|city|schools?|public|area|community|independent|unified|consolidated|joint|union|elementary|high|central|school district|school dist)\b.*$', '', name, flags=re.I).strip()
        if short and len(short) > 2:
            name_lookup[short].append(info)
    
    log(f"Built {len(name_lookup)} lookup keys for {len(districts) - len(already_confirmed)} unconfirmed districts")
    
    # Step 3: Match URLs to districts via slug — try multiple strategies
    url_matches = {}  # leaid -> url
    unmatched_urls = []
    
    for url in all_urls:
        slug_name = extract_slug_name(url)
        
        matched = False
        # Try direct match
        if slug_name in name_lookup:
            for leaid, state, enroll in name_lookup[slug_name]:
                if leaid not in url_matches:
                    url_matches[leaid] = url
                    matched = True
                    break
        
        if matched:
            continue
        
        # Try removing prefix abbreviations (gisd, kcsd, etc.)
        slug_no_prefix = re.sub(r'^[a-z]{2,5}\s+', '', slug_name).strip()
        if slug_no_prefix and slug_no_prefix != slug_name and slug_no_prefix in name_lookup:
            for leaid, state, enroll in name_lookup[slug_no_prefix]:
                if leaid not in url_matches:
                    url_matches[leaid] = url
                    matched = True
                    break
        
        if matched:
            continue
        
        # Try dropping state abbreviations (sc, nc, ga, etc.)
        slug_no_state = re.sub(r'\s+(?:al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy)$', '', slug_name).strip()
        if slug_no_state != slug_name and slug_no_state in name_lookup:
            for leaid, state, enroll in name_lookup[slug_no_state]:
                if leaid not in url_matches:
                    url_matches[leaid] = url
                    matched = True
                    break
        
        if matched:
            continue
        
        # Try various combinations
        # e.g., "fort worth isd school district" -> try "fort worth isd", "fort worth"
        words = slug_name.split()
        for length in range(len(words), 0, -1):
            key = ' '.join(words[:length])
            if key in name_lookup:
                for leaid, state, enroll in name_lookup[key]:
                    if leaid not in url_matches:
                        url_matches[leaid] = url
                        matched = True
                        break
                if matched:
                    break
        
        if not matched:
            unmatched_urls.append(url)
    
    log(f"Matched {len(url_matches)} URLs to unconfirmed districts ({len(unmatched_urls)} unmatched)")
    
    # Step 4: Scrape matched pages
    results = {}
    scraped = 0
    for leaid, url in url_matches.items():
        try:
            dates = scrape_page_for_dates(url)
            scraped += 1
            if dates:
                results[leaid] = {
                    'dates': dates,
                    'source': 'educounty',
                    'url': url,
                }
            if scraped % 50 == 0:
                log(f"  educounty: scraped {scraped}/{len(url_matches)}, confirmed: {len(results)}")
            time.sleep(FETCH_DELAY)
        except Exception as e:
            log(f"  Error scraping {url}: {e}")
    
    log(f"Phase 1 complete: {len(results)} new confirmed from educounty.net (scraped {scraped})")
    return results


# ============================================================
# Phase 2: Brave Search
# ============================================================

def phase2_brave(districts: list[dict], already_confirmed: set) -> dict:
    """Phase 2: Brave Search for remaining unconfirmed districts."""
    log("=" * 60)
    log("PHASE 2: Brave Search")
    log("=" * 60)
    
    # Sort by enrollment descending
    unconfirmed = []
    for d in districts:
        leaid = d['nces_leaid']
        if leaid in already_confirmed:
            continue
        try:
            enroll = int(d.get('enrollment', 0) or 0)
        except:
            enroll = 0
        unconfirmed.append((enroll, d))
    unconfirmed.sort(key=lambda x: -x[0])
    
    log(f"Phase 2: {len(unconfirmed)} districts to search")
    
    results = {}
    searched = 0
    desc_hits = 0
    page_hits = 0
    errors = 0
    
    for enrollment, d in unconfirmed:
        leaid = d['nces_leaid']
        name = d['district_name']
        state = d['state']
        
        query = f'"{name}" {state} school calendar 2025-2026'
        
        try:
            search_results = brave_search(query)
        except Exception as e:
            errors += 1
            if errors > 10:
                log(f"  Too many errors, stopping Brave search")
                break
            continue
        
        searched += 1
        time.sleep(BRAVE_DELAY)
        
        # Strategy 1: descriptions
        found = False
        for sr in search_results:
            combined = (sr.get('description', '') + ' ' + sr.get('title', '') + ' ' + 
                       sr.get('extra_snippets', [''])[0] if isinstance(sr.get('extra_snippets'), list) else '')
            desc_dates = extract_dates_from_description(combined)
            validated = validate(desc_dates)
            if validated:
                results[leaid] = {
                    'dates': validated,
                    'source': 'brave_description',
                    'url': sr.get('url', ''),
                }
                desc_hits += 1
                found = True
                break
        
        # Strategy 2: Fetch good sources
        if not found:
            for sr in search_results[:3]:
                url = sr.get('url', '')
                url_lower = url.lower()
                if any(domain in url_lower for domain in [
                    'educounty.net', 'schoolcalendarinfo.com', 'texasschools.us',
                    'publicschoolreview.com'
                ]):
                    page_dates = scrape_page_for_dates(url)
                    if page_dates:
                        results[leaid] = {
                            'dates': page_dates,
                            'source': f'brave_page',
                            'url': url,
                        }
                        page_hits += 1
                        found = True
                        time.sleep(FETCH_DELAY)
                        break
        
        if searched % 100 == 0:
            log(f"  Brave: {searched}/{len(unconfirmed)} searched, {len(results)} confirmed (desc:{desc_hits} page:{page_hits})")
        
        if searched % SAVE_INTERVAL == 0:
            _save_checkpoint(results, 'phase2', searched)
    
    log(f"Phase 2 complete: {len(results)} confirmed (desc:{desc_hits} page:{page_hits}, searched:{searched})")
    return results


# ============================================================
# Phase 3: State Inference
# ============================================================

def phase3_inference(districts: list[dict], already_confirmed: set) -> dict:
    """Phase 3: Infer from state medians for remaining districts."""
    log("=" * 60)
    log("PHASE 3: State-level inference")
    log("=" * 60)
    
    # Build state date distributions from confirmed districts
    state_dates = defaultdict(list)
    for d in districts:
        if d['nces_leaid'] not in already_confirmed:
            continue
        state = d['state']
        dates = {}
        for field in ['spring_break_start', 'spring_break_end', 'winter_break_start',
                      'winter_break_end', 'first_day', 'last_day']:
            if d.get(field):
                dates[field] = d[field]
        if dates.get('spring_break_start') or dates.get('first_day'):
            state_dates[state].append(dates)
    
    # Compute medians
    state_medians = {}
    for state, date_list in state_dates.items():
        medians = {}
        for field in ['spring_break_start', 'spring_break_end', 'winter_break_start',
                      'winter_break_end', 'first_day', 'last_day']:
            values = []
            for d in date_list:
                if d.get(field):
                    try:
                        values.append(date.fromisoformat(d[field]))
                    except:
                        pass
            if values:
                values.sort()
                medians[field] = values[len(values) // 2].isoformat()
        
        if medians.get('spring_break_start') or medians.get('first_day'):
            if 'first_day' in medians and 'last_day' in medians:
                medians['summer_start'] = medians['last_day']
                medians['summer_end'] = medians['first_day']
            state_medians[state] = medians
    
    log(f"Computed medians for {len(state_medians)} states ({sum(len(v) for v in state_dates.values())} confirmed districts)")
    
    # Apply to unconfirmed
    results = {}
    for d in districts:
        leaid = d['nces_leaid']
        if leaid in already_confirmed:
            continue
        state = d['state']
        if state in state_medians:
            results[leaid] = {
                'dates': state_medians[state].copy(),
                'source': 'state_median_inference',
                'confidence': 'medium',
            }
    
    log(f"Phase 3: {len(results)} districts filled via state median inference")
    return results


# ============================================================
# Checkpoint / Save / Merge
# ============================================================

def _save_checkpoint(results: dict, phase: str, count: int):
    cp_file = BASE_DIR / f"mega_checkpoint_{phase}_{count}.json"
    with open(cp_file, 'w') as f:
        json.dump(results, f, default=str)


def load_mega_results() -> dict:
    if MEGA_RESULTS_FILE.exists():
        try:
            with open(MEGA_RESULTS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"phase1": {}, "phase2": {}, "phase3": {}, "stats": {}}


def merge_to_csv(districts: list[dict], all_results: dict) -> int:
    """Merge results into districts_comprehensive.csv."""
    log("Merging results into CSV...")
    updated = 0
    for d in districts:
        leaid = d['nces_leaid']
        if leaid not in all_results:
            continue
        if d.get('confidence') == 'confirmed':
            continue
        
        result = all_results[leaid]
        dates = result.get('dates', {})
        source = result.get('source', 'mega_scraper')
        confidence = result.get('confidence', 'confirmed')
        
        for field in ['spring_break_start', 'spring_break_end', 'winter_break_start',
                      'winter_break_end', 'first_day', 'last_day', 'summer_start', 'summer_end']:
            if dates.get(field):
                d[field] = dates[field]
        
        d['source'] = source
        d['confidence'] = confidence
        d['school_year'] = '2025-2026'
        updated += 1
    
    fieldnames = list(districts[0].keys())
    with open(COMPREHENSIVE_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(districts)
    
    log(f"Updated {updated} districts in CSV")
    return updated


# ============================================================
# Main
# ============================================================

def main():
    import sys
    
    # Parse args
    skip_phase1 = '--skip-phase1' in sys.argv
    skip_phase2 = '--skip-phase2' in sys.argv
    skip_phase3 = '--skip-phase3' in sys.argv
    phase2_limit = None
    for arg in sys.argv:
        if arg.startswith('--phase2-limit='):
            phase2_limit = int(arg.split('=')[1])
    
    log("=" * 60)
    log("MEGA SCHOOL CALENDAR SCRAPER v2")
    log("=" * 60)
    
    # Load districts
    districts = []
    with open(COMPREHENSIVE_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            districts.append(row)
    log(f"Loaded {len(districts)} districts")
    
    already_confirmed = set()
    for d in districts:
        if d.get('confidence') == 'confirmed':
            already_confirmed.add(d['nces_leaid'])
    log(f"Already confirmed: {len(already_confirmed)}")
    log(f"Need: {len(districts) - len(already_confirmed)}")
    
    # Load previous results
    mega = load_mega_results()
    
    # Phase 1
    if not skip_phase1:
        phase1_results = phase1_educounty(districts, already_confirmed)
        mega['phase1'] = phase1_results
        for leaid in phase1_results:
            already_confirmed.add(leaid)
        # Merge phase 1 immediately
        merge_to_csv(districts, phase1_results)
        # Reload to get updated confidence
        districts = []
        with open(COMPREHENSIVE_FILE, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                districts.append(row)
        log(f"After Phase 1: {len(already_confirmed)} confirmed")
    else:
        log("Skipping Phase 1")
        # Load previous phase 1 results
        for leaid in mega.get('phase1', {}):
            already_confirmed.add(leaid)
    
    # Phase 2
    if not skip_phase2:
        # Optionally limit
        if phase2_limit:
            log(f"Phase 2 limited to {phase2_limit} searches")
        phase2_results = phase2_brave(districts, already_confirmed)
        mega['phase2'] = phase2_results
        for leaid in phase2_results:
            already_confirmed.add(leaid)
        merge_to_csv(districts, phase2_results)
        districts = []
        with open(COMPREHENSIVE_FILE, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                districts.append(row)
        log(f"After Phase 2: {len(already_confirmed)} confirmed")
    else:
        log("Skipping Phase 2")
        for leaid in mega.get('phase2', {}):
            already_confirmed.add(leaid)
    
    # Phase 3
    if not skip_phase3:
        phase3_results = phase3_inference(districts, already_confirmed)
        mega['phase3'] = phase3_results
        merge_to_csv(districts, phase3_results)
        districts = []
        with open(COMPREHENSIVE_FILE, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                districts.append(row)
    else:
        log("Skipping Phase 3")
    
    # Save full results
    mega['stats'] = {
        'phase1_count': len(mega.get('phase1', {})),
        'phase2_count': len(mega.get('phase2', {})),
        'phase3_count': len(mega.get('phase3', {})),
        'timestamp': datetime.now().isoformat(),
    }
    with open(MEGA_RESULTS_FILE, 'w') as f:
        json.dump(mega, f, indent=2, default=str)
    
    # Final stats
    confirmed = sum(1 for d in districts if d.get('confidence') == 'confirmed')
    medium = sum(1 for d in districts if d.get('confidence') == 'medium')
    total = len(districts)
    
    # Source breakdown
    sources = defaultdict(int)
    for d in districts:
        sources[d.get('source', 'none')] += 1
    
    log("=" * 60)
    log("FINAL RESULTS")
    log(f"  Total districts: {total}")
    log(f"  Confirmed: {confirmed} ({confirmed*100/total:.1f}%)")
    log(f"  Medium: {medium} ({medium*100/total:.1f}%)")
    log(f"  Confirmed+Medium: {confirmed+medium} ({(confirmed+medium)*100/total:.1f}%)")
    log(f"  Unresolved: {total - confirmed - medium}")
    log(f"  Sources:")
    for s, c in sorted(sources.items(), key=lambda x: -x[1]):
        log(f"    {s}: {c}")
    log("=" * 60)


if __name__ == '__main__':
    main()
