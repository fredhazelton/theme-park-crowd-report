#!/usr/bin/env python3
"""
Build the comprehensive districts file integrating all data sources:
1. Existing confirmed data (schoolcalendarinfo.com - 603 districts)
2. Top 100 verified districts
3. Tavily search results for large uncovered districts
4. NYC geographic districts (all follow NYC DOE calendar)
5. State-level inference for all remaining districts
"""

import csv, json, os, re
from collections import defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_csv(filename):
    with open(os.path.join(BASE_DIR, filename)) as f:
        return list(csv.DictReader(f))

def load_json(filename):
    with open(os.path.join(BASE_DIR, filename)) as f:
        return json.load(f)

# ─── Load all data ──────────────────────────────────────────
print("Loading data...")
nces_rows = load_csv('nces_all_districts.csv')
nces = {r['leaid']: r for r in nces_rows}

enrollment_rows = load_csv('enrollment_by_district.csv')
enrollment = {r['leaid']: int(r['enrollment_2223']) for r in enrollment_rows}

matches = load_json('district_nces_matches.json')
existing_rows = load_csv('districts_all.csv')
top100_rows = load_csv('districts_top100.csv')
tavily_raw = load_json('tavily_search_results.json')
state_doe = load_json('state_doe_tavily_results.json')

print(f"NCES: {len(nces)} | Enrollment: {len(enrollment)} | Existing: {len(existing_rows)} | Top100: {len(top100_rows)}")

# ─── Build calendar by LEAID ──────────────────────────────────
calendars = {}  # leaid -> calendar dict

# Source 1: districts_all.csv (schoolcalendarinfo)
for row in existing_rows:
    name = row['district_name']
    if name in matches['districts_all']:
        m = matches['districts_all'][name]
        leaid = m['leaid']
        calendars[leaid] = {
            'spring_break_start': row.get('spring_break_start', ''),
            'spring_break_end': row.get('spring_break_end', ''),
            'winter_break_start': row.get('winter_break_start', ''),
            'winter_break_end': row.get('winter_break_end', ''),
            'summer_start': row.get('summer_start', ''),
            'summer_end': row.get('summer_end', ''),
            'first_day': row.get('first_day', ''),
            'last_day': row.get('last_day', ''),
            'school_year': '2025-2026',
            'source': 'schoolcalendarinfo',
            'confidence': 'confirmed'
        }

# Source 2: top100 (verified)
for row in top100_rows:
    name = row['district_name']
    if name in matches['top100']:
        m = matches['top100'][name]
        leaid = m['leaid']
        if leaid not in calendars:
            calendars[leaid] = {
                'spring_break_start': row.get('spring_break_start', ''),
                'spring_break_end': row.get('spring_break_end', ''),
                'winter_break_start': row.get('winter_break_start', ''),
                'winter_break_end': row.get('winter_break_end', ''),
                'summer_start': row.get('summer_start', ''),
                'summer_end': row.get('summer_end', ''),
                'first_day': row.get('summer_end', ''),  # first_day ~ summer_end
                'last_day': row.get('summer_start', ''),  # last_day ~ summer_start
                'school_year': '2025-2026',
                'source': 'schoolcalendarinfo',
                'confidence': 'confirmed'
            }

print(f"After existing + top100: {len(calendars)} districts with confirmed data")

# Source 3: NYC Geographic Districts — all follow NYC DOE calendar
# NYC DOE 2025-2026: First day Sep 4, Last day Jun 26
# Spring break: Apr 2-10, Winter break: Dec 24 - Jan 2
NYC_CALENDAR = {
    'spring_break_start': '2026-04-02',
    'spring_break_end': '2026-04-10',
    'winter_break_start': '2025-12-24',
    'winter_break_end': '2026-01-02',
    'summer_start': '2026-06-26',
    'summer_end': '2025-09-04',
    'first_day': '2025-09-04',
    'last_day': '2026-06-26',
    'school_year': '2025-2026',
    'source': 'nyc_doe_calendar',
    'confidence': 'confirmed'
}

nyc_count = 0
for leaid, dist in nces.items():
    if leaid in calendars:
        continue
    name = dist['lea_name']
    if ('NEW YORK CITY GEOGRAPHIC' in name or 'NYC SPECIAL' in name or 
        'CHANCELLOR' in name or name == 'NEW YORK CITY DEPARTMENT OF EDUCATION'):
        calendars[leaid] = NYC_CALENDAR.copy()
        nyc_count += 1

print(f"Added {nyc_count} NYC geographic districts")

# Source 4: Tavily search results - parse answers properly
def parse_date_from_text(text, default_year=2025):
    months = {'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
              'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12}
    m = re.match(r'(\w+)\s+(\d{1,2})(?:,?\s+(\d{4}))?', text.strip())
    if m:
        mn = m.group(1).lower()
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else default_year
        if mn in months:
            month = months[mn]
            if not m.group(3):
                year = 2025 if month >= 7 else 2026
            try:
                return datetime(year, month, day).strftime('%Y-%m-%d')
            except:
                pass
    return ''

tavily_added = 0
for leaid, r in tavily_raw.items():
    if leaid in calendars:
        continue
    if 'error' in r:
        continue
    
    answer = r.get('answer', '')
    if not answer:
        continue
    
    first_day = ''
    last_day = ''
    spring_start = ''
    spring_end = ''
    
    # Extract first day
    for pat in [
        r'first\s+day\s+(?:of\s+(?:school|the\s+\d{4}[\-–]\d{4}\s+school\s+year)\s+)?(?:(?:in\s+)?(?:is|for\s+\w+\s+is)\s+)?(?:\w+day,?\s+)?(\w+\s+\d{1,2}(?:,?\s+\d{4})?)',
        r'school\s+year\s+(?:starts?|begins?)\s+(?:on\s+)?(?:\w+day,?\s+)?(\w+\s+\d{1,2}(?:,?\s+\d{4})?)',
    ]:
        m = re.search(pat, answer, re.IGNORECASE)
        if m:
            fd = parse_date_from_text(m.group(1))
            # Validate: first day should be Jul-Sep
            if fd and fd[:4] == '2025' and fd[5:7] in ('07','08','09'):
                first_day = fd
                break
    
    # Extract last day
    for pat in [
        r'last\s+day\s+(?:of\s+school\s+)?(?:is\s+)?(?:\w+day,?\s+)?(\w+\s+\d{1,2}(?:,?\s+\d{4})?)',
        r'school\s+year\s+ends?\s+(?:on\s+)?(?:\w+day,?\s+)?(\w+\s+\d{1,2}(?:,?\s+\d{4})?)',
        r'ends?\s+(?:on\s+)?(\w+\s+\d{1,2}(?:,?\s+\d{4})?)',
    ]:
        m = re.search(pat, answer, re.IGNORECASE)
        if m:
            ld = parse_date_from_text(m.group(1), 2026)
            # Validate: last day should be May-Jun 2026
            if ld and ld[:4] == '2026' and ld[5:7] in ('05', '06'):
                last_day = ld
                break
    
    # Spring break
    m = re.search(r'spring\s+break\s*(?:is\s+)?(?:from\s+)?(\w+\s+\d{1,2}(?:,?\s+\d{4})?)\s*(?:to|-|through|–|and\s+ends?\s+(?:on\s+)?)\s*(\w+\s+\d{1,2}(?:,?\s+\d{4})?)', answer, re.IGNORECASE)
    if m:
        spring_start = parse_date_from_text(m.group(1), 2026)
        spring_end = parse_date_from_text(m.group(2), 2026)
        # Validate spring break in March-April 2026
        if spring_start and not (spring_start[:7] in ('2026-03', '2026-04')):
            spring_start = ''
            spring_end = ''
    
    if first_day or last_day or spring_start:
        calendars[leaid] = {
            'spring_break_start': spring_start,
            'spring_break_end': spring_end,
            'winter_break_start': '',
            'winter_break_end': '',
            'summer_start': last_day,  # summer starts after last day
            'summer_end': first_day,   # summer ends on first day
            'first_day': first_day,
            'last_day': last_day,
            'school_year': '2025-2026',
            'source': 'tavily',
            'confidence': 'high'
        }
        tavily_added += 1

print(f"Added {tavily_added} districts from Tavily search")

# ─── State-level inference ──────────────────────────────────
# Build state medians from confirmed data
state_confirmed = defaultdict(list)
for leaid, cal in calendars.items():
    if cal['confidence'] in ('confirmed', 'high') and leaid in nces:
        st = nces[leaid]['st']
        state_confirmed[st].append(cal)

def median_date(dates):
    valid = sorted([d for d in dates if d and len(d) == 10])
    if not valid:
        return ''
    return valid[len(valid)//2]

state_medians = {}
for st, cals in state_confirmed.items():
    state_medians[st] = {
        'spring_break_start': median_date([c['spring_break_start'] for c in cals]),
        'spring_break_end': median_date([c['spring_break_end'] for c in cals]),
        'winter_break_start': median_date([c['winter_break_start'] for c in cals]),
        'winter_break_end': median_date([c['winter_break_end'] for c in cals]),
        'summer_start': median_date([c['summer_start'] for c in cals]),
        'summer_end': median_date([c['summer_end'] for c in cals]),
        'first_day': median_date([c['first_day'] for c in cals]),
        'last_day': median_date([c['last_day'] for c in cals]),
    }

# Enhanced state rules from DOE research + Tavily DOE search
STATE_RULES = {
    'TX': {'first_day': '2025-08-19', 'last_day': '2026-05-21', 'spring_break_start': '2026-03-09', 'spring_break_end': '2026-03-13', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'CA': {'first_day': '2025-08-18', 'last_day': '2026-06-05', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'NY': {'first_day': '2025-09-04', 'last_day': '2026-06-26', 'spring_break_start': '2026-04-02', 'spring_break_end': '2026-04-10', 'winter_break_start': '2025-12-24', 'winter_break_end': '2026-01-02'},
    'FL': {'first_day': '2025-08-11', 'last_day': '2026-06-04', 'spring_break_start': '2026-03-16', 'spring_break_end': '2026-03-20', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'IL': {'first_day': '2025-08-26', 'last_day': '2026-06-10', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'PA': {'first_day': '2025-08-26', 'last_day': '2026-06-10', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-03', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'OH': {'first_day': '2025-08-18', 'last_day': '2026-05-29', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'GA': {'first_day': '2025-08-04', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-03', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'MI': {'first_day': '2025-09-02', 'last_day': '2026-06-12', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-03', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'NC': {'first_day': '2025-08-25', 'last_day': '2026-06-05', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-03', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'NJ': {'first_day': '2025-09-01', 'last_day': '2026-06-18', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-06', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'VA': {'first_day': '2025-08-25', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-03', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'WA': {'first_day': '2025-09-02', 'last_day': '2026-06-12', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-03', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'IN': {'first_day': '2025-08-11', 'last_day': '2026-05-29', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-03', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'TN': {'first_day': '2025-08-04', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-16', 'spring_break_end': '2026-03-20', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'MD': {'first_day': '2025-09-02', 'last_day': '2026-06-15', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-03', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'WI': {'first_day': '2025-09-01', 'last_day': '2026-06-12', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'MN': {'first_day': '2025-09-02', 'last_day': '2026-06-10', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'MO': {'first_day': '2025-08-13', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-16', 'spring_break_end': '2026-03-20', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'CO': {'first_day': '2025-08-12', 'last_day': '2026-06-04', 'spring_break_start': '2026-03-16', 'spring_break_end': '2026-03-20', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'AL': {'first_day': '2025-08-11', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'AZ': {'first_day': '2025-07-28', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-09', 'spring_break_end': '2026-03-13', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'SC': {'first_day': '2025-08-18', 'last_day': '2026-06-05', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-03', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-05'},
    'LA': {'first_day': '2025-08-11', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-03', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'KY': {'first_day': '2025-08-13', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-03', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'OR': {'first_day': '2025-09-02', 'last_day': '2026-06-12', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'OK': {'first_day': '2025-08-14', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-16', 'spring_break_end': '2026-03-20', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'CT': {'first_day': '2025-08-27', 'last_day': '2026-06-12', 'spring_break_start': '2026-04-06', 'spring_break_end': '2026-04-10', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'UT': {'first_day': '2025-08-20', 'last_day': '2026-05-28', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'IA': {'first_day': '2025-08-25', 'last_day': '2026-06-05', 'spring_break_start': '2026-03-16', 'spring_break_end': '2026-03-20', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'NV': {'first_day': '2025-08-11', 'last_day': '2026-06-04', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'KS': {'first_day': '2025-08-14', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-16', 'spring_break_end': '2026-03-20', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'MS': {'first_day': '2025-08-04', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-16', 'spring_break_end': '2026-03-20', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'AR': {'first_day': '2025-08-14', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'NE': {'first_day': '2025-08-13', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-16', 'spring_break_end': '2026-03-20', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'NM': {'first_day': '2025-08-07', 'last_day': '2026-05-29', 'spring_break_start': '2026-03-16', 'spring_break_end': '2026-03-20', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'WV': {'first_day': '2025-08-19', 'last_day': '2026-05-29', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-03', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'ID': {'first_day': '2025-08-21', 'last_day': '2026-06-05', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'HI': {'first_day': '2025-07-28', 'last_day': '2026-05-29', 'spring_break_start': '2026-03-16', 'spring_break_end': '2026-03-20', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'NH': {'first_day': '2025-08-27', 'last_day': '2026-06-12', 'spring_break_start': '2026-04-20', 'spring_break_end': '2026-04-24', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'ME': {'first_day': '2025-09-02', 'last_day': '2026-06-12', 'spring_break_start': '2026-04-20', 'spring_break_end': '2026-04-24', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'MT': {'first_day': '2025-08-27', 'last_day': '2026-06-05', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'RI': {'first_day': '2025-09-03', 'last_day': '2026-06-19', 'spring_break_start': '2026-04-13', 'spring_break_end': '2026-04-17', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'DE': {'first_day': '2025-08-25', 'last_day': '2026-06-12', 'spring_break_start': '2026-03-30', 'spring_break_end': '2026-04-03', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'SD': {'first_day': '2025-08-25', 'last_day': '2026-05-29', 'spring_break_start': '2026-03-16', 'spring_break_end': '2026-03-20', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'ND': {'first_day': '2025-08-21', 'last_day': '2026-05-29', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'AK': {'first_day': '2025-08-20', 'last_day': '2026-05-22', 'spring_break_start': '2026-03-16', 'spring_break_end': '2026-03-20', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'VT': {'first_day': '2025-08-27', 'last_day': '2026-06-12', 'spring_break_start': '2026-04-20', 'spring_break_end': '2026-04-24', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'WY': {'first_day': '2025-08-21', 'last_day': '2026-05-29', 'spring_break_start': '2026-03-23', 'spring_break_end': '2026-03-27', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'DC': {'first_day': '2025-08-25', 'last_day': '2026-06-12', 'spring_break_start': '2026-04-06', 'spring_break_end': '2026-04-10', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
    'MA': {'first_day': '2025-09-02', 'last_day': '2026-06-19', 'spring_break_start': '2026-04-20', 'spring_break_end': '2026-04-24', 'winter_break_start': '2025-12-22', 'winter_break_end': '2026-01-02'},
}

# Infer for all remaining districts
inferred_count = 0
for leaid, dist in nces.items():
    if leaid in calendars:
        continue
    
    st = dist['st']
    
    # Priority: state median from confirmed data > state rules > nothing
    if st in state_medians:
        med = state_medians[st]
        # Fill any gaps with state rules
        if st in STATE_RULES:
            for k, v in STATE_RULES[st].items():
                if not med.get(k):
                    med[k] = v
        
        n_confirmed = len(state_confirmed.get(st, []))
        if n_confirmed >= 10:
            confidence = 'medium'
        elif n_confirmed >= 3:
            confidence = 'medium'
        else:
            confidence = 'inferred'
        
        calendars[leaid] = {
            'spring_break_start': med.get('spring_break_start', ''),
            'spring_break_end': med.get('spring_break_end', ''),
            'winter_break_start': med.get('winter_break_start', ''),
            'winter_break_end': med.get('winter_break_end', ''),
            'summer_start': med.get('summer_start', med.get('last_day', '')),
            'summer_end': med.get('summer_end', med.get('first_day', '')),
            'first_day': med.get('first_day', ''),
            'last_day': med.get('last_day', ''),
            'school_year': '2025-2026',
            'source': 'inferred_state',
            'confidence': confidence
        }
        inferred_count += 1
    elif st in STATE_RULES:
        rules = STATE_RULES[st]
        calendars[leaid] = {
            'spring_break_start': rules.get('spring_break_start', ''),
            'spring_break_end': rules.get('spring_break_end', ''),
            'winter_break_start': rules.get('winter_break_start', ''),
            'winter_break_end': rules.get('winter_break_end', ''),
            'summer_start': rules.get('last_day', ''),
            'summer_end': rules.get('first_day', ''),
            'first_day': rules.get('first_day', ''),
            'last_day': rules.get('last_day', ''),
            'school_year': '2025-2026',
            'source': 'state_rules',
            'confidence': 'inferred'
        }
        inferred_count += 1

print(f"Inferred {inferred_count} districts from state data")
print(f"Total districts with calendar data: {len(calendars)}")

# ─── Build output CSV ──────────────────────────────────────
rows = []
for leaid, dist in nces.items():
    enroll = enrollment.get(leaid, 0)
    cal = calendars.get(leaid, {})
    
    rows.append({
        'nces_leaid': leaid,
        'district_name': dist['lea_name'],
        'state': dist['st'],
        'city': dist.get('city', ''),
        'enrollment': enroll,
        'spring_break_start': cal.get('spring_break_start', ''),
        'spring_break_end': cal.get('spring_break_end', ''),
        'winter_break_start': cal.get('winter_break_start', ''),
        'winter_break_end': cal.get('winter_break_end', ''),
        'summer_start': cal.get('summer_start', ''),
        'summer_end': cal.get('summer_end', ''),
        'first_day': cal.get('first_day', ''),
        'last_day': cal.get('last_day', ''),
        'school_year': cal.get('school_year', '2025-2026'),
        'source': cal.get('source', 'none'),
        'confidence': cal.get('confidence', 'none')
    })

rows.sort(key=lambda x: -x['enrollment'])

fieldnames = ['nces_leaid', 'district_name', 'state', 'city', 'enrollment',
              'spring_break_start', 'spring_break_end', 'winter_break_start', 'winter_break_end',
              'summer_start', 'summer_end', 'first_day', 'last_day',
              'school_year', 'source', 'confidence']

with open(os.path.join(BASE_DIR, 'districts_comprehensive.csv'), 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

# ─── Stats ──────────────────────────────────────────
total_enrollment = sum(enrollment.values())
source_stats = defaultdict(lambda: {'count': 0, 'enrollment': 0})
confidence_stats = defaultdict(lambda: {'count': 0, 'enrollment': 0})

for r in rows:
    source_stats[r['source']]['count'] += 1
    source_stats[r['source']]['enrollment'] += r['enrollment']
    confidence_stats[r['confidence']]['count'] += 1
    confidence_stats[r['confidence']]['enrollment'] += r['enrollment']

print(f"\n{'='*60}")
print(f"COMPREHENSIVE DATASET SUMMARY")
print(f"{'='*60}")
print(f"\nTotal districts: {len(rows)}")
print(f"Total with calendar data: {sum(1 for r in rows if r['source'] != 'none')}")
print(f"Total enrollment: {total_enrollment:,}")

print(f"\nBy Source:")
for src, s in sorted(source_stats.items(), key=lambda x: -x[1]['enrollment']):
    pct = s['enrollment'] / total_enrollment * 100
    print(f"  {src:25s}: {s['count']:6d} districts, {s['enrollment']:12,} students ({pct:5.1f}%)")

print(f"\nBy Confidence:")
for conf, s in sorted(confidence_stats.items(), key=lambda x: -x[1]['enrollment']):
    pct = s['enrollment'] / total_enrollment * 100
    print(f"  {conf:12s}: {s['count']:6d} districts, {s['enrollment']:12,} students ({pct:5.1f}%)")

covered_enrollment = sum(r['enrollment'] for r in rows if r['source'] != 'none')
confirmed_enrollment = sum(r['enrollment'] for r in rows if r['confidence'] in ('confirmed', 'high'))
print(f"\nCoverage: {covered_enrollment:,}/{total_enrollment:,} ({covered_enrollment/total_enrollment*100:.1f}%)")
print(f"Confirmed/High: {confirmed_enrollment:,}/{total_enrollment:,} ({confirmed_enrollment/total_enrollment*100:.1f}%)")

# State breakdown
print(f"\nTop 20 states by enrollment:")
state_stats = defaultdict(lambda: {'total_enroll': 0, 'confirmed_enroll': 0, 'covered_enroll': 0, 'districts': 0})
for r in rows:
    st = r['state']
    state_stats[st]['total_enroll'] += r['enrollment']
    state_stats[st]['districts'] += 1
    if r['source'] != 'none':
        state_stats[st]['covered_enroll'] += r['enrollment']
    if r['confidence'] in ('confirmed', 'high'):
        state_stats[st]['confirmed_enroll'] += r['enrollment']

for st, s in sorted(state_stats.items(), key=lambda x: -x[1]['total_enroll'])[:25]:
    cov = s['covered_enroll']/s['total_enroll']*100 if s['total_enroll'] else 0
    conf = s['confirmed_enroll']/s['total_enroll']*100 if s['total_enroll'] else 0
    print(f"  {st}: {s['districts']:5d} districts, {s['total_enroll']:10,} students, {cov:3.0f}% covered, {conf:3.0f}% confirmed")

print(f"\nWrote: districts_comprehensive.csv")
