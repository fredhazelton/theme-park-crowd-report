#!/bin/bash
# Robust training runner - retries on failure, runs detached from session
set -o pipefail

cd /home/wilma/theme-park-crowd-report
LOG="/mnt/data/pipeline/logs/training_robust_$(date +%Y%m%d_%H%M%S).log"
MAX_RETRIES=3
RETRY=0

echo "$(date) — Starting robust training (max $MAX_RETRIES retries)" | tee "$LOG"

while [ $RETRY -lt $MAX_RETRIES ]; do
    echo "$(date) — Attempt $((RETRY+1))/$MAX_RETRIES" | tee -a "$LOG"
    
    .venv/bin/python3 scripts/hybrid_pipeline_v2.py --use-synthetic >> "$LOG" 2>&1
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo "$(date) — Training completed successfully!" | tee -a "$LOG"
        
        # Run forecasts + WTI
        echo "$(date) — Running forecasts..." | tee -a "$LOG"
        .venv/bin/python3 scripts/forecast_vectorized.py >> "$LOG" 2>&1
        
        echo "$(date) — Running WTI calculation..." | tee -a "$LOG"
        .venv/bin/python3 scripts/calculate_wti_simple.py >> "$LOG" 2>&1
        
        echo "$(date) — Full pipeline recovery complete!" | tee -a "$LOG"
        exit 0
    fi
    
    RETRY=$((RETRY+1))
    echo "$(date) — Failed (exit $EXIT_CODE). Waiting 30s before retry..." | tee -a "$LOG"
    sleep 30
done

echo "$(date) — All $MAX_RETRIES attempts failed!" | tee -a "$LOG"
exit 1
