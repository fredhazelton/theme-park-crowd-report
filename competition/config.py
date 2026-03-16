"""
Central configuration for the model competition framework.
"""

from pathlib import Path

# --- Paths ---
PIPELINE_BASE = Path("/mnt/data/pipeline")
COMPETITION_BASE = PIPELINE_BASE / "competition"

LEDGER_DIR = COMPETITION_BASE / "ledger"
CHALLENGERS_DIR = COMPETITION_BASE / "challengers"
EVALUATION_DIR = COMPETITION_BASE / "evaluation"
BLENDS_DIR = COMPETITION_BASE / "blends"
ARCHIVE_DIR = COMPETITION_BASE / "archive"

# Existing pipeline paths
MODELS_DIR = PIPELINE_BASE / "models"
MATCHED_PAIRS_DIR = PIPELINE_BASE / "matched_pairs"
ACCURACY_DIR = PIPELINE_BASE / "accuracy"
ACCURACY_ARCHIVE_DIR = ACCURACY_DIR / "archive"
STATE_DIR = PIPELINE_BASE / "state"
ENCODING_MAPPINGS_PATH = STATE_DIR / "encoding_mappings.json"
SYNTHETIC_ACTUALS_DIR = PIPELINE_BASE / "synthetic_actuals"

# Project paths
PROJECT_ROOT = Path("/home/wilma/theme-park-crowd-report")

# --- Training ---
TRAINING_DATA_PATH = MATCHED_PAIRS_DIR / "actuals_training_v2.parquet"
ACTUALS_FEATURES = [
    "mins_since_6am",
    "mins_since_open",
    "date_group_id_encoded",
    "season_encoded",
    "season_year_encoded",
]
TARGET_COL = "actual_time"
GEO_DECAY_HALFLIFE_DAYS = 730  # 2 years

# --- Baseline XGBoost params (current production) ---
BASELINE_XGB_PARAMS = {
    "max_depth": 10,
    "learning_rate": 0.1,
    "n_estimators": 2000,
    "min_child_weight": 10,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "objective": "reg:squarederror",
    "random_state": 42,
    "tree_method": "hist",
    "n_jobs": -1,
}

# --- Tournament rules ---
MAX_ACTIVE_CHALLENGERS = 3  # plus baseline = 4 total
MIN_EVALUATION_DAYS = 14
ELIMINATION_THRESHOLD = 0.60  # Must beat baseline on 60% of entities to survive
BLEND_MAE_THRESHOLD = 0.10  # Models within 10% MAE are blend candidates

# --- Evaluation windows ---
ROLLING_WINDOWS = [7, 30, 90]

# --- Resource limits ---
TRAINING_TIMEOUT_SECONDS = 7200  # 2 hours
PREDICTION_TIMEOUT_SECONDS = 1800  # 30 minutes
