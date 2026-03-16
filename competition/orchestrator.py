"""
Competition Orchestrator — Daily pipeline integration.

This is the entry point called by the daily pipeline to:
1. Enroll baseline predictions for today
2. Run all active challenger predictions
3. Backfill actuals and score predictions
4. Update leaderboard
5. Check for blend opportunities
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .baseline import (
    ensure_baseline_registered,
    enroll_baseline_today,
    backfill_baseline_actuals,
)
from .challenger import (
    discover_challengers,
    run_challenger_predictions,
    train_challenger,
)
from .evaluation import (
    generate_leaderboard,
    find_blend_opportunities,
)
from .ledger import ledger_stats

logger = logging.getLogger(__name__)


def run_daily_competition(
    forecast_path: Path | None = None,
    prediction_dates: list[str] | None = None,
    skip_training: bool = True,
    skip_blends: bool = False,
) -> dict:
    """
    Run the full daily competition cycle.

    Called by the pipeline after forecasts are generated.

    Args:
        forecast_path: Path to today's baseline forecast parquet
        prediction_dates: Dates to predict (default: today)
        skip_training: Skip training step (training runs separately overnight)
        skip_blends: Skip blend analysis (expensive, run weekly)

    Returns:
        Summary dict of what happened
    """
    start_time = time.time()
    today = date.today().isoformat()

    if prediction_dates is None:
        prediction_dates = [today]

    summary = {
        "date": today,
        "steps": {},
        "errors": [],
    }

    # Step 1: Ensure baseline is registered
    logger.info("=" * 60)
    logger.info("COMPETITION: Step 1 — Enroll baseline")
    logger.info("=" * 60)
    try:
        ensure_baseline_registered()
        n_baseline = enroll_baseline_today(forecast_path)
        summary["steps"]["baseline_enrollment"] = {
            "predictions_submitted": n_baseline,
        }
        logger.info(f"Baseline: {n_baseline} predictions enrolled")
    except Exception as e:
        logger.error(f"Baseline enrollment failed: {e}")
        summary["errors"].append(f"Baseline enrollment: {e}")

    # Step 2: Run active challengers
    logger.info("=" * 60)
    logger.info("COMPETITION: Step 2 — Run challenger predictions")
    logger.info("=" * 60)
    challengers = discover_challengers(status_filter="active")
    challenger_results = {}

    for config in challengers:
        if config.id == "baseline":
            continue  # Already handled

        try:
            predictions = run_challenger_predictions(
                config.id,
                prediction_dates=prediction_dates,
            )
            challenger_results[config.id] = {
                "predictions_generated": len(predictions),
                "status": "success" if not predictions.empty else "no_predictions",
            }
        except Exception as e:
            logger.error(f"Challenger '{config.id}' failed: {e}")
            challenger_results[config.id] = {"status": "error", "error": str(e)}
            summary["errors"].append(f"Challenger {config.id}: {e}")

    summary["steps"]["challenger_predictions"] = challenger_results

    # Step 3: Backfill actuals
    logger.info("=" * 60)
    logger.info("COMPETITION: Step 3 — Backfill actuals")
    logger.info("=" * 60)
    try:
        n_actuals = backfill_baseline_actuals()
        summary["steps"]["actuals_backfill"] = {"rows_updated": n_actuals}
        logger.info(f"Backfilled {n_actuals} actuals")
    except Exception as e:
        logger.error(f"Actuals backfill failed: {e}")
        summary["errors"].append(f"Actuals backfill: {e}")

    # Step 4: Generate leaderboard
    logger.info("=" * 60)
    logger.info("COMPETITION: Step 4 — Update leaderboard")
    logger.info("=" * 60)
    try:
        leaderboard = generate_leaderboard()
        summary["steps"]["leaderboard"] = {
            "total_challengers": leaderboard["summary"]["total_challengers"],
            "leader": leaderboard["summary"]["leader"],
            "entities_evaluated": leaderboard["summary"]["total_entities_evaluated"],
        }
        logger.info(f"Leaderboard updated: {leaderboard['summary']}")
    except Exception as e:
        logger.error(f"Leaderboard generation failed: {e}")
        summary["errors"].append(f"Leaderboard: {e}")

    # Step 5: Blend analysis (optional, expensive)
    if not skip_blends:
        logger.info("=" * 60)
        logger.info("COMPETITION: Step 5 — Blend analysis")
        logger.info("=" * 60)
        try:
            blend_results = find_blend_opportunities()
            if not blend_results.empty:
                n_improved = len(blend_results[blend_results["improvement_pct"] > 0])
                summary["steps"]["blend_analysis"] = {
                    "entity_pairs_tested": len(blend_results),
                    "improvements_found": n_improved,
                }
                logger.info(f"Blend analysis: {n_improved} improvements found")
            else:
                summary["steps"]["blend_analysis"] = {"status": "insufficient_data"}
        except Exception as e:
            logger.error(f"Blend analysis failed: {e}")
            summary["errors"].append(f"Blend analysis: {e}")

    # Final summary
    elapsed = time.time() - start_time
    summary["elapsed_seconds"] = round(elapsed, 1)
    summary["ledger_stats"] = ledger_stats()

    logger.info("=" * 60)
    logger.info(f"COMPETITION COMPLETE in {elapsed:.1f}s")
    logger.info(f"Errors: {len(summary['errors'])}")
    logger.info("=" * 60)

    return summary


def run_overnight_training(
    challenger_ids: list[str] | None = None,
) -> dict:
    """
    Run overnight training for challengers that need it.

    Called separately from the daily competition cycle, typically 00:00-05:00.

    Args:
        challenger_ids: Specific challengers to train (None = all active)

    Returns:
        Training results dict
    """
    challengers = discover_challengers(status_filter="active")
    results = {}

    for config in challengers:
        if config.id == "baseline":
            continue  # Baseline uses production models

        if challenger_ids and config.id not in challenger_ids:
            continue

        logger.info(f"Training challenger: {config.id}")
        result = train_challenger(config.id)
        results[config.id] = result

    return results
