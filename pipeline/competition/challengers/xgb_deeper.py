"""Challenger: xgb-deeper

Hypothesis: Deeper trees capture feature interactions that max_depth=10 misses.
More depth = more complex splits = potentially better fit on high-traffic entities
where crowd patterns are nonlinear.

Changes from baseline:
- max_depth: 10 -> 12
- Everything else identical
"""

NAME = "xgb-deeper"
DESCRIPTION = "Deeper trees (max_depth 12 vs 10)"
DATE_REGISTERED = "2026-04-06"

HYPERPARAMS = {
    "max_depth": 12,
    "eta": 0.1,
    "n_estimators": 2000,
    "early_stopping": 20,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
}

FEATURES = None  # Use baseline features
GEO_DECAY_HALFLIFE = 730
