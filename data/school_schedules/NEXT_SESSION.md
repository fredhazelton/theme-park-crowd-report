# NEXT SESSION — Barney SSD Extraction Sprint

**Read this first every session. This is your continuity doc.**

## What You're Doing
You are **Barney** — an AI agent doing gold-standard school calendar extractions for the School Schedules Database (SSD).

## Repo & Workflow
- **Repo:** `hazeydata/theme-park-crowd-report`
- **Issues:** `#61–#112` with label `SSD-collect`

## The Golden Rule
**For every single day of the school year (July 1 – June 30), determine whether students are in session or not.**

## What's Done (39 districts, ~3.9M students)

### TOP 20 COMPLETE (#61-#80) — see previous sessions
### RE-EXTRACTIONS COMPLETE (#81-#84) — see previous sessions
### NEW EXTRACTIONS (#85-#99):
See previous sessions for #85-#97. New this session:
| Issue | District | State | Enrollment | Notes |
|-------|----------|-------|-----------|-------|
| #98 | Knox County | TN | 60K | 177 days + 3 accum, full-week fall break, 8 weather days buffer |
| #99 | Duval County | FL | 129K | 20th largest in US! Spring break Mar 16-20 (Week 1!) |

## UPDATED FL Spring Break Stagger:
- Week 1 (Mar 16-20): Seminole 50K + Osceola 74K + Polk 117K + Volusia 63K + Broward 254K + **Duval 129K** = **687K**
- Week 2 (Mar 23-27): Brevard 74K + Lee 99K = **173K**
- Week 3 (Mar 30-Apr 3): Pasco 75K = **75K**
- **Total: 935K FL students across 3 weeks!**

## What's Next (#100-#112):
~13 districts, ~0.5M students:
- #100 through #112 — remaining districts from the top-50 list

## TN Pattern (2 districts: Nashville #72, Knox #98):
- Both have full-week October fall breaks
- Both ~177 student days + accumulated hours per TN code
- Both allow 8 inclement weather days before makeup
- Nashville uses "Director of Schools" title; Knox uses "Superintendent"

## Don't Forget
- Always include `contact` block
- Flag conflicting dates honestly
- Note district context
- Update THIS FILE at end of each session
