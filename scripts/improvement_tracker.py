#!/usr/bin/env python3
"""
Improvement Tracker — The recursion engine's memory.

Used by:
- Gazoo: to raise issues and log scores after reviews
- Wilma: to detect patterns and propose prompt patches
- Fred: to review and approve prompt modifications

Usage:
    # Gazoo raises an issue
    python3 improvement_tracker.py raise <agent> <severity> "<description>"
    
    # Gazoo logs a daily score
    python3 improvement_tracker.py score <agent> <score>
    
    # Gazoo marks an issue as fixed
    python3 improvement_tracker.py fix <issue_id>
    
    # Wilma checks for recurring patterns (3+ cycles unfixed)
    python3 improvement_tracker.py patterns
    
    # Wilma proposes a prompt patch
    python3 improvement_tracker.py propose-patch <agent> "<description>" "<patch_text>"
    
    # Show agent status / leaderboard
    python3 improvement_tracker.py status [agent]
    python3 improvement_tracker.py leaderboard
    
    # Increment cycle counter (run at start of each Gazoo review)
    python3 improvement_tracker.py new-cycle
"""

import json, sys, os
from datetime import datetime, timezone

LEDGER_PATH = os.path.expanduser("~/clawd/data/improvement_ledger.json")


def load():
    with open(LEDGER_PATH) as f:
        return json.load(f)


def save(data):
    with open(LEDGER_PATH, "w") as f:
        json.dump(data, f, indent=2)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def gen_issue_id(agent, data):
    """Generate issue ID like D-001, A-002, etc."""
    prefix = {
        "dino": "D", "arnold": "A", "betty": "B", "pebbles": "P",
        "mr-slate": "S", "bam-bam": "BB", "gazoo": "G", "wilma": "W"
    }.get(agent, "X")
    existing = data["agents"][agent]["issues"]
    nums = [int(i["id"].split("-")[-1]) for i in existing if "-" in i["id"]]
    next_num = max(nums, default=0) + 1
    return f"{prefix}-{next_num:03d}"


def cmd_raise(agent, severity, description):
    """Raise a new issue for an agent."""
    data = load()
    if agent not in data["agents"]:
        print(f"Unknown agent: {agent}", file=sys.stderr)
        sys.exit(1)
    
    issue_id = gen_issue_id(agent, data)
    issue = {
        "id": issue_id,
        "raised": now_iso(),
        "description": description,
        "severity": severity,  # low, medium, high, critical
        "status": "open",
        "cycles_open": 0,
        "notes": []
    }
    data["agents"][agent]["issues"].append(issue)
    data["agents"][agent]["stats"]["total_issues"] += 1
    save(data)
    print(f"Raised {issue_id}: [{severity}] {description}")


def cmd_score(agent, score):
    """Log a daily score for an agent."""
    data = load()
    if agent not in data["agents"]:
        print(f"Unknown agent: {agent}", file=sys.stderr)
        sys.exit(1)
    
    score = int(score)
    scores = data["agents"][agent]["scores"]
    scores.append({"date": now_iso(), "score": score})
    
    # Keep last 14 days
    if len(scores) > 14:
        scores = scores[-14:]
    data["agents"][agent]["scores"] = scores
    
    # Calculate trend
    if len(scores) >= 3:
        recent = [s["score"] for s in scores[-3:]]
        older = [s["score"] for s in scores[:-3]] if len(scores) > 3 else recent
        avg_recent = sum(recent) / len(recent)
        avg_older = sum(older) / len(older)
        if avg_recent > avg_older + 0.5:
            data["agents"][agent]["trend"] = "improving"
        elif avg_recent < avg_older - 0.5:
            data["agents"][agent]["trend"] = "declining"
        else:
            data["agents"][agent]["trend"] = "flat"
    
    save(data)
    trend = data["agents"][agent]["trend"]
    trend_emoji = {"improving": "📈", "declining": "📉", "flat": "➡️", "new": "🆕"}
    print(f"{agent}: {score}/10 {trend_emoji.get(trend, '')} ({trend})")


def cmd_fix(issue_id):
    """Mark an issue as fixed."""
    data = load()
    for agent_name, agent_data in data["agents"].items():
        for issue in agent_data["issues"]:
            if issue["id"] == issue_id:
                issue["status"] = "fixed"
                issue["fixed_on"] = now_iso()
                agent_data["stats"]["fixed"] += 1
                
                # Update avg cycles to fix
                fixed_issues = [i for i in agent_data["issues"] if i["status"] == "fixed"]
                if fixed_issues:
                    avg = sum(i.get("cycles_open", 0) for i in fixed_issues) / len(fixed_issues)
                    agent_data["stats"]["avg_cycles_to_fix"] = round(avg, 1)
                
                save(data)
                print(f"Fixed {issue_id} (was open {issue['cycles_open']} cycles)")
                return
    
    print(f"Issue {issue_id} not found", file=sys.stderr)
    sys.exit(1)


def cmd_patterns():
    """Find recurring issues (open 3+ cycles) — prompt patch candidates."""
    data = load()
    patches_needed = []
    
    for agent_name, agent_data in data["agents"].items():
        for issue in agent_data["issues"]:
            if issue["status"] == "open" and issue.get("cycles_open", 0) >= 3:
                patches_needed.append({
                    "agent": agent_name,
                    "issue": issue["id"],
                    "description": issue["description"],
                    "cycles_open": issue["cycles_open"],
                    "severity": issue["severity"]
                })
    
    if not patches_needed:
        print("No recurring patterns found — all issues either fixed or < 3 cycles old.")
        return
    
    print(f"🔄 {len(patches_needed)} recurring issue(s) — prompt patches recommended:\n")
    for p in sorted(patches_needed, key=lambda x: x["cycles_open"], reverse=True):
        print(f"  [{p['severity'].upper()}] {p['issue']} ({p['agent']}) — {p['cycles_open']} cycles")
        print(f"    {p['description']}")
        print()


def cmd_propose_patch(agent, description, patch_text):
    """Propose a prompt patch for an agent."""
    data = load()
    if agent not in data["agents"]:
        print(f"Unknown agent: {agent}", file=sys.stderr)
        sys.exit(1)
    
    patch = {
        "proposed": now_iso(),
        "description": description,
        "patch_text": patch_text,
        "status": "pending_review",  # pending_review → approved → applied | rejected
        "approved_by": None,
        "applied_on": None
    }
    data["agents"][agent]["prompt_patches"].append(patch)
    data["system"]["prompt_patches_pending_review"] += 1
    save(data)
    print(f"Prompt patch proposed for {agent}: {description}")
    print(f"  Status: pending_review (needs Fred's approval)")


def cmd_new_cycle():
    """Increment cycle counter and age all open issues."""
    data = load()
    data["system"]["total_cycles"] += 1
    cycle = data["system"]["total_cycles"]
    
    aged = 0
    for agent_data in data["agents"].values():
        for issue in agent_data["issues"]:
            if issue["status"] == "open":
                issue["cycles_open"] = issue.get("cycles_open", 0) + 1
                aged += 1
    
    save(data)
    print(f"Cycle {cycle} started. {aged} open issues aged.")


def cmd_status(agent=None):
    """Show agent status."""
    data = load()
    
    if agent:
        if agent not in data["agents"]:
            print(f"Unknown agent: {agent}", file=sys.stderr)
            sys.exit(1)
        agents = {agent: data["agents"][agent]}
    else:
        agents = data["agents"]
    
    for name, a in agents.items():
        open_issues = [i for i in a["issues"] if i["status"] == "open"]
        scores = [s["score"] for s in a["scores"]]
        avg_score = sum(scores) / len(scores) if scores else None
        trend_emoji = {"improving": "📈", "declining": "📉", "flat": "➡️", "new": "🆕"}
        
        print(f"{'─' * 40}")
        print(f"  {name.upper()} — {a['role']}")
        print(f"  Trend: {trend_emoji.get(a['trend'], '')} {a['trend']}")
        print(f"  Avg score: {avg_score:.1f}/10" if avg_score else "  Avg score: —")
        print(f"  Open issues: {len(open_issues)}")
        print(f"  Total fixed: {a['stats']['fixed']}")
        if a['stats']['avg_cycles_to_fix']:
            print(f"  Avg cycles to fix: {a['stats']['avg_cycles_to_fix']}")
        
        for issue in open_issues:
            print(f"    [{issue['severity']}] {issue['id']}: {issue['description']} ({issue['cycles_open']} cycles)")


def cmd_leaderboard():
    """Show improvement velocity leaderboard."""
    data = load()
    board = []
    
    for name, a in data["agents"].items():
        scores = [s["score"] for s in a["scores"]]
        if len(scores) < 2:
            velocity = 0
        else:
            # Improvement velocity = recent avg - first avg
            mid = len(scores) // 2
            first_half = sum(scores[:mid]) / mid
            second_half = sum(scores[mid:]) / (len(scores) - mid)
            velocity = second_half - first_half
        
        avg = sum(scores) / len(scores) if scores else 0
        board.append({
            "agent": name,
            "avg_score": round(avg, 1),
            "velocity": round(velocity, 1),
            "trend": a["trend"],
            "open_issues": len([i for i in a["issues"] if i["status"] == "open"])
        })
    
    board.sort(key=lambda x: (x["velocity"], x["avg_score"]), reverse=True)
    
    trend_emoji = {"improving": "📈", "declining": "📉", "flat": "➡️", "new": "🆕"}
    
    print("🏆 IMPROVEMENT VELOCITY LEADERBOARD")
    print("=" * 50)
    for i, entry in enumerate(board, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f" {i}.")
        trend = trend_emoji.get(entry["trend"], "")
        print(f"  {medal} {entry['agent'].upper():12s}  avg: {entry['avg_score']:4.1f}  velocity: {entry['velocity']:+.1f}  {trend}  ({entry['open_issues']} open)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "raise" and len(sys.argv) == 5:
        cmd_raise(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "score" and len(sys.argv) == 4:
        cmd_score(sys.argv[2], sys.argv[3])
    elif cmd == "fix" and len(sys.argv) == 3:
        cmd_fix(sys.argv[2])
    elif cmd == "patterns":
        cmd_patterns()
    elif cmd == "propose-patch" and len(sys.argv) == 5:
        cmd_propose_patch(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "status":
        cmd_status(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "leaderboard":
        cmd_leaderboard()
    elif cmd == "new-cycle":
        cmd_new_cycle()
    else:
        print(__doc__)
        sys.exit(1)
