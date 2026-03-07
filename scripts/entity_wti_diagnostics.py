#!/usr/bin/env python3
"""
Entity-Level WTI Diagnostics

For each park, compares entity-level forecasts vs actual observations to identify
which entity models are contributing most to WTI error.

WTI = AVG(entity_daily_avg) across all entities in a park for a given day.
So each entity contributes equally — a single bad entity model drags the whole WTI.

Usage:
    python scripts/entity_wti_diagnostics.py --date 2026-02-17
    python scripts/entity_wti_diagnostics.py --date 2026-02-17 --park MK
    python scripts/entity_wti_diagnostics.py --date 2026-02-17 --top 10
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.park_code import entity_code_to_park_code

import duckdb
import pandas as pd

ET = ZoneInfo("America/Toronto")

PARK_NAMES = {
    "AK": "Animal Kingdom",
    "CA": "DCA",
    "DL": "Disneyland",
    "EP": "EPCOT",
    "EU": "Epic Universe",
    "HS": "Hollywood Studios",
    "IA": "Islands of Adv.",
    "MK": "Magic Kingdom",
    "TDL": "Tokyo Disneyland",
    "TDS": "Tokyo DisneySea",
    "UF": "Universal Florida",
    "UH": "Universal Hollywood",
}


def get_entity_names(pipeline_dir: Path) -> dict:
    """Load entity names from dimension tables."""
    dim_file = pipeline_dir / "dimension_tables" / "entities.parquet"
    if dim_file.exists():
        try:
            con = duckdb.connect()
            df = con.execute(f"""
                SELECT entity_code, entity_name 
                FROM read_parquet('{dim_file}')
            """).fetchdf()
            con.close()
            return dict(zip(df["entity_code"], df["entity_name"]))
        except Exception:
            pass
    return {}


def get_entity_diagnostics(eval_date: str, pipeline_dir: Path, park_filter: str = None):
    """
    Compare entity-level forecasts vs actuals for a given date.
    
    Returns DataFrame with columns:
        entity_code, park, entity_name, forecast_avg, actual_avg, error, abs_error,
        pct_contribution (how much this entity contributes to park WTI error)
    """
    archive_dir = pipeline_dir / "accuracy" / "archive"
    fact_dir = pipeline_dir / "fact_tables" / "parquet"
    
    con = duckdb.connect()
    
    # 1. Find the most recent archived forecast made BEFORE eval_date
    best_forecast_file = None
    best_made_date = None
    for f in sorted(archive_dir.glob("forecast_*.parquet")):
        made_date = f.stem.replace("forecast_", "")
        if made_date >= eval_date:
            continue
        best_forecast_file = f
        best_made_date = made_date
    
    if best_forecast_file is None:
        con.close()
        return None, None
    
    # 2. Get entity-level forecast averages for eval_date
    forecast_sql = f"""
        SELECT entity_code,
               ROUND(AVG(predicted_actual), 1) as forecast_avg,
               COUNT(*) as n_forecast_slots
        FROM read_parquet('{best_forecast_file}')
        WHERE park_date::DATE = '{eval_date}'
          AND predicted_actual > 0
        GROUP BY entity_code
    """
    forecasts = con.execute(forecast_sql).fetchdf()
    
    # 3. Get actual entity-level averages for eval_date
    # Use ACTUAL if available, fallback to POSTED (same as WTI calculation)
    actual_sql = f"""
        WITH entity_data AS (
            SELECT entity_code, wait_time_type, wait_time_minutes
            FROM read_parquet('{fact_dir}/*.parquet')
            WHERE park_date::DATE = '{eval_date}'
              AND wait_time_minutes > 0
              AND wait_time_type IN ('ACTUAL', 'POSTED')
        ),
        entity_avg AS (
            SELECT entity_code,
                   COALESCE(
                       AVG(CASE WHEN wait_time_type = 'ACTUAL' THEN wait_time_minutes END),
                       AVG(CASE WHEN wait_time_type = 'POSTED' THEN wait_time_minutes END)
                   ) as actual_avg,
                   CASE WHEN COUNT(CASE WHEN wait_time_type = 'ACTUAL' THEN 1 END) > 0 
                        THEN 'ACTUAL' ELSE 'POSTED' END as data_type,
                   COUNT(*) as n_actual_obs
            FROM entity_data
            GROUP BY entity_code
        )
        SELECT * FROM entity_avg WHERE actual_avg IS NOT NULL
    """
    actuals = con.execute(actual_sql).fetchdf()
    con.close()
    
    if len(forecasts) == 0 or len(actuals) == 0:
        return None, best_made_date
    
    # 4. Merge forecasts with actuals
    merged = forecasts.merge(actuals, on="entity_code", how="inner")
    merged["park"] = merged["entity_code"].apply(entity_code_to_park_code)
    merged["error"] = merged["forecast_avg"] - merged["actual_avg"]
    merged["abs_error"] = merged["error"].abs()
    
    # 5. Load entity names
    names = get_entity_names(pipeline_dir)
    merged["entity_name"] = merged["entity_code"].map(names).fillna("Unknown")
    
    # 6. Filter by park if requested
    if park_filter:
        merged = merged[merged["park"] == park_filter.upper()]
    
    # 7. Calculate per-park WTI contribution
    # WTI error for a park = AVG(entity forecast) - AVG(entity actual)
    # Each entity's contribution = entity_error / n_entities_in_park
    park_counts = merged.groupby("park")["entity_code"].count().to_dict()
    merged["n_park_entities"] = merged["park"].map(park_counts)
    merged["wti_contribution"] = merged["error"] / merged["n_park_entities"]
    
    return merged, best_made_date


def format_park_summary(df: pd.DataFrame, made_date: str, eval_date: str) -> str:
    """Format a park-level summary showing which parks have the worst entity models."""
    lines = []
    lines.append(f"🔬 Entity-Level WTI Diagnostics — {eval_date}")
    lines.append(f"Forecast from: {made_date}")
    lines.append("")
    
    park_stats = []
    for park in sorted(df["park"].unique()):
        pdata = df[df["park"] == park]
        n = len(pdata)
        park_wti_error = pdata["error"].mean()  # = forecast_WTI - actual_WTI
        park_mae = pdata["abs_error"].mean()
        worst = pdata.nlargest(3, "abs_error")
        
        park_stats.append({
            "park": park,
            "n": n,
            "wti_error": park_wti_error,
            "mae": park_mae,
            "worst": worst,
        })
    
    # Sort by absolute WTI error
    park_stats.sort(key=lambda x: abs(x["wti_error"]), reverse=True)
    
    lines.append(f"{'Park':<5} {'N':>3} {'WTI Err':>8} {'Ent MAE':>8} │ Top 3 Worst Entities")
    lines.append("─" * 75)
    
    for ps in park_stats:
        wti_err = ps["wti_error"]
        if abs(wti_err) <= 2.5:
            ind = "🟢"
        elif abs(wti_err) <= 5:
            ind = "🟡"
        elif abs(wti_err) <= 10:
            ind = "🟠"
        else:
            ind = "🔴"
        
        worst_strs = []
        for _, row in ps["worst"].iterrows():
            name = row["entity_name"][:15]
            worst_strs.append(f"{row['entity_code']}({row['error']:+.0f})")
        worst_str = ", ".join(worst_strs)
        
        lines.append(f"{ind} {ps['park']:<4} {ps['n']:>3} {wti_err:>+8.1f} {ps['mae']:>8.1f} │ {worst_str}")
    
    lines.append("─" * 75)
    overall_wti_err = df["error"].mean()
    overall_mae = df["abs_error"].mean()
    lines.append(f"  ALL  {len(df):>3} {overall_wti_err:>+8.1f} {overall_mae:>8.1f}")
    
    return "\n".join(lines)


def format_park_detail(df: pd.DataFrame, park: str, eval_date: str, top_n: int = 20) -> str:
    """Format entity-level detail for a single park."""
    pdata = df[df["park"] == park].copy()
    if len(pdata) == 0:
        return f"No data for park {park}"
    
    park_name = PARK_NAMES.get(park, park)
    lines = []
    lines.append(f"🔬 {park} ({park_name}) Entity Detail — {eval_date}")
    lines.append(f"Entities: {len(pdata)} | WTI Error: {pdata['error'].mean():+.1f}")
    lines.append("")
    
    # Sort by absolute error descending
    pdata = pdata.sort_values("abs_error", ascending=False).head(top_n)
    
    lines.append(f"{'Entity':<8} {'Name':<20} {'Fcst':>5} {'Actual':>6} {'Err':>7} {'Type':>6} {'WTI±':>6}")
    lines.append("─" * 62)
    
    for _, row in pdata.iterrows():
        name = row["entity_name"][:20]
        err = row["error"]
        
        if abs(err) <= 5:
            ind = "🟢"
        elif abs(err) <= 10:
            ind = "🟡"
        elif abs(err) <= 20:
            ind = "🟠"
        else:
            ind = "🔴"
        
        wti_contrib = row["wti_contribution"]
        lines.append(
            f"{ind} {row['entity_code']:<7} {name:<20} {row['forecast_avg']:>5.1f} {row['actual_avg']:>6.1f} "
            f"{err:>+7.1f} {row['data_type']:>6} {wti_contrib:>+6.1f}"
        )
    
    lines.append("─" * 62)
    lines.append(f"WTI± = entity's contribution to park WTI error")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Entity-Level WTI Diagnostics")
    parser.add_argument("--date", type=str, default=None, help="Date to analyze (default: yesterday)")
    parser.add_argument("--park", type=str, default=None, help="Single park to detail (e.g., MK, TDS)")
    parser.add_argument("--top", type=int, default=15, help="Top N worst entities per park (default: 15)")
    parser.add_argument("--all-parks", action="store_true", help="Show entity detail for ALL parks")
    parser.add_argument("--output", type=str, default=None, help="Save report to file")
    args = parser.parse_args()
    
    if args.date:
        eval_date = args.date
    else:
        eval_date = (datetime.now(ET) - timedelta(days=1)).strftime("%Y-%m-%d")
    
    pipeline_dir = Path("/home/wilma/hazeydata/pipeline")
    
    df, made_date = get_entity_diagnostics(eval_date, pipeline_dir, park_filter=args.park)
    
    if df is None or len(df) == 0:
        print(f"No entity-level comparison data available for {eval_date}")
        sys.exit(1)
    
    # Print park summary
    if not args.park:
        summary = format_park_summary(df, made_date, eval_date)
        print(summary)
    
    # Print park detail
    if args.park:
        detail = format_park_detail(df, args.park.upper(), eval_date, args.top)
        print(detail)
    elif args.all_parks:
        for park in sorted(df["park"].unique()):
            print("\n")
            detail = format_park_detail(df, park, eval_date, args.top)
            print(detail)
    
    # Save to file
    if args.output:
        output = []
        if not args.park:
            output.append(format_park_summary(df, made_date, eval_date))
        
        parks = [args.park.upper()] if args.park else sorted(df["park"].unique())
        for park in parks:
            output.append("")
            output.append(format_park_detail(df, park, eval_date, args.top))
        
        Path(args.output).write_text("\n".join(output))
        print(f"\nSaved to {args.output}", file=sys.stderr)
    
    # Also save raw data as parquet for further analysis
    output_dir = pipeline_dir / "accuracy"
    df.to_parquet(output_dir / f"entity_diagnostics_{eval_date}.parquet", index=False)


if __name__ == "__main__":
    main()
