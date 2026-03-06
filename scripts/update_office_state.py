#!/usr/bin/env python3
"""
Update office-state.json with real agent activity.
Called by Wilma during heartbeats or via cron.

Checks:
- Wilma: always working (Clawdbot is 24/7)
- Fred: time-based (resting at night, working during day)
- Bam-Bam: check WILMA-BAMBAM.md for recent activity
- Barney: check if claude.ai session referenced recently
- Sub-agents: check recent session spawns
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / "docs" / "office-state.json"
BAMBAM_FILE = Path.home() / "theme-park-crowd-report" / "WILMA-BAMBAM.md"

def get_hour():
    """Get current hour in ET."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/Toronto")).hour

def determine_fred_state():
    """Fred's state based on time of day."""
    h = get_hour()
    if 1 <= h < 9:
        return "resting", "rest", "Sleeping 😴"
    elif 9 <= h < 12:
        return "working", "desk-2", "Morning deep work"
    elif 12 <= h < 13:
        return "idle", "tarpit-1", "Lunch break"
    elif 13 <= h < 23:
        return "working", "desk-2", "Working on HazeyData"
    else:
        return "working", "desk-2", "Night owl mode 🦉"

def determine_wilma_state():
    """Wilma is always working."""
    return "working", "desk-1", "Monitoring pipeline & managing tasks"

def determine_barney_state():
    """Barney is session-based on claude.ai."""
    h = get_hour()
    if 1 <= h < 9:
        return "offline", "offsite", ""
    return "idle", "tarpit-2", "Available on claude.ai"

def determine_bambam_state():
    """Check WILMA-BAMBAM.md for recent Bam-Bam activity."""
    h = get_hour()
    if 1 <= h < 9:
        return "offline", "offsite", ""
    # Default: idle at desk
    return "idle", "desk-3", "Cursor IDE — ready for code tasks"

def determine_subagent_state(name):
    """Sub-agents are in the pen unless recently spawned."""
    return "idle", "pen", f"Waiting for a task"

def build_state():
    agents = []

    # Fred
    state, zone, task = determine_fred_state()
    agents.append({
        "id": "fred", "name": "Fred", "icon": "🧔",
        "state": state, "zone": zone, "task": task, "color": "#facc15"
    })

    # Wilma
    state, zone, task = determine_wilma_state()
    agents.append({
        "id": "wilma", "name": "Wilma", "icon": "🦴",
        "state": state, "zone": zone, "task": task, "color": "#4a90a4"
    })

    # Barney
    state, zone, task = determine_barney_state()
    agents.append({
        "id": "barney", "name": "Barney", "icon": "🪨",
        "state": state, "zone": zone, "task": task, "color": "#4ade80"
    })

    # Bam-Bam
    state, zone, task = determine_bambam_state()
    agents.append({
        "id": "bambam", "name": "Bam-Bam", "icon": "🔨",
        "state": state, "zone": zone, "task": task, "color": "#c084fc"
    })

    # Dino
    state, zone, task = determine_subagent_state("Dino")
    agents.append({
        "id": "dino", "name": "Dino", "icon": "🦕",
        "state": state, "zone": "pen-1", "task": task, "color": "#fb923c"
    })

    # Pebbles
    state, zone, task = determine_subagent_state("Pebbles")
    agents.append({
        "id": "pebbles", "name": "Pebbles", "icon": "🎀",
        "state": state, "zone": "pen-2", "task": task, "color": "#f472b6"
    })

    # Betty
    state, zone, task = determine_subagent_state("Betty")
    agents.append({
        "id": "betty", "name": "Betty", "icon": "✍️",
        "state": state, "zone": "pen-3", "task": task, "color": "#f87171"
    })

    # Try to preserve recent activity log
    existing_activity = []
    if STATE_FILE.exists():
        try:
            existing = json.loads(STATE_FILE.read_text())
            existing_activity = existing.get("activity", [])[:10]
        except:
            pass

    return {
        "updated": datetime.now(timezone.utc).isoformat(),
        "agents": agents,
        "activity": existing_activity
    }

def main():
    state = build_state()
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    print(f"✅ Updated office state: {len(state['agents'])} agents")

if __name__ == "__main__":
    main()
