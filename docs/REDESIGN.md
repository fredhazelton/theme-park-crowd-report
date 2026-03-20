# HazeyData Enterprise Redesign — Architecture Documentation

**Version:** 1.0  
**Date:** 2026-03-20  
**Status:** IMPLEMENTED  
**Canonical source:** Change Manifest v1.0 in `hazeydata/operations`

---

## Overview

Major architectural redesign completed March 20, 2026, transitioning from single-agent persona switching to true multi-agent enterprise architecture. This document summarizes the implemented changes and new operational patterns.

---

## Key Changes

### 1. Real Multi-Agent Setup (OpenClaw/Clawdbot)

**Before:** Single Wilma agent pretending to be multiple personas via cron-triggered identity switches  
**After:** Three independent agents with separate workspaces and models

| Agent | Model | Workspace | Channels | Role |
|-------|-------|-----------|----------|------|
| **Wilma** | Sonnet 4 | `~/clawd` | #fred-wilma, #pipeline, #alerts | CTO/Orchestrator |
| **Gazoo** | Opus 4.6 | `~/clawd-gazoo` | #gazoo | Independent QA Auditor |
| **Pebbles** | Sonnet 4 | `~/clawd-pebbles` | #pebbles, #glass-ui | Visual Design Lead |

**Benefits:**
- No more session lock timeouts from competing cron jobs
- Gazoo provides truly independent QA (not self-review)
- Pebbles focuses entirely on design without context switching
- Each agent optimized for their domain expertise

### 2. Task Queue System

**Before:** 46 individual cron jobs competing for same session, causing locks  
**After:** 10 consolidated cron jobs feeding a centralized task queue

**Architecture:**
- Queue file: `~/clawd/data/task_queue.json`
- Processing: Wilma checks queue every 30 minutes via heartbeat
- Priority levels: urgent (0) → scheduled (1) → background (2)
- Agent assignment: Tasks routed to appropriate agent (wilma/gazoo/pebbles)

**New Cron Schedule (ET):**
- 2:00 AM: overnight-maintenance
- 6:00 AM: pipeline-daily  
- 8:15 AM: pipeline-post-run
- 9:00 AM: morning-ops
- 3:00 PM: data-quality
- 4:00 PM: gazoo-audit-afternoon
- 5:00 PM: analytics-refresh
- 11:00 PM: queue-maintenance
- **Weekly:** 3:00 AM Sunday (weekly-maintenance), 10:00 AM Sunday (weekly-blog)

### 3. SKILLS.md System

Each agent now has explicit capability documentation:

**Wilma (`~/clawd/SKILLS.md`):**
- Pipeline operations, data analysis, task orchestration
- Discord management, git operations, content generation
- SSD project ownership (unlimited budget authority)
- Delegates design → Pebbles, QA → Gazoo, strategy → Barney

**Gazoo (`~/clawd-gazoo/SKILLS.md`):**
- Independent quality auditing, pipeline accuracy analysis
- Agent performance scoring, trend analysis
- Authority to veto customer-facing content, trigger escalations
- Refuses to execute fixes (audit only)

**Pebbles (`~/clawd-pebbles/SKILLS.md`):**
- UI/UX design, HTML/CSS, brand consistency
- Glass UI aesthetic, data visualization
- Fred's design taste encoded (no red-amber-green, benedictus gradient)
- Refuses backend code, delegates content → Wilma

---

## Operational Changes

### Communication Patterns

**Agent-to-Agent:** Via Discord channel dispatch
- Wilma → Gazoo: Post task request in #gazoo
- Wilma → Pebbles: Post design request in #pebbles  
- Results posted back to requestor or #briefing

**No More Persona Switching:** Wilma is always Wilma, never pretends to be other agents

### Task Processing Flow

```
Cron job triggers → Add task to queue → Wilma heartbeat picks up task → 
Process according to payload → Mark complete → Continue to next task
```

**Heartbeat Priorities (in order):**
1. 🔥 Task queue processing (FIRST PRIORITY)
2. 🟣 #chantale-wilma monitoring  
3. Content review checks (#content-review ✅/❌)
4. SSD pipeline monitoring
5. Regular operational cycles

### Session Management

- **Context overflow prevention:** Auto-compaction at 160K tokens (40K reserve floor)
- **Session resets:** Auto-reset after 2 hours idle, daily full reset at 4 AM ET
- **Heartbeat frequency:** 30 minutes (reduced from 1-2 hours)

---

## Migration Notes

### Retired Systems

- **46-job cron architecture** → Disabled (not deleted), replaced with 10-job queue feeder
- **Persona switching system** → Enterprise multi-agent (Betty/Arnold/Dino/Mr. Slate personas retired)
- **Julia ML training** → Superseded by pipeline_v3 Python-only approach

### Preserved Systems

- **Core pipeline_v3:** No changes to data processing logic
- **SSD project:** Full ownership transferred to Wilma with unlimited budget
- **TPCR accuracy monitoring:** Continues under new queue system
- **Content review workflow:** Unchanged (#content-review ✅/❌)

### Backward Compatibility

- **Discord channels:** All existing channels preserved
- **Git workflows:** No changes to repository structure
- **API endpoints:** No customer-facing changes

---

## Success Metrics

**Measured over 7-day periods post-implementation:**

- ✅ **Zero session lock timeouts** (previous: daily occurrences)
- ✅ **Single morning briefing** instead of 25+ scattered posts
- ✅ **Independent QA audits** from Gazoo (Opus model)
- ✅ **Design consistency** via dedicated Pebbles agent
- ✅ **Task queue processing** during regular heartbeat cycles

---

## Architecture Decisions

### Why Multi-Agent vs. Persona Switching?

- **Reliability:** Eliminates session contention and lock timeouts
- **Quality:** True independent review vs. self-review masquerading as peer review  
- **Specialization:** Each agent optimized for domain expertise
- **Scalability:** Can add more agents without affecting existing workflows

### Why Task Queue vs. Direct Cron Execution?

- **Coordination:** Single orchestrator prevents race conditions
- **Priority:** Critical tasks process before routine maintenance
- **Visibility:** All pending work visible in single queue
- **Recovery:** Failed tasks can be retried without re-running entire cron

### Why Preserve Discord Channel Structure?

- **Minimal disruption:** Fred's workflows unchanged
- **Agent dispatch:** Channels become natural task routing mechanism
- **Audit trail:** All inter-agent communication visible in Discord
- **Human oversight:** Fred can observe all agent interactions

---

## Future Evolution

**Phase 2 Capabilities (potential):**
- **Bam-Bam integration:** Cursor-based coding agent via API bridge
- **Barney automation:** Direct API integration vs. claude.ai manual
- **Local LLM Tier 4:** Cost optimization for bulk processing
- **Cross-project coordination:** Queue system scales to multiple products

---

*This architecture represents a foundational shift toward enterprise-grade AI operations while preserving the collaborative, transparent culture that made the original system successful.*

**Next major review:** Q2 2026 or after 90 days of operation, whichever comes first.

---

**Reference:** Full implementation details in Change Manifest v1.0 (`hazeydata/operations/docs/CHANGE_MANIFEST_20260320.md`)