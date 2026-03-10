# School Calendar Data — Full Confirmation Plan

**Author:** Barney (Chief of Pipeline)  
**Date:** 2026-03-08  
**Goal:** Move from 38.5% confirmed → 90%+ confirmed by enrollment  
**Budget:** Up to $3,000 (Firecrawl Standard plan + compute)  
**Timeline:** 2-3 weeks  
**Operator:** Wilma + Bam-Bam

---

## Why Do This

The current dataset has 13,418 districts but only 664 are confirmed (38.5% of enrollment). The other 12,749 are inferred from state medians. This was the right call for speed — but for a $25K+ enterprise product, buyers will ask: "How much of this is real data vs estimates?"

The answer right now is embarrassing: 61.5% estimated.

The answer after this plan: **<10% estimated.** That's the difference between a data product and a guess with a spreadsheet.

---

## The Math

**Current state:**
- 664 confirmed districts → 38.5% of enrollment (~17.9M students)
- 12,749 inferred districts → 61.5% of enrollment (~28.5M students)
- 5 uncovered → <0.01%

**Target state:**
- ~5,000+ confirmed districts → ~85-90% of enrollment (~42M students)
- ~8,000 inferred (small districts) → ~10% of enrollment (~4.6M students)
- The remaining inferred districts are all <5,000 enrollment each

**Why 5,000 is enough:** Districts follow a power law. The top 500 districts have ~50% of all enrollment. The top 2,000 have ~75%. The top 5,000 have ~90%. The remaining 8,000+ districts average ~500 students each — their individual calendars barely move the aggregate needle.

---

## Execution Plan

### Phase A: Extend schoolcalendarinfo.com (FREE, 1 day)

We already scraped 615 districts from this site. But many pages have multiple years and we may have missed districts that use non-standard formatting (bullet lists instead of tables).

**Action:**
1. Re-crawl the full sitemap with a more permissive parser
2. Try alternate URL patterns (some districts have multiple pages)
3. Parse bullet-list format pages that the original scraper skipped

**Expected yield:** 50-100 additional confirmed districts (FREE)

### Phase B: State DOE Bulk Sources (FREE-LOW COST, 1 week)

Several states publish district-level calendar data centrally. These are gold mines that Wilma identified in the state DOE research but didn't fully exploit.

**Priority states (by enrollment × gap):**

| State | Total Enrollment | Currently Confirmed | Gap | Approach |
|-------|-----------------|--------------------|----|----------|
| **Texas** | 5.11M | 46 districts (37%) | 63% | TEA publishes school start/end dates. Scrape TEA site. |
| **California** | 5.27M | 51 districts (35%) | 65% | CDE has a district directory. Variable calendars but worth trying. |
| **New York** | 2.31M | NYC + 15 others (~45%) | 55% | NYSED may have central data. 32 NYC districts already confirmed. |
| **Illinois** | 1.85M | 4 districts (8%) | 92% | ISBE has district profiles. Major gap. |
| **Pennsylvania** | 1.50M | 14 districts (17%) | 83% | PDE has district info. Major gap. |
| **Ohio** | 1.53M | 28 districts (30%) | 70% | ODE has detailed district data. |
| **Georgia** | 1.71M | 44 districts (70%) | 30% | Already strong. Fill remaining county districts. |
| **Michigan** | 1.22M | 16 districts (22%) | 78% | Post-Labor Day mandate makes inference accurate, but confirm anyway. |
| **New Jersey** | 1.26M | 22 districts (17%) | 83% | NJDOE has district calendars. Major gap. |
| **Florida** | 2.85M | 32 districts (92%) | 8% | Already strong. 67 county districts total — close the gap. |

**Action:** Wilma researches each state DOE for bulk calendar downloads or structured calendar pages. For states with centralized data, scrape it. For states without, move to Phase C.

**Expected yield:** 500-2,000 additional confirmed districts depending on state DOE quality

### Phase C: Firecrawl Batch Extraction ($1,500-$3,000, 1-2 weeks)

For the remaining high-enrollment uncovered districts, use Firecrawl's Extract API to pull calendar data from official district websites.

**Strategy:**
1. Sort all uncovered districts by enrollment (descending)
2. For each district, Firecrawl extracts from the district's official website
3. Use a structured schema to pull: first_day, last_day, spring_break_start/end, winter_break_start/end
4. Validate extracted dates against state patterns (sanity check)

**Cost calculation:**
- Firecrawl Standard plan: $99/month for 100,000 credits
- Extract costs ~24 credits per district
- 100K credits ÷ 24 = ~4,166 districts per month
- At $99/month, that's $0.024 per district
- For 5,000 districts: ~$120 (1 month of Standard)
- For 10,000 districts: ~$240 (3 months of Standard) or $198 (2 months)

Wait — that's WAY cheaper than $3,000. The original $3,000 estimate in RESEARCH.md was based on the old Hobby plan pricing (3,000 credits/month). The Standard plan at $99/month with 100K credits changes the economics completely.

**Revised cost:** ~$200-$300 for Standard plan + compute time

**However:** The real cost is engineering time. Each district website is different. Firecrawl handles the scraping, but:
- Some sites will return garbage (JS calendars, PDF-only)
- Some sites will block the scraper
- Date extraction needs validation
- Estimated success rate: 60-70%

**Expected yield:** 2,000-3,500 additional confirmed districts

### Phase D: Firecrawl + LLM Post-Processing ($500-$1,000)

For districts where Firecrawl returns raw HTML/text but not clean dates, use Claude API to extract structured calendar data from the raw content.

**Pipeline:**
1. Firecrawl scrapes district website → raw HTML/text
2. Claude API extracts: first_day, last_day, spring_break, winter_break dates
3. Validation: dates must fall within expected ranges for the state
4. Save with confidence: "confirmed" (if from official district site)

**Cost:** ~$0.01-0.05 per district for Claude API calls (Haiku for extraction)
- 5,000 districts × $0.03 = ~$150

**Expected yield:** 500-1,000 additional districts from Phase C failures

### Phase E: Manual Verification for Top 100 Theme Park Feeder Districts ($0, 2-3 hours)

For the top 100 districts that feed Orlando, Anaheim, and other major theme park markets, manually verify every calendar date against the official district website.

**These are the districts enterprise buyers will check first.** If Disney asks "What's Orange County FL's spring break?" and we're wrong, we lose the deal.

**Feeder district criteria:**
- Top 50 districts within 500 miles of Walt Disney World
- Top 25 districts within 500 miles of Disneyland
- Top 25 districts within 500 miles of Universal Orlando

Many of these overlap (Florida districts feed both WDW and Universal), so ~75 unique districts.

**Action:** Manual human verification. Fred or an assistant opens each district's official calendar PDF/page and confirms all dates match our dataset.

---

## Projected Results

| Phase | Districts Added | Enrollment Added | Cost | Time |
|-------|----------------|-----------------|------|------|
| A: Extend scraper | 50-100 | ~500K | $0 | 1 day |
| B: State DOE bulk | 500-2,000 | ~8-15M | $0-50 | 1 week |
| C: Firecrawl batch | 2,000-3,500 | ~8-12M | $200-300 | 1-2 weeks |
| D: LLM post-process | 500-1,000 | ~2-4M | $150 | 2-3 days |
| E: Manual top feeders | 75 (verification) | ~3M | $0 | 3 hours |
| **Total** | **~3,000-6,500** | **~19-35M** | **$350-500** | **2-3 weeks** |

**After all phases:**
- Confirmed: ~4,000-7,000 districts → 75-90% of enrollment
- Inferred: ~6,000-9,000 districts (all <5K enrollment) → 10-25% of enrollment
- The daily aggregate national numbers barely change (inference was already accurate at the aggregate level)
- But every large district a buyer would check is individually verified

---

## Implementation: Firecrawl Batch Scraper

Wilma/Bam-Bam should build `firecrawl_batch_scraper.py` with this architecture:

```python
# Pseudocode for the batch scraper

# 1. Load uncovered districts sorted by enrollment
uncovered = load_districts_without_confirmed_data()
uncovered.sort(by='enrollment', descending=True)

# 2. For each district, find their website
# NCES CCD has district website URLs in the directory data
# Alternatively, search "{district_name} {state} school calendar 2025-2026"

# 3. Firecrawl extract with schema
schema = {
    "first_day_of_school": "date",
    "last_day_of_school": "date",
    "spring_break_start": "date",
    "spring_break_end": "date",
    "winter_break_start": "date",
    "winter_break_end": "date",
}

for district in uncovered:
    url = district.website or search_for_calendar_url(district)
    result = firecrawl.extract(url, schema=schema)
    if result and validate_dates(result, district.state):
        save_confirmed(district, result)
    else:
        # Fallback: get raw content, send to Claude for extraction
        raw = firecrawl.scrape(url)
        result = claude_extract_dates(raw.text, district.name, district.state)
        if result and validate_dates(result, district.state):
            save_confirmed(district, result, confidence='high')

# 4. Validate all results
# - Spring break must be Feb-May
# - Winter break must be Nov-Jan  
# - First day must be Jul-Sep
# - Last day must be May-Jun
# - Duration checks (school year 160-200 days)
```

**Key detail:** NCES CCD includes district website URLs. We should download the full CCD directory data which has `WEBSITE` field for most districts. This eliminates the need to search for each district's site.

---

## District Website URLs from NCES

The NCES CCD Local Education Agency (LEA) universe file includes a `WEBSITE` field with the district's official URL. This is available from:
- https://nces.ed.gov/ccd/files.asp (annual CCD files)
- The ElSi Table Generator (includes website URLs as a selectable field)

**Action for Wilma:** Download the CCD LEA universe file for 2023-24. It includes:
- LEAID, LEA_NAME, STATE, CITY, ENROLLMENT
- **WEBSITE** — the district's official URL
- This gives us a direct URL to start Firecrawl from for each district

From the NCES website URL, we can:
1. Try `{url}/calendar` or `{url}/calendars`
2. Try Firecrawl extract on `{url}/*` (crawl the whole site for calendar data)
3. If that fails, search Firecrawl for `"{district_name}" school calendar 2025-2026`

---

## Success Criteria

| Metric | Current | Target | How to Verify |
|--------|---------|--------|---------------|
| Confirmed districts | 664 | 4,000+ | Count rows where confidence='confirmed' |
| Confirmed enrollment % | 38.5% | 85%+ | Sum enrollment for confirmed rows ÷ total |
| Top 100 feeder districts verified | ~80 | 100 | Manual check against official calendars |
| Spring break accuracy (confirmed) | ±0-1 days | ±0-1 days | Spot check 50 random confirmed districts |
| Spring break accuracy (inferred) | ±3-7 days | ±3-7 days | Compare against any newly confirmed data |
| Daily aggregate national accuracy | ±2% | ±1% | More confirmed data tightens the aggregate |

---

## Order of Operations for Wilma

1. **Download NCES CCD LEA universe file** (2023-24) with WEBSITE field
2. **Update enrollment_by_district.csv** with 2023-24 data
3. **Re-run Phase A** (extend schoolcalendarinfo.com scraper)
4. **Run Phase B** (state DOE bulk sources — TX, IL, PA, OH, NJ, MI first)
5. **Sign up for Firecrawl Standard** ($99/month)
6. **Build and run Phase C** (batch Firecrawl extraction, top 5,000 uncovered by enrollment)
7. **Run Phase D** (Claude post-processing for Phase C failures)
8. **Run Phase E** (manual verification of top feeder districts)
9. **Re-run build_comprehensive.py** with all new confirmed data
10. **Re-run build_daily_calendar_v3.py** to produce updated aggregate
11. **Barney reviews output, merges to main**

---

## Why This Changes the Sales Conversation

**Before:**
> "We have 13,418 districts but 61% are estimated from state patterns."
> Enterprise buyer: "So you're guessing for most of the data?"

**After:**
> "We have 13,418 districts. 85% by enrollment are individually confirmed from district calendars. The remaining 15% are small districts (<5K students) where we use state-level patterns — these are the districts that don't meaningfully move the aggregate."
> Enterprise buyer: "Show me Orange County, FL."
> You: "Confirmed. Spring break March 16-20. Verified against ocps.net."

That's the difference between a $5K sale and a $50K sale.

---

*Budget: ~$350-500 total. Timeline: 2-3 weeks. ROI: first enterprise sale pays for it 50x over.*

🪨 Barney
