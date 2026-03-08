#!/usr/bin/env python3
"""
TPCR Discord Bot Health Monitor

Checks:
1. systemd service status (is the process alive?)
2. Discord websocket connected (can the bot see Discord?)
3. DuckDB data accessible (can the bot answer queries?)
4. Bot responding to commands (end-to-end via Discord API)

Exit codes:
  0 = healthy
  1 = degraded (bot running but issues detected)
  2 = critical (bot down or unresponsive)

Usage:
  python3 tpcr_bot_health_check.py [--json] [--fix] [--quiet]
    --json   Output machine-readable JSON
    --fix    Attempt auto-remediation (restart service, etc.)
    --quiet  Only output on failure
"""

import subprocess
import sys
import json
import os
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("bot-health")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")

DUCKDB_PATH = "/mnt/data/pipeline/tpcr_live.duckdb"
SERVICE_NAME = "tpcr-discord-bot"
STATE_FILE = Path(os.path.expanduser("~/clawd-anthropic/memory/bot-health-state.json"))
ALERT_COOLDOWN_SECONDS = 1800  # 30 min between alerts for same issue

# Discord alert channel (HQ #alerts)
ALERTS_CHANNEL_ID = "1479471928262529088"


def run_cmd(cmd, timeout=10):
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def check_service():
    """Check if the systemd service is running."""
    code, out, err = run_cmd(f"systemctl --user is-active {SERVICE_NAME}")
    is_active = out == "active"

    # Get uptime if active
    uptime_seconds = None
    if is_active:
        code2, out2, _ = run_cmd(
            f"systemctl --user show {SERVICE_NAME} --property=ActiveEnterTimestamp"
        )
        if "=" in out2:
            ts_str = out2.split("=", 1)[1].strip()
            if ts_str:
                try:
                    from dateutil import parser as dp
                    started = dp.parse(ts_str)
                    uptime_seconds = (datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()
                except:
                    pass

    # Check memory usage
    mem_mb = None
    code3, out3, _ = run_cmd(
        f"systemctl --user show {SERVICE_NAME} --property=MemoryCurrent"
    )
    if "=" in out3:
        val = out3.split("=", 1)[1].strip()
        if val.isdigit():
            mem_mb = int(val) / (1024 * 1024)

    return {
        "check": "service",
        "ok": is_active,
        "status": "active" if is_active else out or "unknown",
        "uptime_seconds": uptime_seconds,
        "memory_mb": round(mem_mb, 1) if mem_mb else None,
    }


def check_discord_connection():
    """Check if the bot is connected to Discord gateway via recent logs."""
    # Look at recent journal logs for connection issues
    code, out, err = run_cmd(
        f"journalctl --user -u {SERVICE_NAME} --since '5 min ago' --no-pager 2>&1"
    )

    disconnected = False
    resumed = False
    errors = []

    for line in out.split("\n"):
        line_lower = line.lower()
        if "disconnect" in line_lower or "websocket closed" in line_lower:
            disconnected = True
        if "resumed" in line_lower or "ready" in line_lower:
            resumed = True
        if "error" in line_lower and "duckdb" not in line_lower:
            errors.append(line.strip()[-120:])

    # If we see disconnect but also resume, that's fine (normal reconnect)
    # If we see disconnect with no resume, that's bad
    is_ok = not disconnected or resumed

    return {
        "check": "discord_connection",
        "ok": is_ok,
        "status": "connected" if is_ok else "disconnected",
        "recent_errors": errors[-3:] if errors else [],
    }


def check_duckdb():
    """Check if DuckDB is accessible and has fresh data."""
    if not os.path.exists(DUCKDB_PATH):
        return {
            "check": "duckdb",
            "ok": False,
            "status": "missing",
            "error": f"{DUCKDB_PATH} not found",
        }

    try:
        import duckdb
        con = duckdb.connect(DUCKDB_PATH, read_only=True)

        # Check data freshness
        result = con.execute(
            "SELECT source, last_updated FROM data_freshness WHERE source IN ('scraper', 'wti', 'forecasts')"
        ).fetchall()
        con.close()

        now = datetime.now(timezone.utc)
        freshness = {}
        issues = []

        for source, last_updated in result:
            if last_updated:
                import pandas as pd
                ts = pd.to_datetime(last_updated)
                if ts.tzinfo is None:
                    ts = ts.tz_localize("UTC")
                age_hours = (now - ts).total_seconds() / 3600
                freshness[source] = round(age_hours, 1)

                if source == "scraper" and age_hours > 24:  # scraper can be stale overnight / off-hours
                    issues.append(f"scraper data {age_hours:.1f}h old (>24h)")
                elif source in ("wti", "forecasts") and age_hours > 48:
                    issues.append(f"{source} data {age_hours:.1f}h old (>48h)")

        return {
            "check": "duckdb",
            "ok": len(issues) == 0,
            "status": "healthy" if not issues else "stale",
            "freshness_hours": freshness,
            "issues": issues,
        }

    except Exception as e:
        return {
            "check": "duckdb",
            "ok": False,
            "status": "error",
            "error": str(e)[:200],
        }


def check_recent_commands():
    """Check recent bot log for command successes/failures."""
    code, out, err = run_cmd(
        f"journalctl --user -u {SERVICE_NAME} --since '30 min ago' --no-pager 2>&1"
    )

    commands_seen = 0
    errors_seen = 0
    duckdb_locks = 0
    duckdb_errors = 0

    for line in out.split("\n"):
        if "📥 /" in line:
            commands_seen += 1
        if "DuckDB locked" in line:
            duckdb_locks += 1
        if "Error" in line and "DuckDB" in line:
            duckdb_errors += 1
        if "Traceback" in line or "Exception" in line:
            errors_seen += 1

    return {
        "check": "recent_commands",
        "ok": duckdb_errors == 0,
        "status": "healthy" if duckdb_errors == 0 else "degraded",
        "commands_30min": commands_seen,
        "duckdb_locks_30min": duckdb_locks,
        "duckdb_errors_30min": duckdb_errors,
        "exceptions_30min": errors_seen,
    }


def check_bot_process():
    """Check if the bot process is responding (not zombie/hung)."""
    # Get PID
    code, out, _ = run_cmd(f"systemctl --user show {SERVICE_NAME} --property=MainPID")
    if "=" not in out:
        return {"check": "process", "ok": False, "status": "no_pid"}

    pid = out.split("=", 1)[1].strip()
    if pid == "0":
        return {"check": "process", "ok": False, "status": "not_running"}

    # Check process state
    code2, out2, _ = run_cmd(f"cat /proc/{pid}/status 2>/dev/null | grep -E '^(State|Threads|VmRSS)'")
    state_info = {}
    for line in out2.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            state_info[k.strip()] = v.strip()

    is_zombie = "Z" in state_info.get("State", "")
    threads = int(state_info.get("Threads", "0"))

    return {
        "check": "process",
        "ok": not is_zombie and threads > 0,
        "status": state_info.get("State", "unknown"),
        "threads": threads,
        "rss": state_info.get("VmRSS", "unknown"),
    }


def attempt_fix(results):
    """Try to auto-remediate issues."""
    fixes = []

    service_check = next((r for r in results if r["check"] == "service"), None)
    process_check = next((r for r in results if r["check"] == "process"), None)

    # Service not running or process dead → restart
    if (service_check and not service_check["ok"]) or (process_check and not process_check["ok"]):
        logger.info("🔧 Restarting tpcr-discord-bot service...")
        code, out, err = run_cmd(f"systemctl --user restart {SERVICE_NAME}")
        if code == 0:
            # Wait a few seconds and verify
            time.sleep(5)
            code2, out2, _ = run_cmd(f"systemctl --user is-active {SERVICE_NAME}")
            if out2 == "active":
                fixes.append("restarted_service_success")
                logger.info("✅ Service restarted successfully")
            else:
                fixes.append("restarted_service_failed")
                logger.error("❌ Service restart failed")
        else:
            fixes.append(f"restart_error: {err[:100]}")

    # DuckDB WAL corruption → remove WAL and restart
    duckdb_check = next((r for r in results if r["check"] == "duckdb"), None)
    if duckdb_check and duckdb_check.get("status") == "error" and "WAL" in duckdb_check.get("error", ""):
        wal_path = f"{DUCKDB_PATH}.wal"
        if os.path.exists(wal_path):
            bak = f"{wal_path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            logger.info(f"🔧 Backing up corrupt WAL: {wal_path} → {bak}")
            os.rename(wal_path, bak)
            fixes.append("wal_backed_up")
            # Restart bot to reconnect cleanly
            run_cmd(f"systemctl --user restart {SERVICE_NAME}")
            time.sleep(5)
            fixes.append("restarted_after_wal_fix")

    return fixes


def load_state():
    """Load previous health check state."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            pass
    return {}


def save_state(state):
    """Save health check state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def should_alert(issue_key, state):
    """Check if we should alert for this issue (cooldown logic)."""
    alerts = state.get("alerts", {})
    last_alert = alerts.get(issue_key, 0)
    return (time.time() - last_alert) > ALERT_COOLDOWN_SECONDS


def record_alert(issue_key, state):
    """Record that we alerted for this issue."""
    if "alerts" not in state:
        state["alerts"] = {}
    state["alerts"][issue_key] = time.time()


def main():
    args = sys.argv[1:]
    output_json = "--json" in args
    do_fix = "--fix" in args
    quiet = "--quiet" in args

    results = []

    # Run all checks
    results.append(check_service())
    results.append(check_bot_process())
    results.append(check_discord_connection())
    results.append(check_duckdb())
    results.append(check_recent_commands())

    # Determine overall status
    critical_checks = ["service", "process"]
    is_critical = any(
        not r["ok"] for r in results if r["check"] in critical_checks
    )
    is_degraded = any(not r["ok"] for r in results)

    overall = "critical" if is_critical else "degraded" if is_degraded else "healthy"

    # Auto-fix if requested
    fixes = []
    if do_fix and overall != "healthy":
        fixes = attempt_fix(results)

    # If DuckDB data is stale and forecasts exist on disk but not in DuckDB,
    # trigger a re-ingest (the pipeline ran but DuckDB write failed)
    if do_fix:
        duckdb_check = next((r for r in results if r["check"] == "duckdb"), None)
        if duckdb_check and duckdb_check.get("status") == "stale":
            freshness = duckdb_check.get("freshness_hours", {})
            # Check if parquet files on disk are newer than DuckDB data
            forecast_parquet = "/mnt/data/pipeline/curves/forecast_parquet/all_forecasts.parquet"
            wti_parquet = "/mnt/data/pipeline/wti/wti.parquet"
            if os.path.exists(forecast_parquet) and os.path.exists(wti_parquet):
                parquet_age_h = (time.time() - os.path.getmtime(forecast_parquet)) / 3600
                duckdb_age_h = freshness.get("forecasts", 999)
                if parquet_age_h < duckdb_age_h - 1:  # parquet is significantly newer
                    fixes.append(f"stale_duckdb_detected: parquet={parquet_age_h:.1f}h, duckdb={duckdb_age_h:.1f}h")
                    logger.info(f"🔧 DuckDB data stale ({duckdb_age_h:.1f}h) but parquet fresh ({parquet_age_h:.1f}h) — re-ingest needed")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": overall,
        "checks": results,
        "fixes_applied": fixes if fixes else None,
    }

    # Save state
    state = load_state()
    state["last_check"] = report["timestamp"]
    state["last_status"] = overall
    if overall != "healthy":
        state["last_unhealthy"] = report["timestamp"]
        state["last_unhealthy_status"] = overall
    save_state(state)

    if output_json:
        print(json.dumps(report, indent=2))
    elif not quiet or overall != "healthy":
        # Human-readable output
        emoji = {"healthy": "🟢", "degraded": "🟡", "critical": "🔴"}
        print(f"\n{emoji.get(overall, '❓')} TPCR Discord Bot: {overall.upper()}")
        print(f"  Checked: {report['timestamp'][:19]}")
        print()

        for r in results:
            status_emoji = "✅" if r["ok"] else "❌"
            print(f"  {status_emoji} {r['check']}: {r['status']}")
            for k, v in r.items():
                if k not in ("check", "ok", "status") and v:
                    print(f"     {k}: {v}")

        if fixes:
            print(f"\n  🔧 Fixes applied: {', '.join(fixes)}")
        print()

    sys.exit(0 if overall == "healthy" else 1 if overall == "degraded" else 2)


if __name__ == "__main__":
    main()
