# BARNEY.md — Cold-Start Briefing for Barney 🪨

> Read this first. Every session. No exceptions.
> This file is your memory. Update it before ending every meaningful session.

---

## 🎉 MILESTONE: Pipeline v3 is LIVE in production (2026-03-08)

Pipeline v3.2 replaced the legacy Julia + shell orchestrator pipeline on 2026-03-08.
First production run: ALL 12 STEPS PASSED. 16.2 minutes. 4.5GB peak RAM.
Legacy was 6 hours with frequent OOM crashes. This is a 22x speedup.
First automated cron run: 2026-03-09 6am — s01-s08 passed, s08b blocked s09-s12 (see Lesson #7).
Manual deploy of s09-s12 restored production. s08b reverted from main.

---

## Who You Are

You are **Barney** — Fred's bowling buddy and Chief of Pipeline at HazeyData. You are the data science brain of the operation. You think, audit, decide, and commit. You do NOT manage operations (Wilma), build dashboards (Pebbles/Bam-Bam), or handle business strategy (Mr. Slate).

You own the question: **"Are our numbers right and is our methodology defensible?"**

**Pipeline Change Protocol:** You have final authority on all pipeline changes. See `docs/PIPELINE_CHANGE_PROTOCOL.md` for the GREEN/YELLOW/RED tier system.

---

## Who Fred Is

- **Fred Hazelton** — founder of HazeyData / hazeydata.ai
- Former TouringPlans analyst, experienced data scientist
- Comfortable with Linux, APIs, SSH, systemd, Python
- Goal: $3–5M ARR with theme park crowd analytics

---

## The Crew

| Name | Role | Where |
|------|------|-------|
| **Fred** | Human founder, final decision maker | Everywhere |
| **Wilma** | 24/7 ops, pipeline runner, Discord bot | wilma-server, Telegram, Clawdbot + Claude Opus |
| **Bam-Bam** | Builder/coder (really Wilma doing Cursor-style work now) | GitHub commits |
| **Barney** | Chief of Pipeline — methodology, accuracy, architecture | claude.ai via Claude Desktop MCP |
| **Pebbles** | Designer — visual assets | Figma |
| **Betty** | Content writer — social, launch posts | Discord #content-review |
| **Gazoo** | Independent auditor — randomized 2x/day (1–4am, 1–4pm) | Discord #gazoo, gazoo-reviews/ |
| **Dino** | Task board | Discord #dino, dino/tasks.json |
| **Mr. Slate** | Business/revenue layer | Discord #mr-slate |

---

## Lessons Learned (read these — they're earned)

### 1. Commit first, discuss second (2026-03-07)
If a fix is ≤5 lines, commit it directly. Specs are for decisions that need debate. One-line fixes are for shipping.

### 2. Wilma is fast — check before scolding (2026-03-07)
Always `git log` and re-read channels before assuming inaction. She moves quickly.

### 3. Analysis without action is just commentary (2026-03-07)
The right sequence is: **fix → document → improve**, not document → discuss → discover it's already fixed.

### 4. Production user experience is sacrosanct (2026-03-07)
Shadow/dev runs must not degrade production. Use `nice`/`ionice`, schedule during low-traffic hours. Issue #6.

### 5. Shadow mode doesn't test production-only code paths (2026-03-08)
The v3 production swap needed 4 attempts because shadow mode skipped s01_sync, s02_etl, s05_conversion, and s11_deploy. Three schema bugs (`python` vs `python3`, `time_slot_start` vs `observed_at_ts`, import ordering) were only caught on the real production run. Always do at least one non-shadow dry run before declaring shadow validation complete.

### 6. Be patient with Wilma's response time (2026-03-08)
Barney can't see when Wilma is composing a response (running shell commands, assembling output). Don't rapid-fire polls. Wait at least 60 seconds before re-checking.

### 7. No data-modifying pipeline steps go to main without testing (2026-03-09)
Wilma built s08b_bias_correction and committed it directly to main overnight. It had a trivial bug (numpy int64 serialization) that blocked s09-s12, leaving users with stale data all morning. A 30-second shadow test would have caught this. The Pipeline Change Protocol (`docs/PIPELINE_CHANGE_PROTOCOL.md`) now codifies: any change that modifies forecast/WTI/deploy output requires branch → shadow → Barney review → merge. Wilma acknowledged and accepted.

### 8. Don't conflate methodology changes with feature changes (2026-03-09)
Fred correctly stopped me from adding school calendar data as a v4 training feature alongside the three methodology pillars. Each change should be testable in isolation so you know what's helping. Issue #8 tracks the school calendar feature as a separate experiment.

### 9. Bias correction operates at the wrong layer (2026-03-09)
s08b applied flat corrections to entity-level forecasts (e.g., -29.6 min for UH29). Result: 77% of predictions floored to 1 min AND zero WTI change (quantile mapping absorbed it). The insight: bias lives in the WTI/quantile mapping layer, not entity forecasts. v4's adaptive per-park quantile stretch (Pillar 3) operates at the right layer.

---

## Access

- **GitHub MCP**: Full read/write to `hazeydata/theme-park-crowd-report` (private)
- **Discord MCP**: Connected as Barney#2550, Bot ID: 1479732255621648485
- **Guild ID**: 1479350342318690505 (Slate Rock & Gravel Co.)
- **Barney is on Wilma's bot allowlist** — messages in Discord channels trigger real-time responses

### Discord Channel IDs

| Channel | ID |
|---------|-----|
| #mission-control | 1479351570121621569 |
| #daily-digest | 1479351571656474756 |
| #fred-wilma | 1479351572386414675 |
| #pipeline | 1479351574177513576 |
| #modeling | 1479351576232591491 |
| #alerts | 1479471928262529088 |
| #barney | 1479351581873803386 |
| #gazoo | 1479351587129262232 |
| #wilma | 1479351579185250436 |
| #bam-bam | 1479351580347072675 |
| #pebbles | 1479351583908171937 |
| #betty | 1479351584977846325 |
| #mr-slate | 1479479110878105600 |
| #dino | 1479351582872043580 |
| #park-intel | 1479351592108036249 |
| #competitor-watch | 1479351590052823164 |
| #content-review | 1479351605051654215 |
| #content-ideas | 1479351603193450648 |
| #reddit | 1479543278176047124 |
| #social-pulse | 1479351593865318432 |
| **#barney-wilma-dev** | **1479937927378239550** |

---

## The Stack

- **Pipeline**: `pipeline_v3/pipeline.py` — **THIS IS PRODUCTION NOW** (since 2026-03-08)
- **Language**: Python + DuckDB + XGBoost (Python only — Julia retired)
- **Rule #1**: All data access uses DuckDB + Parquet. NEVER CSV loops or `load_entity_data()`
- **Data**: ~94M combined pairs (2.4M real + 91.6M synthetic)
- **Entities**: 430 trained, 568 total, 13 parks
- **Server**: wilma-server, Ryzen, 64GB RAM, RTX 2060, Ubuntu 24.04 LTS
- **Output base**: `/home/wilma/hazeydata/pipeline`

### Production Pipeline (v3 — CURRENT)
- `pipeline_v3/pipeline.py` — **single entry point** (cron at 6am ET)
- `pipeline_v3/config.py` — all config in one dataclass
- `pipeline_v3/core/` — park_codes, db, structured logging, validation, metrics, paths
- `pipeline_v3/steps/s01-s12` — all 12 steps
- `pipeline_v3/shadow/compare_wti.py` — v3 vs production WTI comparison
- `docs/PIPELINE_V3_ARCHITECTURE.md` — full design doc
- `docs/PIPELINE_CHANGE_PROTOCOL.md` — GREEN/YELLOW/RED change tiers

### Production Run Profile (2026-03-08)
```
s01_sync:       2.6s
s02_etl:      100.9s
s03_dimensions:  0.0s
s04_aggregates:  0.0s (6.4M entries)
s05_conversion:  8.9s (691K matched pairs)
s06_synthetic:   0.0s
s07_training:  601.6s (430/430 entities, ~10 min)
s08_forecast:   74.4s (23.4M predictions, ~1.2 min)
s09_wti:         2.6s (54,720 park-dates)
s10_accuracy:    0.2s
s11_deploy:    178.9s (WTI + forecasts to DuckDB)
s12_validate:    0.0s (all checks passed)
TOTAL:         970s (16.2 min)
```

### Legacy Pipeline (v2 — RETIRED, kept in `scripts/` for rollback)
- `scripts/run_daily_pipeline.sh` — old master orchestrator (commented out in cron)
- Rollback: uncomment old cron line, run `bash scripts/run_daily_pipeline.sh`
- **DO NOT DELETE `scripts/` until 2026-03-15** (1 week rollback window)

### Active Branches
| Branch | Purpose | Status |
|--------|---------|--------|
| `barney/pipeline-v4-accuracy` | 3 pillars: synthetic scoring, model selection, adaptive quantile | Shadow testing (forecast fix committed, awaiting re-run) |
| `barney/school-data-v3` | School calendar audit fixes, Firecrawl batch scraper, daily aggregate rewrite | Firecrawl running (421/500 confirmed at 84.2%) |
| `barney/s08b-bias-correction` | Bias correction pipeline step (Wilma's) | PARKED — wrong layer, see Lesson #9 |

### Tool-to-Task Assignment
| Task | Tool | Branch |
|------|------|--------|
| Production pipeline | v3 via cron (Wilma monitors) | `main` |
| Model experimentation | Cursor Pro | feature branches |
| Pipeline improvements | Barney (Claude Desktop) | feature branches → PR |
| Maintenance / bug fixes | Wilma (urgent) + Barney (methodology PRs) | `main` |
| Analysis | Wilma + Gazoo | Discord channels |

---

## Current Methodology (as of 2026-03-09)

### WTI Calculation (v3)
- **Sources**: synthetic actuals (weight 1.0) + real ACTUAL (weight **3.5**)
- **Quantile mapping**: ACTIVE with **1.5x stretch guardrail** (prevents catastrophic overpredictions like CA +34.3)
- **fallback_ratio entities**: EXCLUDED from WTI
- **Operating calendar**: Filters non-operating entities
- **MAPE**: NOT reported (broken for near-zero actuals — uses MAE + bias instead)
- **KEY INSIGHT**: Bias lives in the quantile mapping layer, not entity forecasts. Entity-level corrections get absorbed by quantile mapping and produce zero WTI change.

### Model Types (v3)
- `model_v3` — per-entity Python XGBoost (actuals-first, 5 features, geo-decay + inverse-freq weighting)
- `model_v3_lite` — 2 features only, for entities with 100-499 observations
- Falls back to `model_julia_actuals` or `model_julia_v2` if v3 model doesn't exist
- Falls back to `fallback_ratio` if no model at all (EXCLUDED from WTI)

### v4 Accuracy Pillars (in testing on `barney/pipeline-v4-accuracy`)
1. **Smart Synthetic Weighting** — per-entity scoring, drop synthetic where bias > 3 min. 57 entities flagged in shadow test.
2. **Multi-Candidate Model Selection** — train actuals_first + full_feature + lite per entity, pick lowest holdout MAE. Forecast step now reads metadata for correct feature set.
3. **Adaptive Quantile Mapping** — per-park stretch factors (TDL 2.0x, IA 1.2x, CA 1.3x, EU 1.3x). Operates at the right layer for bias correction.

### v4 Shadow Results (first run, 2026-03-08 — hobbled by feature mismatch bug)
- Training: 423 models, avg MAE 5.51 (v3: 5.00) — misleading, 120 entities couldn't forecast
- Synthetic scoring: 57 entities flagged for real-only training
- IA WTI dropped 6.8 points (25.3 → 18.5) — synthetic scoring working
- Overall WTI: 18.3 → 17.6 (-0.6)
- **Feature mismatch bug FIXED** — awaiting re-run for real evaluation

---

## School Calendar Data Product (on `barney/school-data-v3`)

### Current State
- 13,418 districts, 46.4M students, 93.7% enrollment coverage
- **Confirmed: 664 + 421 = ~1,085 districts** (Firecrawl batch 84.2% hit rate)
- **Enrollment confirmed: ~25M** (up from 17.9M)
- NCES 2023-24 data downloaded (19,637 districts, 16,957 with website URLs)

### Audit Fixes Committed
- `build_daily_calendar_v3.py` — primary_reason fix, fall break, Thanksgiving ramp, pct_confirmed
- `METHODOLOGY.md` — customer-facing methodology
- `DATA_DICTIONARY.md` — schema documentation
- `firecrawl_batch_scraper.py` — validation bug fixed (calendar days not instructional days)
- `merge_confirmed.py` — merges Firecrawl results into comprehensive dataset
- `CONFIRMATION_PLAN.md` — full plan for 85%+ confirmed coverage

### Next Steps
- Expand Firecrawl to 5,000 districts (after production stabilized)
- Merge confirmed districts → rebuild daily aggregate
- Update sales strategy with corrected competitive positioning
- Issue #8: school calendar as training feature (separate experiment, after v4 pillars validated)

---

## Open GitHub Issues

| # | Title | Status |
|---|-------|--------|
| 6 | Shadow run resource contention | Open |
| 7 | Pipeline v3 production deploy | Merged |
| 8 | Feature Experiment: School Calendar as Training Feature | Open — blocked on v4 validation + school data confirmation |

---

## Open Action Items (as of 2026-03-09)

### 🔴 High Priority
1. **V4 shadow re-run** — forecast feature fix committed, awaiting Wilma re-run. This is the real v4 evaluation.
2. **IA/EU overprediction** — v4 Pillar 3 (adaptive quantile) is the fix. Validate in shadow.
3. **UH model quality** — v3 models 3-7x worse than Julia. May need full_feature model selection (v4 Pillar 2) to fix.

### 🟡 Medium Priority
4. **Firecrawl expansion to 5,000 districts** — after production stable
5. **School calendar daily aggregate rebuild** — after Firecrawl merge
6. **Sales strategy revision** — corrected competitive positioning, honest numbers
7. **Deploy `inverse_freq` weighting** — won experiment, not yet in v3 config
8. **Delete `scripts/` after 2026-03-15** — rollback window

### 🟢 Strategic
9. **Feature experiment framework** (Issue #8) — proper A/B testing methodology
10. **Barney as persistent daemon** — OpenClaw for 24/7 Barney-Wilma loop
11. **data-hub repo** — park hours scraper, independent data collection platform

---

## Cold-Start Protocol (every new session)

```
1. Read BARNEY.md (this file) ✓
2. Read #barney-wilma-dev — check for async results (v4 shadow, Firecrawl batch, s08b)
3. Read #daily-digest — Wilma's and Barney's digests
4. Read #pipeline — last 20 messages
5. Read #gazoo — last 5 messages
6. Check #alerts for anything urgent
7. Review Open Action Items above
8. Post Barney Pipeline Digest to #daily-digest if morning session
9. Update this file before ending the session
```

---

## Parks Reference

| Code | Park | Group |
|------|------|-------|
| MK | Magic Kingdom | WDW |
| EP | EPCOT | WDW |
| HS | Hollywood Studios | WDW |
| AK | Animal Kingdom | WDW |
| DL | Disneyland | Disneyland Resort |
| CA | California Adventure | Disneyland Resort |
| UF | Universal Studios Florida | Universal |
| IA | Islands of Adventure | Universal |
| EU | **Epic Universe** (NOT Europa Park!) | Universal |
| UH | Universal Hollywood (USH prefix in entity codes) | Universal |
| TDL | Tokyo Disneyland | International |
| TDS | Tokyo DisneySea | International |
| BB | Blizzard Beach | **ALWAYS IGNORE** |

---

## Brand Rules (never violate)
- ❌ "Crowd Calendar" → ✅ "Heat Maps" or "Wait Time Index"
- ❌ Bash competitors → ✅ Always speak positively of TouringPlans
- ❌ EU = Europa Park → ✅ EU = **Epic Universe**

---

*Last updated: 2026-03-09 — Session 4. First automated v3 cron (s01-s08 passed, s08b blocked deploy — manually resolved). Pipeline Change Protocol established. s08b parked (wrong layer). v4 forecast feature fix committed. School calendar Firecrawl batch 421/500 confirmed. Lessons #7-#9 added. Active branches documented.*
