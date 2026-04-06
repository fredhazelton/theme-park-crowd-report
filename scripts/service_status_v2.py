#!/usr/bin/env python3
"""Service Status Monitor V2 — observe, debounce, announce."""

import argparse, json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path("/mnt/data/pipeline/state/service_status_state.json")
DUCKDB_PATH = "/mnt/data/pipeline/tpcr_live.duckdb"
ANNOUNCEMENTS_CHANNEL = "1471935589371609162"
INTERNAL_CHANNEL = "1479351574177513576"
DEBOUNCE_THRESHOLD = 3
RATE_LIMIT_SECONDS = 6 * 3600
DEFAULT_STATE = {
    "current_status": "operational",
    "consecutive_non_operational": 0,
    "consecutive_status": None,
    "debounce_threshold": DEBOUNCE_THRESHOLD,
    "last_announcement_time": None,
    "announcement_message_id": None,
    "incident_start": None,
    "last_check": None,
}

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return dict(DEFAULT_STATE)

def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def check_pipeline() -> str:
    try:
        r = subprocess.run(
            [sys.executable, "scripts/pipeline_alert_check.py", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(r.stdout)
        status = data.get("status", "error")
    except Exception:
        status = "error"
    # Outside the pipeline run window (6-10 AM ET), errors are expected — no pipeline scheduled
    if status in ("error", "critical"):
        try:
            from zoneinfo import ZoneInfo
            hour_et = datetime.now(ZoneInfo("America/Toronto")).hour
            if hour_et < 6 or hour_et >= 10:
                return "ok"  # Not scheduled — silence is golden
        except Exception:
            pass
    return status

def check_bot() -> str:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", "tpcr-discord-bot"],
            capture_output=True, text=True, timeout=10,
        )
        return "running" if r.stdout.strip() == "active" else "stopped"
    except Exception:
        return "stopped"

def check_duckdb() -> str:
    try:
        import duckdb
        con = duckdb.connect(DUCKDB_PATH, read_only=True)
        con.execute("SELECT count(*) FROM information_schema.tables")
        con.close()
        return "healthy"
    except Exception as e:
        err = str(e).lower()
        # A lock conflict means the scraper is actively writing — database is alive
        if "lock" in err or "conflicting" in err or "busy" in err:
            return "healthy"
        return "unhealthy"

def determine_status(pipeline: str, bot: str, duckdb: str) -> str:
    if bot != "running" or duckdb != "healthy":
        return "down"
    if pipeline == "critical":
        return "degraded"
    return "operational"

def _discord_headers() -> dict:
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    return {"Authorization": f"Bot {token}", "Content-Type": "application/json"}

def discord_post(channel: str, content: str) -> dict:
    import requests
    url = f"https://discord.com/api/v10/channels/{channel}/messages"
    r = requests.post(url, headers=_discord_headers(), json={"content": content}, timeout=15)
    r.raise_for_status()
    return r.json()

def discord_edit(channel: str, message_id: str, content: str) -> dict:
    import requests
    url = f"https://discord.com/api/v10/channels/{channel}/messages/{message_id}"
    r = requests.patch(url, headers=_discord_headers(), json={"content": content}, timeout=15)
    if r.status_code == 404:
        return {"deleted": True}
    r.raise_for_status()
    return r.json()

def format_issue_message(status: str, checks: dict, incident_start: str) -> str:
    parts = []
    if checks.get("pipeline") in ("critical", "error"):
        parts.append("pipeline")
    if checks.get("duckdb") == "unhealthy":
        parts.append("database")
    if checks.get("bot") == "stopped":
        parts.append("service")
    component = "/".join(parts) if parts else "service"
    if status == "down":
        return (
            f"\U0001f534 **Service Interruption**\n\n"
            f"Our wait time service is currently unavailable. "
            f"We're working on restoring it.\n\n"
            f"*Started: {incident_start}*"
        )
    return (
        f"\u26a0\ufe0f **Service Notice**\n\n"
        f"Our wait time bot is experiencing issues with {component}. "
        f"We're looking into it.\n\n"
        f"*Started: {incident_start}*"
    )

def format_restored_message(incident_start: str) -> str:
    try:
        start = datetime.fromisoformat(incident_start)
        dur = datetime.now(timezone.utc) - start
        mins = int(dur.total_seconds() // 60)
        duration = f"{mins}m" if mins < 60 else f"{mins // 60}h {mins % 60}m"
    except Exception:
        duration = "unknown"
    return (
        f"\u2705 **Service Restored**\n\n"
        f"Everything is back to normal. Your wait time data and commands are working.\n\n"
        f"*Issue lasted: {duration}*"
    )

def run_check() -> dict:
    checks = {
        "pipeline": check_pipeline(),
        "bot": check_bot(),
        "duckdb": check_duckdb(),
    }
    checks["status"] = determine_status(checks["pipeline"], checks["bot"], checks["duckdb"])
    checks["timestamp"] = datetime.now(timezone.utc).isoformat()
    return checks

def run_announce(dry_run: bool = False):
    checks = run_check()
    status = checks["status"]
    state = load_state()
    now = datetime.now(timezone.utc)
    state["last_check"] = now.isoformat()
    prev_status = state["current_status"]

    # Debounce logic
    if status == "operational":
        state["consecutive_non_operational"] = 0
        state["consecutive_status"] = None
    else:
        if state["consecutive_status"] == status:
            state["consecutive_non_operational"] += 1
        else:
            state["consecutive_non_operational"] = 1
            state["consecutive_status"] = status
    debounced = state["consecutive_non_operational"] >= DEBOUNCE_THRESHOLD

    # Internal alert — only on status CHANGE (silence is golden, Amendment 004)
    internal_msg = (
        f"[status-check] {status} | pipeline={checks['pipeline']} "
        f"bot={checks['bot']} duckdb={checks['duckdb']} "
        f"consec={state['consecutive_non_operational']}"
    )
    status_changed = status != prev_status
    if dry_run:
        if status_changed:
            print(f"[DRY-RUN] Internal (status change): {internal_msg}")
        else:
            print(f"[DRY-RUN] No change: {internal_msg}")
    elif status_changed:
        try:
            discord_post(INTERNAL_CHANNEL, internal_msg)
        except Exception as e:
            print(f"[WARN] Internal post failed: {e}", file=sys.stderr)

    # Customer announcement logic
    action = None
    if status == "operational" and prev_status != "operational":
        if state.get("announcement_message_id") and state.get("incident_start"):
            msg = format_restored_message(state["incident_start"])
            action = ("edit", msg)
            state["current_status"] = "operational"
            state["incident_start"] = None
    elif status != "operational" and debounced:
        if prev_status == "operational":
            last_ann = state.get("last_announcement_time")
            rate_ok = True
            if last_ann:
                elapsed = (now - datetime.fromisoformat(last_ann)).total_seconds()
                rate_ok = elapsed >= RATE_LIMIT_SECONDS
            if rate_ok:
                incident_start = now.isoformat()
                state["incident_start"] = incident_start
                msg = format_issue_message(status, checks, incident_start)
                action = ("post", msg)
                state["current_status"] = status
        elif prev_status != status:
            if state.get("announcement_message_id") and state.get("incident_start"):
                msg = format_issue_message(status, checks, state["incident_start"])
                action = ("edit", msg)
                state["current_status"] = status

    # Execute announcement
    if action:
        verb, content = action
        if dry_run:
            print(f"[DRY-RUN] Would {verb} customer announcement:\n{content}")
        else:
            try:
                if verb == "edit" and state.get("announcement_message_id"):
                    resp = discord_edit(ANNOUNCEMENTS_CHANNEL, state["announcement_message_id"], content)
                    if resp.get("deleted"):
                        resp = discord_post(ANNOUNCEMENTS_CHANNEL, content)
                        state["announcement_message_id"] = resp["id"]
                        state["last_announcement_time"] = now.isoformat()
                elif verb == "post":
                    resp = discord_post(ANNOUNCEMENTS_CHANNEL, content)
                    state["announcement_message_id"] = resp["id"]
                    state["last_announcement_time"] = now.isoformat()
            except Exception as e:
                print(f"[ERROR] Customer announcement failed: {e}", file=sys.stderr)

    if not dry_run:
        save_state(state)
    else:
        print(f"\n[DRY-RUN] State would be: {json.dumps(state, indent=2)}")
    print(json.dumps(checks, indent=2))

def run_status():
    state = load_state()
    print(json.dumps(state, indent=2))

def main():
    parser = argparse.ArgumentParser(description="Service Status Monitor V2")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Run health checks, print JSON")
    group.add_argument("--announce", action="store_true", help="Run checks + debounce + announce")
    group.add_argument("--status", action="store_true", help="Print current state")
    group.add_argument("--dry-run", action="store_true", help="Like --announce but no side effects")
    args = parser.parse_args()
    if args.check:
        print(json.dumps(run_check(), indent=2))
    elif args.announce:
        run_announce(dry_run=False)
    elif args.dry_run:
        run_announce(dry_run=True)
    elif args.status:
        run_status()

if __name__ == "__main__":
    main()
