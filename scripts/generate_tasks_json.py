#!/usr/bin/env python3
"""Generate tasks.json for Mission Control v3 Tasks tab.

Reads from ~/clawd-anthropic/dino/tasks.json (source of truth)
and writes to docs/analytics-data/tasks.json (dashboard format).
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

SOURCE = Path.home() / "clawd-anthropic" / "dino" / "tasks.json"
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "analytics-data" / "tasks.json"

# Map dino status -> dashboard column
STATUS_TO_COLUMN = {
    "todo": "backlog",
    "in_progress": "in_progress",
    "blocked": "review",
    "done": "done",
}

# Infer project from task context
PROJECT_KEYWORDS = {
    "Pipeline": ["pipeline", "etl", "forecast", "scrape", "data", "historical", "entity", "accuracy"],
    "Discord Bot": ["discord", "bot", "/ask", "dino"],
    "Website": ["dashboard", "website", "html", "overlay", "stream", "mission control"],
    "Content": ["twitter", "x ", "social", "content", "brand", "stream"],
    "Business": ["finance", "api key", "configure", "setup", "mac mini"],
}


def infer_project(task: dict) -> str:
    """Infer a project category from task title + description."""
    text = f"{task.get('title', '')} {task.get('description', '')}".lower()
    for project, keywords in PROJECT_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return project
    return "Pipeline"  # default


def is_this_week(date_str: str) -> bool:
    """Check if a date string falls within the current ISO week."""
    if not date_str:
        return False
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.now()
        # Same ISO week
        return dt.isocalendar()[:2] == now.isocalendar()[:2]
    except (ValueError, TypeError):
        return False


def transform_task(raw: dict, is_completed: bool = False) -> dict:
    """Transform a dino task to dashboard format."""
    status = raw.get("status", "todo")
    column = STATUS_TO_COLUMN.get(status, "backlog")

    # Recurring detection: tasks with "recurring" in notes or title
    is_recurring = False
    text_check = f"{raw.get('title', '')} {raw.get('notes', '')} {raw.get('description', '')}".lower()
    if "recurring" in text_check or "daily" in text_check or "weekly" in text_check:
        is_recurring = True

    if is_recurring and not is_completed:
        column = "recurring"

    project = raw.get("project", infer_project(raw))

    return {
        "id": raw.get("id", ""),
        "title": raw.get("title", ""),
        "description": raw.get("description", ""),
        "status": status,
        "column": "done" if is_completed else column,
        "priority": raw.get("priority", "medium"),
        "owner": raw.get("owner", "Wilma"),
        "project": project,
        "is_recurring": is_recurring,
        "created": raw.get("created", ""),
        "updated": raw.get("updated", raw.get("completed", "")),
        "notes": raw.get("notes", ""),
    }


def main():
    if not SOURCE.exists():
        print(f"Source not found: {SOURCE}")
        return

    with open(SOURCE) as f:
        dino = json.load(f)

    active_raw = dino.get("tasks", [])
    completed_raw = dino.get("completed", [])

    # Transform
    active_tasks = [transform_task(t, is_completed=False) for t in active_raw]
    completed_tasks = [transform_task(t, is_completed=True) for t in completed_raw]

    all_tasks = active_tasks + completed_tasks

    # Summary stats
    total_active = len(active_tasks)
    in_progress = sum(1 for t in active_tasks if t["status"] == "in_progress")
    this_week = sum(1 for t in all_tasks if is_this_week(t.get("updated") or t.get("created")))
    completed_this_week = sum(1 for t in completed_tasks if is_this_week(t.get("updated")))
    total_all = len(all_tasks)
    pct_complete = round(len(completed_tasks) / total_all * 100) if total_all > 0 else 0

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "total": total_active,
            "this_week": max(this_week, len(active_tasks)),  # at minimum show active count
            "in_progress": in_progress,
            "completed_this_week": completed_this_week,
            "pct_complete": pct_complete,
        },
        "tasks": all_tasks,
        "live_activity": [],  # populated later
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Generated {OUTPUT}")
    print(f"   {total_active} active tasks, {len(completed_tasks)} completed")
    print(f"   {in_progress} in progress, {pct_complete}% complete overall")


if __name__ == "__main__":
    main()
