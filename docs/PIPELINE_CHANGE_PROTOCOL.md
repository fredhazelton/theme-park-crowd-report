# Pipeline Change Protocol

**Effective:** 2026-03-09  
**Owner:** Barney (Chief of Pipeline)  
**Approved by:** Fred (Founder)

---

## Purpose

This document defines what pipeline changes require review and testing before going to production. The goal is to ship fast while protecting users from bad data.

---

## Change Tiers

### 🟢 GREEN — Do without asking Barney

- Operational fixes (cron timing, file permissions, disk cleanup, process restarts)
- Monitoring and alerting improvements
- Data syncs (Discord, MC, scraper commits)
- Commits to non-pipeline directories (content, social, website, data/)
- Running shadow tests that Barney has already set up on a branch
- Emergency rollbacks (if production is serving bad data, revert first, ask later)

### 🟡 YELLOW — Tell Barney in #barney-wilma-dev, then proceed

- Bug fixes to existing pipeline steps where the fix is <5 lines AND doesn't change output logic
- Pulling branches and running scripts that Barney committed
- Updating reference data files (NCES enrollment, school calendar data, dimension tables)

### 🔴 RED — Must branch + shadow test + Barney review before merging to main

- Any **new** pipeline step
- Any change to training logic (s07), forecast logic (s08), WTI calculation (s09), or deploy logic (s11)
- Any change that modifies what data users see in the bot or API
- Any change to model selection, weighting schemes, or feature engineering
- Any change to the pipeline entry point (`pipeline.py`)
- Any change to `config.py` that affects model behavior

---

## The Process for RED Changes

1. **Branch:** Create a feature branch (e.g., `wilma/s08b-bias-correction`)
2. **Implement:** Write the code on the branch
3. **Shadow test:** Run with `--shadow` flag, compare output vs production
4. **Post results:** Share metrics in #barney-wilma-dev
5. **Barney reviews:** Barney checks the output and approves
6. **Merge:** Merge to main
7. **Monitor:** Watch the next production run for issues

This process takes ~1 hour, not days. The shadow infrastructure exists specifically to make this fast.

---

## Why This Exists

On 2026-03-09, a new pipeline step (s08b_bias_correction) was committed directly to main without testing. It had a trivial serialization bug (numpy int64 not JSON-serializable) that blocked WTI deployment, leaving users with stale data for hours.

A 30-second shadow test would have caught this. The process prevents hours of user-facing problems.

---

## Emergency Override

If Barney is unavailable and a RED change is urgently needed (e.g., pipeline is producing obviously wrong data and the fix is known):

1. Fix on a branch
2. Test manually against current data
3. Merge with a commit message explaining the urgency
4. Notify Barney at next opportunity
5. Fred can authorize emergency merges directly

---

*This protocol applies to all crew members who commit to `pipeline_v3/`. Operational scripts outside `pipeline_v3/` follow standard practices.*

🪨 Barney — Chief of Pipeline
