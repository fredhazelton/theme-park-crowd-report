"""Step 2: ETL + CSV\u2192Parquet conversion.

During shadow phase: reads from production parquet files (no separate ETL).
Post-swap: runs ETL and converts CSVs to Parquet.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pipeline_v3.config import PipelineConfig
from pipeline_v3.core.logging import PipelineLogger
from pipeline_v3.core.validation import require_file


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Run ETL and convert to parquet."""

    log.info("=" * 60)
    log.info("STEP 2: ETL + CSV\u2192PARQUET")
    log.info("=" * 60)

    if cfg.shadow:
        # Verify production parquet exists
        parquet_files = list(cfg.parquet_dir.glob("*.parquet"))
        if not parquet_files:
            log.error(f"No parquet files found at {cfg.parquet_dir}")
            raise FileNotFoundError(f"Shadow mode requires production parquet at {cfg.parquet_dir}")
        log.info(f"Shadow mode: using {len(parquet_files)} production parquet files")
        return {"rows": 0, "action": "skipped_shadow", "parquet_files": len(parquet_files)}

    # Production mode: run ETL scripts
    project_root = Path(cfg.output_base).parent.parent / "theme-park-crowd-report"
    etl_script = project_root / "scripts" / "run_etl.sh"
    convert_script = project_root / "scripts" / "convert_to_parquet.py"

    if etl_script.exists():
        with log.timed("ETL"):
            result = subprocess.run(
                ["bash", str(etl_script), "--output-base", str(cfg.output_base),
                 "--local-source", str(cfg.raw_data_dir)],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ETL failed: {result.stderr[:500]}")

    if convert_script.exists():
        with log.timed("CSV\u2192Parquet"):
            result = subprocess.run(
                ["python", str(convert_script)],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(f"CSV\u2192Parquet failed: {result.stderr[:500]}")

    parquet_files = list(cfg.parquet_dir.glob("*.parquet"))
    log.info(f"ETL complete: {len(parquet_files)} parquet files")
    return {"rows": 0, "action": "completed", "parquet_files": len(parquet_files)}
