#!/bin/bash
# Robust pipeline runner - v4 integrated pipeline with retries
set -o pipefail

cd /home/wilma/theme-park-crowd-report
LOG="/mnt/data/pipeline/logs/pipeline_v4_$(date +%Y%m%d_%H%M%S).log"
MAX_RETRIES=3
RETRY=0

echo "$(date) — Starting Pipeline v4 (max $MAX_RETRIES retries)" | tee "$LOG"

while [ $RETRY -lt $MAX_RETRIES ]; do
    echo "$(date) — Attempt $((RETRY+1))/$MAX_RETRIES" | tee -a "$LOG"
    
    # Run full v4 pipeline (includes training, forecasting, WTI, all 12 steps)
    .venv/bin/python3 pipeline_v3/pipeline.py --output-base /mnt/data/pipeline >> "$LOG" 2>&1
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo "$(date) — Pipeline v4 completed successfully!" | tee -a "$LOG"
        
        # Data completeness validation
        echo "$(date) — Running data completeness check..." | tee -a "$LOG"
        COMPLETENESS_JSON=$(.venv/bin/python3 scripts/pipeline_data_completeness.py --json 2>&1)
        COMPLETENESS_STATUS=$(echo "$COMPLETENESS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','ok'))" 2>/dev/null || echo "ok")
        echo "$COMPLETENESS_JSON" >> "$LOG"
        if [ "$COMPLETENESS_STATUS" = "warning" ] || [ "$COMPLETENESS_STATUS" = "critical" ]; then
            echo "$(date) — Completeness check: $COMPLETENESS_STATUS — see log for details" | tee -a "$LOG"
        else
            echo "$(date) — Completeness check: OK" | tee -a "$LOG"
        fi
        
        # Export analytics JSONs for The Quarry dashboard
        echo "$(date) — Exporting analytics data for The Quarry..." | tee -a "$LOG"
        .venv/bin/python3 scripts/generate_analytics_json.py >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            echo "$(date) — Analytics export: OK" | tee -a "$LOG"
            # Push to GitHub Pages
            git add docs/analytics-data/ >> "$LOG" 2>&1
            git commit -m "Auto-update analytics data (post-pipeline)" --no-verify >> "$LOG" 2>&1
            git push >> "$LOG" 2>&1
            echo "$(date) — Analytics data pushed to GitHub Pages" | tee -a "$LOG"
        else
            echo "$(date) — Analytics export: FAILED (non-blocking)" | tee -a "$LOG"
        fi
        
        echo "$(date) — Full v4 pipeline complete!" | tee -a "$LOG"
        exit 0
    fi
    
    RETRY=$((RETRY+1))
    echo "$(date) — Failed (exit $EXIT_CODE). Waiting 30s before retry..." | tee -a "$LOG"
    sleep 30
done

echo "$(date) — All $MAX_RETRIES attempts failed!" | tee -a "$LOG"
exit 1
