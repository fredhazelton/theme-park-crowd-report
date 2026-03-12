#!/usr/bin/env python3
"""
Morning Briefing — Daily digest for #morning-briefing.

Posts a comprehensive morning summary to Discord including:
  1. Pipeline health status
  2. Today's WTI forecasts (top-level)
  3. Yesterday's accuracy (if available)
  4. Week-ahead highlights
  5. Open task count
  6. Key alerts / notes

Usage:
    python3 scripts/morning_briefing.py              # Print only (default)
    python3 scripts/morning_briefing.py --post       # Print + post to Discord
    python3 scripts/morning_briefing.py --dry-run    # Same as no flags

Designed to run at 7:30 AM ET via Clawdbot cron.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/Toronto")
NOW = datetime.now(ET)
TODAY = date.today()
TODAY_STR = TODAY.strftime("%Y-%m-%d")
DOW = NOW.strftime("%A")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WTI_PARQUET = Path("/mnt/data/pipeline/wti/wti.parquet")
DUCKDB_PATH = Path("/mnt/data/pipeline/tpcr_live.duckdb")
TASKS_JSON = Path.home() / "clawd-anthropic" / "dino" / "tasks.json"
PIPELINE_STATE = PROJECT_ROOT / "pipeline_state.json"

MORNING_BRIEFING_CHANNEL = "1479351589176082526"
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# Park display config
PARK_NAMES = {
    "MK": "Magic Kingdom", "EP": "EPCOT", "HS": "Hollywood Studios",
    "AK": "Animal Kingdom", "DL": "Disneyland", "CA": "California Adventure",
    "IA": "Islands of Adventure", "UF": "Universal Florida",
    "EU": "Epic Universe", "UH": "Universal Hollywood",
    "TDL": "Tokyo Disneyland", "TDS": "Tokyo DisneySea",
}

WDW_PARKS = ["MK", "EP", "HS", "AK"]
DLR_PARKS = ["DL", "CA"]
UNI_PARKS = ["UF", "IA", "EU", "UH"]

IGNORE_PARKS = {"BB"}


def wti_emoji(wti: float) -> str:
    if wti <= 10: return "❄️"
    elif wti <= 20: return "💎"
    elif wti <= 30: return "⚪"
    elif wti <= 40: return "🌸"
    elif wti <= 50: return "🔥"
    elif wti <= 60: return "🔴"
    else: return "💀"


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def get_pipeline_status() -> dict:
    """Check pipeline health via the health check script."""
    try:
        result = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), str(PROJECT_ROOT / "scripts/tpcr_bot_health_check.py"), "--json"],
            capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT)
        )
        return json.loads(result.stdout)
    except Exception as e:
        return {"status": "unknown", "error": str(e)}


def get_today_wti() -> list[dict]:
    """Get today's WTI forecasts for all parks."""
    if not WTI_PARQUET.exists():
        return []
    try:
        con = duckdb.connect(":memory:")
        rows = con.execute(f"""
            SELECT park_code, wti, park_date
            FROM read_parquet('{WTI_PARQUET}')
            WHERE CAST(park_date AS DATE) = '{TODAY_STR}'
              AND park_code NOT IN ('BB')
            ORDER BY wti DESC
        """).fetchall()
        con.close()
        return [{"park": r[0], "wti": round(r[1], 1), "date": str(r[2])} for r in rows]
    except Exception as e:
        return [{"error": str(e)}]


def get_week_outlook() -> list[dict]:
    """Get average WTI per day for the next 7 days."""
    if not WTI_PARQUET.exists():
        return []
    try:
        start = TODAY_STR
        end = (TODAY + timedelta(days=7)).strftime("%Y-%m-%d")
        con = duckdb.connect(":memory:")
        rows = con.execute(f"""
            SELECT CAST(park_date AS DATE) as pd, AVG(wti) as avg_wti, MIN(wti) as min_wti, MAX(wti) as max_wti
            FROM read_parquet('{WTI_PARQUET}')
            WHERE CAST(park_date AS DATE) BETWEEN '{start}' AND '{end}'
              AND park_code NOT IN ('BB')
            GROUP BY pd
            ORDER BY pd
        """).fetchall()
        con.close()
        return [{"date": str(r[0]), "avg": round(r[1], 1), "min": round(r[2], 1), "max": round(r[3], 1)} for r in rows]
    except Exception:
        return []


def get_yesterday_accuracy() -> dict | None:
    """Check if we have accuracy data for yesterday."""
    try:
        accuracy_dir = Path("/mnt/data/pipeline/accuracy")
        yesterday = (TODAY - timedelta(days=1)).strftime("%Y-%m-%d")
        accuracy_file = accuracy_dir / f"accuracy_{yesterday}.json"
        if accuracy_file.exists():
            with open(accuracy_file) as f:
                return json.load(f)

        # Try the overall accuracy eval
        result = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), str(PROJECT_ROOT / "scripts/pipeline_accuracy_drift.py"), "--json"],
            capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT)
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data
    except Exception:
        pass
    return None


def get_task_summary() -> dict:
    """Count tasks by status."""
    try:
        with open(TASKS_JSON) as f:
            data = json.load(f)
        tasks = data.get("tasks", [])
        counts = {}
        for t in tasks:
            s = t.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1
        return counts
    except Exception:
        return {}


def get_scraper_freshness() -> str:
    """Check when last scrape happened. Falls back to file mtime if DuckDB locked."""
    try:
        if DUCKDB_PATH.exists():
            con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
            row = con.execute("""
                SELECT MAX(scraped_at) FROM raw_wait_times
            """).fetchone()
            con.close()
            if row and row[0]:
                last = row[0]
                if hasattr(last, 'strftime'):
                    return last.strftime("%Y-%m-%d %H:%M ET")
                return str(last)
    except Exception:
        # DuckDB locked — use file modification time as proxy
        try:
            mtime = DUCKDB_PATH.stat().st_mtime
            dt = datetime.fromtimestamp(mtime, tz=ET)
            return f"~{dt.strftime('%Y-%m-%d %H:%M ET')} (file mtime)"
        except Exception:
            pass
    return "unknown"


def get_v3_pipeline_status() -> dict | None:
    """Check v3 pipeline status from pipeline_status.json (more reliable than bot health check alone)."""
    status_file = Path("/mnt/data/pipeline/state/pipeline_status.json")
    try:
        if status_file.exists():
            with open(status_file) as f:
                data = json.load(f)
            pipeline = data.get("pipeline", {})
            steps = pipeline.get("steps", {})
            # Check if all steps completed
            all_done = all(s.get("status") == "done" for s in steps.values()) if steps else False
            last_updated = data.get("last_updated", "")
            wti_done = steps.get("wti", {}).get("done_at", "")
            return {
                "all_done": all_done,
                "last_updated": last_updated,
                "wti_done_at": wti_done,
                "started_at": pipeline.get("started_at", ""),
                "step_count": len(steps),
            }
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Format the briefing
# ---------------------------------------------------------------------------

def format_briefing() -> str:
    lines = []
    lines.append(f"☀️ **Morning Briefing — {DOW}, {NOW.strftime('%B %d, %Y')}**\n")

    # 1. Pipeline Status — use v3 pipeline_status.json as primary, bot health as secondary
    v3 = get_v3_pipeline_status()
    status = get_pipeline_status()
    bot_health = status.get("status", "unknown")

    if v3 and v3["all_done"]:
        # v3 pipeline completed — trust it even if bot health check shows stale
        health = "healthy"
        health_emoji = "✅"
        if v3["wti_done_at"]:
            try:
                wti_dt = datetime.fromisoformat(v3["wti_done_at"])
                hours_ago = (NOW - wti_dt.astimezone(ET)).total_seconds() / 3600
                if hours_ago > 26:
                    health = "degraded"
                    health_emoji = "⚠️"
            except Exception:
                pass
    else:
        health = bot_health
        health_emoji = {"healthy": "✅", "degraded": "⚠️", "critical": "🔴"}.get(health, "❓")

    lines.append(f"**Pipeline:** {health_emoji} {health.title()}")

    scraper = get_scraper_freshness()
    lines.append(f"**Last scrape:** {scraper}")

    # Show last pipeline completion time if available
    if v3 and v3["wti_done_at"]:
        try:
            wti_dt = datetime.fromisoformat(v3["wti_done_at"])
            lines.append(f"**Last pipeline run:** {wti_dt.astimezone(ET).strftime('%Y-%m-%d %H:%M ET')}")
        except Exception:
            pass

    lines.append("")

    # 2. Today's WTI
    wti_data = get_today_wti()
    if wti_data and "error" not in wti_data[0]:
        lines.append("**📊 Today's Crowd Levels (WTI)**")

        # Group by resort
        groups = [
            ("🏰 WDW", WDW_PARKS),
            ("🎆 DLR", DLR_PARKS),
            ("🦖 Universal", UNI_PARKS),
        ]

        wti_map = {d["park"]: d["wti"] for d in wti_data}

        for label, parks in groups:
            park_strs = []
            for p in parks:
                if p in wti_map:
                    w = wti_map[p]
                    park_strs.append(f"{wti_emoji(w)} **{p}** {w}")
            if park_strs:
                lines.append(f"{label}: {' · '.join(park_strs)}")

        # International (if present)
        intl = [f"{wti_emoji(wti_map[p])} **{p}** {wti_map[p]}" for p in ["TDL", "TDS"] if p in wti_map]
        if intl:
            lines.append(f"🌍 Intl: {' · '.join(intl)}")

        # Highest and lowest
        sorted_wti = sorted(wti_data, key=lambda x: x.get("wti", 0), reverse=True)
        if len(sorted_wti) >= 2:
            top = sorted_wti[0]
            bot = sorted_wti[-1]
            lines.append(f"🔺 Busiest: **{PARK_NAMES.get(top['park'], top['park'])}** ({top['wti']})")
            lines.append(f"🔻 Quietest: **{PARK_NAMES.get(bot['park'], bot['park'])}** ({bot['wti']})")
        lines.append("")
    else:
        lines.append("**📊 WTI:** Data unavailable\n")

    # 3. Week Ahead
    outlook = get_week_outlook()
    if outlook:
        lines.append("**🗓️ Week Ahead**")
        best = min(outlook, key=lambda x: x["avg"])
        worst = max(outlook, key=lambda x: x["avg"])
        best_dow = datetime.strptime(best["date"], "%Y-%m-%d").strftime("%A %m/%d")
        worst_dow = datetime.strptime(worst["date"], "%Y-%m-%d").strftime("%A %m/%d")
        lines.append(f"✅ Best day: **{best_dow}** (avg {best['avg']})")
        lines.append(f"❌ Busiest: **{worst_dow}** (avg {worst['avg']})")
        lines.append("")

    # 4. Accuracy (if available)
    accuracy = get_yesterday_accuracy()
    if accuracy and isinstance(accuracy, dict):
        mae = accuracy.get("overall_mae") or accuracy.get("mae")
        bias = accuracy.get("overall_bias") or accuracy.get("bias")
        if mae is not None:
            lines.append(f"**🎯 Accuracy:** MAE {mae:.1f}" + (f" · Bias {bias:+.1f}" if bias is not None else ""))
            lines.append("")

    # 5. Tasks
    tasks = get_task_summary()
    if tasks:
        todo = tasks.get("todo", 0)
        blocked = tasks.get("blocked", 0)
        done = tasks.get("done", 0)
        lines.append(f"**📋 Tasks:** {todo} todo · {blocked} blocked · {done} done")
        lines.append("")

    # Footer
    lines.append(f"-# 📰 Arnold · {NOW.strftime('%H:%M')} ET")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discord posting
# ---------------------------------------------------------------------------

def post_to_discord(content: str) -> bool:
    """Post to #morning-briefing via Discord API."""
    import requests as req

    if not DISCORD_BOT_TOKEN:
        # Try loading from .env
        from dotenv import load_dotenv
        load_dotenv(os.path.expanduser("~/.env"))
        token = os.getenv("DISCORD_BOT_TOKEN", "")
    else:
        token = DISCORD_BOT_TOKEN

    if not token:
        print("ERROR: No DISCORD_BOT_TOKEN available", file=sys.stderr)
        return False

    url = f"https://discord.com/api/v10/channels/{MORNING_BRIEFING_CHANNEL}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    payload = {"content": content}
    resp = req.post(url, headers=headers, json=payload, timeout=15)

    if resp.status_code in (200, 201):
        print(f"[morning-briefing] Posted successfully (msg id: {resp.json().get('id')})")
        return True
    else:
        print(f"[morning-briefing] Failed to post: {resp.status_code} {resp.text}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Morning Briefing")
    parser.add_argument("--post", action="store_true", help="Post to Discord")
    parser.add_argument("--dry-run", action="store_true", help="Print only (default)")
    args = parser.parse_args()

    briefing = format_briefing()
    print(briefing)

    if args.post:
        ok = post_to_discord(briefing)
        if not ok:
            sys.exit(1)
    else:
        print("\n[morning-briefing] Dry run complete. Use --post to send to Discord.")


if __name__ == "__main__":
    main()
