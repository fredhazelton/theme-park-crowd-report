# School Calendar Intelligence — Data Methodology

**Product:** hazeydata.ai School Calendar Dataset  
**Version:** 3.0  
**Last Updated:** 2026-03-08  
**Reviewed by:** Barney (Chief of Pipeline)

---

## Overview

This document describes how the school calendar dataset is built, what confidence levels mean, and what limitations buyers should understand. This is the document you share with enterprise customers during due diligence.

---

## Data Pipeline

### Step 1: Enrollment Base (NCES)

We start with the official NCES Common Core of Data (CCD) enrollment figures. The CCD covers all ~18,000 US public school districts.

- **Source:** NCES CCD via ArcGIS Open Data (school-level, aggregated to district)
- **School Year:** 2022-23 (latest available at time of collection; 2023-24 data should be substituted when the pipeline is re-run)
- **Total US public school enrollment (NCES, fall 2023):** 49.5 million students
- **Our dataset enrollment:** 46.4 million students (93.7% of the 2022-23 base)
- **Matching:** Districts matched to NCES LEAIDs via fuzzy name+state matching (SequenceMatcher), with 13 manual corrections for ambiguous names

**Known limitation:** Enrollment figures are from 2022-23. NCES published 2023-24 data in December 2024. Updating to 2023-24 enrollment is a priority for the next pipeline run.

### Step 2: Calendar Collection (Multi-Source)

Calendar dates are collected from multiple sources, each tagged with a confidence level:

| Source | Districts | Enrollment % | Confidence | Method |
|--------|----------|-------------|------------|--------|
| schoolcalendarinfo.com | 615 | 34.4% | **confirmed** | Automated scraping of structured HTML tables |
| NYC DOE Calendar | 32 | 1.7% | **confirmed** | All NYC geographic districts follow the single DOE calendar |
| Tavily Search (official district sites) | 17 | 1.2% | **high** | AI-assisted extraction from official district websites |
| State-level inference | 12,749 | 56.1% | **medium** or **inferred** | See Step 3 below |
| Not covered | 5 | <0.01% | **none** | Likely closed/reorganized districts |

**What "confirmed" means:** The calendar dates come from a source that publishes the specific district's calendar (either schoolcalendarinfo.com, which aggregates from official calendars, or the district's own website). The dates have been parsed programmatically and are individually verifiable.

**What "high" means:** Dates come from the district's official website via AI-assisted extraction. Accuracy is high but not cross-referenced against a second source.

**What "medium" means:** The district's calendar was inferred from the state median of confirmed districts (10+ confirmed districts in the same state). For most states, districts cluster tightly around the state median (±1 week for spring break, ±3 days for first/last day). This is the most common tier (56.1% of enrollment).

**What "inferred" means:** The district is in a state with fewer than 3 confirmed districts. Calendar dates are based on state DOE rules (mandated start dates, minimum instruction days) combined with regional patterns. This is the lowest confidence tier and should be used with caution for district-level queries.

### Step 3: State-Level Inference Methodology

For the ~12,700 districts without direct calendar data:

1. **Compute state medians:** For each state with 10+ confirmed districts, calculate the median first_day, last_day, spring_break_start, spring_break_end, winter_break_start, winter_break_end, and summer_start dates.

2. **Apply state DOE rules:** Overlay known legal requirements:
   - 6 states mandate post-Labor Day start (VA, MI, MN, WI, MD, IA)
   - 5 states have early starts (Jul/Aug): AZ, HI, GA, TN, MS
   - All states require 160-185+ instructional days
   - States with mandated spring break timing (e.g., Easter-anchored)

3. **Assign dates:** Each inferred district receives the state median dates for all calendar fields.

4. **Assign confidence:**
   - `medium` if state has 10+ confirmed districts (high statistical confidence in the median)
   - `inferred` if state has <10 confirmed districts (lower confidence)

**Why this works for aggregate analysis:** At the national or state level, the inferred districts contribute to the enrollment-weighted average. Because most districts within a state share similar calendar patterns, the aggregate error is small (estimated ±2% on the daily "% on break" metric). At the individual district level, inferred dates may be off by ±1 week.

### Step 4: Daily Aggregate Calculation

The daily aggregate (`daily_aggregate_v3.csv`) is the primary product output. For each day of the school year:

1. **For each district:** Determine if students are in session or on break based on the district's calendar fields (first_day, last_day, spring_break, winter_break, summer dates).

2. **Enrollment weighting:** Multiply each district's status by its enrollment to get weighted student counts.

3. **Holiday overlay:** Federal/common holidays are applied universally:
   - Labor Day, Columbus Day, Veterans Day, Thanksgiving (Thu+Fri), MLK Day, Presidents Day, Memorial Day
   - Christmas Day, New Year's Day

4. **Weekend handling:** All Saturdays and Sundays show 0 students in session.

5. **Fall break modeling (v3 new):** Districts in states with known fall break patterns (TN, GA, parts of TX, IN, KY) are modeled with a 1-week October break. This affects ~8-12% of enrollment during peak fall break week.

6. **Thanksgiving week modeling (v3 new):** Instead of treating only Thu-Fri as Thanksgiving break, the model applies a ramp: ~40% of districts take the full week (Mon-Fri), ~30% take Wed-Fri, and ~30% take only Thu-Fri. This produces a realistic ramp from ~20% on break Monday to 100% on Thursday.

7. **Primary reason assignment (v3 fix):** The `primary_reason` column reflects the dominant reason for the day's status:
   - If >50% of students are on break: the break type (summer_break, spring_break, winter_break, fall_break, thanksgiving)
   - If >50% of students are in session: `in_session`
   - Weekends: `weekend`
   - Federal holidays: the holiday name

8. **Confidence weighting (v3 new):** The daily aggregate includes a `pct_confirmed` column showing what percentage of the day's on-break count comes from confirmed/high-confidence districts vs inferred districts. This lets buyers assess data quality for any specific date.

---

## Known Limitations

1. **61.5% of enrollment is inferred, not confirmed.** The aggregate metrics are robust (state medians are accurate), but individual district lookups for inferred districts should be treated as estimates.

2. **No private schools.** The dataset covers public school districts only. Private and parochial schools represent ~10% of US students (~5.5M). This is a roadmap item.

3. **No year-round school detection.** Some districts (especially in California) operate year-round or multi-track calendars. These are modeled as traditional calendars, which may undercount summer enrollment.

4. **Enrollment data is 2022-23.** Should be updated to 2023-24 when the pipeline is re-run.

5. **schoolcalendarinfo.com is not an official source.** It aggregates from official calendars but may contain transcription errors. For the top 100 districts, we cross-referenced against official district websites.

6. **Fall break coverage is approximate.** Not all states/districts with fall breaks are captured. The modeling uses known state-level patterns but may miss individual district variations.

---

## Validation

### Cross-Reference Checks
- Top 100 districts: Cross-referenced against official district websites (100% match)
- Spring break dates: Validated against known regional patterns (Southern states early March, Northeast late March/April)
- Winter break: 99% of districts within the expected Dec 18-Jan 6 range
- Summer dates: All districts show first_day between Jul 14 and Sep 15, last_day between May 15 and Jun 30

### Sanity Checks Applied
- Spring break must fall in Feb-May
- Winter break must fall in Nov-Jan
- Spring break duration: 4-14 days (outliers flagged)
- Winter break duration: 7-21 days (outliers flagged)
- School year length: 160-200 instructional days

### Year-Over-Year Stability
For 265 districts with both 2024-25 and 2025-26 data: spring break dates shift by 0-1 weeks year-over-year, confirming the stability assumption used for state-level inference.

---

## Update Cadence

- **June-August:** Full annual refresh for upcoming school year
- **October:** Mid-year validation (check for calendar amendments)
- **January:** Winter corrections (snow day adjustments)
- **Pipeline runtime:** <24 hours for full 13,418-district refresh

---

*This methodology document is versioned alongside the data. Any changes to collection methods or inference logic will be reflected here.*
