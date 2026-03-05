#!/usr/bin/env python3
"""Generate calendar.json for Mission Control v3 Calendar tab.

Parses system crontab + hardcoded Clawdbot cron jobs into a weekly
calendar view (Sun-Sat) with always-running services.
"""

import json
import subprocess
import re
from datetime import datetime, timedelta
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "analytics-data" / "calendar.json"

# ─── Always-running services ───────────────────────────────────
ALWAYS_RUNNING = [
    {"name": "queue-times-fetcher", "detail": "Every 5 min", "color": "cyan"},
    {"name": "tpcr-discord-bot", "detail": "7 commands", "color": "cyan"},
    {"name": "chat-server", "detail": "Stream overlay", "color": "cyan"},
    {"name": "twitch-chat", "detail": "Stream overlay", "color": "cyan"},
]

# ─── Known crontab entries (name, owner, color) ───────────────
# Maps a recognisable fragment of the cron command to metadata
KNOWN_CRON = {
    "b2_backup": ("B2 Backup", "System", "#8892b0"),
    "rclone": ("B2 Backup", "System", "#8892b0"),
    "backup": ("B2 Backup", "System", "#8892b0"),
    "retrain": ("Conversion Model Retrain", "Wilma", "#4a90a4"),
    "conversion_model": ("Conversion Model Retrain", "Wilma", "#4a90a4"),
    "daily_pipeline": ("Daily Pipeline", "Wilma", "#22d3ee"),
    "run_pipeline": ("Daily Pipeline", "Wilma", "#22d3ee"),
    "pipeline": ("Daily Pipeline", "Wilma", "#22d3ee"),
    "discord_daily": ("Discord Daily Report", "Wilma", "#4ade80"),
    "daily_report": ("Discord Daily Report", "Wilma", "#4ade80"),
    "screenshot": ("Bot Screenshots", "Wilma", "#4a90a4"),
    "bot_screenshot": ("Bot Screenshots", "Wilma", "#4a90a4"),
    "mission.control": ("Mission Control Update", "Wilma", "#4a90a4"),
    "update_github": ("GitHub Pages Update", "Wilma", "#4a90a4"),
    "update_mission": ("Mission Control Update", "Wilma", "#4a90a4"),
}

# ─── Hardcoded fallback for known system crons ────────────────
SYSTEM_CRONS = [
    {"minute": "0", "hour": "3", "dom": "*", "month": "*", "dow": "*",
     "name": "B2 Backup", "owner": "System", "color": "#8892b0"},
    {"minute": "0", "hour": "5", "dom": "1", "month": "*", "dow": "*",
     "name": "Conversion Model Retrain", "owner": "Wilma", "color": "#4a90a4"},
    {"minute": "0", "hour": "6", "dom": "*", "month": "*", "dow": "*",
     "name": "Daily Pipeline", "owner": "Wilma", "color": "#22d3ee"},
    {"minute": "0", "hour": "7", "dom": "*", "month": "*", "dow": "*",
     "name": "Discord Daily Report", "owner": "Wilma", "color": "#4ade80"},
    {"minute": "0", "hour": "8", "dom": "*", "month": "*", "dow": "*",
     "name": "Bot Screenshots", "owner": "Wilma", "color": "#4a90a4"},
]

# ─── Clawdbot cron jobs ───────────────────────────────────────
CLAWDBOT_CRONS = [
    {"minute": "30", "hour": "7", "dom": "*", "month": "*", "dow": "*",
     "name": "Daily Accuracy Report", "owner": "Wilma", "color": "#4ade80"},
    {"minute": "30", "hour": "7", "dom": "*", "month": "*", "dow": "*",
     "name": "WTI Accuracy Report", "owner": "Wilma", "color": "#4ade80"},
]

# ─── Heartbeat ─────────────────────────────────────────────────
HEARTBEAT = {"name": "Heartbeat Check", "owner": "Wilma", "color": "#22d3ee"}


def parse_crontab():
    """Try to parse real crontab; return list of parsed entries."""
    entries = []
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return entries
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Standard cron: min hour dom month dow command
            m = re.match(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+)$", line)
            if not m:
                continue
            minute, hour, dom, month, dow, cmd = m.groups()
            # Try to identify this cron
            cmd_lower = cmd.lower()
            name, owner, color = None, None, None
            for key, (n, o, c) in KNOWN_CRON.items():
                if key in cmd_lower:
                    name, owner, color = n, o, c
                    break
            if name is None:
                # Use last part of command as name
                cmd_parts = cmd.split("/")
                fname = cmd_parts[-1].split()[0] if cmd_parts else cmd[:30]
                fname = re.sub(r"\.(py|sh|bash)$", "", fname).replace("_", " ").title()
                name = fname[:40]
                owner = "System"
                color = "#8892b0"
            entries.append({
                "minute": minute, "hour": hour, "dom": dom,
                "month": month, "dow": dow,
                "name": name, "owner": owner, "color": color,
            })
    except Exception:
        pass
    return entries


def format_time(hour_str, minute_str):
    """Convert hour/minute strings to '3:00 AM' format."""
    try:
        h = int(hour_str)
        m = int(minute_str)
        ampm = "AM" if h < 12 else "PM"
        display_h = h % 12
        if display_h == 0:
            display_h = 12
        return f"{display_h}:{m:02d} {ampm}"
    except (ValueError, TypeError):
        return f"{hour_str}:{minute_str}"


def cron_matches_date(entry, dt):
    """Check if a cron entry fires on a given date."""
    # Day of month
    dom = entry["dom"]
    if dom != "*":
        try:
            if int(dom) != dt.day:
                return False
        except ValueError:
            pass

    # Month
    month = entry["month"]
    if month != "*":
        try:
            if int(month) != dt.month:
                return False
        except ValueError:
            pass

    # Day of week (0=Sun or 7=Sun in cron, Python: 0=Mon..6=Sun)
    dow = entry["dow"]
    if dow != "*":
        try:
            cron_dow = int(dow)
            # Convert python weekday (0=Mon) to cron (0=Sun)
            py_dow = dt.weekday()  # 0=Mon
            cron_from_py = (py_dow + 1) % 7  # 0=Sun
            if cron_dow == 7:
                cron_dow = 0  # normalize
            if cron_dow != cron_from_py:
                return False
        except ValueError:
            pass

    return True


def get_current_week():
    """Return (week_start_sunday, week_end_saturday) for the current week."""
    today = datetime.now()
    # Go back to Sunday
    days_since_sunday = (today.weekday() + 1) % 7
    sunday = today - timedelta(days=days_since_sunday)
    sunday = sunday.replace(hour=0, minute=0, second=0, microsecond=0)
    saturday = sunday + timedelta(days=6)
    return sunday, saturday


def generate_heartbeat_entries():
    """Generate ~every 30 min heartbeat entries (just show 2 per day for readability)."""
    return [
        {"name": HEARTBEAT["name"], "time": "~every 30 min", "owner": HEARTBEAT["owner"], "color": HEARTBEAT["color"]},
    ]


def main():
    # Parse real crontab
    parsed_crons = parse_crontab()

    # Deduplicate: if we parsed real crons, use them; otherwise fall back to hardcoded
    if parsed_crons:
        # Merge: use parsed crons, but also include any SYSTEM_CRONS not already found
        found_names = {e["name"] for e in parsed_crons}
        all_crons = list(parsed_crons)
        for sc in SYSTEM_CRONS:
            if sc["name"] not in found_names:
                all_crons.append(sc)
    else:
        all_crons = list(SYSTEM_CRONS)

    # Add Clawdbot crons
    all_crons.extend(CLAWDBOT_CRONS)

    # Get current week
    week_start, week_end = get_current_week()
    day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

    days = {}
    for i in range(7):
        dt = week_start + timedelta(days=i)
        day_name = day_names[i]
        day_events = []

        for cron in all_crons:
            if cron_matches_date(cron, dt):
                day_events.append({
                    "name": cron["name"],
                    "time": format_time(cron["hour"], cron["minute"]),
                    "owner": cron["owner"],
                    "color": cron["color"],
                })

        # Add heartbeat
        day_events.append({
            "name": HEARTBEAT["name"],
            "time": "~every 30 min",
            "owner": HEARTBEAT["owner"],
            "color": HEARTBEAT["color"],
        })

        # Sort by time (put heartbeat at end since it's ongoing)
        def sort_key(e):
            if e["time"].startswith("~"):
                return (99, 99)
            try:
                parts = e["time"].replace(" AM", "").replace(" PM", "").split(":")
                h = int(parts[0])
                m = int(parts[1])
                if "PM" in e["time"] and h != 12:
                    h += 12
                if "AM" in e["time"] and h == 12:
                    h = 0
                return (h, m)
            except:
                return (50, 0)

        day_events.sort(key=sort_key)
        days[day_name] = day_events

    # Build final JSON
    result = {
        "generated_at": datetime.now().isoformat(),
        "always_running": ALWAYS_RUNNING,
        "week_start": week_start.strftime("%Y-%m-%d"),
        "week_end": week_end.strftime("%Y-%m-%d"),
        "today": datetime.now().strftime("%A")[:3],
        "today_date": datetime.now().strftime("%Y-%m-%d"),
        "days": days,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2))
    print(f"✅ Generated {OUTPUT}")
    print(f"   Week: {week_start.strftime('%Y-%m-%d')} → {week_end.strftime('%Y-%m-%d')}")
    total_events = sum(len(v) for v in days.values())
    print(f"   Total events: {total_events} across 7 days")


if __name__ == "__main__":
    main()
