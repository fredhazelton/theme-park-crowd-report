#!/usr/bin/env bash
# Git Cleanup Scanner — finds stale scripts, orphaned docs, dead references
# Usage: git_cleanup_scan.sh [repo_path]
# Outputs actionable cleanup candidates. Agents should review before deleting.

set -uo pipefail

REPO="${1:-.}"
cd "$REPO"

echo "🧹 Git Cleanup Scan — $(basename $(pwd))"
echo "   Path: $(pwd)"
echo "   Date: $(date '+%Y-%m-%d %H:%M')"
echo "============================================"
echo ""

# 1. Scripts not referenced anywhere else in the repo
echo "📜 POTENTIALLY ORPHANED SCRIPTS"
echo "   (scripts/*.py not imported/referenced by other files)"
echo "---"
FOUND_ORPHANS=0
for script in scripts/*.py; do
    [ -f "$script" ] || continue
    basename_no_ext=$(basename "$script" .py)
    # Search for references (excluding the file itself, .pyc, __pycache__)
    refs=$(grep -rl "$basename_no_ext" --include='*.py' --include='*.sh' --include='*.md' --include='*.yaml' --include='*.yml' --include='*.json' --include='*.toml' . 2>/dev/null \
        | grep -v "$script" \
        | grep -v __pycache__ \
        | grep -v '.pyc' \
        | grep -v node_modules \
        | grep -v .venv \
        | head -3)
    if [ -z "$refs" ]; then
        last_modified=$(git log -1 --format='%ci' -- "$script" 2>/dev/null | cut -d' ' -f1)
        echo "  ⚠️  $script (last commit: ${last_modified:-unknown})"
        FOUND_ORPHANS=$((FOUND_ORPHANS + 1))
    fi
done
[ $FOUND_ORPHANS -eq 0 ] && echo "  ✅ None found"
echo ""

# 2. Markdown files that haven't been updated in 30+ days
echo "📝 STALE DOCUMENTATION (30+ days since last commit)"
echo "---"
FOUND_STALE=0
for md in $(find . -name '*.md' -not -path './.venv/*' -not -path './node_modules/*' -not -path './.git/*' 2>/dev/null); do
    last_commit_epoch=$(git log -1 --format='%ct' -- "$md" 2>/dev/null || echo 0)
    if [ "$last_commit_epoch" != "0" ]; then
        age_days=$(( ($(date +%s) - last_commit_epoch) / 86400 ))
        if [ $age_days -gt 30 ]; then
            last_date=$(git log -1 --format='%ci' -- "$md" 2>/dev/null | cut -d' ' -f1)
            echo "  📄 $md (${age_days}d old, last: $last_date)"
            FOUND_STALE=$((FOUND_STALE + 1))
        fi
    fi
done
[ $FOUND_STALE -eq 0 ] && echo "  ✅ All docs recently updated"
echo ""

# 3. Empty or near-empty files
echo "📦 EMPTY/TINY FILES (<10 bytes)"
echo "---"
FOUND_EMPTY=0
find . -type f \( -name '*.py' -o -name '*.md' -o -name '*.sh' \) \
    -not -path './.venv/*' -not -path './.git/*' -not -path './node_modules/*' \
    -size -10c 2>/dev/null | while read f; do
    echo "  🗑️  $f ($(wc -c < "$f") bytes)"
    FOUND_EMPTY=$((FOUND_EMPTY + 1))
done
echo ""

# 4. TODO/FIXME/HACK markers
echo "🔧 CODE MARKERS (TODO/FIXME/HACK)"
echo "---"
TODO_COUNT=$(grep -r 'TODO\|FIXME\|HACK\|XXX' --include='*.py' --include='*.sh' \
    -l . 2>/dev/null \
    | grep -v .venv \
    | grep -v node_modules \
    | grep -v __pycache__ \
    | wc -l)
echo "  Files with markers: $TODO_COUNT"
grep -rn 'TODO\|FIXME\|HACK\|XXX' --include='*.py' --include='*.sh' . 2>/dev/null \
    | grep -v .venv \
    | grep -v node_modules \
    | grep -v __pycache__ \
    | head -10
echo ""

# 5. Git branches that are merged/stale
echo "🌿 STALE GIT BRANCHES (merged into current)"
echo "---"
MERGED=$(git branch --merged 2>/dev/null | grep -v '\*' | grep -v 'main\|master' | head -10)
if [ -n "$MERGED" ]; then
    echo "$MERGED" | while read branch; do
        echo "  🗑️  $branch"
    done
else
    echo "  ✅ No stale branches"
fi
echo ""

echo "============================================"
echo "Review each item before acting. Use 'trash' over 'rm'."
echo "Done."
