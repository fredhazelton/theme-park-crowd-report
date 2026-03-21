"""Step 4: Posted Aggregates.

Builds median posted wait times by entity, date_group_id, and time_slot.
Used by forecast step for posted_time estimates and fallback predictions.

During shadow phase: reads from production aggregates.
"""

from __future__ import annotations

from pipeline.config import PipelineConfig
from pipeline.core.logging import PipelineLogger
from pipeline.core.validation import require_file, require_parquet_rows


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Build or validate posted aggregates."""

    log.info("=" * 60)
    log.info("STEP 4: POSTED AGGREGATES")
    log.info("=" * 60)

    agg_path = cfg.output_base / "aggregates" / "model_aggregates.parquet"

    if cfg.shadow:
        log.info("Shadow mode: validating production aggregates")
        try:
            n_rows = require_parquet_rows(agg_path, min_rows=10000, description="Model aggregates")
            log.info(f"Aggregates: {n_rows:,} entries \u2714")
            return {"rows": n_rows, "action": "validated"}
        except Exception as e:
            log.error(f"Aggregates validation failed: {e}")
            raise

    # Production mode: build aggregates
    # TODO: implement direct aggregate build (currently wraps existing script)
    log.info("Production aggregate build not yet implemented in v3")
    log.info("Using production aggregates from existing pipeline")

    if agg_path.exists():
        n_rows = require_parquet_rows(agg_path, min_rows=1, description="Aggregates")
        return {"rows": n_rows, "action": "used_existing"}

    return {"rows": 0, "action": "missing"}
