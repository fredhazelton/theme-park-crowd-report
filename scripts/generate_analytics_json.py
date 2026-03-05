#!/usr/bin/env python3
"""
generate_analytics_json.py — Build analytics JSON files for Mission Control v3.

Reads from pipeline parquet/JSON files and generates JSON consumable by
the MC v3 Analytics dashboard.

Output files:
  docs/analytics-data/accuracy_summary.json
  docs/analytics-data/daily_accuracy.json
  docs/analytics-data/entity_scores.json
  docs/analytics-data/entity_list.json
  docs/analytics-data/entity_curves/{entity_code}/{park_date}.json
"""

import json
import os
import shutil
from pathlib import Path

import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS = PROJECT_ROOT / "docs"
OUT = DOCS / "analytics-data"
CURVES_DIR = OUT / "entity_curves"

ACCURACY_DIR = Path("/mnt/data/pipeline/accuracy")
SLOT_PARQUET = ACCURACY_DIR / "slot_accuracy.parquet"
DAILY_PARQUET = ACCURACY_DIR / "entity_daily_accuracy.parquet"
SUMMARY_JSON = ACCURACY_DIR / "accuracy_summary.json"

ENTITY_NAMES_CSV = Path.home() / "clawd-anthropic" / "entity_short_names_v3.csv"
HAZEYDATA_ENTITIES = Path("/mnt/data/pipeline/dimension_tables/hazeydata_entities.csv")

PARK_NAMES = {
    "ca": "DCA",
    "dl": "Disneyland",
    "td": "Tokyo Disney",
    "eu": "Epic Universe",
    "ia": "Islands of Adventure",
    "uf": "Universal FL",
    "vb": "Volcano Bay",
    "uh": "Universal Hollywood",
    "ak": "Animal Kingdom",
    "bb": "Blizzard Beach",
    "ep": "EPCOT",
    "hs": "Hollywood Studios",
    "mk": "Magic Kingdom",
    "tl": "Tokyo DisneySea",
}


def load_entity_lookup() -> dict:
    """Build entity_code → {name, park} lookup from hazeydata_entities + short names."""
    hz = pd.read_csv(HAZEYDATA_ENTITIES)
    # touringplans_code is the entity_code used in accuracy data
    hz = hz[hz.touringplans_code.notna()].copy()
    hz["park"] = hz.park_code.map(PARK_NAMES).fillna(hz.park_code)

    # Prefer short names from our curated CSV
    names = pd.read_csv(ENTITY_NAMES_CSV)
    name_map = dict(zip(names["code"], names["new_short_name"]))

    lookup = {}
    for _, row in hz.iterrows():
        code = row.touringplans_code
        name = name_map.get(code, row.short_name if pd.notna(row.short_name) else row["name"])
        lookup[code] = {"name": name, "park": row.park}
    return lookup


def write_json(path: Path, data):
    """Write JSON with compact formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"), default=str)
    print(f"  ✓ {path.relative_to(PROJECT_ROOT)}  ({path.stat().st_size:,} bytes)")


def gen_accuracy_summary():
    """Copy + enhance the pipeline accuracy_summary.json."""
    with open(SUMMARY_JSON) as f:
        summary = json.load(f)
    # Round floats for display
    for k in ["overall_mae", "overall_bias", "overall_rmse", "overall_mape",
              "mae_1day", "mae_7day", "mae_30day", "wti_mae", "wti_bias", "wti_median_ae"]:
        if k in summary and isinstance(summary[k], float):
            summary[k] = round(summary[k], 2)
    write_json(OUT / "accuracy_summary.json", summary)


def gen_daily_accuracy(daily: pd.DataFrame, entity_lookup: dict):
    """Aggregate entity_daily_accuracy by park_date → daily MAE/bias/n_entities."""
    agg = (
        daily.groupby("park_date")
        .agg(
            mae=("mae", "mean"),
            bias=("bias", "mean"),
            rmse=("rmse", "mean"),
            n_entities=("entity_code", "nunique"),
        )
        .reset_index()
        .sort_values("park_date")
    )
    # Round
    for col in ["mae", "bias", "rmse"]:
        agg[col] = agg[col].round(2)
    records = agg.to_dict(orient="records")
    write_json(OUT / "daily_accuracy.json", records)


def gen_entity_scores(daily: pd.DataFrame, entity_lookup: dict):
    """Aggregate by entity → avg MAE, bias, n_days, last_mae."""
    # Get last date per entity for last_mae
    daily_sorted = daily.sort_values("park_date")
    last_rows = daily_sorted.groupby("entity_code").last().reset_index()
    last_mae_map = dict(zip(last_rows.entity_code, last_rows.mae))

    agg = (
        daily.groupby("entity_code")
        .agg(
            avg_mae=("mae", "mean"),
            avg_bias=("bias", "mean"),
            avg_rmse=("rmse", "mean"),
            n_days=("park_date", "nunique"),
        )
        .reset_index()
    )
    agg["last_mae"] = agg.entity_code.map(last_mae_map)
    # Add name + park
    agg["name"] = agg.entity_code.map(lambda c: entity_lookup.get(c, {}).get("name", c))
    agg["park"] = agg.entity_code.map(lambda c: entity_lookup.get(c, {}).get("park", "?"))
    # Round
    for col in ["avg_mae", "avg_bias", "avg_rmse", "last_mae"]:
        agg[col] = agg[col].round(2)
    agg = agg.sort_values("avg_mae")
    records = agg[["entity_code", "name", "park", "avg_mae", "avg_bias", "avg_rmse", "n_days", "last_mae"]].to_dict(orient="records")
    write_json(OUT / "entity_scores.json", records)


def gen_entity_list(daily: pd.DataFrame, entity_lookup: dict):
    """Build dropdown list of entities."""
    entities = sorted(daily.entity_code.unique())
    records = []
    for code in entities:
        info = entity_lookup.get(code, {})
        records.append({
            "entity_code": code,
            "name": info.get("name", code),
            "park": info.get("park", "?"),
        })
    write_json(OUT / "entity_list.json", records)


def gen_entity_curves(slots: pd.DataFrame):
    """Generate per-entity per-date curve JSONs."""
    # Clean old curves
    if CURVES_DIR.exists():
        shutil.rmtree(CURVES_DIR)
    CURVES_DIR.mkdir(parents=True, exist_ok=True)

    count = 0
    for (entity_code, park_date), group in slots.groupby(["entity_code", "park_date"]):
        sub = group.sort_values("time_slot")[["time_slot", "forecast_wait", "actual_wait"]].copy()
        sub["forecast_wait"] = sub["forecast_wait"].round(1)
        sub["actual_wait"] = sub["actual_wait"].round(1)
        records = sub.to_dict(orient="records")
        out_path = CURVES_DIR / entity_code / f"{park_date}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(records, f, separators=(",", ":"), default=str)
        count += 1

    print(f"  ✓ entity_curves/  ({count:,} curve files)")


def main():
    print("=" * 60)
    print("Mission Control v3 — Analytics JSON Generator")
    print("=" * 60)

    print("\nLoading data...")
    entity_lookup = load_entity_lookup()
    print(f"  Entity lookup: {len(entity_lookup)} entities")

    daily = pd.read_parquet(DAILY_PARQUET)
    print(f"  entity_daily_accuracy: {len(daily):,} rows, {daily.entity_code.nunique()} entities, {daily.park_date.nunique()} dates")

    slots = pd.read_parquet(SLOT_PARQUET)
    print(f"  slot_accuracy: {len(slots):,} rows")

    print("\nGenerating JSON files...")

    # 1. Accuracy summary
    gen_accuracy_summary()

    # 2. Daily accuracy
    gen_daily_accuracy(daily, entity_lookup)

    # 3. Entity scores
    gen_entity_scores(daily, entity_lookup)

    # 4. Entity list
    gen_entity_list(daily, entity_lookup)

    # 5. Entity curves
    gen_entity_curves(slots)

    print("\n✅ All analytics JSON files generated successfully!")
    print(f"   Output: {OUT.relative_to(PROJECT_ROOT)}/")


if __name__ == "__main__":
    main()
