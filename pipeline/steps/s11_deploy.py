"""Step 11: Deploy \u2014 Load results into DuckDB + Cloudflare.

The ONLY step that writes to DuckDB. All previous steps work with parquet.

In shadow mode: skip deployment entirely (just compare outputs).
In production: load forecasts + WTI into tpcr_live.duckdb, restart API.
"""

from __future__ import annotations

import pandas as pd

from pipeline_v3.config import PipelineConfig
from pipeline_v3.core.db import write_connection
from pipeline_v3.core.logging import PipelineLogger


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Deploy pipeline outputs."""

    log.info("=" * 60)
    log.info("STEP 11: DEPLOY")
    log.info("=" * 60)

    if cfg.shadow:
        log.info("Shadow mode: skipping deployment. Run shadow/compare_wti.py to compare outputs.")
        return {"rows": 0, "action": "skipped_shadow"}

    # Load WTI into DuckDB
    wti_path = cfg.wti_dir / "wti_v3.parquet"
    if wti_path.exists():
        with log.timed("deploy WTI to DuckDB"):
            wti_df = pd.read_parquet(wti_path)
            with write_connection(cfg.duckdb_path) as con:
                min_d = wti_df["park_date"].min()
                max_d = wti_df["park_date"].max()
                con.execute(
                    "DELETE FROM wti WHERE park_date >= ? AND park_date <= ?",
                    [min_d, max_d],
                )
                con.register("_wti", wti_df)
                con.execute("""
                    INSERT INTO wti (park_code, park_date, time_slot, wti, source, updated_at)
                    SELECT park_code, park_date::DATE, 'daily', wti,
                           COALESCE(source, 'forecast'), CURRENT_TIMESTAMP
                    FROM _wti
                """)
                con.execute("""
                    INSERT OR REPLACE INTO data_freshness (source, last_updated, row_count, notes)
                    VALUES ('wti', CURRENT_TIMESTAMP, (SELECT COUNT(*) FROM wti), 'pipeline_v3')
                """)
            log.info(f"WTI deployed: {len(wti_df):,} rows")
    else:
        log.warning("No v3 WTI file to deploy")

    # Load forecasts into DuckDB
    forecast_path = cfg.forecast_dir / "all_forecasts_v3.parquet"
    if forecast_path.exists():
        with log.timed("deploy forecasts to DuckDB"):
            fc_df = pd.read_parquet(forecast_path)
            with write_connection(cfg.duckdb_path) as con:
                min_d = fc_df["park_date"].min()
                max_d = fc_df["park_date"].max()
                if hasattr(min_d, "date"):
                    min_d = min_d.date()
                if hasattr(max_d, "date"):
                    max_d = max_d.date()
                con.execute(
                    "DELETE FROM forecasts WHERE park_date >= ? AND park_date <= ?",
                    [min_d, max_d],
                )
                con.register("_fc", fc_df)
                con.execute("""
                    INSERT INTO forecasts (
                        entity_code, park_date, time_slot,
                        predicted_actual, prediction_method, updated_at
                    )
                    SELECT entity_code, park_date::DATE, CAST(time_slot AS VARCHAR),
                           predicted_actual, COALESCE(prediction_method, 'model'),
                           CURRENT_TIMESTAMP
                    FROM _fc
                """)
                con.execute("""
                    INSERT OR REPLACE INTO data_freshness (source, last_updated, row_count, notes)
                    VALUES ('forecasts', CURRENT_TIMESTAMP, (SELECT COUNT(*) FROM forecasts), 'pipeline_v3')
                """)
            log.info(f"Forecasts deployed: {len(fc_df):,} rows")
            del fc_df
    else:
        log.warning("No v3 forecast file to deploy")

    return {"rows": 0, "action": "deployed"}
