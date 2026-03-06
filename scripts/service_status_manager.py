#!/usr/bin/env python3
"""
TPCR Service Status Manager

Monitors overall service health and manages public Discord announcements
for the TPCR community server. Designed to be called by Wilma (Clawdbot)
who handles the actual Discord message tool calls.

Health checks:
  1. Pipeline status (via pipeline_alert_check.py --json)
  2. Discord bot status (systemctl --user is-active tpcr-discord-bot)
  3. DuckDB database health (test query against tpcr_live.duckdb)

Overall status levels:
  - operational: all green
  - degraded: pipeline issues but bot works
  - down: bot or data not available

Usage:
  python3 service_status_manager.py --check   # Health check → JSON output
  python3 service_status_manager.py --fix     # Health check + auto-fixes
  python3 service_status_manager.py --status  # Show current status from state file

Output:
  JSON with action field: "post", "edit", or "nothing"
  Wilma reads the action and executes the Discord message tool calls.
"""

import argparse
import json
import os
import subprocess
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────

PIPELINE_BASE = Path("/mnt/data/pipeline")
DUCKDB_PATH = PIPELINE_BASE / "tpcr_live.duckdb"
STATE_DIR = PIPELINE_BASE / "state"
STATE_FILE = STATE_DIR / "service_status.json"
LOG_FILE = PIPELINE_BASE / "logs" / "service_status_manager.log"

# TPCR public server
TPCR_GUILD_ID = "1471374656253591695"
TPCR_ANNOUNCEMENTS_CHANNEL = "1471935589371609162"

# Scripts
PIPELINE_ALERT_SCRIPT = Path(__file__).parent / "pipeline_alert_check.py"
PYTHON = Path(__file__).parent.parent / ".venv" / "bin" / "python3"

SERVICE_NAME = "tpcr-discord-bot"

logger = logging.getLogger("service-status")


def setup_logging():
    """Configure logging to both file and stderr."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_FILE, mode="a"),
            logging.StreamHandler(sys.stderr),
        ],
    )


# ── State Management ──────────────────────────────────────────────────

def load_state() -> dict:
    """Load the current state from the state file."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not read state file: {e}")
    return {
        "current_status": "operational",
        "announcement_message_id": None,
        "last_status_change": None,
        "last_check": None,
        "check_details": {},
    }


def save_state(state: dict):
    """Save state to the state file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))
    logger.info(f"State saved: status={state['current_status']}")


# ── Health Checks ─────────────────────────────────────────────────────

def run_cmd(cmd: str, timeout: int = 15) -> tuple:
    """Run a shell command. Returns (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def check_pipeline() -> dict:
    """Run pipeline_alert_check.py and parse result."""
    cmd = f"{PYTHON} {PIPELINE_ALERT_SCRIPT} --json"
    code, stdout, stderr = run_cmd(cmd, timeout=30)

    if code == 3 or not stdout:
        return {
            "status": "unknown",
            "error": stderr or "Script failed to run",
            "issues": [],
        }

    try:
        result = json.loads(stdout)
        return {
            "status": result.get("status", "unknown"),  # ok / warning / critical
            "issue_count": result.get("issue_count", 0),
            "issues": result.get("issues", []),
            "consecutive_failures": result.get("consecutive_info", {}).get(
                "consecutive_failure_days", 0
            ),
        }
    except json.JSONDecodeError as e:
        return {"status": "unknown", "error": f"JSON parse error: {e}", "issues": []}


def check_bot_service() -> dict:
    """Check if the TPCR Discord bot systemd service is running."""
    code, stdout, stderr = run_cmd(f"systemctl --user is-active {SERVICE_NAME}")
    is_active = stdout == "active"

    # Get recent journal lines if not active
    journal_snippet = ""
    if not is_active:
        _, journal_out, _ = run_cmd(
            f"journalctl --user -u {SERVICE_NAME} --since '30 min ago' --no-pager -n 10"
        )
        journal_snippet = journal_out

    return {
        "running": is_active,
        "service_state": stdout or "unknown",
        "journal_snippet": journal_snippet,
    }


def check_duckdb() -> dict:
    """Check DuckDB health by running a simple query."""
    if not DUCKDB_PATH.exists():
        return {"healthy": False, "error": "Database file not found"}

    # Check for WAL file (corruption indicator when paired with failures)
    wal_path = Path(str(DUCKDB_PATH) + ".wal")
    wal_exists = wal_path.exists()
    wal_size = wal_path.stat().st_size if wal_exists else 0

    # Try a simple query via Python — write to temp file to avoid shell quoting issues
    import tempfile

    test_script = (
        "import sys\n"
        "try:\n"
        "    import duckdb\n"
        f"    con = duckdb.connect('{DUCKDB_PATH}', read_only=True)\n"
        "    result = con.execute('SELECT count(*) FROM information_schema.tables').fetchone()\n"
        "    con.close()\n"
        "    print(f'OK:{result[0]}')\n"
        "except Exception as e:\n"
        "    print(f'ERROR:{e}', file=sys.stderr)\n"
        "    sys.exit(1)\n"
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False
    ) as tmp:
        tmp.write(test_script)
        tmp_path = tmp.name

    try:
        code, stdout, stderr = run_cmd(f"{PYTHON} {tmp_path}", timeout=15)
    finally:
        os.unlink(tmp_path)

    if code == 0 and stdout.startswith("OK:"):
        table_count = stdout.split(":")[1]
        return {
            "healthy": True,
            "table_count": int(table_count),
            "wal_exists": wal_exists,
            "wal_size_bytes": wal_size,
        }
    else:
        return {
            "healthy": False,
            "error": stderr or stdout or "Query failed",
            "wal_exists": wal_exists,
            "wal_size_bytes": wal_size,
            "wal_corrupt": "corrupt" in (stderr or "").lower()
            or "io error" in (stderr or "").lower(),
        }


def determine_overall_status(pipeline: dict, bot: dict, duckdb: dict) -> str:
    """
    Determine overall service status.

    - operational: all green (or pipeline has only warnings)
    - degraded: pipeline issues but bot works and data accessible
    - down: bot not running OR data not accessible
    """
    bot_running = bot.get("running", False)
    db_healthy = duckdb.get("healthy", False)
    pipeline_status = pipeline.get("status", "unknown")

    # Down: bot not running or DB inaccessible
    if not bot_running or not db_healthy:
        return "down"

    # Degraded: pipeline critical issues (but bot and DB fine)
    if pipeline_status == "critical":
        return "degraded"

    # Operational: everything fine (warnings are acceptable)
    return "operational"


# ── Auto-Fix ──────────────────────────────────────────────────────────

def auto_fix(bot: dict, duckdb: dict) -> list:
    """
    Attempt to auto-fix common issues.
    Returns a list of actions taken.
    """
    actions = []

    # Fix 1: DuckDB WAL corruption
    if not duckdb.get("healthy", True) and duckdb.get("wal_corrupt", False):
        wal_path = Path(str(DUCKDB_PATH) + ".wal")
        if wal_path.exists():
            try:
                backup_name = f"{wal_path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
                wal_path.rename(backup_name)
                actions.append({
                    "action": "wal_removed",
                    "detail": f"Moved corrupt WAL to {backup_name}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                logger.info(f"Auto-fix: Moved corrupt WAL to {backup_name}")
            except Exception as e:
                logger.error(f"Auto-fix: Failed to move WAL: {e}")
                actions.append({
                    "action": "wal_remove_failed",
                    "detail": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

    # Fix 2: Bot not running → restart
    if not bot.get("running", True):
        logger.info("Auto-fix: Restarting bot service...")
        code, stdout, stderr = run_cmd(
            f"systemctl --user restart {SERVICE_NAME}", timeout=30
        )
        if code == 0:
            # Give it a moment to start
            import time
            time.sleep(3)
            # Verify it started
            code2, stdout2, _ = run_cmd(f"systemctl --user is-active {SERVICE_NAME}")
            restarted = stdout2 == "active"
            actions.append({
                "action": "bot_restarted",
                "success": restarted,
                "detail": f"Service state after restart: {stdout2}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            logger.info(f"Auto-fix: Bot restart {'succeeded' if restarted else 'FAILED'}")
        else:
            actions.append({
                "action": "bot_restart_failed",
                "detail": stderr or "Unknown error",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            logger.error(f"Auto-fix: Bot restart failed: {stderr}")

    return actions


# ── Announcement Message Formatting ──────────────────────────────────

def format_degraded_message(pipeline: dict, bot: dict, duckdb: dict) -> str:
    """Format announcement for degraded status (pipeline issues)."""
    lines = [
        "🛠️ **Service Notice**",
        "",
        "Our forecast data pipeline is currently experiencing issues. "
        "The bot is online and responding to commands, but some data may be outdated.",
        "",
    ]

    # Describe impact without internal details
    consec = pipeline.get("consecutive_failures", 0)
    if consec > 1:
        lines.append(
            f"We've been working on resolving data processing issues "
            f"that started {consec} days ago."
        )
    else:
        lines.append("We're working to resolve this as quickly as possible.")

    lines.extend([
        "",
        "**What this means for you:**",
        "• The bot will still respond to commands",
        "• Wait time estimates and crowd forecasts may not reflect the latest data",
        "• Historical data and park information remain available",
        "",
        "We'll update this message when everything is back to normal. 🔧",
    ])

    return "\n".join(lines)


def format_down_message(pipeline: dict, bot: dict, duckdb: dict) -> str:
    """Format announcement for down status (bot or DB unavailable)."""
    lines = [
        "🔴 **Service Interruption**",
        "",
    ]

    if not bot.get("running", True):
        lines.append(
            "The TPCR bot is currently offline. "
            "We're aware of the issue and working to restore service."
        )
    elif not duckdb.get("healthy", True):
        lines.append(
            "The TPCR bot is having trouble accessing its data. "
            "Commands may not work correctly until this is resolved."
        )
    else:
        lines.append(
            "We're experiencing a service interruption. "
            "Some features may be unavailable."
        )

    lines.extend([
        "",
        "**What this means for you:**",
        "• Bot commands may not work or may return errors",
        "• We're actively working on a fix",
        "",
        "We'll update this message once service is restored. 🔧",
    ])

    return "\n".join(lines)


def format_restored_message(
    previous_status: str, downtime_start: str
) -> str:
    """Format announcement for restored status (edit over the old message)."""
    lines = [
        "✅ **Service Restored**",
        "",
        "All systems are back to normal! The bot is online and data is up to date.",
        "",
    ]

    # Add downtime duration if we know when it started
    if downtime_start:
        try:
            start = datetime.fromisoformat(downtime_start)
            now = datetime.now(timezone.utc)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            duration = now - start
            hours = duration.total_seconds() / 3600
            if hours < 1:
                dur_str = f"{int(duration.total_seconds() / 60)} minutes"
            elif hours < 24:
                dur_str = f"{hours:.1f} hours"
            else:
                dur_str = f"{duration.days} days"
            lines.append(f"*Issue lasted approximately {dur_str}.*")
            lines.append("")
        except (ValueError, TypeError):
            pass

    lines.append("Thank you for your patience! 🎢")

    return "\n".join(lines)


# ── Main Logic ────────────────────────────────────────────────────────

def run_check(do_fix: bool = False) -> dict:
    """
    Run all health checks and determine what action (if any) to take.

    Returns a JSON-serializable dict with:
      - status: overall status (operational/degraded/down)
      - action: what Wilma should do (post/edit/nothing)
      - message_content: the Discord message to post/edit (if action != nothing)
      - channel_id: target channel
      - message_id: message to edit (if action == edit)
      - checks: detailed check results
      - fixes: list of auto-fix actions taken (if --fix)
    """
    now = datetime.now(timezone.utc).isoformat()

    # Run health checks
    logger.info("Running health checks...")
    pipeline = check_pipeline()
    bot = check_bot_service()
    duckdb = check_duckdb()

    # Auto-fix if requested (before determining status, so fixes can improve status)
    fixes = []
    if do_fix:
        fixes = auto_fix(bot, duckdb)
        # Re-check after fixes
        if fixes:
            logger.info("Re-checking after auto-fixes...")
            bot = check_bot_service()
            duckdb = check_duckdb()

    # Determine overall status
    new_status = determine_overall_status(pipeline, bot, duckdb)
    logger.info(
        f"Health check results — pipeline: {pipeline.get('status')}, "
        f"bot: {'running' if bot.get('running') else 'DOWN'}, "
        f"duckdb: {'healthy' if duckdb.get('healthy') else 'UNHEALTHY'} → "
        f"overall: {new_status}"
    )

    # Load previous state
    state = load_state()
    old_status = state.get("current_status", "operational")

    # Determine action
    action = "nothing"
    message_content = None
    message_id = state.get("announcement_message_id")

    if old_status == "operational" and new_status in ("degraded", "down"):
        # Went from good to bad → post new announcement
        action = "post"
        if new_status == "degraded":
            message_content = format_degraded_message(pipeline, bot, duckdb)
        else:
            message_content = format_down_message(pipeline, bot, duckdb)
        logger.info(f"Status change: {old_status} → {new_status} — posting announcement")

    elif old_status in ("degraded", "down") and new_status == "operational":
        # Recovered → edit existing announcement
        if message_id:
            action = "edit"
            message_content = format_restored_message(
                old_status, state.get("last_status_change")
            )
            logger.info(
                f"Status change: {old_status} → {new_status} — "
                f"editing announcement {message_id}"
            )
        else:
            # No message to edit, just update state
            action = "nothing"
            logger.info(
                f"Status change: {old_status} → {new_status} — "
                f"no announcement to edit"
            )

    elif old_status == "degraded" and new_status == "down":
        # Got worse → edit existing announcement (or post new one)
        if message_id:
            action = "edit"
            message_content = format_down_message(pipeline, bot, duckdb)
            logger.info(f"Status worsened: degraded → down — editing announcement")
        else:
            action = "post"
            message_content = format_down_message(pipeline, bot, duckdb)
            logger.info(f"Status worsened: degraded → down — posting announcement")

    elif old_status == "down" and new_status == "degraded":
        # Partially recovered → edit existing announcement
        if message_id:
            action = "edit"
            message_content = format_degraded_message(pipeline, bot, duckdb)
            logger.info(f"Partial recovery: down → degraded — editing announcement")
        else:
            action = "post"
            message_content = format_degraded_message(pipeline, bot, duckdb)
            logger.info(f"Partial recovery: down → degraded — posting announcement")

    else:
        # Status unchanged
        action = "nothing"
        logger.info(f"Status unchanged: {new_status}")

    # Update state
    status_changed = old_status != new_status
    if status_changed:
        state["last_status_change"] = now
    state["current_status"] = new_status
    state["last_check"] = now
    state["check_details"] = {
        "pipeline": {
            k: v
            for k, v in pipeline.items()
            if k != "issues"  # Don't store verbose issues in state
        },
        "bot": bot,
        "duckdb": {k: v for k, v in duckdb.items() if k != "error"},
    }
    save_state(state)

    # Build output
    output = {
        "status": new_status,
        "previous_status": old_status,
        "status_changed": status_changed,
        "action": action,
        "channel_id": TPCR_ANNOUNCEMENTS_CHANNEL,
        "guild_id": TPCR_GUILD_ID,
        "checks": {
            "pipeline": pipeline,
            "bot": bot,
            "duckdb": duckdb,
        },
        "timestamp": now,
    }

    if message_content:
        output["message_content"] = message_content

    if action == "edit" and message_id:
        output["message_id"] = message_id

    if fixes:
        output["fixes"] = fixes

    return output


def show_status() -> dict:
    """Show current status from state file without running checks."""
    state = load_state()
    return {
        "current_status": state.get("current_status", "unknown"),
        "last_check": state.get("last_check"),
        "last_status_change": state.get("last_status_change"),
        "announcement_message_id": state.get("announcement_message_id"),
        "check_details": state.get("check_details", {}),
    }


def main():
    parser = argparse.ArgumentParser(
        description="TPCR Service Status Manager"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check",
        action="store_true",
        help="Run health check, output JSON with action for Wilma",
    )
    group.add_argument(
        "--fix",
        action="store_true",
        help="Run health check + attempt auto-fixes",
    )
    group.add_argument(
        "--status",
        action="store_true",
        help="Show current status from state file",
    )
    # Hidden option: Wilma calls this after posting/editing to save the message ID
    parser.add_argument(
        "--set-message-id",
        metavar="ID",
        help="Save a Discord message ID to state (called after posting)",
    )
    args = parser.parse_args()

    setup_logging()

    if args.set_message_id:
        state = load_state()
        state["announcement_message_id"] = args.set_message_id
        save_state(state)
        print(json.dumps({"ok": True, "message_id": args.set_message_id}))
        return

    if args.status:
        result = show_status()
    elif args.check:
        result = run_check(do_fix=False)
    elif args.fix:
        result = run_check(do_fix=True)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, indent=2))

    # Exit code based on status
    status = result.get("status") or result.get("current_status", "unknown")
    exit_codes = {"operational": 0, "degraded": 1, "down": 2}
    sys.exit(exit_codes.get(status, 0))


if __name__ == "__main__":
    main()
