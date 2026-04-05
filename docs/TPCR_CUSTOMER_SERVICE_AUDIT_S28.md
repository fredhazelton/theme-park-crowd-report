# TPCR Customer Service Audit — Session 28

**Date:** 2026-04-05
**Auditor:** Barney (Session 28)
**Scope:** TPCR customer-facing Discord server — the product layer that 82 members interact with
**Methodology:** Playbook Phase 2 — full channel read, server structure review, bot code survey, customer message analysis
**Status:** Phase 2 complete. Phase 3 (design spec) deferred to next session.

---

## Why This Audit Exists

HazeyData's Audit & Redesign Playbook was applied to three backend systems (org structure, WTI pipeline, SSD pipeline) across Sessions 5-8. The customer-facing Discord server — the actual product — was never audited. This gap was discovered in Session 28 when:

- Barney didn't have access to the customer server until mid-session (added via OAuth2)
- 65 false "Service Restored" messages spammed the customer #announcements channel for 15+ hours with no internal detection
- A customer complained in #feedback before any agent noticed
- Gazoo's audits cover internal infrastructure only — no customer experience checks

The pipeline is the engine room. This server is the showroom floor. We audited the engine but never walked the showroom.

---

## Server Overview

| Property | Value |
|----------|-------|
| Server name | Theme Park Crowd Report |
| Guild ID | 1471374656253591695 |
| Created | 2026-02-12 |
| Members | 82 |
| Channels | 5 text, 0 voice, 1 category |
| Boost tier | 0 (no boosts) |
| Bot | Theme Park Crowd Report (ID: 1471372989806411960) |

### Channel Map

| Channel | ID | Position | Purpose | Activity Level |
|---------|-----|----------|---------|----------------|
| #general | 1478239791010287779 | 0 | Welcome + chat | LOW — last user msg Mar 29 |
| #announcements | 1471935589371609162 | 1 | Product updates | LOW — 4 real announcements in 5 weeks |
| #crowd-reports | 1478240066382860298 | 2 | Daily crowd reports | MEDIUM — daily embeds when working |
| #bot-commands | 1478240248361128079 | 3 | Bot interaction | MEDIUM — sporadic user commands |
| #feedback | 1471935482513457266 | 4 | Feature requests + bugs | LOW — 16 messages total since launch |

---

## Findings by Domain

### 1. Service Status & Health Monitoring — CRITICAL

**Score: 1/10**

The `service_status_manager.py` script was posting autonomously to the customer #announcements channel with no human review, no rate limiting, no debounce, and a fundamental misunderstanding of DuckDB internals (treating WAL files as corruption). This produced 65 identical "Service Restored" messages in 15 hours.

**Evidence:**
- 50+ messages visible in channel read (Apr 4-5)
- Customer complaint from .jeff318 in #feedback: "Can there be a limit on how many alerts for system performance are sent out?"
- Gazoo's audits never flagged this because Gazoo monitors the internal server, not the customer server

**Status:** RESOLVED (S28). Cron disabled, spam deleted, apology posted, customer responded to. Amendment 004 design spec written for rebuild.

**Root cause:** No governance layer between automated systems and customer-facing channels. Any script with the bot token can post anything to any channel at any frequency.

### 2. Bot Command Quality — 7/10 (GOOD with gaps)

The bot's responses are genuinely strong when they work:

**Strengths:**
- `/ask` responses are detailed, personalized, and actionable (e.g., the May 6 Magic Kingdom response with per-ride wait time breakdowns and strategy tips)
- Auto-retry on DuckDB lock failures works well — "Sorry about the earlier hiccup — we fixed the issue and re-ran your question" with the full answer following
- Friendly, accessible tone throughout
- Good error messages for park closures: "park may be closed" with redirect to `/crowd`

**Issues found:**
- "Something went wrong querying the data" — generic error visible to customers (Mar 3, Mar 4, Mar 6). No diagnostic info, no retry suggestion, no context.
- "I don't have forecast data for Magic Kingdom on March 08" — bot couldn't serve same-day forecasts. Appeared twice on Mar 8. Customers trying to plan their current day got nothing.
- Epic Universe not included when user asked about "Universal Orlando Resort parks" — customer had to specifically request it (early March, may be fixed by now given EU dimension work)
- Bot posted what appears to be a test message in #bot-commands: "What are the wait times for Space Mountain tomorrow morning?" — looks like the bot talking to itself (Mar 8)

**Needs deeper investigation (next session):**
- Read `tpcr-discord-bot/bot.py` to understand slash command registration, error handling paths, DuckDB connection management
- Read `tpcr-discord-bot/ask_agent.py` to understand the AI Q&A pipeline
- Test each command from a user perspective and catalog failure modes

### 3. Daily Crowd Reports (#crowd-reports) — 6/10

The channel posts daily crowd report embeds (content is in embeds, not readable via text). Good cadence when working.

**Issue:** 10-day gap from Mar 26 to Apr 5 — no reports posted for that entire period. This likely corresponds to pipeline work during Sessions 22-27, but customers saw a dead channel for over a week with no explanation.

**Positive:** Reports resumed Apr 5 (today's embed posted at 11 AM).

**Needs investigation:** What controls the daily report posting? Is it a cron? Is it in the bot's event loop? What happens when it fails — is there an alert?

### 4. Announcements Channel — 5/10

**Content quality is good** — the 4 real announcements (launch day, v3 upgrade, smarter bot, apology) are well-written, informative, and on-brand.

**Issues:**
- No announcements between Mar 8 and Apr 5 (28 days). The channel went silent for a month.
- During that time, significant product improvements shipped (competition framework, daily recap blog, tweet automation, accuracy improvements) — none were communicated to customers.
- The channel was used as a dumping ground for automated service status messages with no human review gate.

**Recommendation:** Establish a cadence (e.g., biweekly product updates) and a review gate (no automated posting to #announcements without human approval or at minimum a debounce/rate limit).

### 5. Feedback Loop — 4/10

**What's good:** Fred responds personally to feedback. The tone is warm and engaged. Early feedback was enthusiastic ("super cool", "loving the new calendar format", "been watching this come together from the sidelines").

**What's missing:**
- Only 16 messages in 5 weeks across all users — very low engagement for 82 members
- No systematic tracking of feedback items (no tickets filed from feedback)
- The Epic Universe feedback (Mar 3) about it not being included in Universal results is still an open issue 33 days later
- No mechanism to proactively solicit feedback (e.g., polls, feature voting, "what should we build next?")
- No feedback from the last 3 weeks until the spam complaint today

### 6. Server Structure & Onboarding — 5/10

**What exists:** Clean 5-channel layout. #bot-commands has a good topic description listing all available commands. #general has a "Welcome! Start here" topic.

**What's missing:**
- No welcome message or onboarding flow for new members. A new user joins and sees... channels. No explanation of what TPCR is, what the bot does, how to get started.
- No rules/guidelines channel
- No roles (beta tester, premium, etc.) — everyone has the same access
- No server description set (field is null)
- DISBOARD bot is posting promotional embeds in #general (server listing service) — looks spammy in a product server
- Only 1 category — fine for now, but no separation between community and product channels

### 7. Monitoring & Observability (customer perspective) — 2/10

**The fundamental gap:** Nobody on the internal team was monitoring what customers actually see. Barney couldn't access the server. Gazoo audits internal infrastructure. Dino executes tasks on the backend. Fred is the only person who sees the customer server, and he caught the spam only because a customer complained.

**What's needed:**
- Barney's startup protocol should include reading TPCR customer #announcements and #feedback (now possible since S28 OAuth)
- Gazoo should include a "Customer Experience" domain in its audit scoring — at minimum, check for: (a) no spam in #announcements, (b) daily report posted in #crowd-reports, (c) no unanswered feedback older than 48h
- Error messages visible to customers ("Something went wrong") should be logged and counted internally

---

## Summary Scorecard

| Domain | Score | Trend | Critical Finding |
|--------|-------|-------|------------------|
| Service Status | 1/10 | FIXED S28 | 65 spam messages to customers, now disabled |
| Bot Commands | 7/10 | Stable | Strong when working, generic errors when not |
| Daily Reports | 6/10 | Improving | 10-day gap, now resumed |
| Announcements | 5/10 | Stale | 28-day silence, no product updates communicated |
| Feedback Loop | 4/10 | Low engagement | 16 msgs in 5 weeks, no tracking |
| Server Structure | 5/10 | Static | No onboarding, no roles, no welcome flow |
| Monitoring | 2/10 | IMPROVED S28 | Barney now has access, but no systematic checks yet |

**Overall: 4.3/10 — Significant gaps in the customer-facing product layer.**

The backend pipeline scores well (8.4 MAE, 13/13 daily, competition running). But the product wrapper — the thing customers actually touch — has no governance, no monitoring from Tier 2, and no systematic quality process.

---

## Recommended Next Steps (Phase 3: Design Spec)

The audit identifies the problems. The next step per the Playbook is a Customer Service Design Spec — a governing document for the product layer, parallel to `PIPELINE_V4_DESIGN.md` for the engine.

Proposed scope for the design spec:

1. **Communication governance** — what posts to customer channels, under what conditions, with what approval gates
2. **Service status redesign** — Amendment 004 (already drafted)
3. **Bot error handling standards** — no generic "Something went wrong" messages, structured fallbacks
4. **Daily report reliability** — alerting when crowd reports fail to post
5. **Onboarding flow** — welcome message, getting-started guide, role assignment
6. **Feedback tracking** — systematic capture of customer requests into GitHub issues
7. **Barney monitoring protocol** — add TPCR customer channels to session startup
8. **Gazoo customer domain** — add Customer Experience to audit scope
9. **Announcement cadence** — regular product updates, not just silence + spam

This should be Phase 3 work in the next session, with Fred review in Phase 4.

---

## Channels Reference (for SESSION_LOG)

| Channel | Server | ID | Barney Access |
|---------|--------|----|---------------|
| #general | TPCR customer | 1478239791010287779 | ✅ S28 |
| #announcements | TPCR customer | 1471935589371609162 | ✅ S28 |
| #crowd-reports | TPCR customer | 1478240066382860298 | ✅ S28 |
| #bot-commands | TPCR customer | 1478240248361128079 | ✅ S28 |
| #feedback | TPCR customer | 1471935482513457266 | ✅ S28 |

---

*Barney — Chief of Pipeline, Slate Rock & Gravel Co. 🪨*