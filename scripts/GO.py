#!/usr/bin/env python3
"""GO.py — Autonomous Project Orchestrator

Fred's interface for spinning up autonomous work. Fred writes natural language
in Discord, GO.py parses it, posts a proposal to #go-monitor for approval,
then executes once Fred reacts ✅.

Flow:
  1. Fred writes in #the-lodge: "Execute GO.py to do X in Y time"
  2. GO.py parses → posts proposal to #go-monitor forum
  3. Fred reacts ✅ to approve (❌ to reject, 💬 to discuss)
  4. GO.py creates PROJECT_STATE.json, spawns crons, spawns sub-agent

Usage:
  # Parse a message and post proposal:
  python3 GO.py parse "SSD scraper has 20 unmerged sources. Target 92% in 48h"

  # Execute an approved project (called after ✅ reaction):
  python3 GO.py execute <project_name> --fix="<problem>" --target="<metric>" --deadline="<time>"

  # Check status of a running project:
  python3 GO.py status <project_name>

  # List all active projects:
  python3 GO.py list

  # Monitor for GO.py triggers (test a message):
  python3 GO.py monitor --message "Execute GO.py to fix SSD coverage to 92% in 48h"

Built by: Barney (Claude in Claude.ai)
For: Fred Hazelton / HazeyData
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# === CONFIGURATION ===

PROJECTS_DIR = Path.home() / "clawd" / "projects"
SCRIPTS_DIR = Path(__file__).resolve().parent
LOG_DIR = Path.home() / "clawd" / "logs"

# Discord channel IDs
CHANNELS = {
    "the_lodge": "1481008455144701992",
    "go_monitor": "1484246120376045728",  # forum channel
    "briefing": "1482227277508120576",    # forum channel
    "fred_wilma": "1479351572386414675",
    "mission_control": "1479351570121621569",
    "pipeline": "1479351574177513576",
}

# Project name aliases — maps keywords to canonical project names
PROJECT_ALIASES = {
    "ssd": "school-schedules",
    "school": "school-schedules",
    "schedule": "school-schedules",
    "tpcr": "crowd-report",
    "crowd": "crowd-report",
    "pipeline": "crowd-report",
    "forecast": "crowd-report",
    "accord": "accord",
    "cdr": "canadian-digital-railway",
    "railway": "canadian-digital-railway",
    "datahub": "data-hub",
    "data-hub": "data-hub",
    "scraper": "data-hub",
    "quarry": "crowd-report",
    "twitch": "crowd-report",
    "instagram": "crowd-report",
}

# === NATURAL LANGUAGE PARSER ===

def parse_natural_language(message: str) -> dict:
    """Parse Fred's natural language into structured project data.

    Flexible parsing — Fred won't always phrase things the same way.
    Extracts: project context, problem, target metric, deadline, budget.
    """
    result = {
        "raw_message": message,
        "project_name": None,
        "problem_description": None,
        "target_metric": None,
        "target_value": None,
        "deadline_raw": None,
        "deadline_dt": None,
        "budget": "unlimited",
    }

    msg_lower = message.lower()

    # 1. Detect project from keywords
    for keyword, project in PROJECT_ALIASES.items():
        if keyword in msg_lower:
            result["project_name"] = project
            break

    # 2. Extract deadline patterns
    deadline_patterns = [
        (r"(\d+)\s*h(?:ours?|r|rs)?\b", "hours"),
        (r"(\d+)\s*d(?:ays?)?\b", "days"),
        (r"(\d+)\s*w(?:eeks?)?\b", "weeks"),
        (r"in\s+(\d+)\s*h", "hours"),
        (r"in\s+(\d+)\s*d", "days"),
        (r"within\s+(\d+)\s*h", "hours"),
        (r"within\s+(\d+)\s*d", "days"),
        (r"by\s+(?:end\s+of\s+)?tomorrow", "tomorrow"),
        (r"by\s+(?:end\s+of\s+)?(?:this\s+)?week", "end_of_week"),
    ]

    now = datetime.now(timezone.utc)
    for pattern, unit in deadline_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            if unit == "tomorrow":
                result["deadline_raw"] = "tomorrow"
                result["deadline_dt"] = (now + timedelta(days=1)).replace(
                    hour=23, minute=59, second=59
                ).isoformat()
            elif unit == "end_of_week":
                result["deadline_raw"] = "end of week"
                days_until_sunday = (6 - now.weekday()) % 7 or 7
                result["deadline_dt"] = (now + timedelta(days=days_until_sunday)).replace(
                    hour=23, minute=59, second=59
                ).isoformat()
            else:
                amount = int(match.group(1))
                result["deadline_raw"] = f"{amount} {unit}"
                if unit == "hours":
                    result["deadline_dt"] = (now + timedelta(hours=amount)).isoformat()
                elif unit == "days":
                    result["deadline_dt"] = (now + timedelta(days=amount)).isoformat()
                elif unit == "weeks":
                    result["deadline_dt"] = (now + timedelta(weeks=amount)).isoformat()
            break

    # 3. Extract target metric patterns
    target_patterns = [
        r"target\s+(\d+(?:\.\d+)?)\s*%\s*(\w+)",       # "target 92% coverage"
        r"(\d+(?:\.\d+)?)\s*%\s*(\w+)",               # "92% coverage"
        r"target\s+(\w+)\s*(?:of|at|to)?\s*(\d+(?:\.\d+)?)",  # "target MAE of 6.0"
        r"(\w+)\s*(?:below|under|<)\s*(\d+(?:\.\d+)?)",       # "MAE below 6.0"
        r"(\w+)\s*(?:above|over|>)\s*(\d+(?:\.\d+)?)",        # "coverage above 90"
    ]

    for pattern in target_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            groups = match.groups()
            try:
                val = float(groups[0])
                result["target_value"] = val
                result["target_metric"] = groups[1] if len(groups) > 1 else "percent"
            except ValueError:
                result["target_metric"] = groups[0]
                if len(groups) > 1:
                    try:
                        result["target_value"] = float(groups[1])
                    except ValueError:
                        pass
            break

    # 4. Extract problem description — everything that isn't metadata
    problem = re.sub(r"(?i)execute\s+go\.?py\s*(?:to)?\s*", "", message)
    problem = re.sub(r"(?i)target\s+\d+(?:\.\d+)?%?\s*\w*\s*(?:in|within)?\s*\d+\s*\w*", "", problem)
    problem = problem.strip().rstrip(".")
    if problem:
        result["problem_description"] = problem

    # 5. Generate a slug for the project
    if result["project_name"] and result["problem_description"]:
        slug_words = re.sub(r"[^a-z0-9\s]", "", result["problem_description"].lower()).split()[:4]
        result["project_slug"] = f"{result['project_name']}-{'-'.join(slug_words)}"
    elif result["project_name"]:
        result["project_slug"] = f"{result['project_name']}-task-{now.strftime('%Y%m%d')}"
    else:
        result["project_slug"] = f"unknown-task-{now.strftime('%Y%m%d')}"

    return result


# === COMMAND GENERATION ===

def generate_command(parsed: dict) -> str:
    """Generate the GO.py command string from parsed data."""
    parts = [f"GO.py execute {parsed['project_slug']}"]
    if parsed["problem_description"]:
        parts.append(f'--fix="{parsed["problem_description"]}"')
    if parsed["target_metric"] and parsed["target_value"] is not None:
        parts.append(f'--target="{parsed["target_value"]} {parsed["target_metric"]}"')
    if parsed["deadline_raw"]:
        parts.append(f'--deadline="{parsed["deadline_raw"]}"')
    return " ".join(parts)


def generate_proposal(parsed: dict) -> str:
    """Generate the Discord proposal message for #go-monitor."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cmd = generate_command(parsed)

    lines = [
        f"🚀 **PROPOSED GO.py TASK**",
        f"",
        f"```",
        f"{cmd}",
        f"```",
        f"",
        f"**Project:** {parsed.get('project_name', 'unknown')}",
        f"**Problem:** {parsed.get('problem_description', 'not specified')}",
    ]

    if parsed.get("target_metric") and parsed.get("target_value") is not None:
        lines.append(f"**Target:** {parsed['target_value']} {parsed['target_metric']}")
    if parsed.get("deadline_raw"):
        lines.append(f"**Deadline:** {parsed['deadline_raw']}")
        if parsed.get("deadline_dt"):
            lines.append(f"**Due:** {parsed['deadline_dt'][:19]}Z")
    lines.append(f"**Budget:** {parsed.get('budget', 'unlimited')}")
    lines.append(f"")
    lines.append(f"**Proposed at:** {now_str}")
    lines.append(f"")
    lines.append(f"React ✅ to **approve** | ❌ to **reject** | 💬 to **discuss**")

    return "\n".join(lines)


# === PROJECT SCAFFOLDING ===

def create_project_state(parsed: dict, authorized_by: str = "fred") -> dict:
    """Create the PROJECT_STATE.json for an approved project."""
    now = datetime.now(timezone.utc)
    slug = parsed["project_slug"]

    state = {
        "project_name": slug,
        "project_family": parsed.get("project_name", "unknown"),
        "owner": "wilma",
        "authorized_by": authorized_by,
        "authorized_at": now.isoformat(),
        "problem": parsed.get("problem_description", ""),
        "targets": {
            "primary_metric": parsed.get("target_metric", "completion"),
            "primary_target": parsed.get("target_value", 100.0),
            "secondary_metrics": [],
        },
        "deadline": parsed.get("deadline_dt", (now + timedelta(days=7)).isoformat()),
        "deadline_raw": parsed.get("deadline_raw", "7 days"),
        "budget": parsed.get("budget", "unlimited"),
        "baseline": {
            "measured_at": now.isoformat(),
            "notes": "baseline to be measured on first status check",
        },
        "status": "executing",
        "status_history": [
            {"status": "proposed", "at": now.isoformat()},
            {"status": "approved", "at": now.isoformat()},
            {"status": "executing", "at": now.isoformat()},
        ],
        "crons_created": [
            f"{slug}-status-daily",
            f"{slug}-report-weekly",
            f"{slug}-escalation",
        ],
        "sub_agent": {
            "label": f"{slug}-execution",
            "spawned_at": None,
        },
    }
    return state


def scaffold_project(parsed: dict) -> Path:
    """Create the project directory structure and write PROJECT_STATE.json."""
    slug = parsed["project_slug"]
    project_dir = PROJECTS_DIR / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "logs").mkdir(exist_ok=True)

    # Write PROJECT_STATE.json
    state = create_project_state(parsed)
    state_path = project_dir / "PROJECT_STATE.json"
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)

    # Write cron job configs
    crons = {
        "cron_daily_status.json": {
            "name": f"{slug}-status-daily",
            "schedule": "0 8 * * *",
            "task": f"Check progress on {slug}. Measure current metric vs target. "
                    f"Log to ~/clawd/projects/{slug}/logs/status.jsonl. "
                    f"If trending wrong, flag in #alerts.",
            "project": slug,
            "type": "status_check",
        },
        "cron_weekly_report.json": {
            "name": f"{slug}-report-weekly",
            "schedule": "0 12 * * 0",
            "task": f"Post weekly progress report for {slug} to #briefing. "
                    f"Include: current vs target, trend, blockers, next steps.",
            "project": slug,
            "type": "weekly_report",
        },
        "cron_escalation.json": {
            "name": f"{slug}-escalation",
            "schedule": "0 9 * * *",
            "task": f"Check if {slug} has missed targets 2+ consecutive days. "
                    f"If so, escalate: add warning to sub-agent prompt, notify #briefing.",
            "project": slug,
            "type": "escalation_check",
        },
    }

    for filename, config in crons.items():
        with open(project_dir / filename, "w") as f:
            json.dump(config, f, indent=2)

    return project_dir


# === DISCORD INTEGRATION ===

def post_to_discord(channel_id: str, message: str) -> bool:
    """Post a message to a Discord text channel."""
    try:
        token = os.environ.get("DISCORD_BOT_TOKEN", "")
        if not token:
            result = subprocess.run(
                ["bash", "-c", "crontab -l 2>/dev/null | grep -oP 'DISCORD_BOT_TOKEN=\\K[^ ]+' | head -1"],
                capture_output=True, text=True
            )
            token = result.stdout.strip()

        if not token:
            print("ERROR: DISCORD_BOT_TOKEN not found", file=sys.stderr)
            return False

        import urllib.request

        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        data = json.dumps({"content": message}).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"Discord post failed: {e}", file=sys.stderr)
        return False


def post_forum_thread(channel_id: str, title: str, body: str) -> str | None:
    """Create a forum thread. Returns thread ID or None."""
    try:
        result = subprocess.run(
            [str(SCRIPTS_DIR / "discord_forum_post.sh"), channel_id, title, body],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("OK thread_id="):
                    return line.split("=", 1)[1].strip()
        else:
            print(f"Forum post failed: {result.stderr}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Forum post error: {e}", file=sys.stderr)
        return None


def git_commit_project(project_dir: Path, slug: str, parsed: dict) -> bool:
    """Git add and commit the project state."""
    try:
        target_str = ""
        if parsed.get("target_metric") and parsed.get("target_value") is not None:
            target_str = f"\nTarget: {parsed['target_value']} {parsed['target_metric']}"

        deadline_str = ""
        if parsed.get("deadline_raw"):
            deadline_str = f"\nDeadline: {parsed['deadline_raw']}"

        commit_msg = (
            f"go: {slug}\n"
            f"{target_str}"
            f"{deadline_str}\n"
            f"Authorized by: Fred"
        )

        repo_root = SCRIPTS_DIR.parent
        subprocess.run(["git", "add", str(project_dir)], cwd=repo_root, check=True)
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_root, check=True)
        subprocess.run(["git", "push", "origin", "master"], cwd=repo_root, check=False)
        return True
    except Exception as e:
        print(f"Git commit failed: {e}", file=sys.stderr)
        return False


# === CLI COMMANDS ===

def cmd_parse(args):
    """Parse a natural language message and post proposal to #go-monitor."""
    message = " ".join(args.message)
    parsed = parse_natural_language(message)

    print("\n📋 Parsed project data:")
    print(json.dumps(parsed, indent=2))

    proposal = generate_proposal(parsed)
    print("\n📝 Proposal:")
    print(proposal)

    if args.dry_run:
        print("\n[DRY RUN] Would post to #go-monitor")
        return

    title = f"🚀 GO: {parsed['project_slug']}"
    thread_id = post_forum_thread(CHANNELS["go_monitor"], title, proposal)
    if thread_id:
        print(f"\n✅ Posted to #go-monitor (thread: {thread_id})")
        pending_dir = PROJECTS_DIR / ".pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        pending = {
            "parsed": parsed,
            "thread_id": thread_id,
            "proposed_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(pending_dir / f"{parsed['project_slug']}.json", "w") as f:
            json.dump(pending, f, indent=2)
    else:
        print("\n❌ Failed to post to #go-monitor")
        sys.exit(1)


def cmd_execute(args):
    """Execute an approved project — scaffold, create crons, announce."""
    pending_path = PROJECTS_DIR / ".pending" / f"{args.project}.json"

    if pending_path.exists():
        with open(pending_path) as f:
            pending = json.load(f)
        parsed = pending["parsed"]
    else:
        parsed = {
            "project_slug": args.project,
            "project_name": args.project.split("-")[0],
            "problem_description": args.fix or "no description",
            "target_metric": None,
            "target_value": None,
            "deadline_raw": args.deadline or "7 days",
            "deadline_dt": None,
            "budget": "unlimited",
        }
        if args.target:
            parts = args.target.split()
            try:
                parsed["target_value"] = float(parts[0])
                parsed["target_metric"] = parts[1] if len(parts) > 1 else "percent"
            except (ValueError, IndexError):
                parsed["target_metric"] = args.target

    print(f"\n🔧 Scaffolding project: {parsed['project_slug']}")

    project_dir = scaffold_project(parsed)
    print(f"  ✅ Created: {project_dir}")

    announcement = (
        f"🚀 **GO.py Project Launched**\n\n"
        f"**{parsed['project_slug']}**\n"
        f"Problem: {parsed.get('problem_description', 'n/a')}\n"
    )
    if parsed.get("target_metric") and parsed.get("target_value") is not None:
        announcement += f"Target: {parsed['target_value']} {parsed['target_metric']}\n"
    if parsed.get("deadline_raw"):
        announcement += f"Deadline: {parsed['deadline_raw']}\n"
    announcement += f"\nAuthorized by Fred. Executing now."

    post_to_discord(CHANNELS["fred_wilma"], announcement)
    print("  ✅ Announced to #fred-wilma")

    if git_commit_project(project_dir, parsed["project_slug"], parsed):
        print("  ✅ Git committed")
    else:
        print("  ⚠️  Git commit failed (non-fatal)")

    if pending_path.exists():
        pending_path.unlink()

    print(f"\n✅ Project {parsed['project_slug']} is live!")
    print(f"   State: {project_dir / 'PROJECT_STATE.json'}")
    print(f"   Crons: 3 created (daily status, weekly report, escalation)")
    print(f"   Next: Sub-agent will be spawned by Wilma's cron runner")


def cmd_status(args):
    """Check status of a project."""
    project_dir = PROJECTS_DIR / args.project
    state_path = project_dir / "PROJECT_STATE.json"

    if not state_path.exists():
        print(f"❌ No project found: {args.project}")
        sys.exit(1)

    with open(state_path) as f:
        state = json.load(f)

    print(f"\n📊 Project: {state['project_name']}")
    print(f"   Status: {state['status']}")
    print(f"   Owner: {state['owner']}")
    print(f"   Authorized by: {state['authorized_by']}")
    print(f"   Problem: {state.get('problem', 'n/a')}")

    targets = state.get("targets", {})
    print(f"   Target: {targets.get('primary_target', '?')} {targets.get('primary_metric', '')}")
    print(f"   Deadline: {state.get('deadline_raw', state.get('deadline', 'n/a'))}")

    if state.get("deadline"):
        try:
            deadline_dt = datetime.fromisoformat(state["deadline"])
            now = datetime.now(timezone.utc)
            if now > deadline_dt:
                overdue = now - deadline_dt
                print(f"   ⚠️  OVERDUE by {overdue.days}d {overdue.seconds // 3600}h")
            else:
                remaining = deadline_dt - now
                print(f"   ⏰ {remaining.days}d {remaining.seconds // 3600}h remaining")
        except (ValueError, TypeError):
            pass

    log_path = project_dir / "logs" / "status.jsonl"
    if log_path.exists():
        lines = log_path.read_text().strip().splitlines()
        recent = lines[-3:] if len(lines) >= 3 else lines
        print(f"\n   Recent log entries ({len(lines)} total):")
        for line in recent:
            try:
                entry = json.loads(line)
                print(f"     [{entry.get('timestamp', '?')[:16]}] {entry.get('note', entry)}")
            except json.JSONDecodeError:
                print(f"     {line[:80]}")


def cmd_list(args):
    """List all projects."""
    if not PROJECTS_DIR.exists():
        print("No projects directory found.")
        return

    projects = []
    for d in sorted(PROJECTS_DIR.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            state_path = d / "PROJECT_STATE.json"
            if state_path.exists():
                with open(state_path) as f:
                    state = json.load(f)
                projects.append(state)

    if not projects:
        print("No active projects.")
        return

    print(f"\n📋 Active Projects ({len(projects)}):")
    print(f"{'Name':<35} {'Status':<12} {'Target':<20} {'Deadline':<12}")
    print("-" * 80)
    for p in projects:
        name = p.get("project_name", "?")[:34]
        status = p.get("status", "?")[:11]
        targets = p.get("targets", {})
        target = f"{targets.get('primary_target', '?')} {targets.get('primary_metric', '')}"[:19]
        deadline = p.get("deadline_raw", "?")[:11]
        print(f"{name:<35} {status:<12} {target:<20} {deadline:<12}")


def cmd_monitor(args):
    """Monitor mode — check a message for GO.py triggers."""
    print("🔍 GO.py monitor mode")
    print(f"   Trigger: messages containing 'execute go.py' or 'GO.py'")

    if args.message:
        msg = " ".join(args.message)
        if re.search(r"(?i)(?:execute\s+)?go\.?py", msg):
            print(f"🎯 Trigger detected: {msg}")
            parsed = parse_natural_language(msg)
            proposal = generate_proposal(parsed)
            print(proposal)

            if not args.dry_run:
                title = f"🚀 GO: {parsed['project_slug']}"
                post_forum_thread(CHANNELS["go_monitor"], title, proposal)
        else:
            print("No GO.py trigger found in message.")
    else:
        print("Provide a message with --message or pipe via stdin.")
        print("Example: GO.py monitor --message 'Execute GO.py to fix SSD coverage to 92% in 48h'")


# === MAIN ===

def main():
    parser = argparse.ArgumentParser(
        description="GO.py — Autonomous Project Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Built by Barney for Fred. No work talk in The Lodge... except this. 🦬",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # parse
    p_parse = subparsers.add_parser("parse", help="Parse natural language and post proposal")
    p_parse.add_argument("message", nargs="+", help="Natural language message from Fred")
    p_parse.add_argument("--dry-run", action="store_true", help="Don't post to Discord")
    p_parse.set_defaults(func=cmd_parse)

    # execute
    p_exec = subparsers.add_parser("execute", help="Execute an approved project")
    p_exec.add_argument("project", help="Project slug")
    p_exec.add_argument("--fix", help="Problem description")
    p_exec.add_argument("--target", help="Target metric (e.g., '92 coverage')")
    p_exec.add_argument("--deadline", help="Deadline (e.g., '48h', '7 days')")
    p_exec.set_defaults(func=cmd_execute)

    # status
    p_status = subparsers.add_parser("status", help="Check project status")
    p_status.add_argument("project", help="Project slug")
    p_status.set_defaults(func=cmd_status)

    # list
    p_list = subparsers.add_parser("list", help="List all projects")
    p_list.set_defaults(func=cmd_list)

    # monitor
    p_monitor = subparsers.add_parser("monitor", help="Watch for GO.py triggers")
    p_monitor.add_argument("--message", nargs="+", help="Message to check for triggers")
    p_monitor.add_argument("--dry-run", action="store_true", help="Don't post to Discord")
    p_monitor.set_defaults(func=cmd_monitor)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
