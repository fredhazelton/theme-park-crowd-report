# School Schedules Database — Pipeline Architecture
## From Calendar Collection to Day-Level Dataset

**Author:** Wilma  
**Last Updated:** 2026-03-17  
**Version:** 2.0  
**Status:** Active — Executing

---

## 1. What We're Building

A day-level school calendar database for every US public school district (~13,000 regular districts + ~4,000 charters). One row per district per day, Aug 1 – Jul 31.

**Database:** `v3/school_schedules.db` (SQLite, star schema)

```
dim_district         → 18,397 NCES districts (id, name, state, enrollment, email, contact)
dim_calendar_source  → one per district per school year (url, method, confidence)
fact_school_day      → ~365 rows per district per year (date, is_in_session, day_type, break_name)
```

**Day types:** SCHOOL_DAY, WEEKEND, BREAK, HOLIDAY, TEACHER_WORKDAY, HALF_DAY, SUMMER  
**Break names:** WINTER, SPRING, FALL, THANKSGIVING, MARDI_GRAS, MLK_DAY, PRESIDENTS_DAY, etc.

---

## 2. Current State (2026-03-18)

| Metric | Count | Notes |
|--------|-------|-------|
| Districts in database | 8,143 | 60.7% of universe |
| Day-level rows | 2,918,905 | 365 × 8,143 |
| Enrollment covered | 22.7M / 46.3M | 49.2% by enrollment |
| States | 51 | All 50 + DC |
| High confidence (v3) | 2,233 | Full calendar, all break types |
| Medium confidence (v1) | 5,910 | Spring + winter only |
| Target | ALL 13,418 | Every non-school day |

### District Universe

| Type | Total | Found | Unfound | Notes |
|------|-------|-------|---------|-------|
| Regular districts | 13,180 | 5,719 (43%) | 7,461 | Primary target |
| Charter schools | 3,774 | 0 (0%) | 3,774 | Hard — minimal web presence |
| Component (supervisory union) | 411 | 200 (49%) | 211 | Share parent calendar |
| Service agencies | 461 | 0 | 461 | Usually no student calendar |
| Specialized / State / Federal | 571 | 13 | 558 | Low priority |
| **TOTAL** | **18,397** | **5,932 (32%)** | **12,465** | |

---

## 3. The Pipeline (v3)

### Architecture

```
 BRAVE SEARCH (find URLs)
        │
        ├──→ PDF found? ──→ Direct download (free)
        │                         │
        ├──→ HTML calendar? ──→ Firecrawl (JS rendering)
        │                         │
        └──→ No results ──→ Email outreach
                                  │
                          ┌───────┘
                          ▼
                 CLAUDE SONNET (extract)
                    "Extract EVERY non-school day"
                          │
                          ▼
                 GENERATE DAYS (expand)
                    Key dates → 365 rows
                          │
                          ▼
                 SQLITE DATABASE (store)
                    v3/school_schedules.db
```

### Extraction Prompt (v3)
Instead of asking for named breaks (spring_break_start, winter_break_end), we ask:
> "Extract EVERY non-school day from this calendar."

Returns structured array:
```json
{
  "non_school_days": [
    {"date": "2025-11-27", "end_date": "2025-11-28", "type": "BREAK", "name": "Thanksgiving"},
    {"date": "2025-12-22", "end_date": "2026-01-02", "type": "BREAK", "name": "Winter Break"},
    {"date": "2026-01-19", "end_date": null, "type": "HOLIDAY", "name": "MLK Day"},
    ...
  ]
}
```

Also captures: `district_email`, `contact_name`, `calendar_type` (traditional/year_round/modified).

### Scripts

| Script | Purpose | Status |
|--------|---------|--------|
| `pipeline_v3.py` | Full scrape pipeline (search → fetch → extract → store) | ✅ Built |
| `v3/generate_days.py` | Expand key dates → day-level rows | ✅ Built |
| `v3/schema.sql` | Database schema | ✅ Built |
| `brave_url_scan.py` | Brave-only URL discovery for unfound districts | ⏳ Running |
| `brave_pdf_hunt.py` | Find PDF versions for already-found districts | ⏳ Running |

### Legacy Scripts (v1/v2 — do not use)
| Script | Notes |
|--------|-------|
| `llm_scraper.py` | v1 scraper. Used Firecrawl. Got 5,919 districts. |
| `pipeline_v2.py` | Added PDF search + tiers. Only extracted spring/winter break. |

---

## 4. Execution Plan

### Phase 1: URL Discovery (NOW — 2026-03-17)
**Status: ⏳ Running**

Two Brave search scans running simultaneously:
- **PDF Hunt:** Find PDF calendar URLs for 5,919 already-found districts (~1.8 hrs, done ~6:45 PM)
- **URL Scan:** Find any calendar URL for 12,465 unfound districts (~3.8 hrs, done ~7 PM)

**Output:** Two JSON files categorizing every district's best URL as:
- 📄 PDF (free download, no Firecrawl)
- 📅 Calendar page (targeted Firecrawl)
- 🏠 Generic/homepage (skip or low priority)
- ❌ No results (email outreach candidates)

### Phase 2: PDF Extraction (Next — 2026-03-18)
**Status: 🔜 Queued**

For every district where Phase 1 found a PDF:
1. Download PDF directly (free)
2. Extract text with pdftotext
3. Run through v3 Claude prompt ("extract ALL non-school days")
4. Generate day-level rows
5. Load into v3 database

**Estimated:** 2,000-3,000 districts upgraded to full calendars. Cost: Anthropic API only (~$60-90).

### Phase 3: Firecrawl Pass (After Phase 2)
**Status: ⏰ Waiting for credits**

For districts where only HTML calendar pages exist (JS-rendered):
1. Fred reviews URL scan results and approves Firecrawl budget
2. Firecrawl renders targeted calendar pages (NOT homepages)
3. Extract with v3 prompt
4. Load into database

**Estimated:** 2,000-3,000 more districts. Cost: Firecrawl credits + Anthropic.

### Phase 4: Email Outreach (After Phase 3)
**Status: 📋 Planned**

For districts with no findable calendar online:
1. Draft professional email template from wilma@hazeydata.ai
2. Request 2025-2026 calendar PDF
3. Track responses
4. Process received calendars through v3 pipeline

### Phase 5: Multi-Year Expansion
**Status: 📋 Future**

Repeat pipeline for:
- 2024-2025 (historical, for model training)
- 2026-2027 (when published, starting summer 2026)

---

## 5. Cost Model

| Component | Unit Cost | Est. Volume | Total |
|-----------|-----------|-------------|-------|
| Brave Search | $0.005/query | ~20,000 | $100 |
| Claude Sonnet (extraction) | ~$0.02/district | ~10,000 | $200 |
| Firecrawl (JS rendering) | $0.01/page | ~3,000 | $30 |
| PDF download | Free | ~3,000 | $0 |
| **Total estimated** | | | **~$330** |

---

## 6. Quality Validation

### Anomaly Detection
Flag for review when:
- First day before Jul 15 or after Sep 15
- First day on weekend
- Spring break outside Feb 15 – Apr 30
- Winter break doesn't include Dec 25
- Last day before Apr 30 or after Jun 30
- < 3 non-school days extracted (likely incomplete)
- Total school days < 160 or > 200

### Confidence Levels
- **HIGH:** PDF from district domain + 5+ non-school days extracted
- **MEDIUM:** Aggregator site or HTML with 3-4 non-school days
- **LOW:** Single source, < 3 non-school days, or aggregator only

---

## 7. Key Decisions Made

1. **Day-level grain** — One row per district per day, not just key dates (2026-03-17)
2. **Star schema** — dim_district + dim_calendar_source + fact_school_day (2026-03-17)
3. **Extract ALL exceptions** — Don't assume holidays, extract everything from calendar (2026-03-17)
4. **Impute summer** — Days between last_day and first_day = SUMMER (2026-03-17)
5. **Weekends** — Always is_in_session=0, day_type=WEEKEND (2026-03-17)
6. **PDF-first** — Direct PDF download > Firecrawl > email outreach (2026-03-17)
7. **Brave before Firecrawl** — Use cheap search to find targeted URLs, don't spray Firecrawl at homepages (2026-03-17)

---

*"If you have to try 16 different ways to get at the calendar — do it!"*  
*— Fred Hazelton, 2026-03-15*
