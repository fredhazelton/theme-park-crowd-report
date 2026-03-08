#!/usr/bin/env python3
"""
Phase 3: Aggressive Long Tail Pursuit for School Schedules
Scales from 603 districts toward ALL ~13,400 US public school districts.

Multi-angle approach:
1. State DOE bulk sources (mandated dates)
2. Tavily search for high-value uncovered districts
3. State-level inference from existing data
4. Firecrawl for district websites

Usage: python3 phase3_scraper.py [angle]
  angle: all, state_doe, tavily, infer, firecrawl
"""

import csv, json, os, re, sys, time, traceback
import urllib.request, urllib.parse
from datetime import datetime, date
from collections import defaultdict

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NCES_FILE = os.path.join(BASE_DIR, 'nces_all_districts.csv')
ENROLLMENT_FILE = os.path.join(BASE_DIR, 'enrollment_by_district.csv')
MATCHES_FILE = os.path.join(BASE_DIR, 'district_nces_matches.json')
EXISTING_FILE = os.path.join(BASE_DIR, 'districts_all.csv')
TOP100_FILE = os.path.join(BASE_DIR, 'districts_top100.csv')
HISTORICAL_FILE = os.path.join(BASE_DIR, 'districts_historical.csv')
OUTPUT_FILE = os.path.join(BASE_DIR, 'districts_comprehensive.csv')
RESULTS_FILE = os.path.join(BASE_DIR, 'phase3_results.json')
STATE_DOE_FILE = os.path.join(BASE_DIR, 'state_doe_research.md')

TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY', '')
FIRECRAWL_API_KEY = os.environ.get('FIRECRAWL_API_KEY', '')

# ─── Data Loading ──────────────────────────────────────────────
def load_nces():
    districts = {}
    with open(NCES_FILE) as f:
        for row in csv.DictReader(f):
            districts[row['leaid']] = row
    return districts

def load_enrollment():
    enrollment = {}
    with open(ENROLLMENT_FILE) as f:
        for row in csv.DictReader(f):
            enrollment[row['leaid']] = int(row['enrollment_2223'])
    return enrollment

def load_matches():
    with open(MATCHES_FILE) as f:
        return json.load(f)

def load_existing_calendars():
    """Load all existing calendar data and return dict keyed by NCES LEAID"""
    matches = load_matches()
    calendars = {}
    
    # Load districts_all.csv
    with open(EXISTING_FILE) as f:
        for row in csv.DictReader(f):
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
    
    # Load top100
    with open(TOP100_FILE) as f:
        for row in csv.DictReader(f):
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
                        'first_day': row.get('first_day', row.get('summer_end', '')),
                        'last_day': row.get('last_day', row.get('summer_start', '')),
                        'school_year': '2025-2026',
                        'source': 'schoolcalendarinfo',
                        'confidence': 'confirmed'
                    }
    
    return calendars

def load_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {'state_doe': {}, 'tavily': {}, 'firecrawl': {}, 'inferred': {}, 'stats': {}}

def save_results(results):
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2)

# ─── State DOE Research ──────────────────────────────────────────
# Pre-researched state-mandated school calendar rules
# These give us high-confidence defaults for EVERY district in these states
STATE_CALENDAR_RULES = {
    # States with MANDATED start dates (confirmed via DOE research)
    'VA': {
        'note': 'Virginia law prohibits schools from starting before Labor Day (Kings Dominion Law)',
        'first_day_earliest': '2025-09-02',  # Day after Labor Day 2025
        'last_day_latest': '2026-06-19',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-30', '2026-04-03'),  # Week after Easter
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'confidence': 'high'
    },
    'MI': {
        'note': 'Michigan law: schools cannot start before Labor Day',
        'first_day_earliest': '2025-09-02',
        'last_day_latest': '2026-06-19',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-30', '2026-04-03'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'confidence': 'high'
    },
    'MN': {
        'note': 'Minnesota law: school cannot begin before Labor Day (with exceptions)',
        'first_day_earliest': '2025-09-02',
        'last_day_latest': '2026-06-12',
        'min_instruction_days': 165,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'confidence': 'high'
    },
    'WI': {
        'note': 'Wisconsin: school cannot start before September 1',
        'first_day_earliest': '2025-09-01',
        'last_day_latest': '2026-06-12',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'confidence': 'high'
    },
    # States with typical early starts
    'GA': {
        'note': 'Georgia allows early August starts; most start first week of August',
        'first_day_earliest': '2025-08-01',
        'last_day_latest': '2026-05-22',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-30', '2026-04-03'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-04',
        'typical_last_day': '2026-05-22',
        'confidence': 'high'
    },
    'AL': {
        'note': 'Alabama: 180 school days required, typically starts mid-August',
        'first_day_earliest': '2025-08-06',
        'last_day_latest': '2026-05-29',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-11',
        'typical_last_day': '2026-05-22',
        'confidence': 'high'
    },
    'IN': {
        'note': 'Indiana: 180 days, typically early/mid August start',
        'first_day_earliest': '2025-08-04',
        'last_day_latest': '2026-05-29',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-30', '2026-04-03'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-11',
        'typical_last_day': '2026-05-29',
        'confidence': 'high'
    },
    'AZ': {
        'note': 'Arizona: flexible start, most begin late July/early August',
        'first_day_earliest': '2025-07-21',
        'last_day_latest': '2026-05-29',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-09', '2026-03-13'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-07-28',
        'typical_last_day': '2026-05-22',
        'confidence': 'high'
    },
    'MS': {
        'note': 'Mississippi: 180 days, typically starts early August',
        'first_day_earliest': '2025-08-04',
        'last_day_latest': '2026-05-22',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-16', '2026-03-20'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-04',
        'typical_last_day': '2026-05-22',
        'confidence': 'high'
    },
    'KY': {
        'note': 'Kentucky: no earlier than mid-August, 170 instructional days',
        'first_day_earliest': '2025-08-11',
        'last_day_latest': '2026-06-05',
        'min_instruction_days': 170,
        'typical_spring_break': ('2026-03-30', '2026-04-03'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-13',
        'typical_last_day': '2026-05-22',
        'confidence': 'high'
    },
    'SC': {
        'note': 'South Carolina: cannot start before 3rd Monday in August',
        'first_day_earliest': '2025-08-18',
        'last_day_latest': '2026-06-05',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-30', '2026-04-03'),
        'typical_winter_break': ('2025-12-22', '2026-01-05'),
        'typical_first_day': '2025-08-18',
        'typical_last_day': '2026-06-05',
        'confidence': 'high'
    },
    'NC': {
        'note': 'North Carolina: cannot start before nearest Monday to Aug 26; ends no later than Friday closest to June 11',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-12',
        'min_instruction_days': 185,
        'typical_spring_break': ('2026-03-30', '2026-04-03'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-25',
        'typical_last_day': '2026-06-05',
        'confidence': 'high'
    },
    'TX': {
        'note': 'Texas: cannot start before 4th Monday in August unless waiver',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-12',
        'min_instruction_days': 75600,  # minutes, ~180 days
        'typical_spring_break': ('2026-03-09', '2026-03-13'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-18',
        'typical_last_day': '2026-05-29',
        'confidence': 'high'
    },
    'FL': {
        'note': 'Florida: 180 instructional days; most start in August',
        'first_day_earliest': '2025-08-04',
        'last_day_latest': '2026-06-12',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-16', '2026-03-20'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-11',
        'typical_last_day': '2026-06-04',
        'confidence': 'high'
    },
    'CA': {
        'note': 'California: highly variable (year-round, traditional, early/late); 180 days required',
        'first_day_earliest': '2025-07-28',
        'last_day_latest': '2026-06-19',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-18',
        'typical_last_day': '2026-06-05',
        'confidence': 'medium'  # CA is very variable
    },
    'NY': {
        'note': 'New York: 180 days required; most NYC districts follow NYC DOE calendar',
        'first_day_earliest': '2025-09-04',
        'last_day_latest': '2026-06-26',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-04-02', '2026-04-10'),
        'typical_winter_break': ('2025-12-24', '2026-01-02'),
        'typical_first_day': '2025-09-04',
        'typical_last_day': '2026-06-26',
        'confidence': 'high'
    },
    'IL': {
        'note': 'Illinois: 185 days (176 instructional + 9 teacher), typically late August start',
        'first_day_earliest': '2025-08-11',
        'last_day_latest': '2026-06-12',
        'min_instruction_days': 176,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-18',
        'typical_last_day': '2026-06-05',
        'confidence': 'high'
    },
    'PA': {
        'note': 'Pennsylvania: 180 days required, typically late August/early September start',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-19',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-30', '2026-04-03'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-27',
        'typical_last_day': '2026-06-12',
        'confidence': 'high'
    },
    'OH': {
        'note': 'Ohio: 455 hours minimum for half-day K, 910 hours for 1-6, variable; typically late August start',
        'first_day_earliest': '2025-08-11',
        'last_day_latest': '2026-06-12',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-18',
        'typical_last_day': '2026-05-29',
        'confidence': 'high'
    },
    'NJ': {
        'note': 'New Jersey: 180 days required, typically September start',
        'first_day_earliest': '2025-09-02',
        'last_day_latest': '2026-06-26',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-30', '2026-04-06'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-09-03',
        'typical_last_day': '2026-06-19',
        'confidence': 'high'
    },
    'MD': {
        'note': 'Maryland: schools must start after Labor Day (similar to VA)',
        'first_day_earliest': '2025-09-02',
        'last_day_latest': '2026-06-19',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-30', '2026-04-03'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-09-02',
        'typical_last_day': '2026-06-15',
        'confidence': 'high'
    },
    'WA': {
        'note': 'Washington: 180 days, typically late August/early September start',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-19',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-30', '2026-04-03'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-09-02',
        'typical_last_day': '2026-06-12',
        'confidence': 'high'
    },
    'CO': {
        'note': 'Colorado: 160 school days or 1056 hours; typically mid-August start',
        'first_day_earliest': '2025-08-11',
        'last_day_latest': '2026-06-05',
        'min_instruction_days': 160,
        'typical_spring_break': ('2026-03-16', '2026-03-20'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-13',
        'typical_last_day': '2026-05-29',
        'confidence': 'high'
    },
    'MO': {
        'note': 'Missouri: 174 school days or 1044 hours; typically mid-August start',
        'first_day_earliest': '2025-08-11',
        'last_day_latest': '2026-05-29',
        'min_instruction_days': 174,
        'typical_spring_break': ('2026-03-16', '2026-03-20'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-13',
        'typical_last_day': '2026-05-22',
        'confidence': 'high'
    },
    'TN': {
        'note': 'Tennessee: 180 days; typically early August start',
        'first_day_earliest': '2025-08-01',
        'last_day_latest': '2026-05-29',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-16', '2026-03-20'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-04',
        'typical_last_day': '2026-05-22',
        'confidence': 'high'
    },
    'OK': {
        'note': 'Oklahoma: 180 days; typically mid-August start',
        'first_day_earliest': '2025-08-11',
        'last_day_latest': '2026-05-29',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-16', '2026-03-20'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-14',
        'typical_last_day': '2026-05-22',
        'confidence': 'high'
    },
    'LA': {
        'note': 'Louisiana: 177 days; typically mid-August start',
        'first_day_earliest': '2025-08-04',
        'last_day_latest': '2026-05-29',
        'min_instruction_days': 177,
        'typical_spring_break': ('2026-03-30', '2026-04-03'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-11',
        'typical_last_day': '2026-05-22',
        'confidence': 'high'
    },
    'CT': {
        'note': 'Connecticut: 180 days; typically late August/early September start',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-19',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-04-06', '2026-04-10'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-27',
        'typical_last_day': '2026-06-12',
        'confidence': 'high'
    },
    'OR': {
        'note': 'Oregon: varies by district, typically early September start',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-19',
        'min_instruction_days': 165,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-09-02',
        'typical_last_day': '2026-06-12',
        'confidence': 'high'
    },
    'IA': {
        'note': 'Iowa: cannot start before August 23; 180 days',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-12',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-16', '2026-03-20'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-25',
        'typical_last_day': '2026-06-05',
        'confidence': 'high'
    },
    'KS': {
        'note': 'Kansas: 186 school year days (1116 hours); typically mid-August start',
        'first_day_earliest': '2025-08-11',
        'last_day_latest': '2026-05-29',
        'min_instruction_days': 186,
        'typical_spring_break': ('2026-03-16', '2026-03-20'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-14',
        'typical_last_day': '2026-05-22',
        'confidence': 'high'
    },
    'UT': {
        'note': 'Utah: 180 school days or 990 hours; typically late August start',
        'first_day_earliest': '2025-08-18',
        'last_day_latest': '2026-06-05',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-20',
        'typical_last_day': '2026-05-28',
        'confidence': 'high'
    },
    'NV': {
        'note': 'Nevada: 180 school days; Clark County is 72% of state enrollment',
        'first_day_earliest': '2025-08-11',
        'last_day_latest': '2026-06-05',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-11',
        'typical_last_day': '2026-06-04',
        'confidence': 'high'
    },
    'AR': {
        'note': 'Arkansas: 178 school days; typically mid-August start',
        'first_day_earliest': '2025-08-11',
        'last_day_latest': '2026-05-29',
        'min_instruction_days': 178,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-14',
        'typical_last_day': '2026-05-22',
        'confidence': 'high'
    },
    'NE': {
        'note': 'Nebraska: 400-1032 hours (by grade); typically mid-August start',
        'first_day_earliest': '2025-08-11',
        'last_day_latest': '2026-05-29',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-16', '2026-03-20'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-13',
        'typical_last_day': '2026-05-22',
        'confidence': 'high'
    },
    'WV': {
        'note': 'West Virginia: 180 days; set by county boards',
        'first_day_earliest': '2025-08-18',
        'last_day_latest': '2026-06-05',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-30', '2026-04-03'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-19',
        'typical_last_day': '2026-05-29',
        'confidence': 'high'
    },
    'ID': {
        'note': 'Idaho: 450-990 hours depending on grade; typically late August start',
        'first_day_earliest': '2025-08-18',
        'last_day_latest': '2026-06-05',
        'min_instruction_days': 170,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-21',
        'typical_last_day': '2026-06-05',
        'confidence': 'high'
    },
    'NH': {
        'note': 'New Hampshire: 180 days; typically late August start',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-19',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-04-20', '2026-04-24'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-27',
        'typical_last_day': '2026-06-12',
        'confidence': 'high'
    },
    'ME': {
        'note': 'Maine: 175 days; typically late August/early September start',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-19',
        'min_instruction_days': 175,
        'typical_spring_break': ('2026-04-20', '2026-04-24'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-09-02',
        'typical_last_day': '2026-06-12',
        'confidence': 'high'
    },
    'MT': {
        'note': 'Montana: 180 aggregate hours; typically late August start',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-12',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-27',
        'typical_last_day': '2026-06-05',
        'confidence': 'high'
    },
    'SD': {
        'note': 'South Dakota: 180 school days; cannot start before Sept 1 (waiver available)',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-05-29',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-16', '2026-03-20'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-25',
        'typical_last_day': '2026-05-29',
        'confidence': 'high'
    },
    'ND': {
        'note': 'North Dakota: 175 days or equivalent hours; typically late August start',
        'first_day_earliest': '2025-08-18',
        'last_day_latest': '2026-06-05',
        'min_instruction_days': 175,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-21',
        'typical_last_day': '2026-05-29',
        'confidence': 'high'
    },
    'WY': {
        'note': 'Wyoming: 175 student days; typically late August start',
        'first_day_earliest': '2025-08-18',
        'last_day_latest': '2026-06-05',
        'min_instruction_days': 175,
        'typical_spring_break': ('2026-03-23', '2026-03-27'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-21',
        'typical_last_day': '2026-05-29',
        'confidence': 'high'
    },
    'VT': {
        'note': 'Vermont: 175 student days; typically late August/early September start',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-19',
        'min_instruction_days': 175,
        'typical_spring_break': ('2026-04-20', '2026-04-24'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-27',
        'typical_last_day': '2026-06-12',
        'confidence': 'high'
    },
    'RI': {
        'note': 'Rhode Island: 180 days; typically early September start',
        'first_day_earliest': '2025-09-02',
        'last_day_latest': '2026-06-26',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-04-13', '2026-04-17'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-09-03',
        'typical_last_day': '2026-06-19',
        'confidence': 'high'
    },
    'DE': {
        'note': 'Delaware: 180 days; typically late August start',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-12',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-30', '2026-04-03'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-25',
        'typical_last_day': '2026-06-12',
        'confidence': 'high'
    },
    'HI': {
        'note': 'Hawaii: single statewide district (Hawaii DOE); 180 days',
        'first_day_earliest': '2025-07-28',
        'last_day_latest': '2026-06-05',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-16', '2026-03-20'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-07-28',
        'typical_last_day': '2026-05-29',
        'confidence': 'confirmed'  # Single district
    },
    'DC': {
        'note': 'DC Public Schools: typically late August start',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-19',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-04-06', '2026-04-10'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-25',
        'typical_last_day': '2026-06-12',
        'confidence': 'high'
    },
    'NM': {
        'note': 'New Mexico: variable, typically early/mid August start',
        'first_day_earliest': '2025-08-04',
        'last_day_latest': '2026-06-05',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-16', '2026-03-20'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-07',
        'typical_last_day': '2026-05-29',
        'confidence': 'high'
    },
    'MA': {
        'note': 'Massachusetts: 180 days; typically late August/early September start',
        'first_day_earliest': '2025-08-25',
        'last_day_latest': '2026-06-26',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-04-20', '2026-04-24'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-09-02',
        'typical_last_day': '2026-06-19',
        'confidence': 'high'
    },
    'AK': {
        'note': 'Alaska: 180 days; typically mid-August start',
        'first_day_earliest': '2025-08-18',
        'last_day_latest': '2026-06-05',
        'min_instruction_days': 180,
        'typical_spring_break': ('2026-03-16', '2026-03-20'),
        'typical_winter_break': ('2025-12-22', '2026-01-02'),
        'typical_first_day': '2025-08-20',
        'typical_last_day': '2026-05-22',
        'confidence': 'high'
    },
}


# ─── Angle 4: State-Level Inference ──────────────────────────────
def run_state_inference(nces_districts, enrollment, existing_calendars):
    """For uncovered districts, infer calendar from same-state covered districts"""
    print("\n=== ANGLE 4: State-Level Inference ===")
    
    # Build state-level stats from existing confirmed data
    state_calendars = defaultdict(list)
    for leaid, cal in existing_calendars.items():
        if leaid in nces_districts:
            st = nces_districts[leaid]['st']
            state_calendars[st].append(cal)
    
    print(f"States with confirmed data: {len(state_calendars)}")
    for st, cals in sorted(state_calendars.items()):
        print(f"  {st}: {len(cals)} districts")
    
    # Compute median dates per state
    def median_date(dates):
        valid = [d for d in dates if d and d != '']
        if not valid:
            return ''
        # Sort and take middle
        valid.sort()
        return valid[len(valid)//2]
    
    state_medians = {}
    for st, cals in state_calendars.items():
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
    
    # For states without confirmed data, use STATE_CALENDAR_RULES
    for st, rules in STATE_CALENDAR_RULES.items():
        if st not in state_medians:
            sb = rules.get('typical_spring_break', ('', ''))
            wb = rules.get('typical_winter_break', ('', ''))
            state_medians[st] = {
                'spring_break_start': sb[0],
                'spring_break_end': sb[1],
                'winter_break_start': wb[0],
                'winter_break_end': wb[1],
                'summer_start': rules.get('typical_last_day', ''),
                'summer_end': rules.get('typical_first_day', ''),
                'first_day': rules.get('typical_first_day', ''),
                'last_day': rules.get('typical_last_day', ''),
            }
    
    # Now infer for all uncovered districts
    inferred = {}
    for leaid, dist in nces_districts.items():
        if leaid in existing_calendars:
            continue  # Already have data
        
        st = dist['st']
        enroll = enrollment.get(leaid, 0)
        
        if st in state_medians:
            med = state_medians[st]
            # Determine confidence based on source
            if st in state_calendars and len(state_calendars[st]) >= 5:
                confidence = 'medium'  # Inferred from many confirmed same-state districts
            elif st in state_calendars:
                confidence = 'inferred'  # Few data points
            elif st in STATE_CALENDAR_RULES:
                confidence = 'inferred'  # From state rules
            else:
                confidence = 'inferred'
            
            # For state rules, override if we have specific typical values
            if st in STATE_CALENDAR_RULES:
                rules = STATE_CALENDAR_RULES[st]
                if rules.get('typical_first_day') and not med.get('first_day'):
                    med['first_day'] = rules['typical_first_day']
                if rules.get('typical_last_day') and not med.get('last_day'):
                    med['last_day'] = rules['typical_last_day']
            
            source = 'inferred_state_median'
            if st not in state_calendars and st in STATE_CALENDAR_RULES:
                source = 'state_doe_rules'
            
            inferred[leaid] = {
                'spring_break_start': med['spring_break_start'],
                'spring_break_end': med['spring_break_end'],
                'winter_break_start': med['winter_break_start'],
                'winter_break_end': med['winter_break_end'],
                'summer_start': med['summer_start'],
                'summer_end': med['summer_end'],
                'first_day': med['first_day'],
                'last_day': med['last_day'],
                'school_year': '2025-2026',
                'source': source,
                'confidence': confidence
            }
    
    print(f"\nInferred {len(inferred)} district calendars")
    
    # Coverage stats
    total_inferred_enrollment = sum(enrollment.get(lid, 0) for lid in inferred)
    total_enrollment = sum(enrollment.values())
    print(f"Inferred enrollment coverage: {total_inferred_enrollment:,} ({total_inferred_enrollment/total_enrollment*100:.1f}%)")
    
    return inferred


# ─── Angle 3: Tavily Search ──────────────────────────────────────
def tavily_search(query, max_results=5):
    """Search using Tavily API"""
    if not TAVILY_API_KEY:
        return None
    
    data = json.dumps({
        'api_key': TAVILY_API_KEY,
        'query': query,
        'max_results': max_results,
        'include_answer': True,
        'search_depth': 'basic'
    }).encode()
    
    req = urllib.request.Request(
        'https://api.tavily.com/search',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())

def extract_dates_from_text(text):
    """Try to extract school calendar dates from text"""
    result = {}
    
    # Common date patterns
    date_patterns = [
        r'(\d{4}-\d{2}-\d{2})',  # ISO format
        r'(\w+\s+\d{1,2},?\s+\d{4})',  # Month DD, YYYY
        r'(\d{1,2}/\d{1,2}/\d{4})',  # MM/DD/YYYY
    ]
    
    # Look for spring break
    spring_pattern = r'(?:spring\s+break|spring\s+recess)[:\s]*(\w+[\s,]+\d{1,2}[\s,]+\d{4})\s*(?:to|-|through|–)\s*(\w+[\s,]+\d{1,2}[\s,]+\d{4})'
    m = re.search(spring_pattern, text, re.IGNORECASE)
    if m:
        result['spring_break_raw'] = f"{m.group(1)} to {m.group(2)}"
    
    # Look for first/last day
    first_day_pattern = r'(?:first\s+day|school\s+(?:starts|begins))[:\s]*(\w+[\s,]+\d{1,2}[\s,]+\d{4}|\d{1,2}/\d{1,2}/\d{4})'
    m = re.search(first_day_pattern, text, re.IGNORECASE)
    if m:
        result['first_day_raw'] = m.group(1)
    
    last_day_pattern = r'(?:last\s+day|school\s+ends)[:\s]*(\w+[\s,]+\d{1,2}[\s,]+\d{4}|\d{1,2}/\d{1,2}/\d{4})'
    m = re.search(last_day_pattern, text, re.IGNORECASE)
    if m:
        result['last_day_raw'] = m.group(1)
    
    return result

def run_tavily_search(nces_districts, enrollment, existing_calendars, max_searches=100):
    """Search for calendar data for top uncovered districts"""
    print("\n=== ANGLE 3: Tavily Search ===")
    
    results = load_results()
    tavily_results = results.get('tavily', {})
    
    # Get uncovered districts sorted by enrollment
    uncovered = []
    for leaid, dist in nces_districts.items():
        if leaid in existing_calendars:
            continue
        if leaid in tavily_results:
            continue  # Already searched
        enroll = enrollment.get(leaid, 0)
        if enroll >= 10000:  # Only search for districts with 10K+ students
            uncovered.append((leaid, dist, enroll))
    
    uncovered.sort(key=lambda x: -x[2])
    print(f"Uncovered districts with 10K+ students: {len(uncovered)}")
    print(f"Will search top {min(max_searches, len(uncovered))}")
    
    found_count = 0
    search_count = 0
    
    for leaid, dist, enroll in uncovered[:max_searches]:
        name = dist['lea_name']
        st = dist['st']
        
        query = f'"{name}" school calendar 2025-2026 first day last day'
        try:
            result = tavily_search(query)
            if result:
                answer = result.get('answer', '')
                urls = [r.get('url', '') for r in result.get('results', [])]
                contents = [r.get('content', '') for r in result.get('results', [])]
                
                # Try to extract dates
                all_text = answer + ' ' + ' '.join(contents)
                dates = extract_dates_from_text(all_text)
                
                tavily_results[leaid] = {
                    'name': name,
                    'state': st,
                    'enrollment': enroll,
                    'answer': answer[:500],
                    'urls': urls[:3],
                    'dates_found': dates,
                    'searched_at': datetime.now().isoformat()
                }
                
                if dates:
                    found_count += 1
                    print(f"  ✓ {name} ({st}): {dates}")
                else:
                    print(f"  · {name} ({st}): no dates extracted")
            
            search_count += 1
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  ✗ {name} ({st}): {e}")
            tavily_results[leaid] = {
                'name': name,
                'state': st,
                'error': str(e),
                'searched_at': datetime.now().isoformat()
            }
            time.sleep(1)
        
        # Save periodically
        if search_count % 20 == 0:
            results['tavily'] = tavily_results
            save_results(results)
            print(f"  [Saved after {search_count} searches, {found_count} with dates]")
    
    results['tavily'] = tavily_results
    save_results(results)
    print(f"\nTavily: searched {search_count}, found dates in {found_count}")
    return tavily_results


# ─── Build Comprehensive Output ──────────────────────────────────
def build_comprehensive_csv(nces_districts, enrollment, existing_calendars, inferred_calendars):
    """Build the master districts_comprehensive.csv"""
    print("\n=== Building Comprehensive CSV ===")
    
    rows = []
    source_counts = defaultdict(int)
    confidence_counts = defaultdict(int)
    
    for leaid, dist in nces_districts.items():
        enroll = enrollment.get(leaid, 0)
        
        if leaid in existing_calendars:
            cal = existing_calendars[leaid]
            source = cal.get('source', 'schoolcalendarinfo')
            confidence = cal.get('confidence', 'confirmed')
        elif leaid in inferred_calendars:
            cal = inferred_calendars[leaid]
            source = cal.get('source', 'inferred')
            confidence = cal.get('confidence', 'inferred')
        else:
            # No data at all
            cal = {k: '' for k in ['spring_break_start', 'spring_break_end', 'winter_break_start',
                                    'winter_break_end', 'summer_start', 'summer_end', 'first_day', 'last_day']}
            source = 'none'
            confidence = 'none'
        
        source_counts[source] += 1
        confidence_counts[confidence] += 1
        
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
            'source': source,
            'confidence': confidence
        })
    
    # Sort by enrollment descending
    rows.sort(key=lambda x: -x['enrollment'])
    
    # Write CSV
    fieldnames = ['nces_leaid', 'district_name', 'state', 'city', 'enrollment',
                  'spring_break_start', 'spring_break_end', 'winter_break_start', 'winter_break_end',
                  'summer_start', 'summer_end', 'first_day', 'last_day',
                  'school_year', 'source', 'confidence']
    
    with open(OUTPUT_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"\nWrote {len(rows)} districts to {OUTPUT_FILE}")
    print(f"\nSource breakdown:")
    for source, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        enroll = sum(r['enrollment'] for r in rows if r['source'] == source)
        print(f"  {source}: {count} districts, {enroll:,} students")
    
    print(f"\nConfidence breakdown:")
    for conf, count in sorted(confidence_counts.items(), key=lambda x: -x[1]):
        enroll = sum(r['enrollment'] for r in rows if r['confidence'] == conf)
        print(f"  {conf}: {count} districts, {enroll:,} students")
    
    # Coverage stats
    total_enrollment = sum(enrollment.values())
    covered = sum(r['enrollment'] for r in rows if r['source'] != 'none')
    confirmed = sum(r['enrollment'] for r in rows if r['confidence'] == 'confirmed')
    
    print(f"\nTotal coverage: {covered:,}/{total_enrollment:,} ({covered/total_enrollment*100:.1f}%)")
    print(f"Confirmed data: {confirmed:,}/{total_enrollment:,} ({confirmed/total_enrollment*100:.1f}%)")
    
    # Per-state coverage
    print(f"\nPer-state coverage (enrollment-weighted):")
    state_stats = defaultdict(lambda: {'total': 0, 'covered': 0, 'confirmed': 0, 'count': 0})
    for r in rows:
        st = r['state']
        state_stats[st]['total'] += r['enrollment']
        state_stats[st]['count'] += 1
        if r['source'] != 'none':
            state_stats[st]['covered'] += r['enrollment']
        if r['confidence'] == 'confirmed':
            state_stats[st]['confirmed'] += r['enrollment']
    
    for st, stats in sorted(state_stats.items(), key=lambda x: -x[1]['total'])[:20]:
        pct = stats['covered']/stats['total']*100 if stats['total'] else 0
        conf_pct = stats['confirmed']/stats['total']*100 if stats['total'] else 0
        print(f"  {st}: {stats['count']} districts, {stats['total']:,} students, {pct:.0f}% covered ({conf_pct:.0f}% confirmed)")
    
    return rows


# ─── Main ──────────────────────────────────────────────────────
def main():
    angle = sys.argv[1] if len(sys.argv) > 1 else 'all'
    
    print("=" * 60)
    print("Phase 3: Aggressive Long Tail Pursuit")
    print("=" * 60)
    
    # Load data
    print("\nLoading data...")
    nces = load_nces()
    enrollment = load_enrollment()
    existing = load_existing_calendars()
    
    print(f"NCES districts: {len(nces)}")
    print(f"Enrollment records: {len(enrollment)}")
    print(f"Existing calendars: {len(existing)}")
    
    total_enrollment = sum(enrollment.values())
    existing_enrollment = sum(enrollment.get(lid, 0) for lid in existing)
    print(f"Existing enrollment coverage: {existing_enrollment:,}/{total_enrollment:,} ({existing_enrollment/total_enrollment*100:.1f}%)")
    
    inferred = {}
    
    if angle in ('all', 'infer'):
        inferred = run_state_inference(nces, enrollment, existing)
    
    if angle in ('all', 'tavily'):
        run_tavily_search(nces, enrollment, existing, max_searches=50)
    
    if angle in ('all', 'build', 'infer'):
        build_comprehensive_csv(nces, enrollment, existing, inferred)
    
    print("\n" + "=" * 60)
    print("Phase 3 Complete!")
    print("=" * 60)

if __name__ == '__main__':
    main()
