#!/bin/bash
# check_docs_for_instructions.sh - Check WILMA-BAMBAM.md for new Active Items
#
# Pulls latest from git, extracts Active Items section, compares to last run.
# Logs when new instructions are detected.
#
# Designed for hourly cron. Cron survives reboot; no extra setup needed.
#
# Usage:
#   ./scripts/check_docs_for_instructions.sh
#   (typically run via cron; see install_docs_check_cron.sh)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
STATE_FILE="$PROJECT_ROOT/state/docs_check_last_hash"
DOC_FILE="$PROJECT_ROOT/WILMA-BAMBAM.md"

# Ensure state dir exists
mkdir -p "$(dirname "$STATE_FILE")"

# Log to output_base if available, else repo
get_log_dir() {
    local config="$PROJECT_ROOT/config/config.json"
    if [[ -f "$config" ]]; then
        local base=$(python3 -c "
import json
try:
    with open('$config') as f:
        data = json.load(f)
        print(data.get('output_base', ''))
except: pass
" 2>/dev/null)
        if [[ -n "$base" && -d "$base" ]]; then
            mkdir -p "$base/logs"
            echo "$base/logs"
            return
        fi
    fi
    mkdir -p "$PROJECT_ROOT/logs"
    echo "$PROJECT_ROOT/logs"
}

LOG_DIR="$(get_log_dir)"
LOG_FILE="$LOG_DIR/docs_check.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

# Pull latest (best-effort; don't fail if offline or no remote)
cd "$PROJECT_ROOT"
if git pull --no-rebase origin main >> "$LOG_FILE" 2>&1; then
    : # pulled
else
    log "WARN: git pull failed (offline or no remote); using local copy"
fi

# Extract Active Items section (from "## Active Items" to "## Completed" or next "---" after that)
extract_active_items() {
    awk '
        /^## Active Items/ { in_section=1; next }
        in_section && /^## / { exit }
        in_section { print }
    ' "$DOC_FILE" 2>/dev/null || true
}

CONTENT="$(extract_active_items)"
HASH="$(echo "$CONTENT" | sha256sum | cut -d' ' -f1)"

# Compare to last run
if [[ -f "$STATE_FILE" ]]; then
    OLD_HASH="$(cat "$STATE_FILE")"
    if [[ "$HASH" != "$OLD_HASH" ]]; then
        log "NEW INSTRUCTIONS DETECTED in WILMA-BAMBAM.md Active Items"
        log "Previous hash: $OLD_HASH"
        log "Current hash:  $HASH"
    fi
else
    log "First run; storing baseline hash"
fi

echo "$HASH" > "$STATE_FILE"
