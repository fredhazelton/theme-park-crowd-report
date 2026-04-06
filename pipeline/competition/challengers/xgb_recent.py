"""Challenger: xgb-recent

Hypothesis: Recent data matters more than old data. Halving the geo-decay half-life
from 730 to 365 days means data from 2 years ago has much less influence, giving
more weight to current crowd patterns (post-COVID, post-Genie+, post-Epic Universe).

Changes from baseline:
- geo_decay_halflife: 730 -> 365
- Everything else identical
"""

NAME = "xgb-recent"
DESCRIPTION = "Faster geo-decay (365 vs 730 day half-life)"
DATE_REGISTERED = "2026-04-06"

HYPERPARAMS = {}  # Use baseline hyperparams
FEATURES = None  # Use baseline features
GEO_DECAY_HALFLIFE = 365
