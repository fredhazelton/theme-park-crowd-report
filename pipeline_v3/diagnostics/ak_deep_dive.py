#!/usr/bin/env python3
"""AK Deep Dive Diagnostic — Full raw data analysis.

Barney's investigation into why AK WTI predictions are systematically low.
v3 predicts 8.7 vs actual 23.1 during Spring Break. v4 improved to 12.2
but still off. Need to understand ROOT CAUSE.

Runs against production data on the server.

Usage:
    python3 pipeline_v3/diagnostics/ak_deep_dive.py \
        --output-base /home/wilma/hazeydata/pipeline

Outputs:
    - Console report with all findings
    - diagnostics/ak_deep_dive_report.json (machine-readable)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import duckdb
except ImportError:
    print("ERROR: duckdb required. pip install duckdb")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="AK Deep Dive Diagnostic")
    parser.add_argument("--output-base", type=str, default="/home/wilma/hazeydata/pipeline")
    parser.add_argument("--park", type=str, default="AK", help="Park code to analyze (default: AK)")
    args = parser.parse_args()

    base = Path(args.output_base)
    park = args.park
    report = {"park": park, "generated_at": datetime.now().isoformat(), "sections": {}}

    print("=" * 70)
    print(f"DEEP DIVE DIAGNOSTIC: {park}")
    print("=" * 70)

    con = duckdb.connect(database=":memory:", read_only=False)

    # =========================================================================
    # 1. TRAINING DATA — Age, volume, distribution
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 1: TRAINING DATA PROFILE")
    print("=" * 70)

    training_dir = base / "matched_pairs" / "actuals_training_v2"
    training_file = training_dir / f"{park}.parquet"
    training_single = base / "matched_pairs" / "actuals_training_v2.parquet"

    if training_file.exists():
        src = str(training_file).replace("\\", "/")
        tdf = con.execute(f"SELECT * FROM read_parquet('{src}')").fetchdf()
    elif training_single.exists():
        src = str(training_single).replace("\\", "/")
        tdf = con.execute(f"SELECT * FROM read_parquet('{src}') WHERE entity_code LIKE '{park}%'").fetchdf()
    else:
        print(f"ERROR: No training data found for {park}")
        return

    print(f"\nTotal training rows: {len(tdf):,}")
    print(f"Columns: {list(tdf.columns)}")
    print(f"Entities: {tdf['entity_code'].nunique()}")
    print(f"Date range: {tdf['park_date'].min()} to {tdf['park_date'].max()}")

    # Age distribution
    tdf["park_date_dt"] = pd.to_datetime(tdf["park_date"])
    tdf["year"] = tdf["park_date_dt"].dt.year

    print("\n--- Training rows by year ---")
    year_dist = tdf.groupby("year").agg(
        rows=('entity_code', 'count'),
        entities=('entity_code', 'nunique'),
        avg_actual=('actual_time', lambda x: round(x.mean(), 1)),
        median_actual=('actual_time', lambda x: round(x.median(), 1)),
    ).reset_index()
    print(year_dist.to_string(index=False))
    report["sections"]["training_by_year"] = year_dist.to_dict(orient="records")

    # Is there a structural break?
    if "actual_time" in tdf.columns:
        pre_2018 = tdf[tdf["year"] < 2018]["actual_time"]
        post_2022 = tdf[tdf["year"] >= 2022]["actual_time"]
        if len(pre_2018) > 0 and len(post_2022) > 0:
            print(f"\n--- Structural break test ---")
            print(f"Pre-2018 mean actual: {pre_2018.mean():.1f} min (n={len(pre_2018):,})")
            print(f"Post-2022 mean actual: {post_2022.mean():.1f} min (n={len(post_2022):,})")
            print(f"Ratio: {post_2022.mean() / pre_2018.mean():.2f}x")
            report["sections"]["structural_break"] = {
                "pre_2018_mean": round(float(pre_2018.mean()), 2),
                "post_2022_mean": round(float(post_2022.mean()), 2),
                "ratio": round(float(post_2022.mean() / pre_2018.mean()), 2),
                "pre_2018_n": len(pre_2018),
                "post_2022_n": len(post_2022),
            }

    # Synthetic vs real breakdown
    if "is_synthetic" in tdf.columns:
        print("\n--- Synthetic vs Real ---")
        synth_counts = tdf.groupby("is_synthetic").agg(
            rows=('entity_code', 'count'),
            avg_actual=('actual_time', lambda x: round(x.mean(), 1)),
            median_actual=('actual_time', lambda x: round(x.median(), 1)),
        ).reset_index()
        synth_counts["is_synthetic"] = synth_counts["is_synthetic"].map({True: "synthetic", False: "real"})
        print(synth_counts.to_string(index=False))
        report["sections"]["synthetic_vs_real"] = synth_counts.to_dict(orient="records")

        # Synthetic by year
        print("\n--- Synthetic rows by year ---")
        synth_year = tdf[tdf["is_synthetic"] == True].groupby("year").size()
        real_year = tdf[tdf["is_synthetic"] == False].groupby("year").size()
        synth_ratio = pd.DataFrame({"synthetic": synth_year, "real": real_year}).fillna(0)
        synth_ratio["pct_synthetic"] = (synth_ratio["synthetic"] / (synth_ratio["synthetic"] + synth_ratio["real"]) * 100).round(1)
        print(synth_ratio.to_string())
        report["sections"]["synthetic_by_year"] = synth_ratio.reset_index().to_dict(orient="records")
    else:
        print("\nNo is_synthetic column — cannot distinguish synthetic from real.")

    # =========================================================================
    # 2. PER-ENTITY ANALYSIS
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 2: PER-ENTITY PROFILE")
    print("=" * 70)

    entity_stats = tdf.groupby("entity_code").agg(
        n_rows=('actual_time', 'count'),
        mean_actual=('actual_time', 'mean'),
        median_actual=('actual_time', 'median'),
        std_actual=('actual_time', 'std'),
        min_date=('park_date', 'min'),
        max_date=('park_date', 'max'),
    ).reset_index()
    entity_stats = entity_stats.sort_values("n_rows", ascending=False)
    entity_stats["mean_actual"] = entity_stats["mean_actual"].round(1)
    entity_stats["median_actual"] = entity_stats["median_actual"].round(1)
    entity_stats["std_actual"] = entity_stats["std_actual"].round(1)

    print(f"\n{park} entities ({len(entity_stats)} total):")
    print(entity_stats.head(20).to_string(index=False))
    report["sections"]["entity_stats"] = entity_stats.to_dict(orient="records")

    # =========================================================================
    # 3. FEATURE VALUE DISTRIBUTIONS
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 3: FEATURE VALUE DISTRIBUTIONS")
    print("=" * 70)

    feature_cols = [
        "mins_since_6am", "mins_since_open", "posted_time", "actual_time",
        "hour_of_day", "date_group_id_encoded", "season_encoded",
        "season_year_encoded",
    ]
    available_features = [c for c in feature_cols if c in tdf.columns]

    for feat in available_features:
        vals = pd.to_numeric(tdf[feat], errors="coerce").dropna()
        if len(vals) == 0:
            continue
        print(f"\n  {feat}:")
        print(f"    count: {len(vals):,}  mean: {vals.mean():.2f}  median: {vals.median():.2f}")
        print(f"    min: {vals.min():.2f}  max: {vals.max():.2f}  std: {vals.std():.2f}")
        print(f"    p5: {vals.quantile(0.05):.2f}  p25: {vals.quantile(0.25):.2f}  p75: {vals.quantile(0.75):.2f}  p95: {vals.quantile(0.95):.2f}")

    # Posted vs Actual relationship
    if "posted_time" in tdf.columns and "actual_time" in tdf.columns:
        posted = pd.to_numeric(tdf["posted_time"], errors="coerce")
        actual = pd.to_numeric(tdf["actual_time"], errors="coerce")
        valid = posted.notna() & actual.notna() & (posted > 0) & (actual > 0)
        if valid.sum() > 100:
            ratio = (actual[valid] / posted[valid]).mean()
            print(f"\n  Posted → Actual ratio: {ratio:.3f} (actual/posted)")
            print(f"  Mean posted: {posted[valid].mean():.1f}  Mean actual: {actual[valid].mean():.1f}")
            report["sections"]["posted_actual_ratio"] = round(float(ratio), 3)

    # =========================================================================
    # 4. POSTED WAIT TIME RAW DATA (from fact tables)
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 4: RAW POSTED/ACTUAL WAIT TIMES (fact tables)")
    print("=" * 70)

    parquet_dir = base / "fact_tables" / "parquet"
    parquet_str = str(parquet_dir).replace("\\", "/")

    try:
        raw_stats = con.execute(f"""
            SELECT
                wait_time_type,
                COUNT(*) as n_rows,
                AVG(wait_time_minutes) as avg_wait,
                MEDIAN(wait_time_minutes) as median_wait,
                MIN(CAST(park_date AS DATE)) as min_date,
                MAX(CAST(park_date AS DATE)) as max_date,
                COUNT(DISTINCT entity_code) as n_entities
            FROM read_parquet('{parquet_str}/*.parquet')
            WHERE entity_code LIKE '{park}%'
              AND wait_time_minutes > 0
            GROUP BY wait_time_type
        """).fetchdf()
        print("\n" + raw_stats.to_string(index=False))
        report["sections"]["raw_wait_types"] = raw_stats.to_dict(orient="records")
    except Exception as e:
        print(f"  Could not query fact tables: {e}")

    # Recent POSTED vs ACTUAL (last 30 days)
    try:
        recent = con.execute(f"""
            SELECT
                wait_time_type,
                COUNT(*) as n_rows,
                AVG(wait_time_minutes) as avg_wait,
                MEDIAN(wait_time_minutes) as median_wait,
                COUNT(DISTINCT entity_code) as n_entities
            FROM read_parquet('{parquet_str}/*.parquet')
            WHERE entity_code LIKE '{park}%'
              AND wait_time_minutes > 0
              AND CAST(park_date AS DATE) >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY wait_time_type
        """).fetchdf()
        print("\n--- Last 30 days ---")
        print(recent.to_string(index=False))
        report["sections"]["raw_last_30d"] = recent.to_dict(orient="records")
    except Exception as e:
        print(f"  Could not query recent data: {e}")

    # =========================================================================
    # 5. SYNTHETIC ACTUALS ANALYSIS
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 5: SYNTHETIC ACTUALS")
    print("=" * 70)

    synth_dir = base / "synthetic_actuals"
    synth_str = str(synth_dir).replace("\\", "/")

    if synth_dir.exists() and any(synth_dir.glob("*.parquet")):
        try:
            synth_stats = con.execute(f"""
                SELECT
                    COUNT(*) as n_rows,
                    AVG(synthetic_actual) as avg_synth,
                    MEDIAN(synthetic_actual) as median_synth,
                    MIN(CAST(park_date AS DATE)) as min_date,
                    MAX(CAST(park_date AS DATE)) as max_date,
                    COUNT(DISTINCT entity_code) as n_entities
                FROM read_parquet('{synth_str}/*.parquet')
                WHERE entity_code LIKE '{park}%'
                  AND synthetic_actual > 0
            """).fetchdf()
            print("\n" + synth_stats.to_string(index=False))
            report["sections"]["synthetic_overview"] = synth_stats.to_dict(orient="records")

            # Compare synthetic vs real actuals where both exist
            synth_vs_real = con.execute(f"""
                WITH synth AS (
                    SELECT entity_code, park_date,
                           EXTRACT(HOUR FROM CAST(observed_at AS TIMESTAMP)) as hr,
                           AVG(synthetic_actual) as synth_wait
                    FROM read_parquet('{synth_str}/*.parquet')
                    WHERE entity_code LIKE '{park}%' AND synthetic_actual > 0
                    GROUP BY entity_code, park_date, hr
                ),
                real AS (
                    SELECT entity_code, park_date,
                           EXTRACT(HOUR FROM observed_at_ts) as hr,
                           AVG(wait_time_minutes) as real_wait
                    FROM read_parquet('{parquet_str}/*.parquet')
                    WHERE entity_code LIKE '{park}%'
                      AND wait_time_type = 'ACTUAL' AND wait_time_minutes > 0
                    GROUP BY entity_code, park_date, hr
                )
                SELECT s.entity_code,
                       COUNT(*) as n_matched,
                       AVG(s.synth_wait) as avg_synth,
                       AVG(r.real_wait) as avg_real,
                       AVG(s.synth_wait - r.real_wait) as bias,
                       AVG(ABS(s.synth_wait - r.real_wait)) as mae
                FROM synth s
                JOIN real r ON s.entity_code = r.entity_code
                    AND s.park_date = r.park_date AND s.hr = r.hr
                GROUP BY s.entity_code
                HAVING COUNT(*) >= 10
                ORDER BY bias DESC
            """).fetchdf()

            if len(synth_vs_real) > 0:
                print("\n--- Synthetic vs Real Bias per Entity ---")
                synth_vs_real["avg_synth"] = synth_vs_real["avg_synth"].round(1)
                synth_vs_real["avg_real"] = synth_vs_real["avg_real"].round(1)
                synth_vs_real["bias"] = synth_vs_real["bias"].round(1)
                synth_vs_real["mae"] = synth_vs_real["mae"].round(1)
                print(synth_vs_real.to_string(index=False))
                report["sections"]["synthetic_bias"] = synth_vs_real.to_dict(orient="records")

                total_bias = float(synth_vs_real["bias"].mean())
                print(f"\nOverall {park} synthetic bias: {total_bias:+.1f} min")
                if total_bias > 3:
                    print(f"  ⚠️ Synthetic data OVER-estimates {park} by {total_bias:.1f} min")
                elif total_bias < -3:
                    print(f"  ⚠️ Synthetic data UNDER-estimates {park} by {abs(total_bias):.1f} min")
                else:
                    print(f"  ✅ Synthetic bias within ±3 min")
        except Exception as e:
            print(f"  Synthetic analysis failed: {e}")
    else:
        print("  No synthetic actuals directory found.")

    # =========================================================================
    # 6. MODEL METADATA (what did v4 select?)
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 6: MODEL METADATA")
    print("=" * 70)

    models_dir = base / "models"
    ak_models = sorted(models_dir.glob(f"{park}*/metadata_v3.json")) if models_dir.exists() else []

    if ak_models:
        model_summary = []
        for meta_path in ak_models:
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                model_summary.append({
                    "entity": meta.get("entity_code", meta_path.parent.name),
                    "method": meta.get("model_selection_method", "unknown"),
                    "mae": meta.get("mae", -1),
                    "n_samples": meta.get("n_samples", 0),
                    "features": len(meta.get("features", [])),
                })
            except Exception:
                pass

        if model_summary:
            mdf = pd.DataFrame(model_summary).sort_values("mae", ascending=False)
            print(f"\n{park} models ({len(mdf)} total):")
            print(mdf.to_string(index=False))
            report["sections"]["model_metadata"] = model_summary

            method_dist = mdf["method"].value_counts()
            print(f"\nModel selection: {dict(method_dist)}")
            avg_mae = mdf["mae"].mean()
            print(f"Average holdout MAE: {avg_mae:.2f} min")
    else:
        # Check for older model formats
        ak_any = sorted(models_dir.glob(f"{park}*/model_*.json")) if models_dir.exists() else []
        print(f"  No v4 metadata found. Older model files: {len(ak_any)}")

    # =========================================================================
    # 7. FORECAST OUTPUT (what did the pipeline produce?)
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 7: FORECAST OUTPUT")
    print("=" * 70)

    forecast_file = base / "curves" / "forecast_parquet" / "all_forecasts_v3.parquet"
    if forecast_file.exists():
        fstr = str(forecast_file).replace("\\", "/")
        try:
            forecast_summary = con.execute(f"""
                SELECT
                    prediction_method,
                    COUNT(DISTINCT entity_code) as n_entities,
                    COUNT(*) as n_rows,
                    AVG(predicted_actual) as avg_predicted,
                    MEDIAN(predicted_actual) as median_predicted
                FROM read_parquet('{fstr}')
                WHERE entity_code LIKE '{park}%'
                GROUP BY prediction_method
            """).fetchdf()
            print("\n" + forecast_summary.to_string(index=False))
            report["sections"]["forecast_methods"] = forecast_summary.to_dict(orient="records")

            # Per-entity forecast averages (next 7 days)
            entity_forecasts = con.execute(f"""
                SELECT
                    entity_code,
                    prediction_method,
                    COUNT(*) as n_predictions,
                    AVG(predicted_actual) as avg_predicted,
                    MEDIAN(predicted_actual) as median_predicted
                FROM read_parquet('{fstr}')
                WHERE entity_code LIKE '{park}%'
                  AND CAST(park_date AS DATE) BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
                GROUP BY entity_code, prediction_method
                ORDER BY avg_predicted DESC
            """).fetchdf()
            if len(entity_forecasts) > 0:
                print("\n--- Per-entity forecast (next 7 days) ---")
                entity_forecasts["avg_predicted"] = entity_forecasts["avg_predicted"].round(1)
                entity_forecasts["median_predicted"] = entity_forecasts["median_predicted"].round(1)
                print(entity_forecasts.to_string(index=False))
                report["sections"]["entity_forecasts_7d"] = entity_forecasts.to_dict(orient="records")
        except Exception as e:
            print(f"  Forecast analysis failed: {e}")
    else:
        print(f"  No forecast file at {forecast_file}")

    # =========================================================================
    # 8. OPERATING CALENDAR
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 8: OPERATING CALENDAR")
    print("=" * 70)

    oc_file = base / "operating_calendar" / "operating_calendar.parquet"
    if oc_file.exists():
        oc_str = str(oc_file).replace("\\", "/")
        try:
            oc_summary = con.execute(f"""
                SELECT
                    COUNT(DISTINCT entity_code) as n_entities,
                    COUNT(*) as n_rows,
                    SUM(CASE WHEN is_operating THEN 1 ELSE 0 END) as operating_rows,
                    MIN(CAST(park_date AS DATE)) as min_date,
                    MAX(CAST(park_date AS DATE)) as max_date
                FROM read_parquet('{oc_str}')
                WHERE entity_code LIKE '{park}%'
            """).fetchdf()
            print("\n" + oc_summary.to_string(index=False))

            # Next 30 days operating
            oc_next30 = con.execute(f"""
                SELECT
                    COUNT(DISTINCT entity_code) as n_entities,
                    COUNT(DISTINCT CAST(park_date AS DATE)) as n_dates,
                    SUM(CASE WHEN is_operating THEN 1 ELSE 0 END) as operating
                FROM read_parquet('{oc_str}')
                WHERE entity_code LIKE '{park}%'
                  AND CAST(park_date AS DATE) BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days'
            """).fetchdf()
            print("\n--- Next 30 days ---")
            print(oc_next30.to_string(index=False))
            report["sections"]["operating_calendar"] = {
                "overview": oc_summary.to_dict(orient="records"),
                "next_30d": oc_next30.to_dict(orient="records"),
            }
        except Exception as e:
            print(f"  OC analysis failed: {e}")
    else:
        print("  No operating calendar found.")

    # =========================================================================
    # 9. GEO-DECAY WEIGHT ANALYSIS
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 9: GEO-DECAY WEIGHT IMPACT")
    print("=" * 70)

    if "park_date_dt" in tdf.columns and "actual_time" in tdf.columns:
        today = pd.Timestamp.today()
        tdf["days_old"] = (today - tdf["park_date_dt"]).dt.days
        tdf["geo_weight"] = 0.5 ** (tdf["days_old"] / 730)

        # Weighted vs unweighted mean
        actual = pd.to_numeric(tdf["actual_time"], errors="coerce")
        weights = tdf["geo_weight"]
        valid = actual.notna() & (actual > 0) & weights.notna()

        if valid.sum() > 0:
            unweighted_mean = float(actual[valid].mean())
            weighted_mean = float(np.average(actual[valid], weights=weights[valid]))
            print(f"  Unweighted mean actual: {unweighted_mean:.1f} min")
            print(f"  Geo-decay weighted mean (halflife=730d): {weighted_mean:.1f} min")
            print(f"  Difference: {weighted_mean - unweighted_mean:+.1f} min")

            if weighted_mean > unweighted_mean:
                print(f"  → Recent data has HIGHER waits than historical (park getting busier)")
            else:
                print(f"  → Recent data has LOWER waits than historical")

            # What about more aggressive decay?
            for halflife in [365, 180, 90]:
                aggressive_weights = 0.5 ** (tdf["days_old"][valid] / halflife)
                agg_mean = float(np.average(actual[valid], weights=aggressive_weights))
                print(f"  Halflife={halflife}d weighted mean: {agg_mean:.1f} min (delta from 730d: {agg_mean - weighted_mean:+.1f})")

            report["sections"]["geo_decay"] = {
                "unweighted_mean": round(unweighted_mean, 2),
                "weighted_730d": round(weighted_mean, 2),
                "diff": round(weighted_mean - unweighted_mean, 2),
            }

    # =========================================================================
    # 10. SUMMARY & RECOMMENDATIONS
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 10: SUMMARY")
    print("=" * 70)

    print(f"\n{park} diagnostic complete. Key findings above.")
    print(f"Review each section for root cause clues.")
    print(f"Common causes of underprediction:")
    print(f"  - Old training data dominating (check Section 1 year distribution)")
    print(f"  - Synthetic data pulling down actuals (check Section 5 bias)")
    print(f"  - Fallback entities excluded from WTI (check Section 7 methods)")
    print(f"  - Operating calendar gaps (check Section 8)")
    print(f"  - Geo-decay not aggressive enough (check Section 9)")

    # Save report
    diag_dir = base / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)
    report_path = diag_dir / f"{park.lower()}_deep_dive_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport saved to {report_path}")

    con.close()


if __name__ == "__main__":
    main()
