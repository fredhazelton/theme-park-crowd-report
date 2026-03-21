"""Pipeline steps — one module per stage.

Each step exports a `run(cfg, log)` function that:
1. Validates its inputs
2. Does its work
3. Validates its outputs
4. Returns a summary dict

Steps are executed in order by pipeline.py.
"""

# Step execution order
STEP_ORDER = [
    "s01_sync",
    "s02_etl",
    "s03_dimensions",
    "s04_aggregates",
    "s05_conversion",
    "s06_synthetic",
    "s07_training",
    "s08_forecast",
    "s09_wti",
    "s10_accuracy",
    "s11_deploy",
    "s12_validate",
]
