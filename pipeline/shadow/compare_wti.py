"""Compare v3 WTI output against production WTI.

Usage:
    python -m pipeline_v3.shadow.compare_wti

Reads:
    - pipeline_v3 WTI: wti/wti_v3.parquet
    - Production WTI:   wti/wti.parquet

Outputs:
    - Per-park MAE between v3 and production
    - Dates where they diverge significantly
    - Recommendation: is v3 ready to swap?
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pipeline_v3.config import load_config


def compare(output_base: Path | None = None) -> dict:
    cfg = load_config(**(dict(output_base=output_base, shadow=True) if output_base else dict(shadow=True)))

    v3_path = cfg.wti_dir / "wti_v3.parquet"
    prod_path = cfg.prod_output_base / "wti" / "wti.parquet"

    if not v3_path.exists() or not prod_path.exists():
        return {"error": "Missing WTI files", "v3_exists": v3_path.exists(), "prod_exists": prod_path.exists()}

    v3 = pd.read_parquet(v3_path)
    prod = pd.read_parquet(prod_path)

    # Join on park_code + park_date
    merged = v3.merge(
        prod, on=["park_code", "park_date"], suffixes=("_v3", "_prod")
    )

    if len(merged) == 0:
        return {"error": "No overlapping park-dates between v3 and production"}

    merged["diff"] = merged["wti_v3"] - merged["wti_prod"]
    merged["abs_diff"] = merged["diff"].abs()

    # Per-park comparison
    park_stats = []
    for park in sorted(merged["park_code"].unique()):
        pm = merged[merged["park_code"] == park]
        park_stats.append({
            "park": park,
            "n_dates": len(pm),
            "mae_between_v3_and_prod": round(pm["abs_diff"].mean(), 2),
            "mean_diff": round(pm["diff"].mean(), 2),
            "max_diff": round(pm["abs_diff"].max(), 2),
        })

    overall_mae = round(merged["abs_diff"].mean(), 2)
    overall_bias = round(merged["diff"].mean(), 2)

    result = {
        "n_park_dates_compared": len(merged),
        "overall_mae_v3_vs_prod": overall_mae,
        "overall_bias_v3_vs_prod": overall_bias,
        "parks": park_stats,
        "recommendation": "swap" if overall_mae < 1.0 else "investigate" if overall_mae < 3.0 else "not ready",
    }

    return result


if __name__ == "__main__":
    result = compare()
    print(json.dumps(result, indent=2))
