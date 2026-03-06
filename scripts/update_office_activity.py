#!/usr/bin/env python3
"""
Update office-activity.json breadcrumb for a specific agent.
Called by Wilma whenever she detects agent activity.

Usage:
  python3 update_office_activity.py <agent_id> [--task "task description"] [--activity "activity text"]

Examples:
  python3 update_office_activity.py fred --task "Working on crowd report" --activity "Posted in #mission-control"
  python3 update_office_activity.py bambam --task "Fixing pipeline bug"
  python3 update_office_activity.py fred  # Just touch last_active timestamp
"""

import json
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/Toronto")
ACTIVITY_FILE = Path(__file__).parent.parent / "docs" / "office-activity.json"

def main():
    parser = argparse.ArgumentParser(description="Update office activity for an agent")
    parser.add_argument("agent_id", help="Agent ID (fred, wilma, barney, bambam, dino, pebbles, betty, gazoo)")
    parser.add_argument("--task", help="Current task description")
    parser.add_argument("--activity", help="Activity log entry")
    args = parser.parse_args()

    # Load existing
    data = {}
    if ACTIVITY_FILE.exists():
        try:
            data = json.loads(ACTIVITY_FILE.read_text())
        except:
            pass

    now_utc = datetime.now(timezone.utc).isoformat()
    now_local = datetime.now(ET)
    time_str = now_local.strftime("%H:%M")

    # Update agent
    if args.agent_id not in data:
        data[args.agent_id] = {}

    data[args.agent_id]["last_active"] = now_utc
    if args.task:
        data[args.agent_id]["task"] = args.task

    # Add to recent activity
    if args.activity:
        recent = data.get("_recent_activity", [])
        recent.insert(0, {
            "time": time_str,
            "agent": args.agent_id,
            "text": args.activity
        })
        data["_recent_activity"] = recent[:20]

    ACTIVITY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"✅ Updated {args.agent_id}: last_active={now_utc}")
    if args.task:
        print(f"   Task: {args.task}")
    if args.activity:
        print(f"   Activity: {args.activity}")

if __name__ == "__main__":
    main()
