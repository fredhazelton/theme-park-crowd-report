# Model Competition Framework — Design Specification

**Version:** 1.0 APPROVED
**Date:** 2026-03-22
**Authors:** Barney (architect) + Fred (direction)
**Status:** APPROVED by Fred — Session 6

---

## Design Philosophy

**The baseline is sacred.** The 6 AM WTI pipeline runs the baseline model. It does not know challengers exist. It does not wait for them, depend on them, or share any runtime state with them. If the competition framework catches fire, the baseline keeps running.

**Challengers earn their way in.** No model enters production without beating the baseline on real data over a minimum evaluation window. Intuition and single-day results don't count. 7-14 days of head-to-head comparison on the same actuals, same entities, same time horizons.

**Complete separation.** The competition framework has its own directory, its own cron, its own output paths, and its own accuracy evaluation. It reads the same input data as the baseline (fact tables, dimensions, operating calendar) but writes to a completely separate namespace. It is an experiment, not part of the pipeline.

---

## Architecture

```
pipeline/                          # PRODUCTION — do not touch
├── steps/s07_training.py          # Baseline training (sacred)
├── steps/s08_forecast.py          # Baseline forecast (sacred)
└── ...

pipeline/competition/              # EXPERIMENT — completely separate
├── __init__.py
├── config.py                      # Competition-specific config
├── registry.py                    # Challenger definitions
├── train_challenger.py            # Train a registered challenger
├── forecast_challenger.py         # Generate challenger predictions
├── evaluate.py                    # Head-to-head accuracy comparison
├── promote.py                     # Promote winner to baseline (manual trigger)
└── challengers/
    └── hypertuned_v1.py           # First challenger definition
```

### Output Namespace

```
{output_base}/competition/
├── models/{challenger_name}/{entity_code}/
│   ├── model_{challenger_name}.json
│   └── metadata_{challenger_name}.json
├── forecasts/{challenger_name}/
│   └── all_forecasts_{challenger_name}.parquet
├── accuracy/{challenger_name}/
│   ├── entity_daily_accuracy.parquet
│   └── accuracy_summary.json
└── reports/
    └── comparison_{date}.json
```

No file in `competition/` ever overwrites or reads from the baseline output paths. The only shared inputs are the raw data (fact tables, dimensions, operating calendar, synthetic actuals).

---

## Challenger Registry

Each challenger is a Python module in `pipeline/competition/challengers/` that defines:

```python
# challengers/hypertuned_v1.py

NAME = "hypertuned_v1"
DESCRIPTION = "Shallower trees, faster learning, inverse_freq weighting"
DATE_REGISTERED = "2026-03-22"

# What changes vs baseline
HYPERPARAMS = {
    "max_depth": 6,           # baseline: 10
    "eta": 0.3,               # baseline: 0.1
    "n_estimators": 500,      # baseline: 2000
    "early_stopping": 20,     # baseline: 20 (unchanged)
    "subsample": 0.8,         # baseline: 0.8 (unchanged)
    "colsample_bytree": 0.8,  # baseline: 0.8 (unchanged)
}

# Weighting change
WEIGHTING = {
    "method": "inverse_freq",
    "description": "weight = 1.0 / log2(n_real + 1) for synthetic, 1.0 for real",
}

# Same features as baseline (no new features)
FEATURES = None  # None = use baseline features

# Same geo-decay as baseline
GEO_DECAY_HALFLIFE = 730  # unchanged
```

The registry is declarative. Each challenger explicitly states what differs from baseline and what stays the same. This makes auditing trivial — Gazoo can read a challenger definition and know exactly what's being tested.

---

## Challenger #1: hypertuned_v1

**Hypothesis:** The baseline overfits on sparse entity-level data. Shallower trees with faster learning and fewer iterations will generalize better. Combined with inverse_freq weighting (which already won its experiment at MAE 6.96 vs 7.04), this should meaningfully reduce MAE.

**What changes:**

| Parameter | Baseline | Challenger | Rationale |
|-----------|----------|------------|----------|
| max_depth | 10 | 6 | Reduce overfitting on sparse entities |
| eta | 0.1 | 0.3 | Faster learning, fewer trees needed |
| n_estimators | 2000 | 500 | Fewer trees = less overfitting + faster training |
| Weighting | real=10x, synth=1x | inverse_freq | More real data → less synthetic influence |

**What stays the same:** All 5 features, geo-decay half-life (730), early stopping (20), subsample (0.8), colsample_bytree (0.8), entity set, training data sources.

**Prior evidence:** inverse_freq weighting showed MAE 6.96 vs 7.04 baseline in a previous experiment (documented in PIPELINE_V4_ACCURACY.md). The hyperparameter changes are a standard XGBoost overfitting reduction pattern.

---

## Daily Sequence

The competition framework runs AFTER the baseline pipeline, using the same data:

```
6:00 AM  — Baseline pipeline runs (s01-s12, untouched)
~7:00 AM — Baseline completes
7:05 AM  — s14_entity_diagnostics.py (baseline diagnostics)
7:07 AM  — s13_report.py (baseline report to #wti-pipeline)

7:30 AM  — Competition: train challengers (reads same training data)
~8:00 AM — Competition: generate challenger forecasts
8:05 AM  — Competition: evaluate (compare vs baseline on yesterday's actuals)
8:07 AM  — Competition: post comparison report to #wti-pipeline or #barney
```

The competition cron starts at 7:30 AM — 30 minutes after baseline completes. This ensures all baseline outputs are finalized before the competition reads shared input data.

---

## Evaluation

Head-to-head comparison uses the SAME actuals and the SAME evaluation methodology as the baseline:

1. Archive challenger forecasts daily (same as s10_accuracy does for baseline)
2. When actuals arrive, compare: for each (entity, date, time_slot), baseline prediction vs challenger prediction vs actual
3. Compute per-entity MAE, bias, and park-level rollups for both
4. Daily comparison report:

```
🏆 COMPETITION REPORT — 2026-03-29 (Day 7 of 14)

                    Baseline    hypertuned_v1    Delta
Overall MAE:        8.6         6.2              -27.9%  ⬇️
WTI MAE:            6.7         5.1              -23.9%  ⬇️
Bias:               +1.4        +0.3             -1.1    ⬇️
1-day MAE:          7.3         5.0              -31.5%  ⬇️
7-day MAE:          8.9         6.8              -23.6%  ⬇️

Entities where challenger wins: 312/420 (74.3%)
Entities where baseline wins:  108/420 (25.7%)

Worst challenger entities:
  Expedition Everest (AK01): challenger MAE 16.2 vs baseline 14.2 (+14%)
  ...

Status: EVALUATION IN PROGRESS (7/14 days)
```

---

## Promotion

Promotion is a **manual decision by Fred**, not automatic. After 7-14 days:

1. Barney reviews the comparison data and makes a recommendation
2. Fred approves or rejects
3. If approved: `promote.py` copies challenger model files to the baseline namespace, updates `config.py` hyperparameters, and the next 6 AM pipeline run uses the new baseline
4. The old baseline's accuracy data is preserved for historical comparison
5. The promoted model becomes the new baseline; the competition framework resets

**Promotion criteria (minimum):**
- Challenger MAE < Baseline MAE for at least 7 of the evaluation days
- Challenger wins on >60% of entities
- No catastrophic failures (no entity where challenger is >3x worse than baseline)
- Fred says yes

---

## What the Competition Framework Does NOT Do

- Does not modify any file in the baseline output paths
- Does not run during the 6-8 AM pipeline lock window
- Does not add features the baseline doesn't have (that's a separate challenger type)
- Does not auto-promote — Fred decides
- Does not slow down the baseline pipeline in any way

---

## Future Challengers (After hypertuned_v1)

Each enters the same way — a module in `challengers/` with explicit deltas:

- **day_of_week_v1** — Adds day-of-week as 6th feature (same hyperparams as baseline)
- **inverse_freq_only** — Just inverse_freq weighting, no hyperparameter changes (isolates the weighting effect)
- **shallow_only** — Just max_depth=6, no other changes (isolates the depth effect)
- **autoregressive_v1** — Adds yesterday's actual as feature for 1-7 day horizons

One challenger at a time. Clean comparisons. No stacking changes until individual effects are measured.

---

*Barney — Chief of Pipeline, Slate Rock & Gravel Co. 🪨*
*Designed with Fred — Session 6, March 22 2026*
