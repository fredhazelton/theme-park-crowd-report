# HazeyData Enterprise Redesign — Architecture Documentation

**Version:** 2.0
**Original Date:** 2026-03-20
**Last Updated:** 2026-03-22 (Session 5)
**Status:** IMPLEMENTED + EVOLVED
**Canonical source:** Change Manifest v2.0 in `hazeydata/operations`

---

## Overview

Major architectural redesign completed March 20, 2026, transitioning from single-agent persona switching to true multi-agent enterprise architecture. This document summarizes the implemented architecture as of March 22, 2026, including evolutions from Sessions 4-5.

---

## Key Changes

### 1. Real Multi-Agent Setup (Clawdbot v2026.1.24-3)

**Before:** Single Wilma agent pretending to be multiple personas via cron-triggered identity switches
**After:** Three independent agents with separate workspaces, identities, and Discord bot accounts

| Agent | Model | Workspace | Agent Dir | Channels | Role |
|-------|-------|-----------|-----------|----------|------|
| **Wilma** | Sonnet 4 | `~/clawd` | `~/.clawdbot/agents/anthropic/agent` | #fred-wilma, #pipeline, #alerts | CTO/Orchestrator |
| **Gazoo** | Sonnet 4 | `~/clawd-gazoo` | `~/.clawdbot/agents/gazoo/agent` | #gazoo | Independent QA Auditor |
| **Pebbles** | Sonnet 4 | `~/clawd-pebbles` | `~/.clawdbot/agents/pebbles/agent` | #pebbles, #glass-ui | Visual Design Lead |
| **Barney** | Opus 4.6 | N/A (external) | N/A | #barney, #barney-wilma-dev | Chief of Pipeline / Architect |

**Critical architecture note (discovered Session 5):**
- Clawdbot's cron `agentId` field is cosmetic — it does NOT control which agent session processes the cron
- For true agent dispatch, use `clawdbot agent --agent X` via system crontab
- Agent IDENTITY.md must exist in both the workspace AND `~/.clawdbot/agents/X/agent/`
- Each agent has a separate Discord bot account with its own token

### 2. Task Queue System

**Before:** 46 individual cron jobs competing for same session, causing locks
**After:** Consolidated Clawdbot cron jobs + system crontab entries, feeding a centralized task queue

**Architecture:**
- Queue file: `~/clawd/data/task_queue.json`
- Processing: Wilma checks queue every 30 minutes via heartbeat
- Priority levels: urgent (0) → scheduled (1) → background (2)
- All Clawdbot crons use `sessionTarget: "isolated"` to prevent context overflow

**System crontab entries (outside Clawdbot):**
- Pipeline V4 run (6:00 AM) — Python, not LLM
- Pipeline report (7:07 AM) — `s13_report.py --post-discord`, posts + pins to #pipeline
- Gazoo audit overnight (2:00 AM) — `clawdbot agent --agent gazoo`
- Gazoo audit afternoon (4:00 PM) — `clawdbot agent --agent gazoo`

### 3. Ticket System v2.1 (replaced GO.py v1)

**Before (GO.py v1):** "Execute GO.py" trigger → intake → #go-monitor forum → ✅ approval → execution → QA
**After (Ticket System v2.1):** "Make me a ticket" → GitHub Issue created immediately → agent works → Gazoo audits

**Design doc:** `docs/GO_PY_V2_DESIGN.md` in operations repo

**What was retired:** trigger phrases, #go-monitor, approval reactions, heartbeat scanner, standing order issues, 6-namespace labels
**What survived:** GitHub Issues as tickets, evidence-based closure, Gazoo QA audits

### 4. Pipeline V4 (Sessions 4-5)

**Before:** Pipeline V3 with quantile mapping, bias correction, v3 naming throughout
**After:** Pipeline V4 — pure baseline, clean naming, automated reporting

**Key changes:**
- `pipeline_v3/` → `pipeline/` directory rename
- All v3/v2/julia naming purged from filenames and code
- Quantile mapping REMOVED from WTI step (pure aggregation)
- Bias correction REMOVED (killed after March 17 accuracy disaster)
- Model files: `model_baseline.json`, output files: `all_forecasts.parquet`, `wti.parquet`
- DuckDB write lock retry-with-backoff in `pipeline/core/db.py`
- Single-step re-runs write to `pipeline_metrics_{date}_{step}.json` (protect full-run metrics)
- Daily report auto-posts to #pipeline and pins at 7:07 AM

**V4 Day 1 (2026-03-22):** 48min runtime, 47M predictions, 420 models, MAE 8.6, WTI MAE 6.7

**Design doc:** `docs/PIPELINE_V4_DESIGN.md`

### 5. SKILLS.md System

Each agent has explicit capability documentation loaded on session start:

**Wilma:** Pipeline operations, data analysis, task orchestration. Delegates design → Pebbles, QA → Gazoo, strategy → Barney.

**Gazoo:** Independent quality auditing, accuracy analysis, trend analysis. Refuses to execute fixes (audit only).

**Pebbles (updated Session 5):** UI/UX design, HTML/CSS, brand consistency. Mandatory brand references: hazeydata.ai, DESIGN_SPEC.md, LIVE_NOW_CARD_SPEC.md. Color system: Benedictus for data, navy+cyan for brand. No traffic lights ever.

---

## Operational Patterns

### Communication
- **Fred → Agent:** Post in agent's channel
- **Agent → Agent:** Post in target agent's channel
- **Cron → Agent:** System crontab with `clawdbot agent --agent X --deliver`
- **Barney → Anyone:** Via Discord bot account (external)

### Session Management
- Context overflow prevention: `reserveTokensFloor=40000`
- Manual fix: `/compact` in Discord
- All cron jobs: `sessionTarget: "isolated"`
- Heartbeat: 30 minutes, Haiku model

### Ticket Workflow
```
Fred: "Make me a ticket — [description]"
  → Agent creates GitHub Issue immediately
  → Agent works the ticket
  → Agent closes with evidence (commit SHA, test output)
  → Gazoo audits on next 2 AM / 4 PM cycle
```

---

## Retired Systems

- 46-job cron architecture → consolidated crons + system crontab
- Persona switching → real multi-agent
- GO.py v1 approval workflow → Ticket System v2.1
- #go-monitor forum channel → deleted
- Pipeline V3 naming → V4 clean naming
- Bias correction → killed permanently
- Quantile mapping in WTI → removed (enters as challenger if revisited)
- Julia ML training → superseded by Python-only approach

---

## Key Architecture Decisions

### Why `clawdbot agent` over cron `agentId`?
Clawdbot cron `agentId` is metadata only — all crons execute in the default agent session. `clawdbot agent --agent X` properly loads the target agent's identity and routes output through the correct Discord bot account.

### Why Ticket System v2.1 over GO.py v1?
The formal approval workflow added ceremony without proportional quality improvement. Evidence-based closure and Gazoo QA — the parts that matter — survived.

### Why V4 Pure Baseline?
Bias correction and quantile mapping were hiding model quality. A pure baseline gives a clean starting number. Improvements enter as named challengers and prove themselves with data.

### Why Barney external?
Independent architectural perspective, no server resource conflicts, unaffected by Clawdbot session issues. Tradeoff: manual cold-start via BARNEY.md.

---

## Future Evolution

- **Phase D (V4):** 5-7 days of clean baseline accuracy measurement (started 2026-03-22)
- **Phase E (V4):** First challenger model (day_of_week feature) in competition framework
- **Bam-Bam:** Frontend implementation agent via Cursor Pro
- **The Quarry:** Analytics dashboard (Pebbles design, Bam-Bam build)
- **Twitch:** Streaming presence (text setup done, visual assets pending)
- **Morning briefing:** Unified daily briefing combining pipeline report + ops status

---

## Reference Documents

| Document | Repo | Purpose |
|----------|------|---------|
| `docs/BARNEY.md` | operations | Barney cold-start memory |
| `docs/GO_PY_V2_DESIGN.md` | operations | Ticket System v2.1 spec |
| `docs/CHANGE_MANIFEST_20260320.md` | operations | This redesign's change manifest (v2.0) |
| `docs/OPENCLAW_BLOG_NOTES.md` | operations | Blog article notes (14 topics) |
| `docs/PIPELINE_V4_DESIGN.md` | theme-park-crowd-report | Pipeline V4 architecture |
| `docs/DESIGN_SPEC.md` | theme-park-crowd-report | Crowd Card / brand design bible |

---

*Architecture documentation v2.0 — Barney + Fred — March 22, 2026*

**Next major review:** After V4 Phase D baseline measurement (7 days) or significant architectural change.
