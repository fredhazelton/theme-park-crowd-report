#!/usr/bin/env python3
"""
Generate projects.json for Mission Control v3 Projects tab.

These are curated project definitions — edit the PROJECTS list below
to add, remove, or update projects.

Usage:
    python scripts/generate_projects_json.py
"""

import json
import os
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════
# PROJECT DEFINITIONS — Edit these directly
# ═══════════════════════════════════════════════════════════════

PROJECTS = [
    {
        "id": "pipeline",
        "name": "Pipeline & Models",
        "description": "Wait time prediction pipeline — ETL, XGBoost training, conversion model, synthetic actuals, forecasting, WTI calculation. The core engine.",
        "status": "active",
        "priority": "high",
        "owner": "Wilma",
        "tasks_total": 10,
        "tasks_done": 7,
        "pct_complete": 70,
        "updated": "2026-03-05",
        "updated_by": "Wilma",
    },
    {
        "id": "discord-bot",
        "name": "Discord Bot (TPCR)",
        "description": "Theme Park Crowd Report Discord bot — /today, /now, /crowd, /best-day, /ask commands. Launched March 3. Live and serving users.",
        "status": "active",
        "priority": "high",
        "owner": "Bam-Bam",
        "tasks_total": 8,
        "tasks_done": 7,
        "pct_complete": 88,
        "updated": "2026-03-03",
        "updated_by": "Bam-Bam",
    },
    {
        "id": "mission-control",
        "name": "Mission Control v3",
        "description": "All-in-one project dashboard — pipeline status, model analytics, tasks kanban, calendar, projects. The nerve center.",
        "status": "active",
        "priority": "high",
        "owner": "Wilma",
        "tasks_total": 9,
        "tasks_done": 4,
        "pct_complete": 44,
        "updated": "2026-03-05",
        "updated_by": "Wilma",
    },
    {
        "id": "website",
        "name": "Website (hazeydata.ai)",
        "description": "Landing page, blog, infographics. Currently live with WTI article and bot screenshots. Needs fresh content and SEO.",
        "status": "active",
        "priority": "medium",
        "owner": "Fred",
        "tasks_total": 5,
        "tasks_done": 3,
        "pct_complete": 60,
        "updated": "2026-03-02",
        "updated_by": "Wilma",
    },
    {
        "id": "streaming",
        "name": "Streaming & Content",
        "description": "Twitch/YouTube streaming setup — overlays, alerts, chat integration, content calendar. Building the audience.",
        "status": "planning",
        "priority": "medium",
        "owner": "Fred",
        "tasks_total": 6,
        "tasks_done": 2,
        "pct_complete": 33,
        "updated": "2026-02-25",
        "updated_by": "Fred",
    },
    {
        "id": "business",
        "name": "Business & Revenue",
        "description": "Monetization strategy — /ask paywall, premium features, partnerships, Chantale's business roadmap. The path to $3-5M/yr.",
        "status": "planning",
        "priority": "medium",
        "owner": "Fred",
        "tasks_total": 4,
        "tasks_done": 0,
        "pct_complete": 0,
        "updated": "2026-03-02",
        "updated_by": "Wilma",
    },
]

# ═══════════════════════════════════════════════════════════════
# GENERATE
# ═══════════════════════════════════════════════════════════════

def main():
    # Compute summary counts
    status_counts = {}
    for p in PROJECTS:
        s = p["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    summary = {
        "total": len(PROJECTS),
        "active": status_counts.get("active", 0),
        "planning": status_counts.get("planning", 0),
        "paused": status_counts.get("paused", 0),
        "complete": status_counts.get("complete", 0),
    }

    output = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": summary,
        "projects": PROJECTS,
    }

    # Write to docs/analytics-data/projects.json
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    out_path = os.path.join(repo_root, "docs", "analytics-data", "projects.json")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Written {len(PROJECTS)} projects to {out_path}")
    print(f"   Summary: {summary['total']} total · {summary['active']} active · {summary['planning']} planning · {summary.get('paused', 0)} paused")


if __name__ == "__main__":
    main()
