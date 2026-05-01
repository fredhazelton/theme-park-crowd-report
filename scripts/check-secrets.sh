#!/bin/bash
# Scan for hardcoded secrets in this repo and in the current users crontab.
# Exits 1 if any are found. Usage:
#   scripts/check-secrets.sh              # full scan of working tree + crontab
#   scripts/check-secrets.sh --staged     # scan only staged diffs (pre-commit hook mode)
#
# Update patterns below when a new secret class is introduced.

set -uo pipefail

MODE="${1:-full}"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
cd "$REPO_ROOT"

PATTERNS=(
    "sk-ant-api03-[A-Za-z0-9_-]{20,}"
    "BSA[A-Za-z0-9_-]{20,}"
    "fc-[a-f0-9]{32}"
    "MT[A-Za-z0-9_-]{22,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{20,}"
    "discord(app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+"
    "sk_live_[A-Za-z0-9]{24,}"
    "sk_test_[A-Za-z0-9]{24,}"
)

FILE_GLOBS=(--include="*.sh" --include="*.py" --include="*.js" --include="*.ts" --include="*.json" --include="*.yaml" --include="*.yml" --include="*.env" --include="*.conf" --include="*.toml")
EXCLUDE_DIRS=(--exclude-dir=".venv" --exclude-dir="venv" --exclude-dir="node_modules" --exclude-dir=".git" --exclude-dir="__pycache__" --exclude-dir="dist" --exclude-dir="build" --exclude-dir=".tox" --exclude-dir=".mypy_cache" --exclude-dir=".pytest_cache")

FOUND=0

scan_tree() {
    echo "Scanning working tree..."
    for p in "${PATTERNS[@]}"; do
        local m
        m=$(grep -rnE "$p" "${FILE_GLOBS[@]}" "${EXCLUDE_DIRS[@]}" . 2>/dev/null | grep -v "scripts/check-secrets.sh" | grep -v "check-secrets-hook" || true)
        if [ -n "$m" ]; then
            echo "FAIL pattern: $p"
            echo "$m" | head -25
            FOUND=1
        fi
    done
}

scan_crontab() {
    echo "Scanning crontab -l..."
    local cron
    if cron=$(crontab -l 2>/dev/null); then
        for p in "${PATTERNS[@]}"; do
            local m
            m=$(echo "$cron" | grep -nE "$p" || true)
            if [ -n "$m" ]; then
                echo "FAIL crontab pattern: $p"
                echo "$m"
                FOUND=1
            fi
        done
    else
        echo "(no crontab for $USER)"
    fi
}

scan_staged() {
    echo "Scanning staged diff..."
    local staged
    staged=$(git diff --cached --name-only --diff-filter=ACM -- "*.sh" "*.py" "*.js" "*.ts" "*.json" "*.yaml" "*.yml" "*.env" "*.conf" "*.toml" 2>/dev/null || true)
    if [ -z "$staged" ]; then
        echo "(no staged code/config files)"
        return
    fi
    local f p m
    for f in $staged; do
        [[ "$f" == *"check-secrets.sh" ]] && continue
        for p in "${PATTERNS[@]}"; do
            m=$(git show ":$f" 2>/dev/null | grep -nE "$p" || true)
            if [ -n "$m" ]; then
                echo "FAIL $f pattern: $p"
                echo "$m" | head -10
                FOUND=1
            fi
        done
    done
}

case "$MODE" in
    --staged|staged)
        scan_staged
        ;;
    *)
        scan_tree
        scan_crontab
        ;;
esac

if [ "$FOUND" -eq 1 ]; then
    echo
    echo "Hardcoded secrets detected. Move values to env vars (~/.bashrc or ~/.env) and reference via os.environ / \$VAR."
    exit 1
fi

echo "No hardcoded secrets detected."
exit 0
