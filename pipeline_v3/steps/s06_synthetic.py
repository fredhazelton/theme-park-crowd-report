"""Step 6: Synthetic Actuals Generation.

Applies the POSTED\u2192ACTUAL conversion model to all historical POSTED
observations to produce synthetic actual wait times.

During shadow phase: reads from production synthetic actuals.
"""

from __future__ import annotations

from pipeline_v3.config import PipelineConfig
from pipeline_v3.core.logging import PipelineLogger


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Generate or validate synthetic actuals."""

    log.info("=" * 60)
    log.info("STEP 6: SYNTHETIC ACTUALS")
    log.info("=" * 60)

    synth_dir = cfg.output_base / "synthetic_actuals"

    if cfg.shadow:
        log.info("Shadow mode: using production synthetic actuals")
        if synth_dir.exists():
            n_files = len(list(synth_dir.glob("*.parquet")))
            log.info(f"Found {n_files} synthetic actual parquet files")
            return {"rows": 0, "action": "validated", "files": n_files}
        else:
            log.warning("No synthetic actuals directory found")
            return {"rows": 0, "action": "missing"}

    # Production mode: generate synthetic actuals
    # TODO: implement direct generation using v3 conversion model
    log.info("Production synthetic generation not yet implemented in v3")
    return {"rows": 0, "action": "not_implemented"}
