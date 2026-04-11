# Session Log

**Last updated:** 2026-04-11 by Barney (Session 31 — opened)
**Session:** 31
**Status:** Recovery sweep. Critical scraper outage discovered (5 days dark). Dino briefing filed for 4 tasks. Pipeline forecast side healthy. Rolling competition has 5 days of data — early verdicts forming.

---

## Session 31 Summary (in progress)

S30 closed clean but the next 5 days exposed two regressions and surfaced one HQ-side cleanup ticket. Critical finding: TPCR #464, the live scraper, has been broken since the S30 DuckDB subprocess fix (commit `c4d11f2d`). Gazoo caught it Apr 7 16:00 ET. Nobody read Gazoo. ~5 days of stale bot data.

### Critical regression: TPCR #464 — Scraper dark for 5 days 🚨

Commit `c4d11f2d` (S30 DuckDB lock fix) introduced `NameError: name 'QUEUE_TIMES_PARK_MAP' is not defined` at `src/get_wait_times_from_queue_times.py` line 342. Scraper has failed every cycle since Apr 6 15:40 ET. By Gazoo's filing on Apr 7 16:00 ET it had 292 consecutive failures. By S31 open it's well over 1,400. Daily forecasts unaffected (CSV-based) but customer-facing bot has been serving rotten real-time data.

This is the root cause of the daily 100% fallback ratio alert in #wti-pipeline at 03:00 ET — it's not a model issue, it's a scraper-not-writing issue masquerading as one.

**Process failure:** S30 deployed a write-pattern change without watching downstream consumers. Rule 17 violation. Logged as a process note below.

### State of the world (Apr 11 morning)

**Pipeline (forecast side):** Healthy. Apr 7, 8, 9, 10 all 13/13 passed. MAE flat at 8.4 / WTI 7.2 / 1-Day 7.3. ~46M forecasts/day, 420 models, 271 entities. Tokyo s06 hourly-ratio fallback holding.

**Tweets:** Mostly clean. Apr 7 predicted tweet failed once (Twitter API error, recovered). Apr 10 observed tweet skipped — `observed_2026-04-09.json` not found AND SSH host key verification from Mac Mini to wilma failed. Filed as TPCR #465.

**Rolling competition (5 days of data):**
| Challenger | Day | Base | Chal | Delta | Trend |
|---|---|---|---|---|---|
| xgb-highLR | 6 | 8.6 | 11.1 | −2.5 | Losing every day. Discard at Day 7. |
| xgb-dow | 4 | 8.6 | 8.6 | ±0.0 | Flat. Day-of-week not adding signal. |
| xgb-deeper | 4 | 8.6 | 8.6 | ±0.0 | Flat. Depth 12 not helping. |
| xgb-recent | 4 | 8.2 | 8.2 → 8.0 | **+0.3** | **Only winner.** 365d half-life beats 730d. |

**Day 7 verdict for xgb-highLR is tomorrow (Apr 12) — already decided: discard.** xgb-recent hits Day 7 ~Apr 13 — that's the first real promotion candidate.

### HQ S12 carry-over (closed Apr 11)

Fred closed HQ Session 12 with 5 ops tickets filed against `hazeydata/operations`. Only one is in TPCR scope:

| Ticket | Repo | Title | TPCR action |
|---|---|---|---|
| ops #25 | operations | TPCR cleanup follow-up (post-SSD migration, data-hub `1c11980`) | **Yes — Task 3 of S31 Dino briefing** |
| ops #26 | operations | ACCORD repo dedup on wilma + Mac Mini | No (not TPCR) |
| ops #27 | operations | Hardcoded API keys in shell scripts (HIGH) | No (not TPCR, but worth flagging — may escalate) |
| ops #28 | operations | Continuous-loop guardrails policy (HIGH) | No (ops/governance) |
| ops #29 | operations | Hub-cleaning / subtraction discipline charter (Gazoo expansion) | No (Gazoo charter) |

### Tickets — Session 31

**Filed this session (2 new TPCR):**
| Ticket | What | Priority |
|---|---|---|
| TPCR #464 | Live scraper NameError since Apr 6 (filed by Gazoo Apr 7, just discovered now) | P0 |
| TPCR #465 | Apr 10 observed tweet failed — missing JSON + SSH host key | P1 |

**Open TPCR tickets: 2** (#464, #465 — both in Dino briefing)

### Documents Committed This Session
| Document | Repo |
|---|---|
| `docs/briefings/DINO_S31_TPCR_SWEEP_20260411.md` | operations |

### Decisions This Session
| Decision | Who |
|---|---|
| Discard xgb-highLR at Day 7 (already losing −2.5 by Day 6) | Barney (data-driven) |
| xgb-recent is the promotion candidate, but wait until its Day 7 (~Apr 13) | Barney |
| File Apr 10 observed tweet as #465 separate from #464 — likely independent | Barney |
| HQ ops tickets stay in ops repo, only ops #25 enters TPCR scope | Barney |

### Process Notes
- **S30 process failure (Rule 17):** DuckDB subprocess fix deployed without watching the scraper that uses the same module. 5 days of broken bot data. New rule for scraper/DB-touching changes: watch 3 consecutive successful cycles before declaring victory.
- **Read #gazoo daily.** Every Dino session and every Barney session must start by reading the latest Gazoo posts. #464 sat in Gazoo for 4 days and we missed it.
- **Rolling competition is paying off.** Within 4 days of running 4 challengers, we already know which hyperparameter levers help and which don't. xgb-recent (faster geo-decay) is the live signal.

---

## How to Start Next Session

1. Read this file
2. Check #wti-pipeline — verify Dino executed S31 briefing tasks (especially #464 closure)
3. Check #wti-pipeline shadow report for xgb-highLR Day 7 final number
4. Check #gazoo for any new findings (READ EVERY SESSION — see process note above)
5. Check TPCR open issues — should be 0 if Dino closes #464 and #465

## Next Actions (Priority Order)

1. **MONITOR Dino briefing execution** — especially Task 1 (#464 scraper fix). 3 successful scrape cycles required before close.
2. **xgb-highLR Day 7 verdict** — tomorrow Apr 12. Discard.
3. **xgb-recent Day 7 evaluation** — ~Apr 13. First promotion candidate. Decision required.
4. **Add challengers 5-7 from queue:** xgb-seasonal, xgb-narrow, xgb-moretrees (after #464 closed)
5. **Commit PQ research doc** to TPCR (carry-over from S30)
6. **Multi-property tweets** — DLR + Universal Orlando (carry-over from S30)

## Blockers

- **#464 must close before any new pipeline/scraper deploys.** No deploys on top of a broken scraper.

## Key Numbers

| Metric | Value | Updated |
|--------|-------|---------|
| Total predictions | ~46M/day | S31 |
| Overall MAE | 8.4 min | S31 (flat 5 days) |
| WTI MAE | 7.2 min | S31 |
| 1-Day MAE | 7.3 min | S31 |
| Active models | 420 | S31 |
| Active entities | 271 | S31 |
| Active challengers | 4 (xgb-highLR, xgb-dow, xgb-deeper, xgb-recent) | S31 |
| Daily pipeline status | 4/4 days clean since S30 fix | S31 |
| **Live scraper status** | **BROKEN since Apr 6 15:40 (#464)** | S31 |
| **Bot real-time data** | **STALE since Apr 6 15:40** | S31 |
| Tokyo s06 fallback | Holding | S31 |
| Open TPCR tickets | **2** (#464 P0, #465 P1) | S31 |
| HQ S12 carry-over (TPCR scope) | ops #25 only | S31 |

---

*Shared project memory for WTI Pipeline. Updated every session. Git history preserves all versions.*
