# 🌤️ Weather-Design Project — Formal Project Plan

> **Sub-project of:** Theme Park Crowd Report (TPCR)
> **Framework stage:** Phase 3 → 4 transition (Build & Test → Position)
> **Gate advancement:** Directly advances **Gate 0 → Gate 1** criterion #3: "Website shows crowd predictions for 4+ parks with usable interface"
> **Created:** 2026-03-18
> **Owner:** Wilma (Orchestration) · Fred (Vision/Approval)

---

## Project Definition

**What:** Build the production crowd report web interface using the Apple Weather design paradigm — translating weather forecast UX patterns into theme park crowd data cards.

**Why:** This is the customer-facing product. Everything else (pipeline, scraper, ACCORD engine) is infrastructure. This is what users see, touch, and pay for. Without this, there's no Gate 1.

**Origin:** March 17-18, 2026 power sprint. Fred and Wilma designed the complete spec in a single session, documented in:
- `docs/DESIGN_SPEC.md` — Authoritative specification
- `docs/TPCR_SPRINT_2026-03-18.md` — Sprint transcript and decision log
- `prototypes/complete_crowd_report.html` — Working prototype (above + below fold)
- `prototypes/below_fold_with_rides.html` — Initial below-fold prototype

**North Star:** "Does it feel like checking the weather for your theme park trip?"

---

## RICE Score

| Factor | Value | Rationale |
|--------|-------|-----------|
| **R**each | 5,000 | Every user sees this — it IS the product |
| **I**mpact | 3 (massive) | Without it, no product. Core value prop. |
| **C**onfidence | 90% | Spec locked, prototype proven, data pipeline exists |
| **E**ffort | 6 weeks | Multi-component, needs real data integration |
| **RICE Score** | **(5000 × 3 × 0.90) ÷ 6 = 2,250** | 🔴 Highest priority |

---

## Deliverables & Task Breakdown

### Epic 1: Above-the-Fold (WTI Card) 🎯
*The hero card. First thing users see. Must be flawless.*

| # | Task | Maker | Checker | Autonomy | Status |
|---|------|-------|---------|----------|--------|
| 1.1 | **WTI card HTML/CSS** — responsive, mobile-first (390px), glassmorphism, Benedictus spectrum | Bam-Bam | Pebbles (design QA) | Level 2 | 🟡 Prototype exists |
| 1.2 | **Hour-by-hour bar** — 5-min resolution Benedictus gradient from pipeline data | Bam-Bam | Barney (data accuracy QA) | Level 2 | ⬜ Not started |
| 1.3 | **Forecast card** — 7-day rows with global historical range bars (Apple Weather style) | Bam-Bam | Barney (methodology QA) | Level 2 | 🟡 Prototype exists |
| 1.4 | **State logic** — Park open/closed/early entry/evening event states per DESIGN_SPEC | Bam-Bam | Barney (logic QA) | Level 2 | ⬜ Not started |
| 1.5 | **NOW indicators** — Triangle + dot, time-aware, positioned correctly | Bam-Bam | Pebbles (visual QA) | Level 1 | ⬜ Not started |
| 1.6 | **Data JSON generator** — Python script querying pipeline parquet → JSON per park | Bam-Bam | Barney (data QA) | Level 2 | ⬜ Not started |
| 1.7 | **Multi-park support** — 4+ parks (MK, EPCOT, HS, AK minimum) | Bam-Bam | Wilma (integration QA) | Level 2 | ⬜ Not started |
| 1.8 | **Design review** — Fred approves final above-fold visual | Pebbles (presents) | Fred (approves) | Level 4 | ⬜ Blocked by 1.1-1.7 |

### Epic 2: Below-the-Fold Core Sections 📊
*Creative metrics that complement the objective WTI data.*

| # | Task | Maker | Checker | Autonomy | Status |
|---|------|-------|---------|----------|--------|
| 2.1 | **Crowd Density card** — 1-10 scale, Benedictus bar, expert baseline display | Bam-Bam | Pebbles (design) + Barney (stats) | Level 2 | 🟡 Prototype exists |
| 2.2 | **Crowd Density backend** — Bayesian prior from expert calibration, user submission endpoint | Bam-Bam | Barney (statistical methodology QA) | Level 3 | ⬜ Not started |
| 2.3 | **Statistical safeguards** — Trimmed mean, recency weighting, reputation weighting, anomaly detection | Bam-Bam | Barney (methodology QA) | Level 3 | ⬜ Not started |
| 2.4 | **Today's Events timeline** — badges (Ended/Tonight), data from park hours | Bam-Bam | Pebbles (design QA) | Level 1 | 🟡 Prototype exists |
| 2.5 | **Ride Snapshot card** — Top 5 shortest + longest waits, Benedictus dots | Bam-Bam | Barney (data QA) | Level 2 | ⬜ Not started |
| 2.6 | **Crowd Heatmap** — Hour × Day grid, Benedictus cells | Bam-Bam | Pebbles (design QA) | Level 2 | ⬜ Not started |
| 2.7 | **Crowd Trend card** — Direction indicator (↑↓→), 30-60 min rate of change | Bam-Bam | Barney (methodology QA) | Level 2 | ⬜ Not started |
| 2.8 | **Other Parks Today** — Compact row with WTI + Benedictus dots | Bam-Bam | Wilma (integration QA) | Level 1 | ⬜ Not started |
| 2.9 | **Design review** — Fred approves below-fold layout and content | Pebbles (presents) | Fred (approves) | Level 4 | ⬜ Blocked by 2.1-2.8 |

### Epic 3: Merlin / My Must-Dos 🧠
*The killer feature. Live in-park ride recommendation engine.*

| # | Task | Maker | Checker | Autonomy | Status |
|---|------|-------|---------|----------|--------|
| 3.1 | **Gain function implementation** — `gain(ride) = expected_future_wait - current_wait` | Bam-Bam | Barney (algorithm QA) | Level 3 | ⬜ Not started |
| 3.2 | **Weighted average calculator** — Dynamic window, near-term favored, self-calibrating | Bam-Bam | Barney (methodology QA) | Level 3 | ⬜ Not started |
| 3.3 | **Ride selector UI** — Pick up to 4 rides, tags with × remove, + Add | Bam-Bam | Pebbles (design QA) | Level 2 | 🟡 Prototype exists |
| 3.4 | **Brain visualization** — 🧠 click → wait curves animate → recommendation appears | Bam-Bam | Pebbles (animation/UX QA) | Level 2 | 🟡 Prototype exists |
| 3.5 | **Wait curve chart** — 4-ride mini chart with Benedictus colors, weighted window | Bam-Bam | Barney (data accuracy) + Pebbles (visual QA) | Level 2 | 🟡 Prototype exists |
| 3.6 | **Done button + recalculation loop** — Complete ride → drop → recalculate → next | Bam-Bam | Barney (algorithm QA) | Level 2 | ⬜ Not started |
| 3.7 | **Edge cases** — All negative gains, last ride, ride goes down, park closing soon | Bam-Bam | Barney (logic QA) | Level 3 | ⬜ Not started |
| 3.8 | **Info modal** — ℹ️ button explaining the algorithm (educational transparency) | Bam-Bam | Pebbles (copy QA) | Level 1 | 🟡 Prototype exists |
| 3.9 | **Integration with live data** — Real wait times + forecasts feeding the engine | Bam-Bam | Barney (data pipeline QA) | Level 3 | ⬜ Not started |
| 3.10 | **Algorithm review** — Fred + Barney validate methodology before production | Barney (presents analysis) | Fred (approves) | Level 4 | ⬜ Blocked by 3.1-3.7 |

### Epic 4: Infrastructure & Integration 🔧

| # | Task | Maker | Checker | Autonomy | Status |
|---|------|-------|---------|----------|--------|
| 4.1 | **Weather API integration** — Real weather at park coordinates | Bam-Bam | Wilma (ops QA) | Level 2 | ⬜ Not started |
| 4.2 | **Park hours data feed** — Open/close, EMH, party nights from pipeline | Bam-Bam | Barney (data QA) | Level 1 | ⬜ Not started |
| 4.3 | **Responsive design pass** — Desktop, tablet, mobile breakpoints | Bam-Bam | Pebbles (design QA) | Level 2 | ⬜ Not started |
| 4.4 | **Static hosting setup** — Deploy to hazeydata.ai | Wilma | Bam-Bam (tech QA) | Level 2 | ⬜ Not started |
| 4.5 | **Screenshot/social sharing** — Puppeteer headless for Discord/social cards | Bam-Bam | Wilma (ops QA) | Level 1 | ⬜ Partial (exists for forecast images) |
| 4.6 | **Performance optimization** — Load time < 2s, no layout shift | Bam-Bam | Wilma (monitoring QA) | Level 2 | ⬜ Not started |
| 4.7 | **Multi-park routing** — URL structure: `/park/magic-kingdom`, `/park/epcot`, etc. | Bam-Bam | Wilma (ops QA) | Level 1 | ⬜ Not started |

### Epic 5: Content & Launch Prep 📝
*Activates as Epics 1-4 near completion.*

| # | Task | Maker | Checker | Autonomy | Status |
|---|------|-------|---------|----------|--------|
| 5.1 | **Landing page copy** — What is this, why trust it, CTA | Betty | Pebbles (design) + Wilma (approval) | Level 3 | ⬜ Not started |
| 5.2 | **"How it works" explainer** — Simple, non-technical, builds trust | Betty | Barney (accuracy QA) | Level 2 | ⬜ Not started |
| 5.3 | **Privacy policy & ToS** — Required before any user access | Wilma (drafts/templates) | Fred (legal review) | Level 4 | ⬜ Not started |
| 5.4 | **Beta user recruitment** — Reddit, Discord, existing contacts | Fred (leads) | Wilma (tracks) | Level 4 | ⬜ Not started |
| 5.5 | **Feedback mechanism** — In-app, Discord, or email | Bam-Bam | Wilma (ops QA) | Level 2 | ⬜ Not started |

---

## QA Assignments Summary

Per the Flintstones Framework: **Maker builds, Checker verifies. Domain-matched QA.**

| QA Domain | Primary Checker | What They Verify |
|-----------|----------------|------------------|
| **Data accuracy** | Barney | Pipeline data correct, WTI values match, no stale data |
| **Statistical methodology** | Barney | Gain function, Bayesian priors, weighted averages mathematically sound |
| **Algorithm logic** | Barney | Edge cases handled, no degenerate outputs, recommendations sensible |
| **Visual design** | Pebbles | Benedictus colors correct, glassmorphism consistent, responsive, pixel-perfect |
| **UX/interaction** | Pebbles | Flows feel natural, animations smooth, mobile-friendly |
| **Integration/ops** | Wilma | Data feeds connected, hosting works, monitoring in place, no silent failures |
| **Copy/content** | Pebbles + Wilma | Clear, concise, brand-consistent, no jargon |
| **Go/no-go gates** | Fred | Strategic alignment, final visual approval, launch readiness |

**Adaptive QA Rating:** Starting at 🟡 Yellow (new project, every deliverable gets QA). Will adjust to 🟢 Green (spot-check) as confidence builds per domain.

---

## Decision Rights (Project-Specific)

| Decision | Who Decides | Who Helps | Autonomy Level |
|----------|------------|-----------|----------------|
| Algorithm methodology (gain function, weighting) | Barney approves, Fred confirms | Bam-Bam implements | Level 3 |
| Visual design choices (within Benedictus system) | Pebbles proposes | Bam-Bam implements, Fred final approval | Level 2-3 |
| Data source selection | Barney recommends | Bam-Bam implements, Wilma monitors | Level 2 |
| Feature scope changes | Fred decides | Wilma + Barney consult | Level 4 |
| Launch timing | Fred decides | Wilma recommends | Level 4 |
| Bug fixes / minor adjustments | Bam-Bam just does it | Wilma informed | Level 1 |
| New below-fold sections | Fred approves concept | Pebbles designs, Bam-Bam builds | Level 3 |

---

## Execution Plan

### Sprint 1: Foundation (Week 1-2)
**Goal:** Above-the-fold card with real data for Magic Kingdom

| Priority | Tasks | Dependencies |
|----------|-------|-------------|
| 🔴 P0 | 1.6 Data JSON generator | Pipeline data available ✅ |
| 🔴 P0 | 1.1 WTI card HTML/CSS (production quality) | Prototype exists ✅ |
| 🔴 P0 | 1.2 Hour-by-hour bar | 1.6 |
| 🟡 P1 | 1.3 Forecast card with real data | 1.6 |
| 🟡 P1 | 1.4 State logic | 1.1, 1.6 |
| 🟡 P1 | 1.5 NOW indicators | 1.4 |
| 🟢 P2 | 1.8 Design review with Fred | 1.1-1.7 |

**Sprint 1 Exit Criteria:** Magic Kingdom crowd card renders with real pipeline data, state logic works, Fred approves visual.

### Sprint 2: Below the Fold (Week 2-3)
**Goal:** Core below-fold sections with real or realistic data

| Priority | Tasks | Dependencies |
|----------|-------|-------------|
| 🔴 P0 | 2.1 Crowd Density card | Sprint 1 complete |
| 🔴 P0 | 2.4 Today's Events timeline | Park hours data (4.2) |
| 🟡 P1 | 2.5 Ride Snapshot | Live wait data |
| 🟡 P1 | 2.7 Crowd Trend | Live wait data |
| 🟡 P1 | 2.8 Other Parks Today | Multi-park data (1.7) |
| 🟢 P2 | 2.6 Crowd Heatmap | Historical data aggregation |
| 🟢 P2 | 2.9 Design review | 2.1-2.8 |

**Sprint 2 Exit Criteria:** Full page scrolls from WTI card through all below-fold sections. Fred approves layout.

### Sprint 3: Merlin (Week 3-4)
**Goal:** Working ride recommendation engine with real forecasts

| Priority | Tasks | Dependencies |
|----------|-------|-------------|
| 🔴 P0 | 3.1 Gain function | Wait time forecasts available |
| 🔴 P0 | 3.2 Weighted average calculator | 3.1 |
| 🔴 P0 | 3.3 Ride selector UI | Prototype exists ✅ |
| 🟡 P1 | 3.4 Brain visualization | 3.3 |
| 🟡 P1 | 3.5 Wait curve chart | 3.2 |
| 🟡 P1 | 3.6 Done + recalculation loop | 3.1, 3.3 |
| 🔴 P0 | 3.7 Edge cases | 3.1, 3.6 |
| 🟢 P2 | 3.10 Algorithm review | 3.1-3.7 |

**Sprint 3 Exit Criteria:** Merlin produces sensible recommendations from real forecast data. Barney validates algorithm. Fred approves UX.

### Sprint 4: Polish & Multi-Park (Week 4-5)
**Goal:** Production quality across 4+ parks

| Priority | Tasks | Dependencies |
|----------|-------|-------------|
| 🔴 P0 | 1.7 Multi-park support | Sprint 1-3 complete |
| 🔴 P0 | 4.3 Responsive design | Full page built |
| 🟡 P1 | 4.6 Performance optimization | Full page built |
| 🟡 P1 | 4.7 Multi-park routing | 1.7 |
| 🟡 P1 | 4.1 Weather API | Nice-to-have for launch |
| 🟢 P2 | 4.5 Screenshot/sharing | After visual finalization |

**Sprint 4 Exit Criteria:** 4 WDW parks working, responsive, fast, routable.

### Sprint 5: Launch Prep (Week 5-6)
**Goal:** Ready for beta users

| Priority | Tasks | Dependencies |
|----------|-------|-------------|
| 🔴 P0 | 4.4 Deploy to hazeydata.ai | Sprint 4 complete |
| 🔴 P0 | 5.3 Privacy policy & ToS | Legal templates |
| 🟡 P1 | 5.1 Landing page copy | Sprint 4 complete |
| 🟡 P1 | 5.5 Feedback mechanism | Deploy ready |
| 🟢 P2 | 5.4 Beta recruitment | Everything else done |

**Sprint 5 Exit Criteria:** Live on hazeydata.ai, legal docs in place, feedback channel open, ready for first users. **This is Gate 1 territory.**

---

## Risk Register (Project-Specific)

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| Pipeline data gaps (parks without good forecasts) | 🔴 High | Medium | Start with MK (richest data), expand as confidence grows |
| Merlin recommendations feel wrong to users | 🔴 High | Medium | Barney validates algorithm exhaustively, Fred gut-checks with domain experience |
| Design scope creep (too many below-fold sections) | 🟡 Medium | High | Lock v1 scope: WTI + Density + Events + Merlin + Snapshot. Everything else is v2 |
| Weather API costs/reliability | 🟢 Low | Low | Weather is nice-to-have, not blocking. Defer if problematic |
| Mobile performance on data-heavy pages | 🟡 Medium | Medium | Lazy-load below-fold, optimize JSON payloads |
| Crowdsourced density gaming | 🟡 Medium | Low | Statistical safeguards (2.3) handle this. Start with expert-only baseline |

---

## Success Metrics

| Metric | Target | How We Measure |
|--------|--------|---------------|
| Page load time | < 2 seconds | Lighthouse / real user monitoring |
| Mobile usability | Lighthouse score > 90 | Lighthouse audit |
| Data freshness | < 15 minutes stale | Monitoring (Wilma) |
| User comprehension | Users understand WTI without explanation | Beta feedback |
| Merlin accuracy | Recommendations match manual optimization 80%+ | Barney backtesting |
| Parks supported at launch | 4+ (all WDW) | Feature flag |

---

## Communication Rhythm (Project-Specific)

| When | What | Channel |
|------|------|---------|
| Daily | Progress update on active sprint tasks | #fred-wilma |
| Per task | Maker notifies checker when deliverable ready for QA | DM or relevant channel |
| Per sprint | Sprint review with Fred — demo + decide | #fred-wilma |
| Blockers | Immediate escalation | #fred-wilma → Fred DM if urgent |
| Design reviews | Screenshots/prototypes for Fred approval | #fred-wilma or #content-review |

---

## References

| Document | Location | Purpose |
|----------|----------|---------|
| Design Spec | `docs/DESIGN_SPEC.md` | Authoritative specification (element naming, data methodology, state rules) |
| Sprint Transcript | `docs/TPCR_SPRINT_2026-03-18.md` | Decision log and rationale |
| Complete Prototype | `prototypes/complete_crowd_report.html` | Working visual reference |
| TPCR Framework | `TPCR-FRAMEWORK.md` | Parent project operating plan |
| Business Framework | `docs/internal/business-framework.html` | Enterprise framework (stage gates, RACI, etc.) |
| Flintstones Framework | `docs/internal/framework.html` | Org structure, QA system, idea cycle |

---

*This project is the bridge from "we have a pipeline" to "we have a product." Everything the framework was built for leads here.*
