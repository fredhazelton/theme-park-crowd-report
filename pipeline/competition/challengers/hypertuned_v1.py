"""Challenger: hypertuned_v1

Hypothesis: The baseline overfits on sparse entity-level data. 
Shallower trees with faster learning and fewer iterations will generalize better.
Combined with inverse_freq weighting (which already won its experiment at MAE 6.96 vs 7.04).

Changes from baseline:
- max_depth: 10 → 6 (reduce overfitting)  
- eta: 0.1 → 0.3 (faster learning)
- n_estimators: 2000 → 500 (fewer trees = less overfitting)
- weighting: real=10x,synth=1x → inverse_freq (more real data = less synthetic influence)

Everything else identical: features, geo-decay, early stopping, subsample, colsample_bytree.
"""

NAME = "hypertuned_v1"
DESCRIPTION = "Shallower trees, faster learning, inverse_freq weighting"
DATE_REGISTERED = "2026-03-22"

# Hyperparameter deltas from baseline
HYPERPARAMS = {
    "max_depth": 6,           # baseline: 10
    "eta": 0.3,               # baseline: 0.1  
    "n_estimators": 500,      # baseline: 2000
    "early_stopping": 20,     # baseline: 20 (unchanged)
    "subsample": 0.8,         # baseline: 0.8 (unchanged)
    "colsample_bytree": 0.8,  # baseline: 0.8 (unchanged)
}

# Weighting method change
WEIGHTING = {
    "method": "inverse_freq",
    "description": "weight = 1.0 / log2(n_real + 1) for synthetic, 1.0 for real",
}

# Same features as baseline (no new features)
FEATURES = None  # None = use baseline features

# Same geo-decay as baseline  
GEO_DECAY_HALFLIFE = 730  # unchanged from baseline