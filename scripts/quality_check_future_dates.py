#!/usr/bin/env python3
"""
Quality Check: Future Dates

Validates that dimparkhours.csv and dimdategroupid.csv have complete
coverage from tomorrow through the global forecast horizon.

Checks:
  - Every park-date exists in dimparkhours
  - Every park-date has non-NULL opening/closing times
  - Every date exists in dimdategroupid
  - Every date has a non-NULL date_group_id

Exit code 1 if critical issues found (missing park-dates in dimparkhours).

Usage:
    python scripts/quality_check_future_dates.py
    python scripts/quality_check_future_dates.py --output-base /path/to/pipeline
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# Add src to path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.paths import get_output_base
from utils.forecast_horizon import get_forecast_end_date


def main() -> int:
    ap = argparse.ArgumentParser(description="Quality check future date coverage")
    ap.add_argument(
        "--output-base",
        type=Path,
        default=get_output_base(),
        help="Output base directory",
    )
    args = ap.parse_args()

    base = args.output_base.resolve()
    dim_dir = base / "dimension_tables"

    parkhours_file = dim_dir / "dimparkhours.csv"
    dategroupid_file = dim_dir / "dimdategroupid.csv"

    tomorrow = date.today() + timedelta(days=1)
    end_date = get_forecast_end_date()
    future_dates = set(
        (tomorrow + timedelta(days=i)).isoformat()
        for i in range((end_date - tomorrow).days + 1)
    )

    print("=" * 60)
    print("QUALITY CHECK: FUTURE DATE COVERAGE")
    print("=" * 60)
    print(f"Forecast window: {tomorrow} → {end_date} ({len(future_dates)} days)")
    print(f"Output base:     {base}")
    print()

    issues: dict[str, int] = {
        "missing_parkhours_rows": 0,
        "null_opening_time": 0,
        "null_closing_time": 0,
        "null_emh_opening": 0,
        "null_emh_closing": 0,
        "missing_dategroupid_rows": 0,
        "null_date_group_id": 0,
    }

    # ── dimparkhours ─────────────────────────────────────────────
    if not parkhours_file.exists():
        print(f"❌  dimparkhours.csv NOT FOUND at {parkhours_file}")
        return 1

    ph = pd.read_csv(parkhours_file, dtype=str)
    park_map = (
        ph[["park_id", "park"]]
        .drop_duplicates()
        .dropna(subset=["park_id", "park"])
    )
    all_parks = sorted(park_map["park_id"].unique())
    print(f"Parks in dimparkhours: {len(all_parks)}")
    print(f"  Codes: {sorted(park_map['park'].unique())}")
    print()

    # Filter to future rows only
    ph_future = ph[ph["date"].isin(future_dates)].copy()
    existing_keys = set(zip(ph_future["park_id"], ph_future["date"]))

    # Check missing park-date rows
    missing_by_park: dict[str, int] = {}
    for d in sorted(future_dates):
        for pid in all_parks:
            if (pid, d) not in existing_keys:
                issues["missing_parkhours_rows"] += 1
                park_code = park_map.loc[park_map["park_id"] == pid, "park"].iloc[0]
                missing_by_park[park_code] = missing_by_park.get(park_code, 0) + 1

    # Check null times in future rows
    for _, row in ph_future.iterrows():
        ot = row.get("opening_time", "")
        ct = row.get("closing_time", "")
        oe = row.get("opening_time_with_emh", "")
        ce = row.get("closing_time_with_emh_or_party", "")
        if pd.isna(ot) or ot == "":
            issues["null_opening_time"] += 1
        if pd.isna(ct) or ct == "":
            issues["null_closing_time"] += 1
        if pd.isna(oe) or oe == "":
            issues["null_emh_opening"] += 1
        if pd.isna(ce) or ce == "":
            issues["null_emh_closing"] += 1

    # ── dimdategroupid ───────────────────────────────────────────
    if not dategroupid_file.exists():
        print(f"❌  dimdategroupid.csv NOT FOUND at {dategroupid_file}")
        issues["missing_dategroupid_rows"] = len(future_dates)
    else:
        dg = pd.read_csv(dategroupid_file, dtype=str)
        dg_dates = set(dg["park_date"].dropna())
        for d in future_dates:
            if d not in dg_dates:
                issues["missing_dategroupid_rows"] += 1

        dg_future = dg[dg["park_date"].isin(future_dates)]
        null_dgid = dg_future["date_group_id"].isna() | (dg_future["date_group_id"] == "")
        issues["null_date_group_id"] = int(null_dgid.sum())

    # ── Summary ──────────────────────────────────────────────────
    total_issues = sum(issues.values())
    total_parkdates = len(future_dates) * len(all_parks)

    print("─" * 60)
    print("RESULTS")
    print("─" * 60)
    print(f"Future dates checked:        {len(future_dates):,}")
    print(f"Parks:                       {len(all_parks)}")
    print(f"Total park-dates expected:   {total_parkdates:,}")
    print()

    print("dimparkhours:")
    print(f"  Missing park-date rows:    {issues['missing_parkhours_rows']:,}")
    if missing_by_park:
        for park, cnt in sorted(missing_by_park.items(), key=lambda x: -x[1]):
            print(f"    {park}: {cnt:,} missing")
    print(f"  NULL opening_time:         {issues['null_opening_time']:,}")
    print(f"  NULL closing_time:         {issues['null_closing_time']:,}")
    print(f"  NULL emh opening:          {issues['null_emh_opening']:,}")
    print(f"  NULL emh closing:          {issues['null_emh_closing']:,}")
    print()

    print("dimdategroupid:")
    print(f"  Missing date rows:         {issues['missing_dategroupid_rows']:,}")
    print(f"  NULL date_group_id:        {issues['null_date_group_id']:,}")
    print()

    print("─" * 60)
    if total_issues == 0:
        print("✅  All checks passed — full future coverage")
    else:
        print(f"⚠️   Total issues: {total_issues:,}")

    # Critical = missing park-date rows in dimparkhours
    critical = issues["missing_parkhours_rows"] > 0
    if critical:
        print("❌  CRITICAL: Missing park-date rows in dimparkhours!")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
