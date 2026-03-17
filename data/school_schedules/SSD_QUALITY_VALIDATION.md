# SSD Quality Validation System

## Overview

The SSD (School Schedule Data) quality validation system detects hallucinated and low-quality entries in school calendar datasets. Built to address the ~40% fabrication rate in LLM-extracted school calendar data.

## Files

- **`ssd_quality_check.py`** - Main validation script with 5 quality checks
- **`run_quality_gate.py`** - CI/QA integration wrapper  
- **`ssd_quality_report.json`** - Detailed validation results (auto-generated)

## Quality Checks Implemented

### 1. Duplicate Date Detection
**Issue:** LLM hallucinates identical calendars across multiple districts
**Check:** Flag date combinations shared by 20+ districts (threshold configurable)
**Example:** 284 districts sharing identical spring break dates

### 2. Date Plausibility 
**Issue:** Dates outside reasonable ranges for 2025-26 school year
**Check:** Validate date ranges:
- `first_day`: Jul-Sep 2025
- `last_day`: Apr-Jul 2026  
- `spring_break`: Feb-May 2026
- `winter_break`: Nov 2025-Jan 2026

### 3. Break Length Sanity
**Issue:** Implausible vacation lengths
**Check:** 
- Spring break: 2-14 days
- Winter break: 7-21 days
- School year: 150-300 days

### 4. State-Level Consistency
**Issue:** Districts within a state having wildly different calendars
**Check:** Flag spring break dates >30 days from state median

### 5. Source URL Validation
**Issue:** Generic URLs that wouldn't contain district-specific calendars
**Check:** Flag state DOE sites, generic "/about" pages, etc.

## Usage

### Standalone Validation
```bash
# Run quality checks
python3 ssd_quality_check.py [--input data.json] [--output report.json]

# Exit codes: 0 if quality_score > 0.8, 1 otherwise
```

### CI/QA Integration
```bash  
# Quality gate for automated pipelines
python3 run_quality_gate.py [--input data.json] [--threshold 0.8]

# Exit codes:
# 0: Data passes quality gate
# 1: Data fails quality gate
# 2: Error running checks
```

## Output Formats

### Console Summary
```
📊 SSD Quality Report Summary
========================================
Total 'found' entries:     5,919
Clean entries:             2,837
Flagged entries:           3,082  
Overall quality score:     0.479

Issues by type:
  • duplicate_dates      2,829
  • invalid_break_length 152
  • invalid_year_length  5
  • state_outlier        166
  • suspicious_url       1
```

### JSON Report Structure
```json
{
  "timestamp": "2026-03-16T20:50:44.375495",
  "summary": {
    "total_found": 5919,
    "flagged": 3082,
    "clean": 2837, 
    "quality_score": 0.479
  },
  "issues_by_type": {"duplicate_dates": 2829, ...},
  "flagged_entries": {
    "nces_id": {
      "issues": [{"type": "...", "description": "...", "severity": "..."}],
      "entry": {...}
    }
  }
}
```

## Current Data Quality Results

**❌ CRITICAL QUALITY ISSUES DETECTED**

- **5,919** total "found" entries examined
- **3,082** entries flagged (52.1% failure rate)
- **0.479** overall quality score (below 0.8 threshold)

**Top Issues:**
1. **Duplicate dates:** 2,829 entries (47.8%) - Mass hallucination
2. **Invalid lengths:** 157 entries - Implausible break durations  
3. **State outliers:** 166 entries - Inconsistent within states
4. **Suspicious URLs:** 1 entry - Generic/non-district sources

## Reusability Pattern

The validation system follows a reusable pattern for other data products:

```python
class DataQualityChecker:
    def __init__(self, data): ...
    def run_checks(self) -> QualityReport: ...
    def _check_specific_issue(self, entries): ...
    def _generate_report(self) -> QualityReport: ...
```

This pattern can be adapted for:
- **Park hours data** (operating hours plausibility, seasonal patterns)
- **Weather/Traffic Index** (value ranges, temporal consistency)
- **Any structured dataset** requiring validation

## Recommendations

1. **Immediate:** Do not use current LLM scraper results for production
2. **Short-term:** Implement multi-source triangulation as described in PIPELINE_ARCHITECTURE.md
3. **Long-term:** Run quality validation after each scraping run before data release

## Integration Points

- Add to **CI/CD pipelines** for automated quality gates
- Integrate with **data monitoring** systems for ongoing validation
- Use in **scraper development** to catch quality regressions early
- Include in **customer data delivery** process for quality assurance