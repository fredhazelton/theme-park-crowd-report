# SSD District Collection — GitHub Issues Workflow

## Overview

Barney and Wilma coordinate school calendar data collection through GitHub Issues on the `theme-park-crowd-report` repo. This mirrors the ACCORD project workflow where agents communicate through git.

## Labels

| Label | Meaning |
|-------|---------|
| `SSD-collect` | District needs calendar data collected |
| `SSD-extracted` | Barney has posted extraction JSON, awaiting ingestion |
| `SSD-complete` | Data ingested into v3 DB, issue closed |
| `SSD-blocked` | Cannot find calendar data online — needs alternative approach |

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
3. **Any days outside typical boundaries where students ARE in session** (Saturday school, summer bridge programs if applicable)

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
  "notes": "Calendar source is the board-approved instructional calendar. 180 instructional days. Includes 4 teacher-only days and 6 early release days."
}
```

**Key fields:**
- Named break fields (`spring_break_start/end`, etc.) = convenience shortcuts for common breaks
- `other_breaks` = ANY additional multi-day break not covered by the named fields. Use this freely.
- `non_school_days` = EVERY individual non-session day (holidays, teacher days, half days, anything)
- `saturday_sessions` = Any Saturday or Sunday where students ARE in session
- `notes` = Total instructional days from the calendar (for cross-checking), any caveats

## Quality Standard

**Gold standard (required for top 50 districts by enrollment):**
- Source is the official board-approved calendar (not an aggregator site)
- Every non-session day extracted with date, type, and name
- Half days and early release days captured
- Teacher workdays / PD days captured
- Total instructional day count cross-checked against calendar's own stated count
- Notes field documents source and any ambiguities

**Minimum viable (acceptable for smaller districts):**
- Source is an official or reliable aggregator
- First/last day + all multi-day breaks captured
- Major holidays captured
- Teacher workdays captured if visible on calendar
- Half days captured if visible on calendar

**When in doubt, capture it.** An extra entry in `non_school_days` that turns out to be wrong is easy to remove. A missing day is invisible and creates silent errors in the aggregate.

## Issue Template (created by Wilma)

**Title:** `SSD Collect: {District Name} ({State}) — {Enrollment}K students`

**Body includes:**
- NCES ID, state, enrollment, priority tier
- Known URLs (NCES website, Brave scan results, calendar URLs if found)
- Suggested search queries
- Any state-specific notes (e.g., "Louisiana districts typically have Mardi Gras break")

## Workflow

1. **Wilma** creates issues for districts needing collection (label: `SSD-collect`)
2. **Barney** picks up issues, finds the official calendar, reads it exhaustively, posts complete JSON extraction as a comment
3. **Barney** labels `SSD-extracted`
4. **Wilma** ingests into v3 DB, confirms row counts + instructional day count, closes issue (label: `SSD-complete`)
5. If data can't be found: label `SSD-blocked`, document what was tried

## Priority Order

1. Top 50 by enrollment — gold standard extraction
2. Districts 51-200 by enrollment — gold standard
3. Remaining districts — minimum viable
