# BARNEY.md — Cold-Start Memory for Barney (Claude Opus 4.6)

**Last updated:** 2026-03-20 05:30 UTC (marathon overnight session)
**Purpose:** When starting a new chat with Barney, point him here first. This file contains everything needed to resume work without re-explaining context.

---

## Who I Am

I'm **Barney**, Claude Opus 4.6 running in Claude.ai (or Claude Desktop). I'm the **Chief of Pipeline** and strategic advisor for HazeyData. I operate externally — not on OpenClaw, not on wilma-server. I communicate with the team via Discord (using the Barney bot account) and GitHub.

My role: architecture, code building, complex investigations, audits, and strategic planning. I push code to GitHub, interview Wilma via Discord, and work directly with Fred in marathon sessions like the one that produced this file.

---

## The Enterprise

**HazeyData** (hazeydata.ai) — solo-founder AI-augmented enterprise run by Fred Hazelton. Theme park crowd prediction and analytics platform. Multiple projects, not just theme parks.

### The Crew (Real Agents as of 2026-03-20)

| Agent | Model | Role | Platform |
|-------|-------|------|----------|
| **Fred** | Human | CEO, founder, final authority | Everywhere |
| **Wilma** | Sonnet (conversations) / Haiku (crons) | CTO, orchestrator, coordinator | OpenClaw on wilma-server |
| **Gazoo** | Opus | Independent auditor-in-chief. Nightly deep review. Triggers new jobs. | OpenClaw separate agent |
| **Pebbles** | Sonnet | Visual design specialist. UX/UI, dashboards, apps, Discord formatting. | OpenClaw separate agent |
| **Barney** | Opus 4.6 | Strategic advisor, code builder, architect. External. | Claude.ai / Claude Desktop |
| **Bam-Bam** | Parked | Future T4 local model. Not active today. | — |

### Infrastructure

- **wilma-server**: Ryzen / 64GB RAM / Ubuntu 24.04. Runs OpenClaw, pipeline, all operations.
- **OpenClaw/Clawdbot**: Node.js AI agent framework. Gateway + sessions + crons + Discord integration.
- **Discord**: "Slate Rock & Gravel Co." (guild: `1479350342318690505`) is the operational hub.

### Key Discord Channels

| Channel | ID | Purpose |
|---------|-----|---------|
| #barney-wilma-dev | `1479937927378239550` | Barney-Wilma development loop |
| #fred-wilma | `1479351572386414675` | Fred-Wilma primary channel |
| #barney | `1479351581873803386` | Barney's channel |
| #pebbles | `1479351583908171937` | Pebbles design channel |
| #gazoo | `1479351587129262232` | Gazoo audit channel |
| #mission-control | `1479351570121621569` | Mission control |
| #pipeline | `1479351574177513576` | Pipeline ops |
| #the-quarry | `1481020609583382648` | Analytics dashboard |
| #the-lodge | `1481008455144701992` | General ops |
| #go-monitor | `1484246120376045728` | GO.py project forum |
| #glass-ui | `1483966764650991616` | Glass UI design channel |

### GitHub Repos

| Repo | Branch | Purpose |
|------|--------|---------|
| `hazeydata/theme-park-crowd-report` | main + master | Production pipeline, forecasting, operations |
| `hazeydata/data-hub` | main | Independent data collection platform |

**GitHub PAT rule**: Must be classic token with top-level `repo` scope. Fine-grained tokens cause silent write failures.

---

## Current State (as of 2026-03-20)

### Enterprise Redesign — IN PROGRESS

We are executing the **Change Manifest** (`docs/CHANGE_MANIFEST_20260320.md`). This is the master plan for:

1. **Real multi-agent setup** — Gazoo and Pebbles as separate OpenClaw agents (not Wilma wearing costumes)
2. **Task queue system** — `scripts/task_queue.py` replacing 46 competing cron jobs with sequential processing
3. **Consolidated cron schedule** — 10 triggers replacing 46
4. **SKILLS.md for all agents** — defining capabilities, delegation rules, and refusal boundaries
5. **Automated memory management** — daily distillation, weekly MEMORY.md refresh, cold-start catchup
6. **Documentation cleanup** — archive stale docs, update superseded ones

### What's Been Committed This Session

| File | Commit | What |
|------|--------|------|
| `scripts/GO.py` | `34fe532` | Autonomous project orchestrator — NL parser, forum proposals, auto-execution |
| `docs/CHANGE_MANIFEST_20260320.md` | `eb5f46bf` | Complete implementation plan for enterprise redesign |
| `scripts/task_queue.py` | `f7b3e369` | Sequential task processing system (add/next/complete/list/stats/archive/dispatch) |

### What's Been Delivered (not on GitHub)

- `OpenClaw_Audit_Report.docx` — 9-section report from Wilma interview (7 batches)
- `HazeyData_Enterprise_Audit.docx` — 14-section, 4-part enterprise architecture audit

### Wilma's Execution Status

Wilma has been instructed to:
- [ ] Create Gazoo agent (`openclaw agents add gazoo`)
- [ ] Create Pebbles agent (`openclaw agents add pebbles`)
- [ ] Read and confirm understanding of Change Manifest
- [ ] Update her own SOUL.md (remove multi-persona instructions)
- [ ] Disable all 46 old cron jobs
- [ ] Create 10 new consolidated crons
- [ ] Configure agent-to-agent communication
- [ ] Set up Discord bindings for Gazoo and Pebbles

**Check #barney-wilma-dev for latest status.**

---

## Key Decisions Made This Session

### AK Prediction Accuracy Crisis
- AK underpredicting by ~14 WTI points. Root cause: 183K rows of 2014 Disney API data (7-min intervals) making 2014 the 3rd most influential training year despite geometric decay.
- **Fix**: `min_training_year: 2016` for all WDW parks. Models retrained March 17.
- **Still investigating**: WTI sign flip (Issue #49) — slot-level bias +5.15 but WTI-level -11.0.
- **Key insight**: Fleet-level MAE masked per-park problems for weeks. Multi-level monitoring (entity/park/WTI/property) is critical.

### Agent Architecture
- **OpenClaw supports REAL multi-agent routing.** `openclaw agents add <name>` creates fully isolated agents with own workspace, sessions, model, and memory. This was the biggest discovery of the night.
- Each agent gets: own SOUL.md, SKILLS.md, AGENTS.md, own session store, optionally own LLM model.
- Per-agent model selection: Gazoo on Opus (worth the cost for deep thinking), Pebbles on Sonnet, Wilma on Sonnet (conversations) / Haiku (crons).
- Agent-to-agent communication via `tools.agentToAgent` config or Discord channel posts.

### Queue System Design
- JSON-based queue at `~/clawd/data/task_queue.json`
- Three priorities: urgent (0), scheduled (1), background (2)
- Wilma processes sequentially — no lock contention
- Tasks enter from: cron triggers, GO.py, Fred messages, self-generated monitoring
- Priority routing is project-agnostic (ACCORD, CDR, SSD, crowd report all use same queue)

### Consolidated Cron Schedule
| Time | Name | What |
|------|------|------|
| 2:00 AM | overnight-maintenance | Memory distillation, cleanup, stale job check |
| 6:00 AM | pipeline-run | Pipeline v3 execution (UNCHANGED) |
| 7:30 AM | morning-ops | Accuracy report, pipeline health, park intel |
| 7:45 AM | morning-content | Tweet, blog promo |
| 1:00 PM | midday-check | Social, competitor watch, queue review |
| 3:00 PM | afternoon-content | Tweet |
| 9:00 PM | gazoo-nightly | Dispatched to Gazoo agent (Opus) |
| 11:00 PM | overnight-prep | Queue tomorrow's tasks |
| Sunday 10 AM | weekly-report | Comprehensive weekly summary |
| Monday 9 AM | weekly-content-plan | Plan week's content |

### GO.py Design
- Should be **conversational** (discussion-based job initiation), not code-like
- Fred says something natural → Wilma asks clarifying questions → GO.py formalizes into tracked project
- GO.py is the formalization engine at the end of a conversation, not the conversation itself

### Memory Management (PENDING — needs to be added to manifest)
- Daily distillation at 2 AM: read daily file → extract key decisions → append to WEEKLY_DIGEST.md
- Weekly MEMORY.md refresh on Sundays: curate permanent knowledge from weekly digest
- Cold-start catchup in HEARTBEAT.md: read last 3 daily files before first response after restart

### NemoClaw / CDR Connection
- NemoClaw announced at GTC March 16, 2026. NVIDIA's enterprise security/privacy layer for OpenClaw.
- OpenShell runtime for sandboxed execution, Nemotron local models, Privacy Router, YAML policy engine.
- Relevant for CDR (Canadian Digital Railway) project — sovereign AI infrastructure needs.

---

## Key Learnings & Rules

- **Pipeline v3 IS built and in production.** `pipeline_v3/` directory has pipeline.py, config.py, steps/, models/, core/, tests/, shadow/, diagnostics/. The architecture doc was the design; the implementation followed.
- **`systemd-run` is mandatory** for long-running pipeline processes. `nohup` gets killed by Clawdbot exec session timeouts.
- **Archive filename rule**: Must contain `YYYY-MM-DD` with hyphens or forecast evaluator silently skips them.
- **The Quarry data rule**: Only display data the pipeline auto-generates.
- **GitHub PAT**: Classic token with `repo` scope. Fine-grained tokens silently fail on writes.
- **Discord**: Always use known channel IDs directly. Guild lookups unreliable.
- **Long Discord messages**: Split into multiple `discord_send` calls to avoid character limit failures.
- **No red-amber-green** traffic light color schemes anywhere. Benedictus brand gradient only.
- **Fred's work windows**: 9 AM–4 PM and 9 PM–2 AM. Crew autonomous schedules in off-hours.
- **Pipeline locked 6–8 AM** during execution.
- **Wilma's first-message-wakes pattern**: First message triggers session wake-up. Second message gets processed.
- **Wilma is most reliable on #fred-wilma**. Check there if she's not responding elsewhere.

---

## Projects Beyond Theme Parks

HazeyData is a wide net. The redesigned system must be project-agnostic:
- **Theme Park Crowd Report** — crown jewel, production pipeline
- **Data Hub** — independent data collection (park hours, wait times, events)
- **ACCORD** — Canadian rules engine
- **Canadian Digital Railway (CDR)** — sovereign AI infrastructure
- **School Schedules Database (SSD)** — school calendar data
- **Twitch/streaming** — live coding, data analysis, theme park discussions

---

## How to Resume Work

1. Read this file (BARNEY.md)
2. Check `docs/CHANGE_MANIFEST_20260320.md` for current execution status
3. Read latest messages in `#barney-wilma-dev` (ID: `1479937927378239550`) for Wilma's progress
4. Check GitHub recent commits for what's been pushed since this file was last updated
5. Ask Fred what's on his mind — he moves fast

---

*Barney — Chief of Pipeline, Slate Rock & Gravel Co. 🪨*
