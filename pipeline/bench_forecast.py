#!/usr/bin/env python3
"""Benchmark script to profile where forecast time is spent.

Run: python3 pipeline/bench_forecast.py --output-base /home/wilma/hazeydata/pipeline
"""

import argparse
import time
from datetime import date, timedelta
from pathlib import Path
import sys

if str(Path(__file__).parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.config import load_config
from pipeline.core.logging import PipelineLogger
from pipeline.core.park_codes import PARK_TIMEZONE, entity_to_park
from pipeline.steps.s08_forecast import (
    _load_date_features, _load_park_hours, _load_aggregates_df,
    _load_entity_list, _load_operating_calendar, _load_fallback_ratios,
    _generate_park_time_grid, _forecast_entity_vectorized,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-base", type=Path, default=Path("/home/wilma/hazeydata/pipeline"))
    args = parser.parse_args()

    cfg = load_config(output_base=args.output_base)
    log = PipelineLogger("bench", None)

    print("=" * 60)
    print("FORECAST BENCHMARK")
    print("=" * 60)

    # Phase 1: Data loading
    timings = {}
    t0 = time.time()
    date_features = _load_date_features(cfg, log)
    timings["date_features"] = time.time() - t0

    t = time.time()
    park_hours = _load_park_hours(cfg, log)
    timings["park_hours"] = time.time() - t

    t = time.time()
    agg_df = _load_aggregates_df(cfg, log)
    timings["aggregates"] = time.time() - t

    t = time.time()
    entities = _load_entity_list(cfg, log)
    timings["entity_list"] = time.time() - t

    t = time.time()
    oc = _load_operating_calendar(cfg, log)
    timings["operating_cal"] = time.time() - t

    t = time.time()
    ratios = _load_fallback_ratios(cfg, log)
    timings["fallback_ratios"] = time.time() - t

    total_load = time.time() - t0
    print(f"\n--- DATA LOADING ---")
    for k, v in timings.items():
        print(f"  {k}: {v:.2f}s")
    print(f"  TOTAL: {total_load:.2f}s")

    # Phase 2: Grid generation
    start_date = date.today() + timedelta(days=1)
    end_date = start_date + timedelta(days=365)

    print(f"\n--- GRID GENERATION (365 days) ---")
    for park in ["MK", "EP", "IA", "TDL"]:
        tz = PARK_TIMEZONE.get(park, "America/New_York")
        t = time.time()
        grid = _generate_park_time_grid(start_date, end_date, date_features, park_hours, park, tz)
        dur = time.time() - t
        n = len(grid) if grid is not None else 0
        print(f"  {park}: {dur:.2f}s, {n:,} rows")

    # Phase 3: Entity forecast (sample 5 entities from MK)
    print(f"\n--- ENTITY FORECAST (MK, sample) ---")
    mk_grid = _generate_park_time_grid(start_date, end_date, date_features, park_hours, "MK", "America/New_York")
    park_open = {}
    for d_offset in range((end_date - start_date).days + 1):
        dd = start_date + timedelta(days=d_offset)
        h = park_hours.get(("MK", dd))
        park_open[dd] = h[0] if h and h[0] else 360

    mk_entities = [e for e in entities if entity_to_park(e) == "MK"][:5]
    for entity in mk_entities:
        t = time.time()
        result = _forecast_entity_vectorized(
            entity, "MK", mk_grid, cfg.models_dir, agg_df, park_open, ratios, oc
        )
        dur = time.time() - t
        n = len(result) if result is not None else 0
        print(f"  {entity}: {dur:.2f}s, {n:,} predictions")

    # Phase 4: Full park benchmark (MK only)
    print(f"\n--- FULL PARK FORECAST (MK, all entities) ---")
    t = time.time()
    total_preds = 0
    for entity in mk_entities:
        result = _forecast_entity_vectorized(
            entity, "MK", mk_grid, cfg.models_dir, agg_df, park_open, ratios, oc
        )
        if result is not None:
            total_preds += len(result)
    mk_dur = time.time() - t
    print(f"  {len(mk_entities)} entities: {mk_dur:.2f}s, {total_preds:,} predictions")
    print(f"  Per entity: {mk_dur/max(len(mk_entities),1):.2f}s")
    print(f"  Estimated full (405 entities): {mk_dur/max(len(mk_entities),1) * 405:.0f}s ({mk_dur/max(len(mk_entities),1) * 405 / 60:.1f} min)")

    print(f"\n{'=' * 60}")
    print(f"DONE")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
