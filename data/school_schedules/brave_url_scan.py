#!/usr/bin/env python3
"""Brave URL Scanner — Find calendar URLs for unfound districts.

Searches Brave for each unfound district, collects the top results,
categorizes them (PDF / calendar page / generic / aggregator), and
saves to a JSON file for review before spending Firecrawl credits.

Usage:
    python3 brave_url_scan.py                    # Scan all unfound
    python3 brave_url_scan.py --max 100          # Test with 100
    python3 brave_url_scan.py --resume           # Resume from checkpoint
    python3 brave_url_scan.py --report           # Just print stats from saved results
"""

import argparse
import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
NCES_FILE = BASE_DIR / "nces_all_districts.csv"
LLM_RESULTS = BASE_DIR / "llm_scraper_results.json"
V2_RESULTS = BASE_DIR / "pipeline_v2_results.json"
OUTPUT_FILE = BASE_DIR / "brave_url_scan_results.json"

BRAVE_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")
RATE_LIMIT = 1.1  # seconds between calls

CAL_KEYWORDS = ['calendar', 'schedule', 'school-year', 'dates', 'academic-calendar',
                'student-calendar', 'school_calendar', 'schoolcalendar']
AGGREGATOR_DOMAINS = ['californiaschools.us', 'illinoisschools.us', 'educounty.net',
                      'publicschoolreview.com', 'niche.com', 'greatschools.org',
                      'usnews.com', 'schooldigger.com']


def load_already_found() -> set:
    """Load NCES IDs of districts we already have data for."""
    found = set()
    
    if LLM_RESULTS.exists():
        with open(LLM_RESULTS) as f:
            for k, v in json.load(f).items():
                if v.get('status') == 'found':
                    found.add(k)
    
    if V2_RESULTS.exists():
        with open(V2_RESULTS) as f:
            for k, v in json.load(f).items():
                if v.get('status') == 'found':
                    found.add(k)
    
    return found


def load_districts() -> list:
    """Load all NCES districts."""
    districts = []
    with open(NCES_FILE) as f:
        for r in csv.DictReader(f):
            districts.append(r)
    return districts


def brave_search(query: str) -> list:
    """Search Brave and return results."""
    params = urllib.parse.urlencode({'q': query, 'count': 5})
    url = f"https://api.search.brave.com/res/v1/web/search?{params}"
    
    req = urllib.request.Request(url, headers={
        'Accept': 'application/json',
        'X-Subscription-Token': BRAVE_API_KEY,
    })
    
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return data.get('web', {}).get('results', [])
    except Exception as e:
        print(f"  Brave error: {e}")
        return []


def categorize_url(url: str, title: str) -> str:
    """Categorize a URL as pdf/calendar/aggregator/generic."""
    url_lower = url.lower()
    title_lower = title.lower()
    
    # PDF
    if url_lower.endswith('.pdf') or ('pdf' in title_lower and 'calendar' in title_lower):
        return 'pdf'
    
    # Aggregator
    for domain in AGGREGATOR_DOMAINS:
        if domain in url_lower:
            return 'aggregator'
    
    # Calendar-specific page
    if any(k in url_lower for k in CAL_KEYWORDS):
        return 'calendar'
    
    # Title mentions calendar but URL doesn't
    if 'calendar' in title_lower or 'schedule' in title_lower:
        return 'calendar_likely'
    
    return 'generic'


def scan_district(district: dict) -> dict:
    """Search Brave for a district's calendar URL."""
    name = district['lea_name']
    state = district.get('st', '')
    nces_id = district['leaid']
    
    # Try focused search
    clean_name = re.sub(r'\s*\(.*?\)', '', name)
    query = f'"{clean_name}" "2025-2026" school calendar'
    
    results = brave_search(query)
    
    if not results:
        return {
            'nces_id': nces_id,
            'name': name,
            'state': state,
            'status': 'no_results',
            'urls': [],
            'best_category': 'none',
            'query': query,
            'timestamp': datetime.now().isoformat()
        }
    
    urls = []
    for r in results[:3]:
        url = r.get('url', '')
        title = r.get('title', '')
        category = categorize_url(url, title)
        urls.append({
            'url': url,
            'title': title,
            'category': category,
        })
    
    # Best category (priority: pdf > calendar > calendar_likely > aggregator > generic)
    priority = {'pdf': 0, 'calendar': 1, 'calendar_likely': 2, 'aggregator': 3, 'generic': 4}
    best = min(urls, key=lambda u: priority.get(u['category'], 99))
    
    return {
        'nces_id': nces_id,
        'name': name,
        'state': state,
        'status': 'found',
        'urls': urls,
        'best_url': best['url'],
        'best_title': best['title'],
        'best_category': best['category'],
        'query': query,
        'timestamp': datetime.now().isoformat()
    }


def print_report(results: dict):
    """Print summary statistics."""
    total = len(results)
    
    categories = {}
    for r in results.values():
        cat = r.get('best_category', 'none')
        categories[cat] = categories.get(cat, 0) + 1
    
    print("\n" + "=" * 60)
    print("BRAVE URL SCAN — SUMMARY")
    print("=" * 60)
    print(f"Total scanned: {total:,}")
    print()
    
    for cat in ['pdf', 'calendar', 'calendar_likely', 'aggregator', 'generic', 'none']:
        n = categories.get(cat, 0)
        pct = n / total * 100 if total > 0 else 0
        emoji = {'pdf': '📄', 'calendar': '📅', 'calendar_likely': '📋', 
                 'aggregator': '🌐', 'generic': '🏠', 'none': '❌'}.get(cat, '?')
        label = {'pdf': 'PDF (free download)', 'calendar': 'Calendar page (targeted)',
                 'calendar_likely': 'Likely calendar (from title)', 'aggregator': 'Aggregator site',
                 'generic': 'Generic/homepage', 'none': 'No results'}.get(cat, cat)
        print(f"  {emoji} {label}: {n:,} ({pct:.1f}%)")
    
    # Firecrawl estimate
    pdf = categories.get('pdf', 0)
    cal = categories.get('calendar', 0)
    cal_likely = categories.get('calendar_likely', 0)
    agg = categories.get('aggregator', 0)
    
    print()
    print("FIRECRAWL CREDIT ESTIMATE:")
    print(f"  Free (PDFs, no Firecrawl needed): {pdf:,}")
    print(f"  High-confidence Firecrawl targets: {cal + cal_likely:,}")
    print(f"  Aggregator (might work without Firecrawl): {agg:,}")
    print(f"  Skip (generic + no results): {categories.get('generic', 0) + categories.get('none', 0):,}")
    print(f"  → Recommended Firecrawl budget: {cal + cal_likely:,} credits")
    
    # By state
    by_state = {}
    for r in results.values():
        st = r.get('state', '??')
        if st not in by_state:
            by_state[st] = {'total': 0, 'found': 0}
        by_state[st]['total'] += 1
        if r.get('status') == 'found':
            by_state[st]['found'] += 1
    
    print()
    print("TOP 10 STATES (unfound districts):")
    top = sorted(by_state.items(), key=lambda x: -x[1]['total'])[:10]
    for st, counts in top:
        print(f"  {st}: {counts['total']:,} scanned, {counts['found']:,} URLs found")
    
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--max', type=int, help='Max districts to scan')
    parser.add_argument('--resume', action='store_true', help='Resume from saved results')
    parser.add_argument('--report', action='store_true', help='Print report only')
    args = parser.parse_args()
    
    # Report mode
    if args.report:
        if OUTPUT_FILE.exists():
            with open(OUTPUT_FILE) as f:
                results = json.load(f)
            print_report(results)
        else:
            print("No results file found. Run scan first.")
        return
    
    if not BRAVE_API_KEY:
        print("ERROR: BRAVE_SEARCH_API_KEY not set")
        return
    
    # Load existing results for resume
    existing = {}
    if args.resume and OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)
        print(f"Loaded {len(existing):,} existing results")
    
    # Load districts
    found_ids = load_already_found()
    all_districts = load_districts()
    
    # Filter to unfound only
    unfound = [d for d in all_districts if d['leaid'] not in found_ids]
    print(f"Total unfound districts: {len(unfound):,}")
    
    # Skip already scanned
    if args.resume:
        unfound = [d for d in unfound if d['leaid'] not in existing]
        print(f"After resume filter: {len(unfound):,} remaining")
    
    if args.max:
        unfound = unfound[:args.max]
    
    print(f"Will scan: {len(unfound):,} districts")
    print(f"Estimated time: {len(unfound) * RATE_LIMIT / 60:.0f} minutes")
    print()
    
    results = dict(existing)
    
    for i, d in enumerate(unfound, 1):
        result = scan_district(d)
        results[d['leaid']] = result
        
        status = result['best_category']
        emoji = {'pdf': '📄', 'calendar': '📅', 'calendar_likely': '📋',
                 'aggregator': '🌐', 'generic': '🏠', 'none': '❌'}.get(status, '?')
        
        print(f"[{i}/{len(unfound)}] {emoji} {d['lea_name']} ({d['st']}) → {status}")
        
        # Save checkpoint every 100
        if i % 100 == 0:
            with open(OUTPUT_FILE, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"  💾 Saved checkpoint ({len(results):,} total)")
        
        time.sleep(RATE_LIMIT)
    
    # Final save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    
    print_report(results)


if __name__ == '__main__':
    main()
