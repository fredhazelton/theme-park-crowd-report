"""Pipeline Run Report — standalone post-run script.

Generates a structured run report from pipeline metrics and accuracy data.
Runs AFTER the pipeline completes so it has access to the full metrics JSON
including step timings, row counts, and pass/fail status.

Usage (standalone):
    cd ~/theme-park-crowd-report
    .venv/bin/python -m pipeline.steps.s13_report
    .venv/bin/python -m pipeline.steps.s13_report --output-base /path/to/pipeline

Usage (from Wilma's post-run cron):
    7 7 * * * cd /home/wilma/theme-park-crowd-report && .venv/bin/python -m pipeline.steps.s13_report --output-base /home/wilma/hazeydata/pipeline

Output:
    {logs_dir}/pipeline_report_{date}.md — formatted report for Discord posting

NOT in STEP_ORDER. This is a consumer of pipeline output, not a pipeline step.
The pipeline produces data; the report reads it after the fact.

Design: docs/PIPELINE_V4_DESIGN.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


# Human-readable step names for the report
STEP_DISPLAY_NAMES = {
    "s01_sync": "Sync",
    "s02_etl": "ETL",
    "s03_dimensions": "Dimensions",
    "s04_aggregates": "Aggregates",
    "s05_conversion": "Conversion",
    "s06_synthetic": "Synthetic",
    "s07_training": "Training",
    "s08_forecast": "Forecast",
    "s09_wti": "WTI",
    "s10_accuracy": "Accuracy",
    "s11_deploy": "Deploy",
    "s12_validate": "Validate",
}


def _format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 1:
        return "<1s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if secs == 0:
        return f"{minutes}m"
    return f"{minutes}m{secs:02d}s"


def _status_icon(status: str) -> str:
    """Map step status to emoji."""
    return {
        "done": "\u2705",
        "failed": "\u274c",
        "skipped": "\u23ed\ufe0f",
        "running": "\U0001f7e1",
    }.get(status, "\u2753")


def _load_metrics(logs_dir: Path, run_date: str) -> dict | None:
    """Load the pipeline metrics JSON for today's run."""
    metrics_path = logs_dir / f"pipeline_metrics_{run_date}.json"
    if not metrics_path.exists():
        return None
    with open(metrics_path) as f:
        return json.load(f)


def _load_accuracy_summary(accuracy_dir: Path) -> dict:
    """Load the accuracy summary JSON."""
    path = accuracy_dir / "accuracy_summary.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _build_report(metrics: dict, accuracy: dict) -> str:
    """Build the formatted run report string."""
    run_date = metrics.get("run_date", date.today().isoformat())
    status = metrics.get("status", "unknown")
    total_sec = metrics.get("total_duration_sec", 0)
    steps = metrics.get("steps", {})

    status_icon = "\u2705 COMPLETE" if status == "done" else "\u274c FAILED"
    lines = []
    lines.append(f"\U0001f4ca **PIPELINE RUN REPORT \u2014 {run_date}**")
    lines.append("")
    lines.append(f"**Status:** {status_icon} ({_format_duration(total_sec)})")
    lines.append("")

    # --- DATA HEALTH ---
    etl_step = steps.get("s02_etl", {})
    new_obs = etl_step.get("new_observations", None)
    # rows_out from the metrics captures the return dict's "rows" value
    if new_obs is None:
        new_obs = etl_step.get("rows_out", None)

    lines.append("**DATA HEALTH:**")
    if new_obs is not None and new_obs == 0:
        lines.append("  \u26a0\ufe0f **NO NEW DATA YESTERDAY** \u2014 data feed may be broken")
    elif new_obs is not None and new_obs > 0:
        lines.append(f"  New observations yesterday: {new_obs:,}")
    elif new_obs is not None and new_obs < 0:
        lines.append("  New observations: \u2753 (count failed)")
    else:
        lines.append("  New observations: N/A")

    sync_step = steps.get("s01_sync", {})
    lines.append(f"  S3 sync: {_status_icon(sync_step.get('status', 'unknown'))} ({_format_duration(sync_step.get('duration_sec', 0))})")
    lines.append("")

    # --- MODELS & FORECASTS ---
    train_step = steps.get("s07_training", {})
    forecast_step = steps.get("s08_forecast", {})
    wti_step = steps.get("s09_wti", {})

    lines.append("**MODELS & FORECASTS:**")

    train_rows = train_step.get("rows_out", 0)
    lines.append(f"  Training: {train_rows} baseline models ({_format_duration(train_step.get('duration_sec', 0))})")

    forecast_rows = forecast_step.get("rows_out", 0)
    lines.append(f"  Forecast: {forecast_rows:,} predictions ({_format_duration(forecast_step.get('duration_sec', 0))})")

    wti_rows = wti_step.get("rows_out", 0)
    lines.append(f"  WTI: {wti_rows:,} park-dates ({_format_duration(wti_step.get('duration_sec', 0))})")
    lines.append("")

    # --- ACCURACY ---
    lines.append("**ACCURACY:**")
    mae = accuracy.get("overall_mae")
    bias = accuracy.get("overall_bias")
    wti_mae = accuracy.get("wti_mae")
    mae_1d = accuracy.get("mae_1day")
    mae_7d = accuracy.get("mae_7day")
    mae_30d = accuracy.get("mae_30day")
    dates_eval = accuracy.get("dates_evaluated", 0)
    entities_eval = accuracy.get("entities_evaluated", 0)

    if mae is not None:
        lines.append(f"  Overall MAE: {float(mae):.1f} min (bias: {float(bias or 0):+.1f})")
    else:
        lines.append("  Overall MAE: awaiting first evaluation")

    if wti_mae is not None:
        lines.append(f"  WTI MAE: {float(wti_mae):.1f} min")

    if mae_1d is not None:
        parts = []
        if mae_1d is not None:
            parts.append(f"1-day: {float(mae_1d):.1f}")
        if mae_7d is not None:
            parts.append(f"7-day: {float(mae_7d):.1f}")
        if mae_30d is not None:
            parts.append(f"30-day: {float(mae_30d):.1f}")
        if parts:
            lines.append(f"  {' | '.join(parts)}")

    if dates_eval:
        lines.append(f"  Evaluated: {dates_eval} dates, {entities_eval} entities")
    lines.append("")

    # --- TIMING ---
    lines.append("**TIMING:**")
    timing_parts = []
    for step_name, step_data in steps.items():
        display = STEP_DISPLAY_NAMES.get(step_name, step_name)
        icon = _status_icon(step_data.get("status", "unknown"))
        dur = _format_duration(step_data.get("duration_sec", 0))
        timing_parts.append(f"{display} {icon} {dur}")

    # Format as two rows of ~6 steps each
    mid = len(timing_parts) // 2
    if timing_parts:
        lines.append(f"  {' \u2192 '.join(timing_parts[:mid])}")
        lines.append(f"  {' \u2192 '.join(timing_parts[mid:])}")
    lines.append("")

    return "\n".join(lines)


def run_report(output_base: Path) -> str | None:
    """Generate the Pipeline Run Report. Returns the report text, or None on failure."""
    from pipeline.config import load_config

    cfg = load_config(output_base=output_base)
    run_date = date.today().isoformat()

    # Load metrics
    metrics = _load_metrics(cfg.logs_dir, run_date)
    if metrics is None:
        print(f"No metrics file found at {cfg.logs_dir}/pipeline_metrics_{run_date}.json")
        return None

    # Load accuracy summary
    accuracy = _load_accuracy_summary(cfg.accuracy_dir)

    # Build report
    report = _build_report(metrics, accuracy)

    # Save report to file
    report_path = cfg.logs_dir / f"pipeline_report_{run_date}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report)

    print(f"Report saved: {report_path}")
    print()
    print(report)

    return report


# Legacy interface for pipeline.py (if ever re-added to STEP_ORDER)
def run(cfg, log) -> dict:
    """Pipeline step interface (not currently used — runs standalone)."""
    from pipeline.core.logging import PipelineLogger

    run_date = date.today().isoformat()
    metrics = _load_metrics(cfg.logs_dir, run_date)
    if metrics is None:
        log.info("No metrics file found — building report from accuracy data only")
        metrics = {"run_date": run_date, "status": "done", "total_duration_sec": 0, "steps": {}}

    accuracy = _load_accuracy_summary(cfg.accuracy_dir)
    report = _build_report(metrics, accuracy)

    report_path = cfg.logs_dir / f"pipeline_report_{run_date}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report)

    log.info(f"Report saved: {report_path}")
    return {"rows": 0, "report_path": str(report_path)}


if __name__ == "__main__":
    # Standalone execution — the intended usage path
    _repo_root = str(Path(__file__).parent.parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

    parser = argparse.ArgumentParser(description="Generate Pipeline Run Report")
    parser.add_argument(
        "--output-base", type=Path,
        default=Path("/home/wilma/hazeydata/pipeline"),
        help="Pipeline output base directory",
    )
    args = parser.parse_args()

    result = run_report(args.output_base)
    sys.exit(0 if result else 1)
