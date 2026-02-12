#!/usr/bin/env python3
"""
Generate Synthetic Actuals

Applies the trained POSTED->ACTUAL conversion model to all historical POSTED
observations for STANDBY entities. Uses DuckDB for fast bulk processing.

Output: synthetic_actuals/{entity_code}.parquet for each processed entity

Usage:
    python scripts/generate_synthetic_actuals.py
    python scripts/generate_synthetic_actuals.py --output-base /mnt/data/pipeline
    python scripts/generate_synthetic_actuals.py --min-posted-obs 1000
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Add src to path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from processors.synthetic_actuals import generate_all
from utils.paths import get_output_base


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(ZoneInfo('UTC')).strftime('%Y%m%d_%H%M%S')
    log_file = log_dir / f"generate_synthetic_actuals_{timestamp}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger(__name__)
    logger.info(f"Log file: {log_file}")
    return logger


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic actuals from POSTED data")
    parser.add_argument("--output-base", type=Path, default=get_output_base())
    parser.add_argument("--min-posted-obs", type=int, default=500)
    args = parser.parse_args()

    output_base = args.output_base.resolve()
    logger = setup_logging(output_base / "logs")

    logger.info("=" * 60)
    logger.info("GENERATE SYNTHETIC ACTUALS")
    logger.info("=" * 60)
    logger.info(f"Output base: {output_base}")
    logger.info(f"Min POSTED obs: {args.min_posted_obs}")

    try:
        summary = generate_all(output_base, logger, args.min_posted_obs)

        logger.info("")
        logger.info("Results:")
        for k, v in summary.items():
            logger.info(f"  {k}: {v}")

    except Exception as e:
        logger.exception(f"Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
