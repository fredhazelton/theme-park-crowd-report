#!/bin/bash
# Pre-commit secret scanner for ops#27 compliance.
# Scans staged files AND crontab for hardcoded API keys/tokens.
# Exit 1 if secrets found (blocks commit when used as pre-commit hook).

set -euo pipefail

PATTERNS=(
    'BSAEB_'
    'sk-ant-api[0-9]'
    'fc-[a-f0-9]{20,}'
    'MTQ[0-9A-Za-z]'
    'BRAVE_API_KEY="[A-Z]'
    'ANTHROPIC_API_KEY="sk-'
    'FIRECRAWL_API_KEY="fc-'
    'DISCORD_BOT_TOKEN="M'
)

FOUND=0

# Scan git staged files
echo "Scanning staged files for secrets..."
for pattern in "${PATTERNS[@]}"; do
    matches=$(git diff --cached --diff-filter=ACMR -S "$pattern" --name-only 2>/dev/null || true)
    if [ -n "$matches" ]; then
        echo "  SECRET FOUND (pattern: $pattern) in:"
        echo "$matches" | sed 's/^/    /'
        FOUND=1
    fi
done

# Scan crontab
echo "Scanning crontab for inline tokens..."
if crontab -l 2>/dev/null | grep -qE 'DISCORD_BOT_TOKEN=M|sk-ant-|BSAEB_|fc-[a-f0-9]{20}'; then
    echo "  SECRET FOUND in crontab entries:"
    crontab -l 2>/dev/null | grep -nE 'DISCORD_BOT_TOKEN=M|sk-ant-|BSAEB_|fc-[a-f0-9]{20}' | sed 's/^/    /'
    FOUND=1
fi

if [ $FOUND -eq 1 ]; then
    echo ""
    echo "BLOCKED: Hardcoded secrets detected. Move to ~/.env and use os.environ.get()."
    exit 1
else
    echo "OK: No hardcoded secrets found."
    exit 0
fi
