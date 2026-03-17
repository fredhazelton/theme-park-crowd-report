# SALES_STRATEGY Corrections Log

**Updated by:** Barney  
**Date:** 2026-03-17  
**Applies to:** `data/school_schedules/SALES_STRATEGY.md`

---

## Changes Required (in priority order)

These corrections should be applied to SALES_STRATEGY.md before any customer-facing use. The corrected content is available in separate files already committed to the repo.

### 1. Section 4 — Competitive Landscape (REPLACE ENTIRELY)
**File:** `COMPETITIVE_ANALYSIS_v2.md`  
**What changed:**
- Section 4.1 "There Is No Direct Competition" → "Two Established Competitors, Different Angles"
- Burbio threat level: Medium → **HIGH** (sells to travel/retail/staffing, publishes spring break wave charts)
- Inntopia SCX: added 5+ year history, university data, human-vetted quality, quarterly refresh details
- Added "Our Honest Weaknesses" section
- Added per-competitor strategy

### 2. Section 1 — Executive Summary
**Line:** "No one else has this data in structured, queryable form."  
**Change to:** "We built the first enrollment-weighted school calendar database — a unique analytics layer on top of district calendar data."  
**Reason:** Burbio has structured, queryable data. Our differentiator is enrollment weighting, not the raw data's existence.

**Line:** "Historical data (2022-2025) is being collected"  
**Change to:** "Historical data is being collected (2024-2025 available; expanding annually)"  
**Reason:** We don't have 2022-2024 data yet. Audit finding F-14.

### 3. Section 2.2 — Data Specifications
**Line:** `States/territories | 55`  
**Change to:** Verify actual count from NCES data (should be 50 states + DC = 51, or 56 with territories)  
**Reason:** Audit finding F-07.

**Line:** `Students covered | 46,259,613`  
**Change to:** Derive from `districts_comprehensive.csv` at build time; do not hardcode  
**Reason:** Audit finding F-04 (inconsistent counts: 46,259,613 vs 46,407,113 vs 46.3M).

### 4. Slide 7 — Competitive Landscape (Pitch Deck)
**Current:** Lists only schoolcalendarinfo, NCES, TouringPlans — "This category is empty"  
**Change to:** Acknowledge Burbio and Inntopia as existing competitors, position our enrollment weighting as the differentiator  
**Reason:** A prospect who discovers Burbio or Inntopia after our pitch will lose trust if we claimed "empty category"

### 5. Section 8.2 — Email Template
**Line:** "it's something that genuinely doesn't exist anywhere else"  
**Change to:** "it's something no one else does with enrollment weighting at this scale"  
**Reason:** Same as above — don't claim the category is empty when it isn't

### 6. Appendix A — Key Dataset Statistics
**Line:** `States/territories | 55`  
**Fix:** Same as Section 2.2

**Line:** `Historical years planned | 2022-2026 (5 years)`  
**Change to:** `Historical years available | 2024-2026 (2 years; expanding annually)`  
**Reason:** Audit finding F-14

---

## New Files Added (already committed)

| File | Purpose |
|------|---------|
| `SSD_ONE_PAGER.md` | Customer-facing product sheet with corrected positioning |
| `COMPETITIVE_ANALYSIS_v2.md` | Full replacement for Section 4 |
| `SSD_AUDIT_V3.md` | Phase 1 audit findings (14 issues) |
| `ssd_quality_check_v3.py` | v3 quality validation script |

---

*Fred: Review and approve these changes before applying them to SALES_STRATEGY.md. The separate files are ready to use immediately for customer conversations.*
