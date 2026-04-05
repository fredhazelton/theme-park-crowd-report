# V4 Amendment 004: Service Status Manager Redesign

**Version:** 1.0
**Date:** 2026-04-05
**Authors:** Barney (architect) + Fred (decision-maker)
**Status:** PROPOSED — Awaiting Fred's approval
**Based on:** Session 28 service status spam incident (65 false "Service Restored" messages in 15 hours)

---

## Problem Statement

The current `service_status_manager.py` (43KB) was designed to monitor TPCR service health and post customer-facing announcements to the TPCR Discord `#announcements` channel. On April 4-5, 2026, it malfunctioned catastrophically:

- **65 identical "Service Restored" messages** posted to the customer announcements channel in 15 hours
- Messages fired every 6-15 minutes, all saying "We cleared a corrupted database write log"
- A customer complained in `#feedback`: "Can there be a limit on how many alerts for system performance are sent out?"
- The actual service was running fine the entire time — 13/13 pipeline, bot operational, data fresh

### Root Cause (Three Bugs)

1. **WAL files treated as corruption.** DuckDB creates write-ahead log (WAL) files during normal write operations. The scraper writes continuously, so a WAL file is almost always present. The script treated any WAL file as "corruption," moved it to `.bak`, then declared the issue "fixed" — disrupting in-progress scraper transactions in the process.

2. **New messages instead of edits.** The `pending_cleanup` logic cleared `announcement_message_id` after 6 hours, so subsequent cycles couldn't find the old message to edit. Each recovery posted a brand new message.

3. **No debounce or rate limiting.** Every status transition (even a 2-minute blip) immediately fired a customer-facing announcement. No cooldown, no confirmation period.

### Additional Risk: tpcr_bot_health_check.py

A second script (`tpcr_bot_health_check.py`, 14KB) contains identical WAL backup logic in its `attempt_fix()` function. This script also needs to be fixed to prevent the same pattern.

---

## Design Philosophy

**Silence is golden.** A monitoring system that cries wolf is worse than no monitoring at all. Customers should only see announcements for genuine, sustained outages — not transient blips, not normal database operations, not auto-fix cycles.

**Observe, don't intervene.** The status manager should NEVER modify the system it's monitoring. No moving WAL files, no restarting services, no "auto-fixing." If something needs fixing, alert a human or an agent. The monitor is a thermometer, not a thermostat.

**One message per incident.** An incident gets one announcement. Status changes edit that message in place. Customers never see a wall of notifications.

---

## What We Keep

The existing script has good bones in several areas:

| Component | Verdict | Notes |
|-----------|---------|-------|
| Health check structure (pipeline, bot, duckdb) | **KEEP** | Three-check model is sound |
| `pipeline_alert_check.py` integration | **KEEP** | Delegates pipeline checks correctly |
| Bot service check via systemctl | **KEEP** | Simple, reliable |
| DuckDB read-only query test | **KEEP** | Tests actual data accessibility |
| Status levels (operational/degraded/down) | **KEEP** | Clear three-tier model |
| Message formatting (friendly tone) | **KEEP** | Fred's "be transparent" directive |
| State file for tracking status changes | **KEEP** | Needed for debounce and edit-in-place |
| Discord REST API posting | **KEEP** | Direct API is more reliable than bot commands |
| `--check` mode (JSON output, no side effects) | **KEEP** | Useful for Gazoo audits |
| `--status` mode (read state file) | **KEEP** | Quick status queries |

## What We Remove

| Component | Verdict | Why |
|-----------|---------|-----|
| WAL file detection as corruption | **REMOVE** | WAL files are normal DuckDB behavior |
| Auto-fix: WAL backup/move | **REMOVE** | Destructive — corrupts in-progress transactions |
| Auto-fix: bot restart | **MOVE** | Belongs in a separate remediation script, not the monitor |
| `--fix` mode | **REMOVE** | Monitor should never modify the system |
| `--auto` mode (check + fix + post) | **REPLACE** | New `--announce` mode: check + post (no fix) |
| `pending_cleanup` / auto-delete | **REMOVE** | Creates the announcement_message_id clearing bug. Old messages stay; edit-in-place handles updates. |

## What We Add

| Component | Description |
|-----------|-------------|
| **Debounce** | Don't announce degradation until 3 consecutive failed checks (≥15 min at 5-min interval) |
| **Rate limit** | Maximum one new announcement per 6 hours. Status changes within an incident edit the existing message. |
| **Edit-in-place** | One Discord message per incident. All status transitions edit that message. Never post a new message while one exists. |
| **Incident lifecycle** | Clear open → degraded/down → resolved flow. `announcement_message_id` is NEVER cleared until the incident is manually archived or 7 days pass. |
| **WAL awareness** | DuckDB check passes if the read-only query succeeds, regardless of WAL file presence. WAL existence is logged as informational, not flagged. |
| **Internal-only alerting** | Post to internal `#wti-pipeline` for operational awareness. Customer `#announcements` only for confirmed sustained issues. |
| **Dry-run mode** | `--dry-run`: run all checks, compute what WOULD be posted, but don't actually post. For testing. |

---

## New Architecture

### Script: `scripts/service_status_v2.py`

New file. The old `service_status_manager.py` stays in place (disabled) as reference until V2 is proven.

### CLI Modes

```
service_status_v2.py --check          # Health check → JSON to stdout (no side effects)
service_status_v2.py --announce       # Health check → debounce → post/edit Discord if warranted
service_status_v2.py --status         # Read current state from state file
service_status_v2.py --dry-run        # Like --announce but prints what WOULD happen without posting
```

### Health Checks (unchanged logic, new WAL handling)

```
1. Pipeline: call pipeline_alert_check.py --json → ok/warning/critical
2. Bot: systemctl --user is-active tpcr-discord-bot → running/stopped
3. DuckDB: SELECT count(*) FROM information_schema.tables (read-only) → healthy/unhealthy
   - WAL file presence: LOGGED but NOT treated as failure
   - Only actual query failure = unhealthy
```

### Status Determination (unchanged)

```
operational = bot running AND duckdb healthy AND pipeline ok/warning
degraded    = bot running AND duckdb healthy AND pipeline critical
down        = bot NOT running OR duckdb unhealthy
```

### Debounce Logic

```python
# State tracks consecutive check results
state = {
    "current_status": "operational",
    "consecutive_non_operational": 0,     # Count of consecutive checks that aren't operational
    "consecutive_status": null,           # What non-operational status we're seeing
    "debounce_threshold": 3,             # Must see N consecutive failures before announcing
    "last_announcement_time": null,       # When we last posted/edited
    "announcement_message_id": null,      # The ONE message for the current incident
    "incident_start": null,               # When the current incident began
}

# On each check:
if new_status == "operational":
    state.consecutive_non_operational = 0
    state.consecutive_status = null
    if state.current_status != "operational":
        # RECOVERY — edit existing announcement to show resolved
        edit_announcement(format_restored_message(...))
        state.current_status = "operational"
else:
    if new_status == state.consecutive_status:
        state.consecutive_non_operational += 1
    else:
        # Different non-operational status — reset counter
        state.consecutive_non_operational = 1
        state.consecutive_status = new_status
    
    if state.consecutive_non_operational >= state.debounce_threshold:
        # Confirmed sustained issue — announce or update
        if state.current_status == "operational":
            # NEW INCIDENT — post announcement
            post_announcement(format_issue_message(...))
            state.incident_start = now
        elif state.current_status != new_status:
            # STATUS CHANGED within incident — edit announcement
            edit_announcement(format_issue_message(...))
        # else: same status, already announced — do nothing
        state.current_status = new_status
```

### Rate Limiting

```python
MIN_ANNOUNCEMENT_INTERVAL = 6 * 3600  # 6 hours between new announcements

def can_post_new_announcement():
    if not state.last_announcement_time:
        return True
    elapsed = now - state.last_announcement_time
    return elapsed > MIN_ANNOUNCEMENT_INTERVAL
```

The rate limit applies only to NEW announcements (new incidents). Edits to an existing message (status changes within an incident, recovery messages) are always allowed — they update in place, not spam.

### Edit-in-Place (One Message Per Incident)

```python
def post_announcement(content):
    """Post a new announcement. Only called for new incidents."""
    if not can_post_new_announcement():
        log.warning(f"Rate limited — last announcement was {elapsed}s ago")
        return
    resp = discord_post(ANNOUNCEMENTS_CHANNEL, content)
    state.announcement_message_id = resp["id"]
    state.last_announcement_time = now

def edit_announcement(content):
    """Edit the existing announcement. Called for status changes and recovery."""
    if not state.announcement_message_id:
        # No message to edit — post new one
        post_announcement(content)
        return
    resp = discord_edit(ANNOUNCEMENTS_CHANNEL, state.announcement_message_id, content)
    if resp is None:
        # Message was deleted externally — post new one
        post_announcement(content)
```

### Message Formats (keep existing tone)

Same friendly, transparent messages as the current script. The key change: recovery messages always EDIT the incident message, so customers see the original issue message transform into a "resolved" message rather than getting a new notification.

### Internal Alerting

Every check result (pass or fail) gets logged locally. Failures also post to internal `#wti-pipeline` for operational awareness — but only once per incident (same debounce applies).

### Cron Schedule

```
# Run every 5 minutes on wilma-server
*/5 * * * * /home/wilma/theme-park-crowd-report/.venv/bin/python /home/wilma/theme-park-crowd-report/scripts/service_status_v2.py --announce >> /mnt/data/pipeline/logs/service_status.log 2>&1
```

At 5-minute intervals with a debounce threshold of 3, the minimum time before a customer sees an announcement is **15 minutes** of sustained failure. This filters out transient blips while still alerting quickly for real outages.

---

## Also Fix: tpcr_bot_health_check.py

The `attempt_fix()` function in `tpcr_bot_health_check.py` has the same WAL backup bug. Changes needed:

1. **Remove WAL backup logic** from `attempt_fix()` — the "if WAL exists, move it" block
2. **Keep** the bot restart logic (this script is explicitly a remediation tool, not just a monitor)
3. **Add** a comment: "WAL files are normal DuckDB behavior — do not move or delete them"

This is a small surgical edit to an existing file, not a rewrite.

---

## Implementation Plan

### Phase 1: Write service_status_v2.py (Dino)

New file at `scripts/service_status_v2.py`. Approximately 200-250 lines (vs the current 43KB monster). The old file stays as `service_status_manager.py` (disabled) for reference.

Key simplifications vs. the current script:
- No auto-fix logic (removes ~100 lines)
- No cleanup logic (removes ~80 lines)
- No `--fix` mode
- Debounce + rate limit adds ~50 lines
- Net: much smaller, much simpler

### Phase 2: Fix tpcr_bot_health_check.py (Dino)

Surgical edit: remove WAL backup logic from `attempt_fix()`, add comment.

### Phase 3: Proof-batch (Rule 17)

Before enabling the cron:

1. Run `--dry-run` 5 times manually at 5-minute intervals with all services healthy → should report "nothing to announce" every time
2. Temporarily stop the bot (`systemctl --user stop tpcr-discord-bot`), run `--dry-run` 3 times at 5-minute intervals → should NOT announce on checks 1-2, SHOULD report "would announce" on check 3 (debounce)
3. Restart the bot, run `--dry-run` once → should report "would edit announcement to show resolved"
4. Verify no actual messages were posted during the dry-run tests

### Phase 4: Enable cron

Add the cron entry on wilma-server. Monitor the first 24 hours via Gazoo audit.

---

## Anti-Spam Guarantees

| Safeguard | Protection |
|-----------|-----------|
| Debounce (3 consecutive checks) | Transient blips never reach customers |
| Rate limit (6h between new posts) | Maximum 4 new announcements per day, ever |
| Edit-in-place | Status changes update existing message, not new messages |
| No auto-fix | Monitor never modifies the system → no fix/recheck/announce cycle |
| WAL = normal | DuckDB WAL files never trigger any action |
| Dry-run mode | Test the entire flow without touching Discord |
| Read-only DuckDB check | Monitor never writes to the database |

### Worst-Case Scenario Analysis

**Q: What if the bot goes down and comes back every 10 minutes?**
A: Debounce catches the first down. If it recovers within 15 min (3 checks), no announcement is ever posted. If it stays down for 15+ min, one announcement is posted. When it recovers, that same message is edited to show "resolved." If it goes down again within 6 hours, no new announcement — edit-in-place updates the existing message. Customer sees: one message, updated in place. Maximum one notification.

**Q: What if the pipeline fails for 3 days?**
A: One announcement at the 15-minute mark (degraded). If it worsens to "down," the same message is edited. When resolved, the same message is edited to "resolved." Customer sees: one notification, content updates in place. Zero spam.

**Q: What if DuckDB WAL files exist continuously?**
A: Nothing happens. WAL files are logged as informational. The DuckDB health check is a read-only query — if the query succeeds, the database is healthy, period. No WAL detection, no WAL backup, no announcements.

---

## Success Criteria

| Criteria | Measure |
|----------|---------|
| Zero false announcements in first 7 days | No "Service Restored" messages when service was never actually down |
| Maximum 1 notification per incident | Customer sees one message per outage, updated in place |
| 15-minute debounce works | Transient blips (<15 min) never produce announcements |
| Dry-run matches reality | `--dry-run` output matches what `--announce` actually does |
| Gazoo audit approves | Service status domain score ≥8/10 after 1 week |

---

*Barney — Chief of Pipeline, Slate Rock & Gravel Co. 🪨*
