"""Step 1: S3 Sync.

Syncs raw wait time data from S3 to local storage.

During shadow phase: reads from production data (no separate sync needed).
Post-swap: runs sync_s3_data.sh or equivalent Python implementation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pipeline.config import PipelineConfig
from pipeline.core.logging import PipelineLogger


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Sync data from S3."""

    log.info("=" * 60)
    log.info("STEP 1: S3 SYNC")
    log.info("=" * 60)

    if cfg.shadow:
        log.info("Shadow mode: using production data, no separate sync needed")
        return {"rows": 0, "action": "skipped_shadow"}

    sync_script = Path(cfg.output_base).parent.parent / "theme-park-crowd-report" / "scripts" / "sync_s3_data.sh"
    if sync_script.exists():
        with log.timed("S3 sync"):
            result = subprocess.run(
                ["bash", str(sync_script), "--output-base", str(cfg.output_base)],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                log.error(f"S3 sync failed: {result.stderr[:500]}")
                raise RuntimeError(f"S3 sync failed with code {result.returncode}")
            log.info("S3 sync complete")
    else:
        log.warning(f"Sync script not found at {sync_script} \u2014 skipping")

    return {"rows": 0, "action": "synced"}
