#!/usr/bin/env python3
"""
Wayback Batch Scraper
=====================
Uses the bulk CDX index to efficiently fetch archived pages from the Wayback Machine.
For each district, picks the BEST snapshot and parses ALL available school years.

Usage:
  python3 wayback_batch_scraper.py [--batch N] [--resume]
"""

import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from html.parser import HTMLParser
from collections import defaultdict

BASE_DIR = Path(__file__).parent
CDX_INDEX = BASE_DIR / 'cdx_bulk_index.json'
RESULTS_FILE = BASE_DIR / 'historical_wayback_scrape.json'
DISTRICTS_ALL = BASE_DIR / 'districts_all.csv'

TARGET_YEARS = ['2022-2023', '2023-2024', '2024-2025']
PAGE_RATE_LIMIT = 2.0

DATE_FORMATS = [
    "%a, %d %b %Y",
    "%a, %b %d %Y",
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
    if not date_str or not date_str.strip(): return None
    date_str = date_str.strip()
    for fmt in DATE_FORMATS:
        try: return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError: continue
    return None


def validate_dates(data, school_year):
    sy = int(school_year.split('-')[0])
    ey = int(school_year.split('-')[1])
    if data.get('spring_break_start'):
        try:
            sb = datetime.strptime(data['spring_break_start'], '%Y-%m-%d')
            if sb.year != ey or sb.month < 2 or sb.month > 5: return False
        except: return False
    if data.get('winter_break_start'):
        try:
            wb = datetime.strptime(data['winter_break_start'], '%Y-%m-%d')
            if wb.year != sy or wb.month not in (11, 12): return False
        except: return False
    if data.get('first_day'):
        try:
            fd = datetime.strptime(data['first_day'], '%Y-%m-%d')
            if fd.year != sy or fd.month < 7 or fd.month > 10: return False
        except: return False
    return True


def parse_all_years(text):
    results = {}
    date_pat = r'(\w{3},\s*\w{3}\s+\d{1,2}\s+\d{4}|\w{3},\s*\d{1,2}\s+\w{3}\s+\d{4})'
    lines = text.split('\n')
    
    sections = []
    for i, line in enumerate(lines):
        m = re.search(r'(20\d{2})[-–](20\d{2})\s+School\s+Calendar', line, re.IGNORECASE)
        if m:
            year = f"{m.group(1)}-{m.group(2)}"
            sections.append((i, year))
    
    for sec_idx, (start_line, school_year) in enumerate(sections):
        if school_year not in TARGET_YEARS: continue
        end_line = sections[sec_idx + 1][0] if sec_idx + 1 < len(sections) else len(lines)
        
        data = {k: '' for k in ['spring_break_start','spring_break_end','winter_break_start','winter_break_end','summer_start','summer_end','first_day','last_day']}
        
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
        
        filled = sum(1 for k in ['spring_break_start','winter_break_start','first_day','last_day'] if data.get(k))
        if filled >= 2 and validate_dates(data, school_year):
            results[school_year] = data
    
    return results


def fetch_wayback_page(timestamp, slug, retries=2):
    url = f"https://schoolcalendarinfo.com/{slug}/"
    wb_url = f"https://web.archive.org/web/{timestamp}/{url}"
    
    for attempt in range(retries):
        try:
            req = urllib.request.Request(wb_url, headers={'User-Agent': 'Mozilla/5.0 (research)'})
            with urllib.request.urlopen(req, timeout=60) as resp:
                html = resp.read().decode('utf-8', errors='replace')
            html = re.sub(r'<!-- BEGIN WAYBACK TOOLBAR INSERT -->.*?<!-- END WAYBACK TOOLBAR INSERT -->', '', html, flags=re.DOTALL)
            ext = TextExtractor()
            ext.feed(html)
            return ext.get_text()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                wait = (attempt + 1) * 30
                log(f"    WB {e.code} on {slug}, waiting {wait}s...")
                time.sleep(wait)
            else: return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(10)
    return None


def pick_best_snapshot(snapshots):
    """Pick the snapshot most likely to have the most school year data.
    Prefer snapshots from Sep-Nov (have current year data) and latest dates.
    """
    if not snapshots: return None
    
    # Group by digest (unique content)
    by_digest = {}
    for s in snapshots:
        if s['digest'] not in by_digest:
            by_digest[s['digest']] = s
    
    unique = list(by_digest.values())
    # Sort by timestamp descending — most recent first
    unique.sort(key=lambda s: s['timestamp'], reverse=True)
    
    # Return the most recent unique snapshot
    return unique[0] if unique else None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', type=int, default=0)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    
    log("Wayback Batch Scraper")
    log("=" * 60)
    
    # Load CDX index
    with open(CDX_INDEX) as f:
        cdx_index = json.load(f)
    log(f"CDX index: {len(cdx_index)} districts")
    
    # Load existing results
    results = {}
    if args.resume and RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            results = json.load(f)
        log(f"Resuming: {len(results)} already processed")
    
    slugs = sorted(cdx_index.keys())
    total = len(slugs)
    new_this_run = 0
    pages_fetched = 0
    records_found = 0
    start_time = time.time()
    
    for i, slug in enumerate(slugs):
        if slug in results:
            continue
        
        snapshots = cdx_index[slug]
        
        # Strategy: try up to 2 unique snapshots
        # First try the most recent, then if needed try an older one
        by_digest = {}
        for s in snapshots:
            if s['digest'] not in by_digest:
                by_digest[s['digest']] = s
        unique = sorted(by_digest.values(), key=lambda s: s['timestamp'], reverse=True)
        
        slug_results = {}
        years_found = set()
        
        for snap in unique[:2]:  # Max 2 page fetches per district
            if all(y in years_found for y in TARGET_YEARS[:2]):  # Focus on 2022-2023 and 2023-2024
                break
            
            text = fetch_wayback_page(snap['timestamp'], slug)
            pages_fetched += 1
            
            if text:
                year_data = parse_all_years(text)
                for year, data in year_data.items():
                    if year not in years_found:
                        slug_results[year] = {
                            'data': data,
                            'snapshot': snap['timestamp'],
                        }
                        years_found.add(year)
                        records_found += 1
            
            time.sleep(PAGE_RATE_LIMIT)
        
        results[slug] = slug_results
        new_this_run += 1
        
        if new_this_run % 10 == 0:
            processed = len(results)
            elapsed = time.time() - start_time
            rate = new_this_run / elapsed if elapsed > 0 else 0
            remaining = total - processed
            eta = remaining / rate / 60 if rate > 0 else 999
            log(f"  [{processed}/{total}] Pages:{pages_fetched} Records:{records_found} "
                f"Rate:{rate:.2f}/s ETA:{eta:.0f}min")
            
            with open(RESULTS_FILE, 'w') as f:
                json.dump(results, f)
        
        if args.batch and new_this_run >= args.batch:
            log(f"\nBatch limit ({args.batch}) reached.")
            break
    
    # Final save
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f)
    
    elapsed = time.time() - start_time
    log(f"\nComplete in {elapsed/60:.1f}min:")
    log(f"  Processed: {len(results)}/{total}")
    log(f"  Pages fetched: {pages_fetched}")
    log(f"  Records found: {records_found}")
    
    by_year = defaultdict(int)
    for v in results.values():
        for y in v:
            by_year[y] += 1
    for y in sorted(by_year):
        log(f"  {y}: {by_year[y]} districts")


if __name__ == "__main__":
    main()
