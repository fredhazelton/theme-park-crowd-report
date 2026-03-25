# SESSION_LOG — WTI Pipeline

**Last updated:** 2026-03-24 by Barney (Session 1)
**Session:** 1
**Status:** Production pipeline running. 730-day forecast restored. The Quarry shipped. Setting up shared memory system.

---

## Project Background

**What we're building:** The Wait Time Index (WTI) — a theme park crowd prediction and analytics platform that forecasts wait times and crowd patterns for Walt Disney World attractions up to 730 days out.

**Why it matters:** WTI is HazeyData's core product. Accurate crowd predictions are the foundation for all monetization — Discord bot, premium subscriptions, public dashboards, and the eventual customer-facing analytics layer. Competitive advantage comes from forecast accuracy, entity coverage, and freshness.

**Who uses it / who buys it:** Theme park visitors planning trips (free tier via Discord bot, future premium subscribers), theme park enthusiasts and data nerds, and eventually travel planners and agencies.

**How we got here:** The pipeline evolved from v1 through v4. A comprehensive audit on 2026-02-19 (`docs/PIPELINE_AUDIT_20260219.md`) identified key issues — the 730-day forecast was truncated to 365 days by a hardcoded date limit, archive filenames broke the evaluator, and observation freshness data was missing from analytics. These were fixed in the March 2026 sprint. The Quarry analytics dashboard was shipped as the internal monitoring layer. The enterprise redesign (2026-03-20) moved operations to a dedicated repo and professionalized Wilma's cron/task architecture.

**Key findings that still apply:**
- Archive filenames MUST contain `YYYY-MM-DD` dates with hyphens or the forecast evaluator silently skips them
- The Quarry only displays data the pipeline produces automatically — no manual data allowed
- `systemd-run --scope --user` is mandatory for long-running pipeline processes on Wilma
- Forecast end date must come from `get_forecast_end_date()`, never hardcoded

**Foundational documents:**
| Document | Location | What |
|----------|----------|------|
| Pipeline V4 Design | `docs/PIPELINE_V4_DESIGN.md` in TPCR | The governing design spec |
| Pipeline Audit (Feb 2026) | `docs/PIPELINE_AUDIT_20260219.md` in TPCR | Full audit with findings |
| Pipeline V3 Architecture | `docs/PIPELINE_V3_ARCHITECTURE.md` in TPCR | Architecture reference |
| The Quarry Architecture | `docs/THE_QUARRY_ARCHITECTURE.md` in TPCR | Dashboard system design |
| Modeling & WTI Methodology | `docs/MODELING_AND_WTI_METHODOLOGY.md` in TPCR | ML methodology doc |
| Audit & Redesign Playbook | `docs/AUDIT_REDESIGN_PLAYBOOK.md` in operations | Repeatable process |

---

## Current State

- **Forecast scope:** 64.1M predictions, 59,129 WTI park-dates through March 2028
- **Operating calendar:** 11.8M rows
- **Pipeline version:** V4 (governed by `PIPELINE_V4_DESIGN.md`)
- **The Quarry:** Live at `docs/the-quarry.html` on GitHub Pages
- **Analytics data:** `docs/analytics-data/` — accuracy_summary.json, daily_accuracy.json, entity_scores.json, entity_list.json, entity_dates_index.json
- **Observation freshness:** obs_total, obs_yesterday, obs_last_7d fields per entity
- **Cron jobs:** 10 jobs live via task_queue.py + cron_dispatch.py (queue-first architecture)
- **Pipeline lock window:** 6–8 AM ET (no modifications)
- **Wilma server:** wilma-server (Ryzen/64GB RAM/Ubuntu 24.04)

---

## Last Session Summary

Session 1 (2026-03-24): Initial SESSION_LOG.md creation as part of the project setup guide rollout. No pipeline changes this session — this is infrastructure/process work.

---

## In Progress

| Item | Status | Details |
|------|--------|---------|
| The Quarry UI iteration | Active | Pebbles daily design sprints |
| Data-hub Firecrawl scraper | PR #1 open | WDW park hours via Firecrawl, branch `barney/firecrawl-scraper` in data-hub |
| Session log system rollout | This session | Setting up shared memory for WTI project |

---

## Next Actions (Priority Order)

1. Complete WTI project setup (instructions, files, Wilma notification, verification)
2. Review The Quarry design iterations from Pebbles
3. Test and merge Firecrawl-based WDW park hours scraper (data-hub PR #1)
4. Pipeline accuracy monitoring — review daily accuracy reports
5. Plan customer-facing dashboard / Twitch streaming layer

---

## Blockers

None currently.

---

## Key Numbers

| Metric | Value | Updated |
|--------|-------|---------|
| Total predictions | 64.1M | Session 1 |
| WTI park-dates | 59,129 | Session 1 |
| Forecast horizon | Through March 2028 | Session 1 |
| Operating calendar rows | 11.8M | Session 1 |
| Cron jobs active | 10 | Session 1 |

---

## Decisions Log

| Date | Session | Decision | Who |
|------|---------|----------|-----|
| 2026-03-24 | 1 | Adopt SESSION_LOG.md shared memory system for WTI | Fred + Barney |
| 2026-03-20 | pre | Enterprise redesign: operations repo, task_queue, cron_dispatch | Fred + Barney |
| 2026-03-18 | pre | The Quarry data rule: only auto-generated pipeline data | Fred + Barney |
| 2026-02-19 | pre | Pipeline audit: fix 730-day truncation, archive filenames, obs freshness | Barney + Gazoo |

---

## Open Tickets

| Ticket | Repo | Status | Notes |
|--------|------|--------|-------|
| PR #1 | data-hub | Open | Firecrawl-based WDW park hours scraper |
| #14 | TPCR | Closed | The Quarry shipped |
| #15 | TPCR | Closed | Evaluator filename fix |

---

## Agent Notes

- **Wilma cron dispatch:** All crons use queue-first via `task_queue.py` + `cron_dispatch.py`. Session target is `isolated` for most jobs to avoid context overflow.
- **Pipeline output:** Lives at `/home/wilma/hazeydata/pipeline` on wilma-server
- **GitHub Pages:** Served from `docs/` directory
- **Clawdbot config:** `~/.clawdbot/clawdbot.json` on wilma-server. Discord bot token is in `~/.env`, NOT the JSON config.
- **No red-amber-green:** The benedictus brand gradient must be used for all health indicators and status elements.
- **Gazoo audits:** Fire at 2 AM and 4 PM ET. Posts to #gazoo channel.

---

## How to Start Next Session

Any agent beginning work on this project should:

1. Read this file (`SESSION_LOG.md` in `hazeydata/theme-park-crowd-report`)
2. Read the governing spec (`docs/PIPELINE_V4_DESIGN.md` in TPCR)
3. Check `#wti-pipeline` (`1479351574177513576`) for messages since last update
4. Pick up from "Next Actions" above

---

*This is the shared project memory for WTI Pipeline. Updated every session. Git history preserves all previous versions.*
