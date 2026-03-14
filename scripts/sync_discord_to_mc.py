#!/usr/bin/env python3
"""
sync_discord_to_mc.py — Sync real Discord activity into Mission Control.

Reads recent messages from key Discord HQ channels via the Discord bot token
and writes docs/analytics-data/discord.json with live data.

Also regenerates docs/mission-control-content.json with fresh system data.

Usage:
    .venv/bin/python3 scripts/sync_discord_to_mc.py [--push]
    
    --push: auto git-add, commit, push to GitHub Pages after updating
"""

import json
import os
import sys
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: .venv/bin/pip install requests")
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHANNEL_MAP_PATH = Path.home() / "clawd-anthropic" / "discord-hq-channels.json"
DISCORD_JSON_OUT = PROJECT_ROOT / "docs" / "analytics-data" / "discord.json"
MC_CONTENT_JSON = PROJECT_ROOT / "docs" / "mission-control-content.json"

# Load bot token from ~/.env
ENV_FILE = Path.home() / ".env"

def load_env():
    """Load environment variables from ~/.env"""
    if not ENV_FILE.exists():
        return {}
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
    return env

env = load_env()
BOT_TOKEN = env.get("DISCORD_BOT_TOKEN", os.environ.get("DISCORD_BOT_TOKEN", ""))
GUILD_ID = "1479350342318690505"

# Key channels to pull recent messages from (most important ones)
KEY_CHANNELS = {
    "briefing": "1482227277508120576",
    "pipeline": "1479351574177513576",
    "alerts": "1479471928262529088",
    "fred-wilma": "1479351572386414675",
    "modeling": "1479351576232591491",
    "wilma": "1479351579185250436",
    "bam-bam": "1479351580347072675",
    "gazoo": "1479351587129262232",
}

# Channel metadata
CHANNEL_META = {
    "briefing": {"emoji": "📊", "purpose": "All automated reports — accuracy, park intel, competitor watch, MC status"},
    "fred-wilma": {"emoji": "🦴", "purpose": "Direct line between Fred and Wilma — private strategy and planning"},
    "pipeline": {"emoji": "🔧", "purpose": "Pipeline monitoring — ETL status, forecast runs, data quality checks"},
    "modeling": {"emoji": "🧪", "purpose": "Model experiments — XGBoost tuning, accuracy analysis, feature engineering"},
    "alerts": {"emoji": "🚨", "purpose": "System alerts — pipeline failures, accuracy drops, infrastructure issues"},
    "wilma": {"emoji": "🦕", "purpose": "Wilma's workspace — task execution, background processing, log output"},
    "bam-bam": {"emoji": "🏏", "purpose": "Bam-Bam's workspace — coding tasks, Discord bot development"},
    "barney": {"emoji": "🧠", "purpose": "Barney's workspace — research, analysis, deep thinking tasks"},
    "dino": {"emoji": "🦖", "purpose": "Dino's workspace — lightweight automation, fetch tasks, monitoring"},
    "pebbles": {"emoji": "🎀", "purpose": "Pebbles' workspace — creative content, social media, design tasks"},
    "betty": {"emoji": "✍️", "purpose": "Betty's workspace — writing, documentation, content editing"},
    "gazoo": {"emoji": "👽", "purpose": "Gazoo's workspace — nightly reviews, devil's advocate, R&D"},
    "morning-briefing": {"emoji": "☀️", "purpose": "Automated morning briefings — daily agenda, weather, key metrics"},
    "mr-slate": {"emoji": "🪨", "purpose": "Mr. Slate — CBO, executive oversight"},
}

# Category structure
CATEGORY_META = {
    "command-center": {
        "display_name": "Command Center", "emoji": "🏛️",
        "description": "Core HQ channels — daily ops, planning, and Fred-Wilma direct line",
        "channels": ["briefing", "fred-wilma"]
    },
    "operations": {
        "display_name": "Operations", "emoji": "⚙️",
        "description": "Pipeline monitoring, model training, and system alerts",
        "channels": ["pipeline", "modeling", "alerts"]
    },
    "agents": {
        "display_name": "Agents", "emoji": "🤖",
        "description": "Individual agent workspaces and morning briefings",
        "channels": ["wilma", "bam-bam", "barney", "dino", "pebbles", "betty", "gazoo", "morning-briefing", "mr-slate"]
    },
}


# ── Discord API ────────────────────────────────────────────────────

DISCORD_API = "https://discord.com/api/v10"
HEADERS = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}


def fetch_recent_messages(channel_id: str, limit: int = 5) -> list:
    """Fetch recent messages from a Discord channel."""
    if not BOT_TOKEN:
        return []
    try:
        url = f"{DISCORD_API}/channels/{channel_id}/messages?limit={limit}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"  ⚠️ Channel {channel_id}: HTTP {resp.status_code}")
            return []
    except Exception as e:
        print(f"  ⚠️ Channel {channel_id}: {e}")
        return []


def format_message(msg: dict) -> dict:
    """Format a Discord message for the MC JSON."""
    author = msg.get("author", {})
    content = msg.get("content", "")
    # Truncate long messages
    if len(content) > 200:
        content = content[:197] + "..."
    # Handle embeds
    if not content and msg.get("embeds"):
        embed = msg["embeds"][0]
        content = embed.get("title", embed.get("description", "[embed]"))
        if content and len(content) > 200:
            content = content[:197] + "..."
    
    return {
        "author": author.get("global_name") or author.get("username", "Unknown"),
        "author_id": author.get("id", ""),
        "is_bot": author.get("bot", False),
        "message": content or "[attachment/embed]",
        "timestamp": msg.get("timestamp", ""),
        "message_id": msg.get("id", ""),
    }


# ── Build Discord JSON ────────────────────────────────────────────

def build_discord_json() -> dict:
    """Build the full discord.json with live data."""
    print("\n📡 Fetching live Discord activity...")
    
    now = datetime.now(timezone.utc)
    
    # Load channel map for full channel list
    channel_map = {}
    if CHANNEL_MAP_PATH.exists():
        with open(CHANNEL_MAP_PATH) as f:
            channel_map = json.load(f)
    
    all_channels = channel_map.get("channels", {})
    all_categories = channel_map.get("categories", {})
    
    # Fetch recent messages from key channels
    recent_activity = []
    channel_last_active = {}  # channel_name → latest message timestamp
    
    for ch_name, ch_id in KEY_CHANNELS.items():
        print(f"  Fetching #{ch_name}...")
        messages = fetch_recent_messages(ch_id, limit=3)
        meta = CHANNEL_META.get(ch_name, {})
        
        for msg in messages:
            formatted = format_message(msg)
            activity_item = {
                "channel": ch_name,
                "channel_emoji": meta.get("emoji", "💬"),
                "channel_id": ch_id,
                "agent": formatted["author"],
                "is_bot": formatted["is_bot"],
                "message": formatted["message"],
                "timestamp": formatted["timestamp"],
                "message_id": formatted["message_id"],
                "url": f"https://discord.com/channels/{GUILD_ID}/{ch_id}/{formatted['message_id']}",
            }
            recent_activity.append(activity_item)
            
            # Track latest message per channel
            if ch_name not in channel_last_active or formatted["timestamp"] > channel_last_active[ch_name]:
                channel_last_active[ch_name] = formatted["timestamp"]
    
    # Sort by timestamp (newest first)
    recent_activity.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    
    # Keep only the most recent 20 messages across all channels
    recent_activity = recent_activity[:20]
    
    # Build categories with channels
    categories = []
    for cat_key, cat_info in CATEGORY_META.items():
        cat_channels = []
        for ch_name in cat_info["channels"]:
            ch_id = all_channels.get(ch_name, KEY_CHANNELS.get(ch_name, ""))
            if not ch_id:
                continue
            meta = CHANNEL_META.get(ch_name, {})
            cat_channels.append({
                "name": ch_name,
                "id": ch_id,
                "emoji": meta.get("emoji", "💬"),
                "purpose": meta.get("purpose", ""),
                "url": f"https://discord.com/channels/{GUILD_ID}/{ch_id}",
                "last_active": channel_last_active.get(ch_name, ""),
            })
        categories.append({
            "key": cat_key,
            "id": all_categories.get(cat_key, ""),
            "display_name": cat_info["display_name"],
            "emoji": cat_info["emoji"],
            "description": cat_info["description"],
            "channels": cat_channels,
        })
    
    # Server summary
    server = {
        "name": "Slate Rock & Gravel Co.",
        "id": GUILD_ID,
        "icon_status": "configured",
        "total_channels": len(all_channels),
        "total_categories": len(all_categories),
        "url": f"https://discord.com/channels/{GUILD_ID}",
    }
    
    # Summary stats
    now_utc = datetime.now(timezone.utc)
    messages_today = sum(
        1 for a in recent_activity 
        if a.get("timestamp", "")[:10] == now_utc.strftime("%Y-%m-%d")
    )
    active_channels_today = len(set(
        a["channel"] for a in recent_activity 
        if a.get("timestamp", "")[:10] == now_utc.strftime("%Y-%m-%d")
    ))
    
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "server": server,
        "categories": categories,
        "recent_activity": recent_activity,
        "stats": {
            "messages_shown": len(recent_activity),
            "active_channels_today": active_channels_today,
            "messages_today": messages_today,
        }
    }


# ── MC Content Refresh ─────────────────────────────────────────────

def refresh_mc_content():
    """Re-run the pipeline status JSON generator."""
    print("\n🔄 Refreshing Mission Control content JSON...")
    gen_script = PROJECT_ROOT / "scripts" / "generate_pipeline_status_json.py"
    if gen_script.exists():
        result = subprocess.run(
            [str(PROJECT_ROOT / ".venv" / "bin" / "python3"), str(gen_script)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print("  ✅ MC content JSON refreshed")
        else:
            print(f"  ⚠️ MC content refresh failed: {result.stderr[:200]}")
    else:
        print(f"  ⚠️ Script not found: {gen_script}")


# ── Git Push ───────────────────────────────────────────────────────

def git_push():
    """Commit and push updated JSON files to GitHub Pages."""
    print("\n📤 Pushing to GitHub Pages...")
    os.chdir(str(PROJECT_ROOT))
    
    files_to_add = [
        "docs/analytics-data/discord.json",
        "docs/mission-control-content.json",
        "docs/office-state.json",
        "docs/office-activity.json",
    ]
    
    # Only add files that exist
    existing = [f for f in files_to_add if (PROJECT_ROOT / f).exists()]
    
    if not existing:
        print("  No files to push")
        return
    
    subprocess.run(["git", "add"] + existing, capture_output=True)
    
    # Check if there are changes to commit
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if result.returncode == 0:
        print("  No changes to commit")
        return
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    subprocess.run(
        ["git", "commit", "-m", f"Sync Discord + MC data ({now_str})"],
        capture_output=True, text=True
    )
    
    result = subprocess.run(
        ["git", "push"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        print("  ✅ Pushed to GitHub")
    else:
        print(f"  ⚠️ Push failed: {result.stderr[:200]}")


# ── Main ───────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Discord ↔ Mission Control Sync")
    print("=" * 60)
    
    auto_push = "--push" in sys.argv
    
    if not BOT_TOKEN:
        print("❌ No DISCORD_BOT_TOKEN found in ~/.env")
        sys.exit(1)
    
    # 1. Build discord.json with live data
    discord_data = build_discord_json()
    
    DISCORD_JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(DISCORD_JSON_OUT, "w") as f:
        json.dump(discord_data, f, indent=2)
    print(f"\n✅ Written: {DISCORD_JSON_OUT.relative_to(PROJECT_ROOT)}")
    print(f"   {len(discord_data['recent_activity'])} recent messages")
    print(f"   {discord_data['stats']['active_channels_today']} active channels today")
    
    # 2. Refresh MC content JSON
    refresh_mc_content()
    
    # 3. Push to GitHub Pages
    if auto_push:
        git_push()
    else:
        print("\n💡 Run with --push to auto-push to GitHub Pages")
    
    print("\n✅ Sync complete!")


if __name__ == "__main__":
    main()
