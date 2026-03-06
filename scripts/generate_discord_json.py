#!/usr/bin/env python3
"""
Generate discord.json for Mission Control v3 Discord tab.

Reads the Discord HQ channel map and produces a structured JSON
with server info, categories, channels, and placeholder activity.

Usage:
    python scripts/generate_discord_json.py
"""

import json
import os
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

CHANNEL_MAP_PATH = os.path.expanduser("~/clawd-anthropic/discord-hq-channels.json")

# Channel → category mapping
CHANNEL_CATEGORIES = {
    # Command Center
    "mission-control": "command-center",
    "daily-digest": "command-center",
    "fred-wilma": "command-center",
    # Operations
    "pipeline": "operations",
    "modeling": "operations",
    "alerts": "operations",
    # Agents
    "wilma": "agents",
    "bam-bam": "agents",
    "barney": "agents",
    "dino": "agents",
    "pebbles": "agents",
    "betty": "agents",
    "gazoo": "agents",
    "morning-briefing": "agents",
    # Automated Feeds
    "competitor-watch": "automated-feeds",
    "park-intel": "automated-feeds",
    "social-pulse": "automated-feeds",
    # Projects
    "website": "projects",
    "streaming": "projects",
    "discord-bot": "projects",
    "business": "projects",
    # Creative
    "ideas": "creative",
    "content-ideas": "creative",
    "content-review": "creative",
}

# Category metadata (display names, emojis, descriptions)
CATEGORY_META = {
    "command-center": {
        "display_name": "Command Center",
        "emoji": "🏛️",
        "description": "Core HQ channels — daily ops, planning, and Fred-Wilma direct line",
    },
    "operations": {
        "display_name": "Operations",
        "emoji": "⚙️",
        "description": "Pipeline monitoring, model training, and system alerts",
    },
    "agents": {
        "display_name": "Agents",
        "emoji": "🤖",
        "description": "Individual agent workspaces and morning briefings",
    },
    "automated-feeds": {
        "display_name": "Automated Feeds",
        "emoji": "📡",
        "description": "Auto-populated intel channels — competitor data, park updates, social monitoring",
    },
    "projects": {
        "display_name": "Projects",
        "emoji": "📂",
        "description": "Active project channels — website, streaming, Discord bot, business",
    },
    "creative": {
        "display_name": "Creative",
        "emoji": "💡",
        "description": "Idea brainstorming, content planning, and review workflows",
    },
}

# Channel metadata (descriptions, emojis)
CHANNEL_META = {
    "mission-control": {
        "emoji": "🎯",
        "purpose": "Central command — status updates, key decisions, daily priorities",
    },
    "daily-digest": {
        "emoji": "📰",
        "purpose": "Automated daily summary — pipeline health, accuracy metrics, task progress",
    },
    "fred-wilma": {
        "emoji": "🦴",
        "purpose": "Direct line between Fred and Wilma — private strategy and planning",
    },
    "pipeline": {
        "emoji": "🔧",
        "purpose": "Pipeline monitoring — ETL status, forecast runs, data quality checks",
    },
    "modeling": {
        "emoji": "🧪",
        "purpose": "Model experiments — XGBoost tuning, accuracy analysis, feature engineering",
    },
    "alerts": {
        "emoji": "🚨",
        "purpose": "System alerts — pipeline failures, accuracy drops, infrastructure issues",
    },
    "wilma": {
        "emoji": "🦕",
        "purpose": "Wilma's workspace — task execution, background processing, log output",
    },
    "bam-bam": {
        "emoji": "🏏",
        "purpose": "Bam-Bam's workspace — coding tasks, Discord bot development",
    },
    "barney": {
        "emoji": "🧠",
        "purpose": "Barney's workspace — research, analysis, deep thinking tasks",
    },
    "dino": {
        "emoji": "🦖",
        "purpose": "Dino's workspace — lightweight automation, fetch tasks, monitoring",
    },
    "pebbles": {
        "emoji": "🎀",
        "purpose": "Pebbles' workspace — creative content, social media, design tasks",
    },
    "betty": {
        "emoji": "✍️",
        "purpose": "Betty's workspace — writing, documentation, content editing",
    },
    "gazoo": {
        "emoji": "👽",
        "purpose": "Gazoo's workspace — experimental features, moonshot ideas, R&D",
    },
    "morning-briefing": {
        "emoji": "☀️",
        "purpose": "Automated morning briefings — daily agenda, weather, key metrics",
    },
    "competitor-watch": {
        "emoji": "👁️",
        "purpose": "Competitor monitoring — Touring Plans, Thrill Data, market moves",
    },
    "park-intel": {
        "emoji": "🎢",
        "purpose": "Park intelligence — closures, events, crowd patterns, ride updates",
    },
    "social-pulse": {
        "emoji": "📊",
        "purpose": "Social media monitoring — mentions, sentiment, trending topics",
    },
    "website": {
        "emoji": "🌐",
        "purpose": "Website project — hazeydata.ai updates, SEO, content publishing",
    },
    "streaming": {
        "emoji": "🎥",
        "purpose": "Streaming project — Twitch/YouTube overlays, schedule, content",
    },
    "discord-bot": {
        "emoji": "🤖",
        "purpose": "TPCR Discord bot — development, testing, user feedback",
    },
    "business": {
        "emoji": "💰",
        "purpose": "Business strategy — monetization, partnerships, revenue planning",
    },
    "ideas": {
        "emoji": "💡",
        "purpose": "Idea dump — raw ideas, shower thoughts, quick captures",
    },
    "content-ideas": {
        "emoji": "📝",
        "purpose": "Content planning — blog posts, videos, infographics pipeline",
    },
    "content-review": {
        "emoji": "👀",
        "purpose": "Content review — drafts ready for feedback, approval workflow",
    },
}

# Placeholder recent activity
RECENT_ACTIVITY = [
    {
        "channel": "mission-control",
        "agent": "Wilma",
        "message": "Pipeline run complete — all 6 parks updated",
        "timestamp": "placeholder",
    },
    {
        "channel": "daily-digest",
        "agent": "Wilma",
        "message": "Daily digest posted — MAE 11.2, 47 entities evaluated",
        "timestamp": "placeholder",
    },
    {
        "channel": "alerts",
        "agent": "System",
        "message": "All systems nominal — no alerts in last 24h",
        "timestamp": "placeholder",
    },
    {
        "channel": "pipeline",
        "agent": "Wilma",
        "message": "Forecast generation completed for tomorrow",
        "timestamp": "placeholder",
    },
    {
        "channel": "morning-briefing",
        "agent": "Wilma",
        "message": "Morning briefing delivered — 3 tasks scheduled today",
        "timestamp": "placeholder",
    },
]


# ═══════════════════════════════════════════════════════════════
# GENERATE
# ═══════════════════════════════════════════════════════════════

def main():
    # Load channel map
    with open(CHANNEL_MAP_PATH) as f:
        channel_map = json.load(f)

    guild_id = channel_map["guild_id"]
    guild_name = channel_map["guild_name"]
    categories_raw = channel_map["categories"]
    channels_raw = channel_map["channels"]

    # Build categories list
    categories = []
    for cat_key, cat_id in categories_raw.items():
        meta = CATEGORY_META.get(cat_key, {})
        cat_channels = []
        for ch_name, ch_id in channels_raw.items():
            if CHANNEL_CATEGORIES.get(ch_name) == cat_key:
                ch_meta = CHANNEL_META.get(ch_name, {})
                cat_channels.append({
                    "name": ch_name,
                    "id": ch_id,
                    "emoji": ch_meta.get("emoji", "💬"),
                    "purpose": ch_meta.get("purpose", ""),
                    "url": f"https://discord.com/channels/{guild_id}/{ch_id}",
                })
        categories.append({
            "key": cat_key,
            "id": cat_id,
            "display_name": meta.get("display_name", cat_key.replace("-", " ").title()),
            "emoji": meta.get("emoji", "📁"),
            "description": meta.get("description", ""),
            "channels": cat_channels,
        })

    # Server summary
    server = {
        "name": guild_name,
        "id": guild_id,
        "icon_status": "configured",
        "total_channels": len(channels_raw),
        "total_categories": len(categories_raw),
        "url": f"https://discord.com/channels/{guild_id}",
    }

    # Recent activity with timestamps
    now = datetime.now(timezone.utc)
    activity = []
    for item in RECENT_ACTIVITY:
        ch_id = channels_raw.get(item["channel"], "")
        ch_meta = CHANNEL_META.get(item["channel"], {})
        activity.append({
            "channel": item["channel"],
            "channel_emoji": ch_meta.get("emoji", "💬"),
            "channel_id": ch_id,
            "agent": item["agent"],
            "message": item["message"],
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "url": f"https://discord.com/channels/{guild_id}/{ch_id}" if ch_id else "",
        })

    output = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "server": server,
        "categories": categories,
        "recent_activity": activity,
    }

    # Write output
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    out_path = os.path.join(repo_root, "docs", "analytics-data", "discord.json")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Written discord.json to {out_path}")
    print(f"   Server: {guild_name} ({guild_id})")
    print(f"   {len(categories)} categories · {len(channels_raw)} channels")
    print(f"   {len(activity)} recent activity items")


if __name__ == "__main__":
    main()
