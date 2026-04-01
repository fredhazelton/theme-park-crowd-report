"""Daily Recap Extraction — Build structured JSON for WDW daily recap blog posts.

Compares predicted vs observed WTI at park level, then drills into entity-level
error breakdown for the spotlight park (biggest miss). Uses identical evaluation
methodology to s10_accuracy.py and shadow_evaluate.py.

Usage (CLI on wilma-server):
    cd /home/wilma/theme-park-crowd-report
    source .venv/bin/activate
    python -m pipeline.content.extract_daily_recap \
        --date 2026-03-30 \
        --output-base /home/wilma/hazeydata/pipeline
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PARK_NAMES = {
    "MK": "Magic Kingdom",
    "EP": "EPCOT",
    "HS": "Hollywood Studios",
    "AK": "Animal Kingdom",
}

PARK_ORDER = ["MK", "EP", "HS", "AK"]


def load_entity_names(dimentity_path: str) -> dict:
    """Load entity_code -> name mapping from dimentity.csv."""
    names = {}
    with open(dimentity_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            names[row["code"]] = row["short_name"] or row["name"]
    return names


def load_content_json(content_dir: Path, kind: str, date_str: str) -> dict | None:
    """Load predicted_YYYY-MM-DD.json or observed_YYYY-MM-DD.json."""
    path = content_dir / f"{kind}_{date_str}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def get_entity_errors(
    eval_date: str,
    park_code: str,
    output_base: Path,
    forecast_parquet: str,
) -> list[dict]:
    """Get per-entity prediction errors for a specific park on a date.

    Uses the same methodology as s10_accuracy.py:
    - wait_time_type = 'ACTUAL'
    - TIME_BUCKET with 2.5-min midpoint rounding
    - Synthetic actuals fallback
    """
    import duckdb

    parquet_dir = output_base / "fact_tables" / "parquet"
    synth_dir = output_base / "synthetic_actuals"

    recent_parquets = sorted(
        f for f in parquet_dir.glob("*.parquet")
        if f.name >= "2026-01"
    )[-3:]

    if not recent_parquets:
        return []

    parquet_glob = "', '".join(str(f) for f in recent_parquets)
    has_synth = synth_dir.exists() and any(synth_dir.glob("*.parquet"))
    synth_glob = str(synth_dir).replace("\\", "/") + "/*.parquet"

    con = duckdb.connect()

    # Actuals CTE — same as s10_accuracy.py
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
        AND entity_code LIKE '{park_code}%'
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
        AND entity_code LIKE '{park_code}%'
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

    # Join forecasts against actuals at entity level
    try:
        rows = con.execute(f"""
            {actuals_cte},
            forecasts AS (
                SELECT entity_code, time_slot, predicted_actual
                FROM read_parquet('{forecast_parquet}')
                WHERE park_date::VARCHAR = '{eval_date}'
                AND entity_code LIKE '{park_code}%'
            ),
            matched AS (
                SELECT
                    a.entity_code,
                    a.time_slot,
                    a.actual_wait,
                    f.predicted_actual as forecast,
                    (a.actual_wait - f.predicted_actual) as error,
                    ABS(a.actual_wait - f.predicted_actual) as abs_error
                FROM actuals a
                JOIN forecasts f ON a.entity_code = f.entity_code AND a.time_slot = f.time_slot
            )
            SELECT
                entity_code,
                ROUND(AVG(actual_wait), 1) as avg_actual,
                ROUND(AVG(forecast), 1) as avg_forecast,
                ROUND(AVG(error), 1) as mean_error,
                ROUND(AVG(abs_error), 1) as mae,
                COUNT(*) as n_slots
            FROM matched
            GROUP BY entity_code
            ORDER BY AVG(abs_error) DESC
        """).fetchall()
    except Exception as e:
        print(f"Entity error query failed: {e}", file=sys.stderr)
        con.close()
        return []

    con.close()

    results = []
    for row in rows:
        results.append({
            "entity_code": row[0],
            "avg_actual": float(row[1]),
            "avg_forecast": float(row[2]),
            "mean_error": float(row[3]),
            "mae": float(row[4]),
            "n_slots": row[5],
        })
    return results


def detect_closures(
    eval_date: str,
    park_code: str,
    output_base: Path,
) -> list[dict]:
    """Detect potential ride closures from gaps in POSTED observations.

    A gap of 60+ consecutive minutes with no POSTED data for an entity
    that has data before and after suggests a closure or extended downtime.
    """
    import duckdb

    parquet_dir = output_base / "fact_tables" / "parquet"
    recent_parquets = sorted(
        f for f in parquet_dir.glob("*.parquet")
        if f.name >= "2026-01"
    )[-3:]

    if not recent_parquets:
        return []

    parquet_glob = "', '".join(str(f) for f in recent_parquets)
    con = duckdb.connect()

    try:
        rows = con.execute(f"""
            WITH posted AS (
                SELECT
                    entity_code,
                    observed_at_ts::TIMESTAMP as ts
                FROM read_parquet(['{parquet_glob}'])
                WHERE wait_time_type = 'POSTED'
                AND park_date::VARCHAR = '{eval_date}'
                AND entity_code LIKE '{park_code}%'
            ),
            with_next AS (
                SELECT
                    entity_code,
                    ts,
                    LEAD(ts) OVER (PARTITION BY entity_code ORDER BY ts) as next_ts
                FROM posted
            ),
            gaps AS (
                SELECT
                    entity_code,
                    ts as gap_start,
                    next_ts as gap_end,
                    EXTRACT(EPOCH FROM (next_ts - ts)) / 60 as gap_minutes
                FROM with_next
                WHERE next_ts IS NOT NULL
                AND EXTRACT(EPOCH FROM (next_ts - ts)) / 60 >= 60
            )
            SELECT entity_code, gap_start::VARCHAR, gap_end::VARCHAR, ROUND(gap_minutes, 0)::INT
            FROM gaps
            ORDER BY gap_minutes DESC
        """).fetchall()
    except Exception as e:
        print(f"Closure detection failed: {e}", file=sys.stderr)
        con.close()
        return []

    con.close()

    closures = []
    for row in rows:
        closures.append({
            "entity_code": row[0],
            "gap_start": row[1],
            "gap_end": row[2],
            "gap_minutes": row[3],
        })
    return closures


def classify_error_pattern(entity_errors: list[dict]) -> str:
    """Classify error distribution pattern.

    Returns: 'concentrated', 'top_heavy', or 'distributed'
    """
    if not entity_errors:
        return "distributed"

    total_mae_sum = sum(e["mae"] * e["n_slots"] for e in entity_errors)
    if total_mae_sum == 0:
        return "distributed"

    # Check if top entity accounts for >40% of total error
    top = entity_errors[0]  # already sorted by MAE desc
    top_share = (top["mae"] * top["n_slots"]) / total_mae_sum

    if top_share > 0.4:
        return "concentrated"

    # Check if top 3 account for >60%
    top3_share = sum(e["mae"] * e["n_slots"] for e in entity_errors[:3]) / total_mae_sum
    if top3_share > 0.6:
        return "top_heavy"

    return "distributed"


def build_recap(
    date_str: str,
    output_base_str: str,
    dimentity_path: str,
    forecast_parquet: str,
) -> dict | None:
    """Build the full recap JSON for a given date."""
    output_base = Path(output_base_str)
    content_dir = output_base / "content"

    # Load predicted & observed
    predicted = load_content_json(content_dir, "predicted", date_str)
    observed = load_content_json(content_dir, "observed", date_str)

    if not predicted or not observed:
        print(f"Missing content files for {date_str}", file=sys.stderr)
        return None

    if predicted.get("status") != "ready" or observed.get("status") != "ready":
        print(f"Content not ready for {date_str}", file=sys.stderr)
        return None

    # Load entity names
    entity_names = load_entity_names(dimentity_path)

    # Build park-level comparison
    pred_by_park = {p["park_code"]: p for p in predicted["parks"]}
    obs_by_park = {p["park_code"]: p for p in observed["parks"]}

    parks = []
    max_abs_delta = 0
    spotlight_park = None

    for pc in PARK_ORDER:
        if pc not in pred_by_park or pc not in obs_by_park:
            continue
        pred_wti = pred_by_park[pc]["wti"]
        obs_wti = obs_by_park[pc]["wti"]
        delta = round(obs_wti - pred_wti, 1)
        abs_delta = abs(delta)

        parks.append({
            "park_code": pc,
            "park_name": PARK_NAMES.get(pc, pc),
            "predicted_wti": pred_wti,
            "observed_wti": obs_wti,
            "delta": delta,
            "abs_delta": abs_delta,
        })

        if abs_delta > max_abs_delta:
            max_abs_delta = abs_delta
            spotlight_park = pc

    if not parks:
        print("No park data to compare", file=sys.stderr)
        return None

    # Overall accuracy
    overall_mae = round(sum(p["abs_delta"] for p in parks) / len(parks), 1)

    # Entity-level drill-down for spotlight park
    entity_errors = get_entity_errors(date_str, spotlight_park, output_base, forecast_parquet)

    # Resolve entity names
    for e in entity_errors:
        e["entity_name"] = entity_names.get(e["entity_code"], e["entity_code"])

    # Classify error pattern
    error_pattern = classify_error_pattern(entity_errors)

    # Detect closures at spotlight park
    closures = detect_closures(date_str, spotlight_park, output_base)
    for c in closures:
        c["entity_name"] = entity_names.get(c["entity_code"], c["entity_code"])

    recap = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "property": "WDW",
        "overall_mae": overall_mae,
        "parks": parks,
        "spotlight": {
            "park_code": spotlight_park,
            "park_name": PARK_NAMES.get(spotlight_park, spotlight_park),
            "predicted_wti": pred_by_park[spotlight_park]["wti"],
            "observed_wti": obs_by_park[spotlight_park]["wti"],
            "delta": round(obs_by_park[spotlight_park]["wti"] - pred_by_park[spotlight_park]["wti"], 1),
            "error_pattern": error_pattern,
            "top_entities": entity_errors[:10],
            "all_entities": entity_errors,
            "closures": closures,
        },
    }

    return recap


def main():
    parser = argparse.ArgumentParser(
        description="Extract daily recap data for WDW blog post"
    )
    parser.add_argument("--date", required=True, help="Date to recap (YYYY-MM-DD)")
    parser.add_argument("--output-base", required=True, help="Pipeline output base")
    parser.add_argument(
        "--dimentity",
        default="/home/wilma/clawd-anthropic/dimentity.csv",
        help="Path to dimentity.csv",
    )
    parser.add_argument(
        "--forecast-parquet",
        default="/home/wilma/hazeydata/pipeline/curves/forecast_parquet/all_forecasts_v3.parquet.with_bias_correction",
        help="Path to forecast parquet",
    )

    args = parser.parse_args()

    recap = build_recap(
        date_str=args.date,
        output_base_str=args.output_base,
        dimentity_path=args.dimentity,
        forecast_parquet=args.forecast_parquet,
    )

    if recap is None:
        print("FAILED: Could not build recap", file=sys.stderr)
        sys.exit(1)

    # Write output
    out_dir = Path(args.output_base) / "content"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"recap_{args.date}.json"
    with open(out_path, "w") as f:
        json.dump(recap, f, indent=2)

    print(f"RECAP_OK: {out_path}")
    print(f"  Overall MAE: {recap['overall_mae']}")
    print(f"  Spotlight: {recap['spotlight']['park_name']} (delta: {recap['spotlight']['delta']:+.1f})")
    print(f"  Pattern: {recap['spotlight']['error_pattern']}")
    print(f"  Top entities: {len(recap['spotlight']['top_entities'])}")
    print(f"  Closures: {len(recap['spotlight']['closures'])}")


if __name__ == "__main__":
    repo_root = Path(__file__).parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    sys.exit(main())
