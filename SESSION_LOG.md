# Session Log

**Last updated:** 2026-04-04 by Barney (Session 27)
**Session:** 27
**Status:** False degradation fixed. Competition system overhauled — archive naming by reference_date, multi-challenger rollout launched. Pipeline 13/13. Tweets posting. Daily Recap live.

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

**How we got here:** Pipeline evolved v1→v4. Sessions 20-21 built Twitter content pipeline (Step 14 + quality gate). Session 22 proved the four-tier architecture, migrated tweets to Dino, launched rolling competition framework (Amendment 002), and excluded water parks from the pipeline. Session 23 relaxed the quality gate, diagnosed broken shadow run, and completed Priority Queue (Lightning Lane) research. Session 24 (Dino solo): fixed shadow paths, tweet threading, intel brief dedup. Session 25: overhauled shadow evaluation methodology, designed + approved + built WDW Daily Recap blog product. Session 26: fixed all Gazoo audit findings (DuckDB lock Day 31, service status, analytics staleness, etc.), aligned shadow MAE averaging with s10 methodology. Session 27: fixed false service degradation (path mismatch), overhauled competition archive naming to reference_date convention, launched multi-challenger rollout per Amendment 002.

**Key findings that still apply:**
- Archive filenames MUST contain `YYYY-MM-DD` dates with hyphens or the forecast evaluator silently skips them
- `systemd-run --scope --user` is mandatory for long-running pipeline processes on wilma-server
- Forecast end date must come from `get_forecast_end_date()`, never hardcoded
- The Quarry is **retired** as of Session 20 / Amendment 001
- EU entity = **Epic Universe** (Universal Orlando), NOT Europa-Park — dimension table fix pending
- Water parks (BB, TL, VB) **excluded from all pipeline processing** — ETL, training, forecasts, tweets
- **Shadow evaluation must use identical methodology to s10_accuracy.py** — evaluation logic lives in `pipeline/competition/shadow_evaluate.py` in TPCR, never in the orchestrator scripts
- **Shadow MAE uses entity-weighted averaging** (S26) — average of per-entity MAEs, not flat slot average. This matches how s10 computes entity_daily_accuracy. Slot-level MAE available as `slot_baseline_mae` / `slot_challenger_mae` for reference.
- **Shadow archive naming convention (S27):** Files named by **reference_date** — the date predictions are FOR. `baseline_2026-04-05.parquet` = predictions FOR April 5. CLI uses `--reference-date`. No more mental arithmetic.
- **Blog repo:** `hazeydata/hazeydata.ai` (master branch), blog at `theme-park-crowd-report/blog/`
- **DuckDB scraper lock fix (S26):** Scraper patched with `gc.collect()` after `con.close()` to release DuckDB lock. WAL backups cleaned. Never hold DuckDB connections across sleep cycles.
- **Analytics refresh automated (S26):** 7:30 AM cron on wilma-server refreshes analytics JSONs after pipeline completes.
- **Service status path fix (S27):** `pipeline_state.json` at `/mnt/data/pipeline/state/` — permanent fix via `update_pipeline_state.sh` cron at 07:15. Both paths are same inode on wilma-server. 76 WAL backups cleaned.
- **gc-layer-validator (S27 note):** Crashed 112K+ times, disabled by Wilma. Not related to TPCR bot. Fix code if needed later.

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

## Blog Post Scheduling System (Added SSD S23, 2026-04-03)

**⚠️ NEW: All blog posts should use the scheduler instead of pushing directly to live directories.**

A scheduling system is deployed on `hazeydata/hazeydata.ai`:
- **Generator scripts** write posts + JSON manifests to `scheduled/` directory (not directly to blog dirs)
- **GitHub Actions workflow** (`.github/workflows/publish-scheduled.yml`) runs daily at 6 AM ET
- Posts whose `publish_date` has arrived are automatically moved to their target blog directory and the index is updated

**Manifest format** (write to `scheduled/{slug}.json`):
```json
{
  "publish_date": "2026-04-20",
  "post_file": "orlando-this-week-april-20-2026.html",
  "target_dir": "theme-park-crowd-report/blog",
  "index_card_html": "<a href=\"orlando-this-week-april-20-2026.html\" class=\"blog-card\">...card HTML...</a>"
}
```

**Impact on TPCR blog generators:**
- `generate_weekly_blog.py` (wilma-server) needs refactoring to write to `scheduled/` instead of directly to `theme-park-crowd-report/blog/`
- `daily_recap_publish.py` (Mac Mini) should also use the scheduler — generate recap HTML + manifest to `scheduled/`, let Actions publish on schedule
- The workflow + publish script are already deployed: `.github/workflows/publish-scheduled.yml` and `.github/scripts/publish_scheduled.py`

**Spec:** `data-hub/docs/SSD_WEEKLY_BLOG_SPEC.md` has the full design. SSD generator already refactored (SSD S23).

---

## Dino's Mac Mini Crontab (10 jobs)

| Time (ET) | Job | Status |
|-----------|-----|--------|
| 2:00 AM | Gazoo audit | ✅ Live |
| 4:00 AM | SSD daily report | ✅ Live |
| 6:00 AM | ACCORD intel brief | ✅ Live |
| 7:00 AM | Shadow run (`rolling_shadow.py`) | ✅ Live — reference_date naming deployed S27 |
| 7:07 AM | WTI daily report | ✅ Live |
| 7:30 AM | **Analytics refresh** | ✅ Live — S26 |
| 8:30 AM | WTI observed tweet | ✅ Live |
| 9:00 AM | **WDW Daily Recap** (`daily_recap_publish.py`) | ✅ Live — S25, proof-batched |
| 4:00 PM | Gazoo audit + WTI predicted tweet | ✅ Live |

wilma-server: Pipeline at 6 AM (compute only). 07:15 `update_pipeline_state.sh` (S27 fix). Tweet crons DISABLED. Broken monthly conversion retrain cron REMOVED (s05 handles daily).

---

## Current State

- **Forecast scope:** ~46M predictions/day, 59,255 WTI park-dates through March 2028
- **Pipeline version:** V4 (governed by `PIPELINE_V4_DESIGN.md` + Amendments 001, 002, 003)
- **Daily pipeline:** Running 6 AM ET on wilma-server, steps s01-s14, ~59 min, 13/13 passing daily
- **Accuracy:** Overall MAE 8.4, WTI MAE 7.2, 1-Day MAE 7.3 (Apr 4)
- **Challengers:** `xgb-highLR` reset to Day 0 (archive naming change). Multi-challenger rollout starting Apr 5.
- **Models:** 420 baseline, 433 total coverage, 109 on fallback
- **Twitter:** LIVE on @DisneyStatsWhiz — predicted + observed tweets posting daily, threading working
- **Blog:** WDW Daily Recap live — publishing daily since Apr 2
- **Quality gate:** Relaxed Session 23 (peer outlier 60%→90%, day-jump 15→25, staleness exact→24h)
- **Scraper:** Running (Restart=always), DuckDB lock fix deployed S26
- **Bot health:** Operational. gc-layer-validator was crashing (112K restarts), disabled — not TPCR bot.
- **Service status:** FIXED S27 — false degradation cleared, permanent cron fix deployed, 76 WAL backups cleaned
- **Analytics:** FRESH + AUTOMATED S26 — 7:30 AM cron refreshes daily
- **Shadow run:** BREAKING CHANGE S27 — archive files now named by reference_date. Old archives deleted. Evaluation window reset.
- **Water parks:** BB/TL/VB excluded from ETL — verified S26, TPCR #457 closed S27
- **Properties with WTI data:** 13 (WDW, DLR, Universal Orlando, Universal Hollywood, Tokyo Disney, Epic Universe)

---

## Session 27 Summary (2026-04-04)

### Barney (Tier 2):
1. Read SESSION_LOG, checked Discord #wti-pipeline (30 msgs), #barney-wilma-dev (15 msgs), #gazoo (15 msgs)
2. **Situational awareness:** Pipeline stable 13/13 (Apr 3+4). Shadow baseline MAE 15.0 (not the expected 8-9). Gazoo overnight audit 7.1/10: two new HIGHs (false degradation, WAL accumulation). Tweets threading correctly. Daily Recap publishing.
3. **False service degradation root cause:** Traced through `pipeline_state.py`, `pipeline_alert_check.py`, and `service_status_manager.py` (43KB). Root cause: path mismatch — pipeline writes state to `/home/wilma/hazeydata/pipeline/state/` but service_status_manager reads from `/mnt/data/pipeline/state/`. When the bridge cron fails, stale timestamps → false DEGRADED notice to customers.
4. **Wrote Dino briefing:** `DINO_SERVICE_STATUS_FIX_20260404.md` — 4 fixes in priority order with verification steps.
5. **Dino executed service status fix** — false degradation cleared, "Service Restored" posted, 76 WAL backups cleaned, permanent cron fix deployed (`update_pipeline_state.sh` at 07:15), hazeydata.ai repo synced, TPCR #457 closed.
6. **Shadow MAE analysis:** Single-day entity-weighted MAE (15.0) is inherently more volatile than pipeline's multi-date average (8.4). Not a bug — the relative comparison (challenger vs baseline on same day) is what matters for promotion. Entity count difference (~224 shadow vs 271 pipeline) also contributes.
7. **Competition system overhaul — archive naming:**
   - Old: `baseline_{run_date}.parquet` containing predictions for `run_date + 1` (confusing)
   - New: `baseline_{reference_date}.parquet` containing predictions FOR `reference_date` (filename = content)
   - Updated `shadow_evaluate.py` in TPCR: `--archive-date` → `--reference-date`, internal `eval_date` → `reference_date`
   - Updated `rolling_shadow.py` in operations: archive files named by reference_date, evaluate passes `--reference-date`
   - Both scripts now have comprehensive DATE SEMANTICS docstrings
8. **Multi-challenger rollout briefing:** `DINO_COMPETITION_RESET_20260404.md` — reset xgb-highLR, start adding one challenger per day from Amendment 002 queue (xgb-dow, xgb-deeper, xgb-recent, etc.)
9. **Possible service interruption** — Fred flagged additional Wilma messages about another TPCR service issue. Could not locate the specific message. To investigate next session.

### Fred (Tier 1) — Decisions:
- Fix customer-facing false degradation first
- Archive files should be named by reference_date (what the predictions are FOR)
- Reset xgb-highLR evaluation window (no promotions done yet, clean slate)
- Launch multi-challenger rollout per Amendment 002 — one new challenger per day

### Dino (Tier 3) — Execution:
- Service status fix: false degradation cleared, permanent 07:15 cron fix, 76 WAL backups cleaned, #457 closed
- Pending: competition system deploy (pull both repos, delete old archives, reset registry, train xgb-dow)

---

## In Progress

| Item | Status | Details |
|------|--------|---------|
| **Competition archive naming** | Code committed, deploy pending | BREAKING: both repos need pull before 7 AM Apr 5. Old archives deleted, registry reset. |
| **Multi-challenger rollout** | Briefing committed, starts Apr 5 | xgb-dow first, then one per day. Queue in `DINO_COMPETITION_RESET_20260404.md`. |
| **xgb-highLR** | Reset to Day 0 | New evaluation with reference_date naming starts Apr 5. Promotion eligible ~Apr 12. |
| **Possible service interruption** | Unresolved | Fred flagged Wilma messages about another issue. Message ID 1490083798245707969 not found in accessible channels. |
| **PQ research doc** | Needs commit | Ready for commit to `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md` in TPCR |
| **EU dimension fix** | Flagged | "Europa-Park" → "Epic Universe" across pipeline |
| **extract_daily_wti.py date bug** | Flagged | Predicted mode date logic wrong — workaround in place |
| **Refactor blog generators to use scheduler** | Pending | `generate_weekly_blog.py` and `daily_recap_publish.py` need to write to `scheduled/` |

---

## Next Actions (Priority Order)

1. **Investigate service interruption** — Fred flagged something from Wilma. Check all channels next session.
2. **Verify competition deploy** — confirm Dino pulled both repos, deleted old archives, reset registry before 7 AM Apr 5
3. **Verify xgb-dow trained + registered** — second challenger should appear in Apr 5 shadow report
4. **Continue daily challenger additions** — xgb-deeper (Apr 6), xgb-recent (Apr 7), xgb-narrow (Apr 8)
5. **xgb-highLR promotion decision** — ~Apr 12 (Day 7 with new naming)
6. **Commit PQ research doc** to `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md` in TPCR
7. **Refactor TPCR blog generators to use scheduler**
8. **Fix EU dimension table** — "Europa-Park" → "Epic Universe"
9. **Multi-property tweets** — DLR + Universal Orlando ready. Design schedule.
10. **Daily Recap Phase 2** — add LLM narrative after template proven (~1 week of data)

---

## Blockers

- **Possible service interruption** — needs investigation next session. May be false alarm or a channel Barney can't access.

---

## Key Numbers

| Metric | Value | Updated |
|--------|-------|---------|
| Total predictions | ~46M/day | S27 |
| WTI park-dates | 59,255 | S25 |
| Forecast horizon | Through March 2028 | S1 |
| Overall MAE | 8.4 min | S27 |
| WTI MAE | 7.2 min | S27 |
| 1-Day MAE | 7.3 min | S27 |
| Baseline models | 420 | S25 |
| Fallback entities | 109 | S20 |
| Properties with WTI | 13 | S22 |
| Dino crons | 10 | S26 |
| Active challengers | 1 (reset to Day 0, multi-challenger starting Apr 5) | S27 |
| Tweet success rate | High — posting daily, threading confirmed | S26 |
| Blog posts | 10 existing + daily recaps live (Apr 2+) | S26 |
| Gazoo composite | 7.1 (up from 5.9) | S27 |

---

## Decisions Log

| Date | Session | Decision | Who |
|------|---------|----------|-----|
| 2026-04-04 | 27 | **Archive files named by reference_date** — `baseline_2026-04-05.parquet` = predictions FOR Apr 5. Breaking change, both repos. | Fred + Barney |
| 2026-04-04 | 27 | **Reset xgb-highLR** — evaluation window cleared for clean start with new naming | Fred + Barney |
| 2026-04-04 | 27 | **Multi-challenger rollout NOW** — one per day from Amendment 002 queue, starting xgb-dow | Fred + Barney |
| 2026-04-04 | 27 | Fix customer-facing false degradation before other work | Fred |
| 2026-04-03 | SSD S23 | **Blog scheduling system deployed** — all blog generators should write to `scheduled/` with manifests, GitHub Actions publishes on date. Refactor TPCR generators. | Fred + Barney |
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
| #457 | TPCR | **CLOSED S27** | Water park suppression verified + closed by Dino |
| #453 | TPCR | Open | Competition — archive naming overhauled S27, multi-challenger starting |
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
- **Shadow archives:** `{PIPELINE_BASE}/competition/shadow/{challenger_name}/` on wilma-server. **Named by reference_date (S27).**
- **Challenger registry:** `pipeline/competition/challenger_registry.json` on wilma-server.
- **Baseline forecasts path:** `curves/forecast_parquet/all_forecasts.parquet` (from `config.py`).
- **Blog repo:** `hazeydata/hazeydata.ai` (master branch). Blog at `theme-park-crowd-report/blog/`. CSS: `blog.css` + `styles.css`.
- **Blog scheduling (SSD S23):** All blog posts should use the scheduler at `scheduled/` in hazeydata.ai.
- **Briefings:** `docs/briefings/` in operations repo — version-controlled cross-tier comms.
- **EU bug:** Epic Universe, NOT Europa-Park. Dimension table corrupted enterprise-wide. Fix pending.
- **Water parks:** BB/TL/VB filtered at ETL. No models, no forecasts, no tweets. Verified S26, #457 closed S27.
- **Shadow evaluation architecture (S25+S26+S27):** Evaluation logic lives in `pipeline/competition/shadow_evaluate.py` (TPCR). Uses identical SQL to `s10_accuracy.py`: ACTUAL wait_time_type, TIME_BUCKET with 2.5-min midpoint rounding, synthetic actuals fallback. **Entity-weighted MAE** (S26). **Reference_date naming** (S27): `--reference-date` CLI arg, archive files named `baseline_{reference_date}.parquet` = predictions FOR that date. Orchestrator (`rolling_shadow.py` in operations) calls it via SSH — never runs its own evaluation SQL.
- **Daily Recap architecture (S25):** `extract_daily_recap.py` (TPCR, wilma-server) queries pipeline data → JSON. `daily_recap_publish.py` (operations, Mac Mini) renders HTML, pushes to hazeydata.ai repo, posts Discord notification. Cron at 9 AM ET.
- **Service status fix (S27):** False degradation was caused by stale `pipeline_state.json` at `/mnt/data/pipeline/state/`. Permanent fix: `update_pipeline_state.sh` cron at 07:15. Both paths are same inode. 76 WAL backups cleaned. service_status_manager auto-fix creates WAL backups aggressively — consider disabling.
- **gc-layer-validator (S27):** Crashed 112K+ times (every 10 sec), disabled by Wilma. Code bug at line 243 of validation_bot.py. Not related to TPCR bot.

---

## How to Start Next Session

1. Read this file (`SESSION_LOG.md` in `hazeydata/theme-park-crowd-report`)
2. **Investigate service interruption** Fred flagged from Wilma — check all channels, try message ID 1490083798245707969
3. Verify competition deploy landed — both repos pulled, old archives deleted, registry reset
4. Check shadow report — should show xgb-highLR Day 1 + xgb-dow Day 1 (if trained)
5. Check `#wti-pipeline` for pipeline status, shadow reports, tweet confirmations
6. Check `#gazoo` for audit score
7. Verify Daily Recap published at 9 AM
8. Pick up from "Next Actions" above

---

*Shared project memory for WTI Pipeline. Updated every session. Git history preserves all versions.*
