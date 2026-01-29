# MEMORY.md - Wilma's Long-Term Memory

*Last updated: 2026-01-28*

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

## Active Projects

1. **Stream Overlay** (`/home/wilma/stream-overlay/`)
   - Built HTML/CSS/JS overlay for Twitch/YouTube
   - Animated borders, slide-ins, glows
   - Control panel for toggling elements
   - Ready for Mac Mini + Streamlabs

2. **Pipeline Linux Support**
   - Bash scripts for ETL, dimensions, queue-times
   - Cron installer, systemd service
   - Pushed to repo

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
