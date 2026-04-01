"""Shadow Evaluation — Compare archived shadow predictions against actuals.

Uses the EXACT SAME evaluation methodology as s10_accuracy.py:
  - Actuals from wait_time_type = 'ACTUAL' (NOT POSTED)
  - TIME_BUCKET with 2.5-minute midpoint rounding for time slot alignment
  - Synthetic actuals as fallback when real actuals are missing
  - Proper entity-level and overall metrics

This ensures shadow run results are directly comparable to pipeline accuracy.

Usage (CLI on wilma-server):
    cd /home/wilma/theme-park-crowd-report
    source .venv/bin/activate
    python -m pipeline.competition.shadow_evaluate \
        --challenger xgb-highLR \
        --eval-date 2026-03-31 \
        --output-base /home/wilma/hazeydata/pipeline

Output: JSON report to stdout (RESULT:{...}) for parsing by the orchestrator.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path


def evaluate_shadow_day(
    eval_date: str,
    challenger_parquet: str,
    baseline_parquet: str,
    output_base: str,
) -> dict | None:
    """Compare one day of archived shadow predictions against actuals.

    Uses identical methodology to s10_accuracy.py:
      - wait_time_type = 'ACTUAL' (real actuals, not POSTED)
      - TIME_BUCKET(INTERVAL '5 minutes', ts + 2m30s) for slot alignment
      - Synthetic actuals fallback for entities without real actuals

    Args:
        eval_date: The date to evaluate (YYYY-MM-DD). Predictions were made
                   for this date; actuals are now available.
        challenger_parquet: Path to archived challenger predictions for eval_date.
        baseline_parquet: Path to archived baseline predictions for eval_date.
        output_base: Pipeline output base (e.g., /home/wilma/hazeydata/pipeline).

    Returns:
        Dict with evaluation metrics, or None if insufficient data.
    """
    import duckdb

    output_base_path = Path(output_base)
    parquet_dir = output_base_path / "fact_tables" / "parquet"
    synth_dir = output_base_path / "synthetic_actuals"

    # Find recent parquet files for actuals
    recent_parquets = sorted(
        f for f in parquet_dir.glob("*.parquet")
        if f.name >= "2026-01"
    )[-3:]  # last 3 months

    if not recent_parquets:
        return None

    parquet_glob = "', '".join(str(f) for f in recent_parquets)
    has_synth = synth_dir.exists() and any(synth_dir.glob("*.parquet"))
    synth_glob = str(synth_dir).replace("\\", "/") + "/*.parquet"

    con = duckdb.connect()

    # --- Build actuals CTE: EXACT SAME as s10_accuracy.py ---
    actuals_cte = f"""
    WITH actuals_raw AS (
        SELECT
            entity_code,
            park_date::VARCHAR as park_date,
            TIME_BUCKET(INTERVAL '5 minutes',
                (observed_at_ts::TIMESTAMP + INTERVAL '2 minutes 30 seconds'))::TIME as time_slot,
            AVG(wait_time_minutes) as actual_wait,
            COUNT(*) as n_obs
        FROM read_parquet(['{parquet_glob}'])
        WHERE wait_time_type = 'ACTUAL'
        AND park_date::VARCHAR = '{eval_date}'
        GROUP BY entity_code, park_date, time_slot
    )"""

    if has_synth:
        actuals_cte += f""",
    actuals_synth AS (
        SELECT
            entity_code,
            park_date::VARCHAR as park_date,
            TIME_BUCKET(INTERVAL '5 minutes',
                (CAST(observed_at AS TIMESTAMP) + INTERVAL '2 minutes 30 seconds'))::TIME as time_slot,
            AVG(synthetic_actual) as actual_wait,
            COUNT(*) as n_obs
        FROM read_parquet('{synth_glob}')
        WHERE park_date::VARCHAR = '{eval_date}'
        AND synthetic_actual > 0
        GROUP BY entity_code, park_date, time_slot
    ),
    actuals AS (
        SELECT
            COALESCE(r.entity_code, s.entity_code) as entity_code,
            COALESCE(r.park_date, s.park_date) as park_date,
            COALESCE(r.time_slot, s.time_slot) as time_slot,
            COALESCE(r.actual_wait, s.actual_wait) as actual_wait,
            COALESCE(r.n_obs, 0) + COALESCE(s.n_obs, 0) as n_obs
        FROM actuals_raw r
        FULL OUTER JOIN actuals_synth s
            ON r.entity_code = s.entity_code
            AND r.park_date = s.park_date
            AND r.time_slot = s.time_slot
    )"""
    else:
        actuals_cte += """,
    actuals AS (
        SELECT entity_code, park_date, time_slot, actual_wait, n_obs
        FROM actuals_raw
    )"""

    # Check if archived predictions exist
    chal_path = Path(challenger_parquet)
    base_path = Path(baseline_parquet)
    if not chal_path.exists() or not base_path.exists():
        return None

    # --- Evaluate: join both sets of predictions against actuals ---
    try:
        result = con.execute(f"""
            {actuals_cte},
            challenger AS (
                SELECT entity_code, time_slot, predicted_actual
                FROM read_parquet('{challenger_parquet}')
            ),
            baseline AS (
                SELECT entity_code, time_slot, predicted_actual
                FROM read_parquet('{baseline_parquet}')
            ),
            matched AS (
                SELECT
                    a.entity_code,
                    a.time_slot,
                    a.actual_wait,
                    b.predicted_actual as baseline_pred,
                    c.predicted_actual as challenger_pred,
                    ABS(b.predicted_actual - a.actual_wait) as baseline_ae,
                    ABS(c.predicted_actual - a.actual_wait) as challenger_ae,
                    (b.predicted_actual - a.actual_wait) as baseline_error,
                    (c.predicted_actual - a.actual_wait) as challenger_error
                FROM actuals a
                JOIN baseline b ON a.entity_code = b.entity_code AND a.time_slot = b.time_slot
                JOIN challenger c ON a.entity_code = c.entity_code AND a.time_slot = c.time_slot
            )
            SELECT
                ROUND(AVG(baseline_ae), 2) as baseline_mae,
                ROUND(AVG(challenger_ae), 2) as challenger_mae,
                ROUND(AVG(baseline_error), 2) as baseline_bias,
                ROUND(AVG(challenger_error), 2) as challenger_bias,
                COUNT(*) as n_matched,
                COUNT(DISTINCT entity_code) as n_entities,
                SUM(CASE WHEN challenger_ae < baseline_ae THEN 1 ELSE 0 END) as challenger_slot_wins,
                SUM(CASE WHEN baseline_ae < challenger_ae THEN 1 ELSE 0 END) as baseline_slot_wins
            FROM matched
        """).fetchone()
    except Exception as e:
        print(f"EVAL_ERROR: {e}", file=sys.stderr)
        return None

    if result[0] is None:
        return None

    # --- Per-entity breakdown ---
    try:
        entity_rows = con.execute(f"""
            {actuals_cte},
            challenger AS (
                SELECT entity_code, time_slot, predicted_actual
                FROM read_parquet('{challenger_parquet}')
            ),
            baseline AS (
                SELECT entity_code, time_slot, predicted_actual
                FROM read_parquet('{baseline_parquet}')
            ),
            matched AS (
                SELECT
                    a.entity_code,
                    a.time_slot,
                    a.actual_wait,
                    b.predicted_actual as baseline_pred,
                    c.predicted_actual as challenger_pred
                FROM actuals a
                JOIN baseline b ON a.entity_code = b.entity_code AND a.time_slot = b.time_slot
                JOIN challenger c ON a.entity_code = c.entity_code AND a.time_slot = c.time_slot
            )
            SELECT
                entity_code,
                ROUND(AVG(ABS(baseline_pred - actual_wait)), 2) as entity_baseline_mae,
                ROUND(AVG(ABS(challenger_pred - actual_wait)), 2) as entity_challenger_mae,
                COUNT(*) as entity_slots
            FROM matched
            GROUP BY entity_code
        """).fetchall()
    except Exception:
        entity_rows = []

    entity_challenger_wins = sum(1 for r in entity_rows if r[2] < r[1])
    entity_baseline_wins = sum(1 for r in entity_rows if r[1] < r[2])

    # --- Per-park breakdown ---
    try:
        park_rows = con.execute(f"""
            {actuals_cte},
            challenger AS (
                SELECT entity_code, time_slot, predicted_actual
                FROM read_parquet('{challenger_parquet}')
            ),
            baseline AS (
                SELECT entity_code, time_slot, predicted_actual
                FROM read_parquet('{baseline_parquet}')
            ),
            matched AS (
                SELECT
                    a.entity_code,
                    a.entity_code[:2] as park_code,
                    a.actual_wait,
                    b.predicted_actual as baseline_pred,
                    c.predicted_actual as challenger_pred
                FROM actuals a
                JOIN baseline b ON a.entity_code = b.entity_code AND a.time_slot = b.time_slot
                JOIN challenger c ON a.entity_code = c.entity_code AND a.time_slot = c.time_slot
            )
            SELECT
                park_code,
                ROUND(AVG(ABS(baseline_pred - actual_wait)), 2) as park_baseline_mae,
                ROUND(AVG(ABS(challenger_pred - actual_wait)), 2) as park_challenger_mae,
                COUNT(DISTINCT entity_code) as park_entities
            FROM matched
            GROUP BY park_code
            ORDER BY park_code
        """).fetchall()
    except Exception:
        park_rows = []

    con.close()

    report = {
        "date": eval_date,
        "baseline_mae": float(result[0]),
        "challenger_mae": float(result[1]),
        "baseline_bias": float(result[2]),
        "challenger_bias": float(result[3]),
        "n_matched": result[4],
        "n_entities": result[5],
        "challenger_slot_wins": result[6],
        "baseline_slot_wins": result[7],
        "entity_challenger_wins": entity_challenger_wins,
        "entity_baseline_wins": entity_baseline_wins,
        "parks": {
            r[0]: {
                "baseline_mae": r[1],
                "challenger_mae": r[2],
                "entities": r[3],
            }
            for r in park_rows
        },
    }
    return report


def main():
    """CLI entry point for shadow evaluation."""
    parser = argparse.ArgumentParser(
        description="Evaluate shadow predictions against actuals (same methodology as s10_accuracy)"
    )
    parser.add_argument("--challenger", required=True, help="Challenger name (e.g., xgb-highLR)")
    parser.add_argument("--eval-date", required=True, help="Date to evaluate (YYYY-MM-DD)")
    parser.add_argument("--shadow-dir", required=True, help="Directory containing shadow archives")
    parser.add_argument("--output-base", required=True, help="Pipeline output base directory")
    parser.add_argument("--archive-date", required=True,
                        help="Date of the archived predictions (YYYY-MM-DD, typically eval_date - 1 day)")

    args = parser.parse_args()

    shadow_dir = Path(args.shadow_dir)
    challenger_parquet = str(shadow_dir / f"challenger_{args.archive_date}.parquet")
    baseline_parquet = str(shadow_dir / f"baseline_{args.archive_date}.parquet")

    if not Path(challenger_parquet).exists():
        print("NO_DATA: No challenger archive")
        return 0
    if not Path(baseline_parquet).exists():
        print("NO_DATA: No baseline archive")
        return 0

    result = evaluate_shadow_day(
        eval_date=args.eval_date,
        challenger_parquet=challenger_parquet,
        baseline_parquet=baseline_parquet,
        output_base=args.output_base,
    )

    if result is None:
        print("NO_MATCH: No matched prediction-actual pairs")
        return 0

    print("RESULT:" + json.dumps(result))
    return 0


if __name__ == "__main__":
    repo_root = Path(__file__).parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    sys.exit(main())
