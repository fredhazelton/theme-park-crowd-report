# NEXT SESSION — Barney SSD Extraction Sprint

**Read this first every session. This is your continuity doc.**

## What You're Doing
You are **Barney** — an AI agent doing gold-standard school calendar extractions for the School Schedules Database (SSD).

## Repo & Workflow
- **Repo:** `hazeydata/theme-park-crowd-report`
- **Issues:** `#61–#112` with label `SSD-collect`

## The Golden Rule
**For every single day of the school year (July 1 – June 30), determine whether students are in session or not.**

## What's Done (~40 extractions, ~4.0M students)

### TOP 20 COMPLETE (#61-#80)
### RE-EXTRACTIONS COMPLETE (#81-#84)
### NEW EXTRACTIONS (#85-#99 + #94 Klein)

⚠️ IMPORTANT: Issue number mapping shifted during FL cluster sprint.
Issues #88-#99 in GitHub have DIFFERENT district titles than what Barney extracted.
Example: GitHub #94 = "Klein ISD TX" but Barney posted Polk County FL extraction there.
Klein ISD extraction was ALSO posted to #94 as a second comment.
**Wilma needs to reconcile: match extraction JSON district_name to correct NCES ID regardless of issue number.**

### Districts Extracted (by district, not issue number):
Complete list of 40 unique district extractions posted as GitHub comments:
Broward FL, Fairfax VA, Hawaii DOE, Montgomery MD, CyFair TX, Cobb GA,
Northside TX, Lee FL, San Diego CA, Katy TX, Prince William VA,
Nashville TN, Fort Bend TX, Greenville SC, Jeffco CO, Osceola FL,
Davis UT, Milwaukee WI, Frisco TX, VA Beach VA,
Philadelphia PA (re), Denver CO (re), Alpine UT (re), Loudoun VA (re),
Long Beach CA, Washoe NV, Chesterfield VA, Volusia FL, Douglas CO,
Granite UT, Jordan UT, NYC District #31 NY, NYC District #2 NY,
Polk FL, Brevard FL, Pasco FL, Seminole FL, Knox TN, Duval FL, Klein TX

## What Remains (issues with 0 comments):
- #101 Cumberland County NC — 49K
- #103 Detroit Public Schools MI — 48K
- #104 Horry 01 SC — 47K
- #105 Round Rock ISD TX — 46K
- #106 Hamilton County TN — 45K
- #107 Columbus City OH — 45K
- #109 Killeen ISD TX — 43K
- #110 Chandler Unified AZ — 43K
- #112 Portland SD 1J OR — 43K

Also need actual extractions for the CORRECT districts on:
- #95 Cherry Creek CO — 52K
- #96 Rutherford County TN — 50K
- #97 Jefferson Parish LA — 50K
- #98 Henrico County VA — 50K
- #99 St. Johns FL — 50K
- #100 Charleston SC — 49K
- #102 NYC District #24 NY — 49K (batch with #92/#93)
- #108 NYC District #20 NY — 44K (batch with #92/#93)

## Don't Forget
- Check issue TITLE before posting — match district to correct issue
- Always include `contact` block
- NYC districts can be batch-extracted (same DOE calendar)
- Update THIS FILE at end of each session
