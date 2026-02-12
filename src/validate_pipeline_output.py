#!/usr/bin/env python3
"""
Pipeline Post-Run Validation

Runs after the full pipeline completes. Checks data quality and flags issues.

Checks:
1. Forecast coverage: today+1 has forecast curves for all active parks
2. WTI anomaly: flag dates where WTI jumps >30% from neighbors
3. Entity coverage: non-extinct entities in dimentity that lack trained models
4. Forecast date range: forecasts extend at least 7 days into future

Output: pipeline_validation/validation_report.json and validation_report.txt
Exit: 0 if all pass, 1 if any RED flags
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from utils import get_output_base

# Park codes to expect forecasts for (active parks)
ACTIVE_PARK_CODES = {"MK", "EP", "HS", "AK", "DL", "CA", "IA", "UF", "EU", "UH", "TDL", "TDS"}
WTI_ANOMALY_THRESHOLD = 0.30  # 30% jump


def load_wti(output_base: Path) -> pd.DataFrame | None:
    path = output_base / "wti" / "wti.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df["park_date"] = pd.to_datetime(df["park_date"]).dt.date
    return df


def load_forecasts(output_base: Path) -> pd.DataFrame | None:
    path = output_base / "curves" / "forecast_parquet" / "all_forecasts.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def load_dimentity(output_base: Path) -> pd.DataFrame | None:
    path = output_base / "dimension_tables" / "dimentity.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, low_memory=False)


def get_trained_entities(output_base: Path) -> set[str]:
    models_dir = output_base / "models"
    if not models_dir.exists():
        return set()
    return {
        d.name for d in models_dir.iterdir()
        if d.is_dir() and (d / "model_julia_v2.json").exists()
    }


def check_forecast_coverage(output_base: Path, results: dict) -> bool:
    """Today+1 has forecast curves for all active parks?"""
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    df = load_forecasts(output_base)
    if df is None or df.empty:
        results["forecast_coverage"] = {"pass": False, "reason": "No forecast file"}
        return False

    df["park_date"] = pd.to_datetime(df["park_date"]).dt.date.astype(str)
    df["park_code"] = df["entity_code"].str[:2].str.upper()
    tomorrow_parks = set(df[df["park_date"] == tomorrow]["park_code"].unique())

    missing = ACTIVE_PARK_CODES - tomorrow_parks
    if missing:
        results["forecast_coverage"] = {
            "pass": False,
            "reason": f"Missing forecasts for {tomorrow}",
            "missing_parks": sorted(missing),
        }
        return False
    results["forecast_coverage"] = {"pass": True}
    return True


def check_wti_anomaly(output_base: Path, results: dict) -> bool:
    """Flag dates where WTI jumps >30% from neighbors."""
    df = load_wti(output_base)
    if df is None or df.empty:
        results["wti_anomaly"] = {"pass": True, "reason": "No WTI data"}
        return True

    anomalies = []
    for park in df["park_code"].unique():
        park_df = df[df["park_code"] == park].sort_values("park_date")
        if len(park_df) < 3:
            continue
        park_df = park_df.reset_index(drop=True)
        for i in range(1, len(park_df) - 1):
            prev = park_df.iloc[i - 1]["wti"]
            curr = park_df.iloc[i]["wti"]
            next_ = park_df.iloc[i + 1]["wti"]
            if prev <= 0:
                continue
            drop = (prev - curr) / prev if prev > 0 else 0
            jump = (next_ - curr) / curr if curr > 0 else 0
            if abs(drop) > WTI_ANOMALY_THRESHOLD or abs(jump) > WTI_ANOMALY_THRESHOLD:
                anomalies.append({
                    "park": park,
                    "date": str(park_df.iloc[i]["park_date"]),
                    "prev": float(prev),
                    "curr": float(curr),
                    "next": float(next_),
                })

    if anomalies:
        results["wti_anomaly"] = {"pass": False, "anomalies": anomalies[:20]}
        return False
    results["wti_anomaly"] = {"pass": True}
    return True


def check_entity_coverage(output_base: Path, results: dict) -> bool:
    """Flag non-extinct entities in dimentity that lack trained models."""
    dim = load_dimentity(output_base)
    if dim is None or dim.empty:
        results["entity_coverage"] = {"pass": True, "reason": "No dimentity"}
        return True

    code_col = "code" if "code" in dim.columns else "entity_code"
    extinct_col = "extinct_on" if "extinct_on" in dim.columns else None

    if code_col not in dim.columns:
        results["entity_coverage"] = {"pass": True, "reason": "No entity code column"}
        return True

    today_str = date.today().isoformat()
    if extinct_col and extinct_col in dim.columns:
        active = dim[dim[extinct_col].isna() | (dim[extinct_col].astype(str) > today_str)]
    else:
        active = dim

    active_codes = set(active[code_col].astype(str).str.upper())
    trained = get_trained_entities(output_base)
    missing = active_codes - trained

    if len(missing) > 50:  # Allow some gap (e.g. low-obs entities)
        results["entity_coverage"] = {
            "pass": False,
            "reason": f"{len(missing)} non-extinct entities lack models",
            "sample_missing": sorted(missing)[:10],
        }
        return False
    results["entity_coverage"] = {"pass": True, "missing_count": len(missing)}
    return True


def check_forecast_date_range(output_base: Path, results: dict) -> bool:
    """Forecasts extend at least 7 days into future?"""
    df = load_forecasts(output_base)
    if df is None or df.empty:
        results["forecast_date_range"] = {"pass": False, "reason": "No forecast file"}
        return False

    max_date = pd.to_datetime(df["park_date"]).max().date()
    min_required = date.today() + timedelta(days=7)
    if max_date < min_required:
        results["forecast_date_range"] = {
            "pass": False,
            "reason": f"Max forecast date {max_date} < required {min_required}",
        }
        return False
    results["forecast_date_range"] = {"pass": True, "max_date": str(max_date)}
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline post-run validation")
    parser.add_argument("--output-base", type=Path, default=get_output_base())
    args = parser.parse_args()

    output_base = args.output_base.resolve()
    out_dir = output_base / "pipeline_validation"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    check_forecast_coverage(output_base, results)
    check_wti_anomaly(output_base, results)
    check_entity_coverage(output_base, results)
    check_forecast_date_range(output_base, results)

    all_pass = all(r.get("pass", False) for r in results.values())

    # Write JSON
    json_path = out_dir / "validation_report.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)

    # Write human-readable summary
    txt_lines = ["Pipeline Validation Report", "=" * 40]
    for name, r in results.items():
        status = "PASS" if r.get("pass") else "FAIL"
        txt_lines.append(f"\n{name}: {status}")
        for k, v in r.items():
            if k != "pass":
                txt_lines.append(f"  {k}: {v}")
    txt_path = out_dir / "validation_report.txt"
    txt_path.write_text("\n".join(txt_lines), encoding="utf-8")

    print(f"Validation: {'PASS' if all_pass else 'FAIL'}")
    print(f"Report: {json_path}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
