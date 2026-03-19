#!/bin/bash
# Batch ingest all GitHub issues labeled 'wilma-ingest' or 'SSD-extracted'
# Extracts JSON from the last comment, ingests into v3, relabels as SSD-complete
set -euo pipefail

cd "$(dirname "$0")"

echo "Fetching issues with wilma-ingest or SSD-extracted labels..."

# Get issue numbers
ISSUES=$(gh issue list -R hazeydata/theme-park-crowd-report \
    --label "wilma-ingest" --state open \
    --json number --jq '.[].number' 2>/dev/null || true)

ISSUES2=$(gh issue list -R hazeydata/theme-park-crowd-report \
    --label "SSD-extracted" --state open \
    --json number --jq '.[].number' 2>/dev/null || true)

ALL_ISSUES=$(echo -e "${ISSUES}\n${ISSUES2}" | sort -rn | uniq | grep -v '^$' || true)

if [ -z "$ALL_ISSUES" ]; then
    echo "No issues ready for ingestion."
    exit 0
fi

COUNT=$(echo "$ALL_ISSUES" | wc -l)
echo "Found $COUNT issues to process."

SUCCESS=0
FAILED=0

for ISSUE_NUM in $ALL_ISSUES; do
    echo ""
    echo "================================================================"
    echo "Processing issue #${ISSUE_NUM}..."
    
    # Get the last comment body
    COMMENT=$(gh issue view "$ISSUE_NUM" -R hazeydata/theme-park-crowd-report \
        --json comments --jq '.comments[-1].body' 2>/dev/null || true)
    
    if [ -z "$COMMENT" ]; then
        echo "  ⚠️ No comments found on #${ISSUE_NUM}, skipping"
        FAILED=$((FAILED + 1))
        continue
    fi
    
    # Extract JSON from the comment (between ```json and ```)
    JSON=$(echo "$COMMENT" | sed -n '/^```json/,/^```$/p' | sed '1d;$d')
    
    if [ -z "$JSON" ]; then
        echo "  ⚠️ No JSON block found in #${ISSUE_NUM}, skipping"
        FAILED=$((FAILED + 1))
        continue
    fi
    
    # Ingest
    RESULT=$(python3 ingest_from_issue.py "$JSON" 2>&1) || {
        echo "  ❌ Ingestion failed for #${ISSUE_NUM}:"
        echo "$RESULT"
        FAILED=$((FAILED + 1))
        continue
    }
    echo "$RESULT"
    
    # Get row counts for the comment
    DISTRICT_NAME=$(echo "$JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['district_name'])" 2>/dev/null || echo "Unknown")
    SCHOOL_DAYS=$(echo "$RESULT" | grep -oP '(\d+) school days' | head -1 || echo "?")
    
    # Post confirmation comment
    gh issue comment "$ISSUE_NUM" -R hazeydata/theme-park-crowd-report \
        -b "✅ **Ingested into v3 database** by Wilma.

${SCHOOL_DAYS} generated. Data verified and committed." 2>/dev/null || true
    
    # Relabel: add SSD-complete, remove wilma-ingest and SSD-extracted
    gh issue edit "$ISSUE_NUM" -R hazeydata/theme-park-crowd-report \
        --add-label "SSD-complete" \
        --remove-label "wilma-ingest" \
        --remove-label "SSD-extracted" \
        --remove-label "barney" \
        --remove-label "wilma" \
        --remove-label "SSD-collect" 2>/dev/null || true
    
    # Close the issue
    gh issue close "$ISSUE_NUM" -R hazeydata/theme-park-crowd-report 2>/dev/null || true
    
    echo "  ✅ Issue #${ISSUE_NUM} → SSD-complete, closed"
    SUCCESS=$((SUCCESS + 1))
done

echo ""
echo "================================================================"
echo "Batch complete: ${SUCCESS} ingested, ${FAILED} failed/skipped"
