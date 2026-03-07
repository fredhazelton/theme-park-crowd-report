#!/usr/bin/env python3
"""
TPCR Service Status Manager

Monitors overall service health and manages public Discord announcements
for the TPCR community server.

Health checks:
  1. Pipeline status (via pipeline_alert_check.py --json)
  2. Discord bot status (systemctl --user is-active tpcr-discord-bot)
  3. DuckDB database health (test query against tpcr_live.duckdb)

Overall status levels:
  - operational: all green
  - degraded: pipeline issues but bot works
  - down: bot or data not available

Usage:
  python3 service_status_manager.py --check   # Health check → JSON output (for Wilma)
  python3 service_status_manager.py --fix     # Health check + auto-fixes → JSON output
  python3 service_status_manager.py --auto    # Health check + fixes + Discord post/edit (for cron)
  python3 service_status_manager.py --status  # Show current status from state file

Output (--check/--fix):
  JSON with action field: "post", "edit", or "nothing"
  Wilma reads the action and executes the Discord message tool calls.

Output (--auto):
  Runs the check, applies auto-fixes, and directly posts/edits Discord
  announcements via the REST API. Designed for cron execution.
"""

import argparse
import json
import os
import subprocess
import sys
import logging
import requests
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

DISCORD_API_BASE = "https://discord.com/api/v10"


def _get_discord_token() -> str | None:
    """Load the Discord bot token from environment."""
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        logger.error("DISCORD_BOT_TOKEN not set in environment")
    return token


def discord_post_message(channel_id: str, content: str) -> dict | None:
    """
    Post a new message to a Discord channel via REST API.
    Returns the message object on success, None on failure.
    """
    token = _get_discord_token()
    if not token:
        return None

    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    payload = {"content": content}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            data = resp.json()
            logger.info(f"Discord: Posted message {data['id']} to channel {channel_id}")
            return data
        else:
            logger.error(
                f"Discord POST failed: {resp.status_code} — {resp.text[:300]}"
            )
            return None
    except Exception as e:
        logger.error(f"Discord POST exception: {e}")
        return None


def discord_edit_message(channel_id: str, message_id: str, content: str) -> dict | None:
    """
    Edit an existing Discord message via REST API.
    Returns the updated message object on success, None on failure.
    """
    token = _get_discord_token()
    if not token:
        return None

    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    payload = {"content": content}

    try:
        resp = requests.patch(url, headers=headers, json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"Discord: Edited message {message_id} in channel {channel_id}")
            return data
        elif resp.status_code == 404:
            logger.warning(
                f"Discord PATCH 404: Message {message_id} not found — may need new post"
            )
            return None
        else:
            logger.error(
                f"Discord PATCH failed: {resp.status_code} — {resp.text[:300]}"
            )
            return None
    except Exception as e:
        logger.error(f"Discord PATCH exception: {e}")
        return None


def execute_discord_action(result: dict) -> bool:
    """
    Execute the Discord action determined by run_check().
    Posts or edits the announcement message and saves the message_id to state.
    Returns True if the action was executed successfully (or nothing to do).
    """
    action = result.get("action", "nothing")
    channel_id = result.get("channel_id", TPCR_ANNOUNCEMENTS_CHANNEL)
    message_content = result.get("message_content")

    if action == "nothing":
        logger.info("Auto: No Discord action needed")
        return True

    if not message_content:
        logger.error("Auto: Action requires message_content but none provided")
        return False

    if action == "post":
        resp = discord_post_message(channel_id, message_content)
        if resp and "id" in resp:
            # Save the new message ID to state so future edits target it
            state = load_state()
            state["announcement_message_id"] = resp["id"]
            save_state(state)
            logger.info(f"Auto: Posted announcement, saved message_id={resp['id']}")
            return True
        else:
            logger.error("Auto: Failed to post announcement")
            return False

    elif action == "edit":
        message_id = result.get("message_id")
        if not message_id:
            logger.warning("Auto: Edit requested but no message_id — falling back to post")
            resp = discord_post_message(channel_id, message_content)
            if resp and "id" in resp:
                state = load_state()
                state["announcement_message_id"] = resp["id"]
                save_state(state)
                logger.info(f"Auto: Fallback post, saved message_id={resp['id']}")
                return True
            return False

        resp = discord_edit_message(channel_id, message_id, message_content)
        if resp:
            logger.info(f"Auto: Edited announcement {message_id}")
            return True
        else:
            # Edit failed (maybe message was deleted) — fall back to new post
            logger.warning("Auto: Edit failed, falling back to new post")
            resp = discord_post_message(channel_id, message_content)
            if resp and "id" in resp:
                state = load_state()
                state["announcement_message_id"] = resp["id"]
                save_state(state)
                logger.info(f"Auto: Fallback post after edit fail, message_id={resp['id']}")
                return True
            return False

    else:
        logger.warning(f"Auto: Unknown action '{action}'")
        return False


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
#
# Fred's rule: be transparent. Users appreciate honesty.
# Tell people what happened and why, just skip the internal jargon.
# Tone: friendly, technical-but-accessible, like a dev blog post.


def _describe_pipeline_issues(pipeline: dict) -> list:
    """
    Translate raw pipeline issues into plain-language explanations.
    Returns a list of human-readable strings (no internal jargon).
    """
    descriptions = []
    issues = pipeline.get("issues", [])
    issue_types = {i["type"] for i in issues}

    if "OOM_KILL" in issue_types or "MEMORY_ERROR" in issue_types or "OOM_ERROR" in issue_types:
        descriptions.append(
            "Our forecast models ran out of memory during training. "
            "These models crunch a lot of historical park data at once, "
            "and sometimes that exceeds what our server can handle."
        )
    elif "STEP_FAILED" in issue_types or "NONZERO_EXIT" in issue_types:
        descriptions.append(
            "One of the steps in our data processing pipeline hit an error "
            "and couldn't finish. This means new forecast data wasn't generated."
        )

    if "PROLONGED_FAILURE" in issue_types:
        consec = pipeline.get("consecutive_failures", 0)
        descriptions.append(
            f"This has been an ongoing issue — our pipeline has been struggling "
            f"for about {consec} days now. We're actively working on a fix "
            f"(likely adjusting how much data we process at once)."
        )
    elif "MULTI_DAY_FAILURE" in issue_types or "REPEATED_FAILURE" in issue_types:
        consec = pipeline.get("consecutive_failures", 0)
        descriptions.append(
            f"This issue has persisted for {consec} days. "
            f"We're investigating the root cause."
        )

    if "WTI_STALE" in issue_types or "WTI_MISSING" in issue_types:
        descriptions.append(
            "The Wait Time Index (the crowd level scores you see for each park) "
            "hasn't been refreshed recently, so the numbers may be out of date."
        )

    if "FORECAST_STALE" in issue_types or "FORECAST_MISSING" in issue_types:
        descriptions.append(
            "Our crowd forecasts haven't been updated with the latest data, "
            "so predictions may be less accurate than usual."
        )

    if "VALIDATION_FAIL" in issue_types:
        descriptions.append(
            "Our automated quality checks flagged some issues with the output data. "
            "The forecasts were generated but may not meet our accuracy standards."
        )

    # Fallback if none of the above matched
    if not descriptions and issues:
        descriptions.append(
            "Our data processing pipeline ran into a technical issue. "
            "We're looking into it."
        )

    return descriptions


def _describe_db_issue(duckdb: dict) -> str:
    """Translate DB issues into plain language."""
    if duckdb.get("wal_corrupt", False):
        return (
            "The bot's database had a write log that got corrupted — "
            "think of it like a scratch file that got garbled. "
            "This prevented the bot from reading park data."
        )
    return (
        "The bot couldn't access its database where all the park data is stored. "
        "Without that data, it can't answer questions about wait times or crowds."
    )


def _format_duration(downtime_start: str) -> str | None:
    """Calculate and format a human-readable duration string."""
    if not downtime_start:
        return None
    try:
        start = datetime.fromisoformat(downtime_start)
        now = datetime.now(timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        total_seconds = (now - start).total_seconds()
        if total_seconds < 60:
            return "under a minute"
        elif total_seconds < 3600:
            mins = int(total_seconds / 60)
            return f"about {mins} minute{'s' if mins != 1 else ''}"
        elif total_seconds < 86400:
            hours = total_seconds / 3600
            if hours < 2:
                return "about an hour"
            return f"about {hours:.0f} hours"
        else:
            days = (now - start).days
            return f"about {days} day{'s' if days != 1 else ''}"
    except (ValueError, TypeError):
        return None


def _describe_fixes(fixes: list) -> list:
    """Translate auto-fix actions into plain language (deduplicated)."""
    descriptions = []
    seen_actions = set()
    for fix in (fixes or []):
        action = fix.get("action", "")
        # Deduplicate: only describe each action type once
        action_key = f"{action}:{fix.get('success', '')}"
        if action_key in seen_actions:
            continue
        seen_actions.add(action_key)
        if action == "bot_restarted" and fix.get("success"):
            descriptions.append("We restarted the bot service and it came back up successfully.")
        elif action == "bot_restarted" and not fix.get("success"):
            descriptions.append(
                "We tried restarting the bot but it didn't come back cleanly — "
                "we're investigating further."
            )
        elif action == "wal_removed":
            descriptions.append(
                "We cleared a corrupted database write log and restored the database to a clean state."
            )
        elif action == "bot_restart_failed":
            descriptions.append(
                "We attempted to restart the bot but ran into an error. "
                "We're looking into it manually."
            )
    return descriptions


def format_degraded_message(pipeline: dict, bot: dict, duckdb: dict) -> str:
    """Format announcement for degraded status (pipeline issues, bot still works)."""
    lines = [
        "🛠️ **Service Notice — Data Pipeline Issues**",
        "",
        "Hey everyone — quick heads up on what's going on.",
        "",
    ]

    # Explain what happened
    lines.append("**What happened:**")
    descriptions = _describe_pipeline_issues(pipeline)
    for desc in descriptions:
        lines.append(desc)
    lines.append("")

    # Explain what still works
    lines.append("**What still works:**")
    lines.append("• The bot is online and responding to commands ✅")
    lines.append("• Historical wait time data and park info are still available")
    lines.append("• `/now` live wait times from the parks are unaffected (those come directly from the parks)")
    lines.append("")

    # Explain what's affected
    lines.append("**What's affected:**")
    issue_types = {i["type"] for i in pipeline.get("issues", [])}
    if "WTI_STALE" in issue_types or "WTI_MISSING" in issue_types:
        lines.append("• Wait Time Index scores may be out of date")
    if "FORECAST_STALE" in issue_types or "FORECAST_MISSING" in issue_types:
        lines.append("• Crowd level forecasts may not reflect the most recent trends")
    if not any(t in issue_types for t in ("WTI_STALE", "WTI_MISSING", "FORECAST_STALE", "FORECAST_MISSING")):
        lines.append("• Crowd forecasts and Wait Time Index data may not be fully up to date")
    lines.append("")

    lines.append("We're working on it and will update this message when it's resolved. 🔧")

    return "\n".join(lines)


def format_down_message(pipeline: dict, bot: dict, duckdb: dict) -> str:
    """Format announcement for down status (bot or DB unavailable)."""
    bot_down = not bot.get("running", True)
    db_down = not duckdb.get("healthy", True)

    lines = [
        "🔴 **Service Interruption**",
        "",
        "Hey everyone — we're having some issues right now. Here's what's going on:",
        "",
    ]

    # Explain what happened — be specific
    lines.append("**What happened:**")

    if bot_down and db_down:
        lines.append(
            "The bot process went down, and we're also seeing issues with "
            "the underlying database. We're working on bringing everything back up."
        )
        # Add DB-specific context
        lines.append(_describe_db_issue(duckdb))
    elif bot_down:
        # Check journal for clues about why
        journal = bot.get("journal_snippet", "")
        if "memory" in journal.lower() or "killed" in journal.lower() or "oom" in journal.lower():
            lines.append(
                "The bot ran out of memory and crashed. This can happen during "
                "heavy usage or when our data processing pipeline is running "
                "at the same time. We're restarting it now."
            )
        elif "error" in journal.lower() or "exception" in journal.lower():
            lines.append(
                "The bot hit an unexpected error and stopped running. "
                "We're looking at the logs to figure out what went wrong "
                "and getting it back online."
            )
        else:
            lines.append(
                "The bot stopped running. We're not sure of the exact cause yet "
                "but we're restarting it and investigating."
            )
    elif db_down:
        lines.append(
            "The bot is running, but it can't access its data right now. "
            "That means commands that need park data (crowd forecasts, "
            "wait time history, etc.) won't work correctly."
        )
        lines.append(_describe_db_issue(duckdb))
    else:
        lines.append(
            "We're seeing multiple issues across our systems. "
            "The bot may not respond correctly to commands."
        )
    lines.append("")

    # What's affected
    lines.append("**What this means for you:**")
    if bot_down:
        lines.append("• Bot commands won't work until we get it restarted")
        lines.append("• This is usually a quick fix — we'll have it back shortly")
    elif db_down:
        lines.append("• Commands like `/crowd`, `/today`, and `/ask` may return errors")
        lines.append("• `/now` (live wait times) might still work since it pulls directly from parks")
    else:
        lines.append("• Some commands may not work or may return errors")
    lines.append("")

    lines.append(
        "We're on it and will update this message as soon as things are back to normal. 🔧"
    )

    return "\n".join(lines)


def format_restored_message(
    previous_status: str,
    downtime_start: str,
    pipeline: dict | None = None,
    bot: dict | None = None,
    duckdb: dict | None = None,
    fixes: list | None = None,
) -> str:
    """Format announcement for restored status (edit over the old message)."""
    lines = [
        "✅ **Service Restored**",
        "",
    ]

    # Duration
    dur_str = _format_duration(downtime_start)

    # Explain what happened and how it was fixed
    lines.append("**What happened:**")

    if previous_status == "down":
        # Describe what was wrong
        bot_was_down = bot and not bot.get("was_running_before_fix", True)
        db_was_down = duckdb and not duckdb.get("was_healthy_before_fix", True)

        # Use fix descriptions if we have them
        fix_descriptions = _describe_fixes(fixes)

        if fix_descriptions:
            for desc in fix_descriptions:
                lines.append(desc)
        elif previous_status == "down":
            lines.append(
                "The bot experienced a service interruption and needed to be restarted."
            )
        lines.append("")
    elif previous_status == "degraded":
        lines.append(
            "Our data pipeline was having trouble processing new forecast data. "
            "The models have now completed their run and everything is fresh again."
        )
        lines.append("")

    if dur_str:
        lines.append(f"*The issue lasted {dur_str}.*")
        lines.append("")

    # What's working now
    lines.append("**Current status:**")
    lines.append("• Bot is online and responding to commands ✅")
    if pipeline and pipeline.get("status") == "ok":
        lines.append("• Data pipeline is healthy — forecasts and crowd data are up to date ✅")
    if duckdb and duckdb.get("healthy"):
        lines.append("• Database is healthy ✅")
    lines.append("")

    lines.append("Thanks for your patience — and sorry for the interruption! 🎢")

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

    # Snapshot pre-fix state so recovery messages can describe what was wrong
    pre_fix_bot = dict(bot)
    pre_fix_duckdb = dict(duckdb)

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
        # Recovered → edit existing announcement with full context
        if message_id:
            action = "edit"
            # Pull outage context from state for the recovery narrative
            outage_ctx = state.get("outage_context", {})
            message_content = format_restored_message(
                previous_status=old_status,
                downtime_start=state.get("last_status_change"),
                pipeline=pipeline,
                bot=bot,
                duckdb=duckdb,
                fixes=outage_ctx.get("fixes", fixes),
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

        # When entering a bad state, save outage context so recovery
        # messages can explain what happened and how it was fixed
        if new_status in ("degraded", "down"):
            state["outage_context"] = {
                "entered_at": now,
                "entered_status": new_status,
                "pipeline_issues": [
                    {"type": i["type"], "message": i["message"]}
                    for i in pipeline.get("issues", [])
                ],
                "bot_was_running": pre_fix_bot.get("running", True),
                "db_was_healthy": pre_fix_duckdb.get("healthy", True),
                "db_wal_corrupt": pre_fix_duckdb.get("wal_corrupt", False),
                "fixes": [
                    {"action": f["action"], "success": f.get("success", True)}
                    for f in fixes
                ] if fixes else [],
            }
        elif new_status == "operational":
            # Clear outage context on recovery (already used for message)
            state.pop("outage_context", None)

    # Accumulate fixes into outage context even on subsequent checks
    if fixes and new_status in ("degraded", "down"):
        ctx = state.get("outage_context", {})
        existing_fixes = ctx.get("fixes", [])
        existing_fixes.extend(
            {"action": f["action"], "success": f.get("success", True)}
            for f in fixes
        )
        ctx["fixes"] = existing_fixes
        state["outage_context"] = ctx

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
        "--auto",
        action="store_true",
        help="Run health check + fixes + execute Discord actions (for cron)",
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
    elif args.auto:
        result = run_check(do_fix=True)
        # Execute the Discord action directly
        success = execute_discord_action(result)
        result["auto_executed"] = success
        if not success:
            logger.error("Auto: Discord action failed")
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
