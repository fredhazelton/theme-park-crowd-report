#!/usr/bin/env python3
"""
Generate social.json for Mission Control v3 Social tab.

Reads social account data and outputs structured JSON.
For now, this is relatively static — can be enhanced later
to pull live follower counts via APIs.

Usage:
    python scripts/generate_social_json.py
"""

import json
import os
from datetime import datetime, timezone

def main():
    now = datetime.now(timezone.utc)

    output = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "accounts": [
            {
                "platform": "twitter",
                "name": "Twitter / X",
                "handle": "@DisneyStatsWhiz",
                "status": "active",
                "url": "https://twitter.com/DisneyStatsWhiz",
                "stats": [
                    {"value": "2,872", "label": "Followers"},
                    {"value": "✓", "label": "Verified"},
                ],
            },
            {
                "platform": "youtube",
                "name": "YouTube",
                "handle": "@hazeydata-fred",
                "status": "active",
                "url": "https://youtube.com/@hazeydata-fred",
                "stats": [
                    {"value": "1", "label": "Videos"},
                    {"value": "720p", "label": "Quality"},
                ],
            },
            {
                "platform": "tiktok",
                "name": "TikTok",
                "handle": "@fredhazelton",
                "status": "active",
                "url": "https://tiktok.com/@fredhazelton",
                "stats": [
                    {"value": "185", "label": "Followers"},
                    {"value": "1K+", "label": "Views"},
                ],
            },
            {
                "platform": "twitch",
                "name": "Twitch",
                "handle": "hazeydata",
                "status": "setup",
                "url": "https://twitch.tv/hazeydata",
                "stats": [
                    {"value": "—", "label": "Followers"},
                    {"value": "Live", "label": "Overlay"},
                ],
            },
            {
                "platform": "reddit",
                "name": "Reddit",
                "handle": "r/WaltDisneyWorld",
                "status": "planned",
                "url": "https://reddit.com/r/WaltDisneyWorld",
                "stats": [
                    {"value": "—", "label": "Posts"},
                    {"value": "Target", "label": "Launch"},
                ],
            },
        ],
        "engagement_summary": {
            "total_followers": "3,057+",
            "total_platforms": "5",
            "active_platforms": "3",
            "primary_platform": "Twitter",
            "notes": "🦕 Alpha phase — organic growth only, no ad spend. Twitter is primary discovery channel with 2.8K+ followers from TouringPlans background.",
        },
    }

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    out_path = os.path.join(repo_root, "docs", "analytics-data", "social.json")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Written social.json to {out_path}")
    print(f"   {len(output['accounts'])} accounts")


if __name__ == "__main__":
    main()
