#!/usr/bin/env python3
"""Detailed per-operation benchmark for a single entity forecast.

Run: python3 pipeline_v3/bench_entity_detail.py --output-base /home/wilma/hazeydata/pipeline
"""

import argparse
import time
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

if str(Path(__file__).parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline_v3.config import load_config
from pipeline_v3.core.logging import PipelineLogger
from pipeline_v3.steps.s08_forecast import (
    _load_date_features, _load_park_hours, _load_aggregates_df,
    _load_operating_calendar, _generate_park_time_grid,
)

FEATURES = ["mins_since_6am", "mins_since_open", "date_group_id_encoded", "season_encoded", "season_year_encoded"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-base", type=Path, default=Path("/home/wilma/hazeydata/pipeline"))
    parser.add_argument("--entity", default="MK01")
    parser.add_argument("--park", default="MK")
    args = parser.parse_args()

    cfg = load_config(output_base=args.output_base)
    log = PipelineLogger("bench", None)

    # Load shared data
    print("Loading shared data...")
    df_feat = _load_date_features(cfg, log)
    ph = _load_park_hours(cfg, log)
    agg = _load_aggregates_df(cfg, log)
    oc = _load_operating_calendar(cfg, log)

    sd = date.today() + timedelta(1)
    ed = sd + timedelta(365)
    grid = _generate_park_time_grid(sd, ed, df_feat, ph, args.park, "America/New_York")
    po = {}
    for d in range(366):
        dd = sd + timedelta(d)
        h = ph.get((args.park, dd))
        po[dd] = h[0] if h and h[0] else 360

    print(f"\n--- ENTITY DETAIL: {args.entity} ({len(grid):,} grid rows) ---")

    # 1. Copy grid
    t = time.time()
    g = grid.copy()
    g["entity_code"] = args.entity
    print(f"  copy grid:     {time.time()-t:.4f}s")

    # 2. Operating calendar filter
    t = time.time()
    if oc is not None:
        ec = args.entity.upper()
        op_dates = {d for (e, d) in oc if e == ec}
        if op_dates:
            g = g[g["park_date"].isin(op_dates)]
    print(f"  OC filter:     {time.time()-t:.4f}s ({len(g):,} rows after)")

    # 3. Merge aggregates
    t = time.time()
    ea = agg[agg["entity_code"] == args.entity]
    if len(ea) > 0:
        g = g.merge(
            ea[["date_group_id", "time_slot_15min", "wait_median"]],
            on=["date_group_id", "time_slot_15min"],
            how="left",
        )
        g["posted_time"] = g["wait_median"].fillna(5.0)
        g.drop(columns=["wait_median"], inplace=True)
    else:
        g["posted_time"] = 5.0
    print(f"  merge agg:     {time.time()-t:.4f}s")

    # 4. mins_since_open
    t = time.time()
    g["_o"] = g["park_date"].map(po).fillna(360)
    g["mins_since_open"] = (g["mins_since_6am"] + 360 - g["_o"]).clip(lower=0)
    g.drop(columns=["_o"], inplace=True)
    print(f"  mins_open:     {time.time()-t:.4f}s")

    # 5. Load model
    t = time.time()
    model_path = cfg.models_dir / args.entity / "model_v3.json"
    if not model_path.exists():
        model_path = cfg.models_dir / args.entity / "model_julia_actuals.json"
    if not model_path.exists():
        print(f"  No model found for {args.entity}")
        return
    m = xgb.XGBRegressor()
    m.load_model(str(model_path))
    print(f"  load model:    {time.time()-t:.4f}s ({model_path.name})")

    # 6. Build feature matrix
    t = time.time()
    X = g[FEATURES].values.astype(np.float32)
    print(f"  build X:       {time.time()-t:.4f}s ({X.shape})")

    # 7. Predict
    t = time.time()
    preds = m.predict(X)
    print(f"  predict:       {time.time()-t:.4f}s ({len(preds):,} predictions)")

    # 8. Post-process
    t = time.time()
    preds = np.clip(preds, 0, 300)
    g["predicted_actual"] = np.round(preds).astype(int)
    g["prediction_method"] = "model_v3"
    out = g[["entity_code", "park_date", "time_slot", "predicted_actual", "prediction_method"]]
    print(f"  post-process:  {time.time()-t:.4f}s")

    print(f"\n  TOTAL per entity: sum of above")
    print(f"  × 405 entities = estimated total forecast time")


if __name__ == "__main__":
    main()
