#!/usr/bin/env python3
"""
Fetch school calendar data from schoolcalendarinfo.com for top 100 US districts.
Uses simple HTTP requests + regex parsing. No Firecrawl credits needed!
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

# Import our scraper module
sys.path.insert(0, str(Path(__file__).parent))
from scraper import DISTRICT_SLUGS, parse_calendar_text, parse_date

BASE_URL = "https://schoolcalendarinfo.com"
CSV_PATH = Path(__file__).parent / "districts_top100.csv"
RESULTS_PATH = Path(__file__).parent / "fetch_results.json"

TARGET_YEAR = "2025-2026"


class TextExtractor(HTMLParser):
    """Simple HTML to text converter for parsing schoolcalendarinfo.com pages."""
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.skip_tags = {'script', 'style', 'noscript'}
        self.current_skip = 0
        
    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.current_skip += 1
        # Add newlines for block elements
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'tr', 'li', 'br'):
            self.text_parts.append('\n')
        if tag in ('td', 'th'):
            self.text_parts.append('')  # no separator needed, text runs together like in readability
            
    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.current_skip = max(0, self.current_skip - 1)
            
    def handle_data(self, data):
        if self.current_skip == 0:
            self.text_parts.append(data)
            
    def get_text(self):
        return ''.join(self.text_parts)


def fetch_district_calendar(district_name, slug):
    """Fetch and parse calendar data for a single district."""
    url = f"{BASE_URL}/{slug}/"
    
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8', errors='replace')
            
        # Convert HTML to text
        extractor = TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()
        
        # Parse the calendar data
        result = parse_calendar_text(text, TARGET_YEAR)
        
        # Check if we got any data
        has_data = any(v for v in result.values())
        
        return {
            'status': 'success' if has_data else 'no_data',
            'url': url,
            'data': result,
            'http_status': 200,
        }
        
    except urllib.error.HTTPError as e:
        return {
            'status': 'http_error',
            'url': url,
            'http_status': e.code,
            'error': str(e),
            'data': {},
        }
    except Exception as e:
        return {
            'status': 'error',
            'url': url,
            'error': str(e),
            'data': {},
        }


def update_csv(results):
    """Update the CSV file with fetched calendar data."""
    # Read existing CSV
    rows = []
    with open(CSV_PATH, 'r') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
    
    # Ensure we have all needed columns
    needed_cols = ['calendar_url', 'spring_break_start', 'spring_break_end', 
                   'winter_break_start', 'winter_break_end', 'summer_start', 
                   'summer_end', 'last_updated']
    
    # Update rows with fetched data
    updated_count = 0
    for row in rows:
        district_name = row['district_name']
        if district_name in results and results[district_name]['status'] == 'success':
            data = results[district_name]['data']
            row['calendar_url'] = results[district_name]['url']
            row['spring_break_start'] = data.get('spring_break_start', '')
            row['spring_break_end'] = data.get('spring_break_end', '')
            row['winter_break_start'] = data.get('winter_break_start', '')
            row['winter_break_end'] = data.get('winter_break_end', '')
            row['summer_start'] = data.get('summer_start', '')
            row['summer_end'] = data.get('summer_end', '')
            row['last_updated'] = datetime.now().strftime('%Y-%m-%d')
            updated_count += 1
    
    # Write updated CSV
    with open(CSV_PATH, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    return updated_count


def main():
    print(f"Fetching school calendars for {len(DISTRICT_SLUGS)} districts...")
    print(f"Target year: {TARGET_YEAR}")
    print(f"Source: {BASE_URL}")
    print("=" * 60)
    
    results = {}
    success = 0
    no_data = 0
    errors = 0
    
    for i, (district_name, slug) in enumerate(DISTRICT_SLUGS.items(), 1):
        print(f"[{i:3d}/{len(DISTRICT_SLUGS)}] {district_name}...", end=" ", flush=True)
        
        result = fetch_district_calendar(district_name, slug)
        results[district_name] = result
        
        if result['status'] == 'success':
            data = result['data']
            print(f"✅ Spring: {data.get('spring_break_start', 'N/A')}, Winter: {data.get('winter_break_start', 'N/A')}")
            success += 1
        elif result['status'] == 'no_data':
            print(f"⚠️  Page found but no {TARGET_YEAR} data parsed")
            no_data += 1
        else:
            print(f"❌ {result.get('http_status', '?')} - {result.get('error', 'unknown')}")
            errors += 1
        
        # Be polite - don't hammer the server
        time.sleep(0.5)
    
    print("\n" + "=" * 60)
    print(f"Results: {success} success, {no_data} no data, {errors} errors")
    print(f"Success rate: {success}/{len(DISTRICT_SLUGS)} = {success*100/len(DISTRICT_SLUGS):.1f}%")
    
    # Save raw results
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nRaw results saved to: {RESULTS_PATH}")
    
    # Update CSV
    updated = update_csv(results)
    print(f"CSV updated: {updated} districts with data")
    print(f"CSV path: {CSV_PATH}")
    
    # Print districts with no data for manual follow-up
    if no_data + errors > 0:
        print(f"\n{'='*60}")
        print("Districts needing manual follow-up:")
        for name, result in results.items():
            if result['status'] != 'success':
                print(f"  - {name}: {result['status']} ({result.get('url', '')})")


if __name__ == "__main__":
    main()
