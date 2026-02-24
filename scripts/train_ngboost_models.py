#!/usr/bin/env python3
"""
NGBoost Heteroscedastic Model Training

Trains per-entity NGBoost models that predict BOTH mean and variance of actual
wait times. This enables distribution-aware forecasting and solves the WTI
range compression problem caused by XGBoost's mean-only predictions.

Each entity gets:
- ngboost_model.pkl   — pickled NGBRegressor (Normal distribution)
- ngboost_metadata.json — training metrics, feature names, etc.

Uses the same matched-pairs training data and features as the XGBoost pipeline,
with posted_time as the primary feature.

Usage:
    # Train all eligible entities
    python scripts/train_ngboost_models.py

    # Train specific entities (testing)
    python scripts/train_ngboost_models.py --entities MK01 MK05 MK191

    # Use actuals-first data (no posted_time)
    python scripts/train_ngboost_models.py --actuals-first
"""

import argparse
import json
import logging
import os
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, date
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure src is on path
if str(Path(__file__).resolve().parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils.park_code import entity_code_to_park_code

# Constants
DEFAULT_WORKERS = 8
DEFAULT_MIN_SAMPLES = 200  # Minimum training rows per entity
GEO_DECAY_HALFLIFE_DAYS = 730  # 2 years, matching hybrid_pipeline_v2

# Default NGBoost hyperparameters
NGBOOST_PARAMS = {
    "n_estimators": 500,
    "learning_rate": 0.04,
    "minibatch_frac": 0.8,
    "natural_gradient": True,
    "verbose": False,
}

# Feature sets
FEATURES_STANDARD = [
    "posted_time",
    "mins_since_6am",
    "mins_since_open",
    "hour_of_day",
    "date_group_id_encoded",
    "season_encoded",
    "season_year_encoded",
]

FEATURES_ACTUALS = [
    "mins_since_6am",
    "mins_since_open",
    "date_group_id_encoded",
    "season_encoded",
    "season_year_encoded",
]

TARGET = "actual_time"

# Paths
OUTPUT_BASE = Path("/mnt/data/pipeline")
MODELS_DIR = OUTPUT_BASE / "models"
LOGS_DIR = OUTPUT_BASE / "logs"


def setup_logging(log_dir: Path | None = None) -> logging.Logger:
    log_dir = log_dir or LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"train_ngboost_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


def compute_geo_decay_weights(
    observed_at_ts: pd.Series, halflife_days: int = GEO_DECAY_HALFLIFE_DAYS
) -> np.ndarray:
    """Compute geo-decay sample weights: 0.5^(days_since / halflife).

    More recent observations get higher weight. Matches the weighting
    strategy used in the XGBoost training pipeline.
    """
    now = pd.Timestamp.now(tz="America/New_York")
    # Make sure timestamps are tz-aware
    if observed_at_ts.dt.tz is None:
        ts = observed_at_ts.dt.tz_localize("America/New_York")
    else:
        ts = observed_at_ts.dt.tz_convert("America/New_York")
    days_since = (now - ts).dt.total_seconds() / 86400.0
    weights = np.power(0.5, days_since / halflife_days)
    return weights.values.astype(np.float64)


def train_single_entity(args) -> dict:
    """Train an NGBoost model for a single entity. Runs in a worker process."""
    entity_code, entity_df, features, models_dir, min_samples = args

    result = {
        "entity_code": entity_code,
        "status": "failed",
        "n_train": 0,
        "mae": None,
        "rmse": None,
        "mean_std": None,
        "elapsed": 0.0,
        "error": None,
    }

    start = time.time()

    try:
        from ngboost import NGBRegressor
        from ngboost.distns import Normal

        df = entity_df.copy()

        # Drop rows with NaN in features or target
        required_cols = features + [TARGET]
        df = df.dropna(subset=required_cols)

        if len(df) < min_samples:
            result["status"] = "skipped_insufficient"
            result["n_train"] = len(df)
            result["error"] = f"Only {len(df)} samples (need {min_samples})"
            return result

        X = df[features].values.astype(np.float32)
        y = df[TARGET].values.astype(np.float64)

        # Compute geo-decay sample weights
        if "observed_at_ts" in df.columns:
            sample_weight = compute_geo_decay_weights(df["observed_at_ts"])
        else:
            sample_weight = None

        # Train NGBoost model
        model = NGBRegressor(
            Dist=Normal,
            n_estimators=NGBOOST_PARAMS["n_estimators"],
            learning_rate=NGBOOST_PARAMS["learning_rate"],
            minibatch_frac=NGBOOST_PARAMS["minibatch_frac"],
            natural_gradient=NGBOOST_PARAMS["natural_gradient"],
            verbose=NGBOOST_PARAMS["verbose"],
        )

        model.fit(X, y, sample_weight=sample_weight)

        # Evaluate on training set (in-sample metrics for monitoring)
        y_dist = model.pred_dist(X)
        y_pred = y_dist.mean()
        y_std = y_dist.std()

        mae = float(np.mean(np.abs(y - y_pred)))
        rmse = float(np.sqrt(np.mean((y - y_pred) ** 2)))
        mean_std = float(np.mean(y_std))
        median_std = float(np.median(y_std))

        # Save model
        entity_dir = models_dir / entity_code
        entity_dir.mkdir(parents=True, exist_ok=True)

        model_path = entity_dir / "ngboost_model.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(model, f, protocol=pickle.HIGHEST_PROTOCOL)

        # Save metadata
        metadata = {
            "entity_code": entity_code,
            "model_type": "NGBRegressor",
            "distribution": "Normal",
            "features": features,
            "target": TARGET,
            "n_train": int(len(df)),
            "hyperparameters": NGBOOST_PARAMS,
            "metrics": {
                "mae": round(mae, 3),
                "rmse": round(rmse, 3),
                "mean_predicted_std": round(mean_std, 3),
                "median_predicted_std": round(median_std, 3),
                "mean_actual": round(float(y.mean()), 3),
                "std_actual": round(float(y.std()), 3),
            },
            "trained_at": datetime.now().isoformat(),
            "model_file": "ngboost_model.pkl",
            "version": "ngboost_v1",
            "uses_posted_time": "posted_time" in features,
            "geo_decay_halflife_days": GEO_DECAY_HALFLIFE_DAYS,
        }

        metadata_path = entity_dir / "ngboost_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        result.update({
            "status": "success",
            "n_train": int(len(df)),
            "mae": mae,
            "rmse": rmse,
            "mean_std": mean_std,
            "elapsed": time.time() - start,
        })

    except Exception as e:
        import traceback
        result["error"] = f"{str(e)[:200]}\n{traceback.format_exc()[:300]}"
        result["elapsed"] = time.time() - start

    return result


def load_training_data(output_base: Path, actuals_first: bool, logger) -> pd.DataFrame:
    """Load training data from matched pairs or actuals-first data."""
    import duckdb

    if actuals_first:
        # Try actuals-first training data
        actuals_path = output_base / "matched_pairs" / "actuals_training_v2.parquet"
        if actuals_path.exists():
            logger.info(f"Loading actuals-first training data: {actuals_path}")
            con = duckdb.connect()
            df = con.execute(
                f"SELECT * FROM read_parquet('{actuals_path}')"
            ).fetchdf()
            con.close()
            logger.info(f"  Loaded {len(df):,} rows")
            return df
        else:
            logger.warning(
                f"Actuals-first data not found at {actuals_path}, falling back to matched pairs"
            )

    # Standard matched pairs
    pairs_path = output_base / "matched_pairs" / "all_pairs_v2.parquet"
    if not pairs_path.exists():
        logger.error(f"Training data not found: {pairs_path}")
        sys.exit(1)

    logger.info(f"Loading matched pairs: {pairs_path}")
    con = duckdb.connect()
    df = con.execute(f"SELECT * FROM read_parquet('{pairs_path}')").fetchdf()
    con.close()
    logger.info(f"  Loaded {len(df):,} rows")
    return df


def get_eligible_entities(output_base: Path, logger) -> set[str]:
    """Get entity codes where has_posted=TRUE from dimentity."""
    import duckdb

    dimentity_path = output_base / "dimension_tables" / "dimentity.csv"
    if not dimentity_path.exists():
        logger.warning("dimentity.csv not found — training all entities in data")
        return None  # None means "no filter"

    con = duckdb.connect()
    path_str = str(dimentity_path).replace("\\", "/")
    result = con.execute(
        f"SELECT code FROM read_csv_auto('{path_str}') WHERE has_posted = TRUE"
    ).fetchdf()
    con.close()

    entities = set(result["code"].tolist())
    logger.info(f"  Eligible entities (has_posted=TRUE): {len(entities)}")
    return entities


def main():
    parser = argparse.ArgumentParser(description="Train NGBoost heteroscedastic models")
    parser.add_argument("--output-base", type=Path, default=OUTPUT_BASE)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Parallel workers")
    parser.add_argument("--entities", nargs="+", help="Train only these entity codes")
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES, help="Min training rows")
    parser.add_argument("--actuals-first", action="store_true", help="Use actuals-first data (no posted_time)")
    parser.add_argument("--max-entities", type=int, help="Limit entities (testing)")
    args = parser.parse_args()

    output_base = args.output_base.resolve()
    models_dir = output_base / "models"
    logger = setup_logging(output_base / "logs")

    logger.info("=" * 60)
    logger.info("NGBOOST HETEROSCEDASTIC MODEL TRAINING")
    logger.info("=" * 60)
    logger.info(f"Output base: {output_base}")
    logger.info(f"Workers: {args.workers}")
    logger.info(f"Min samples: {args.min_samples}")
    logger.info(f"Actuals-first: {args.actuals_first}")
    logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("")

    total_start = time.time()

    # Determine feature set
    if args.actuals_first:
        features = FEATURES_ACTUALS
    else:
        features = FEATURES_STANDARD
    logger.info(f"Features: {features}")

    # Load training data
    all_data = load_training_data(output_base, args.actuals_first, logger)

    # Get eligible entities
    if args.entities:
        entity_codes = set(args.entities)
        logger.info(f"CLI entity filter: {sorted(entity_codes)}")
    else:
        eligible = get_eligible_entities(output_base, logger)
        entity_codes_in_data = set(all_data["entity_code"].unique())
        if eligible is not None:
            entity_codes = entity_codes_in_data & eligible
        else:
            entity_codes = entity_codes_in_data
        logger.info(f"Entities in data: {len(entity_codes_in_data)}")
        logger.info(f"Entities after has_posted filter: {len(entity_codes)}")

    if args.max_entities:
        entity_codes = set(sorted(entity_codes)[: args.max_entities])
        logger.info(f"Limited to {len(entity_codes)} entities (--max-entities)")

    # Group data by entity
    logger.info("Grouping data by entity...")
    grouped = {
        code: group for code, group in all_data.groupby("entity_code") if code in entity_codes
    }
    logger.info(f"  Prepared {len(grouped)} entity groups")

    # Free the full dataset
    del all_data

    # Build work items
    work_items = [
        (code, df, features, models_dir, args.min_samples) for code, df in grouped.items()
    ]
    work_items.sort(key=lambda x: x[0])  # alphabetical for determinism

    logger.info(f"Training {len(work_items)} entities with {args.workers} workers...")
    logger.info("")

    # Train in parallel
    results = []
    completed = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(train_single_entity, item): item[0] for item in work_items}

        for future in as_completed(futures):
            entity = futures[future]
            try:
                result = future.result()
            except Exception as e:
                result = {
                    "entity_code": entity,
                    "status": "error",
                    "error": str(e)[:200],
                    "n_train": 0,
                    "mae": None,
                    "rmse": None,
                    "mean_std": None,
                    "elapsed": 0.0,
                }

            results.append(result)
            completed += 1

            # Progress logging every 50 entities or on failures
            if completed % 50 == 0 or result["status"] not in ("success",):
                elapsed = time.time() - total_start
                rate = completed / elapsed if elapsed > 0 else 0
                if result["status"] == "success":
                    logger.info(
                        f"  [{completed}/{len(work_items)}] {result['entity_code']}: "
                        f"OK (n={result['n_train']}, MAE={result['mae']:.1f}, "
                        f"σ̄={result['mean_std']:.1f}, {result['elapsed']:.1f}s) "
                        f"[{rate:.1f} ent/sec]"
                    )
                elif result["status"] == "skipped_insufficient":
                    logger.info(
                        f"  [{completed}/{len(work_items)}] {result['entity_code']}: "
                        f"SKIP ({result['error']})"
                    )
                else:
                    logger.warning(
                        f"  [{completed}/{len(work_items)}] {result['entity_code']}: "
                        f"FAIL ({result['error'][:100]})"
                    )

    # Summary
    total_elapsed = time.time() - total_start
    successes = [r for r in results if r["status"] == "success"]
    skipped = [r for r in results if r["status"] == "skipped_insufficient"]
    failures = [r for r in results if r["status"] not in ("success", "skipped_insufficient")]

    logger.info("")
    logger.info("=" * 60)
    logger.info("NGBOOST TRAINING COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Successful: {len(successes)}")
    logger.info(f"Skipped (insufficient data): {len(skipped)}")
    logger.info(f"Failed: {len(failures)}")
    logger.info(f"Total time: {total_elapsed:.1f}s ({total_elapsed / 60:.1f} min)")

    if successes:
        maes = [r["mae"] for r in successes]
        rmses = [r["rmse"] for r in successes]
        stds = [r["mean_std"] for r in successes]
        n_trains = [r["n_train"] for r in successes]
        logger.info(f"")
        logger.info(f"Metrics across {len(successes)} models:")
        logger.info(f"  MAE:  median={np.median(maes):.1f}, mean={np.mean(maes):.1f}, "
                     f"min={np.min(maes):.1f}, max={np.max(maes):.1f}")
        logger.info(f"  RMSE: median={np.median(rmses):.1f}, mean={np.mean(rmses):.1f}")
        logger.info(f"  σ̄:    median={np.median(stds):.1f}, mean={np.mean(stds):.1f}")
        logger.info(f"  Training rows: median={int(np.median(n_trains))}, "
                     f"total={sum(n_trains):,}")

    if failures:
        logger.info("")
        logger.info("Failed entities:")
        for r in failures[:10]:
            logger.info(f"  {r['entity_code']}: {r['error'][:120]}")
        if len(failures) > 10:
            logger.info(f"  ... and {len(failures) - 10} more")

    # Save training summary
    summary_path = output_base / "state" / "ngboost_training_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "trained_at": datetime.now().isoformat(),
        "n_successful": len(successes),
        "n_skipped": len(skipped),
        "n_failed": len(failures),
        "features": features,
        "actuals_first": args.actuals_first,
        "hyperparameters": NGBOOST_PARAMS,
        "total_elapsed_sec": round(total_elapsed, 1),
        "entities_trained": sorted([r["entity_code"] for r in successes]),
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Summary saved: {summary_path}")

    logger.info("=" * 60)

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
