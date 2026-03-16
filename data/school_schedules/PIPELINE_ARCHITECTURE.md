# School Calendar Collection Pipeline — Architecture Document
## "The 16 Ways" Multi-Source Triangulation Engine

**Author:** Wilma (AI Data Collection Engineer)  
**Date:** 2026-03-16  
**Version:** 1.0  
**Status:** Draft — Ready for Review

---

## 1. Executive Summary

We are building a production-grade system to collect, verify, and maintain school calendar data for every public school district in the United States (~10,000 districts). The data must be accurate enough to charge $1,200/state for commercial licensing.

**Key insight from testing:** No single collection method achieves acceptable accuracy alone. Our V1 scraper was 27% accurate with 73% fabricated dates. Even Claude with web search tools only achieves 67% precision. The only way to build a premium data product is **multi-source triangulation** — hitting every available source and building consensus.

**Competitive landscape:** `schools-calendar.com` ("School Calendar API") exists as a competitor but uses single-source scraping. We verified their data contains the same systematic errors as our V1 scraper. Our state DOE approach and multi-source verification give us a fundamental quality edge.

---

## 2. Target Data Model

### Per District, Per School Year
```
district_id         NCES district ID (e.g., "0100189")
district_name       Official name (e.g., "Satsuma City")
state               2-letter code
school_year         "2025-2026"

first_day           YYYY-MM-DD  First day of school for STUDENTS
last_day            YYYY-MM-DD  Last day of school for STUDENTS
winter_break_start  YYYY-MM-DD  First day of winter/Christmas break
winter_break_end    YYYY-MM-DD  Last day of winter/Christmas break
spring_break_start  YYYY-MM-DD  First day of spring break
spring_break_end    YYYY-MM-DD  Last day of spring break

confidence          verified | high | medium | low | unverified
sources_count       Number of independent sources that agree
primary_source      URL of best source
secondary_source    URL of confirming source
collection_date     When data was last collected
```

### Deliverable: Fact Table
```
date_iso8601    district_code    is_in_session    session_status    confidence_level
2025-08-07      0100189          true             regular           verified
2025-12-22      0100189          false            winter_break      verified
...
```

---

## 3. Collection Tiers

### Tier 0: State DOE Centralized Data
**Coverage:** ~400 districts (6 GOLD states)  
**Accuracy:** 100% (official state submissions)  
**Cost:** Free  
**Method:** Direct download from state education department

| State | Source | Format | Est. Districts |
|-------|--------|--------|----------------|
| Florida | DOE XLSX | Excel (3 sheets) | 67 (county-level) |
| Utah | USBE PDF | Table PDF | 42 |
| Alaska | DOE Portal | HTML per-school | 54 |
| Delaware | DOE PDF | District calendar PDF | 19 |
| South Carolina | DOE Composite | PDF composite | 85 |
| Virginia | DOE Directories | Excel | 132 |

**Sub-tier 0.5: State Portals (SILVER)**  
Alabama (alabamaachieves.org), Illinois (ISBE inquiry), Kentucky (KDE), Colorado (CDE pipeline)  
~800 additional districts, per-district but from official state system.

### Tier 1: PDF-First Targeted Search
**Coverage:** ~4,000 districts (estimated)  
**Accuracy:** 72-85% (from validation tests)  
**Cost:** ~$0.01/district (search API + compute)  
**Method:** Search for district calendar PDF → pdftotext → Claude extraction

Search queries (in priority order):
1. `"{District Name}" {State} 2025-2026 school calendar PDF`
2. `"{District Name}" Schools calendar 2025 2026 filetype:pdf`
3. `site:{district-domain} calendar 2025-2026`

Source priority:
1. PDF from district's own domain (*.k12.*.us, *.edu, district website)
2. PDF from known hosting platforms (Finalsite, Thrillshare, Core-Docs S3, MyConnectSuite)
3. PDF from Google Drive or other cloud hosting
4. HTML calendar page from district website

### Tier 2: Claude-Driven Smart Search
**Coverage:** ~2,000 districts (ones where Tier 1 fails)  
**Accuracy:** 67% precision (from validation tests)  
**Cost:** ~$0.03-0.05/district  
**Method:** Give Claude search + fetch tools, let it reason about source quality

Claude advantages over Python heuristics:
- Can reason about search results ("this is Auburn, not Barbour")
- Can exclude wrong locations ("-georgia" for Thomasville)
- Can try creative search strategies
- Knows to look for nine-weeks tables as anchor dates
- Can cross-reference multiple sources

### Tier 3: Multi-Source Brute Force
**Coverage:** ~2,000 districts (the hard ones)  
**Accuracy:** Depends on source availability  
**Cost:** ~$0.10-0.50/district  
**Method:** Hit EVERY possible source, build consensus

---

## 4. The 16 Sources (Tier 3 Brute Force)

For every district where Tiers 0-2 fail or produce low confidence results, 
we systematically check ALL of the following:

### A. Official Sources
1. **State DOE portal** — check even BRONZE/NONE states for individual district data
2. **District website calendar page** — fetch with Playwright (handles JS rendering)
3. **District website PDF** — search known URL patterns for the hosting platform
4. **Board meeting minutes** — calendar approval is often in board minutes/agendas
5. **District email inquiry** — email the superintendent/board office for verification

### B. Search Engines
6. **Brave Search** — targeted queries with district name + year + calendar
7. **Google (via SerpAPI or similar)** — different index than Brave, may find different results
8. **Bing** — same concept, different index

### C. Social Media & Community
9. **Facebook** — district pages often post calendar images (need OCR for image-based)
10. **Reddit** — `"{District Name}" spring break 2025 site:reddit.com`
11. **Local news / Patch.com** — `"{District Name}" school calendar 2025-2026 site:patch.com`
12. **Parent forums / NextDoor** — parents discuss school dates

### D. Aggregator Cross-Reference
13. **schools-calendar.com** — use as a DATA POINT, not as truth (known errors)
14. **educounty.net** — another aggregator
15. **schooldistrictcalendar.org** — another aggregator
16. **niche.com / greatschools.org** — sometimes have calendar links

### E. Nuclear Options
17. **OCR on calendar images** — for districts that only post image calendars (Facebook, etc.)
18. **Wayback Machine** — check if last year's calendar pattern applies
19. **FOIA/Public Records Request** — for districts with zero online presence
20. **Phone call** — if all else fails, call the district office (could be automated with voice AI)

---

## 5. Triangulation & Consensus Engine

### The Problem
Different sources may report different dates. We need to determine which is correct.

### The Algorithm

For each district, collect dates from all available sources. Then:

```
For each field (first_day, spring_break_start, etc.):
    1. Collect all values from all sources
    2. Group identical values
    3. If 2+ sources agree → HIGH confidence, use consensus value
    4. If all sources agree → VERIFIED confidence
    5. If sources disagree → compare source reliability:
       - State DOE > District PDF > District website > Aggregator > Forum
    6. If only 1 source → MEDIUM confidence (LOW if it's an aggregator)
    7. If 0 sources → NULL (don't fabricate)
```

### Source Reliability Ranking
```
Tier 1 (Most Reliable):
  - State DOE official data
  - District-published PDF with grading period table
  
Tier 2 (Reliable):
  - District website (non-PDF)  
  - Board meeting minutes
  - District email confirmation
  
Tier 3 (Useful for cross-reference):
  - Local news articles
  - Aggregator sites (schools-calendar.com, etc.)
  - Social media posts from official district accounts
  
Tier 4 (Low reliability, good for leads):
  - Reddit/forum posts
  - Parent discussion groups
  - Generic education sites
```

### Anomaly Detection
Flag for manual review when:
- First day is before July 15 or after September 15
- First day is on a weekend
- Spring break is outside Feb 15 - April 30
- Winter break doesn't include Dec 25
- Last day is before April 30 or after June 30
- First day differs from previous year by > 14 days
- Total school days < 160 or > 200

---

## 6. District Profile Database

Every interaction with every district is logged permanently:

```json
{
  "nces_id": "0100189",
  "name": "Satsuma City",
  "state": "AL",
  
  "website": {
    "url": "https://www.satsumaschools.com",
    "platform": "finalsite",
    "calendar_page": "/gatorlife/student-calendar",
    "js_rendered": false,
    "has_pdf": true,
    "pdf_url_pattern": "resources.finalsite.net/.../{filename}.pdf"
  },
  
  "collection_attempts": [
    {
      "date": "2026-03-15",
      "method": "brave_search",
      "query": "\"Satsuma City\" Alabama 2025-2026 calendar PDF",
      "url_found": "https://resources.finalsite.net/...",
      "result": "success",
      "dates_extracted": { ... },
      "verified_against": "manual_review"
    }
  ],
  
  "sources_tried": {
    "state_doe": { "available": false, "tier": "SILVER" },
    "district_pdf": { "found": true, "quality": "high" },
    "district_website": { "js_rendered": false, "calendar_text": false },
    "facebook": { "checked": false },
    "reddit": { "checked": false },
    "aggregators": { "schools_calendar_com": "no_data" },
    "email": { "sent": false }
  },
  
  "characteristics": {
    "calendar_style": "traditional",
    "typical_first_day": "early_august",
    "pdf_naming": "descriptive",
    "year_over_year_consistent": true
  }
}
```

This profile accumulates over collection cycles. By Q3 2026, we know exactly where to find each district's calendar.

---

## 7. Pipeline Execution Plan

### Phase 1: Quick Wins (Week 1)
**Target:** 500 verified districts  
- Collect all GOLD state DOE data (FL, UT, AK, DE, SC, VA) → ~400 districts
- Run Tier 1 PDF search on top 500 largest remaining districts  
- Cross-validate sample against known data

### Phase 2: Broad Coverage (Weeks 2-3)
**Target:** 3,000 verified districts  
- Collect SILVER state portal data (AL, IL, KY, CO)
- Run Tier 1 on all remaining districts with enrollment > 1,000
- Run Tier 2 (Claude search) on Tier 1 failures
- Build consensus from multi-source comparison

### Phase 3: Deep Coverage (Weeks 3-4)
**Target:** 6,000 verified districts  
- Run Tier 2 on all remaining districts
- Add Reddit/forum searches for stubborn districts
- Add Facebook scraping (with OCR for image calendars)
- Add local news search (Patch.com, local papers)

### Phase 4: Completion Push (Weeks 4-6)
**Target:** 8,000+ verified districts  
- Tier 3 brute force on remaining gaps
- Email outreach to districts with no online calendar
- Manual review queue for flagged anomalies
- Cross-reference all data against aggregators for additional validation

### Phase 5: Quality Assurance (Week 6)
- Statistical analysis: date distributions by state
- Outlier detection: flag districts outside expected ranges
- Spot-check: manually verify random 5% sample
- Publish quality report with confidence metrics

---

## 8. Cost Estimates

### Per Collection Cycle (Quarterly)

| Component | Unit Cost | Volume | Total |
|-----------|-----------|--------|-------|
| Brave Search API | $0.005/query | 50,000 queries | $250 |
| Claude Sonnet (extraction) | $0.02/district | 10,000 districts | $200 |
| Claude Sonnet (smart search) | $0.05/district | 3,000 districts | $150 |
| Firecrawl (JS rendering) | $0.01/page | 5,000 pages | $50 |
| OCR processing | $0.01/image | 500 images | $5 |
| Manual review time | $25/hr | 20 hours | $500 |
| **Total per cycle** | | | **~$1,155** |

### Revenue Potential
- 50 states × $1,200/state = $60,000/year
- 4 cycles/year × $1,155 = $4,620/year cost
- **Gross margin: ~92%**

---

## 9. Technology Stack

- **Search:** Brave Search API (primary), Google SerpAPI (secondary)
- **Fetching:** wget/curl for PDFs, Playwright for JS-rendered pages
- **PDF Processing:** pdftotext (poppler), OCR via Tesseract for image PDFs
- **Extraction:** Claude Sonnet 4 via Anthropic API (tool use for smart search)
- **Storage:** JSON profiles database (upgrade to PostgreSQL if needed)
- **Orchestration:** Python pipeline with async workers
- **Monitoring:** Progress tracking, error logging, cost tracking
- **Quality:** Consensus engine, anomaly detection, spot-check automation

---

## 10. Success Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Districts with any data | 95% (9,500) | 32% (3,177) |
| Districts with verified data | 80% (8,000) | 22% (2,220) |
| Overall accuracy (vs spot-check) | >95% | ~72% (Tier 1) |
| Fields per district | 6/6 | varies |
| Collection cycle time | <2 weeks | n/a |
| Cost per cycle | <$1,500 | n/a |

---

## 11. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| District websites change | Sources break | Profile database remembers past sources; check multiple each cycle |
| Aggregator data poisoning | Wrong "consensus" | Weight aggregators lower; always require 1 official source |
| PDF format changes | Extraction fails | Multiple extraction methods; Claude can adapt |
| Rate limiting / blocking | Can't access data | Polite request spacing; rotate user agents; use multiple search engines |
| Small districts with zero web presence | Can't find data | Email outreach; phone verification; FOIA |
| Calendar not yet published | No 2026-2027 data in July | Historical pattern prediction; re-collect when available |

---

## 12. Next Steps

1. ✅ State DOE survey complete (50 states classified)
2. ✅ Florida + Utah collected (124 districts)
3. ✅ Validation framework built (8 AL districts as ground truth)
4. ✅ District profiles database initialized (10,042 profiles)
5. ✅ Methodology documented
6. **→ Build Tier 1 bulk pipeline (PDF-first search + extract)**
7. **→ Build consensus engine**
8. **→ Run Phase 1: GOLD states + top 500 districts**
9. **→ Iterate and expand**

---

*"If you have to try 16 different ways to get at the calendar — do it!"*  
*— Fred Hazelton, 2026-03-15*
