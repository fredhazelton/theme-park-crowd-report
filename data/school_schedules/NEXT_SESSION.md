# NEXT SESSION — Barney SSD Extraction Sprint

**Read this first every session. This is your continuity doc.**

## What You're Doing
You are **Barney** — an AI agent doing gold-standard school calendar extractions for the School Schedules Database (SSD).

## Repo & Workflow
- **Repo:** `hazeydata/theme-park-crowd-report`
- **Issues:** `#61–#112` with label `SSD-collect`

## The Golden Rule
**For every single day of the school year (July 1 – June 30), determine whether students are in session or not.**

## What's Done (~51 extractions, ~4.6M students)

### TOP 20 COMPLETE (#61-#80)
### RE-EXTRACTIONS COMPLETE (#81-#84)
### NEW EXTRACTIONS (#85-#112 mostly done)

⚠️ IMPORTANT: Issue number mapping shifted during FL cluster sprint.
**Wilma needs to reconcile: match extraction JSON district_name to correct NCES ID regardless of issue number.**

### Districts Extracted (51 unique, by district name):
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
Hamilton County TN, Jefferson Parish LA, Henrico County VA, Charleston SC

## What Remains (6 issues still need extractions):
- #101 Cumberland County NC — 49K
- #103 Detroit Public Schools MI — 48K
- #104 Horry 01 SC — 47K
- #107 Columbus City OH — 45K
- #110 Chandler Unified AZ — 43K
- #112 Portland SD 1J OR — 43K

## New State Patterns This Session:
- **Louisiana (1 district: Jefferson Parish):** MARDI GRAS BREAK (Feb 13-20, 6 school days!). Smart Start staggered entry. Spring break Apr 3-7. Storm recovery days designated.
- **SC expanded (2 districts: Greenville, Charleston):** Charleston chose Calendar A (no fall break) to preserve school meals. Spring break Apr 6-10.

## Don't Forget
- Check issue TITLE before posting — match district to correct issue
- Always include `contact` block
- Update THIS FILE at end of each session
