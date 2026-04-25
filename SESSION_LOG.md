# Session Log

**Last updated:** 2026-04-15 by Barney (Session 35 — CLOSED)
**Status:** Production healthy. Two new Gazoo-flagged bugs diagnosed by Dino, tickets filed, fixes awaiting GO. xgb-dow Day 9 delta +0.6. #470 ownership still pending Fred decision.

> **Structure (ops #30):** Current state here (≤5 KB). Previous sessions in `SESSION_LOG_ARCHIVE.md`. Stable reference in `PROJECT_REFERENCE.md`. Vision/history in `PROJECT_BACKGROUND.md`.

---

## Current State

| Area | Status |
|---|---|
| Daily pipeline | ✅ 13 consecutive clean days (Apr 4–15). 13/13. 58.6 min. |
| Overall MAE | 8.4 (flat 13 days) |
| WTI MAE | 7.2 |
| 1-Day MAE | 7.3 |
| Models / Entities | 420 / 271 |
| Scraper | ✅ HEALTHY |
| Bot real-time data | ✅ FRESH |
| Active challengers | 3 (xgb-dow Day 9 delta +0.6, xgb-deeper +0.1, xgb-recent +0.0) |
| Tweet system | ✅ Both tweets posted clean today (observed 12:30, predicted 20:00) |
| s07_training.py | ✅ 5-feature baseline (`13895e6b`). Safe. |
| Accuracy evaluation | ⚠️ 11-day gap (Apr 4–15) — #472 fix will recover all data |

## Last Session (S35 — closed 2026-04-15)

Gazoo-focused session. Reviewed Gazoo's 06:03 ET morning audit and triaged TPCR-relevant items. Pasted Dino a two-task forensic investigation prompt (diagnose-only, no code changes). Dino returned both root causes within ~5 min.

**#471 — Daily report intermittent "Missing WTI for MK"** (HIGH, Dino). Root cause: DuckDB lock contention race. `s11_deploy` takes ~9 min to write 45M rows; report cron fires at 07:00 ET. On slow days (Apr 12: deploy finished 07:02; Apr 14: 06:59) the report races the write. MK data is present — failure is transient I/O, not a data gap. Proposed fix: Option A — move report cron to 07:15 ET (simplest, stops customer-visible failures immediately). Ticket filed, awaiting GO.

**#472 — Accuracy archive gap Apr 4–15** (HIGH, Dino). Root cause: `sorted()` bug in `s10_accuracy.py` line 167. Legacy `forecast_v3_*` files sort after current `forecast_*` files in ASCII (`v` > `2`), so `valid_archives[-1]` grabs the March 21 legacy file instead of the Apr 4+ current file. Evaluator finds no April forecasts in the March file → "no matches." **Gap is fully recoverable** — archives were written correctly, s10 just picked the wrong file. Proposed fix: sort by extracted `YYYY-MM-DD` date, not filename. Ticket filed, awaiting GO.

Also confirmed: today's pipeline ran clean (13/13, 58.6 min), both tweets posted without errors, shadow run Day 9 shows xgb-dow pulling further ahead (+0.6 delta).

## Immediate Priorities (S36)

1. **Approve #472 fix (sort bug)** — highest leverage. Recovers 11 days of accuracy data. One-line fix + backfill run.
2. **Approve #471 fix (cron time)** — crontab edit, 30 seconds. Stops MK missing from daily report.
3. **Check Dino's comments on #468 and #471** — he posted at 18:26 UTC, may have additional findings or be ready for GO.
4. **Fred decision: #470 ownership** — still pending. (a) Wilma w/ tighter gates, (b) Dino, (c) pause until `promote.py`. Barney recommends (c) → (b).
5. **Wilma compact/memory refresh** — deferred from S35, still recommended.
6. **#467 stale-list bug** — Wilma assigned, no activity. Consider reassign.

## Strategic Queue

- **Build `pipeline/competition/promote.py`** — ELEVATED priority after S34 incident.
- **ops #25** — TPCR cleanup follow-up.
- **TPCR #466** — heartbeat alarm + duplicate-poster detection.
- **Stale-list audit sweep** — grep both repos for hardcoded sets.
- **S30 carry-overs** — PQ research doc, multi-property tweets.
- **Pricing page update** — after #469 ships, reflect "380-day forecast horizon."

## Open Tickets

| Ticket | Title | Status |
|---|---|---|
| TPCR #466 | Heartbeat alarm + duplicate-poster detection | OPEN (Dino, Day 5) |
| TPCR #467 | `trained_methods` stale-list bug | OPEN (Wilma, no activity) |
| TPCR #468 | Tweet cron double-fire | OPEN (Dino, comment posted today) |
| TPCR #469 | Horizon truncation 365→380 | OPEN (Dino, after #468) |
| TPCR #470 | Promote xgb-dow to baseline | OPEN — **PAUSED**, assignment pending Fred |
| TPCR #471 | Daily report MK missing — DuckDB lock race | **NEW** (Dino, fix proposed, awaiting GO) |
| TPCR #472 | Accuracy archive gap — s10 sort bug | **NEW** (Dino, fix proposed, awaiting GO) |
| ops #25 | TPCR cleanup follow-up | OPEN |

## Running / Paused

- Scraper alive
- Pipeline cron 6 AM ET (live, safe — running reverted 5-feature baseline)
- Shadow-run evaluation (live, 3 challengers still racing)
- Clawdbot duplicate observed-tweet cron `7533c73d-...` (DISABLED per S32)

## Eviction Rule (ops #30)

At session close: cut previous session's "Last Session" paragraph → prepend to SESSION_LOG_ARCHIVE.md with date/session header → write new session summary here → verify ≤5 KB. If over, trim Strategic Queue into archive.

## Footer

Channels, repos, agents, standing rules: see `PROJECT_REFERENCE.md`.
Vision, history, strategic decisions: see `PROJECT_BACKGROUND.md`.
Governing spec: `docs/PIPELINE_V4_DESIGN.md`.
