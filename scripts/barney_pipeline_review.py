#!/usr/bin/env python3
"""
Barney's Independent Pipeline Review

Runs at Barney's cold-start via GitHub MCP + Discord MCP.
Reads pipeline artifacts directly (not Wilma's interpretation) and produces
an independent health assessment.

This is NOT a server-side script. It's a protocol spec that Barney executes
manually by reading files via GitHub MCP and posting results to Discord.

Data sources (all readable via GitHub MCP):
  1. docs/mission-control-content.json  — Wilma's pipeline status snapshot
  2. docs/pipeline-status.json          — lightweight step status
  3. docs/office-state.json             — crew activity
  4. accuracy_report_*.json             — per-park daily WTI accuracy
  5. Git commit history                 — file staleness proxy
  6. Discord #gazoo, #alerts            — independent audit findings

Output:
  - Discord message to #pipeline with Barney's independent assessment
  - barney_reviews/YYYY-MM-DD.json committed to repo (audit trail)

Usage:
  Barney reads this file, then follows the REVIEW PROTOCOL below
  using GitHub MCP and Discord MCP tools. This is a human-in-the-loop
  script — Barney IS the runtime.
"""

# =============================================================================
# REVIEW PROTOCOL — Barney follows these steps every cold-start
# =============================================================================
#
# After completing the standard cold-start (BARNEY.md steps 1-4), run this:
#
# STEP 1: READ ARTIFACTS
#   github:get_file_contents → docs/mission-control-content.json
#   github:get_file_contents → docs/pipeline-status.json
#   github:get_file_contents → docs/office-state.json
#   github:list_commits (last 10) → check recency of pipeline-related commits
#
# STEP 2: STALENESS CHECKS
#   - mission-control-content.json → parse "last_updated" field
#     🟢 <4h old = fresh    🟡 4-12h = stale    🔴 >12h = dead
#   - accuracy.days_evaluated → is this growing? compare to last review
#   - pipeline_status.forecasts → row count changing?
#   - Last Wilma commit with actual pipeline work (not Discord sync) → how long ago?
#
# STEP 3: ACCURACY CHECKS
#   From mission-control-content.json → accuracy block:
#   - wti_mae: 🟢 <7  🟡 7-10  🔴 >10
#   - wti_bias: 🟢 <|3|  🟡 |3-5|  🔴 >|5| (overprediction = positive)
#   - entity_mae: 🟢 <10  🟡 10-15  🔴 >15
#   - MAPE: if >50%, flag as suspicious (may be calculation bug, not real accuracy)
#
#   From accuracy_report_*.json (latest available):
#   - Per-park breakdown: which parks have abs_error > 10?
#   - Is IA still overpredicting? Is EU still overpredicting?
#   - Any park with error > 15 = 🔴 immediate investigation
#
# STEP 4: INFRASTRUCTURE CHECKS
#   From mission-control-content.json → infrastructure block:
#   - disk_main_pct: 🟢 <80%  🟡 80-90%  🔴 >90%
#   - All services active? Any failed/unknown?
#   - db_forecasts row count: compare to expected (~29M for 365 days)
#     If <20M → forecasts likely incomplete or stale
#
# STEP 5: CONFIG DRIFT CHECK
#   github:get_file_contents → scripts/run_daily_pipeline.sh
#   - Verify forecast call still has --workers 2 --days 365
#   - Verify no 2>/dev/null on critical state checks
#   - Verify Cloudflare account ID not hardcoded (or note if still pending)
#
# STEP 6: CROSS-REFERENCE GAZOO
#   discord:discord_read_messages → #gazoo (last 5)
#   - Does Gazoo's accuracy assessment match what I see in the JSON?
#   - Any findings Gazoo flagged that don't show in the data?
#   - Any data issues I see that Gazoo missed?
#
# STEP 7: PRODUCE ASSESSMENT
#   Build a JSON review object (see REVIEW SCHEMA below) and:
#   a) Post summary to #pipeline
#   b) Commit full JSON to barney_reviews/YYYY-MM-DD.json
#
# =============================================================================

# =============================================================================
# REVIEW SCHEMA — barney_reviews/YYYY-MM-DD.json
# =============================================================================
REVIEW_SCHEMA = {
    "review_date": "YYYY-MM-DD",
    "review_session": 1,  # increment if multiple reviews per day
    "overall_grade": "🟢|🟡|🔴",  # worst of all checks
    "staleness": {
        "mission_control_age_hours": 0.0,
        "last_pipeline_commit_age_hours": 0.0,
        "forecast_row_count": 0,
        "accuracy_days_evaluated": 0,
        "grade": "🟢|🟡|🔴",
    },
    "accuracy": {
        "wti_mae": 0.0,
        "wti_bias": 0.0,
        "entity_mae": 0.0,
        "mape": 0.0,
        "mape_suspicious": False,  # True if MAPE > 50%
        "worst_parks": [],  # [{"park": "IA", "error": +17.1}, ...]
        "grade": "🟢|🟡|🔴",
    },
    "infrastructure": {
        "disk_main_pct": 0,
        "services_down": [],  # names of non-active services
        "grade": "🟢|🟡|🔴",
    },
    "config_drift": {
        "forecast_workers": 2,
        "forecast_days": 365,
        "issues_found": [],  # ["Cloudflare ID still hardcoded", ...]
        "grade": "🟢|🟡|🔴",
    },
    "gazoo_cross_ref": {
        "gazoo_agrees": True,
        "discrepancies": [],  # ["Gazoo says MAE 6.4 but MC JSON says 6.8", ...]
    },
    "action_items": [],  # ["Investigate IA +17 bias", ...]
    "notes": "",
}

# =============================================================================
# GRADE THRESHOLDS — reference for Barney
# =============================================================================
THRESHOLDS = {
    "staleness": {
        "mc_hours": {"green": 4, "yellow": 12},  # hours since last_updated
        "commit_hours": {"green": 6, "yellow": 18},  # hours since last pipeline commit
    },
    "accuracy": {
        "wti_mae": {"green": 7, "yellow": 10},
        "wti_bias_abs": {"green": 3, "yellow": 5},
        "entity_mae": {"green": 10, "yellow": 15},
        "park_error_alert": 15,  # per-park abs error triggers investigation
        "mape_suspicious": 50,  # MAPE > 50% = probably a bug, not real
    },
    "infrastructure": {
        "disk_pct": {"green": 80, "yellow": 90},
        "forecast_rows_min": 20_000_000,  # below this = incomplete forecast
    },
}

# =============================================================================
# DISCORD OUTPUT FORMAT
# =============================================================================
# Post to #pipeline as:
#
# ## 🪨 Barney Pipeline Review — YYYY-MM-DD
#
# **Overall: 🟢/🟡/🔴**
#
# | Check | Grade | Detail |
# |-------|-------|--------|
# | Staleness | 🟢 | MC updated 2.1h ago |
# | Accuracy | 🟡 | WTI MAE 6.8, IA +17.1 |
# | Infrastructure | 🔴 | Disk 90%, services OK |
# | Config | 🟢 | No drift detected |
#
# **Action items:**
# 1. Investigate IA overprediction (+17.1)
# 2. Disk at 90% — clean up old logs
#
# *Independent of Wilma/Gazoo. Cross-referenced with Gazoo 2026-03-07: agrees on MAE, missed disk warning.*
