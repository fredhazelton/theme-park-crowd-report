# Session Log

**Last updated:** 2026-04-05 by Barney (Session 28)
**Session:** 28
**Status:** Service status spam killed (65 msgs deleted, customer apology posted). Scraper fixed. Competition deployed with reference_date naming. Analytics cron fixed. Pipeline 13/13. Tweets posting. Daily Recap live.

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

**How we got here:** Pipeline evolved v1→v4. Sessions 20-21 built Twitter content pipeline (Step 14 + quality gate). Session 22 proved the four-tier architecture, migrated tweets to Dino, launched rolling competition framework (Amendment 002), and excluded water parks from the pipeline. Session 23 relaxed the quality gate, diagnosed broken shadow run, and completed Priority Queue (Lightning Lane) research. Session 24 (Dino solo): fixed shadow paths, tweet threading, intel brief dedup. Session 25: overhauled shadow evaluation methodology, designed + approved + built WDW Daily Recap blog product. Session 26: fixed all Gazoo audit findings (DuckDB lock Day 31, service status, analytics staleness, etc.), aligned shadow MAE averaging with s10 methodology. Session 27: fixed false service degradation (path mismatch), overhauled competition archive naming to reference_date convention, launched multi-challenger rollout per Amendment 002. Session 28: killed service status notification spam (65 msgs deleted from customer channel), fixed scraper (stale lock files), deployed competition system, fixed analytics cron, gained Barney bot access to TPCR customer Discord server.

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
- **service_status_manager.py DISABLED (S28):** Cron commented out (`#DISABLED_S28`). Was spamming customer announcements channel every 6-15 min by treating normal DuckDB WAL files as corruption. Do NOT re-enable until rebuilt with: (1) WAL files treated as normal, (2) edit-in-place instead of new posts, (3) rate limiting (max 1 status change/hour), (4) debounce (15 min before announcing degradation).
- **DuckDB WAL files are NORMAL (S28):** WAL = write-ahead log, created during any write operation. The scraper writes continuously, so a WAL file is almost always present. This is NOT corruption. Never auto-fix by moving/deleting WAL files.
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
| 7:00 AM | Shadow run (`rolling_shadow.py`) | ✅ Live — reference_date naming deployed S28 |
| 7:07 AM | WTI daily report | ✅ Live |
| 7:30 AM | **Analytics refresh** | ✅ FIXED S28 — absolute venv python path |
| 8:30 AM | WTI observed tweet | ✅ Live |
| 9:00 AM | **WDW Daily Recap** (`daily_recap_publish.py`) | ✅ Live — S25, proof-batched |
| 4:00 PM | Gazoo audit + WTI predicted tweet | ✅ Live |

wilma-server: Pipeline at 6 AM (compute only). 07:15 `update_pipeline_state.sh` (S27 fix). Tweet crons DISABLED. service_status_manager cron DISABLED S28 (`#DISABLED_S28`). Broken monthly conversion retrain cron REMOVED (s05 handles daily).

---

## Current State

- **Forecast scope:** ~46M predictions/day, 59,255 WTI park-dates through March 2028
- **Pipeline version:** V4 (governed by `PIPELINE_V4_DESIGN.md` + Amendments 001, 002, 003)
- **Daily pipeline:** Running 6 AM ET on wilma-server, steps s01-s14, ~59 min, 13/13 passing daily
- **Accuracy:** Overall MAE 8.4, WTI MAE 7.2, 1-Day MAE 7.3 (Apr 5)
- **Challengers:** `xgb-highLR` Day 1 (uses hypertuned_v1 module: eta 0.3, max_depth 6, n_estimators 500, inverse_freq weighting). Multi-challenger rollout pending — xgb-dow not yet trained.
- **Models:** 420 baseline, 433 total coverage, 109 on fallback
- **Twitter:** LIVE on @DisneyStatsWhiz — predicted + observed tweets posting daily, threading working
- **Blog:** WDW Daily Recap live — publishing daily since Apr 2
- **Quality gate:** Relaxed Session 23 (peer outlier 60%→90%, day-jump 15→25, staleness exact→24h)
- **Scraper:** FIXED S28 — stale lock files cleared, restarted, data flowing. PID 1759694.
- **Bot health:** Operational. TPCR bot running fine. gc-layer-validator disabled (not TPCR).
- **Service status manager:** DISABLED S28 — was spamming customer announcements with false "Service Restored" every 6-15 min. 65 spam messages deleted. Apology posted. Customer complaint answered. Needs full redesign before re-enabling.
- **Analytics:** FIXED S28 — cron updated to use absolute venv python path instead of `source .venv/bin/activate`. Manual run confirmed working.
- **Shadow run:** Deployed S28 — reference_date naming active, xgb-highLR Day 1 (no comparison data yet, expected). First evaluation Apr 6.
- **Water parks:** BB/TL/VB excluded from ETL — verified S26, TPCR #457 closed S27
- **Properties with WTI data:** 13 (WDW, DLR, Universal Orlando, Universal Hollywood, Tokyo Disney, Epic Universe)

---

## Session 28 Summary (2026-04-05)

### Barney (Tier 2):
1. Read SESSION_LOG, checked Discord #wti-pipeline (30 msgs), #barney-wilma-dev (15 msgs), #gazoo (15 msgs), #fred-wilma (10 msgs)
2. **Situational awareness:** Pipeline stable 13/13 (Apr 5). Scraper offline (Wilma killed it ~1 AM due to 400-500% CPU spinning). Competition S27 deploy may not have landed. Gazoo overnight 7.1/10: stale scraper lock file (HIGH), analytics cron broken Day 2 (HIGH), service status now operational.
3. **Scraper fix briefing:** `DINO_SHADOW_FIX_20260405.md` — 5 tasks: fix scraper (stale lock files), deploy competition changes, verify xgb-highLR module, pre-flight shadow run, fix analytics cron.
4. **Dino executed all 5 tasks** in 10 min: scraper running (0% idle CPU, stale locks were root cause), TPCR pulled (5 commits), old archives deleted, registry reset, xgb-highLR confirmed as hypertuned_v1 module, shadow run ready, analytics cron fixed (absolute venv python path).
5. **Investigated Fred's service interruption report:** Traced across #wti-pipeline, #fred-wilma, #gazoo. Root cause was `service_status_manager.py` — NOT actual service issues.
6. **Gained access to TPCR customer Discord server** — Barney bot added via OAuth2. Can now read customer-facing channels directly.
7. **Discovered service status spam disaster:** Read customer `#announcements` channel — **50+ identical "Service Restored" messages** in 15 hours, firing every 6-15 min. Customer .jeff318 complained in `#feedback`.
8. **Root cause analysis of spam:** `service_status_manager.py --auto` runs on cron every 3 min. It sees normal DuckDB WAL files (created by scraper writes), treats them as "corruption," moves WAL to `.bak`, re-checks (passes since WAL gone), posts NEW "Service Restored" message. Minutes later scraper creates new WAL. Repeat forever. Three bugs: (a) WAL ≠ corruption, (b) posts new messages instead of editing, (c) no debounce/rate limiting.
9. **Spam fix briefing:** `DINO_SERVICE_STATUS_SPAM_20260405.md` — disable cron, delete spam, post apology, respond to customer.
10. **Dino executed in 3 min:** Cron disabled (`#DISABLED_S28`), 65 spam messages deleted, apology posted to #announcements, response posted to .jeff318 in #feedback, 42 WAL backups cleaned, bot + scraper confirmed running.
11. **Verified customer channels clean:** #announcements now shows launch posts + apology only. #feedback has customer complaint + our response.

### Fred (Tier 1) — Decisions:
- Fix scraper and get 7 AM shadow run working
- Investigate recurring service interruptions on customer server
- Kill the service status spam immediately
- Added Barney bot to TPCR customer Discord server

### Dino (Tier 3) — Execution (two briefings, both complete):
- Briefing 1 (shadow fix): Scraper fixed, competition deployed, analytics cron fixed, shadow run Day 1 posted
- Briefing 2 (spam fix): Service status cron disabled, 65 spam messages deleted, apology posted, customer responded to, 42 WAL backups cleaned

---

## In Progress

| Item | Status | Details |
|------|--------|---------|
| **xgb-highLR evaluation** | Day 1 of 7 | Uses hypertuned_v1 module (combined hypothesis: eta 0.3, depth 6, 500 trees, inverse_freq). First comparison Apr 6. Promotion eligible ~Apr 12. |
| **Multi-challenger rollout** | Pending | xgb-dow not yet trained. Queue in `DINO_COMPETITION_RESET_20260404.md`. Need to train + register one per day. |
| **Service status manager redesign** | Disabled, needs rebuild | Must fix: WAL=normal, edit-in-place, debounce, rate limit. Do NOT re-enable the cron until redesigned. |
| **PQ research doc** | Needs commit | Ready for commit to `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md` in TPCR |
| **EU dimension fix** | Flagged | "Europa-Park" → "Epic Universe" across pipeline |
| **extract_daily_wti.py date bug** | Flagged | Predicted mode date logic wrong — workaround in place |
| **Refactor blog generators to use scheduler** | Pending | `generate_weekly_blog.py` and `daily_recap_publish.py` need to write to `scheduled/` |

---

## Next Actions (Priority Order)

1. **Train + register xgb-dow** — second challenger, day-of-week feature. Then one per day from the queue.
2. **Redesign service_status_manager.py** — needs proper architecture: WAL files normal, edit-in-place, debounce (15 min), rate limit (1/hour). Write design spec before implementing.
3. **xgb-highLR Day 7 evaluation** — ~Apr 12. Note: it's actually hypertuned_v1 (combined hypothesis), not just a learning rate change.
4. **Commit PQ research doc** to `docs/priority-queue/PRIORITY_QUEUE_RESEARCH.md` in TPCR
5. **Refactor TPCR blog generators to use scheduler**
6. **Fix EU dimension table** — "Europa-Park" → "Epic Universe"
7. **Multi-property tweets** — DLR + Universal Orlando ready. Design schedule.
8. **Daily Recap Phase 2** — add LLM narrative after template proven (~1 week of data)

---

## Blockers

- None currently. Service interruption investigation (S27 blocker) resolved — it was the service_status_manager spam.

---

## Key Numbers

| Metric | Value | Updated |
|--------|-------|---------|
| Total predictions | ~46M/day | S28 |
| WTI park-dates | 59,255 | S25 |
| Forecast horizon | Through March 2028 | S1 |
| Overall MAE | 8.4 min | S28 |
| WTI MAE | 7.2 min | S28 |
| 1-Day MAE | 7.3 min | S28 |
| Baseline models | 420 | S25 |
| Fallback entities | 109 | S20 |
| Properties with WTI | 13 | S22 |
| Dino crons | 10 | S26 |
| Active challengers | 1 (xgb-highLR/hypertuned_v1, Day 1) | S28 |
| Tweet success rate | High — posting daily, threading confirmed | S26 |
| Blog posts | 10 existing + daily recaps live (Apr 2+) | S26 |
| Gazoo composite | 7.1 | S27 |

---

## Decisions Log

| Date | Session | Decision | Who |
|------|---------|----------|-----|
| 2026-04-05 | 28 | **Disable service_status_manager.py** — cron commented out. Was spamming customer channel. Do not re-enable until redesigned. | Fred + Barney |
| 2026-04-05 | 28 | **DuckDB WAL files are normal** — never treat WAL as corruption. Never auto-move/delete WAL files. | Barney |
| 2026-04-05 | 28 | **Barney bot added to TPCR customer server** — can now monitor customer-facing channels (#announcements, #feedback) directly | Fred |
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
| 2026-04-01 | 25 | Daily Recap Phase 1: pure data/template, WDI only, 9 AM ET | Fred + Barney |
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
| #453 | TPCR | Open | Competition — archive naming deployed S28, multi-challenger pending |
| PR #1 | data-hub | Open | Firecrawl WDW park hours scraper |

---

## Agent Notes

- **Dino (Mac Mini):** Claude Code v2.1.84, Opus 4.6, Claude Max. `~/hazeydata/` repos. SSH to wilma@192.168.2.75. `bypassPermissions` enabled. Scripts at `~/hazeydata/operations/scripts/` and `~/hazeydata/scripts/`.
- **Dino communication:** Briefings committed as markdown to `operations/docs/briefings/` — Dino cannot receive task assignments via Discord. Write a prompt file for Fred to paste into Claude Code.
- **Wilma:** Does NOT know about Dino or v3.0 yet. Update when convenient. Her tweet crons are disabled (commented out, not deleted).
- **Twitter creds:** Mac Mini `~/.env`. Wilma-server `/home/wilma/.clawdbot/.env`.
- **Tweet state:** Mac Mini `~/hazeydata/reports/wti_daily/tweet_state.json`.
- **Pipeline output:** `/home/wilma/hazeydata/pipeline` on wilma-server.
- **Content JSONs:** `/home/wilma/hazeydata/pipeline/content/`.
- **Recap JSONs:** `/home/wilma/hazeydata/pipeline/content/recap_{date}.json` on wilma-server.
- **Shadow archives:** `{PIPELINE_BASE}/competition/shadow/{challenger_name}/` on wilma-server. **Named by reference_date (S27).**
- **Challenger registry (JSON):** `pipeline/competition/challenger_registry.json` on wilma-server. xgb-highLR uses module_name=hypertuned_v1.
- **Challenger modules (Python):** `pipeline/competition/challengers/` in TPCR repo. Only `hypertuned_v1.py` exists. New challengers need module files created here.
- **Baseline forecasts path:** `curves/forecast_parquet/all_forecasts.parquet` (from `config.py`).
- **Blog repo:** `hazeydata/hazeydata.ai` (master branch). Blog at `theme-park-crowd-report/blog/`. CSS: `blog.css` + `styles.css`.
- **Blog scheduling (SSD S23):** All blog posts should use the scheduler at `scheduled/` in hazeydata.ai.
- **Briefings:** `docs/briefings/` in operations repo — version-controlled cross-tier comms.
- **EU bug:** Epic Universe, NOT Europa-Park. Dimension table corrupted enterprise-wide. Fix pending.
- **Water parks:** BB/TL/VB filtered at ETL. No models, no forecasts, no tweets. Verified S26, #457 closed S27.
- **Shadow evaluation architecture (S25+S26+S27):** Evaluation logic lives in `pipeline/competition/shadow_evaluate.py` (TPCR). Uses identical SQL to `s10_accuracy.py`: ACTUAL wait_time_type, TIME_BUCKET with 2.5-min midpoint rounding, synthetic actuals fallback. **Entity-weighted MAE** (S26). **Reference_date naming** (S27): `--reference-date` CLI arg, archive files named `baseline_{reference_date}.parquet` = predictions FOR that date. Orchestrator (`rolling_shadow.py` in operations) calls it via SSH — never runs its own evaluation SQL.
- **Daily Recap architecture (S25):** `extract_daily_recap.py` (TPCR, wilma-server) queries pipeline data → JSON. `daily_recap_publish.py` (operations, Mac Mini) renders HTML, pushes to hazeydata.ai repo, posts Discord notification. Cron at 9 AM ET.
- **Service status manager (S28):** DISABLED. Cron on wilma-server commented out with `#DISABLED_S28`. Was running every 3 min, treating normal DuckDB WAL files as corruption, posting "Service Restored" to customer #announcements channel in an infinite loop. 65 spam messages deleted, apology posted, customer responded to. Needs full redesign: WAL=normal, edit-in-place, debounce, rate limit. See `DINO_SERVICE_STATUS_SPAM_20260405.md` for design notes.
- **TPCR customer Discord server:** Barney bot now has access (S28). Channel IDs: #announcements `1471935589371609162`, #feedback `1471935482513457266`. Guild ID `1471374656253591695`. Bot user ID `1471372989806411960`.
- **gc-layer-validator (S27):** Crashed 112K+ times (every 10 sec), disabled by Wilma. Code bug at line 243 of validation_bot.py. Not related to TPCR bot.

---

## How to Start Next Session

1. Read this file (`SESSION_LOG.md` in `hazeydata/theme-park-crowd-report`)
2. Check `#wti-pipeline` for pipeline status, shadow reports, tweet confirmations
3. Check `#gazoo` for audit score — expect improved score with scraper fixed + analytics cron fixed
4. Check TPCR customer `#announcements` (`1471935589371609162`) — confirm no new spam messages
5. Check shadow report — should show xgb-highLR Day 2+ with first comparison data
6. Train + register xgb-dow (next challenger from Amendment 002 queue)
7. Pick up from "Next Actions" above

---

*Shared project memory for WTI Pipeline. Updated every session. Git history preserves all versions.*
