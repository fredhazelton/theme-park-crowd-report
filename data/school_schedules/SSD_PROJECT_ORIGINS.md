# School Schedules Database (SSD) — Project Origins & Next Steps

**Author:** Wilma  
**Created:** 2026-03-18  
**Last Updated:** 2026-03-18

---

## 1. Origins

### The TouringPlans Insight

Fred Hazelton spent years at **TouringPlans.com** building crowd prediction models for Disney theme parks. A core discovery: **school schedules are the single strongest predictor of theme park attendance.** When kids are on spring break, parks flood. When school's in session, they empty out.

At TouringPlans, the team eventually *stopped* manually gathering school calendars because they could approximate the effect with a "date group ID" — a proxy based on weekday/weekend/holiday patterns that captured most of the variance without the pain of collecting 13,000 individual calendars.

> *"The patterns were predictable enough that we didn't need to gather the school schedule, we just needed to know where the weekdays and weekends and holidays fell, and we could make a pretty good guess about the number of schools in session."*  
> — Fred Hazelton, 2026-03-15

### The Data Product Idea

In February 2026, while building **hazeydata.ai** (Fred's theme park analytics company), the question came up: **what if we actually did collect every school calendar?** Not as a proxy — the real thing. A complete, day-level dataset answering: *"What percentage of US students are on break today?"*

No one sells this data comprehensively. The competitive landscape (as of March 2026):
- **SchoolCalendarInfo.com** — Aggregates calendars but no API, limited coverage
- **Burbio.com** — School calendar data for real estate, $100K+/yr enterprise
- **State DOE sites** — Fragmented, no standard format, often behind JS-rendered portals

The gap: **a complete, machine-readable, day-level school calendar dataset for every US public school district**, priced accessibly and updated annually. Useful for theme parks, travel companies, retail, transportation, and anyone whose business fluctuates with school schedules.

### First Steps (Feb 5, 2026)

Fred told Wilma: *"Why don't you get started on school schedules? You can start with the first 100 and see how it goes."*

Wilma began scraping the top 100 US school districts by enrollment using SchoolCalendarInfo.com as the initial source. The daily flag table concept was established early — one row per district per day, with `is_in_session` as the core field.

### The Daily Flag Table

Fred's vision from the start:

> *"That daily flag table is how I pictured it and how the LLM will be trained — a simple binary: are kids in school today, yes or no?"*

The product output is a **daily aggregate**: for each day of the school year, what percentage of US students (weighted by enrollment) are in session vs. on break. This directly feeds crowd prediction models.

---

## 2. Evolution Timeline

### Phase 1: SchoolCalendarInfo Scraper (Feb 5-8, 2026)
- Scraped **655 districts** from SchoolCalendarInfo.com
- Built the first `daily_aggregate.csv` showing spring break waves
- Covered 38.5% of US enrollment by confirmed data
- Remaining 61.5% filled with state-level inference (median dates)

### Phase 2: LLM Scraper v1 (Mar 8-16, 2026)
- Barney designed the pipeline architecture ("Confirmation Plan")
- Used **Firecrawl** (JS rendering) + **Claude Sonnet** (extraction) to scrape district websites
- Processed **5,919 districts** — 96.7% success rate
- But only extracted **spring break + winter break** dates (2 break types)
- Enrolled in NCES CCD data for the full district universe: **13,418 regular districts, 46.3M enrollment**

### Phase 3: The Accuracy Wake-Up Call (Mar 15, 2026)
- Deep audit revealed the LLM scraper was only **27% accurate** — most dates were fabricated or from wrong school years
- Even Claude with web search benchmarked at only **67% precision**
- Fred's response: *"If you have to try 16 different ways to get at the calendar — do it!"*
- Led to the **"16 Ways" Multi-Source Triangulation** concept

### Phase 4: Pipeline v3 — Star Schema (Mar 17, 2026)
- Complete architectural rewrite
- **Star schema**: `dim_district` + `dim_calendar_source` + `fact_school_day`
- New extraction prompt: *"Extract EVERY non-school day"* (not just named breaks)
- Day types: SCHOOL_DAY, WEEKEND, BREAK, HOLIDAY, TEACHER_WORKDAY, HALF_DAY, SUMMER
- Strategy: Brave Search → find URLs → PDF download (free) or Firecrawl (JS pages) → Claude extraction → SQLite
- Loaded initial 5,932 districts from v1 data migration

### Phase 5: PDF + Firecrawl Sprints (Mar 17-18, 2026)
- **Brave URL Scan**: Searched 12,465 unfound districts — found URLs for 6,769 (54%)
  - 2,348 PDFs, 1,977 calendar pages, 681 likely calendars, 1,290 generic pages
- **PDF Extraction**: Downloaded and processed ~1,045 PDFs through v3 pipeline
- **Firecrawl Batches**: Processed ~1,107 districts via Firecrawl JS rendering
- **Manual Extraction**: 10 high-value districts manually verified

---

## 3. Where We Are Now (March 18, 2026)

### Database Status

| Metric | Value |
|--------|-------|
| **Districts with day-level data** | 8,143 |
| **Total in universe** | 13,418 |
| **Coverage (districts)** | 60.7% |
| **Enrollment captured** | 22.7M |
| **Total US enrollment** | 46.3M |
| **Coverage (enrollment)** | 49.2% |
| **Day-level rows** | 2,918,905 |
| **States represented** | 51 (incl. DC) |

### Collection Methods

| Method | Districts | Notes |
|--------|-----------|-------|
| `llm_extract` (v1 migration) | 5,910 | Original Firecrawl+Claude scrape, spring+winter only |
| `pdf_extract_v3` | 1,045 | Direct PDF download → pdftotext → Claude |
| `firecrawl_v3` | 819 | Firecrawl JS rendering → Claude |
| `retry_firecrawl_v3` | 164 | Failed districts retried |
| `gap_firecrawl_v3` | 124 | Gap-filling pass |
| `gap_pdf_v3` | 50 | Additional PDF finds |
| `tier1_pdf_search` | 20 | Targeted PDF search |
| `manual_extract_v3` | 10 | Hand-verified |
| `tier2_website_pdf` | 1 | Website PDF extraction |

### Confidence Levels

| Level | Districts | Meaning |
|-------|-----------|---------|
| **high** | 2,233 | v3 pipeline (PDF or Firecrawl), full calendar extracted |
| **medium** | 5,910 | v1 migration, spring+winter break only |

### URL Intelligence (from Brave Scan)

Of 12,465 districts searched:
- **Found URLs:** 6,769 (54%)
  - PDF links: 2,348
  - Calendar pages: 1,977
  - Calendar likely: 681
  - Aggregator: 473
  - Generic/homepage: 1,290
- **No results:** 5,696 (46%)

---

## 4. What Still Needs Doing

### Remaining Gap: ~5,275 districts (39.3%), ~23.5M enrollment (50.8%)

### Immediate Next Steps

#### A. Re-extract v1 Districts (5,910 districts) — HIGH PRIORITY
The 5,910 `llm_extract` districts only have spring + winter break dates. They need re-processing through the v3 prompt to capture ALL non-school days (fall break, Thanksgiving, teacher workdays, holidays, etc.). Many of these already have good source URLs from the original scrape.

**Action:** Run v3 extraction on existing source URLs/content for these 5,910 districts.  
**Expected result:** Upgrade from `medium` to `high` confidence, capture 6+ break types per district.  
**Cost:** ~$120 in Claude API (already have the content cached).

#### B. Process Remaining Calendar URLs (~2,534 districts)
From the Brave URL scan, 2,534 districts have known calendar URLs (calendar pages or PDFs) but haven't been processed yet.

**Action:** Firecrawl the calendar pages, download the PDFs, run through v3 pipeline.  
**Expected result:** 1,500-2,000 new districts added.  
**Cost:** Firecrawl credits + ~$50 Claude API.

#### C. Second-Pass URL Discovery (~5,696 districts)
5,696 districts returned no results in the first Brave scan. Options:
1. **Refined search queries** — Try variations: "school year calendar 2025-2026", district website + "/calendar", state DOE directory lookups
2. **NCES website field** — Many of these districts have a `website` URL in the NCES CCD data; try navigating directly to `{website}/calendar`
3. **State DOE centralized calendars** — Some states publish all district calendars centrally

**Action:** Build a second-pass search with improved queries + NCES website data.  
**Expected result:** Find URLs for 2,000-3,000 more districts.

#### D. Email Outreach (Final Mile)
For districts where no calendar can be found online:
1. Draft professional email from wilma@hazeydata.ai
2. Request 2025-2026 calendar PDF
3. Track responses, process received calendars

**Action:** Build email template + tracking system.  
**Expected result:** Cover the hardest-to-find districts (mostly small/rural).

#### E. Quality Validation Pass
- Spot-check v1 migrated data against known calendars
- Flag anomalies (spring break in December, < 160 school days, etc.)
- Cross-reference top 100 districts against official published calendars
- Build automated QA checks into the pipeline

### Medium-Term Roadmap

#### F. 2026-2027 Collection (THE SELLABLE PRODUCT)
Once 2025-2026 hits 95%, repeat the pipeline for 2026-2027 calendars as districts publish them (summer 2026). This is the first revenue-generating dataset — buyers need *future* calendars.

#### G. Retrofit 2024-2025 (Medium Confidence)
With two years of high-quality data (2025-2026 + 2026-2027), analyze year-over-year patterns to retrofit 2024-2025 at medium confidence. Most districts repeat the same calendar structure ±1 week.

#### H. Data Product Packaging
- **API**: REST endpoint — `GET /api/ssd/districts?state=FL&format=csv`
- **Stripe integration**: One-time purchase ($X) or annual subscription
- **Landing page**: hazeydata.ai/school-schedules with sample data + methodology
- **Data dictionary**: Column definitions, confidence levels, update cadence

#### I. Sales & Distribution
- Target buyers: theme parks, travel companies, retail chains, transportation, education analytics
- Pricing research completed (see `SALES_STRATEGY.md`)
- Competitive positioning: More comprehensive than Burbio, more affordable, API-first

### Business Timeline & Market Reality

**The 2025-2026 school year is NOT the product for sale.** By the time we reach 95% coverage, that school year will be mostly over. The 2025-2026 collection is the **proving ground** — building the pipeline, validating quality, and establishing coverage.

**The real product is 2026-2027:**
1. Hit 95% coverage on 2025-2026 (proves the pipeline works)
2. Repeat the process for 2026-2027 calendars (published summer 2026)
3. Ship 2026-2027 data to market — this is the first sellable product
4. With two years of high-quality data (2025-2026 + 2026-2027), analyze patterns
5. Retrofit 2024-2025 with medium confidence using those patterns
6. Three school years of data = predictive model + recurring annual product

**Why this order matters:** Buyers need *future* school calendars, not past ones. A travel company planning for spring break 2027 needs that data by fall 2026. The 2025-2026 collection is an investment in pipeline maturity, not direct revenue.

### Long-Term Vision

The complete dataset — **every US public school district, every day of the school year, updated annually** — becomes the authoritative source for school-calendar-driven analytics. Historical data enables prediction. Prediction enables premium pricing. The first product from hazeydata.ai.

---

## 5. Architecture Reference

```
districts_comprehensive.csv     ← 13,418 district universe (NCES CCD)
brave_url_scan_results.json     ← URL discovery for 12,465 districts
brave_pdf_hunt_results.json     ← PDF-specific search for 5,919 districts
v3/school_schedules.db          ← Star schema SQLite (production)
  ├── dim_district              ← District metadata + enrollment
  ├── dim_calendar_source       ← Source URL, method, confidence per district
  └── fact_school_day           ← One row per district per day (365 × N)
v3/pipeline_v3.py               ← Main pipeline (Brave → Firecrawl/PDF → Claude → SQLite)
v3/firecrawl_concurrent.py      ← Parallel Firecrawl processing
v3/pdf_batch_extract.py         ← PDF download + extraction
v3/generate_days.py             ← Expand key dates → 365 day-level rows
v3/gap_filler.py                ← Fill gaps in existing data
v3/retry_failures.py            ← Retry failed extractions
```

---

## 6. Cost to Date (Estimated)

| Component | Estimated Cost |
|-----------|---------------|
| Brave Search API | ~$80 |
| Firecrawl credits | ~$30 |
| Claude Sonnet API (extraction) | ~$250 |
| NCES data | Free |
| SchoolCalendarInfo scraping | Free |
| **Total** | **~$360** |

---

## 7. Key Quotes

> *"If you have to try 16 different ways to get at the calendar — do it!"*  
> — Fred Hazelton, 2026-03-15

> *"The daily flag table is how I pictured it — a simple binary: are kids in school today, yes or no?"*  
> — Fred Hazelton, 2026-03-08

> *"This is why we stopped putting in the manual effort at TouringPlans — the patterns were predictable enough. But now instead of a proxy, you've got the real thing."*  
> — Fred, reflecting on the SSD vs. TouringPlans approach

---

*This document captures the full history and forward plan for the SSD project. Update as milestones are hit.*
