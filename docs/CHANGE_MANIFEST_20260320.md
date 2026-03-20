# HazeyData Enterprise Redesign — Change Manifest

**Version:** 1.0
**Date:** 2026-03-20
**Authors:** Barney (architect) + Fred (approver)
**Status:** APPROVED — EXECUTING

---

## Purpose

This document is the single source of truth for the HazeyData enterprise redesign.
Every change is listed with exact steps, dependencies, verification, and rollback.
Wilma executes changes in order. Fred approves at gates. Barney builds code artifacts.

---

## Phase 1: Real Agents (OpenClaw Multi-Agent Setup)

### 1.1 Create Gazoo as a separate OpenClaw agent

**Why:** Independent QA requires a separate brain. Gazoo auditing Wilma-as-Gazoo is self-review, not QA.

**Steps:**
```bash
# On wilma-server:
openclaw agents add gazoo

# This creates:
# ~/.openclaw/workspace-gazoo/   (workspace)
# ~/.openclaw/agents/gazoo/      (state + sessions)
```

**Post-creation config:**
- Set model to `claude-opus-4-6` in agent config
- Create `~/.openclaw/workspace-gazoo/SOUL.md` (Barney provides content — see soul files below)
- Create `~/.openclaw/workspace-gazoo/SKILLS.md` (Barney provides content)
- Create `~/.openclaw/workspace-gazoo/AGENTS.md` (operational instructions)
- Create `~/.openclaw/workspace-gazoo/USER.md` (copy from Wilma's — Fred's preferences)

**Discord binding:**
- Bind Gazoo agent to `#gazoo` channel (ID: `1479351587129262232`)
- Create a separate Discord bot token for Gazoo if needed, or route via existing bot

**Verification:**
- [ ] `openclaw agents list --bindings` shows gazoo as separate agent
- [ ] Send test message to #gazoo, verify response comes from Gazoo agent (not Wilma)
- [ ] Verify Gazoo has no access to Wilma's session history

**Rollback:** `openclaw agents remove gazoo`

---

### 1.2 Create Pebbles as a separate OpenClaw agent

**Why:** Visual design quality is critical to Fred. Pebbles needs her own design-focused brain with Fred's aesthetic preferences baked in.

**Steps:**
```bash
openclaw agents add pebbles
```

**Post-creation config:**
- Set model to `claude-sonnet-4-6` in agent config
- Create workspace files: SOUL.md, SKILLS.md, AGENTS.md, USER.md
- SKILLS.md focuses on: UX/UI design, dashboards, slide decks, apps, HTML/CSS, Discord output formatting, the benedictus brand, Fred's visual taste

**Discord binding:**
- Bind to `#pebbles` channel (ID: `1479351583908171937`)
- Bind to `#glass-ui` channel (ID: `1483966764650991616`)

**Verification:**
- [ ] `openclaw agents list --bindings` shows pebbles as separate agent
- [ ] Send design request to #pebbles, verify response is design-focused
- [ ] Verify Pebbles workspace has SKILLS.md with design capabilities

**Rollback:** `openclaw agents remove pebbles`

---

### 1.3 Update Wilma's configuration

**Why:** Wilma becomes the coordinator/orchestrator. She no longer pretends to be other agents.

**Steps:**
- Update Wilma's SOUL.md: Remove multi-persona instructions. She is Wilma — orchestrator, not 8 people.
- Create Wilma's SKILLS.md: Orchestration, pipeline ops, data analysis, task coordination, scheduling, Discord management, Git operations, content generation, social media posting.
- Update AGENTS.md: Remove agent persona instructions. Add queue management instructions.
- Set conversation model to `claude-sonnet-4-6` (already done tonight)
- Keep cron job model overrides at `claude-haiku-4-5` (already done tonight)

**Verification:**
- [ ] Wilma responds as herself, not as personas
- [ ] Wilma can dispatch tasks to Gazoo and Pebbles via agent-to-agent messaging or Discord

---

### 1.4 Agent-to-Agent Communication

**Why:** Wilma needs to dispatch work to Gazoo and Pebbles.

**Steps:**
- Enable `tools.agentToAgent` in OpenClaw config:
```json
{
  "tools": {
    "agentToAgent": {
      "enabled": true,
      "allow": ["wilma", "gazoo", "pebbles"]
    }
  }
}
```
- Alternatively, agents communicate via Discord channel posts (simpler, already works)

**Verification:**
- [ ] Wilma can send a task to Gazoo via #gazoo channel
- [ ] Gazoo can post results to #gazoo and #briefing

---

## Phase 2: Task Queue System

### 2.1 Build the queue system

**Who builds:** Barney (pushes to GitHub)
**File:** `scripts/task_queue.py`

**Design:**
- JSON-based queue file at `~/clawd/data/task_queue.json`
- Three priority levels: `urgent` (0), `scheduled` (1), `background` (2)
- Tasks enter from: cron triggers, Fred messages (GO.py), self-generated (monitoring/escalation)
- Wilma checks queue on each heartbeat (~30 min) and between conversations
- Sequential processing — one task at a time, no lock contention
- Task lifecycle: queued → executing → completed → archived
- Completed tasks auto-archive after 24 hours

**Queue entry structure:**
```json
{
  "id": "task-20260320-001",
  "priority": 1,
  "source": "cron:morning-ops",
  "project": "crowd-report",
  "description": "Run morning operations check",
  "payload": "Check pipeline status, generate accuracy report, compile park intel",
  "created_at": "2026-03-20T06:30:00Z",
  "status": "queued",
  "assigned_to": "wilma",
  "result": null
}
```

**Commands:**
```bash
# Add task to queue
python3 scripts/task_queue.py add --priority scheduled --description "Morning ops" --payload "..."

# Process next task (Wilma calls this)
python3 scripts/task_queue.py next

# List queue
python3 scripts/task_queue.py list

# Mark task complete
python3 scripts/task_queue.py complete <task-id> --result "..."

# Archive completed tasks
python3 scripts/task_queue.py archive
```

**Verification:**
- [ ] Can add, list, process, complete, and archive tasks
- [ ] Priority ordering works (urgent before scheduled before background)
- [ ] Queue file is readable/writable by Wilma

---

### 2.2 Create consolidated cron schedule

**Why:** Replace 46 competing crons with ~10 queue-feeding triggers.

**New schedule (all times ET, America/Toronto):**

| Time | Name | What it does | Model |
|------|------|-------------|-------|
| 2:00 AM | `overnight-maintenance` | Memory distillation, task archive cleanup, stale job check | Haiku |
| 6:00 AM | `pipeline-run` | Execute pipeline_v3/pipeline.py (UNCHANGED) | N/A (Python) |
| 7:30 AM | `morning-ops` | Accuracy report, pipeline health check, park intel summary | Haiku |
| 7:45 AM | `morning-content` | Morning tweet, blog promo check | Haiku |
| 1:00 PM | `midday-check` | Social engagement, competitor watch, task queue review | Haiku |
| 3:00 PM | `afternoon-content` | Afternoon tweet | Haiku |
| 9:00 PM | `gazoo-nightly` | **Dispatched to Gazoo agent (Opus)** — full system audit | Opus |
| 11:00 PM | `overnight-prep` | Queue tomorrow's scheduled tasks, check for stale projects | Haiku |
| Every 30 min | `heartbeat` | Queue check, urgent task processing, proactive monitoring | (existing) |

**Weekly additions:**
| Day | Time | Name | What |
|-----|------|------|------|
| Sunday | 10:00 AM | `weekly-report` | Comprehensive weekly summary across all projects | Haiku |
| Monday | 9:00 AM | `weekly-content-plan` | Plan week's blog/social content | Haiku |

**That's 10 scheduled crons + heartbeat, replacing 46.**

**Steps to implement:**
1. Disable all 46 existing cron jobs (don't delete — disable)
2. Create 10 new cron jobs with the schedule above
3. Each new cron adds a task to the queue instead of doing the work directly
4. Wilma processes the queue on heartbeat

**Verification:**
- [ ] `cron list` shows only 10 enabled jobs
- [ ] Queue receives tasks at scheduled times
- [ ] No session lock timeouts during peak hours

**Rollback:** Re-enable old cron jobs from disabled state

---

## Phase 3: SKILLS.md Files

### 3.1 Wilma SKILLS.md

```markdown
# Wilma — Skills Manifest

## Core Competencies
- Pipeline operations (monitoring, debugging, deployment)
- Data analysis (DuckDB, Parquet, Python, pandas)
- Task orchestration (queue management, priority routing, delegation)
- Discord management (channel ops, message routing, forum management)
- Git operations (commit, push, branch management)
- Content generation (tweets, blog posts, reports)
- Social media management (Twitter/X posting, Reddit scouting)
- Scheduling and cron management
- Memory management (daily files, MEMORY.md distillation)
- System administration (wilma-server ops, process management)

## Delegate To
- **Gazoo**: All QA audits, independent reviews, quality scoring
- **Pebbles**: All visual design, UI/UX, dashboards, slide decks, HTML/CSS
- **Barney**: Strategic decisions, architecture review, complex investigations
- **Fred**: Go/no-go decisions, strategic direction, budget approvals

## Refuse
- Visual design work (delegate to Pebbles)
- Independent QA of own work (delegate to Gazoo)
- Spending decisions over $50 (escalate to Fred)
- Pipeline methodology changes (require Barney review per Change Protocol)
```

### 3.2 Gazoo SKILLS.md

```markdown
# Gazoo — Skills Manifest

## Core Competencies
- Independent quality auditing of all system outputs
- Pipeline accuracy analysis and anomaly detection
- Agent performance scoring (0-10 scale)
- Issue identification with severity classification
- Trend analysis across audit history
- Creative recommendations for system improvement
- Triggering new tasks/jobs based on audit findings

## Authority
- Can file GitHub issues for any agent
- Can trigger escalation engine for underperforming areas
- Can recommend cron job changes (Wilma implements)
- Can veto customer-facing content (Fred can override)
- Posts to #gazoo, #briefing, #alerts

## Refuse
- Executing fixes (audit only — Wilma or Bam-Bam implements)
- Direct pipeline modifications
- Approving own audit findings (Fred reviews Gazoo's work)
```

### 3.3 Pebbles SKILLS.md

```markdown
# Pebbles — Skills Manifest

## Core Competencies
- UI/UX design (web, mobile, dashboard)
- HTML/CSS/JavaScript implementation
- Brand consistency (benedictus gradient, no red-amber-green)
- Slide deck design and layout
- Data visualization (charts, graphs, infographics)
- Discord output formatting (embeds, rich messages)
- iOS Weather-inspired glass UI design
- Responsive design and accessibility
- Design system documentation

## Design Principles (Fred's Taste)
- Clean, modern, dark-themed interfaces
- Benedictus brand gradient for all health/status indicators
- NO red-amber-green traffic light color schemes anywhere
- Glass/translucent aesthetic inspired by iOS Weather app
- Data density without clutter
- Professional but not corporate

## Delegate To
- **Wilma**: Data queries, pipeline ops, content writing
- **Gazoo**: Design QA and review

## Refuse
- Backend code, pipeline logic, data processing
- Content writing (delegate to Wilma)
```

---

## Phase 4: Documentation Cleanup

### 4.1 Archive stale documentation

**Move to `docs/archive/`:**
- `docs/XGBOOST_PARAMS.md` → `docs/archive/XGBOOST_PARAMS_v2.md` (stale since Feb 2026 audit)
- Any `scripts/` files superseded by pipeline_v3 → `scripts/archive/`

### 4.2 Update pipeline_v3 architecture doc

Add header to `docs/PIPELINE_V3_ARCHITECTURE.md`:
```
> **Status:** IMPLEMENTED — in production since ~March 2026
> **This document is the DESIGN doc. For current state, see pipeline_v3/ source code.**
```

### 4.3 Create REDESIGN.md

New file documenting tonight's decisions: real agents, queue system, consolidated crons, SKILLS.md system. This becomes the reference doc for the new architecture.

---

## Phase 5: Repo Audit

### 5.1 Full repo structure audit

Barney conducts a systematic review of:
- [ ] All files in `scripts/` — identify active vs stale vs superseded
- [ ] All files in `docs/` — identify current vs stale
- [ ] All files in `pipeline_v3/` — verify completeness
- [ ] GitHub Issues — close resolved, update active
- [ ] Branch cleanup — identify and delete stale branches

### 5.2 Produce repo health report

Deliverable: `docs/REPO_AUDIT_20260320.md` with findings and recommended actions.

---

## Execution Order

| Step | What | Who | Depends On | Status |
|------|------|-----|-----------|--------|
| 1 | Build task_queue.py | Barney | — | 🔄 |
| 2 | Build SKILLS.md files | Barney | — | 🔄 |
| 3 | Push Change Manifest to GitHub | Barney | — | 🔄 |
| 4 | Create Gazoo agent | Wilma | Step 3 | ⏳ |
| 5 | Create Pebbles agent | Wilma | Step 3 | ⏳ |
| 6 | Update Wilma config | Wilma | Step 3 | ⏳ |
| 7 | Disable old cron jobs | Wilma | Step 1 | ⏳ |
| 8 | Create new consolidated crons | Wilma | Step 1, 7 | ⏳ |
| 9 | Configure agent-to-agent comms | Wilma | Steps 4, 5 | ⏳ |
| 10 | Test queue system end-to-end | Wilma + Fred | Steps 1, 8 | ⏳ |
| 11 | Archive stale docs | Wilma | — | ⏳ |
| 12 | Repo audit | Barney | — | ⏳ |
| 13 | Gazoo first real audit | Gazoo | Steps 4, 10 | ⏳ |

---

## Success Criteria

The redesign is "done" when:
1. ✅ Gazoo runs as an independent agent on Opus, producing nightly audits
2. ✅ Pebbles runs as an independent agent on Sonnet, handling design requests
3. ✅ Wilma processes a task queue instead of competing cron jobs
4. ✅ No session lock timeouts for 7 consecutive days
5. ✅ Fred receives one clear morning briefing instead of 25 scattered Discord posts
6. ✅ All stale documentation is archived or updated
7. ✅ GO.py successfully runs a project through the full lifecycle

---

*Change Manifest v1.0 — Barney + Fred — March 20, 2026, 4:00 AM session*
*🪨 Let's build this.*
