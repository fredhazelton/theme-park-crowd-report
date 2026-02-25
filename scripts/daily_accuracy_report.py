#!/usr/bin/env python3
"""
Daily WTI Accuracy Report

Generates a Telegram-friendly accuracy report comparing yesterday's
WTI predictions vs actuals, park by park, plus running overall accuracy.

Usage:
    python scripts/daily_accuracy_report.py
    python scripts/daily_accuracy_report.py --date 2026-02-17
    python scripts/daily_accuracy_report.py --output /path/to/report.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Add src to path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd

ET = ZoneInfo("America/Toronto")

# Synthetic models first completed 2026-02-17 22:16
# First forecasts using synthetic models: made_date >= 2026-02-18
SYNTHETIC_FIRST_FORECAST_DATE = "2026-02-18"

PARK_NAMES = {
    "AK": "Animal Kingdom",
    "CA": "DCA",
    "DL": "Disneyland",
    "EP": "EPCOT",
    "EU": "Europa Park",
    "HS": "Hollywood Studios",
    "IA": "Islands of Adv.",
    "MK": "Magic Kingdom",
    "TDL": "Tokyo Disneyland",
    "TDS": "Tokyo DisneySea",
    "UF": "Universal Florida",
    "UH": "Universal Hollywood",
}


def get_model_type(made_date: str) -> str:
    """Determine if forecast was made with synthetic-augmented models."""
    if made_date >= SYNTHETIC_FIRST_FORECAST_DATE:
        return "v2+synth"
    return "v2"


def load_yesterday_comparison(eval_date: str, archive_dir: Path, wti_actual: pd.DataFrame):
    """Compare forecasted WTI vs actual WTI for a given date."""
    
    actuals = wti_actual[wti_actual["park_date"].astype(str).str[:10] == eval_date]
    if len(actuals) == 0:
        return None
    
    # Find the most recent forecast made BEFORE eval_date
    best_forecast = None
    best_made_date = None
    
    for f in sorted(archive_dir.glob("wti_*.parquet")):
        made_date = f.stem.replace("wti_", "")
        if made_date >= eval_date:
            continue
        
        fdf = pd.read_parquet(f)
        fday = fdf[fdf["park_date"].astype(str).str[:10] == eval_date]
        if len(fday) > 0:
            best_forecast = fday
            best_made_date = made_date
    
    if best_forecast is None:
        return None
    
    merged = best_forecast.merge(
        actuals[["park_code", "wti"]],
        on="park_code",
        suffixes=("_forecast", "_actual"),
    )
    merged["error"] = merged["wti_forecast"] - merged["wti_actual"]
    merged["abs_error"] = merged["error"].abs()
    merged["made_date"] = best_made_date
    merged["model_type"] = get_model_type(best_made_date)
    
    return merged


def load_overall_accuracy(archive_dir: Path, wti_actual: pd.DataFrame, up_to_date: str):
    """Calculate running overall accuracy per park across all evaluated dates."""
    
    all_comparisons = []
    
    # Only evaluate dates that could have archived forecasts
    # (forecast archives start around Feb 13, so only check recent dates)
    archive_files = sorted(archive_dir.glob("wti_*.parquet"))
    if not archive_files:
        return None
    
    earliest_archive = archive_files[0].stem.replace("wti_", "")
    
    # Get dates from earliest archive +1 day through up_to_date
    actual_dates = sorted(
        wti_actual[
            (wti_actual["park_date"].astype(str).str[:10] > earliest_archive)
            & (wti_actual["park_date"].astype(str).str[:10] <= up_to_date)
        ]["park_date"]
        .astype(str)
        .str[:10]
        .unique()
    )
    
    for eval_date in actual_dates:
        result = load_yesterday_comparison(eval_date, archive_dir, wti_actual)
        if result is not None:
            result["eval_date"] = eval_date
            all_comparisons.append(result)
    
    if not all_comparisons:
        return None
    
    return pd.concat(all_comparisons, ignore_index=True)


def get_bias_corrections(pipeline_dir: Path) -> dict:
    """Read per-park bias corrections from accuracy data, or fallback to log."""
    import re
    
    # Try to compute per-park corrections from wti_accuracy data directly
    wti_accuracy_path = pipeline_dir / "accuracy" / "wti_accuracy.parquet"
    if wti_accuracy_path.exists():
        try:
            acc = pd.read_parquet(wti_accuracy_path)
            # Use same 14-day window as the pipeline
            cutoff = (datetime.now(ET) - timedelta(days=14)).strftime("%Y-%m-%d")
            recent = acc[acc["park_date"].astype(str).str[:10] >= cutoff]
            if len(recent) > 0:
                park_biases = recent.groupby("park_code")["wti_error"].mean()
                corrections = {park: round(-bias, 1) for park, bias in park_biases.items()}
                # Also compute overall fallback
                corrections["_fallback"] = round(-recent["wti_error"].mean(), 1)
                return corrections
        except Exception:
            pass
    
    # Fallback: parse flat correction from log
    logs_dir = pipeline_dir / "logs"
    for pattern in ["calculate_wti_simple_*.log", "daily_pipeline_*.log"]:
        files = sorted(logs_dir.glob(pattern), reverse=True)
        for f in files:
            text = f.read_text()
            match = re.search(r"Bias correction applied: \+?([-\d.]+)", text)
            if match:
                flat = float(match.group(1))
                return {"_flat": flat}
    return {}


def format_report(yesterday: pd.DataFrame, overall: pd.DataFrame, eval_date: str, corrections: dict = None) -> str:
    """Format the accuracy report for Telegram."""
    if corrections is None:
        corrections = {}
    
    def get_correction(park: str) -> float:
        """Get per-park correction, fallback to overall or flat."""
        if park in corrections:
            return corrections[park]
        if "_fallback" in corrections:
            return corrections["_fallback"]
        if "_flat" in corrections:
            return corrections["_flat"]
        return 0.0
    
    lines = []
    lines.append(f"📊 WTI Accuracy Report — {eval_date}")
    lines.append("")
    
    # Determine model type
    if yesterday is not None and len(yesterday) > 0:
        model_type = yesterday.iloc[0]["model_type"]
        made_date = yesterday.iloc[0]["made_date"]
        lines.append(f"Model: {model_type} (forecast from {made_date})")
        if corrections:
            if "_flat" in corrections:
                lines.append(f"Bias: flat {corrections['_flat']:+.1f}")
            else:
                lines.append(f"Bias: per-park corrections ({len([k for k in corrections if not k.startswith('_')])} parks)")
    lines.append("")
    
    # Header — Raw and Adjusted columns
    lines.append(f"{'Park':<5} {'Pred':>5} {'Adj':>5} {'Actual':>6} {'Raw':>6} {'Adj':>5} │ {'Ovr':>5}")
    lines.append("─" * 50)
    
    # Get overall stats per park (using raw errors)
    overall_by_park = {}
    if overall is not None:
        for park, grp in overall.groupby("park_code"):
            overall_by_park[park] = {
                "mae": grp["abs_error"].mean(),
                "bias": grp["error"].mean(),
                "n": len(grp),
            }
    
    # Sort parks by adjusted absolute error (worst first)
    if yesterday is not None:
        parks = yesterday.copy()
        parks["adj_err"] = parks.apply(
            lambda r: abs((r["wti_forecast"] + get_correction(r["park_code"])) - r["wti_actual"]),
            axis=1,
        )
        parks = parks.sort_values("adj_err", ascending=False)
    else:
        parks = pd.DataFrame()
    
    for _, row in parks.iterrows():
        park = row["park_code"]
        pred = row["wti_forecast"]
        corr = get_correction(park)
        adj_pred = pred + corr
        actual = row["wti_actual"]
        raw_err = row["error"]
        adj_err = adj_pred - actual
        
        overall_mae = overall_by_park.get(park, {}).get("mae", float("nan"))
        
        raw_str = f"{raw_err:+.1f}"
        adj_str = f"{adj_err:+.1f}"
        overall_str = f"±{overall_mae:.1f}" if not pd.isna(overall_mae) else "  —"
        
        # Emoji based on adjusted error (what matters after correction)
        if abs(adj_err) <= 2.5:
            indicator = "🟢"
        elif abs(adj_err) <= 5:
            indicator = "🟡"
        elif abs(adj_err) <= 10:
            indicator = "🟠"
        else:
            indicator = "🔴"
        
        lines.append(f"{indicator} {park:<4} {pred:>5.1f} {adj_pred:>5.1f} {actual:>6.1f} {raw_str:>6} {adj_str:>5} │ {overall_str:>5}")
    
    lines.append("─" * 50)
    
    # Summary rows
    if yesterday is not None and len(yesterday) > 0:
        raw_mae = yesterday["abs_error"].mean()
        raw_bias = yesterday["error"].mean()
        adj_errors = yesterday.apply(
            lambda r: (r["wti_forecast"] + get_correction(r["park_code"])) - r["wti_actual"],
            axis=1,
        )
        adj_mae = adj_errors.abs().mean()
        adj_bias = adj_errors.mean()
        lines.append(f"  Raw:  MAE={raw_mae:.1f}  Bias={raw_bias:+.1f}")
        lines.append(f"  Adj:  MAE={adj_mae:.1f}  Bias={adj_bias:+.1f}")
    
    if overall is not None:
        overall_mae = overall["abs_error"].mean()
        overall_bias = overall["error"].mean()
        n_dates = overall["eval_date"].nunique()
        lines.append("")
        lines.append(f"Overall raw ({n_dates} days): MAE={overall_mae:.1f}, Bias={overall_bias:+.1f}")
    
    # Target reminder
    lines.append("")
    lines.append("🎯 Target: ±2.5 adj points")
    lines.append("🟢 ≤2.5  🟡 ≤5  🟠 ≤10  🔴 >10")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Daily WTI Accuracy Report")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Evaluation date (YYYY-MM-DD). Default: yesterday.",
    )
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    parser.add_argument(
        "--json", action="store_true", help="Also output JSON for programmatic use"
    )
    args = parser.parse_args()
    
    # Default to yesterday
    if args.date:
        eval_date = args.date
    else:
        eval_date = (datetime.now(ET) - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Paths
    pipeline_dir = Path("/home/wilma/hazeydata/pipeline")
    wti_file = pipeline_dir / "wti" / "wti.parquet"
    archive_dir = pipeline_dir / "accuracy" / "archive"
    
    if not wti_file.exists():
        print("ERROR: No WTI file found", file=sys.stderr)
        sys.exit(1)
    
    # Load actual WTI (historical source)
    wti_all = pd.read_parquet(wti_file)
    wti_actual = wti_all[wti_all["source"] == "historical"]
    
    # Get bias corrections (per-park or flat fallback)
    corrections = get_bias_corrections(pipeline_dir)
    
    # Yesterday's comparison
    yesterday = load_yesterday_comparison(eval_date, archive_dir, wti_actual)
    if yesterday is None:
        report = f"📊 WTI Accuracy Report — {eval_date}\n\n⚠️ No forecast/actual comparison available for this date."
    else:
        # Overall running accuracy
        overall = load_overall_accuracy(archive_dir, wti_actual, eval_date)
        report = format_report(yesterday, overall, eval_date, corrections)
    
    # Output
    print(report)
    
    if args.output:
        Path(args.output).write_text(report)
        print(f"\nSaved to {args.output}", file=sys.stderr)
    
    if args.json and yesterday is not None:
        json_out = {
            "eval_date": eval_date,
            "parks": yesterday[
                ["park_code", "wti_forecast", "wti_actual", "error", "abs_error", "model_type", "made_date"]
            ].to_dict(orient="records"),
            "yesterday_mae": float(yesterday["abs_error"].mean()),
            "yesterday_bias": float(yesterday["error"].mean()),
        }
        json_path = args.output.replace(".txt", ".json") if args.output else f"accuracy_report_{eval_date}.json"
        Path(json_path).write_text(json.dumps(json_out, indent=2, default=str))


if __name__ == "__main__":
    main()
