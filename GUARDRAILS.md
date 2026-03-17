# GUARDRAILS.md — Flintstones Framework Safety Rules
> **Status:** Active — referenced by all agent sprint prompts
> **Created:** 2026-03-16
> **Author:** Fred Hazelton + Wilma

---

## Core Principle
**Anything that leaves the building needs a human stamp. Inside the building, agents work freely.**

---

## 🔴 HARD BLOCKS — Always Require Fred's Approval
These actions are NEVER autonomous. Route through #content-review (✅/❌) or ask Fred directly.

| Action | Route |
|--------|-------|
| Post to social media (X, Reddit, Instagram) | #content-review → ✅/❌ |
| Send emails from hazeydata.ai | Ask Fred |
| Publish new blog posts | #content-review → ✅/❌ |
| Delete repos, branches, or production data | Ask Fred |
| Any financial transaction or signup | Ask Fred |
| Change DNS, domains, or auth credentials | Ask Fred |
| Modify pipeline production config | Ask Fred or Wilma |
| Push to public-facing repos without tests passing | Blocked — tests are the gate |
| Override Gazoo's QA veto | Fred only |

---

## 🟡 SOFT GATES — Agent Can Act, Gets Reviewed
These actions are allowed but tracked and audited.

| Action | Review By |
|--------|-----------|
| Code pushes to main branch | Gazoo nightly review + Wilma spot-check |
| Filing GitHub issues | Gazoo audits for spam/noise |
| Cross-team task assignment | Wilma monitors for runaway loops |
| Content drafts (not published) | Domain QA agent reviews |
| Design changes to website | Pebbles creates → Betty/Gazoo review |
| Task status changes | Dino manages, Wilma audits |

---

## 🟢 FULLY AUTONOMOUS — No Approval Needed
These actions are safe and unrestricted.

- Reading files, repos, data
- Running tests
- Writing to own workspace/notes/memory
- Posting to own Discord channel
- Logging to QA ledger
- Web searches and research
- Git commits to feature branches
- Filing issues (within cap, see below)
- Updating task statuses
- Running analysis scripts

---

## System-Level Guardrails

### 1. Issue Creation Cap
No agent files more than **10 GitHub issues per sprint session**. Prevents Gazoo or Bam-Bam from flooding the backlog with noise. If you find more than 10 issues, log the extras in your sprint report and file them next session.

### 2. Three-Round Max Rule
If the same task bounces between maker and checker **3 times** without resolution:
1. **Round 3 fails** → Auto-escalate to Wilma
2. **Wilma can't resolve** → Escalate to Fred
3. **Task gets reclassified** if the agent type can't handle it

This prevents infinite QA loops (the recursion termination condition).

### 3. Sprint Session Time Cap
If a sprint session runs longer than **15 minutes of active processing**, wrap up and report what's remaining for the next sprint. Prevents rabbit holes and token burn.

### 4. Runaway Loop Detection
If Agent A assigns a task to Agent B, who assigns it back to Agent A, who assigns it back to Agent B — that's a loop. After **2 bounces**, the task escalates to Wilma for resolution.

### 5. No Self-Approval
No agent can approve their own QA ledger entries. The maker and checker must always be different agents. Gazoo can review anyone. Wilma can review anyone except her own work (Gazoo reviews Wilma).

### 6. Correlated Error Prevention
For critical/pre-ship decisions, use **two different agents** for QA — not just one. Example: Bam-Bam writes code → Barney reviews logic → Gazoo audits independently. Two independent checks catch more than one.

### 7. External Communication Freeze Hours
No automated external communications (tweets, emails) between **11 PM and 7 AM ET**. Prevents embarrassing middle-of-the-night posts if something goes wrong.

### 8. Data Deletion Policy
- Use `trash` instead of `rm` wherever possible (recoverable beats gone forever)
- Never delete production data without Fred's explicit approval
- Git history is sacred — never force push or rewrite history on main
- Backups before bulk operations

---

## Escalation Chain
```
Agent → Wilma (Tier 2) → Fred (Tier 1)
                ↑
            Gazoo can escalate directly to Fred
            on quality veto issues
```

### 🎯 Three Ideas Rule for Quality Escalations
When escalating ANY quality problem or decision to Fred, the escalation MUST include:

1. **Problem description:** Clear explanation of what's wrong and how it was detected
2. **Three concrete solutions:** Each with pros/cons/effort/expected outcome
3. **Agent's recommendation:** Which option they think is best and why

**No exceptions.** Escalations without 3 realistic fix options will be bounced back to the agent.

This applies to:
- Data quality issues
- Code bugs and technical problems  
- Process failures
- Strategic decisions
- QA disagreements between agents
- Performance/accuracy problems

See FRAMEWORK.md "Three Ideas Rule & Decision Learning" section for full details.

---

## Audit Trail
Everything is tracked:
- **QA Ledger** (`data/qa_ledger.json`) — every deliverable, every review
- **Git history** — every code change
- **Discord channels** — every sprint report
- **GitHub issues** — every ticket filed
- **Gazoo reviews** (`gazoo-reviews/`) — daily audits

If it's not logged, it didn't happen.

---

*These guardrails exist to protect Fred's reputation, finances, and data. They're non-negotiable.*
*Update this file when new risks are identified.*
