# Session Log

**Last updated:** 2026-03-26 by Barney (Session 22 FINAL — all tasks complete, shadow run live)
**Session:** 22
**Status:** Four-tier architecture live. Tweets posting from Dino. Shadow run Day 1 complete. Amendment 002 approved. Water parks excluded.

---

## Enterprise Architecture (v3.0)

| Tier | Agent | WTI Role |
|------|-------|----------|
| 1 | **Fred** | Approvals, content direction, monetization |
| 2 | **Barney** 🪨 | Pipeline design, architecture, accuracy review (Claude Desktop) |
| 3 | **Dino** 🦕 | Operations brain — crons, tweets, reports, shadow runs, monitoring (Claude Code on Mac Mini) |
| 4 | **wilma-server** | Compute engine — pipeline, training, databases, scraping |

**Key principle:** Fred decides → Barney plans → Dino executes → wilma-server computes

**Governing docs:** `docs/REDESIGN.md` v3.0 in operations repo

## 2026-03-25 - SSD Pipeline Continuous Processing Implementation

### Microsoft MarkitDown Research Item
**Added:** 2026-03-25 22:00 EDT  
**Source:** Fred Hazelton suggestion  
**Repository:** https://github.com/microsoft/markitdown  

**Description:** Document-to-markdown conversion tool that could significantly improve SSD pipeline PDF/document extraction success rates.

**Current Pain Points:**
- PDF parsing failures (404s, malformed docs)
- Multiple document formats (PDF, Word, Excel)
- Inconsistent extraction quality (~70% success rate)

**Potential Benefits:**
- Preprocessing step: Convert docs to clean markdown before LLM extraction
- Backup method: Try MarkitDown if direct PDF parsing fails
- Quality improvement: Structured markdown → more consistent date extraction
- Could boost success rate significantly

**Priority:** Research backlog for Sprint 3 pipeline improvements

**Status:** Identified - needs evaluation and potential integration testing

---

**Why it matters:** WTI is HazeyData's core product. Accurate crowd predictions are the foundation for all monetization — Discord bot, premium subscriptions, public dashboards, and the eventual customer-facing analytics layer.

**How we got here:** Pipeline evolved v1→v4. Sessions 20-21 built Twitter content pipeline (Step 14 + quality gate). Session 22 proved the four-tier architecture, migrated tweets to Dino, launched rolling competition framework (Amendment 002), and excluded water parks from the pipeline.

**Key findings that still apply:**
- Archive filenames MUST contain `YYYY-MM-DD` dates with hyphens or the forecast evaluator silently skips them
- `systemd-run --scope --user` is mandatory for long-running pipeline processes on wilma-server
- Forecast end date must come from `get_forecast_end_date()`, never hardcoded
- The Quarry is **retired** as of Session 20 / Amendment 001
- EU entity = **Epic Universe** (Universal Orlando), NOT Europa-Park — dimension table fix pending
- Water parks (BB, TL, VB) **excluded from all pipeline processing** — ETL, training, forecasts, tweets

**Foundational documents:**
| Document | Location | What |
|----------|----------|------|
| Pipeline V4 Design | `docs/PIPELINE_V4_DESIGN.md` in TPCR | The governing design spec |
| V4 Amendment 001 | `docs/V4_AMENDMENT_001_CONTENT_PIPELINE.md` in TPCR | Step 14 content pipeline + quality gate |
| V4 Amendment 002 | `docs/V4_AMENDMENT_002_ROLLING_COMPETITION.md` in TPCR | Rolling competition framework (APPROVED) |
| REDESIGN.md v3.0 | `docs/REDESIGN.md` in operations | Four-tier enterprise architecture |
| Dino briefings | `docs/briefings/` in operations | Cross-tier task assignments |

---

## Dino's Mac Mini Crontab (8 jobs)

| Time (ET) | Job | Status |
|-----------|-----|--------|
| 2:00 AM | Gazoo audit | ✅ Live |
| 4:00 AM | SSD daily report | ✅ Live |
| 6:00 AM | ACCORD intel brief | ✅ Live |
| 7:00 AM | Shadow run challenger (`shadow_run_challenger.py`) | ✅ NEW Session 22 |
| 7:07 AM | WTI daily report | ✅ Live |
| 8:30 AM | WTI observed tweet | ✅ NEW Session 22 |
| 4:00 PM | Gazoo audit + WTI predicted tweet | ✅ NEW Session 22 |

wilma-server: Pipeline at 6 AM (compute only). Tweet crons DISABLED.

---

## Current State

- **Forecast scope:** ~47M predictions/day, 59,261 WTI park-dates through March 2028
- **Pipeline version:** V4 (governed by `PIPELINE_V4_DESIGN.md` + Amendments 001, 002)
- **Daily pipeline:** Running 6 AM ET on wilma-server, steps s01-s14, ~55 min
- **Accuracy:** Overall MAE 8.6, WTI MAE 6.78 (baseline)
- **Challenger:** `xgb-highLR` MAE 4.84 vs baseline 6.78 — shadow Day 1 complete, ends April 2
- **Models:** 420 baseline, 433 total coverage, 109 on fallback
- **Twitter:** LIVE on @DisneyStatsWhiz — Dino owns posting (Mac Mini crons)
- **First tweet:** Posted Session 22, tweet ID 2037097302976782433
- **Video tweets:** Code complete (SHA `c9595da`), first video tweet fires 4 PM ET today
- **Scraper:** Restarted Session 22 after 4-day outage. `Restart=always` applied.
- **Shadow run:** Live — `shadow_run_challenger.py` cron at 7 AM. Day 1 archived (SHA `080fcf6`).
- **Water parks:** BB/TL/VB excluded from ETL (TPCR #457, SHA `030655e8`)
- **Properties with WTI data:** 13 (WDW, DLR, Universal Orlando, Universal Hollywood, Tokyo Disney, Epic Universe)

---

## Session 22 Summary (2026-03-26) — THE BIG ONE

**Four-tier architecture proven. Barney designed, Dino executed. Everything delivered in a single session.**

### Barney (Tier 2) — Strategy & Architecture:
1. Full situational awareness — SESSION_LOG, Discord, codebase, operations docs
2. Learned v3.0 architecture and Dino's role as Tier 3
3. Drafted & committed tweet migration briefing → Dino assessed → green light
4. Drafted & committed six-task work list → Dino completed all 6 in ~25 min
5. Designed competition fix (Steps A→B→C) → Fred approved fast-track
6. Designed **V4 Amendment 002: Rolling Competition Framework** → Fred approved
7. Codified water park exclusion (BB/TL/VB) at ETL level per Fred directive
8. Committed 3 briefing docs to `docs/briefings/` in operations repo
9. Updated SESSION_LOG throughout

### Dino (Tier 3) — Execution (complete summary):

| # | Task | Result | Commit |
|---|------|--------|--------|
| 1 | Scraper freshness | Dead 4 days (SIGTERM Mar 22). Restarted. `Restart=always` | server config |
| 2 | Competition eval | `xgb-highLR` MAE 4.84 vs baseline 6.78 | diagnostics |
| 3 | Remotion video tweets (Phase 2) | Code complete. Renders on wilma, SCPs to Mac Mini, uploads to Twitter | `c9595da` |
| 4 | CLAUDE.md cleanup | Updated to V4 reality | `3e3ce342` |
| 5 | Closed stale tickets | #455, #456, ops #22 | GitHub API |
| 6 | Multi-property scoping | 13 parks have WTI data. DLR + Universal Orlando next targets | diagnostics |
| A | Fixed incomplete challenger forecasts | Assembled from `_temp/` fragments | wilma-server |
| B | Full evaluation from ledger data | Posted to Discord | diagnostics |
| C | Shadow run live | Day 1 archived, cron at 7 AM, ends April 2 | `080fcf6` |
| — | Updated Rule 4 (smarter ticket policy) | | `5653b60` |
| — | Suppressed water parks BB/TL/VB (#457) | Excluded from ETL | `030655e8` |

### Fred (Tier 1) — Decisions:
- Approved tweet migration to Dino
- Approved fast-tracking shadow run
- Approved Amendment 002 (rolling competition)
- Directed water park exclusion from ETL (not just tweets)
- Confirmed EU = Epic Universe, not Europa-Park

---

## In Progress

| Item | Status | Details |
|------|--------|---------|
| **Video tweet** | Code complete | First video tweet fires 4 PM ET today — verify @DisneyStatsWhiz |
| **Shadow run** | Day 1 of 7 | `xgb-highLR` vs baseline. Ends April 2. Auto-evaluate. |
| **Rolling competition** | Infrastructure live | Add one new challenger per day from queue (Amendment 002) |
| **EU dimension fix** | Flagged | "Europa-Park" → "Epic Universe" across pipeline |
| **extract_daily_wti.py date bug** | Flagged | Predicted mode date logic wrong — workaround in place |

---

## Next Actions (Priority Order)

1. **Verify 4 PM video tweet (today):** Check @DisneyStatsWhiz — does video render and post?
2. **Verify 8:30 AM observed tweet (tomorrow):** Does the reply thread work?
3. **Dino: Add challenger #2 from queue** — `xgb-dow` (day-of-week feature). Per Amendment 002, one new challenger per day.
4. **Fix EU dimension table** — "Europa-Park" → "Epic Universe" in entity mapping
5. **Fix extract_daily_wti.py date logic** — predicted mode wrong
6. **Multi-property tweets** — DLR + Universal Orlando ready. Design schedule.
7. **Tell Wilma about v3.0** — She doesn't know about Dino yet.

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
| Baseline MAE | 6.78 min | S22 |
| Challenger MAE | 4.84 min (`xgb-highLR`, shadow Day 1) | S22 |
| Shadow run ends | April 2, 2026 | S22 |
| Baseline models | 420 | S20 |
| Fallback entities | 109 | S20 |
| Properties with WTI | 13 | S22 |
| Dino crons | 8 | S22 |
| Active challengers | 1 (target: 7-10) | S22 |

---

## Decisions Log

| Date | Session | Decision | Who |
|------|---------|----------|-----|
| 2026-03-26 | 22 | V4 Amendment 002 approved: Rolling Competition Framework | Fred + Barney |
| 2026-03-26 | 22 | Water parks (BB/TL/VB) excluded from ALL pipeline processing at ETL | Fred |
| 2026-03-26 | 22 | Fast-track competition shadow run. 7-day min before promotion. | Fred + Barney |
| 2026-03-26 | 22 | Migrate tweet posting from Wilma to Dino (Mac Mini) | Fred + Barney |
| 2026-03-26 | 22 | Scraper: Restart=on-failure → Restart=always | Fred + Barney |
| 2026-03-26 | 22 | Dino scripts live in operations repo, not TPCR | Barney |
| 2026-03-26 | 22 | DLR + Universal Orlando are next tweet targets | Fred + Barney |
| 2026-03-25 | 20 | V4 Amendment 001 approved: Step 14 content pipeline | Fred + Barney |
| 2026-03-25 | 20 | The Quarry retired | Fred + Barney |
| 2026-03-24 | 1 | SESSION_LOG.md shared memory system | Fred + Barney |

---

## Open Tickets

| Ticket | Repo | Status | Notes |
|--------|------|--------|-------|
| #457 | TPCR | Open | Water park suppression (BB/TL/VB) — ETL filter implemented |
| #453 | TPCR | Open | Competition — shadow run active, rolling framework per Amendment 002 |
| PR #1 | data-hub | Open | Firecrawl WDW park hours scraper |

---

## Agent Notes

- **Dino (Mac Mini):** Claude Code v2.1.84, Opus 4.6, Claude Max. `~/hazeydata/` repos. SSH to wilma@192.168.2.75. `bypassPermissions` enabled. Scripts at `~/hazeydata/scripts/`.
- **Wilma:** Does NOT know about Dino or v3.0 yet. Update when convenient. Her tweet crons are disabled (commented out, not deleted).
- **Twitter creds:** Mac Mini `~/.env`. Wilma-server `/home/wilma/.clawdbot/.env`.
- **Tweet state:** Mac Mini `~/hazeydata/reports/wti_daily/tweet_state.json`.
- **Pipeline output:** `/home/wilma/hazeydata/pipeline` on wilma-server.
- **Content JSONs:** `/home/wilma/hazeydata/pipeline/content/`.
- **Shadow forecasts:** `forecasts/shadow/{challenger_name}/` on wilma-server.
- **Challenger registry:** `pipeline/competition/challenger_registry.json` on wilma-server.
- **Briefings:** `docs/briefings/` in operations repo — version-controlled cross-tier comms.
- **EU bug:** Epic Universe, NOT Europa-Park. Dimension table corrupted enterprise-wide. Fix pending.
- **Water parks:** BB/TL/VB filtered at ETL. No models, no forecasts, no tweets.

---

## How to Start Next Session

1. Read this file (`SESSION_LOG.md` in `hazeydata/theme-park-crowd-report`)
2. Read governing spec (`docs/PIPELINE_V4_DESIGN.md`) and Amendments 001 + 002
3. Read enterprise architecture (`docs/REDESIGN.md` in operations)
4. Check `#wti-pipeline` and `#barney-wilma-dev` for Dino's updates
5. Check @DisneyStatsWhiz — verify tweets are posting with video
6. Check shadow run status — how many days in? Any challengers promoted/retired?
7. Pick up from "Next Actions" above

---

*Shared project memory for WTI Pipeline. Updated every session. Git history preserves all versions.*
>>>>>>> 84f0a59ab6cbf3a397fcf625e18bd121ec0359b0
