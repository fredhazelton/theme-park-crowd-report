#!/usr/bin/env python3
"""Pipeline v3 — Single entry point.

Usage:
    python pipeline_v3/pipeline.py                        # Full run
    python pipeline_v3/pipeline.py --shadow               # Shadow mode
    python pipeline_v3/pipeline.py --step s09_wti         # Single step
    python pipeline_v3/pipeline.py --step s07_training --park MK  # Single park
    python pipeline_v3/pipeline.py --output-base /path    # Custom output
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timezone
from importlib import import_module
from pathlib import Path

# Ensure pipeline_v3 is importable
if str(Path(__file__).parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline_v3.config import load_config
from pipeline_v3.core.logging import PipelineLogger
from pipeline_v3.core.metrics import PipelineMetrics
from pipeline_v3.core.paths import log_events_path
from pipeline_v3.steps import STEP_ORDER


def main():
    parser = argparse.ArgumentParser(description="HazeyData Pipeline v3")
    parser.add_argument("--output-base", type=Path, default=None)
    parser.add_argument("--shadow", action="store_true", help="Shadow mode: compare, don't deploy")
    parser.add_argument("--step", type=str, default=None, help="Run a single step (e.g. s09_wti)")
    parser.add_argument("--park", type=str, default=None, help="Limit to one park (e.g. MK)")
    parser.add_argument("--days", type=int, default=None, help="Override forecast days")
    args = parser.parse_args()

    # Build config
    overrides = {}
    if args.output_base:
        overrides["output_base"] = args.output_base
    if args.shadow:
        overrides["shadow"] = True
    if args.days:
        overrides["forecast_days"] = args.days
    cfg = load_config(**overrides)

    run_date = date.today().isoformat()
    log = PipelineLogger("pipeline", cfg.logs_dir)
    metrics = PipelineMetrics(
        run_date=run_date,
        run_start=datetime.now(timezone.utc).isoformat(),
        shadow_mode=cfg.shadow,
    )

    log.info("=" * 60)
    log.info(f"HAZEYDATA PIPELINE v3 {'(SHADOW MODE)' if cfg.shadow else ''}")
    log.info(f"Run date: {run_date}")
    log.info(f"Output: {cfg.output_base}")
    if cfg.shadow:
        log.info(f"Shadow output: {cfg.shadow_output_base}")
    log.info("=" * 60)

    start_time = time.time()
    metrics.status = "running"

    # Determine which steps to run
    if args.step:
        if args.step not in STEP_ORDER:
            log.error(f"Unknown step: {args.step}. Available: {STEP_ORDER}")
            return 1
        steps = [args.step]
    else:
        steps = STEP_ORDER

    # Execute steps
    failed = False
    for step_name in steps:
        step_log = PipelineLogger(step_name, cfg.logs_dir)
        metrics.start_step(step_name)

        try:
            module = import_module(f"pipeline_v3.steps.{step_name}")
            if not hasattr(module, "run"):
                log.warning(f"Step {step_name} has no run() function — skipping")
                metrics.skip_step(step_name, "no run() function")
                continue

            result = module.run(cfg, step_log)
            rows_out = result.get("rows", 0) if isinstance(result, dict) else 0
            metrics.end_step(step_name, rows_out=rows_out)

            # Save step events
            step_log.save_events(log_events_path(cfg, run_date))

        except Exception as e:
            log.error(f"Step {step_name} FAILED: {e}")
            metrics.fail_step(step_name, str(e))
            failed = True
            # In shadow mode, continue on failure. In production, stop.
            if not cfg.shadow:
                break

    # Finalize
    total = round(time.time() - start_time, 2)
    metrics.total_duration_sec = total
    metrics.status = "failed" if failed else "done"

    log.info("=" * 60)
    log.info(f"PIPELINE {'FAILED' if failed else 'COMPLETE'} in {total}s")
    log.info("=" * 60)

    # Save metrics
    metrics_path = cfg.logs_dir / f"v3_metrics_{run_date}.json"
    metrics.save(metrics_path)
    log.info(f"Metrics saved: {metrics_path}")

    # Save all pipeline-level events
    log.save_events(log_events_path(cfg, run_date))

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
