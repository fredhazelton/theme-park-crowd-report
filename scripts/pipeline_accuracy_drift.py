#!/usr/bin/env python3
"""
Pipeline Accuracy Drift Check (Phase 4)

Run daily. Detects accuracy degradation — MAE jumps, bias trending,
new fallbacks appearing, entity-level outliers.

Checks:
  1. MAE jump vs 7-day moving average (park level)
  2. New fallback entities that previously had trained models
  3. Bias trending in one direction for a park
  4. Entity-level outliers (MAE > 2x park average)

Usage:
    python scripts/pipeline_accuracy_drift.py [--json] [--discord] [--quiet]

Exit codes:
    0 = ok
    1 = warning
    2 = critical
    3 = script error
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

import duckdb
import numpy as np

# ── Configuration ─────────────────────────────────────────────────────
PIPELINE_BASE = Path("/mnt/data/pipeline")
LIVE_DB = PIPELINE_BASE / "tpcr_live.duckdb"
ACCURACY_DIR = PIPELINE_BASE / "accuracy"
MODELS_DIR = PIPELINE_BASE / "models"

# Thresholds
MAE_JUMP_WARN = 0.25       # Warn if MAE jumps >25% vs 7-day avg
MAE_JUMP_CRIT = 0.50       # Critical if MAE jumps >50%
BIAS_TREND_WARN = 3.0      # Warn if bias magnitude > 3 minutes consistently
BIAS_TREND_DAYS = 5        # Number of consecutive days to consider a trend
OUTLIER_FACTOR = 2.0       # Entity MAE > 2x park average = outlier
OUTLIER_MIN_SLOTS = 10     # Only flag outliers with enough data

PARK_NAMES = {
    "AK": "Animal Kingdom",
    "CA": "DCA",
    "DL": "Disneyland",
    "EP": "EPCOT",
    "EU": "Epic Universe",
    "HS": "Hollywood Studios",
    "IA": "Islands of Adv.",
    "MK": "Magic Kingdom",
    "TDL": "Tokyo Disneyland",
    "TDS": "Tokyo DisneySea",
    "UF": "Universal Florida",
    "UH": "Universal Hollywood",
}


def load_accuracy_data(con: duckdb.DuckDBPyConnection) -> dict:
    """Load accuracy data from parquet files."""
    result = {"entity_daily": None, "slot": None, "wti": None}

    entity_path = ACCURACY_DIR / "entity_daily_accuracy.parquet"
    if entity_path.exists():
        try:
            result["entity_daily"] = con.execute(f"""
                SELECT * FROM read_parquet('{entity_path}')
            """).fetchdf()
        except Exception:
            pass

    wti_path = ACCURACY_DIR / "wti_accuracy.parquet"
    if wti_path.exists():
        try:
            result["wti"] = con.execute(f"""
                SELECT * FROM read_parquet('{wti_path}')
            """).fetchdf()
        except Exception:
            pass

    return result


def extract_park_code(entity_code: str) -> str:
    """Extract park code from entity code (e.g., AK01 -> AK)."""
    import re
    match = re.match(r"^([A-Z]+)", entity_code)
    return match.group(1) if match else ""


def check_mae_drift(data: dict) -> dict:
    """Check for MAE jumps vs 7-day moving average per park."""
    issues = []
    stats = {}

    df = data.get("entity_daily")
    if df is None or df.empty:
        stats["mae_check"] = "no data"
        return {"issues": issues, "stats": stats}

    # Add park_code
    df = df.copy()
    df["park_code"] = df["entity_code"].apply(extract_park_code)
    df["park_date_dt"] = df["park_date"].astype(str).str[:10]

    # Compute park-level MAE per date
    park_daily = df.groupby(["park_code", "park_date_dt"]).agg(
        mae=("mae", "mean"),
        entity_count=("entity_code", "nunique"),
        total_slots=("n_slots", "sum"),
    ).reset_index().sort_values(["park_code", "park_date_dt"])

    stats["park_daily_summary"] = {}
    drift_alerts = []

    for park_code, park_df in park_daily.groupby("park_code"):
        park_df = park_df.sort_values("park_date_dt")

        if len(park_df) < 3:
            continue

        # 7-day rolling average
        park_df["mae_7d_avg"] = park_df["mae"].rolling(7, min_periods=3).mean()

        latest = park_df.iloc[-1]
        latest_mae = latest["mae"]
        latest_7d = latest["mae_7d_avg"]

        park_stats = {
            "latest_date": latest["park_date_dt"],
            "latest_mae": round(float(latest_mae), 2),
            "mae_7d_avg": round(float(latest_7d), 2) if not np.isnan(latest_7d) else None,
            "entity_count": int(latest["entity_count"]),
        }

        if latest_7d and latest_7d > 0 and not np.isnan(latest_7d):
            jump_pct = (latest_mae - latest_7d) / latest_7d
            park_stats["mae_jump_pct"] = round(float(jump_pct), 4)

            if jump_pct > MAE_JUMP_CRIT:
                drift_alerts.append({
                    "park": park_code,
                    "park_name": PARK_NAMES.get(park_code, park_code),
                    "severity": "critical",
                    "mae_today": round(float(latest_mae), 2),
                    "mae_7d_avg": round(float(latest_7d), 2),
                    "jump_pct": round(float(jump_pct), 4),
                })
            elif jump_pct > MAE_JUMP_WARN:
                drift_alerts.append({
                    "park": park_code,
                    "park_name": PARK_NAMES.get(park_code, park_code),
                    "severity": "warning",
                    "mae_today": round(float(latest_mae), 2),
                    "mae_7d_avg": round(float(latest_7d), 2),
                    "jump_pct": round(float(jump_pct), 4),
                })

        stats["park_daily_summary"][park_code] = park_stats

    if drift_alerts:
        stats["drift_alerts"] = drift_alerts
        critical_parks = [a for a in drift_alerts if a["severity"] == "critical"]
        warning_parks = [a for a in drift_alerts if a["severity"] == "warning"]

        if critical_parks:
            names = ", ".join(a["park_name"] for a in critical_parks)
            issues.append({
                "type": "MAE_SPIKE_CRITICAL",
                "severity": "critical",
                "message": f"MAE spiked >50% in: {names}",
                "detail": "; ".join(f"{a['park']}: {a['mae_today']} vs 7d avg {a['mae_7d_avg']} (+{a['jump_pct']:.0%})" for a in critical_parks),
            })
        if warning_parks:
            names = ", ".join(a["park_name"] for a in warning_parks)
            issues.append({
                "type": "MAE_SPIKE_WARN",
                "severity": "warning",
                "message": f"MAE elevated in: {names}",
                "detail": "; ".join(f"{a['park']}: {a['mae_today']} vs 7d avg {a['mae_7d_avg']} (+{a['jump_pct']:.0%})" for a in warning_parks),
            })

    return {"issues": issues, "stats": stats}


def check_fallback_regression(data: dict) -> dict:
    """Check for entities that lost their trained models."""
    issues = []
    stats = {}

    df = data.get("entity_daily")
    if df is None or df.empty:
        return {"issues": issues, "stats": stats}

    df = df.copy()
    df["park_date_dt"] = df["park_date"].astype(str).str[:10]

    # Get entities on fallback in latest evaluation
    latest_date = df["park_date_dt"].max()
    latest = df[df["park_date_dt"] == latest_date]

    fallback_methods = {"fallback_ratio", "aggregate"}
    trained_methods = {"model_actuals", "model_v2", "model_scope_scale", "model_lite"}

    # Current fallback entities
    current_fallback = set()
    if "prediction_method" in latest.columns:
        fb = latest[latest["prediction_method"].isin(fallback_methods)]
        current_fallback = set(fb["entity_code"].tolist())

    # Check which of these had trained models in earlier evaluations
    earlier = df[df["park_date_dt"] < latest_date]
    if "prediction_method" in earlier.columns and not earlier.empty:
        previously_trained = set(
            earlier[earlier["prediction_method"].isin(trained_methods)]["entity_code"].tolist()
        )
        newly_fallback = current_fallback & previously_trained

        if newly_fallback:
            stats["newly_fallback_entities"] = sorted(newly_fallback)
            stats["newly_fallback_count"] = len(newly_fallback)

            severity = "critical" if len(newly_fallback) > 5 else "warning"
            issues.append({
                "type": "NEW_FALLBACK_ENTITIES",
                "severity": severity,
                "message": f"{len(newly_fallback)} entities regressed to fallback (previously had trained models)",
                "detail": f"Entities: {', '.join(sorted(newly_fallback)[:10])}{'...' if len(newly_fallback) > 10 else ''}",
            })

    stats["current_fallback_count"] = len(current_fallback)
    stats["latest_eval_date"] = latest_date

    return {"issues": issues, "stats": stats}


def check_bias_trend(data: dict) -> dict:
    """Check for persistent bias trending in one direction per park."""
    issues = []
    stats = {}

    df = data.get("entity_daily")
    if df is None or df.empty:
        return {"issues": issues, "stats": stats}

    df = df.copy()
    df["park_code"] = df["entity_code"].apply(extract_park_code)
    df["park_date_dt"] = df["park_date"].astype(str).str[:10]

    # Park-level bias per date
    park_bias = df.groupby(["park_code", "park_date_dt"]).agg(
        avg_bias=("bias", "mean"),
    ).reset_index().sort_values(["park_code", "park_date_dt"])

    bias_alerts = []
    stats["park_bias"] = {}

    for park_code, park_df in park_bias.groupby("park_code"):
        park_df = park_df.sort_values("park_date_dt")

        if len(park_df) < BIAS_TREND_DAYS:
            continue

        recent = park_df.tail(BIAS_TREND_DAYS)
        avg_bias = recent["avg_bias"].mean()
        all_positive = (recent["avg_bias"] > 0).all()
        all_negative = (recent["avg_bias"] < 0).all()

        stats["park_bias"][park_code] = {
            "recent_avg_bias": round(float(avg_bias), 2),
            "trending": "positive" if all_positive else ("negative" if all_negative else "mixed"),
            "last_n_days": BIAS_TREND_DAYS,
        }

        if (all_positive or all_negative) and abs(avg_bias) > BIAS_TREND_WARN:
            direction = "over-predicting" if avg_bias > 0 else "under-predicting"
            bias_alerts.append({
                "park": park_code,
                "park_name": PARK_NAMES.get(park_code, park_code),
                "direction": direction,
                "avg_bias": round(float(avg_bias), 2),
            })

    if bias_alerts:
        stats["bias_alerts"] = bias_alerts
        for alert in bias_alerts:
            issues.append({
                "type": "BIAS_TREND",
                "severity": "warning",
                "message": f"{alert['park_name']} consistently {alert['direction']} (bias: {alert['avg_bias']:+.1f} min over {BIAS_TREND_DAYS} days)",
                "detail": f"Park {alert['park']}: average bias of {alert['avg_bias']:+.1f} for last {BIAS_TREND_DAYS} evaluated days",
            })

    return {"issues": issues, "stats": stats}


def check_entity_outliers(data: dict) -> dict:
    """Check for entity-level outliers with MAE > 2x park average."""
    issues = []
    stats = {}

    df = data.get("entity_daily")
    if df is None or df.empty:
        return {"issues": issues, "stats": stats}

    df = df.copy()
    df["park_code"] = df["entity_code"].apply(extract_park_code)
    df["park_date_dt"] = df["park_date"].astype(str).str[:10]

    # Use latest evaluation date only
    latest_date = df["park_date_dt"].max()
    latest = df[df["park_date_dt"] == latest_date].copy()

    if latest.empty:
        return {"issues": issues, "stats": stats}

    # Filter entities with enough data
    latest = latest[latest["n_slots"] >= OUTLIER_MIN_SLOTS]

    outliers = []
    for park_code, park_df in latest.groupby("park_code"):
        if len(park_df) < 3:
            continue

        park_avg_mae = park_df["mae"].mean()
        threshold = park_avg_mae * OUTLIER_FACTOR

        bad = park_df[park_df["mae"] > threshold]
        for _, row in bad.iterrows():
            outliers.append({
                "entity_code": row["entity_code"],
                "park_code": park_code,
                "mae": round(float(row["mae"]), 2),
                "park_avg_mae": round(float(park_avg_mae), 2),
                "ratio": round(float(row["mae"] / park_avg_mae), 2),
                "n_slots": int(row["n_slots"]),
                "prediction_method": row.get("prediction_method", "unknown"),
            })

    if outliers:
        # Sort by ratio (worst first)
        outliers.sort(key=lambda x: x["ratio"], reverse=True)
        stats["outliers"] = outliers[:20]  # Top 20
        stats["outlier_count"] = len(outliers)

        severity = "warning" if len(outliers) < 10 else "critical"
        issues.append({
            "type": "ENTITY_OUTLIERS",
            "severity": severity,
            "message": f"{len(outliers)} entities have MAE >{OUTLIER_FACTOR}x their park average",
            "detail": "; ".join(f"{o['entity_code']}: MAE={o['mae']} ({o['ratio']}x park avg)" for o in outliers[:5]),
        })

    return {"issues": issues, "stats": stats}


def check_wti_accuracy_drift(data: dict) -> dict:
    """Check WTI accuracy trends."""
    issues = []
    stats = {}

    wti_df = data.get("wti")
    if wti_df is None or wti_df.empty:
        stats["wti_accuracy"] = "no data"
        return {"issues": issues, "stats": stats}

    wti_df = wti_df.copy()
    wti_df["park_date_str"] = wti_df["park_date"].astype(str).str[:10]

    # Overall WTI MAE
    stats["wti_overall_mae"] = round(float(wti_df["wti_abs_error"].mean()), 2)
    stats["wti_overall_bias"] = round(float(wti_df["wti_error"].mean()), 2)
    stats["wti_eval_count"] = len(wti_df)

    # Per-park WTI accuracy
    park_wti = wti_df.groupby("park_code").agg(
        mae=("wti_abs_error", "mean"),
        bias=("wti_error", "mean"),
        count=("park_date", "count"),
    ).reset_index()

    stats["wti_by_park"] = park_wti.to_dict("records")

    # Flag parks with high WTI error
    high_wti = park_wti[park_wti["mae"] > 15]
    if not high_wti.empty:
        parks = ", ".join(f"{r['park_code']} (MAE={r['mae']:.1f})" for _, r in high_wti.iterrows())
        issues.append({
            "type": "HIGH_WTI_ERROR",
            "severity": "warning",
            "message": f"High WTI error for: {parks}",
            "detail": "WTI MAE > 15 min indicates significant prediction inaccuracy at the park level",
        })

    return {"issues": issues, "stats": stats}


def run_drift_check() -> dict:
    """Run all accuracy drift checks."""
    con = duckdb.connect()  # In-memory for parquet reads
    data = load_accuracy_data(con)

    all_issues = []
    all_stats = {}

    # Check 1: MAE drift
    md = check_mae_drift(data)
    all_issues.extend(md["issues"])
    all_stats["mae_drift"] = md["stats"]

    # Check 2: Fallback regression
    fr = check_fallback_regression(data)
    all_issues.extend(fr["issues"])
    all_stats["fallback"] = fr["stats"]

    # Check 3: Bias trend
    bt = check_bias_trend(data)
    all_issues.extend(bt["issues"])
    all_stats["bias"] = bt["stats"]

    # Check 4: Entity outliers
    eo = check_entity_outliers(data)
    all_issues.extend(eo["issues"])
    all_stats["outliers"] = eo["stats"]

    # Check 5: WTI accuracy
    wti = check_wti_accuracy_drift(data)
    all_issues.extend(wti["issues"])
    all_stats["wti_accuracy"] = wti["stats"]

    con.close()

    # Determine overall status
    severities = [i["severity"] for i in all_issues]
    if "critical" in severities:
        status = "critical"
    elif "warning" in severities:
        status = "warning"
    else:
        status = "ok"

    return {
        "check": "pipeline_accuracy_drift",
        "status": status,
        "check_time": datetime.now(timezone.utc).isoformat(),
        "issue_count": len(all_issues),
        "issues": all_issues,
        "stats": all_stats,
    }


def format_discord_alert(result: dict) -> str:
    """Format as Discord message."""
    status = result["status"]
    emoji = {"ok": "✅", "warning": "⚠️", "critical": "🚨"}[status]
    lines = [f"{emoji} **Pipeline Accuracy Drift** [{status.upper()}]"]

    stats = result.get("stats", {})

    # MAE drift summary
    mae_stats = stats.get("mae_drift", {})
    park_summary = mae_stats.get("park_daily_summary", {})
    if park_summary:
        top_parks = sorted(park_summary.items(), key=lambda x: x[1].get("latest_mae", 0), reverse=True)[:5]
        lines.append("**Park MAE (latest):**")
        for pk, ps in top_parks:
            name = PARK_NAMES.get(pk, pk)
            jump = ps.get("mae_jump_pct")
            jump_str = f" ({jump:+.0%})" if jump and jump != 0 else ""
            lines.append(f"  {name}: {ps.get('latest_mae', '?')}{jump_str}")

    # Drift alerts
    drift = mae_stats.get("drift_alerts", [])
    for d in drift:
        sev = "🔴" if d["severity"] == "critical" else "🟡"
        lines.append(f"{sev} {d['park_name']}: MAE {d['mae_today']} vs 7d avg {d['mae_7d_avg']} ({d['jump_pct']:+.0%})")

    # Fallback
    fb = stats.get("fallback", {})
    if fb.get("newly_fallback_count"):
        lines.append(f"🟡 {fb['newly_fallback_count']} entities regressed to fallback")

    # Outliers
    outlier_stats = stats.get("outliers", {})
    if outlier_stats.get("outlier_count"):
        lines.append(f"🟡 {outlier_stats['outlier_count']} entity outliers (>{OUTLIER_FACTOR}x park MAE)")

    # WTI
    wti = stats.get("wti_accuracy", {})
    if isinstance(wti, dict) and "wti_overall_mae" in wti:
        lines.append(f"WTI overall MAE: {wti['wti_overall_mae']} | Bias: {wti['wti_overall_bias']:+.1f}")

    for issue in result["issues"]:
        if issue["type"] not in ("MAE_SPIKE_CRITICAL", "MAE_SPIKE_WARN"):  # already shown above
            sev = "🔴" if issue["severity"] == "critical" else "🟡"
            lines.append(f"{sev} {issue['message']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Pipeline accuracy drift check")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--discord", action="store_true", help="Output Discord-formatted message")
    parser.add_argument("--quiet", action="store_true", help="Only output if issues found")
    args = parser.parse_args()

    try:
        result = run_drift_check()
    except Exception as e:
        error_result = {
            "check": "pipeline_accuracy_drift",
            "status": "critical",
            "check_time": datetime.now(timezone.utc).isoformat(),
            "issues": [{
                "type": "CHECK_ERROR",
                "severity": "critical",
                "message": f"Drift check failed: {e}",
                "detail": str(e),
            }]
        }
        if args.json:
            print(json.dumps(error_result, indent=2))
        else:
            print(f"🚨 Drift check error: {e}")
        sys.exit(3)

    if args.quiet and result["status"] == "ok":
        sys.exit(0)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    elif args.discord:
        print(format_discord_alert(result))
    else:
        emoji = {"ok": "✅", "warning": "⚠️", "critical": "🚨"}
        print(f"\n{emoji.get(result['status'], '?')} Accuracy Drift: {result['status'].upper()}")
        print(f"   Issues: {result['issue_count']}")

        stats = result.get("stats", {})

        # Park MAE summary
        mae_stats = stats.get("mae_drift", {})
        park_summary = mae_stats.get("park_daily_summary", {})
        if park_summary:
            print("\n   Park MAE (latest date):")
            for pk, ps in sorted(park_summary.items()):
                name = PARK_NAMES.get(pk, pk)
                jump = ps.get("mae_jump_pct")
                jump_str = f" ({jump:+.0%})" if jump else ""
                print(f"     {name}: {ps.get('latest_mae', '?')}{jump_str}")

        # WTI accuracy
        wti = stats.get("wti_accuracy", {})
        if isinstance(wti, dict) and "wti_overall_mae" in wti:
            print(f"\n   WTI MAE: {wti['wti_overall_mae']} | Bias: {wti['wti_overall_bias']:+.1f}")

        for issue in result["issues"]:
            sev = "🔴" if issue["severity"] == "critical" else "🟡"
            print(f"\n  {sev} [{issue['type']}] {issue['message']}")
            print(f"     {issue['detail']}")

    exit_codes = {"ok": 0, "warning": 1, "critical": 2}
    sys.exit(exit_codes.get(result["status"], 3))


if __name__ == "__main__":
    main()
