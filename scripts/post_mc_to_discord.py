#!/usr/bin/env python3
"""
post_mc_to_discord.py — Post Mission Control status summary to Discord #mission-control.

Reads the current mission-control-content.json and posts a formatted embed
to the Discord #mission-control channel. Designed to run periodically.

Usage:
    .venv/bin/python3 scripts/post_mc_to_discord.py [--force]
    
    --force: post even if nothing changed since last post
"""

import json
import os
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not installed")
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MC_CONTENT_JSON = PROJECT_ROOT / "docs" / "mission-control-content.json"
STATE_FILE = PROJECT_ROOT / "docs" / "analytics-data" / ".mc_discord_state.json"

ENV_FILE = Path.home() / ".env"
DISCORD_API = "https://discord.com/api/v10"
MC_CHANNEL_ID = "1479351570121621569"  # #mission-control

def load_env():
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
HEADERS = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def content_hash(data: dict) -> str:
    """Hash the key fields to detect changes."""
    key_fields = {
        "pipeline": data.get("pipeline_status", {}),
        "accuracy": data.get("accuracy", {}),
        "tasks": [t["task"] for t in data.get("todays_focus", [])],
    }
    return hashlib.md5(json.dumps(key_fields, sort_keys=True).encode()).hexdigest()[:12]


def build_embed(data: dict) -> dict:
    """Build a Discord embed from MC content."""
    now = datetime.now(timezone.utc)
    
    # Pipeline status line
    pipeline = data.get("pipeline_status", {})
    pipeline_lines = []
    status_emoji = {"done": "✅", "running": "🔄", "pending": "⏳", "error": "❌"}
    for key, info in pipeline.items():
        emoji = status_emoji.get(info.get("status", ""), "❓")
        label = info.get("label", key)
        detail = info.get("detail", "")
        pipeline_lines.append(f"{emoji} **{label}** — {detail}" if detail else f"{emoji} **{label}**")
    
    # Accuracy
    acc = data.get("accuracy", {})
    acc_text = (
        f"Entity MAE: **{acc.get('entity_mae', 'N/A')}** · "
        f"WTI MAE: **{acc.get('wti_mae', 'N/A')}** · "
        f"Days: **{acc.get('days_evaluated', 0)}**"
    )
    
    # Tasks
    tasks = data.get("todays_focus", [])
    task_lines = []
    for t in tasks[:5]:
        task_lines.append(f"{t.get('status_text', '📝')} {t.get('task', '')}")
    
    # Infrastructure
    infra = data.get("infrastructure", {})
    services = infra.get("services", [])
    active_svcs = sum(1 for s in services if s.get("status") == "active")
    disk_main = infra.get("disk_main_pct", 0)
    disk_data = infra.get("disk_data_pct", 0)
    
    # Ask analytics
    ask = data.get("ask_analytics", {})
    ask_text = f"Questions: **{ask.get('total_questions', 0)}** · Users: **{ask.get('unique_users', 0)}** · 👍 {ask.get('thumbs_up', 0)} / 👎 {ask.get('thumbs_down', 0)}"
    
    embed = {
        "title": "🦴 Mission Control Status",
        "url": "https://hazeydata.github.io/theme-park-crowd-report/mission-control-v3.html",
        "color": 0x4a90a4,  # Accent cyan
        "fields": [
            {
                "name": "🔧 Pipeline",
                "value": "\n".join(pipeline_lines) or "No data",
                "inline": False,
            },
            {
                "name": "📊 Accuracy",
                "value": acc_text,
                "inline": False,
            },
            {
                "name": "🎯 Today's Priorities",
                "value": "\n".join(task_lines) or "No active tasks",
                "inline": False,
            },
            {
                "name": "🖥️ Infrastructure",
                "value": f"Services: **{active_svcs}/{len(services)}** active · Disk: main **{disk_main}%** · data **{disk_data}%**",
                "inline": False,
            },
            {
                "name": "🤖 /ask Bot",
                "value": ask_text,
                "inline": False,
            },
        ],
        "footer": {"text": f"Auto-synced from Mission Control"},
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    
    return embed


def send_embed(embed: dict) -> bool:
    """Send an embed to #mission-control."""
    url = f"{DISCORD_API}/channels/{MC_CHANNEL_ID}/messages"
    payload = {"embeds": [embed]}
    
    try:
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=10)
        if resp.status_code in (200, 201):
            msg_data = resp.json()
            print(f"  ✅ Posted to #mission-control (msg: {msg_data.get('id', '?')})")
            return True
        else:
            print(f"  ❌ Failed: HTTP {resp.status_code} — {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def main():
    print("=" * 60)
    print("Mission Control → Discord Sync")
    print("=" * 60)
    
    force = "--force" in sys.argv
    
    if not BOT_TOKEN:
        print("❌ No DISCORD_BOT_TOKEN found")
        sys.exit(1)
    
    if not MC_CONTENT_JSON.exists():
        print(f"❌ MC content not found: {MC_CONTENT_JSON}")
        sys.exit(1)
    
    with open(MC_CONTENT_JSON) as f:
        data = json.load(f)
    
    # Check if content changed
    current_hash = content_hash(data)
    state = load_state()
    last_hash = state.get("last_hash", "")
    
    if current_hash == last_hash and not force:
        print("  No changes since last post — skipping (use --force to override)")
        return
    
    print(f"  Content hash: {current_hash} (was: {last_hash or 'never'})")
    
    # Build and send embed
    embed = build_embed(data)
    if send_embed(embed):
        state["last_hash"] = current_hash
        state["last_posted"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
    
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
