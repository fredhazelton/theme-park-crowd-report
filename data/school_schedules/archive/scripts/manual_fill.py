#!/usr/bin/env python3
"""
Manually fill in calendar data for districts that couldn't be auto-scraped.
Data sourced from Firecrawl extract, official district websites, and schoolcalendarinfo.com.
"""

import csv
import json
from datetime import datetime
from pathlib import Path

CSV_PATH = Path(__file__).parent / "districts_top100.csv"

# Manual data collected from multiple sources
MANUAL_DATA = {
    # NYC - from Firecrawl extract (schools.nyc.gov)
    "New York City": {
        "calendar_url": "https://www.schools.nyc.gov/about-us/news/2025-26-school-year-calendar",
        "spring_break_start": "2026-04-02",
        "spring_break_end": "2026-04-10",
        "winter_break_start": "2025-12-24",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-06-26",
        "summer_end": "2025-09-04",
    },
    # LAUSD - from Firecrawl extract (lausd.org)
    "Los Angeles Unified": {
        "calendar_url": "https://www.lausd.org/calendars",
        "spring_break_start": "2026-03-30",
        "spring_break_end": "2026-04-03",
        "winter_break_start": "2025-12-18",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-06-10",
        "summer_end": "2025-08-14",
    },
    # Hawaii DOE - from hawaiipublicschools.org homepage events
    "Hawaii Department of Education": {
        "calendar_url": "https://hawaiipublicschools.org/",
        "spring_break_start": "2026-03-16",
        "spring_break_end": "2026-03-20",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-05-28",
        "summer_end": "2025-07-28",  # Hawaii starts very early
    },
    # Montgomery County MD - public data
    # Source: https://www.montgomeryschoolsmd.org/calendar/
    "Montgomery County": {
        "calendar_url": "https://schoolcalendarinfo.com/montgomery-county-public-schools/",
        "spring_break_start": "2026-03-30",
        "spring_break_end": "2026-04-03",
        "winter_break_start": "2025-12-24",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-06-15",
        "summer_end": "2025-08-25",
    },
    # Philadelphia - from philasd.org/calendar/
    "Philadelphia City": {
        "calendar_url": "https://www.philasd.org/calendar/",
        "spring_break_start": "2026-03-30",
        "spring_break_end": "2026-04-03",
        "winter_break_start": "2025-12-24",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-06-11",
        "summer_end": "2025-08-25",
    },
    # Shelby County (Memphis) - scsk12.org
    "Shelby County": {
        "calendar_url": "https://www.scsk12.org/calendar",
        "spring_break_start": "2026-03-16",
        "spring_break_end": "2026-03-20",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-05-22",
        "summer_end": "2025-08-04",
    },
    # Lee County FL
    "Lee County": {
        "calendar_url": "https://www.leeschools.net/our_district/calendars",
        "spring_break_start": "2026-03-16",
        "spring_break_end": "2026-03-20",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-05-29",
        "summer_end": "2025-08-11",
    },
    # Douglas County CO - from schoolcalendarinfo.com/douglas-county-schools/
    "Douglas County No RE1": {
        "calendar_url": "https://schoolcalendarinfo.com/douglas-county-schools/",
        "spring_break_start": "2026-04-06",
        "spring_break_end": "2026-04-10",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-05-22",
        "summer_end": "2025-08-11",
    },
    # Elk Grove Unified - multi-track, using Traditional calendar
    "Elk Grove Unified": {
        "calendar_url": "https://schoolcalendarinfo.com/elk-grove-unified-school-district/",
        "spring_break_start": "2026-03-16",
        "spring_break_end": "2026-03-20",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-05",
        "summer_start": "2026-05-29",
        "summer_end": "2025-08-14",
    },
    # Arlington ISD TX
    "Arlington ISD": {
        "calendar_url": "https://www.aisd.net/district/calendars/",
        "spring_break_start": "2026-03-16",
        "spring_break_end": "2026-03-20",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-06-04",
        "summer_end": "2025-08-11",
    },
    # Howard County MD - from schoolcalendarinfo.com/howard-county-public-schools/
    "Howard County": {
        "calendar_url": "https://schoolcalendarinfo.com/howard-county-public-schools/",
        "spring_break_start": "2026-03-30",
        "spring_break_end": "2026-04-03",
        "winter_break_start": "2025-12-24",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-06-12",
        "summer_end": "2025-08-25",
    },
    # Winston-Salem/Forsyth County NC
    "Winston-Salem/Forsyth County": {
        "calendar_url": "https://www.wsfcs.k12.nc.us/calendars",
        "spring_break_start": "2026-04-06",
        "spring_break_end": "2026-04-10",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-06-10",
        "summer_end": "2025-08-25",
    },
    # Corona-Norco Unified CA
    "Corona-Norco Unified": {
        "calendar_url": "https://www.cnusd.k12.ca.us/departments/educational_services/school_calendar",
        "spring_break_start": "2026-03-30",
        "spring_break_end": "2026-04-03",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-05",
        "summer_start": "2026-06-11",
        "summer_end": "2025-08-11",
    },
    # DC Public Schools
    "District of Columbia": {
        "calendar_url": "https://dcps.dc.gov/calendar",
        "spring_break_start": "2026-04-06",
        "spring_break_end": "2026-04-10",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-06-19",
        "summer_end": "2025-08-25",
    },
    # Jefferson Parish LA
    "Jefferson Parish": {
        "calendar_url": "https://www.jpschools.org/Page/2",
        "spring_break_start": "2026-04-03",
        "spring_break_end": "2026-04-10",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-05-21",
        "summer_end": "2025-08-06",
    },
    # Pasadena ISD TX
    "Pasadena ISD": {
        "calendar_url": "https://www1.pasadenaisd.org/calendar",
        "spring_break_start": "2026-03-09",
        "spring_break_end": "2026-03-13",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-05-28",
        "summer_end": "2025-08-11",
    },
    # San Bernardino City Unified CA
    "San Bernardino City Unified": {
        "calendar_url": "https://www.sbcusd.com/district/calendars",
        "spring_break_start": "2026-03-30",
        "spring_break_end": "2026-04-03",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-05",
        "summer_start": "2026-06-04",
        "summer_end": "2025-08-11",
    },
    # Fix Volusia County (had empty data despite "success")
    "Volusia County": {
        "calendar_url": "https://www.vcsedu.org/schools/school-calendar",
        "spring_break_start": "2026-03-16",
        "spring_break_end": "2026-03-20",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-05-27",
        "summer_end": "2025-08-11",
    },
    # North East ISD (had partial data - missing spring break end)
    "North East ISD": {
        "calendar_url": "https://schoolcalendarinfo.com/north-east-independent-school-district/",
        "spring_break_start": "2026-03-09",
        "spring_break_end": "2026-03-13",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-02",
        "summer_start": "2026-06-04",
        "summer_end": "2025-08-11",
    },
}


def main():
    # Read existing CSV
    rows = []
    with open(CSV_PATH, 'r') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
    
    # Update rows with manual data
    updated = 0
    for row in rows:
        name = row['district_name']
        if name in MANUAL_DATA:
            for key, value in MANUAL_DATA[name].items():
                row[key] = value
            row['last_updated'] = datetime.now().strftime('%Y-%m-%d')
            updated += 1
            print(f"  ✅ Updated: {name}")
    
    # Write back
    with open(CSV_PATH, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    # Count completeness
    total = len(rows)
    filled = sum(1 for r in rows if r.get('spring_break_start'))
    empty = sum(1 for r in rows if not r.get('spring_break_start'))
    
    print(f"\n{updated} districts manually updated.")
    print(f"Total: {total} districts, {filled} with data, {empty} still empty")
    
    if empty > 0:
        print(f"\nStill missing:")
        for r in rows:
            if not r.get('spring_break_start'):
                print(f"  - {r['district_name']} ({r['state']})")


if __name__ == "__main__":
    main()
