# Session Log

**Last updated:** 2026-04-11 by Barney (Session 32 — IN PROGRESS)
**Session:** 32
**Status:** #465 closed (Clawdbot duplicate disabled). Fallback alert root-caused as stale monitor (NOT a real outage). TPCR #467 pending Dino's DuckDB confirmation. xgb-highLR Day 7 verdict + ops #25 still queued.

---

## Session 32 Summary (in progress)

S32 opened with two surprises layered on S31's clean handoff:

1. The 03:00 ET Apr 11 data quality alert reported `HIGH_FALLBACK_RATIO: 89/89 entities (100%) using fallback predictions` — not in S31's log, looked alarming.
2. Gazoo's 06:02 ET audit was still pre-scraper-fix and showed Day 5 / 110h scraper outage. Created brief uncertainty about whether the S31 fix held.

Both resolved without firefighting.

### TPCR #465 — CLOSED ✅ (Dino Task 2)

Dino picked up the second-cron hunt where S31 paused. He found it: a **Clawdbot agent cron** named `wti-morning-observed` (ID `7533c73d-46ab-4c71-8ca1-4e9fe0119e6e`), AI-powered, fires 08:45 ET (15 min after the canonical Mac Mini cron). Failure history:
- Apr 10: SSH host key verification failed (separate `known_hosts` from wilma user) → posted #465 alert
- Apr 9: posted for **wrong date** `2026-03-25` instead of `2026-04-08` due to script hardcoding
- Multiple failure modes: SSH, dates, 403 on Twitter reply
- Costs Anthropic API credits per run (it's an AI agent, not a script)

**Decision:** Disable, not delete. Mac Mini `wti_observed_tweet.py` 08:30 ET cron remains as the sole observed-tweet poster.

**Resolution:** `clawdbot cron disable 7533c73d-46ab-4c71-8ca1-4e9fe0119e6e` ✅. Verified removed from active job list. #465 closed with full root cause + re-enable command preserved.

**Process win:** Dino stopped cleanly after Task 2 instead of chaining into Task 3. Same discipline that caught the near-miss in S31.

### TPCR #467 — Filed (pending Dino DuckDB confirmation)

The 100% fallback alert is **not** a real outage. Repo doc scan found the root cause:

`scripts/pipeline_data_completeness.py` line ~177 defines:
```python
trained_methods = {"model_actuals", "model_v2", "model_scope_scale", "model_lite"}
fallback_methods = {"fallback_ratio", "aggregate"}
```

Pipeline V4 renamed trained models from `model_v3.json` → `model_baseline.json` (per `PIPELINE_V4_DESIGN.md` Phase B). The actual V4 prediction_method name is NOT in `trained_methods`. Result: V4 baseline-trained entities are excluded from both numerator and denominator. The script computes 89/89 = 100% from the fallback subset alone.

**Confirming evidence (already in hand before Dino runs the query):**
- Daily pipeline reports: `Models: 420, Entities: 271` consistent for 5+ days
- MAE flat at 8.4 for 5+ days (impossible if 100% real fallback)
- 89 ≈ legitimate ~20-30% design fallback rate for entities without V4 models
- Same class of bug as #463/#464 (stale references after refactor)

**Dino Task 3 in flight:** Read-only DuckDB query to confirm exact V4 prediction_method name, then file TPCR #467 with the precise fix. Briefing: `operations/docs/briefings/DINO_S32_FALLBACK_ALERT_INVESTIGATION_20260411.md`. **Read-only investigation only — no script edits in this task.** Fix is a separate ticket → branch → PR cycle.

### Gazoo audit timing artifact (not a regression)

Gazoo's 09:06–09:07 ET messages in #gazoo still treated #464 as live and unfixed, citing 110h staleness and Day 5 outage. Initially looked like possible regression of S31's fix. Resolved as **memory-write artifact**: the 06:02 ET audit cycle fired before S31's 06:20 fix landed, and Gazoo's later diagnostic posts were finalizing memory from that pre-fix audit cycle. Scraper PID 943974 is still the canonical fix per S31 log. The 04:00 PM Apr 11 audit cycle will reflect reality. **No action needed** — but worth noting that Gazoo's audit cycles can lag real-world state by hours, which is itself an argument for #466 (real-time heartbeat alarm).

### #466 scope expansion (note for when we write the briefing)

Today's #465 finding adds a new requirement to #466's acceptance criteria: **duplicate-poster detection.** If two messages with similar content hit the same channel within a short window, alert. The Clawdbot duplicate cron was posting wrong dates publicly for who knows how long and nothing in our monitoring caught it.

### Tickets — Session 32

| Ticket | Action | Status |
|---|---|---|
| TPCR #465 | Closed (Clawdbot duplicate disabled, evidence in close comment) | ✅ CLOSED |
| TPCR #467 | Drafted, awaiting Dino DuckDB confirmation before filing | 🟡 PENDING |
| TPCR #466 | Still queued. Scope expanded: now includes duplicate-poster detection | 📋 OPEN |

**Open TPCR tickets at this snapshot: 1** (#466). Will become 2 once #467 is filed.

### Documents Committed This Session

| Document | Repo |
|---|---|
| `docs/briefings/DINO_S32_FALLBACK_ALERT_INVESTIGATION_20260411.md` | operations |

### Decisions This Session

| Decision | Who |
|---|---|
| Disable Clawdbot `wti-morning-observed` cron, not delete (preserve ID for re-enable) | Fred + Barney |
| Mac Mini `wti_observed_tweet.py` 08:30 ET is sole observed-tweet poster | Fred + Barney |
| Fallback alert is monitor bug, not pipeline outage — file as MEDIUM not CRITICAL | Barney |
| #466 scope expanded to include duplicate-poster detection | Barney |
| Always scan repo docs before assuming an alert is a real outage (new rule) | Barney |

### Process Notes (S32)

- **Repo doc scan beat panic.** The fallback alert looked like a 🚨 at first. A 30-second `search_code` for `HIGH_FALLBACK_RATIO` in the org found the source script in one hit, and reading it answered the question definitively — no Dino needed, no SSH session needed, no production state poking. Documentation as a debugging tool, not a publishing tool.
- **Dino's "stop and report" discipline holding across two consecutive sessions.** Task 2 stopped cleanly. This is the pattern that caught #465's near-miss in S31.
- **Gazoo audit lag is real.** Gazoo's two daily cycles (2 AM, 4 PM ET) mean its "current state" can be 8-10 hours stale. Don't trust Gazoo posts as real-time evidence of regression — verify directly.
- **Stale-list bugs are a recurring class.** #463 deleted `QUEUE_TIMES_PARK_MAP`, #464 was the symptom, #467 is the same pattern in a different file. Anywhere we have a hardcoded list of names that mirror something the pipeline produces, that list is a refactor landmine. Worth a sweep at some point.

---

## How to Start Session 33

1. Read this file
2. Read latest #gazoo posts (STANDING RULE)
3. Check #wti-pipeline for:
   - Apr 12 06:00 pipeline run (should be clean)
   - Apr 12 11:07 ET shadow report — **xgb-highLR Day 7 final number** (formal discard decision)
   - Apr 12 03:00 ET data quality alert — should still report 89/89 (until #467 fix lands)
4. Verify Dino reported back with TPCR #467 + DuckDB query output
5. Verify scraper still alive (PID 943974 or successor)

## Next Actions (Priority Order for S33)

1. **xgb-highLR Day 7 verdict** — Apr 12 11:07 ET shadow report. Formally discard. Update competition tracker.
2. **TPCR #467 fix** — file as separate ticket → branch → PR. One-line `trained_methods` set update. Wilma or Dino implements.
3. **ops #25** — TPCR cleanup follow-up from HQ S12 (still queued).
4. **TPCR #466** — heartbeat alarm + duplicate-poster detection. Briefing now writeable since #465 landscape is mapped.
5. **xgb-recent Day 7 evaluation** — ~Apr 13. First real promotion candidate. Needs Barney decision.
6. Stale-list audit sweep: any other hardcoded `*_methods` / `*_names` / `*_codes` sets that the pipeline writes to?
7. Carry-overs from S30: PQ research doc commit, multi-property tweets (DLR + UO).

## Blockers

- None. #465 closed unblocks #466 implementation.

## Key Numbers

| Metric | Value | Updated |
|--------|-------|---------|
| Total predictions | ~46M/day | S31 |
| Overall MAE | 8.4 min | S31 (flat 6+ days) |
| WTI MAE | 7.2 min | S31 |
| 1-Day MAE | 7.3 min | S31 |
| Active models | 420 | S31 |
| Active entities | 271 | S31 |
| Active challengers | 4 (highLR D6→D7 verdict pending, dow D5, deeper D5, recent D5) | S32 |
| Daily pipeline status | 6/6 days clean since S30 fix | S32 |
| Live scraper status | ✅ HEALTHY (PID 943974, S31 fix `35384bc8` holding) | S32 |
| Bot real-time data | ✅ FRESH | S32 |
| DuckDB live table name | `live_waits` (NOT `live_wait_times`) | S31 |
| Open TPCR tickets | **1** (#466), pending #467 = **2** | S32 |
| Fallback alert status | Known noisy monitor (TPCR #467 incoming), NOT real outage | S32 |

---

*Shared project memory for WTI Pipeline. Updated every session. Git history preserves all versions.*
