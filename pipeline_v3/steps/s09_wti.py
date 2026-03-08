"""Step 9: WTI Calculation — v4 with adaptive quantile mapping.

v3: Global 1.5x stretch cap for quantile mapping.
v4: Per-park stretch factors optimized from historical accuracy (Pillar 3).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline_v3.config import PipelineConfig
from pipeline_v3.core.db import read_connection
from pipeline_v3.core.logging import PipelineLogger
from pipeline_v3.core.park_codes import park_code_sql
from pipeline_v3.core.validation import require_file, require_parquet_rows
from pipeline_v3.models.adaptive_quantile import optimize_stretch_factors


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Calculate WTI from forecasts and historical actuals."""

    log.info("=" * 60)
    log.info("STEP 9: WTI CALCULATION (v4 — adaptive quantile mapping)")
    log.info("=" * 60)

    results = []
    pc_sql = park_code_sql("entity_code")

    # === Pillar 3: Optimize per-park stretch factors ===
    with log.timed("optimize quantile mapping stretch factors"):
        stretch_factors = optimize_stretch_factors(cfg, log)
    log.info(f"Per-park stretch factors: {stretch_factors}")

    # Historical WTI
    with log.timed("historical WTI"):
        results.append(_compute_historical_wti(cfg, log, pc_sql))

    # Forecast WTI
    forecast_file = cfg.forecast_dir / "all_forecasts_v3.parquet"
    if not forecast_file.exists():
        forecast_file = cfg.forecast_dir / "all_forecasts.parquet"
    if forecast_file.exists():
        with log.timed("forecast WTI"):
            results.append(_compute_forecast_wti(cfg, log, pc_sql, forecast_file))
    else:
        log.warning(f"No forecast file found — forecast WTI skipped")

    # Adaptive quantile mapping with per-park stretch factors
    if cfg.quantile_mapping and len(results) >= 2:
        with log.timed("adaptive quantile mapping"):
            results = _apply_adaptive_quantile_mapping(cfg, log, results, stretch_factors)

    # Combine and save
    if not results or all(r is None for r in results):
        log.error("No WTI data produced")
        return {"rows": 0}

    combined = pd.concat([r for r in results if r is not None], ignore_index=True)
    combined = combined.sort_values(["park_code", "park_date", "source"])
    combined = combined.drop_duplicates(subset=["park_code", "park_date"], keep="first")

    output_path = cfg.wti_dir / "wti_v3.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(output_path, index=False)

    log.info(f"WTI written: {len(combined):,} park-dates to {output_path}")
    log.metric("wti_park_dates", len(combined))
    log.metric("wti_parks", combined["park_code"].nunique())

    return {"rows": len(combined), "path": str(output_path)}


def _compute_historical_wti(
    cfg: PipelineConfig, log: PipelineLogger, pc_sql: str
) -> pd.DataFrame | None:
    """Compute historical WTI from synthetic actuals + real actuals."""
    synth_dir = cfg.output_base / "synthetic_actuals"
    if not synth_dir.exists() or not any(synth_dir.glob("*.parquet")):
        log.warning("No synthetic actuals found")
        return None

    synth_str = str(synth_dir).replace("\\", "/")
    parquet_str = str(cfg.parquet_dir).replace("\\", "/")
    dimentity_path = cfg.dimension_dir / "dimentity.csv"

    with read_connection() as con:
        posted_join = ""
        if dimentity_path.exists():
            dim_str = str(dimentity_path).replace("\\", "/")
            con.execute(f"""
                CREATE TEMP TABLE posted_entities AS
                SELECT code as entity_code
                FROM read_csv_auto('{dim_str}')
                WHERE has_posted = TRUE
            """)
            posted_join = "JOIN posted_entities pe ON all_obs.entity_code = pe.entity_code"

        W_REAL = cfg.real_actual_weight
        W_SYNTH = cfg.synthetic_weight

        sql = f"""
            WITH
            synth AS (
                SELECT {pc_sql} as park_code,
                    CAST(park_date AS DATE) as park_date, entity_code,
                    synthetic_actual as wait_minutes, {W_SYNTH} as weight
                FROM read_parquet('{synth_str}/*.parquet')
                WHERE synthetic_actual > 0
            ),
            real_actuals AS (
                SELECT {pc_sql} as park_code,
                    CAST(park_date AS DATE) as park_date, entity_code,
                    wait_time_minutes as wait_minutes, {W_REAL} as weight
                FROM read_parquet('{parquet_str}/*.parquet')
                WHERE wait_time_type = 'ACTUAL' AND wait_time_minutes > 0
            ),
            all_obs AS (
                SELECT * FROM synth UNION ALL SELECT * FROM real_actuals
            ),
            filtered AS (
                SELECT all_obs.* FROM all_obs {posted_join}
            ),
            entity_avg AS (
                SELECT park_code, park_date, entity_code,
                    ROUND(SUM(wait_minutes * weight) / SUM(weight), 1) as entity_avg
                FROM filtered
                GROUP BY park_code, park_date, entity_code
            )
            SELECT park_code, park_date,
                ROUND(AVG(entity_avg), 1) as wti,
                COUNT(DISTINCT entity_code) as n_entities,
                'historical' as source
            FROM entity_avg
            WHERE entity_avg IS NOT NULL
            GROUP BY park_code, park_date
            ORDER BY park_code, park_date
        """
        df = con.execute(sql).fetchdf()

    log.info(f"Historical WTI: {len(df):,} park-dates")
    return df


def _compute_forecast_wti(
    cfg: PipelineConfig, log: PipelineLogger, pc_sql: str, forecast_file
) -> pd.DataFrame | None:
    """Compute forecast WTI from predictions."""
    forecast_str = str(forecast_file).replace("\\", "/")
    oc_path = cfg.output_base / "operating_calendar" / "operating_calendar.parquet"
    dimentity_path = cfg.dimension_dir / "dimentity.csv"

    excluded_methods = "('fallback_ratio')" if cfg.exclude_fallback_ratio else "('')"
    pc_f = park_code_sql("f.entity_code")

    with read_connection() as con:
        posted_join = ""
        if dimentity_path.exists():
            dim_str = str(dimentity_path).replace("\\", "/")
            con.execute(f"""
                CREATE TEMP TABLE posted_entities AS
                SELECT code as entity_code
                FROM read_csv_auto('{dim_str}')
                WHERE has_posted = TRUE
            """)
            posted_join = "JOIN posted_entities pe ON f.entity_code = pe.entity_code"

        if oc_path.exists():
            oc_str = str(oc_path).replace("\\", "/")
            sql = f"""
                SELECT {pc_f} as park_code, f.park_date,
                    ROUND(AVG(f.predicted_actual), 1) as wti,
                    COUNT(DISTINCT f.entity_code) as n_entities,
                    'forecast' as source
                FROM read_parquet('{forecast_str}') f
                JOIN read_parquet('{oc_str}') oc
                    ON f.entity_code = oc.entity_code
                    AND CAST(f.park_date AS DATE) = CAST(oc.park_date AS DATE)
                {posted_join}
                WHERE f.predicted_actual > 0
                  AND oc.is_operating = TRUE
                  AND f.prediction_method NOT IN {excluded_methods}
                GROUP BY {pc_f}, f.park_date
                ORDER BY park_code, f.park_date
            """
        else:
            pc_bare = park_code_sql("entity_code")
            posted_join_bare = posted_join.replace("f.entity_code", "entity_code")
            sql = f"""
                SELECT {pc_bare} as park_code, park_date,
                    ROUND(AVG(predicted_actual), 1) as wti,
                    COUNT(DISTINCT entity_code) as n_entities,
                    'forecast' as source
                FROM read_parquet('{forecast_str}')
                {posted_join_bare}
                WHERE predicted_actual > 0
                  AND prediction_method NOT IN {excluded_methods}
                GROUP BY {pc_bare}, park_date
                ORDER BY park_code, park_date
            """

        df = con.execute(sql).fetchdf()

    log.info(f"Forecast WTI: {len(df):,} park-dates")
    return df


def _apply_adaptive_quantile_mapping(
    cfg: PipelineConfig,
    log: PipelineLogger,
    results: list[pd.DataFrame],
    stretch_factors: dict[str, float],
) -> list[pd.DataFrame]:
    """Quantile mapping with per-park adaptive stretch factors (Pillar 3)."""
    from scipy import stats

    historical = [df for df in results if df is not None and (df["source"] == "historical").any()]
    forecast_idx = [i for i, df in enumerate(results) if df is not None and (df["source"] == "forecast").any()]

    if not historical or not forecast_idx:
        log.info("Quantile mapping skipped — missing data")
        return results

    hist_combined = pd.concat(historical, ignore_index=True)
    hist_combined = hist_combined[hist_combined["source"] == "historical"]
    default_stretch = cfg.quantile_mapping_max_stretch
    parks_mapped = 0
    total_capped = 0

    for idx in forecast_idx:
        df = results[idx]
        forecast_mask = df["source"] == "forecast"

        for park_code in df.loc[forecast_mask, "park_code"].unique():
            park_hist = hist_combined[hist_combined["park_code"] == park_code]["wti"].values
            if len(park_hist) < 30:
                continue

            park_mask = forecast_mask & (df["park_code"] == park_code)
            forecast_vals = df.loc[park_mask, "wti"].values
            if len(forecast_vals) == 0:
                continue

            # Per-park stretch factor (v4 adaptive)
            max_stretch = stretch_factors.get(park_code, default_stretch)

            percentiles = stats.rankdata(forecast_vals, method="average") / len(forecast_vals)
            clamped = np.clip(percentiles * 100, 1.0, 99.0)
            mapped = np.percentile(park_hist, clamped)

            original = forecast_vals
            stretch = np.where(original > 0, mapped / original, 1.0)
            capped = np.where(
                np.abs(stretch) > max_stretch,
                original * np.sign(stretch) * max_stretch,
                mapped,
            )

            n_capped = int(np.sum(np.abs(stretch) > max_stretch))
            if n_capped > 0:
                log.info(f"  {park_code}: {n_capped} values capped at {max_stretch}x")
                total_capped += n_capped

            results[idx].loc[park_mask, "wti"] = np.round(capped, 1)
            parks_mapped += 1

    log.info(f"Adaptive quantile mapping: {parks_mapped} parks, {total_capped} values capped")
    return results
