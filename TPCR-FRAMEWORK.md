# TPCR-FRAMEWORK.md — Theme Park Crowd Report Operating Plan
> **Step 3 of Fred's Strategy:** The billion-dollar framework compressed to current scale.
> 
> This is the working document. Not aspirational — operational.
> 
> Last updated: 2026-03-16

---

## Where TPCR Sits Today

| Phase | Status | Notes |
|-------|--------|-------|
| ✅ Phase 1 — Discover | **Done** | Fred spotted the gap at TouringPlans years ago |
| ✅ Phase 2 — Validate | **Done** | Pipeline built, ACCORD engine proven, methodology documented |
| 🔄 Phase 3 — Build & Test | **Active** | Pipeline v3 in production (16 min, 22x faster than legacy). v4 accuracy improvements in progress. School schedule scraper: 5,919/6,123 districts (96.7%). Wait time collector running 24/7. |
| ⬜ Phase 4 — Position | **Partially done** | Website exists, brand exists. Pricing model designed ($12/mo premium) but not live. Buyer personas not formalized. |
| ⬜ Phase 5 — Launch | **Not started** | Betty + Pebbles assigned but no content engine yet |
| ⬜ Phase 6 — Monitor | **Not started** | Pipeline metrics tracked internally, no user-facing analytics |
| ⬜ Phase 7 — Grow | **Future** | |

**Current Stage Gate: Gate 0 (Pre-Revenue)**

**North Star Metric (Seed stage):** Engaged users — anyone using a core feature unprompted.

---

## The Team (Current Reality)

| Who | Role on TPCR | Actual Capacity | Current Focus |
|-----|-------------|-----------------|---------------|
| 👑 Fred | Vision, strategy, final decisions | Evenings + weekends (day job) | Framework planning, Reddit engagement, strategic direction |
| 🦴 Wilma | Orchestration, monitoring, daily ops | 24/7 (always on) | Scraper monitoring, pipeline health, heartbeat checks, task coordination |
| 🏏 Bam-Bam | Code, pipeline, dashboard | Session-based (Cursor) | Pipeline v4 accuracy, dashboard development |
| 🪨 Barney | Strategy QA, methodology | Session-based (Claude) | Pipeline methodology review, ACCORD engine validation |
| ✍️ Betty | Content, copy | Not yet active on TPCR | — |
| 🎀 Pebbles | Design, visuals | Not yet active on TPCR | — |
| 🦕 Dino | Metrics, tracking | Minimal (cron reports) | Daily pipeline reports, competitor watch |
| 👽 Gazoo | Independent audit | Session-based | Framework building, QA audits |

**Honest assessment:** Fred + Wilma + Bam-Bam are the active core. Barney consults. Everyone else is waiting for Phases 4-5.

---

## Current Priorities (This Week / This Month)

### 🔴 Must Do
1. **Pipeline v4 accuracy improvements** — MAE from 6.69 → target <5.0. Bam-Bam leads, Barney QAs methodology. Three pillars: smart synthetic weighting, better feature engineering, model tuning.
2. **School schedule scraper completion** — 96.7% done. Monitor remaining districts. Validate and normalize full corpus into pipeline-ready format.
3. **Keep the lights on** — Pipeline runs daily at 6am. Wait time collector runs 24/7. Wilma monitors. No unplanned downtime.

### 🟡 Should Do (This Month)
4. **Stripe integration** — Premium tier ($12/mo) setup is documented (`docs/STRIPE_PREMIUM_SETUP.md`). Needs implementation and testing.
5. **Website MVP polish** — Current site exists but needs crowd calendar as the primary feature. Free tier showing today's crowd levels for 4+ parks.
6. **Define user personas** — Planning Patty, Annual Andy, Data Dave, Agency Alice (or revised versions). Fred leads based on StatsCan experience.
7. **Claim @hazeydata on all platforms** — Twitter, Instagram, TikTok, Reddit, YouTube. Lock down the handles now.

### 🟢 Nice to Have (Next Month)
8. **First blog post** — "Disney World Crowd Predictions: [Month] 2026." Betty drafts, Barney verifies data claims.
9. **Discord community channel structure** — public channels designed, welcome message written, daily forecast automated.
10. **Google Search Console + Analytics** — instrument the site for SEO tracking.

---

## Decision Rights (TPCR-Specific)

Compressed from the full RACI. For this project, at this scale:

| Decision | Who Decides | Who Helps |
|----------|------------|-----------|
| Pipeline methodology changes | Barney approves, Bam-Bam implements | Fred informed |
| Pipeline code changes (non-methodology) | Bam-Bam decides | Wilma informed |
| Website content publish | Wilma approves | Betty drafts |
| Pricing changes | Fred decides | Barney + Wilma consult |
| External outreach (Reddit, partners) | Fred decides | Wilma drafts |
| Daily operations (monitoring, restarts) | Wilma decides | Fred informed only if anomaly |
| Design decisions | Pebbles proposes, Fred approves | — |
| Spending < $50 | Wilma can approve | Fred informed |
| Spending > $50 | Fred approves | — |

---

## Workflow: How Work Actually Flows

### Task Management — Recursive Improvement Loop

**Single source of truth: GitHub Issues** across all hazeydata repos (auto-discovered via `gh repo list hazeydata`).

**The Loop:**
```
1. Issues created (by agents, Gazoo, Fred, or anyone)
   → labeled with domain (testing, design, pipeline, etc.)
   
2. Auto-assigned (1:00 AM daily)
   → assign_stale_issues.py labels unassigned issues >24h old
   → domain labels determine which agent gets it
   
3. Agent picks up work (every sprint)
   → python3 ~/clawd/scripts/my_issues.py <agent>
   → assigned issues ALWAYS take priority over self-directed work
   
4. Agent executes → commits → comments results → closes issue

5. Agent creates NEW issues for problems found during work
   → feeds back into step 1

6. Gazoo reviews all work (9:00 PM daily)
   → grades agents, files quality issues
   → proposes prompt patches for recurring problems
   
7. Next day: cycle repeats
```

**Key Scripts:**
- `my_issues.py <agent>` — "What should I work on?" (scans all repos)
- `assign_stale_issues.py` — Auto-assigns unassigned issues after 24h
- `improvement_tracker.py` — Gazoo's grading and tracking system

**Label Convention:**
| Label | Purpose |
|-------|---------|
| Agent labels (bam-bam, pebbles, betty, etc.) | Assignment — who owns this |
| Domain labels (testing, design, pipeline, etc.) | Routing — which agent's domain |
| `sprint-ready` | Ready for an agent to pick up |
| `priority:high` / `priority:low` | Urgency |

**Discord Mirror:**
- #tasks channel shows a live read-only dashboard of all GitHub Issues
- Auto-refreshes periodically — NOT a separate task system
- Dino maintains the mirror, not a separate task list

**What we retired:**
- tasks.json (replaced by GitHub Issues)
- generate_tasks_json.py (no longer needed)
- stale_task_check.py (replaced by assign_stale_issues.py)

**Current reality:** Most work flows through GitHub Issues now. Fred creates strategic issues, agents pick them up via `my_issues.py`, work gets done and tracked automatically.

---

## Metrics That Matter Right Now

At Seed stage, only a few metrics are relevant. Don't track everything yet.

| Metric | Current | Target (Gate 1) | Who Tracks |
|--------|---------|-----------------|------------|
| Pipeline MAE | 6.69 | < 5.0 | Barney / pipeline logs |
| School districts scraped | 5,919 / 6,123 | 6,123 / 6,123 | Wilma (heartbeat) |
| Pipeline uptime | ~99% (daily cron) | 99%+ | Wilma (monitoring) |
| Website visitors/week | ~0 (not launched) | 100+ | Google Analytics |
| Discord members | ~0 (not launched) | 10+ | Discord |
| Reddit engagement | Occasional posts | 1 post/week with replies | Fred |
| GitHub Issues closed/week | varies | 5+ | my_issues.py tracking |
| Issue assignment coverage | varies | <24h avg | assign_stale_issues.py |

**Not tracking yet (dormant until Gate 1+):** MRR, conversion rate, churn, LTV, CAC, NPS. These metrics activate when there are users.

---

## Phase Transition Criteria

### Phase 3 → Phase 4 (Build → Position): WHEN?
All three must be true:
- [ ] Pipeline v4 accuracy: MAE < 5.0 consistently
- [ ] School schedule data: integrated into prediction model as a feature
- [ ] Website: shows crowd predictions for at least 4 parks with a usable interface

### Phase 4 → Phase 5 (Position → Launch): WHEN?
All must be true:
- [ ] Pricing model finalized and Stripe integration working
- [ ] User personas defined and validated (at least 3 Reddit conversations confirming assumptions)
- [ ] Free tier clearly differentiated from Pro tier
- [ ] Privacy policy and Terms of Service live

### Phase 5 → Phase 6 (Launch → Monitor): WHEN?
- [ ] Product publicly accessible (not just friends and family)
- [ ] First 50 organic users (found you without being told)
- [ ] At least one feedback mechanism live (Discord, email, or in-app)

---

## How This Maps to the Big Framework

| Big Framework Section | TPCR Status | Action |
|----------------------|-------------|--------|
| Flintstones Org Chart | Using Fred + Wilma + Bam-Bam + Barney core | Full team activates at Phase 5 |
| QA System | Informal — Barney reviews pipeline, Fred reviews strategy | Formalize at Gate 2 |
| Adaptive QA Ratings | Not yet needed — too few tasks per type | Start tracking at Gate 2 |
| Micro QA Principle | Applied to pipeline changes (Barney reviews) | Expand to all work at Phase 5 |
| Metrics Framework | Pipeline accuracy only | Full AARRR at Gate 1 |
| Legal / IP | Business registration pending | Complete at Gate 0 |
| Financial Model | No revenue yet | Activate at Gate 1 |
| Competitive Moat | School schedule corpus building daily | Continuous |
| Content & SEO | Not started | Activate late Gate 0 / early Gate 1 |
| Community | Not started | Seed at Gate 0 |
| Revenue Ops | Stripe setup documented | Implement at Gate 1 |
| Support Plan | Not needed yet | Implement at Gate 1 |
| Incident Response | Informal (Wilma restarts things) | Formalize at Gate 1 |
| Data Governance | Pipeline data tracked in PROJECT_MAP.md | Formal catalog at Gate 2 |

---

## Communication Rhythm (Current Scale)

| When | What | Who |
|------|------|-----|
| Daily | Pipeline health check + scraper status (heartbeat) | Wilma → #briefing |
| Daily | Competitor watch briefing | Dino → Discord |
| Daily | GitHub Issues dashboard update | render_issue_dashboard.py → #tasks |
| As needed | Pipeline issues, server alerts | Wilma → Fred (DM) |
| Weekly | Progress summary — GitHub Issues closed, what's next, any blockers | Wilma compiles → Fred reviews |
| As needed | Strategy discussions, big picture planning | Fred ↔ Barney / Gazoo |

**Fred's time commitment:** ~30-60 min/day reviewing + making decisions. Bulk work is Bam-Bam (code) and Wilma (ops).

---

## Testing & Quality

**Testing Philosophy:** Agents are expected to write and run tests for all code changes. Quality is built in, not inspected later.

**Process:**
- Agents write tests as part of their work (not after)
- Test coverage issues are filed with `testing` + `sprint-ready` labels
- Bam-Bam is primary owner of testing tasks but all agents write tests
- Gazoo reviews test quality during daily work reviews (9:00 PM)

**Quality Gates:**
- No commits without corresponding tests (except documentation)
- Pipeline changes require methodology review from Barney + tests from Bam-Bam
- All issues must include testing criteria in acceptance requirements

**Test Categories:**
- Unit tests: Core functions and calculations
- Integration tests: Pipeline end-to-end, data flow validation
- Quality tests: Data accuracy, model performance, scraper reliability
- Smoke tests: Website functionality, API endpoints

---

## The "Not Now" List (for TPCR specifically)

Deferred with trigger conditions. Not forgotten — parked.

| Item | Trigger to Activate |
|------|-------------------|
| Mobile app | Weekly mobile traffic > 70% AND MRR > $5K |
| Real-time wait times (live feed) | Legal partnership with parks OR user-contributed data model |
| Itinerary builder | 1,000+ active users requesting it |
| International parks | US parks profitable (MRR > $5K) |
| AI chat interface ("Ask about your trip") | After core product proven, Gate 3+ |
| B2B data licensing | After first 6 months of consumer product |
| Video content (YouTube) | After blog content cadence proven (8+ posts) |

---

## Next Actions (Immediate)

After this document is finalized:

1. **Bam-Bam:** Continue pipeline v4 accuracy work (Pillar 1: smart synthetic weighting)
2. **Wilma:** Monitor scraper completion, maintain pipeline, start Gate 0 task list items (documentation, data catalog, Break Glass doc)
3. **Fred:** Reddit engagement (1 post/week), start thinking about user personas, review this document and adjust
4. **Barney:** QA pipeline v4 methodology changes as they come through
5. **Betty + Pebbles:** On standby until Phase 4 priorities are set

---

## Living Document

This file gets updated as things change. Wilma owns it. Fred reviews quarterly (or more often if things are moving fast).

When TPCR hits Gate 1 (first paid customer), this document gets a major revision to activate the next layer of the framework.

---

*The cathedral is designed. This is the first room. Let's build it well.*
