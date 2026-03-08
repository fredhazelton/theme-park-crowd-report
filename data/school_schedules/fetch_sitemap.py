#!/usr/bin/env python3
"""Fetch and parse the full sitemap from schoolcalendarinfo.com to discover all district pages."""

import urllib.request
import re
import json
from pathlib import Path

def fetch_sitemap():
    url = "https://schoolcalendarinfo.com/post-sitemap.xml"
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        xml = response.read().decode('utf-8')
    return xml

def parse_urls(xml):
    """Extract all <loc> URLs from sitemap XML."""
    urls = re.findall(r'<loc>(https://schoolcalendarinfo\.com/[^<]+)</loc>', xml)
    return urls

def classify_url(url):
    """Determine if a URL is likely a district page vs other content."""
    slug = url.rstrip('/').split('/')[-1]
    
    # Skip the homepage
    if url == 'https://schoolcalendarinfo.com/' or slug == '':
        return 'homepage', slug
    
    # Skip URLs that look like generic content pages
    skip_patterns = [
        'calendar-holidays-',
        'michigan-center-schools-calendar-holidays',
        'loudoun-county-public-schools-calendar-holidays',
    ]
    for pattern in skip_patterns:
        if pattern in slug:
            return 'other', slug
    
    # District pages typically end with school-district, public-schools, county-schools, etc.
    district_patterns = [
        'school-district', 'public-schools', 'county-schools', 'city-schools',
        'independent-school-district', 'unified-school-district', 'schools',
        'department-of-education', 'charter-schools', 'isd', 'school'
    ]
    
    for pattern in district_patterns:
        if pattern in slug:
            return 'district', slug
    
    # If no pattern matches, still likely a district page (most content on this site is)
    return 'likely_district', slug

def main():
    print("Fetching sitemap...")
    xml = fetch_sitemap()
    print(f"Sitemap size: {len(xml):,} bytes")
    
    urls = parse_urls(xml)
    print(f"Total URLs found: {len(urls)}")
    
    districts = []
    other = []
    
    for url in urls:
        category, slug = classify_url(url)
        if category in ('district', 'likely_district'):
            districts.append({'url': url, 'slug': slug, 'category': category})
        else:
            other.append({'url': url, 'slug': slug, 'category': category})
    
    print(f"\nDistrict pages: {len(districts)}")
    print(f"Other pages: {len(other)}")
    
    # Save results
    output = {
        'total_urls': len(urls),
        'district_count': len(districts),
        'other_count': len(other),
        'districts': districts,
        'other': other,
    }
    
    outpath = Path(__file__).parent / 'sitemap_districts.json'
    with open(outpath, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to: {outpath}")
    
    # Also save just the district URLs as a simple text file
    urlpath = Path(__file__).parent / 'district_urls.txt'
    with open(urlpath, 'w') as f:
        for d in districts:
            f.write(d['url'] + '\n')
    print(f"URL list: {urlpath}")
    
    # Print some stats
    print(f"\nSample district slugs:")
    for d in districts[:20]:
        print(f"  {d['slug']}")

if __name__ == "__main__":
    main()
