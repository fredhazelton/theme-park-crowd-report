#!/usr/bin/env python3
"""
WTI Entity Breakdown Diagnostic

Shows every entity contributing to a specific day's WTI for a given park,
including predicted wait, model type, and relative contribution.

Usage:
  python scripts/wti_entity_breakdown.py MK 2026-02-22
  python scripts/wti_entity_breakdown.py CA 2026-03-15 --historical
  python scripts/wti_entity_breakdown.py MK 2026-02-22 --json
  python scripts/wti_entity_breakdown.py MK 2026-02-22 --csv
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

try:
    import duckdb
except ImportError:
    print("Error: duckdb not available. Run from the project venv.", file=sys.stderr)
    sys.exit(1)

OUTPUT_BASE = Path("/home/wilma/hazeydata/pipeline")
DB_PATH = OUTPUT_BASE / "tpcr_live.duckdb"
OC_PATH = OUTPUT_BASE / "operating_calendar" / "operating_calendar.parquet"
SYNTH_DIR = OUTPUT_BASE / "synthetic_actuals"
PARQUET_DIR = OUTPUT_BASE / "fact_tables" / "parquet"
FORECAST_PATH = OUTPUT_BASE / "curves" / "forecast_parquet" / "all_forecasts.parquet"


def park_code_sql(col="entity_code"):
    return f"""CASE
        WHEN {col} LIKE 'USH%' THEN 'UH'
        WHEN {col} LIKE 'TDL%' THEN 'TDL'
        WHEN {col} LIKE 'TDS%' THEN 'TDS'
        ELSE UPPER(LEFT({col}, 2))
    END"""


def get_forecast_breakdown(con, park_code: str, park_date: str) -> list[dict]:
    """Get entity-level breakdown for a forecast date."""
    oc_str = str(OC_PATH)
    
    # Determine entity_code prefix pattern for the park
    prefix_map = {
        "UH": "UH%",  # Could also be USH%
        "TDL": "TDL%",
        "TDS": "TDS%",
    }
    prefix = prefix_map.get(park_code, f"{park_code}%")
    
    # For UH, we need to also match USH prefix
    if park_code == "UH":
        entity_filter = "(f.entity_code LIKE 'UH%' OR f.entity_code LIKE 'USH%')"
    else:
        entity_filter = f"f.entity_code LIKE '{prefix}'"
    
    sql = f"""
        SELECT 
            f.entity_code,
            e.entity_name,
            e.category,
            COALESCE(e.has_posted, FALSE) as has_posted,
            f.prediction_method,
            ROUND(AVG(f.predicted_actual), 1) as avg_predicted_wait,
            ROUND(MIN(f.predicted_actual), 1) as min_predicted,
            ROUND(MAX(f.predicted_actual), 1) as max_predicted,
            COUNT(*) as n_slots,
            CASE WHEN oc.is_operating THEN 'operating' ELSE 'closed' END as status
        FROM read_parquet('{FORECAST_PATH}') f
        JOIN read_parquet('{oc_str}') oc 
            ON f.entity_code = oc.entity_code 
            AND CAST(f.park_date AS DATE) = CAST(oc.park_date AS DATE)
        LEFT JOIN entities e ON f.entity_code = e.entity_code
        WHERE {entity_filter}
            AND f.park_date = '{park_date}'
            AND f.predicted_actual > 0
            AND oc.is_operating = TRUE
        GROUP BY f.entity_code, e.entity_name, e.category, e.has_posted,
                 f.prediction_method, oc.is_operating
        ORDER BY avg_predicted_wait DESC
    """
    
    rows = con.execute(sql).fetchdf()
    if rows.empty:
        return []
    
    # Compute contribution (only from has_posted=True entities, matching WTI calc)
    posted_rows = rows[rows['has_posted'] == True]
    total_sum_posted = posted_rows['avg_predicted_wait'].sum()
    n_posted = len(posted_rows)
    
    results = []
    for _, row in rows.iterrows():
        hp = bool(row['has_posted'])
        # Contribution % is relative to the has_posted=True total (what goes into WTI)
        pct_of_wti = round((row['avg_predicted_wait'] / total_sum_posted) * 100, 1) if total_sum_posted > 0 and hp else 0
        results.append({
            "entity_code": row['entity_code'],
            "entity_name": row['entity_name'] or "Unknown",
            "category": row['category'] or "—",
            "has_posted": hp,
            "in_wti": hp,
            "prediction_method": row['prediction_method'],
            "avg_predicted_wait": float(row['avg_predicted_wait']),
            "min_predicted": float(row['min_predicted']),
            "max_predicted": float(row['max_predicted']),
            "n_slots": int(row['n_slots']),
            "pct_contribution": pct_of_wti,
        })
    
    return results


def get_historical_breakdown(con, park_code: str, park_date: str) -> list[dict]:
    """Get entity-level breakdown for a historical date using synthetic actuals + real actuals."""
    synth_str = str(SYNTH_DIR)
    parquet_str = str(PARQUET_DIR)
    pc_sql = park_code_sql("entity_code")
    
    REAL_WEIGHT = 3.5
    SYNTH_WEIGHT = 1.0
    
    sql = f"""
        WITH 
        synth AS (
            SELECT entity_code,
                synthetic_actual as wait_minutes,
                {SYNTH_WEIGHT} as weight,
                'synthetic' as obs_type
            FROM read_parquet('{synth_str}/*.parquet')
            WHERE {pc_sql} = '{park_code}'
              AND CAST(park_date AS DATE) = '{park_date}'
              AND synthetic_actual > 0
        ),
        real_actuals AS (
            SELECT entity_code,
                wait_time_minutes as wait_minutes,
                {REAL_WEIGHT} as weight,
                'actual' as obs_type
            FROM read_parquet('{parquet_str}/*.parquet')
            WHERE {pc_sql} = '{park_code}'
              AND CAST(park_date AS DATE) = '{park_date}'
              AND wait_time_type = 'ACTUAL'
              AND wait_time_minutes > 0
        ),
        all_obs AS (
            SELECT * FROM synth
            UNION ALL
            SELECT * FROM real_actuals
        ),
        entity_stats AS (
            SELECT entity_code,
                ROUND(SUM(wait_minutes * weight) / SUM(weight), 1) as weighted_avg,
                COUNT(*) as n_obs,
                SUM(CASE WHEN obs_type = 'actual' THEN 1 ELSE 0 END) as n_actual,
                SUM(CASE WHEN obs_type = 'synthetic' THEN 1 ELSE 0 END) as n_synthetic
            FROM all_obs
            GROUP BY entity_code
        )
        SELECT 
            s.entity_code,
            e.entity_name,
            e.category,
            s.weighted_avg,
            s.n_obs,
            s.n_actual,
            s.n_synthetic,
            CASE 
                WHEN s.n_actual > 0 AND s.n_synthetic > 0 THEN 'actual+synthetic'
                WHEN s.n_actual > 0 THEN 'actual'
                ELSE 'synthetic'
            END as data_source
        FROM entity_stats s
        LEFT JOIN entities e ON s.entity_code = e.entity_code
        ORDER BY s.weighted_avg DESC
    """
    
    rows = con.execute(sql).fetchdf()
    if rows.empty:
        return []
    
    total_sum = rows['weighted_avg'].sum()
    n_entities = len(rows)
    
    results = []
    for _, row in rows.iterrows():
        pct_of_wti = round((row['weighted_avg'] / total_sum) * 100, 1) if total_sum > 0 else 0
        results.append({
            "entity_code": row['entity_code'],
            "entity_name": row['entity_name'] or "Unknown",
            "category": row['category'] or "—",
            "data_source": row['data_source'],
            "weighted_avg_wait": float(row['weighted_avg']),
            "n_obs": int(row['n_obs']),
            "n_actual": int(row['n_actual']),
            "n_synthetic": int(row['n_synthetic']),
            "pct_contribution": pct_of_wti,
        })
    
    return results


def format_table(entities: list[dict], is_forecast: bool, park_code: str, 
                 park_date: str, wti_value: float | None = None) -> str:
    """Format entities into a readable table."""
    if not entities:
        return f"No data found for {park_code} on {park_date}"
    
    n = len(entities)
    in_wti = [e for e in entities if e.get('in_wti', True)]
    not_in_wti = [e for e in entities if not e.get('in_wti', True)]
    n_wti = len(in_wti)
    
    if is_forecast:
        avg_wait_wti = sum(e['avg_predicted_wait'] for e in in_wti) / n_wti if n_wti else 0
        lines = [
            f"╔══════════════════════════════════════════════════════════════════════════╗",
            f"║  WTI Entity Breakdown: {park_code} — {park_date} (FORECAST)                  ║",
            f"╠══════════════════════════════════════════════════════════════════════════╣",
            f"║  In WTI: {n_wti}/{n} entities  |  Raw WTI: {avg_wait_wti:.1f} min" + 
            (f"  |  Corrected: {wti_value}" if wti_value else "") + "  ║",
            f"╚══════════════════════════════════════════════════════════════════════════╝",
            "",
            f"{'#':>3}  {'Code':<8} {'Avg Wait':>8} {'Range':>11} {'Method':<16} {'Contrib':>7}  {'Name'}",
            f"{'—'*3}  {'—'*8} {'—'*8} {'—'*11} {'—'*16} {'—'*7}  {'—'*40}",
        ]
        for i, e in enumerate(in_wti, 1):
            rng = f"{e['min_predicted']:.0f}–{e['max_predicted']:.0f}"
            lines.append(
                f"{i:>3}  {e['entity_code']:<8} {e['avg_predicted_wait']:>7.1f}m {rng:>11} "
                f"{e['prediction_method']:<16} {e['pct_contribution']:>6.1f}%  {e['entity_name'][:50]}"
            )
        
        if not_in_wti:
            lines.append("")
            lines.append(f"── Excluded from WTI (has_posted=False): {len(not_in_wti)} entities ──")
            for e in not_in_wti:
                rng = f"{e['min_predicted']:.0f}–{e['max_predicted']:.0f}"
                lines.append(
                    f"  ·  {e['entity_code']:<8} {e['avg_predicted_wait']:>7.1f}m {rng:>11} "
                    f"{e['prediction_method']:<16}         {e['entity_name'][:50]}"
                )
        
        # Summary by method (WTI entities only)
        methods = {}
        for e in in_wti:
            m = e['prediction_method']
            if m not in methods:
                methods[m] = {'count': 0, 'total_wait': 0}
            methods[m]['count'] += 1
            methods[m]['total_wait'] += e['avg_predicted_wait']
        
        lines.append("")
        lines.append("Method Summary (WTI entities):")
        for m, stats in sorted(methods.items(), key=lambda x: -x[1]['count']):
            avg = stats['total_wait'] / stats['count']
            lines.append(f"  {m:<20} {stats['count']:>3} entities  avg wait: {avg:.1f}m")
    else:
        avg_wait = sum(e['weighted_avg_wait'] for e in entities) / n
        lines = [
            f"╔══════════════════════════════════════════════════════════════════════╗",
            f"║  WTI Entity Breakdown: {park_code} — {park_date} (HISTORICAL)          ║",
            f"╠══════════════════════════════════════════════════════════════════════╣",
            f"║  Entities: {n}  |  WTI: {avg_wait:.1f} min                             ║",
            f"╚══════════════════════════════════════════════════════════════════════╝",
            "",
            f"{'#':>3}  {'Code':<8} {'Avg Wait':>8} {'Source':<18} {'Obs':>6} {'Actual':>6} {'Synth':>6} {'Contrib':>7}  {'Name'}",
            f"{'—'*3}  {'—'*8} {'—'*8} {'—'*18} {'—'*6} {'—'*6} {'—'*6} {'—'*7}  {'—'*40}",
        ]
        for i, e in enumerate(entities, 1):
            lines.append(
                f"{i:>3}  {e['entity_code']:<8} {e['weighted_avg_wait']:>7.1f}m "
                f"{e['data_source']:<18} {e['n_obs']:>6} {e['n_actual']:>6} {e['n_synthetic']:>6} "
                f"{e['pct_contribution']:>6.1f}%  {e['entity_name'][:50]}"
            )
        
        # Summary by source
        sources = {}
        for e in entities:
            s = e['data_source']
            if s not in sources:
                sources[s] = {'count': 0, 'total_wait': 0}
            sources[s]['count'] += 1
            sources[s]['total_wait'] += e['weighted_avg_wait']
        
        lines.append("")
        lines.append("Source Summary:")
        for s, stats in sorted(sources.items(), key=lambda x: -x[1]['count']):
            avg = stats['total_wait'] / stats['count']
            lines.append(f"  {s:<20} {stats['count']:>3} entities  avg wait: {avg:.1f}m")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="WTI Entity Breakdown Diagnostic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s MK 2026-02-22              # Forecast breakdown
  %(prog)s CA 2026-02-20 --historical  # Historical breakdown
  %(prog)s MK 2026-02-22 --json        # JSON output
  %(prog)s MK 2026-02-22 --csv         # CSV output
        """
    )
    parser.add_argument("park", type=str, help="Park code (MK, EP, HS, AK, DL, CA, etc.)")
    parser.add_argument("date", type=str, help="Date (YYYY-MM-DD)")
    parser.add_argument("--historical", action="store_true", 
                        help="Force historical mode (uses synthetic actuals + real actuals)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--csv", action="store_true", help="Output as CSV")
    parser.add_argument("--output-base", type=Path, default=OUTPUT_BASE)
    args = parser.parse_args()
    
    park_code = args.park.upper()
    park_date = args.date
    
    # Validate date
    try:
        target_date = datetime.strptime(park_date, "%Y-%m-%d").date()
    except ValueError:
        print(f"Error: Invalid date format '{park_date}'. Use YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)
    
    con = duckdb.connect(str(DB_PATH), read_only=True)
    
    # Determine if forecast or historical
    today = date.today()
    is_forecast = target_date > today and not args.historical
    
    if args.historical or target_date <= today:
        entities = get_historical_breakdown(con, park_code, park_date)
        is_forecast = False
    else:
        entities = get_forecast_breakdown(con, park_code, park_date)
        is_forecast = True
    
    # Get the stored WTI value if available
    try:
        wti_row = con.execute(
            f"SELECT wti FROM wti WHERE park_code = '{park_code}' AND park_date = '{park_date}'"
        ).fetchone()
        wti_value = round(wti_row[0], 1) if wti_row else None
    except:
        wti_value = None
    
    con.close()
    
    if args.json:
        output = {
            "park_code": park_code,
            "park_date": park_date,
            "mode": "forecast" if is_forecast else "historical",
            "wti_stored": wti_value,
            "wti_computed": round(
                sum(e.get('avg_predicted_wait', e.get('weighted_avg_wait', 0)) for e in entities) / len(entities), 1
            ) if entities else None,
            "n_entities": len(entities),
            "entities": entities,
        }
        print(json.dumps(output, indent=2, default=str))
    elif args.csv:
        import csv
        import io
        buf = io.StringIO()
        if entities:
            writer = csv.DictWriter(buf, fieldnames=entities[0].keys())
            writer.writeheader()
            writer.writerows(entities)
        print(buf.getvalue())
    else:
        print(format_table(entities, is_forecast, park_code, park_date, wti_value))


if __name__ == "__main__":
    main()
