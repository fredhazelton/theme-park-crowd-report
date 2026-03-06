#!/usr/bin/env python3
"""
Generate ideas.json for Mission Control v3 Ideas tab.

Reads ideas from a source file and outputs structured JSON.
For now, ideas are maintained directly in the JSON file.

Usage:
    python scripts/generate_ideas_json.py
"""

import json
import os
from datetime import datetime, timezone

def main():
    now = datetime.now(timezone.utc)

    # Ideas list — edit here or in the output JSON directly
    ideas = [
        {
            "id": "idea-001",
            "title": "Real-time crowd heatmap overlay",
            "description": "Interactive park map with color-coded crowd density by land/area, updating in real-time from live wait data.",
            "category": "product",
            "status": "exploring",
            "owner": "Fred",
            "created": "2025-02-10",
        },
        {
            "id": "idea-002",
            "title": "\"Best Time to Visit\" content series",
            "description": "Weekly blog/video series analyzing optimal visit windows by park, using our forecast data as the backbone.",
            "category": "content",
            "status": "approved",
            "owner": "Pebbles",
            "created": "2025-02-14",
        },
        {
            "id": "idea-003",
            "title": "Stripe subscription tiers post-alpha",
            "description": "Free tier with basic forecasts, Pro tier ($5/mo) with entity-level predictions, alerts, and API access.",
            "category": "business",
            "status": "exploring",
            "owner": "Fred",
            "created": "2025-02-13",
        },
        {
            "id": "idea-004",
            "title": "Discord bot /plan command",
            "description": "Users input date + park, bot returns an optimized ride order based on predicted waits throughout the day.",
            "category": "product",
            "status": "exploring",
            "owner": "Bam-Bam",
            "created": "2025-02-18",
        },
        {
            "id": "idea-005",
            "title": "Automated Reddit posting for launches",
            "description": "Bot-assisted posting to r/WaltDisneyWorld, r/DisneyPlanning, r/UniversalOrlando with crowd forecasts.",
            "category": "content",
            "status": "new",
            "owner": "Wilma",
            "created": "2025-02-20",
        },
        {
            "id": "idea-006",
            "title": "ML model ensemble (XGBoost + LSTM)",
            "description": "Combine current XGBoost predictions with an LSTM time-series model for improved accuracy on high-variance days.",
            "category": "technical",
            "status": "new",
            "owner": "Fred",
            "created": "2025-02-22",
        },
        {
            "id": "idea-007",
            "title": "Park comparison dashboard",
            "description": "Side-by-side view comparing crowd levels across all 6 parks for a given date — helps users pick the least crowded park.",
            "category": "product",
            "status": "approved",
            "owner": "Fred",
            "created": "2025-02-08",
        },
        {
            "id": "idea-008",
            "title": "Affiliate links for Disney merch/tickets",
            "description": "Add Disney ticket affiliate links to forecast pages for passive revenue.",
            "category": "business",
            "status": "rejected",
            "owner": "Fred",
            "created": "2025-02-15",
        },
        {
            "id": "idea-009",
            "title": "Wait time alerts via push notification",
            "description": "Users subscribe to alerts when their favorite ride drops below a threshold — requires mobile PWA or native app.",
            "category": "product",
            "status": "new",
            "owner": "Bam-Bam",
            "created": "2025-03-01",
        },
        {
            "id": "idea-010",
            "title": "TikTok \"Did You Know\" shorts series",
            "description": "15-second facts about theme park wait patterns — \"Did you know Space Mountain is shortest at 2pm on Tuesdays?\"",
            "category": "content",
            "status": "exploring",
            "owner": "Pebbles",
            "created": "2025-02-25",
        },
        {
            "id": "idea-011",
            "title": "Backfill historical accuracy scoring",
            "description": "Run accuracy evaluation on all historical forecast data to build a comprehensive accuracy timeline from day 1.",
            "category": "technical",
            "status": "new",
            "owner": "Wilma",
            "created": "2025-03-05",
        },
        {
            "id": "idea-012",
            "title": "Sponsor partnerships with travel blogs",
            "description": "Partner with Disney travel bloggers for cross-promotion — they embed our widgets, we feature their content.",
            "category": "business",
            "status": "new",
            "owner": "Fred",
            "created": "2025-03-10",
        },
    ]

    # Compute summary
    status_counts = {"new": 0, "exploring": 0, "approved": 0, "rejected": 0}
    for idea in ideas:
        s = idea.get("status", "new")
        if s in status_counts:
            status_counts[s] += 1

    output = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "total": len(ideas),
            **status_counts,
        },
        "ideas": ideas,
    }

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    out_path = os.path.join(repo_root, "docs", "analytics-data", "ideas.json")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Written ideas.json to {out_path}")
    print(f"   {len(ideas)} ideas — {status_counts['new']} new, {status_counts['exploring']} exploring, {status_counts['approved']} approved, {status_counts['rejected']} rejected")


if __name__ == "__main__":
    main()
