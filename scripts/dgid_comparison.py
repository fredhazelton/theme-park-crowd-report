#!/usr/bin/env python3
"""
Date Group ID Comparison Tool

Compares today's (or any date's) WTI against historical dates with the same
date_group_id value. When differences are found, drills into features that
might explain why.

Usage:
    python scripts/dgid_comparison.py                    # today
    python scripts/dgid_comparison.py --date 2026-02-22  # specific date
    python scripts/dgid_comparison.py --park MK           # specific park deep-dive
    python scripts/dgid_comparison.py --json              # machine-readable output
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb

OUTPUT_BASE = Path("/mnt/data/pipeline")
DGID_PATH = OUTPUT_BASE / "dimension_tables" / "dimdategroupid.csv"
WTI_PATH = OUTPUT_BASE / "wti" / "wti.parquet"
DIMENTITY_PATH = OUTPUT_BASE / "dimension_tables" / "dimentity.csv"
SYNTH_DIR = OUTPUT_BASE / "synthetic_actuals"
PARQUET_DIR = OUTPUT_BASE / "fact_tables" / "parquet"
OC_PATH = OUTPUT_BASE / "operating_calendar" / "operating_calendar.parquet"


def get_dgid_info(con, target_date):
    """Get date_group_id and metadata for target date."""
    df = con.execute(f"""
        SELECT park_date::DATE as park_date, date_group_id, 
               day_of_week_name, month_name, holidaycode, holidayname
        FROM read_csv_auto('{DGID_PATH}')
        WHERE park_date::DATE = '{target_date}'
    """).fetchdf()
    if df.empty:
        return None
    return df.iloc[0].to_dict()


def get_same_dgid_dates(con, dgid, before_date=None):
    """Get all dates with the same date_group_id."""
    where_clause = f"AND park_date::DATE < '{before_date}'" if before_date else ""
    df = con.execute(f"""
        SELECT park_date::DATE as park_date, day_of_week_name, 
               year, holidaycode, holidayname
        FROM read_csv_auto('{DGID_PATH}')
        WHERE date_group_id = '{dgid}' {where_clause}
        ORDER BY park_date
    """).fetchdf()
    return df


def wti_comparison(con, target_date, same_dates, parks=None):
    """Compare target date WTI vs historical same-dgid WTI."""
    dates_sql = ",".join([f"'{str(d)[:10]}'" for d in same_dates['park_date']])
    park_filter = f"AND park_code IN ({','.join([repr(p) for p in parks])})" if parks else ""
    
    df = con.execute(f"""
        WITH hist AS (
            SELECT park_code, 
                   round(avg(wti), 1) as avg_hist,
                   count(*) as n_dates,
                   round(min(wti), 1) as hist_min,
                   round(max(wti), 1) as hist_max,
                   round(percentile_cont(0.25) WITHIN GROUP (ORDER BY wti), 1) as hist_p25,
                   round(percentile_cont(0.75) WITHIN GROUP (ORDER BY wti), 1) as hist_p75,
                   round(stddev(wti), 1) as hist_std
            FROM read_parquet('{WTI_PATH}')
            WHERE source = 'historical' 
            AND CAST(park_date AS DATE) IN ({dates_sql})
            {park_filter}
            GROUP BY park_code
        ),
        today AS (
            SELECT park_code, wti as today_wti, source
            FROM read_parquet('{WTI_PATH}')
            WHERE CAST(park_date AS DATE) = '{target_date}'
            {park_filter}
        )
        SELECT h.park_code, h.n_dates,
               h.hist_min, h.hist_p25, h.avg_hist, h.hist_p75, h.hist_max, h.hist_std,
               t.today_wti, t.source as today_source,
               round(t.today_wti - h.avg_hist, 1) as diff,
               CASE 
                   WHEN h.hist_std > 0 THEN round((t.today_wti - h.avg_hist) / h.hist_std, 1)
                   ELSE 0 
               END as z_score
        FROM hist h
        JOIN today t ON h.park_code = t.park_code
        ORDER BY abs(t.today_wti - h.avg_hist) DESC
    """).fetchdf()
    return df


def entity_count_comparison(con, target_date, same_dates, park_code):
    """Compare how many entities contribute to WTI on target vs historical dates."""
    dates_sql = ",".join([f"'{str(d)[:10]}'" for d in same_dates['park_date']])
    
    # Count entities with data on target date
    today_count = con.execute(f"""
        SELECT COUNT(DISTINCT entity_code) as n
        FROM read_parquet('{SYNTH_DIR}/*.parquet')
        WHERE CAST(park_date AS DATE) = '{target_date}'
        AND entity_code LIKE '{park_code}%'
        AND synthetic_actual > 0
    """).fetchone()[0]
    
    # Average entity count on historical same-dgid dates
    hist_counts = con.execute(f"""
        SELECT CAST(park_date AS DATE) as pd, COUNT(DISTINCT entity_code) as n
        FROM read_parquet('{SYNTH_DIR}/*.parquet')
        WHERE CAST(park_date AS DATE) IN ({dates_sql})
        AND entity_code LIKE '{park_code}%'
        AND synthetic_actual > 0
        GROUP BY CAST(park_date AS DATE)
    """).fetchdf()
    
    return today_count, hist_counts


def top_entity_drivers(con, target_date, same_dates, park_code, n=10):
    """Find entities driving the biggest WTI difference vs historical."""
    dates_sql = ",".join([f"'{str(d)[:10]}'" for d in same_dates['park_date']])
    
    df = con.execute(f"""
        WITH hist_entity AS (
            SELECT entity_code,
                   round(avg(synthetic_actual), 1) as hist_avg,
                   count(DISTINCT CAST(park_date AS DATE)) as n_dates
            FROM read_parquet('{SYNTH_DIR}/*.parquet')
            WHERE CAST(park_date AS DATE) IN ({dates_sql})
            AND entity_code LIKE '{park_code}%'
            AND synthetic_actual > 0
            GROUP BY entity_code
        ),
        today_entity AS (
            SELECT entity_code,
                   round(avg(synthetic_actual), 1) as today_avg
            FROM read_parquet('{SYNTH_DIR}/*.parquet')
            WHERE CAST(park_date AS DATE) = '{target_date}'
            AND entity_code LIKE '{park_code}%'
            AND synthetic_actual > 0
            GROUP BY entity_code
        ),
        names AS (
            SELECT code, name, has_posted
            FROM read_csv_auto('{DIMENTITY_PATH}')
            WHERE code LIKE '{park_code}%'
        )
        SELECT COALESCE(h.entity_code, t.entity_code) as entity_code,
               n.name,
               n.has_posted,
               h.hist_avg,
               t.today_avg,
               round(COALESCE(t.today_avg, 0) - COALESCE(h.hist_avg, 0), 1) as diff,
               h.n_dates as hist_dates
        FROM hist_entity h
        FULL OUTER JOIN today_entity t ON h.entity_code = t.entity_code
        LEFT JOIN names n ON COALESCE(h.entity_code, t.entity_code) = n.code
        WHERE n.has_posted = TRUE
        ORDER BY abs(COALESCE(t.today_avg, 0) - COALESCE(h.hist_avg, 0)) DESC
        LIMIT {n}
    """).fetchdf()
    return df


def nearby_holidays(con, target_date, same_dates):
    """Check if holiday proximity differs across same-dgid dates."""
    dates_sql = ",".join([f"'{str(d)[:10]}'" for d in same_dates['park_date']])
    
    df = con.execute(f"""
        SELECT d.park_date::DATE as park_date, d.holidaycode, d.holidayname,
               -- Look at surrounding week for holidays
               (SELECT string_agg(DISTINCT h2.holidayname, ', ')
                FROM read_csv_auto('{DGID_PATH}') h2
                WHERE h2.park_date::DATE BETWEEN d.park_date::DATE - INTERVAL 7 DAY 
                      AND d.park_date::DATE + INTERVAL 7 DAY
                AND h2.holidaycode != 'NONE'
               ) as nearby_holidays
        FROM read_csv_auto('{DGID_PATH}') d
        WHERE d.park_date::DATE IN ({dates_sql}, '{target_date}')
        ORDER BY d.park_date
    """).fetchdf()
    return df


def main():
    parser = argparse.ArgumentParser(description="Date Group ID Comparison")
    parser.add_argument("--date", type=str, default=str(date.today()),
                        help="Target date (default: today)")
    parser.add_argument("--park", type=str, default=None,
                        help="Deep-dive into specific park (e.g., MK)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--top-entities", type=int, default=10,
                        help="Number of top entity drivers to show")
    args = parser.parse_args()
    
    con = duckdb.connect()
    target_date = args.date
    
    # 1. Get today's date_group_id
    info = get_dgid_info(con, target_date)
    if info is None:
        print(f"ERROR: No date_group_id found for {target_date}")
        return 1
    
    dgid = info['date_group_id']
    
    print("=" * 70)
    print(f"DATE GROUP ID COMPARISON")
    print(f"=" * 70)
    print(f"Target date:    {target_date} ({info['day_of_week_name']})")
    print(f"date_group_id:  {dgid}")
    print(f"Holiday:        {info['holidayname'] or 'None'}")
    print()
    
    # 2. Get historical same-dgid dates
    same_dates = get_same_dgid_dates(con, dgid, before_date=target_date)
    print(f"Historical comparable dates: {len(same_dates)} ({same_dates['park_date'].min()} to {same_dates['park_date'].max()})")
    print()
    
    if same_dates.empty:
        print("No historical comparison dates found.")
        return 0
    
    # 3. WTI comparison
    wti = wti_comparison(con, target_date, same_dates,
                         parks=[args.park] if args.park else None)
    
    print(f"{'Park':<6} {'Dates':>5} {'Hist Min':>8} {'Hist Avg':>8} {'Hist Max':>8} {'Today':>7} {'Diff':>6} {'Z':>5} {'Signal'}")
    print("-" * 75)
    for _, row in wti.iterrows():
        z = row['z_score']
        signal = ""
        if abs(z) >= 2.0:
            signal = "🔴 UNUSUAL" if z > 0 else "🔵 UNUSUAL"
        elif abs(z) >= 1.0:
            signal = "🟡 notable" if z > 0 else "🟢 notable"
        src = "📊" if row['today_source'] == 'historical' else "🔮"
        print(f"{row['park_code']:<6} {row['n_dates']:>5} {row['hist_min']:>8} {row['avg_hist']:>8} {row['hist_max']:>8} {row['today_wti']:>6}{src} {row['diff']:>+6.1f} {z:>+5.1f} {signal}")
    
    print()
    print("📊 = actual observed today  |  🔮 = forecast")
    
    # 4. Deep-dive for specific park or parks with big deviations
    dive_parks = [args.park] if args.park else [
        row['park_code'] for _, row in wti.iterrows() 
        if abs(row['z_score']) >= 1.0
    ]
    
    for park in dive_parks[:3]:  # Max 3 deep dives
        print()
        print(f"{'=' * 70}")
        print(f"DEEP DIVE: {park}")
        print(f"{'=' * 70}")
        
        # Entity drivers
        print(f"\nTop entity drivers (biggest WTI contributors):")
        entities = top_entity_drivers(con, target_date, same_dates, park, args.top_entities)
        if not entities.empty:
            print(f"{'Entity':<8} {'Name':<40} {'Hist Avg':>8} {'Today':>7} {'Diff':>7}")
            print("-" * 75)
            for _, e in entities.iterrows():
                hist = f"{e['hist_avg']:.1f}" if e['hist_avg'] is not None else "  N/A"
                today = f"{e['today_avg']:.1f}" if e['today_avg'] is not None else "  N/A"
                diff = f"{e['diff']:+.1f}" if e['diff'] is not None else "  N/A"
                print(f"{e['entity_code']:<8} {str(e['name'])[:40]:<40} {hist:>8} {today:>7} {diff:>7}")
    
    # 5. Holiday proximity check
    print()
    print(f"{'=' * 70}")
    print("HOLIDAY CONTEXT")
    print(f"{'=' * 70}")
    holidays = nearby_holidays(con, target_date, same_dates)
    for _, h in holidays.iterrows():
        nearby = h['nearby_holidays'] or "none"
        marker = " <<< TARGET" if str(h['park_date'])[:10] == target_date else ""
        print(f"  {str(h['park_date'])[:10]}  nearby: {nearby}{marker}")
    
    # JSON output
    if args.json:
        output = {
            "target_date": target_date,
            "date_group_id": dgid,
            "day_of_week": info['day_of_week_name'],
            "n_comparable_dates": len(same_dates),
            "parks": {}
        }
        for _, row in wti.iterrows():
            output["parks"][row['park_code']] = {
                "hist_avg": float(row['avg_hist']),
                "hist_min": float(row['hist_min']),
                "hist_max": float(row['hist_max']),
                "today_wti": float(row['today_wti']),
                "diff": float(row['diff']),
                "z_score": float(row['z_score']),
                "source": row['today_source'],
                "n_dates": int(row['n_dates'])
            }
        print("\n" + json.dumps(output, indent=2))
    
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
