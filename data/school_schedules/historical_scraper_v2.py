#!/usr/bin/env python3
"""
Historical School Calendar Scraper v2
=====================================
Multi-angle collection of historical school calendar data.

Angle 1: Scrape current schoolcalendarinfo.com pages (fast, reliable)
  - Most pages have 2025-2026 AND 2024-2025 data
  - Uses urllib (no external deps)
  
Angle 2: Wayback Machine for older years (2022-2023, 2023-2024)
  - CDX API to find snapshots
  - Parse archived pages
  - Rate limited to respect archive.org

Usage:
  python3 historical_scraper_v2.py current          # Scrape current pages for 2024-2025
  python3 historical_scraper_v2.py wayback [--batch N] [--resume]  # Wayback for older years
  python3 historical_scraper_v2.py build             # Build output from all collected data
  python3 historical_scraper_v2.py all               # Everything
"""

import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from html.parser import HTMLParser
from collections import defaultdict

BASE_DIR = Path(__file__).parent
SITEMAP_FILE = BASE_DIR / 'sitemap_districts.json'
DISTRICTS_ALL = BASE_DIR / 'districts_all.csv'
DISTRICTS_COMPREHENSIVE = BASE_DIR / 'districts_comprehensive.csv'
EXISTING_HISTORICAL = BASE_DIR / 'districts_historical.csv'

# Storage files
CURRENT_SCRAPE_JSON = BASE_DIR / 'historical_current_scrape.json'
WAYBACK_SCRAPE_JSON = BASE_DIR / 'historical_wayback_scrape.json'
CDX_CACHE_JSON = BASE_DIR / 'cdx_cache.json'

# Output files
OUTPUT_CSV = BASE_DIR / 'districts_historical_all.csv'
AGGREGATE_CSV = BASE_DIR / 'historical_aggregate.csv'
RESULTS_JSON = BASE_DIR / 'historical_results.json'

# Config
CURRENT_RATE_LIMIT = 0.5  # seconds between current page fetches
WAYBACK_CDX_RATE = 3.0    # seconds between CDX queries
WAYBACK_PAGE_RATE = 2.0   # seconds between page fetches

TARGET_YEARS = ['2022-2023', '2023-2024', '2024-2025']

DATE_FORMATS = [
    "%a, %d %b %Y",   # Mon, 8 Aug 2022
    "%a, %b %d %Y",   # Mon, Aug 8 2022
    "%B %d, %Y",
    "%b %d, %Y",
    "%m/%d/%Y",
]


def log(msg):
    print(msg, flush=True)


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.skip_tags = {'script', 'style', 'noscript'}
        self.current_skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags: self.current_skip += 1
        if tag in ('h1','h2','h3','h4','h5','h6','p','div','tr','li','br'):
            self.text_parts.append('\n')
        if tag in ('td','th'):
            self.text_parts.append(' | ')
    def handle_endtag(self, tag):
        if tag in self.skip_tags: self.current_skip = max(0, self.current_skip - 1)
        if tag == 'tr': self.text_parts.append('\n')
    def handle_data(self, data):
        if self.current_skip == 0: self.text_parts.append(data)
    def get_text(self):
        return ''.join(self.text_parts)


def parse_date(date_str):
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_all_years_from_text(text, allowed_years=None):
    """
    Parse calendar data for ALL school years found in the text.
    Returns dict: {school_year: {field: value, ...}, ...}
    """
    results = {}
    date_pat = r'(\w{3},\s*\w{3}\s+\d{1,2}\s+\d{4}|\w{3},\s*\d{1,2}\s+\w{3}\s+\d{4})'
    
    lines = text.split('\n')
    
    # Find all school year section headers
    sections = []
    for i, line in enumerate(lines):
        m = re.search(r'(20\d{2})[-–](20\d{2})\s+School\s+Calendar', line, re.IGNORECASE)
        if m:
            year = f"{m.group(1)}-{m.group(2)}"
            sections.append((i, year))
    
    if not sections:
        return results
    
    for sec_idx, (start_line, school_year) in enumerate(sections):
        if allowed_years and school_year not in allowed_years:
            continue
        
        end_line = sections[sec_idx + 1][0] if sec_idx + 1 < len(sections) else len(lines)
        
        data = {
            'spring_break_start': '', 'spring_break_end': '',
            'winter_break_start': '', 'winter_break_end': '',
            'summer_start': '', 'summer_end': '',
            'first_day': '', 'last_day': '',
        }
        
        for i in range(start_line, end_line):
            line = lines[i].strip()
            ll = line.lower()
            
            if 'first day' in ll and 'school' in ll:
                m = re.search(date_pat, line)
                if m:
                    d = parse_date(m.group(1))
                    if d: data['first_day'] = d; data['summer_end'] = d
            
            if 'last day' in ll and 'school' in ll:
                m = re.search(date_pat, line)
                if m:
                    d = parse_date(m.group(1))
                    if d: data['last_day'] = d; data['summer_start'] = d
            
            if ('christmas' in ll or ('winter' in ll and 'mid' not in ll)) and 'break' in ll:
                dates = re.findall(date_pat, line)
                if len(dates) >= 2:
                    d1, d2 = parse_date(dates[0]), parse_date(dates[1])
                    if d1: data['winter_break_start'] = d1
                    if d2: data['winter_break_end'] = d2
                elif len(dates) == 1:
                    d = parse_date(dates[0])
                    if d: data['winter_break_start'] = d
            
            if 'spring break' in ll:
                dates = re.findall(date_pat, line)
                if len(dates) >= 2:
                    d1, d2 = parse_date(dates[0]), parse_date(dates[1])
                    if d1: data['spring_break_start'] = d1
                    if d2: data['spring_break_end'] = d2
                elif len(dates) == 1:
                    d = parse_date(dates[0])
                    if d: data['spring_break_start'] = d
        
        # Validate: need at least 2 key fields
        key_fields = ['spring_break_start', 'winter_break_start', 'first_day', 'last_day']
        filled = sum(1 for k in key_fields if data.get(k))
        if filled >= 2 and validate_dates(data, school_year):
            results[school_year] = data
    
    return results


def validate_dates(data, school_year):
    start_year = int(school_year.split('-')[0])
    end_year = int(school_year.split('-')[1])
    
    if data.get('spring_break_start'):
        try:
            sb = datetime.strptime(data['spring_break_start'], '%Y-%m-%d')
            if sb.year != end_year or sb.month < 2 or sb.month > 5:
                return False
        except: return False
    
    if data.get('winter_break_start'):
        try:
            wb = datetime.strptime(data['winter_break_start'], '%Y-%m-%d')
            if wb.year != start_year or wb.month not in (11, 12):
                return False
        except: return False
    
    if data.get('first_day'):
        try:
            fd = datetime.strptime(data['first_day'], '%Y-%m-%d')
            if fd.year != start_year or fd.month < 7 or fd.month > 10:
                return False
        except: return False
    
    return True


# ============================================================
# ANGLE 1: Current page scraping
# ============================================================

def fetch_current_page(slug):
    """Fetch current schoolcalendarinfo.com page."""
    url = f"https://schoolcalendarinfo.com/{slug}/"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode('utf-8', errors='replace')
        ext = TextExtractor()
        ext.feed(html)
        return ext.get_text()
    except Exception as e:
        return None


def scrape_current_pages(slugs, resume=False):
    """Scrape all current schoolcalendarinfo.com pages for 2024-2025 data."""
    log("\n" + "=" * 70)
    log("ANGLE 1: Scraping current pages for 2024-2025 data")
    log("=" * 70)
    
    results = {}
    if resume and CURRENT_SCRAPE_JSON.exists():
        with open(CURRENT_SCRAPE_JSON) as f:
            results = json.load(f)
        log(f"  Resuming: {len(results)} already scraped")
    
    total = len(slugs)
    new = 0
    found_2024 = 0
    errors = 0
    
    for i, slug in enumerate(slugs):
        if slug in results:
            if results[slug].get('2024-2025'):
                found_2024 += 1
            continue
        
        text = fetch_current_page(slug)
        new += 1
        
        if text:
            year_data = parse_all_years_from_text(text, allowed_years=['2024-2025'])
            if '2024-2025' in year_data:
                results[slug] = {'2024-2025': year_data['2024-2025']}
                found_2024 += 1
            else:
                results[slug] = {}
        else:
            results[slug] = {'error': True}
            errors += 1
        
        if new % 25 == 0:
            already_done = sum(1 for s in slugs if s in results)
            log(f"  [{already_done}/{total}] {found_2024} with 2024-2025 data, {errors} errors")
            with open(CURRENT_SCRAPE_JSON, 'w') as f:
                json.dump(results, f)
        
        time.sleep(CURRENT_RATE_LIMIT)
    
    # Save final
    with open(CURRENT_SCRAPE_JSON, 'w') as f:
        json.dump(results, f)
    
    total_with_2024 = sum(1 for v in results.values() if v.get('2024-2025'))
    log(f"\nCurrent page scrape complete:")
    log(f"  Total scraped: {len(results)}")
    log(f"  With 2024-2025 data: {total_with_2024}")
    log(f"  Errors: {errors}")
    
    return results


# ============================================================
# ANGLE 2: Wayback Machine scraping
# ============================================================

def get_cdx_snapshots(slug, retries=3):
    """Get all Wayback Machine snapshots for a district."""
    url = f"https://schoolcalendarinfo.com/{slug}/"
    cdx_url = (
        f"https://web.archive.org/cdx/search/cdx?url={url}"
        f"&output=json&from=20220101&to=20250101"
        f"&limit=15&filter=statuscode:200&filter=mimetype:text/html"
    )
    
    for attempt in range(retries):
        try:
            req = urllib.request.Request(cdx_url, headers={'User-Agent': 'Mozilla/5.0 (research)'})
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            if len(data) <= 1:
                return []
            return [{'timestamp': r[1], 'digest': r[5]} for r in data[1:]]
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                wait = (attempt + 1) * 20
                log(f"    CDX {e.code} for {slug}, waiting {wait}s...")
                time.sleep(wait)
            elif e.code == 404:
                return []
            else:
                return []
        except Exception:
            if attempt < retries - 1:
                time.sleep(10)
    return []


def fetch_wayback_page(timestamp, slug, retries=2):
    """Fetch archived page from Wayback Machine."""
    url = f"https://schoolcalendarinfo.com/{slug}/"
    wb_url = f"https://web.archive.org/web/{timestamp}/{url}"
    
    for attempt in range(retries):
        try:
            req = urllib.request.Request(wb_url, headers={'User-Agent': 'Mozilla/5.0 (research)'})
            with urllib.request.urlopen(req, timeout=60) as resp:
                html = resp.read().decode('utf-8', errors='replace')
            html = re.sub(
                r'<!-- BEGIN WAYBACK TOOLBAR INSERT -->.*?<!-- END WAYBACK TOOLBAR INSERT -->',
                '', html, flags=re.DOTALL
            )
            ext = TextExtractor()
            ext.feed(html)
            return ext.get_text()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                wait = (attempt + 1) * 25
                log(f"    WB {e.code}, waiting {wait}s...")
                time.sleep(wait)
            else: return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(10)
    return None


def scrape_wayback(slugs, resume=False, batch_size=0):
    """Scrape Wayback Machine for 2022-2023 and 2023-2024 data."""
    log("\n" + "=" * 70)
    log("ANGLE 2: Wayback Machine for 2022-2023, 2023-2024")
    log("=" * 70)
    
    # Load state
    results = {}
    cdx_cache = {}
    if resume:
        if WAYBACK_SCRAPE_JSON.exists():
            with open(WAYBACK_SCRAPE_JSON) as f:
                results = json.load(f)
        if CDX_CACHE_JSON.exists():
            with open(CDX_CACHE_JSON) as f:
                cdx_cache = json.load(f)
        log(f"  Resuming: {len(results)} processed, {len(cdx_cache)} CDX cached")
    
    target_wayback_years = ['2022-2023', '2023-2024']
    total = len(slugs)
    new_this_run = 0
    records_found = 0
    cdx_queries = 0
    pages_fetched = 0
    start_time = time.time()
    
    for i, slug in enumerate(slugs):
        if slug in results:
            continue
        
        # CDX query
        if slug in cdx_cache:
            snapshots = cdx_cache[slug]
        else:
            snapshots = get_cdx_snapshots(slug)
            cdx_cache[slug] = snapshots
            cdx_queries += 1
            time.sleep(WAYBACK_CDX_RATE)
        
        slug_results = {}
        
        if snapshots:
            # Pick best snapshots: one per year, prefer latest in each year
            by_year = defaultdict(list)
            for s in snapshots:
                y = s['timestamp'][:4]
                by_year[y].append(s)
            
            seen_digests = set()
            pages_to_try = []
            for y in sorted(by_year.keys(), reverse=True):
                for s in sorted(by_year[y], key=lambda x: x['timestamp'], reverse=True):
                    if s['digest'] not in seen_digests:
                        seen_digests.add(s['digest'])
                        pages_to_try.append(s)
                        break
            
            years_found = set()
            for snap in pages_to_try[:3]:
                if all(y in years_found for y in target_wayback_years):
                    break
                
                text = fetch_wayback_page(snap['timestamp'], slug)
                pages_fetched += 1
                
                if text:
                    year_data = parse_all_years_from_text(text, allowed_years=target_wayback_years)
                    for year, data in year_data.items():
                        if year not in years_found:
                            slug_results[year] = {
                                'data': data,
                                'snapshot': snap['timestamp'],
                            }
                            years_found.add(year)
                            records_found += 1
                
                time.sleep(WAYBACK_PAGE_RATE)
        
        results[slug] = slug_results
        new_this_run += 1
        
        # Progress
        if new_this_run % 10 == 0:
            processed = len(results)
            elapsed = time.time() - start_time
            rate = new_this_run / elapsed if elapsed > 0 else 0
            remaining = total - processed
            eta = remaining / rate / 60 if rate > 0 else 999
            log(f"  [{processed}/{total}] CDX:{cdx_queries} Pages:{pages_fetched} "
                f"Records:{records_found} Rate:{rate:.1f}/s ETA:{eta:.0f}min")
            
            # Save progress
            with open(WAYBACK_SCRAPE_JSON, 'w') as f:
                json.dump(results, f)
            with open(CDX_CACHE_JSON, 'w') as f:
                json.dump(cdx_cache, f)
        
        if batch_size and new_this_run >= batch_size:
            log(f"\nBatch limit ({batch_size}) reached.")
            break
    
    # Final save
    with open(WAYBACK_SCRAPE_JSON, 'w') as f:
        json.dump(results, f)
    with open(CDX_CACHE_JSON, 'w') as f:
        json.dump(cdx_cache, f)
    
    elapsed = time.time() - start_time
    log(f"\nWayback scrape complete in {elapsed/60:.1f}min:")
    log(f"  Processed: {len(results)}")
    log(f"  CDX queries: {cdx_queries}, Pages fetched: {pages_fetched}")
    log(f"  Records found: {records_found}")
    
    by_year_count = defaultdict(int)
    for v in results.values():
        for y in v:
            by_year_count[y] += 1
    for y in sorted(by_year_count):
        log(f"  {y}: {by_year_count[y]} districts")
    
    return results


# ============================================================
# BUILD: Combine all data into output files
# ============================================================

def build_outputs():
    """Build final output files from all collected data."""
    log("\n" + "=" * 70)
    log("BUILDING OUTPUT FILES")
    log("=" * 70)
    
    # Load lookups
    district_lookup = {}
    if DISTRICTS_ALL.exists():
        with open(DISTRICTS_ALL) as f:
            for row in csv.DictReader(f):
                slug = row.get('source_slug', '')
                if slug:
                    district_lookup[slug] = {
                        'name': row.get('district_name', ''),
                        'state': row.get('state', ''),
                    }
    
    nces_lookup = {}
    if DISTRICTS_COMPREHENSIVE.exists():
        with open(DISTRICTS_COMPREHENSIVE) as f:
            for row in csv.DictReader(f):
                name = row.get('district_name', '').lower().strip()
                state = row.get('state', '').strip()
                nces_lookup[f"{state}|{name}"] = {
                    'nces_leaid': row.get('nces_leaid', ''),
                    'enrollment': row.get('enrollment', ''),
                }
    
    all_records = []
    seen_keys = set()
    
    def add_record(slug, school_year, data, source):
        key = f"{slug}|{school_year}"
        if key in seen_keys:
            return
        seen_keys.add(key)
        
        info = district_lookup.get(slug, {'name': slug, 'state': ''})
        district_name = re.sub(r'\s+\d{4}-\d{4}.*$', '', info['name']).strip()
        state = info['state']
        
        nces_key = f"{state}|{district_name.lower()}"
        nces = nces_lookup.get(nces_key, {})
        
        all_records.append({
            'nces_leaid': nces.get('nces_leaid', ''),
            'district_name': district_name,
            'state': state,
            'enrollment': nces.get('enrollment', ''),
            'school_year': school_year,
            'spring_break_start': data.get('spring_break_start', ''),
            'spring_break_end': data.get('spring_break_end', ''),
            'winter_break_start': data.get('winter_break_start', ''),
            'winter_break_end': data.get('winter_break_end', ''),
            'summer_start': data.get('summer_start', ''),
            'summer_end': data.get('summer_end', ''),
            'first_day': data.get('first_day', ''),
            'last_day': data.get('last_day', ''),
            'source': source,
            'confidence': 'confirmed',
        })
    
    # Source 1: Current page scrape (2024-2025)
    if CURRENT_SCRAPE_JSON.exists():
        with open(CURRENT_SCRAPE_JSON) as f:
            current_data = json.load(f)
        for slug, year_data in current_data.items():
            if '2024-2025' in year_data:
                add_record(slug, '2024-2025', year_data['2024-2025'], 'schoolcalendarinfo.com:current')
        log(f"  Current scrape: {sum(1 for v in current_data.values() if '2024-2025' in v)} districts with 2024-2025")
    
    # Source 2: Existing historical CSV (2024-2025, might have some from expand)
    if EXISTING_HISTORICAL.exists():
        with open(EXISTING_HISTORICAL) as f:
            for row in csv.DictReader(f):
                slug = row.get('source_slug', '')
                year = row.get('school_year', '2024-2025')
                data = {k: row.get(k, '') for k in [
                    'spring_break_start', 'spring_break_end',
                    'winter_break_start', 'winter_break_end',
                    'summer_start', 'summer_end', 'first_day', 'last_day',
                ]}
                add_record(slug, year, data, row.get('source', 'schoolcalendarinfo.com'))
    
    # Source 3: Wayback Machine (2022-2023, 2023-2024)
    if WAYBACK_SCRAPE_JSON.exists():
        with open(WAYBACK_SCRAPE_JSON) as f:
            wayback_data = json.load(f)
        wb_count = 0
        for slug, year_data in wayback_data.items():
            for year, info in year_data.items():
                if isinstance(info, dict) and 'data' in info:
                    add_record(slug, year, info['data'], f"wayback:{info.get('snapshot', '')}")
                    wb_count += 1
        log(f"  Wayback scrape: {wb_count} year-records")
    
    # Sort
    all_records.sort(key=lambda r: (r['school_year'], r['state'], r['district_name']))
    
    # Write CSV
    fieldnames = ['nces_leaid', 'district_name', 'state', 'enrollment', 'school_year',
                  'spring_break_start', 'spring_break_end',
                  'winter_break_start', 'winter_break_end',
                  'summer_start', 'summer_end', 'first_day', 'last_day',
                  'source', 'confidence']
    
    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_records)
    
    # Stats
    by_year = defaultdict(lambda: {'count': 0, 'spring': 0, 'enrollment': 0})
    for r in all_records:
        by_year[r['school_year']]['count'] += 1
        if r.get('spring_break_start'): by_year[r['school_year']]['spring'] += 1
        try: by_year[r['school_year']]['enrollment'] += int(r.get('enrollment', 0))
        except: pass
    
    log(f"\nMaster CSV: {OUTPUT_CSV}")
    log(f"Total records: {len(all_records)}")
    for year in sorted(by_year):
        s = by_year[year]
        log(f"  {year}: {s['count']} districts, {s['spring']} with spring break, {s['enrollment']:,} enrollment")
    
    # Build aggregate
    build_daily_aggregate(all_records)
    
    # Save summary
    summary = {
        'timestamp': datetime.now().isoformat(),
        'total_records': len(all_records),
        'by_year': {y: dict(by_year[y]) for y in sorted(by_year)},
    }
    with open(RESULTS_JSON, 'w') as f:
        json.dump(summary, f, indent=2)
    log(f"Results JSON: {RESULTS_JSON}")
    
    return all_records


def build_daily_aggregate(records):
    """Build daily aggregate for break periods."""
    log("\nBuilding daily aggregate...")
    
    by_year = defaultdict(list)
    for r in records:
        by_year[r['school_year']].append(r)
    
    rows = []
    for school_year in sorted(by_year):
        recs = by_year[school_year]
        sy = int(school_year.split('-')[0])
        ey = int(school_year.split('-')[1])
        
        # Precompute break ranges
        districts = []
        for r in recs:
            enr = 0
            try: enr = int(r.get('enrollment', 0))
            except: pass
            if enr == 0: enr = 5000
            
            sb_start = sb_end = wb_start = wb_end = None
            try:
                if r.get('spring_break_start') and r.get('spring_break_end'):
                    sb_start = datetime.strptime(r['spring_break_start'], '%Y-%m-%d')
                    sb_end = datetime.strptime(r['spring_break_end'], '%Y-%m-%d')
            except: pass
            try:
                if r.get('winter_break_start') and r.get('winter_break_end'):
                    wb_start = datetime.strptime(r['winter_break_start'], '%Y-%m-%d')
                    wb_end = datetime.strptime(r['winter_break_end'], '%Y-%m-%d')
            except: pass
            
            districts.append({'enr': enr, 'sb_start': sb_start, 'sb_end': sb_end,
                            'wb_start': wb_start, 'wb_end': wb_end})
        
        # Only Nov - May (interesting period)
        current = datetime(sy, 11, 1)
        end = datetime(ey, 5, 31)
        
        while current <= end:
            on_spring = on_winter = total_enr = 0
            for d in districts:
                total_enr += d['enr']
                if d['sb_start'] and d['sb_end'] and d['sb_start'] <= current <= d['sb_end']:
                    on_spring += d['enr']
                if d['wb_start'] and d['wb_end'] and d['wb_start'] <= current <= d['wb_end']:
                    on_winter += d['enr']
            
            if total_enr > 0:
                rows.append({
                    'date': current.strftime('%Y-%m-%d'),
                    'school_year': school_year,
                    'day_of_week': current.strftime('%A'),
                    'districts_counted': len(districts),
                    'total_enrollment': total_enr,
                    'on_spring_break': on_spring,
                    'on_winter_break': on_winter,
                    'pct_spring_break': round(on_spring / total_enr * 100, 2),
                    'pct_winter_break': round(on_winter / total_enr * 100, 2),
                })
            current += timedelta(days=1)
    
    if rows:
        fieldnames = ['date', 'school_year', 'day_of_week', 'districts_counted',
                      'total_enrollment', 'on_spring_break', 'on_winter_break',
                      'pct_spring_break', 'pct_winter_break']
        with open(AGGREGATE_CSV, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        log(f"Aggregate CSV: {AGGREGATE_CSV} ({len(rows)} rows)")
        for year in sorted(by_year):
            year_rows = [r for r in rows if r['school_year'] == year and r['pct_spring_break'] > 0]
            if year_rows:
                peak = max(year_rows, key=lambda r: r['pct_spring_break'])
                log(f"  {year} spring break peak: {peak['date']} ({peak['pct_spring_break']}%)")


def load_sitemap():
    with open(SITEMAP_FILE) as f:
        data = json.load(f)
    return [d['slug'] for d in data['districts']]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['current', 'wayback', 'build', 'all'],
                       help='What to do')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--batch', type=int, default=0)
    args = parser.parse_args()
    
    log(f"Historical Scraper v2 — {args.command}")
    log(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    slugs = load_sitemap()
    log(f"Total districts: {len(slugs)}")
    
    if args.command in ('current', 'all'):
        scrape_current_pages(slugs, resume=args.resume)
    
    if args.command in ('wayback', 'all'):
        scrape_wayback(slugs, resume=args.resume, batch_size=args.batch)
    
    if args.command in ('build', 'all'):
        build_outputs()
    
    log(f"\nDone: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
