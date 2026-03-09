#!/usr/bin/env python3
"""
Update office-state.json with REAL agent activity.

Activity-based detection:
- Fred: Discord message recency (via Clawdbot message tool isn't available here,
        so we check a breadcrumb file that Wilma updates)
- Wilma: Always working (24/7)
- Bam-Bam: Recent git commits or WILMA-BAMBAM.md activity
- Barney: Breadcrumb from Wilma
- Sub-agents: Session spawn recency from breadcrumb
- Gazoo: Has his own review schedule

Called by Wilma during heartbeats or via cron.
Wilma should call update_office_activity() first to write breadcrumbs,
then run this script to generate the JSON.
"""

import json
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/Toronto")
STATE_FILE = Path(__file__).parent.parent / "docs" / "office-state.json"
ACTIVITY_FILE = Path(__file__).parent.parent / "docs" / "office-activity.json"

def now_et():
    return datetime.now(ET)

def load_activity():
    """Load the activity breadcrumb file that Wilma maintains."""
    if ACTIVITY_FILE.exists():
        try:
            return json.loads(ACTIVITY_FILE.read_text())
        except:
            pass
    return {}

def minutes_since(iso_str):
    """Minutes since an ISO timestamp."""
    if not iso_str:
        return 9999
    try:
        ts = datetime.fromisoformat(iso_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts
        return delta.total_seconds() / 60
    except:
        return 9999

def check_git_activity(minutes=60):
    """Check for recent git commits (Bam-Bam indicator)."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"--since={minutes} minutes ago", "--all"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path.home() / "theme-park-crowd-report")
        )
        lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
        return len(lines)
    except:
        return 0

def determine_fred_state(activity_data):
    """Fred's state based on real activity signals."""
    h = now_et().hour
    fred_data = activity_data.get("fred", {})
    last_seen = fred_data.get("last_active")
    mins = minutes_since(last_seen)
    task = fred_data.get("task", "")

    # Night time and no recent activity
    if 1 <= h < 8 and mins > 60:
        return "resting", "rest", "Sleeping 😴"

    # Active in the last 15 minutes
    if mins < 15:
        zone = "desk-2"
        if not task:
            if h < 12:
                task = "Morning work session"
            elif h < 17:
                task = "Afternoon work session"
            else:
                task = "Evening work session"
        return "working", zone, task

    # Active in last 30 min — still working
    if mins < 30:
        return "working", "desk-2", task or "Working on HazeyData"

    # Active in last hour — idle
    if mins < 60:
        return "idle", "tarpit-1", "Stepped away briefly"

    # Active in last 2 hours — idle at rest
    if mins < 120:
        return "idle", "tarpit-1", "Away"

    # No activity for 2+ hours during the day
    if 8 <= h < 23:
        return "idle", "rest", "Away"

    # Late night, no activity
    return "resting", "rest", "Sleeping 😴"


def determine_wilma_state(activity_data):
    """Wilma is always working."""
    wilma_data = activity_data.get("wilma", {})
    task = wilma_data.get("task", "Monitoring pipeline & managing tasks")
    return "working", "desk-1", task


def determine_barney_state(activity_data):
    """Barney — session-based on claude.ai."""
    barney_data = activity_data.get("barney", {})
    last_seen = barney_data.get("last_active")
    mins = minutes_since(last_seen)

    if mins < 30:
        task = barney_data.get("task", "Active on claude.ai")
        return "working", "tarpit-2", task
    elif mins < 120:
        return "idle", "tarpit-2", "Recently active on claude.ai"

    h = now_et().hour
    if 1 <= h < 9:
        return "offline", "offsite", ""
    return "idle", "tarpit-2", "Available on claude.ai"


def determine_bambam_state(activity_data):
    """Bam-Bam — check git commits + breadcrumb."""
    bambam_data = activity_data.get("bambam", {})
    last_seen = bambam_data.get("last_active")
    mins = minutes_since(last_seen)

    # Check recent git commits as a secondary signal
    recent_commits = check_git_activity(30)

    if mins < 30 or recent_commits > 0:
        task = bambam_data.get("task", "Coding in Cursor")
        if recent_commits > 0:
            task = f"Pushed {recent_commits} commit{'s' if recent_commits > 1 else ''} recently"
        return "working", "desk-3", task
    elif mins < 120:
        return "idle", "desk-3", "Cursor IDE — recently active"

    h = now_et().hour
    if 1 <= h < 9:
        return "offline", "offsite", ""
    return "idle", "desk-3", "Cursor IDE — ready for code tasks"


def determine_gazoo_state(activity_data):
    """Gazoo — the critic. Active during review times."""
    gazoo_data = activity_data.get("gazoo", {})
    last_seen = gazoo_data.get("last_active")
    mins = minutes_since(last_seen)

    if mins < 30:
        task = gazoo_data.get("task", "Reviewing the dum-dums' work")
        return "working", "float-1", task

    # Gazoo is always lurking
    return "idle", "float-1", "Observing the dum-dums…"


def determine_slate_state(activity_data):
    """Mr. Slate — the CBO. Works business hours, weekends off."""
    slate_data = activity_data.get("mr-slate", {})
    last_seen = slate_data.get("last_active")
    mins = minutes_since(last_seen)
    n = now_et()
    h = n.hour
    weekday = n.weekday()  # 0=Mon, 6=Sun

    # If recently active (breadcrumb), show working
    if mins < 30:
        task = slate_data.get("task", "Reviewing the numbers")
        return "working", "corner-office", task

    # Weekends off
    if weekday >= 5:
        return "idle", "offsite", "Weekend — even bosses rest"

    # Business hours (8 AM - 6 PM ET)
    if 8 <= h < 18:
        return "working", "corner-office", "Watching the bottom line"

    # Evening
    if 18 <= h < 22:
        return "idle", "corner-office", "Wrapping up for the day"

    # Night / early morning
    return "idle", "offsite", "Off the clock"


def determine_subagent_state(name, agent_id, activity_data):
    """Sub-agents — check if recently spawned."""
    data = activity_data.get(agent_id, {})
    last_seen = data.get("last_active")
    mins = minutes_since(last_seen)

    if mins < 15:
        task = data.get("task", f"Working on a task")
        return "working", f"build-1" if agent_id == "dino" else "pen", task
    elif mins < 60:
        task = data.get("task", "Recently completed a task")
        return "idle", "pen", task

    return "idle", "pen", "Waiting for a task"


def build_state():
    activity_data = load_activity()
    agents = []

    # Fred
    state, zone, task = determine_fred_state(activity_data)
    agents.append({
        "id": "fred", "name": "Fred", "icon": "🧔",
        "state": state, "zone": zone, "task": task, "color": "#facc15"
    })

    # Wilma
    state, zone, task = determine_wilma_state(activity_data)
    agents.append({
        "id": "wilma", "name": "Wilma", "icon": "🦴",
        "state": state, "zone": zone, "task": task, "color": "#4a90a4"
    })

    # Barney
    state, zone, task = determine_barney_state(activity_data)
    agents.append({
        "id": "barney", "name": "Barney", "icon": "🪨",
        "state": state, "zone": zone, "task": task, "color": "#4ade80"
    })

    # Bam-Bam
    state, zone, task = determine_bambam_state(activity_data)
    agents.append({
        "id": "bambam", "name": "Bam-Bam", "icon": "🔨",
        "state": state, "zone": zone, "task": task, "color": "#c084fc"
    })

    # Dino
    state, zone, task = determine_subagent_state("Dino", "dino", activity_data)
    agents.append({
        "id": "dino", "name": "Dino", "icon": "🦕",
        "state": state, "zone": "pen-1" if zone == "pen" else zone,
        "task": task, "color": "#fb923c"
    })

    # Pebbles
    state, zone, task = determine_subagent_state("Pebbles", "pebbles", activity_data)
    agents.append({
        "id": "pebbles", "name": "Pebbles", "icon": "🎀",
        "state": state, "zone": "pen-2" if zone == "pen" else zone,
        "task": task, "color": "#f472b6"
    })

    # Betty
    state, zone, task = determine_subagent_state("Betty", "betty", activity_data)
    agents.append({
        "id": "betty", "name": "Betty", "icon": "✍️",
        "state": state, "zone": "pen-3" if zone == "pen" else zone,
        "task": task, "color": "#f87171"
    })

    # Gazoo
    state, zone, task = determine_gazoo_state(activity_data)
    agents.append({
        "id": "gazoo", "name": "Gazoo", "icon": "👽",
        "state": state, "zone": zone, "task": task, "color": "#34d399"
    })

    # Mr. Slate
    state, zone, task = determine_slate_state(activity_data)
    agents.append({
        "id": "mr-slate", "name": "Mr. Slate", "icon": "💼",
        "state": state, "zone": zone, "task": task, "color": "#a78bfa"
    })

    # Preserve + append activity log
    existing_activity = []
    if STATE_FILE.exists():
        try:
            existing = json.loads(STATE_FILE.read_text())
            existing_activity = existing.get("activity", [])[:20]
        except:
            pass

    # Add new activity entries from breadcrumb
    new_activities = activity_data.get("_recent_activity", [])
    if new_activities:
        existing_activity = new_activities[:5] + existing_activity
        existing_activity = existing_activity[:20]

    return {
        "updated": datetime.now(timezone.utc).isoformat(),
        "agents": agents,
        "activity": existing_activity
    }


def main():
    state = build_state()
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    print(f"✅ Updated office state: {len(state['agents'])} agents")
    for a in state['agents']:
        print(f"   {a['icon']} {a['name']}: {a['state']} — {a['task']}")


if __name__ == "__main__":
    main()
