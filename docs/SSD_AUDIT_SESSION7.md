# SSD Pipeline Audit Report — Session 7
## Barney — Chief of Pipeline, Slate Rock & Gravel Co.

**Date:** 2026-03-23  
**Scope:** Full audit of School Schedules Database project + pipeline  
**Classification:** Revenue-critical — HazeyData's first potential product  
**Commissioned by:** Fred (Session 6 directive)

---

## EXECUTIVE SUMMARY

The SSD project has a strong strategic foundation and a validated collection methodology, but it is **nowhere near product-ready**. The core problem is a massive gap between current coverage (51.8% enrollment) and the 95% target needed for viability, combined with the absence of a formal, automated, repeatable pipeline.

What exists today is a collection of scripts — good scripts, proven methodology — but not a pipeline in the WTI sense. There is no orchestrator, no daily cron, no automated reporting, no quality gates, no standardized output. The SSD "pipeline" is currently a set of manual steps that Wilma and Barney execute on an ad-hoc basis.

**The good news:** The hard intellectual work is done. The extraction methodology is proven. The star schema is designed and populated. The competitive landscape is wide open. The unit economics are excellent (~$560 total cost to build, ~$150/quarter to maintain). Fred identified a real market gap and the collection approach works.

**The bad news:** At current pace, we won't reach 95% enrollment coverage until mid-summer 2026, and the 2025-2026 school year data will be stale before we can sell it. The real product is 2026-2027 data, which means the coverage sprint and the next-year collection sprint are effectively the same problem — and districts don't publish 2026-2027 calendars until April-September.

**Bottom line:** SSD can be HazeyData's first revenue stream, but only if we treat it like a real pipeline project (not a side hustle) and execute Sprints 1-3 in April while simultaneously preparing for 2026-2027 collection.

---

## 1. CURRENT STATE OF THE SSD PIPELINE

### 1.1 What Exists

| Component | Status | Location | Notes |
|-----------|--------|----------|-------|
| Universe definition (NCES districts) | ✅ Complete | `data/school_schedules/nces_lea_complete_2324.csv` | 18,397 total districts, 13,418 regular |
| Star schema (v3.1) | ✅ Designed + populated | `data/school_schedules/v3/school_schedules.db` | dim_district, dim_calendar_source, fact_school_day |
| Extraction prompt (v3) | ✅ Proven | In `pipeline_v3.py` | "Extract EVERY non-school day" approach works |
| Brave URL discovery | ✅ Built, partially run | `brave_url_scan.py`, `brave_pdf_hunt.py` | Found URLs for ~7,700 districts |
| Pipeline v3 script | ✅ Built | `pipeline_v3.py` (45KB) | Full scrape → fetch → extract → store |
| Day-level expansion | ✅ Built | `v3/generate_days.py` | Key dates → 365 rows per district |
| Schema SQL | ✅ Built | `v3/schema.sql` | Star schema DDL |
| QA scripts | ✅ Built | `qa_sweep.py`, `ssd_quality_check_v3.py`, `run_quality_gate.py` | Quality validation logic exists |
| Daily report script | ✅ Built | `ssd_daily_report.py` | Coverage metrics reporter |
| Barney extraction workflow | ✅ Active | GitHub Issues (#61-#112) | Gold-standard manual extractions |
| Barney ingestion script | ✅ Built | `mass_ingest_barney.py` | Parses GitHub Issue JSON → DB |
| Collection methodology doc | ✅ Written | `collection_methodology.md` | Three-tier approach documented |
| Sales strategy | ✅ Written (needs corrections merged) | `SALES_STRATEGY.md` + `SALES_STRATEGY_CORRECTIONS.md` | 55KB + 3.4KB |
| Competitive analysis | ✅ Done | `COMPETITIVE_ANALYSIS_v2.md`, `docs/research/ssd_competitive_intelligence_report.md` | No direct competitor with day-level nationwide data |
| One-pager | ✅ Written | `SSD_ONE_PAGER.md` | Customer-facing summary |
| SSD Explorer (HTML dashboard) | ✅ Built | `docs/ssd-explorer.html` + `docs/ssd-explorer-data.json` | Interactive coverage visualization |

### 1.2 What's Running

**Nothing is running on a cron.** There is no automated daily SSD pipeline execution. Every step is manual:

- Brave URL scans: run manually by Wilma
- Pipeline v3 extractions: run manually by Wilma in batches  
- Barney extractions: session-based via GitHub Issues
- QA checks: run manually
- Daily report: exists but not cron-scheduled
- Ingestion: manual script execution

### 1.3 What's Broken or Missing

| Gap | Severity | Impact |
|-----|----------|--------|
| No pipeline orchestrator | 🔴 Critical | No automated execution, no repeatability |
| No cron scheduling | 🔴 Critical | Pipeline doesn't run without human intervention |
| No Discord reporting | 🟡 High | No visibility into SSD progress in #school-schedules |
| No automated QA gates | 🟡 High | Quality depends on manual spot-checking |
| Medium-confidence districts not re-extracted | 🔴 Critical | 5,910 districts with incomplete data |
| 2,534 known URLs not processed | 🔴 Critical | Free coverage sitting on the table |
| No twin QA comparison | 🟡 High | Barney extractions vs pipeline extractions not compared |
| Sales strategy corrections not merged | 🟢 Low | Known factual errors in go-to-market doc |
| 25+ legacy scrapers not archived | 🟢 Low | Code clutter, confusion risk |
| No API endpoint | 🟡 High | Can't serve data to customers |
| No 2026-2027 collection process | 🔴 Critical | The actual sellable product doesn't exist yet |

---

## 2. COVERAGE METRICS — WHERE WE ACTUALLY STAND

### 2.1 District Coverage

| Category | Districts | % of Regular Universe (13,418) |
|----------|-----------|-------------------------------|
| In database (any data) | 8,150 | 60.7% |
| High confidence (v3, full calendar) | 2,233 | 16.6% |
| Medium confidence (v1, spring+winter only) | 5,910 | 44.1% |
| Low confidence | 7 | 0.05% |
| Not in database | 5,268 | 39.3% |
| **Target for Gate 1** | **12,750+** | **95%** |

### 2.2 Enrollment Coverage

| Metric | Value |
|--------|-------|
| Total US K-12 enrollment (NCES 2023-24) | 46.26M |
| Enrollment covered by current data | 23.98M (51.8%) |
| Enrollment in high-confidence districts | ~8.9M (est. 19.2%) |
| Enrollment in medium-confidence districts | ~15.1M (est. 32.6%) |
| Barney gold-standard extractions | 29 districts, ~2.9M students (6.3%) |
| **Target for Gate 1** | **43.9M+ (95%)** |

### 2.3 The Coverage Gap

To reach 95% enrollment coverage, we need approximately:

- **Upgrade 5,910 medium → high confidence** (Sprint 1): These districts already have spring+winter break. Re-extraction with v3 prompt would capture ALL non-school days. This alone would push high-confidence from 16.6% to ~60.7% of districts.
- **Process 2,534 known URLs** (Sprint 2): Districts where we found a calendar URL but haven't run extraction yet. Expected yield: ~1,500-2,000 new districts.
- **Find + process ~2,700 more districts** (Sprints 4+7): Through second-pass URL discovery + email outreach.

### 2.4 Enrollment Distribution Reality

The enrollment distribution is heavily top-weighted. The top 200 districts by enrollment cover ~15M students (~32% of national K-12). Barney's gold-standard extractions of 29 districts already cover ~2.9M students. The top 1,000 districts cover roughly 55-60% of national enrollment.

**Key insight:** Even at 60.7% district coverage, we could be at 80%+ enrollment coverage IF we prioritize the right districts. The 5,268 missing districts are disproportionately small. Sprint prioritization by enrollment is correct.

---

## 3. GAP ANALYSIS — PATH TO 95%

### 3.1 Coverage Roadmap

| Sprint | Action | Est. New Districts | Est. Enrollment Added | Cumulative Enrollment % |
|--------|--------|--------------------|-----------------------|------------------------|
| Current | Baseline | 8,150 | 23.98M | 51.8% |
| Sprint 1 | Re-extract 5,910 medium districts | 0 new (upgrade quality) | 0 new (quality upgrade) | 51.8% (but ~60% high-confidence) |
| Sprint 2 | Process 2,534 known URLs | +1,500-2,000 | +3-5M | ~60-63% |
| Sprint 3 | Barney Top-200 (ongoing) | +170 | +7-10M | ~75-85% |
| Sprint 4 | Second-pass URL discovery | +2,000-3,000 | +3-5M | ~85-90% |
| Sprint 7 | Email outreach | +500 | +1-2M | ~92-95% |
| **Total** | | **~12,150-13,650** | **~38-46M** | **~90-95%** |

### 3.2 Critical Path

The critical path to revenue is NOT 2025-2026 coverage. The 2025-2026 school year is already more than half over. The actual sellable product is **2026-2027 school year data**, which districts begin publishing in April-September 2026.

This means:
1. Sprints 1-3 serve dual purposes: prove the pipeline works AND build the district URL/contact database for 2026-2027 collection
2. Sprint 8 (2026-2027 collection) is the REAL product sprint and overlaps with Sprints 4-7
3. The pipeline must be automated and repeatable BEFORE Sprint 8 begins

### 3.3 What "95% Coverage" Actually Means for Revenue

A buyer (TouringPlans, Thinkwell, local tourism boards) cares about:
- Day-level resolution (not just "spring break is March 15-22")
- Enrollment-weighted aggregation (what % of kids are out of school on any given day)
- Timeliness (data available BEFORE the school year, updated quarterly)
- Comprehensive coverage (no major districts missing)

At 80% enrollment coverage with high confidence, we have a viable MVP for most buyers. 95% is the quality bar for premium pricing. The gap between 80% and 95% is mostly small districts that don't materially affect crowd models.

---

## 4. SPRINT PRIORITIZATION — WHAT HAPPENS NEXT

### IMMEDIATE (This Week — Pre-Sprint)

| # | Task | Owner | Est. Time | Why Now |
|---|------|-------|-----------|---------|
| P0 | Archive 25+ legacy scrapers to `archive/` | Wilma | 1 hour | Code hygiene, reduce confusion |
| P1 | Merge `SALES_STRATEGY_CORRECTIONS.md` into `SALES_STRATEGY.md` | Wilma | 30 min | Known errors in customer-facing doc |
| P2 | Set up SSD daily report cron (post to #school-schedules) | Wilma | 1 hour | Visibility — Fred needs to see daily progress |
| P3 | Create `SSD_PIPELINE_V1_DESIGN.md` (this document's Section 7) | Barney | Done (below) | Governing spec before any pipeline work |

### Sprint 1: Re-Extract Medium Districts (April 2026)

**Priority:** 🔴 HIGHEST — biggest coverage quality jump for lowest cost  
**Owner:** Wilma (automated), Barney (QA)  
**Cost:** ~$120 Claude API  
**Duration:** 1-2 weeks (batched, ~500/day)  
**Success:** 5,910 districts upgraded from medium → high confidence  

Execution:
1. Query `dim_calendar_source` for all districts with `confidence = 'medium'`
2. For each: re-fetch original URL (or use cached content)
3. Run v3 extraction prompt ("extract EVERY non-school day")
4. Compare result to existing data — append new extraction, set `is_primary` flag
5. Generate day-level rows from new extraction
6. QA: Barney spot-checks 50 random districts against known calendars

### Sprint 2: Process Known URLs (April 2026)

**Priority:** 🔴 HIGH — free districts sitting on the table  
**Owner:** Wilma  
**Cost:** ~$100 (Firecrawl + Claude)  
**Duration:** 1-2 weeks  
**Success:** +1,500-2,000 new districts in database  

### Sprint 3: Barney Top-200 (Ongoing)

**Priority:** 🔴 HIGH — gold-standard quality anchor  
**Owner:** Barney  
**Pace:** ~10-15 districts/session  
**Current:** 29/200 complete  
**Success:** Top 200 by enrollment complete with twin QA  

### Sprint 4-8: Per SSD-FRAMEWORK.md (May-September 2026)

No changes to the existing sprint plan — it's well-designed. The key addition is that Sprint 8 (2026-2027 collection) should be treated as the **primary revenue sprint** and resourced accordingly.

---

## 5. REVENUE TIMELINE

### Realistic Path to First Paying Customer

| Date | Milestone | Coverage Est. |
|------|-----------|---------------|
| March 2026 | SSD Pipeline V1 Design approved | 51.8% enrollment |
| April 2026 | Sprints 1+2 complete, pipeline automated | ~63% enrollment, 60%+ high-confidence |
| May 2026 | Sprint 4 (URL rediscovery) + Sprint 5 (CCD backfill) | ~75% enrollment |
| June 2026 | Sprint 7 (email outreach begins) + 2026-2027 calendars start appearing | ~80% enrollment (2025-26) |
| July 2026 | Sprint 8 begins (2026-2027 collection, peak publishing season) | Early 2026-27 data |
| August 2026 | 2026-2027 data at 60%+ | MVP quality for early buyers |
| September 2026 | 2026-2027 data at 80%+ | **FIRST SALES CONVERSATIONS** |
| October 2026 | 2026-2027 data at 90%+ with QA | **FIRST PAYING CUSTOMER TARGET** |

**Revenue model (from SALES_STRATEGY.md):**
- API access: $500-2,000/month depending on tier
- Bulk data license: $5,000-15,000/year
- Custom aggregation: $2,000-5,000 one-time

**Conservative first-year target:** 2-3 customers at ~$1,000/month = $24-36K ARR

### Why October 2026 (Not Sooner)

The 2025-2026 school year ends in May-June. Selling historical data for a school year that's already over has much lower value than selling upcoming-year data. The real value proposition is: "Here's day-level school schedule data for 2026-2027, available before school starts, so you can plan your crowd models / staffing / marketing."

This means the product launch window is **August-October 2026**, when we have sufficient 2026-2027 data to be useful and buyers are planning for the new school year.

---

## 6. RISK ASSESSMENT

### 🔴 Critical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Districts don't publish 2026-2027 calendars on time** | Medium | High — delays the product | Start collection in April; historical data shows ~60% publish by July, ~90% by September |
| **Pipeline not automated before Sprint 8** | High (current trajectory) | Critical — can't process 13K districts manually | SSD Pipeline V1 Design (below) must be implemented in April |
| **Wilma bandwidth conflict with WTI pipeline** | Medium | High — SSD and WTI compete for Wilma's execution time | Clear sprint boundaries; SSD pipeline runs on different schedule than WTI |
| **Quality issues in automated extraction go undetected** | Medium | High — bad data erodes buyer trust | Automated QA gates (Sprint 6) + Barney twin QA on top 200 |

### 🟡 Moderate Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Firecrawl costs exceed budget | Low | Medium | PDF-first approach minimizes Firecrawl usage |
| Competitor enters market | Low (no one is close) | Medium | Speed to market is our moat — no one else has day-level nationwide data |
| Fred capacity constraints during sales phase | Medium | Medium | Pre-build sales materials; one-pager exists; automate demos |
| Schema changes needed mid-collection | Low | Medium | v3.1 schema is stable; append-only data model handles evolution |

### 🟢 Low Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| NCES data quality issues | Low | Low | CCD data is well-maintained; we already have it loaded |
| API infrastructure complexity | Low | Medium | Simple REST API on existing infrastructure; Bam-Bam can build quickly |
| Email outreach deliverability | Medium | Low | wilma@hazeydata.ai on legitimate domain; professional templates |

---

## 7. RECOMMENDED SSD PIPELINE DESIGN SPEC (V1)

### 7.0 Preamble

This section specifies the SSD Pipeline V1 with the same rigor as `PIPELINE_V4_DESIGN.md` for WTI. It is the governing spec for all SSD pipeline work.

**Design principles (inherited from WTI V4):**
- Pipeline is a sequence of numbered steps
- Each step reads inputs and writes outputs to known paths
- Steps are independently re-runnable
- Output paths are standardized (no version numbers in filenames)
- Daily report posts to Discord automatically
- Quality gates prevent bad data from reaching the product

### 7.1 Pipeline Steps

```
SSD Pipeline V1 — Step Sequence

S0: Universe Sync
    Input:  NCES CCD export (nces_lea_complete_2324.csv)
    Output: dim_district table (SQLite)
    Freq:   Quarterly (when NCES publishes new data)
    Owner:  Wilma

S1: URL Discovery
    Input:  dim_district (districts without calendar URLs)
    Output: url_discovery_results.json (district_id → URL + classification)
    Freq:   Weekly during active collection; monthly during maintenance
    Method: Brave Search API → classify as PDF / HTML / homepage / not_found
    Owner:  Wilma
    Cost:   ~$0.005/query

S2: Content Fetch
    Input:  url_discovery_results.json (new/updated URLs)
    Output: raw_content/{district_id}/ (PDF files, HTML snapshots)
    Freq:   After S1, or on re-fetch schedule
    Method: Direct PDF download (free) || Firecrawl for JS-rendered pages
    Owner:  Wilma
    Cost:   Free (PDF) or ~$0.01/page (Firecrawl)

S3: Calendar Extraction
    Input:  raw_content/{district_id}/
    Output: extractions/{district_id}.json (structured non_school_days array)
    Freq:   After S2
    Method: Claude Sonnet v3 extraction prompt
    Owner:  Wilma
    Cost:   ~$0.02/district
    QA:     Automated anomaly detection (S5 pre-check)

S4: Day-Level Expansion
    Input:  extractions/{district_id}.json
    Output: fact_school_day rows (SQLite)
    Freq:   After S3
    Method: Key dates → 365 rows/district/year (generate_days.py logic)
    Owner:  Wilma

S5: Quality Gate
    Input:  fact_school_day (new rows), dim_calendar_source
    Output: quality_report.json, flagged_districts.csv
    Freq:   After S4
    Method: Automated checks:
            - Instructional day count (160-200 range)
            - First day / last day within expected ranges
            - Winter break includes Dec 25
            - Spring break within Feb 15 - Apr 30
            - No duplicate days per district
            - At least 5 non-school day types extracted
            - State law minimum instructional days check
    Owner:  Gazoo validates; Wilma builds
    Gate:   Districts failing >2 checks → flagged for manual review
            Districts failing 0-1 checks → auto-promoted to high confidence

S6: Aggregation
    Input:  fact_school_day (all districts), dim_district (enrollment)
    Output: daily_aggregate.csv (date → national/state/regional enrollment-weighted metrics)
    Freq:   After S5 (or on demand)
    Method: For each day: sum enrollment of districts in session / total enrollment
    Owner:  Wilma

S7: Report
    Input:  All above outputs
    Output: Discord message to #school-schedules
    Freq:   Daily at 8:00 AM (after WTI pipeline completes)
    Content:
      - Coverage: X/13,418 districts (Y%), Z/46.3M enrollment (W%)
      - Quality: N high-confidence, M medium, L low, F flagged
      - Delta: +X districts since yesterday, +Y enrollment
      - Sprint progress: current sprint status
      - Barney extraction count: N/200
    Owner:  Wilma (Dino cron)

S8: Product Export (Phase 5 — not yet)
    Input:  fact_school_day, dim_district, daily_aggregate
    Output: API-ready JSON/Parquet files
    Freq:   After major collection milestones
    Method: Export to API-servable format
    Owner:  Bam-Bam
```

### 7.2 Directory Structure

```
data/school_schedules/
├── v3/
│   ├── school_schedules.db      # SQLite star schema (canonical)
│   ├── schema.sql               # DDL
│   └── generate_days.py         # Key dates → day-level expansion
├── pipeline/
│   ├── s0_universe_sync.py      # NCES → dim_district
│   ├── s1_url_discovery.py      # Brave Search → URL classification
│   ├── s2_content_fetch.py      # Download PDFs / Firecrawl HTML
│   ├── s3_extraction.py         # Claude Sonnet → structured JSON
│   ├── s4_day_expansion.py      # JSON → fact_school_day rows
│   ├── s5_quality_gate.py       # Automated QA checks
│   ├── s6_aggregation.py        # Enrollment-weighted daily aggregates
│   ├── s7_report.py             # Discord report to #school-schedules
│   └── run_ssd_pipeline.sh      # Orchestrator script
├── raw_content/                 # Fetched PDFs and HTML (gitignored)
├── extractions/                 # Claude extraction JSONs (gitignored)
├── archive/                     # Legacy scrapers (25+ files)
└── [existing data files]
```

### 7.3 Cron Schedule

```bash
# SSD Pipeline — daily at 8:00 AM ET (after WTI pipeline completes)
# Phase: Collection mode (Sprints 1-4, run S1-S7)
0 8 * * * cd ~/theme-park-crowd-report && .venv/bin/python -m data.school_schedules.pipeline.run_ssd_pipeline >> ~/hazeydata/ssd/logs/ssd_pipeline_$(date +\%Y-\%m-\%d).log 2>&1

# SSD Report — daily at 8:30 AM ET (even when not in collection mode)
30 8 * * * cd ~/theme-park-crowd-report && .venv/bin/python -m data.school_schedules.pipeline.s7_report >> ~/hazeydata/ssd/logs/ssd_report_$(date +\%Y-\%m-\%d).log 2>&1
```

### 7.4 Output Paths

| Output | Path | Format |
|--------|------|--------|
| SQLite database | `~/hazeydata/ssd/school_schedules.db` | SQLite 3 |
| URL discovery results | `~/hazeydata/ssd/url_discovery_results.json` | JSON |
| Raw content | `~/hazeydata/ssd/raw_content/{district_id}/` | PDF/HTML |
| Extractions | `~/hazeydata/ssd/extractions/{district_id}.json` | JSON |
| Quality report | `~/hazeydata/ssd/quality_report.json` | JSON |
| Daily aggregate | `~/hazeydata/ssd/daily_aggregate.csv` | CSV |
| Pipeline metrics | `~/hazeydata/ssd/ssd_metrics_{date}.json` | JSON |
| Logs | `~/hazeydata/ssd/logs/` | Text |

### 7.5 Separation from WTI Pipeline

The SSD pipeline is **completely separate** from the WTI pipeline:
- Different code directory (`data/school_schedules/pipeline/` vs `pipeline/steps/`)
- Different output directory (`~/hazeydata/ssd/` vs `~/hazeydata/pipeline/`)
- Different cron schedule (8:00 AM vs 6:00 AM)
- Different Discord channel (#school-schedules vs #wti-pipeline)
- No shared state or dependencies at runtime
- Both read from the same git repo but operate independently

### 7.6 Implementation Priority

1. **Week 1:** Create `pipeline/` directory with s7_report.py (daily visibility first)
2. **Week 2:** Build s3_extraction.py + s4_day_expansion.py + s5_quality_gate.py (core pipeline)
3. **Week 3:** Build s1_url_discovery.py + s2_content_fetch.py (collection automation)
4. **Week 4:** Build run_ssd_pipeline.sh orchestrator + cron setup
5. **Ongoing:** s0_universe_sync.py (quarterly), s6_aggregation.py (after major milestones)

---

## 8. BACKGROUND MONITORING NOTES

### 8.1 WTI Pipeline Status

- V4 Phase D baseline measurement: Day 2 (started 2026-03-22)
- Day 1 baseline: MAE 8.6, WTI MAE 6.7, bias +1.4
- Entity diagnostics should appear in today's 7:07 AM report (first automated cron run of s14)
- **Cannot verify Discord content from this session** — I don't have direct Discord read access. Fred or Wilma should confirm the entity diagnostics section appeared in today's #wti-pipeline report.

### 8.2 Gazoo 2 AM Audit

- Gazoo's 2 AM Opus audit should have run overnight (first on Opus 4.6)
- Expected to review: ops #18, TPCR #452, TPCR #453
- **Cannot verify from this session** — check #gazoo channel for audit post

### 8.3 Open Ticket Status

| Ticket | Status | Notes |
|--------|--------|-------|
| **ops #18** — QA script regex bug | ✅ Still OPEN | Day 3+. `agent:wilma`. Reopened by Barney Session 6 (closed without evidence). 2 comments. Gazoo should have advisory in 2 AM audit. |
| **TPCR #452** — Entity diagnostics | ✅ CLOSED | Closed 2026-03-23 00:01 UTC. 3 comments. Needs Gazoo verification that closure evidence is adequate (commit SHA, cron line, screenshot). |
| **TPCR #453** — Competition framework | ✅ Still OPEN | Day 1. `agent:wilma`. 2 comments. Code was on dead v4-restructure branch — needs to land on main. Crons may be pointing at non-existent code. |

### 8.4 Wilma Pattern Watch

The "close fast, verify never" pattern identified by Gazoo in Session 6 remains a concern. TPCR #452 was closed at 00:01 UTC — suspiciously fast after being filed at 23:43 UTC. Gazoo's audit should validate whether the closure evidence meets the ticket's requirements (commit SHA, cron line, screenshot of entity diagnostics in a real report).

---

## 9. RECOMMENDATIONS FOR FRED

### Immediate Actions

1. **Approve SSD Pipeline V1 Design** (Section 7 above) — this is the governing spec
2. **File ticket for Wilma:** "Implement SSD Pipeline V1 — Phase 1 (report + core pipeline)" — priority above competition framework
3. **File ticket for Wilma:** "Archive 25+ legacy SSD scrapers to `data/school_schedules/archive/`"
4. **Confirm entity diagnostics appeared** in today's #wti-pipeline report (8.1 above)
5. **Check Gazoo's 2 AM audit** in #gazoo for findings on all 3 tickets

### Strategic Decision Needed

**SSD vs WTI priority for Wilma's bandwidth in April:**

Wilma currently has three open WTI tickets (#18, #453) plus ongoing pipeline ops. SSD Sprints 1-2 are the highest-impact revenue work. Fred needs to decide: does Wilma prioritize SSD Sprint 1-2 execution in April, or continue WTI competition framework + ongoing ops?

**My recommendation:** SSD Sprints 1-2 first. The WTI pipeline is running and stable. The competition framework (#453) is valuable but not urgent — the baseline measurement period runs 7 days regardless. SSD is revenue-sensitive and time-boxed (2026-2027 calendars start appearing in April).

### Session 7 Barney Deliverables

- [x] Cold-start memory loaded
- [x] SSD-FRAMEWORK.md re-read
- [x] All SSD docs scanned and read
- [x] SSD pipeline code inventory complete
- [x] Coverage metrics assessed
- [x] Gap analysis to 95% complete
- [x] Sprint prioritization confirmed
- [x] Revenue timeline established
- [x] Risk assessment complete
- [x] SSD Pipeline V1 Design Spec written
- [x] Background monitoring: ticket status verified
- [ ] Background monitoring: Discord #wti-pipeline report — cannot verify (no Discord read access)
- [ ] Background monitoring: Gazoo 2 AM audit — cannot verify (no Discord read access)

---

*Barney — Chief of Pipeline, Slate Rock & Gravel Co. 🪨*
*Session 7 — 2026-03-23*
