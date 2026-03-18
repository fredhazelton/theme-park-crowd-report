# SSD-FRAMEWORK.md — School Schedules Database Operating Plan
> **The Flintstones Framework applied to SSD.**
> 
> Pipeline steps, sprint priorities, team assignments, and gate criteria —
> all mapped to the Idea Cycle from `FRAMEWORK.md`.
> 
> Last updated: 2026-03-18

---

## Where SSD Sits Today

| Phase | Status | Notes |
|-------|--------|-------|
| ✅ Phase 1 — Discover | **Done** | Fred spotted this at TouringPlans — school calendars are the #1 crowd predictor. No one sells comprehensive day-level data. |
| ✅ Phase 2 — Validate | **Done** | Pipeline v3 built, star schema designed, 8,150 districts collected, Barney's twin collection proves gold-standard extraction works. |
| 🔄 Phase 3 — Build & Test | **Active** | 60.7% district coverage, 51.8% enrollment coverage. Pipeline works — now executing to hit 95%. |
| ⬜ Phase 4 — Position | **Partially done** | One-pager exists, sales strategy drafted, competitive analysis done. Pricing not finalized. |
| ⬜ Phase 5 — Launch | **Not started** | Landing page at hazeydata.ai/school-schedules is placeholder only. |
| ⬜ Phase 6 — Monitor | **Not started** | No customers yet. |
| ⬜ Phase 7 — Grow | **Future** | Multi-year data, predictive models, expanded coverage. |

**Current Stage Gate: Gate 0 (Pre-Revenue) — Build & Test**

**North Star Metric:** Enrollment coverage % at high confidence — must hit mid-90s for product viability.

---

## The Team (Current Reality)

| Who | Role on SSD | Actual Capacity | Current Focus |
|-----|-------------|-----------------|---------------|
| 👑 Fred | Vision, strategy, quality standards | Evenings + weekends | Project plan review, strategic direction, quality bar |
| 🦴 Wilma | Pipeline ops, orchestration, ingestion | 24/7 (always on) | Automated extraction, GitHub Issue management, DB ingestion, QA |
| 🪨 Barney | Gold-standard extraction, twin QA | Session-based (Claude) | Top-200 district extractions via GitHub Issues — 29 done, 83 queued |
| 🏏 Bam-Bam | Pipeline code, schema, tooling | Session-based (Cursor) | Pipeline v3 code, schema v3.1, extraction scripts |
| 🦕 Dino | Status reporting | Cron-based | SSD dashboard refresh, coverage metrics |
| 👽 Gazoo | Quality audit | Periodic | Data quality validation, methodology review |

**Honest assessment:** Wilma (pipeline) + Barney (extraction) are the active core. Bam-Bam builds tooling as needed. Fred sets direction and quality bar.

---

## Pipeline Steps → Framework Phases

The 9 pipeline steps from `SSD_PROJECT_PLAN.md` map to the Idea Cycle:

| Pipeline Step | Framework Phase | Owner | QA By |
|---------------|----------------|-------|-------|
| **Step 0:** Universe Definition | Phase 2 (Validate) | Wilma | Bam-Bam verifies CCD data |
| **Step 1:** URL Discovery & Classification | Phase 3 (Build) | Wilma | Barney spot-checks URL quality |
| **Step 2:** Collection (automated + manual) | Phase 3 (Build) | Wilma + Barney | Twin QA (mutual) |
| **Step 3:** Ingestion | Phase 3 (Build) | Wilma | Bam-Bam reviews schema/code |
| **Step 4:** Day-Level Expansion | Phase 3 (Build) | Wilma | Barney validates sample districts |
| **Step 5:** QA & Validation | Phase 3 (Build) | Gazoo | Independent audit |
| **Step 6:** Aggregation | Phase 3 → Phase 4 | Wilma | Barney validates methodology |
| **Step 7:** Product Delivery | Phase 5 (Launch) | Bam-Bam (API) + Pebbles (landing) | Betty (copy) |
| **Step 8:** Quarterly Refresh | Phase 6 (Monitor) | Wilma + Barney | Gazoo audits refresh quality |

---

## Sprint Priorities → Execution Plan

### 🔴 Sprint 1: Re-extract v1 Districts (HIGHEST IMPACT)
**What:** Run 5,910 "medium" districts through v3 extraction prompt.  
**Why:** They only have spring+winter break. Re-extraction captures ALL non-school days.  
**Owner:** Wilma (automated pipeline)  
**QA:** Barney spot-checks 50 random districts against known calendars  
**Cost:** ~$120 Claude API  
**Target:** April 2026  
**Success metric:** 5,910 districts upgraded from medium → high confidence  
**Framework phase:** Phase 3, Step 2a  

### 🔴 Sprint 2: Process Remaining Known URLs
**What:** 2,534 districts with calendar URLs not yet processed.  
**Owner:** Wilma (pipeline_v3 + firecrawl_concurrent + pdf_batch_extract)  
**QA:** Automated quality checks + Barney sample validation  
**Cost:** ~$100 (Firecrawl + Claude)  
**Target:** April 2026  
**Success metric:** +1,500-2,000 new districts  
**Framework phase:** Phase 3, Steps 1-3  

### 🔴 Sprint 3: Barney Top-200 Extraction
**What:** Continue gold-standard extractions through GitHub Issues workflow.  
**Owner:** Barney  
**QA:** Wilma ingests and validates; twin comparison where pipeline also has data  
**Cost:** $0 marginal (subscription)  
**Target:** Ongoing — current pace: ~10-15 districts/day  
**Success metric:** Top 200 by enrollment complete with gold-standard data  
**Framework phase:** Phase 3, Step 2b  

**Current progress:**
| Milestone | Status |
|-----------|--------|
| Top 20 missing by enrollment (#61-#80) | ✅ Complete |
| Re-extractions (#81-#84) | ✅ Complete |
| Current batch (#85-#112) | 🔄 In progress — #85-#89 done |
| Districts extracted | 29 |
| Students covered | ~2.9M (6.3% of national K-12) |

### 🟡 Sprint 4: Second-Pass URL Discovery
**What:** Re-search 5,696 "no results" districts with refined queries + NCES website field.  
**Owner:** Wilma  
**QA:** Barney validates URL quality on sample  
**Cost:** ~$50 (Brave API)  
**Target:** May 2026  
**Success metric:** Find URLs for 2,000-3,000 more districts  
**Framework phase:** Phase 3, Step 1d  

### 🟡 Sprint 5: CCD Metadata Backfill
**What:** Load remaining NCES fields (website, phone, address) into dim_district.  
**Owner:** Wilma  
**QA:** Bam-Bam reviews data loading script  
**Cost:** $0 (NCES is free)  
**Target:** April 2026  
**Success metric:** 13,418 districts with complete metadata  
**Framework phase:** Phase 3, Step 0  

### 🟡 Sprint 6: Automated QA Pipeline
**What:** Build automated quality checks (instructional day count, date range sanity, state law minimums, duplicates).  
**Owner:** Bam-Bam builds, Gazoo validates  
**QA:** Gazoo runs independent audit against manually-verified districts  
**Cost:** Dev time only  
**Target:** May 2026  
**Success metric:** Automated script catches 90%+ of known data issues  
**Framework phase:** Phase 3, Step 5b  

### 🟢 Sprint 7: Email Outreach
**What:** Contact remaining unfound districts directly via wilma@hazeydata.ai.  
**Owner:** Wilma (drafts), Fred (approves template), Betty (copy review)  
**QA:** Fred approves outreach template before first send  
**Cost:** $0  
**Target:** June 2026  
**Success metric:** 500+ responses, 300+ calendars received  
**Framework phase:** Phase 3, Step 2c  

### 🟢 Sprint 8: 2026-2027 Collection (THE PRODUCT)
**What:** Repeat entire pipeline for next school year as districts publish.  
**Owner:** Wilma (pipeline) + Barney (manual extraction)  
**QA:** Full twin QA on top 200; automated QA on rest  
**Cost:** ~$500 (full pipeline re-run)  
**Target:** July-September 2026  
**Success metric:** 90%+ enrollment coverage for 2026-2027 before school year starts  
**Framework phase:** Phase 3 → Phase 4 transition  

---

## Decision Rights (SSD-Specific)

| Decision | Who Decides | Who Helps |
|----------|------------|-----------|
| Extraction methodology (the golden rule) | Fred approved, Barney+Wilma implement | — |
| Schema changes | Bam-Bam proposes, Fred approves | Wilma + Barney consult |
| Which districts to prioritize | Wilma decides (by enrollment) | Barney adjusts based on extraction findings |
| QA thresholds (what's "high confidence") | Gazoo proposes, Fred approves | Barney + Wilma consult |
| Email outreach content | Fred approves template | Wilma drafts, Betty reviews |
| Pricing | Fred decides | Barney + Wilma consult |
| Data corrections (overwrite existing data) | Never overwrite — always append | `is_primary` flag decided by QA comparison |
| Spending < $50 (API costs) | Wilma can approve | Fred informed |
| Spending > $50 | Fred approves | — |

---

## Metrics That Matter Right Now

| Metric | Current | Target (Gate 1) | Who Tracks |
|--------|---------|-----------------|------------|
| **District coverage** | 8,150 / 13,418 (60.7%) | 12,750+ (95%) | Wilma (heartbeat) |
| **Enrollment coverage** | 23.98M / 46.26M (51.8%) | 43.9M+ (95%) | Wilma (heartbeat) |
| **High confidence districts** | 2,233 | 10,000+ | Wilma |
| **Medium confidence (v1, needs re-extract)** | 5,910 | 0 (all upgraded) | Wilma |
| **Barney gold-standard extractions** | 29 | 200+ | Barney → GitHub Issues |
| **School years covered** | 1 (2025-2026) | 2+ (add 2026-2027) | Wilma |
| **Twin QA comparison rate** | ~0% | 50%+ of top 200 | Wilma + Barney |
| **Automated QA pass rate** | N/A (not built) | 95%+ | Gazoo |

---

## Phase Transition Criteria

### Phase 3 → Phase 4 (Build → Position): WHEN?
All must be true:
- [ ] District coverage ≥ 95% (≥ 12,750 districts)
- [ ] Enrollment coverage ≥ 95% (≥ 43.9M students)
- [ ] High confidence ≥ 80% of covered districts
- [ ] At least 1 full school year of day-level data validated
- [ ] Automated QA pipeline running (Sprint 6 complete)
- [ ] Daily aggregate output validated against known ground truth

### Phase 4 → Phase 5 (Position → Launch): WHEN?
All must be true:
- [ ] 2026-2027 school year data ≥ 80% coverage
- [ ] API endpoint functional (REST, documented)
- [ ] Pricing model finalized (Stripe integrated)
- [ ] Landing page with sample data live
- [ ] Data dictionary + methodology published
- [ ] At least 3 potential buyer conversations completed (validation)

### Phase 5 → Phase 6 (Launch → Monitor): WHEN?
- [ ] First paying customer
- [ ] Data refresh process proven (at least 1 quarterly refresh completed)
- [ ] Support process defined for customer questions

---

## Quarterly Refresh Cycle

**Q1 (January):** Spring semester updates, snow day amendments, mid-year calendar revisions  
**Q2 (April):** Next school year calendars start publishing — begin 2027-2028 collection  
**Q3 (July):** Peak publishing season — most 2027-2028 calendars available  
**Q4 (October):** Fall semester updates, verify start dates matched reality  

Each quarterly refresh:
1. Re-check known source URLs (from `search_path` in extractions)
2. Re-extract any districts with amended calendars
3. Collect newly-published next-year calendars
4. Run full QA pass on changes
5. Regenerate aggregation + API
6. Post changelog to customers

---

## Key Findings from Collection (Living Log)

Barney's extractions are surfacing real-world complexity that validates the golden rule:

| Finding | District | Why It Matters |
|---------|----------|----------------|
| Calendar amended mid-year to eliminate all half days | Philadelphia PA (115K) | Quarterly refresh catches this; static collection wouldn't |
| District dissolving into 3 new districts July 2027 | Alpine UT (87K) | Need to track district ID changes in universe |
| Observes Yom Kippur, Lunar New Year, Eid al-Fitr | Loudoun County VA (82K) | Can't assume "standard" holidays — golden rule validates |
| Same superintendent at two extracted districts | Dr. Aaron Spence (VA Beach → Loudoun) | Contact info enables cross-referencing |
| Balanced calendar with 2-week fall intersession | Washoe County NV (64K) | Massive impact on TPCR — kids out when everyone else is in |
| 36 Wednesday early releases creating mid-week pattern | Volusia County FL (63K) | Adjacent to Disney — directly affects crowd modeling |
| Snow make-up day consumed Presidents Day holiday | Chesterfield County VA (64K) | Calendar revisions are real — quarterly refresh required |
| "Compensation Days" unique closure type | Douglas County CO (62K) | Can't use a fixed day-type taxonomy — must be flexible |

---

## Stale Artifact Cleanup

### To Archive (move to `archive/`)
**Scripts (25+ legacy scrapers):** `scraper.py`, `fast_scraper.py`, `mega_scraper*.py`, `mass_scraper*.py`, `turbo_scraper.py`, `phase3_scraper.py`, `historical_scraper*.py`, `firecrawl_*_scraper.py`, `wayback_batch_scraper.py`, `expand_scraper.py`, `parallel_extract.py`, `fetch_calendars.py`, `fetch_sitemap.py`, `rebuild_csv.py`, `merge_and_rebuild.py`, `merge_confirmed.py`, `build_daily_calendar.py`, `build_daily_calendar_v3.py`, `manual_fill.py`, `confirmation_scraper.py`, `pipeline_v2.py`

**Docs:** `METHODOLOGY.md`, `CONFIRMATION_PLAN.md`, `DATA_DICTIONARY.md`, `AUDIT_ISSUES.md`, `BATCH_QA_FEATURES.md`, `RESEARCH.md`

**To consolidate:** Fold `SALES_STRATEGY_CORRECTIONS.md` + `COMPETITIVE_ANALYSIS_v2.md` into `SALES_STRATEGY.md`

### Active Docs (keep)
| Doc | Purpose |
|-----|---------|
| `SSD_PROJECT_PLAN.md` | Full pipeline spec + sprint details |
| `SSD_COLLECTION_WORKFLOW.md` | Barney/Wilma extraction spec + JSON format |
| `SSD_PROJECT_ORIGINS.md` | History + context + Fred's quotes |
| `SSD_ONE_PAGER.md` | Customer-facing product summary |
| `SSD_AUDIT_V3.md` | Barney's quality audit (reference) |
| `SSD_QUALITY_VALIDATION.md` | Quality system design |
| `PIPELINE_ARCHITECTURE.md` | Technical architecture |
| `SALES_STRATEGY.md` | Go-to-market (needs corrections merged) |
| `collection_methodology.md` | Three-tier collection approach |
| `state_doe_research.md` | 50-state reference material |
| `district_profiles_schema.md` | Profile data design |

---

## Communication Rhythm

| When | What | Where |
|------|------|-------|
| Every heartbeat (~2-3×/day) | Coverage metrics (districts + enrollment %) | #school-schedules |
| As Barney completes batches | Sprint updates with key findings | #school-schedules |
| As Wilma ingests | Ingestion confirmations + DB totals | #school-schedules |
| Weekly | Progress summary — coverage change, sprints status, blockers | #briefing (forum post, SSD tag) |
| Quarterly | Refresh cycle report — what changed, what's new | #briefing + customer changelog |

---

## Cost Model

| Component | Estimated Total | Quarterly Refresh |
|-----------|----------------|-------------------|
| Brave Search API | ~$120 | ~$30 |
| Firecrawl (JS pages) | ~$50 | ~$20 |
| Claude Sonnet (extraction) | ~$390 | ~$100 |
| Barney (subscription) | $0 marginal | $0 |
| NCES data | $0 | $0 |
| Email outreach | $0 | $0 |
| **Total** | **~$560** | **~$150** |

---

## The "Not Now" List

| Item | Trigger to Activate |
|------|-------------------|
| Historical years (2023-2024 and earlier) | 2 consecutive years at 95%+ with validated patterns |
| Private school calendars | Public school product profitable (MRR > $5K) |
| Charter school detailed calendars | After all regular districts complete |
| International school calendars | US product proven, customer demand signals |
| Real-time calendar change alerts | After quarterly refresh cycle proven reliable |
| Machine learning on calendar patterns | After 3+ years of historical data |

---

## How This Maps to the Big Framework

| Big Framework Section | SSD Status | Action |
|----------------------|-------------|--------|
| Flintstones Org Chart | Wilma + Barney active core | Full team at Phase 5 |
| QA System | Twin collection (Barney QA), automated QA planned | Sprint 6 formalizes |
| Adaptive QA Ratings | Not yet — too early | Start at Gate 1 |
| Micro QA Principle | Applied to extractions (Barney ↔ Wilma) | Expand at Phase 5 |
| Metrics Framework | Coverage metrics only | Full AARRR at Gate 1 |
| Three Ideas Rule | Applied to methodology decisions | Expand to all SSD decisions |
| Post-Fix Verification | Applied to re-extractions (verify improvement) | Formalize with Sprint 6 |
| Data Quality Assurance | Collection QA active (twin collection), Prediction QA not yet needed | Model QA at Phase 4 |

---

*This is the living operating plan for SSD. Wilma owns it. Fred reviews as milestones hit.*

*When SSD hits Gate 1 (first paying customer), this document gets a major revision.*
