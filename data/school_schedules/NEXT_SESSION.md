# NEXT SESSION — Barney SSD Extraction Sprint

**Read this first every session. This is your continuity doc.**

## What You're Doing
You are **Barney** — an AI agent doing gold-standard school calendar extractions for the School Schedules Database (SSD).

## Repo & Workflow
- **Repo:** `hazeydata/theme-park-crowd-report`
- **Issues:** `#61–#112` with label `SSD-collect`

## The Golden Rule
**For every single day of the school year (July 1 – June 30), determine whether students are in session or not.**

## What's Done (~48 extractions, ~4.4M students)

### TOP 20 COMPLETE (#61-#80)
### RE-EXTRACTIONS COMPLETE (#81-#84)
### NEW EXTRACTIONS (#85-#112 partial)

⚠️ IMPORTANT: Issue number mapping shifted during FL cluster sprint.
Issues #88-#99 in GitHub have DIFFERENT district titles than what Barney extracted.
**Wilma needs to reconcile: match extraction JSON district_name to correct NCES ID regardless of issue number.**

### Districts Extracted (48 unique, by district name):
Broward FL, Fairfax VA, Hawaii DOE, Montgomery MD, CyFair TX, Cobb GA,
Northside TX, Lee FL, San Diego CA, Katy TX, Prince William VA,
Nashville TN, Fort Bend TX, Greenville SC, Jeffco CO, Osceola FL,
Davis UT, Milwaukee WI, Frisco TX, VA Beach VA,
Philadelphia PA (re), Denver CO (re), Alpine UT (re), Loudoun VA (re),
Long Beach CA, Washoe NV, Chesterfield VA, Volusia FL, Douglas CO,
Granite UT, Jordan UT, NYC District #31 NY, NYC District #2 NY,
Polk FL, Brevard FL, Pasco FL, Seminole FL, Knox TN, Duval FL,
Klein TX, NYC District #24 NY, NYC District #20 NY, Round Rock TX,
Killeen TX, Cherry Creek CO, Rutherford County TN, St. Johns FL,
Hamilton County TN

## What Remains (~9 issues still need extractions):
- #97 Jefferson Parish LA — 50K
- #98 Henrico County VA — 50K
- #100 Charleston SC — 49K
- #101 Cumberland County NC — 49K
- #103 Detroit Public Schools MI — 48K
- #104 Horry 01 SC — 47K
- #107 Columbus City OH — 45K
- #110 Chandler Unified AZ — 43K
- #112 Portland SD 1J OR — 43K

## Updated FL Spring Break Stagger (now with St. Johns!):
- Week 1 (Mar 16-20): Broward 254K + Duval 129K + Polk 117K + Osceola 74K + Volusia 63K + Seminole 50K + **St. Johns 50K** = **737K**
- Week 2 (Mar 23-27): Brevard 74K + Lee 99K = **173K**
- Week 3 (Mar 30-Apr 3): Pasco 75K = **75K**
- **Total: 985K FL students across 3 weeks!**

## TN Pattern (4 districts: Nashville, Knox, Rutherford, Hamilton):
- All have full-week October fall breaks (but Hamilton is Oct 13-17, others Oct 6-10)
- All ~177 student days + accumulated hours per TN code
- Hamilton has only 3-day Thanksgiving (Wed-Fri); others have full week
- Hamilton and Rutherford observe Good Friday; Nashville and Knox do not
- Rutherford spring break is Mar 30-Apr 3 (later); others are Mar 16-20

## Don't Forget
- Check issue TITLE before posting — match district to correct issue
- Always include `contact` block
- Update THIS FILE at end of each session
