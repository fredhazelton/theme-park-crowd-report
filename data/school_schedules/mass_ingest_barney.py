#!/usr/bin/env python3
"""Mass ingest Barney's 57 district extractions from GitHub issues."""

import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Setup paths
V3_DIR = Path(__file__).parent / "v3"
DB_PATH = V3_DIR / "school_schedules.db"
sys.path.insert(0, str(V3_DIR))

from generate_days import generate_days


def get_open_issues():
    """Get list of open SSD-collect issues."""
    cmd = ["gh", "issue", "list", "--label", "SSD-collect", "--state", "open", 
           "--limit", "100", "--json", "number,title"]
    result = subprocess.run(cmd, cwd=Path.cwd().parent.parent, 
                          capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error getting issues: {result.stderr}")
        return []
    return json.loads(result.stdout)


def get_issue_comments(issue_num):
    """Get issue body and comments."""
    cmd = ["gh", "issue", "view", str(issue_num), "--comments", "--json", "body,comments"]
    result = subprocess.run(cmd, cwd=Path.cwd().parent.parent,
                          capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error getting issue {issue_num}: {result.stderr}")
        return None
    return json.loads(result.stdout)


def extract_json_from_text(text):
    """Extract all JSON blocks from text between ```json and ```."""
    if not text:
        return []
    
    # Find all ```json ... ``` blocks
    pattern = r'```json\s*\n(.*?)\n```'
    matches = re.findall(pattern, text, re.DOTALL)
    
    jsons = []
    for match in matches:
        try:
            parsed = json.loads(match.strip())
            jsons.append(parsed)
        except json.JSONDecodeError as e:
            print(f"  JSON parse error: {e}")
            continue
    
    return jsons


def validate_extraction(data, issue_title):
    """Validate extraction matches issue title and has required fields."""
    required_fields = ["nces_id", "district_name", "state", "school_year", 
                      "first_day", "last_day"]
    
    # Check required fields
    for field in required_fields:
        if field not in data:
            return False, f"Missing required field: {field}"
    
    # Check district name match with issue title
    extracted_name = data["district_name"].lower()
    title_lower = issue_title.lower()
    
    # Clean up names for comparison
    def clean_name(name):
        # Remove common punctuation and normalize
        import re
        name = re.sub(r'[^\w\s]', ' ', name)  # Remove punctuation
        name = re.sub(r'\s+', ' ', name)      # Normalize spaces
        return name.strip().lower()
    
    clean_extracted = clean_name(extracted_name)
    clean_title = clean_name(title_lower)
    
    # Extract key parts from both
    extracted_parts = set(clean_extracted.split())
    title_parts = set(clean_title.split())
    
    # Remove common stop words
    stop_words = {'ssd', 'collect', 'school', 'district', 'isd', 'public', 'schools', 'county', 'sd', 'students', 'k'}
    extracted_key = extracted_parts - stop_words
    title_key = title_parts - stop_words
    
    # Check if significant overlap exists
    overlap = extracted_key & title_key
    if len(overlap) >= 2 or (len(extracted_key) <= 2 and len(overlap) >= 1):
        return True, "OK"
    
    # Special cases for known patterns
    if "nyc" in clean_extracted or "new york city" in clean_extracted:
        if "new york city" in clean_title or "nyc" in clean_title:
            return True, "OK"
    
    return False, f"District name mismatch: '{extracted_name}' vs '{issue_title}'"


def ingest_extraction(data):
    """Ingest single extraction into v3 database."""
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    
    try:
        nces_id = data["nces_id"]
        district_name = data["district_name"]
        state = data["state"]
        enrollment = data.get("enrollment", 0)
        school_year = data["school_year"]
        
        print(f"    Processing: {district_name} ({state}) — {enrollment:,} students")
        
        # Format district_id as STATE_NCES_ID
        district_id = f"{state}_{nces_id}"
        
        # Check if district exists
        existing = db.execute(
            "SELECT district_id FROM dim_district WHERE nces_id=?", (nces_id,)
        ).fetchone()
        
        if existing:
            print(f"      Found existing dim_district")
            # Update enrollment if new value is better (non-zero)
            if enrollment > 0:
                db.execute(
                    "UPDATE dim_district SET enrollment=?, updated_at=? WHERE nces_id=?",
                    (enrollment, datetime.now().isoformat(), nces_id)
                )
        else:
            # Insert new district
            contact_name = data.get("contact", {}).get("name", "")
            district_email = data.get("contact", {}).get("email", "")
            phone = data.get("contact", {}).get("phone", "")
            
            db.execute(
                """INSERT INTO dim_district 
                   (nces_id, district_name, state, enrollment, contact_name, 
                    district_email, phone, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (nces_id, district_name, state, enrollment, contact_name, 
                 district_email, phone, datetime.now().isoformat(), 
                 datetime.now().isoformat())
            )
            print(f"      Inserted new dim_district")
        
        # Insert calendar source
        try:
            cursor = db.execute(
                """INSERT INTO dim_calendar_source
                   (district_id, school_year, calendar_url, scrape_method, scrape_date,
                    raw_key_dates, quality_confidence, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (nces_id, school_year, data.get("source_url", ""),
                 "barney_manual_v3", datetime.now().strftime("%Y-%m-%d"),
                 json.dumps(data), "high",
                 data.get("notes", "Manual extraction by Barney"))
            )
            source_id = cursor.lastrowid
            print(f"      Inserted calendar source (id={source_id})")
        except sqlite3.IntegrityError:
            # Already exists, update it
            db.execute(
                """UPDATE dim_calendar_source SET
                   calendar_url=?, scrape_date=?, raw_key_dates=?, notes=?
                   WHERE district_id=? AND school_year=?""",
                (data.get("source_url", ""), datetime.now().strftime("%Y-%m-%d"),
                 json.dumps(data), data.get("notes", "Manual extraction by Barney"),
                 nces_id, school_year)
            )
            source_id = db.execute(
                "SELECT source_id FROM dim_calendar_source WHERE district_id=? AND school_year=?",
                (nces_id, school_year)
            ).fetchone()[0]
            print(f"      Updated existing calendar source (id={source_id})")
        
        # Build key_dates dict for generate_days
        key_dates = {
            "first_day": data.get("first_day"),
            "last_day": data.get("last_day"),
            "spring_break_start": data.get("spring_break_start"),
            "spring_break_end": data.get("spring_break_end"),
            "winter_break_start": data.get("winter_break_start"),
            "winter_break_end": data.get("winter_break_end"),
            "fall_break_start": data.get("fall_break_start"),
            "fall_break_end": data.get("fall_break_end"),
            "thanksgiving_break_start": data.get("thanksgiving_break_start") or data.get("thanksgiving_start"),
            "thanksgiving_break_end": data.get("thanksgiving_break_end") or data.get("thanksgiving_end"),
        }
        
        # Add non_school_days
        non_school_days = data.get("non_school_days", [])
        if non_school_days:
            key_dates["non_school_days"] = non_school_days
        
        # Add saturday_sessions and other_breaks if present
        if "saturday_sessions" in data:
            key_dates["saturday_sessions"] = data["saturday_sessions"]
        if "other_breaks" in data:
            key_dates["other_breaks"] = data["other_breaks"]
        
        # Delete existing day rows for this district/year combo
        db.execute(
            "DELETE FROM fact_school_day WHERE district_id=? AND school_year=?",
            (nces_id, school_year)
        )
        
        # Generate day-level rows
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
            print(f"      ✅ Generated {len(rows)} day rows ({school_days} school days)")
        else:
            print(f"      ❌ No rows generated!")
            
        db.commit()
        return True, enrollment
        
    except Exception as e:
        db.rollback()
        print(f"      ❌ Error: {e}")
        return False, 0
    finally:
        db.close()


def close_issue(issue_num):
    """Close issue and update labels."""
    try:
        # Remove SSD-collect, add SSD-complete
        subprocess.run([
            "gh", "issue", "edit", str(issue_num),
            "--remove-label", "SSD-collect",
            "--add-label", "SSD-complete"
        ], cwd=Path.cwd().parent.parent, check=True)
        
        # Close with comment
        subprocess.run([
            "gh", "issue", "close", str(issue_num),
            "--comment", "✅ Ingested into v3 DB."
        ], cwd=Path.cwd().parent.parent, check=True)
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"    ❌ Error closing issue {issue_num}: {e}")
        return False


def main():
    """Main ingestion process."""
    print("🚀 Starting mass ingestion of Barney's 57 extractions...")
    
    # Get open issues
    issues = get_open_issues()
    print(f"Found {len(issues)} open SSD-collect issues")
    
    # Track stats
    ingested_districts = 0
    total_enrollment = 0
    errors = []
    mismatches = []
    closed_issues = []
    
    for issue in issues:
        issue_num = issue["number"]
        title = issue["title"]
        print(f"\n📋 Processing Issue #{issue_num}: {title}")
        
        # Get comments
        issue_data = get_issue_comments(issue_num)
        if not issue_data:
            continue
        
        # Extract JSON from body and comments
        all_text = issue_data["body"] or ""
        for comment in issue_data.get("comments", []):
            all_text += "\n" + (comment.get("body") or "")
        
        json_blocks = extract_json_from_text(all_text)
        
        if not json_blocks:
            print(f"  ❌ No JSON extractions found")
            continue
        
        print(f"  Found {len(json_blocks)} JSON extraction(s)")
        
        issue_success = True
        for i, data in enumerate(json_blocks):
            print(f"  Processing extraction {i+1}/{len(json_blocks)}:")
            
            # Validate
            valid, msg = validate_extraction(data, title)
            if not valid:
                print(f"    ❌ Validation failed: {msg}")
                mismatches.append(f"Issue #{issue_num}: {msg}")
                issue_success = False
                continue
            
            # Ingest
            success, enrollment = ingest_extraction(data)
            if success:
                ingested_districts += 1
                total_enrollment += enrollment
            else:
                errors.append(f"Issue #{issue_num}: Ingestion failed")
                issue_success = False
        
        # Close issue if all extractions succeeded
        if issue_success and json_blocks:
            if close_issue(issue_num):
                closed_issues.append(issue_num)
                print(f"  ✅ Closed issue #{issue_num}")
    
    # Get final DB stats
    db = sqlite3.connect(str(DB_PATH))
    total_districts = db.execute("SELECT COUNT(*) FROM dim_district").fetchone()[0]
    total_db_enrollment = db.execute("SELECT COALESCE(SUM(enrollment),0) FROM dim_district").fetchone()[0]
    total_day_rows = db.execute("SELECT COUNT(*) FROM fact_school_day").fetchone()[0]
    db.close()
    
    # Print summary
    print(f"\n{'='*80}")
    print(f"🎉 MASS INGESTION COMPLETE")
    print(f"{'='*80}")
    print(f"Districts ingested: {ingested_districts}")
    print(f"Enrollment added: {total_enrollment:,}")
    print(f"Issues closed: {len(closed_issues)}")
    print(f"Errors: {len(errors)}")
    print(f"Mismatches: {len(mismatches)}")
    print(f"")
    print(f"Updated DB totals:")
    print(f"  Total districts: {total_districts:,}")
    print(f"  Total enrollment: {total_db_enrollment:,}")  
    print(f"  Total day rows: {total_day_rows:,}")
    
    if errors:
        print(f"\nErrors:")
        for error in errors:
            print(f"  - {error}")
    
    if mismatches:
        print(f"\nMismatches (skipped):")
        for mismatch in mismatches:
            print(f"  - {mismatch}")
    
    # Return summary for Discord posting
    return {
        "districts_ingested": ingested_districts,
        "enrollment_added": total_enrollment,
        "issues_closed": len(closed_issues),
        "errors": len(errors),
        "mismatches": len(mismatches),
        "total_districts": total_districts,
        "total_enrollment": total_db_enrollment,
        "total_day_rows": total_day_rows,
        "error_details": errors,
        "mismatch_details": mismatches
    }


if __name__ == "__main__":
    summary = main()
    
    # Save summary for potential Discord posting
    with open("mass_ingest_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"\nSummary saved to mass_ingest_summary.json")