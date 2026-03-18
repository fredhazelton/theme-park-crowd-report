# SSD Project Plan — School Schedules Database

**Product:** US School Calendar Intelligence  
**Company:** hazeydata.ai  
**Last Updated:** 2026-03-18  
**Status:** Active Collection — Phase 5

---

## The Product

A complete, day-level school calendar dataset for **every US public school district** (~13,418 districts, ~46.3M students). For each district, for each day of the school year: are students in session or not?

**Why it matters:** School schedules are the single strongest predictor of travel demand, retail patterns, and theme park attendance. No one sells this data comprehensively at an accessible price point.

**The golden rule:**
> For every single day of the school year (July 1 – June 30), determine whether students are in session or not. No assumptions. No shortcuts. The source calendar is the only truth.

---

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SSD PIPELINE                                 │
│                                                                     │
│  STEP 0          STEP 1           STEP 2          STEP 3            │
│  Universe    →   URL Discovery →  Collection  →   Ingestion         │
│  Definition      & Classification                                   │
│                                                                     │
│  STEP 4          STEP 5           STEP 6          STEP 7            │
│  Day-Level   →   QA &         →   Aggregation →   Product           │
│  Expansion       Validation                       Delivery          │
│                                                                     │
│  STEP 8                                                             │
│  Quarterly Refresh                                                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## STEP 0: Universe Definition

**Goal:** Establish the complete list of US public school districts with metadata.

**Source:** NCES Common Core of Data (CCD) — LEA (Local Education Agency) directory.

| Field | Source | Status |
|-------|--------|--------|
| District ID (NCES LEAID) | CCD | ✅ Done |
| District name | CCD | ✅ Done |
| State | CCD | ✅ Done |
| City / County / ZIP | CCD | ✅ Done |
| Enrollment | CCD (2023-2024) | ✅ Done (233 districts missing) |
| Lat / Lon | CCD | ✅ Done |
| District website | CCD `website` field | ⚠️ Partial — in CCD raw file, not fully loaded |
| Phone | CCD | ⚠️ Partial |
| Mailing/physical address | CCD | ⚠️ Partial |

**Current universe:** `districts_comprehensive.csv` — 13,418 districts

**Remaining work:**
- [ ] Backfill 233 districts with missing enrollment from CCD or manual lookup
- [ ] Load `website` field from CCD raw file for all districts (many already have it)
- [ ] Load phone and address fields from CCD for email outreach
- [ ] Add calendar type classification (traditional / year-round / modified) — currently all default to "traditional"

**Output:** `dim_district` table fully populated with NCES metadata.

---

## STEP 1: URL Discovery & Classification

**Goal:** For every district, find the URL where their official school calendar lives and classify what type of content it is.

### 1a. Brave Search Scan

Search for each district's calendar using Brave API.

| Metric | Value |
|--------|-------|
| Districts searched | 12,465 |
| Found URLs | 6,769 (54%) |
| No results | 5,696 (46%) |

**URL classification breakdown:**

| Category | Count | Description |
|----------|-------|-------------|
| `pdf` | 2,348 | Direct PDF link — cheapest to process (free download) |
| `calendar` | 1,977 | Calendar page (likely JS-rendered) — needs Firecrawl |
| `calendar_likely` | 681 | Probably a calendar page — needs verification |
| `aggregator` | 473 | Third-party site (SchoolCalendarInfo, etc.) |
| `generic` | 1,290 | Homepage or generic page — needs deeper crawling |
| No results | 5,696 | Nothing found — needs alternative approaches |

**Stored in:** `brave_url_scan_results.json`

### 1b. NCES Website Field

The CCD includes a `website` field for most districts. For the 5,696 "no results" districts:
- [ ] Try navigating to `{website}/calendar` or `{website}/calendars`
- [ ] Check for sitemap.xml entries containing "calendar"
- [ ] Use as fallback starting point for manual search

### 1c. State DOE Directories

Some states publish all district calendars centrally.
- [ ] Review `state_doe_calendar_survey.json` for states with centralized data
- [ ] Prioritize states where many districts are missing
- [ ] Gold standard states (ones that mandate reporting): cross-reference `state_doe_research.md`

### 1d. Second-Pass Search (Unfound Districts)

For districts where Brave found nothing:
- [ ] Refined queries: `"{district name}" "2025-2026" calendar site:.us`
- [ ] State-specific search: `"{district name}" {state} school calendar`
- [ ] Try Google Custom Search API as backup

**Output:** For each district, a `calendar_url` and `url_type` (pdf / html / unknown / not_found).

---

## STEP 2: Collection

**Goal:** Extract the complete school calendar from every district's source.

### The Two Collection Tracks

| Track | Agent | Method | Cost Model |
|-------|-------|--------|------------|
| **Automated Pipeline** | Wilma | Brave → PDF/Firecrawl → Claude extraction → SQLite | Per-API-call |
| **Manual Extraction** | Barney | Web search → read calendar → post JSON to GitHub Issues | Subscription (no per-query cost) |

Both tracks run **independently and in parallel**. Results are stored as separate rows in `dim_calendar_source` (tagged by `scrape_method`). Neither overwrites the other.

### 2a. Automated Pipeline (Wilma)

**Script:** `pipeline_v3.py` + modules in `v3/`

| Source Type | Tool | Cost | Speed |
|-------------|------|------|-------|
| PDF | `pdftotext` (free) → Claude | ~$0.01/district | ~500/hour |
| HTML/JS | Firecrawl ($0.01/page) → Claude | ~$0.02/district | ~200/hour |
| Stubborn sites | Brave retry → alternate URLs | Variable | Manual |

**Extraction prompt (v3):** Instructs Claude to extract EVERY non-school day — no checklist of expected breaks. Captures holidays, teacher workdays, half days, unusual closures (county fairs, weather days, cultural holidays), Saturday sessions.

**Current automated coverage:**

| Method | Districts | Confidence |
|--------|-----------|------------|
| `llm_extract` (v1 migration) | 5,910 | ⚠️ Medium — spring+winter break only |
| `pdf_extract_v3` | 1,045 | ✅ High |
| `firecrawl_v3` | 819 | ✅ High |
| `retry_firecrawl_v3` | 164 | ✅ High |
| `gap_firecrawl_v3` | 124 | ✅ High |
| `gap_pdf_v3` | 50 | ✅ High |
| Other v3 methods | 31 | ✅ High |
| **Total** | **8,143** | |

### 2b. Manual Extraction (Barney via GitHub Issues)

**Workflow:** See `SSD_COLLECTION_WORKFLOW.md` for full spec.

1. Wilma creates `SSD-collect` issues (top 50 individual, rest batched by state)
2. Barney picks up issues, finds official calendar, reads it exhaustively
3. Barney posts complete JSON extraction per school year as issue comment
4. Barney labels `SSD-extracted`
5. Wilma ingests, validates, closes as `SSD-complete`

**Extraction standard:**
- Every non-school day with date, type, and name
- Saturday sessions if present
- Total instructional day count for cross-checking
- Contact info (superintendent name, email, phone)
- Source URL + search path (for quarterly repeatability)
- All available school years (2025-2026 required, 2026-2027 when published, 2024-2025 bonus)

**Current Barney progress:**

| Metric | Value |
|--------|-------|
| Districts extracted | 24 |
| Students covered | ~2.6M |
| Top 20 by enrollment | ✅ Complete |
| Issues queued (#85-#112) | 28 districts, ~1.3M students |

### 2c. Email Outreach (Final Mile)

For districts where no calendar can be found online:
- [ ] Draft professional outreach email from wilma@hazeydata.ai
- [ ] Request 2025-2026 (and 2026-2027 if available) calendar PDF
- [ ] Track responses in GitHub Issues (`SSD-blocked` → `SSD-collected`)
- [ ] FOIA request as last resort for non-responsive districts

**Contact data needed:** `contact_name`, `district_email`, `phone` — sourced from CCD, district websites, or Barney's extraction notes.

---

## STEP 3: Ingestion

**Goal:** Parse extraction JSON and load into v3 star schema.

**Database:** `v3/school_schedules.db` (SQLite)

**Schema v3.1:**

```
dim_district           — One row per district (NCES metadata + contact info)
dim_calendar_source    — One row per extraction (district × school_year × scrape_method)
fact_school_day        — One row per district per day (365 × districts × years)
```

**Key design decisions:**
- `UNIQUE(district_id, school_year, scrape_method)` — both Wilma and Barney extractions coexist
- `is_primary` flag — marks which source is trusted for production dataset
- Dual-source storage — never overwrite, always keep both
- Multi-year support — separate source rows per school year

**Ingestion scripts:**
- `v3/ingest_barney.py` — processes Barney's GitHub Issue JSON
- `v3/generate_days.py` — expands key dates into 365-row fact table
- Handles `saturday_sessions`, `other_breaks`, and all day types

---

## STEP 4: Day-Level Expansion

**Goal:** Turn key-date extractions into one row per district per day.

**Logic in `v3/generate_days.py`:**

```
For each day from July 1 to June 30:
  1. Before first_day or after last_day → SUMMER
  2. Explicitly listed in non_school_days → use stated type (HOLIDAY/BREAK/TEACHER_WORKDAY/HALF_DAY)
  3. Explicitly listed in saturday_sessions → SCHOOL_DAY (is_in_session=1)
  4. Saturday or Sunday (not in saturday_sessions) → WEEKEND
  5. Everything else between first_day and last_day → SCHOOL_DAY
```

**Validation check:** Count SCHOOL_DAY rows between first_day and last_day. If significantly more than the calendar's stated `total_instructional_days` (e.g., 195 vs 180), there are likely missing non-school days.

---

## STEP 5: QA & Validation

### 5a. Twin Collection Comparison

When both Wilma and Barney have extracted the same district:

| Scenario | Action |
|----------|--------|
| Both agree on dates | ✅ Highest confidence |
| Barney finds days Wilma missed | Barney's data fills the gap |
| Wilma has data Barney can't find | Use Wilma's, flag for verification |
| Disagreement on a date | Flag for Fred's manual review |

### 5b. Automated Quality Checks

- [ ] Instructional day count cross-check (extracted count vs calendar's stated count)
- [ ] Spring break sanity (should be in March-April for most districts)
- [ ] School year boundaries (first_day typically Aug-Sep, last_day typically May-Jun)
- [ ] Minimum school days per state law (most states require 170-180)
- [ ] Duplicate detection (same calendar assigned to wrong district)
- [ ] Year-over-year consistency (when we have multiple years)

### 5c. Confidence Levels

| Level | Criteria |
|-------|----------|
| **high** | v3 extraction (all day types), cross-checked, source is official calendar |
| **medium** | v1 migration (spring+winter only) OR automated extraction without cross-check |
| **low** | Inferred from state medians or aggregator data |

---

## STEP 6: Aggregation

**Goal:** Produce the headline metric — *"What percentage of US students are on break today?"*

**Output:** `daily_aggregate_v3.csv`

| Column | Description |
|--------|-------------|
| `date` | YYYY-MM-DD |
| `pct_in_session` | Enrollment-weighted % of students in school |
| `pct_on_break` | Enrollment-weighted % on named break |
| `pct_weekend` | % on weekend |
| `pct_summer` | % in summer |
| `districts_reporting` | How many districts have data for this date |
| `enrollment_covered` | Total enrollment with data |
| `total_enrollment` | Universe enrollment |
| `coverage_pct` | enrollment_covered / total_enrollment |

**State-level aggregation** (same structure, per state) for regional analysis.

---

## STEP 7: Product Delivery

- [ ] REST API: `GET /api/ssd/daily?date=2026-03-18&state=FL`
- [ ] Bulk CSV download
- [ ] Stripe integration (one-time purchase or annual subscription)
- [ ] Landing page at hazeydata.ai/school-schedules
- [ ] Data dictionary + methodology docs
- [ ] Sample data (free tier — top 100 districts or state-level aggregates)

---

## STEP 8: Quarterly Refresh

**Frequency:** 4× per year (Sep, Dec, Mar, Jun)

**Why quarterly:**
- Districts amend calendars mid-year (Philadelphia just eliminated all half days — affects 170K+ students)
- Snow days, COVID closures, and board votes change schedules
- New school years get published in spring/summer for the following year

**Repeatability built into the workflow:**
- Every extraction documents `source_url` + `search_path` + `extraction_date`
- Next quarter: go directly to known source URLs first
- Only re-search districts whose sources returned 404 or changed
- Barney's search paths mean we don't reinvent the wheel

**Refresh process:**
1. Re-check known source URLs for updates
2. Re-extract any districts with amended calendars
3. Collect newly-published next-year calendars (e.g., 2027-2028 in spring 2027)
4. Run full QA pass on changes
5. Regenerate aggregation + API

---

## Current State — Honest Numbers

### Coverage (March 18, 2026)

```
Districts    ████████████░░░░░░░░  60.7%  (8,150 / 13,418)
Enrollment   ██████████░░░░░░░░░░  51.8%  (23.98M / 46.26M)
Target       ███████████████████░  95.0%
```

### Quality Breakdown

| Tier | Districts | Enrollment | Notes |
|------|-----------|------------|-------|
| ✅ High confidence (v3) | 2,233 | ~12M | Full calendar, all day types |
| ⚠️ Medium (v1 migration) | 5,910 | ~12M | Spring+winter break only — needs re-extraction |
| ❌ Not yet collected | 5,268 | ~22.3M | No data |
| 🔵 Barney manual (gold) | 24 | ~2.6M | Independent verification, all day types |

### Known Issues

1. **5,910 "medium" districts are incomplete.** They only have spring + winter break. Missing: fall break, Thanksgiving, teacher workdays, holidays, half days, unusual closures. **These need re-extraction through v3 prompt.** This is the single biggest quality gap.

2. **233 districts missing enrollment.** Can't weight them in aggregation. Need CCD backfill.

3. **Only 2025-2026 data collected.** No 2026-2027 yet (districts haven't all published). No 2024-2025 retroactive collection yet.

4. **Contact info sparse.** Only 128/8,150 districts have superintendent name. Only 41 have email. Limits email outreach capability.

5. **No automated QA.** Quality checks are manual. Need to build automated pipeline (Step 5b).

---

## Priority Execution Order

### Sprint 1: Re-extract v1 Districts (HIGHEST IMPACT)
**What:** Run 5,910 "medium" districts through v3 extraction prompt.
**Why:** These already have source URLs. Re-extraction upgrades them from "spring+winter only" to "every non-school day." Moves 5,910 districts from medium → high confidence.  
**Cost:** ~$120 Claude API (content already cached or URL known).
**Impact:** Quality jumps massively without adding a single new district.

### Sprint 2: Process Remaining Known URLs
**What:** 2,534 districts have calendar URLs (from Brave scan) but haven't been processed.
**Why:** We already know where the calendar is — just need to download and extract.
**Impact:** +2,000 districts estimated.

### Sprint 3: Barney Continues Top Districts
**What:** Continue GitHub Issues workflow through top 200 by enrollment.
**Why:** Gold-standard extractions, twin collection QA, contact info gathering.
**Impact:** Covers the biggest districts = most enrollment per extraction.

### Sprint 4: Second-Pass URL Discovery
**What:** Re-search 5,696 "no results" districts with refined queries + NCES website field.
**Why:** First Brave scan was single-query. Multi-query approach should find 2,000-3,000 more.
**Impact:** Attacks the long tail.

### Sprint 5: CCD Metadata Backfill
**What:** Load remaining CCD fields (website, phone, address) into dim_district.
**Why:** Enables email outreach (Step 2c) and improves URL discovery (Step 1b).
**Impact:** Foundation for final-mile collection.

### Sprint 6: Automated QA Pipeline
**What:** Build Step 5b quality checks into automated script.
**Why:** Can't manually QA 13,000+ districts. Need automated anomaly detection.
**Impact:** Catch errors before they reach customers.

### Sprint 7: Email Outreach
**What:** Contact remaining unfound districts directly.
**Why:** Some small/rural districts don't publish calendars online.
**Impact:** Final mile — gets us from ~90% to 95%+.

### Sprint 8: 2026-2027 Collection (THE PRODUCT)
**What:** Repeat pipeline for next school year.
**Why:** This is what buyers actually want — future calendars.
**When:** Summer 2026 as districts publish.

---

## Target Milestones

| Milestone | Target | Metric |
|-----------|--------|--------|
| 80% enrollment coverage (high confidence) | April 2026 | Sprint 1 + 2 |
| 90% enrollment coverage | May 2026 | Sprint 3 + 4 |
| 95% enrollment coverage | June 2026 | Sprint 5 + 6 + 7 |
| 2026-2027 collection begins | July 2026 | Sprint 8 |
| First sellable product ships | September 2026 | 2026-2027 data |
| Three-year dataset (predictive) | December 2026 | 2024-25 + 25-26 + 26-27 |

---

## Architecture Reference

### Active Code (v3/)

| Script | Purpose |
|--------|---------|
| `pipeline_v3.py` | Main pipeline orchestrator |
| `generate_days.py` | Key dates → 365 day-level rows |
| `ingest_barney.py` | Process Barney's GitHub Issue JSON |
| `firecrawl_concurrent.py` | Parallel Firecrawl processing |
| `pdf_batch_extract.py` | PDF download + Claude extraction |
| `gap_filler.py` | Fill gaps in existing data |
| `retry_failures.py` | Retry failed extractions |
| `target_hunter.py` | Find URLs for unfound districts |
| `manual_extract.py` | Manual high-value extraction |
| `nces_backfill.py` | CCD metadata enrichment |
| `contact_enrichment.py` | Contact info gathering |
| `status_dashboard.py` | Coverage reporting |

### Active Data Files

| File | Purpose |
|------|---------|
| `districts_comprehensive.csv` | Universe (13,418 districts) |
| `brave_url_scan_results.json` | URL discovery results |
| `brave_pdf_hunt_results.json` | PDF-specific search |
| `v3/school_schedules.db` | Production star schema |
| `v3/schema.sql` | Database DDL |

### Active Documentation

| Doc | Purpose |
|-----|---------|
| `SSD_PROJECT_PLAN.md` | This file — the master plan |
| `SSD_COLLECTION_WORKFLOW.md` | Barney/Wilma collection spec + JSON format |
| `SSD_PROJECT_ORIGINS.md` | History + context + Fred's quotes |
| `SSD_ONE_PAGER.md` | Customer-facing product summary |
| `PIPELINE_ARCHITECTURE.md` | Technical architecture details |

### Stale / To Archive

**Scripts (root level):** ~25 legacy scrapers from v1/v2 era — `scraper.py`, `fast_scraper.py`, `mega_scraper*.py`, `mass_scraper*.py`, `turbo_scraper.py`, `phase3_scraper.py`, `historical_scraper*.py`, `firecrawl_*_scraper.py`, `wayback_batch_scraper.py`, `expand_scraper.py`, `parallel_extract.py`, `fetch_calendars.py`, `fetch_sitemap.py`, `rebuild_csv.py`, `merge_and_rebuild.py`, `merge_confirmed.py`, `build_daily_calendar.py`, `build_daily_calendar_v3.py`, `manual_fill.py`, `confirmation_scraper.py`, `pipeline_v2.py`

**Docs:** `METHODOLOGY.md` (pre-v3), `CONFIRMATION_PLAN.md` (pre-v3), `DATA_DICTIONARY.md` (pre-v3 schema), `AUDIT_ISSUES.md` (pre-v3), `BATCH_QA_FEATURES.md` (v2-specific), `RESEARCH.md` (Phase 1 only), `SALES_STRATEGY_CORRECTIONS.md` (should be folded into SALES_STRATEGY.md)

**Data files:** ~40 intermediate JSON/CSV files from v1/v2 scraping runs — can be archived once v3 is stable.

---

## Cost Model

| Component | Per-District | At Scale (13,418) |
|-----------|-------------|-------------------|
| Brave Search | $0.005 | ~$67 |
| Firecrawl (JS pages) | $0.01 | ~$50 (only ~5K need it) |
| Claude Sonnet (extraction) | $0.02 | ~$268 |
| Claude (re-extraction of v1) | $0.02 | ~$118 |
| Barney (subscription) | $0 marginal | $0 |
| Email outreach | $0 | $0 |
| **Total estimated** | | **~$500** |

**Quarterly refresh cost:** ~$200 (only re-process changed/updated calendars + new school years).

---

## Key Principles

1. **No assumptions.** Don't assume weekends off. Don't assume federal holidays observed. Only the calendar is truth.
2. **Dual-source everything.** Wilma's pipeline + Barney's manual extraction coexist. Quality wins.
3. **Document the search path.** Every extraction records how the source was found — for quarterly repeatability.
4. **Capture all years available.** 2025-2026 required. 2026-2027 is the product. 2024-2025 is a bonus.
5. **Never overwrite.** Always append. Use `is_primary` to decide what's production.
6. **GitHub Issues is the hub.** All collection flows through issues — trackable, auditable, team-visible.
7. **95% enrollment coverage is the bar.** Both districts and enrollment must hit mid-90s for product viability.

---

*This is the living project plan. Update as milestones are hit.*
