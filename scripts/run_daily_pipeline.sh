#!/bin/bash
# run_daily_pipeline.sh - Master script: run full pipeline in order (daily)
#
# Order: ETL → Dimensions → Posted Aggregates → Report → Training → Forecast → WTI
#
# Lock: state/daily_pipeline.lock ensures only one run at a time. If the previous run
# is still in progress (e.g. still training), this run skips cleanly (exit 0) so it
# doesn't kill or conflict with the other run.
#
# Usage:
#   ./scripts/run_daily_pipeline.sh
#   ./scripts/run_daily_pipeline.sh --output-base /path/to/output
#   ./scripts/run_daily_pipeline.sh --no-stop-on-error   # continue on step failure, log and exit with 1 at end
#   ./scripts/run_daily_pipeline.sh --skip-etl --skip-training
#
# For cron: use one job that runs this script (e.g. 6:00 AM ET after network is up).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Options
OUTPUT_BASE=""
STOP_ON_ERROR=true
SKIP_ETL=false
SKIP_DIMENSIONS=false
SKIP_CLOSURES=false
SKIP_AGGREGATES=false
SKIP_REPORT=false
SKIP_TRAINING=false
SKIP_FORECAST=false
SKIP_WTI=false
SKIP_VALIDATION=false
SKIP_DROPBOX_CHECK=false
SKIP_SYNC=false
SKIP_IF_UNCHANGED=false
USE_SYNTHETIC=false
USE_ACTUALS_ONLY=false
PARK=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --output-base|-o)
            OUTPUT_BASE="$2"
            shift 2
            ;;
        --no-stop-on-error)
            STOP_ON_ERROR=false
            shift
            ;;
        --skip-etl)
            SKIP_ETL=true
            shift
            ;;
        --skip-dimensions)
            SKIP_DIMENSIONS=true
            shift
            ;;
        --skip-closures)
            SKIP_CLOSURES=true
            shift
            ;;
        --skip-aggregates)
            SKIP_AGGREGATES=true
            shift
            ;;
        --skip-report)
            SKIP_REPORT=true
            shift
            ;;
        --skip-training)
            SKIP_TRAINING=true
            shift
            ;;
        --skip-forecast)
            SKIP_FORECAST=true
            shift
            ;;
        --skip-wti)
            SKIP_WTI=true
            shift
            ;;
        --skip-validation)
            SKIP_VALIDATION=true
            shift
            ;;
        --skip-dropbox-check)
            SKIP_DROPBOX_CHECK=true
            shift
            ;;
        --skip-sync)
            SKIP_SYNC=true
            shift
            ;;
        --skip-if-unchanged)
            SKIP_IF_UNCHANGED=true
            shift
            ;;
        --use-synthetic)
            USE_SYNTHETIC=true
            shift
            ;;
        --actuals-only)
            USE_ACTUALS_ONLY=true
            shift
            ;;
        --park)
            PARK="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Runs full pipeline in order: ETL → Dimensions → Posted Aggregates → Report → Training → Forecast → WTI"
            echo ""
            echo "Options:"
            echo "  --output-base PATH    Output base (default: from config/config.json)"
            echo "  --no-stop-on-error    Continue on step failure; log and exit 1 at end"
            echo "  --skip-etl             Skip main ETL"
            echo "  --skip-dimensions      Skip dimension fetches"
            echo "  --skip-closures        Skip closures module (get_closures + operating calendar)"
            echo "  --skip-aggregates      Skip posted aggregates build"
            echo "  --skip-report           Skip wait time DB report"
            echo "  --skip-training        Skip batch training"
            echo "  --skip-forecast        Skip forecast generation"
            echo "  --skip-wti             Skip WTI calculation"
            echo "  --skip-validation      Skip post-run validation"
            echo "  --skip-dropbox-check   Do not force-quit Dropbox (use if output_base is not on Dropbox)"
            echo "  --skip-sync             Skip S3 sync (use existing local raw data)"
            echo "  --skip-if-unchanged    Skip training/forecast/WTI if data hasn't changed (fast incremental mode)"
            echo "  --use-synthetic        Include synthetic actuals in training (balances real vs synthetic data)"
            echo "  --actuals-only        ACTUALS-FIRST: train on actuals only, 5 features, no posted_time (OOM-safe)"
            echo "  --park PARK            Run training, forecast, and WTI for one park only (e.g. MK, EP, AK)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# Setup
PROJECT_ROOT="$(get_project_root)"
PYTHON="$(get_python)"

if [[ -z "$OUTPUT_BASE" ]]; then
    OUTPUT_BASE="$(get_output_base "$PROJECT_ROOT")"
fi

cd "$PROJECT_ROOT"
ensure_logs_dir "$OUTPUT_BASE"
mkdir -p "$OUTPUT_BASE/state"

# Force-quit Dropbox when output_base is on Dropbox (avoids file locks / partial reads)
if ! $SKIP_DROPBOX_CHECK; then
    ensure_dropbox_stopped "$OUTPUT_BASE"
fi

# Single daily log (set early so skip message can be written)
LOG_FILE="$OUTPUT_BASE/logs/daily_pipeline_$(date '+%Y-%m-%d').log"
PIPELINE_LOCK="$OUTPUT_BASE/state/daily_pipeline.lock"

# Pipeline-level lock: only one run at a time. If previous run still in progress, skip (don't kill it).
acquire_pipeline_lock() {
    if [[ -f "$PIPELINE_LOCK" ]]; then
        local other_pid
        other_pid=$(sed -n 's/^PID: //p' "$PIPELINE_LOCK" 2>/dev/null | head -1)
        if [[ -n "$other_pid" ]] && kill -0 "$other_pid" 2>/dev/null; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Previous run still in progress (PID $other_pid); skipping to avoid overlapping." >> "$LOG_FILE"
            exit 0
        fi
        rm -f "$PIPELINE_LOCK"
    fi
    echo "PID: $$" > "$PIPELINE_LOCK"
    echo "Start: $(date -Iseconds 2>/dev/null || date)" >> "$PIPELINE_LOCK"
}
release_pipeline_lock() {
    rm -f "$PIPELINE_LOCK"
}
trap release_pipeline_lock EXIT

acquire_pipeline_lock

# Pipeline status file for dashboard
$PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" pipeline-start 2>/dev/null || true

# Initialize run manifest for skip-if-unchanged cascade tracking
if $SKIP_IF_UNCHANGED; then
    $PYTHON scripts/pipeline_state.py start-run 2>/dev/null || true
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Daily pipeline started. Output base: $OUTPUT_BASE" >> "$LOG_FILE"
export PIPELINE_LOG="$LOG_FILE"  # Tells Python scripts to skip file handlers (tee handles it)
exec > >(tee -a "$LOG_FILE") 2>&1

run_step() {
    local name="$1"
    shift
    local cmd=("$@")
    log_info "=== $name ==="
    if "${cmd[@]}"; then
        log_info "Done: $name"
        return 0
    else
        log_error "Failed: $name"
        return 1
    fi
}

run_step_optional() {
    local name="$1"
    shift
    if run_step "$name" "$@"; then
        return 0
    fi
    if $STOP_ON_ERROR; then
        log_error "Stopping on first failure (use --no-stop-on-error to continue)"
        exit 1
    fi
    return 1
}

FAILED_ANY=false

# -1. Init DuckDB for bot + dashboard (if not yet created)
if [[ ! -f "$OUTPUT_BASE/tpcr_live.duckdb" ]]; then
    log_info "=== Init DuckDB (tpcr_live.duckdb) ==="
    if $PYTHON scripts/init_live_duckdb.py --output-base "$OUTPUT_BASE" 2>/dev/null; then
        log_info "DuckDB initialized for bot + dashboard"
    else
        log_info "DuckDB init skipped or failed (non-fatal)"
    fi
fi

# 0. S3 sync (before ETL) - syncs wait_times and fastpass_times to output_base/raw for reliable local reads
if ! $SKIP_SYNC && ! $SKIP_ETL; then
    if run_step "S3 sync" "$SCRIPT_DIR/sync_s3_data.sh" --output-base "$OUTPUT_BASE"; then
        :
    else
        FAILED_ANY=true
        $STOP_ON_ERROR && exit 1
    fi
elif $SKIP_SYNC; then
    log_info "=== S3 sync (skipped) ==="
fi

# 1. ETL (incremental) — reads from output_base/raw only (sync-only; no S3 streaming)
if $SKIP_ETL; then
    log_info "=== ETL (skipped) ==="
    $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step etl done 2>/dev/null || true
else
    if run_step "ETL (incremental)" "$SCRIPT_DIR/run_etl.sh" --output-base "$OUTPUT_BASE" --local-source "$OUTPUT_BASE/raw"; then
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step etl done 2>/dev/null || true
    else
        FAILED_ANY=true
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step etl failed 2>/dev/null || true
        $STOP_ON_ERROR && exit 1
    fi
fi

# 1b. Convert CSVs to Parquet (needed by WTI, forecasts, and posted aggregates)
# Must run after ETL so new CSVs are included in the parquet files
if $SKIP_ETL; then
    log_info "=== CSV→Parquet conversion (skipped - ETL skipped) ==="
else
    if run_step "CSV→Parquet conversion" $PYTHON scripts/convert_to_parquet.py; then
        :
    else
        FAILED_ANY=true
        $STOP_ON_ERROR && exit 1
    fi
fi

# 2. Dimension fetches
if $SKIP_DIMENSIONS; then
    log_info "=== Dimension fetches (skipped) ==="
    $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step dimensions done 2>/dev/null || true
else
    if run_step "Dimension fetches" "$SCRIPT_DIR/run_dimension_fetches.sh" --output-base "$OUTPUT_BASE"; then
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step dimensions done 2>/dev/null || true
    else
        FAILED_ANY=true
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step dimensions failed 2>/dev/null || true
        $STOP_ON_ERROR && exit 1
    fi
fi

# 2a. Closures module (get_closures from S3 + build operating calendar)
# Runs after dimensions (needs dimentity); before posted aggregates
if $SKIP_CLOSURES || $SKIP_DIMENSIONS; then
    log_info "=== Closures module (skipped) ==="
else
    if run_step "Closures: get_closures from S3" $PYTHON src/get_closures_from_s3.py --output-base "$OUTPUT_BASE"; then
        if run_step "Closures: build operating calendar" $PYTHON src/build_operating_calendar.py --output-base "$OUTPUT_BASE"; then
            :
        else
            FAILED_ANY=true
            $STOP_ON_ERROR && exit 1
        fi
    else
        FAILED_ANY=true
        # Non-fatal: downstream can run without operating calendar (assume all operating)
        log_info "WARNING: Closures module failed; continuing (operating calendar may be stale/missing)"
        if $STOP_ON_ERROR; then
            exit 1
        fi
    fi
fi

# 2b. Impute park hours (fills missing future park hours using donor pool)
# Runs after dimensions because it needs dimparkhours + dimdategroupid
if $SKIP_DIMENSIONS; then
    log_info "=== Impute park hours (skipped - dimensions skipped) ==="
else
    if run_step "Impute park hours" $PYTHON scripts/impute_park_hours.py --output-base "$OUTPUT_BASE"; then
        :
    else
        FAILED_ANY=true
        $STOP_ON_ERROR && exit 1
    fi
fi

# 3. Posted aggregates
if $SKIP_AGGREGATES; then
    log_info "=== Posted aggregates (skipped) ==="
    $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step aggregates done 2>/dev/null || true
else
    if run_step "Posted aggregates (fast)" $PYTHON scripts/build_posted_aggregates_fast.py --output-base "$OUTPUT_BASE"; then
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step aggregates done 2>/dev/null || true
    else
        FAILED_ANY=true
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step aggregates failed 2>/dev/null || true
        $STOP_ON_ERROR && exit 1
    fi
fi

# 4. Wait time DB report
if $SKIP_REPORT; then
    log_info "=== Wait time DB report (skipped) ==="
    $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step report done 2>/dev/null || true
else
    if run_step "Wait time DB report" $PYTHON scripts/report_wait_time_db.py --quick --lookback-days 14 --output-base "$OUTPUT_BASE"; then
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step report done 2>/dev/null || true
    else
        FAILED_ANY=true
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step report failed 2>/dev/null || true
        $STOP_ON_ERROR && exit 1
    fi
fi

# 4b. Forecast Accuracy Evaluation (BEFORE new forecasts overwrite old ones)
# Compares previous forecast against fresh actuals, archives current forecast
log_info "=== Forecast accuracy evaluation ==="
if run_step "Forecast accuracy evaluation" $PYTHON src/evaluate_forecast_accuracy.py --output-base "$OUTPUT_BASE" --run-date "$(date +%Y-%m-%d)"; then
    log_info "Done: Forecast accuracy evaluation"
else
    log_info "WARNING: Forecast accuracy evaluation failed (non-fatal, continuing)"
    # Non-fatal — don't stop the pipeline for accuracy tracking failures
fi

# 4c. Weekly Conversion Model Refresh
# Retrains the global POSTED→ACTUAL conversion model every Monday (or if model is missing).
# Uses geo-decay weighted sample pairs. Model saved to models/_conversion/.
CONVERSION_MODEL="$OUTPUT_BASE/models/_conversion/model.json"
DOW=$(date +%u)  # 1=Monday, 7=Sunday
if [ "$DOW" = "1" ] || [ ! -f "$CONVERSION_MODEL" ]; then
    log_info "=== Conversion model retrain (weekly refresh) ==="
    if run_step "Conversion model retrain" $PYTHON scripts/train_conversion_model.py --output-base "$OUTPUT_BASE"; then
        log_info "Done: Conversion model retrain"
    else
        log_info "WARNING: Conversion model retrain failed (non-fatal, continuing)"
    fi
else
    log_info "=== Conversion model retrain (skipped — not Monday, model exists) ==="
fi

# 4d. Synthetic Actuals Generation
# Applies trained POSTED→ACTUAL conversion model to all historical POSTED observations.
# Output: synthetic_actuals/{entity_code}.parquet — used by dashboard curve display.
# NOTE: NOT used for training yet. Training integration planned for later.
log_info "=== Synthetic actuals generation ==="
if run_step "Synthetic actuals generation" $PYTHON scripts/generate_synthetic_actuals.py --output-base "$OUTPUT_BASE"; then
    log_info "Done: Synthetic actuals generation"
else
    log_info "WARNING: Synthetic actuals generation failed (non-fatal, continuing)"
    # Non-fatal — dashboard falls back to raw actuals if synthetic unavailable
fi

# 5. Hybrid training V2 (Julia XGBoost with geo decay weights)
# Uses DuckDB for matched pairs + Julia for training (with date_group_id, season, geo_decay)
# Skip logic: only skip if no entities have new observations (checks entity_index.sqlite)
if $SKIP_TRAINING; then
    log_info "=== Hybrid training V2 (skipped) ==="
    $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step training done 2>/dev/null || true
    $SKIP_IF_UNCHANGED && $PYTHON scripts/pipeline_state.py record training false "explicitly skipped" 2>/dev/null || true
elif $SKIP_IF_UNCHANGED && $PYTHON scripts/pipeline_state.py check training 2>/dev/null; then
    log_info "=== Hybrid training V2 (skipped - no entities with new observations) ==="
    $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step training done 2>/dev/null || true
    $PYTHON scripts/pipeline_state.py record training false "no dirty entities" 2>/dev/null || true
else
    # Build training command
    TRAINING_CMD="$PYTHON scripts/hybrid_pipeline_v2.py --output-base $OUTPUT_BASE --skip-scoring"
    if $USE_ACTUALS_ONLY; then
        TRAINING_CMD="$TRAINING_CMD --actuals-only"
        TRAINING_DESC="Actuals-only training (5 features, no posted_time, OOM-safe)"
    elif $USE_SYNTHETIC; then
        TRAINING_CMD="$TRAINING_CMD --use-synthetic"
        TRAINING_DESC="Hybrid training V2 (Julia + geo decay + synthetic actuals)"
    else
        TRAINING_DESC="Hybrid training V2 (Julia + geo decay)"
    fi
    
    # Retry logic for training (up to 3 attempts with 60s cooldown)
    TRAIN_MAX_RETRIES=3
    TRAIN_ATTEMPT=0
    TRAIN_SUCCESS=false
    while [ $TRAIN_ATTEMPT -lt $TRAIN_MAX_RETRIES ]; do
        TRAIN_ATTEMPT=$((TRAIN_ATTEMPT+1))
        if [ $TRAIN_ATTEMPT -gt 1 ]; then
            log_info "Training retry $TRAIN_ATTEMPT/$TRAIN_MAX_RETRIES (waiting 60s)..."
            sleep 60
        fi
        if run_step "$TRAINING_DESC (attempt $TRAIN_ATTEMPT/$TRAIN_MAX_RETRIES)" $TRAINING_CMD; then
            TRAIN_SUCCESS=true
            break
        else
            log_error "Training attempt $TRAIN_ATTEMPT failed"
        fi
    done
    if $TRAIN_SUCCESS; then
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step training done 2>/dev/null || true
        $PYTHON scripts/pipeline_state.py update training 2>/dev/null || true
        $SKIP_IF_UNCHANGED && $PYTHON scripts/pipeline_state.py record training true "entities had new observations" 2>/dev/null || true
    else
        log_error "Training failed after $TRAIN_MAX_RETRIES attempts"
        FAILED_ANY=true
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step training failed 2>/dev/null || true
        $SKIP_IF_UNCHANGED && $PYTHON scripts/pipeline_state.py record training false "training failed after $TRAIN_MAX_RETRIES retries" 2>/dev/null || true
        $STOP_ON_ERROR && exit 1
    fi
fi

# 5b. Scope-and-scale group model training (for EU/new entities without per-entity models)
# Fast (~15s) — trains pooled models by scope_and_scale category from dimentity.csv
# Non-fatal: forecast works without these (falls back to aggregate)
if ! $SKIP_TRAINING; then
    log_info "=== Scope-and-scale group model training ==="
    if run_step "Scope-scale group models" $PYTHON scripts/train_scope_scale_models.py --output-base "$OUTPUT_BASE"; then
        log_info "Done: Scope-scale group models"
    else
        log_info "WARNING: Scope-scale group model training failed (non-fatal, continuing)"
    fi
fi

# 6. Forecast
# Skip logic: only skip if training was skipped this run (no new models = forecasts still valid)
if $SKIP_FORECAST; then
    log_info "=== Forecast (skipped) ==="
    $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step forecast done 2>/dev/null || true
    $SKIP_IF_UNCHANGED && $PYTHON scripts/pipeline_state.py record forecast false "explicitly skipped" 2>/dev/null || true
elif $SKIP_IF_UNCHANGED && $PYTHON scripts/pipeline_state.py check forecast 2>/dev/null; then
    log_info "=== Forecast (skipped - training didn't run, forecasts still valid) ==="
    $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step forecast done 2>/dev/null || true
    $PYTHON scripts/pipeline_state.py record forecast false "training was skipped" 2>/dev/null || true
else
    if run_step "Forecast (vectorized)" $PYTHON scripts/forecast_vectorized.py --output-base "$OUTPUT_BASE" --days 730; then
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step forecast done 2>/dev/null || true
        $PYTHON scripts/pipeline_state.py update forecast 2>/dev/null || true
        $SKIP_IF_UNCHANGED && $PYTHON scripts/pipeline_state.py record forecast true "training ran this run" 2>/dev/null || true
    else
        FAILED_ANY=true
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step forecast failed 2>/dev/null || true
        $SKIP_IF_UNCHANGED && $PYTHON scripts/pipeline_state.py record forecast false "forecast failed" 2>/dev/null || true
        $STOP_ON_ERROR && exit 1
    fi
fi

# 7. WTI (simplified version that works with current data)
# Skip logic: only skip if forecast was skipped this run (no new forecasts = WTI still valid)
if $SKIP_WTI; then
    log_info "=== WTI (skipped) ==="
    $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step wti done 2>/dev/null || true
    $SKIP_IF_UNCHANGED && $PYTHON scripts/pipeline_state.py record wti false "explicitly skipped" 2>/dev/null || true
elif $SKIP_IF_UNCHANGED && $PYTHON scripts/pipeline_state.py check wti 2>/dev/null; then
    log_info "=== WTI (skipped - forecast didn't run, WTI still valid) ==="
    $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step wti done 2>/dev/null || true
    $PYTHON scripts/pipeline_state.py record wti false "forecast was skipped" 2>/dev/null || true
else
    if run_step "WTI" $PYTHON scripts/calculate_wti_simple.py --output-base "$OUTPUT_BASE"; then
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step wti done 2>/dev/null || true
        $PYTHON scripts/pipeline_state.py update wti 2>/dev/null || true
        $SKIP_IF_UNCHANGED && $PYTHON scripts/pipeline_state.py record wti true "forecast ran this run" 2>/dev/null || true
    else
        FAILED_ANY=true
        $PYTHON scripts/update_pipeline_status.py --output-base "$OUTPUT_BASE" step wti failed 2>/dev/null || true
        $SKIP_IF_UNCHANGED && $PYTHON scripts/pipeline_state.py record wti false "wti failed" 2>/dev/null || true
        $STOP_ON_ERROR && exit 1
    fi
fi

# Pre-generate calendar heatmap images for Discord bot
log_info "=== Generate calendar images ==="
$PYTHON scripts/generate_calendar_images.py || log_info "Calendar image generation failed (non-fatal)"

# Generate landing page chart (MK 7-day)
log_info "=== Generate landing page chart ==="
$PYTHON scripts/generate_landing_chart.py || log_info "Landing chart generation failed (non-fatal)"

# Export year-view data for hazeydata.ai and deploy
log_info "=== Export year-view data ==="
if $PYTHON scripts/export_year_view_data.py; then
    log_info "Year-view data exported, deploying to Cloudflare Pages..."
    (
        cd /home/wilma/hazeydata.ai && \
        git add -A && \
        git diff --cached --quiet || \
        (git commit -m "Daily year-view data update $(date +%Y-%m-%d)" && \
         git push origin master && \
         source <(grep -v '#' ~/.env | grep '=' | sed 's/^/export /') && \
         CLOUDFLARE_API_TOKEN=$CLOUDFLARE_PAGES_TOKEN \
         CLOUDFLARE_ACCOUNT_ID=0ec71dc83a3e7f8559be115fa548902e \
         npx wrangler pages deploy . --project-name hazeydata --branch master)
    ) >> "$OUTPUT_BASE/logs/year_view_deploy.log" 2>&1 && \
    log_info "Year-view deployed to hazeydata.ai" || \
    log_info "Year-view deploy skipped or failed (non-fatal)"
else
    log_info "Year-view export failed (non-fatal)"
fi

if $FAILED_ANY; then
    log_error "Daily pipeline finished with one or more failures. Check log: $LOG_FILE"
    exit 1
fi

# Post-run validation (data quality checks)
if $SKIP_VALIDATION; then
    log_info "=== Pipeline validation (skipped) ==="
else
    log_info "=== Pipeline validation ==="
    if $PYTHON src/validate_pipeline_output.py --output-base "$OUTPUT_BASE"; then
        log_info "Validation: PASS"
    else
        log_error "Validation: FAIL (see pipeline_validation/validation_report.txt)"
        exit 1
    fi
fi

# Restart dashboard API to pick up new data (WTI, fact tables, etc.)
API_PID=$(pgrep -f "dashboard/api.py" 2>/dev/null | head -1)
if [[ -n "$API_PID" ]]; then
    log_info "Restarting dashboard API (PID $API_PID) to load new data..."
    kill "$API_PID" 2>/dev/null || true
    sleep 2
    cd "$PROJECT_ROOT" && nohup "$PYTHON" dashboard/api.py >> "$OUTPUT_BASE/logs/api.log" 2>&1 &
    log_info "Dashboard API restarted (new PID $!)"
fi

# Regenerate Mission Control content JSON (pipeline status, accuracy, infrastructure)
log_info "=== Mission Control content refresh ==="
$PYTHON scripts/generate_pipeline_status_json.py || log_info "MC content refresh failed (non-fatal)"

log_info "Daily pipeline completed successfully. Log: $LOG_FILE"
exit 0
