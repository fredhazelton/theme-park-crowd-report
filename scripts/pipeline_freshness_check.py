#!/usr/bin/env python3
"""
Pipeline Freshness Check (Phase 3)

Run every 6 hours. Validates that data is flowing and fresh — actuals arriving,
forecasts being updated, WTI computed for recent dates.

Checks:
  1. Are actuals flowing in? Count entities with data in last 24h
  2. Any "silent gaps" — dates where data stops without an error?
  3. Is the forecast archive being updated? (latest timestamp)
  4. Is WTI being computed for recent dates?
  5. Entity count comparison to 7-day average

Usage:
    python scripts/pipeline_freshness_check.py [--json] [--discord] [--quiet]

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

# ── Configuration ─────────────────────────────────────────────────────
PIPELINE_BASE = Path("/mnt/data/pipeline")
LIVE_DB = PIPELINE_BASE / "tpcr_live.duckdb"
FORECAST_PARQUET_DIR = PIPELINE_BASE / "curves" / "forecast_parquet"
ACCURACY_DIR = PIPELINE_BASE / "accuracy"
ARCHIVE_DIR = ACCURACY_DIR / "archive"
WTI_DIR = PIPELINE_BASE / "wti"
FACT_DIR = PIPELINE_BASE / "fact_tables" / "parquet"
STATE_DIR = PIPELINE_BASE / "state"

# Thresholds
ACTUAL_STALENESS_HOURS = 26      # Actuals older than this = stale
FORECAST_STALENESS_HOURS = 26    # Forecast file older than this = stale
WTI_STALENESS_HOURS = 26         # WTI file older than this = stale
ENTITY_DROP_PCT = 0.15           # Flag if entity count drops >15% from 7-day avg
GAP_DAYS_WARN = 2                # Warn if gap in actuals is > N days


def connect_live_db(retries: int = 3, delay: float = 2.0) -> duckdb.DuckDBPyConnection:
    """Connect to the live DB with retries for lock conflicts."""
    import time
    last_err = None
    for attempt in range(retries):
        try:
            return duckdb.connect(str(LIVE_DB), read_only=True)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(delay)
    raise last_err


def check_actuals_freshness(con: duckdb.DuckDBPyConnection) -> dict:
    """Check that actual wait time data is flowing in."""
    issues = []
    stats = {}
    now = datetime.now(timezone.utc)

    try:
        # Check live_waits for recent data
        freshness = con.execute("""
            SELECT 
                MAX(observed_at) as latest_obs,
                COUNT(DISTINCT entity_code) as entity_count,
                COUNT(*) as obs_count
            FROM live_waits
            WHERE park_date >= CURRENT_DATE - INTERVAL '1 day'
        """).fetchdf()

        if freshness.empty or freshness["latest_obs"].iloc[0] is None:
            issues.append({
                "type": "NO_RECENT_ACTUALS",
                "severity": "critical",
                "message": "No actual wait time data in the last 24 hours",
                "detail": "The scraper may have stopped or data pipeline is broken",
            })
            stats["actuals_flowing"] = False
            return {"issues": issues, "stats": stats}

        latest = freshness["latest_obs"].iloc[0]
        entity_count = int(freshness["entity_count"].iloc[0])
        obs_count = int(freshness["obs_count"].iloc[0])

        # Handle timezone-aware comparison
        if hasattr(latest, 'tzinfo') and latest.tzinfo is not None:
            age_hours = (now - latest).total_seconds() / 3600
        else:
            age_hours = (now - latest.replace(tzinfo=timezone.utc)).total_seconds() / 3600

        stats["actuals_flowing"] = True
        stats["latest_observation"] = str(latest)
        stats["actuals_age_hours"] = round(age_hours, 1)
        stats["recent_entity_count"] = entity_count
        stats["recent_obs_count"] = obs_count

        if age_hours > ACTUAL_STALENESS_HOURS:
            issues.append({
                "type": "ACTUALS_STALE",
                "severity": "critical",
                "message": f"Most recent actual data is {age_hours:.0f}h old",
                "detail": f"Latest observation: {latest}. Entities in last 24h: {entity_count}",
            })

    except Exception as e:
        issues.append({
            "type": "ACTUALS_QUERY_ERROR",
            "severity": "warning",
            "message": f"Could not check actuals freshness: {e}",
            "detail": str(e),
        })
        stats["actuals_flowing"] = None

    # Also check data_freshness table
    try:
        df_fresh = con.execute("""
            SELECT source, last_updated, row_count 
            FROM data_freshness 
            ORDER BY source
        """).fetchdf()
        stats["data_freshness"] = df_fresh.to_dict("records")
    except Exception:
        pass

    return {"issues": issues, "stats": stats}


def check_silent_gaps(con: duckdb.DuckDBPyConnection) -> dict:
    """Check for dates where data stops without any error."""
    issues = []
    stats = {}

    try:
        # Get dates with actuals in the last 14 days
        dates_df = con.execute("""
            SELECT DISTINCT park_date
            FROM live_waits
            WHERE park_date >= CURRENT_DATE - INTERVAL '14 days'
            ORDER BY park_date
        """).fetchdf()

        if dates_df.empty:
            return {"issues": issues, "stats": stats}

        dates = sorted(dates_df["park_date"].tolist())
        stats["dates_with_data"] = len(dates)

        # Find gaps
        gaps = []
        for i in range(1, len(dates)):
            prev = dates[i - 1]
            curr = dates[i]
            gap_days = (curr - prev).days
            if gap_days > GAP_DAYS_WARN:
                gaps.append({
                    "from": str(prev),
                    "to": str(curr),
                    "gap_days": gap_days,
                })

        if gaps:
            stats["gaps"] = gaps
            max_gap = max(g["gap_days"] for g in gaps)
            severity = "critical" if max_gap > 5 else "warning"
            issues.append({
                "type": "DATA_GAP",
                "severity": severity,
                "message": f"{len(gaps)} gap(s) in actuals data (max {max_gap} days)",
                "detail": f"Gaps: {gaps[:3]}",
            })

    except Exception as e:
        issues.append({
            "type": "GAP_CHECK_ERROR",
            "severity": "warning",
            "message": f"Could not check for data gaps: {e}",
            "detail": str(e),
        })

    return {"issues": issues, "stats": stats}


def check_forecast_freshness() -> dict:
    """Check that forecast outputs are being updated."""
    issues = []
    stats = {}
    now = datetime.now(timezone.utc)

    # Check all_forecasts.parquet
    forecast_file = FORECAST_PARQUET_DIR / "all_forecasts.parquet"
    if forecast_file.exists():
        mtime = datetime.fromtimestamp(forecast_file.stat().st_mtime, tz=timezone.utc)
        age_hours = (now - mtime).total_seconds() / 3600
        stats["forecast_file_age_hours"] = round(age_hours, 1)
        stats["forecast_file_mtime"] = mtime.isoformat()

        if age_hours > FORECAST_STALENESS_HOURS:
            issues.append({
                "type": "FORECAST_FILE_STALE",
                "severity": "warning",
                "message": f"Forecast parquet is {age_hours:.0f}h old (threshold: {FORECAST_STALENESS_HOURS}h)",
                "detail": f"Last updated: {mtime.strftime('%Y-%m-%d %H:%M UTC')}",
            })
    else:
        stats["forecast_file_exists"] = False
        issues.append({
            "type": "FORECAST_FILE_MISSING",
            "severity": "critical",
            "message": "all_forecasts.parquet not found",
            "detail": f"Expected at: {forecast_file}",
        })

    # Check forecast archive (latest archived forecast)
    if ARCHIVE_DIR.exists():
        archives = sorted(ARCHIVE_DIR.glob("forecast_*.parquet"))
        if archives:
            latest_archive = archives[-1]
            stats["latest_archive"] = latest_archive.name
            archive_mtime = datetime.fromtimestamp(latest_archive.stat().st_mtime, tz=timezone.utc)
            archive_age_hours = (now - archive_mtime).total_seconds() / 3600
            stats["archive_age_hours"] = round(archive_age_hours, 1)
        else:
            stats["archive_count"] = 0
    else:
        stats["archive_exists"] = False

    # Check pipeline_state.json timestamps
    state_file = STATE_DIR / "pipeline_state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            for key in ["training_completed", "forecast_completed", "wti_completed"]:
                ts_str = state.get(key)
                if ts_str:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    age = (now - ts).total_seconds() / 3600
                    stats[f"{key}_age_hours"] = round(age, 1)
        except Exception:
            pass

    return {"issues": issues, "stats": stats}


def check_wti_freshness(con: duckdb.DuckDBPyConnection) -> dict:
    """Check that WTI is being computed for recent dates."""
    issues = []
    stats = {}
    now = datetime.now(timezone.utc)

    # Check WTI parquet file
    wti_parquet = WTI_DIR / "wti.parquet"
    if wti_parquet.exists():
        mtime = datetime.fromtimestamp(wti_parquet.stat().st_mtime, tz=timezone.utc)
        age_hours = (now - mtime).total_seconds() / 3600
        stats["wti_file_age_hours"] = round(age_hours, 1)

        if age_hours > WTI_STALENESS_HOURS:
            issues.append({
                "type": "WTI_FILE_STALE",
                "severity": "critical",
                "message": f"WTI parquet is {age_hours:.0f}h old",
                "detail": f"Last updated: {mtime.strftime('%Y-%m-%d %H:%M UTC')}",
            })
    else:
        issues.append({
            "type": "WTI_FILE_MISSING",
            "severity": "critical",
            "message": "wti.parquet not found",
            "detail": f"Expected at: {wti_parquet}",
        })

    # Check WTI date coverage in live DB
    try:
        wti_df = con.execute("""
            SELECT 
                source,
                MIN(park_date) as min_date,
                MAX(park_date) as max_date,
                COUNT(*) as row_count,
                COUNT(DISTINCT park_date) as date_count
            FROM wti
            GROUP BY source
        """).fetchdf()
        stats["wti_coverage"] = wti_df.to_dict("records")

        # Check that forecast WTI covers near future
        forecast_wti = wti_df[wti_df["source"] == "forecast"]
        if not forecast_wti.empty:
            max_forecast_date = forecast_wti["max_date"].iloc[0]
            today = date.today()
            if hasattr(max_forecast_date, 'date'):
                max_forecast_date = max_forecast_date.date() if callable(getattr(max_forecast_date, 'date', None)) else max_forecast_date
            days_ahead = (max_forecast_date - today).days if max_forecast_date else 0
            stats["wti_forecast_days_ahead"] = days_ahead

            if days_ahead < 7:
                issues.append({
                    "type": "WTI_SHORT_HORIZON",
                    "severity": "warning",
                    "message": f"Forecast WTI only covers {days_ahead} days ahead (expected 365+)",
                    "detail": f"Max forecast date: {max_forecast_date}",
                })
        else:
            issues.append({
                "type": "WTI_NO_FORECAST",
                "severity": "warning",
                "message": "No forecast-source WTI data found",
                "detail": "WTI table has no rows with source='forecast'",
            })
    except Exception as e:
        issues.append({
            "type": "WTI_QUERY_ERROR",
            "severity": "warning",
            "message": f"Could not query WTI data: {e}",
            "detail": str(e),
        })

    return {"issues": issues, "stats": stats}


def check_entity_count_trend(con: duckdb.DuckDBPyConnection) -> dict:
    """Compare today's entity count to 7-day average."""
    issues = []
    stats = {}

    try:
        # Get entity counts by date for the last 14 days from live_waits
        trend_df = con.execute("""
            SELECT 
                park_date,
                COUNT(DISTINCT entity_code) as entity_count
            FROM live_waits
            WHERE park_date >= CURRENT_DATE - INTERVAL '14 days'
            GROUP BY park_date
            ORDER BY park_date
        """).fetchdf()

        if len(trend_df) < 2:
            return {"issues": issues, "stats": stats}

        # 7-day average (excluding today)
        import pandas as pd
        today = pd.Timestamp(date.today())
        trend_df["park_date"] = pd.to_datetime(trend_df["park_date"])
        historical = trend_df[trend_df["park_date"] < today]
        if len(historical) >= 3:
            avg_7d = historical["entity_count"].tail(7).mean()
            latest_count = trend_df["entity_count"].iloc[-1]

            stats["entity_count_today"] = int(latest_count)
            stats["entity_count_7d_avg"] = round(float(avg_7d), 1)

            if avg_7d > 0:
                drop_pct = (avg_7d - latest_count) / avg_7d
                stats["entity_count_drop_pct"] = round(float(drop_pct), 4)

                if drop_pct > ENTITY_DROP_PCT:
                    issues.append({
                        "type": "ENTITY_COUNT_DROP",
                        "severity": "warning",
                        "message": f"Entity count dropped {drop_pct:.1%} vs 7-day avg ({latest_count} vs {avg_7d:.0f})",
                        "detail": f"Recent counts: {trend_df[['park_date', 'entity_count']].tail(5).to_dict('records')}",
                    })

    except Exception as e:
        issues.append({
            "type": "TREND_CHECK_ERROR",
            "severity": "warning",
            "message": f"Could not check entity count trend: {e}",
            "detail": str(e),
        })

    return {"issues": issues, "stats": stats}


def run_freshness_check() -> dict:
    """Run all freshness checks."""
    all_issues = []
    all_stats = {}

    # Connect to live DB with retries (scraper may hold a lock)
    con = None
    try:
        con = connect_live_db(retries=3, delay=2.0)
    except Exception as e:
        all_issues.append({
            "type": "DB_LOCK_ERROR",
            "severity": "warning",
            "message": f"Could not open live DB (lock conflict): {e}",
            "detail": "The scraper may be writing. DB-dependent checks skipped.",
        })

    # Check 1: Actuals freshness (requires DB)
    if con:
        af = check_actuals_freshness(con)
        all_issues.extend(af["issues"])
        all_stats["actuals"] = af["stats"]

        # Check 2: Silent gaps
        sg = check_silent_gaps(con)
        all_issues.extend(sg["issues"])
        all_stats["gaps"] = sg["stats"]
    else:
        all_stats["actuals"] = {"note": "skipped (DB locked)"}
        all_stats["gaps"] = {"note": "skipped (DB locked)"}

    # Check 3: Forecast freshness (file-based, no DB needed)
    ff = check_forecast_freshness()
    all_issues.extend(ff["issues"])
    all_stats["forecasts"] = ff["stats"]

    # Check 4: WTI freshness
    if con:
        wf = check_wti_freshness(con)
        all_issues.extend(wf["issues"])
        all_stats["wti"] = wf["stats"]

        # Check 5: Entity count trend
        et = check_entity_count_trend(con)
        all_issues.extend(et["issues"])
        all_stats["entity_trend"] = et["stats"]
    else:
        all_stats["wti"] = {"note": "skipped (DB locked)"}
        all_stats["entity_trend"] = {"note": "skipped (DB locked)"}

    if con:
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
        "check": "pipeline_freshness",
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
    lines = [f"{emoji} **Pipeline Freshness Check** [{status.upper()}]"]

    stats = result.get("stats", {})

    # Actuals
    actuals = stats.get("actuals", {})
    if actuals.get("actuals_flowing") is False:
        lines.append("🔴 **No actuals flowing!**")
    elif "actuals_age_hours" in actuals:
        lines.append(f"Actuals age: {actuals['actuals_age_hours']:.0f}h | Entities: {actuals.get('recent_entity_count', '?')}")

    # Forecasts
    forecasts = stats.get("forecasts", {})
    if "forecast_file_age_hours" in forecasts:
        lines.append(f"Forecast file age: {forecasts['forecast_file_age_hours']:.0f}h")

    # WTI
    wti = stats.get("wti", {})
    if "wti_file_age_hours" in wti:
        lines.append(f"WTI file age: {wti['wti_file_age_hours']:.0f}h")

    # Entity trend
    trend = stats.get("entity_trend", {})
    if "entity_count_drop_pct" in trend and trend["entity_count_drop_pct"] > 0:
        lines.append(f"Entity count: {trend.get('entity_count_today', '?')} (7d avg: {trend.get('entity_count_7d_avg', '?')}, drop: {trend['entity_count_drop_pct']:.1%})")

    for issue in result["issues"]:
        sev = "🔴" if issue["severity"] == "critical" else "🟡"
        lines.append(f"{sev} {issue['message']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Pipeline freshness check")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--discord", action="store_true", help="Output Discord-formatted message")
    parser.add_argument("--quiet", action="store_true", help="Only output if issues found")
    args = parser.parse_args()

    try:
        result = run_freshness_check()
    except Exception as e:
        error_result = {
            "check": "pipeline_freshness",
            "status": "critical",
            "check_time": datetime.now(timezone.utc).isoformat(),
            "issues": [{
                "type": "CHECK_ERROR",
                "severity": "critical",
                "message": f"Freshness check failed: {e}",
                "detail": str(e),
            }]
        }
        if args.json:
            print(json.dumps(error_result, indent=2))
        else:
            print(f"🚨 Freshness check error: {e}")
        sys.exit(3)

    if args.quiet and result["status"] == "ok":
        sys.exit(0)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    elif args.discord:
        print(format_discord_alert(result))
    else:
        emoji = {"ok": "✅", "warning": "⚠️", "critical": "🚨"}
        print(f"\n{emoji.get(result['status'], '?')} Pipeline Freshness: {result['status'].upper()}")
        print(f"   Issues: {result['issue_count']}")

        stats = result.get("stats", {})

        actuals = stats.get("actuals", {})
        if actuals:
            print(f"\n   Actuals flowing: {actuals.get('actuals_flowing', '?')}")
            if "actuals_age_hours" in actuals:
                print(f"   Latest actual: {actuals.get('actuals_age_hours', '?')}h ago ({actuals.get('recent_entity_count', '?')} entities)")

        forecasts = stats.get("forecasts", {})
        if "forecast_file_age_hours" in forecasts:
            print(f"   Forecast file: {forecasts['forecast_file_age_hours']:.0f}h old")

        wti = stats.get("wti", {})
        if "wti_file_age_hours" in wti:
            print(f"   WTI file: {wti['wti_file_age_hours']:.0f}h old")

        trend = stats.get("entity_trend", {})
        if trend:
            print(f"   Entity count today: {trend.get('entity_count_today', '?')} (7d avg: {trend.get('entity_count_7d_avg', '?')})")

        gaps = stats.get("gaps", {})
        if gaps.get("gaps"):
            print(f"   Data gaps: {gaps['gaps']}")

        for issue in result["issues"]:
            sev = "🔴" if issue["severity"] == "critical" else "🟡"
            print(f"\n  {sev} [{issue['type']}] {issue['message']}")
            print(f"     {issue['detail']}")

    exit_codes = {"ok": 0, "warning": 1, "critical": 2}
    sys.exit(exit_codes.get(result["status"], 3))


if __name__ == "__main__":
    main()
