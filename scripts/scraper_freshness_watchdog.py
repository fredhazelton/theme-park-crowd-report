#!/usr/bin/env python3
"""Scraper freshness watchdog — TPCR #466.

Reads `tpcr_live.duckdb` `data_freshness` table and alerts `#wti-pipeline`
when the scraper's last_updated drifts past the freshness threshold.

Designed to be run from cron every 10 minutes, independent of the scraper
process — a scraper crash cannot take its own watchdog down.

State transitions:
  fresh -> stale        : 🚨 alert posted
  stale -> very_stale   : 🚨🚨🚨 escalation (after ESCALATE_AFTER consecutive
                          stale checks), @-mentions TPCR_ALERT_USER_ID if set
  stale -> fresh        : ✅ recovery
  very_stale -> fresh   : ✅ recovery

State persists at STATE_FILE to suppress duplicate alerts — only state
transitions post to Discord.

Usage:
  python3 scripts/scraper_freshness_watchdog.py
  python3 scripts/scraper_freshness_watchdog.py --dry-run
  python3 scripts/scraper_freshness_watchdog.py --simulate-stale 20   # Rule 17 proof only

See TPCR #466.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Config ──────────────────────────────────────────────────────────────
STATE_FILE = Path("/mnt/data/pipeline/state/scraper_watchdog_state.json")
DUCKDB_PATH = "/mnt/data/pipeline/tpcr_live.duckdb"
INTERNAL_CHANNEL = "1479351574177513576"  # #wti-pipeline
# Failsafe: every alert we try to post is also appended to this file. If the
# Discord path is down (bot identity issue, 403, network), the log file is
# the durable record. State advances regardless of post success so we never
# get stuck in a "should-have-alerted-but-couldn't" loop.
ALERT_LOG_FILE = Path("/home/wilma/hazeydata/pipeline/logs/scraper_watchdog_alerts.log")

# Freshness thresholds (minutes) — ops hours vs off hours.
# Ops hours cover all global parks: 06:00-02:00 ET (includes Tokyo evenings
# overlapping ET late night).
FRESH_THRESHOLD_MINS_OPS = 15
FRESH_THRESHOLD_MINS_OFFHOURS = 60
OPS_START_HOUR_ET = 6   # inclusive (06:00 ET onward)
OPS_END_HOUR_ET = 2     # exclusive (02:00 ET → off until 06:00)

# Debounce — how many consecutive stale checks before escalating
ESCALATE_AFTER_CONSECUTIVE_STALE = 3

# Optional Discord user ID to @-mention on escalation. Set via env var.
ALERT_USER_ID_ENV = "TPCR_ALERT_USER_ID"

DEFAULT_STATE = {
    "current_state": "fresh",          # 'fresh' | 'stale' | 'very_stale'
    "consecutive_stale": 0,
    "last_check_ts": None,
    "last_alert_ts": None,
    "incident_start": None,
}


# ── Freshness calculation ───────────────────────────────────────────────
def in_ops_hours() -> bool:
    """Scraper ops hours = 06:00-02:00 ET. True in ops, False off-hours."""
    hour_et = datetime.now(ZoneInfo("America/Toronto")).hour
    # Hours 6-23 and 0-1 are ops. Hours 2-5 are off.
    return hour_et >= OPS_START_HOUR_ET or hour_et < OPS_END_HOUR_ET


def threshold_minutes() -> int:
    return FRESH_THRESHOLD_MINS_OPS if in_ops_hours() else FRESH_THRESHOLD_MINS_OFFHOURS


def get_scraper_age_minutes(simulate_stale_mins: int = 0) -> tuple[float | None, str]:
    """Return (age_minutes, status).

    status values:
        ok       — query succeeded; age is valid.
        lock     — DuckDB lock conflict (scraper is writing). The DB is ALIVE.
                   Caller should skip this tick without progressing state.
        missing  — connect OK but no scraper row found in data_freshness.
                   Treat as stale (data is unambiguously not being written).
        error    — unknown failure. Skip without progressing state.
    """
    try:
        import duckdb
    except ImportError:
        print("[ERROR] duckdb module not available", file=sys.stderr)
        return None, "error"

    last_err: Exception | None = None
    # Short retry loop — scraper lock windows are sub-second; retry bridges those.
    for attempt in range(3):
        try:
            con = duckdb.connect(DUCKDB_PATH, read_only=True)
            try:
                r = con.execute(
                    "SELECT last_updated FROM data_freshness WHERE source='scraper'"
                ).fetchone()
            finally:
                con.close()
            if not r or r[0] is None:
                return None, "missing"
            last = r[0]
            if simulate_stale_mins > 0:
                last = last - timedelta(minutes=simulate_stale_mins)
            age = (datetime.now(timezone.utc) - last.astimezone(timezone.utc)).total_seconds() / 60
            return max(0.0, age), "ok"
        except Exception as e:
            last_err = e
            err = str(e).lower()
            if "lock" in err or "conflicting" in err or "busy" in err:
                # Scraper is actively writing. Back off briefly.
                import time as _t
                _t.sleep(1.5)
                continue
            # Non-lock error — bail immediately, don't burn retries.
            break

    err_str = str(last_err).lower() if last_err else ""
    if "lock" in err_str or "conflicting" in err_str or "busy" in err_str:
        print(f"[WARN] scraper holds DB lock after 3 retries — DB is alive; skipping tick", file=sys.stderr)
        return None, "lock"
    print(f"[WARN] freshness read failed: {last_err}", file=sys.stderr)
    return None, "error"


# ── State ───────────────────────────────────────────────────────────────
def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return dict(DEFAULT_STATE)


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def log_alert_failsafe(content: str) -> None:
    """Append alert to failsafe log file — durable record even when Discord is down."""
    try:
        ALERT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with ALERT_LOG_FILE.open("a") as f:
            ts = datetime.now(timezone.utc).isoformat()
            f.write(f"[{ts}]\n{content}\n\n")
    except Exception as e:
        print(f"[WARN] alert log write failed: {e}", file=sys.stderr)


# ── Discord posting ─────────────────────────────────────────────────────
def _discord_token() -> str:
    t = os.environ.get("DISCORD_BOT_TOKEN", "")
    if t:
        return t
    env_path = Path.home() / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("DISCORD_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def discord_post(channel: str, content: str) -> bool:
    token = _discord_token()
    if not token:
        print("[WARN] DISCORD_BOT_TOKEN not found; message not sent", file=sys.stderr)
        return False
    url = f"https://discord.com/api/v10/channels/{channel}/messages"
    req = urllib.request.Request(
        url,
        data=json.dumps({"content": content}).encode("utf-8"),
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status in (200, 201):
                try:
                    body = json.loads(r.read().decode("utf-8"))
                    msg_id = body.get("id", "?")
                    print(f"[watchdog] posted message_id={msg_id} channel={channel}")
                except Exception:
                    pass
                return True
            return False
    except Exception as e:
        print(f"[WARN] discord post failed: {e}", file=sys.stderr)
        return False


def format_stale_alert(age_mins: float, threshold: int, is_escalation: bool) -> str:
    uid = os.environ.get(ALERT_USER_ID_ENV, "").strip()
    mention = f"<@{uid}> " if (is_escalation and uid) else ""
    if is_escalation:
        header = "🚨🚨🚨 **Scraper ESCALATION — ~30 min dark**"
    else:
        header = "🚨 **Scraper stale**"
    age_str = f"{age_mins:.1f} min" if age_mins != float("inf") else "unknown"
    return (
        f"{mention}{header}\n"
        f"Age: {age_str} · threshold: {threshold} min · "
        f"{'ops' if in_ops_hours() else 'off'}-hours\n"
        f"Ref: TPCR #466"
    )


def format_recovery(incident_start_iso: str | None) -> str:
    duration = ""
    if incident_start_iso:
        try:
            start = datetime.fromisoformat(incident_start_iso)
            mins = int((datetime.now(timezone.utc) - start).total_seconds() // 60)
            duration = (
                f" (incident lasted {mins}m)"
                if mins < 60
                else f" (incident lasted {mins // 60}h {mins % 60}m)"
            )
        except Exception:
            pass
    return (
        f"✅ **Scraper recovered**{duration} — fresh data flowing again.\n"
        f"Ref: TPCR #466"
    )


# ── Main logic ──────────────────────────────────────────────────────────
def run(dry_run: bool, simulate_stale_mins: int, state_file: Path, no_post: bool = False) -> int:
    now = datetime.now(timezone.utc)
    age, read_status = get_scraper_age_minutes(simulate_stale_mins=simulate_stale_mins)
    threshold = threshold_minutes()

    # If we couldn't read (lock or transient error), don't progress state.
    # Lock means scraper IS writing = DB alive. Error means unknown; skip to avoid
    # false alerts on flaky reads.
    if read_status in ("lock", "error"):
        state = load_state(state_file)
        print(
            f"[watchdog] read_status={read_status} state={state['current_state']} "
            f"consec_stale={state.get('consecutive_stale', 0)} "
            f"post=no (skipped — read failed) dry_run={dry_run}"
        )
        if not dry_run:
            state["last_check_ts"] = now.isoformat()
            save_state(state_file, state)
        return 0

    if read_status == "missing":
        # Connect OK but no scraper heartbeat row. Treat as stale.
        raw_new_state = "stale"
        age_for_alert: float = float("inf")
    else:
        # read_status == "ok"
        age_for_alert = age if age is not None else 0.0
        raw_new_state = "fresh" if (age is not None and age <= threshold) else "stale"

    state = load_state(state_file)
    prev_state = state["current_state"]

    # Update consecutive-stale counter
    if raw_new_state == "stale":
        state["consecutive_stale"] = state.get("consecutive_stale", 0) + 1
    else:
        state["consecutive_stale"] = 0

    # Decide final state (stale may upgrade to very_stale on escalation)
    is_staleness_new = raw_new_state == "stale" and prev_state == "fresh"
    escalate_now = (
        raw_new_state == "stale"
        and state["consecutive_stale"] >= ESCALATE_AFTER_CONSECUTIVE_STALE
        and prev_state != "very_stale"
    )
    if escalate_now:
        new_state = "very_stale"
    elif raw_new_state == "stale":
        # Stay stale if already stale; upgrade to stale if previously fresh
        new_state = "very_stale" if prev_state == "very_stale" else "stale"
    else:
        new_state = "fresh"
    is_recovery = new_state == "fresh" and prev_state in ("stale", "very_stale")

    # Compose alert (only on state change)
    alert: str | None = None
    if is_staleness_new:
        alert = format_stale_alert(age_for_alert, threshold, is_escalation=False)
    elif escalate_now:
        alert = format_stale_alert(age_for_alert, threshold, is_escalation=True)
    elif is_recovery:
        alert = format_recovery(state.get("incident_start"))

    print(
        f"[watchdog] age={age_for_alert if age is not None else 'None'} "
        f"threshold={threshold} state:{prev_state}->{new_state} "
        f"consec_stale={state['consecutive_stale']} "
        f"post={'yes' if alert else 'no'} dry_run={dry_run} "
        f"simulate_stale={simulate_stale_mins}"
    )

    # Delivery model: Discord is best-effort, failsafe log is durable.
    # Every alert is written to ALERT_LOG_FILE regardless of Discord success,
    # and state advances either way so the watchdog never gets stuck in a
    # "couldn't post → didn't advance → permanently wrong state" loop.
    if alert:
        if dry_run or no_post:
            tag = "DRY-RUN" if dry_run else "NO-POST"
            print(f"[{tag}] would post to {INTERNAL_CHANNEL} and log to {ALERT_LOG_FILE}")
            print(alert)
        else:
            # Write to durable log first — if Discord 403s, the record survives.
            log_alert_failsafe(alert)
            post_ok = discord_post(INTERNAL_CHANNEL, alert)
            if post_ok:
                state["last_alert_ts"] = now.isoformat()
                if is_staleness_new and not state.get("incident_start"):
                    state["incident_start"] = now.isoformat()
                if is_recovery:
                    state["incident_start"] = None
            else:
                print(
                    f"[watchdog] Discord post failed — alert recorded in {ALERT_LOG_FILE}; "
                    f"state still advancing",
                    file=sys.stderr,
                )
                # Still track incident timing off the log entry so recovery posts
                # (if/when Discord auth is restored) show accurate duration.
                if is_staleness_new and not state.get("incident_start"):
                    state["incident_start"] = now.isoformat()
                if is_recovery:
                    state["incident_start"] = None

    state["current_state"] = new_state
    state["last_check_ts"] = now.isoformat()
    if not dry_run:
        save_state(state_file, state)
    return 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Print would-post messages; do not send or save state")
    p.add_argument(
        "--simulate-stale",
        type=int,
        default=0,
        metavar="N",
        help="Force the freshness check to see last_updated - N minutes. For Rule 17 proof only.",
    )
    p.add_argument(
        "--state-file",
        type=Path,
        default=STATE_FILE,
        help=f"Path to state JSON (default: {STATE_FILE}). Override for Rule 17 proof runs.",
    )
    p.add_argument(
        "--no-post",
        action="store_true",
        help="Advance state and save but skip the Discord post. Useful for offline testing.",
    )
    args = p.parse_args()
    sys.exit(run(
        dry_run=args.dry_run,
        simulate_stale_mins=args.simulate_stale,
        state_file=args.state_file,
        no_post=args.no_post,
    ))


if __name__ == "__main__":
    main()
