#!/usr/bin/env python3
"""
Build daily school calendar flag table from district break data.

Produces:
  - daily_calendar.csv.gz — one row per district per day (Jul 1 2025 - Jun 30 2026)
  - daily_aggregate.csv — daily summary with enrollment-weighted percentages

Usage:
  python3 build_daily_calendar.py
"""

import csv
import gzip
import re
import sys
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
TOP100_FILE = SCRIPT_DIR / "districts_top100.csv"
ALL_FILE = SCRIPT_DIR / "districts_all.csv"
CALENDAR_FILE = SCRIPT_DIR / "daily_calendar.csv.gz"
AGGREGATE_FILE = SCRIPT_DIR / "daily_aggregate.csv"

START_DATE = date(2025, 7, 1)
END_DATE = date(2026, 6, 30)

# Federal holidays for 2025-2026 school year
FEDERAL_HOLIDAYS = {
    date(2025, 9, 1): "federal_holiday",    # Labor Day
    date(2025, 10, 13): "federal_holiday",   # Columbus Day
    date(2025, 11, 11): "federal_holiday",   # Veterans Day
    date(2025, 11, 27): "thanksgiving_break", # Thanksgiving Thu
    date(2025, 11, 28): "thanksgiving_break", # Thanksgiving Fri
    date(2026, 1, 19): "federal_holiday",    # MLK Day
    date(2026, 2, 16): "federal_holiday",    # Presidents Day
    date(2026, 5, 25): "federal_holiday",    # Memorial Day
}

# ── Helper Functions ───────────────────────────────────────────────────

def parse_date(s):
    """Parse YYYY-MM-DD string to date, returns None if empty/invalid."""
    s = s.strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def clean_district_name(name):
    """Remove cruft like '2025-2026 in PDF', 'Holidays', etc."""
    name = re.sub(r'\s*(Holidays?\s*)?(\d{4}-\d{4}).*$', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s+', ' ', name)
    return name


def daterange(start, end):
    """Yield dates from start through end (inclusive)."""
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# ── Load Districts ─────────────────────────────────────────────────────

def load_top100():
    """Load top100 districts with enrollment."""
    districts = []
    with open(TOP100_FILE, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # In top100: summer_end = first day of school, summer_start = last day of school
            d = {
                'district_name': row['district_name'].strip(),
                'state': row['state'].strip(),
                'enrollment': int(row['students_2019']),
                'first_day': parse_date(row['summer_end']),  # summer_end IS first day
                'last_day': parse_date(row['summer_start']),  # summer_start IS last day
                'spring_break_start': parse_date(row['spring_break_start']),
                'spring_break_end': parse_date(row['spring_break_end']),
                'winter_break_start': parse_date(row['winter_break_start']),
                'winter_break_end': parse_date(row['winter_break_end']),
                'source': 'top100',
            }
            districts.append(d)
    return districts


def load_all_districts():
    """Load districts_all.csv (without enrollment)."""
    districts = []
    skipped = 0
    with open(ALL_FILE, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            first_day = parse_date(row.get('first_day', '') or row.get('summer_end', ''))
            last_day = parse_date(row.get('last_day', '') or row.get('summer_start', ''))

            # Validate dates are in the right school year (2025-2026)
            # first_day should be in 2025, last_day in 2025 or 2026
            if first_day and first_day.year < 2025:
                skipped += 1
                continue
            if last_day and last_day.year < 2025:
                skipped += 1
                continue

            d = {
                'district_name': clean_district_name(row['district_name']),
                'state': row['state'].strip(),
                'enrollment': None,  # Will be estimated
                'first_day': first_day,
                'last_day': last_day,
                'spring_break_start': parse_date(row['spring_break_start']),
                'spring_break_end': parse_date(row['spring_break_end']),
                'winter_break_start': parse_date(row['winter_break_start']),
                'winter_break_end': parse_date(row['winter_break_end']),
                'source': 'all',
            }
            districts.append(d)
    if skipped:
        print(f"  Skipped {skipped} districts with wrong-year dates")
    return districts


def deduplicate_districts(top100, all_districts):
    """
    Merge: top100 is authoritative. Remove duplicates from all_districts
    using fuzzy matching on name + state.
    """
    # Build set of (normalized_name, state) from top100
    def normalize(name):
        # Remove common suffixes for matching
        n = name.lower().strip()
        for suffix in [' public schools', ' school district', ' schools',
                       ' independent school district', ' isd', ' sd',
                       ' unified school district', ' unified',
                       ' county school district', ' county schools',
                       ' city schools', ' city school district']:
            n = n.replace(suffix, '')
        n = re.sub(r'\s*\(.*?\)', '', n)  # Remove parentheticals
        n = re.sub(r'\s+', ' ', n).strip()
        return n

    top100_keys = set()
    for d in top100:
        key = (normalize(d['district_name']), d['state'].lower())
        top100_keys.add(key)

    # Filter all_districts
    deduped = []
    dupes = 0
    for d in all_districts:
        key = (normalize(d['district_name']), d['state'].lower())
        if key in top100_keys:
            dupes += 1
        else:
            deduped.append(d)

    print(f"  Dedup: removed {dupes} duplicates from districts_all")
    return deduped


def estimate_enrollment(top100, other_districts):
    """
    Estimate enrollment for districts without it.
    Use state averages from top100, with a floor for small districts.
    """
    # Calculate state average from top100
    state_totals = defaultdict(lambda: {'total': 0, 'count': 0})
    for d in top100:
        state_totals[d['state']]['total'] += d['enrollment']
        state_totals[d['state']]['count'] += 1

    state_avg = {}
    for state, data in state_totals.items():
        state_avg[state] = data['total'] // data['count']

    # Overall average for states not in top100
    overall_avg = sum(d['enrollment'] for d in top100) // len(top100)
    # Districts in the "all" file are smaller — use a conservative estimate
    # Median US school district is ~3,500 students; these are larger since they
    # made it into a scraped dataset, so estimate ~15,000
    DEFAULT_ENROLLMENT = 15000

    for d in other_districts:
        if d['enrollment'] is None:
            # Use state average discounted (these are smaller districts)
            # or default
            avg = state_avg.get(d['state'], overall_avg)
            # Cap at 50% of state average from top100 (those are the biggest)
            d['enrollment'] = min(avg // 3, DEFAULT_ENROLLMENT)
            if d['enrollment'] < 5000:
                d['enrollment'] = 5000  # Floor

    return other_districts


# ── Generate Daily Flags ───────────────────────────────────────────────

def generate_daily_flags(district):
    """
    Generate (date, in_session, reason) tuples for one district.
    Returns list of (date, bool, str) for each day in the range.
    """
    first_day = district['first_day']
    last_day = district['last_day']
    spring_start = district['spring_break_start']
    spring_end = district['spring_break_end']
    winter_start = district['winter_break_start']
    winter_end = district['winter_break_end']

    results = []

    for d in daterange(START_DATE, END_DATE):
        in_session = True
        reason = ""

        # 1. Weekend check
        if d.weekday() >= 5:  # Saturday=5, Sunday=6
            in_session = False
            reason = "weekend"

        # 2. Summer break (before school starts or after school ends)
        # Before first day of school (fall)
        elif first_day and d < first_day:
            in_session = False
            reason = "summer_break"
        # After last day of school (spring/summer)
        elif last_day and d > last_day:
            in_session = False
            reason = "summer_break"

        # 3. Winter break
        elif winter_start and winter_end and winter_start <= d <= winter_end:
            in_session = False
            reason = "winter_break"

        # 4. Spring break
        elif spring_start and spring_end and spring_start <= d <= spring_end:
            in_session = False
            reason = "spring_break"

        # 5. Federal holidays / Thanksgiving (only on weekdays not already covered)
        elif d in FEDERAL_HOLIDAYS:
            in_session = False
            reason = FEDERAL_HOLIDAYS[d]

        results.append((d, in_session, reason))

    return results


# ── Main ───────────────────────────────────────────────────────────────

def main():
    print("Loading districts...")
    top100 = load_top100()
    print(f"  Top 100: {len(top100)} districts, {sum(d['enrollment'] for d in top100):,} students")

    all_districts = load_all_districts()
    print(f"  All districts: {len(all_districts)} districts")

    # Deduplicate
    other_districts = deduplicate_districts(top100, all_districts)
    print(f"  After dedup: {len(other_districts)} additional districts")

    # Estimate enrollment for others
    other_districts = estimate_enrollment(top100, other_districts)
    total_other_enrollment = sum(d['enrollment'] for d in other_districts)
    print(f"  Estimated enrollment for others: {total_other_enrollment:,}")

    # Combine
    all_combined = top100 + other_districts
    total_enrollment = sum(d['enrollment'] for d in all_combined)
    print(f"\nTotal: {len(all_combined)} districts, {total_enrollment:,} estimated students")

    # Count days
    num_days = (END_DATE - START_DATE).days + 1
    total_rows = len(all_combined) * num_days
    print(f"Generating {total_rows:,} rows ({len(all_combined)} districts × {num_days} days)...")

    # Build daily aggregate accumulators
    agg = defaultdict(lambda: {
        'total_students': 0,
        'students_in_session': 0,
        'students_on_break': 0,
        'reasons': defaultdict(int)  # reason -> enrollment
    })

    # Write daily calendar (gzipped) and accumulate aggregates
    rows_written = 0
    with gzip.open(CALENDAR_FILE, 'wt', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['district_name', 'state', 'enrollment', 'date', 'in_session', 'reason'])

        for i, district in enumerate(all_combined):
            flags = generate_daily_flags(district)
            enrollment = district['enrollment']

            for d, in_session, reason in flags:
                writer.writerow([
                    district['district_name'],
                    district['state'],
                    enrollment,
                    d.isoformat(),
                    in_session,
                    reason
                ])
                rows_written += 1

                # Accumulate aggregate
                day_agg = agg[d]
                day_agg['total_students'] += enrollment
                if in_session:
                    day_agg['students_in_session'] += enrollment
                else:
                    day_agg['students_on_break'] += enrollment
                    if reason:
                        day_agg['reasons'][reason] += enrollment

            if (i + 1) % 100 == 0:
                print(f"  Processed {i + 1}/{len(all_combined)} districts...")

    print(f"Wrote {rows_written:,} rows to {CALENDAR_FILE}")

    # Write aggregate
    with open(AGGREGATE_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'date', 'total_students', 'students_in_session', 'students_on_break',
            'pct_on_break', 'pct_in_session', 'primary_reason'
        ])

        for d in daterange(START_DATE, END_DATE):
            day = agg[d]
            total = day['total_students']
            if total == 0:
                continue
            pct_break = round(100.0 * day['students_on_break'] / total, 2)
            pct_session = round(100.0 * day['students_in_session'] / total, 2)

            # Primary reason = reason with most students
            primary = ""
            if day['reasons']:
                primary = max(day['reasons'].items(), key=lambda x: x[1])[0]

            writer.writerow([
                d.isoformat(),
                total,
                day['students_in_session'],
                day['students_on_break'],
                pct_break,
                pct_session,
                primary
            ])

    print(f"Wrote {num_days} rows to {AGGREGATE_FILE}")

    # Print some interesting facts
    print("\n── Sample Insights ──")

    # Find peak summer break
    summer_peak = max(
        ((d, agg[d]) for d in daterange(date(2025, 7, 1), date(2025, 8, 31))),
        key=lambda x: x[1]['students_on_break']
    )
    sp_d, sp_agg = summer_peak
    print(f"Peak summer break: {sp_d} — {sp_agg['students_on_break'] / sp_agg['total_students'] * 100:.1f}% on break")

    # Spring break spread
    print("\nSpring break spread (top weeks by % on break, excluding weekends):")
    spring_days = []
    for d in daterange(date(2026, 3, 1), date(2026, 4, 30)):
        if d.weekday() < 5:  # Weekdays only
            day = agg[d]
            if day['total_students'] > 0:
                pct = day['students_on_break'] / day['total_students'] * 100
                spring_days.append((d, pct, day['reasons'].get('spring_break', 0) / day['total_students'] * 100))

    spring_days.sort(key=lambda x: -x[2])
    for d, pct_total, pct_spring in spring_days[:10]:
        print(f"  {d} ({d.strftime('%A')[:3]}): {pct_spring:.1f}% spring break, {pct_total:.1f}% total on break")

    # Answer THE question
    target = date(2026, 3, 17)
    t_agg = agg[target]
    if t_agg['total_students'] > 0:
        print(f"\n🎯 March 17, 2026: {t_agg['students_on_break'] / t_agg['total_students'] * 100:.1f}% on break")
        for reason, enrollment in sorted(t_agg['reasons'].items(), key=lambda x: -x[1]):
            print(f"   {reason}: {enrollment / t_agg['total_students'] * 100:.1f}%")

    print("\nDone!")


if __name__ == '__main__':
    main()
