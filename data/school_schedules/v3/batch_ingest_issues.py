#!/usr/bin/env python3
"""
Batch ingest all wilma-ingest / SSD-extracted GitHub issues into v3 DB.

For each issue:
1. Read the NCES ID from the issue body (source of truth from our CSV)
2. Read the extraction JSON from the last comment
3. Override the JSON's nces_id with the issue body's NCES ID
4. Ingest into v3 database
5. Post confirmation comment, relabel SSD-complete, close issue
"""

import json
import re
import subprocess
import sys
from ingest_from_issue import ingest_one, DB_PATH
import sqlite3
from datetime import datetime


def gh(*args):
    """Run a gh CLI command and return stdout."""
    result = subprocess.run(
        ["gh"] + list(args),
        capture_output=True, text=True,
        cwd="/home/wilma/theme-park-crowd-report"
    )
    return result.stdout.strip()


def get_issues():
    """Get all open issues with wilma-ingest or SSD-extracted labels."""
    issues = set()
    for label in ["wilma-ingest", "SSD-extracted"]:
        raw = gh("issue", "list", "--label", label, "--state", "open",
                 "--json", "number", "--jq", ".[].number", "--limit", "100")
        for line in raw.strip().split("\n"):
            if line.strip().isdigit():
                issues.add(int(line.strip()))
    return sorted(issues)


def get_nces_from_body(issue_num):
    """Extract the correct NCES ID from the issue body."""
    body = gh("issue", "view", str(issue_num), "--json", "body", "--jq", ".body")
    match = re.search(r'\*?NCES ID:?\*?\*?\s*(\d{7})', body)
    return match.group(1) if match else None


def get_json_from_comments(issue_num):
    """Extract the JSON extraction from the last comment."""
    body = gh("issue", "view", str(issue_num), "--json", "comments",
              "--jq", ".comments[-1].body")
    
    # Find JSON block
    match = re.search(r'```json\s*\n(.*?)\n```', body, re.DOTALL)
    if not match:
        return None
    
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        print(f"  ❌ JSON parse error: {e}")
        return None


def main():
    issues = get_issues()
    if not issues:
        print("No issues ready for ingestion.")
        return

    print(f"Found {len(issues)} issues to process: {issues}\n")

    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")

    success = 0
    failed = 0
    results = []

    for issue_num in issues:
        print(f"\n{'='*60}")
        print(f"Processing issue #{issue_num}...")

        # Get correct NCES from issue body
        correct_nces = get_nces_from_body(issue_num)
        if not correct_nces:
            print(f"  ⚠️ Could not find NCES ID in issue body, skipping")
            failed += 1
            continue

        # Get extraction JSON
        extraction = get_json_from_comments(issue_num)
        if not extraction:
            print(f"  ⚠️ Could not extract JSON from comments, skipping")
            failed += 1
            continue

        # Override NCES ID with the correct one from the issue body
        barney_nces = extraction.get("nces_id")
        if str(barney_nces) != str(correct_nces):
            print(f"  🔧 Fixing NCES: Barney had {barney_nces}, using {correct_nces} from issue body")
            extraction["nces_id"] = correct_nces

        # Ingest
        try:
            result = ingest_one(db, extraction)
            results.append(result)
            school_days = result["school_days"]
            total_rows = result["total_rows"]
            
            # Commit after each successful ingest
            db.commit()
            
            # Post confirmation comment
            gh("issue", "comment", str(issue_num),
               "-b", f"✅ **Ingested into v3 database** by Wilma.\n\n"
                     f"- District ID: `{result['district_id']}`\n"
                     f"- NCES ID: `{correct_nces}`"
                     f"{' (corrected from ' + str(barney_nces) + ')' if str(barney_nces) != str(correct_nces) else ''}\n"
                     f"- {school_days} school days, {total_rows} total day rows\n"
                     f"- School year: {result['school_year']}")

            # Relabel and close
            gh("issue", "edit", str(issue_num),
               "--add-label", "SSD-complete",
               "--remove-label", "wilma-ingest",
               "--remove-label", "SSD-extracted",
               "--remove-label", "barney",
               "--remove-label", "wilma",
               "--remove-label", "SSD-collect")
            
            gh("issue", "close", str(issue_num))
            
            print(f"  ✅ #{issue_num} → SSD-complete, closed")
            success += 1

        except Exception as e:
            print(f"  ❌ Ingestion failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    # Final summary
    total_d = db.execute("SELECT COUNT(*) FROM dim_district").fetchone()[0]
    total_e = db.execute("SELECT COALESCE(SUM(enrollment),0) FROM dim_district").fetchone()[0]
    total_rows = db.execute("SELECT COUNT(*) FROM fact_school_day").fetchone()[0]
    
    print(f"\n{'='*60}")
    print(f"Batch complete: {success} ingested, {failed} failed/skipped")
    print(f"Database totals: {total_d:,} districts, {total_e:,} enrollment, {total_rows:,} day rows")

    db.close()

    # Print enrollment added
    if results:
        total_enrolled = sum(r["enrollment"] for r in results)
        print(f"Enrollment added this batch: {total_enrolled:,}")


if __name__ == "__main__":
    main()
