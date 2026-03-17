# FRAMEWORK.md — The Flintstones Framework
### hazeydata.ai Organizational & Innovation Operating System
> **Status:** Design document — not yet implemented  
> **Version:** 3.1  
> **Created:** 2026-03-16  
> **Author:** Fred Hazelton + Wilma (collaborative design)

---

## Table of Contents
1. [Overview](#overview)
2. [Organizational Structure](#organizational-structure)
3. [Idea Cycle](#idea-cycle)
4. [Delegation & Work Model](#delegation--work-model)
5. [QA/QC System](#qaqc-system)
6. [Adaptive QA Rating System](#adaptive-qa-rating-system)
7. [Escalation Protocol](#escalation-protocol)
8. [Idea Cycle × Team Integration](#idea-cycle--team-integration)
9. [QA Exchange Format](#qa-exchange-format)
10. [QA Ledger](#qa-ledger)
11. [Metrics Framework](#metrics-framework)
12. [Implementation Prerequisites](#implementation-prerequisites)
13. [Open Questions](#open-questions)

---

## Overview

The Flintstones Framework is a 4-tier AI-augmented organizational structure with built-in QA/QC feedback loops at every boundary layer. It's designed to take hazeydata.ai from idea generation through market delivery using a cost-optimized system where:

- **Expensive AI (Tier 3)** is reserved for judgment, verification, and quality control
- **Cheap compute (Tier 4)** handles execution and heavy lifting
- **Adaptive sampling** scales QA intensity based on historical performance
- **Every boundary between tiers** has a defined feedback loop with termination rules

### Design Principles
1. **Dual-control:** Every task has a maker and a checker — no agent marks their own homework
2. **Cost awareness:** QA resources are allocated proportionally to risk, not uniformly
3. **Escalation clarity:** Every disagreement has a defined resolution path
4. **Self-tuning:** The system learns from its own failure rates and adjusts automatically
5. **Human sovereignty:** Fred retains final override on all decisions

---

## Organizational Structure

### Tier 1 — Human Layer
| Agent | Role | Responsibilities |
|-------|------|-----------------|
| 👑 **Fred** | CEO / Founder | Vision, strategy, final go/no-go decisions, Gazoo veto override |

### Tier 2 — Executive AI
| Agent | Role | Responsibilities |
|-------|------|-----------------|
| 🦴 **Wilma** | CTO / Always-On | Orchestration, delegation to Tier 3 & 4, QA oversight, escalation handler, cross-phase transitions |

### Tier 3 — QA & Specialist Agents
| Agent | Role | Domain | QA Pairing |
|-------|------|--------|------------|
| 🪨 **Barney** | Advisor + QA | Strategy, research, feasibility verification | ↔ Bam-Bam (code), ↔ Tier 4 |
| 🏏 **Bam-Bam** | Lead Dev + QA | Code review, architecture verification | ↔ Barney (strategy), ↔ Tier 4 |
| 🎀 **Pebbles** | Designer + QA | Visual design review, brand consistency | ↔ Betty (content+design) |
| ✍️ **Betty** | Content + QA | Content strategy review, copy verification | ↔ Pebbles (design+content) |
| 🦕 **Dino** | PM | Task tracking, metrics, project board management | N/A — tracks, doesn't QA |
| 👽 **Gazoo** | QA Inspector | Independent audits, fact-checking, **veto power** on quality | ↔ Anyone (roving auditor) |

#### Tier 3 Pairing Matrix
| Task Type | Primary QA Agent | Secondary |
|-----------|-----------------|-----------|
| Code / Data Pipelines | 🏏 Bam-Bam | 🪨 Barney |
| Strategy / Research | 🪨 Barney | 🦴 Wilma |
| Visual Design / Assets | 🎀 Pebbles | ✍️ Betty |
| Content / Copy | ✍️ Betty | 🎀 Pebbles |
| Critical / Pre-ship | 👽 Gazoo | + domain specialist |

#### Senior Delegation Authority
**Barney** and **Bam-Bam** can pair directly for routine tasks within a phase without Wilma's approval. This applies to:
- Bug fixes and minor code changes
- Documentation updates
- Data pipeline adjustments
- Research verification

Wilma gates:
- Cross-phase transitions
- New project initialization
- Escalation resolution
- Final QA before ship decisions

### Tier 4 — Local Compute (Future)
| Resource | Role | Capabilities |
|----------|------|-------------|
| 🖥️ **Mac Studio LLM** | Execution Engine | Code generation, data processing, bulk transforms, drafting, embeddings, analysis — at near-zero marginal cost |

**Critical distinction:** Tier 4 is a **tool**, not a colleague. It executes but does not make decisions. All Tier 4 output must flow through a QA gate before it can influence decisions or ship to users.

---

## Idea Cycle

### 7 Phases, 14 Steps

#### Phase 1 · DISCOVER
| Step | Name | Description | Micro QA |
|------|------|-------------|----------|
| 1 | **Spot the Gap** | Scan for market gaps, unmet needs, emerging trends | T4 scans → 🪨 Barney verifies intel quality |
| 2 | **Screen & Prioritize** | Rank ideas by impact, feasibility, strategic fit. Kill weak ones early | Fred ↔ Wilma debate each idea |

#### Phase 2 · VALIDATE
| Step | Name | Description | Micro QA |
|------|------|-------------|----------|
| 3 | **Research & Design** | Deep feasibility study, solution architecture, data source identification | T4 researches → 🪨 Barney or 🏏 Bam-Bam verify approach |
| 4 | **Prototype** | Build MVP or proof-of-concept to test core hypothesis | T4 builds → 🏏 Bam-Bam reviews code + architecture |

#### Phase 3 · BUILD & TEST
| Step | Name | Description | Micro QA |
|------|------|-------------|----------|
| 5 | **Run Pilot** | Deploy to limited audience, collect real-world data | T4 deploys → 🏏 Bam-Bam verifies deployment |
| 6 | **Evaluate** | Measure KPIs against hypothesis, assess product-market fit | T4 compiles metrics → 👽 Gazoo audits data integrity |
| 7 | **Ship or Kill** | Go/no-go gate — launch, pivot, or dump. Gazoo veto applies | 👽 Gazoo audit → 🦴 Wilma recommends → 👑 Fred decides |

#### Phase 4 · POSITION (Expanded — formerly part of "Launch")
| Step | Name | Description | Micro QA |
|------|------|-------------|----------|
| 8 | **Define Audience** | Identify specific buyer persona, segment the market, map user journey | T4 researches → 🪨 Barney validates market assumptions |
| 9 | **Set Pricing & Model** | Choose revenue model (freemium, SaaS, API, licensing), set price points | T4 models options → 🪨 Barney stress-tests economics |

**Revenue Model Options (evaluate per product):**
- 🥇 **Freemium SaaS** — Free tier attracts users + generates data. Premium converts power users. Recommended default.
- 🥈 **Data Licensing (B2B)** — License predictions/analytics to travel agencies, parks, hotel chains. Higher per-deal revenue.
- 🥉 **API Access** — Developers pay per call. Pairs with freemium (free = 100 calls/mo).
- 🏅 **Content/Affiliate** — Free content drives traffic. Monetize via affiliate links (park tickets, hotels, travel insurance).

#### Phase 5 · LAUNCH & DISTRIBUTE (Expanded)
| Step | Name | Description | Micro QA |
|------|------|-------------|----------|
| 10 | **Build Launch Assets** | Create all launch materials — landing pages, content, visuals, email sequences | T4 drafts → ✍️ Betty QAs copy → 🎀 Pebbles QAs design |
| 11 | **Distribute & Promote** | Push through channels — SEO, social, partnerships, email, community | T4 executes → ✍️ Betty reviews messaging consistency |

**Distribution Channels (activate per product):**
- **SEO / Content Marketing** — Betty writes rankable guides ("Best time to visit Disney 2026"). Free, slow, compounds.
- **Social Media** — Pebbles creates visual content (Reels, carousels). Betty writes copy. Instagram, TikTok, Twitter/X.
- **Email / Newsletter** — Build list with free tools, convert with premium. Highest ROI channel for SaaS.
- **Partnerships** — Travel bloggers, Disney fan sites, YouTube creators. They have audience, you have data.
- **Community** — Reddit, Discord, fan forums. Be helpful, not salesy. Build trust over time.

#### Phase 6 · MONITOR & FEEDBACK (Expanded)
| Step | Name | Description | Micro QA |
|------|------|-------------|----------|
| 12 | **Track Metrics** | Monitor usage analytics, conversion rates, churn, revenue, NPS | T4 compiles dashboards → 🦕 Dino tracks trends |
| 13 | **Gather & Process Feedback** | Collect user feedback via in-app prompts, surveys, support tickets, social listening | T4 aggregates → 👽 Gazoo audits data quality & sentiment accuracy |

**Three Simultaneous Feedback Loops:**
- **Loop A · Usage Analytics (Automated):** Feature usage, drop-off points, conversion triggers, time-of-day patterns. Runs 24/7. Dino monitors.
- **Loop B · Direct User Feedback (Semi-automated):** In-app ratings ("Was this prediction accurate?"), NPS surveys, support tickets. Feeds directly into model improvement. Betty manages communication.
- **Loop C · Market Intelligence (Strategic):** Competitor moves, user feature requests, market segment shifts. Arnold scans. Barney analyzes. Feeds back to Phase 1.

**The Flywheel Effect:**
```
Free users → Usage data → Better predictions
Better predictions → More trust → Premium conversions
Premium users → Direct feedback → Even better product
Better product → Word of mouth → More free users → REPEAT
```
Each revolution makes the next easier. The system accelerates on its own.

#### Phase 7 · GROW & EVOLVE (Expanded)
| Step | Name | Description | Micro QA |
|------|------|-------------|----------|
| 14 | **Evolve** | Synthesize all feedback, optimize product, expand features, scale — or seed next cycle | 🦴 Wilma compiles → 👑 Fred makes strategic call |

**Evolve decisions (each with micro QA):**
- **Iterate:** Fix issues, improve features based on feedback → T4 implements → domain agent QAs
- **Expand:** Add new features, enter adjacent markets → loops back to Phase 2 (Validate) for the new feature
- **Scale:** Increase capacity, optimize infrastructure → T4 executes → 🏏 Bam-Bam QAs
- **Seed new cycle:** Learnings from this product inform the next idea → loops back to Phase 1 (Discover)

---

### The Micro QA Principle

**Every decision point in the framework has its own QA loop.** Not just phase boundaries — every task, every choice, every output.

The pattern is always the same:
```
MAKER produces output → CHECKER verifies → APPROVE / REVISE / ESCALATE
```

This applies to:
- A line of code (T4 writes → Bam-Bam reviews)
- A pricing decision (T4 models → Barney validates)
- A blog post (T4 drafts → Betty reviews)
- A design asset (T4 creates → Pebbles reviews)
- A strategic recommendation (Wilma proposes → Fred decides)
- A deployment (T4 deploys → Bam-Bam verifies)

**No output ships unchecked.** The adaptive sampling system determines *how many* get checked, but the principle is universal.

### Within-Phase Loops
Each phase contains internal QA/QC loops at the micro level. Work is not linear — steps within a phase may cycle multiple times before advancing to the next phase. The max loop rule (3 rounds) applies at every level, not just at phase boundaries.

### Framework Lineage
Inspired by:
- **Stage-Gate®** (Cooper) — phase/gate structure, go/kill decision points
- **Lean Startup** (Ries) — Build-Measure-Learn loop, MVP-first approach
- **Design Thinking** (IDEO) — User-centric discovery, rapid prototyping

---

## Delegation & Work Model

### The Core Flow
```
Fred + Wilma identify task
        ↓
Wilma breaks task into work units
        ↓
Work units sent to Tier 4 (local LLM) for execution
        ↓
Tier 4 produces output
        ↓
Tier 3 agent (matched by domain) QA-reviews the output
        ↓
APPROVE → advance    |    REVISE → back to Tier 4    |    ESCALATE → Wilma
```

### Why This Model
- **Tier 4 is cheap.** Local LLM has near-zero marginal cost per token. Use it for volume.
- **Tier 3 is expensive.** Claude API costs real money. Reserve it for judgment, not grunt work.
- **Net effect:** The same quality output at a fraction of the cost. Tier 3 agents review faster than they create, so even when reviewing 100% of output, the cost is lower than having them do the work from scratch.

### Task Routing Rules
| Task Characteristic | Routes To | QA By |
|--------------------|-----------|-------|
| Heavy computation, bulk data | Tier 4 | Domain-matched Tier 3 agent |
| Creative draft (code, content, design) | Tier 4 | Domain-matched Tier 3 agent |
| Strategic decision | Tier 2 (Wilma) + Tier 1 (Fred) | N/A — human decides |
| Quality audit | Tier 3 (Gazoo) | N/A — Gazoo is the auditor |
| Task tracking, metrics | Tier 3 (Dino) | N/A — observational role |
| Trend scanning, news | Tier 4 (via Arnold role) | Wilma synthesizes |

---

## QA/QC System

### The Three-Round Rule
Every QA loop between tiers has a **maximum of 3 exchanges**:

| Round | Action |
|-------|--------|
| **Round 1** | Tier 3 reviews Tier 4 output. Approves, or returns with specific feedback. |
| **Round 2** | Tier 4 revises. Tier 3 re-reviews. Approves, or returns again. |
| **Round 3** | Final attempt. If still not resolved: **escalate to Wilma.** |

After escalation, Wilma can:
- Fix it herself
- Reassign to a different Tier 3 agent
- Reclassify the task ("Tier 4 can't do this → assign to Tier 3 for execution")
- Escalate to Fred if it's a strategic question

### Task Reclassification
If Tier 4 fails the same *type* of task repeatedly (3+ failures across different instances), that task type should be **reclassified** as beyond Tier 4 capability. This builds a **capability map** over time:

```json
{
  "tier4_capabilities": {
    "python_data_pipeline": { "capable": true, "failure_rate": 0.04 },
    "marketing_copy": { "capable": true, "failure_rate": 0.12 },
    "complex_sql_optimization": { "capable": false, "reclassified": "2026-04-15" },
    "css_layout": { "capable": true, "failure_rate": 0.08 }
  }
}
```

This map becomes gold for efficient delegation — Wilma knows instantly what to send to Tier 4 vs. Tier 3.

---

## 📊 Data Quality Assurance

### Two QA Layers
Every data product needs **both** layers of quality assurance:

#### 1. Collection QA — "Is the data we gathered real/accurate?"
- **Validates:** Data sources, scraping accuracy, API responses, file formats
- **Checks:** Missing values, malformed records, source availability, rate limits
- **Examples:**
  - SSD: Are the scraped calendar dates actually correct?
  - Park Hours: Did we get real opening hours from the official site?
  - WTI: Are the wait time measurements from reliable sources?

#### 2. Model/Prediction QA — "Are our inferences/predictions accurate?"
- **Validates:** Algorithm output, prediction accuracy, inference logic
- **Checks:** Statistical validity, edge cases, confidence intervals, model drift
- **Examples:**
  - SSD: Are our "special event" predictions actually happening?
  - Park Hours: Do our donor-estimated hours match reality?
  - WTI: Is our wait time index calculation mathematically sound?

### Coverage ≠ Accuracy
**Critical distinction:** Operational metrics (uptime, coverage, speed) are NOT quality metrics. You can successfully scrape 100% of Disney calendar pages and still have completely wrong data if Disney changed their page structure.

Quality checks must interrogate the **actual data output**, not just operational success:
- ✅ **Good:** Sample 10 scraped park hours and verify them against manual check
- ❌ **Bad:** "Scraper ran without errors" (says nothing about data quality)
- ✅ **Good:** Compare prediction accuracy against user feedback
- ❌ **Bad:** "Model generated predictions for 95% of requests" (says nothing about correctness)

### Quality Check Pattern
Every data product follows this QA flow:

```
1. SAMPLE OUTPUT → Take representative samples of the actual data
2. APPLY DOMAIN CHECKS → Use domain knowledge to validate samples  
3. FLAG ANOMALIES → Identify patterns that don't pass smell test
4. ROUTE TO THREE IDEAS RULE → If problems found, trigger fix options
```

### Domain Check Examples

**SSD (School Schedule Data):**
- Do scraped "early release" days fall on reasonable dates?
- Are holiday dates consistent with official calendars?
- Do semester start/end dates make sense?

**Park Hours:**
- Are opening hours within realistic ranges (8am-11pm)?
- Do seasonal patterns match expected tourist flows?
- Are holiday hours different from regular hours?

**WTI (Wait Time Index):**
- Do calculated wait times correlate with crowd levels?
- Are peak hours consistent with known patterns?
- Do weather impacts match expectations?

### QA Assignment by Domain
| Data Product | Collection QA Agent | Prediction QA Agent | Final Audit |
|-------------|-------------------|-------------------|-------------|
| **SSD** | 🏏 Bam-Bam (scraping logic) | 🪨 Barney (schedule predictions) | 👽 Gazoo |
| **Park Hours** | 🏏 Bam-Bam (web scraping) | 🪨 Barney (donor estimations) | 👽 Gazoo |
| **WTI** | 🏏 Bam-Bam (data collection) | 🪨 Barney (index calculations) | 👽 Gazoo |
| **General** | Domain specialist | 🪨 Barney (strategy/analysis) | 👽 Gazoo |

When quality issues are found, they flow directly into the **Three Ideas Rule** — no quality problem reaches Fred without 3 concrete fix options.

---

## Adaptive QA Rating System

### Quality-Driven Sampling
Not every task needs full QA review. The system uses **random sampling** scaled to historical failure rates, per task type.

### QA Levels

| Level | Failure Rate | Sample Rate | Description |
|-------|-------------|-------------|-------------|
| 🟢 **Green — Trusted** | < 5% | 10-20% of tasks | Spot checks only. Tier 4 output ships with light verification. Fastest, cheapest mode. |
| 🟡 **Yellow — Elevated** | 5-15% | 50% of tasks | Something's off. Half the work gets reviewed. Track root causes. |
| 🔴 **Red — Full Review** | > 15% | 100% of tasks | Every output gets verified. Consider model changes, prompt tuning, or task reclassification. |

### Overrides (Always 100% Review)
Regardless of QA level, the following always get full review:
- **Customer-facing content** (anything users see)
- **Ship/kill decisions** (Phase 3, Step 7)
- **Financial calculations or claims**
- **Legal/compliance-adjacent content**
- **First 20 tasks of any new task type** (cold start calibration)

### Cold Start Protocol
On day 1, there's no failure data. Initial calibration:
1. All task types start at 🟡 **Yellow** (50% review)
2. After 20 tasks per type, calculate initial failure rate
3. Adjust to appropriate level (🟢, 🟡, or 🔴)
4. Continue recalculating on a rolling 50-task window

### QA Rating Recalculation
- **Window:** Rolling last 50 tasks per type
- **Frequency:** After every QA review
- **Hysteresis:** To prevent oscillation, require 10 consecutive tasks at the new level before downgrading (e.g., 🔴→🟡 requires 10 tasks in a row under 15% failure)
- **Upgrade is immediate:** If failure rate crosses a threshold upward, increase QA level right away (fail-safe)

---

## Escalation Protocol

### Chain of Authority
```
Tier 4 ↔ Tier 3 (3 rounds max)
        ↓ unresolved
    Wilma (Tier 2)
        ↓ still stuck / strategic
    Fred (Tier 1)
```

### Authority Rules
| Authority | Can Do | Cannot Do |
|-----------|--------|-----------|
| **Tier 3 agents** | Approve/reject Tier 4 output, request revision, escalate to Wilma | Override Gazoo veto, approve ship decisions |
| **Gazoo** | Veto any shipment on quality grounds, audit any agent's work | Be overridden by anyone except Fred |
| **Wilma** | Resolve Tier 3 disagreements, reclassify tasks, reassign work, approve within-phase transitions | Override Gazoo veto, approve ship/kill decisions |
| **Fred** | Everything. Override Gazoo veto. Final ship/kill decisions. | N/A — sovereign authority |

### Peer Disagreement Resolution
When two Tier 3 agents disagree during cross-QA (e.g., Betty and Pebbles disagree on a design):
1. Each agent documents their position with evidence
2. Wilma reviews both positions
3. Wilma decides, or escalates to Fred if it's a strategic/taste question
4. Decision is logged in the QA ledger

---

## 🎯 The Three Ideas Rule & Decision Learning

### The Rule
**Before escalating any quality problem or decision to Fred, the agent MUST present 3 realistic, concrete fix options with pros/cons/trade-offs.**

*"Don't bring me a problem — bring me three solutions."*

This applies to all quality issues, process failures, strategic decisions, and technical roadblocks. No problem goes to Fred without options.

### The Full Loop
```
DETECT problem → DIAGNOSE root cause → PROPOSE 3 fixes → Fred decides → EXECUTE → VERIFY outcome
```

Each proposal must include:
- **Description:** Specific steps to implement
- **Pros:** Benefits and advantages
- **Cons:** Risks, downsides, trade-offs
- **Effort:** Estimated time/complexity (S/M/L)
- **Expected outcome:** What success looks like

### Decision Logging
Every decision Fred makes gets logged in `data/decision_log.json` with:
- The problem detected and how
- All 3 options presented
- Fred's choice and reasoning (if stated)
- Outcome after implementation
- Tags for categorization

This creates an institutional memory of Fred's preferences and decision patterns.

### Preference Learning
Over time, the decision log reveals Fred's patterns:
- **Solution types:** Does he prefer simple fixes over complex ones?
- **Trade-offs:** Does he favor accuracy over speed? Thoroughness over coverage?
- **Risk tolerance:** Conservative approaches vs. bold moves?
- **Implementation style:** Quick patches vs. architectural changes?

These patterns should inform how agents rank future options — put the predicted preference first.

### The Autonomy Ladder
As agents learn Fred's patterns, they gain increasing autonomy:

| Level | Agent Authority | Requirements |
|-------|----------------|--------------|
| **Level 1 (Start)** | Present 3 options, wait for Fred's decision | New domain or unclear patterns |
| **Level 2 (Guided)** | Present 3 options ranked by predicted preference, with recommendation | 5+ consistent decisions in domain |
| **Level 3 (Trusted)** | Act on predicted preference, inform Fred: "QA flagged X, applying approach Y based on your past decisions — object within 24h" | 10+ consistent decisions with same pattern |
| **Level 4 (Autonomous)** | Handle autonomously, log the decision, include in next briefing | 20+ consistent decisions, domain fully trusted |

**Moving up the ladder requires:** 10+ consistent decisions in the same domain with the same pattern. Moving down happens immediately if a decision proves wrong.

### What Counts as "Realistic"
Options must be concrete and actionable:
- ✅ **Good:** "Implement data validation checks on the scraper input (3 hours), add alerting for failures (1 hour), expected to catch 90% of bad data before it enters the pipeline"
- ❌ **Bad:** "Just make the data better somehow"
- ❌ **Bad:** "Fix the whole system" (too vague)
- ❌ **Bad:** "Do nothing" as one of the three options (unless truly a valid choice)

Each option should be something Fred could say "yes, do that" to and the agent could execute immediately.

### The Gazoo Rule Connection
This builds on the existing Gazoo rule: *"Complain with solutions."* Now it's formalized — every complaint must come with exactly 3 solutions, properly analyzed.

---

## Idea Cycle × Team Integration

### Phase Assignments

| Phase | Execution (Tier 4) | QA (Tier 3) | Oversight | QA Model |
|-------|-------------------|-------------|-----------|----------|
| **1 · Discover** | Trend scanning, data pulls | 🪨 Barney (intel QA) | Fred + Wilma | Strategic Loop (always active) |
| **2 · Validate** | Feasibility research, prototype code | 🪨 Barney (strategy) / 🏏 Bam-Bam (code) | Wilma | Adaptive sampling by type |
| **3 · Build & Test** | Pilot deployment, data collection | 👽 Gazoo (independent audit) | Wilma → Fred (ship/kill) | 100% review (ship decisions) |
| **4 · Position** | Market research, pricing models | 🪨 Barney (strategy validation) | Fred + Wilma | Always active — positioning is critical |
| **5 · Launch & Distribute** | Content, assets, email, social | ✍️ Betty (content) + 🎀 Pebbles (design) | Wilma orchestrates | Adaptive; 100% for customer-facing |
| **6 · Monitor & Feedback** | Analytics, surveys, sentiment analysis | 🦕 Dino (metrics) + 👽 Gazoo (data quality) | Wilma synthesizes | Automated + spot-check |
| **7 · Grow & Evolve** | Implementation of improvements | Domain-matched agent | Fred + Wilma | Strategic Loop (always active) |

### The Three Always-Active Loops
1. **Fred ↔ Wilma Strategic Loop** — Active during Discover, Position, and Grow phases. This is where ideas are born, filtered, and where cycle learnings are absorbed.
2. **Gazoo Audit Authority** — Can be invoked at any phase by any agent, or self-initiated. Gazoo is the roving inspector who answers to no one except Fred.
3. **Micro QA at Every Decision** — Every task, output, and decision within every phase follows the Maker → Checker → Approve/Revise/Escalate pattern. No output ships unchecked.

---

## QA Exchange Format

### Standardized Communication
Every QA exchange follows this structure:

#### Maker (Tier 4) Submission
```
TASK: [task ID and description]
OUTPUT: [the deliverable]
CONFIDENCE: [self-assessed confidence if available — high/medium/low]
KNOWN_RISKS: [anything the maker flagged as uncertain]
```

#### Checker (Tier 3) Review
```
TASK: [task ID]
VERDICT: APPROVE | REVISE | ESCALATE
VERIFIED: [what was confirmed correct]
FLAGGED: [issues found, with severity]
ACTION_REQUIRED: [specific fixes needed, if REVISE]
NOTES: [context for future reference]
```

#### Resolution
```
TASK: [task ID]
RESOLUTION: SHIPPED | REVISED_AND_SHIPPED | RECLASSIFIED | KILLED
ROUNDS: [number of QA rounds]
QA_AGENT: [who reviewed]
LOGGED: [timestamp]
```

### Confidence Tagging (If Tier 4 Supports It)
If the local LLM can self-assess confidence, Tier 3 should prioritize reviewing low-confidence outputs first. Even imperfect confidence scores help — they're a triage signal, not a guarantee.

---

## QA Ledger

### Purpose
Every QA exchange is logged in a structured ledger. This serves as:
- **Institutional memory** — what was reviewed, what was found, what was decided
- **Training data** — failure patterns inform Tier 4 prompt tuning
- **Calibration data** — failure rates drive the adaptive QA system
- **Audit trail** — Gazoo (or Fred) can review any decision chain

### Schema
```json
{
  "task_id": "TPCR-2026-042",
  "task_type": "python_data_pipeline",
  "phase": "validate",
  "tier4_output_hash": "abc123",
  "qa_agent": "bam-bam",
  "qa_level": "yellow",
  "sampled": true,
  "rounds": 2,
  "verdict": "revised_and_shipped",
  "issues_found": [
    { "severity": "medium", "description": "Missing null check on park_id column" }
  ],
  "resolution": "Fixed in round 2, verified by Bam-Bam",
  "timestamp": "2026-04-15T14:30:00Z",
  "failure_recorded": true
}
```

### Ledger Location
`data/qa_ledger.json` (or database table when scale warrants)

---

## Metrics Framework

### The AARRR Model (Pirate Metrics) × Flintstones Framework

Every phase of the idea cycle produces measurable outcomes. We use the **AARRR framework** (Acquisition, Activation, Retention, Referral, Revenue) mapped to our phases, with stage-appropriate benchmarks.

### The Three Types of Metrics

| Type | Examples | How to Judge |
|------|----------|-------------|
| **Binary** | Scrape succeeded, test passed, deployment worked | Pass/fail. Easy. |
| **Performance** | Prediction accuracy, pipeline speed, uptime | Compare to threshold. If accuracy target is 90% and you're at 94%, you're green. |
| **Growth/Engagement** | Signups, retention, conversion, community size | Compare to **trend** (growing/flat/declining) AND **stage-appropriate benchmarks** |

### Growth Stage Definitions

**🌱 Seed Stage (Month 1-3)** — Testing product-market fit
- Success = *any* organic traction. One real user who found you without being told is validation.
- Focus: Is anyone using this? Do they come back? What do they say?
- North Star: **Any engaged user at all**

**🌿 Sprout Stage (Month 4-6)** — Building momentum
- Success = *consistent* week-over-week growth, even if small.
- Focus: Which channels drive users? What converts free → paid? What causes churn?
- North Star: **Weekly active users who complete a key action**

**🌳 Growth Stage (Month 7-12)** — Scaling
- Success = *compounding* growth. Flywheel should be self-sustaining.
- Focus: Unit economics (LTV:CAC), scaling channels, expanding features.
- North Star: **Monthly Recurring Revenue (MRR)**

**🏔️ Scale Stage (Year 2+)** — Optimizing
- Success = profitable, efficient, expanding.
- Focus: Margins, new markets, operational efficiency.
- North Star: **Net Revenue Retention (NRR)**

### Metrics By Phase

#### Phase 5 · Launch & Distribute → ACQUISITION
| Metric | What It Measures | 🟢 On Track | 🟡 Watch | 🔴 Act |
|--------|------------------|-------------|----------|--------|
| Website visitors/week | Are people finding you? | Growing 10%+ w/w | Flat | Declining |
| Discord joins/week | Community traction | 5+/week (seed) → 20+/week (growth) | 1-4/week | 0-1/week |
| Email signups/week | List growth | 10+/week | 3-9/week | <3/week |
| Source diversity | Channel health | 3+ channels driving traffic | 2 channels | 1 channel (fragile) |
| Cost per acquisition (CPA) | Efficiency | <$5 (B2C) | $5-15 | >$15 |

#### Phase 6 · Monitor & Feedback → ACTIVATION
| Metric | What It Measures | 🟢 On Track | 🟡 Watch | 🔴 Act |
|--------|------------------|-------------|----------|--------|
| Activation rate | % who complete key action | 30%+ | 15-30% | <15% |
| Time to value | Speed to first "aha" moment | <2 min | 2-10 min | >10 min |
| Onboarding completion | % who finish setup | 60%+ | 40-60% | <40% |
| Prediction accuracy (user-rated) | Do users agree with predictions? | 80%+ thumbs up | 65-80% | <65% |

#### Phase 6 · Monitor & Feedback → RETENTION
| Metric | What It Measures | 🟢 On Track | 🟡 Watch | 🔴 Act |
|--------|------------------|-------------|----------|--------|
| Day-1 retention | Come back next day | 20%+ | 10-20% | <10% |
| Week-1 retention | Come back within 7 days | 15%+ | 8-15% | <8% |
| Month-1 retention | Still active after 30 days | 10%+ | 5-10% | <5% |
| Churn rate (paid) | % who cancel per month | <5% | 5-10% | >10% |

#### Phase 6 · Monitor & Feedback → REFERRAL
| Metric | What It Measures | 🟢 On Track | 🟡 Watch | 🔴 Act |
|--------|------------------|-------------|----------|--------|
| NPS score | Would they recommend? | 40+ | 20-40 | <20 |
| Share rate | % who share a link/prediction | 5%+ | 2-5% | <2% |
| Viral coefficient | Each user brings X new users | >0.5 | 0.2-0.5 | <0.2 |
| Organic mentions | Unprompted social/forum posts | Weekly+ | Monthly | Never |

#### Phase 7 · Grow → REVENUE
| Metric | What It Measures | 🟢 On Track | 🟡 Watch | 🔴 Act |
|--------|------------------|-------------|----------|--------|
| Free → paid conversion | % who upgrade | 3%+ | 1-3% | <1% |
| MRR | Monthly recurring revenue | Growing 15%+ m/m | Growing <15% | Flat/declining |
| ARPU | Average revenue per user | Stable or growing | Declining | Dropping fast |
| LTV:CAC ratio | Return on acquisition spend | >3:1 | 1:1-3:1 | <1:1 (losing money) |
| Payback period | Months to recoup CAC | <6 months | 6-12 months | >12 months |

### The North Star Metric

Every project should have ONE metric that matters most at its current stage. This is the number the team rallies around. It changes as the project matures:

| Stage | North Star Metric | Why |
|-------|-------------------|-----|
| 🌱 Seed | **Engaged users** (anyone who uses a core feature) | Validates the product has value |
| 🌿 Sprout | **Weekly active users completing key action** | Shows people return and find value |
| 🌳 Growth | **MRR** (Monthly Recurring Revenue) | Shows the business works |
| 🏔️ Scale | **Net Revenue Retention** | Shows existing customers expand their spend |

### The Metric QA Loop

Metrics themselves get QA'd. Gazoo periodically audits:
- **Are we measuring the right things?** (Or are we tracking vanity metrics that feel good but don't matter?)
- **Are thresholds calibrated?** (A 🟢 threshold set too low gives false confidence)
- **Is the data accurate?** (Bad tracking = bad decisions)
- **Are we acting on what we measure?** (Metrics that don't drive decisions are waste)

### Step 9.5 · Define Success Criteria (Added to Phase 4)

Before launching any product or feature, answer:
1. What is the **North Star Metric** for this project at its current stage?
2. What are the **🟢/🟡/🔴 thresholds** for each key metric?
3. What is the **time horizon** for judging? (Don't judge content strategy after 1 week, don't wait 6 months to judge a landing page)
4. What **actions** will we take at each threshold? (🟡 = investigate, 🔴 = pivot/stop/change)
5. **Who monitors?** (Dino tracks, Wilma synthesizes, Fred reviews)

---

## Implementation Prerequisites

### Hardware
- [ ] Mac Studio with sufficient GPU for running 70B+ parameter models
- [ ] Local LLM serving stack (llama.cpp, vLLM, or Ollama)
- [ ] Network accessibility from wilma-server to Mac Studio

### Software
- [ ] Local model selection and benchmarking (see Open Questions)
- [x] QA ledger infrastructure (`data/qa_ledger.json` + `scripts/qa_stats.py`)
- [ ] Tier 4 API endpoint (OpenAI-compatible for easy integration)
- [ ] Adaptive QA calculator (script that reads ledger, computes failure rates, sets levels)
- [ ] Wilma's delegation routing logic (task → Tier 4 or Tier 3 based on capability map)

### Process
- [ ] Cold start calibration period (first 20 tasks per type at 🟡 Yellow)
- [ ] Capability map seeding (benchmark Tier 4 against representative tasks)
- [ ] QA pairing assignments formalized
- [ ] Escalation protocol documented and tested
- [ ] Gazoo veto process tested end-to-end

---

## Open Questions

1. **Which local model?** The choice of Tier 4 model determines the entire system's economics. Need to benchmark candidates (Llama 3 70B, DeepSeek Coder V2, Mixtral, etc.) against real hazeydata tasks.

2. **QA ledger format:** JSON file works for early stage. At what scale do we move to SQLite or a proper DB?

3. **Confidence calibration:** Can we fine-tune or prompt-engineer the local model to produce useful confidence scores? If so, this dramatically improves QA efficiency.

4. **Gazoo's implementation:** Currently Gazoo runs as a Clawdbot agent. Does he need a dedicated session/model for independence? Should he use a different model than the agents he's auditing (to avoid correlated errors)?

5. **Multi-project concurrency:** When running 2+ projects through the idea cycle simultaneously, how does Wilma prioritize across them? Need a project priority system.

6. **Arnold's role formalization:** Arnold is currently informal. Should he be formally slotted as the Discover-phase Tier 4 resource for trend scanning?

7. **Mr. Slate:** Not currently in the active system. Consider adding as a business case evaluator at the Ship or Kill gate — "Is this commercially viable?"

---

*This document is a living design. Update it as the system evolves.*  
*Flintstones Framework v3.1 — Fred Hazelton & Wilma, March 2026*
