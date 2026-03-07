"""Pipeline v3 Configuration — Single source of truth.

All configuration lives here. No scattered constants, no env var surprises.
Override via CLI args to pipeline.py, not by editing this file in production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PipelineConfig:
    """All pipeline configuration in one place."""

    # === Paths ===
    output_base: Path = Path("/home/wilma/hazeydata/pipeline")
    raw_data_dir: Path = field(default=None)  # set in __post_init__
    fact_tables_dir: Path = field(default=None)
    parquet_dir: Path = field(default=None)
    dimension_dir: Path = field(default=None)
    models_dir: Path = field(default=None)
    forecast_dir: Path = field(default=None)
    wti_dir: Path = field(default=None)
    accuracy_dir: Path = field(default=None)
    logs_dir: Path = field(default=None)
    state_dir: Path = field(default=None)
    duckdb_path: Path = field(default=None)

    # === Shadow mode ===
    shadow: bool = False
    shadow_output_base: Path = field(default=None)

    # === Forecast ===
    forecast_days: int = 365
    forecast_workers: int = 1  # Sequential by default. Memory-safe.

    # === Training ===
    training_min_obs: int = 500
    training_min_obs_lite: int = 100
    training_max_depth: int = 10
    training_eta: float = 0.1
    training_rounds: int = 2000
    training_early_stopping: int = 20
    geo_decay_halflife_days: int = 730

    # === WTI ===
    real_actual_weight: float = 3.5  # TODO: switch to inverse_freq when validated
    synthetic_weight: float = 1.0
    wti_min_wait: float = 5.0  # Floor for WTI values
    exclude_fallback_ratio: bool = True
    quantile_mapping: bool = True
    quantile_mapping_max_stretch: float = 1.5  # Guardrail: max 50% stretch

    # === Conversion model ===
    conversion_retrain_day: int = 0  # 0=Monday
    conversion_holdout_fraction: float = 0.15
    conversion_max_mae_regression: float = 1.0  # Only deploy if MAE doesn't worsen by >1 min

    # === Accuracy ===
    report_mape: bool = False  # MAPE is broken for near-zero actuals. Use MAE.

    # === Infrastructure ===
    memory_limit_gb: float = 50.0  # Stay under this on a 62GB box
    duckdb_read_only: bool = True  # All queries read-only; single write step at end

    # === Parks ===
    parks: list[str] = field(default_factory=lambda: [
        "MK", "EP", "HS", "AK",  # WDW
        "DL", "CA",               # Disneyland Resort
        "UF", "IA", "EU",         # Universal Orlando
        "UH",                     # Universal Hollywood
        "TDL", "TDS",             # Tokyo
    ])
    ignore_parks: list[str] = field(default_factory=lambda: ["BB"])  # Blizzard Beach

    def __post_init__(self):
        """Derive paths from output_base."""
        base = self.output_base
        if self.shadow:
            base = self.shadow_output_base or (base.parent / "pipeline_v3_shadow")
            self.shadow_output_base = base

        self.raw_data_dir = self.raw_data_dir or base / "raw"
        self.fact_tables_dir = self.fact_tables_dir or base / "fact_tables"
        self.parquet_dir = self.parquet_dir or base / "fact_tables" / "parquet"
        self.dimension_dir = self.dimension_dir or base / "dimension_tables"
        self.models_dir = self.models_dir or base / "models"
        self.forecast_dir = self.forecast_dir or base / "curves" / "forecast_parquet"
        self.wti_dir = self.wti_dir or base / "wti"
        self.accuracy_dir = self.accuracy_dir or base / "accuracy"
        self.logs_dir = self.logs_dir or base / "logs"
        self.state_dir = self.state_dir or base / "state"
        self.duckdb_path = self.duckdb_path or base / "tpcr_live.duckdb"


def load_config(**overrides) -> PipelineConfig:
    """Create config with optional overrides."""
    return PipelineConfig(**overrides)
