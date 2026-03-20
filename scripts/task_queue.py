#!/usr/bin/env python3
"""Task Queue System — Sequential task processing for HazeyData

Replaces 46 competing cron jobs with a priority queue that Wilma
processes sequentially. No more session lock contention.

Tasks enter the queue from: cron triggers, GO.py projects, Fred's
messages, self-generated monitoring/escalation tasks.

Priority levels:
  0 = urgent (process immediately)
  1 = scheduled (has a time window, process in order)
  2 = background (process when idle)

Usage:
  # Add a task
  python3 task_queue.py add --priority 1 --source "cron:morning-ops" \\
    --description "Morning operations check" \\
    --payload "Check pipeline status, accuracy report, park intel"

  # Add urgent task
  python3 task_queue.py add --priority 0 --description "Pipeline failure" \\
    --payload "s07 training step failed with OOM"

  # Process next task (returns task details for Wilma to execute)
  python3 task_queue.py next

  # Mark task complete
  python3 task_queue.py complete <task-id> --result "Accuracy report generated"

  # List queue
  python3 task_queue.py list
  python3 task_queue.py list --status queued
  python3 task_queue.py list --status executing

  # Archive completed tasks (older than 24h)
  python3 task_queue.py archive

  # Queue stats
  python3 task_queue.py stats

  # Dispatch to specific agent
  python3 task_queue.py add --priority 1 --assign-to gazoo \\
    --description "Nightly audit" --payload "Full system review"

Built by: Barney (Claude Opus 4.6)
For: Fred Hazelton / HazeyData
Part of: Enterprise Redesign — Change Manifest v1.0
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

# === CONFIGURATION ===

QUEUE_DIR = Path.home() / "clawd" / "data"
QUEUE_FILE = QUEUE_DIR / "task_queue.json"
ARCHIVE_DIR = QUEUE_DIR / "queue_archive"
ARCHIVE_AFTER_HOURS = 24

PRIORITY_LABELS = {0: "URGENT", 1: "SCHEDULED", 2: "BACKGROUND"}
VALID_STATUSES = ["queued", "executing", "completed", "failed", "cancelled"]
VALID_AGENTS = ["wilma", "gazoo", "pebbles", "barney", "fred"]


# === QUEUE OPERATIONS ===

def load_queue() -> dict:
    """Load the task queue from disk."""
    if QUEUE_FILE.exists():
        with open(QUEUE_FILE) as f:
            return json.load(f)
    return {
        "_meta": {
            "version": 1,
            "created": now_iso(),
            "description": "HazeyData task queue — sequential processing, no lock contention",
        },
        "tasks": [],
    }


def save_queue(queue: dict):
    """Save the task queue to disk."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    queue["_meta"]["last_modified"] = now_iso()
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_id() -> str:
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    short_uuid = uuid4().hex[:6]
    return f"task-{date_part}-{short_uuid}"


# === COMMANDS ===

def cmd_add(args):
    """Add a task to the queue."""
    queue = load_queue()

    task = {
        "id": generate_id(),
        "priority": args.priority,
        "priority_label": PRIORITY_LABELS.get(args.priority, "UNKNOWN"),
        "source": args.source or "manual",
        "project": args.project or "general",
        "description": args.description,
        "payload": args.payload or "",
        "assigned_to": args.assign_to or "wilma",
        "created_at": now_iso(),
        "status": "queued",
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
    }

    queue["tasks"].append(task)
    save_queue(queue)

    print(f"Added: {task['id']}")
    print(f"  Priority: {task['priority_label']} ({task['priority']})")
    print(f"  Assigned: {task['assigned_to']}")
    print(f"  Description: {task['description']}")

    return task["id"]


def cmd_next(args):
    """Get and start the next task from the queue."""
    queue = load_queue()

    # Check for currently executing tasks
    executing = [t for t in queue["tasks"] if t["status"] == "executing"]
    if executing and not args.force:
        t = executing[0]
        print(f"Task already executing: {t['id']}")
        print(f"  Description: {t['description']}")
        print(f"  Started: {t['started_at']}")
        print(f"Use --force to start another task anyway, or complete the current one first.")
        return

    # Find next queued task by priority (lower number = higher priority), then by creation time
    queued = [t for t in queue["tasks"] if t["status"] == "queued"]
    if not queued:
        print("Queue empty — no tasks waiting.")
        return

    queued.sort(key=lambda t: (t["priority"], t["created_at"]))
    task = queued[0]

    # Mark as executing
    task["status"] = "executing"
    task["started_at"] = now_iso()
    save_queue(queue)

    print(f"\n{'='*60}")
    print(f"NEXT TASK: {task['id']}")
    print(f"{'='*60}")
    print(f"  Priority:    {task['priority_label']}")
    print(f"  Source:      {task['source']}")
    print(f"  Project:     {task['project']}")
    print(f"  Assigned to: {task['assigned_to']}")
    print(f"  Description: {task['description']}")
    if task["payload"]:
        print(f"  Payload:     {task['payload']}")
    print(f"{'='*60}")

    # Output as JSON for programmatic consumption
    if args.json:
        print(json.dumps(task, indent=2))


def cmd_complete(args):
    """Mark a task as completed."""
    queue = load_queue()

    task = _find_task(queue, args.task_id)
    if not task:
        print(f"Task not found: {args.task_id}")
        sys.exit(1)

    task["status"] = "completed"
    task["completed_at"] = now_iso()
    task["result"] = args.result or "completed"

    save_queue(queue)

    duration = ""
    if task["started_at"]:
        try:
            start = datetime.fromisoformat(task["started_at"])
            end = datetime.fromisoformat(task["completed_at"])
            delta = end - start
            mins = delta.total_seconds() / 60
            duration = f" ({mins:.1f} min)"
        except (ValueError, TypeError):
            pass

    print(f"Completed: {task['id']}{duration}")
    if args.result:
        print(f"  Result: {args.result}")


def cmd_fail(args):
    """Mark a task as failed."""
    queue = load_queue()

    task = _find_task(queue, args.task_id)
    if not task:
        print(f"Task not found: {args.task_id}")
        sys.exit(1)

    task["status"] = "failed"
    task["completed_at"] = now_iso()
    task["error"] = args.error or "unknown error"

    save_queue(queue)
    print(f"Failed: {task['id']}")
    print(f"  Error: {task['error']}")


def cmd_cancel(args):
    """Cancel a queued task."""
    queue = load_queue()

    task = _find_task(queue, args.task_id)
    if not task:
        print(f"Task not found: {args.task_id}")
        sys.exit(1)

    if task["status"] not in ("queued", "executing"):
        print(f"Cannot cancel task in '{task['status']}' status")
        sys.exit(1)

    task["status"] = "cancelled"
    task["completed_at"] = now_iso()

    save_queue(queue)
    print(f"Cancelled: {task['id']}")


def cmd_list(args):
    """List tasks in the queue."""
    queue = load_queue()
    tasks = queue["tasks"]

    if args.status:
        tasks = [t for t in tasks if t["status"] == args.status]

    if args.agent:
        tasks = [t for t in tasks if t["assigned_to"] == args.agent]

    if not tasks:
        print("No tasks found.")
        return

    # Sort: executing first, then by priority and creation time
    status_order = {"executing": 0, "queued": 1, "failed": 2, "completed": 3, "cancelled": 4}
    tasks.sort(key=lambda t: (status_order.get(t["status"], 9), t["priority"], t["created_at"]))

    print(f"\n{'ID':<28} {'Pri':<10} {'Status':<12} {'Agent':<10} {'Description'}")
    print("-" * 100)
    for t in tasks:
        pri = t.get("priority_label", str(t["priority"]))
        status = t["status"].upper()
        agent = t.get("assigned_to", "wilma")
        desc = t["description"][:40]
        print(f"{t['id']:<28} {pri:<10} {status:<12} {agent:<10} {desc}")

    print(f"\nTotal: {len(tasks)} tasks")


def cmd_stats(args):
    """Show queue statistics."""
    queue = load_queue()
    tasks = queue["tasks"]

    counts = {}
    for t in tasks:
        s = t["status"]
        counts[s] = counts.get(s, 0) + 1

    print(f"\nQueue Statistics:")
    print(f"  Queued:    {counts.get('queued', 0)}")
    print(f"  Executing: {counts.get('executing', 0)}")
    print(f"  Completed: {counts.get('completed', 0)}")
    print(f"  Failed:    {counts.get('failed', 0)}")
    print(f"  Cancelled: {counts.get('cancelled', 0)}")
    print(f"  Total:     {len(tasks)}")

    # Priority breakdown for queued tasks
    queued = [t for t in tasks if t["status"] == "queued"]
    if queued:
        print(f"\nQueued by priority:")
        for pri in sorted(set(t["priority"] for t in queued)):
            count = sum(1 for t in queued if t["priority"] == pri)
            label = PRIORITY_LABELS.get(pri, f"P{pri}")
            print(f"  {label}: {count}")

    # Agent breakdown
    agents = {}
    for t in tasks:
        a = t.get("assigned_to", "wilma")
        if a not in agents:
            agents[a] = {"queued": 0, "executing": 0, "completed": 0}
        if t["status"] in agents[a]:
            agents[a][t["status"]] += 1

    if agents:
        print(f"\nBy agent:")
        for agent, stats in sorted(agents.items()):
            print(f"  {agent}: {stats['queued']}q / {stats['executing']}e / {stats['completed']}c")


def cmd_archive(args):
    """Archive completed tasks older than threshold."""
    queue = load_queue()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours or ARCHIVE_AFTER_HOURS)

    to_archive = []
    remaining = []

    for task in queue["tasks"]:
        if task["status"] in ("completed", "cancelled", "failed"):
            completed_at = task.get("completed_at")
            if completed_at:
                try:
                    dt = datetime.fromisoformat(completed_at)
                    if dt < cutoff:
                        to_archive.append(task)
                        continue
                except (ValueError, TypeError):
                    pass
        remaining.append(task)

    if not to_archive:
        print("Nothing to archive.")
        return

    # Write archive file
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    archive_file = ARCHIVE_DIR / f"queue_archive_{date_str}.jsonl"

    with open(archive_file, "a") as f:
        for task in to_archive:
            f.write(json.dumps(task) + "\n")

    queue["tasks"] = remaining
    save_queue(queue)

    print(f"Archived {len(to_archive)} tasks to {archive_file}")
    print(f"Remaining in queue: {len(remaining)}")


def cmd_dispatch(args):
    """Dispatch a task to a specific agent (convenience wrapper for add + assign)."""
    args.assign_to = args.agent
    args.source = args.source or f"dispatch:{args.agent}"
    return cmd_add(args)


# === HELPERS ===

def _find_task(queue: dict, task_id: str) -> dict | None:
    """Find a task by ID (supports partial match)."""
    for task in queue["tasks"]:
        if task["id"] == task_id or task["id"].endswith(task_id):
            return task
    return None


# === MAIN ===

def main():
    parser = argparse.ArgumentParser(
        description="HazeyData Task Queue — sequential processing, no lock contention",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Part of the HazeyData Enterprise Redesign. Built by Barney. 🪨",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # add
    p_add = subparsers.add_parser("add", help="Add a task to the queue")
    p_add.add_argument("--priority", type=int, default=1, choices=[0, 1, 2],
                       help="0=urgent, 1=scheduled, 2=background")
    p_add.add_argument("--source", help="Where this task came from (e.g., cron:morning-ops)")
    p_add.add_argument("--project", help="Project name (e.g., crowd-report, accord, ssd)")
    p_add.add_argument("--description", required=True, help="What this task does")
    p_add.add_argument("--payload", help="Detailed instructions for the task")
    p_add.add_argument("--assign-to", default="wilma", choices=VALID_AGENTS,
                       help="Which agent should handle this")
    p_add.set_defaults(func=cmd_add)

    # next
    p_next = subparsers.add_parser("next", help="Get and start the next task")
    p_next.add_argument("--force", action="store_true", help="Start even if another task is executing")
    p_next.add_argument("--json", action="store_true", help="Output as JSON")
    p_next.set_defaults(func=cmd_next)

    # complete
    p_complete = subparsers.add_parser("complete", help="Mark a task as completed")
    p_complete.add_argument("task_id", help="Task ID to complete")
    p_complete.add_argument("--result", help="Result description")
    p_complete.set_defaults(func=cmd_complete)

    # fail
    p_fail = subparsers.add_parser("fail", help="Mark a task as failed")
    p_fail.add_argument("task_id", help="Task ID")
    p_fail.add_argument("--error", help="Error description")
    p_fail.set_defaults(func=cmd_fail)

    # cancel
    p_cancel = subparsers.add_parser("cancel", help="Cancel a queued task")
    p_cancel.add_argument("task_id", help="Task ID")
    p_cancel.set_defaults(func=cmd_cancel)

    # list
    p_list = subparsers.add_parser("list", help="List tasks")
    p_list.add_argument("--status", choices=VALID_STATUSES, help="Filter by status")
    p_list.add_argument("--agent", choices=VALID_AGENTS, help="Filter by agent")
    p_list.set_defaults(func=cmd_list)

    # stats
    p_stats = subparsers.add_parser("stats", help="Show queue statistics")
    p_stats.set_defaults(func=cmd_stats)

    # archive
    p_archive = subparsers.add_parser("archive", help="Archive old completed tasks")
    p_archive.add_argument("--hours", type=int, help=f"Archive tasks older than N hours (default: {ARCHIVE_AFTER_HOURS})")
    p_archive.set_defaults(func=cmd_archive)

    # dispatch (convenience)
    p_dispatch = subparsers.add_parser("dispatch", help="Dispatch a task to a specific agent")
    p_dispatch.add_argument("agent", choices=VALID_AGENTS, help="Target agent")
    p_dispatch.add_argument("--priority", type=int, default=1, choices=[0, 1, 2])
    p_dispatch.add_argument("--source", help="Task source")
    p_dispatch.add_argument("--project", help="Project name")
    p_dispatch.add_argument("--description", required=True, help="Task description")
    p_dispatch.add_argument("--payload", help="Detailed instructions")
    p_dispatch.set_defaults(func=cmd_dispatch)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
