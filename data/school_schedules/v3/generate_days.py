#!/usr/bin/env python3
"""Generate day-level school calendar rows from key dates.

Takes extracted key dates (first_day, last_day, breaks, holidays) and expands
them into one row per day per district per school year.

Logic:
  - Before first_day → SUMMER
  - After last_day → SUMMER  
  - Sat/Sun → WEEKEND
  - Extracted non-school days → BREAK/HOLIDAY/TEACHER_WORKDAY/HALF_DAY
  - Everything else between first_day and last_day → SCHOOL_DAY

Input: key dates JSON (from scraper)
Output: SQLite database (school_schedules.db)
"""

import argparse
import csv
import json
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
V3_DIR = Path(__file__).parent
DB_PATH = V3_DIR / "school_schedules.db"
SCHEMA_PATH = V3_DIR / "schema.sql"

# Existing data sources
LLM_RESULTS = BASE_DIR / "llm_scraper_results.json"
PIPELINE_V2_RESULTS = BASE_DIR / "pipeline_v2_results.json"
NCES_FILE = BASE_DIR / "nces_all_districts.csv"

DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def init_db() -> sqlite3.Connection:
    """Initialize SQLite database with schema."""
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_PATH) as f:
        db.executescript(f.read())
    return db


def load_nces() -> dict:
    """Load NCES district data."""
    districts = {}
    if NCES_FILE.exists():
        with open(NCES_FILE) as f:
            for row in csv.DictReader(f):
                districts[row['leaid']] = row
    return districts


def make_district_id(state: str, nces_id: str) -> str:
    """Generate our district_id from state + NCES ID."""
    return f"{state.upper()}_{nces_id}"


def parse_date(s) -> date | None:
    """Parse a date string, return None if invalid."""
    if not s or s in ('null', 'None', ''):
        return None
    try:
        return date.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


def detect_school_year(first_day: date | None, last_day: date | None, 
                       spring_break: date | None) -> str:
    """Detect school year from extracted dates."""
    # Use first_day year as the start year
    if first_day:
        return f"{first_day.year}-{first_day.year + 1}"
    # Fall back to spring break (always in the end year)
    if spring_break:
        return f"{spring_break.year - 1}-{spring_break.year}"
    if last_day:
        return f"{last_day.year - 1}-{last_day.year}"
    return "2025-2026"  # default


def school_year_date_range(school_year: str) -> tuple[date, date]:
    """Return Aug 1 of start year to Jul 31 of end year."""
    parts = school_year.split('-')
    start_year = int(parts[0])
    end_year = int(parts[1])
    return date(start_year, 8, 1), date(end_year, 7, 31)


def build_exception_map(key_dates: dict) -> dict[date, tuple[str, str]]:
    """Build a map of date → (day_type, break_name) from key dates.
    
    Handles: spring_break, winter_break, fall_break, thanksgiving_break,
    and the other_breaks array.
    """
    exceptions = {}
    
    # Named break pairs
    break_pairs = [
        ('spring_break_start', 'spring_break_end', 'BREAK', 'SPRING'),
        ('winter_break_start', 'winter_break_end', 'BREAK', 'WINTER'),
        ('fall_break_start', 'fall_break_end', 'BREAK', 'FALL'),
        ('thanksgiving_break_start', 'thanksgiving_break_end', 'BREAK', 'THANKSGIVING'),
    ]
    
    for start_key, end_key, day_type, break_name in break_pairs:
        start = parse_date(key_dates.get(start_key))
        end = parse_date(key_dates.get(end_key))
        if start and end:
            d = start
            while d <= end:
                exceptions[d] = (day_type, break_name)
                d += timedelta(days=1)
        elif start:
            # Single day break
            exceptions[start] = (day_type, break_name)
    
    # Other breaks (array of {name, start, end})
    for brk in key_dates.get('other_breaks', []):
        if isinstance(brk, dict):
            start = parse_date(brk.get('start'))
            end = parse_date(brk.get('end'))
            name = brk.get('name', 'OTHER').upper().replace(' ', '_')
            if start:
                end = end or start
                d = start
                while d <= end:
                    exceptions[d] = ('BREAK', name)
                    d += timedelta(days=1)
    
    # Non-school-day entries (holidays, teacher workdays)
    for item in key_dates.get('non_school_days', []):
        if isinstance(item, dict):
            d = parse_date(item.get('date'))
            end_d = parse_date(item.get('end_date'))
            day_type = item.get('type', 'HOLIDAY').upper()
            name = item.get('name', '').upper().replace(' ', '_') or None
            if d:
                end_d = end_d or d
                while d <= end_d:
                    exceptions[d] = (day_type, name)
                    d += timedelta(days=1)
    
    return exceptions


def generate_days(district_id: str, school_year: str, key_dates: dict,
                  source_id: int | None = None) -> list[tuple]:
    """Generate day-level rows for one district/year.
    
    Returns list of tuples matching fact_school_day columns.
    """
    first_day = parse_date(key_dates.get('first_day'))
    last_day = parse_date(key_dates.get('last_day'))
    
    # Get the full Aug 1 - Jul 31 range
    range_start, range_end = school_year_date_range(school_year)
    
    # Build exception map from all breaks/holidays
    exceptions = build_exception_map(key_dates)
    
    # Build saturday_sessions set (weekend days where students ARE in session)
    saturday_sessions = set()
    for item in key_dates.get('saturday_sessions', []):
        if isinstance(item, dict):
            sat_date = parse_date(item.get('date'))
            if sat_date:
                saturday_sessions.add(sat_date)
    
    rows = []
    d = range_start
    while d <= range_end:
        dow = d.weekday()  # 0=Mon, 6=Sun
        day_name = DAY_NAMES[dow]
        
        # Determine day status
        if d in exceptions:
            day_type, break_name = exceptions[d]
            is_in_session = 0 if day_type != 'HALF_DAY' else 1
            if day_type == 'HALF_DAY':
                is_in_session = 1  # Still in session, just shortened
        elif d in saturday_sessions:
            # Weekend day explicitly marked as in-session (makeup day, etc.)
            day_type = 'SCHOOL_DAY'
            break_name = None
            is_in_session = 1
        elif dow >= 5:  # Saturday or Sunday
            day_type = 'WEEKEND'
            break_name = None
            is_in_session = 0
        elif first_day and d < first_day:
            day_type = 'SUMMER'
            break_name = None
            is_in_session = 0
        elif last_day and d > last_day:
            day_type = 'SUMMER'
            break_name = None
            is_in_session = 0
        elif not first_day and not last_day:
            # No first/last day — can't determine, skip day-level generation
            day_type = 'UNKNOWN'
            break_name = None
            is_in_session = -1  # Unknown
        else:
            day_type = 'SCHOOL_DAY'
            break_name = None
            is_in_session = 1
        
        # Add notes for special days
        notes = None
        if first_day and d == first_day:
            notes = 'First day of school'
        elif last_day and d == last_day:
            notes = 'Last day of school'
        
        rows.append((
            district_id,
            source_id,
            d.isoformat(),
            dow,
            day_name,
            is_in_session,
            day_type,
            break_name,
            notes,
            school_year,
        ))
        
        d += timedelta(days=1)
    
    return rows


def upsert_district(db: sqlite3.Connection, district_id: str, nces_id: str,
                    name: str, state: str, nces_data: dict | None = None):
    """Insert or update a district in dim_district."""
    enrollment = None
    city = county = zip_code = lat = lon = district_url = None
    
    if nces_data:
        enrollment = int(nces_data.get('enrollment', 0) or 0) or None
        city = nces_data.get('lcity') or nces_data.get('city')
        county = nces_data.get('county_name')
        zip_code = nces_data.get('lzip')
        lat = float(nces_data.get('lat', 0) or 0) or None
        lon = float(nces_data.get('lon', 0) or 0) or None
        district_url = nces_data.get('website')
    
    db.execute("""
        INSERT INTO dim_district (district_id, nces_id, district_name, state,
            city, county, zip, lat, lon, enrollment, district_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(district_id) DO UPDATE SET
            district_name=excluded.district_name,
            enrollment=COALESCE(excluded.enrollment, dim_district.enrollment),
            city=COALESCE(excluded.city, dim_district.city),
            county=COALESCE(excluded.county, dim_district.county),
            district_url=COALESCE(excluded.district_url, dim_district.district_url),
            updated_at=datetime('now')
    """, (district_id, nces_id, name, state, city, county, zip_code, lat, lon,
          enrollment, district_url))


def upsert_source(db: sqlite3.Connection, district_id: str, school_year: str,
                  calendar_url: str | None, method: str | None,
                  key_dates: dict, confidence: str = 'medium') -> int:
    """Insert or update a calendar source. Returns source_id."""
    db.execute("""
        INSERT INTO dim_calendar_source (district_id, school_year, calendar_url,
            scrape_method, raw_key_dates, quality_confidence)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(district_id, school_year) DO UPDATE SET
            calendar_url=COALESCE(excluded.calendar_url, dim_calendar_source.calendar_url),
            scrape_method=COALESCE(excluded.scrape_method, dim_calendar_source.scrape_method),
            raw_key_dates=excluded.raw_key_dates,
            quality_confidence=excluded.quality_confidence,
            scrape_date=date('now')
    """, (district_id, school_year, calendar_url, method,
          json.dumps(key_dates), confidence))
    
    cur = db.execute(
        "SELECT source_id FROM dim_calendar_source WHERE district_id=? AND school_year=?",
        (district_id, school_year))
    return cur.fetchone()[0]


def import_existing_results(db: sqlite3.Connection, nces_lookup: dict):
    """Import existing LLM scraper + pipeline v2 results into the new schema."""
    imported = 0
    skipped = 0
    
    # Load all result sources
    sources = {}
    
    if LLM_RESULTS.exists():
        with open(LLM_RESULTS) as f:
            llm = json.load(f)
        for nid, entry in llm.items():
            if entry.get('status') == 'found':
                sources[nid] = entry
    
    if PIPELINE_V2_RESULTS.exists():
        with open(PIPELINE_V2_RESULTS) as f:
            v2 = json.load(f)
        for nid, entry in v2.items():
            if entry.get('status') == 'found':
                sources[nid] = entry  # v2 overrides LLM if both exist
    
    print(f"Found {len(sources)} districts with data to import")
    
    for nces_id, entry in sources.items():
        name = entry.get('name', '')
        state = entry.get('state', 'XX')
        
        if not name or not state:
            skipped += 1
            continue
        
        district_id = make_district_id(state, nces_id)
        nces_data = nces_lookup.get(nces_id)
        
        # Get dates
        dates = entry.get('dates', {})
        if not dates:
            skipped += 1
            continue
        
        # Detect school year
        first_day = parse_date(dates.get('first_day'))
        spring_break = parse_date(dates.get('spring_break_start'))
        last_day = parse_date(dates.get('last_day'))
        school_year = entry.get('school_year') or detect_school_year(first_day, last_day, spring_break)
        
        # Upsert district
        upsert_district(db, district_id, nces_id, name, state, nces_data)
        
        # Determine method and URL
        method = entry.get('method', entry.get('scrape_method', 'llm_extract'))
        url = entry.get('source_url', entry.get('url'))
        confidence = entry.get('confidence', 'medium')
        
        # Upsert source
        source_id = upsert_source(db, district_id, school_year, url, method,
                                  dates, confidence)
        
        # Generate day-level rows
        rows = generate_days(district_id, school_year, dates, source_id)
        
        # Delete existing days for this district/year and insert new ones
        db.execute("DELETE FROM fact_school_day WHERE district_id=? AND school_year=?",
                   (district_id, school_year))
        
        db.executemany("""
            INSERT INTO fact_school_day 
            (district_id, source_id, date, day_of_week, day_name, is_in_session,
             day_type, break_name, notes, school_year)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        
        imported += 1
        
        if imported % 500 == 0:
            db.commit()
            print(f"  Imported {imported} districts...")
    
    db.commit()
    return imported, skipped


def print_stats(db: sqlite3.Connection):
    """Print summary statistics."""
    print("\n" + "=" * 60)
    print("SCHOOL SCHEDULES DATABASE — SUMMARY")
    print("=" * 60)
    
    districts = db.execute("SELECT COUNT(*) FROM dim_district").fetchone()[0]
    sources = db.execute("SELECT COUNT(*) FROM dim_calendar_source").fetchone()[0]
    days = db.execute("SELECT COUNT(*) FROM fact_school_day").fetchone()[0]
    
    print(f"Districts: {districts:,}")
    print(f"Calendar sources: {sources:,}")
    print(f"Day-level rows: {days:,}")
    
    # By school year
    print("\nBy school year:")
    for row in db.execute("""
        SELECT school_year, COUNT(DISTINCT district_id) as districts, COUNT(*) as days
        FROM fact_school_day GROUP BY school_year ORDER BY school_year
    """):
        print(f"  {row[0]}: {row[1]:,} districts, {row[2]:,} rows")
    
    # By state (top 10)
    print("\nTop 10 states:")
    for row in db.execute("""
        SELECT state, COUNT(*) as n, SUM(COALESCE(enrollment,0)) as total_enrollment
        FROM dim_district GROUP BY state ORDER BY n DESC LIMIT 10
    """):
        print(f"  {row[0]}: {row[1]:,} districts, {row[2]:,} students")
    
    # Day type distribution
    print("\nDay type distribution:")
    for row in db.execute("""
        SELECT day_type, COUNT(*) as n, 
               ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM fact_school_day), 1) as pct
        FROM fact_school_day GROUP BY day_type ORDER BY n DESC
    """):
        print(f"  {row[0]}: {row[1]:,} ({row[2]}%)")
    
    # Break name distribution
    print("\nBreak types captured:")
    for row in db.execute("""
        SELECT break_name, COUNT(DISTINCT district_id) as districts, COUNT(*) as days
        FROM fact_school_day WHERE break_name IS NOT NULL 
        GROUP BY break_name ORDER BY districts DESC
    """):
        print(f"  {row[0]}: {row[1]:,} districts, {row[2]:,} days")
    
    # Sample query: peak spring break week
    print("\nPeak spring break dates (by # districts on break):")
    for row in db.execute("""
        SELECT date, COUNT(DISTINCT district_id) as districts_on_break
        FROM fact_school_day 
        WHERE break_name = 'SPRING' AND date BETWEEN '2026-03-01' AND '2026-04-30'
        GROUP BY date ORDER BY districts_on_break DESC LIMIT 10
    """):
        print(f"  {row[0]}: {row[1]:,} districts")
    
    print("=" * 60)
    
    # DB file size
    db_size = os.path.getsize(DB_PATH) / (1024 * 1024)
    print(f"\nDatabase size: {db_size:.1f} MB")


def main():
    parser = argparse.ArgumentParser(description='Generate day-level school calendar database')
    parser.add_argument('--stats-only', action='store_true', help='Just print stats')
    parser.add_argument('--rebuild', action='store_true', help='Drop and rebuild all tables')
    args = parser.parse_args()
    
    if args.stats_only:
        db = sqlite3.connect(str(DB_PATH))
        print_stats(db)
        db.close()
        return
    
    if args.rebuild and DB_PATH.exists():
        os.remove(DB_PATH)
        print("Removed existing database")
    
    print("Initializing database...")
    db = init_db()
    
    print("Loading NCES data...")
    nces = load_nces()
    print(f"  {len(nces):,} districts in NCES")
    
    print("Importing existing results...")
    imported, skipped = import_existing_results(db, nces)
    print(f"  Imported: {imported:,}, Skipped: {skipped:,}")
    
    print_stats(db)
    db.close()


if __name__ == '__main__':
    main()
