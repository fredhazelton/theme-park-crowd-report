# Session Log

**Last updated:** 2026-04-06 by Barney (Session 29 — FINAL UPDATE)
**Session:** 29
**Status:** Monster session. Design Spec + Amendment 004 APPROVED. service_status_v2.py live. 5 hazeydata.ai tickets closed. EU bug fixed. Year View refreshed + in nav + auto-cron. Blog index recaps added. Gazoo Customer Experience domain live. TDS50 root-caused (Tokyo data calibration). Internal spam fixed. Pipeline 13/13 stable.

---

## Session 29 Summary

Largest single session to date — 12+ deliverables across both repos.

### Stream 1: Customer Service Design Spec (Playbook Phase 3 → Phase 4 APPROVED)
Wrote the full 9-domain Customer Service Design Spec. Fred approved both the Design Spec and Amendment 004.

**Product vision (Fred directive):** Free, community-oriented, organic growth, stunning visuals, feedback-driven improvement.

### Stream 2: Website Audit + Fixes (hazeydata.ai)
Audited hazeydata.ai/theme-park-crowd-report/ and fixed every finding:
- Year View data refreshed with current pipeline forecasts
- Year View date range rendering fixed (dynamic from JSON data)
- "Crowd Calendar" added to main nav (TPCR index + blog pages)
- Daily recap section added to blog index
- Year View auto-refresh cron set (8 AM ET daily)
- Screenshot git push resolved

### Stream 3: service_status_v2.py — Full Lifecycle
Built → proof-batched → false-alerted (deployment sequencing error) → root-caused → redeployed correctly → internal spam fixed → pipeline night-check fixed → running clean in production.

Amendment 004 updated to v1.1 with deployment lesson and correct cron env vars.

### Stream 4: Customer-Facing Fixes
- Epic Universe bot bug fixed (TPCR #460 — CLOSED)
- Gazoo Customer Experience audit domain added to AUDIT_SCOPE.md

### Stream 5: TDS50 Investigation
Root-caused MAE 79.3: Tokyo parks have POSTED data but zero ACTUAL data. Conversion model has no Tokyo-specific training. Model predicts ~96 min for rides with ~175 min actual waits. Fred directive: apply global POSTED→ACTUAL ratios to Tokyo entities, retrain.

**Dino tasks still running at session end:** Tokyo conversion fix, bot error handling (#459), daily report quality gate (#461). Prompts provided to Fred for sequential execution.

### Tickets — Session 29

**Closed this session:**
| Ticket | What |
|--------|------|
| hazeydata.ai #9 | Crowd Calendar in main nav |
| hazeydata.ai #10 | Year View data + dynamic date range |
| hazeydata.ai #11 | Blog index daily recaps |
| TPCR #460 | Epic Universe bot bug |

**Still open:**
| Ticket | What | Status |
|--------|------|--------|
| TPCR #458 | Phase 1 umbrella | Service status done. Fred quick wins pending. |
| TPCR #459 | Bot error handling | Dino prompt ready, awaiting execution |
| TPCR #461 | Daily report quality gate | Dino prompt ready, awaiting execution |

### Deployed This Session
| What | Where |
|------|-------|
| service_status_v2.py | wilma-server cron (*/5, with env vars) |
| Year View auto-refresh | wilma-server cron (8 AM ET daily) |
| Crowd Calendar nav link | hazeydata.ai (Cloudflare Pages) |
| Dynamic year-view date range | hazeydata.ai |
| Blog index daily recaps | hazeydata.ai |
| EU bot fix (UOR grouping) | tpcr-discord-bot on wilma-server |
| Gazoo Customer Experience domain | AUDIT_SCOPE.md in operations |
| service_status_v2.py spam fix | Internal posts only on status changes |
| service_status_v2.py night fix | Pipeline check treats off-hours as ok |

### Documents Committed This Session
| Document | Repo |
|----------|------|
| `docs/TPCR_CUSTOMER_SERVICE_DESIGN_SPEC.md` (APPROVED) | TPCR |
| `docs/V4_AMENDMENT_004_SERVICE_STATUS_REDESIGN.md` (APPROVED v1.1) | TPCR |
| `docs/briefings/DINO_CUSTOMER_SERVICE_PHASE2_20260405.md` | operations |
| `scripts/service_status_v2.py` | TPCR |
| `tpcr-discord-bot/ask_agent.py` (EU fix) | TPCR |
| `docs/AUDIT_SCOPE.md` (Customer Experience domain) | operations |

### Decisions This Session
| Decision | Who |
|----------|-----|
| Customer Service Design Spec APPROVED | Fred |
| Amendment 004 APPROVED | Fred |
| Product vision: free, community, organic growth, stunning visuals | Fred |
| Retrain TDS50 — apply global POSTED→ACTUAL ratios to Tokyo parks | Fred |
| No new Discord channels until 250+ members | Barney |
| Remove DISBOARD bot | Fred + Barney |
| Biweekly announcement cadence | Fred + Barney |
| service_status_v2.py deployment sequence: write final cron → reset state → verify first cycle | Barney (learned from incident) |

### Process Fix: Dino Communication
**Barney must NEVER address Dino via Discord.** Dino is Claude Code on the Mac Mini — he cannot read Discord. Task assignments via committed briefings in `operations/docs/briefings/` only. Fred pastes prompts into Dino's terminal. Discord posts are for situational awareness only.

---

## How to Start Next Session

1. Read this file
2. Read TPCR customer channels: `#announcements`, `#feedback`, `#crowd-reports` (Domain 7)
3. Check `#gazoo` — should now include Customer Experience domain score
4. Verify service_status_v2.py cron is running clean (check log)
5. Check if Dino completed: Tokyo conversion fix, bot error handling (#459), daily report quality gate (#461)
6. Verify Fred completed: welcome message, server description, DISBOARD removal, Chela response
7. Check shadow report — xgb-highLR comparison data
8. Check if TDL/TDS MAE improved after Tokyo conversion fix

## Next Actions (Priority Order)

1. **Dino (prompts provided):** Tokyo conversion fix → bot error handling (#459) → daily report quality gate (#461)
2. **Fred: Phase 1 quick wins** — welcome message, server description, DISBOARD removal
3. **Fred: Close loop with Chela** — respond in TPCR #feedback about EU fix
4. **Fred: First biweekly announcement** — lots shipped, time to tell customers
5. **Train + register xgb-dow** — second challenger
6. **xgb-highLR Day 7 evaluation** — ~Apr 12
7. **Commit PQ research doc** to TPCR
8. **Multi-property tweets** — DLR + Universal Orlando

## Blockers

- None

## Key Numbers

| Metric | Value | Updated |
|--------|-------|---------|
| Total predictions | ~46M/day | S29 |
| Overall MAE | 8.4 min | S29 |
| WTI MAE | 7.2 min | S29 |
| 1-Day MAE | 7.3 min | S29 |
| TPCR server members | 82 | S28 |
| Customer service spec | APPROVED | S29 |
| Amendment 004 | APPROVED v1.1 | S29 |
| service_status_v2.py | Live, running clean | S29 |
| Gazoo Customer Experience | Domain added, next audit picks it up | S29 |
| Active challengers | 1 (xgb-highLR, Day 1 reset) | S29 |
| Gazoo composite | 7.1 (expect improvement next cycle) | S29 |
| Open TPCR tickets | 3 (#458, #459, #461) | S29 |
| Open hazeydata.ai tickets | 2 (#7, #8 — SSD, not TPCR) | S29 |
| Tickets closed this session | 4 | S29 |

---

*Shared project memory for WTI Pipeline. Updated every session. Git history preserves all versions.*
