#!/usr/bin/env python3
"""
Expansion Scraper — Phase 2
Scrape ALL district pages from schoolcalendarinfo.com discovered via sitemap.
Reuses parsing logic from scraper.py.
Rate limited to 0.5s minimum between requests.
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

# Import parsing functions from Phase 1
sys.path.insert(0, str(Path(__file__).parent))
from scraper import parse_calendar_text, parse_date

BASE_DIR = Path(__file__).parent
SITEMAP_FILE = BASE_DIR / 'sitemap_districts.json'
OUTPUT_CSV = BASE_DIR / 'districts_all.csv'
RESULTS_FILE = BASE_DIR / 'expand_results.json'
TOP100_CSV = BASE_DIR / 'districts_top100.csv'

TARGET_YEAR = "2025-2026"
RATE_LIMIT = 0.6  # seconds between requests


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


def extract_district_name_from_html(html):
    """Extract district name from the page title or H1."""
    # Try <title>
    title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
    if title_match:
        title = title_match.group(1)
        # Remove common suffixes
        for suffix in [' Calendar with Holidays', ' Calendar With Holidays', 
                       ' Calendar with holidays', ' - School Calendar Info',
                       ' | School Calendar Info', ' Calendar']:
            title = title.replace(suffix, '')
        return title.strip()
    
    # Try <h1>
    h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
    if h1_match:
        return h1_match.group(1).strip()
    
    return None


def extract_state_from_html(html):
    """Try to extract state from page content."""
    # Look for state mentions near "school district" or in breadcrumbs
    # Common pattern: "X School District, State" or "located in State"
    text_ext = TextExtractor()
    text_ext.feed(html)
    text = text_ext.get_text()
    
    # List of US states
    states = [
        'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado',
        'Connecticut', 'Delaware', 'Florida', 'Georgia', 'Hawaii', 'Idaho',
        'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana',
        'Maine', 'Maryland', 'Massachusetts', 'Michigan', 'Minnesota',
        'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada',
        'New Hampshire', 'New Jersey', 'New Mexico', 'New York',
        'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon',
        'Pennsylvania', 'Rhode Island', 'South Carolina', 'South Dakota',
        'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington',
        'West Virginia', 'Wisconsin', 'Wyoming', 'District of Columbia'
    ]
    
    # Look for state in first 2000 chars (usually in intro paragraph)
    intro = text[:3000]
    for state in states:
        if state in intro:
            return state
    
    return ''


def extract_available_years(text):
    """Find which school years have data on the page."""
    years = re.findall(r'(20\d{2}-20\d{2}) School Calendar', text)
    return list(set(years))


def fetch_and_parse(url):
    """Fetch a district page and parse calendar data."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=20) as response:
            html = response.read().decode('utf-8', errors='replace')
        
        # Extract metadata
        district_name = extract_district_name_from_html(html)
        state = extract_state_from_html(html)
        
        # Convert to text for calendar parsing
        extractor = TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()
        
        # Find available years
        available_years = extract_available_years(text)
        
        # Parse 2025-2026 data
        data = parse_calendar_text(text, TARGET_YEAR)
        has_data = any(v for v in data.values())
        
        # Also try 2024-2025 if available (for historical track)
        data_2024 = parse_calendar_text(text, "2024-2025")
        has_2024 = any(v for v in data_2024.values())
        
        return {
            'status': 'success' if has_data else 'no_2025_data',
            'url': url,
            'district_name': district_name or '',
            'state': state,
            'data_2025_2026': data if has_data else {},
            'data_2024_2025': data_2024 if has_2024 else {},
            'available_years': available_years,
            'has_2025_data': has_data,
            'has_2024_data': has_2024,
            'http_status': 200,
        }
        
    except urllib.error.HTTPError as e:
        return {
            'status': 'http_error',
            'url': url,
            'http_status': e.code,
            'error': str(e),
        }
    except Exception as e:
        return {
            'status': 'error',
            'url': url,
            'error': str(e),
        }


def load_top100_slugs():
    """Load the slugs we already have in top100 to avoid duplication."""
    existing = set()
    if TOP100_CSV.exists():
        with open(TOP100_CSV) as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get('calendar_url', '')
                if 'schoolcalendarinfo.com' in url:
                    slug = url.rstrip('/').split('/')[-1]
                    existing.add(slug)
    return existing


def main():
    # Load sitemap URLs
    with open(SITEMAP_FILE) as f:
        sitemap = json.load(f)
    
    districts = sitemap['districts']
    print(f"Total district URLs from sitemap: {len(districts)}")
    
    # Load existing top100 slugs
    top100_slugs = load_top100_slugs()
    print(f"Already in top100: {len(top100_slugs)} districts")
    
    # Check for previous progress (resume support)
    results = {}
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            results = json.load(f)
        print(f"Resuming: {len(results)} already scraped")
    
    # Scrape all districts
    success_2025 = 0
    success_2024 = 0
    no_data = 0
    errors = 0
    skipped = 0
    
    for i, district in enumerate(districts, 1):
        url = district['url']
        slug = district['slug']
        
        # Skip if already done
        if slug in results:
            r = results[slug]
            if r.get('has_2025_data'):
                success_2025 += 1
            if r.get('has_2024_data'):
                success_2024 += 1
            if r.get('status') in ('no_2025_data',):
                no_data += 1
            if r.get('status') in ('http_error', 'error'):
                errors += 1
            skipped += 1
            continue
        
        print(f"[{i:3d}/{len(districts)}] {slug}...", end=" ", flush=True)
        
        result = fetch_and_parse(url)
        results[slug] = result
        
        if result.get('has_2025_data'):
            d = result['data_2025_2026']
            print(f"✅ 2025-26: Spring={d.get('spring_break_start','?')}", end="")
            success_2025 += 1
        else:
            status = result.get('status', '?')
            if status == 'no_2025_data':
                avail = result.get('available_years', [])
                print(f"⚠️  No 2025-26 (has: {', '.join(avail) if avail else 'none'})", end="")
                no_data += 1
            else:
                print(f"❌ {result.get('http_status', '?')} {result.get('error', '')[:50]}", end="")
                errors += 1
        
        if result.get('has_2024_data'):
            print(" +2024", end="")
            success_2024 += 1
        
        print()
        
        # Save progress every 50
        if i % 50 == 0:
            with open(RESULTS_FILE, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"  [Progress saved: {len(results)} results]")
        
        time.sleep(RATE_LIMIT)
    
    # Final save
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"Total districts:     {len(districts)}")
    print(f"Skipped (cached):    {skipped}")
    print(f"2025-26 data:        {success_2025}")
    print(f"2024-25 data:        {success_2024}")
    print(f"No 2025-26 data:     {no_data}")
    print(f"Errors:              {errors}")
    
    # Build the CSV
    build_csv(results)


def build_csv(results):
    """Build districts_all.csv from scrape results."""
    rows = []
    for slug, result in results.items():
        if not result.get('has_2025_data'):
            continue
        
        data = result['data_2025_2026']
        row = {
            'district_name': result.get('district_name', slug),
            'state': result.get('state', ''),
            'source_url': result.get('url', ''),
            'source_slug': slug,
            'spring_break_start': data.get('spring_break_start', ''),
            'spring_break_end': data.get('spring_break_end', ''),
            'winter_break_start': data.get('winter_break_start', ''),
            'winter_break_end': data.get('winter_break_end', ''),
            'summer_start': data.get('summer_start', ''),
            'summer_end': data.get('summer_end', ''),
            'first_day': data.get('first_day', ''),
            'last_day': data.get('last_day', ''),
            'school_year': '2025-2026',
            'last_updated': datetime.now().strftime('%Y-%m-%d'),
        }
        rows.append(row)
    
    # Sort by district name
    rows.sort(key=lambda r: r['district_name'])
    
    fieldnames = ['district_name', 'state', 'source_url', 'source_slug',
                  'spring_break_start', 'spring_break_end',
                  'winter_break_start', 'winter_break_end',
                  'summer_start', 'summer_end', 'first_day', 'last_day',
                  'school_year', 'last_updated']
    
    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"\nCSV written: {OUTPUT_CSV}")
    print(f"Districts with 2025-26 data: {len(rows)}")


if __name__ == "__main__":
    main()
