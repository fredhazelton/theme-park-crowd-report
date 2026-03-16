"""
Challenger Management — Register, discover, train, and run challengers.

A challenger is a directory under /mnt/data/pipeline/competition/challengers/
with:
  - challenger.yaml  (metadata)
  - train.py         (training script)
  - predict.py       (prediction script)
  - model/           (model artifacts, created by train.py)
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .config import (
    CHALLENGERS_DIR,
    ARCHIVE_DIR,
    TRAINING_DATA_PATH,
    TRAINING_TIMEOUT_SECONDS,
    PREDICTION_TIMEOUT_SECONDS,
    MAX_ACTIVE_CHALLENGERS,
    ACTUALS_FEATURES,
    TARGET_COL,
)
from .ledger import submit_predictions

logger = logging.getLogger(__name__)


class ChallengerConfig:
    """Parsed challenger.yaml metadata."""

    def __init__(self, path: Path):
        self.path = path
        self.dir = path.parent

        with open(path) as f:
            self._data = yaml.safe_load(f)

        self.id: str = self._data["id"]
        self.name: str = self._data.get("name", self.id)
        self.description: str = self._data.get("description", "")
        self.approach: str = self._data.get("approach", "unknown")
        self.category: str = self._data.get("category", "unknown")
        self.author: str = self._data.get("author", "unknown")
        self.created: str = self._data.get("created", "")
        self.status: str = self._data.get("status", "active")
        self.training_script: str = self._data.get("training_script", "train.py")
        self.predict_script: str = self._data.get("predict_script", "predict.py")
        self.xgb_params: dict = self._data.get("xgb_params", {})
        self.features: list[str] = self._data.get("features", ACTUALS_FEATURES)
        self.notes: str = self._data.get("notes", "")

    def to_dict(self) -> dict:
        return self._data.copy()


def discover_challengers(status_filter: str | None = "active") -> list[ChallengerConfig]:
    """
    Find all registered challengers.

    Args:
        status_filter: Only return challengers with this status (None for all)

    Returns:
        List of ChallengerConfig objects
    """
    CHALLENGERS_DIR.mkdir(parents=True, exist_ok=True)
    challengers = []

    for yaml_path in sorted(CHALLENGERS_DIR.glob("*/challenger.yaml")):
        try:
            config = ChallengerConfig(yaml_path)
            if status_filter is None or config.status == status_filter:
                challengers.append(config)
        except Exception as e:
            logger.warning(f"Failed to load {yaml_path}: {e}")

    return challengers


def get_challenger(challenger_id: str) -> ChallengerConfig | None:
    """Get a specific challenger by ID."""
    yaml_path = CHALLENGERS_DIR / challenger_id / "challenger.yaml"
    if yaml_path.exists():
        return ChallengerConfig(yaml_path)
    return None


def train_challenger(
    challenger_id: str,
    training_data_path: Path | str | None = None,
    timeout: int | None = None,
    venv_python: str | None = None,
) -> dict:
    """
    Train a challenger model.

    Args:
        challenger_id: The challenger to train
        training_data_path: Path to training data (default: standard actuals training)
        timeout: Training timeout in seconds
        venv_python: Path to Python interpreter (default: project venv)

    Returns:
        Dict with training result metadata
    """
    config = get_challenger(challenger_id)
    if config is None:
        return {"status": "error", "message": f"Challenger {challenger_id} not found"}

    if training_data_path is None:
        training_data_path = TRAINING_DATA_PATH
    if timeout is None:
        timeout = TRAINING_TIMEOUT_SECONDS
    if venv_python is None:
        venv_python = str(Path("/home/wilma/theme-park-crowd-report/.venv/bin/python"))

    train_script = config.dir / config.training_script
    model_dir = config.dir / "model"
    model_dir.mkdir(parents=True, exist_ok=True)

    if not train_script.exists():
        return {"status": "error", "message": f"Training script not found: {train_script}"}

    logger.info(f"Training challenger '{challenger_id}' (timeout: {timeout}s)")
    start_time = time.time()

    try:
        result = subprocess.run(
            [
                venv_python,
                str(train_script),
                "--training-data", str(training_data_path),
                "--model-output", str(model_dir),
                "--challenger-config", str(config.path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(config.dir),
            env={**os.environ, "PYTHONPATH": str(Path("/home/wilma/theme-park-crowd-report"))},
        )

        elapsed = time.time() - start_time

        if result.returncode == 0:
            logger.info(f"Training completed for '{challenger_id}' in {elapsed:.1f}s")
            return {
                "status": "success",
                "challenger_id": challenger_id,
                "elapsed_seconds": round(elapsed, 1),
                "stdout": result.stdout[-2000:] if result.stdout else "",
            }
        else:
            logger.error(f"Training failed for '{challenger_id}': {result.stderr[-500:]}")
            return {
                "status": "error",
                "challenger_id": challenger_id,
                "elapsed_seconds": round(elapsed, 1),
                "returncode": result.returncode,
                "stderr": result.stderr[-2000:] if result.stderr else "",
            }

    except subprocess.TimeoutExpired:
        logger.error(f"Training timed out for '{challenger_id}' after {timeout}s")
        return {
            "status": "timeout",
            "challenger_id": challenger_id,
            "timeout_seconds": timeout,
        }
    except Exception as e:
        logger.error(f"Training error for '{challenger_id}': {e}")
        return {"status": "error", "challenger_id": challenger_id, "message": str(e)}


def run_challenger_predictions(
    challenger_id: str,
    prediction_dates: list[str] | None = None,
    entity_codes: list[str] | None = None,
    timeout: int | None = None,
    venv_python: str | None = None,
) -> pd.DataFrame:
    """
    Run a challenger's predict script and submit results to the ledger.

    Args:
        challenger_id: The challenger to run
        prediction_dates: Dates to predict (default: today + tomorrow)
        entity_codes: Entities to predict (default: all with models)
        timeout: Prediction timeout in seconds
        venv_python: Path to Python interpreter

    Returns:
        DataFrame of predictions
    """
    config = get_challenger(challenger_id)
    if config is None:
        logger.error(f"Challenger {challenger_id} not found")
        return pd.DataFrame()

    if timeout is None:
        timeout = PREDICTION_TIMEOUT_SECONDS
    if venv_python is None:
        venv_python = str(Path("/home/wilma/theme-park-crowd-report/.venv/bin/python"))

    predict_script = config.dir / config.predict_script
    model_dir = config.dir / "model"

    if not predict_script.exists():
        logger.error(f"Predict script not found: {predict_script}")
        return pd.DataFrame()

    if not model_dir.exists():
        logger.error(f"Model directory not found: {model_dir} — train first!")
        return pd.DataFrame()

    # Build args
    args = [
        venv_python,
        str(predict_script),
        "--model-dir", str(model_dir),
        "--challenger-config", str(config.path),
    ]
    if prediction_dates:
        args.extend(["--dates", ",".join(prediction_dates)])
    if entity_codes:
        args.extend(["--entities", ",".join(entity_codes)])

    logger.info(f"Running predictions for '{challenger_id}'")
    start_time = time.time()

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(config.dir),
            env={**os.environ, "PYTHONPATH": str(Path("/home/wilma/theme-park-crowd-report"))},
        )

        elapsed = time.time() - start_time

        if result.returncode != 0:
            logger.error(f"Prediction failed for '{challenger_id}': {result.stderr[-500:]}")
            return pd.DataFrame()

        # Read predictions output file
        output_file = model_dir / "latest_predictions.parquet"
        if not output_file.exists():
            # Try CSV fallback
            output_file = model_dir / "latest_predictions.csv"

        if output_file.exists():
            if output_file.suffix == ".parquet":
                predictions = pd.read_parquet(output_file)
            else:
                predictions = pd.read_csv(output_file)

            # Submit to ledger
            n_submitted = submit_predictions(predictions, challenger_id)
            logger.info(
                f"Challenger '{challenger_id}': {n_submitted} predictions "
                f"submitted in {elapsed:.1f}s"
            )
            return predictions
        else:
            logger.error(f"No prediction output file found for '{challenger_id}'")
            return pd.DataFrame()

    except subprocess.TimeoutExpired:
        logger.error(f"Prediction timed out for '{challenger_id}' after {timeout}s")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Prediction error for '{challenger_id}': {e}")
        return pd.DataFrame()


def retire_challenger(challenger_id: str, reason: str = "") -> bool:
    """
    Retire a challenger (move to archive, update status).
    """
    config = get_challenger(challenger_id)
    if config is None:
        logger.error(f"Challenger {challenger_id} not found")
        return False

    # Update status in YAML
    config._data["status"] = "retired"
    config._data["retired_at"] = datetime.utcnow().isoformat()
    config._data["retirement_reason"] = reason

    with open(config.path, "w") as f:
        yaml.dump(config._data, f, default_flow_style=False)

    logger.info(f"Challenger '{challenger_id}' retired: {reason}")
    return True


def create_challenger_from_template(
    challenger_id: str,
    name: str,
    description: str,
    xgb_params: dict | None = None,
    features: list[str] | None = None,
    approach: str = "hyperparameter_variant",
    category: str = "gradient_boosting",
    notes: str = "",
) -> Path:
    """
    Create a new challenger directory from the standard template.

    Returns:
        Path to the new challenger directory
    """
    challenger_dir = CHALLENGERS_DIR / challenger_id
    if challenger_dir.exists():
        raise ValueError(f"Challenger directory already exists: {challenger_dir}")

    challenger_dir.mkdir(parents=True)
    (challenger_dir / "model").mkdir()

    # Write challenger.yaml
    config = {
        "id": challenger_id,
        "name": name,
        "description": description,
        "approach": approach,
        "category": category,
        "author": "wilma",
        "created": datetime.utcnow().strftime("%Y-%m-%d"),
        "status": "active",
        "training_script": "train.py",
        "predict_script": "predict.py",
    }
    if xgb_params:
        config["xgb_params"] = xgb_params
    if features:
        config["features"] = features
    if notes:
        config["notes"] = notes

    with open(challenger_dir / "challenger.yaml", "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    # Copy template scripts
    template_dir = Path("/home/wilma/theme-park-crowd-report/competition/templates")
    for script in ["train.py", "predict.py"]:
        src = template_dir / script
        if src.exists():
            import shutil
            shutil.copy(src, challenger_dir / script)
        else:
            logger.warning(f"Template {script} not found at {src}")

    logger.info(f"Created challenger '{challenger_id}' at {challenger_dir}")
    return challenger_dir
