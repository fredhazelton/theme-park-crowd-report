# Pipeline Refactor: S3 Streaming → Local Sync

**Author:** Wilma  
**For:** Bam-Bam (Cursor)  
**Priority:** HIGH — Pipeline is currently blocked  
**Date:** 2026-02-02

---

## Problem

The current ETL (`get_tp_wait_time_data_from_s3.py`) streams large CSV files directly from S3 into pandas. This is fragile:

- Connection drops mid-stream → entire operation fails
- 30-50MB files over network = frequent `IncompleteRead` errors
- Current run has been stuck for 17+ hours with 141 connection errors
- Only processed 580/1160 files

**Error pattern:**
```
botocore.exceptions.ResponseStreamingError: Connection broken: 
IncompleteRead(33690234 bytes read, 2082870 more expected)
```

---

## Solution: Sync-First Architecture

### Before (Current):
```
S3 → [network stream] → pandas → process → write
        ↑
    Fragile (fails on connection drop)
```

### After (New):
```
S3 → [aws s3 sync] → Local Files → pandas → process → write
        ↑                  ↑
    Reliable (resumes)   Fast reads
```

---

## Implementation Steps

### 1. Create Sync Script

**New file:** `scripts/sync_s3_data.sh`

```bash
#!/bin/bash
# Sync TouringPlans S3 data to local storage
# Run before ETL, or on a schedule (e.g., 5:30 AM daily)

set -e

LOCAL_RAW_DIR="/home/wilma/hazeydata/raw"
S3_BUCKET="s3://touringplans_stats/export"

echo "[$(date)] Starting S3 sync..."

# Sync wait_times (standby data)
aws s3 sync "$S3_BUCKET/wait_times/" "$LOCAL_RAW_DIR/wait_times/" \
    --no-progress \
    --only-show-errors

# Sync fastpass_times (priority/lightning lane data)  
aws s3 sync "$S3_BUCKET/fastpass_times/" "$LOCAL_RAW_DIR/fastpass_times/" \
    --no-progress \
    --only-show-errors

echo "[$(date)] S3 sync complete."
```

### 2. Modify ETL to Read Local Files

**File:** `src/get_tp_wait_time_data_from_s3.py`

**Changes needed:**

1. Add `--local-source` argument:
```python
parser.add_argument(
    "--local-source",
    type=str,
    default=None,
    help="Read from local directory instead of S3 streaming"
)
```

2. Modify file reading logic:
```python
# BEFORE: Stream from S3
obj = s3.get_object(Bucket=bucket, Key=key)
df = pd.read_csv(obj['Body'], ...)

# AFTER: Read from local file
if args.local_source:
    local_path = Path(args.local_source) / key
    df = pd.read_csv(local_path, ...)
else:
    # Keep S3 streaming as fallback
    obj = s3.get_object(Bucket=bucket, Key=key)
    df = pd.read_csv(obj['Body'], ...)
```

3. Modify file listing logic:
```python
# BEFORE: List S3 bucket
paginator = s3.get_paginator('list_objects_v2')

# AFTER: List local directory OR S3
if args.local_source:
    files = list(Path(args.local_source).rglob("*.csv"))
else:
    # Keep S3 listing as fallback
```

### 3. Update Daily Pipeline Script

**File:** `scripts/run_daily_pipeline.sh`

```bash
# Add sync step BEFORE ETL
if [[ "$SKIP_SYNC" != "true" ]]; then
    log "Starting S3 sync..."
    ./scripts/sync_s3_data.sh
fi

# Run ETL with local source
python3 src/get_tp_wait_time_data_from_s3.py \
    --output-base "$OUTPUT_BASE" \
    --local-source /home/wilma/hazeydata/raw
```

### 4. Update Cron Schedule

```cron
# Sync S3 data at 5:30 AM (before pipeline)
30 5 * * * /home/wilma/theme-park-crowd-report/scripts/sync_s3_data.sh >> /home/wilma/hazeydata/pipeline/logs/s3_sync.log 2>&1

# Run pipeline at 6:00 AM (after sync)
0 6 * * * cd /home/wilma/theme-park-crowd-report && ./scripts/run_daily_pipeline.sh --skip-dropbox-check >> /home/wilma/hazeydata/pipeline/logs/daily_pipeline_$(date +\%Y-\%m-\%d).log 2>&1
```

---

## Storage Requirements

**Estimated S3 data size:**
- wait_times: ~5-10 GB (all parks, all years)
- fastpass_times: ~5-10 GB

**Location:** `/home/wilma/hazeydata/raw/`

The Ryzen server has ~4TB storage, so this is fine.

---

## Testing

1. Run sync script manually, verify files download
2. Run ETL with `--local-source`, verify it processes files
3. Compare output to previous S3-streaming output (should be identical)
4. Time comparison: local reads should be 10-100x faster

---

## Rollback

Keep the S3 streaming code as fallback. The `--local-source` flag makes this opt-in, so we can revert by simply not passing the flag.

---

## Questions for Bam-Bam

1. Should we keep the S3 streaming as fallback, or fully remove it?
2. Any concerns about the sync approach for incremental files?
3. Should sync script handle deleted files (mirror vs sync)?

---

## Current State

- **Stuck process:** PID 238077, 238104 (kill when ready to test)
- **Lock file:** `/home/wilma/hazeydata/pipeline/state/processing.lock`
- **Progress:** 580/1160 files processed before stalling

---

**Once implemented, tell Wilma and she'll kill the old process and test the new pipeline.**
