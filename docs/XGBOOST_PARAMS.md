# XGBoost Training Parameters

> **Last updated:** 2026-03-04 — reflects all model types: per-entity (Julia), scope-scale, and conversion model

We train several XGBoost model types in the pipeline:

1. **V2 Models** (`model_julia_v2.json`) — Per-entity, 7 features including posted_time
2. **Actuals-First Models** (`model_julia_actuals.json`) — Per-entity, 5 features, NO posted_time
3. **Scope-Scale Group Models** (`model_scope_scale_*.json`) — Pooled by ride category, for EU cold-start
4. **POSTED→ACTUAL Conversion Model** (`models/_conversion/model.json`) — Global, converts POSTED to synthetic actuals

Per-entity V2 and actuals-first models use identical hyperparameters; only the feature set differs.

---

## Current Hyperparameters (Julia)

Defined in `julia-ml/train_v2.jl` and `julia-ml/train_actuals_v2.jl`:

| Parameter              | Value                   | Notes |
|------------------------|-------------------------|-------|
| `objective`            | `"reg:squarederror"`    | MSE-based (robust for wait time prediction) |
| `num_round`            | `2000`                  | Max boosting rounds (early stopping usually stops earlier) |
| `max_depth`            | `10`                    | Deeper trees for complex time-of-day patterns |
| `eta` (learning_rate)  | `0.1`                   | Standard learning rate |
| `subsample`            | `0.8`                   | Row subsampling per tree |
| `colsample_bytree`     | `0.8`                   | Column subsampling per tree |
| `min_child_weight`     | `1`                     | Minimum sum of instance weight in a child |
| `seed`                 | `42`                    | Reproducibility |
| `early_stopping_rounds`| `20`                    | Stop if no improvement on eval set for 20 rounds |
| `verbosity`            | `0`                     | Silent |

---

## Training Features

### V2 Model (7 features)
```
posted_time, mins_since_6am, mins_since_open, hour_of_day,
date_group_id_encoded, season_encoded, season_year_encoded
```

### Actuals-First Model (5 features)
```
mins_since_6am, mins_since_open,
date_group_id_encoded, season_encoded, season_year_encoded
```

The key difference: actuals-first models have **no dependency on posted_time**, meaning they can predict actual wait times from temporal features alone.

---

## Training Data Split

- **80/20 temporal split** — first 80% of rows (sorted by date) for training, last 20% for validation
- Early stopping uses the validation set (`watchlist = [(dtrain, "train"), (dval, "eval")]`)
- Typical models stop between 50-200 rounds (well under the 2000 max)

---

## Geo Decay Weights

Both model types use geographic/temporal decay weighting:
- **Half-life:** 730 days (newer observations weighted higher)
- **Real actuals:** 3.5× weight multiplier on top of geo decay
- Weights computed at training time, not stored in model files

---

## Lite Models (Fallback)

For entities with very few training samples (< threshold), a "lite" model is trained with fewer features:
- **V2 Lite:** `posted_time, mins_since_6am, mins_since_open, hour_of_day` (4 features)
- **Actuals Lite:** `mins_since_6am, mins_since_open` (2 features)

These are stored in the same model files but flagged in metadata (`model_label` contains "LITE").

---

## Conversion Model Parameters

Defined in `src/processors/posted_to_actual.py`. Trains a global POSTED→ACTUAL model used to generate synthetic actuals.

| Parameter              | Value (as of 2026-03-04) | Previous | Change Reason |
|------------------------|--------------------------|----------|---------------|
| `objective`            | `reg:absoluteerror`      | same     | MAE robust to outliers in POSTED data |
| `n_estimators`         | `2000`                   | same     | |
| `max_depth`            | `8`                      | `6`      | Needs depth for 272 entities × time × season |
| `learning_rate`        | `0.1`                    | same     | |
| `subsample`            | `0.8`                    | `0.5`    | Was starving trees of data, aligned with per-entity |
| `colsample_bytree`     | `0.8`                    | `1.0`    | Added column sampling, aligned with per-entity |
| `min_child_weight`     | `3`                      | `10`     | Was too conservative; couldn't learn entity-level patterns |
| `early_stopping_rounds`| `20`                     | `50`     | Aligned with per-entity models |
| **Geo-decay weights**  | **✅ Yes (730-day half-life)** | **❌ None** | **Critical fix: POSTED→ACTUAL ratio changes over time** |

### Conversion Model Features (14)
```
posted_time, posted_delta_15m, posted_delta_30m, posted_delta_60m,
posted_rolling_mean_30m, posted_rolling_mean_60m, posted_volatility_30m,
hour_of_day, mins_since_6am, mins_since_open,
entity_encoded, park_encoded, date_group_id_encoded, season_encoded
```

### Why Geo-Decay Matters for Conversion

The POSTED→ACTUAL ratio has shifted over time. Disney increasingly overestimates posted times in recent years:

| Period | Avg Actual/Posted Ratio |
|--------|------------------------|
| 2015–2018 | ~0.72–0.82 |
| 2019–2020 | ~0.67–0.69 |
| 2023–2025 | ~0.70–0.79 |

Without geo-decay, 1.5M training pairs from 2014 (ratio ~0.67) counted equally with recent data. The model learned a blended historical average instead of the current relationship. Entity-specific shifts (e.g., Na'vi River dropping from 0.79 to 0.58 ratio) were masked.

**Change history (2026-03-04):** Previous params were over-regularized — the model trained only 19 trees before early stopping. Root cause: `min_child_weight=10` + `subsample=0.5` double-regularization prevented learning entity/time-specific patterns. Combined with no geo-decay, the model produced a slightly refined historical average that systematically overestimated synthetic actuals by 8–17 minutes per hour for high-wait rides.

---

## Scope-Scale Group Model Parameters

Defined in `scripts/train_scope_scale_models.py`. Pooled models by ride category for EU cold-start.

| Parameter              | Value | Notes |
|------------------------|-------|-------|
| `max_depth`            | `6`   | Shallower — pooling across entities provides implicit regularization |
| `learning_rate`        | `0.1` | |
| `n_estimators`         | `500` | Lower max — pools have plenty of data, converges faster |
| `min_child_weight`     | `10`  | Conservative — diverse entities in one model |
| `subsample`            | `0.8` | |
| `colsample_bytree`     | `0.8` | |
| `early_stopping`       | `20`  | |
| **Geo-decay weights**  | ✅ Yes | |

---

## Legacy Reference

The original Julia pipeline (`run_trainer.jl` from attraction-io) used different parameters:

| Parameter            | Legacy | Current | Change Reason |
|----------------------|--------|---------|---------------|
| `max_depth`          | 6      | 10      | Deeper trees for richer patterns |
| `subsample`          | 0.5    | 0.8     | More data per tree, less variance |
| `colsample_bytree`   | 1.0    | 0.8     | Added column sampling for regularization |
| `min_child_weight`   | 10     | 1       | Allow finer splits |
| `objective`          | `reg:absoluteerror` | `reg:squarederror` | MSE gives better gradient signal |
| `early_stopping`     | None   | 20 rounds | Prevents overfitting, faster training |

---

## P95 Cap

**REMOVED** (2026-02-18, Fred's decision). Models tend to underpredict on busy days, and XGBoost is impervious to outliers. Capping at p95 was artificially limiting predictions.
