#!/usr/bin/env python3
"""QA Ledger Stats — Flintstones Framework adaptive QA calculator.

Reads data/qa_ledger.json, computes failure rates per task type,
and reports current QA level (🟢/🟡/🔴) for each.

Usage: python3 qa_stats.py [--detail]
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

LEDGER = Path(__file__).parent.parent / "data" / "qa_ledger.json"

# Adaptive QA thresholds (from FRAMEWORK.md)
GREEN_THRESHOLD = 0.05   # <5% failure → 10-20% spot checks
YELLOW_THRESHOLD = 0.15  # 5-15% failure → 50% review
# >15% → Red (100% review)

COLD_START_MIN = 20  # need 20 tasks before leaving Yellow

def load_ledger():
    with open(LEDGER) as f:
        return json.load(f)

def compute_stats(entries, window=50):
    """Compute per-task-type stats over rolling window."""
    by_type = defaultdict(list)
    by_project = defaultdict(list)
    by_maker = defaultdict(list)

    for e in entries:
        by_type[e["task_type"]].append(e)
        by_project[e.get("project", "unknown")].append(e)
        by_maker[e.get("maker", "unknown")].append(e)

    stats = {}
    for task_type, tasks in by_type.items():
        recent = tasks[-window:]  # rolling window
        total = len(recent)
        failures = sum(1 for t in recent if t["verdict"] in ("revise", "escalate"))
        approvals = sum(1 for t in recent if t["verdict"] == "approve")
        failure_rate = failures / total if total > 0 else 0

        # Determine QA level
        if total < COLD_START_MIN:
            level = "🟡 YELLOW (cold start — need %d more tasks)" % (COLD_START_MIN - total)
        elif failure_rate < GREEN_THRESHOLD:
            level = "🟢 GREEN (spot check 10-20%%)"
        elif failure_rate < YELLOW_THRESHOLD:
            level = "🟡 YELLOW (review 50%%)"
        else:
            level = "🔴 RED (review 100%%)"

        avg_rounds = sum(t.get("rounds", 1) for t in recent) / total if total else 0

        stats[task_type] = {
            "total": total,
            "failures": failures,
            "approvals": approvals,
            "failure_rate": failure_rate,
            "level": level,
            "avg_rounds": avg_rounds,
        }

    return stats, by_project, by_maker

def main():
    detail = "--detail" in sys.argv
    data = load_ledger()
    entries = data["entries"]

    if not entries:
        print("📋 QA Ledger is empty. No stats to report.")
        return

    stats, by_project, by_maker = compute_stats(entries)

    print("=" * 60)
    print("📊 QA LEDGER STATS — Flintstones Framework")
    print("=" * 60)
    print(f"Total entries: {len(entries)}")
    print(f"Task types tracked: {len(stats)}")
    print()

    # Summary by task type
    print("─" * 60)
    print("BY TASK TYPE:")
    print("─" * 60)
    for task_type, s in sorted(stats.items()):
        print(f"\n  📌 {task_type}")
        print(f"     Tasks: {s['total']}  |  Approved: {s['approvals']}  |  Revise/Escalate: {s['failures']}")
        print(f"     Failure rate: {s['failure_rate']:.1%}  |  Avg rounds: {s['avg_rounds']:.1f}")
        print(f"     QA Level: {s['level']}")

    # Summary by project
    print("\n" + "─" * 60)
    print("BY PROJECT:")
    print("─" * 60)
    for project, tasks in sorted(by_project.items()):
        total = len(tasks)
        failures = sum(1 for t in tasks if t["verdict"] in ("revise", "escalate"))
        print(f"  {project}: {total} tasks, {failures} failures ({failures/total:.1%})")

    # Summary by maker
    print("\n" + "─" * 60)
    print("BY MAKER:")
    print("─" * 60)
    for maker, tasks in sorted(by_maker.items()):
        total = len(tasks)
        failures = sum(1 for t in tasks if t["verdict"] in ("revise", "escalate"))
        print(f"  {maker}: {total} tasks, {failures} failures ({failures/total:.1%})")

    if detail:
        print("\n" + "─" * 60)
        print("ALL ENTRIES:")
        print("─" * 60)
        for e in entries:
            status_icon = "✅" if e["verdict"] == "approve" else "🔄" if e["verdict"] == "revise" else "⬆️"
            print(f"  {status_icon} {e['task_id']} | {e['task_type']} | {e['maker']}→{e['checker']} | R{e.get('rounds',1)} | {e['verdict']}")
            if e.get("issues_found"):
                for issue in e["issues_found"]:
                    print(f"      ⚠️  [{issue['severity']}] {issue['description']}")

    print("\n" + "=" * 60)
    print("Note: QA levels use cold start (🟡 Yellow) until 20 tasks per type.")
    print("=" * 60)

if __name__ == "__main__":
    main()
