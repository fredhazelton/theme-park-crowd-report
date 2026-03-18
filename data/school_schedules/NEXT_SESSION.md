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

## What's Done (16 districts, ~1.86M students)

| Issue | District | State | Enrollment | Status |
|-------|----------|-------|-----------|--------|
| #61 | Broward County | FL | 254K | ✅ Posted |
| #62 | Fairfax County | VA | 180K | ✅ Posted |
| #63 | Hawaii DOE | HI | 170K | ✅ Posted |
| #64 | Montgomery County | MD | 161K | ✅ Posted |
| #65 | Cypress-Fairbanks ISD | TX | 118K | ✅ Posted |
| #66 | Cobb County | GA | 107K | ✅ Posted |
| #67 | Northside ISD | TX | 103K | ✅ Posted |
| #68 | Lee County | FL | 99K | ✅ Posted |
| #69 | San Diego Unified | CA | 94K | ✅ Posted (MEDIUM — conflicting first-day dates) |
| #70 | Katy ISD | TX | 93K | ✅ Posted |
| #71 | Prince William County | VA | 91K | ✅ Posted (revised calendar — added Eid al-Adha) |
| #72 | Davidson County (Nashville) | TN | 81K | ✅ Posted |
| #73 | Fort Bend ISD | TX | 80K | ✅ Posted |
| #74 | Greenville 01 | SC | 78K | ✅ Posted |
| #75 | Jefferson County (Jeffco) | CO | 75K | ✅ Posted |
| #76 | Osceola | FL | 74K | ✅ Posted (Rodeo Day! Adjacent to Disney) |

## What's Next (in priority order)

### Continue top-50 new extractions:
1. **#77 Davis District UT** — 73K students
2. **#78 Milwaukee WI** — 68K students
3. **#79 Frisco ISD TX** — 67K students
4. **#80 VA Beach City VA** — 65K students
5. Then #85–#112 (Long Beach CA through Portland OR)

### Re-extractions needed (incomplete first-pass data):
- **#81 Philadelphia PA** — 115K — has breaks+holidays but MISSING teacher workdays, half days (Philly has half-days on 2nd+3rd Friday monthly)
- **#82 Denver CO** — 88K — has breaks+4 holidays but MISSING ~11 teacher-only days
- **#83 Alpine UT** — 87K — has breaks+2 holidays but MISSING teacher workdays, half days
- **#84 Loudoun County VA** — 82K — has breaks+5 holidays but MISSING teacher workdays, half days

## How To Extract (step by step)

1. **Search** for the district's official 2025-2026 calendar: `"[District Name]" 2025-2026 school calendar`
2. **Fetch** the official calendar page or PDF if needed for detail
3. **Extract** into the JSON format (see below)
4. **Search** for superintendent name, email, phone
5. **Post** as a comment on the GitHub issue using `github:add_issue_comment`
6. **Move to next issue**

Target pace: ~8-10 minutes per district, 3-6 districts per session.

## JSON Format

```json
{
  "nces_id": "...",
  "district_name": "...",
  "state": "...",
  "enrollment": N,
  "school_year": "2025-2026",
  "source_url": "...",
  "source_description": "...",
  "first_day": "YYYY-MM-DD",
  "last_day": "YYYY-MM-DD",
  "total_instructional_days": N,
  "spring_break_start": "YYYY-MM-DD",
  "spring_break_end": "YYYY-MM-DD",
  "winter_break_start": "YYYY-MM-DD",
  "winter_break_end": "YYYY-MM-DD",
  "thanksgiving_break_start": "YYYY-MM-DD",
  "thanksgiving_break_end": "YYYY-MM-DD",
  "other_breaks": [{"name": "...", "start": "...", "end": "..."}],
  "non_school_days": [
    {"date": "YYYY-MM-DD", "type": "HOLIDAY|TEACHER_WORKDAY|HALF_DAY", "name": "..."}
  ],
  "saturday_sessions": [{"date": "YYYY-MM-DD", "name": "..."}],
  "contact": {"name": "...", "email": "...", "phone": "...", "source": "..."},
  "notes": "..."
}
```

## Key Patterns Observed
- **Texas ISDs** (CFISD, NISD, Katy, Fort Bend): District of Innovation = early August start. Dual-designated bad weather/PD days. ~171-177 instructional days.
- **Virginia districts** (Fairfax, Prince William): Teacher workdays + professional workdays around holidays. Quarter-end early releases. PWCS observes Rosh Hashanah + both Eids.
- **Florida districts** (Broward, Lee, Osceola): ~180 days. Teacher planning days. Hurricane/severe weather make-up days. Osceola has "Rodeo Day."
- **Georgia districts** (Cobb): Digital Learning Days count toward instructional requirement. Fall break in September.
- **California districts** (San Diego): Lincoln Day separate from Presidents Day. Non-instructional days. 80/20 split model.
- **Tennessee districts** (Nashville/Davidson): "Director of Schools" title. Fall break full week in October.
- **Maryland districts** (Montgomery County): Student Transition Day. 181 instructional days.
- **South Carolina districts** (Greenville): "Modified year-round" designation. Semester ends before winter break. SC State Composite Calendar is excellent source.
- **Colorado districts** (Jeffco): 172 student days / 185 teacher days. Modified Contact Days vary by school.

## Don't Forget
- Always include `contact` block (superintendent name, email, phone)
- Note confidence level honestly — flag conflicting dates
- Include notes about district context (size ranking, DOI status, unusual calendar features)
- If calendar PDF is image-based, flag for Wilma to verify during ingestion
- Update THIS FILE at end of each session with what you completed
