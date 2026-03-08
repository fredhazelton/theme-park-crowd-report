# School Calendar Data — Audit Issues & Fixes

**Auditor:** Barney (Chief of Pipeline)  
**Date:** 2026-03-08  
**Status:** Fixes committed to `barney/school-data-v3` branch

---

## Issues Found

### CRITICAL (must fix before selling)

1. **`primary_reason` labeling bug** — During Oct-May when 99.9% of students are in session, the label says `summer_break` instead of `in_session`. Enterprise buyers reviewing the CSV will notice immediately.
   - **Fix:** New logic in `build_daily_calendar_v3.py` — labels based on majority status.

2. **Inconsistent student count across documents** — Sales strategy says 46,259,613. Daily aggregate says 46,407,113. RESEARCH.md says 46.3M.
   - **Fix:** All documents should derive total from the `districts_comprehensive.csv` at build time. No hardcoded numbers.

3. **No `pct_confirmed` transparency** — Buyers can't tell what percentage of any day's number comes from confirmed vs inferred data.
   - **Fix:** New `pct_confirmed` column in `daily_aggregate_v3.csv`.

### HIGH (fix before enterprise sales)

4. **Fall break not modeled** — Many Southern states have October fall break. Daily aggregate shows 99.9% in session all October, which is wrong.
   - **Fix:** Fall break modeling for TN, GA, KY, IN, NC in `build_daily_calendar_v3.py`.

5. **Thanksgiving week is too abrupt** — Jumps from 0.1% on break to 100% on Thu. Real pattern is a ramp from Mon.
   - **Fix:** Thanksgiving break type modeling (full_week / wed_fri / thu_fri) based on district size as proxy.

6. **Enrollment data is 2022-23** — NCES published 2023-24 in Dec 2024.
   - **Fix:** Wilma should download updated NCES data and re-run the pipeline. Filed as action item.

7. **No data dictionary** — Enterprise buyers need schema documentation.
   - **Fix:** `DATA_DICTIONARY.md` created.

### MEDIUM (fix for product polish)

8. **Sales strategy overstates competitive uniqueness** — Burbio actively sells school calendar data to travel/retail, not just EdTech. Claims "no direct competition" are inaccurate.
   - **Fix:** Revised competitive section in sales strategy (pending).

9. **"55 states/territories" count is wrong** — US has 50 states + DC + 5 territories = 56.
   - **Fix:** Verify actual count from NCES data and correct.

10. **No standalone methodology document** — RESEARCH.md is internal notes, not customer-facing.
    - **Fix:** `METHODOLOGY.md` created for enterprise due diligence.

---

## Files Created/Modified

| File | Action | Description |
|------|--------|-------------|
| `build_daily_calendar_v3.py` | NEW | Rewritten daily aggregate builder with all fixes |
| `METHODOLOGY.md` | NEW | Customer-facing methodology document |
| `DATA_DICTIONARY.md` | NEW | Schema documentation for all CSV files |
| `AUDIT_ISSUES.md` | NEW | This document |

## Next Steps for Wilma/Bam-Bam

1. Pull `barney/school-data-v3` branch
2. Run `python build_daily_calendar_v3.py` in `data/school_schedules/`
3. Verify output: check Oct 13-17 for fall break, Nov 24-28 for Thanksgiving ramp
4. Download NCES 2023-24 enrollment data and update `enrollment_by_district.csv`
5. Re-run `build_comprehensive.py` with updated enrollment
6. Re-run `build_daily_calendar_v3.py` with updated districts
7. Commit new `daily_aggregate_v3.csv` to branch
8. Barney reviews output, merges to main

🪨 Barney
