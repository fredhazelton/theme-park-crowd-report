#!/usr/bin/env python3
"""Scrape texasschools.us for all Texas district calendars."""

import csv
import json
import re
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).parent
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
RESULTS_FILE = BASE_DIR / "texasschools_results.json"
LOG_FILE = BASE_DIR / "texasschools_scraper.log"

MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6, 'jul': 7, 'aug': 8,
    'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def parse_month_day(month_str, day_str):
    month_str = month_str.lower().strip().rstrip('.')
    month = MONTHS.get(month_str)
    if not month:
        return None
    try:
        day = int(re.search(r'\d+', str(day_str)).group())
    except:
        return None
    if not (1 <= day <= 31):
        return None
    year = 2025 if month >= 7 else 2026
    try:
        return date(year, month, day)
    except ValueError:
        return None


def fetch_url(url, timeout=20):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    })
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.read().decode('utf-8', errors='replace')
    except:
        return None


def html_to_text(html):
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


def extract_texasschools_dates(text):
    """Extract dates from texasschools.us page content - optimized for their format."""
    result = {}
    
    for line in text.split('\n'):
        ll = line.lower().strip()
        
        # "First Day of School: August 12, 2025" or "August 12 – First Day of School"
        if ('first day' in ll or 'school begins' in ll or 'classes begin' in ll) and 'first_day' not in result:
            m = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})', ll)
            if m:
                d = parse_month_day(m.group(1), m.group(2))
                if d and date(2025, 7, 1) <= d <= date(2025, 9, 30):
                    result['first_day'] = d.isoformat()
        
        # "Last Day of School: May 22, 2026" or "May 22 – Last Day"
        if ('last day' in ll) and 'last_day' not in result:
            m = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})', ll)
            if m:
                d = parse_month_day(m.group(1), m.group(2))
                if d and date(2026, 5, 1) <= d <= date(2026, 7, 15):
                    result['last_day'] = d.isoformat()
        
        # "Spring Break: March 16, 2026 – March 20, 2026" or "March 16–20 – Spring Break"
        if 'spring break' in ll and 'spring_break_start' not in result:
            # Two different months
            m = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})\s*[-–to,\s]+\s*(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})', ll)
            if m:
                d1 = parse_month_day(m.group(1), m.group(2))
                d2 = parse_month_day(m.group(3), m.group(4))
                if d1 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                    result['spring_break_start'] = d1.isoformat()
                    result['spring_break_end'] = (d2 or d1).isoformat()
            else:
                # Same month
                m = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})', ll)
                if m:
                    d1 = parse_month_day(m.group(1), m.group(2))
                    d2 = parse_month_day(m.group(1), m.group(3))
                    if d1 and date(2026, 2, 1) <= d1 <= date(2026, 5, 31):
                        result['spring_break_start'] = d1.isoformat()
                        result['spring_break_end'] = (d2 or d1).isoformat()
        
        # "Winter Break: December 22, 2025 – January 2, 2026"
        if ('winter break' in ll or 'christmas break' in ll) and 'winter_break_start' not in result:
            m = re.search(r'(december|november)\s+(\d{1,2})\s*[-–to,\s]+\s*(january|december)\s+(\d{1,2})', ll)
            if m:
                d1 = parse_month_day(m.group(1), m.group(2))
                d2 = parse_month_day(m.group(3), m.group(4))
                if d1:
                    result['winter_break_start'] = d1.isoformat()
                    if d2:
                        result['winter_break_end'] = d2.isoformat()
            else:
                m = re.search(r'(december|november)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})', ll)
                if m:
                    d1 = parse_month_day(m.group(1), m.group(2))
                    d2 = parse_month_day(m.group(1), m.group(3))
                    if d1:
                        result['winter_break_start'] = d1.isoformat()
                        if d2:
                            result['winter_break_end'] = d2.isoformat()
    
    if 'first_day' in result and 'last_day' in result:
        result['summer_start'] = result['last_day']
        result['summer_end'] = result['first_day']
    
    return result


def validate(data):
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
        except:
            has_spring = False
    if has_year:
        try:
            fd = date.fromisoformat(data['first_day'])
            ld = date.fromisoformat(data['last_day'])
            if fd > ld:
                return None
        except:
            has_year = False
    if not has_spring and not has_year:
        return None
    return data


def main():
    log("=" * 60)
    log("TEXASSCHOOLS.US SCRAPER")
    log("=" * 60)
    
    # Load districts
    districts = []
    with open(COMPREHENSIVE_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            districts.append(row)
    
    # Get TX unconfirmed
    tx_unconfirmed = {}
    for d in districts:
        if d['state'] == 'TX' and d.get('confidence') != 'confirmed':
            tx_unconfirmed[d['nces_leaid']] = d
    log(f"TX unconfirmed districts: {len(tx_unconfirmed)}")
    
    # Fetch all calendar URLs from sitemap
    sitemap_url = 'https://texasschools.us/district-calendars.xml'
    req = urllib.request.Request(sitemap_url, headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    })
    xml_text = urllib.request.urlopen(req, timeout=30).read().decode()
    root = ET.fromstring(xml_text)
    ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    cal_urls = [u.text for u in root.findall('.//ns:url/ns:loc', ns) if '/districts/' in u.text and '/calendar/' in u.text]
    log(f"Found {len(cal_urls)} calendar URLs from texasschools.us")
    
    # Build name lookup for TX districts
    name_lookup = defaultdict(list)
    for leaid, d in tx_unconfirmed.items():
        name = d['district_name'].lower().strip()
        name_lookup[name].append(leaid)
        
        # Various normalizations
        for pat in [
            r'\s*(unified |consolidated |independent )?school\s*dist(rict)?\s*$',
            r'\s*(isd|cisd|csd|usd)\s*$',
        ]:
            stripped = re.sub(pat, '', name, flags=re.I).strip()
            if stripped and stripped != name:
                name_lookup[stripped].append(leaid)
        
        # Short name
        short = re.sub(r'\s+(isd|cisd|csd)\b.*$', '', name, flags=re.I).strip()
        if short and len(short) > 2:
            name_lookup[short].append(leaid)
    
    # Match URLs to districts
    url_matches = {}
    for url in cal_urls:
        slug = url.rstrip('/').split('/')[-2]  # e.g., "plano-isd" from .../districts/plano-isd/calendar/
        slug_clean = slug.replace('-', ' ').strip().lower()
        
        # Try direct
        if slug_clean in name_lookup:
            for leaid in name_lookup[slug_clean]:
                if leaid not in url_matches:
                    url_matches[leaid] = url
                    break
            continue
        
        # Try without isd/cisd suffix
        slug_no_suffix = re.sub(r'\s*(isd|cisd|csd)\s*$', '', slug_clean).strip()
        if slug_no_suffix in name_lookup:
            for leaid in name_lookup[slug_no_suffix]:
                if leaid not in url_matches:
                    url_matches[leaid] = url
                    break
    
    log(f"Matched {len(url_matches)} URLs to unconfirmed TX districts")
    
    # Scrape
    results = {}
    scraped = 0
    for leaid, url in url_matches.items():
        html = fetch_url(url)
        scraped += 1
        if html:
            text = html_to_text(html)
            dates = extract_texasschools_dates(text)
            validated = validate(dates)
            if validated:
                results[leaid] = {
                    'dates': validated,
                    'source': 'texasschools',
                    'url': url,
                }
        
        if scraped % 50 == 0:
            log(f"  Scraped {scraped}/{len(url_matches)}, confirmed: {len(results)}")
        time.sleep(0.3)
    
    log(f"Complete: {len(results)} confirmed from texasschools.us")
    
    # Save results
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    # Merge to CSV
    if results:
        updated = 0
        for d in districts:
            leaid = d['nces_leaid']
            if leaid in results and d.get('confidence') != 'confirmed':
                r = results[leaid]
                dates = r['dates']
                for field in ['spring_break_start', 'spring_break_end', 'winter_break_start',
                              'winter_break_end', 'first_day', 'last_day', 'summer_start', 'summer_end']:
                    if dates.get(field):
                        d[field] = dates[field]
                d['source'] = 'texasschools'
                d['confidence'] = 'confirmed'
                d['school_year'] = '2025-2026'
                updated += 1
        
        fieldnames = list(districts[0].keys())
        with open(COMPREHENSIVE_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(districts)
        log(f"Updated {updated} districts in CSV")
    
    # Stats
    confirmed = sum(1 for d in districts if d.get('confidence') == 'confirmed')
    log(f"Total confirmed now: {confirmed}/{len(districts)} ({confirmed*100/len(districts):.1f}%)")


if __name__ == '__main__':
    main()
