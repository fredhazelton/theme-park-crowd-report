#!/usr/bin/env python3
"""
Closures S3 Downloader

================================================================================
PURPOSE
================================================================================
Downloads temporary closure CSV files from S3 and stores them locally for
processing by build_operating_calendar.py. Part of the closures module that
tracks attraction closures (temporary + permanent) for WTI and forecast accuracy.

================================================================================
S3 SOURCE
================================================================================
  - Bucket: touringplans_stats
  - Prefix: export/closures/
  - Files: current_wdw_closures.csv, current_dlr_closures.csv,
           current_uor_closures.csv, current_tdr_closures.csv,
           current_ush_closures.csv

================================================================================
OUTPUT
================================================================================
  - raw_closures/*.csv under --output-base
  - Logs: logs/get_closures_YYYYMMDD_HHMMSS.log

================================================================================
USAGE
================================================================================
  python src/get_closures_from_s3.py
  python src/get_closures_from_s3.py --output-base /path/to/output
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ResponseStreamingError

from utils import get_output_base

# =============================================================================
# CONFIGURATION
# =============================================================================
S3_BUCKET = "touringplans_stats"
S3_CLOSURES_PREFIX = "export/closures/"

CLOSURE_FILES = [
    "current_wdw_closures.csv",
    "current_dlr_closures.csv",
    "current_uor_closures.csv",
    "current_tdr_closures.csv",
    "current_ush_closures.csv",
]

MAX_RETRIES = 3
RETRY_WAIT = [1, 2, 4]


# =============================================================================
# LOGGING
# =============================================================================
def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"get_closures_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger(__name__)
    logger.info("Logging initialized. Log file: %s", log_file)
    return logger


# =============================================================================
# S3 HELPERS
# =============================================================================
def _download_csv(s3, bucket: str, key: str, logger: logging.Logger) -> bytes | None:
    """Download S3 object as bytes with retries. Returns None on failure."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = s3.get_object(Bucket=bucket, Key=key)
            return resp["Body"].read()
        except (ClientError, ResponseStreamingError, OSError) as e:
            wait = RETRY_WAIT[attempt] if attempt < len(RETRY_WAIT) else RETRY_WAIT[-1]
            if attempt < MAX_RETRIES - 1:
                logger.warning(
                    "Error reading %s (attempt %d/%d): %s. Retrying in %ds...",
                    key, attempt + 1, MAX_RETRIES, e, wait,
                )
                time.sleep(wait)
            else:
                logger.error("Failed to read %s after %d attempts: %s", key, MAX_RETRIES, e)
                return None
    return None


# =============================================================================
# MAIN
# =============================================================================
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Download closure CSVs from S3 to raw_closures/"
    )
    ap.add_argument(
        "--output-base",
        type=Path,
        default=get_output_base(),
        help="Output base directory",
    )
    args = ap.parse_args()

    base = args.output_base.resolve()
    log_dir = base / "logs"
    raw_dir = base / "raw_closures"
    logger = setup_logging(log_dir)

    logger.info("=" * 60)
    logger.info("Closures S3 download")
    logger.info("=" * 60)
    logger.info("Output base: %s", base)
    logger.info("S3 bucket: %s  prefix: %s", S3_BUCKET, S3_CLOSURES_PREFIX)

    try:
        config = Config(
            retries={"max_attempts": 5, "mode": "adaptive"},
            read_timeout=120,
            connect_timeout=60,
            proxies={},
        )
        s3 = boto3.client("s3", config=config)
        logger.info("S3 client initialized")
    except Exception as e:
        logger.error("Failed to initialize S3 client: %s", e)
        sys.exit(1)

    raw_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    failed = 0

    for filename in CLOSURE_FILES:
        key = S3_CLOSURES_PREFIX + filename
        raw = _download_csv(s3, S3_BUCKET, key, logger)
        if raw is None:
            logger.warning("Skipping %s (download failed)", filename)
            failed += 1
            continue
        out_path = raw_dir / filename
        tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
        try:
            tmp_path.write_bytes(raw)
            os.replace(tmp_path, out_path)
            logger.info("Downloaded %s (%d bytes)", filename, len(raw))
            downloaded += 1
        except Exception as e:
            logger.error("Failed to write %s: %s", out_path, e)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            failed += 1

    if downloaded == 0:
        logger.error("No closure files could be downloaded. All %d files failed.", len(CLOSURE_FILES))
        logger.info("Continuing; build_operating_calendar will use permanent closures only.")
        # Don't exit 1 — downstream handles empty input per spec
    else:
        logger.info("Done. Downloaded %d/%d files.", downloaded, len(CLOSURE_FILES))
    if failed > 0:
        logger.warning("%d file(s) failed or missing; downstream will use available data.", failed)


if __name__ == "__main__":
    main()
