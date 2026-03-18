#!/usr/bin/env python3
"""Ingest Barney's manual extractions into the v3 database."""

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from generate_days import generate_days, parse_date, school_year_date_range

V3_DIR = Path(__file__).parent
DB_PATH = V3_DIR / "school_schedules.db"
BARNEY_JSON = V3_DIR.parent / "barney_manual_extractions.json"


def ingest():
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    
    with open(BARNEY_JSON) as f:
        data = json.load(f)
    
    for d in data["districts"]:
        nces_id = d["nces_id"]
        district_name = d["district_name"]
        state = d["state"]
        enrollment = d.get("enrollment", 0)
        
        print(f"\nProcessing: {district_name} ({state}) — {enrollment:,} students")
        
        # Check if district exists in dim_district
        existing = db.execute(
            "SELECT district_id FROM dim_district WHERE nces_id=?", (nces_id,)
        ).fetchone()
        
        if existing:
            district_pk = existing[0]
            print(f"  Found existing dim_district (pk={district_pk})")
            # Update enrollment if we have better data
            db.execute(
                "UPDATE dim_district SET enrollment=?, updated_at=? WHERE nces_id=?",
                (enrollment, datetime.now().isoformat(), nces_id)
            )
        else:
            # Insert new district
            db.execute(
                """INSERT INTO dim_district 
                   (nces_id, district_name, state, enrollment, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (nces_id, district_name, state, enrollment,
                 datetime.now().isoformat(), datetime.now().isoformat())
            )
            district_pk = db.execute(
                "SELECT district_id FROM dim_district WHERE nces_id=?", (nces_id,)
            ).fetchone()[0]
            print(f"  Inserted new dim_district (pk={district_pk})")
        
        # Remove any existing calendar source + days for this district
        old_source = db.execute(
            "SELECT source_id FROM dim_calendar_source WHERE district_id=?", (nces_id,)
        ).fetchone()
        if old_source:
            db.execute("DELETE FROM fact_school_day WHERE district_id=?", (nces_id,))
            db.execute("DELETE FROM dim_calendar_source WHERE district_id=?", (nces_id,))
            print(f"  Replaced existing calendar data")
        
        # Insert calendar source
        db.execute(
            """INSERT INTO dim_calendar_source
               (district_id, school_year, calendar_url, scrape_method, scrape_date,
                raw_key_dates, quality_confidence, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (nces_id, d["school_year"], d["source_url"],
             "barney_manual_v3", datetime.now().strftime("%Y-%m-%d"),
             json.dumps(d["dates"]), "high",
             d.get("notes", "Manual extraction by Barney"))
        )
        source_id = db.execute(
            "SELECT source_id FROM dim_calendar_source WHERE district_id=?", (nces_id,)
        ).fetchone()[0]
        print(f"  Inserted calendar source (id={source_id})")
        
        # Build key_dates dict in the format generate_days expects
        dates = d["dates"]
        key_dates = {
            "first_day": dates.get("first_day"),
            "last_day": dates.get("last_day"),
            "spring_break_start": dates.get("spring_break_start"),
            "spring_break_end": dates.get("spring_break_end"),
            "winter_break_start": dates.get("winter_break_start"),
            "winter_break_end": dates.get("winter_break_end"),
            "fall_break_start": dates.get("fall_break_start"),
            "fall_break_end": dates.get("fall_break_end"),
            "thanksgiving_break_start": dates.get("thanksgiving_start"),
            "thanksgiving_break_end": dates.get("thanksgiving_end"),
        }
        
        # Add holidays as non_school_days
        non_school_days = []
        for h in d.get("holidays", []):
            non_school_days.append({
                "date": h["date"],
                "type": "HOLIDAY",
                "name": h["name"]
            })
        # Also include any non_school_days already in the source data
        for nsd in d.get("non_school_days", []):
            non_school_days.append(nsd)
        key_dates["non_school_days"] = non_school_days
        
        # Pass through saturday_sessions and other_breaks
        if "saturday_sessions" in d:
            key_dates["saturday_sessions"] = d["saturday_sessions"]
        if "other_breaks" in d:
            key_dates["other_breaks"] = d["other_breaks"]
        
        # Generate day-level rows
        school_year = d["school_year"]
        rows = generate_days(nces_id, school_year, key_dates, source_id)
        
        if rows:
            db.executemany(
                """INSERT OR REPLACE INTO fact_school_day
                   (district_id, source_id, date, day_of_week, day_name, 
                    is_in_session, day_type, break_name, notes, school_year)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows
            )
            school_days = sum(1 for r in rows if r[5] == 1)  # is_in_session
            non_school = sum(1 for r in rows if r[5] == 0 and r[6] not in ('WEEKEND', 'SUMMER'))
            print(f"  ✅ Generated {len(rows)} day-level rows ({school_days} school days, {non_school} non-school days)")
        else:
            print(f"  ❌ No rows generated!")
    
    db.commit()
    
    # Summary
    total_d = db.execute("SELECT COUNT(*) FROM dim_district").fetchone()[0]
    total_e = db.execute("SELECT COALESCE(SUM(enrollment),0) FROM dim_district").fetchone()[0]
    total_rows = db.execute("SELECT COUNT(*) FROM fact_school_day").fetchone()[0]
    print(f"\n{'='*60}")
    print(f"Database now: {total_d:,} districts, {total_e:,} enrollment, {total_rows:,} day rows")
    
    db.close()


if __name__ == "__main__":
    ingest()
