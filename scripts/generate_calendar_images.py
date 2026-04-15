#!/usr/bin/env python3
"""
Pre-generate calendar heatmap images for all parks.
Run daily after WTI calculation in the pipeline.

Generates 90-day and 365-day calendar images for each park,
saving them to /mnt/data/pipeline/calendar_images/.

The Discord bot serves these pre-generated images instead of
rendering them live (which causes DuckDB lock contention and
blocks the Discord heartbeat).
"""

import os
import sys
import duckdb
import pandas as pd
from datetime import date, timedelta

# Add the bot directory to path for calendar_image module
BOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tpcr-discord-bot')
sys.path.insert(0, BOT_DIR)

from calendar_image import generate_calendar_image

DUCKDB_PATH = "/mnt/data/pipeline/tpcr_live.duckdb"
OUTPUT_DIR = "/mnt/data/pipeline/calendar_images"

# Park code → display name
PARKS = {
    "MK": "Magic Kingdom",
    "EP": "EPCOT",
    "HS": "Hollywood Studios",
    "AK": "Animal Kingdom",
    "DL": "Disneyland",
    "CA": "California Adventure",
    "UF": "Universal Studios Florida",
    "IA": "Islands of Adventure",
    "EU": "Epic Universe",
    "UH": "Universal Studios Hollywood",
    "TDL": "Tokyo Disneyland",
    "TDS": "Tokyo DisneySea",
}

# Entity prefix mapping (same as bot.py)
ENTITY_PREFIXES = {
    "UH": ["UH", "USH"],
}

TIMEFRAMES = [90, 380]  # #469: extended from 365


def _entity_filter_sql(park_code: str) -> str:
    prefixes = ENTITY_PREFIXES.get(park_code, [park_code])
    if len(prefixes) == 1:
        return f"entity_code LIKE '{prefixes[0]}%'"
    conditions = " OR ".join(f"entity_code LIKE '{p}%'" for p in prefixes)
    return f"({conditions})"


def generate_for_park(con, park_code: str, park_name: str, timeframe: int) -> bool:
    """Generate a calendar image for one park/timeframe. Returns True on success."""
    today = date.today()
    start = today + timedelta(days=1)
    end = today + timedelta(days=timeframe)
    
    entity_filter = _entity_filter_sql(park_code)
    
    try:
        # Batch query: per-date slot stats
        slot_stats = con.execute(f"""
            WITH slot_avgs AS (
                SELECT park_date, 
                       CAST(time_slot AS VARCHAR) as ts,
                       AVG(predicted_actual) as slot_avg
                FROM forecasts
                WHERE {entity_filter}
                  AND park_date BETWEEN ? AND ?
                  AND CAST(time_slot AS VARCHAR) BETWEEN '08:00' AND '22:00'
                GROUP BY park_date, time_slot
            )
            SELECT park_date, 
                   MIN(slot_avg) as raw_low,
                   AVG(slot_avg) as raw_avg, 
                   MAX(slot_avg) as raw_high
            FROM slot_avgs
            GROUP BY park_date
            ORDER BY park_date
        """, [start, end]).fetchdf()
        
        # WTI mapped values
        wti_vals = con.execute("""
            SELECT park_date, wti FROM wti
            WHERE park_code = ? AND park_date BETWEEN ? AND ?
        """, [park_code, start, end]).fetchdf()
        
        if len(slot_stats) == 0 or len(wti_vals) == 0:
            print(f"  ⚠️  No data for {park_code} ({timeframe}d)")
            return False
        
        # Build WTI lookup
        wti_map = {}
        for _, wrow in wti_vals.iterrows():
            wd = wrow['park_date']
            if isinstance(wd, pd.Timestamp):
                wd = wd.date()
            wti_map[wd] = float(wrow['wti'])
        
        # Build days_data
        days_data = []
        for _, srow in slot_stats.iterrows():
            d = srow['park_date']
            if isinstance(d, pd.Timestamp):
                d = d.date()
            raw_low = float(srow['raw_low'])
            raw_avg = float(srow['raw_avg'])
            raw_high = float(srow['raw_high'])
            
            if d in wti_map and raw_avg > 0:
                mapped_avg = wti_map[d]
                scale = mapped_avg / raw_avg
                days_data.append({
                    "date": d,
                    "wti_low": round(raw_low * scale, 1),
                    "wti_avg": round(mapped_avg, 1),
                    "wti_high": round(raw_high * scale, 1),
                })
            elif raw_avg > 0:
                days_data.append({
                    "date": d,
                    "wti_low": raw_low,
                    "wti_avg": raw_avg,
                    "wti_high": raw_high,
                })
        
        if not days_data:
            print(f"  ⚠️  No valid days_data for {park_code} ({timeframe}d)")
            return False
        
        # Generate image
        buf = generate_calendar_image(park_name, days_data)
        
        # Save
        filename = f"{park_code}_{timeframe}.png"
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(buf.read())
        
        size_kb = os.path.getsize(filepath) / 1024
        print(f"  ✅ {park_code}_{timeframe}.png — {len(days_data)} days, {size_kb:.0f}KB")
        return True
        
    except Exception as e:
        print(f"  ❌ {park_code} ({timeframe}d): {e}")
        return False


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print(f"📅 Generating calendar images...")
    print(f"   Output: {OUTPUT_DIR}")
    print(f"   Parks: {len(PARKS)}")
    print(f"   Timeframes: {TIMEFRAMES}")
    print()
    
    con = duckdb.connect(DUCKDB_PATH, read_only=True)
    
    success = 0
    failed = 0
    
    for park_code, park_name in PARKS.items():
        print(f"🏰 {park_name} ({park_code})")
        for tf in TIMEFRAMES:
            if generate_for_park(con, park_code, park_name, tf):
                success += 1
            else:
                failed += 1
    
    con.close()
    
    print(f"\n{'='*40}")
    print(f"✅ Generated: {success}")
    if failed:
        print(f"❌ Failed: {failed}")
    print(f"📁 Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
