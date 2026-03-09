#!/usr/bin/env python3
"""
School Calendar Scraper - Phase 1 Prototype
Scrapes schoolcalendarinfo.com for structured school break data.
This site has consistent HTML tables with break dates for major US districts.
"""

import csv
import re
import sys
import time
import json
from datetime import datetime
from pathlib import Path

# We'll use web_fetch via simple HTTP requests since it returns clean markdown
# But first, let's build the URL slug mapping for our top 100 districts

# District name -> schoolcalendarinfo.com URL slug
# Convention: lowercase, hyphenated, usually "[district-name]-public-schools" or similar
DISTRICT_SLUGS = {
    "New York City": "new-york-city-department-of-education",
    "Los Angeles Unified": "los-angeles-unified-school-district",
    "City of Chicago (SD 299)": "chicago-public-schools",
    "Miami-Dade County": "miami-dade-county-public-schools",
    "Clark County": "clark-county-school-district",
    "Broward County": "broward-county-public-schools",
    "Hillsborough County": "hillsborough-county-public-schools",
    "Houston ISD": "houston-independent-school-district",
    "Orange County": "orange-county-public-schools",
    "Palm Beach": "palm-beach-county-school-district",
    "Fairfax County": "fairfax-county-public-schools",
    "Hawaii Department of Education": "hawaii-department-of-education",
    "Gwinnett County": "gwinnett-county-public-schools",
    "Montgomery County": "montgomery-county-public-schools",
    "Wake County": "wake-county-public-schools",
    "Dallas ISD": "dallas-independent-school-district",
    "Charlotte-Mecklenburg": "charlotte-mecklenburg-schools",
    "Prince George's County": "prince-georges-county-public-schools",
    "Philadelphia City": "school-district-of-philadelphia",
    "Duval County": "duval-county-public-schools",
    "Cypress-Fairbanks ISD": "cypress-fairbanks-independent-school-district",
    "Baltimore County": "baltimore-county-public-schools",
    "Shelby County": "shelby-county-schools",
    "Cobb County": "cobb-county-school-district",
    "Northside ISD": "northside-independent-school-district",
    "Polk County": "polk-county-public-schools",
    "San Diego Unified": "san-diego-unified-school-district",
    "Jefferson County": "jefferson-county-public-schools",  # Kentucky
    "Pinellas County": "pinellas-county-schools",
    "DeKalb County": "dekalb-county-school-district",
    "Lee County": "lee-county-public-schools",  # FL
    "Fulton County": "fulton-county-schools",
    "Prince William County": "prince-william-county-public-schools",
    "Denver": "denver-public-schools",
    "Albuquerque": "albuquerque-public-schools",
    "Davidson County": "metro-nashville-public-schools",
    "Anne Arundel County": "anne-arundel-county-public-schools",
    "Jefferson County No R1": "jeffco-public-schools",
    "Loudoun County": "loudoun-county-public-schools",
    "Alpine": "alpine-school-district",
    "Katy ISD": "katy-independent-school-district",
    "Fort Worth ISD": "fort-worth-independent-school-district",
    "Austin ISD": "austin-independent-school-district",
    "Baltimore City": "baltimore-city-public-schools",
    "Fort Bend ISD": "fort-bend-independent-school-district",
    "Greenville County": "greenville-county-schools",
    "Pasco County": "pasco-county-schools",
    "Davis": "davis-school-district",
    "Milwaukee": "milwaukee-public-schools",
    "Brevard County": "brevard-public-schools",
    "Guilford County": "guilford-county-schools",
    "Long Beach Unified": "long-beach-unified-school-district",
    "Fresno Unified": "fresno-unified-school-district",
    "Osceola County": "osceola-county-school-district",
    "Virginia Beach City": "virginia-beach-city-public-schools",
    "Seminole County": "seminole-county-public-schools",
    "Douglas County No RE1": "douglas-county-school-district",
    "Washoe County": "washoe-county-school-district",
    "Aldine ISD": "aldine-independent-school-district",
    "Granite": "granite-school-district",
    "Conroe ISD": "conroe-independent-school-district",
    "North East ISD": "north-east-independent-school-district",
    "Elk Grove Unified": "elk-grove-unified-school-district",
    "Volusia County": "volusia-county-schools",
    "Frisco ISD": "frisco-independent-school-district",
    "Mesa Unified": "mesa-public-schools",
    "Chesterfield County": "chesterfield-county-public-schools",
    "Knox County": "knox-county-schools",
    "Arlington ISD": "arlington-independent-school-district",
    "Howard County": "howard-county-public-school-system",
    "Jordan": "jordan-school-district",
    "Cherry Creek No 5": "cherry-creek-school-district",
    "Seattle": "seattle-public-schools",
    "Garland ISD": "garland-independent-school-district",
    "El Paso ISD": "el-paso-independent-school-district",
    "Winston-Salem/Forsyth County": "winston-salem-forsyth-county-schools",
    "Clayton County": "clayton-county-public-schools",
    "Klein ISD": "klein-independent-school-district",
    "Mobile County": "mobile-county-public-schools",
    "Omaha": "omaha-public-schools",
    "Pasadena ISD": "pasadena-independent-school-district",
    "San Francisco Unified": "san-francisco-unified-school-district",
    "Plano ISD": "plano-independent-school-district",
    "Corona-Norco Unified": "corona-norco-unified-school-district",
    "Atlanta": "atlanta-public-schools",
    "Lewisville ISD": "lewisville-independent-school-district",
    "Henrico County": "henrico-county-public-schools",
    "District of Columbia": "district-of-columbia-public-schools",
    "Round Rock ISD": "round-rock-independent-school-district",
    "Cumberland County": "cumberland-county-schools",
    "Detroit": "detroit-public-schools",
    "Forsyth County": "forsyth-county-schools",  # Georgia
    "Boston": "boston-public-schools",
    "Charleston 01": "charleston-county-school-district",
    "Manatee County": "manatee-county-school-district",
    "Jefferson Parish": "jefferson-parish-public-schools",
    "Wichita": "wichita-public-schools",
    "Columbus City": "columbus-city-schools",
    "San Bernardino City Unified": "san-bernardino-city-unified-school-district",
    "Portland SD1J": "portland-public-schools",
}

BASE_URL = "https://schoolcalendarinfo.com"


def parse_date(date_str):
    """Parse various date formats from schoolcalendarinfo.com"""
    if not date_str or date_str.strip() == '':
        return None
    
    date_str = date_str.strip()
    
    # Try formats: "Mon, Aug 11 2025" or "Mon, 12 Aug 2024"
    formats = [
        "%a, %b %d %Y",   # Mon, Aug 11 2025
        "%a, %d %b %Y",   # Mon, 12 Aug 2024
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    return None


def parse_calendar_text(text, target_year="2025-2026"):
    """Parse the markdown text from schoolcalendarinfo.com to extract calendar data."""
    result = {
        'spring_break_start': '',
        'spring_break_end': '',
        'winter_break_start': '',
        'winter_break_end': '',
        'summer_start': '',  # last day of school
        'summer_end': '',    # first day of school (next year or same year)
        'first_day': '',
        'last_day': '',
    }
    
    # Find the target year section
    lines = text.split('\n')
    in_target_section = False
    
    for i, line in enumerate(lines):
        if target_year in line and 'School Calendar' in line:
            in_target_section = True
            continue
        
        # Stop if we hit another year section
        if in_target_section and re.search(r'20\d{2}-20\d{2} School Calendar', line) and target_year not in line:
            break
        
        if not in_target_section:
            continue
        
        # Parse table rows: "EventStartsEnds" format or "First Day of SchoolMon, Aug 11 2025"
        # The markdown doesn't have proper table formatting from readability extractor
        # It comes as: "First Day of SchoolMon, Aug 11 2025"
        # or "Christmas BreakMon, Dec 22 2025Mon, Jan 5 2026"
        
        line_lower = line.lower().strip()
        
        # Match patterns like "First Day of SchoolTue, Aug 12 2025"
        first_day_match = re.search(r'first day of school\s*(\w{3}, \w{3} \d{1,2} \d{4}|\w{3}, \d{1,2} \w{3} \d{4})', line, re.IGNORECASE)
        if first_day_match:
            result['first_day'] = parse_date(first_day_match.group(1)) or ''
            # Summer end is the first day of school
            result['summer_end'] = result['first_day']
        
        last_day_match = re.search(r'last day of school\s*(\w{3}, \w{3} \d{1,2} \d{4}|\w{3}, \d{1,2} \w{3} \d{4})', line, re.IGNORECASE)
        if last_day_match:
            result['last_day'] = parse_date(last_day_match.group(1)) or ''
            # Summer start is the last day of school
            result['summer_start'] = result['last_day']
        
        # Match Christmas/Winter Break (but NOT "Mid-Winter Break")
        winter_match = re.search(r'(?:christmas|(?<!mid-)(?<!mid )winter) break\s*(\w{3}, \w{3} \d{1,2} \d{4}|\w{3}, \d{1,2} \w{3} \d{4})\s*(\w{3}, \w{3} \d{1,2} \d{4}|\w{3}, \d{1,2} \w{3} \d{4})', line, re.IGNORECASE)
        if winter_match:
            result['winter_break_start'] = parse_date(winter_match.group(1)) or ''
            result['winter_break_end'] = parse_date(winter_match.group(2)) or ''
        
        # Match Spring Break
        spring_match = re.search(r'spring break\s*(\w{3}, \w{3} \d{1,2} \d{4}|\w{3}, \d{1,2} \w{3} \d{4})\s*(\w{3}, \w{3} \d{1,2} \d{4}|\w{3}, \d{1,2} \w{3} \d{4})', line, re.IGNORECASE)
        if spring_match:
            result['spring_break_start'] = parse_date(spring_match.group(1)) or ''
            result['spring_break_end'] = parse_date(spring_match.group(2)) or ''
    
    return result


def test_parsing():
    """Test the parser on known data."""
    # Miami-Dade sample text
    sample = """### 2025-2026 School Calendar

EventStartsEnds
First Day of SchoolThu, Aug 14 2025 
Thanksgiving BreakMon, Nov 24 2025Fri, Nov 28 2025
Christmas BreakMon, Dec 22 2025Fri, Jan 2 2026
January BreakFri, Jan 16 2026Mon, Jan 19 2026
Spring BreakFri, Mar 20 2026Fri, Mar 27 2026
Last Day of SchoolThu, Jun 4 2026 

### 2024-2025 School Calendar"""

    result = parse_calendar_text(sample, "2025-2026")
    print("Parse test (Miami-Dade):")
    print(json.dumps(result, indent=2))
    
    assert result['first_day'] == '2025-08-14', f"Expected 2025-08-14, got {result['first_day']}"
    assert result['winter_break_start'] == '2025-12-22', f"Expected 2025-12-22, got {result['winter_break_start']}"
    assert result['winter_break_end'] == '2026-01-02', f"Expected 2026-01-02, got {result['winter_break_end']}"
    assert result['spring_break_start'] == '2026-03-20', f"Expected 2026-03-20, got {result['spring_break_start']}"
    assert result['spring_break_end'] == '2026-03-27', f"Expected 2026-03-27, got {result['spring_break_end']}"
    assert result['last_day'] == '2026-06-04', f"Expected 2026-06-04, got {result['last_day']}"
    print("✅ All assertions passed!\n")
    
    # Houston ISD sample
    sample2 = """### 2025-2026 School Calendar

EventStartsEnds
First Day of SchoolTue, Aug 12 2025
September BreakMon, Sep 1 2025Tue, Sep 2 2025
Fall BreakThu, Oct 2 2025Fri, Oct 3 2025
Thanksgiving BreakMon, Nov 24 2025Fri, Nov 28 2025
Christmas BreakMon, Dec 22 2025Mon, Jan 5 2026
Mid-Winter BreakFri, Feb 13 2026Mon, Feb 16 2026
Spring BreakMon, Mar 9 2026Fri, Mar 13 2026
Last Day of SchoolThu, Jun 4 2026

### 2024-2025 School Calendar"""

    result2 = parse_calendar_text(sample2, "2025-2026")
    print("Parse test (Houston ISD):")
    print(json.dumps(result2, indent=2))
    
    assert result2['first_day'] == '2025-08-12'
    assert result2['spring_break_start'] == '2026-03-09'
    assert result2['spring_break_end'] == '2026-03-13'
    print("✅ All assertions passed!\n")


if __name__ == "__main__":
    test_parsing()
    print(f"\nTotal districts with URL slugs: {len(DISTRICT_SLUGS)}")
    print(f"Districts in CSV: 100")
    print(f"Coverage: {len(DISTRICT_SLUGS)}/100 = {len(DISTRICT_SLUGS)}%")
