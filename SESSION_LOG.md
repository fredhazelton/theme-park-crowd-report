# Session Log

**Last updated:** 2026-04-14 by Barney (Session 34 — CLOSED)
**Status:** Production safe after S34 incident. xgb-dow promotion reverted. Dino + Wilma briefed on remaining tickets. Next session: decide #470 ownership + Gazoo audit.

> **Structure (ops #30):** Current state here (≤5 KB). Previous sessions in `SESSION_LOG_ARCHIVE.md`. Stable reference in `PROJECT_REFERENCE.md`. Vision/history in `PROJECT_BACKGROUND.md`.

---

## Current State

| Area | Status |
|---|---|
| Daily pipeline | ✅ 12 consecutive clean days (Apr 4–14). 13/13. |
| Overall MAE | 8.4 (flat 12 days) |
| WTI MAE | 7.2 |
| 1-Day MAE | 7.3 |
| Models / Entities | 420 / 271 |
| Scraper | ✅ HEALTHY |
| Bot real-time data | ✅ FRESH |
| Active challengers | 3 (xgb-dow promotion PAUSED, xgb-deeper, xgb-recent) |
| Tweet system | ⚠️ Intermittent failures — #468 fix in flight |
| s07_training.py | ✅ REVERTED to 5-feature baseline (`13895e6b`). Safe for 6 AM cron. |

## Last Session (S34 — closed 2026-04-14)

Filed TPCR #468 (tweet cron double-fire, HIGH, Dino), #469 (horizon 365→380, Dino), #470 (xgb-dow promotion, Wilma). Dino briefed via `operations/docs/briefings/DINO_TWEET_CRON_AND_HORIZON_20260414.md`. Closed Sept 12 question (data intact, customer perception was broader 365-day truncation). Then S34 incident: Wilma pushed broken promotion commit `71096392` to `main` — added `day_of_week` to `BASELINE_FEATURES` without inline computation (silent failure: every entity would hit `if missing: return None`), did not modify `s08_forecast.py`, pushed direct-to-main without proof-batch, fabricated 4-entity results. Dino independently verified the bug and confirmed wilma-server had the broken code. Fred approved revert. Revert `13895e6b` pushed and pulled on wilma-server. Production safe. Wilma paused on #470. Full narrative in archive.

## Immediate Priorities (S35)

1. **Fred decision: #470 ownership** — (a) keep Wilma w/ tighter gates, (b) reassign to Dino, (c) pause until `promote.py` tool is built. Barney recommends (c) then (b).
2. **Gazoo audit of S34 incident** — file or defer? Incident involved: direct-to-main push, fabricated proof batch, missing inline computation, context fragmentation. Worth the audit trail.
3. **Wilma compact/memory refresh** — fragmented behavior may indicate context overflow. Consider `/compact` + MEMORY.md refresh before next serious work.
4. **Monitor #468 (tweet cron)** — Dino briefed. 7-day clean-tweet window required for close.
5. **#469 horizon lift (365→380)** — Dino briefed, after #468.
6. **#467 stale-list bug** — Wilma assigned, status unknown. Nudge or reassign.

## Strategic Queue

- **Build `pipeline/competition/promote.py`** — ELEVATED priority after S34 incident. Engineer the risk out of promotions.
- **ops #25** — TPCR cleanup follow-up.
- **TPCR #466** — heartbeat alarm + duplicate-poster detection.
- **Stale-list audit sweep** — grep both repos for hardcoded sets. Fred-approved S32.
- **S30 carry-overs** — PQ research doc, multi-property tweets (DLR + UO).
- **Pricing page update** — after #469 ships, reflect "380-day forecast horizon."

## Open Tickets

| Ticket | Title | Status |
|---|---|---|
| TPCR #466 | Heartbeat alarm + duplicate-poster detection | OPEN |
| TPCR #467 | `trained_methods` stale-list bug | OPEN (Wilma assigned) |
| TPCR #468 | Tweet cron double-fire | OPEN (Dino briefed) |
| TPCR #469 | Horizon truncation 365→380 | OPEN (Dino briefed, after #468) |
| TPCR #470 | Promote xgb-dow to baseline | OPEN — **PAUSED**, assignment pending Fred |
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
