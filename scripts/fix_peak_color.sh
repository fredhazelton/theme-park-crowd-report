#!/bin/bash
#
# Fix PEAK metric color from red to teal
#
# This script searches for the PEAK metric styling and changes it from red to teal.
# Run on the server where the dashboard file is located.
#

DASHBOARD_FILE="${1:-/home/wilma/clawd-anthropic/streaming/stream-dashboard.html}"

if [ ! -f "$DASHBOARD_FILE" ]; then
    echo "Error: Dashboard file not found: $DASHBOARD_FILE"
    echo "Usage: $0 [path-to-dashboard.html]"
    exit 1
fi

echo "Fixing PEAK metric color in: $DASHBOARD_FILE"

# Create backup
cp "$DASHBOARD_FILE" "${DASHBOARD_FILE}.backup"
echo "Backup created: ${DASHBOARD_FILE}.backup"

# Replace red colors in PEAK metric (common patterns)
# Pattern 1: style="color: #ff1a5c" or similar red in PEAK context
sed -i 's/PEAK.*color:\s*#ff1a5c/PEAK.*color: #4a90a4/g' "$DASHBOARD_FILE"
sed -i 's/PEAK.*color:\s*#A60038/PEAK.*color: #4a90a4/g' "$DASHBOARD_FILE"
sed -i 's/PEAK.*color:\s*var(--red)/PEAK.*color: var(--cyan)/g' "$DASHBOARD_FILE"
sed -i 's/PEAK.*color:\s*var(--red-light)/PEAK.*color: var(--cyan)/g' "$DASHBOARD_FILE"

# Pattern 2: nth-child(2) for second metric card
sed -i 's/\.stat-box:nth-child(2).*color:\s*#ff1a5c/.stat-box:nth-child(2).*color: #4a90a4/g' "$DASHBOARD_FILE"
sed -i 's/\.metric-card:nth-child(2).*color:\s*#ff1a5c/.metric-card:nth-child(2).*color: #4a90a4/g' "$DASHBOARD_FILE"

# Pattern 3: Direct style attributes on PEAK elements
sed -i 's/<[^>]*PEAK[^>]*style="[^"]*color:\s*#ff1a5c[^"]*"/<PEAK style="color: #4a90a4"/g' "$DASHBOARD_FILE"

# Pattern 4: CSS class for PEAK
sed -i 's/\.peak.*color:\s*#ff1a5c/.peak { color: #4a90a4/g' "$DASHBOARD_FILE"
sed -i 's/\.peak.*color:\s*#A60038/.peak { color: #4a90a4/g' "$DASHBOARD_FILE"

echo "Done! Check the file to verify changes."
echo "If the changes look wrong, restore from backup:"
echo "  cp ${DASHBOARD_FILE}.backup $DASHBOARD_FILE"
