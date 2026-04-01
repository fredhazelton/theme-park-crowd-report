# Session Log

**Last updated:** 2026-04-01 by Barney (Session 25)
**Session:** 25
**Status:** Shadow evaluation overhauled. Pipeline stable 13/13. Tweets posting. xgb-highLR shadow resetting for clean 7 days.

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

**How we got here:** Pipeline evolved v1→v4. Sessions 20-21 built Twitter content pipeline (Step 14 + quality gate). Session 22 proved the four-tier architecture, migrated tweets to Dino, launched rolling competition framework (Amendment 002), and excluded water parks from the pipeline. Session 23 relaxed the quality gate, diagnosed broken shadow run, and completed Priority Queue (Lightning Lane) research. Session 24 (Dino solo): fixed shadow paths, tweet threading, intel brief dedup. Session 25: overhauled shadow evaluation methodology.

**Key findings that still apply:**
- Archive filenames MUST contain `YYYY-MM-DD` dates with hyphens or the forecast evaluator silently skips them
- `systemd-run --scope --user` is mandatory for long-running pipeline processes on wilma-server
- Forecast end date must come from `get_forecast_end_date()`, never hardcoded
- The Quarry is **retired** as of Session 20 / Amendment 001
- EU entity = **Epic Universe** (Universal Orlando), NOT Europa-Park — dimension table fix pending
- Water parks (BB, TL, VB) **excluded from all pipeline processing** — ETL, training, forecasts, tweets
- **Shadow evaluation must use identical methodology to s10_accuracy.py** — evaluation logic lives in `pipeline/competition/shadow_evaluate.py` in TPCR, never in the orchestrator scripts

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
| 7:00 AM | Shadow run (`rolling_shadow.py` or `shadow_run_challenger.py`) | ⚠️ NEEDS DEPLOY — new code committed, Dino must `git pull` both repos |
| 7:07 AM | WTI daily report | ✅ Live |
| 8:30 AM | WTI observed tweet | ✅ Live |
| 4:00 PM | Gazoo audit + WTI predicted tweet | ✅ Live |

wilma-server: Pipeline at 6 AM (compute only). Tweet crons DISABLED.

---

## Current State

- **Forecast scope:** ~46M predictions/day, 59,255 WTI park-dates through March 2028
- **Pipeline version:** V4 (governed by `PIPELINE_V4_DESIGN.md` + Amendments 001, 002)
- **Daily pipeline:** Running 6 AM ET on wilma-server, steps s01-s14, ~59 min, 13/13 passing daily
- **Accuracy:** Overall MAE 8.4, WTI MAE 7.1, 1-Day MAE 7.3 (Apr 1)
- **Challenger:** `xgb-highLR` — shadow run resetting for clean 7 days with corrected evaluation
- **Models:** 420 baseline, 433 total coverage, 109 on fallback
- **Twitter:** LIVE on @DisneyStatsWhiz — predicted + observed tweets posting daily, threading fixed
- **Quality gate:** Relaxed Session 23 (peer outlier 60%→90%, day-jump 15→25, staleness exact→24h)
- **Scraper:** Running (Restart=always)
- **Shadow run:** Evaluation overhauled Session 25. Old data used POSTED methodology (inflated MAE 16-17). New methodology matches s10_accuracy.py exactly. Needs deploy + reset.
- **Water parks:** BB/TL/VB excluded from ETL (TPCR #457)
- **Properties with WTI data:** 13 (WDW, DLR, Universal Orlando, Universal Hollywood, Tokyo Disney, Epic Universe)

---

## Session 25 Summary (2026-04-01)

### Barney (Tier 2):
1. Read SESSION_LOG, checked Discord #wti-pipeline (50 msgs), #barney-wilma-dev (20 msgs), recent commits in both repos
2. **Situational awareness:** Pipeline stable 13/13 daily. Shadow run fixed by Dino (S24) but producing inflated MAE. Tweets posting reliably. Tweet threading fix deployed Mar 31. Intel brief dedup deployed.
3. **Shadow run deep dive (Fred-directed):** Analyzed `rolling_shadow.py`, `shadow_run_challenger.py`, and `s10_accuracy.py` line by line. Found 4 methodology divergences causing shadow MAE ~16-17 vs pipeline MAE 8.4:
   - `wait_time_type = 'POSTED'` instead of `'ACTUAL'`
   - Floor-based time bucketing vs `TIME_BUCKET` with midpoint rounding
   - No synthetic actuals fallback
   - Residual stale paths in `shadow_run_challenger.py`
4. **Created `pipeline/competition/shadow_evaluate.py`** in TPCR — shared evaluation module using identical SQL patterns to `s10_accuracy.py`. Called via CLI.
5. **Rewrote `rolling_shadow.py`** in operations — removed all inline evaluation SQL, delegates to `shadow_evaluate.py` via SSH. Fixed baseline path.
6. **Deprecated `shadow_run_challenger.py`** — now a redirect wrapper to `rolling_shadow.py`.
7. **Briefed Dino** via #barney-wilma-dev with deployment steps.
8. Updated SESSION_LOG.

### Fred (Tier 1) — Decisions:
- Directed full shadow evaluation fix (no quick patches)
- Principle established: shadow run = same logic, different predictions. Evaluation methodology must live in one place.

---

## In Progress

| Item | Status | Details |
|------|--------|---------|
| **Shadow evaluation deploy** | Dino must deploy | `git pull` on both TPCR (wilma-server) and operations (Mac Mini). Reset challenger registry. |
| **Shadow run reset** | After deploy | Clear xgb-highLR daily_metrics and shadow_days. Clean 7 days with correct methodology. |
| **PQ research doc** | Needs commit | Ready for commit to `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md` in TPCR |
| **EU dimension fix** | Flagged | "Europa-Park" → "Epic Universe" across pipeline |
| **extract_daily_wti.py date bug** | Flagged | Predicted mode date logic wrong — workaround in place |

---

## Next Actions (Priority Order)

1. **Dino: Deploy shadow evaluation overhaul** — `git pull` both repos, reset challenger registry
2. **Monitor shadow run Apr 2-3** — verify new methodology produces comparison data with MAE consistent with pipeline (~8-9 range, not 16-17)
3. **Commit PQ research doc** to `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md` in TPCR
4. **Dino: Add challenger #2 from queue** — `xgb-dow` (day-of-week feature) per Amendment 002
5. **Fix EU dimension table** — "Europa-Park" → "Epic Universe"
6. **Multi-property tweets** — DLR + Universal Orlando ready. Design schedule.
7. **PQ data collection** — evaluate MDE scraper vs Thrill-Data partnership

---

## Blockers

| Blocker | Impact | Resolution |
|---------|--------|------------|
| Shadow evaluation deploy | No clean competition data until Dino deploys | Briefed via Discord, straightforward git pull + reset |

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
| Dino crons | 8 | S22 |
| Active challengers | 1 (resetting for clean eval) | S25 |
| Tweet success rate | High — posting daily since gate fix | S25 |

---

## Decisions Log

| Date | Session | Decision | Who |
|------|---------|----------|-----|
| 2026-04-01 | 25 | Shadow evaluation must use identical methodology to s10_accuracy.py — no divergent SQL | Fred + Barney |
| 2026-04-01 | 25 | Shadow evaluation logic lives in TPCR repo (`shadow_evaluate.py`), never in orchestrator scripts | Barney |
| 2026-04-01 | 25 | Old shadow data (3 days, POSTED methodology) discarded — reset for clean 7 days | Fred + Barney |
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
| #453 | TPCR | Open | Competition — shadow evaluation overhauled S25, needs deploy |
| PR #1 | data-hub | Open | Firecrawl WDW park hours scraper |

---

## Agent Notes

- **Dino (Mac Mini):** Claude Code v2.1.84, Opus 4.6, Claude Max. `~/hazeydata/` repos. SSH to wilma@192.168.2.75. `bypassPermissions` enabled. Scripts at `~/hazeydata/scripts/`.
- **Wilma:** Does NOT know about Dino or v3.0 yet. Update when convenient. Her tweet crons are disabled (commented out, not deleted).
- **Twitter creds:** Mac Mini `~/.env`. Wilma-server `/home/wilma/.clawdbot/.env`.
- **Tweet state:** Mac Mini `~/hazeydata/reports/wti_daily/tweet_state.json`.
- **Pipeline output:** `/home/wilma/hazeydata/pipeline` on wilma-server.
- **Content JSONs:** `/home/wilma/hazeydata/pipeline/content/`.
- **Shadow archives:** `{PIPELINE_BASE}/competition/shadow/{challenger_name}/` on wilma-server.
- **Challenger registry:** `pipeline/competition/challenger_registry.json` on wilma-server.
- **Baseline forecasts path:** `curves/forecast_parquet/all_forecasts.parquet` (from `config.py`).
- **Briefings:** `docs/briefings/` in operations repo — version-controlled cross-tier comms.
- **EU bug:** Epic Universe, NOT Europa-Park. Dimension table corrupted enterprise-wide. Fix pending.
- **Water parks:** BB/TL/VB filtered at ETL. No models, no forecasts, no tweets.
- **Shadow evaluation architecture (S25):** Evaluation logic lives in `pipeline/competition/shadow_evaluate.py` (TPCR). Uses identical SQL to `s10_accuracy.py`: ACTUAL wait_time_type, TIME_BUCKET with 2.5-min midpoint rounding, synthetic actuals fallback. Orchestrator (`rolling_shadow.py` in operations) calls it via SSH — never runs its own evaluation SQL. `shadow_run_challenger.py` deprecated to a redirect wrapper.

---

## How to Start Next Session

1. Read this file (`SESSION_LOG.md` in `hazeydata/theme-park-crowd-report`)
2. Check if Dino deployed the shadow evaluation overhaul — look for shadow reports with MAE ~8-9 (not 16-17)
3. Check `#wti-pipeline` for shadow reports and pipeline status
4. Verify tweets still posting on @DisneyStatsWhiz
5. Pick up from "Next Actions" above

---

*Shared project memory for WTI Pipeline. Updated every session. Git history preserves all versions.*
