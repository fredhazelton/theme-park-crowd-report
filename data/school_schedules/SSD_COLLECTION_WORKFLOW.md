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

## Issue Template (created by Wilma)

**Title:** `SSD Collect: {District Name} ({State}) — {Enrollment}K students`

**Body:**
```
## District Info
- **NCES ID:** {nces_id}
- **District:** {district_name}
- **State:** {state}
- **Enrollment:** {enrollment}
- **Priority:** {high/medium/low based on enrollment}

## Known URLs
- NCES Website: {url from NCES data}
- Brave Scan Result: {url if found}
- Calendar URL (if known): {url}

## Search Suggestions
- `"{district_name}" {state} 2025-2026 school calendar`
- `"{district_name}" school calendar PDF 2025-2026`
- `site:{nces_website_domain} calendar`

## Extraction Target (Gold Standard)
- [ ] first_day / last_day
- [ ] winter_break start/end
- [ ] spring_break start/end
- [ ] thanksgiving start/end
- [ ] fall_break start/end (if applicable)
- [ ] Individual holidays (non_school_days)
- [ ] Teacher workdays / PD days
- [ ] Half days

## JSON Format
Post extraction as a comment using this format:
```json
{
  "first_day": "YYYY-MM-DD",
  "last_day": "YYYY-MM-DD",
  "spring_break_start": "YYYY-MM-DD",
  "spring_break_end": "YYYY-MM-DD",
  "winter_break_start": "YYYY-MM-DD",
  "winter_break_end": "YYYY-MM-DD",
  "fall_break_start": null,
  "fall_break_end": null,
  "thanksgiving_break_start": "YYYY-MM-DD",
  "thanksgiving_break_end": "YYYY-MM-DD",
  "other_breaks": [],
  "non_school_days": [
    {"date": "YYYY-MM-DD", "type": "HOLIDAY|TEACHER_WORKDAY|HALF_DAY", "name": "..."}
  ]
}
```
```

## Workflow

1. **Wilma** creates issues for districts needing collection (label: `SSD-collect`)
2. **Barney** picks up issues, searches for calendar data, posts JSON extraction as comment
3. **Barney** adds label `SSD-extracted` and assigns back to Wilma
4. **Wilma** ingests into v3 DB, confirms with row counts, closes issue (label: `SSD-complete`)
5. If data can't be found: label `SSD-blocked`, note what was tried

## Priority Order

1. Top 50 by enrollment — gold standard extraction
2. Districts 51-200 by enrollment — gold standard
3. Remaining districts — minimum viable (breaks only, no teacher workdays)
