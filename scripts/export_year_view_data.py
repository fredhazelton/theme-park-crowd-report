#!/usr/bin/env python3
"""
Export year-view JSON data for hazeydata.ai interactive heatmap.

Reads WTI parquet and exports one JSON file per park with 365 days of data.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

WTI_PATH = "/home/wilma/hazeydata/pipeline/wti/wti.parquet"
OUTPUT_DIR = Path("/home/wilma/hazeydata.ai/year-view-data")

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
    end_date = today + timedelta(days=365)

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

            data = {
                "park_code": park_code,
                "park_name": park_name,
                "generated": today.isoformat(),
                "days": df.to_dict(orient="records"),
            }

            output_file = OUTPUT_DIR / f"{park_code}.json"
            with open(output_file, "w") as f:
                json.dump(data, f, separators=(",", ":"))  # compact JSON

            size_kb = output_file.stat().st_size / 1024
            log.info("  %s (%s): %d days, %.1f KB", park_code, park_name, len(df), size_kb)
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
