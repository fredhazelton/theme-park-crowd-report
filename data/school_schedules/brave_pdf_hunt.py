#!/usr/bin/env python3
"""Brave PDF Hunt — Find PDF calendar URLs for already-found districts.

For each district we already have data for, search Brave for a PDF version
of their calendar. PDFs can be downloaded directly without Firecrawl.

Usage:
    python3 brave_pdf_hunt.py                # Hunt for all found districts
    python3 brave_pdf_hunt.py --max 100      # Test with 100
    python3 brave_pdf_hunt.py --resume       # Resume from checkpoint
    python3 brave_pdf_hunt.py --report       # Print stats
"""

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
LLM_RESULTS = BASE_DIR / "llm_scraper_results.json"
OUTPUT_FILE = BASE_DIR / "brave_pdf_hunt_results.json"

BRAVE_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")
RATE_LIMIT = 1.1


def brave_search(query: str) -> list:
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
        return []


def hunt_pdf(name: str, state: str) -> dict:
    """Search for PDF calendar for a district."""
    clean = re.sub(r'\s*\(.*?\)', '', name)
    
    # Try PDF-focused search
    query = f'"{clean}" "2025-2026" school calendar PDF'
    results = brave_search(query)
    time.sleep(RATE_LIMIT)
    
    # Look for actual PDF URLs
    pdfs = []
    html_cals = []
    
    for r in results:
        url = r.get('url', '')
        title = r.get('title', '')
        
        if url.lower().endswith('.pdf'):
            pdfs.append({'url': url, 'title': title})
        elif any(k in url.lower() for k in ['calendar', 'schedule', 'school-year']):
            html_cals.append({'url': url, 'title': title})
    
    if pdfs:
        return {
            'status': 'pdf_found',
            'pdf_url': pdfs[0]['url'],
            'pdf_title': pdfs[0]['title'],
            'all_pdfs': pdfs[:3],
            'query': query,
        }
    elif html_cals:
        return {
            'status': 'html_only',
            'best_url': html_cals[0]['url'],
            'best_title': html_cals[0]['title'],
            'query': query,
        }
    elif results:
        return {
            'status': 'generic_only',
            'best_url': results[0].get('url', ''),
            'best_title': results[0].get('title', ''),
            'query': query,
        }
    else:
        return {'status': 'no_results', 'query': query}


def print_report(results: dict):
    total = len(results)
    cats = {}
    for r in results.values():
        s = r.get('status', 'unknown')
        cats[s] = cats.get(s, 0) + 1
    
    print("\n" + "=" * 60)
    print("BRAVE PDF HUNT — SUMMARY")
    print("=" * 60)
    print(f"Total scanned: {total:,}")
    print()
    
    pdf = cats.get('pdf_found', 0)
    html = cats.get('html_only', 0)
    generic = cats.get('generic_only', 0)
    none = cats.get('no_results', 0)
    
    print(f"  📄 PDF found (free extract):      {pdf:,} ({pdf/total*100:.1f}%)")
    print(f"  📅 Calendar HTML (needs Firecrawl): {html:,} ({html/total*100:.1f}%)")
    print(f"  🏠 Generic only:                   {generic:,} ({generic/total*100:.1f}%)")
    print(f"  ❌ No results:                     {none:,} ({none/total*100:.1f}%)")
    print()
    print(f"→ {pdf:,} districts can be re-extracted for FREE via PDF")
    print(f"→ {html:,} districts need Firecrawl for HTML calendars")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--max', type=int)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args()
    
    if args.report:
        if OUTPUT_FILE.exists():
            with open(OUTPUT_FILE) as f:
                print_report(json.load(f))
        else:
            print("No results yet.")
        return
    
    if not BRAVE_API_KEY:
        print("ERROR: BRAVE_SEARCH_API_KEY not set")
        return
    
    # Load existing
    existing = {}
    if args.resume and OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)
        print(f"Loaded {len(existing):,} existing results")
    
    # Load found districts
    with open(LLM_RESULTS) as f:
        found = {k: v for k, v in json.load(f).items() if v.get('status') == 'found'}
    
    districts = [(k, v) for k, v in found.items() if k not in existing]
    print(f"Found districts to scan: {len(districts):,}")
    
    if args.max:
        districts = districts[:args.max]
    
    print(f"Will scan: {len(districts):,}")
    print(f"Estimated time: {len(districts) * RATE_LIMIT / 60:.0f} minutes")
    print()
    
    results = dict(existing)
    
    for i, (nid, dist) in enumerate(districts, 1):
        name = dist.get('name', '')
        state = dist.get('state', '')
        
        result = hunt_pdf(name, state)
        result['nces_id'] = nid
        result['name'] = name
        result['state'] = state
        result['old_url'] = dist.get('source_url') or dist.get('url', '')
        result['timestamp'] = datetime.now().isoformat()
        
        results[nid] = result
        
        emoji = {'pdf_found': '📄', 'html_only': '📅', 'generic_only': '🏠', 'no_results': '❌'}.get(result['status'], '?')
        print(f"[{i}/{len(districts)}] {emoji} {name} ({state}) → {result['status']}")
        
        if i % 100 == 0:
            with open(OUTPUT_FILE, 'w') as f:
                json.dump(results, f, indent=2)
            
            # Running stats
            pdf = sum(1 for r in results.values() if r.get('status') == 'pdf_found')
            print(f"  💾 Checkpoint: {len(results):,} total, {pdf:,} PDFs found ({pdf/len(results)*100:.0f}%)")
    
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    
    print_report(results)


if __name__ == '__main__':
    main()
