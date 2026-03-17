#!/usr/bin/env python3
"""
Live project status — single source of truth for all agents.

Run this BEFORE reporting on any project. Do NOT use hardcoded stats.

Usage:
    python3 scripts/project_status.py              # All projects
    python3 scripts/project_status.py --project ssd
    python3 scripts/project_status.py --project tpcr
    python3 scripts/project_status.py --project accord
    python3 scripts/project_status.py --json        # Machine-readable
"""

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/Toronto")


def ssd_status() -> dict:
    """School Schedules Database — live stats from actual data files."""
    ssd_dir = Path("/home/wilma/theme-park-crowd-report/data/school_schedules")
    csv_file = ssd_dir / "districts_comprehensive.csv"

    status = {
        "project": "SSD",
        "name": "School Schedules Database",
    }

    if not csv_file.exists():
        status["error"] = "districts_comprehensive.csv not found"
        return status

    rows = list(csv.DictReader(open(csv_file)))
    total = len(rows)

    # Confidence breakdown
    conf = Counter(r.get("confidence", "") for r in rows)
    confirmed = conf.get("confirmed", 0)
    medium = conf.get("medium", 0)
    low = conf.get("low", 0)
    none_conf = conf.get("none", 0) + conf.get("", 0)

    # Source breakdown
    sources = Counter(r.get("source", "") for r in rows)
    state_median = sources.get("state_median_inference", 0)

    # Real vs inferred
    real_data = total - state_median - none_conf
    inferred = state_median

    status.update({
        "total_districts": total,
        "confirmed": confirmed,
        "confirmed_pct": round(confirmed / total * 100, 1) if total else 0,
        "medium_inferred": medium,
        "medium_inferred_pct": round(medium / total * 100, 1) if total else 0,
        "real_data_districts": real_data,
        "real_data_pct": round(real_data / total * 100, 1) if total else 0,
        "state_median_inference": state_median,
        "no_data": none_conf,
        "sources": dict(sources.most_common()),
    })

    # LLM scraper status
    llm_file = ssd_dir / "llm_scraper_results.json"
    if llm_file.exists():
        llm = json.load(open(llm_file))
        llm_found = sum(1 for r in llm.values() if r.get("status") == "found")
        llm_total = len(llm)
        # How many LLM results are merged into main CSV?
        llm_in_csv = sum(1 for r in rows if "llm" in r.get("source", "").lower())
        status["llm_scraper"] = {
            "processed": llm_total,
            "found": llm_found,
            "merged_into_csv": llm_in_csv,
            "unmerged": llm_found - llm_in_csv,
        }

    # Pipeline v2 status
    pv2_file = ssd_dir / "pipeline_v2_results.json"
    if pv2_file.exists():
        pv2 = json.load(open(pv2_file))
        pv2_entries = list(pv2.values()) if isinstance(pv2, dict) else pv2
        pv2_found = sum(1 for r in pv2_entries if isinstance(r, dict) and r.get("status") == "found")
        status["pipeline_v2"] = {
            "processed": len(pv2_entries),
            "found": pv2_found,
            "hit_rate_pct": round(pv2_found / len(pv2_entries) * 100, 1) if pv2_entries else 0,
        }

    # Active scraper check
    try:
        result = subprocess.run(
            ["pgrep", "-f", "llm_scraper|brave_scraper|pipeline_v2"],
            capture_output=True, text=True, timeout=5,
        )
        status["scraper_running"] = result.returncode == 0
    except Exception:
        status["scraper_running"] = "unknown"

    # Summary line for agents
    status["summary"] = (
        f"SSD: {total} districts total — {confirmed} confirmed ({status['confirmed_pct']}%), "
        f"{state_median} state-median inferences ({status['medium_inferred_pct']}%). "
        f"Real coverage: {status['real_data_pct']}%. "
        f"Target: convert the {state_median} inferred districts to confirmed."
    )

    return status


def tpcr_status() -> dict:
    """Theme Park Crowd Report — live pipeline stats."""
    status = {
        "project": "TPCR",
        "name": "Theme Park Crowd Report",
    }

    # Accuracy stats
    acc_file = Path("/home/wilma/hazeydata/pipeline/accuracy/accuracy_summary.json")
    if acc_file.exists():
        acc = json.load(open(acc_file))
        status["accuracy"] = {
            "wti_mae": round(acc.get("wti_mae", 0), 1),
            "wti_bias": round(acc.get("wti_bias", 0), 1),
            "wti_dates_evaluated": acc.get("wti_dates_evaluated", 0),
            "last_eval_date": acc.get("wti_last_eval_date", "unknown"),
            "last_run": acc.get("last_run", "unknown"),
        }

    # Pipeline health
    log_dir = Path("/home/wilma/hazeydata/pipeline/logs")
    today = datetime.now(ET).strftime("%Y-%m-%d")
    yesterday = (datetime.now(ET) - timedelta(days=1)).strftime("%Y-%m-%d")

    today_log = log_dir / f"v3_{today}.log"
    yesterday_log = log_dir / f"v3_{yesterday}.log"

    if today_log.exists():
        status["pipeline_last_run"] = today
        status["pipeline_healthy"] = True
    elif yesterday_log.exists():
        status["pipeline_last_run"] = yesterday
        status["pipeline_healthy"] = True
    else:
        recent = sorted(log_dir.glob("v3_*.log"))
        if recent:
            status["pipeline_last_run"] = recent[-1].stem.replace("v3_", "")
            days_ago = (datetime.now(ET).date() - datetime.strptime(status["pipeline_last_run"], "%Y-%m-%d").date()).days
            status["pipeline_healthy"] = days_ago <= 2
        else:
            status["pipeline_last_run"] = "unknown"
            status["pipeline_healthy"] = False

    # WTI data freshness
    wti_v3 = Path("/home/wilma/hazeydata/pipeline/wti/wti_v3.parquet")
    wti_legacy = Path("/home/wilma/hazeydata/pipeline/wti/wti.parquet")
    wti_file = wti_v3 if wti_v3.exists() else wti_legacy
    if wti_file.exists():
        mtime = datetime.fromtimestamp(wti_file.stat().st_mtime, tz=ET)
        status["wti_data_updated"] = mtime.strftime("%Y-%m-%d %H:%M")
        status["wti_data_stale"] = (datetime.now(ET) - mtime).total_seconds() > 86400 * 2

    # Website
    blog_dir = Path("/home/wilma/hazeydata.ai/theme-park-crowd-report/blog")
    if blog_dir.exists():
        posts = sorted(blog_dir.glob("*.html"))
        posts = [p for p in posts if p.name != "index.html" and "draft" not in p.name]
        status["blog_posts"] = len(posts)
        if posts:
            status["latest_blog"] = posts[-1].name

    # Git activity
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-1", "--format=%ci"],
            capture_output=True, text=True, timeout=5,
            cwd="/home/wilma/theme-park-crowd-report",
        )
        if result.returncode == 0:
            status["last_commit"] = result.stdout.strip()[:10]
    except Exception:
        pass

    acc_info = status.get("accuracy", {})
    status["summary"] = (
        f"TPCR: Pipeline {'healthy' if status.get('pipeline_healthy') else 'UNHEALTHY'}, "
        f"last run {status.get('pipeline_last_run', 'unknown')}. "
        f"WTI accuracy: MAE {acc_info.get('wti_mae', '?')}, "
        f"bias {acc_info.get('wti_bias', '?'):+} over {acc_info.get('wti_dates_evaluated', '?')} days. "
        f"{status.get('blog_posts', 0)} blog posts published."
    )

    return status


def accord_status() -> dict:
    """ACCORD — Canadian hotel occupancy project status."""
    status = {
        "project": "ACCORD",
        "name": "ACCORD (Canadian Hotel Occupancy)",
    }

    accord_dir = Path("/home/wilma/ACCORD")
    if not accord_dir.exists():
        status["error"] = "ACCORD directory not found"
        status["summary"] = "ACCORD: Directory not found at ~/ACCORD"
        return status

    # Git activity
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-1", "--format=%ci %s"],
            capture_output=True, text=True, timeout=5,
            cwd=str(accord_dir),
        )
        if result.returncode == 0:
            status["last_commit"] = result.stdout.strip()
    except Exception:
        pass

    # Open issues
    try:
        result = subprocess.run(
            ["gh", "issue", "list", "--repo", "hazeydata/ACCORD", "--state", "open", "--json", "number"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            issues = json.loads(result.stdout)
            status["open_issues"] = len(issues)
    except Exception:
        pass

    status["summary"] = (
        f"ACCORD: Last commit {status.get('last_commit', 'unknown')[:10] if status.get('last_commit') else 'unknown'}. "
        f"{status.get('open_issues', '?')} open issues."
    )

    return status


def print_human_readable(statuses: list[dict]):
    """Print a human-readable status report."""
    print("=" * 60)
    print(f"  PROJECT STATUS — {datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}")
    print("=" * 60)

    for s in statuses:
        print()
        print(f"📋 {s.get('name', s.get('project', 'Unknown'))}")
        print("-" * 40)

        if "error" in s:
            print(f"  ⚠️  {s['error']}")
            continue

        if s["project"] == "SSD":
            print(f"  Total districts: {s['total_districts']}")
            print(f"  ✅ Confirmed (real data): {s['confirmed']} ({s['confirmed_pct']}%)")
            print(f"  ⚠️  State-median inference: {s['medium_inferred']} ({s['medium_inferred_pct']}%)")
            print(f"  ❌ No data: {s['no_data']}")
            if "llm_scraper" in s:
                llm = s["llm_scraper"]
                print(f"  🤖 LLM scraper: {llm['found']} found, {llm['merged_into_csv']} merged, {llm['unmerged']} UNMERGED")
            if "pipeline_v2" in s:
                pv2 = s["pipeline_v2"]
                print(f"  🔧 Pipeline v2: {pv2['processed']} processed, {pv2['found']} found ({pv2['hit_rate_pct']}% hit rate)")
            print(f"  🔄 Scraper running: {s.get('scraper_running', 'unknown')}")

        elif s["project"] == "TPCR":
            print(f"  Pipeline: {'✅ healthy' if s.get('pipeline_healthy') else '❌ UNHEALTHY'} (last run: {s.get('pipeline_last_run', 'unknown')})")
            if "accuracy" in s:
                acc = s["accuracy"]
                print(f"  WTI accuracy: MAE {acc['wti_mae']}, bias {acc['wti_bias']:+} ({acc['wti_dates_evaluated']} days)")
                print(f"  Last eval: {acc['last_eval_date']}")
            if "wti_data_updated" in s:
                stale = " ⚠️ STALE!" if s.get("wti_data_stale") else ""
                print(f"  WTI data: {s['wti_data_updated']}{stale}")
            print(f"  Blog posts: {s.get('blog_posts', 0)} (latest: {s.get('latest_blog', 'none')})")

        elif s["project"] == "ACCORD":
            print(f"  Last commit: {s.get('last_commit', 'unknown')}")
            print(f"  Open issues: {s.get('open_issues', 'unknown')}")

        print()
        print(f"  📝 {s.get('summary', 'No summary')}")

    print()
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Live project status")
    parser.add_argument("--project", choices=["ssd", "tpcr", "accord", "all"], default="all")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    status_funcs = {
        "ssd": ssd_status,
        "tpcr": tpcr_status,
        "accord": accord_status,
    }

    if args.project == "all":
        statuses = [f() for f in status_funcs.values()]
    else:
        statuses = [status_funcs[args.project]()]

    if args.json:
        print(json.dumps(statuses, indent=2, default=str))
    else:
        print_human_readable(statuses)


if __name__ == "__main__":
    main()
