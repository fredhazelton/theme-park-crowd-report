#!/usr/bin/env python3
"""
generate_pipeline_status_json.py — Auto-generate Mission Control content JSON.

Reads live system data (pipeline logs, accuracy, services, disk, tasks)
and writes docs/mission-control-content.json for the GitHub Pages dashboard.

Run: .venv/bin/python3 scripts/generate_pipeline_status_json.py
"""

import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_JSON = PROJECT_ROOT / "docs" / "mission-control-content.json"

PIPELINE_LOG_DIR = Path("/mnt/data/pipeline/logs")
ACCURACY_SUMMARY = Path("/mnt/data/pipeline/accuracy/accuracy_summary.json")
TASKS_JSON = Path.home() / "clawd-anthropic" / "dino" / "tasks.json"
ASK_USAGE_JSON = PROJECT_ROOT / "tpcr-discord-bot" / "ask_usage.json"
DUCKDB_PATH = Path("/mnt/data/pipeline/tpcr_live.duckdb")

# Pipeline steps we track and the log text that marks them done
# Maps step_key → (label, log_done_text)
PIPELINE_STEPS = {
    "etl":          ("S3 ETL",       "Done: ETL (incremental)"),
    "forecasts":    ("Forecasts",    "Done: Synthetic actuals generation"),
    "wti":          ("WTI",          "WTI Summary:"),
    "live_waits":   ("Live Waits",   None),  # checked via process, not log
    "discord_bot":  ("Discord Bot",  None),  # checked via systemctl
    "daily_report": ("Daily Report", "Done: Wait time DB report"),
}


def now_eastern() -> datetime:
    """Get current time (server is in America/Toronto = Eastern)."""
    return datetime.now()


def run_cmd(cmd: str, timeout: int = 5) -> str:
    """Run a shell command and return stdout (empty string on failure)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except Exception:
        return ""


# ── Pipeline Status ───────────────────────────────────────────────────

def get_pipeline_status() -> dict:
    """Parse today's pipeline log to determine step statuses."""
    today = now_eastern().strftime("%Y-%m-%d")
    log_file = PIPELINE_LOG_DIR / f"daily_pipeline_{today}.log"

    if not log_file.exists():
        # No log yet today — everything pending
        return {
            key: {"status": "pending", "label": label, "detail": "Awaiting 6 AM run"}
            for key, (label, _) in PIPELINE_STEPS.items()
        }

    log_text = log_file.read_text(errors="replace")

    result = {}
    for key, (label, done_pattern) in PIPELINE_STEPS.items():
        if done_pattern is None:
            # These are checked via services, not log
            result[key] = {"status": "done", "label": label, "detail": ""}
            continue

        # Check for failure first
        # Patterns: "ERROR: Failed: <step>" or "FAIL" near the step name
        step_name_short = done_pattern.replace("Done: ", "")
        fail_pattern = re.compile(
            rf"(ERROR|FAIL).*{re.escape(step_name_short)}", re.IGNORECASE
        )
        done_re = re.compile(re.escape(done_pattern), re.IGNORECASE)

        if fail_pattern.search(log_text):
            result[key] = {"status": "error", "label": label, "detail": "Failed today"}
        elif done_re.search(log_text):
            result[key] = {"status": "done", "label": label, "detail": "Completed today"}
        elif f"=== {step_name_short}" in log_text:
            # Step started but not done yet
            result[key] = {"status": "running", "label": label, "detail": "In progress"}
        else:
            result[key] = {"status": "pending", "label": label, "detail": "Not started yet"}

    # Enrich with row counts from parquet file stats (fast, no DuckDB lock)
    _enrich_pipeline_details(result)

    return result


def _enrich_pipeline_details(status: dict):
    """Add detail strings with data counts from file stats."""
    output_base = Path("/mnt/data/pipeline")

    # Entity count from dimentity
    dimentity = output_base / "dimension_tables" / "dimentity.csv"
    if dimentity.exists():
        try:
            # Fast line count
            count = sum(1 for _ in open(dimentity)) - 1  # minus header
            if count > 0:
                status.get("etl", {})["detail"] = f"{count:,} entities tracked"
        except Exception:
            pass

    # Forecast count from all_forecasts.parquet
    all_forecasts = output_base / "curves" / "forecast_parquet" / "all_forecasts.parquet"
    if all_forecasts.exists():
        try:
            import pyarrow.parquet as pq
            meta = pq.read_metadata(str(all_forecasts))
            n_rows = meta.num_rows
            size_mb = all_forecasts.stat().st_size / (1024 * 1024)
            if status.get("forecasts", {}).get("status") == "done":
                status["forecasts"]["detail"] = f"{n_rows:,.0f} rows, {size_mb:.0f} MB"
            elif status.get("forecasts", {}).get("status") != "error":
                status["forecasts"]["detail"] = f"{n_rows:,.0f} rows"
        except Exception:
            pass

    # WTI count from wti.parquet
    wti_file = output_base / "wti" / "wti.parquet"
    if wti_file.exists():
        try:
            import pyarrow.parquet as pq
            meta = pq.read_metadata(str(wti_file))
            n_rows = meta.num_rows
            if status.get("wti", {}).get("status") == "done":
                status["wti"]["detail"] = f"{n_rows:,.0f} park-dates"
            elif status.get("wti", {}).get("status") != "error":
                status["wti"]["detail"] = f"{n_rows:,.0f} park-dates"
        except Exception:
            pass


# ── Accuracy ──────────────────────────────────────────────────────────

def get_accuracy() -> dict:
    """Read accuracy summary JSON."""
    defaults = {
        "entity_mae": "N/A",
        "entity_bias": "N/A",
        "wti_mae": "N/A",
        "wti_bias": "N/A",
        "days_evaluated": 0,
    }
    if not ACCURACY_SUMMARY.exists():
        return defaults

    try:
        with open(ACCURACY_SUMMARY) as f:
            data = json.load(f)
        return {
            "entity_mae": f"{data.get('overall_mae', 0):.1f} min",
            "entity_bias": f"+{data['overall_bias']:.1f} min" if data.get('overall_bias', 0) >= 0 else f"{data['overall_bias']:.1f} min",
            "overall_rmse": f"{data.get('overall_rmse', 0):.1f}",
            "wti_mae": str(round(data.get("wti_mae", 0), 1)),
            "wti_bias": str(round(data.get("wti_bias", 0), 1)),
            "days_evaluated": data.get("dates_evaluated", 0),
        }
    except Exception:
        return defaults


# ── Infrastructure ────────────────────────────────────────────────────

def get_infrastructure() -> dict:
    """Get live service status, disk usage, and DB stats."""
    services = []

    # systemctl services
    for svc_name, detail_default in [
        ("tpcr-discord-bot", "Discord bot"),
        ("chat-server", "Stream overlay"),
        ("twitch-chat", "Stream overlay"),
    ]:
        status_text = run_cmd(f"systemctl --user is-active {svc_name}")
        services.append({
            "name": svc_name,
            "status": status_text if status_text in ("active", "inactive", "failed") else "unknown",
            "detail": detail_default,
        })

    # queue-times fetcher (process check)
    qt_output = run_cmd("pgrep -f 'queue.times' > /dev/null 2>&1 && echo active || echo inactive")
    services.append({
        "name": "queue-times-fetcher",
        "status": qt_output if qt_output else "unknown",
        "detail": "Live wait times",
    })

    # Disk usage
    disk_main_pct = _parse_disk_pct("/home/wilma")
    disk_data_pct = _parse_disk_pct("/mnt/data")

    # DB stats from file sizes (avoid locking DuckDB)
    db_stats = _get_db_stats_from_files()

    return {
        "services": services,
        "disk_main_pct": disk_main_pct,
        "disk_data_pct": disk_data_pct,
        **db_stats,
    }


def _parse_disk_pct(mount: str) -> int:
    """Parse disk usage percentage from df output."""
    output = run_cmd(f"df -h {mount} | tail -1")
    if not output:
        return 0
    # Find percentage like "90%"
    match = re.search(r"(\d+)%", output)
    return int(match.group(1)) if match else 0


def _get_db_stats_from_files() -> dict:
    """Get DB row counts from parquet metadata without opening DuckDB."""
    output_base = Path("/mnt/data/pipeline")
    stats = {
        "db_entities": 0,
        "db_forecasts": 0,
        "db_live_waits": 0,
        "db_wti": 0,
    }

    try:
        import pyarrow.parquet as pq
        HAS_PYARROW = True
    except ImportError:
        HAS_PYARROW = False

    # Entity count from dimentity.csv
    dimentity = output_base / "dimension_tables" / "dimentity.csv"
    if dimentity.exists():
        try:
            stats["db_entities"] = sum(1 for _ in open(dimentity)) - 1
        except Exception:
            pass

    if HAS_PYARROW:
        # Forecast rows from parquet metadata (fast — reads footer only)
        forecast_pq = output_base / "curves" / "forecast_parquet" / "all_forecasts.parquet"
        if forecast_pq.exists():
            try:
                stats["db_forecasts"] = pq.read_metadata(str(forecast_pq)).num_rows
            except Exception:
                pass

        # Fact table rows (live waits / observations)
        fact_parquet_dir = output_base / "fact_tables" / "parquet"
        if fact_parquet_dir.exists():
            try:
                total = 0
                for f in fact_parquet_dir.iterdir():
                    if f.suffix == ".parquet":
                        total += pq.read_metadata(str(f)).num_rows
                stats["db_live_waits"] = total
            except Exception:
                pass

        # WTI rows from parquet
        wti_pq = output_base / "wti" / "wti.parquet"
        if wti_pq.exists():
            try:
                stats["db_wti"] = pq.read_metadata(str(wti_pq)).num_rows
            except Exception:
                pass

    return stats


# ── Today's Focus (Tasks) ────────────────────────────────────────────

def get_todays_focus() -> list:
    """Read top 5 active tasks from dino tasks.json."""
    if not TASKS_JSON.exists():
        return [{"status_class": "medium", "status_text": "📝 No tasks", "task": "No tasks file found"}]

    try:
        with open(TASKS_JSON) as f:
            data = json.load(f)
    except Exception:
        return [{"status_class": "medium", "status_text": "⚠️ Error", "task": "Could not read tasks.json"}]

    tasks = data.get("tasks", [])
    # Exclude done tasks
    active = [t for t in tasks if t.get("status") != "done"]

    # Sort by priority: high > medium > low
    priority_order = {"high": 0, "medium": 1, "low": 2}
    active.sort(key=lambda t: priority_order.get(t.get("priority", "low"), 3))

    # Map status to display
    status_map = {
        "in_progress": ("active", "🔄 Active"),
        "todo": ("medium", "📝 Todo"),
        "blocked": ("high", "🚫 Blocked"),
    }

    result = []
    for t in active[:5]:
        status = t.get("status", "todo")
        cls, text = status_map.get(status, ("medium", "📝 Todo"))
        result.append({
            "status_class": cls,
            "status_text": text,
            "task": t.get("title", "Untitled"),
        })

    return result if result else [{"status_class": "done", "status_text": "✅ Clear", "task": "No active tasks"}]


# ── Key Dates ─────────────────────────────────────────────────────────

def get_key_dates() -> list:
    """Generate key dates including next pipeline run and retrain day."""
    today = now_eastern().date()
    dates = []

    # Pipeline running daily
    dates.append({
        "emoji": "📊",
        "event": "Pipeline running daily",
        "date": "6 AM EST",
        "days_out": 0,
        "urgency": "",
    })

    # Next Monday (conversion model retrain)
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7  # next Monday, not today
        # Unless it IS Monday and we haven't run yet
        if today.weekday() == 0:
            days_until_monday = 0

    next_monday = today + timedelta(days=days_until_monday)
    if days_until_monday == 0:
        urgency = "today"
        label = "Today"
    elif days_until_monday == 1:
        urgency = "tomorrow"
        label = "Tomorrow"
    else:
        urgency = ""
        label = next_monday.strftime("%b %-d")

    dates.append({
        "emoji": "🔄",
        "event": "Conversion model retrain",
        "date": label,
        "days_out": days_until_monday,
        "urgency": urgency,
    })

    return dates


# ── Ask Analytics ─────────────────────────────────────────────────────

def get_ask_analytics() -> dict:
    """Read /ask usage stats from ask_usage.json."""
    defaults = {
        "total_questions": 0,
        "unique_users": 0,
        "thumbs_up": 0,
        "thumbs_down": 0,
        "avg_response_ms": 0,
        "model": "Claude Sonnet 4",
    }

    if not ASK_USAGE_JSON.exists():
        return defaults

    try:
        with open(ASK_USAGE_JSON) as f:
            data = json.load(f)

        # Data is {month_key: {user_id: count}}
        total_questions = 0
        unique_users = set()
        for month_key, users in data.items():
            if isinstance(users, dict):
                for user_id, count in users.items():
                    total_questions += count
                    unique_users.add(user_id)

        # Read feedback from ask_feedback.jsonl
        thumbs_up = 0
        thumbs_down = 0
        feedback_file = ASK_USAGE_JSON.parent / "ask_feedback.jsonl"
        if feedback_file.exists():
            try:
                with open(feedback_file) as ff:
                    for line in ff:
                        line = line.strip()
                        if not line:
                            continue
                        entry = json.loads(line)
                        rating = entry.get("rating", "")
                        if rating == "up":
                            thumbs_up += 1
                        elif rating == "down":
                            thumbs_down += 1
            except Exception:
                pass

        return {
            "total_questions": total_questions,
            "unique_users": len(unique_users),
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "avg_response_ms": 0,
            "model": "Claude Sonnet 4",
        }
    except Exception:
        return defaults


# ── Main ──────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Mission Control — Pipeline Status JSON Generator")
    print("=" * 60)

    print("\nGathering data...")

    # 1. Pipeline status
    print("  • Pipeline status (parsing today's log)...")
    pipeline_status = get_pipeline_status()
    for key, info in pipeline_status.items():
        print(f"    {info['label']}: {info['status']}")

    # 2. Accuracy
    print("  • Accuracy metrics...")
    accuracy = get_accuracy()
    print(f"    Entity MAE: {accuracy['entity_mae']}, Days: {accuracy['days_evaluated']}")

    # 3. Infrastructure
    print("  • Infrastructure (services, disk)...")
    infrastructure = get_infrastructure()
    active_count = sum(1 for s in infrastructure["services"] if s["status"] == "active")
    print(f"    Services: {active_count}/{len(infrastructure['services'])} active")
    print(f"    Disk: main={infrastructure['disk_main_pct']}%, data={infrastructure['disk_data_pct']}%")

    # 4. Today's focus
    print("  • Today's focus (tasks)...")
    todays_focus = get_todays_focus()
    print(f"    {len(todays_focus)} active tasks")

    # 5. Key dates
    print("  • Key dates...")
    key_dates = get_key_dates()

    # 6. Ask analytics
    print("  • Ask analytics...")
    ask_analytics = get_ask_analytics()
    print(f"    Total questions: {ask_analytics['total_questions']}")

    # 7. Timestamp
    last_updated = now_eastern().isoformat()

    # Assemble
    content = {
        "todays_focus": todays_focus,
        "key_dates": key_dates,
        "pipeline_status": pipeline_status,
        "accuracy": accuracy,
        "ask_analytics": ask_analytics,
        "infrastructure": infrastructure,
        "last_updated": last_updated,
    }

    # Write
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w") as f:
        json.dump(content, f, indent=4)

    size = OUTPUT_JSON.stat().st_size
    print(f"\n✅ Written: {OUTPUT_JSON.relative_to(PROJECT_ROOT)} ({size:,} bytes)")
    print(f"   Last updated: {last_updated}")


if __name__ == "__main__":
    main()
