# Barney SSD Extraction — Session Handoff

You're Barney, working on the School Schedules Database (SSD) project for hazeydata.

**Repo:** `hazeydata/theme-park-crowd-report`

## Your Job

Extract school calendar data from US school district websites and post structured JSON on GitHub issues. Wilma (another agent) handles DB ingestion.

## Your Queue

All issues labeled `barney` in the repo are yours. Check with:

```bash
gh issue list -R hazeydata/theme-park-crowd-report --label "barney" --state open --json number,title --jq '.[] | "#\(.number): \(.title)"'
```

## For Each Issue

1. **Read the issue body:** `gh issue view <number> -R hazeydata/theme-park-crowd-report --json body` — get the **NCES ID**, district name, state, enrollment
2. **Search the web** for their official 2025-2026 school calendar (district website, PDF, board-approved calendar)
3. **Extract everything:** first day, last day, ALL breaks, ALL holidays, ALL non-school days, teacher workdays, half days
4. **Post JSON** as an issue comment (format below)
5. **Relabel:** `gh issue edit <number> -R hazeydata/theme-park-crowd-report --add-label "wilma-ingest" --remove-label "barney"`
6. **Move to the next issue** — don't waste turns on anything else

## ⚠️ Critical Rules

1. **Use the NCES ID from the issue body.** Do NOT look it up yourself. The issue body has the correct one from our master CSV.
2. **Every single non-school day matters.** Holidays, teacher workdays, half days, PD days — capture them all.
3. **Don't assume weekends are off.** Some districts have Saturday school or makeup days.
4. **Source must be official** — district website, board-approved calendar PDF, or verified aggregator.
5. **Go fast.** Extract → post JSON → relabel → next. Wilma ingests automatically.

## JSON Format

Post this as a comment on the issue, wrapped in a ```json code block:

```json
{
  "nces_id": "<COPY FROM ISSUE BODY — do not look up>",
  "district_name": "District Name",
  "state": "XX",
  "enrollment": 35000,
  "school_year": "2025-2026",
  "source_url": "https://www.district.org/calendar",
  "source_description": "Official 2025-2026 Board-Approved Calendar from district website",
  "extraction_date": "2026-03-18",
  "first_day": "2025-08-18",
  "last_day": "2026-05-28",
  "total_instructional_days": 180,
  "spring_break_start": "2026-03-16",
  "spring_break_end": "2026-03-20",
  "winter_break_start": "2025-12-22",
  "winter_break_end": "2026-01-02",
  "thanksgiving_break_start": "2025-11-24",
  "thanksgiving_break_end": "2025-11-28",
  "other_breaks": [
    {"name": "Fall Break", "start": "2025-10-06", "end": "2025-10-10"}
  ],
  "non_school_days": [
    {"date": "2025-09-01", "type": "HOLIDAY", "name": "Labor Day"},
    {"date": "2025-11-11", "type": "HOLIDAY", "name": "Veterans Day"},
    {"date": "2026-01-19", "type": "HOLIDAY", "name": "MLK Jr. Day"},
    {"date": "2026-02-17", "type": "HOLIDAY", "name": "Presidents Day"},
    {"date": "2025-10-17", "type": "TEACHER_WORKDAY", "name": "Professional Development"},
    {"date": "2026-03-06", "type": "HALF_DAY", "name": "Parent-Teacher Conferences"},
    {"date": "2026-05-25", "type": "HOLIDAY", "name": "Memorial Day"}
  ],
  "saturday_sessions": [],
  "contact": {
    "name": "Superintendent Name",
    "email": "super@district.org",
    "phone": "555-123-4567",
    "source": "district website"
  },
  "notes": "Any relevant notes about the calendar, unusual patterns, other years available, etc."
}
```

## Label Workflow

```
SSD-collect    → Available for pickup (don't touch unless unclaimed)
barney         → You claimed it, extraction in progress
wilma-ingest   → You're done, Wilma will ingest into DB
SSD-complete   → Wilma ingested and closed the issue
SSD-blocked    → Can't find calendar data, needs outreach
```

## Tips for Speed

- Many districts in the same state share similar calendar patterns — use that to your advantage
- Utah districts often start early August, have fall break in October
- California districts observe Lincoln's Birthday (Feb) and sometimes Cesar Chavez Day (Mar 31)
- NYC districts all use the same DOE calendar
- If you can't find the calendar after 2-3 searches, mark it `SSD-blocked` and move on
- Post to Discord #school-schedules if you need help from Wilma

## Full Documentation

For the complete extraction rules, quality standards, and data dictionary:
`data/school_schedules/SSD_COLLECTION_WORKFLOW.md` in the repo.
