#!/usr/bin/env python3
"""
Daily WTI Accuracy Report

Generates a Telegram-friendly accuracy report comparing yesterday's
WTI predictions vs actuals, park by park, plus running overall accuracy.

Reports ONLY what users saw (raw predictions, no bias adjustments).

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

if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd

ET = ZoneInfo("America/Toronto")

SYNTHETIC_FIRST_FORECAST_DATE = "2026-02-18"

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


def get_model_type(made_date: str) -> str:
    if made_date >= SYNTHETIC_FIRST_FORECAST_DATE:
        return "v2+synth"
    return "v2"


def load_yesterday_comparison(eval_date: str, archive_dir: Path, wti_actual: pd.DataFrame):
    """Compare forecasted WTI vs actual WTI for a given date."""
    actuals = wti_actual[wti_actual["park_date"].astype(str).str[:10] == eval_date]
    if len(actuals) == 0:
        return None

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
    """Calculate running overall accuracy across all evaluated dates."""
    all_comparisons = []

    archive_files = sorted(archive_dir.glob("wti_*.parquet"))
    if not archive_files:
        return None

    earliest_archive = archive_files[0].stem.replace("wti_", "")

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


def format_report(yesterday: pd.DataFrame, overall: pd.DataFrame, eval_date: str) -> str:
    """Format the accuracy report — raw predictions only (what users saw)."""
    lines = []
    lines.append(f"📊 WTI Accuracy Report — {eval_date}")
    lines.append("")

    if yesterday is not None and len(yesterday) > 0:
        model_type = yesterday.iloc[0]["model_type"]
        made_date = yesterday.iloc[0]["made_date"]
        lines.append(f"Model: {model_type} (forecast from {made_date})")
    lines.append("")

    # Header
    lines.append(f"{'Park':<5} {'Shown':>5} {'Actual':>6} {'Error':>6} │ {'Avg':>5}")
    lines.append("─" * 42)

    # Overall stats per park
    overall_by_park = {}
    if overall is not None:
        for park, grp in overall.groupby("park_code"):
            overall_by_park[park] = {
                "mae": grp["abs_error"].mean(),
                "bias": grp["error"].mean(),
                "n": len(grp),
            }

    # Sort by absolute error (worst first)
    if yesterday is not None:
        parks = yesterday.sort_values("abs_error", ascending=False)
    else:
        parks = pd.DataFrame()

    for _, row in parks.iterrows():
        park = row["park_code"]
        pred = row["wti_forecast"]
        actual = row["wti_actual"]
        err = row["error"]
        overall_mae = overall_by_park.get(park, {}).get("mae", float("nan"))

        err_str = f"{err:+.1f}"
        overall_str = f"±{overall_mae:.1f}" if not pd.isna(overall_mae) else "  —"

        if abs(err) <= 2.5:
            indicator = "🟢"
        elif abs(err) <= 5:
            indicator = "🟡"
        elif abs(err) <= 10:
            indicator = "🟠"
        else:
            indicator = "🔴"

        lines.append(f"{indicator} {park:<4} {pred:>5.1f} {actual:>6.1f} {err_str:>6} │ {overall_str:>5}")

    lines.append("─" * 42)

    # Summary
    if yesterday is not None and len(yesterday) > 0:
        mae = yesterday["abs_error"].mean()
        bias = yesterday["error"].mean()
        lines.append(f"  Yesterday:  MAE={mae:.1f}  Bias={bias:+.1f}")

    if overall is not None:
        overall_mae = overall["abs_error"].mean()
        overall_bias = overall["error"].mean()
        n_dates = overall["eval_date"].nunique()
        lines.append(f"  Overall ({n_dates} days):  MAE={overall_mae:.1f}  Bias={overall_bias:+.1f}")

    lines.append("")
    lines.append("🟢 ≤2.5  🟡 ≤5  🟠 ≤10  🔴 >10")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Daily WTI Accuracy Report")
    parser.add_argument("--date", type=str, default=None, help="Evaluation date (YYYY-MM-DD). Default: yesterday.")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    parser.add_argument("--json", action="store_true", help="Also output JSON")
    args = parser.parse_args()

    if args.date:
        eval_date = args.date
    else:
        eval_date = (datetime.now(ET) - timedelta(days=1)).strftime("%Y-%m-%d")

    pipeline_dir = Path("/home/wilma/hazeydata/pipeline")
    wti_file = pipeline_dir / "wti" / "wti.parquet"
    archive_dir = pipeline_dir / "accuracy" / "archive"

    if not wti_file.exists():
        print("ERROR: No WTI file found", file=sys.stderr)
        sys.exit(1)

    wti_all = pd.read_parquet(wti_file)
    wti_actual = wti_all[wti_all["source"] == "historical"]

    yesterday = load_yesterday_comparison(eval_date, archive_dir, wti_actual)
    if yesterday is None:
        report = f"📊 WTI Accuracy Report — {eval_date}\n\n⚠️ No forecast/actual comparison available for this date."
    else:
        overall = load_overall_accuracy(archive_dir, wti_actual, eval_date)
        report = format_report(yesterday, overall, eval_date)

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
