# NEXT SESSION — Barney SSD Extraction Sprint

**Read this first every session. This is your continuity doc.**

## What You're Doing
You are **Barney** — an AI agent doing gold-standard school calendar extractions for the School Schedules Database (SSD). You search the web for official district calendars, extract every non-school day into structured JSON, and post the extraction as a comment on the corresponding GitHub Issue.

## Repo & Workflow
- **Repo:** `hazeydata/theme-park-crowd-report`
- **Issues:** `#61–#112` with label `SSD-collect` (top 50 missing districts by enrollment)
- **Re-extractions:** `#81–#84` (Denver, Philly, Alpine, Loudoun — partial data, need gold standard)
- **Workflow doc:** `data/school_schedules/SSD_COLLECTION_WORKFLOW.md` — has the JSON format spec and golden rule

## The Golden Rule
**For every single day of the school year (July 1 – June 30), determine whether students are in session or not. No assumptions. No shortcuts. The source calendar is the only truth.**

## What's Done (18 districts, ~2.0M students)

| Issue | District | State | Enrollment | Status |
|-------|----------|-------|-----------|--------|
| #61 | Broward County | FL | 254K | ✅ |
| #62 | Fairfax County | VA | 180K | ✅ |
| #63 | Hawaii DOE | HI | 170K | ✅ |
| #64 | Montgomery County | MD | 161K | ✅ |
| #65 | Cypress-Fairbanks ISD | TX | 118K | ✅ |
| #66 | Cobb County | GA | 107K | ✅ |
| #67 | Northside ISD | TX | 103K | ✅ |
| #68 | Lee County | FL | 99K | ✅ |
| #69 | San Diego Unified | CA | 94K | ✅ (MEDIUM) |
| #70 | Katy ISD | TX | 93K | ✅ |
| #71 | Prince William County | VA | 91K | ✅ |
| #72 | Davidson County (Nashville) | TN | 81K | ✅ |
| #73 | Fort Bend ISD | TX | 80K | ✅ |
| #74 | Greenville 01 | SC | 78K | ✅ |
| #75 | Jefferson County (Jeffco) | CO | 75K | ✅ |
| #76 | Osceola | FL | 74K | ✅ |
| #77 | Davis District | UT | 73K | ✅ |
| #78 | Milwaukee | WI | 68K | ✅ (Sept start!) |

## What's Next (in priority order)

### Continue top-50 new extractions:
1. **#79 Frisco ISD TX** — 67K students
2. **#80 VA Beach City VA** — 65K students
3. Then #85–#112 (Long Beach CA through Portland OR)

### Re-extractions needed (incomplete first-pass data — HIGH VALUE):
- **#81 Philadelphia PA** — 115K — MISSING teacher workdays, half days
- **#82 Denver CO** — 88K — MISSING ~11 teacher-only days
- **#83 Alpine UT** — 87K — MISSING teacher workdays, half days
- **#84 Loudoun County VA** — 82K — MISSING teacher workdays, half days

## How To Extract (step by step)
1. Search for official 2025-2026 calendar
2. Fetch calendar page/PDF for detail
3. Extract into JSON format
4. Search for superintendent contact
5. Post as comment on GitHub issue
6. Move to next issue

## Key Patterns by State
- **Texas ISDs**: DOI = early August start, dual bad-weather/PD days, ~171-177 days
- **Virginia**: Teacher + professional workdays, quarter-end early releases, religious holidays
- **Florida**: ~180 days, teacher planning days, hurricane make-up days
- **Georgia**: Digital Learning Days, September fall break
- **California**: Lincoln Day separate from Presidents Day, NI days
- **Tennessee**: "Director of Schools" title, October fall break
- **South Carolina**: "Modified year-round," semester before winter break
- **Colorado**: 172 student / 185 teacher days, Modified Contact Days
- **Utah**: Fall recess (2 days), A/B rotation, late-start Wednesdays
- **Wisconsin**: Late September start (post-Labor Day), calendar in 9 languages

## Don't Forget
- Always include `contact` block
- Flag conflicting dates honestly
- Note district context (size, DOI, unusual features)
- Flag image-based PDFs for Wilma
- Update THIS FILE at end of each session
