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

## What's Done (24 districts, ~2.6M students)

### TOP 20 COMPLETE (#61-#80):
| Issue | District | State | Enrollment |
|-------|----------|-------|-----------|
| #61 | Broward County | FL | 254K |
| #62 | Fairfax County | VA | 180K |
| #63 | Hawaii DOE | HI | 170K |
| #64 | Montgomery County | MD | 161K |
| #65 | Cypress-Fairbanks ISD | TX | 118K |
| #66 | Cobb County | GA | 107K |
| #67 | Northside ISD | TX | 103K |
| #68 | Lee County | FL | 99K |
| #69 | San Diego Unified | CA | 94K |
| #70 | Katy ISD | TX | 93K |
| #71 | Prince William County | VA | 91K |
| #72 | Davidson County (Nashville) | TN | 81K |
| #73 | Fort Bend ISD | TX | 80K |
| #74 | Greenville 01 | SC | 78K |
| #75 | Jefferson County (Jeffco) | CO | 75K |
| #76 | Osceola | FL | 74K |
| #77 | Davis District | UT | 73K |
| #78 | Milwaukee | WI | 68K |
| #79 | Frisco ISD | TX | 67K |
| #80 | VA Beach City | VA | 65K |

### RE-EXTRACTIONS COMPLETE (#81-#84):
| Issue | District | State | Enrollment | Notes |
|-------|----------|-------|-----------|-------|
| #81 | Philadelphia | PA | 115K | 12 holidays, ~11 half days, calendar AMENDED Mar 2026 |
| #82 | Denver | CO | 88K | 174.5/186 student/teacher days, 6 non-student contact days |
| #83 | Alpine | UT | 87K | Splitting into 3 districts Jul 2027, Wed early release |
| #84 | Loudoun County | VA | 82K | 179/194 student/teacher days, Yom Kippur/Lunar NY/Eid holidays |

## What's Next — Remaining new extractions (#85-#112):
~28 districts, ~1.3M students:
- #85 Long Beach Unified CA — 65K
- #86 Washoe County NV — 64K
- #87 Chesterfield County VA — 64K
- #88 Volusia FL — 63K
- #89 Douglas County CO — 62K
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
- **Virginia**: Teacher + professional workdays, quarter-end early releases, religious holidays
- **Florida**: ~180 days, teacher planning days, hurricane make-up days
- **Georgia**: Digital Learning Days, September fall break
- **California**: Lincoln Day separate, NI days
- **Tennessee**: "Director of Schools" title, October fall break
- **South Carolina**: "Modified year-round," semester before winter break
- **Colorado**: 172-174.5 student / 185-186 teacher days, Non-Student Contact Days
- **Utah**: Fall recess/break, A/B or Wed early release, districts splitting
- **Wisconsin**: Late September start (post-Labor Day)
- **Pennsylvania**: Philadelphia observes most religious/cultural holidays, eliminating half days

## Don't Forget
- Always include `contact` block
- Flag conflicting dates honestly
- Note district context (size, DOI, unusual features)
- Flag image-based PDFs for Wilma
- Update THIS FILE at end of each session
