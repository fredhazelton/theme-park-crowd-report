# The Quarry — Analytics Dashboard Architecture

> **Status:** Accepted  
> **Date:** 2026-03-10  
> **Decision Makers:** Fred, Barney  
> **Pending Input:** Wilma (pipeline export status)

---

## Context

Mission Control v3 was built as an all-in-one operational dashboard: pipeline status, tasks, calendar, team activity, ideas, finance, analytics, Discord overview, social media, and memory — all in a single GitHub Pages app fed by static JSON files.

It worked well for about 5 minutes. Then Discord became the operational hub. The Flintstones crew (Wilma, Dino, Arnold, Gazoo, Pebbles, Betty, Mr. Slate) all live in Discord via OpenClaw. Tasks, schedules, team coordination, status updates — everything operational moved there naturally. MC v3 went stale because it was a secondary copy of data that was better served by Discord in real time.

## Decision

**Split visualization into three layers based on audience and purpose.**

### Layer 1: Discord (Operational Layer — Primary)

**What lives here:** Everything operational — pipeline status, task management, team coordination, schedules, ideas, morning briefings, alerts, agent activity.

**Why:** Discord is already the source of truth. The bots are there, the humans are there, and the data is generated in-context. Trying to mirror this to a web dashboard creates a maintenance burden with zero benefit.

**Enhancements to lean into:**
- Richer embeds in #pipeline and #morning-briefing with key accuracy numbers
- Wilma-generated chart images (matplotlib/plotly PNGs) attached to embeds for visual summaries
- Edit-in-place pinned messages in #mission-control for persistent status (instead of posting new messages that scroll away)
- Threads for drill-down detail, keeping channels clean

### Layer 2: The Quarry (Analytics Layer — Internal)

**What lives here:** Interactive data visualization for wait time analytics, model accuracy exploration, and prediction quality assessment.

**Why:** This is the one thing Discord genuinely can't do well. Exploring which entities are underperforming, visualizing predicted vs actual wait time curves, comparing accuracy across parks and date ranges, drilling into the entity scoreboard — this is spatial, interactive, analytical work that needs a real web UI.

**Scope (what stays):**
- Accuracy overview (MAE, Bias, RMSE big numbers)
- Daily accuracy trend chart (last 30+ days)
- Entity Explorer (pick entity + date → see predicted vs actual curves)
- Entity Scoreboard (sortable, searchable accuracy rankings)
- Park-level accuracy comparisons
- Any future analytical views (model competition results, synthetic data quality metrics, etc.)

**Scope (what gets removed from MC v3):**
- ❌ Pipeline status → lives in Discord #pipeline
- ❌ Tasks/Kanban → lives in Discord #dino
- ❌ Calendar → lives in Discord #calendar / Wilma's scheduling
- ❌ Discord overview → you're already in Discord
- ❌ Social media → lives in Discord social channels
- ❌ Ideas → lives in Discord #ideas forum
- ❌ Finance → lives in Discord #business / Mr. Slate
- ❌ Memory → lives in Discord / Wilma's memory system
- ❌ Today's Focus → lives in Discord #morning-briefing
- ❌ Infrastructure → lives in Discord #pipeline / #alerts

**Freshness strategy:** The Quarry reads from `docs/analytics-data/*.json` files that are auto-exported by the daily pipeline cron as a post-processing step. No manual updates, no separate maintenance process. Pipeline runs → forecasts generated → accuracy evaluated → JSONs exported → git push → dashboard is current.

**Tech stack:** Keep it simple — static HTML/CSS/JS on GitHub Pages with Chart.js. No build step, no framework, no server. The pipeline handles data; the dashboard just renders it.

### Layer 3: Public/Twitch Dashboard (Showcase Layer — Future)

**What lives here:** A polished, public-facing visualization of HazeyData's predictions for the Twitch stream, website embeds, and marketing.

**Why:** Different audience (potential customers, stream viewers), different needs (impressive visuals, simplified interface, branding), different data scope (today's predictions, live vs predicted, "how accurate are we" proof points).

**Relationship to The Quarry:** Can share the same `analytics-data/` JSON pipeline. The data source is identical — only the presentation layer differs. The Quarry is internal/analytical; the public dashboard is external/showcase.

**Status:** Early exploration. Stream overlay work has started. Full spec TBD.

---

## Data Pipeline Requirements

For The Quarry to work without going stale, the daily pipeline must export these files to `docs/analytics-data/` and push to GitHub:

| File | Contents | Update Frequency |
|------|----------|-----------------|
| `accuracy_summary.json` | Overall MAE, Bias, RMSE, entity count, days evaluated | Daily |
| `daily_accuracy.json` | Per-day accuracy metrics for trend chart | Daily |
| `entity_scores.json` | Per-entity accuracy rankings for scoreboard | Daily |
| `entity_list.json` | All entities with park grouping for dropdowns | Daily (or on entity change) |
| `entity_dates_index.json` | Maps entity_code → available dates for explorer | Daily |
| `entity_curves/{entity_code}/{date}.json` | Predicted vs actual wait time curves | Daily (new dates appended) |

> **⚠️ Action Item:** Confirm with Wilma which of these already exist in the pipeline vs need to be built. Message sent to #barney-wilma-dev.

---

## Migration Plan

1. **Confirm data exports** — Wilma reports on current state of analytics JSON generation
2. **Build/wire missing exports** — Ensure all JSONs above are produced by the pipeline cron
3. **Fork MC v3 → The Quarry** — Strip out all non-analytics tabs, rename, update branding
4. **Enhance Discord operational posts** — Richer embeds, chart image attachments, edit-in-place pins
5. **Sunset MC v3** — Redirect or archive once The Quarry is live
6. **Layer 3 planning** — Spec out the public/Twitch dashboard separately

---

## Naming

**The Quarry** 🪨⛏️ — Where you mine insights from the data. Stays in the Flintstones universe. Reflects the analytical/exploratory nature of the tool.

Other candidates considered: HazeyData Analytics (too generic), The Observatory (fun but no Flintstones tie-in), Crystal Ball (predictions angle but same issue), Slate Board (decent but The Quarry won).

---

## Key Principles

1. **Discord is the operational source of truth.** Don't duplicate it.
2. **The Quarry only shows data the pipeline produces automatically.** If a human has to update it, it will go stale.
3. **Visualization serves analysis.** If you can't interact with it (filter, sort, drill down), it probably belongs as a Discord embed instead.
4. **Keep the stack simple.** Static files, no server, no build step. The pipeline is the only moving part.
5. **Layer 3 shares data, not code.** The public dashboard can look completely different but reads the same JSONs.
