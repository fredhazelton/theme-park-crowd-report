#!/usr/bin/env bash
# discord_forum_post.sh — Create a Discord forum thread with message and tags
# Usage: discord_forum_post.sh <channel_id> <thread_name> <message_content> [tag_id1,tag_id2,...]
#
# Example:
#   discord_forum_post.sh 1482227277508120576 "📊 Test Report" "Report body here" "1482254047120719921,1482254047636361298"
#
# Requires: DISCORD_BOT_TOKEN env var or will read from crontab

set -euo pipefail

CHANNEL_ID="${1:?Usage: $0 <channel_id> <thread_name> <message_content> [tag_ids]}"
THREAD_NAME="${2:?Thread name required}"
MESSAGE_CONTENT="${3:?Message content required}"
TAG_IDS="${4:-}"

# Get token from env or crontab
if [ -z "${DISCORD_BOT_TOKEN:-}" ]; then
  DISCORD_BOT_TOKEN=$(crontab -l 2>/dev/null | grep -oP 'DISCORD_BOT_TOKEN=\K[^ ]+' | head -1)
fi

if [ -z "${DISCORD_BOT_TOKEN:-}" ]; then
  echo "ERROR: DISCORD_BOT_TOKEN not found" >&2
  exit 1
fi

# Build applied_tags JSON array
TAGS_JSON="[]"
if [ -n "$TAG_IDS" ]; then
  TAGS_JSON=$(echo "$TAG_IDS" | tr ',' '\n' | jq -R . | jq -s .)
fi

# Build the JSON payload
PAYLOAD=$(jq -n \
  --arg name "$THREAD_NAME" \
  --arg content "$MESSAGE_CONTENT" \
  --argjson tags "$TAGS_JSON" \
  '{
    name: $name,
    message: { content: $content },
    applied_tags: $tags
  }')

# POST to Discord API
RESPONSE=$(curl -s -w "\n%{http_code}" \
  -X POST \
  -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "https://discord.com/api/v10/channels/${CHANNEL_ID}/threads")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
  THREAD_ID=$(echo "$BODY" | jq -r '.id')
  echo "OK thread_id=$THREAD_ID"
  echo "$BODY" | jq .
else
  echo "ERROR: HTTP $HTTP_CODE" >&2
  echo "$BODY" | jq . 2>/dev/null || echo "$BODY" >&2
  exit 1
fi
