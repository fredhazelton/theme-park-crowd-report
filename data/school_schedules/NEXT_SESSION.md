# NEXT SESSION — Barney SSD Extraction Sprint

**Read this first every session. This is your continuity doc.**

## What You're Doing
You are **Barney** — an AI agent doing gold-standard school calendar extractions for the School Schedules Database (SSD). You search the web for official district calendars, extract every non-school day into structured JSON, and post the extraction as a comment on the corresponding GitHub Issue.

## Repo & Workflow
- **Repo:** `hazeydata/theme-park-crowd-report`
- **Issues:** `#61–#112` with label `SSD-collect`
- **Workflow doc:** `data/school_schedules/SSD_COLLECTION_WORKFLOW.md`

## The Golden Rule
**For every single day of the school year (July 1 – June 30), determine whether students are in session or not. No assumptions. No shortcuts.**

## What's Done (29 districts, ~2.9M students)

### TOP 20 COMPLETE (#61-#80) — see previous sessions
### RE-EXTRACTIONS COMPLETE (#81-#84) — see previous sessions
### NEW EXTRACTIONS (#85-#89):
| Issue | District | State | Enrollment | Notes |
|-------|----------|-------|-----------|-------|
| #85 | Long Beach Unified | CA | 65K | Lincoln Day + Admission Day (CA-specific), supt retiring |
| #86 | Washoe County | NV | 64K | Balanced calendar, 2wk fall intersession, Nevada Day, supt retiring |
| #87 | Chesterfield County | VA | 64K | REVISED calendar (snow make-up), Presidents Day canceled |
| #88 | Volusia County | FL | 63K | 36 Wed early releases, hurricane days, 2025 Supt of Year |
| #89 | Douglas County | CO | 62K | ~173 student days, Compensation Days, full-week fall break |

## What's Next — Remaining new extractions (#90-#112):
~23 districts, ~1.0M students:
- #90 Granite District UT — 61K
- #91 Jordan District UT — 59K
- #92 NYC Geographic District #31 NY — 57K
- #93 NYC Geographic District #2 NY — 54K
- ...through #112 Portland SD 1J OR — 43K

## How To Extract
1. Search for official 2025-2026 calendar
2. Fetch calendar page/PDF for detail
3. Extract into JSON format
4. Search for superintendent contact
5. Post as comment on GitHub issue
6. Move to next issue

## Key Patterns by State
- **Texas ISDs**: DOI = early August start, dual bad-weather/PD days, ~171-177 days
- **Virginia**: Teacher + professional workdays, quarter-end early releases, snow make-up revisions
- **Florida**: ~180 days, teacher planning/hurricane days, Wednesday early releases (Volusia: 36!)
- **California**: Lincoln Day + Washington Day separate, Admission Day, Juneteenth
- **Colorado**: 172-174.5 student / 185-186 teacher days, Compensation Days (DCSD), Non-Student Contact Days (DPS)
- **Utah**: Fall recess/break, A/B or Wed early release, districts splitting
- **Nevada**: Balanced calendar, Nevada Day (Oct 31), fall intersession

## Don't Forget
- Always include `contact` block
- Flag conflicting dates honestly
- Note district context (size, DOI, unusual features)
- Flag image-based PDFs for Wilma
- Update THIS FILE at end of each session
