# Session Log

**Last updated:** 2026-04-02 by Barney (Session 26)
**Session:** 26
**Status:** All 8 Gazoo findings fixed. Shadow MAE averaging aligned with s10. Pipeline 13/13. Tweets posting. Daily Recap live. 10 Mac Mini crons.

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

**How we got here:** Pipeline evolved v1→v4. Sessions 20-21 built Twitter content pipeline (Step 14 + quality gate). Session 22 proved the four-tier architecture, migrated tweets to Dino, launched rolling competition framework (Amendment 002), and excluded water parks from the pipeline. Session 23 relaxed the quality gate, diagnosed broken shadow run, and completed Priority Queue (Lightning Lane) research. Session 24 (Dino solo): fixed shadow paths, tweet threading, intel brief dedup. Session 25: overhauled shadow evaluation methodology, designed + approved + built WDW Daily Recap blog product. Session 26: fixed all Gazoo audit findings (DuckDB lock Day 31, service status, analytics staleness, etc.), aligned shadow MAE averaging with s10 methodology.

**Key findings that still apply:**
- Archive filenames MUST contain `YYYY-MM-DD` dates with hyphens or the forecast evaluator silently skips them
- `systemd-run --scope --user` is mandatory for long-running pipeline processes on wilma-server
- Forecast end date must come from `get_forecast_end_date()`, never hardcoded
- The Quarry is **retired** as of Session 20 / Amendment 001
- EU entity = **Epic Universe** (Universal Orlando), NOT Europa-Park — dimension table fix pending
- Water parks (BB, TL, VB) **excluded from all pipeline processing** — ETL, training, forecasts, tweets
- **Shadow evaluation must use identical methodology to s10_accuracy.py** — evaluation logic lives in `pipeline/competition/shadow_evaluate.py` in TPCR, never in the orchestrator scripts
- **Shadow MAE uses entity-weighted averaging** (S26) — average of per-entity MAEs, not flat slot average. This matches how s10 computes entity_daily_accuracy. Slot-level MAE available as `slot_baseline_mae` / `slot_challenger_mae` for reference.
- **Blog repo:** `hazeydata/hazeydata.ai` (master branch), blog at `theme-park-crowd-report/blog/`
- **DuckDB scraper lock fix (S26):** Scraper patched with `gc.collect()` after `con.close()` to release DuckDB lock. WAL backups cleaned. Never hold DuckDB connections across sleep cycles.
- **Analytics refresh automated (S26):** 7:30 AM cron on wilma-server refreshes analytics JSONs after pipeline completes.

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

## Dino's Mac Mini Crontab (10 jobs)

| Time (ET) | Job | Status |
|-----------|-----|--------|
| 2:00 AM | Gazoo audit | ✅ Live |
| 4:00 AM | SSD daily report | ✅ Live |
| 6:00 AM | ACCORD intel brief | ✅ Live |
| 7:00 AM | Shadow run (`rolling_shadow.py`) | ✅ Live — entity-weighted MAE deployed S26 |
| 7:07 AM | WTI daily report | ✅ Live |
| 7:30 AM | **Analytics refresh** | ✅ Live — NEW S26, auto-refreshes analytics JSONs on wilma-server |
| 8:30 AM | WTI observed tweet | ✅ Live |
| 9:00 AM | **WDW Daily Recap** (`daily_recap_publish.py`) | ✅ Live — S25, proof-batched |
| 4:00 PM | Gazoo audit + WTI predicted tweet | ✅ Live |

wilma-server: Pipeline at 6 AM (compute only). Tweet crons DISABLED. Broken monthly conversion retrain cron REMOVED (s05 handles daily).

---

## Current State

- **Forecast scope:** ~46M predictions/day, 59,255 WTI park-dates through March 2028
- **Pipeline version:** V4 (governed by `PIPELINE_V4_DESIGN.md` + Amendments 001, 002, 003)
- **Daily pipeline:** Running 6 AM ET on wilma-server, steps s01-s14, ~59 min, 13/13 passing daily
- **Accuracy:** Overall MAE 8.4, WTI MAE 7.2, 1-Day MAE 7.3 (Apr 2)
- **Challenger:** `xgb-highLR` — shadow eval with entity-weighted MAE (S26 fix). Promotion eligible Apr 8.
- **Models:** 420 baseline, 433 total coverage, 109 on fallback
- **Twitter:** LIVE on @DisneyStatsWhiz — predicted + observed tweets posting daily, threading working
- **Blog:** WDW Daily Recap live — first real post published Apr 2 (MAE 7.2, AK spotlight +10.1)
- **Quality gate:** Relaxed Session 23 (peer outlier 60%→90%, day-jump 15→25, staleness exact→24h)
- **Scraper:** Running (Restart=always), DuckDB lock fix deployed S26
- **Bot health:** RESTORED S26 — DuckDB lock resolved (was Day 31), WAL backups cleaned, bot can read/write
- **Service status:** FIXED S26 — no longer reporting false degradation to customers
- **Analytics:** FRESH + AUTOMATED S26 — 7:30 AM cron refreshes daily
- **Shadow run:** Entity-weighted MAE fix deployed S26. Expect shadow baseline MAE ~8-9 (was ~17 due to slot-level averaging).
- **Water parks:** BB/TL/VB excluded from ETL — verified S26 (0 entities in live data)
- **Properties with WTI data:** 13 (WDW, DLR, Universal Orlando, Universal Hollywood, Tokyo Disney, Epic Universe)

---

## Session 26 Summary (2026-04-02)

### Barney (Tier 2):
1. Read SESSION_LOG, checked Discord #wti-pipeline (30 msgs), #barney-wilma-dev (15 msgs), #gazoo (30 msgs), recent commits
2. **Situational awareness:** Pipeline stable 13/13. Daily Recap first real post published (Apr 1 data, MAE 7.2, AK +10.1). Tweet threading confirmed working. Shadow reporting MAE ~17 (unexplained discrepancy vs pipeline 8.4).
3. **Gazoo audit review:** Read full Apr 2 audit (4 PM). Composite score 5.9/10. Three HIGHs stuck: DuckDB lock Day 31, analytics 3.4 days stale, service status inverted Day 23. Five MEDIUMs: clawdbot perms, screenshot push, water parks unassigned, conversion cron broken, zombie.
4. **Wrote comprehensive Dino briefing** — `docs/briefings/DINO_GAZOO_FIXES_20260402.md` in operations. 8 fixes in priority order with verification steps for each. Committed to GitHub.
5. **Dino executed all 8 fixes** within same session (~9 min). All verification checks pass. Posted report to #wti-pipeline.
6. **Shadow MAE discrepancy investigation:** Traced both code paths (shadow_evaluate.py vs s10_accuracy.py). Root cause: shadow used flat slot-level averaging (over-weights high-traffic entities), while s10 uses entity-weighted averaging (per-entity MAE first, then average across entities). Methodology (ACTUAL type, TIME_BUCKET, synthetic fallback) was correct — only the aggregation differed.
7. **Committed entity-weighted MAE fix** to `shadow_evaluate.py` in TPCR. Primary MAE now = average of per-entity MAEs. Slot-level MAE preserved as reference fields. No orchestrator changes needed.
8. **Dino confirmed deployment** — TPCR already pulled on wilma-server, `shadow_evaluate.py` verified importable. Live for Apr 3 shadow run.

### Fred (Tier 1) — Decisions:
- Fix all Gazoo findings with proper fixes via Dino (not band-aids)
- Align shadow MAE averaging before promotion decision (not after)

### Dino (Tier 3) — Execution:
- All 8 Gazoo fixes executed and verified:
  - Fix 1: DuckDB lock — scraper patched with gc.collect() after con.close(), 1,218 WAL backups cleaned
  - Fix 2: Service status — alert check log filename pattern corrected, now reports `status=ok`
  - Fix 3: Analytics — refreshed to current, 7:30 AM daily cron added
  - Fix 4: clawdbot.json — chmod 400 (was 444)
  - Fix 5: Screenshot git push — rebased diverged branch, conflict resolved
  - Fix 6: Conversion cron — removed broken monthly retrain (s05 handles daily)
  - Fix 7: Water parks — verified 0 BB/TL/VB entities in live data, TPCR #457 ready to close
  - Fix 8: Zombie — reaped via bot restart
- Shadow evaluate pull confirmed — TPCR pulled on wilma, module verified importable

---

## In Progress

| Item | Status | Details |
|------|--------|---------|
| **Shadow run entity-weighted eval** | Deployed, Day 1 results Apr 3 | Entity-weighted MAE fix live. Expect baseline ~8-9 (not ~17). |
| **xgb-highLR promotion** | Eligible Apr 8 | 7 clean days needed. Entity-weighted comparison starts Apr 3. |
| **PQ research doc** | Needs commit | Ready for commit to `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md` in TPCR |
| **EU dimension fix** | Flagged | "Europa-Park" → "Epic Universe" across pipeline |
| **TPCR #457 close** | Ready | Dino verified 0 water park entities. Just needs ticket closure. |
| **extract_daily_wti.py date bug** | Flagged | Predicted mode date logic wrong — workaround in place |

---

## Next Actions (Priority Order)

1. **Monitor shadow run Apr 3** — verify entity-weighted MAE produces baseline ~8-9 (not ~17)
2. **Close TPCR #457** — water park suppression verified by Dino S26
3. **xgb-highLR promotion decision** — Apr 8+ (Day 7). Review entity-level breakdown with entity-weighted MAE.
4. **Verify Gazoo score improvement** — next audit should jump from 5.9 to ~8+
5. **Commit PQ research doc** to `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md` in TPCR
6. **Dino: Add challenger #2** — `xgb-dow` (day-of-week feature) per Amendment 002 queue
7. **Fix EU dimension table** — "Europa-Park" → "Epic Universe"
8. **Multi-property tweets** — DLR + Universal Orlando ready. Design schedule.
9. **Daily Recap Phase 2** — add LLM narrative after template proven (~1 week of data)

---

## Blockers

None. All systems operational. Bot health restored. Analytics automated. Service status accurate.

---

## Key Numbers

| Metric | Value | Updated |
|--------|-------|---------|
| Total predictions | ~46M/day | S26 |
| WTI park-dates | 59,255 | S25 |
| Forecast horizon | Through March 2028 | S1 |
| Overall MAE | 8.4 min | S26 |
| WTI MAE | 7.2 min | S26 |
| 1-Day MAE | 7.3 min | S26 |
| Baseline models | 420 | S25 |
| Fallback entities | 109 | S20 |
| Properties with WTI | 13 | S22 |
| Dino crons | 10 | S26 (analytics refresh added) |
| Active challengers | 1 (entity-weighted eval starting) | S26 |
| Tweet success rate | High — posting daily, threading confirmed | S26 |
| Blog posts | 10 existing + daily recaps live (Apr 2+) | S26 |
| Gazoo composite | 5.9 → expect ~8+ next audit | S26 |

---

## Decisions Log

| Date | Session | Decision | Who |
|------|---------|----------|-----|
| 2026-04-02 | 26 | Shadow MAE must use entity-weighted averaging (match s10_accuracy) | Fred + Barney |
| 2026-04-02 | 26 | Fix all Gazoo findings with proper fixes, not band-aids | Fred |
| 2026-04-02 | 26 | DuckDB scraper: never hold write connections across sleep cycles | Barney |
| 2026-04-02 | 26 | Analytics refresh: automated 7:30 AM cron on wilma-server | Barney |
| 2026-04-02 | 26 | clawdbot.json: mode 400 (not 444) while gateway running | Barney |
| 2026-04-02 | 26 | Broken monthly conversion cron removed (s05 retrains daily) | Barney |
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
| #457 | TPCR | Ready to close | Water park suppression verified — 0 BB/TL/VB entities in live data (S26) |
| #453 | TPCR | Open | Competition — entity-weighted eval deployed, clean eval running |
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
- **Water parks:** BB/TL/VB filtered at ETL. No models, no forecasts, no tweets. Verified S26.
- **Shadow evaluation architecture (S25+S26):** Evaluation logic lives in `pipeline/competition/shadow_evaluate.py` (TPCR). Uses identical SQL to `s10_accuracy.py`: ACTUAL wait_time_type, TIME_BUCKET with 2.5-min midpoint rounding, synthetic actuals fallback. **Entity-weighted MAE** (S26): average of per-entity MAEs, not flat slot average. Slot-level MAE available as `slot_baseline_mae`/`slot_challenger_mae`. Orchestrator (`rolling_shadow.py` in operations) calls it via SSH — never runs its own evaluation SQL. `shadow_run_challenger.py` deprecated to a redirect wrapper.
- **Daily Recap architecture (S25):** `extract_daily_recap.py` (TPCR, wilma-server) queries pipeline data → JSON. `daily_recap_publish.py` (operations, Mac Mini) renders HTML, pushes to hazeydata.ai repo, posts Discord notification. Cron at 9 AM ET. Proof-batched Mar 29-31. First real post Apr 2.
- **DuckDB lock fix (S26):** Scraper patched with gc.collect() after con.close(). WAL backups cleaned. Bot health restored.
- **Service status fix (S26):** Alert check now reads correct pipeline log filename pattern. No longer reporting false degradation.
- **Analytics automation (S26):** 7:30 AM cron on wilma-server refreshes analytics JSONs. Previously manual/disabled.

---

## How to Start Next Session

1. Read this file (`SESSION_LOG.md` in `hazeydata/theme-park-crowd-report`)
2. Check shadow run report — should now show entity-weighted baseline MAE ~8-9 (not ~17)
3. Check `#wti-pipeline` for pipeline status, shadow reports, and tweet confirmations
4. Check `#gazoo` for audit score improvement (expect 5.9 → ~8+)
5. Check if Daily Recap published at 9 AM
6. Verify analytics data is fresh (7:30 AM auto-refresh)
7. Pick up from "Next Actions" above

---

*Shared project memory for WTI Pipeline. Updated every session. Git history preserves all versions.*
