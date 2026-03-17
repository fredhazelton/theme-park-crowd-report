#!/usr/bin/env python3
"""
Show open issues for a specific agent. Used at the start of work sessions
so agents know what Gazoo wants them to fix.

Usage: python3 my_issues.py <agent_name>
"""
import json, sys, os

LEDGER_PATH = os.path.expanduser("~/clawd/data/improvement_ledger.json")

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 my_issues.py <agent_name>")
        sys.exit(1)
    
    agent = sys.argv[1].lower()
    data = json.load(open(LEDGER_PATH))
    
    if agent not in data["agents"]:
        print(f"Unknown agent: {agent}")
        sys.exit(1)
    
    a = data["agents"][agent]
    open_issues = [i for i in a["issues"] if i["status"] == "open"]
    scores = [s["score"] for s in a["scores"]]
    
    if not open_issues and not scores:
        print(f"No issues or scores yet for {agent}. Fresh start!")
        return
    
    trend_emoji = {"improving": "📈", "declining": "📉", "flat": "➡️", "new": "🆕"}
    
    if scores:
        last = scores[-1]
        print(f"Last score: {last}/10 | Trend: {trend_emoji.get(a['trend'], '')} {a['trend']}")
    
    if open_issues:
        print(f"\n⚠️ {len(open_issues)} OPEN ISSUE(S) from Gazoo — FIX THESE TODAY:")
        for issue in sorted(open_issues, key=lambda x: x.get("cycles_open", 0), reverse=True):
            urgency = "🔴" if issue["cycles_open"] >= 3 else "🟡" if issue["cycles_open"] >= 1 else "⚪"
            print(f"  {urgency} {issue['id']} [{issue['severity']}] — {issue['description']} (open {issue['cycles_open']} cycles)")
    else:
        print("\n✅ No open issues — clean slate!")
    
    # Check for pending prompt patches
    pending = [p for p in a.get("prompt_patches", []) if p["status"] == "pending_review"]
    if pending:
        print(f"\n🔧 {len(pending)} prompt patch(es) pending Fred's review")

if __name__ == "__main__":
    main()
