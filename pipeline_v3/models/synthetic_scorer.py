"""Per-entity synthetic quality scoring.

Pillar 1 of v4 accuracy improvements.

For each entity, computes the bias between synthetic actuals and real actuals
where both exist for the same time slots. Entities with |bias| > threshold
should be trained on real_only data.

Usage:
    from pipeline_v3.models.synthetic_scorer import score_synthetic_quality
    scores = score_synthetic_quality(cfg, log)
    # scores = {"MK01": {"bias": 1.2, "use_synthetic": True}, ...}
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pipeline_v3.config import PipelineConfig
from pipeline_v3.core.db import read_connection
from pipeline_v3.core.logging import PipelineLogger


def score_synthetic_quality(
    cfg: PipelineConfig,
    log: PipelineLogger,
    bias_threshold: float = 3.0,
) -> dict[str, dict]:
    """Score each entity's synthetic actual quality.

    Returns dict of {entity_code: {bias, mae, n_matched, use_synthetic}}.
    Saves results to state/synthetic_quality.json.
    """

    synth_dir = cfg.output_base / "synthetic_actuals"
    parquet_dir = cfg.parquet_dir

    if not synth_dir.exists() or not any(synth_dir.glob("*.parquet")):
        log.warning("No synthetic actuals found — cannot score quality")
        return {}

    synth_str = str(synth_dir).replace("\\", "/")
    parquet_str = str(parquet_dir).replace("\\", "/")

    # NOTE: Synthetic parquets use 'observed_at' (VARCHAR), not 'observed_at_ts' (TIMESTAMP).
    # Fact table parquets use 'observed_at_ts'. Must CAST synthetic column for EXTRACT to work.
    with read_connection() as con:
        df = con.execute(f"""
            WITH synth AS (
                SELECT entity_code, park_date,
                       EXTRACT(HOUR FROM CAST(observed_at AS TIMESTAMP)) as hour_bucket,
                       AVG(synthetic_actual) as synth_wait
                FROM read_parquet('{synth_str}/*.parquet')
                WHERE synthetic_actual > 0
                GROUP BY entity_code, park_date, hour_bucket
            ),
            real AS (
                SELECT entity_code, park_date,
                       EXTRACT(HOUR FROM observed_at_ts) as hour_bucket,
                       AVG(wait_time_minutes) as real_wait
                FROM read_parquet('{parquet_str}/*.parquet')
                WHERE wait_time_type = 'ACTUAL' AND wait_time_minutes > 0
                GROUP BY entity_code, park_date, hour_bucket
            )
            SELECT s.entity_code,
                   AVG(s.synth_wait - r.real_wait) as bias,
                   AVG(ABS(s.synth_wait - r.real_wait)) as mae,
                   COUNT(*) as n_matched
            FROM synth s
            INNER JOIN real r
                ON s.entity_code = r.entity_code
                AND s.park_date = r.park_date
                AND s.hour_bucket = r.hour_bucket
            GROUP BY s.entity_code
            HAVING COUNT(*) >= 20
        """).fetchdf()

    scores = {}
    for _, row in df.iterrows():
        entity = row["entity_code"]
        bias = float(row["bias"])
        mae = float(row["mae"])
        n = int(row["n_matched"])
        use_synthetic = abs(bias) <= bias_threshold

        scores[entity] = {
            "bias": round(bias, 2),
            "mae": round(mae, 2),
            "n_matched": n,
            "use_synthetic": use_synthetic,
        }

    n_real_only = sum(1 for s in scores.values() if not s["use_synthetic"])
    n_combined = sum(1 for s in scores.values() if s["use_synthetic"])
    log.info(f"Synthetic quality: {n_combined} entities use combined, {n_real_only} use real_only")

    # Save to state
    state_path = cfg.state_dir / "synthetic_quality.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        json.dump(scores, f, indent=2)
    log.info(f"Synthetic quality scores saved to {state_path}")

    return scores
