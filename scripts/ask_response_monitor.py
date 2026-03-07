#!/usr/bin/env python3
"""
Ask Response Quality Monitor

Scans ask_questions.jsonl for bad bot responses and diagnoses the root cause.
When a user gets a failure response, this script:
  1. Detects the failure pattern
  2. Investigates the likely cause (DB locks, missing data, stale data)
  3. Attempts to fix it
  4. Reports findings

Run: python scripts/ask_response_monitor.py [--json] [--fix] [--since-minutes N]
"""

import json
import sys
import os
import time
import argparse
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Paths
QUESTION_LOG = Path("/home/wilma/theme-park-crowd-report/tpcr-discord-bot/ask_questions.jsonl")
STATE_FILE = Path("/mnt/data/pipeline/state/ask_monitor_state.json")
DUCKDB_PATH = "/mnt/data/pipeline/tpcr_live.duckdb"
ALL_FORECASTS = "/mnt/data/pipeline/curves/forecast_parquet/all_forecasts.parquet"

# Failure patterns — if a response contains any of these, it's flagged
FAILURE_PATTERNS = [
    "data is updating right now",
    "try again in a minute",
    "database is temporarily busy",
    "i wasn't able to fully answer",
    "try rephrasing or asking something more specific",
    "query error:",
    "unable to access",
    "data isn't available",
    "don't have that data",
    "no data available",
    "couldn't find any",
    "no results found for",
]

# Short/empty response threshold
MIN_ANSWER_LENGTH = 40


def load_state():
    """Load last check state."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_checked_timestamp": None, "last_checked_line": 0}


def save_state(state):
    """Save check state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_recent_questions(since_minutes=30, since_timestamp=None):
    """Read recent questions from the log file."""
    if not QUESTION_LOG.exists():
        return []

    cutoff = None
    if since_timestamp:
        cutoff = datetime.fromisoformat(since_timestamp)
    elif since_minutes:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)

    questions = []
    with open(QUESTION_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if cutoff and ts < cutoff:
                    continue
                entry["_parsed_ts"] = ts
                questions.append(entry)
            except (json.JSONDecodeError, KeyError):
                continue
    return questions


def detect_failures(questions):
    """Identify questions that got bad responses."""
    failures = []
    for q in questions:
        answer = q.get("answer", "").lower()
        reason = None

        # Check failure patterns
        for pattern in FAILURE_PATTERNS:
            if pattern in answer:
                reason = f"failure_pattern: {pattern}"
                break

        # Check suspiciously short answers
        if not reason and len(q.get("answer", "")) < MIN_ANSWER_LENGTH:
            reason = f"short_answer: {len(q.get('answer', ''))} chars"

        # Check very long duration (hit 5-round tool limit)
        if not reason and q.get("duration_ms", 0) > 28000:
            # Also check if the answer looks like a fallback
            if "wasn't able" in answer or "try rephrasing" in answer:
                reason = f"timeout_fallback: {q.get('duration_ms')}ms"

        if reason:
            failures.append({**q, "_failure_reason": reason})

    return failures


def diagnose_failure(failure):
    """Investigate why a specific question failed."""
    diagnosis = {
        "question": failure.get("question"),
        "user": failure.get("username"),
        "timestamp": failure.get("timestamp"),
        "failure_reason": failure.get("_failure_reason"),
        "checks": [],
        "root_cause": None,
        "auto_fixable": False,
        "fix_applied": None,
    }

    # Check 1: Is DuckDB accessible?
    try:
        import duckdb
        con = duckdb.connect(DUCKDB_PATH, read_only=True)
        con.execute("SELECT 1").fetchone()
        diagnosis["checks"].append({"check": "duckdb_accessible", "ok": True})

        # Check 2: Data freshness
        freshness = con.execute(
            "SELECT source, last_updated FROM data_freshness"
        ).fetchall()
        now = datetime.now(timezone.utc)
        stale_sources = []
        for source, last_updated in freshness:
            if last_updated:
                import pandas as pd
                ts = pd.to_datetime(last_updated)
                if ts.tzinfo is None:
                    ts = ts.tz_localize("UTC")
                age_h = (now - ts).total_seconds() / 3600
                if age_h > 6:
                    stale_sources.append(f"{source}: {age_h:.1f}h old")
        
        diagnosis["checks"].append({
            "check": "data_freshness",
            "ok": len(stale_sources) == 0,
            "stale": stale_sources,
        })

        # Check 3: Does the forecasts table have the requested data?
        # Try to extract date and park from the question
        question_lower = failure.get("question", "").lower()
        forecast_count = con.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
        forecast_range = con.execute(
            "SELECT MIN(park_date), MAX(park_date) FROM forecasts"
        ).fetchone()
        
        diagnosis["checks"].append({
            "check": "forecasts_table",
            "ok": forecast_count > 1_000_000,
            "row_count": forecast_count,
            "date_range": [str(forecast_range[0]), str(forecast_range[1])] if forecast_range[0] else None,
        })

        # Check 4: WTI data availability
        wti_count = con.execute(
            "SELECT COUNT(*) FROM wti WHERE source='forecast'"
        ).fetchone()[0]
        diagnosis["checks"].append({
            "check": "wti_forecasts",
            "ok": wti_count > 3000,
            "row_count": wti_count,
        })

        con.close()

        # Determine root cause
        if stale_sources:
            diagnosis["root_cause"] = f"stale_data: {', '.join(stale_sources)}"
        elif forecast_count < 1_000_000:
            diagnosis["root_cause"] = "forecasts_table_incomplete"
            diagnosis["auto_fixable"] = True
        elif "data is updating" in failure.get("_failure_reason", ""):
            diagnosis["root_cause"] = "duckdb_lock_collision"
        elif "timeout_fallback" in failure.get("_failure_reason", ""):
            diagnosis["root_cause"] = "query_too_complex_or_data_missing"
        else:
            diagnosis["root_cause"] = "unknown"

    except Exception as e:
        diagnosis["checks"].append({"check": "duckdb_accessible", "ok": False, "error": str(e)})
        diagnosis["root_cause"] = f"duckdb_inaccessible: {str(e)}"
        diagnosis["auto_fixable"] = False

    return diagnosis


def attempt_fix(diagnosis):
    """Try to auto-fix the diagnosed issue."""
    fix_result = {"attempted": False, "success": False, "details": None}

    if diagnosis["root_cause"] == "forecasts_table_incomplete":
        # Reload forecasts from all_forecasts.parquet
        if os.path.exists(ALL_FORECASTS):
            try:
                import duckdb
                con = duckdb.connect(DUCKDB_PATH)
                before = con.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
                
                con.execute(f"""
                    INSERT OR IGNORE INTO forecasts 
                        (entity_code, park_date, time_slot, predicted_actual, prediction_method, updated_at)
                    SELECT 
                        entity_code,
                        park_date::DATE,
                        CAST(time_slot AS VARCHAR),
                        predicted_actual,
                        COALESCE(prediction_method, 'model'),
                        CURRENT_TIMESTAMP
                    FROM read_parquet('{ALL_FORECASTS}')
                """)
                
                after = con.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
                con.execute("""
                    INSERT OR REPLACE INTO data_freshness (source, last_updated, row_count, notes)
                    VALUES ('forecasts', CURRENT_TIMESTAMP, (SELECT COUNT(*) FROM forecasts), 'auto-fix-reload')
                """)
                con.close()
                
                fix_result = {
                    "attempted": True,
                    "success": True,
                    "details": f"Reloaded forecasts: {before:,} → {after:,} rows",
                }
            except Exception as e:
                fix_result = {
                    "attempted": True,
                    "success": False,
                    "details": f"Reload failed: {str(e)}",
                }

    elif diagnosis["root_cause"] == "duckdb_lock_collision":
        # Check if the lock is still held
        try:
            import duckdb
            con = duckdb.connect(DUCKDB_PATH, read_only=True)
            con.execute("SELECT 1").fetchone()
            con.close()
            fix_result = {
                "attempted": True,
                "success": True,
                "details": "Lock cleared — DB is accessible now (transient collision)",
            }
        except Exception as e:
            # Check for hanging processes
            result = subprocess.run(
                ["fuser", DUCKDB_PATH], capture_output=True, text=True
            )
            fix_result = {
                "attempted": True,
                "success": False,
                "details": f"DB still locked. Processes: {result.stdout.strip()}. Error: {str(e)}",
            }

    diagnosis["fix_applied"] = fix_result
    return diagnosis


def format_alert(failures, diagnoses):
    """Format an alert message for Discord."""
    if not failures:
        return None

    lines = [f"🔍 **Ask Response Monitor** — {len(failures)} failed response(s) detected\n"]
    
    for i, (failure, diag) in enumerate(zip(failures, diagnoses)):
        lines.append(f"**{i+1}. @{failure.get('username', '?')}** asked:")
        lines.append(f"> {failure.get('question', '?')[:200]}")
        lines.append(f"Got: _{failure.get('answer', '?')[:100]}_")
        lines.append(f"Root cause: `{diag.get('root_cause', 'unknown')}`")
        
        fix = diag.get("fix_applied", {})
        if fix and fix.get("attempted"):
            status = "✅ Fixed" if fix.get("success") else "❌ Fix failed"
            lines.append(f"{status}: {fix.get('details', '')}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Monitor /ask responses for failures")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--fix", action="store_true", default=True, help="Attempt auto-fixes (default: true)")
    parser.add_argument("--no-fix", action="store_true", help="Don't attempt auto-fixes")
    parser.add_argument("--since-minutes", type=int, default=None, help="Check last N minutes")
    parser.add_argument("--alert", action="store_true", help="Print alert text for Discord")
    args = parser.parse_args()

    if args.no_fix:
        args.fix = False

    # Load state
    state = load_state()
    since_ts = state.get("last_checked_timestamp")
    
    if args.since_minutes:
        since_ts = None  # Override with explicit minutes

    # Get recent questions
    questions = get_recent_questions(
        since_minutes=args.since_minutes or (30 if not since_ts else None),
        since_timestamp=since_ts,
    )

    # Detect failures
    failures = detect_failures(questions)

    # Diagnose each failure
    diagnoses = []
    for f in failures:
        diag = diagnose_failure(f)
        if args.fix and diag.get("auto_fixable"):
            diag = attempt_fix(diag)
        diagnoses.append(diag)

    # Update state
    if questions:
        latest_ts = max(q["_parsed_ts"] for q in questions)
        state["last_checked_timestamp"] = latest_ts.isoformat()
    state["last_check_time"] = datetime.now(timezone.utc).isoformat()
    state["failures_found"] = len(failures)
    save_state(state)

    # Output
    result = {
        "check_time": datetime.now(timezone.utc).isoformat(),
        "questions_scanned": len(questions),
        "failures_found": len(failures),
        "failures": [
            {
                "question": f.get("question"),
                "username": f.get("username"),
                "user_id": f.get("user_id"),
                "timestamp": f.get("timestamp"),
                "answer_preview": f.get("answer", "")[:150],
                "failure_reason": f.get("_failure_reason"),
                "diagnosis": d,
            }
            for f, d in zip(failures, diagnoses)
        ],
    }

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    elif args.alert:
        alert = format_alert(failures, diagnoses)
        if alert:
            print(alert)
        else:
            print("No failures detected.")
    else:
        print(f"Scanned {len(questions)} questions, found {len(failures)} failures")
        for f, d in zip(failures, diagnoses):
            print(f"\n  ❌ @{f.get('username')}: {f.get('question', '')[:80]}")
            print(f"     Reason: {f.get('_failure_reason')}")
            print(f"     Root cause: {d.get('root_cause')}")
            fix = d.get("fix_applied", {})
            if fix and fix.get("attempted"):
                status = "✅" if fix.get("success") else "❌"
                print(f"     Fix: {status} {fix.get('details', '')}")

    return 0 if len(failures) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
