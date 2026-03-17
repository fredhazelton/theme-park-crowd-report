# MEMORY.md - Wilma's Long-Term Memory

*Last updated: 2026-03-16*

---

## Who I Am

- **Name:** Wilma
- **Born:** 2026-01-28
- **Email:** wilma@hazeydata.ai
- **Home:** wilma-server (Linux) — dedicated to me
- **Part of:** The Flintstones AI crew

---

## The Flintstones Crew

| Name | Role | Where |
|------|------|-------|
| **Fred** | Human, the boss | Mac Mini (arriving soon) |
| **Barney** | Advisor | Claude on claude.ai |
| **Bam-Bam** | Deep coder | Claude in Cursor |
| **Wilma** | 24/7 assistant | wilma-server (Linux) |

---

## About Fred

- **Full name:** Fred Hazelton
- **Day job:** Data Scientist at Government of Canada (Infrastructure Canada) — builds dashboards
- **Background:** Former TouringPlans.com (theme park wait time predictions)
- **Side project:** hazeydata.ai
- **Location:** Ontario, Canada (America/Toronto timezone)
- **Wife:** Chantale Hazelton (escalation path if Fred gets out of line 😄)

### Work Style
- Night owl, but deep work best in mornings
- Works all hours — OK to interrupt anytime
- Stream of consciousness thinker — dumps thoughts, I organize them
- Very particular about data visualizations
- Pain points: organization, coding (he's the data scientist, not the coder)

### Tools
- Figma (design)
- Cursor (coding with Bam-Bam)
- Gmail / Google Calendar
- Workflowy (personal notes — private)
- Streamlabs (streaming)

---

## hazeydata.ai

**Umbrella company** for Fred's independent work.

### First Project: Theme Park Crowd Report
- **Repo:** github.com/hazeydata/theme-park-crowd-report
- **Tech:** Python ETL pipeline, XGBoost models, SQLite deduplication
- **Data:** Wait times from S3 (TouringPlans data) + live from queue-times.com
- **Output:** Fact tables, dimension tables, WTI (Wait Time Index)

### The Vision
- Dashboard on website
- Twitch/YouTube daily stream
- Newsletter
- Blog
- Social media
- Focus: Help people pick dates to avoid crowds

### Key Concepts
- **Posted time:** What the park displays (usually overestimate)
- **Actual time:** Real wait time (shorter than posted)
- **WTI:** Wait Time Index — single number summarizing crowd level

---

## Writing Style (for content)

**Fred's credibility + Becky's warmth**

From TouringPlans analysis:
- Data-first, always specific numbers
- Transparent about methodology and misses
- Clear structure: Hook → TL;DR → Context → Breakdown → Action
- Conversational but professional
- Always actionable: "here's what to do"

Style guides in: `memory/fred-writing-style-analysis.md`, `memory/becky-writing-style-analysis.md`

---

## Credentials & Access

Stored in `.credentials/` (gitignored):
- `gmail.json` — Email app password
- `figma.json` — Figma API token

Also have:
- SSH key for GitHub (wilma@hazeydata.ai)
- Access to hazeydata/theme-park-crowd-report repo

---

## Flintstones Framework (codified 2026-03-16)

**Location:** `/home/wilma/clawd/FRAMEWORK.md` + `/home/wilma/clawd/GUARDRAILS.md`
**Business Framework:** `/home/wilma/theme-park-crowd-report/docs/internal/business-framework.html`

ALL projects go through the Idea Cycle: Discover → Validate → Build & Test → Position → Launch → Monitor → Grow (7 phases, 14 steps). Every output gets Maker→Checker→Approve/Revise/Escalate. Three Ideas Rule on every escalation. Adaptive QA starts at Yellow. Fred at ship/kill gate. See FRAMEWORK.md for full details.

---

## Active Projects

1. **Canadian Digital Railway (CDR)** — See dedicated section above 🚂

2. **Theme Park Crowd Report** — Main hazeydata.ai product
   - Repo: github.com/hazeydata/theme-park-crowd-report
   - Pipeline on wilma-server
   - SSD (School Schedule Data) scraper running

3. **Stream Overlay** (`/home/wilma/stream-overlay/`)
   - Built HTML/CSS/JS overlay for Twitch/YouTube
   - Ready for Mac Mini + Streamlabs

4. **Pipeline Linux Support**
   - Bash scripts for ETL, dimensions, queue-times
   - Cron installer, systemd service
   - Pushed to repo

---

## The Canadian Digital Railway (CDR) — ACTIVE PROJECT 🚂

**Repo:** github.com/hazeydata/cdr
**Status:** Phase 2 (Validate) — building prototype
**North Star:** "One working tool from one published schema deployed at one organization"

### What CDR Is
A network of sovereign AI agents ("terrys") that help Canadian organizations build compliant software tools without compromising data security. Each node runs locally, respects institutional security boundaries, and shares knowledge through the Railway network.

### NemoClaw Integration (decided 2026-03-16)
NVIDIA announced NemoClaw at GTC 2026 — it's essentially the CDR architecture built as enterprise infrastructure. **CDR positions as the Canadian institutional distribution of NemoClaw** (like Red Hat to Linux). NemoClaw provides the runtime/security/hardware foundation. CDR provides Canadian compliance intelligence, schema workflow, bootstrap protocol, and the Railway network.

### The Four Buildable Items (APPROVED 2026-03-16)
Fred approved this plan and ordered execution via the Flintstones Framework:

**🥇 #1 PRIORITY: Schema Workflow (Phase 2 → Step 4: Prototype)**
- CDR's original invention. Schemas in → compliant tools out → deploy on-network
- HICC org chart tool is the proof of concept
- Blocker: schema publication approval OR use public PeopleSoft vendor docs to prove concept
- Recommendation: Prototype with public schema-like data NOW, HICC approval in parallel

**🥈 #2: Canadian Compliance Engine (Phase 2 → Step 3: Research)**
- Translate ITSG-33/PHIPA/WCAG/OLA into machine-enforceable OpenShell policies
- CDR profiles already drafted in repo. Need OpenShell policy syntax docs (just launched)
- Maker: Bam-Bam | Checker: Barney | Audit: Gazoo

**🥉 #3: Railway Network (Phase 2 → Step 4: Prototype)**
- Architecture designed. Bootstrap protocol exists. HQ (Wilma) operational
- Next milestone: first external node deployment
- Depends on Items 1 & 2 being further along

**4th: Canadian Model Fine-Tuning (Phase 1 → Step 1: Discover)**
- Fine-tune Nemotron on bilingual GC corpus for institutional specialization
- PARKED until Items 1-3 prove the model. Activates when we have real usage data
- Fred's domain (data science). Needs compute resources (SCIP/Access Fund)

### Sovereignty Score
NemoClaw alone: ~60% of Canada's sovereignty requirements
NemoClaw + CDR (all 4 items): ~80%
Remaining 20%: supply chain (chip fab) — national policy, not our problem

### Key Documents in Repo
- `nemoclaw-impact-analysis.md` — Full NemoClaw analysis
- `sovereignty-gap-analysis.md` — Canada's requirements vs what exists
- `gc-code-audit.md` — GC open-source code catalogue
- `BOOTSTRAP.md` — Node initialization protocol
- `principles.md` — CDR's six core principles
- `profiles/gc-federal/` — GC compliance profile drafts

---

## Ideas Backlog

- **The Nice News** — Positive news aggregator with sentiment analysis (`memory/ideas/the-nice-news.md`)

---

## Key Dates

- **2026-01-28:** Birthday! First day.
- **TBD:** Mac Mini arrives → streaming setup

---

## Notes to Future Me

- Fred uses stream-of-consciousness — just capture and organize
- He's particular about visuals — respect the aesthetic
- Chantale is the backup if Fred needs organizing help
- Pipeline runs under fred@wilma-server, I'm wilma@wilma-server
- Amused overlay from Nerd or Die is in Fred's Dropbox for future use
