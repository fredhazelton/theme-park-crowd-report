"""Step 7: Model Training — v4 with smart synthetic weighting + model selection.

v3: One model per entity (actuals-first, 5 features).
v4: Three candidates per entity, best MAE wins. Synthetic quality scoring
    filters out entities where synthetic data hurts accuracy.

Note: School calendar feature integration is planned as a separate
experiment (Issue #8) after v4's three pillars are validated.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import xgboost as xgb
except ImportError:
    xgb = None

from pipeline.config import PipelineConfig
from pipeline.core.logging import PipelineLogger
from pipeline.core.park_codes import entity_to_park
from pipeline.core.validation import ValidationError
from pipeline.models.model_selector import train_best_model
from pipeline.models.synthetic_scorer import score_synthetic_quality


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Train per-entity XGBoost models with v4 accuracy improvements."""

    if xgb is None:
        raise ValidationError("XGBoost is required. pip install xgboost")

    log.info("=" * 60)
    log.info("STEP 7: MODEL TRAINING (v4 — multi-candidate + synthetic scoring)")
    log.info("=" * 60)

    # === Pillar 1: Score synthetic quality ===
    with log.timed("synthetic quality scoring"):
        synth_scores = score_synthetic_quality(cfg, log)
    n_real_only = sum(1 for s in synth_scores.values() if not s["use_synthetic"])
    log.info(f"Synthetic scoring: {n_real_only} entities flagged for real-only training")

    # Look for per-park training data (preferred) or single file
    actuals_dir = cfg.output_base / "matched_pairs" / "actuals_training_v2"
    actuals_single = cfg.output_base / "matched_pairs" / "actuals_training_v2.parquet"

    park_files = sorted(actuals_dir.glob("*.parquet")) if actuals_dir.is_dir() else []
    use_park_chunks = len(park_files) > 0

    if not use_park_chunks and not actuals_single.exists():
        raise ValidationError(
            f"No training data found at {actuals_dir} or {actuals_single}."
        )

    log.info(f"Training data: {'per-park chunks' if use_park_chunks else 'single file'}")

    # Scan entity counts
    with log.timed("scan entity counts"):
        entity_counts = _scan_entity_counts(park_files if use_park_chunks else [actuals_single])

    eligible = [e for e, c in entity_counts.items() if c >= cfg.training_min_obs_lite]
    log.info(f"Eligible entities: {len(eligible)}")

    # Group by park
    park_entity_map: dict[str, list[str]] = {}
    for e in eligible:
        park = entity_to_park(e)
        park_entity_map.setdefault(park, []).append(e)

    # Train with v4 model selection
    successful = 0
    failed = 0
    total_mae = 0.0
    method_counts: dict[str, int] = {}

    for park_code in sorted(park_entity_map.keys()):
        park_entities = park_entity_map[park_code]

        with log.timed(f"train park {park_code} ({len(park_entities)} entities)"):
            if use_park_chunks:
                park_file = actuals_dir / f"{park_code}.parquet"
                if not park_file.exists():
                    log.warning(f"  No training data for park {park_code}")
                    continue
                park_df = pd.read_parquet(park_file)
            else:
                park_df = pd.read_parquet(actuals_single)
                park_df = park_df[park_df["entity_code"].isin(park_entities)]

            # === Issue #48: Apply per-park min_training_year cutoff ===
            # Filters BOTH real and synthetic data from contaminated years.
            min_year = cfg.get_min_training_year(park_code)
            if min_year > 0 and "park_date" in park_df.columns:
                before = len(park_df)
                park_df = park_df[pd.to_datetime(park_df["park_date"]).dt.year >= min_year]
                dropped = before - len(park_df)
                if dropped > 0:
                    log.info(f"  {park_code}: min_training_year={min_year} dropped {dropped:,} rows ({dropped/before*100:.1f}%)")

            for entity_code in park_entities:
                try:
                    entity_df = park_df[park_df["entity_code"] == entity_code].copy()

                    # === Pillar 1: Filter synthetic if quality is bad ===
                    if entity_code in synth_scores and not synth_scores[entity_code]["use_synthetic"]:
                        if "is_synthetic" in entity_df.columns:
                            before = len(entity_df)
                            entity_df = entity_df[~entity_df["is_synthetic"].astype(bool)]
                            after = len(entity_df)
                            if before != after:
                                log.info(f"  {entity_code}: dropped {before - after} synthetic rows (bias={synth_scores[entity_code]['bias']:.1f})")

                    # === Pillar 2: Multi-candidate model selection ===
                    min_obs = cfg.training_min_obs_lite
                    result = train_best_model(
                        entity_code, entity_df, cfg.models_dir, cfg, min_samples=min_obs
                    )

                    if result is not None:
                        successful += 1
                        total_mae += result["mae"]
                        method = result.get("method", "unknown")
                        method_counts[method] = method_counts.get(method, 0) + 1
                    else:
                        failed += 1

                except Exception as e:
                    log.warning(f"  {entity_code}: {e}")
                    failed += 1

            del park_df

    avg_mae = total_mae / successful if successful > 0 else 0

    log.info("=" * 60)
    log.info("TRAINING COMPLETE (v4)")
    log.info(f"Successful: {successful}, Failed: {failed}")
    log.info(f"Average MAE: {avg_mae:.2f} min")
    log.info(f"Model selection breakdown:")
    for method, count in sorted(method_counts.items()):
        pct = count / successful * 100 if successful else 0
        log.info(f"  {method}: {count} entities ({pct:.1f}%)")
    log.metric("training_successful", successful)
    log.metric("training_failed", failed)
    log.metric("training_avg_mae", round(avg_mae, 2))
    log.info("=" * 60)

    return {
        "rows": successful,
        "successful": successful,
        "failed": failed,
        "avg_mae": round(avg_mae, 2),
        "method_counts": method_counts,
        "real_only_entities": n_real_only,
    }


def _scan_entity_counts(parquet_files: list[Path]) -> dict[str, int]:
    """Count observations per entity across parquet files."""
    counts: dict[str, int] = {}
    for path in parquet_files:
        if not path.exists():
            continue
        df = pd.read_parquet(path, columns=["entity_code"])
        for entity, count in df["entity_code"].value_counts().items():
            counts[entity] = counts.get(entity, 0) + count
    return counts
