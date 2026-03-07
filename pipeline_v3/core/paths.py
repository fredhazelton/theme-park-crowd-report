"""Path utilities — resolve all file locations from config.

Every file the pipeline reads or writes is defined here.
No hardcoded paths in step modules.
"""

from __future__ import annotations

from pathlib import Path

from pipeline_v3.config import PipelineConfig


def entity_model_dir(cfg: PipelineConfig, entity_code: str) -> Path:
    """Path to a specific entity's model directory."""
    return cfg.models_dir / entity_code


def entity_model_path(cfg: PipelineConfig, entity_code: str) -> Path:
    """Path to entity's trained XGBoost model file."""
    return cfg.models_dir / entity_code / "model_v3.json"


def entity_metadata_path(cfg: PipelineConfig, entity_code: str) -> Path:
    """Path to entity's model metadata."""
    return cfg.models_dir / entity_code / "metadata_v3.json"


def conversion_model_path(cfg: PipelineConfig) -> Path:
    """Path to the POSTED→ACTUAL conversion model."""
    return cfg.models_dir / "_conversion" / "model_v3.json"


def conversion_model_backup_path(cfg: PipelineConfig) -> Path:
    """Path to the previous conversion model (rollback)."""
    return cfg.models_dir / "_conversion" / "model_v3_previous.json"


def forecast_output_path(cfg: PipelineConfig) -> Path:
    """Path to the combined forecast parquet."""
    return cfg.forecast_dir / "all_forecasts_v3.parquet"


def wti_output_path(cfg: PipelineConfig) -> Path:
    """Path to the WTI parquet."""
    return cfg.wti_dir / "wti_v3.parquet"


def log_events_path(cfg: PipelineConfig, run_date: str) -> Path:
    """Path to structured log events for a run."""
    return cfg.logs_dir / f"v3_events_{run_date}.jsonl"


def shadow_comparison_path(cfg: PipelineConfig, run_date: str) -> Path:
    """Path to shadow comparison report."""
    return cfg.accuracy_dir / f"v3_shadow_comparison_{run_date}.json"
