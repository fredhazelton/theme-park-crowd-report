# SSD District Collection — GitHub Issues Workflow

## Overview

Barney and Wilma coordinate school calendar data collection through GitHub Issues on the `theme-park-crowd-report` repo, using the same pattern as the ACCORD project.

**Barney operates as a parallel QA / twin collection process.** He independently extracts calendar data for every district via web search, running alongside Wilma's automated pipeline. Where both sources agree, confidence is highest. Where they differ, discrepancies are flagged for review. Over time, Barney's extractions may become the primary source of truth — or at minimum, they validate and fill gaps in the automated pipeline.

Barney is subscription-based (no per-query API costs), so there are no limits on how many districts he can process.

## Labels

| Label | Meaning |
|-------|---------|
| `SSD-collect` | District needs calendar data collected |
| `SSD-extracted` | Barney has posted extraction JSON, awaiting ingestion |
| `SSD-complete` | Data ingested into v3 DB, issue closed |
| `SSD-blocked` | Cannot find calendar data online — needs email outreach or FOIA |

## The Golden Rule

**We are building the most comprehensive school calendar dataset ever assembled. It needs to be worth $15K to a buyer.**

The extraction principle is simple:

> **For every single day of the school year (July 1 – June 30), determine whether students are in session or not. No assumptions. No shortcuts. The source calendar is the only truth.**

This means:
- **Do NOT assume weekends are off.** Some schools have Saturday classes, Saturday makeup days, or Saturday events. If the calendar shows Saturday in session, capture it.
- **Do NOT limit extraction to a pre-defined list of break types.** If a Louisiana district has Mardi Gras break, capture it. If an Ohio district has a random 2-day "fall recess" in November, capture it. If a school closes for a county fair, capture it.
- **Do NOT assume federal holidays are observed.** Some districts don't observe Columbus Day. Some observe Juneteenth, others don't. Some have Diwali, Eid, Lunar New Year. Only record what the calendar actually shows.
- **Capture EVERY non-standard day:** holidays, teacher workdays, professional development, half days, early release, parent conferences, weather makeup days, testing days with modified schedules, literally anything where students are not in normal full-day session.

## What to Extract

For each district, read the **complete official calendar** and extract:

1. **First day of school** and **last day of school** (the boundaries)
2. **Every single day between those boundaries where students are NOT in regular full-day session**, with:
   - The exact date
   - The type: `HOLIDAY`, `BREAK`, `TEACHER_WORKDAY`, `HALF_DAY`
   - The name/reason as stated on the calendar
3. **Any days outside typical boundaries where students ARE in session** (Saturday school, makeup days, summer bridge programs)
4. **District contact information** for follow-up or FOIA requests

The engine will handle the rest:
- Days between first_day and last_day not explicitly marked → `SCHOOL_DAY`
- Days before first_day / after last_day → `SUMMER`
- Weekends are NOT automatically marked — they should come from the calendar. If a weekend day is not marked as in-session, the engine marks it `WEEKEND`.

## JSON Format for Extraction

Post extraction as a GitHub issue comment:

```json
{
  "nces_id": "0622710",
  "district_name": "Los Angeles Unified",
  "state": "CA",
  "enrollment": 426268,
  "school_year": "2025-2026",
  "source_url": "https://...",
  "source_description": "Official 2025-2026 Instructional Calendar PDF from lausd.org",
  "first_day": "2025-08-14",
  "last_day": "2026-06-10",
  "total_instructional_days": 180,
  "spring_break_start": "2026-03-30",
  "spring_break_end": "2026-04-03",
  "winter_break_start": "2025-12-22",
  "winter_break_end": "2026-01-02",
  "thanksgiving_break_start": "2025-11-24",
  "thanksgiving_break_end": "2025-11-28",
  "other_breaks": [
    {"name": "Mardi Gras", "start": "2026-02-16", "end": "2026-02-17"},
    {"name": "Fall Recess", "start": "2025-11-03", "end": "2025-11-04"}
  ],
  "non_school_days": [
    {"date": "2025-09-01", "type": "HOLIDAY", "name": "Labor Day"},
    {"date": "2025-11-07", "type": "TEACHER_WORKDAY", "name": "Professional Development"},
    {"date": "2025-12-12", "type": "HALF_DAY", "name": "End of Quarter - Early Release"},
    {"date": "2026-01-19", "type": "HOLIDAY", "name": "MLK Jr. Day"},
    {"date": "2026-03-06", "type": "HALF_DAY", "name": "Parent-Teacher Conferences"}
  ],
  "saturday_sessions": [
    {"date": "2026-03-14", "name": "Saturday Makeup Day"}
  ],
  "contact": {
    "name": "Dr. Jane Smith, Superintendent",
    "email": "jsmith@lausd.net",
    "phone": "(213) 241-1000",
    "source": "district website contact page"
  },
  "notes": "Calendar source is the board-approved instructional calendar. 180 instructional days stated on calendar. Includes 4 teacher-only days and 6 early release days."
}
```

**Key fields:**
- Named break fields (`spring_break_start/end`, etc.) = convenience shortcuts for common breaks
- `other_breaks` = ANY additional multi-day break not covered by the named fields. Use this freely.
- `non_school_days` = EVERY individual non-session day (holidays, teacher days, half days, anything)
- `saturday_sessions` = Any Saturday or Sunday where students ARE in session
- `total_instructional_days` = The calendar's own stated instructional day count (for cross-checking)
- `contact` = District contact info for email outreach or FOIA if calendar can't be found
- `notes` = Source description, caveats, ambiguities

## Quality Standard

**Gold standard (required for top 200 districts by enrollment):**
- Source is the official board-approved calendar (not an aggregator site)
- Every non-session day extracted with date, type, and name
- Half days and early release days captured
- Teacher workdays / PD days captured
- Total instructional day count cross-checked against calendar's own stated count
- Contact info captured (superintendent name + email at minimum)
- Notes field documents source and any ambiguities

**Minimum viable (acceptable for smaller districts):**
- Source is an official or reliable aggregator
- First/last day + all multi-day breaks captured
- Major holidays captured
- Teacher workdays captured if visible on calendar
- Half days captured if visible on calendar
- Contact info captured if readily available

**When in doubt, capture it.** An extra entry in `non_school_days` that turns out to be wrong is easy to remove. A missing day is invisible and creates silent errors in the aggregate.

## Twin Collection / QA Process

Barney's extractions run as an independent QA layer alongside Wilma's automated pipeline:

| Scenario | Action |
|----------|--------|
| Both Barney and Wilma agree on dates | ✅ Highest confidence — mark as `confirmed` |
| Barney finds days Wilma missed | Barney's data fills the gap |
| Wilma has data Barney can't find | Use Wilma's data, flag for future verification |
| Both disagree on a date | Flag for manual review by Fred |
| Neither can find calendar data | Use contact info to email district or file FOIA |

**Validation check:** For each district, count SCHOOL_DAY rows between first_day and last_day. If the count is significantly higher than the calendar's stated instructional days (e.g., 195 vs 180), there are likely missing non-school days in the data.

## Issue Creation (Wilma's job)

**Title:** `SSD Collect: {District Name} ({State}) — {Enrollment}K students`

**Body includes:**
- NCES ID, state, city, enrollment, priority tier
- Known URLs (NCES website, Brave scan results, calendar URLs if found)
- Suggested search queries
- State-specific notes (e.g., "Louisiana districts typically have Mardi Gras break")
- Whether Wilma's pipeline already has data for this district (and what's missing)

**Scale:** Issues should be created for ALL 13,418 districts in the universe, batched by state or enrollment tier. Barney works through them systematically.

## Workflow

1. **Wilma** batch-creates issues for all districts (label: `SSD-collect`)
2. **Barney** picks up issues in priority order, finds the official calendar, reads it exhaustively, captures contact info, posts complete JSON extraction as a comment
3. **Barney** labels `SSD-extracted`
4. **Wilma** ingests into v3 DB, compares against her pipeline data, confirms row counts + instructional day count, closes issue (label: `SSD-complete`)
5. If data can't be found: label `SSD-blocked`, document what was tried, use contact info for email outreach

## Priority Order

1. Top 50 by enrollment — gold standard extraction (these alone = ~40% of total enrollment)
2. Districts 51-200 by enrollment — gold standard
3. Districts 201-1000 — gold standard where possible, minimum viable otherwise
4. Remaining ~12,400 districts — minimum viable, batched by state
