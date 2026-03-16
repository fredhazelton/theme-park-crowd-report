"""
Baseline Enrollment — Enroll the current production pipeline as the "baseline" challenger.

Reads existing forecast archive parquet files and extracts per-entity daily mean
predicted actual wait times, then submits them to the prediction ledger.
Also handles creating the baseline challenger.yaml and backfilling actuals.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .config import (
    CHALLENGERS_DIR,
    ACCURACY_ARCHIVE_DIR,
    PIPELINE_BASE,
    BASELINE_XGB_PARAMS,
    ACTUALS_FEATURES,
    MODELS_DIR,
)
from .ledger import submit_predictions, backfill_actuals, read_ledger

logger = logging.getLogger(__name__)

BASELINE_ID = "baseline"


def ensure_baseline_registered() -> Path:
    """
    Ensure the baseline challenger is registered with challenger.yaml.
    
    Returns:
        Path to baseline challenger directory
    """
    baseline_dir = CHALLENGERS_DIR / BASELINE_ID
    baseline_dir.mkdir(parents=True, exist_ok=True)

    yaml_path = baseline_dir / "challenger.yaml"
    if not yaml_path.exists():
        config = {
            "id": BASELINE_ID,
            "name": "Production Pipeline (Actuals-First V4)",
            "description": (
                "Current production XGBoost pipeline. Julia-trained, per-entity models "
                "with geo-decay weighting and actuals-first methodology."
            ),
            "approach": "production_pipeline",
            "category": "gradient_boosting",
            "author": "pipeline",
            "created": datetime.utcnow().strftime("%Y-%m-%d"),
            "status": "active",
            "xgb_params": {
                "max_depth": 10,
                "eta": 0.1,
                "num_round": 2000,
            },
            "features": ACTUALS_FEATURES,
            "notes": (
                "This is the production pipeline auto-enrolled as baseline. "
                "Model artifacts are symlinked from the production models directory."
            ),
        }

        with open(yaml_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False)
        logger.info(f"Registered baseline challenger at {yaml_path}")

    # Symlink to production models if not already linked
    model_link = baseline_dir / "model"
    if not model_link.exists():
        model_link.symlink_to(MODELS_DIR)
        logger.info(f"Symlinked baseline model → {MODELS_DIR}")

    return baseline_dir


def extract_daily_entity_predictions(forecast_path: Path) -> pd.DataFrame:
    """
    Extract per-entity daily mean predicted actual wait from a forecast archive parquet.
    
    The forecast archives contain 5-minute time slot predictions. We compute
    the daily mean predicted_actual per entity to get a single number for
    the competition ledger.
    
    Args:
        forecast_path: Path to forecast_{date}.parquet
    
    Returns:
        DataFrame with [entity_code, prediction_date, predicted_actual]
    """
    df = pd.read_parquet(forecast_path)
    
    # Compute daily mean predicted_actual per entity per date
    daily = (
        df.groupby(["entity_code", "park_date"])["predicted_actual"]
        .mean()
        .reset_index()
    )
    daily.columns = ["entity_code", "prediction_date", "predicted_actual"]
    
    return daily


def enroll_baseline_from_archives(
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    """
    Backfill baseline predictions from forecast archive parquets.
    
    Reads all forecast_{date}.parquet files in the accuracy archive directory,
    extracts daily mean predictions per entity, and submits them to the ledger.
    
    Args:
        start_date: Earliest date to process (ISO format)
        end_date: Latest date to process (ISO format)
    
    Returns:
        Total number of predictions submitted
    """
    ensure_baseline_registered()
    
    archive_files = sorted(ACCURACY_ARCHIVE_DIR.glob("forecast_*.parquet"))
    if not archive_files:
        logger.warning(f"No forecast archives found in {ACCURACY_ARCHIVE_DIR}")
        return 0
    
    total_submitted = 0
    
    for forecast_file in archive_files:
        # Extract date from filename
        file_date = forecast_file.stem.replace("forecast_", "")
        
        if start_date and file_date < start_date:
            continue
        if end_date and file_date > end_date:
            continue
        
        try:
            daily_preds = extract_daily_entity_predictions(forecast_file)
            if daily_preds.empty:
                continue
            
            n = submit_predictions(daily_preds, BASELINE_ID)
            total_submitted += n
            logger.info(f"Baseline: {n} predictions from {forecast_file.name}")
            
        except Exception as e:
            logger.warning(f"Failed to process {forecast_file.name}: {e}")
    
    logger.info(f"Baseline enrollment complete: {total_submitted} total predictions")
    return total_submitted


def enroll_baseline_today(forecast_path: Path | None = None) -> int:
    """
    Enroll today's baseline predictions (called as part of daily pipeline).
    
    Args:
        forecast_path: Path to today's forecast parquet (auto-detected if None)
    
    Returns:
        Number of predictions submitted
    """
    ensure_baseline_registered()
    
    if forecast_path is None:
        today = date.today().isoformat()
        forecast_path = ACCURACY_ARCHIVE_DIR / f"forecast_{today}.parquet"
    
    if not forecast_path.exists():
        logger.warning(f"Today's forecast not found: {forecast_path}")
        return 0
    
    daily_preds = extract_daily_entity_predictions(forecast_path)
    if daily_preds.empty:
        return 0
    
    return submit_predictions(daily_preds, BASELINE_ID)


def backfill_baseline_actuals() -> int:
    """
    Backfill actual wait times from the entity_daily_accuracy.parquet file.
    
    This file contains the average actual wait per entity per day, which is
    exactly what we need for the ledger's actual_wait field.
    
    Returns:
        Number of rows updated
    """
    accuracy_path = PIPELINE_BASE / "accuracy" / "entity_daily_accuracy.parquet"
    if not accuracy_path.exists():
        logger.warning(f"Entity accuracy file not found: {accuracy_path}")
        return 0
    
    acc = pd.read_parquet(accuracy_path)
    
    # Extract entity-level daily mean actuals
    actuals = acc[["entity_code", "park_date", "avg_actual"]].copy()
    actuals.columns = ["entity_code", "prediction_date", "actual_wait"]
    
    # Also try to get actuals from the synthetic_actuals or other sources
    # for broader coverage
    return backfill_actuals(actuals)


def get_baseline_status() -> dict:
    """Get status info about the baseline enrollment."""
    baseline_dir = CHALLENGERS_DIR / BASELINE_ID
    
    status = {
        "registered": (baseline_dir / "challenger.yaml").exists(),
        "model_linked": (baseline_dir / "model").exists(),
    }
    
    # Check ledger
    ledger = read_ledger(challenger_ids=[BASELINE_ID])
    if not ledger.empty:
        status["ledger_rows"] = len(ledger)
        status["date_range"] = {
            "start": str(ledger["prediction_date"].min()),
            "end": str(ledger["prediction_date"].max()),
        }
        status["entities"] = int(ledger["entity_code"].nunique())
        status["has_actuals"] = int(ledger["actual_wait"].notna().sum())
    else:
        status["ledger_rows"] = 0
    
    return status
