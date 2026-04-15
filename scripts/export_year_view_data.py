#!/usr/bin/env python3
"""
Export year-view JSON data for hazeydata.ai interactive heatmap.

Reads WTI parquet and exports one JSON file per park with 365 days of data.
Enriches busiest-week data with headliner ride peak waits from forecast curves.
These static JSONs get deployed to Cloudflare Pages alongside year-view.html.

Output: /home/wilma/hazeydata.ai/year-view-data/<PARK_CODE>.json

Run after WTI calculation in the daily pipeline.
"""

import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

WTI_PATH = "/home/wilma/hazeydata/pipeline/wti/wti.parquet"
FORECAST_PATH = "/mnt/data/pipeline/curves/forecast_parquet/all_forecasts.parquet"
DIMENTITY_PATH = "/mnt/data/pipeline/dimension_tables/dimentity.csv"
OUTPUT_DIR = Path("/home/wilma/hazeydata.ai/theme-park-crowd-report/year-view-data")

PARK_NAMES = {
    "MK": "Magic Kingdom",
    "EP": "EPCOT",
    "HS": "Hollywood Studios",
    "AK": "Animal Kingdom",
    "DL": "Disneyland",
    "CA": "California Adventure",
    "UF": "Universal Studios Florida",
    "IA": "Islands of Adventure",
    "EU": "Epic Universe",
    "UH": "Universal Studios Hollywood",
    "TDL": "Tokyo Disneyland",
    "TDS": "Tokyo DisneySea",
}

# Top 3 headliner rides per park — the ones visitors care about most.
# Used to show "what you'll experience" in the busiest weeks section.
HEADLINERS = {
    "MK":  ["MK191", "MK141", "MK01"],    # TRON, Seven Dwarfs, Space Mountain
    "EP":  ["EP197", "EP14", "EP155"],      # Guardians, Test Track, Frozen
    "HS":  ["HS113", "HS103", "HS12"],      # Rise of Resistance, Slinky Dog, Rock 'n' Roller
    "AK":  ["AK86", "AK85", "AK07"],       # Flight of Passage, Na'vi River, Kilimanjaro
    "DL":  ["DL180", "DL179", "DL46"],     # Rise of Resistance, Smuggler's, Space Mountain
    "CA":  ["CA109", "CA188", "CA155"],     # Radiator Springs, WEB Slingers, Guardians
    "UF":  ["UF63", "UF48", "UF30"],       # Escape from Gringotts, Hollywood Rip Ride, Transformers
    "IA":  ["IA65", "IA69", "IA16"],       # Hagrid's, VelociCoaster, Forbidden Journey
    "EU":  ["EU07", "EU06", "EU04"],       # Battle at Ministry, Mine-Cart Madness, Mario Kart
    "UH":  ["UH46", "UH13", "UH52"],      # Mario Kart, Jurassic World, Studio Tour
    "TDL": ["TDL60", "TDL14", "TDL61"],   # Enchanted Tale, Splash Mountain, Baymax
    "TDS": ["TDS56", "TDS50", "TDS15"],   # Frozen Journey, Soaring, Toy Story Mania
}


def load_entity_names():
    """Load entity code → display name mapping from dimentity."""
    if not os.path.exists(DIMENTITY_PATH):
        log.warning("dimentity.csv not found, using codes as names")
        return {}
    dim = pd.read_csv(DIMENTITY_PATH)
    # Use short_name if available, otherwise name
    names = {}
    for _, row in dim.iterrows():
        code = row.get("code", "")
        short = row.get("short_name", "")
        full = row.get("name", "")
        # Prefer a clean short name, fall back to full
        names[code] = short if short and len(short) < 25 else full
    return names


def compute_headliner_peaks(park_code, busiest_week_starts):
    """
    For the busiest weeks, compute peak daily wait for each headliner ride.
    Returns dict: { "2026-12-28": [{"ride": "TRON", "peak": 110}, ...], ... }
    """
    headliner_codes = HEADLINERS.get(park_code, [])
    if not headliner_codes or not os.path.exists(FORECAST_PATH):
        return {}

    entity_names = load_entity_names()

    # Build date ranges for all busiest weeks (7 days each)
    all_dates = set()
    for ws in busiest_week_starts:
        start = datetime.strptime(ws, "%Y-%m-%d").date()
        for i in range(7):
            all_dates.add(start + timedelta(days=i))

    if not all_dates:
        return {}

    try:
        # Read only the headliner entities from forecast parquet
        df = pd.read_parquet(
            FORECAST_PATH,
            columns=["entity_code", "park_date", "predicted_actual"],
            filters=[("entity_code", "in", headliner_codes)],
        )

        # Filter to just our week dates
        df = df[df["park_date"].isin(all_dates)]

        if df.empty:
            return {}

        # Get peak daily wait per entity per date, then max per week
        daily_peaks = df.groupby(["entity_code", "park_date"])["predicted_actual"].max().reset_index()

        result = {}
        for ws in busiest_week_starts:
            start = datetime.strptime(ws, "%Y-%m-%d").date()
            end = start + timedelta(days=6)
            week_data = daily_peaks[
                (daily_peaks["park_date"] >= start) & (daily_peaks["park_date"] <= end)
            ]
            week_peaks = (
                week_data.groupby("entity_code")["predicted_actual"]
                .max()
                .sort_values(ascending=False)
            )

            rides = []
            for code, peak in week_peaks.items():
                name = entity_names.get(code, code)
                rides.append({"ride": name, "code": code, "peak": round(peak)})

            if rides:
                result[ws] = rides

        return result

    except Exception as e:
        log.warning("  Error computing headliner peaks for %s: %s", park_code, e)
        return {}


def main():
    log.info("=" * 60)
    log.info("EXPORT YEAR-VIEW DATA")
    log.info("=" * 60)

    if not os.path.exists(WTI_PATH):
        log.error("WTI file not found: %s", WTI_PATH)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    today = date.today()
    end_date = today + timedelta(days=380)  # #469: extended from 365

    exported = 0
    for park_code, park_name in PARK_NAMES.items():
        try:
            df = con.execute(f"""
                SELECT 
                    park_date::DATE::TEXT as date,
                    ROUND(wti, 1) as wti
                FROM read_parquet('{WTI_PATH}')
                WHERE park_code = '{park_code}'
                  AND park_date >= '{today}'
                  AND park_date <= '{end_date}'
                ORDER BY park_date
            """).fetchdf()

            if df.empty:
                log.warning("  No data for %s (%s), skipping", park_code, park_name)
                continue

            # Compute weekly averages to find the 5 busiest weeks
            days = df.to_dict(orient="records")
            weeks = {}
            for d in days:
                dt = datetime.strptime(d["date"], "%Y-%m-%d").date()
                # Week starts on Monday
                week_start = dt - timedelta(days=dt.weekday())
                ws_key = week_start.isoformat()
                if ws_key not in weeks:
                    weeks[ws_key] = {"wti_sum": 0.0, "count": 0}
                weeks[ws_key]["wti_sum"] += d["wti"]
                weeks[ws_key]["count"] += 1

            # Only include full weeks (5+ days)
            week_list = [
                {"start": k, "avg_wti": round(v["wti_sum"] / v["count"], 1)}
                for k, v in weeks.items()
                if v["count"] >= 5
            ]
            week_list.sort(key=lambda w: w["avg_wti"], reverse=True)
            busiest_5 = week_list[:5]
            busiest_starts = [w["start"] for w in busiest_5]

            # Get headliner ride peaks for busiest weeks
            headliner_peaks = {}
            if busiest_starts and park_code in HEADLINERS:
                log.info("  Computing headliner peaks for %s...", park_code)
                headliner_peaks = compute_headliner_peaks(park_code, busiest_starts)

            data = {
                "park_code": park_code,
                "park_name": park_name,
                "generated": today.isoformat(),
                "days": days,
            }

            # Only include headliner data if we got it
            if headliner_peaks:
                data["headliner_peaks"] = headliner_peaks

            output_file = OUTPUT_DIR / f"{park_code}.json"
            with open(output_file, "w") as f:
                json.dump(data, f, separators=(",", ":"))  # compact JSON

            size_kb = output_file.stat().st_size / 1024
            log.info("  %s (%s): %d days, %.1f KB", park_code, park_name, len(df), size_kb)
            if headliner_peaks:
                log.info("    → headliner peaks for %d busiest weeks", len(headliner_peaks))
            exported += 1

        except Exception as e:
            log.warning("  Error exporting %s: %s", park_code, e)

    con.close()

    log.info("=" * 60)
    log.info("Exported %d park JSON files to %s", exported, OUTPUT_DIR)
    log.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
