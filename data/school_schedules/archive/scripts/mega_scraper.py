#!/usr/bin/env python3
"""Mega School Calendar Scraper — Multi-strategy approach.

Phase 1: educounty.net bulk scraping (34 sitemaps, thousands of pages)
Phase 2: Brave Search + description parsing + page scraping
Phase 3: State-level inference for remaining districts

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
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Configuration ---
BASE_DIR = Path(__file__).parent
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
NCES_ALL_FILE = BASE_DIR / "nces_all_districts.csv"
CONFIRMATION_RESULTS = BASE_DIR / "confirmation_results.json"
MEGA_RESULTS_FILE = BASE_DIR / "mega_scraper_results.json"
LOG_FILE = BASE_DIR / "mega_scraper.log"

BRAVE_API_KEY = ""
BRAVE_SEARCH_URL = "https://api.brave.com/res/v1/web/search"

# Rate limits
BRAVE_DELAY = 1.1  # 1 req/sec for free tier
EDUCOUNTY_DELAY = 0.5  # Be polite
SAVE_INTERVAL = 25

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
# Date Parsing (copied/adapted from confirmation_scraper.py)
# ============================================================

def parse_month_day(month_str: str, day_str: str) -> date | None:
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
        
        # Detect month headers
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
        
        # Table format
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
        
        # Context-based table
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
        
        # Text patterns
        _extract_first_day(line_stripped, result)
        _extract_last_day(line_stripped, result)
        _extract_spring_break(line_stripped, result)
        _extract_winter_break(line_stripped, result)
        
        # Section-based
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
    
    # Also try comma-separated date formats: "August 19, 2025"
    _extract_iso_dates(md, result)
    
    if 'first_day' in result and 'last_day' in result:
        result['summer_start'] = result['last_day']
        result['summer_end'] = result['first_day']
    
    return result


def _extract_iso_dates(md: str, result: dict):
    """Extract dates in 'Month Day, Year' format from full text."""
    lines = md.split('\n')
    for line in lines:
        ll = line.lower()
        
        # "First day of school: August 19, 2025" or "August 19, 2025 - First day"
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
                                 'last day of instruction']):
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
            if day2_str:
                try:
                    d2 = date(2026, 1, int(day2_str))
                    result['winter_break_end'] = d2.isoformat()
                except ValueError:
                    pass


def _extract_first_day(line, result):
    if 'first_day' in result:
        return
    patterns = [
        r'first\s+day\s+(?:of\s+)?(?:school|class|instruction)[:\s]*(\w+)\s+(\d{1,2})',
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
    patterns = [
        r'spring\s+break[:\s]*(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})',
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\s*[|\s]*[*]*(?:no school)?[*\s]*spring\s+break',
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\s+spring\s+break',
        r'spring\s+break[:\s]*(\w+)\s+(\d{1,2})\s*[-–through]+\s*\w+\s+(\d{1,2})',
        # "Spring Break is from March 9-13"
        r'spring\s+break\s+(?:is\s+)?(?:from\s+)?(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})',
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
    patterns = [
        r'(?:winter|christmas)\s+(?:break|holiday|vacation)[:\s]*(\w+)\s+(\d{1,2})\s*[-–]\s*(\w+)\s+(\d{1,2})',
        r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\w+)\s+(\d{1,2})\s*[|\s]*[*]*(?:no school)?[*\s]*(?:winter|christmas)\s+(?:break|holiday)',
        r'(?:winter|christmas)\s+(?:break|holiday|vacation)[:\s]*(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})',
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


def validate(data: dict) -> dict | None:
    """Validate extracted dates."""
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
            if sb_end < sb_start:
                return None
            if (sb_end - sb_start).days > 21:
                return None
            if sb_start < date(2026, 2, 1) or sb_start > date(2026, 5, 31):
                return None
        except (ValueError, TypeError):
            has_spring = False
    
    # Validate first/last day
    if has_year:
        try:
            fd = date.fromisoformat(data['first_day'])
            ld = date.fromisoformat(data['last_day'])
            if fd > ld:
                return None
            if fd < date(2025, 7, 1) or fd > date(2025, 9, 30):
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
    """Fetch a URL and return text content."""
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; SchoolCalendarBot/1.0)',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        return None


def brave_search(query: str) -> list[dict]:
    """Search Brave and return results with titles, URLs, descriptions."""
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
        # Handle gzip
        if resp.headers.get('Content-Encoding') == 'gzip':
            import gzip
            data = gzip.decompress(data)
        result = json.loads(data)
        return result.get('web', {}).get('results', [])
    except Exception as e:
        log(f"Brave search error: {e}")
        return []


import urllib.parse


# ============================================================
# Phase 1: educounty.net Bulk Scraping
# ============================================================

def fetch_all_educounty_urls() -> list[str]:
    """Fetch all post URLs from educounty.net sitemaps."""
    sitemap_urls = [f"https://www.educounty.net/post-sitemap{i}.xml" for i in range(1, 35)]
    all_urls = []
    
    for sm_url in sitemap_urls:
        log(f"Fetching sitemap: {sm_url}")
        xml_text = fetch_url(sm_url, timeout=30)
        if not xml_text:
            log(f"  Failed to fetch {sm_url}")
            continue
        
        # Parse XML
        try:
            root = ET.fromstring(xml_text)
            ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            for url_elem in root.findall('.//ns:url/ns:loc', ns):
                url = url_elem.text.strip()
                # Only include calendar-related URLs (contain 'calendar' or '25-26')
                url_lower = url.lower()
                if 'calendar' in url_lower or '25-26' in url_lower or '2025-26' in url_lower:
                    all_urls.append(url)
        except ET.ParseError as e:
            log(f"  XML parse error for {sm_url}: {e}")
        
        time.sleep(0.3)
    
    log(f"Found {len(all_urls)} calendar URLs from educounty.net sitemaps")
    return all_urls


def extract_district_name_from_url(url: str) -> str:
    """Extract a rough district name from an educounty.net URL."""
    # e.g., https://www.educounty.net/austin-isd-schools-calendar-25-26-pdf/
    slug = url.split('/')[-2] if url.endswith('/') else url.split('/')[-1]
    # Remove common suffixes
    slug = re.sub(r'[-_](school|schools|calendar|cal|25-26|2025-26|2025-2026|pdf|district)s?', ' ', slug)
    slug = re.sub(r'[-_]', ' ', slug).strip()
    return slug


def match_educounty_to_districts(ec_urls: list[str], districts: list[dict]) -> dict[str, str]:
    """Try to match educounty URLs to our district list.
    Returns: {nces_leaid: educounty_url}
    """
    # Build lookup indices
    name_to_ids = defaultdict(list)
    for d in districts:
        name = d['district_name'].lower().strip()
        leaid = d['nces_leaid']
        state = d['state']
        # Store various name forms
        name_to_ids[name].append((leaid, state))
        # Also short forms: remove "school district", "independent school district", etc.
        short = re.sub(r'\s*(unified |consolidated |independent |joint |union |elementary |high )?school\s*district\s*$', '', name, flags=re.I).strip()
        if short != name:
            name_to_ids[short].append((leaid, state))
        # Also "County" form
        short2 = re.sub(r'\s*county\s*$', ' county', name, flags=re.I).strip()
        name_to_ids[short2].append((leaid, state))
        # City form
        short3 = re.sub(r'\s*(city|public|schools?|isd|cisd|csd)\s*$', '', name, flags=re.I).strip()
        if short3 and short3 != name:
            name_to_ids[short3].append((leaid, state))
    
    matches = {}
    for url in ec_urls:
        slug = extract_district_name_from_url(url)
        slug_lower = slug.lower().strip()
        
        # Try direct match
        if slug_lower in name_to_ids:
            for leaid, state in name_to_ids[slug_lower]:
                if leaid not in matches:
                    matches[leaid] = url
                    break
            continue
        
        # Try fuzzy: check if slug words are subset of any district name
        slug_words = set(slug_lower.split())
        if len(slug_words) < 2:
            continue
        
        best_match = None
        best_score = 0
        for name, id_list in name_to_ids.items():
            name_words = set(name.split())
            overlap = slug_words & name_words
            if len(overlap) >= 2 and len(overlap) / max(len(slug_words), len(name_words)) > 0.5:
                score = len(overlap) / max(len(slug_words), len(name_words))
                if score > best_score:
                    best_score = score
                    best_match = id_list[0]  # (leaid, state)
        
        if best_match and best_match[0] not in matches:
            matches[best_match[0]] = url
    
    return matches


def scrape_educounty_page(url: str) -> dict | None:
    """Scrape a single educounty.net page and extract dates."""
    html = fetch_url(url)
    if not html:
        return None
    
    # educounty pages have structured calendar tables
    # The readability extraction works well, but we have raw HTML
    # Let's extract the main content area and parse it
    
    # Simple HTML-to-text conversion for date extraction
    text = html
    # Remove script/style
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.S|re.I)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.S|re.I)
    # Convert table cells to readable format
    text = re.sub(r'</?tr[^>]*>', '\n', text, flags=re.I)
    text = re.sub(r'</?td[^>]*>', ' | ', text, flags=re.I)
    text = re.sub(r'</?th[^>]*>', ' | ', text, flags=re.I)
    # Convert headings and paragraphs to newlines
    text = re.sub(r'<(?:h[1-6]|p|div|br|li)[^>]*>', '\n', text, flags=re.I)
    # Remove remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&#8211;', '–').replace('&#8212;', '—')
    text = re.sub(r'&[a-z]+;', ' ', text)
    text = re.sub(r'&#\d+;', ' ', text)
    # Clean whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n', text)
    
    dates = extract_dates(text)
    return validate(dates)


def phase1_educounty(districts: list[dict], already_confirmed: set) -> dict:
    """Phase 1: Scrape educounty.net for all matching districts."""
    log("=" * 60)
    log("PHASE 1: educounty.net bulk scraping")
    log("=" * 60)
    
    # Get all educounty URLs
    ec_urls = fetch_all_educounty_urls()
    if not ec_urls:
        log("No URLs found from educounty.net sitemaps!")
        return {}
    
    # Match to districts
    unconfirmed = [d for d in districts if d['nces_leaid'] not in already_confirmed]
    matches = match_educounty_to_districts(ec_urls, unconfirmed)
    log(f"Matched {len(matches)} educounty URLs to unconfirmed districts")
    
    # Also try to match ALL URLs (even for confirmed districts, to get more data)
    all_matches = match_educounty_to_districts(ec_urls, districts)
    new_matches = {k: v for k, v in all_matches.items() if k not in already_confirmed}
    matches.update(new_matches)
    log(f"Total matches for unconfirmed districts: {len(matches)}")
    
    results = {}
    scraped = 0
    
    for leaid, url in matches.items():
        if leaid in already_confirmed:
            continue
        
        try:
            dates = scrape_educounty_page(url)
            if dates:
                results[leaid] = {
                    'dates': dates,
                    'source': 'educounty',
                    'url': url,
                }
                scraped += 1
                if scraped % 50 == 0:
                    log(f"  educounty: {scraped} scraped, {len(results)} confirmed so far")
            
            time.sleep(EDUCOUNTY_DELAY)
        except Exception as e:
            log(f"  Error scraping {url}: {e}")
    
    log(f"Phase 1 complete: {len(results)} new confirmed from educounty.net")
    return results


# ============================================================
# Phase 2: Brave Search
# ============================================================

def extract_dates_from_description(desc: str) -> dict:
    """Extract dates from Brave search result descriptions."""
    result = {}
    desc_lower = desc.lower()
    
    # "Spring Break is from March 9-13" or "Spring Break: March 16-20, 2026"
    sb_match = re.search(
        r'spring\s+break\s+(?:is\s+)?(?:from\s+)?(\w+)\s+(\d{1,2})\s*[-–to]+\s*(?:(\w+)\s+)?(\d{1,2})',
        desc, re.I
    )
    if sb_match:
        month1 = sb_match.group(1)
        day1 = sb_match.group(2)
        month2 = sb_match.group(3) or month1
        day2 = sb_match.group(4)
        d1 = parse_month_day(month1, day1)
        d2 = parse_month_day(month2, day2)
        if d1 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
            result['spring_break_start'] = d1.isoformat()
            result['spring_break_end'] = (d2 or d1).isoformat()
    
    # "First Day of School: August 19" or "School starts August 7"
    fd_match = re.search(
        r'(?:first\s+day\s+(?:of\s+)?school|school\s+(?:starts?|begins?))[:\s]+(\w+)\s+(\d{1,2})',
        desc, re.I
    )
    if fd_match:
        d = parse_month_day(fd_match.group(1), fd_match.group(2))
        if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
            result['first_day'] = d.isoformat()
    
    # "Last Day of School: May 28"
    ld_match = re.search(
        r'(?:last\s+day\s+(?:of\s+)?school|school\s+(?:ends?))[:\s]+(\w+)\s+(\d{1,2})',
        desc, re.I
    )
    if ld_match:
        d = parse_month_day(ld_match.group(1), ld_match.group(2))
        if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
            result['last_day'] = d.isoformat()
    
    # "Winter Break: December 22 - January 2"
    wb_match = re.search(
        r'(?:winter|christmas)\s+break[:\s]+(\w+)\s+(\d{1,2})\s*[-–to]+\s*(\w+)\s+(\d{1,2})',
        desc, re.I
    )
    if wb_match:
        d1 = parse_month_day(wb_match.group(1), wb_match.group(2))
        d2 = parse_month_day(wb_match.group(3), wb_match.group(4))
        if d1 and d1.month in (11, 12):
            result['winter_break_start'] = d1.isoformat()
            if d2:
                result['winter_break_end'] = d2.isoformat()
    
    return result


def phase2_brave_search(districts: list[dict], already_confirmed: set, phase1_results: dict) -> dict:
    """Phase 2: Use Brave Search to find calendar data for remaining districts."""
    log("=" * 60)
    log("PHASE 2: Brave Search + page scraping")
    log("=" * 60)
    
    # Sort unconfirmed by enrollment (highest first — biggest impact)
    unconfirmed = []
    for d in districts:
        leaid = d['nces_leaid']
        if leaid in already_confirmed or leaid in phase1_results:
            continue
        try:
            enroll = int(d.get('enrollment', 0) or 0)
        except (ValueError, TypeError):
            enroll = 0
        unconfirmed.append((enroll, d))
    
    unconfirmed.sort(key=lambda x: -x[0])
    log(f"Phase 2: {len(unconfirmed)} districts to search")
    
    results = {}
    searched = 0
    desc_hits = 0
    page_hits = 0
    
    for enrollment, d in unconfirmed:
        leaid = d['nces_leaid']
        name = d['district_name']
        state = d['state']
        
        query = f"{name} {state} school calendar 2025-2026"
        
        try:
            search_results = brave_search(query)
            time.sleep(BRAVE_DELAY)
        except Exception as e:
            log(f"  Search error for {name}: {e}")
            continue
        
        searched += 1
        
        # Strategy 1: Extract from search descriptions
        for sr in search_results:
            desc = sr.get('description', '') + ' ' + sr.get('title', '')
            desc_dates = extract_dates_from_description(desc)
            validated = validate(desc_dates)
            if validated:
                results[leaid] = {
                    'dates': validated,
                    'source': 'brave_description',
                    'url': sr.get('url', ''),
                    'query': query,
                }
                desc_hits += 1
                break
        
        if leaid in results:
            if searched % 100 == 0:
                log(f"  Brave: {searched} searched, {len(results)} confirmed (desc:{desc_hits} page:{page_hits})")
            continue
        
        # Strategy 2: Fetch and parse top educounty/schoolcalendarinfo results
        for sr in search_results[:3]:
            url = sr.get('url', '')
            url_lower = url.lower()
            
            # Only fetch known-good sources to be efficient
            if any(domain in url_lower for domain in ['educounty.net', 'schoolcalendarinfo.com', 'texasschools.us']):
                page_dates = scrape_educounty_page(url)  # works for any HTML
                if page_dates:
                    results[leaid] = {
                        'dates': page_dates,
                        'source': f'brave_page_{url_lower.split("/")[2]}',
                        'url': url,
                        'query': query,
                    }
                    page_hits += 1
                    time.sleep(EDUCOUNTY_DELAY)
                    break
        
        if searched % 100 == 0:
            log(f"  Brave: {searched} searched, {len(results)} confirmed (desc:{desc_hits} page:{page_hits})")
        
        # Save incrementally
        if searched % SAVE_INTERVAL == 0:
            save_mega_results(results, f"phase2_checkpoint_{searched}")
    
    log(f"Phase 2 complete: {len(results)} new confirmed (desc:{desc_hits} page:{page_hits})")
    return results


# ============================================================
# Phase 3: State-level Inference
# ============================================================

def phase3_state_inference(districts: list[dict], all_confirmed: dict) -> dict:
    """Phase 3: For remaining districts, infer dates from same-state confirmed districts."""
    log("=" * 60)
    log("PHASE 3: State-level inference for remaining districts")
    log("=" * 60)
    
    # Build state -> confirmed dates lookup
    state_dates = defaultdict(list)
    for d in districts:
        leaid = d['nces_leaid']
        if leaid not in all_confirmed:
            continue
        state = d['state']
        
        # Get the dates for this confirmed district
        dates = None
        if leaid in all_confirmed:
            if isinstance(all_confirmed[leaid], dict):
                dates = all_confirmed[leaid].get('dates', all_confirmed[leaid])
            else:
                dates = all_confirmed[leaid]
        
        if not dates:
            # Try from the CSV directly
            dates = {}
            for field in ['spring_break_start', 'spring_break_end', 'winter_break_start', 
                         'winter_break_end', 'first_day', 'last_day']:
                if d.get(field):
                    dates[field] = d[field]
        
        if dates and ('spring_break_start' in dates or 'first_day' in dates):
            state_dates[state].append(dates)
    
    log(f"State date distributions from {sum(len(v) for v in state_dates.values())} confirmed districts across {len(state_dates)} states")
    
    # Calculate state medians
    state_medians = {}
    for state, date_list in state_dates.items():
        medians = {}
        for field in ['spring_break_start', 'spring_break_end', 'winter_break_start',
                      'winter_break_end', 'first_day', 'last_day']:
            values = []
            for d in date_list:
                if field in d and d[field]:
                    try:
                        values.append(date.fromisoformat(d[field]))
                    except (ValueError, TypeError):
                        pass
            if values:
                values.sort()
                median_idx = len(values) // 2
                medians[field] = values[median_idx].isoformat()
        
        if medians.get('spring_break_start') or medians.get('first_day'):
            state_medians[state] = medians
            # Add derived fields
            if 'first_day' in medians and 'last_day' in medians:
                medians['summer_start'] = medians['last_day']
                medians['summer_end'] = medians['first_day']
    
    log(f"Computed medians for {len(state_medians)} states")
    
    # Apply to unconfirmed
    results = {}
    for d in districts:
        leaid = d['nces_leaid']
        state = d['state']
        if leaid in all_confirmed:
            continue
        
        if state in state_medians:
            results[leaid] = {
                'dates': state_medians[state].copy(),
                'source': 'state_median_inference',
                'confidence': 'medium',
            }
    
    log(f"Phase 3 complete: {len(results)} districts filled with state median inference")
    return results


# ============================================================
# Results Management
# ============================================================

def load_mega_results() -> dict:
    if MEGA_RESULTS_FILE.exists():
        try:
            with open(MEGA_RESULTS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"phase1": {}, "phase2": {}, "phase3": {}, "stats": {}}


def save_mega_results(results: dict, checkpoint: str = ""):
    # Merge into main results file
    existing = load_mega_results()
    if isinstance(results, dict) and 'phase1' in results:
        existing.update(results)
    else:
        # It's a sub-result being saved as checkpoint
        existing[f'checkpoint_{checkpoint}'] = {
            'count': len(results),
            'timestamp': datetime.now().isoformat(),
        }
    with open(MEGA_RESULTS_FILE, "w") as f:
        json.dump(existing, f, indent=2, default=str)


def merge_to_csv(districts: list[dict], all_results: dict):
    """Merge all results back into districts_comprehensive.csv."""
    log("Merging results into districts_comprehensive.csv...")
    
    updated = 0
    for d in districts:
        leaid = d['nces_leaid']
        if leaid not in all_results:
            continue
        
        result = all_results[leaid]
        dates = result.get('dates', result)
        source = result.get('source', 'mega_scraper')
        confidence = result.get('confidence', 'confirmed')
        
        # Only update if currently not confirmed
        if d.get('confidence') == 'confirmed':
            continue
        
        # Update fields
        for field in ['spring_break_start', 'spring_break_end', 'winter_break_start',
                      'winter_break_end', 'first_day', 'last_day', 'summer_start', 'summer_end']:
            if field in dates and dates[field]:
                d[field] = dates[field]
        
        d['source'] = source
        d['confidence'] = confidence
        d['school_year'] = '2025-2026'
        updated += 1
    
    # Write back
    fieldnames = districts[0].keys()
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
    log("=" * 60)
    log("MEGA SCHOOL CALENDAR SCRAPER")
    log("=" * 60)
    
    # Load data
    districts = []
    with open(COMPREHENSIVE_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            districts.append(row)
    log(f"Loaded {len(districts)} districts")
    
    # Track what's already confirmed
    already_confirmed = set()
    for d in districts:
        if d.get('confidence') == 'confirmed':
            already_confirmed.add(d['nces_leaid'])
    log(f"Already confirmed: {len(already_confirmed)}")
    
    # Phase 1: educounty.net
    phase1_results = phase1_educounty(districts, already_confirmed)
    
    # Update confirmed set
    for leaid in phase1_results:
        already_confirmed.add(leaid)
    
    # Save phase 1
    mega_results = load_mega_results()
    mega_results['phase1'] = phase1_results
    mega_results['stats']['phase1_count'] = len(phase1_results)
    with open(MEGA_RESULTS_FILE, 'w') as f:
        json.dump(mega_results, f, indent=2, default=str)
    log(f"After Phase 1: {len(already_confirmed)} total confirmed")
    
    # Phase 2: Brave Search
    phase2_results = phase2_brave_search(districts, already_confirmed, phase1_results)
    
    for leaid in phase2_results:
        already_confirmed.add(leaid)
    
    mega_results['phase2'] = phase2_results
    mega_results['stats']['phase2_count'] = len(phase2_results)
    with open(MEGA_RESULTS_FILE, 'w') as f:
        json.dump(mega_results, f, indent=2, default=str)
    log(f"After Phase 2: {len(already_confirmed)} total confirmed")
    
    # Phase 3: State inference
    # Build unified confirmed dict for inference
    all_confirmed_data = {}
    for d in districts:
        if d['nces_leaid'] in already_confirmed:
            all_confirmed_data[d['nces_leaid']] = d
    
    phase3_results = phase3_state_inference(districts, already_confirmed)
    
    mega_results['phase3'] = phase3_results
    mega_results['stats']['phase3_count'] = len(phase3_results)
    
    # Merge all results
    all_results = {}
    all_results.update(phase1_results)
    all_results.update(phase2_results)
    all_results.update(phase3_results)
    
    mega_results['stats']['total_new'] = len(all_results)
    mega_results['stats']['timestamp'] = datetime.now().isoformat()
    
    with open(MEGA_RESULTS_FILE, 'w') as f:
        json.dump(mega_results, f, indent=2, default=str)
    
    # Merge to CSV
    updated = merge_to_csv(districts, all_results)
    
    # Final stats
    confirmed_count = sum(1 for d in districts if d.get('confidence') == 'confirmed')
    medium_count = sum(1 for d in districts if d.get('confidence') == 'medium')
    total = len(districts)
    
    log("=" * 60)
    log("FINAL RESULTS")
    log(f"  Total districts: {total}")
    log(f"  Confirmed: {confirmed_count} ({confirmed_count*100/total:.1f}%)")
    log(f"  Medium confidence: {medium_count} ({medium_count*100/total:.1f}%)")
    log(f"  Confirmed + Medium: {confirmed_count + medium_count} ({(confirmed_count + medium_count)*100/total:.1f}%)")
    log(f"  Phase 1 (educounty): {len(phase1_results)}")
    log(f"  Phase 2 (Brave): {len(phase2_results)}")
    log(f"  Phase 3 (inference): {len(phase3_results)}")
    log("=" * 60)


if __name__ == '__main__':
    main()
