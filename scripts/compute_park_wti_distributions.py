#!/usr/bin/env python3
"""
Compute per-park WTI distributions from historical data.

Output: state/park_wti_distributions.json
Also copies to hazeydata.ai for static web access.

Used by all visual surfaces (Discord bot, stream dashboard, web) for
per-park Benedictus color scaling. A "red day" at MK means busy FOR MK,
not compared to all parks.

Run after WTI calculation in the daily pipeline.
"""

import json
import logging
import os
import sys
from pathlib import Path

import duckdb

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

WTI_PATH = "/home/wilma/hazeydata/pipeline/wti/wti.parquet"
OUTPUT_PATH = "/mnt/data/pipeline/state/park_wti_distributions.json"
WEB_OUTPUT_PATH = "/home/wilma/hazeydata.ai/year-view-data/distributions.json"


def main():
    log.info("=" * 60)
    log.info("COMPUTE PARK WTI DISTRIBUTIONS")
    log.info("=" * 60)

    if not os.path.exists(WTI_PATH):
        log.error("WTI file not found: %s", WTI_PATH)
        return 1

    con = duckdb.connect()

    df = con.execute(f"""
        SELECT
            park_code,
            COUNT(*) as n_days,
            ROUND(MIN(wti), 1) as min,
            ROUND(PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY wti), 1) as p5,
            ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY wti), 1) as p25,
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY wti), 1) as median,
            ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY wti), 1) as p75,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY wti), 1) as p95,
            ROUND(MAX(wti), 1) as max
        FROM read_parquet('{WTI_PATH}')
        WHERE source = 'historical'
        GROUP BY park_code
        HAVING COUNT(*) >= 30
        ORDER BY park_code
    """).fetchdf()

    if df.empty:
        log.error("No historical WTI data found")
        con.close()
        return 1

    # Compute global "ALL" distribution for all-parks comparison (lollipop chart)
    all_df = con.execute(f"""
        SELECT
            COUNT(*) as n_days,
            ROUND(MIN(wti), 1) as min,
            ROUND(PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY wti), 1) as p5,
            ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY wti), 1) as p25,
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY wti), 1) as median,
            ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY wti), 1) as p75,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY wti), 1) as p95,
            ROUND(MAX(wti), 1) as max
        FROM read_parquet('{WTI_PATH}')
        WHERE source = 'historical'
    """).fetchdf()
    con.close()

    all_row = all_df.iloc[0]

    # Build the output dict (ALL first for lollipop chart)
    distributions = {
        "ALL": {
            "p5": float(all_row["p5"]),
            "p25": float(all_row["p25"]),
            "median": float(all_row["median"]),
            "p75": float(all_row["p75"]),
            "p95": float(all_row["p95"]),
            "min": float(all_row["min"]),
            "max": float(all_row["max"]),
            "n_days": int(all_row["n_days"]),
        }
    }
    log.info("  ALL: p5=%.1f  median=%.1f  p95=%.1f  (n=%d days)", all_row["p5"], all_row["median"], all_row["p95"], all_row["n_days"])
    for _, row in df.iterrows():
        park = row["park_code"]
        distributions[park] = {
            "p5": float(row["p5"]),
            "p25": float(row["p25"]),
            "median": float(row["median"]),
            "p75": float(row["p75"]),
            "p95": float(row["p95"]),
            "min": float(row["min"]),
            "max": float(row["max"]),
            "n_days": int(row["n_days"]),
        }
        log.info(
            "  %s: p5=%.1f  median=%.1f  p95=%.1f  (n=%d days)",
            park, row["p5"], row["median"], row["p95"], row["n_days"],
        )

    # Write to pipeline state
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(distributions, f, indent=2)
    log.info("Wrote %s (%d parks)", OUTPUT_PATH, len(distributions))

    # Also write to hazeydata.ai for web access
    os.makedirs(os.path.dirname(WEB_OUTPUT_PATH), exist_ok=True)
    with open(WEB_OUTPUT_PATH, "w") as f:
        json.dump(distributions, f, separators=(",", ":"))  # compact for web
    log.info("Wrote %s", WEB_OUTPUT_PATH)

    log.info("=" * 60)
    log.info("Done — %d parks with distributions", len(distributions))
    log.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
