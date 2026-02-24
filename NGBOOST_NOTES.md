# NGBoost Heteroscedastic Model Notes

## Branch: `feature/ngboost-heteroscedastic`

## Problem Statement
XGBoost compresses predictions toward the mean, producing a narrow forecast WTI range (~5-17) when historical reality ranges ~2-56. This makes the year-view heatmap useless (wall of same-colored red). Quantile mapping was added as a stopgap on `main`.

## Solution
NGBoost predicts both mean (μ) AND variance (σ²) for each entity's wait times using a Normal distribution. This enables:
1. **Wider prediction range** — naturally reflects busy vs quiet days
2. **Uncertainty quantification** — know which predictions to trust
3. **Distribution-aware WTI** — weight entities by inverse variance

## Files Added/Modified

### New Scripts
- `scripts/train_ngboost_models.py` — Per-entity NGBoost model training
- `scripts/forecast_ngboost.py` — Forecast generation with μ and σ

### Modified Scripts
- `scripts/calculate_wti_simple.py` — Added NGBoost-aware WTI aggregation:
  - Detects `ngboost_forecasts.parquet` automatically
  - Uses inverse-variance weighted mean (confident entities matter more)
  - Skips quantile mapping when NGBoost is active (not needed)

### Output Files
- `/mnt/data/pipeline/models/{entity}/ngboost_model.pkl` — Pickled model
- `/mnt/data/pipeline/models/{entity}/ngboost_metadata.json` — Training metadata
- `/mnt/data/pipeline/curves/forecast_parquet/ngboost_forecasts.parquet` — Forecasts with μ and σ

## Architecture

```
Training Data (all_pairs_v2.parquet)
    ↓
train_ngboost_models.py (per-entity NGBRegressor)
    ↓
ngboost_model.pkl + ngboost_metadata.json
    ↓
forecast_ngboost.py (predict μ and σ for 365+ days)
    ↓
ngboost_forecasts.parquet (predicted_wait, predicted_std, predicted_actual)
    ↓
calculate_wti_simple.py (inverse-variance weighted WTI)
    ↓
wti.parquet
```

## Key Design Decisions

1. **Additive, not replacement** — XGBoost pipeline continues working. NGBoost is a parallel path.
2. **Same features** — Uses identical feature set as XGBoost V2 models for fair comparison.
3. **Geo-decay weighting** — Sample weights decay with age (half-life 730 days), matching XGBoost pipeline.
4. **Inverse-variance WTI** — Entities with lower predicted σ contribute more to park WTI.
5. **Pickle format** — NGBoost doesn't support JSON serialization like XGBoost.

## Hyperparameters

```python
n_estimators=500
learning_rate=0.04
minibatch_frac=0.8
natural_gradient=True
Distribution=Normal
```

## Training Performance (initial test)
- MK01: 62K rows, MAE=8.8, σ̄=12.2
- MK05: 56K rows, MAE=8.6, σ̄=18.0
- MK191: 3.2K rows, MAE=10.8, σ̄=31.3

Training time: ~20-25 sec/entity (with 500 estimators on 50-60K rows).
Full pipeline (~500+ entities): estimated 30-45 min with 8 workers.

## Forecast Output Comparison
- **NGBoost** predicted_wait range: 0.1 - 117.3 (for MK entities)
- **XGBoost** predicted_actual range: ~5 - 50 (compressed toward mean)
- NGBoost provides predicted_std: 3.4 - 200.0 (uncertainty varies with context)

## Known Issues / Warnings

1. **overflow in ngboost Normal.py** — `RuntimeWarning: overflow encountered in square` during training. This is a known NGBoost behavior with extreme variance values; it doesn't affect model quality.
2. **Training speed** — NGBoost is ~5x slower than XGBoost for same data. Full entity training takes 30-45 min vs 5-10 min for XGBoost via Julia.
3. **Model size** — ~1.3 MB per entity (pickle). ~650 MB total for 500 entities. Acceptable.

## Next Steps
- [ ] Full pipeline training run (all 735 has_posted entities)
- [ ] Compare NGBoost vs XGBoost WTI distributions across parks
- [ ] Add `--actuals-first` support for NGBoost (remove posted_time dependency)
- [ ] Tune hyperparameters per entity (or per park group)
- [ ] Add early stopping to reduce training time
- [ ] Integrate into nightly pipeline cron
