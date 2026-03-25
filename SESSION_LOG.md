# SESSION_LOG — WTI Pipeline

**Last updated:** 2026-03-25 by Barney (Session 20)
**Session:** 20
**Status:** Production pipeline running. V4 Amendment 001 approved — Step 14 Content Pipeline + Quality Gate. The Quarry retired.

---

## Project Background

**What we're building:** The Wait Time Index (WTI) — a theme park crowd prediction and analytics platform that forecasts wait times and crowd patterns for Walt Disney World attractions up to 730 days out.

**Why it matters:** WTI is HazeyData's core product. Accurate crowd predictions are the foundation for all monetization — Discord bot, premium subscriptions, public dashboards, and the eventual customer-facing analytics layer. Competitive advantage comes from forecast accuracy, entity coverage, and freshness.

**Who uses it / who buys it:** Theme park visitors planning trips (free tier via Discord bot, future premium subscribers), theme park enthusiasts and data nerds, and eventually travel planners and agencies.

**How we got here:** The pipeline evolved from v1 through v4. A comprehensive audit on 2026-02-19 identified key issues — the 730-day forecast was truncated, archive filenames broke the evaluator, and observation freshness data was missing. These were fixed in the March 2026 sprint. The enterprise redesign (2026-03-20) moved operations to a dedicated repo and professionalized Wilma's cron/task architecture. Session 20 designed and approved the Twitter content pipeline as a formal v4 extension.

**Key findings that still apply:**
- Archive filenames MUST contain `YYYY-MM-DD` dates with hyphens or the forecast evaluator silently skips them
- `systemd-run --scope --user` is mandatory for long-running pipeline processes on Wilma
- Forecast end date must come from `get_forecast_end_date()`, never hardcoded
- The Quarry is **retired** as of Session 20 / Amendment 001

**Foundational documents:**
| Document | Location | What |
|----------|----------|------|
| Pipeline V4 Design | `docs/PIPELINE_V4_DESIGN.md` in TPCR | The governing design spec |
| V4 Amendment 001 | `docs/V4_AMENDMENT_001_CONTENT_PIPELINE.md` in TPCR | Step 14 content pipeline + quality gate (APPROVED) |
| Pipeline Audit (Feb 2026) | `docs/PIPELINE_AUDIT_20260219.md` in TPCR | Full audit with findings |
| Modeling & WTI Methodology | `docs/MODELING_AND_WTI_METHODOLOGY.md` in TPCR | ML methodology doc |
| Audit & Redesign Playbook | `docs/AUDIT_REDESIGN_PLAYBOOK.md` in operations | Repeatable process |

---

## Current State

- **Forecast scope:** 64.1M predictions, 59,129 WTI park-dates through March 2028
- **Operating calendar:** 11.8M rows
- **Pipeline version:** V4 (governed by `PIPELINE_V4_DESIGN.md` + Amendment 001)
- **Daily pipeline:** Running 6 AM ET, all steps passing (s01-s13), ~55 min runtime
- **Accuracy:** Overall MAE 8.6, WTI MAE 6.7 (stable since Mar 22)
- **Models:** 420 baseline, 433 total coverage, 109 on fallback
- **Cron jobs:** 10 jobs live via task_queue.py + cron_dispatch.py
- **Pipeline lock window:** 6–8 AM ET (no modifications)
- **Wilma server:** wilma-server (Ryzen/64GB RAM/Ubuntu 24.04)
- **The Quarry:** RETIRED (Session 20, Amendment 001)

---

## Last Session Summary

**Session 20 (2026-03-25):**

1. **Read SESSION_LOG, #wti-pipeline, #barney-wilma-dev, #gazoo, #fred-wilma** — full situational awareness
2. **Identified accuracy report confusion:** Wilma modified legacy `scripts/run_daily_pipeline.sh` and `scripts/daily_accuracy_report.py` thinking they were part of the v4 pipeline. They are not. The v4 pipeline's Step 10 (s10_accuracy.py) runs every day and produces accuracy metrics. Sent investigation questions to Wilma in #barney-wilma-dev (awaiting response).
3. **Identified stale v3 data source incident:** Wilma fixed `extract_daily_wti.py` to read from v4 pipeline output instead of stale v3 shadow data. Root cause: no formal system linking pipeline output to content generation.
4. **Designed V4 Amendment 001:** Twitter content pipeline as Step 14 (s14_content.py) with quality gate. Predicted tweet (afternoon, tomorrow's WTI for 4 WDW parks) + observed tweet (morning reply, yesterday's actuals). Quality gate prevents publishing bad data (catches AK=9 scenario).
5. **Fred approved Amendment 001.** Committed as `docs/V4_AMENDMENT_001_CONTENT_PIPELINE.md`.
6. **Filed TPCR #456** — implementation ticket for Wilma, 3 phases.
7. **Retired The Quarry** formally in Amendment 001.
8. **Noted legacy scripts still in `scripts/` that should be archived** — included in #456 cleanup.

---

## In Progress

| Item | Status | Details |
|------|--------|---------|
| **TPCR #456 — Step 14 Content Pipeline** | Filed, Phase 1 | s14_content.py + quality gate + legacy cleanup |
| **TPCR #453 — Competition framework** | Open | 430 entities trained, needs fresh eval with full model set |
| **Accuracy report investigation** | Awaiting Wilma | Questions posted in #barney-wilma-dev about what she actually modified |
| **Scraper freshness** | Flagged by Gazoo | 60.4h stale as of Mar 24 PM audit |

---

## Next Actions (Priority Order)

1. **Wilma: Begin TPCR #456 Phase 1** — read Amendment 001, implement s14_content.py, archive legacy scripts
2. **Wilma: Answer accuracy investigation questions** in #barney-wilma-dev
3. **Wilma: Run fresh competition evaluation** (TPCR #453) — need baseline vs hypertuned_v1 comparison
4. **Wilma: Fix scraper freshness** — Gazoo flagged 60h stale
5. **Pebbles: Design predicted vs observed tweet visuals** — distinct styles per Amendment 001

---

## Blockers

None currently.

---

## Key Numbers

| Metric | Value | Updated |
|--------|-------|---------|
| Total predictions | ~47M/day | Session 20 |
| WTI park-dates | 59,261 | Session 20 |
| Forecast horizon | Through March 2028 | Session 1 |
| Overall MAE | 8.6 min | Session 20 (stable Mar 22-24) |
| WTI MAE | 6.7 min | Session 20 |
| Baseline models | 420 | Session 20 |
| Fallback entities | 109 | Session 20 |
| Cron jobs active | 10 | Session 1 |

---

## Decisions Log

| Date | Session | Decision | Who |
|------|---------|----------|-----|
| 2026-03-25 | 20 | V4 Amendment 001 approved: Step 14 content pipeline + quality gate | Fred + Barney |
| 2026-03-25 | 20 | The Quarry retired | Fred + Barney |
| 2026-03-25 | 20 | Twitter content: WDW only for v1, predicted + observed reply thread, quality gate with manual release | Fred + Barney |
| 2026-03-25 | 20 | Observed tweet: clean WTI only, no accuracy comparison | Fred |
| 2026-03-25 | 20 | Legacy scripts (daily_accuracy_report.py, run_daily_pipeline.sh, etc.) formally dead code — archive | Barney |
| 2026-03-24 | 1 | Adopt SESSION_LOG.md shared memory system for WTI | Fred + Barney |
| 2026-03-20 | pre | Enterprise redesign: operations repo, task_queue, cron_dispatch | Fred + Barney |

---

## Open Tickets

| Ticket | Repo | Status | Notes |
|--------|------|--------|-------|
| #456 | TPCR | Open | Step 14 content pipeline + quality gate (NEW, Session 20) |
| #453 | TPCR | Open | Competition framework — needs fresh eval |
| #455 | TPCR | Open | Stale — references retired v2 pipeline. Close as superseded. |
| PR #1 | data-hub | Open | Firecrawl-based WDW park hours scraper |

---

## Agent Notes

- **Wilma cron dispatch:** All crons use queue-first via `task_queue.py` + `cron_dispatch.py`. Session target is `isolated` for most jobs.
- **Pipeline output:** Lives at `/home/wilma/hazeydata/pipeline` on wilma-server
- **Clawdbot config:** `~/.clawdbot/clawdbot.json` on wilma-server. Discord bot token is in `~/.env`, NOT the JSON config.
- **No red-amber-green:** The benedictus brand gradient must be used for all health indicators and status elements.
- **Gazoo audits:** Fire at 2 AM and 4 PM ET. Posts to #gazoo channel.
- **Wilma accuracy investigation pending:** She may have modified legacy scripts thinking they were v4. Need evidence of what was actually changed. See #barney-wilma-dev.

---

## How to Start Next Session

Any agent beginning work on this project should:

1. Read this file (`SESSION_LOG.md` in `hazeydata/theme-park-crowd-report`)
2. Read the governing spec (`docs/PIPELINE_V4_DESIGN.md`) and Amendment 001 (`docs/V4_AMENDMENT_001_CONTENT_PIPELINE.md`)
3. Check `#wti-pipeline` (`1479351574177513576`) for messages since last update
4. Check `#barney-wilma-dev` (`1479937927378239550`) for Wilma's response to accuracy investigation
5. Pick up from "Next Actions" above

---

*This is the shared project memory for WTI Pipeline. Updated every session. Git history preserves all previous versions.*
