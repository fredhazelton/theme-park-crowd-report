# School Calendar Dataset — Data Dictionary

**Version:** 3.0  
**Last Updated:** 2026-03-08

---

## File: `districts_comprehensive.csv`

The master dataset. One row per US public school district.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `nces_leaid` | string | Official NCES Local Education Agency ID | `0622710` |
| `district_name` | string | District name | `Los Angeles Unified` |
| `state` | string | Two-letter state code | `CA` |
| `city` | string | City/town | `Los Angeles` |
| `enrollment` | integer | Total student enrollment (NCES 2022-23) | `426268` |
| `first_day` | date (YYYY-MM-DD) | First day of school | `2025-08-14` |
| `last_day` | date (YYYY-MM-DD) | Last day of school | `2026-06-10` |
| `winter_break_start` | date | First day of winter break | `2025-12-18` |
| `winter_break_end` | date | Last day of winter break | `2026-01-02` |
| `spring_break_start` | date | First day of spring break | `2026-03-30` |
| `spring_break_end` | date | Last day of spring break | `2026-04-03` |
| `summer_start` | date | First day of summer break | `2026-06-10` |
| `summer_end` | date | Last day of summer break (= first_day) | `2025-08-14` |
| `fall_break_start` | date or null | First day of fall break (if applicable) | `2025-10-06` |
| `fall_break_end` | date or null | Last day of fall break (if applicable) | `2025-10-10` |
| `thanksgiving_break_type` | string | `full_week`, `wed_fri`, or `thu_fri` | `wed_fri` |
| `confidence` | string | Data quality tier: `confirmed`, `high`, `medium`, `inferred` | `confirmed` |
| `source` | string | Collection source | `schoolcalendarinfo` |
| `calendar_url` | string or null | URL of source calendar | `https://...` |

**Row count:** 13,418 districts  
**Enrollment total:** ~46.4M students

---

## File: `daily_aggregate_v3.csv`

Daily enrollment-weighted summary. One row per day for the school year.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `date` | date (YYYY-MM-DD) | Calendar date | `2026-03-16` |
| `total_students` | integer | Total students in dataset | `46407113` |
| `students_in_session` | integer | Students in school (enrollment-weighted) | `34028007` |
| `students_on_break` | integer | Students on break (enrollment-weighted) | `12379106` |
| `pct_on_break` | float | Percent on break (0.0-100.0) | `26.7` |
| `pct_in_session` | float | Percent in session (0.0-100.0) | `73.3` |
| `primary_reason` | string | Dominant reason for the day's status | `spring_break` |
| `pct_confirmed` | float | Percent of on-break count from confirmed/high sources | `62.3` |

**`primary_reason` values:**
- `in_session` — majority of students are in school
- `summer_break` — majority on summer break
- `spring_break` — majority on spring break
- `winter_break` — majority on winter break
- `fall_break` — majority on fall break
- `thanksgiving` — Thanksgiving break
- `weekend` — Saturday or Sunday
- `labor_day`, `columbus_day`, `veterans_day`, `mlk_day`, `presidents_day`, `memorial_day` — federal holidays

**Row count:** 366 (Jul 1, 2025 – Jun 30, 2026)

---

## File: `districts_top100.csv`

The 100 largest districts by enrollment, all individually verified. Same schema as `districts_comprehensive.csv` but every row is `confidence: confirmed`.

---

## File: `districts_historical_all.csv`

Historical calendar data for districts where prior year data was collected.

| Column | Type | Description |
|--------|------|-------------|
| `school_year` | string | School year (e.g., `2024-2025`) |
| All columns from `districts_comprehensive.csv` | | Same schema |

**Row count:** 266 district-year records (primarily 2024-2025)

---

## File: `historical_aggregate.csv`

Daily aggregate for historical school years. Same schema as `daily_aggregate_v3.csv` plus `school_year` column.

---

## File: `enrollment_by_district.csv`

NCES enrollment data aggregated from school level to district level.

| Column | Type | Description |
|--------|------|-------------|
| `LEAID` | string | NCES Local Education Agency ID |
| `LEA_NAME` | string | District name (NCES official) |
| `STATE` | string | State name |
| `TOTAL_ENROLLMENT` | integer | Total student enrollment |

---

## Confidence Tier Definitions

| Tier | Source | Accuracy | % of Enrollment | Use Case |
|------|--------|----------|----------------|----------|
| **confirmed** | schoolcalendarinfo.com, official district sites | ±0-1 days | 34.4% | District-level queries, verification |
| **high** | AI-extracted from official sites | ±1-3 days | 1.2% | District-level queries |
| **medium** | State median (10+ confirmed in state) | ±3-7 days | 54.8% | State/regional aggregates |
| **inferred** | State DOE rules + regional patterns | ±7-14 days | 3.5% | National aggregates only |

---

*Questions about this data? Contact fred@hazeydata.ai*
