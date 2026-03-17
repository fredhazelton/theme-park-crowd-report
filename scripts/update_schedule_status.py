#!/usr/bin/env python3
"""
Real-time schedule status updater for the pinned #briefing schedule thread.

Usage:
    python3 update_schedule_status.py <job-key> <status>
    python3 update_schedule_status.py --reset

Status values: ok, error, skip, running
Job keys match the schedule lines (see JOB_MAP below).

Examples:
    python3 update_schedule_status.py park-intel ok
    python3 update_schedule_status.py accuracy-report error
    python3 update_schedule_status.py --reset
"""

import os, sys, re, json, subprocess

# Config
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
if not BOT_TOKEN:
    env_path = os.path.expanduser("~/.clawdbot/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("DISCORD_BOT_TOKEN="):
                    BOT_TOKEN = line.strip().split("=", 1)[1]
                    break

THREAD_ID = "1483080808574222458"
MESSAGE_ID = "1483080808574222458"

STATUS_EMOJI = {
    "ok": "✅",
    "error": "❌",
    "skip": "⏭️",
    "running": "⏳",
}

# Map job keys to text patterns in the schedule message
JOB_MAP = {
    # Overnight work sessions
    "dino-work": "Dino (task management)",
    "arnold-work": "Arnold (news & intel)",
    "betty-work": "Betty (content)",
    "pebbles-work": "Pebbles (design)",
    "mrslate-work": "Mr. Slate (business)",
    "wilma-work": "Wilma (orchestration",
    # Morning
    "pipeline": "Pipeline v4",
    "park-intel": "Park Intel daily",
    "accuracy-report": "Accuracy report",
    "morning-tweet": "Morning WTI tweet",
    # Mid-morning
    "stale-tasks": "Stale task check",
    "bam-bam-am": "Bam-Bam AM sprint",
    "tokyo-blog": "Weekly blog",       # consolidated line
    "disneyland-blog": "Weekly blog",   # same line
    "orlando-blog": "Weekly blog",      # same line
    "blog-promo": "Blog promo tweet",
    # Midday
    "reddit-scout": "Reddit scout",
    "betty-midday": "Betty midday sprint",
    "competitor-watch": "Competitor watch",
    "bam-bam-midday": "Bam-Bam midday sprint",
    "pebbles-midday": "Pebbles midday sprint",
    "arnold-midday": "Arnold midday sprint",
    "dino-midday": "Dino midday sprint",
    "mrslate-midday": "Mr. Slate midday sprint",
    # Afternoon/Evening
    "afternoon-tweet": "Afternoon prediction tweet",
    "bam-bam-pm": "Bam-Bam PM sprint",
    "betty-pm": "Betty PM sprint",
    "pebbles-pm": "Pebbles PM sprint",
    "arnold-pm": "Arnold PM sprint",
    "dino-pm": "Dino PM sprint",
    "mrslate-pm": "Mr. Slate PM sprint",
    # Night
    "gazoo-review": "Gazoo review",
    "bam-bam-patrol": "Bam-Bam patrol",
}


def discord_get(endpoint):
    """GET from Discord API via curl."""
    result = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: Bot {BOT_TOKEN}", f"https://discord.com/api/v10{endpoint}"],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)


def discord_patch(endpoint, body):
    """PATCH to Discord API via curl."""
    result = subprocess.run(
        ["curl", "-s", "-X", "PATCH",
         "-H", f"Authorization: Bot {BOT_TOKEN}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(body),
         f"https://discord.com/api/v10{endpoint}"],
        capture_output=True, text=True
    )
    resp = json.loads(result.stdout)
    if "code" in resp and "message" in resp:
        print(f"Discord API error: {resp}", file=sys.stderr)
        sys.exit(1)
    return resp


def get_message():
    return discord_get(f"/channels/{THREAD_ID}/messages/{MESSAGE_ID}")


def edit_message(content):
    return discord_patch(f"/channels/{THREAD_ID}/messages/{MESSAGE_ID}", {"content": content})


def strip_status(line):
    """Remove any existing status emoji from a line."""
    return re.sub(r'\s*[✅❌⏭⏳️]\s*$', '', line)


def update_status(job_key, status):
    if job_key not in JOB_MAP:
        print(f"Unknown job key: {job_key}", file=sys.stderr)
        print(f"Valid keys: {', '.join(sorted(JOB_MAP.keys()))}", file=sys.stderr)
        sys.exit(1)

    if status not in STATUS_EMOJI:
        print(f"Unknown status: {status}. Use: {', '.join(STATUS_EMOJI.keys())}", file=sys.stderr)
        sys.exit(1)

    emoji = STATUS_EMOJI[status]
    pattern = JOB_MAP[job_key]

    msg = get_message()
    content = msg["content"]
    lines = content.split("\n")
    updated = False

    for i, line in enumerate(lines):
        if pattern in line:
            clean_line = strip_status(line)
            lines[i] = f"{clean_line} {emoji}"
            updated = True
            break

    if not updated:
        print(f"Warning: Could not find line matching '{pattern}' in schedule", file=sys.stderr)
        sys.exit(1)

    new_content = "\n".join(lines)
    edit_message(new_content)
    print(f"Updated: {job_key} → {emoji}")


def reset_all():
    """Remove all status emojis from the schedule."""
    msg = get_message()
    content = msg["content"]
    lines = content.split("\n")

    for i, line in enumerate(lines):
        lines[i] = strip_status(line)

    import datetime
    today = datetime.date.today().strftime("%Y-%m-%d")
    lines = [re.sub(r'Updated \d{4}-\d{2}-\d{2}', f'Updated {today}', l) for l in lines]

    new_content = "\n".join(lines)
    edit_message(new_content)
    print("Schedule reset — all statuses cleared")


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Error: DISCORD_BOT_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) == 2 and sys.argv[1] == "--reset":
        reset_all()
    elif len(sys.argv) == 3:
        update_status(sys.argv[1], sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)
