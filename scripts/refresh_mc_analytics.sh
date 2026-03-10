#!/bin/bash
# Refresh Mission Control analytics JSON + push to GitHub Pages
# Runs after daily pipeline to keep MC data current
set -e

cd /home/wilma/theme-park-crowd-report

echo "$(date '+%Y-%m-%d %H:%M:%S') Starting MC analytics refresh..."

# Regenerate analytics JSON from latest accuracy data
.venv/bin/python3 scripts/generate_analytics_json.py

# Stage and push if there are changes
if ! git diff --quiet docs/analytics-data/ docs/mission-control-content.json 2>/dev/null; then
    git add docs/analytics-data/ docs/mission-control-content.json
    git commit -m "Auto-refresh MC analytics data ($(date '+%Y-%m-%d %H:%M'))"
    git push
    echo "$(date '+%Y-%m-%d %H:%M:%S') Pushed updated analytics to GitHub Pages"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') No analytics changes to push"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') Done"
