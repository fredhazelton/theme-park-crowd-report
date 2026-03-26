# SESSION_LOG — WTI Pipeline

**Last updated:** 2026-03-26 by Barney (Session 22 — Dino operational, tweet pipeline live, scraper fixed)
**Session:** 22
**Status:** Four-tier architecture live. Tweet pipeline migrated to Dino (Mac Mini). First tweet posted. Scraper restarted. Competition shadow run approved.

---

## Enterprise Architecture (v3.0)

| Tier | Agent | WTI Role |
|------|-------|----------|
| 1 | **Fred** | Approvals, content direction, monetization |
| 2 | **Barney** 🪨 | Pipeline design, architecture, accuracy review (Claude Desktop) |
| 3 | **Dino** 🦕 | Operations brain — crons, tweets, reports, monitoring (Claude Code on Mac Mini) |
| 4 | **wilma-server** | Compute engine — pipeline, training, databases, scraping |

**Key principle:** Fred decides → Barney plans → Dino executes → wilma-server computes

**Governing doc:** `docs/REDESIGN.md` v3.0 in operations repo

---

## Project Background

**What we're building:** The Wait Time Index (WTI) — a theme park crowd prediction and analytics platform that forecasts wait times and crowd patterns for Walt Disney World attractions up to 730 days out.

**Why it matters:** WTI is HazeyData's core product. Accurate crowd predictions are the foundation for all monetization — Discord bot, premium subscriptions, public dashboards, and the eventual customer-facing analytics layer.

**How we got here:** Pipeline evolved v1→v4. Sessions 20-21 built the Twitter content pipeline (Step 14 + quality gate). Session 22 introduced the four-tier architecture with Dino as Tier 3 operations brain, migrated tweet posting from Wilma to Dino, and fast-tracked the competition shadow run.

**Key findings that still apply:**
- Archive filenames MUST contain `YYYY-MM-DD` dates with hyphens or the forecast evaluator silently skips them
- `systemd-run --scope --user` is mandatory for long-running pipeline processes on wilma-server
- Forecast end date must come from `get_forecast_end_date()`, never hardcoded
- The Quarry is **retired** as of Session 20 / Amendment 001
- EU entity = **Epic Universe** (Universal Orlando), NOT Europa-Park — dimension table needs fix

**Foundational documents:**
| Document | Location | What |
|----------|----------|------|
| Pipeline V4 Design | `docs/PIPELINE_V4_DESIGN.md` in TPCR | The governing design spec |
| V4 Amendment 001 | `docs/V4_AMENDMENT_001_CONTENT_PIPELINE.md` in TPCR | Step 14 content pipeline + quality gate |
| REDESIGN.md v3.0 | `docs/REDESIGN.md` in operations | Four-tier enterprise architecture |
| Dino briefings | `docs/briefings/` in operations | Cross-tier task assignments |

---

## Dino's Mac Mini Crontab (7 jobs)

| Time (ET) | Job | Status |
|-----------|-----|--------|
| 2:00 AM | Gazoo audit | ✅ Live |
| 4:00 AM | SSD daily report | ✅ Live |
| 6:00 AM | ACCORD intel brief | ✅ Live |
| 7:07 AM | WTI daily report | ✅ Live |
| 8:30 AM | WTI observed tweet | ✅ NEW Session 22 |
| 4:00 PM | Gazoo audit + WTI predicted tweet | ✅ NEW Session 22 |

wilma-server: Pipeline at 6 AM (compute only). Tweet crons DISABLED.

---

## Current State

- **Forecast scope:** ~47M predictions/day, 59,261 WTI park-dates through March 2028
- **Pipeline version:** V4 (governed by `PIPELINE_V4_DESIGN.md` + Amendment 001)
- **Daily pipeline:** Running 6 AM ET on wilma-server, steps s01-s14, ~55 min
- **Accuracy:** Overall MAE 8.6, WTI MAE 6.7 (stable since Mar 22)
- **Challenger MAE:** 4.90 (partial eval — `xgb-highLR`, incomplete forecasts)
- **Models:** 420 baseline, 433 total coverage, 109 on fallback
- **Twitter:** LIVE on @DisneyStatsWhiz — Dino owns posting (Mac Mini crons)
- **First tweet:** Session 22, tweet ID 2037097302976782433
- **Video tweets:** Code complete (SHA `c9595da`), first video tweet fires 4 PM ET today
- **Scraper:** Restarted Session 22 after 4-day outage. `Restart=always` applied.
- **Properties with WTI data:** 13 (WDW, DLR, Universal Orlando, Universal Hollywood, Tokyo Disney, Epic Universe)

---

## Session 22 Summary (2026-03-26)

**Major session. Four-tier architecture proven. Dino completed 6-task sprint in ~25 minutes.**

### Barney (Tier 2):
1. Full situational awareness — SESSION_LOG, Discord channels, codebase
2. Learned v3.0 architecture — Dino, four-tier model, Mac Mini as Tier 3
3. Drafted and committed tweet migration briefing to operations repo
4. Reviewed Dino's assessment, sent green light for Phase 1
5. Drafted and committed six-task work list for Dino
6. Designed competition fix: Step A (fix forecasts) → Step B (full eval) → Step C (shadow run)
7. Got Fred's approval to fast-track shadow run
8. Committed competition shadow run briefing to operations repo
9. Updated SESSION_LOG

### Dino (Tier 3 — all tasks completed):
| Task | Result |
|------|--------|
| Pipeline diagnosis | NOT broken — "NOT RUN" was from Dino's own 3:40 AM test runs |
| Remotion fix | Both posting scripts fixed on wilma-server (SHA `6c67bfe`) |
| Tweet Phase 1 | Text-only tweets live. Crons installed. Wilma crons disabled. |
| Tweet Phase 2 | Video code complete (SHA `c9595da`). First video tweet 4 PM today. |
| Scraper | Dead since Mar 22 (SIGTERM). Restarted. `Restart=always` applied. |
| Competition eval | `xgb-highLR` MAE 4.90 vs baseline 6.85. Blocked by incomplete `_temp/` forecasts. |
| CLAUDE.md | Updated to V4 (SHA `3e3ce342`) |
| Tickets | Closed TPCR #455, #456, ops #22 |
| Multi-property | 13 properties scoped. DLR + Universal Orlando ready for tweets. |
| EU bug | EU = Epic Universe, NOT Europa-Park. Dimension table corrupted. |

---

## In Progress

| Item | Status | Details |
|------|--------|---------|
| **Video tweet** | Code complete | First video tweet fires 4 PM ET today — verify on @DisneyStatsWhiz |
| **Competition shadow run** | APPROVED, not started | See `docs/briefings/DINO_COMPETITION_SHADOW_20260326.md` in operations |
| **EU dimension fix** | Flagged | "Europa-Park" → "Epic Universe" across pipeline |
| **extract_daily_wti.py date bug** | Flagged | Predicted mode date logic wrong — workaround in place |

---

## Next Actions (Priority Order)

1. **Verify 4 PM video tweet (today):** Check @DisneyStatsWhiz — does video render and post?
2. **Verify 8:30 AM observed tweet (tomorrow):** Does the reply thread work?
3. **Dino: Competition shadow run** — Fix forecasts → full eval → start 7-day shadow. See briefing in operations.
4. **Fix EU dimension table** — "Europa-Park" → "Epic Universe" in entity mapping
5. **Fix extract_daily_wti.py date logic** — predicted mode wrong
6. **Multi-property tweets** — DLR + Universal Orlando ready. Design schedule (don't flood followers).
7. **Tell Wilma about v3.0** — She doesn't know about Dino yet. Got confused seeing Barney's green light.

---

## Blockers

None.

---

## Key Numbers

| Metric | Value | Updated |
|--------|-------|---------|
| Total predictions | ~47M/day | S20 |
| WTI park-dates | 59,261 | S20 |
| Forecast horizon | Through March 2028 | S1 |
| Overall MAE | 8.6 min | S20 |
| WTI MAE | 6.7 min | S20 |
| Challenger MAE | 4.90 min (partial) | S22 |
| Baseline models | 420 | S20 |
| Fallback entities | 109 | S20 |
| Properties with WTI | 13 | S22 |
| Dino crons | 7 | S22 |
| Scraper downtime | 4 days (fixed S22) | S22 |

---

## Decisions Log

| Date | Session | Decision | Who |
|------|---------|----------|-----|
| 2026-03-26 | 22 | Fast-track competition shadow run. 7-day min before promotion. | Fred + Barney |
| 2026-03-26 | 22 | Migrate tweet posting from Wilma to Dino (Mac Mini) | Fred + Barney |
| 2026-03-26 | 22 | Scraper: Restart=on-failure → Restart=always | Fred + Barney |
| 2026-03-26 | 22 | Dino scripts live in operations repo, not TPCR | Barney |
| 2026-03-26 | 22 | DLR + Universal Orlando are next tweet targets | Fred + Barney |
| 2026-03-25 | 20 | Twitter content pipeline GO LIVE | Fred |
| 2026-03-25 | 20 | V4 Amendment 001 approved | Fred + Barney |
| 2026-03-25 | 20 | The Quarry retired | Fred + Barney |
| 2026-03-24 | 1 | SESSION_LOG.md shared memory system | Fred + Barney |

---

## Open Tickets

| Ticket | Repo | Status | Notes |
|--------|------|--------|-------|
| #453 | TPCR | Open | Competition — shadow run approved, awaiting Dino |
| PR #1 | data-hub | Open | Firecrawl WDW park hours scraper |

---

## Agent Notes

- **Dino (Mac Mini):** Claude Code v2.1.84, Opus 4.6, Claude Max. `~/hazeydata/` repos. SSH to wilma@192.168.2.75. `bypassPermissions` enabled. Scripts at `~/hazeydata/scripts/`.
- **Wilma:** Does NOT know about Dino or v3.0 yet. Update when convenient.
- **Twitter creds:** Mac Mini `~/.env`. Wilma-server `/home/wilma/.clawdbot/.env`.
- **Tweet state:** Mac Mini `~/hazeydata/reports/wti_daily/tweet_state.json`.
- **Pipeline output:** `/home/wilma/hazeydata/pipeline` on wilma-server.
- **Content JSONs:** `/home/wilma/hazeydata/pipeline/content/`.
- **Briefings:** `docs/briefings/` in operations repo — version-controlled cross-tier comms.
- **EU bug:** Epic Universe, NOT Europa-Park. Dimension table corrupted enterprise-wide.

---

## How to Start Next Session

1. Read this file (`SESSION_LOG.md` in `hazeydata/theme-park-crowd-report`)
2. Read governing spec (`docs/PIPELINE_V4_DESIGN.md`) and Amendment 001
3. Read enterprise architecture (`docs/REDESIGN.md` in operations)
4. Check `#wti-pipeline` and `#barney-wilma-dev` for Dino's updates
5. Check @DisneyStatsWhiz — verify tweets are posting
6. Pick up from "Next Actions" above

---

*Shared project memory for WTI Pipeline. Updated every session. Git history preserves all versions.*
