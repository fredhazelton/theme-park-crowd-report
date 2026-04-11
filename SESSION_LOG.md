# Session Log

**Last updated:** 2026-04-11 by Barney (Session 32 — CLOSED)
**Session:** 32
**Status:** #465 closed (Clawdbot duplicate disabled). #467 filed (stale monitor confirmed via DuckDB query). Fallback alert is NOT a real outage. xgb-highLR Day 7 verdict + ops #25 + #466 carry to S33.

---

## Session 32 Summary

S32 opened with two surprises layered on S31's clean handoff:

1. The 03:00 ET Apr 11 data quality alert reported `HIGH_FALLBACK_RATIO: 89/89 entities (100%) using fallback predictions` — not in S31's log, looked alarming.
2. Gazoo's 06:02 ET audit was still pre-scraper-fix and showed Day 5 / 110h scraper outage. Created brief uncertainty about whether the S31 fix held.

Both resolved without firefighting. The fallback alarm turned out to be a stale-monitor bug, not a forecast outage. The Gazoo audit was a memory-write artifact from the pre-fix audit cycle.

### TPCR #465 — CLOSED ✅ (Dino Task 2)

Dino picked up the second-cron hunt where S31 paused. Found it: a **Clawdbot agent cron** named `wti-morning-observed` (ID `7533c73d-46ab-4c71-8ca1-4e9fe0119e6e`), AI-powered, fires 08:45 ET (15 min after the canonical Mac Mini cron). Failure history:
- Apr 10: SSH host key verification failed (separate `known_hosts` from wilma user) → posted #465 alert
- Apr 9: posted for **wrong date** `2026-03-25` instead of `2026-04-08` due to script hardcoding
- Multiple failure modes: SSH, dates, 403 on Twitter reply
- Costs Anthropic API credits per run (it's an AI agent, not a script)

**Decision:** Disable, not delete. Mac Mini `wti_observed_tweet.py` 08:30 ET cron remains as the sole observed-tweet poster.

**Resolution:** `clawdbot cron disable 7533c73d-46ab-4c71-8ca1-4e9fe0119e6e` ✅. Verified removed from active job list. #465 closed with full root cause + re-enable command preserved.

### TPCR #467 — FILED ✅ (Dino Task 3)

The 100% fallback alert is **not** a real outage. Repo doc scan found the suspect, Dino's investigation of `s08_forecast.py` confirmed the smoking gun.

**Root cause:** `scripts/pipeline_data_completeness.py` line ~177 defines:
```python
trained_methods = {"model_actuals", "model_v2", "model_scope_scale", "model_lite"}
fallback_methods = {"fallback_ratio", "aggregate"}
```

Pipeline V4's `s08_forecast.py` actually writes **three** prediction_method names that aren't in the trained_methods set:
- `model_baseline` — V4 production (~180 entities)
- `model_legacy_actuals` — legacy fallback path still in use
- `model_legacy_v2` — legacy fallback path still in use

Result: V4 baseline-trained entities are excluded from both numerator and denominator. The script computes 89/89 = 100% from the legitimate-fallback subset alone (which is the ~25-35% design fallback rate per `PIPELINE_V4_DESIGN.md`).

**Confirming evidence:**
- Daily pipeline reports: `Models: 420, Entities: 271` consistent for 6+ days
- MAE flat at 8.4 for 6+ days (impossible if 100% real fallback)
- Dino direct grep of `s08_forecast.py` showed `method = "model_baseline"`, `method = "model_legacy_actuals"`, `method = "model_legacy_v2"`
- Same class of bug as #463/#464 (stale references after refactor)

**TPCR #467 filed**, assigned to Wilma on GitHub (not just labeled). Fix is one line: add the three V4 method names to `trained_methods`. Detailed fix comment posted to the issue with verification steps. Implementation is a separate ticket → branch → PR cycle.

**Note:** DuckDB query was blocked by running pipeline (PID 935880 holding the lock). Dino confirmed method names from source code instead — equally authoritative.

### Gazoo audit timing artifact (not a regression)

Gazoo's 09:06–09:07 ET messages in #gazoo still treated #464 as live and unfixed, citing 110h staleness. Initially looked like possible regression. Resolved as **memory-write artifact**: the 06:02 ET audit cycle fired before S31's 06:20 fix landed, and Gazoo's later diagnostic posts were finalizing memory from that pre-fix audit cycle. Scraper PID 943974 is the canonical fix per S31 log. **No action needed** — but worth noting that Gazoo's audit cycles can lag real-world state by hours.

### #466 scope expansion (queued for S33)

Today's #465 finding adds a new requirement to #466's acceptance criteria: **duplicate-poster detection.** If two messages with similar content hit the same channel within a short window, alert. The Clawdbot duplicate cron was posting wrong dates publicly for who knows how long and nothing in our monitoring caught it. Class-of-bug gap, not just an instance.

### Tickets — Session 32

| Ticket | Action | Status |
|---|---|---|
| TPCR #465 | Closed (Clawdbot duplicate disabled, evidence in close comment) | ✅ CLOSED |
| TPCR #467 | Filed (Wilma assigned, exact fix in comment) | 📋 OPEN |
| TPCR #466 | Scope expanded: now includes duplicate-poster detection | 📋 OPEN |

**Open TPCR tickets at session close: 2** (#466, #467)

### Documents Committed This Session

| Document | Repo |
|---|---|
| `docs/briefings/DINO_S32_FALLBACK_ALERT_INVESTIGATION_20260411.md` | operations |
| SESSION_LOG.md (this file, two updates) | theme-park-crowd-report |

### Decisions This Session

| Decision | Who |
|---|---|
| Disable Clawdbot `wti-morning-observed` cron, not delete (preserve ID for re-enable) | Fred + Barney |
| Mac Mini `wti_observed_tweet.py` 08:30 ET is sole observed-tweet poster | Fred + Barney |
| Fallback alert is monitor bug, not pipeline outage — file as MEDIUM not CRITICAL | Barney |
| Add ALL three missing V4 method names to `trained_methods`, not just `model_baseline` | Barney + Dino |
| #466 scope expanded to include duplicate-poster detection | Barney |
| Always scan repo docs before assuming an alert is a real outage (new rule) | Barney |
| Stale-list audit sweep added to S33 priorities | Barney |

### Process Notes (S32)

- **Repo doc scan beat panic.** The fallback alert looked like 🚨 at first. A 30-second `search_code` for `HIGH_FALLBACK_RATIO` in the org found the source script in one hit, and reading it answered the question definitively before sending Dino on a wild goose chase. Documentation as a debugging tool, not just a publishing tool. **New standing rule: scan repo docs before assuming any alert is a real outage.**
- **Dino's "stop and report" discipline holding across three consecutive sessions.** Tasks 2 and 3 both stopped cleanly without chaining. This is the pattern that caught #465's near-miss in S31 and kept S32 well-paced.
- **Gazoo audit lag is real.** Gazoo's two daily cycles (2 AM, 4 PM ET) mean its "current state" can be 8-10 hours stale. Don't trust Gazoo posts as real-time evidence of regression — verify directly. Itself an argument for #466 (real-time heartbeat alarm).
- **Stale-list bugs are a recurring class.** #463 deleted `QUEUE_TIMES_PARK_MAP`, #464 was the symptom, #467 is the same pattern in a different file with three names instead of one. Anywhere we have a hardcoded list of names that mirror something the pipeline writes, that list is a refactor landmine. Sweep queued for S33.
- **DuckDB lock is read-blocking, not just write-blocking.** Dino tried to query the forecasts table while the pipeline was running and got blocked by PID 935880. Worked around by reading source code instead. Worth knowing: read-only queries during pipeline execution are NOT safe to assume.

---

## How to Start Session 33

1. Read this file
2. Read latest #gazoo posts (STANDING RULE)
3. Scan repo docs before assuming any alert is real (NEW STANDING RULE)
4. Check #wti-pipeline for:
   - Apr 12 06:00 pipeline run (should be clean)
   - Apr 12 11:07 ET shadow report — **xgb-highLR Day 7 final number** (formal discard decision)
   - Apr 12 03:00 ET data quality alert — will still report 89/89 until #467 fix lands (expected noise)
5. Check whether Wilma picked up #467 and pushed a fix
6. Verify scraper still alive (PID 943974 or successor)

## Next Actions (Priority Order for S33)

1. **xgb-highLR Day 7 verdict** — Apr 12 11:07 ET shadow report. Formally discard. Update competition tracker.
2. **TPCR #467 implementation** — verify Wilma's PR (or write briefing if she hasn't picked it up). One-line `trained_methods` set update + verification run.
3. **ops #25** — TPCR cleanup follow-up from HQ S12 (still queued).
4. **TPCR #466** — heartbeat alarm + duplicate-poster detection. Briefing now writeable since #465 landscape is mapped.
5. **xgb-recent Day 7 evaluation** — ~Apr 13. First real promotion candidate. Needs Barney decision.
6. **Stale-list audit sweep** — grep both repos for `*_methods = {`, `*_codes = {`, `*_names = {` style hardcoded sets. Catch the next #464 preemptively. Fred-approved S32.
7. Carry-overs from S30: PQ research doc commit, multi-property tweets (DLR + UO).

## Blockers

- None. #465 closed unblocks #466 implementation. #467 fix is independent of everything else.

## Key Numbers

| Metric | Value | Updated |
|--------|-------|---------|
| Total predictions | ~46M/day | S31 |
| Overall MAE | 8.4 min | S31 (flat 6+ days) |
| WTI MAE | 7.2 min | S31 |
| 1-Day MAE | 7.3 min | S31 |
| Active models | 420 | S31 |
| Active entities | 271 | S31 |
| Active challengers | 4 (highLR D6→D7 verdict pending Apr 12, dow D5, deeper D5, recent D5) | S32 |
| Daily pipeline status | 6/6 days clean since S30 fix | S32 |
| Live scraper status | ✅ HEALTHY (PID 943974, S31 fix `35384bc8` holding) | S32 |
| Bot real-time data | ✅ FRESH | S32 |
| DuckDB live table name | `live_waits` (NOT `live_wait_times`) | S31 |
| V4 prediction_method names | `model_baseline`, `model_legacy_actuals`, `model_legacy_v2` (+ `fallback_ratio`, `aggregate`) | S32 |
| Open TPCR tickets | **2** (#466, #467) | S32 |
| Fallback alert status | Known noisy monitor (TPCR #467 filed), NOT real outage | S32 |
| Tokyo s06 fallback | Holding | S31 |

---

*Shared project memory for WTI Pipeline. Updated every session. Git history preserves all versions.*
