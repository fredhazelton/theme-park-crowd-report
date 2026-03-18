#!/usr/bin/env python3
"""
Historical Data Scraper — Phase 2 Track 2
Collects historical school calendar data from:
1. Current schoolcalendarinfo.com pages (many have 2024-2025 data)
2. Wayback Machine snapshots for older years (2022-2023, 2023-2024)

Rate limited: 1s between requests (more polite for Wayback Machine)
"""

import csv
import json
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from html.parser import HTMLParser

sys.path.insert(0, str(Path(__file__).parent))
from scraper import parse_calendar_text, parse_date

BASE_DIR = Path(__file__).parent
EXPAND_RESULTS = BASE_DIR / 'expand_results.json'
OUTPUT_CSV = BASE_DIR / 'districts_historical.csv'
HISTORICAL_RESULTS = BASE_DIR / 'historical_results.json'

WAYBACK_CDX_URL = "https://web.archive.org/cdx/search/cdx"
WAYBACK_BASE = "https://web.archive.org/web"

RATE_LIMIT = 1.0  # Longer rate limit for Wayback Machine


class TextExtractor(HTMLParser):
    """Simple HTML to text converter."""
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.skip_tags = {'script', 'style', 'noscript'}
        self.current_skip = 0
        
    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.current_skip += 1
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'tr', 'li', 'br'):
            self.text_parts.append('\n')
        if tag in ('td', 'th'):
            self.text_parts.append('')
            
    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.current_skip = max(0, self.current_skip - 1)
            
    def handle_data(self, data):
        if self.current_skip == 0:
            self.text_parts.append(data)
            
    def get_text(self):
        return ''.join(self.text_parts)


def collect_from_expand_results():
    """
    Extract 2024-2025 historical data from the expansion scraper results.
    Many pages already had 2024-2025 data that was parsed.
    """
    if not EXPAND_RESULTS.exists():
        print("No expand_results.json found — run expand_scraper.py first")
        return []
    
    with open(EXPAND_RESULTS) as f:
        results = json.load(f)
    
    historical = []
    for slug, result in results.items():
        if result.get('has_2024_data') and result.get('data_2024_2025'):
            data = result['data_2024_2025']
            historical.append({
                'district_name': result.get('district_name', slug),
                'state': result.get('state', ''),
                'source_slug': slug,
                'school_year': '2024-2025',
                'spring_break_start': data.get('spring_break_start', ''),
                'spring_break_end': data.get('spring_break_end', ''),
                'winter_break_start': data.get('winter_break_start', ''),
                'winter_break_end': data.get('winter_break_end', ''),
                'summer_start': data.get('summer_start', ''),
                'summer_end': data.get('summer_end', ''),
                'first_day': data.get('first_day', ''),
                'last_day': data.get('last_day', ''),
                'source': 'schoolcalendarinfo.com (current page)',
            })
    
    return historical


def get_wayback_snapshots(slug, year_prefix):
    """Get Wayback Machine snapshots for a given district and year."""
    url = f"https://schoolcalendarinfo.com/{slug}/"
    cdx_url = f"{WAYBACK_CDX_URL}?url={url}&output=json&from={year_prefix}0101&to={year_prefix}1231&limit=3"
    
    try:
        req = urllib.request.Request(cdx_url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode('utf-8'))
        
        # First row is header
        if len(data) <= 1:
            return []
        
        snapshots = []
        for row in data[1:]:
            if row[3] == 'text/html' and row[4] == '200':
                snapshots.append({
                    'timestamp': row[1],
                    'url': f"{WAYBACK_BASE}/{row[1]}/{url}",
                })
        return snapshots
        
    except Exception as e:
        return []


def fetch_wayback_page(wayback_url):
    """Fetch a page from the Wayback Machine."""
    try:
        req = urllib.request.Request(wayback_url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode('utf-8', errors='replace')
        
        # Remove Wayback Machine toolbar
        html = re.sub(r'<!-- BEGIN WAYBACK TOOLBAR INSERT -->.*?<!-- END WAYBACK TOOLBAR INSERT -->', '', html, flags=re.DOTALL)
        
        extractor = TextExtractor()
        extractor.feed(html)
        return extractor.get_text()
    except Exception as e:
        return None


def scrape_historical_from_wayback(slug, target_years):
    """
    For a given district, check Wayback Machine for historical snapshots
    and try to extract calendar data for target years.
    """
    results = {}
    
    for target_year in target_years:
        # Determine which calendar year to search for snapshots
        # 2022-2023 school year → search for snapshots in 2022 and early 2023
        start_year = target_year.split('-')[0]
        
        snapshots = get_wayback_snapshots(slug, start_year)
        if not snapshots:
            # Also try the second year
            end_year = target_year.split('-')[1]
            snapshots = get_wayback_snapshots(slug, end_year)
        
        if not snapshots:
            continue
        
        # Try the most recent snapshot for this year range
        for snapshot in snapshots:
            text = fetch_wayback_page(snapshot['url'])
            if not text:
                continue
            
            data = parse_calendar_text(text, target_year)
            has_data = any(v for v in data.values())
            
            if has_data:
                results[target_year] = {
                    'data': data,
                    'snapshot_url': snapshot['url'],
                    'timestamp': snapshot['timestamp'],
                }
                break  # Got data for this year, move on
            
            time.sleep(RATE_LIMIT)
    
    return results


def test_wayback_viability():
    """
    Test the Wayback Machine approach on a few districts to see if it's viable.
    """
    test_slugs = [
        'clark-county-school-district',
        'miami-dade-county-public-schools',
        'houston-independent-school-district',
        'fairfax-county-public-schools',
        'wake-county-public-schools',
    ]
    
    target_years = ['2023-2024', '2022-2023']
    
    print("Testing Wayback Machine viability...")
    print(f"Testing {len(test_slugs)} districts for years: {', '.join(target_years)}")
    print("=" * 60)
    
    viable_count = 0
    total_records = 0
    
    for slug in test_slugs:
        print(f"\n{slug}:")
        results = scrape_historical_from_wayback(slug, target_years)
        
        if results:
            viable_count += 1
            for year, data in results.items():
                spring = data['data'].get('spring_break_start', '?')
                print(f"  {year}: Spring={spring} (from {data['timestamp'][:8]})")
                total_records += 1
        else:
            print(f"  No historical data found")
        
        time.sleep(RATE_LIMIT)
    
    print(f"\n{'='*60}")
    print(f"Viability: {viable_count}/{len(test_slugs)} districts had historical data")
    print(f"Total records found: {total_records}")
    print(f"Verdict: {'VIABLE ✅' if viable_count >= 3 else 'NOT VIABLE ❌'}")
    
    return viable_count >= 3


def main():
    print("Historical Data Collection — Phase 2 Track 2")
    print("=" * 60)
    
    # Step 1: Collect 2024-2025 data from expansion scraper results
    print("\n1. Collecting 2024-2025 data from expansion results...")
    historical_2024 = collect_from_expand_results()
    print(f"   Found {len(historical_2024)} districts with 2024-2025 data")
    
    # Step 2: Test Wayback Machine viability
    print("\n2. Testing Wayback Machine for older years...")
    is_viable = test_wayback_viability()
    
    # Step 3: Save what we have
    all_historical = historical_2024
    
    # Sort by year then district
    all_historical.sort(key=lambda r: (r['school_year'], r['district_name']))
    
    fieldnames = ['district_name', 'state', 'source_slug', 'school_year',
                  'spring_break_start', 'spring_break_end',
                  'winter_break_start', 'winter_break_end',
                  'summer_start', 'summer_end', 'first_day', 'last_day',
                  'source']
    
    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_historical)
    
    print(f"\n{'='*60}")
    print(f"HISTORICAL DATA SUMMARY")
    print(f"{'='*60}")
    print(f"2024-2025 records: {len(historical_2024)}")
    print(f"Wayback Machine viable: {is_viable}")
    print(f"Total historical records saved: {len(all_historical)}")
    print(f"Output: {OUTPUT_CSV}")
    
    if is_viable:
        print(f"\n⚡ Wayback Machine IS viable for historical data!")
        print(f"   Next step: Run full Wayback scrape for all 660 districts")
        print(f"   Estimated time: ~30 min per year (at 1s rate limit)")
        print(f"   Priority years: 2023-2024, 2022-2023")


if __name__ == "__main__":
    main()
