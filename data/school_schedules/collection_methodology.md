# School Calendar Collection Methodology
## Updated 2026-03-15 based on manual review of 11 districts + 50-state DOE survey

## Three-Tier Collection Strategy

### Tier 1: State DOE Centralized Data (GOLD states)
**One download per state → all districts**

| State | Source | Format | URL | Districts |
|-------|--------|--------|-----|-----------|
| Alaska | DOE Calendar Portal | HTML per district | education.alaska.gov/DOE_Rolodex/SchoolCalendar/Home/Districts | ~54 |
| Delaware | DOE District Calendar | PDF | education.delaware.gov/wp-content/uploads/2025/05/2025-26-calendar-distr... | ~19 |
| Florida | DOE School District Calendars | XLSX (3 sheets) | fldoe.org/file/7584/school-district-calendars.xlsx | 67 |
| South Carolina | DOE Composite School Calendar | PDF | ed.sc.gov/data/other/school-calendars/ | ~85 |
| Utah | DOE District Calendar | PDF | schools.utah.gov/schoolcalendars/2526DistrictCalendar.pdf | ~41 |
| Virginia | DOE School Directories | Excel | doe.virginia.gov/about-vdoe/virginia-school-directories | ~132 |

### Tier 1.5: State DOE Portal (SILVER states)
**Per-district but accessible via state system**

| State | Source | Format | URL |
|-------|--------|--------|-----|
| Alabama | AlabamaAchieves | Web DB | alabamaachieves.org/al-sch-cal/ |
| Colorado | CDE Data Pipeline | Data pipeline | ed.cde.state.co.us/datapipeline/per-collections/per-inst-hours-days |
| Illinois | ISBE Calendar Inquiry | Web app | apps.isbe.net/SchCalInquiry/SchCalInquiry.aspx |
| Kentucky | KDE Calendar Summaries | PDF/Web | education.ky.gov/districts/enrol/Pages/School-Calendar.aspx |

### Tier 2: Targeted Search + Scrape (Remaining ~40 states)
**Search for each district individually using improved methodology**

#### Search Strategy (from manual review lessons):
1. Search Brave: `"[District Name]" "2025-2026" school calendar`
2. Search Brave: `"[District Name]" school district first day of school 2025`
3. Score results: PDFs +4, "calendar" in title +3, "2025-2026" +3, .gov domains +2
4. Fetch top 3 results (PDF via pdftotext locally, HTML via basic fetch)
5. Extract with Claude using strict "don't hallucinate" prompt

#### Key Lessons from Manual Review:
- **Don't scrape homepages** — find the actual calendar page/PDF
- **Event feeds ≠ calendars** — ski meets, concerts etc. get extracted as break dates
- **PDFs are gold** — most reliable source, use local pdftotext
- **If no calendar found, say so** — never fabricate dates
- **Multiple years on one page** — verify you're reading the right school year
- **Spring break is the hardest field** — wrong 90%+ of the time in v1
- **Nine Weeks / Grading Period tables** — most reliable anchor for first/last day

## Target Data Per District
- first_day (first day of school for students)
- last_day (last day of school for students)  
- winter_break_start
- winter_break_end
- spring_break_start
- spring_break_end
- school_year (2025-2026)
- source_url
- source_type (state_doe | district_pdf | district_web | manual)
- confidence (high | medium | low)
- collection_date
