#!/bin/bash
# sync_s3_data.sh - Sync TouringPlans S3 wait_times and fastpass_times to local storage
#
# Run before ETL so the pipeline reads from local files (reliable, resumable).
# Used by run_daily_pipeline.sh; can also run on a schedule (e.g. 5:30 AM before pipeline).
#
# Usage:
#   ./scripts/sync_s3_data.sh
#   ./scripts/sync_s3_data.sh --output-base /path/to/output
#   OUTPUT_BASE=/path ./scripts/sync_s3_data.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

OUTPUT_BASE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --output-base|-o)
            OUTPUT_BASE="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--output-base PATH]"
            echo "Syncs S3 export/wait_times and export/fastpass_times to OUTPUT_BASE/raw/export/..."
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

PROJECT_ROOT="$(get_project_root)"
if [[ -z "$OUTPUT_BASE" ]]; then
    OUTPUT_BASE="$(get_output_base "$PROJECT_ROOT")"
fi

LOCAL_RAW_DIR="$OUTPUT_BASE/raw"
S3_BUCKET="s3://touringplans_stats"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting S3 sync to $LOCAL_RAW_DIR..."

# Sync wait_times (standby data) - local path mirrors S3 key prefix export/wait_times/
aws s3 sync "$S3_BUCKET/export/wait_times/" "$LOCAL_RAW_DIR/export/wait_times/" \
    --no-progress \
    --only-show-errors

# Sync fastpass_times (priority/lightning lane data)
aws s3 sync "$S3_BUCKET/export/fastpass_times/" "$LOCAL_RAW_DIR/export/fastpass_times/" \
    --no-progress \
    --only-show-errors

echo "[$(date '+%Y-%m-%d %H:%M:%S')] S3 sync complete."
