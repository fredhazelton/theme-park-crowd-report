#!/usr/bin/env python3
"""
Pipeline Health Check & Alert Generator

Reads the daily pipeline log and state files to detect failures,
staleness, and missing outputs. Returns structured JSON for alerting.

Usage:
    python pipeline_alert_check.py [--date YYYY-MM-DD] [--json] [--quiet]

Exit codes:
    0 = ok
    1 = warning
    2 = critical
    3 = script error
"""

import argparse
import json
import os
import sys
import re
import glob
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────
PIPELINE_BASE = Path("/mnt/data/pipeline")
LOG_DIR = PIPELINE_BASE / "logs"
STATE_DIR = PIPELINE_BASE / "state"
WTI_DIR = PIPELINE_BASE / "wti"
FORECAST_PARQUET_DIR = PIPELINE_BASE / "curves" / "forecast_parquet"
FORECAST_CSV_DIR = PIPELINE_BASE / "curves" / "forecast"

STALENESS_THRESHOLD_HOURS = 26  # forecasts/WTI older than this = stale

# Patterns that indicate failures in pipeline logs
ERROR_PATTERNS = [
    (r"Killed\s", "OOM_KILL", "Process was killed (likely OOM)"),
    (r"\bERROR\b.*[Ff]ailed", "STEP_FAILED", "Pipeline step failed"),
    (r"exit code [1-9]", "NONZERO_EXIT", "Non-zero exit code"),
    (r"MemoryError", "MEMORY_ERROR", "Python MemoryError"),
    (r"OutOfMemoryError", "OOM_ERROR", "Out of memory error"),
    (r"ENOMEM", "ENOMEM", "System out of memory"),
    (r"Cannot allocate memory", "ALLOC_FAIL", "Memory allocation failed"),
    (r"Segmentation fault", "SEGFAULT", "Segmentation fault"),
    (r"core dumped", "CORE_DUMP", "Process core dumped"),
]

# Broader error patterns (checked after the specific ones above)
GENERAL_ERROR_PATTERNS = [
    (r"\] ERROR:", "LOGGED_ERROR", "Error logged during pipeline run"),
]

# Patterns that are warnings but not critical
WARNING_PATTERNS = [
    (r"Validation: FAIL", "VALIDATION_FAIL", "Pipeline validation failed"),
    (r"\[WARNING\].*failed", "WARNING_FAIL", "Warning with failure"),
]


def get_log_path(date_str: str) -> Path:
    """Get the daily pipeline log path for a given date."""
    return LOG_DIR / f"daily_pipeline_{date_str}.log"


def check_log_for_issues(log_path: Path) -> dict:
    """Parse a pipeline log for errors, kills, and failures."""
    issues = []
    
    if not log_path.exists():
        # Pipeline runs at 6 AM ET — don't alert before the scheduled run time
        from zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/Toronto"))
        pipeline_hour = 7  # suppress until 7 AM ET (run is at 6, give it time to finish)
        if now_et.strftime("%Y-%m-%d") == log_path.stem.replace("daily_pipeline_", "") and now_et.hour < pipeline_hour:
            return {
                "log_exists": False,
                "issues": [{
                    "type": "NO_LOG_PRE_SCHEDULE",
                    "severity": "info",
                    "message": "No pipeline log yet — scheduled run is at 6:00 AM ET",
                    "detail": f"Current time: {now_et.strftime('%I:%M %p ET')}. Pipeline has not run yet today.",
                    "suggestion": "No action needed. Check again after 7 AM ET."
                }]
            }
        return {
            "log_exists": False,
            "issues": [{
                "type": "NO_LOG",
                "severity": "critical",
                "message": f"No pipeline log found: {log_path.name}",
                "detail": "Pipeline may not have run at all today",
                "suggestion": "Check if the daily cron/systemd timer is running: systemctl --user status daily-pipeline-wilma.timer"
            }]
        }
    
    log_text = log_path.read_text(errors="replace")
    log_lines = log_text.splitlines()
    seen_codes = set()
    
    # Check for critical error patterns
    for pattern, code, description in ERROR_PATTERNS:
        matches = [line.strip() for line in log_lines if re.search(pattern, line)]
        if matches and code not in seen_codes:
            seen_codes.add(code)
            # Grab context: the match and a few lines before/after
            sample = matches[0][:200]
            issues.append({
                "type": code,
                "severity": "critical",
                "message": description,
                "detail": sample,
                "count": len(matches),
                "suggestion": _suggest_fix(code),
            })
    
    # Check for general error patterns (broader catch — only if no specific errors found)
    if not any(i["severity"] == "critical" for i in issues):
        for pattern, code, description in GENERAL_ERROR_PATTERNS:
            matches = [line.strip() for line in log_lines if re.search(pattern, line)]
            if matches and code not in seen_codes:
                seen_codes.add(code)
                sample = matches[0][:200]
                issues.append({
                    "type": code,
                    "severity": "critical",
                    "message": description,
                    "detail": sample,
                    "count": len(matches),
                    "suggestion": _suggest_fix(code),
                })
    
    # Check for warning patterns
    for pattern, code, description in WARNING_PATTERNS:
        matches = [line.strip() for line in log_lines if re.search(pattern, line)]
        if matches and code not in seen_codes:
            seen_codes.add(code)
            issues.append({
                "type": code,
                "severity": "warning",
                "message": description,
                "detail": matches[0][:200],
                "count": len(matches),
                "suggestion": _suggest_fix(code),
            })
    
    # Check if log ends with a success indicator
    last_lines = "\n".join(log_lines[-20:]) if log_lines else ""
    has_completion = bool(re.search(r"Pipeline complete|All steps completed|SUCCESS", last_lines, re.IGNORECASE))
    
    return {
        "log_exists": True,
        "log_size_kb": round(log_path.stat().st_size / 1024, 1),
        "line_count": len(log_lines),
        "has_completion_marker": has_completion,
        "issues": issues,
    }


def check_pipeline_state() -> dict:
    """Check pipeline_status.json for step-level failures."""
    issues = []
    status_file = STATE_DIR / "pipeline_status.json"
    state_file = STATE_DIR / "pipeline_state.json"
    
    state_info = {}
    
    # Check pipeline_status.json (real-time step tracker)
    if status_file.exists():
        try:
            status = json.loads(status_file.read_text())
            pipeline = status.get("pipeline", {})
            steps = pipeline.get("steps", {})
            current_step = pipeline.get("current_step", "unknown")
            started_at = pipeline.get("started_at", "")
            
            state_info["current_step"] = current_step
            state_info["started_at"] = started_at
            
            failed_steps = []
            pending_steps = []
            done_steps = []
            
            for step_name, step_data in steps.items():
                step_status = step_data.get("status", "unknown")
                if step_status == "failed":
                    failed_steps.append(step_name)
                    failed_at = step_data.get("failed_at", "unknown")
                    issues.append({
                        "type": "STEP_FAILED",
                        "severity": "critical",
                        "message": f"Step '{step_name}' failed",
                        "detail": f"Failed at {failed_at}",
                        "suggestion": _suggest_fix_for_step(step_name),
                    })
                elif step_status == "pending":
                    pending_steps.append(step_name)
                elif step_status == "done":
                    done_steps.append(step_name)
            
            state_info["failed_steps"] = failed_steps
            state_info["pending_steps"] = pending_steps
            state_info["done_steps"] = done_steps
            
            # If there are pending steps after a failure, that's expected but worth noting
            if failed_steps and pending_steps:
                issues.append({
                    "type": "DOWNSTREAM_SKIPPED",
                    "severity": "warning",
                    "message": f"Steps skipped due to upstream failure: {', '.join(pending_steps)}",
                    "detail": f"Upstream failure in: {', '.join(failed_steps)}",
                    "suggestion": "Fix the upstream failure first, then re-run the pipeline",
                })
                
        except (json.JSONDecodeError, KeyError) as e:
            issues.append({
                "type": "STATE_CORRUPT",
                "severity": "warning",
                "message": f"Could not parse pipeline_status.json: {e}",
                "detail": str(e),
                "suggestion": "Check file integrity, may need manual inspection",
            })
    
    # Check pipeline_state.json (persistent state with timestamps)
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            state_info["last_training"] = state.get("training_completed")
            state_info["last_forecast"] = state.get("forecast_completed")
            state_info["last_wti"] = state.get("wti_completed")
        except (json.JSONDecodeError, KeyError):
            pass
    
    return {"state_info": state_info, "issues": issues}


def check_output_staleness() -> dict:
    """Check if forecast and WTI outputs are stale."""
    issues = []
    now = datetime.now(timezone.utc)
    staleness_info = {}
    
    # Check WTI parquet (the main WTI output)
    wti_parquet = WTI_DIR / "wti.parquet"
    if wti_parquet.exists():
        mtime = datetime.fromtimestamp(wti_parquet.stat().st_mtime, tz=timezone.utc)
        age_hours = (now - mtime).total_seconds() / 3600
        staleness_info["wti_parquet_age_hours"] = round(age_hours, 1)
        staleness_info["wti_parquet_mtime"] = mtime.isoformat()
        if age_hours > STALENESS_THRESHOLD_HOURS:
            issues.append({
                "type": "WTI_STALE",
                "severity": "critical",
                "message": f"WTI output is {age_hours:.0f}h old (threshold: {STALENESS_THRESHOLD_HOURS}h)",
                "detail": f"Last updated: {mtime.strftime('%Y-%m-%d %H:%M UTC')}",
                "suggestion": "WTI hasn't been regenerated. Check if training/forecast steps completed.",
            })
    else:
        issues.append({
            "type": "WTI_MISSING",
            "severity": "critical",
            "message": "WTI parquet file missing entirely",
            "detail": f"Expected at: {wti_parquet}",
            "suggestion": "Run WTI calculation manually or trigger full pipeline",
        })
    
    # Check forecast parquet (all_forecasts.parquet)
    forecast_parquet = FORECAST_PARQUET_DIR / "all_forecasts.parquet"
    if forecast_parquet.exists():
        mtime = datetime.fromtimestamp(forecast_parquet.stat().st_mtime, tz=timezone.utc)
        age_hours = (now - mtime).total_seconds() / 3600
        staleness_info["forecast_parquet_age_hours"] = round(age_hours, 1)
        staleness_info["forecast_parquet_mtime"] = mtime.isoformat()
        if age_hours > STALENESS_THRESHOLD_HOURS:
            issues.append({
                "type": "FORECAST_STALE",
                "severity": "warning",
                "message": f"Forecast output is {age_hours:.0f}h old (threshold: {STALENESS_THRESHOLD_HOURS}h)",
                "detail": f"Last updated: {mtime.strftime('%Y-%m-%d %H:%M UTC')}",
                "suggestion": "Forecasts haven't been regenerated. Check training step.",
            })
    else:
        staleness_info["forecast_parquet_exists"] = False
        issues.append({
            "type": "FORECAST_MISSING",
            "severity": "warning",
            "message": "all_forecasts.parquet not found",
            "detail": f"Expected at: {forecast_parquet}",
            "suggestion": "Run forecast step manually",
        })
    
    # Check pipeline_state.json timestamps
    state_file = STATE_DIR / "pipeline_state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            for key, label in [
                ("training_completed", "Training"),
                ("forecast_completed", "Forecast"),
                ("wti_completed", "WTI"),
            ]:
                ts_str = state.get(key)
                if ts_str:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    age_hours = (now - ts).total_seconds() / 3600
                    staleness_info[f"{key}_age_hours"] = round(age_hours, 1)
                    if age_hours > STALENESS_THRESHOLD_HOURS:
                        issues.append({
                            "type": f"{key.upper()}_STALE",
                            "severity": "warning" if "training" in key else "critical",
                            "message": f"{label} last completed {age_hours:.0f}h ago",
                            "detail": f"Timestamp: {ts_str}",
                            "suggestion": f"Pipeline hasn't successfully completed {label.lower()} in over a day.",
                        })
        except (json.JSONDecodeError, ValueError):
            pass
    
    return {"staleness_info": staleness_info, "issues": issues}


def check_consecutive_failures() -> dict:
    """Check for consecutive days of pipeline failure.
    
    A day counts as a failure ONLY if it had errors AND no successful recovery run.
    The robust re-run script logs to training_robust_*.log with a "recovery complete" marker.
    We also check for fresh forecast/WTI outputs as evidence of successful recovery.
    """
    issues = []
    today = datetime.now().date()
    consecutive_fail_days = 0
    log_dir = Path(LOG_DIR)
    output_base = Path("/home/wilma/hazeydata/pipeline")
    
    for days_ago in range(0, 30):
        check_date = today - timedelta(days=days_ago)
        date_str = check_date.isoformat()
        log_path = get_log_path(date_str)
        
        if not log_path.exists():
            break
        
        log_text = log_path.read_text(errors="replace")
        all_fail_patterns = ERROR_PATTERNS + GENERAL_ERROR_PATTERNS
        has_failure = any(
            re.search(pattern, log_text)
            for pattern, _, _ in all_fail_patterns
        )
        
        if has_failure:
            # Check if a successful recovery run happened the same day
            recovered = False
            
            # Check for robust re-run logs with "recovery complete" on this date
            date_compact = check_date.strftime("%Y%m%d")
            for robust_log in log_dir.glob(f"training_robust_{date_compact}*.log"):
                try:
                    robust_text = robust_log.read_text(errors="replace")
                    if "recovery complete" in robust_text.lower() or "pipeline recovery complete" in robust_text.lower():
                        recovered = True
                        break
                except Exception:
                    pass
            
            # Also check if forecast archive exists for this date (evidence of successful run)
            if not recovered:
                forecast_archive = output_base / "accuracy" / "archive" / f"forecast_{date_str}.parquet"
                wti_archive = output_base / "accuracy" / "archive" / f"wti_{date_str}.parquet"
                if forecast_archive.exists() and wti_archive.exists():
                    recovered = True
            
            if not recovered:
                consecutive_fail_days += 1
            else:
                break  # Recovered day breaks the streak
        else:
            break
    
    info = {"consecutive_failure_days": consecutive_fail_days}
    
    if consecutive_fail_days >= 7:
        issues.append({
            "type": "PROLONGED_FAILURE",
            "severity": "critical",
            "message": f"Pipeline has been failing for {consecutive_fail_days} consecutive days!",
            "detail": f"Failures detected from {(today - timedelta(days=consecutive_fail_days-1)).isoformat()} to {today.isoformat()}",
            "suggestion": "This needs immediate human attention. The pipeline is broken and forecasts are increasingly stale.",
        })
    elif consecutive_fail_days >= 3:
        issues.append({
            "type": "MULTI_DAY_FAILURE",
            "severity": "critical",
            "message": f"Pipeline has failed {consecutive_fail_days} days in a row",
            "detail": f"First failure: {(today - timedelta(days=consecutive_fail_days-1)).isoformat()}",
            "suggestion": "Multiple consecutive failures suggest a systemic issue, not a transient error.",
        })
    elif consecutive_fail_days >= 2:
        issues.append({
            "type": "REPEATED_FAILURE",
            "severity": "warning",
            "message": f"Pipeline has failed {consecutive_fail_days} days in a row",
            "detail": "Might be transient, but worth checking.",
            "suggestion": "Check logs for recurring patterns.",
        })
    
    return {"consecutive_info": info, "issues": issues}


def _suggest_fix(code: str) -> str:
    """Return a suggested fix for an error code."""
    suggestions = {
        "OOM_KILL": "Process killed by OOM killer. Options: (1) reduce batch size in training, (2) add swap, (3) train fewer entities at once.",
        "STEP_FAILED": "Check the log for details above the error line.",
        "NONZERO_EXIT": "A subprocess exited with an error. Check log context.",
        "MEMORY_ERROR": "Python ran out of memory. Reduce data size or batch processing.",
        "OOM_ERROR": "JVM/Julia out of memory. Increase heap size or reduce data.",
        "ENOMEM": "System-level memory exhaustion. Check `free -h` and running processes.",
        "ALLOC_FAIL": "Memory allocation failed. Check available RAM.",
        "SEGFAULT": "Segfault in native code. May be a corrupted dependency or data issue.",
        "CORE_DUMP": "Process crashed. Check core dump for details.",
        "LOGGED_ERROR": "An ERROR was logged. Check the full log for context.",
        "VALIDATION_FAIL": "Pipeline validation checks failed. Review validation_report.json.",
        "WARNING_FAIL": "Non-fatal failure during pipeline execution.",
    }
    return suggestions.get(code, "Check the pipeline log for details.")


def _suggest_fix_for_step(step_name: str) -> str:
    """Return a suggested fix for a failed pipeline step."""
    suggestions = {
        "training": "Training failed. Common causes: OOM during model training. Check `dmesg | grep -i kill` for OOM kills. Consider reducing batch size or adding --skip-synthetic.",
        "forecast": "Forecast generation failed. Check if models exist and are valid.",
        "wti": "WTI calculation failed. Check if forecast data is available.",
        "etl": "Data extraction/loading failed. Check source data availability.",
        "dimensions": "Dimension building failed. Check DuckDB integrity.",
        "aggregates": "Aggregate computation failed.",
        "report": "Report generation failed.",
    }
    return suggestions.get(step_name, f"Step '{step_name}' failed. Check logs for details.")


def run_health_check(date_str: str = None) -> dict:
    """Run all health checks and return a consolidated result."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    log_path = get_log_path(date_str)
    
    # Run all checks
    log_check = check_log_for_issues(log_path)
    state_check = check_pipeline_state()
    staleness_check = check_output_staleness()
    consecutive_check = check_consecutive_failures()
    
    # Collect all issues
    all_issues = (
        log_check["issues"]
        + state_check["issues"]
        + staleness_check["issues"]
        + consecutive_check["issues"]
    )
    
    # Deduplicate by type
    seen = set()
    unique_issues = []
    for issue in all_issues:
        key = issue["type"]
        if key not in seen:
            seen.add(key)
            unique_issues.append(issue)
    
    # If pipeline recovered today (consecutive failures = 0 despite errors in log),
    # downgrade OOM_KILL and STEP_FAILED from critical to warning (they happened but were resolved)
    consec_days = consecutive_check.get("consecutive_info", {}).get("consecutive_failure_days", 0)
    if consec_days == 0:
        recoverable_types = {"OOM_KILL", "STEP_FAILED"}
        for issue in unique_issues:
            if issue["type"] in recoverable_types and issue["severity"] == "critical":
                issue["severity"] = "warning"
                issue["message"] += " (recovered via re-run)"
    
    # Determine overall status
    severities = [i["severity"] for i in unique_issues]
    if "critical" in severities:
        status = "critical"
    elif "warning" in severities:
        status = "warning"
    else:
        status = "ok"
    
    return {
        "status": status,
        "check_time": datetime.now(timezone.utc).isoformat(),
        "date_checked": date_str,
        "log_file": str(log_path),
        "issue_count": len(unique_issues),
        "issues": unique_issues,
        "log_info": {k: v for k, v in log_check.items() if k != "issues"},
        "state_info": state_check.get("state_info", {}),
        "staleness_info": staleness_check.get("staleness_info", {}),
        "consecutive_info": consecutive_check.get("consecutive_info", {}),
    }


def format_discord_alert(result: dict) -> str:
    """Format the health check result as a Discord message."""
    status = result["status"]
    date = result["date_checked"]
    issues = result["issues"]
    
    if status == "ok":
        return f"✅ **Pipeline Health Check — {date}**\nAll systems nominal. No issues detected."
    
    emoji = "🚨" if status == "critical" else "⚠️"
    header = f"{emoji} **Pipeline Health Check — {date}** [{status.upper()}]"
    
    lines = [header, ""]
    
    # Group by severity
    critical = [i for i in issues if i["severity"] == "critical"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    
    if critical:
        lines.append("**Critical Issues:**")
        for issue in critical:
            lines.append(f"🔴 **{issue['message']}**")
            lines.append(f"   ↳ {issue['detail']}")
            lines.append(f"   💡 {issue['suggestion']}")
            lines.append("")
    
    if warnings:
        lines.append("**Warnings:**")
        for issue in warnings:
            lines.append(f"🟡 {issue['message']}")
            lines.append(f"   ↳ {issue['detail']}")
            lines.append("")
    
    # Add staleness summary
    staleness = result.get("staleness_info", {})
    consec = result.get("consecutive_info", {})
    
    if staleness or consec:
        lines.append("**Quick Stats:**")
        if consec.get("consecutive_failure_days", 0) > 0:
            lines.append(f"• Consecutive failures: **{consec['consecutive_failure_days']} days**")
        wti_age = staleness.get("wti_parquet_age_hours")
        if wti_age:
            lines.append(f"• WTI data age: **{wti_age:.0f}h**")
        forecast_age = staleness.get("forecast_parquet_age_hours")
        if forecast_age:
            lines.append(f"• Forecast data age: **{forecast_age:.0f}h**")
        training_age = staleness.get("training_completed_age_hours")
        if training_age:
            lines.append(f"• Last successful training: **{training_age:.0f}h ago**")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Pipeline health check")
    parser.add_argument("--date", help="Date to check (YYYY-MM-DD), default: today")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--discord", action="store_true", help="Output Discord-formatted message")
    parser.add_argument("--quiet", action="store_true", help="Only output if issues found")
    args = parser.parse_args()
    
    try:
        result = run_health_check(args.date)
    except Exception as e:
        error_result = {
            "status": "critical",
            "check_time": datetime.now(timezone.utc).isoformat(),
            "issues": [{
                "type": "CHECK_ERROR",
                "severity": "critical",
                "message": f"Health check itself failed: {e}",
                "detail": str(e),
                "suggestion": "Check the alert script for bugs",
            }]
        }
        if args.json:
            print(json.dumps(error_result, indent=2))
        else:
            print(f"🚨 Health check error: {e}")
        sys.exit(3)
    
    if args.quiet and result["status"] == "ok":
        sys.exit(0)
    
    if args.json:
        print(json.dumps(result, indent=2))
    elif args.discord:
        print(format_discord_alert(result))
    else:
        # Human-readable output
        status_emoji = {"ok": "✅", "warning": "⚠️", "critical": "🚨"}
        print(f"\n{status_emoji.get(result['status'], '?')} Pipeline Status: {result['status'].upper()}")
        print(f"   Date: {result['date_checked']}")
        print(f"   Issues: {result['issue_count']}")
        print()
        
        for issue in result["issues"]:
            sev_icon = "🔴" if issue["severity"] == "critical" else "🟡"
            print(f"  {sev_icon} [{issue['type']}] {issue['message']}")
            print(f"     {issue['detail']}")
            if issue.get("suggestion"):
                print(f"     💡 {issue['suggestion']}")
            print()
    
    # Exit code reflects status
    exit_codes = {"ok": 0, "warning": 1, "critical": 2}
    sys.exit(exit_codes.get(result["status"], 3))


if __name__ == "__main__":
    main()
