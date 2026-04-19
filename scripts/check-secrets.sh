#!/bin/bash
# Security check: scan for hardcoded API keys in committed files
# Exit with error if any hardcoded secrets are found

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "🔍 Scanning for hardcoded API keys..."

# Patterns to search for
PATTERNS=(
    'sk-ant-[a-zA-Z0-9_-]+'
    'BRAVE_API_KEY="[^"]*"'
    'FIRECRAWL_API_KEY="[^"]*"' 
    'ANTHROPIC_API_KEY="[^"]*"'
)

FOUND_SECRETS=0

for pattern in "${PATTERNS[@]}"; do
    echo "  Checking pattern: $pattern"
    
    # Check committed files (exclude this script itself)
    MATCHES=$(grep -rE "$pattern" --include='*.sh' --include='*.py' --include='*.js' --include='*.json' --include='*.yaml' --include='*.yml' . 2>/dev/null | grep -v "check-secrets.sh" || true)
    
    if [ ! -z "$MATCHES" ]; then
        echo "❌ FOUND HARDCODED SECRETS:"
        echo "$MATCHES"
        FOUND_SECRETS=1
    fi
done

if [ $FOUND_SECRETS -eq 1 ]; then
    echo "🚨 SECURITY VIOLATION: Hardcoded secrets found!"
    echo "Move all secrets to environment variables or encrypted storage."
    exit 1
else
    echo "✅ No hardcoded secrets found"
    exit 0
fi