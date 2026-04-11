# Session Log

**Last updated:** 2026-04-11 by Barney (Session 31 — CLOSED)
**Session:** 31
**Status:** Recovery sweep. Critical 5-day scraper outage discovered and fixed (#464 closed). 2 new tickets filed (#465, #466). #465 paused mid-investigation pending duplicate-job hunt. Pipeline forecast side healthy. Rolling competition reaching first verdicts.

---

## Session 31 Summary

S30 closed at "0 open tickets" but the live scraper had silently been broken for ~10 hours by then — and stayed broken for 4 days 14 hours total. Gazoo filed #464 on Apr 7 16:00 ET, nobody read #gazoo for 4 days. Customer-facing bot served stale wait times the entire time. Forecasts unaffected (CSV-based).

S31 was a full recovery sweep: discovered the outage, briefed Dino, closed #464, caught a near-miss premature close on #465, filed #466 as the structural fix, and queued ops #25 + xgb-highLR Day 7 verdict for S32.

### TPCR #464 — Live scraper fixed ✅ CLOSED

**Root cause:** S30 commit `c4d11f2d` (DuckDB lock fix) accidentally **deleted** the `QUEUE_TIMES_PARK_MAP` dict — the 13-entry park ID → code mapping. Not renamed, deleted. NameError on every scrape cycle from Apr 6 15:40 ET onward.

**Fix (Dino, commit `35384bc8`):** Restored `QUEUE_TIMES_PARK_MAP` verbatim. Restarted scraper under `systemd-run --scope --user` (PID 943974). Verified 3 successful consecutive scrape cycles + DuckDB freshness query showing 128 rows in last 30 min, latest `observed_at` 06:26:12.

**Schema discovery:** Table is `live_waits`, not `live_wait_times`. Logged for #466.

**Outage duration:** Apr 6 15:40 ET → Apr 11 06:20 ET = ~4d 14h. ~1,328 failed scrape cycles before fix.

### TPCR #465 — Apr 10 observed tweet failure 🟡 IN PROGRESS

Filed at session open. Symptoms: `observed_2026-04-09.json` not found + SSH host key verification failure to wilma at 12:45/12:46 ET.

Dino's first pass found that the **primary** observed-tweet cron (08:30 ET) worked fine on Apr 10 — Apr 9 tweet posted successfully at 12:30 ET (Tweet ID 2042580917487644761). He recommended close as "unable to reproduce."

**Barney pushed back.** The original alerts came from a **second** "WTI Observed Tweet" job that fires 15 minutes after the primary, with different message format. Two posters running on the same channel — one succeeded at 12:30, one failed at 12:45. Dino's `crontab -l | grep observed` only found the primary. The second job lives somewhere else (different crontab, systemd timer, Clawdbot schedule, or different user).

Comment posted on #465 with revised acceptance criteria. **Sent back for deeper investigation.** Carries to S32.

### TPCR #466 — Scraper freshness heartbeat alarm 📋 FILED

Filed during Task 1 verification. The class-level fix for the bug pattern that #464 represents. Three monitoring systems failed simultaneously to catch #464:
1. Bot health check reported `duckdb=healthy` based on "can connect" not "fresh data"
2. 03:00 ET data quality alert fired daily but had become noise
3. Gazoo's audit was filed but unread for 4 days

**Acceptance:** independent 10-min cron reads `SELECT max(observed_at) FROM live_waits`, alerts to #wti-pipeline if data is more than 15 min stale during operating hours. Bot health check rewired to fail loudly on staleness. Proof batch (Rule 17) required before install.

Architecture decision: **5-min cycle scraper stays.** Fred + Barney aligned. The cycle pattern is the right design — what's missing is monitoring, not architecture. Decision rationale documented in this session log for future reference.

### Rolling competition — first verdicts forming

5 days of shadow data now available:

| Challenger | Day | Base | Chal | Delta | Verdict |
|---|---|---|---|---|---|
| xgb-highLR | 6 | 8.6 | 11.1 | −2.5 | Losing every day. **Discard at Day 7 (Apr 12).** |
| xgb-dow | 4 | 8.6 | 8.6 | ±0.0 | Day-of-week feature flat. |
| xgb-deeper | 4 | 8.6 | 8.6 | ±0.0 | Depth 12 flat. |
| xgb-recent | 4 | 8.2 | 8.0 | **+0.3** | **Only winner.** 365d half-life beats 730d. Day 7 ~Apr 13. |

xgb-recent is the first real promotion candidate. Decision deferred to S32+ until its Day 7 hits.

### HQ S12 carry-over

Fred closed HQ Session 12 with 5 ops tickets. Only one in TPCR scope:

| Ticket | Status |
|---|---|
| ops #25 — TPCR cleanup follow-up (post-SSD migration) | ⏸️ Queued for S32 (Dino Task 3) |
| ops #26-29 (ACCORD dedup, API keys, loop guardrails, hub-cleaning charter) | Out of TPCR scope |

### Tickets — Session 31

| Ticket | Action | Status |
|---|---|---|
| TPCR #464 | Closed with full evidence | ✅ CLOSED |
| TPCR #465 | Filed at open, sent back for re-investigation mid-session | 🟡 IN PROGRESS |
| TPCR #466 | Filed during Task 1 (heartbeat alarm) | 📋 OPEN |

**Open TPCR tickets: 2** (#465, #466)

### Documents Committed This Session

| Document | Repo |
|---|---|
| `docs/briefings/DINO_S31_TPCR_SWEEP_20260411.md` | operations |
| Scraper fix `35384bc8` | theme-park-crowd-report |

### Decisions This Session

| Decision | Who |
|---|---|
| Keep 5-min cycle scraper architecture (don't revert to always-on) | Fred + Barney |
| File #466 as the structural fix for the #464 class of bug | Barney |
| Push back on Dino's premature #465 close — second job exists | Barney |
| Discard xgb-highLR at Day 7 (data-driven, already losing −2.5) | Barney |
| Defer xgb-recent promotion decision until its Day 7 (~Apr 13) | Barney |
| New process rule: every Barney session begins with #gazoo read | Barney |
| New process rule: scraper/DB infra changes require 3-cycle observation | Barney |

### Process Notes

- **Rule 17 violation in S30, recovered in S31.** S30 deployed DuckDB subprocess fix without watching the scraper that uses the same module. 4d 14h of customer-facing data outage. New rule logged: any change touching scraper or DB write paths requires 3 successful downstream cycles observed before declaring victory.
- **Read #gazoo every session.** #464 sat in Gazoo for 4 days. Every Barney + Dino session now opens with a #gazoo pull.
- **"Stop and report" discipline working.** Dino correctly stopped after Task 1 instead of chaining. Caught the near-miss on #465 because we got to review before he closed.
- **Rolling competition is paying off fast.** 4 challengers, 4-5 days of data, clear signal that 3 of 4 hypotheses don't work and 1 does. Evidence-based model selection in action.
- **Architecture rationale captured:** 5-min cycle scraper is correct because (a) eliminates lock conflicts by design, (b) cycle boundaries are natural alarm checkpoints, (c) memory pressure resets, (d) code deploys on next cycle. CPU and API cost are negligible vs always-on. The cost is operational complexity, paid by #466.

---

## How to Start Session 32

1. Read this file
2. Read latest #gazoo posts (NEW STANDING RULE)
3. Check #wti-pipeline for:
   - Apr 11 morning observed tweet at 08:30 ET (should fire clean)
   - Any 12:45 ET duplicate alert (the second job from #465)
   - Apr 12 shadow report at 11:07 ET — xgb-highLR Day 7 final number
4. Check Dino's progress on #465 second-job hunt (paused mid-session, may have continued autonomously)
5. Verify the scraper is still alive and writing (PID 943974 or successor)

## Next Actions (Priority Order for S32)

1. **#465** — finish second observed-tweet job hunt, identify, fix or remove
2. **xgb-highLR Day 7 verdict** — capture from Apr 12 11 AM shadow report, formally discard
3. **ops #25** — TPCR cleanup follow-up from HQ S12
4. **#466** — scraper heartbeat alarm implementation (briefing pending — write after #465 closes so we know schema/cron landscape)
5. **xgb-recent Day 7 evaluation** — ~Apr 13. First real promotion candidate. Decision needed.
6. **Add challengers 5-7** from queue: xgb-seasonal, xgb-narrow, xgb-moretrees (after #466 lands)
7. Carry-overs from S30: PQ research doc commit, multi-property tweets (DLR + UO)

## Blockers

- **#465 second-job hunt blocks #466 implementation.** Need to know full landscape of monitoring/posting jobs before adding another one.

## Key Numbers

| Metric | Value | Updated |
|--------|-------|---------|
| Total predictions | ~46M/day | S31 |
| Overall MAE | 8.4 min | S31 (flat 5+ days) |
| WTI MAE | 7.2 min | S31 |
| 1-Day MAE | 7.3 min | S31 |
| Active models | 420 | S31 |
| Active entities | 271 | S31 |
| Active challengers | 4 (highLR D6, dow D4, deeper D4, recent D4) | S31 |
| Daily pipeline status | 5/5 days clean since S30 fix | S31 |
| Live scraper status | ✅ HEALTHY (PID 943974, fixed `35384bc8`) | S31 |
| Bot real-time data | ✅ FRESH (1.16M rows total, 128 in last 30 min at fix time) | S31 |
| Live scraper outage | Apr 6 15:40 → Apr 11 06:20 (4d 14h, ~1,328 failed cycles) | S31 |
| Tokyo s06 fallback | Holding | S31 |
| DuckDB live table name | `live_waits` (NOT `live_wait_times`) | S31 |
| Open TPCR tickets | **2** (#465, #466) | S31 |
| HQ S12 carry-over (TPCR scope) | ops #25 only | S31 |

---

*Shared project memory for WTI Pipeline. Updated every session. Git history preserves all versions.*
