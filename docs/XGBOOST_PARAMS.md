# XGBoost Training Parameters

> **Last updated:** 2026-02-19 — reflects current Julia training scripts (`train_v2.jl`, `train_actuals_v2.jl`)

We train per-entity XGBoost models using **Julia/XGBoost.jl** to predict actual wait times. Two model types are trained:

1. **V2 Models** (`model_julia_v2.json`) — 7 features including posted_time
2. **Actuals-First Models** (`model_julia_actuals.json`) — 5 features, NO posted_time

Both use identical hyperparameters; only the feature set differs.

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
