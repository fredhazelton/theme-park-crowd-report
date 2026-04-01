# Session Log

**Last updated:** 2026-04-01 by Barney (Session 25 FINAL)
**Session:** 25
**Status:** Shadow eval fixed + deployed. Daily Recap APPROVED + built + cron live. Pipeline 13/13. Tweets posting. 9 Mac Mini crons.

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

**How we got here:** Pipeline evolved v1→v4. Sessions 20-21 built Twitter content pipeline (Step 14 + quality gate). Session 22 proved the four-tier architecture, migrated tweets to Dino, launched rolling competition framework (Amendment 002), and excluded water parks from the pipeline. Session 23 relaxed the quality gate, diagnosed broken shadow run, and completed Priority Queue (Lightning Lane) research. Session 24 (Dino solo): fixed shadow paths, tweet threading, intel brief dedup. Session 25: overhauled shadow evaluation methodology, designed + approved + built WDW Daily Recap blog product.

**Key findings that still apply:**
- Archive filenames MUST contain `YYYY-MM-DD` dates with hyphens or the forecast evaluator silently skips them
- `systemd-run --scope --user` is mandatory for long-running pipeline processes on wilma-server
- Forecast end date must come from `get_forecast_end_date()`, never hardcoded
- The Quarry is **retired** as of Session 20 / Amendment 001
- EU entity = **Epic Universe** (Universal Orlando), NOT Europa-Park — dimension table fix pending
- Water parks (BB, TL, VB) **excluded from all pipeline processing** — ETL, training, forecasts, tweets
- **Shadow evaluation must use identical methodology to s10_accuracy.py** — evaluation logic lives in `pipeline/competition/shadow_evaluate.py` in TPCR, never in the orchestrator scripts
- **Blog repo:** `hazeydata/hazeydata.ai` (master branch), blog at `theme-park-crowd-report/blog/`

**Foundational documents:**
| Document | Location | What |
|----------|----------|------|
| Pipeline V4 Design | `docs/PIPELINE_V4_DESIGN.md` in TPCR | The governing design spec |
| V4 Amendment 001 | `docs/V4_AMENDMENT_001_CONTENT_PIPELINE.md` in TPCR | Step 14 content pipeline + quality gate |
| V4 Amendment 002 | `docs/V4_AMENDMENT_002_ROLLING_COMPETITION.md` in TPCR | Rolling competition framework (APPROVED) |
| V4 Amendment 003 | `docs/V4_AMENDMENT_003_DAILY_RECAP.md` in TPCR | WDW Daily Recap blog product (APPROVED) |
| REDESIGN.md v3.0 | `docs/REDESIGN.md` in operations | Four-tier enterprise architecture |
| PQ Research | `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md` in TPCR | Lightning Lane / Priority Queue complete landscape analysis |
| Dino briefings | `docs/briefings/` in operations | Cross-tier task assignments |

---

## Dino's Mac Mini Crontab (9 jobs)

| Time (ET) | Job | Status |
|-----------|-----|--------|
| 2:00 AM | Gazoo audit | ✅ Live |
| 4:00 AM | SSD daily report | ✅ Live |
| 6:00 AM | ACCORD intel brief | ✅ Live |
| 7:00 AM | Shadow run (`rolling_shadow.py`) | ✅ Live — overhauled S25, deployed, registry reset |
| 7:07 AM | WTI daily report | ✅ Live |
| 8:30 AM | WTI observed tweet | ✅ Live |
| 9:00 AM | **WDW Daily Recap** (`daily_recap_publish.py`) | ✅ Live — NEW S25, proof-batched, cron added |
| 4:00 PM | Gazoo audit + WTI predicted tweet | ✅ Live |

wilma-server: Pipeline at 6 AM (compute only). Tweet crons DISABLED.

---

## Current State

- **Forecast scope:** ~46M predictions/day, 59,255 WTI park-dates through March 2028
- **Pipeline version:** V4 (governed by `PIPELINE_V4_DESIGN.md` + Amendments 001, 002, 003)
- **Daily pipeline:** Running 6 AM ET on wilma-server, steps s01-s14, ~59 min, 13/13 passing daily
- **Accuracy:** Overall MAE 8.4, WTI MAE 7.1, 1-Day MAE 7.3 (Apr 1)
- **Challenger:** `xgb-highLR` — shadow reset for clean 7 days with corrected ACTUAL methodology. Promotion eligible Apr 8.
- **Models:** 420 baseline, 433 total coverage, 109 on fallback
- **Twitter:** LIVE on @DisneyStatsWhiz — predicted + observed tweets posting daily, threading fixed
- **Blog:** WDW Daily Recap cron live at 9:00 AM ET. First real post publishes Apr 2.
- **Quality gate:** Relaxed Session 23 (peer outlier 60%→90%, day-jump 15→25, staleness exact→24h)
- **Scraper:** Running (Restart=always)
- **Shadow run:** Evaluation overhauled + deployed S25. Delegated to `shadow_evaluate.py` (TPCR). Registry reset. Clean Day 1 starts Apr 2.
- **Water parks:** BB/TL/VB excluded from ETL (TPCR #457)
- **Properties with WTI data:** 13 (WDW, DLR, Universal Orlando, Universal Hollywood, Tokyo Disney, Epic Universe)

---

## Session 25 Summary (2026-04-01)

### Barney (Tier 2):
1. Read SESSION_LOG, checked Discord #wti-pipeline (50 msgs), #barney-wilma-dev (20 msgs), recent commits in both repos
2. **Situational awareness:** Pipeline stable 13/13 daily. Shadow run fixed by Dino (S24) but producing inflated MAE (16-17 vs pipeline 8.4). Tweets posting reliably. Tweet threading fix deployed Mar 31.
3. **Shadow run deep dive (Fred-directed):** Found 4 methodology divergences in shadow evaluation vs s10_accuracy.py. Created shared `shadow_evaluate.py` module in TPCR, rewrote `rolling_shadow.py` in operations, deprecated `shadow_run_challenger.py`.
4. **Dino deployed shadow eval overhaul** — git pull both repos, registry reset, import verified (all within session).
5. **V4 Amendment 003: WDW Daily Recap** — Fred spotted AK +15.1 miss on Twitter and asked for daily blog post analyzing predicted-vs-observed gaps. Designed full spec: park scorecard, entity-level spotlight, closure detection, pattern classification. Pure data/template Phase 1. Blog lives in `hazeydata/hazeydata.ai` repo.
6. **Fred approved Amendment 003** — committed as APPROVED.
7. **Dino built + deployed Daily Recap** — both scripts (extract + publish), proof-batched 3 historical dates (Mar 29-31), caught and fixed overnight closure false positives, added system cron at 9 AM ET. All within same session.

### Fred (Tier 1) — Decisions:
- Shadow evaluation: full fix, no quick patches. Evaluation methodology lives in one place.
- Daily Recap approved: pure data/template Phase 1, WDW only, publish to hazeydata.ai blog.
- Approved proof batch output → cron added.

### Dino (Tier 3) — Execution:
- Deployed shadow eval overhaul (4 steps, 32 seconds)
- Built `extract_daily_recap.py` (TPCR, wilma-server) — DuckDB queries matching s10_accuracy.py methodology
- Built `daily_recap_publish.py` (operations, Mac Mini) — 606 lines, SSH orchestration, HTML rendering, blog index update, git push, Discord notification
- Proof batch: Mar 29 (MAE 4.9, AK +8.4), Mar 30 (MAE 7.6, AK +15.4, 1 closure: Character Landing 95m), Mar 31 (MAE 7.1, AK +12.6)
- System cron added at 9:00 AM ET

---

## In Progress

| Item | Status | Details |
|------|--------|---------|
| **Shadow run clean eval** | Day 1 starts Apr 2 | Corrected ACTUAL methodology. First comparison Apr 3. Promotion eligible Apr 8. |
| **Daily Recap first real post** | Apr 2 at 9 AM | Recap for Apr 1 reference date publishes to hazeydata.ai blog |
| **PQ research doc** | Needs commit | Ready for commit to `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md` in TPCR |
| **EU dimension fix** | Flagged | "Europa-Park" → "Epic Universe" across pipeline |
| **extract_daily_wti.py date bug** | Flagged | Predicted mode date logic wrong — workaround in place |

---

## Next Actions (Priority Order)

1. **Monitor Daily Recap Apr 2** — verify first real post publishes correctly to hazeydata.ai
2. **Monitor shadow run Apr 2-3** — verify corrected methodology produces MAE ~8-9 (not 16-17)
3. **xgb-highLR promotion decision** — Apr 8 (Day 7+). Review entity-level breakdown.
4. **Commit PQ research doc** to `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md` in TPCR
5. **Dino: Add challenger #2** — `xgb-dow` (day-of-week feature) per Amendment 002 queue
6. **Fix EU dimension table** — "Europa-Park" → "Epic Universe"
7. **Multi-property tweets** — DLR + Universal Orlando ready. Design schedule.
8. **Daily Recap Phase 2** — add LLM narrative after template proven (~1 week of data)

---

## Blockers

None. All systems operational.

---

## Key Numbers

| Metric | Value | Updated |
|--------|-------|---------|
| Total predictions | ~46M/day | S25 |
| WTI park-dates | 59,255 | S25 |
| Forecast horizon | Through March 2028 | S1 |
| Overall MAE | 8.4 min | S25 |
| WTI MAE | 7.1 min | S25 |
| 1-Day MAE | 7.3 min | S25 |
| Baseline models | 420 | S25 |
| Fallback entities | 109 | S20 |
| Properties with WTI | 13 | S22 |
| Dino crons | 9 | S25 |
| Active challengers | 1 (clean eval restarting) | S25 |
| Tweet success rate | High — posting daily since gate fix | S25 |
| Blog posts | 10 existing + daily recaps starting Apr 2 | S25 |

---

## Decisions Log

| Date | Session | Decision | Who |
|------|---------|----------|-----|
| 2026-04-01 | 25 | V4 Amendment 003 approved: WDW Daily Recap blog product | Fred + Barney |
| 2026-04-01 | 25 | Daily Recap Phase 1: pure data/template, WDW only, 9 AM ET | Fred + Barney |
| 2026-04-01 | 25 | Blog publishes to hazeydata/hazeydata.ai repo (master branch) | Barney |
| 2026-04-01 | 25 | Shadow evaluation must use identical methodology to s10_accuracy.py | Fred + Barney |
| 2026-04-01 | 25 | Shadow evaluation logic lives in TPCR repo (`shadow_evaluate.py`) | Barney |
| 2026-04-01 | 25 | Old shadow data (3 days, POSTED methodology) discarded | Fred + Barney |
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
| #453 | TPCR | Open | Competition — shadow eval overhauled + deployed, clean eval running |
| PR #1 | data-hub | Open | Firecrawl WDW park hours scraper |

---

## Agent Notes

- **Dino (Mac Mini):** Claude Code v2.1.84, Opus 4.6, Claude Max. `~/hazeydata/` repos. SSH to wilma@192.168.2.75. `bypassPermissions` enabled. Scripts at `~/hazeydata/operations/scripts/` and `~/hazeydata/scripts/`.
- **Wilma:** Does NOT know about Dino or v3.0 yet. Update when convenient. Her tweet crons are disabled (commented out, not deleted).
- **Twitter creds:** Mac Mini `~/.env`. Wilma-server `/home/wilma/.clawdbot/.env`.
- **Tweet state:** Mac Mini `~/hazeydata/reports/wti_daily/tweet_state.json`.
- **Pipeline output:** `/home/wilma/hazeydata/pipeline` on wilma-server.
- **Content JSONs:** `/home/wilma/hazeydata/pipeline/content/`.
- **Recap JSONs:** `/home/wilma/hazeydata/pipeline/content/recap_{date}.json` on wilma-server.
- **Shadow archives:** `{PIPELINE_BASE}/competition/shadow/{challenger_name}/` on wilma-server.
- **Challenger registry:** `pipeline/competition/challenger_registry.json` on wilma-server.
- **Baseline forecasts path:** `curves/forecast_parquet/all_forecasts.parquet` (from `config.py`).
- **Blog repo:** `hazeydata/hazeydata.ai` (master branch). Blog at `theme-park-crowd-report/blog/`. CSS: `blog.css` + `styles.css`.
- **Briefings:** `docs/briefings/` in operations repo — version-controlled cross-tier comms.
- **EU bug:** Epic Universe, NOT Europa-Park. Dimension table corrupted enterprise-wide. Fix pending.
- **Water parks:** BB/TL/VB filtered at ETL. No models, no forecasts, no tweets.
- **Shadow evaluation architecture (S25):** Evaluation logic lives in `pipeline/competition/shadow_evaluate.py` (TPCR). Uses identical SQL to `s10_accuracy.py`: ACTUAL wait_time_type, TIME_BUCKET with 2.5-min midpoint rounding, synthetic actuals fallback. Orchestrator (`rolling_shadow.py` in operations) calls it via SSH — never runs its own evaluation SQL. `shadow_run_challenger.py` deprecated to a redirect wrapper.
- **Daily Recap architecture (S25):** `extract_daily_recap.py` (TPCR, wilma-server) queries pipeline data → JSON. `daily_recap_publish.py` (operations, Mac Mini) renders HTML, pushes to hazeydata.ai repo, posts Discord notification. Cron at 9 AM ET. Proof-batched Mar 29-31.

---

## How to Start Next Session

1. Read this file (`SESSION_LOG.md` in `hazeydata/theme-park-crowd-report`)
2. Check if Daily Recap published at 9 AM — look at hazeydata.ai/theme-park-crowd-report/blog/
3. Check shadow run reports — should show MAE ~8-9 with corrected ACTUAL methodology (not 16-17)
4. Check `#wti-pipeline` for pipeline status and shadow reports
5. Verify tweets still posting on @DisneyStatsWhiz
6. Pick up from "Next Actions" above

---

*Shared project memory for WTI Pipeline. Updated every session. Git history preserves all versions.*
