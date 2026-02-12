#!/usr/bin/env python3
"""
Train POSTED->ACTUAL Conversion Model

Trains a global conversion model that learns the systematic bias between
POSTED wait times (what Disney displays) and ACTUAL wait times (ground truth).

Uses matched (POSTED, ACTUAL) pairs from all STANDBY entities to build a
model that accounts for:
- Disney's intentional overestimation buffer
- Human lag in updating posted times
- Trend dynamics (rising/falling queue effects)
- Time-of-day and entity-specific patterns

Output:
- models/_conversion/model.json: XGBoost conversion model
- models/_conversion/metadata.json: Validation metrics and feature info

Usage:
    python scripts/train_conversion_model.py
    python scripts/train_conversion_model.py --output-base /mnt/data/pipeline
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

from processors.posted_to_actual import train_conversion_model
from utils.paths import get_output_base


def setup_logging(log_dir: Path) -> logging.Logger:
    """Set up file and console logging."""
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(ZoneInfo('UTC')).strftime('%Y%m%d_%H%M%S')
    log_file = log_dir / f"train_conversion_model_{timestamp}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"Training conversion model - Log file: {log_file}")
    return logger


def main() -> None:
    parser = argparse.ArgumentParser(description="Train POSTED->ACTUAL conversion model")
    parser.add_argument(
        "--output-base",
        type=Path,
        default=get_output_base(),
        help="Output base directory (default: from config)",
    )
    
    args = parser.parse_args()
    
    output_base = args.output_base.resolve()
    log_dir = output_base / "logs"
    logger = setup_logging(log_dir)
    
    logger.info("=" * 60)
    logger.info("TRAIN POSTED->ACTUAL CONVERSION MODEL")
    logger.info("=" * 60)
    logger.info(f"Output base: {output_base}")
    
    start_time = time.time()
    
    try:
        # Train the conversion model
        metrics = train_conversion_model(output_base, logger)
        
        elapsed = time.time() - start_time
        
        logger.info("=" * 60)
        logger.info("TRAINING COMPLETE")
        logger.info("=" * 60)
        logger.info(f"⏱️  Training time: {elapsed:.1f} seconds")
        logger.info("")
        logger.info("Final Test Metrics:")
        logger.info(f"  MAE (Mean Absolute Error): {metrics['mae']:.2f} minutes")
        logger.info(f"  RMSE (Root Mean Squared Error): {metrics['rmse']:.2f} minutes")
        logger.info(f"  R² (Coefficient of Determination): {metrics['r2']:.3f}")
        logger.info(f"  Bias (Mean Signed Error): {metrics['bias']:.2f} minutes")
        logger.info(f"  Correlation: {metrics['correlation']:.3f}")
        logger.info("")
        logger.info("Training Data:")
        logger.info(f"  Training samples: {metrics['n_train']:,}")
        logger.info(f"  Validation samples: {metrics['n_val']:,}")
        logger.info(f"  Test samples: {metrics['n_test']:,}")
        logger.info("")
        logger.info("Model saved to:")
        logger.info(f"  {output_base}/models/_conversion/model.json")
        logger.info(f"  {output_base}/models/_conversion/metadata.json")
        logger.info("=" * 60)
        
        # Success
        sys.exit(0)
        
    except Exception as e:
        logger.exception(f"Training failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()