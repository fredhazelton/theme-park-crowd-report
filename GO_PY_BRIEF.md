# GO.py Build Brief for Claude

## Context

We have built the core accountability enforcement layer for hazeydata.ai:
- `gazoo_parser.py` — parses Gazoo reviews into improvement_ledger.json
- `prompt_injector.py` — injects enforcement instructions into agent cron prompts
- `escalation_engine.py` — monitors agent scores and escalates low performers

Now we need **GO.py** — the orchestrator that ties everything together and gives Fred a way to authorize and execute autonomous projects.

## What GO.py Does

GO.py is Fred's interface for spinning up autonomous work. Fred writes **natural language** in Discord. GO.py parses it, shows the command for approval, waits for Fred to react ✅/❌/💬, then executes.

### The Flow

```
1. Fred writes in #the-lodge:
   "SSD scraper has 20 unmerged sources. Execute GO.py to ingest them, 
    target 92% coverage in 48h"

2. GO.py parses and posts to #go-manager forum:
   "PROPOSED GO.py TASK
    GO.py ssd-merge-sources --fix="20 unmerged sources, target 92% coverage in 48h"
    React ✅ to approve"

3. Fred clicks ✅

4. GO.py executes:
   - Creates PROJECT_STATE.json with targets, deadline, baseline
   - Spawns daily status cron
   - Spawns weekly report cron  
   - Spawns sub-agent to do the work
   - Posts announcement to #briefing
   - Git commits the change
```

## Core Requirements

### 1. Natural Language Parsing
Input: A Discord message with a problem and request
Output: Structured data
- `project_name` — derived from context (ssd, tpcr, accord, cdr)
- `problem_description` — the issue
- `target_metric` — what success looks like (e.g., "92% coverage")
- `deadline` — how long (e.g., "48h", "7 days")
- `budget` — optional, defaults to "unlimited"

### 2. Command Generation
Take parsed data and generate the GO.py command:
```bash
GO.py <project> --fix="<problem>, target <metric> in <deadline>"
```

### 3. Forum Post to #go-manager
Post a forum thread with:
- The GO.py command
- Full spec (what, why, target, deadline)
- Instructions to react ✅ to approve

### 4. Reaction Handling
Listen for reactions on the forum thread:
- ✅ = APPROVED → execute
- ❌ = REJECTED → close thread, no action
- 💬 = DISCUSS → Fred adds a comment with revisions, GO.py re-posts updated command

### 5. Execution (Once Approved)
Create and initialize a project:
```
~/clawd/projects/<project_name>/
  ├── PROJECT_STATE.json (targets, deadline, budget, current state)
  ├── cron_daily_status.json (cron job config)
  ├── cron_weekly_report.json (cron job config)
  └── logs/ (project execution logs)
```

PROJECT_STATE.json structure:
```json
{
  "project_name": "ssd-merge-sources",
  "owner": "wilma",
  "authorized_by": "fred",
  "authorized_at": "2026-03-19T22:52:00Z",
  "targets": {
    "primary_metric": "coverage_percent",
    "primary_target": 92.0,
    "secondary_metrics": []
  },
  "deadline": "2026-03-21T22:52:00Z",  // 48 hours from now
  "budget": "unlimited",
  "baseline": {
    "coverage_percent": 89.8,
    "measured_at": "2026-03-19T22:52:00Z"
  },
  "status": "executing",
  "crons_created": [
    "ssd-merge-status-daily",
    "ssd-merge-report-weekly",
    "ssd-merge-escalation"
  ],
  "sub_agent": {
    "label": "ssd-merge-20-sources",
    "spawned_at": "2026-03-19T22:52:00Z"
  }
}
```

### 6. Cron Jobs to Create
Three crons for every project:

**Daily Status** (runs every day)
- Measures current progress vs target
- Logs to project/logs/status.jsonl
- If trending wrong, flags it

**Weekly Report** (runs Sundays)
- Posts to #briefing with progress update
- Current vs target, trend, next steps

**Escalation Check** (runs daily)
- If project misses targets 2+ days, auto-escalates
- Adds warning to sub-agent prompt
- Notifies #briefing

### 7. Sub-Agent Spawning
When GO.py executes, spawn a sub-agent with:
```
Task: [problem description]
Target: [metric] target in [deadline]
Budget: [budget]

Success = project reaches targets within deadline.
Autonomously execute until done.
Report progress to #school-schedules daily.
When complete, post final report to #briefing and #fred-wilma.
```

### 8. Git Commit
Once executed, commit:
```bash
git add projects/<project>/PROJECT_STATE.json
git commit -m "go: <project>-<short-goal>

Target: <metric>
Deadline: <deadline>
Authorized by: Fred"
```

## Technical Details

### Input Source
GO.py listens on #the-lodge Discord messages. Use Discord API to:
- Monitor #the-lodge for messages mentioning "Execute GO.py"
- Extract the natural language
- Parse it
- Post proposal to #go-manager

### Discord Integration
- Post forum threads to #go-manager (channel_id: TBD)
- Listen for reactions (✅ ❌ 💬)
- Post announcements to #briefing (channel_id: 1482227277508120576)
- Post execution updates to #fred-wilma (channel_id: 1479351572386414675)

Use the existing `message` tool from Clawdbot for all Discord actions.

### File Storage
All project state in: `~/clawd/projects/<project_name>/`

### Sub-Agent Spawning
Use `sessions_spawn` to create autonomous work agents:
```python
sessions_spawn(
    task="<full task description>",
    label=f"{project_name}-execution",
    model="sonnet",
    runTimeoutSeconds=86400  # 24 hours, adjust per project
)
```

## Expected Output

1. **Script:** `~/clawd/scripts/GO.py` (fully functional)
2. **Git:** Commit with enforcement scripts (already done: 026a53d)
3. **Readiness:** Ready to use immediately — Fred types in Discord, GO.py responds

## Testing

Before handoff, verify:
- [ ] Natural language parsing works (test with sample Discord messages)
- [ ] Forum thread posting works (#go-manager creates thread correctly)
- [ ] Reaction handling works (bot detects ✅ ❌ 💬)
- [ ] PROJECT_STATE.json created correctly
- [ ] Cron jobs created and would execute
- [ ] Sub-agent spawning works
- [ ] Git commit happens

## Success Criteria

GO.py is "done" when:
1. Fred can type "Execute GO.py to do X in Y time" in #the-lodge
2. GO.py posts a proposal to #go-manager
3. Fred reacts ✅
4. GO.py creates PROJECT_STATE.json and spawns the work
5. Daily/weekly crons are set up
6. Work executes autonomously

## Notes

- Don't over-engineer. This is functional tooling, not production code.
- Error handling is important (network failures, Discord API issues, missing context)
- Make the natural language parsing flexible — Fred won't always phrase things the same way
- When in doubt, ask Fred for clarification in #go-manager before executing
- The existing 3 scripts (gazoo_parser, prompt_injector, escalation_engine) are already working — GO.py uses those, doesn't replace them

---

**Built by:** Barney (Claude in Claude.ai)
**For:** Fred Hazelton
**Status:** Ready to build
