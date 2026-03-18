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

## What's Done (34 districts, ~3.3M students)

### TOP 20 COMPLETE (#61-#80) — see previous sessions
### RE-EXTRACTIONS COMPLETE (#81-#84) — see previous sessions
### NEW EXTRACTIONS (#85-#94):
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
| #94 | Polk County | FL | 117K | LEGOLAND in-county! Disney-adjacent! 10 early dismissals |

## What's Next — Remaining new extractions (#95-#112):
~18 districts, ~0.7M students:
- #95 Brevard FL — 52K (Space Coast)
- #96 Pasco FL — 51K (Tampa metro)
- #97 Seminole FL — 50K (Disney-adjacent!)
- #98 Knox County TN — 50K
- #99 Duval County FL — 49K
- ...through #112 Portland SD 1J OR — 43K

## FL Disney-Adjacent Cluster Status:
- ✅ #68 Lee County FL — 99K (Fort Myers)
- ✅ #76 Osceola FL — 74K (Adjacent to Disney, "Rodeo Day")
- ✅ #88 Volusia County FL — 63K (Daytona, 36 Wed early releases)
- ✅ #94 Polk County FL — 117K (LEGOLAND in-county, Disney-adjacent)
- 🔲 #95 Brevard FL — 52K (Space Coast, next up)
- 🔲 #97 Seminole FL — 50K (Adjacent to Orange County)

## Don't Forget
- Always include `contact` block
- Flag conflicting dates honestly
- Note district context (size, DOI, unusual features)
- Flag image-based PDFs for Wilma
- Update THIS FILE at end of each session
