# Session Log

**Last updated:** 2026-04-25 by Barney (Session 36 — IN PROGRESS)
**Status:** Production healthy. 6-feat baseline live (Day 2). #466 watchdog shipped + first real fire (recovered). ops #27 closed. #470 follow-up PR queued for Apr 26 (3-clean-day gate).

> **Structure (ops #30):** Current state here (≤5 KB). Previous sessions in `SESSION_LOG_ARCHIVE.md`. Stable reference in `PROJECT_REFERENCE.md`. Vision/history in `PROJECT_BACKGROUND.md`.

---

## Current State

| Area | Status |
|---|---|
| Daily pipeline | ✅ Apr 25 clean (13/13, 57m22s). Day 2 of 6-feat baseline. |
| Overall MAE | 8.3 (entity, 73 dates / 276 entities) |
| WTI MAE | 6.7 (69 dates / 800 park-dates) |
| 1-Day MAE | 7.4 |
| Models / Entities | 420 baseline / 276 evaluated (433 baseline + 97 fallback per s14 diag) |
| Scraper | ✅ HEALTHY (PID 943974, 13.8d uptime). Watchdog LIVE. |
| Bot real-time data | ✅ FRESH |
| Active challengers | 3 (xgb-dow Day 19 +0.2, xgb-deeper +0.1, xgb-recent +0.1 vs new 6-feat baseline) |
| Tweet system | ✅ 8/8 last 4 days (predicted 20:00, observed 12:30) |
| s07_training.py | ✅ 6-feat baseline (`bba5775` via PR #475). Day 2 stable. |
| Watchdog | ✅ LIVE. First real fire today 11:00 ET (9-min stale, recovered). |

## Last Session (S35 — closed 2026-04-25, 10-day span Apr 15-25)

S35 ran across ~10 calendar days as multiple HQ Barney instances (HQ S20-S23) executing the S34 queue — log refresh was deferred until S36 catch-up. Five tickets closed: #466 (scraper watchdog, PR #476+#478, first real fire today), #468 (tweet cron double-fire — 3-part fix shipped), #469 (horizon 365→380), #470 (xgb-dow promotion, PR #475 squash to `bba5775`, 6-feat baseline live since Apr 24), and ops #27 (API key rotation — 8 files / 4 secret mechanisms / 4 services restarted, ops #37 filed for canonical secret-store consolidation). Two short-lived sub-bugs surfaced from #472 (entity accuracy sort) and got fixed in their own tickets — #471 (DuckDB lock race for daily report MK missing) and #473 (WTI eval matching, separate from entity sort) — both closed within ~24h of filing. Two operational firsts: #mission-control channel created (escalation path now real for Gazoo), and dedicated Dino bot identity (403 wall down, Dino can post directly). New tickets opened: #479 (s07 parquet memory column-prune, MK 10.4GB → 5.1GB) and #480 (`_forecast_entity_fast` None on MK162 + EP18, predates promotion) — both filed by Dino from #470 proof-batch findings. Plus ops #33 (hazeydata.ai 22/46 divergence — Option C selected, prompt issued, queued behind Dino's other work), ops #35 (B2 backup scraper-pause window), ops #34 (Mr. Slate calibration), ops #37 (secret-store consolidation). MAE held at 8.3-8.4 across the run; today is Day 2 of the 6-feat baseline producing matching MAE — no regression visible yet.

## Immediate Priorities (S36)

1. **Memorial Day blog article** — Fred-requested. Memorial Day weekend wait pattern ("not always busiest on the actual holiday itself"). Use 2024 + 2025 actuals to support the angle.
2. **#470 follow-up PR queued for Apr 26** — Day 3 of 6-feat clean. Single PR: remove xgb-dow from challenger registry + update `PIPELINE_V4_DESIGN.md` Step 7 (6-feat documented) + update `MODELING_AND_WTI_METHODOLOGY.md`.
3. **Nudge Dino on ops #33** — Option C prompt issued Apr 24, no commit-list back-post yet. Day 3 of ticket. hazeydata.ai now 22/46 and growing.
4. **Shadow framework re-baseline check** — verify the post-promotion shadow runner correctly bootstrapped against the new 6-feat baseline (otherwise Day 19 numbers compare stale ground truth). xgb-recent +0.3 is suspicious.
5. **Acknowledge watchdog first fire in #wti-pipeline** — 11:00 ET 9-min stale + recovery is the system working. Brief note so Mr. Slate / Gazoo don't escalate the pattern next time.
6. **Gazoo persistent findings still on the board.** 3,902 unpushed TPCR commits is the loudest data-loss risk. hazeydata.ai 22/46. Bot DuckDB false DEGRADED is fixed in code but Gazoo audit may still report Day 36+ — verify next audit cycle clears it.

## Strategic Queue

- **Build `pipeline/competition/promote.py`** — ELEVATED priority post-S34. Engineer the risk out of promotions.
- **TPCR #466 duplicate-poster detection** — second half of #466 scope; watchdog covered the freshness half.
- **Stale-list audit sweep** — grep both repos for hardcoded sets. #467, #471, #472 all this class.
- **S30 carry-overs** — PQ research doc, multi-property tweets (DLR + UO).
- **Pricing page update** — reflect "380-day forecast horizon" post-#469.
- **ops #25** — TPCR cleanup follow-up.

## Open Tickets

| Ticket | Title | Status |
|---|---|---|
| TPCR #467 | `trained_methods` stale-list bug | OPEN — assigned hazeydata, no movement Day 14 |
| TPCR #479 | s07 parquet memory column-prune | OPEN (Dino, Day 0, from #470 fallout) |
| TPCR #480 | `_forecast_entity_fast` None on MK162 + EP18 | OPEN (Dino, Day 0, predates promotion) |
| ops #28 | Continuous-loop guardrails | OPEN (unassigned, Day 15) |
| ops #30 | Gazoo→Dino auto-fix loop | OPEN (unassigned, Day 11) |
| ops #31 | Mr. Slate agent | OPEN (unassigned, Phase 2 deferred) |
| ops #33 | hazeydata.ai git divergence (22/46, Day 3 ticket / Day 42 finding) | OPEN (Dino, Option C prompt issued Apr 24) |
| ops #34 | Mr. Slate Phase 1 calibration | OPEN (unassigned, Day 3) |
| ops #35 | B2 backup scraper-pause window | OPEN (Dino, queued behind #33) |
| ops #37 | Canonical secret-store consolidation | OPEN (Dino, from ops #27 postmortem) |

## Running / Paused

- Scraper alive (PID 943974, 13.8d uptime, watchdog LIVE)
- Pipeline cron 6 AM ET (live, 6-feat baseline since Apr 24)
- Shadow-run evaluation (live, 3 challengers racing new baseline)
- Watchdog cron `*/10 * * * *` (live since Apr 24)
- Clawdbot duplicate observed-tweet cron `7533c73d-...` (DISABLED per S32)

## Eviction Rule (ops #30)

At session close: cut previous session's "Last Session" paragraph → prepend to SESSION_LOG_ARCHIVE.md with date/session header → write new session summary here → verify ≤5 KB. If over, trim Strategic Queue into archive.

## Footer

Channels, repos, agents, standing rules: see `PROJECT_REFERENCE.md`.
Vision, history, strategic decisions: see `PROJECT_BACKGROUND.md`.
Governing spec: `docs/PIPELINE_V4_DESIGN.md`.
