#!/usr/bin/env python3
"""
Pipeline Data Completeness Check (Phase 2)

Run after each pipeline run (training + forecast). Validates that outputs
are complete, correct, and haven't silently degraded.

Checks:
  1. Are all expected entities present in today's forecasts?
  2. How many entities used fallback vs trained models? Alert if fallback_ratio > 10%
  3. Are accuracy eval dates suspiciously incomplete?
  4. Any entities that had models yesterday but fell back today?
  5. Summary stats: entity counts by prediction method

Usage:
    python scripts/pipeline_data_completeness.py [--json] [--fix] [--date YYYY-MM-DD]

Exit codes:
    0 = ok
    1 = warning
    2 = critical
    3 = script error
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

import duckdb

# ── Configuration ─────────────────────────────────────────────────────
PIPELINE_BASE = Path("/mnt/data/pipeline")
LIVE_DB = PIPELINE_BASE / "tpcr_live.duckdb"
MODELS_DIR = PIPELINE_BASE / "models"
ACCURACY_DIR = PIPELINE_BASE / "accuracy"
FORECAST_PARQUET_DIR = PIPELINE_BASE / "curves" / "forecast_parquet"
DIMENSION_DIR = PIPELINE_BASE / "dimension_tables"
STATE_DIR = PIPELINE_BASE / "state"
FACT_DIR = PIPELINE_BASE / "fact_tables" / "parquet"

# Thresholds
FALLBACK_RATIO_WARN = 0.10   # Warn if > 10% of entities are on fallback
FALLBACK_RATIO_CRIT = 0.25   # Critical if > 25% fallback
ENTITY_DROP_WARN = 0.05      # Warn if entity count drops > 5% from expected
ACCURACY_ENTITY_LOW = 0.50   # Flag dates where evaluated entities < 50% of available

PROJECT_ROOT = Path("/home/wilma/theme-park-crowd-report")


def get_expected_entities(con: duckdb.DuckDBPyConnection) -> set:
    """Get the set of entities we expect to have forecasts for.
    
    Priority order:
    1. entities_to_train.txt (the pipeline's own list of entities it forecasts)
    2. entities with model directories on disk
    3. Fallback: entities table with has_posted=true (i.e., entities with data)
    """
    # Best source: the pipeline's own entity list
    entities_file = STATE_DIR / "entities_to_train.txt"
    if entities_file.exists():
        with open(entities_file) as f:
            entities = set(line.strip() for line in f if line.strip())
        if entities:
            return entities

    # Second: entities that have model dirs
    if MODELS_DIR.exists():
        entities = set()
        for d in MODELS_DIR.iterdir():
            if d.is_dir() and not d.name.startswith('.') and not d.name.startswith('_'):
                entities.add(d.name)
        if entities:
            return entities

    # Fallback: DB query for entities that actually have data
    try:
        df = con.execute("""
            SELECT entity_code 
            FROM entities 
            WHERE has_wait_times = true AND is_extinct = false AND has_posted = true
        """).fetchdf()
        return set(df["entity_code"].tolist())
    except Exception:
        entity_csv = DIMENSION_DIR / "dimentity.csv"
        if entity_csv.exists():
            import pandas as pd
            edf = pd.read_csv(entity_csv)
            active = edf[(edf["extinct_on"].isna() | (edf["extinct_on"] == "")) & (edf["has_posted"] == True)]
            return set(active["code"].tolist())
        return set()


def get_entities_with_models() -> set:
    """Get entities that have trained Julia v2 models."""
    entities = set()
    if not MODELS_DIR.exists():
        return entities
    for d in MODELS_DIR.iterdir():
        if d.is_dir() and (d / "model_julia_v2.json").exists():
            entities.add(d.name)
    return entities


def get_recent_forecast_baseline(con: duckdb.DuckDBPyConnection) -> tuple[int, set]:
    """Get the typical entity count and set from recent forecasts.
    
    Returns the median entity count and entity set from the most stable
    recent forecast dates (to compare against current).
    """
    try:
        # Get entity count per date for recent forecasts (first 7 dates after today)
        df = con.execute("""
            SELECT park_date, COUNT(DISTINCT entity_code) as entity_count
            FROM forecasts
            WHERE park_date >= CURRENT_DATE
            GROUP BY park_date
            ORDER BY park_date
            LIMIT 14
        """).fetchdf()
        if df.empty:
            return 0, set()

        median_count = int(df["entity_count"].median())

        # Get entity set from the date closest to today
        first_date = df["park_date"].iloc[0]
        entities_df = con.execute(f"""
            SELECT DISTINCT entity_code
            FROM forecasts
            WHERE park_date = '{first_date}'
        """).fetchdf()
        return median_count, set(entities_df["entity_code"].tolist())
    except Exception:
        return 0, set()


def check_forecast_completeness(con: duckdb.DuckDBPyConnection, check_date: str) -> dict:
    """Check that forecasts cover all expected entities."""
    issues = []
    stats = {}

    # Get the pipeline's expected entity list (training candidates)
    training_expected = get_expected_entities(con)
    stats["training_entity_count"] = len(training_expected)

    # Get baseline from recent forecast history (what we actually produce)
    baseline_count, baseline_entities = get_recent_forecast_baseline(con)
    stats["baseline_entity_count"] = baseline_count

    # Get entities present in forecasts for the check date
    try:
        forecast_df = con.execute(f"""
            SELECT DISTINCT entity_code, prediction_method
            FROM forecasts
            WHERE park_date = '{check_date}'
        """).fetchdf()
    except Exception as e:
        issues.append({
            "type": "FORECAST_QUERY_ERROR",
            "severity": "critical",
            "message": f"Could not query forecasts: {e}",
            "detail": str(e),
        })
        return {"issues": issues, "stats": stats}

    if forecast_df.empty:
        issues.append({
            "type": "NO_FORECASTS",
            "severity": "critical",
            "message": f"No forecasts found for {check_date}",
            "detail": "The forecast table has no rows for the target date",
        })
        return {"issues": issues, "stats": stats}

    forecast_entities = set(forecast_df["entity_code"].tolist())
    stats["forecast_entity_count"] = len(forecast_entities)

    # Entities by prediction method
    method_counts = forecast_df.groupby("prediction_method").size().to_dict()
    stats["prediction_methods"] = method_counts

    # Check against baseline (entities that WERE being forecast but now aren't)
    if baseline_entities:
        dropped = baseline_entities - forecast_entities
        if dropped:
            stats["dropped_entities"] = sorted(dropped)
            drop_pct = len(dropped) / len(baseline_entities)
            severity = "critical" if drop_pct > ENTITY_DROP_WARN else "warning"
            issues.append({
                "type": "ENTITY_DROP",
                "severity": severity,
                "message": f"{len(dropped)} entities dropped from forecasts vs recent baseline ({drop_pct:.1%})",
                "detail": f"Dropped: {', '.join(sorted(dropped)[:10])}{'...' if len(dropped) > 10 else ''}",
            })

    # Check against training list (entities we SHOULD be forecasting but aren't)
    if training_expected:
        not_forecasted = training_expected - forecast_entities
        # Only flag if significant and these are entities that have model dirs
        entities_with_models = get_entities_with_models()
        should_have = not_forecasted & entities_with_models
        if should_have:
            stats["entities_with_models_not_forecasted"] = len(should_have)
            if len(should_have) > 5:
                issues.append({
                    "type": "MODELS_NOT_FORECASTED",
                    "severity": "warning",
                    "message": f"{len(should_have)} entities have trained models but no forecasts",
                    "detail": f"Examples: {', '.join(sorted(should_have)[:10])}",
                })

    # Fallback ratio check
    fallback_methods = {"fallback_ratio", "aggregate"}
    trained_methods = {"model_actuals", "model_v2", "model_scope_scale", "model_lite"}

    fallback_count = sum(method_counts.get(m, 0) for m in fallback_methods)
    trained_count = sum(method_counts.get(m, 0) for m in trained_methods)
    total = fallback_count + trained_count

    if total > 0:
        fallback_ratio = fallback_count / total
        stats["fallback_count"] = fallback_count
        stats["trained_count"] = trained_count
        stats["fallback_ratio"] = round(fallback_ratio, 4)

        if fallback_ratio > FALLBACK_RATIO_CRIT:
            issues.append({
                "type": "HIGH_FALLBACK_RATIO",
                "severity": "critical",
                "message": f"{fallback_count}/{total} entities ({fallback_ratio:.1%}) using fallback predictions",
                "detail": f"Threshold: warn>{FALLBACK_RATIO_WARN:.0%}, critical>{FALLBACK_RATIO_CRIT:.0%}. Methods: {method_counts}",
            })
        elif fallback_ratio > FALLBACK_RATIO_WARN:
            issues.append({
                "type": "ELEVATED_FALLBACK_RATIO",
                "severity": "warning",
                "message": f"{fallback_count}/{total} entities ({fallback_ratio:.1%}) using fallback predictions",
                "detail": f"Methods: {method_counts}",
            })

    return {"issues": issues, "stats": stats}


def check_model_regression(con: duckdb.DuckDBPyConnection, check_date: str) -> dict:
    """Check if any entities regressed from trained model to fallback."""
    issues = []
    stats = {}

    # Entities with trained models on disk
    entities_with_models = get_entities_with_models()
    stats["entities_with_v2_models"] = len(entities_with_models)

    if not entities_with_models:
        return {"issues": issues, "stats": stats}

    # Check which of these are using fallback in forecasts
    try:
        fallback_df = con.execute(f"""
            SELECT DISTINCT entity_code, prediction_method
            FROM forecasts
            WHERE park_date = '{check_date}'
              AND entity_code IN ({','.join("'" + e + "'" for e in entities_with_models)})
              AND prediction_method IN ('fallback_ratio', 'aggregate')
        """).fetchdf()
    except Exception:
        return {"issues": issues, "stats": stats}

    if not fallback_df.empty:
        regressed = fallback_df["entity_code"].tolist()
        stats["regressed_entities"] = sorted(regressed)
        stats["regressed_count"] = len(regressed)

        severity = "critical" if len(regressed) > 10 else "warning"
        issues.append({
            "type": "MODEL_REGRESSION",
            "severity": severity,
            "message": f"{len(regressed)} entities have trained models but are using fallback predictions",
            "detail": f"These entities have model_julia_v2.json on disk but forecasts use fallback: {', '.join(sorted(regressed)[:10])}{'...' if len(regressed) > 10 else ''}",
        })

    return {"issues": issues, "stats": stats}


def check_accuracy_completeness(con: duckdb.DuckDBPyConnection) -> dict:
    """Check accuracy evaluation dates for suspicious incompleteness."""
    issues = []
    stats = {}

    accuracy_parquet = ACCURACY_DIR / "entity_daily_accuracy.parquet"
    if not accuracy_parquet.exists():
        stats["accuracy_available"] = False
        return {"issues": issues, "stats": stats}

    stats["accuracy_available"] = True

    try:
        # Get entity counts per evaluation_date
        eval_df = con.execute(f"""
            SELECT 
                park_date,
                evaluation_date,
                COUNT(DISTINCT entity_code) as eval_entity_count,
                AVG(mae) as avg_mae
            FROM read_parquet('{accuracy_parquet}')
            GROUP BY park_date, evaluation_date
            ORDER BY park_date
        """).fetchdf()
    except Exception as e:
        issues.append({
            "type": "ACCURACY_QUERY_ERROR",
            "severity": "warning",
            "message": f"Could not query accuracy data: {e}",
            "detail": str(e),
        })
        return {"issues": issues, "stats": stats}

    if eval_df.empty:
        return {"issues": issues, "stats": stats}

    stats["accuracy_dates"] = len(eval_df)
    stats["avg_entities_per_date"] = round(eval_df["eval_entity_count"].mean(), 1)

    # Flag dates with suspiciously low entity counts
    median_count = eval_df["eval_entity_count"].median()
    if median_count > 0:
        low_dates = eval_df[eval_df["eval_entity_count"] < median_count * ACCURACY_ENTITY_LOW]
        if not low_dates.empty:
            stats["low_entity_dates"] = low_dates[["park_date", "eval_entity_count"]].to_dict("records")
            issues.append({
                "type": "ACCURACY_INCOMPLETE_DATES",
                "severity": "warning",
                "message": f"{len(low_dates)} accuracy dates have <50% of typical entity count (median={median_count:.0f})",
                "detail": f"Low dates: {low_dates['park_date'].tolist()[:5]}",
            })

    return {"issues": issues, "stats": stats}


def attempt_fix_accuracy(con: duckdb.DuckDBPyConnection) -> list:
    """Attempt to re-run accuracy evaluation for stale/incomplete dates."""
    results = []
    eval_script = PROJECT_ROOT / "src" / "evaluate_forecast_accuracy.py"

    if not eval_script.exists():
        results.append({"action": "skip", "reason": "evaluate_forecast_accuracy.py not found"})
        return results

    try:
        result = subprocess.run(
            [str(PROJECT_ROOT / ".venv" / "bin" / "python3"), str(eval_script)],
            capture_output=True, text=True, timeout=300,
            cwd=str(PROJECT_ROOT),
        )
        results.append({
            "action": "re-run accuracy eval",
            "exit_code": result.returncode,
            "stdout_tail": result.stdout[-500:] if result.stdout else "",
            "stderr_tail": result.stderr[-500:] if result.stderr else "",
        })
    except subprocess.TimeoutExpired:
        results.append({"action": "re-run accuracy eval", "error": "timeout after 300s"})
    except Exception as e:
        results.append({"action": "re-run accuracy eval", "error": str(e)})

    return results


def run_completeness_check(check_date: str = None, do_fix: bool = False) -> dict:
    """Run all completeness checks."""
    if check_date is None:
        # Use the max forecast date as the check date
        check_date = (date.today() + timedelta(days=1)).isoformat()

    import time as _time
    last_err = None
    con = None
    for _attempt in range(3):
        try:
            con = duckdb.connect(str(LIVE_DB), read_only=True)
            break
        except Exception as e:
            last_err = e
            _time.sleep(2)
    if con is None:
        return {
            "check": "pipeline_data_completeness",
            "status": "critical",
            "check_time": datetime.now(timezone.utc).isoformat(),
            "check_date": check_date or "",
            "issue_count": 1,
            "issues": [{"type": "DB_LOCK_ERROR", "severity": "critical",
                        "message": f"Cannot open live DB: {last_err}", "detail": str(last_err)}],
            "stats": {},
        }

    # Determine a good date to check (first future date in forecasts)
    try:
        max_date = con.execute("SELECT MAX(park_date)::VARCHAR FROM forecasts").fetchone()[0]
        if max_date:
            check_date = max_date
    except Exception:
        pass

    all_issues = []
    all_stats = {}

    # Check 1: Forecast completeness
    fc = check_forecast_completeness(con, check_date)
    all_issues.extend(fc["issues"])
    all_stats["forecast"] = fc["stats"]

    # Check 2: Model regression
    mr = check_model_regression(con, check_date)
    all_issues.extend(mr["issues"])
    all_stats["models"] = mr["stats"]

    # Check 3: Accuracy completeness
    ac = check_accuracy_completeness(con)
    all_issues.extend(ac["issues"])
    all_stats["accuracy"] = ac["stats"]

    con.close()

    # Determine overall status
    severities = [i["severity"] for i in all_issues]
    if "critical" in severities:
        status = "critical"
    elif "warning" in severities:
        status = "warning"
    else:
        status = "ok"

    result = {
        "check": "pipeline_data_completeness",
        "status": status,
        "check_time": datetime.now(timezone.utc).isoformat(),
        "check_date": check_date,
        "issue_count": len(all_issues),
        "issues": all_issues,
        "stats": all_stats,
    }

    # Attempt remediation if requested
    if do_fix and status != "ok":
        fix_con = duckdb.connect(str(LIVE_DB), read_only=True)
        result["fix_results"] = attempt_fix_accuracy(fix_con)
        fix_con.close()

    return result


def format_discord_alert(result: dict) -> str:
    """Format as Discord message."""
    status = result["status"]
    emoji = {"ok": "✅", "warning": "⚠️", "critical": "🚨"}[status]
    lines = [f"{emoji} **Pipeline Data Completeness** [{status.upper()}]"]

    stats = result.get("stats", {})
    fc = stats.get("forecast", {})
    if fc:
        methods = fc.get("prediction_methods", {})
        baseline = fc.get('baseline_entity_count', fc.get('training_entity_count', '?'))
        lines.append(f"Entities: {fc.get('forecast_entity_count', '?')}/{baseline} baseline")
        if methods:
            lines.append("Methods: " + " | ".join(f"{k}: {v}" for k, v in sorted(methods.items())))
        if "fallback_ratio" in fc:
            lines.append(f"Fallback ratio: **{fc['fallback_ratio']:.1%}**")

    for issue in result["issues"]:
        sev = "🔴" if issue["severity"] == "critical" else "🟡"
        lines.append(f"{sev} {issue['message']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Pipeline data completeness check")
    parser.add_argument("--date", help="Date to check forecasts for (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--fix", action="store_true", help="Attempt auto-remediation")
    parser.add_argument("--discord", action="store_true", help="Output Discord-formatted message")
    parser.add_argument("--quiet", action="store_true", help="Only output if issues found")
    args = parser.parse_args()

    try:
        result = run_completeness_check(check_date=args.date, do_fix=args.fix)
    except Exception as e:
        error_result = {
            "check": "pipeline_data_completeness",
            "status": "critical",
            "check_time": datetime.now(timezone.utc).isoformat(),
            "issues": [{
                "type": "CHECK_ERROR",
                "severity": "critical",
                "message": f"Completeness check failed: {e}",
                "detail": str(e),
            }]
        }
        if args.json:
            print(json.dumps(error_result, indent=2))
        else:
            print(f"🚨 Completeness check error: {e}")
        sys.exit(3)

    if args.quiet and result["status"] == "ok":
        sys.exit(0)

    if args.json:
        print(json.dumps(result, indent=2))
    elif args.discord:
        print(format_discord_alert(result))
    else:
        emoji = {"ok": "✅", "warning": "⚠️", "critical": "🚨"}
        print(f"\n{emoji.get(result['status'], '?')} Data Completeness: {result['status'].upper()}")
        print(f"   Check date: {result['check_date']}")
        print(f"   Issues: {result['issue_count']}")

        stats = result.get("stats", {})
        fc = stats.get("forecast", {})
        if fc:
            baseline = fc.get('baseline_entity_count', fc.get('training_entity_count', '?'))
            print(f"\n   Forecast entities: {fc.get('forecast_entity_count', '?')}/{baseline} baseline")
            methods = fc.get("prediction_methods", {})
            if methods:
                for m, c in sorted(methods.items()):
                    print(f"     {m}: {c}")
            if "fallback_ratio" in fc:
                print(f"   Fallback ratio: {fc['fallback_ratio']:.1%}")

        models = stats.get("models", {})
        if models.get("regressed_count"):
            print(f"\n   ⚠️  Model regressions: {models['regressed_count']} entities")

        for issue in result["issues"]:
            sev = "🔴" if issue["severity"] == "critical" else "🟡"
            print(f"\n  {sev} [{issue['type']}] {issue['message']}")
            print(f"     {issue['detail']}")

    exit_codes = {"ok": 0, "warning": 1, "critical": 2}
    sys.exit(exit_codes.get(result["status"], 3))


if __name__ == "__main__":
    main()
