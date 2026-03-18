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

## What's Done (33 districts, ~3.2M students)

### TOP 20 COMPLETE (#61-#80) — see previous sessions
### RE-EXTRACTIONS COMPLETE (#81-#84) — see previous sessions
### NEW EXTRACTIONS (#85-#93):
| Issue | District | State | Enrollment | Notes |
|-------|----------|-------|-----------|-------|
| #85 | Long Beach Unified | CA | 65K | Lincoln Day + Admission Day, supt retiring |
| #86 | Washoe County | NV | 64K | Balanced calendar, 2wk fall intersession, supt retiring |
| #87 | Chesterfield County | VA | 64K | REVISED (snow make-up), Presidents Day canceled |
| #88 | Volusia County | FL | 63K | 36 Wed early releases, hurricane days, 2025 Supt of Year |
| #89 | Douglas County | CO | 62K | ~173 days, Compensation Days, full-week fall break |
| #90 | Granite District | UT | 61K | 177/189 student/teacher days, 4-term, A/B rotation |
| #91 | Jordan District | UT | 59K | 180 days, full-week fall recess, Health & Wellness Virtual Day |
| #92 | NYC District #31 | NY | 57K | NYC DOE calendar — 12+ holidays, Diwali, Midwinter Recess |
| #93 | NYC District #2 | NY | 54K | Same NYC DOE calendar — batch extracted with #92 |

## What's Next — Remaining new extractions (#94-#112):
~19 districts, ~0.8M students:
- #94 Polk County FL — 53K (Disney-adjacent!)
- #95 Brevard FL — 52K
- #96 Pasco FL — 51K
- #97 Seminole FL — 50K (Disney-adjacent!)
- #98 Knox County TN — 50K
- #99 Duval County FL — 49K
- ...through #112 Portland SD 1J OR — 43K

## Key Patterns by State
- **New York**: NYC DOE post-Labor Day start (Sep 4), latest start we've seen. 12+ holidays incl. Diwali, Rosh Hashanah×2, Yom Kippur, Lunar New Year, Eid×2. Midwinter Recess (full week Feb). Spring Recess 7 school days (Passover+Easter). Snow days = remote learning.
- **Texas ISDs**: DOI = early Aug, bad-weather/PD days, ~171-177 days
- **Virginia**: Teacher workdays, quarter-end early releases, snow make-up revisions
- **Florida**: ~180 days, hurricane days, Wednesday early releases
- **California**: Lincoln Day + Washington Day separate, Admission Day, Juneteenth
- **Colorado**: 172-174.5 student / 185-186 teacher days
- **Utah**: Fall recess (2 days to full week), 177-180 student days

## Don't Forget
- Always include `contact` block
- Flag conflicting dates honestly
- Note district context (size, DOI, unusual features)
- Flag image-based PDFs for Wilma
- Update THIS FILE at end of each session
