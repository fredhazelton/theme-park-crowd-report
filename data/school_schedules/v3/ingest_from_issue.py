#!/usr/bin/env python3
"""
Ingest extraction JSON from a GitHub issue comment into the v3 database.

Usage:
    python3 ingest_from_issue.py '{"nces_id":"0608760", ...}'
    python3 ingest_from_issue.py --file extraction.json
    echo '<json>' | python3 ingest_from_issue.py --stdin

Uses the proper district_id slug (e.g. CA_0608760) as the FK,
looked up from dim_district via nces_id.
"""

import json
import sys
import sqlite3
from datetime import datetime
from pathlib import Path
from generate_days import generate_days

V3_DIR = Path(__file__).parent
DB_PATH = V3_DIR / "school_schedules.db"


def get_district_id(db, nces_id):
    """Look up the district_id slug from nces_id."""
    row = db.execute(
        "SELECT district_id FROM dim_district WHERE nces_id = ?", (nces_id,)
    ).fetchone()
    return row[0] if row else None


def ingest_one(db, d):
    """Ingest a single extraction dict into the v3 database."""
    nces_id = str(d["nces_id"]).strip()
    district_name = d["district_name"]
    state = d["state"]
    enrollment = d.get("enrollment") or 0
    school_year = d.get("school_year", "2025-2026")

    # Look up or create district
    district_id = get_district_id(db, nces_id)

    if district_id:
        print(f"  Found district: {district_id} ({district_name})")
        # Update enrollment if we have better data
        if enrollment:
            db.execute(
                "UPDATE dim_district SET enrollment=?, updated_at=? WHERE district_id=?",
                (enrollment, datetime.now().isoformat(), district_id)
            )
    else:
        # Build slug: STATE_NCESID
        district_id = f"{state}_{nces_id}"
        db.execute(
            """INSERT INTO dim_district
               (district_id, nces_id, district_name, state, enrollment, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (district_id, nces_id, district_name, state, enrollment,
             datetime.now().isoformat(), datetime.now().isoformat())
        )
        print(f"  Created new district: {district_id}")

    # Update contact info if provided
    contact = d.get("contact", {})
    if contact:
        updates = []
        params = []
        if contact.get("email"):
            updates.append("district_email = ?")
            params.append(contact["email"])
        if contact.get("name"):
            updates.append("contact_name = ?")
            params.append(contact["name"])
        if contact.get("phone"):
            updates.append("phone = ?")
            params.append(contact["phone"])
        if updates:
            params.append(datetime.now().isoformat())
            params.append(district_id)
            db.execute(
                f"UPDATE dim_district SET {', '.join(updates)}, updated_at=? WHERE district_id=?",
                params
            )

    # Remove existing calendar data for this district+year+method (upsert)
    existing_source = db.execute(
        "SELECT source_id FROM dim_calendar_source WHERE district_id=? AND school_year=? AND scrape_method=?",
        (district_id, school_year, "barney_manual_v3")
    ).fetchone()

    if existing_source:
        old_sid = existing_source[0]
        db.execute("DELETE FROM fact_school_day WHERE source_id=?", (old_sid,))
        db.execute("DELETE FROM dim_calendar_source WHERE source_id=?", (old_sid,))
        print(f"  Replaced existing barney extraction for {school_year}")

    # Insert calendar source
    db.execute(
        """INSERT INTO dim_calendar_source
           (district_id, school_year, calendar_url, scrape_method, scrape_date,
            raw_key_dates, quality_confidence, notes, is_primary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        (district_id, school_year, d.get("source_url", ""),
         "barney_manual_v3", d.get("extraction_date", datetime.now().strftime("%Y-%m-%d")),
         json.dumps(d), "high",
         d.get("notes", "Manual extraction by Barney"))
    )
    source_id = db.execute(
        "SELECT source_id FROM dim_calendar_source WHERE district_id=? AND school_year=? AND scrape_method=?",
        (district_id, school_year, "barney_manual_v3")
    ).fetchone()[0]
    print(f"  Calendar source inserted (source_id={source_id})")

    # Build key_dates for generate_days
    key_dates = {
        "first_day": d.get("first_day"),
        "last_day": d.get("last_day"),
        "spring_break_start": d.get("spring_break_start"),
        "spring_break_end": d.get("spring_break_end"),
        "winter_break_start": d.get("winter_break_start"),
        "winter_break_end": d.get("winter_break_end"),
        "thanksgiving_break_start": d.get("thanksgiving_break_start"),
        "thanksgiving_break_end": d.get("thanksgiving_break_end"),
        "non_school_days": d.get("non_school_days", []),
        "other_breaks": d.get("other_breaks", []),
        "saturday_sessions": d.get("saturday_sessions", []),
    }

    # Generate day-level rows
    rows = generate_days(district_id, school_year, key_dates, source_id)

    if rows:
        # Use district_id (slug) as the FK — matches fact_school_day PK
        db.executemany(
            """INSERT OR REPLACE INTO fact_school_day
               (district_id, source_id, date, day_of_week, day_name,
                is_in_session, day_type, break_name, notes, school_year)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows
        )
        school_days = sum(1 for r in rows if r[5] == 1)
        non_school = sum(1 for r in rows if r[5] == 0 and r[6] not in ('WEEKEND', 'SUMMER'))
        stated = d.get("total_instructional_days")
        check = ""
        if stated and abs(school_days - stated) > 3:
            check = f" ⚠️ MISMATCH: stated={stated}, got={school_days}"
        print(f"  ✅ {len(rows)} day rows ({school_days} school days, {non_school} non-school){check}")
    else:
        print(f"  ❌ No rows generated!")

    return {
        "district_id": district_id,
        "district_name": district_name,
        "state": state,
        "enrollment": enrollment,
        "school_year": school_year,
        "total_rows": len(rows) if rows else 0,
        "school_days": sum(1 for r in rows if r[5] == 1) if rows else 0,
    }


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--file":
        with open(sys.argv[2]) as f:
            raw = f.read()
    elif len(sys.argv) > 1 and sys.argv[1] == "--stdin":
        raw = sys.stdin.read()
    elif len(sys.argv) > 1 and sys.argv[1] != "--help":
        raw = sys.argv[1]
    else:
        print(__doc__)
        sys.exit(1)

    # Parse JSON — handle single object or array
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]

    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")

    results = []
    for d in data:
        print(f"\n{'='*60}")
        print(f"Ingesting: {d['district_name']} ({d['state']}) — NCES {d['nces_id']}")
        result = ingest_one(db, d)
        results.append(result)

    db.commit()

    # Summary
    total_d = db.execute("SELECT COUNT(*) FROM dim_district").fetchone()[0]
    total_e = db.execute("SELECT COALESCE(SUM(enrollment),0) FROM dim_district").fetchone()[0]
    total_rows = db.execute("SELECT COUNT(*) FROM fact_school_day").fetchone()[0]
    print(f"\n{'='*60}")
    print(f"Ingested {len(results)} district(s)")
    print(f"Database totals: {total_d:,} districts, {total_e:,} enrollment, {total_rows:,} day rows")
    db.close()

    return results


if __name__ == "__main__":
    main()
