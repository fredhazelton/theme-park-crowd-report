# SSD Data Quality Audit — Initial Findings

**Auditor:** Barney
**Date:** 2026-03-17
**Scope:** Codebase review, documentation cross-reference, methodology analysis
**Status:** Phase 1 — Pre-data-run observations (full data run pending repo access)

---

## Executive Summary

Based on a thorough review of all SSD documentation (METHODOLOGY.md, PIPELINE_ARCHITECTURE.md, AUDIT_ISSUES.md, DATA_DICTIONARY.md, SALES_STRATEGY.md, SSD_QUALITY_VALIDATION.md) and the existing quality check code, I've identified **14 findings** across three categories: data integrity, documentation consistency, and commercial readiness.

The v1 quality checker scored the dataset at **0.479** — well below the 0.80 threshold. The v3 pipeline addresses several critical issues (primary_reason labeling, fall break modeling, Thanksgiving ramp) but several gaps remain that need to be closed before this is sellable.

---

## Critical Findings (Block Sales)

### F-01: Enrollment is zero for all districts in v3 database
**Source:** Issue #57, Discord thread
**Impact:** CRITICAL — enrollment weighting is the core value prop. Without it, the daily aggregate percentages are meaningless.
**Root cause:** NCES field name mismatch during import into the v3 SQLite schema.
**Fix:** Wilma owns this (issue #57). Must be resolved before any other quality metrics are trustworthy.

### F-02: 52% of districts flagged by v1 quality checker
**Source:** SSD_QUALITY_VALIDATION.md
**Impact:** CRITICAL — 2,829 of 5,919 districts share identical date fingerprints (mass hallucination from LLM scraper).
**Root cause:** V1 LLM scraper fabricated dates when it couldn't find real ones.
**Fix:** The v3 multi-source triangulation pipeline is designed to fix this. The Brave PDF hunt (791 PDFs found) and upcoming Firecrawl pass should replace hallucinated data with real extractions. Key metric to track: **how many of the 2,829 flagged districts get clean data after re-extraction?**

### F-03: Only spring and winter breaks captured in v3 DB
**Source:** Discord thread, issue #55
**Impact:** HIGH — fall break, Thanksgiving, teacher workdays, and other non-school days are missing from the fact table.
**Fix:** The v3 extraction prompt ("extract ALL exceptions") is designed to capture everything. Verify after PDF re-extraction pass.

---

## High Findings (Fix Before Enterprise Sales)

### F-04: Inconsistent student counts across documents
**Source:** AUDIT_ISSUES.md (#2)
**Impact:** Enterprise buyers doing due diligence will notice. Sales strategy says 46,259,613; daily aggregate says 46,407,113; research doc says 46.3M.
**Fix:** Documents should derive totals from a single source at build time.

### F-05: NCES enrollment data is 2022-23 (two years stale)
**Source:** METHODOLOGY.md, AUDIT_ISSUES.md (#6)
**Impact:** Enrollment figures used for weighting are from 2022-23. NCES published 2023-24 in December 2024.
**Status:** Wilma owns (issue #57).

### F-06: Sales strategy overstates competitive uniqueness
**Source:** AUDIT_ISSUES.md (#8)
**Impact:** Section 4.1 says "There Is No Direct Competition." This is factually wrong.
**Competitors:** Burbio ($3-6K/yr, 80K+ schools), Inntopia School Calendar Explorer (3K districts, hospitality focus), schools-calendar.com API.
**Fix:** Rewrite 4.1 to "Limited Direct Competition" and lead with differentiation.

### F-07: "55 states/territories" count is incorrect
**Source:** AUDIT_ISSUES.md (#9)
**Fix:** Verify actual distinct state codes in NCES data. US = 50 states + DC + 5 territories = 56.

---

## Medium Findings (Product Polish)

### F-08: No validation of post-Labor Day start rule
**Impact:** 6 states (VA, MI, MN, WI, MD, IA) mandate post-Labor Day starts. Districts showing first_day before Labor Day 2025 (Sep 1) are likely wrong.
**Fix:** Add state-specific rule check to validator.

### F-09: No year-round school detection
**Source:** METHODOLOGY.md limitation #3
**Fix:** Flag known year-round districts from NCES data.

### F-10: Fall break coverage is approximate
**Source:** METHODOLOGY.md limitation #6
**Fix:** After PDF re-extraction, fall break should come from actual data, not state-level assumptions.

### F-11: Daily aggregate pct_confirmed column untested
**Fix:** Run validator against daily_aggregate_v3.csv and spot-check.

---

## Documentation Findings

### F-12: Data dictionary doesn't match v3 SQLite schema
**Fix:** Document the SQLite star schema (dim_district, dim_calendar_source, fact_school_day).

### F-13: No private school coverage noted in sales materials
**Impact:** Private/parochial = ~10% of US students (~5.5M). Transparently note this gap.

### F-14: Historical data claims are aspirational
**Source:** SALES_STRATEGY.md mentions 2022-2025 history. Actual = 266 district-year records for 2024-25.
**Fix:** Correct sales materials to reflect actual availability.

---

## Recommended Priority Order

1. **F-01** — Fix enrollment zeros (blocks all weighted analysis)
2. **F-02** — Track hallucination cleanup rate after PDF re-extraction
3. **F-03** — Verify v3 extraction captures all break types
4. **F-04** — Single-source student counts
5. **F-06** — Fix competitive claims in sales strategy
6. **F-14** — Correct historical data claims
7. **F-08** — Add state-specific validation rules
8. **F-12** — Document v3 SQLite schema

---

## Next Steps (Barney)

1. Run `ssd_quality_check_v3.py` against current data once PDF re-extraction completes
2. Update SALES_STRATEGY.md — fix competitive claims, historical data, student counts
3. Create sample datasets for sales demos (issue #56)
4. Build automated quality gate that runs after each pipeline execution

---

*Phase 1 (documentation review). Phase 2 (full data validation) runs after Brave scan results are processed and PDF re-extraction is complete.*
