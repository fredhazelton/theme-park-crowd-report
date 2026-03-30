# Session Log

**Last updated:** 2026-03-30 by Barney (Session 23)
**Session:** 23
**Status:** Quality gate relaxed. Shadow run broken (Dino fixing). PQ research complete. Tweets posting daily.

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

---

**Why it matters:** WTI is HazeyData's core product. Accurate crowd predictions are the foundation for all monetization — Discord bot, premium subscriptions, public dashboards, and the eventual customer-facing analytics layer.

**How we got here:** Pipeline evolved v1→v4. Sessions 20-21 built Twitter content pipeline (Step 14 + quality gate). Session 22 proved the four-tier architecture, migrated tweets to Dino, launched rolling competition framework (Amendment 002), and excluded water parks from the pipeline. Session 23 relaxed the quality gate, diagnosed broken shadow run, and completed Priority Queue (Lightning Lane) research.

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
| PQ Research | `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md` in TPCR | Lightning Lane / Priority Queue complete landscape analysis |
| Dino briefings | `docs/briefings/` in operations | Cross-tier task assignments |

---

## Dino's Mac Mini Crontab (8 jobs)

| Time (ET) | Job | Status |
|-----------|-----|--------|
| 2:00 AM | Gazoo audit | ✅ Live |
| 4:00 AM | SSD daily report | ✅ Live |
| 6:00 AM | ACCORD intel brief | ✅ Live |
| 7:00 AM | Shadow run challenger (`shadow_run_challenger.py`) | ⚠️ BROKEN — path mismatches (Dino fixing) |
| 7:07 AM | WTI daily report | ✅ Live |
| 8:30 AM | WTI observed tweet | ✅ Live (quality gate relaxed S23) |
| 4:00 PM | Gazoo audit + WTI predicted tweet | ✅ Live (quality gate relaxed S23) |

wilma-server: Pipeline at 6 AM (compute only). Tweet crons DISABLED.

---

## Current State

- **Forecast scope:** ~47M predictions/day, 59,255 WTI park-dates through March 2028
- **Pipeline version:** V4 (governed by `PIPELINE_V4_DESIGN.md` + Amendments 001, 002)
- **Daily pipeline:** Running 6 AM ET on wilma-server, steps s01-s14, ~58-60 min, 13/13 passing daily
- **Accuracy:** Overall MAE 8.4, WTI MAE 6.9 (baseline, Mar 30)
- **Challenger:** `xgb-highLR` — shadow Day 4, but **zero comparison data** due to broken paths
- **Models:** 420 baseline, 433 total coverage, 109 on fallback
- **Twitter:** LIVE on @DisneyStatsWhiz — predicted + observed tweets posting daily (confirmed visible)
- **Quality gate:** Relaxed Session 23 (peer outlier 60%→90%, day-jump 15→25, staleness exact→24h)
- **Scraper:** Running (Restart=always)
- **Shadow run:** BROKEN — `rolling_shadow.py` has hardcoded `hypertuned_v1` paths instead of using challenger name, plus stale V3 baseline path. Dino briefed to fix.
- **Water parks:** BB/TL/VB excluded from ETL (TPCR #457)
- **Properties with WTI data:** 13 (WDW, DLR, Universal Orlando, Universal Hollywood, Tokyo Disney, Epic Universe)

---

## Session 23 Summary (2026-03-30)

### Barney (Tier 2):
1. Read SESSION_LOG, checked Discord #wti-pipeline (50 messages), reviewed commit history
2. **Priority Queue research:** Complete web research sweep on Lightning Lane system — current rules, tiers, pricing, public opinion, competitive landscape, data collection opportunities. Document ready for repo at `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md`
3. **Drafted reply to @TheHappyRecap** — methodology question about non-operational rides in WTI (screenshot from X)
4. **Tweet troubleshooting:** Diagnosed intermittent tweet failures — quality gate too strict was holding good content
5. **Committed quality gate relaxation** to `s14_content.py` (SHA `873a4027`) — peer outlier 60→90%, day-jump 15→25, staleness exact date→24h window
6. **Diagnosed broken shadow run:** `rolling_shadow.py` has 3 path bugs — hardcoded `hypertuned_v1` in forecast generation, hardcoded `hypertuned_v1` in archive paths, stale V3 baseline path `/mnt/data/`. Briefed Dino directly.
7. Updated SESSION_LOG

### Fred (Tier 1) — Decisions:
- Approved quality gate relaxation (~50%)
- Directed Priority Queue research as next data product after WTI competition stabilizes
- Confirmed "Priority Queue" as enterprise-wide term for all skip-the-line systems
- Sent shadow run fix directly to Dino

---

## In Progress

| Item | Status | Details |
|------|--------|---------|
| **Shadow run fix** | Dino briefed | 3 path bugs in `rolling_shadow.py`. Reset xgb-highLR for clean 7 days after fix. |
| **Quality gate relaxation** | ✅ Committed | Takes effect next pipeline run (tomorrow 6 AM). Wilma must `git pull`. |
| **PQ research doc** | Complete | Ready for commit to `docs/priority-queue/` in TPCR |
| **EU dimension fix** | Flagged | "Europa-Park" → "Epic Universe" across pipeline |
| **extract_daily_wti.py date bug** | Flagged | Predicted mode date logic wrong — workaround in place |

---

## Next Actions (Priority Order)

1. **Dino: Fix rolling_shadow.py paths** — 3 bugs identified. Reset shadow run after fix.
2. **Verify quality gate relaxation works** — check tomorrow's tweets post without holds
3. **Commit PQ research doc** to `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md` in TPCR
4. **Dino: Add challenger #2 from queue** — `xgb-dow` (day-of-week feature) per Amendment 002
5. **Reply to @TheHappyRecap** — methodology question about non-operational rides
6. **Fix EU dimension table** — "Europa-Park" → "Epic Universe"
7. **Multi-property tweets** — DLR + Universal Orlando ready. Design schedule.
8. **PQ data collection** — evaluate MDE scraper vs Thrill-Data partnership (5 open questions in research doc)

---

## Blockers

| Blocker | Impact | Resolution |
|---------|--------|------------|
| Shadow run path bugs | Zero competition data after 4 days | Dino fixing — reset shadow run after |

---

## Key Numbers

| Metric | Value | Updated |
|--------|-------|---------|
| Total predictions | ~47M/day | S20 |
| WTI park-dates | 59,255 | S23 |
| Forecast horizon | Through March 2028 | S1 |
| Overall MAE | 8.4 min | S23 |
| WTI MAE | 6.9 min | S23 |
| 1-Day MAE | 7.3 min | S23 |
| Baseline models | 420 | S23 |
| Fallback entities | 109 | S20 |
| Properties with WTI | 13 | S22 |
| Dino crons | 8 | S22 |
| Active challengers | 1 (broken, fixing) | S23 |
| Tweet success rate | ~70% → expected ~95%+ after gate fix | S23 |

---

## Decisions Log

| Date | Session | Decision | Who |
|------|---------|----------|-----|
| 2026-03-30 | 23 | Quality gate relaxed ~50%: peer 60→90%, day-jump 15→25, staleness 24h | Fred + Barney |
| 2026-03-30 | 23 | Priority Queue confirmed as enterprise-wide term for skip-the-line systems | Fred |
| 2026-03-30 | 23 | PQ research is next data product after WTI competition stabilizes | Fred |
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
| #453 | TPCR | Open | Competition — shadow run broken, Dino fixing paths |
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
- **Shadow run bug (S23):** `rolling_shadow.py` in operations repo has 3 path issues: (1) `generate_forecasts()` hardcodes `--challenger hypertuned_v1` instead of using challenger name, (2) `archive_predictions()` hardcodes `hypertuned_v1` in chal_src path, (3) `base_src` uses stale `/mnt/data/` V3 path instead of V4 `/home/wilma/hazeydata/pipeline/forecasts/all_forecasts.parquet`. All three must be fixed, then shadow run reset for clean 7 days.

---

## How to Start Next Session

1. Read this file (`SESSION_LOG.md` in `hazeydata/theme-park-crowd-report`)
2. Check if Dino fixed the shadow run paths — should see comparison data in Discord reports
3. Check @DisneyStatsWhiz — verify quality gate relaxation eliminated held tweets
4. Check `#wti-pipeline` for Dino's updates
5. Pick up from "Next Actions" above

---

*Shared project memory for WTI Pipeline. Updated every session. Git history preserves all versions.*
