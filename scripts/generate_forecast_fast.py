#!/usr/bin/env python3
"""
Fast Forecast Generation - Parallel by Entity

Generates forecasts for all entities in parallel using ProcessPoolExecutor.
Much faster than sequential generate_forecast.py.

Usage:
    python scripts/generate_forecast_fast.py [--workers N] [--max-entities N]
"""

import argparse
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

# Add src to path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.paths import get_output_base

# Default workers
DEFAULT_WORKERS = 8


def setup_logging(output_base: Path):
    log_dir = output_base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    from datetime import datetime
    log_file = log_dir / f"forecast_fast_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


def generate_entity_forecasts(args):
    """Generate all forecasts for a single entity (worker function)."""
    entity_code, start_date, end_date, output_base = args
    
    # Import inside worker to avoid pickling issues
    import subprocess
    from pathlib import Path
    
    project_root = Path(__file__).parent.parent
    venv_python = project_root / ".venv" / "bin" / "python"
    
    try:
        result = subprocess.run(
            [
                str(venv_python),
                "scripts/generate_forecast.py",
                "--entity", entity_code,
                "--start-date", start_date,
                "--end-date", end_date,
                "--output-base", str(output_base),
            ],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour max per entity
        )
        
        if result.returncode == 0:
            return entity_code, True, "OK"
        else:
            return entity_code, False, result.stderr[:200]
    
    except subprocess.TimeoutExpired:
        return entity_code, False, "Timeout"
    except Exception as e:
        return entity_code, False, str(e)[:200]


def main():
    parser = argparse.ArgumentParser(description="Fast parallel forecast generation")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Number of parallel workers")
    parser.add_argument("--output-base", type=str, help="Pipeline output base")
    parser.add_argument("--max-entities", type=int, help="Limit entities (for testing)")
    parser.add_argument("--start-date", type=str, help="Start date (default: tomorrow)")
    parser.add_argument("--end-date", type=str, help="End date (default: +2 years)")
    args = parser.parse_args()
    
    output_base = Path(args.output_base) if args.output_base else get_output_base()
    logger = setup_logging(output_base)
    
    # Date range
    start = date.today() + timedelta(days=1) if not args.start_date else date.fromisoformat(args.start_date)
    end = start + timedelta(days=730) if not args.end_date else date.fromisoformat(args.end_date)
    
    logger.info("=" * 60)
    logger.info("FAST FORECAST GENERATION (Parallel)")
    logger.info("=" * 60)
    logger.info(f"Workers: {args.workers}")
    logger.info(f"Date range: {start} to {end}")
    
    # Get entities with models
    models_dir = output_base / "models"
    if not models_dir.exists():
        logger.error(f"Models directory not found: {models_dir}")
        return 1
    
    entities = [d.name for d in models_dir.iterdir() if d.is_dir() and (d / "model.json").exists()]
    
    # Also check for Julia models
    julia_entities = [d.name for d in models_dir.iterdir() if d.is_dir() and (d / "model_julia.json").exists()]
    entities = list(set(entities + julia_entities))
    entities.sort()
    
    if args.max_entities:
        entities = entities[:args.max_entities]
    
    logger.info(f"Entities with models: {len(entities)}")
    
    # Prepare work items
    work_items = [
        (entity, start.isoformat(), end.isoformat(), output_base)
        for entity in entities
    ]
    
    # Process in parallel
    logger.info(f"Starting parallel forecast generation...")
    start_time = time.time()
    
    successful = 0
    failed = 0
    
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(generate_entity_forecasts, item): item[0] for item in work_items}
        
        for i, future in enumerate(as_completed(futures), 1):
            entity = futures[future]
            entity_code, success, msg = future.result()
            
            if success:
                successful += 1
            else:
                failed += 1
                logger.warning(f"Failed {entity_code}: {msg}")
            
            if i % 10 == 0 or i == len(entities):
                elapsed = time.time() - start_time
                rate = i / elapsed * 60
                logger.info(f"Progress: {i}/{len(entities)} ({successful} OK, {failed} failed) - {rate:.1f} entities/min")
    
    elapsed = time.time() - start_time
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("FORECAST GENERATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Time: {elapsed/60:.1f} minutes")
    logger.info("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
