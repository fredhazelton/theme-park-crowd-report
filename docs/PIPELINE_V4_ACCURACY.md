# Pipeline v4 — Accuracy Through Intelligence

> **Author**: Barney (Chief of Pipeline)
> **Status**: DESIGN + BUILDING
> **Goal**: Improve MAE from 6.69 to <5.0 through smarter data selection and model tuning
> **Approach**: Methodology improvements on top of v3 infrastructure. Same 12 steps, smarter decisions.

---

## Why

v3 solved infrastructure: 16 min runtime, no OOM, no Julia, no crashes.
But the numbers haven't improved. WTI MAE is still 6.69, bias +1.48.
IA overpredicts by +17.9, EU by +15.9. UH models got worse.

The pipeline is fast and reliable. Now it needs to be *smart*.

---

## The Three Pillars

### Pillar 1: Smart Synthetic Weighting

**Problem**: Every entity gets the same synthetic actuals treatment.
But synthetic hurts ~40% of entities — MK41 goes from MAE 3.62 to 5.96 with synthetic.

**Solution**: Per-entity synthetic quality scoring.

For each entity, compute:
```
synthetic_bias = mean(synthetic_actual - real_actual)
```
where both exist for the same time slot.

Decision rule:
- If |synthetic_bias| > 3 min → train on real_only (synthetic is misleading)
- If |synthetic_bias| <= 3 min → train on combined (synthetic adds volume)
- Store scores in `state/synthetic_quality.json` for transparency

**Implementation**: New function in `s07_training.py` that runs before training loop.
Query matched slots where both synthetic and real actuals exist, compute per-entity bias,
filter training data accordingly.

**Expected impact**: ~5% MAE improvement across affected entities.

### Pillar 2: Model Selection Intelligence

**Problem**: v3 trains one model per entity (actuals-first, 5 features) and uses it.
But for UH entities, the v2-style model with `posted_time` as a feature was 3-7x better.

**Solution**: Train multiple candidates per entity, pick the best.

For each entity with sufficient data, train:
1. **Actuals-first** (5 features, no posted_time) — current v3 default
2. **Full-feature** (7 features, includes posted_time + hour_of_day) — v2 style
3. **Lite** (2 features) — for low-data entities

Evaluate each on the same holdout set. Deploy the one with lowest MAE.
Store the selection reason in metadata for audit.

**Implementation**: Modify `_train_entity()` to train 2-3 candidates and pick winner.
Add `model_selection_method` to metadata JSON.

**Expected impact**: Fixes UH regression (3-7x), likely improves 10-20% of entities
where posted_time carries signal that actuals-first misses.

### Pillar 3: Adaptive Quantile Mapping

**Problem**: v3 uses a global 1.5x stretch cap. TDL needs more (real seasonal extremes),
IA needs less (consistently overpredicted). CA had a +34.3 blowup from uncapped mapping.

**Solution**: Learn optimal stretch factor per park from historical accuracy.

Weekly (or on retrain), for each park:
1. Compute forecast WTI for past 30 days (with mapping at various stretch levels)
2. Compare against actual WTI for those days
3. Pick the stretch factor that minimized MAE
4. Store in `state/quantile_mapping_params.json`

Default to 1.5x for parks with insufficient history.

**Implementation**: New `_tune_quantile_mapping()` in `s09_wti.py`.
Runs before the mapping step, reads recent accuracy data, optimizes per-park.

**Expected impact**: Prevents catastrophic overprediction (CA +34.3 class events)
while allowing real seasonal variance (TDL Golden Week). Est. 1-2 point MAE improvement
on the worst days.

---

## Additional Improvements

### inverse_freq weighting (quick win)
Already won the experiment (MAE 6.96 vs 7.04). Just needs to be set in config.
```python
# config.py change:
real_actual_weight: float = 1.0  # was 3.5
use_inverse_freq: bool = True    # new
```
The inverse_freq formula: `weight = 1.0 / log2(n_real + 1)` for synthetic,
`weight = 1.0` for real. More real data → less synthetic influence.

### Entity-specific fallback strategy
For entities where v3 model is worse than Julia's (like UH), fall back to the
better model automatically. Check both `model_v3.json` and `model_julia_actuals.json`,
compare holdout MAE, use the winner.

### Accuracy-weighted WTI
Instead of simple average across entities, weight each entity's contribution to WTI
by its model's validation MAE. High-confidence entities get more weight.
Entities with MAE > 15 get downweighted.

---

## Implementation Plan

All changes go in `pipeline_v3/` on the `barney/pipeline-v4-accuracy` branch.
Same shadow testing process as v3:

1. **Phase 1**: Implement Pillar 1 (synthetic quality scoring) + inverse_freq
2. **Phase 2**: Implement Pillar 2 (model selection) 
3. **Phase 3**: Implement Pillar 3 (adaptive quantile mapping)
4. **Shadow test**: Run with `--shadow` and compare MAE against v3 production
5. **Swap**: If v4 shadow MAE < v3 production MAE for 3+ days, merge and swap

Each pillar is independent — we can ship them one at a time.

---

## Success Metrics

| Metric | v3 Current | v4 Target |
|--------|-----------|----------|
| WTI MAE | 6.69 | <5.0 |
| WTI Bias | +1.48 | <±0.5 |
| IA Bias | +17.9 | <+5.0 |
| EU Bias | +15.9 | <+5.0 |
| UH MAE (v3 vs Julia) | 3-7x worse | Equal or better |
| Worst single-day error | +34.3 (CA) | <+15.0 |

---

*Barney — Chief of Pipeline. v3 solved speed. v4 solves accuracy. 🪨*
