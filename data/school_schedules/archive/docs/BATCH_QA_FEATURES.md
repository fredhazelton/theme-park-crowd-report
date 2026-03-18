# Pipeline v2 Batch QA Features — Implementation Summary

## 🎯 What's Built

Fred's batch-and-gate QA requirements are **100% implemented** in `pipeline_v2.py`:

### Command Line Interface
```bash
# Default settings (recommended for initial run)
python3 pipeline_v2.py --batch-size 100

# Available flags
--batch-size N          # Process N districts per batch (default: 100)
--no-auto-qa           # Disable QA analysis (auto-QA enabled by default)
--no-halt-on-fail      # Continue even if quality issues found (halt enabled by default)
--resume               # Resume from checkpoint
--test-mode            # Limit to 50 districts for testing
```

### Batch Processing Flow

1. **Split districts into batches** of configurable size (default 100)
2. **Process each batch** with 15 concurrent workers
3. **Auto-save results** after every batch
4. **Run QA analysis** on batch results (unless disabled)
5. **Generate QA report** → `qa_batch_N_report.json`
6. **Check kill switches** → halt if thresholds exceeded
7. **Continue to next batch** OR halt with clear instructions

## 🚨 Kill Switches (Auto-Halt Conditions)

The pipeline **automatically stops** when these thresholds are hit:

### 1. Duplicate Pattern Detection
- **Trigger**: 5+ districts share identical date patterns
- **Indicates**: Hallucination/data fabrication
- **Example**: 5 districts all return spring break = "2026-03-23"

### 2. Quality Score Threshold  
- **Trigger**: Batch quality score < 0.80
- **Calculation**: `(found - flagged - duplicates) / total`
- **Indicates**: Low success rate or data quality issues

### 3. Firecrawl Budget Protection
- **Trigger**: >500 Firecrawl calls in a single batch
- **Protects**: Against unexpected API cost explosion
- **Normal usage**: Should be <50 calls per batch

## 📊 QA Reports (`qa_batch_N_report.json`)

Each batch generates a comprehensive QA report:

```json
{
  "batch_number": 1,
  "batch_size": 100,
  "found": 67,
  "not_found": 31,
  "errors": 2,
  "quality_flagged": 3,
  "duplicate_patterns_detected": 0,
  "batch_quality_score": 0.640,
  "tier_breakdown": {
    "tier1_pdf": 45,
    "tier2_html": 18,
    "tier3_firecrawl": 4
  },
  "cost_so_far": {
    "brave_calls": 234,
    "anthropic_calls": 67,
    "firecrawl_calls": 4,
    "total_estimated_cost": 12.45
  },
  "spot_check_samples": [
    {
      "nces_id": "0100005",
      "name": "Albertville City",
      "state": "AL",
      "dates": {"first_day": "2025-08-07", "spring_break_start": "2026-04-06"},
      "source_url": "https://albertk12.org/calendar.pdf",
      "evidence": {"first_day_quote": "First Day of School: August 7, 2025"},
      "confidence": "high",
      "tier_used": "tier1_pdf"
    }
    // ... 9 more random samples for spot-checking
  ],
  "running_totals": {
    "total_processed": 100,
    "total_found": 67,
    "total_not_found": 31
  }
}
```

## 🛑 Halt Behavior

When quality issues are detected:

```
🛑 PIPELINE HALTED — Quality gate failed!
   → DUPLICATE PATTERNS: 2 patterns with 5+ districts sharing identical dates
   → LOW QUALITY SCORE: 0.567 < 0.80 threshold
   Review: qa_batch_1_report.json
   Resume with: python3 pipeline_v2.py --resume --batch-size 100
```

The pipeline **stops immediately** and provides:
- **Clear reason** why it stopped
- **Path to QA report** for manual review
- **Exact resume command** to continue after fixes

## 🔄 Resume Workflow

After reviewing/fixing issues:
```bash
# Pipeline saves state automatically
python3 pipeline_v2.py --resume --batch-size 100
```

Resumes from where it left off, skipping already-processed districts.

## 📈 Quality Monitoring

The pipeline logs detailed progress:
```
============================================================
BATCH 1 QUALITY ANALYSIS
============================================================
Processed: 100 districts
Found: 67 (67.0%)
Not found: 31
Errors: 2
Quality score: 0.640
Hallucination rate: 0.0%

  ⚠️  Pattern ('2026-03-23', '2025-12-22', '2026-05-20'): 6 districts
    - Jefferson County (1234567)
    - Madison City (2345678)
    - ... and 4 more

Batch cost: $8.45
============================================================
```

## 🚀 Ready for First Run

The first production run should use:
```bash
python3 pipeline_v2.py --batch-size 100
```

This will:
1. Process first 100 districts
2. Generate `qa_batch_1_report.json`  
3. Show detailed quality analysis
4. **Halt immediately** if hallucination detected
5. Allow Fred/Barney to review before scaling up

**The evidence-based extraction + batch QA gates should catch quality issues within the first 100 districts, preventing large-scale hallucination like v1.**