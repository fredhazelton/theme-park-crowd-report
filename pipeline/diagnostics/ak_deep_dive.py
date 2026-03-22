#!/usr/bin/env python3
"""Park Deep Dive Diagnostic — Full raw data + filtering funnel analysis.

Barney's investigation into why park WTI predictions are systematically off.
Traces every entity through each pipeline filtering step to identify where
attractions get dropped, misclassified, or suppressed.

Usage:
    python3 pipeline/diagnostics/ak_deep_dive.py \
        --output-base /home/wilma/hazeydata/pipeline
    python3 pipeline/diagnostics/ak_deep_dive.py --park UH

Outputs:
    - Console report with all findings
    - diagnostics/{park}_deep_dive_report.json (machine-readable)
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
    parser = argparse.ArgumentParser(description="Park Deep Dive Diagnostic")
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

    # Structural break
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
            }

    # Synthetic vs real
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

    if "posted_time" in tdf.columns and "actual_time" in tdf.columns:
        posted = pd.to_numeric(tdf["posted_time"], errors="coerce")
        actual = pd.to_numeric(tdf["actual_time"], errors="coerce")
        valid = posted.notna() & actual.notna() & (posted > 0) & (actual > 0)
        if valid.sum() > 100:
            ratio = (actual[valid] / posted[valid]).mean()
            print(f"\n  Posted → Actual ratio: {ratio:.3f} (actual/posted)")
            print(f"  Mean posted: {posted[valid].mean():.1f}  Mean actual: {actual[valid].mean():.1f}")

    # =========================================================================
    # 4. RAW POSTED/ACTUAL WAIT TIMES (fact tables)
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 4: RAW POSTED/ACTUAL WAIT TIMES (fact tables)")
    print("=" * 70)

    parquet_dir = base / "fact_tables" / "parquet"
    parquet_str = str(parquet_dir).replace("\\", "/")

    try:
        raw_stats = con.execute(f"""
            SELECT wait_time_type,
                   COUNT(*) as n_rows,
                   AVG(wait_time_minutes) as avg_wait,
                   MEDIAN(wait_time_minutes) as median_wait,
                   MIN(CAST(park_date AS DATE)) as min_date,
                   MAX(CAST(park_date AS DATE)) as max_date,
                   COUNT(DISTINCT entity_code) as n_entities
            FROM read_parquet('{parquet_str}/*.parquet')
            WHERE entity_code LIKE '{park}%' AND wait_time_minutes > 0
            GROUP BY wait_time_type
        """).fetchdf()
        print("\n" + raw_stats.to_string(index=False))

        recent = con.execute(f"""
            SELECT wait_time_type,
                   COUNT(*) as n_rows, AVG(wait_time_minutes) as avg_wait,
                   MEDIAN(wait_time_minutes) as median_wait,
                   COUNT(DISTINCT entity_code) as n_entities
            FROM read_parquet('{parquet_str}/*.parquet')
            WHERE entity_code LIKE '{park}%' AND wait_time_minutes > 0
              AND CAST(park_date AS DATE) >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY wait_time_type
        """).fetchdf()
        print("\n--- Last 30 days ---")
        print(recent.to_string(index=False))
    except Exception as e:
        print(f"  Could not query fact tables: {e}")

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
                SELECT s.entity_code, COUNT(*) as n_matched,
                       ROUND(AVG(s.synth_wait), 1) as avg_synth,
                       ROUND(AVG(r.real_wait), 1) as avg_real,
                       ROUND(AVG(s.synth_wait - r.real_wait), 1) as bias,
                       ROUND(AVG(ABS(s.synth_wait - r.real_wait)), 1) as mae
                FROM synth s
                JOIN real r ON s.entity_code = r.entity_code
                    AND s.park_date = r.park_date AND s.hr = r.hr
                GROUP BY s.entity_code
                HAVING COUNT(*) >= 10
                ORDER BY bias DESC
            """).fetchdf()
            if len(synth_vs_real) > 0:
                print("\n--- Synthetic vs Real Bias per Entity ---")
                print(synth_vs_real.to_string(index=False))
                total_bias = float(synth_vs_real["bias"].mean())
                print(f"\nOverall {park} synthetic bias: {total_bias:+.1f} min")
        except Exception as e:
            print(f"  Synthetic analysis failed: {e}")
    else:
        print("  No synthetic actuals found.")

    # =========================================================================
    # 6. MODEL METADATA
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 6: MODEL METADATA")
    print("=" * 70)

    models_dir = base / "models"
    park_models = sorted(models_dir.glob(f"{park}*/metadata_v3.json")) if models_dir.exists() else []

    if park_models:
        model_summary = []
        for meta_path in park_models:
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

    # =========================================================================
    # 7. FORECAST OUTPUT
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 7: FORECAST OUTPUT")
    print("=" * 70)

    forecast_file = base / "curves" / "forecast_parquet" / "all_forecasts_v3.parquet"
    if forecast_file.exists():
        fstr = str(forecast_file).replace("\\", "/")
        try:
            forecast_summary = con.execute(f"""
                SELECT prediction_method,
                       COUNT(DISTINCT entity_code) as n_entities,
                       COUNT(*) as n_rows,
                       ROUND(AVG(predicted_actual), 1) as avg_predicted,
                       ROUND(MEDIAN(predicted_actual), 1) as median_predicted
                FROM read_parquet('{fstr}')
                WHERE entity_code LIKE '{park}%'
                GROUP BY prediction_method
            """).fetchdf()
            print("\n" + forecast_summary.to_string(index=False))

            entity_forecasts = con.execute(f"""
                SELECT entity_code, prediction_method,
                       COUNT(*) as n_predictions,
                       ROUND(AVG(predicted_actual), 1) as avg_predicted
                FROM read_parquet('{fstr}')
                WHERE entity_code LIKE '{park}%'
                  AND CAST(park_date AS DATE) BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
                GROUP BY entity_code, prediction_method
                ORDER BY avg_predicted DESC
            """).fetchdf()
            if len(entity_forecasts) > 0:
                print("\n--- Per-entity forecast (next 7 days) ---")
                print(entity_forecasts.to_string(index=False))
        except Exception as e:
            print(f"  Forecast analysis failed: {e}")

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
                SELECT COUNT(DISTINCT entity_code) as n_entities, COUNT(*) as n_rows,
                       SUM(CASE WHEN is_operating THEN 1 ELSE 0 END) as operating_rows,
                       MIN(CAST(park_date AS DATE)) as min_date,
                       MAX(CAST(park_date AS DATE)) as max_date
                FROM read_parquet('{oc_str}')
                WHERE entity_code LIKE '{park}%'
            """).fetchdf()
            print("\n" + oc_summary.to_string(index=False))

            oc_next30 = con.execute(f"""
                SELECT COUNT(DISTINCT entity_code) as n_entities,
                       COUNT(DISTINCT CAST(park_date AS DATE)) as n_dates,
                       SUM(CASE WHEN is_operating THEN 1 ELSE 0 END) as operating
                FROM read_parquet('{oc_str}')
                WHERE entity_code LIKE '{park}%'
                  AND CAST(park_date AS DATE) BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days'
            """).fetchdf()
            print("\n--- Next 30 days ---")
            print(oc_next30.to_string(index=False))
        except Exception as e:
            print(f"  OC analysis failed: {e}")

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
        actual = pd.to_numeric(tdf["actual_time"], errors="coerce")
        weights = tdf["geo_weight"]
        valid = actual.notna() & (actual > 0) & weights.notna()

        if valid.sum() > 0:
            unweighted_mean = float(actual[valid].mean())
            weighted_mean = float(np.average(actual[valid], weights=weights[valid]))
            print(f"  Unweighted mean actual: {unweighted_mean:.1f} min")
            print(f"  Geo-decay weighted mean (halflife=730d): {weighted_mean:.1f} min")
            print(f"  Difference: {weighted_mean - unweighted_mean:+.1f} min")

            for halflife in [365, 180, 90]:
                agg_w = 0.5 ** (tdf["days_old"][valid] / halflife)
                agg_mean = float(np.average(actual[valid], weights=agg_w))
                print(f"  Halflife={halflife}d: {agg_mean:.1f} min (delta: {agg_mean - weighted_mean:+.1f})")

    # =========================================================================
    # 10. ENTITY FILTERING FUNNEL — where do attractions get dropped?
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 10: ENTITY FILTERING FUNNEL")
    print("=" * 70)
    print("\nTraces each entity through every pipeline filtering step.\n")

    dim_str = str(base / "dimension_tables" / "dimentity.csv").replace("\\", "/")

    # Step A: All entities in dimension table for this park
    try:
        all_dim_entities = con.execute(f"""
            SELECT code, name, fastpass_booth, scope_and_scale, is_extinct
            FROM read_csv_auto('{dim_str}')
            WHERE code LIKE '{park}%'
        """).fetchdf()
        n_dim = len(all_dim_entities)
        n_extinct = int(all_dim_entities["is_extinct"].sum()) if "is_extinct" in all_dim_entities.columns else 0
        n_fastpass = int(all_dim_entities["fastpass_booth"].sum()) if "fastpass_booth" in all_dim_entities.columns else 0
        print(f"A. Dimension table: {n_dim} entities total")
        print(f"   - Extinct: {n_extinct}")
        print(f"   - FastPass booths (filtered out): {n_fastpass}")
        print(f"   - Active non-booth: {n_dim - n_extinct - n_fastpass}")
        report["sections"]["funnel_A_dimension"] = {
            "total": n_dim, "extinct": n_extinct, "fastpass_booth": n_fastpass,
            "active": n_dim - n_extinct - n_fastpass,
        }

        # Show extinct + fastpass entities
        if n_extinct > 0 and "is_extinct" in all_dim_entities.columns:
            extinct_list = all_dim_entities[all_dim_entities["is_extinct"] == True]["code"].tolist()
            print(f"   Extinct entities: {extinct_list[:20]}{'...' if len(extinct_list) > 20 else ''}")
        if n_fastpass > 0 and "fastpass_booth" in all_dim_entities.columns:
            fp_list = all_dim_entities[all_dim_entities["fastpass_booth"] == True]["code"].tolist()
            print(f"   FastPass booths: {fp_list[:20]}{'...' if len(fp_list) > 20 else ''}")
    except Exception as e:
        print(f"  Dimension table query failed: {e}")
        all_dim_entities = pd.DataFrame()

    # Step B: Entities with POSTED wait time data (s08 entity_list filter)
    try:
        posted_entities = con.execute(f"""
            SELECT DISTINCT f.entity_code
            FROM read_parquet('{parquet_str}/*.parquet') f
            INNER JOIN read_csv_auto('{dim_str}') d ON f.entity_code = d.code
            WHERE f.entity_code LIKE '{park}%'
              AND f.wait_time_type = 'POSTED'
              AND f.wait_time_minutes > 0
              AND d.fastpass_booth = FALSE
        """).fetchdf()
        n_posted = len(posted_entities)
        print(f"\nB. Has POSTED wait data + not booth: {n_posted} entities")
        report["sections"]["funnel_B_posted"] = {"count": n_posted}

        # Who's in dim but has NO posted data?
        if len(all_dim_entities) > 0:
            dim_codes = set(all_dim_entities[
                (all_dim_entities.get("fastpass_booth", False) == False) &
                (all_dim_entities.get("is_extinct", False) == False)
            ]["code"].tolist()) if "fastpass_booth" in all_dim_entities.columns else set(all_dim_entities["code"].tolist())
            posted_codes = set(posted_entities["entity_code"].tolist())
            no_posted = dim_codes - posted_codes
            if no_posted:
                print(f"   ⚠️ {len(no_posted)} active entities have NO posted wait data:")
                for code in sorted(no_posted)[:15]:
                    name_row = all_dim_entities[all_dim_entities["code"] == code]
                    name = name_row["name"].values[0] if len(name_row) > 0 and "name" in name_row.columns else "?"
                    print(f"     {code}: {name}")
                if len(no_posted) > 15:
                    print(f"     ... and {len(no_posted) - 15} more")
    except Exception as e:
        print(f"  Posted entity query failed: {e}")

    # Step C: Entities with trained models
    try:
        model_entities = set()
        if models_dir.exists():
            for p in models_dir.glob(f"{park}*/model_*.json"):
                model_entities.add(p.parent.name)
        n_models = len(model_entities)
        print(f"\nC. Has trained model: {n_models} entities")
        report["sections"]["funnel_C_models"] = {"count": n_models}

        # Who has posted data but NO model?
        if 'posted_codes' in dir():
            no_model = posted_codes - model_entities
            if no_model:
                print(f"   ⚠️ {len(no_model)} entities have posted data but NO model (use fallback_ratio):")
                for code in sorted(no_model)[:15]:
                    name_row = all_dim_entities[all_dim_entities["code"] == code] if len(all_dim_entities) > 0 else pd.DataFrame()
                    name = name_row["name"].values[0] if len(name_row) > 0 and "name" in name_row.columns else "?"
                    print(f"     {code}: {name}")
                if len(no_model) > 15:
                    print(f"     ... and {len(no_model) - 15} more")
    except Exception as e:
        print(f"  Model entity query failed: {e}")

    # Step D: Entities in operating calendar (next 7 days)
    if oc_file.exists():
        try:
            oc_str_d = str(oc_file).replace("\\", "/")
            oc_entities = con.execute(f"""
                SELECT DISTINCT UPPER(entity_code) as entity_code
                FROM read_parquet('{oc_str_d}')
                WHERE UPPER(entity_code) LIKE '{park}%'
                  AND is_operating = TRUE
                  AND CAST(park_date AS DATE) BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
            """).fetchdf()
            oc_codes = set(oc_entities["entity_code"].tolist())
            n_oc = len(oc_codes)
            print(f"\nD. Operating next 7 days (per OC): {n_oc} entities")
            report["sections"]["funnel_D_operating"] = {"count": n_oc}

            # Who has a model but is NOT in OC?
            model_upper = {e.upper() for e in model_entities}
            not_operating = model_upper - oc_codes
            if not_operating:
                print(f"   ⚠️ {len(not_operating)} entities have models but OC says NOT operating:")
                for code in sorted(not_operating)[:15]:
                    name_row = all_dim_entities[all_dim_entities["code"].str.upper() == code] if len(all_dim_entities) > 0 else pd.DataFrame()
                    name = name_row["name"].values[0] if len(name_row) > 0 and "name" in name_row.columns else "?"
                    print(f"     {code}: {name}")
                if len(not_operating) > 15:
                    print(f"     ... and {len(not_operating) - 15} more")

            # Who is operating but NOT in entity list at all?
            if 'posted_codes' in dir():
                posted_upper = {e.upper() for e in posted_codes}
                operating_no_data = oc_codes - posted_upper
                if operating_no_data:
                    print(f"   ⚠️ {len(operating_no_data)} entities marked operating but have NO posted data:")
                    for code in sorted(operating_no_data)[:10]:
                        print(f"     {code}")
        except Exception as e:
            print(f"  OC entity query failed: {e}")

    # Step E: Entities in actual forecast output
    if forecast_file.exists():
        try:
            forecast_entities = con.execute(f"""
                SELECT entity_code, prediction_method,
                       COUNT(*) as n_rows,
                       ROUND(AVG(predicted_actual), 1) as avg_pred
                FROM read_parquet('{fstr}')
                WHERE entity_code LIKE '{park}%'
                  AND CAST(park_date AS DATE) BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
                GROUP BY entity_code, prediction_method
                ORDER BY prediction_method, avg_pred DESC
            """).fetchdf()
            forecast_codes = set(forecast_entities["entity_code"].tolist())
            n_forecast = len(forecast_codes)
            print(f"\nE. In forecast output (next 7 days): {n_forecast} entities")
            report["sections"]["funnel_E_forecast"] = {"count": n_forecast}

            # Method breakdown
            method_summary = forecast_entities.groupby("prediction_method").agg(
                entities=("entity_code", "nunique"),
                avg_predicted=("avg_pred", "mean"),
            ).reset_index()
            method_summary["avg_predicted"] = method_summary["avg_predicted"].round(1)
            print(method_summary.to_string(index=False))

            # fallback_ratio entities (EXCLUDED from WTI)
            fallback_entities = forecast_entities[forecast_entities["prediction_method"] == "fallback_ratio"]
            model_entities_f = forecast_entities[forecast_entities["prediction_method"] != "fallback_ratio"]
            if len(fallback_entities) > 0:
                print(f"\n   ⚠️ {len(fallback_entities)} entities use fallback_ratio (EXCLUDED from WTI):")
                for _, row in fallback_entities.head(10).iterrows():
                    print(f"     {row['entity_code']}: avg {row['avg_pred']} min")
                fb_avg = fallback_entities["avg_pred"].mean()
                model_avg = model_entities_f["avg_pred"].mean() if len(model_entities_f) > 0 else 0
                print(f"\n   Fallback avg prediction: {fb_avg:.1f} min")
                print(f"   Model avg prediction: {model_avg:.1f} min")
                if fb_avg > model_avg * 1.5:
                    print(f"   🔴 Fallback entities predict {fb_avg/model_avg:.1f}x HIGHER than model entities!")
                    print(f"   These high-wait attractions are MISSING from WTI — this suppresses the index!")
        except Exception as e:
            print(f"  Forecast entity query failed: {e}")

    # Step F: Entities in WTI calculation
    wti_file = base / "wti" / "wti_forecast.parquet"
    if wti_file.exists():
        wti_str = str(wti_file).replace("\\", "/")
        try:
            # WTI doesn't have per-entity data, but we can check the aggregate
            wti_data = con.execute(f"""
                SELECT CAST(park_date AS DATE) as park_date, wti_forecast
                FROM read_parquet('{wti_str}')
                WHERE park_code = '{park}'
                  AND CAST(park_date AS DATE) BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
                ORDER BY park_date
            """).fetchdf()
            if len(wti_data) > 0:
                print(f"\nF. WTI output (next 7 days):")
                print(wti_data.to_string(index=False))
                avg_wti = wti_data["wti_forecast"].mean()
                print(f"   Average WTI: {avg_wti:.1f}")
        except Exception as e:
            print(f"  WTI query failed: {e}")

    # =========================================================================
    # FUNNEL SUMMARY
    # =========================================================================
    print("\n" + "=" * 70)
    print("FILTERING FUNNEL SUMMARY")
    print("=" * 70)
    print(f"""
    A. Dimension table:          {report['sections'].get('funnel_A_dimension', {}).get('total', '?')} entities
       └─ Extinct:               {report['sections'].get('funnel_A_dimension', {}).get('extinct', '?')}
       └─ FastPass booths:       {report['sections'].get('funnel_A_dimension', {}).get('fastpass_booth', '?')}
       └─ Active non-booth:      {report['sections'].get('funnel_A_dimension', {}).get('active', '?')}
    B. Has POSTED data:          {report['sections'].get('funnel_B_posted', {}).get('count', '?')} entities
    C. Has trained model:        {report['sections'].get('funnel_C_models', {}).get('count', '?')} entities
    D. Operating (next 7d):      {report['sections'].get('funnel_D_operating', {}).get('count', '?')} entities
    E. In forecast output:       {report['sections'].get('funnel_E_forecast', {}).get('count', '?')} entities
       └─ model_v3/actuals:      (see above for method breakdown)
       └─ fallback_ratio:        (EXCLUDED from WTI ← potential suppression)
    F. WTI index:                (park-level aggregate)

    🔍 Key question: Are high-wait attractions falling out at steps B-D
       and ending up as fallback_ratio (excluded from WTI)?
    """)

    # =========================================================================
    # 11. CLOSED ATTRACTION DETECTION ANALYSIS
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 11: CLOSED/TEMPORARILY CLOSED ATTRACTION ANALYSIS")
    print("=" * 70)

    # Check: entities with recent historical data but marked not-operating
    try:
        # Find entities with posted data in last 90 days
        recent_active = con.execute(f"""
            SELECT entity_code,
                   COUNT(*) as n_recent_posts,
                   MAX(CAST(park_date AS DATE)) as last_seen,
                   AVG(wait_time_minutes) as avg_wait
            FROM read_parquet('{parquet_str}/*.parquet')
            WHERE entity_code LIKE '{park}%'
              AND wait_time_type = 'POSTED'
              AND wait_time_minutes > 0
              AND CAST(park_date AS DATE) >= CURRENT_DATE - INTERVAL '90 days'
            GROUP BY entity_code
        """).fetchdf()
        print(f"\nEntities with posted data in last 90 days: {len(recent_active)}")

        if oc_file.exists():
            oc_next7 = con.execute(f"""
                SELECT DISTINCT UPPER(entity_code) as entity_code
                FROM read_parquet('{oc_str}')
                WHERE UPPER(entity_code) LIKE '{park}%'
                  AND is_operating = TRUE
                  AND CAST(park_date AS DATE) BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
            """).fetchdf()
            oc_next7_codes = set(oc_next7["entity_code"].tolist())

            # Recently active but OC says closed
            recent_codes = set(recent_active["entity_code"].str.upper().tolist())
            recently_closed = recent_codes - oc_next7_codes
            if recently_closed:
                print(f"\n   🔴 {len(recently_closed)} entities had recent data but OC says NOT operating next 7 days:")
                for code in sorted(recently_closed):
                    ra_row = recent_active[recent_active["entity_code"].str.upper() == code]
                    if len(ra_row) > 0:
                        last_seen = ra_row["last_seen"].values[0]
                        avg_w = ra_row["avg_wait"].values[0]
                        n_posts = ra_row["n_recent_posts"].values[0]
                        name_row = all_dim_entities[all_dim_entities["code"].str.upper() == code] if len(all_dim_entities) > 0 else pd.DataFrame()
                        name = name_row["name"].values[0] if len(name_row) > 0 and "name" in name_row.columns else "?"
                        print(f"     {code} ({name}): last seen {last_seen}, avg {avg_w:.0f} min, {n_posts} posts")
                print(f"\n   If these are genuinely open, OC is filtering them out → suppressing WTI")
            else:
                print(f"   ✅ All recently-active entities are marked operating")
    except Exception as e:
        print(f"  Closed attraction analysis failed: {e}")

    # Check: entities in OC marked operating but with zero recent data (ghost entities)
    try:
        if oc_file.exists() and 'oc_next7_codes' in dir():
            ghost_entities = oc_next7_codes - recent_codes if 'recent_codes' in dir() else set()
            if ghost_entities:
                print(f"\n   ⚠️ {len(ghost_entities)} entities marked operating but have NO data in last 90 days (ghost entities):")
                for code in sorted(ghost_entities)[:15]:
                    name_row = all_dim_entities[all_dim_entities["code"].str.upper() == code] if len(all_dim_entities) > 0 else pd.DataFrame()
                    name = name_row["name"].values[0] if len(name_row) > 0 and "name" in name_row.columns else "?"
                    print(f"     {code}: {name}")
                if len(ghost_entities) > 15:
                    print(f"     ... and {len(ghost_entities) - 15} more")
                print(f"   Ghost entities may have stale/low models → could suppress WTI")
    except Exception as e:
        print(f"  Ghost entity analysis failed: {e}")

    # Check: scraper status — is the scraper even collecting data for this park?
    try:
        scraper_recency = con.execute(f"""
            SELECT entity_code,
                   MAX(CAST(park_date AS DATE)) as last_date,
                   COUNT(*) FILTER (WHERE CAST(park_date AS DATE) = CURRENT_DATE) as today_count
            FROM read_parquet('{parquet_str}/*.parquet')
            WHERE entity_code LIKE '{park}%'
              AND wait_time_type = 'POSTED'
            GROUP BY entity_code
            ORDER BY last_date DESC
        """).fetchdf()
        if len(scraper_recency) > 0:
            today_active = scraper_recency[scraper_recency["today_count"] > 0]
            stale = scraper_recency[scraper_recency["today_count"] == 0]
            print(f"\n--- Scraper recency ---")
            print(f"   Entities with data today: {len(today_active)}")
            print(f"   Entities with NO data today: {len(stale)}")
            if len(stale) > 0:
                print(f"   Most recent stale entities:")
                for _, row in stale.head(10).iterrows():
                    print(f"     {row['entity_code']}: last data {row['last_date']}")
    except Exception as e:
        print(f"  Scraper recency check failed: {e}")

    # =========================================================================
    # 12. SUMMARY & RECOMMENDATIONS
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 12: SUMMARY")
    print("=" * 70)

    print(f"\n{park} diagnostic complete. Key investigation areas:")
    print(f"  1. Structural break: Check Section 1 — did the park fundamentally change?")
    print(f"  2. Synthetic poisoning: Check Section 5 — is synthetic data biased?")
    print(f"  3. Entity dropout: Check Section 10 funnel — are high-wait rides falling out?")
    print(f"  4. Closed attraction misclassification: Check Section 11 — is OC wrong?")
    print(f"  5. Fallback suppression: Check Section 10 Step E — are fallback entities")
    print(f"     high-wait rides excluded from WTI?")
    print(f"  6. Geo-decay: Check Section 9 — is the halflife too long for this park?")

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
