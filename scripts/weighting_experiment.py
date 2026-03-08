#!/usr/bin/env python3
"""
Weighting Experiment Framework
==============================
Tests different real:synthetic weighting schemes for XGBoost wait-time models.

Usage:
    python weighting_experiment.py --scheme <scheme> [--entities <entity1,entity2,...>] [--output-dir <dir>]

Schemes:
    real_only        - Train on real data only (no synthetic)
    uniform_3.5      - Current production: real=3.5x, synth=1.0x
    uniform_5        - real=5x, synth=1.0x
    uniform_10       - real=10x, synth=1.0x
    uniform_20       - real=20x, synth=1.0x
    inverse_freq     - Synthetic weight = 1 / log2(n_real + 1) per entity
    adaptive         - Per-entity: less synthetic weight when more real data available
    all              - Run all schemes and produce comparison report

Mirrors the Julia train_v2.jl pipeline:
- Same features (FEATURE_COLS_V2)
- Same geo_decay weighting (half-life=730 days)
- Same chronological 85/15 split
- Same XGBoost hyperparameters (max_depth=10, eta=0.1, etc.)
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

import duckdb
import numpy as np
import xgboost as xgb

# ==============================================================================
# Constants — must mirror Julia train_v2.jl exactly
# ==============================================================================

FEATURE_COLS = [
    "posted_time",
    "mins_since_6am",
    "mins_since_open",
    "hour_of_day",
    "date_group_id_encoded",
    "season_encoded",
    "season_year_encoded",
]

XGB_PARAMS = {
    "max_depth": 10,
    "learning_rate": 0.1,      # eta in Julia
    "min_child_weight": 1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "objective": "reg:squarederror",
    "seed": 42,
    "verbosity": 0,
    "tree_method": "hist",     # Fast CPU training
}

NUM_ROUND = 2000
EARLY_STOPPING = 20
GEO_DECAY_HALFLIFE = 730  # days
TRAIN_SPLIT = 0.85
MIN_SAMPLES = 500

# Data paths
REAL_PAIRS = "/mnt/data/pipeline/matched_pairs/all_pairs_v2.parquet"
SYNTHETIC_PAIRS = "/mnt/data/pipeline/matched_pairs/synthetic_pairs_v2.parquet"
COMBINED_PAIRS = "/mnt/data/pipeline/matched_pairs/combined_pairs_v2.parquet"
DEFAULT_OUTPUT_DIR = "/mnt/data/pipeline/experiments/weighting"

# ==============================================================================
# Experiment entities: 15 entities spanning the full real-data distribution
# Selected to cover low/medium/high real data counts with diverse parks
# ==============================================================================

EXPERIMENT_ENTITIES = [
    # LOW real data (500-1000 real pairs) — synthetic dominates
    "IA14",    #   533 real,  410K synth  (Islands of Adventure)
    "DL02",    #   586 real,  639K synth  (Disneyland)
    "MK45",    #   639 real,  320K synth  (Magic Kingdom)

    # LOW-MED (1000-3000 real pairs)
    "UF64",    #  1,041 real, 376K synth  (Universal Florida)
    "DL16",    #  1,080 real, 671K synth  (Disneyland)
    "CA06",    #  1,210 real, 141K synth  (DCA)

    # MEDIUM (3000-10000 real pairs)
    "DL07",    #  3,554 real, 694K synth  (Disneyland)
    "MK41",    #  4,931 real, 181K synth  (Magic Kingdom)
    "DL40",    #  6,316 real, 637K synth  (Disneyland)

    # HIGH (10000-30000 real pairs)
    "EP155",   # 11,731 real, 478K synth  (EPCOT)
    "AK86",    # 14,206 real, 448K synth  (Animal Kingdom)
    "MK96",    # 23,770 real, 552K synth  (Magic Kingdom)

    # VERY HIGH (30000+ real pairs) — real data rich
    "MK29",    # 34,280 real, 709K synth  (Magic Kingdom)
    "EP09",    # 56,049 real, 667K synth  (EPCOT)
    "MK23",    # 67,303 real, 721K synth  (Magic Kingdom)
]


# ==============================================================================
# Weighting schemes
# ==============================================================================

def compute_weights_real_only(is_synthetic, geo_weights, n_real, n_synth):
    """No synthetic data — mask to zero."""
    weights = geo_weights.copy()
    weights[is_synthetic] = 0.0  # Will be filtered out before training
    return weights, "real_only"


def compute_weights_uniform(ratio):
    """Factory: real=ratio, synth=1.0, both scaled by geo_decay."""
    def _fn(is_synthetic, geo_weights, n_real, n_synth):
        weights = geo_weights.copy()
        weights[~is_synthetic] *= ratio
        weights[is_synthetic] *= 1.0
        return weights, f"uniform_{ratio}"
    return _fn


def compute_weights_inverse_freq(is_synthetic, geo_weights, n_real, n_synth):
    """
    Synthetic weight inversely proportional to log of real data available.
    Entities with lots of real data get less synthetic influence.
    
    synth_multiplier = 1 / log2(n_real + 1)
    real_multiplier  = 3.5 (baseline)
    
    Example: n_real=500  → synth_mult = 1/log2(501) ≈ 0.111
             n_real=5000 → synth_mult = 1/log2(5001) ≈ 0.081
             n_real=50000→ synth_mult = 1/log2(50001)≈ 0.064
    """
    synth_mult = 1.0 / np.log2(n_real + 1)
    real_mult = 3.5
    
    weights = geo_weights.copy()
    weights[~is_synthetic] *= real_mult
    weights[is_synthetic] *= synth_mult
    return weights, f"inverse_freq(synth_mult={synth_mult:.4f})"


def compute_weights_adaptive(is_synthetic, geo_weights, n_real, n_synth):
    """
    Per-entity adaptive weighting based on real sample count.
    
    The idea: when you have very little real data, synthetic data is valuable.
    When you have lots of real data, synthetic becomes noise.
    
    Strategy:
    - real_mult = 3.5 (constant, matches production)
    - synth_mult scales from 1.0 (few real) → 0.05 (lots of real)
    - Transition: sigmoid centered at n_real=10000 with width 5000
    
    synth_mult = 0.05 + 0.95 / (1 + exp((n_real - 10000) / 5000))
    
    n_real=500   → synth_mult ≈ 1.00 (lean heavily on synthetic)
    n_real=5000  → synth_mult ≈ 0.78
    n_real=10000 → synth_mult ≈ 0.52
    n_real=30000 → synth_mult ≈ 0.07
    n_real=60000 → synth_mult ≈ 0.05 (mostly ignore synthetic)
    """
    synth_mult = 0.05 + 0.95 / (1.0 + np.exp((n_real - 10000) / 5000))
    real_mult = 3.5
    
    weights = geo_weights.copy()
    weights[~is_synthetic] *= real_mult
    weights[is_synthetic] *= synth_mult
    return weights, f"adaptive(synth_mult={synth_mult:.4f})"


SCHEMES = {
    "real_only": compute_weights_real_only,
    "uniform_3.5": compute_weights_uniform(3.5),
    "uniform_5": compute_weights_uniform(5.0),
    "uniform_10": compute_weights_uniform(10.0),
    "uniform_20": compute_weights_uniform(20.0),
    "inverse_freq": compute_weights_inverse_freq,
    "adaptive": compute_weights_adaptive,
}


# ==============================================================================
# Data loading (DuckDB)
# ==============================================================================

def load_entity_data(entity_code: str, include_synthetic: bool = True) -> dict:
    """
    Load data for a single entity using DuckDB for memory efficiency.
    Returns dict with numpy arrays for features, labels, weights, and masks.
    """
    con = duckdb.connect()
    
    if include_synthetic:
        query = f"""
        SELECT 
            posted_time, mins_since_6am, 
            COALESCE(mins_since_open, 0) as mins_since_open,
            hour_of_day, date_group_id_encoded, season_encoded, season_year_encoded,
            actual_time, park_date, is_synthetic
        FROM read_parquet('{COMBINED_PAIRS}')
        WHERE entity_code = ?
          AND actual_time > 0
          AND actual_time IS NOT NULL
        ORDER BY park_date, observed_at
        """
    else:
        query = f"""
        SELECT 
            posted_time, mins_since_6am,
            COALESCE(mins_since_open, 0) as mins_since_open,
            hour_of_day, date_group_id_encoded, season_encoded, season_year_encoded,
            actual_time, park_date, false as is_synthetic
        FROM read_parquet('{REAL_PAIRS}')
        WHERE entity_code = ?
          AND actual_time > 0
          AND actual_time IS NOT NULL
        ORDER BY park_date, observed_at
        """
    
    df = con.execute(query, [entity_code]).fetchdf()
    con.close()
    
    if len(df) == 0:
        return None
    
    # Build feature matrix
    X = df[FEATURE_COLS].values.astype(np.float32)
    y = df["actual_time"].values.astype(np.float32)
    is_synthetic = df["is_synthetic"].values.astype(bool)
    
    # Compute geo decay weights: 0.5^(days_old / 730)
    today = date.today()
    park_dates = df["park_date"].values
    # Handle string dates
    if hasattr(park_dates[0], 'date'):
        days_old = np.array([(today - pd.date()).days for pd in park_dates], dtype=np.float32)
    else:
        days_old = np.array([(today - datetime.strptime(str(pd)[:10], "%Y-%m-%d").date()).days 
                             for pd in park_dates], dtype=np.float32)
    
    geo_weights = np.power(0.5, days_old / GEO_DECAY_HALFLIFE).astype(np.float32)
    
    n_real = int((~is_synthetic).sum())
    n_synth = int(is_synthetic.sum())
    
    return {
        "X": X,
        "y": y,
        "is_synthetic": is_synthetic,
        "geo_weights": geo_weights,
        "n_real": n_real,
        "n_synth": n_synth,
        "n_total": len(df),
    }


# ==============================================================================
# Training and evaluation
# ==============================================================================

def train_and_evaluate(entity_code: str, data: dict, weight_fn, holdout_frac: float = 0.15) -> dict:
    """
    Train XGBoost model with given weighting scheme and evaluate.
    
    Returns dict with metrics:
    - mae, rmse, mape, bias on holdout real data
    - training details (n_train, n_val, scheme name)
    """
    X = data["X"]
    y = data["y"]
    is_synthetic = data["is_synthetic"]
    geo_weights = data["geo_weights"]
    n_real = data["n_real"]
    n_synth = data["n_synth"]
    
    # Compute weights for this scheme
    weights, scheme_name = weight_fn(is_synthetic, geo_weights, n_real, n_synth)
    
    # For real_only, filter out synthetic rows entirely
    if "real_only" in scheme_name:
        mask = ~is_synthetic
        X = X[mask]
        y = y[mask]
        weights = weights[mask]
        is_synthetic = is_synthetic[mask]
    
    # Remove zero/nan weight rows
    valid = (weights > 0) & ~np.isnan(weights) & ~np.isnan(y)
    X = X[valid]
    y = y[valid]
    weights = weights[valid]
    is_synthetic_valid = is_synthetic[valid]
    
    if len(y) < MIN_SAMPLES:
        return {
            "entity_code": entity_code,
            "scheme": scheme_name,
            "error": f"Not enough samples after filtering ({len(y)})",
        }
    
    # Chronological split (85/15) — matches Julia exactly
    n = len(y)
    train_end = int(n * TRAIN_SPLIT)
    
    X_train, y_train = X[:train_end], y[:train_end]
    X_val, y_val = X[train_end:], y[train_end:]
    w_train = weights[:train_end]
    is_synth_val = is_synthetic_valid[train_end:]
    
    # Create DMatrix
    dtrain = xgb.DMatrix(X_train, label=y_train, weight=w_train,
                          feature_names=FEATURE_COLS)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_COLS)
    
    # Train
    t0 = time.time()
    bst = xgb.train(
        XGB_PARAMS,
        dtrain,
        num_boost_round=NUM_ROUND,
        evals=[(dtrain, "train"), (dval, "eval")],
        early_stopping_rounds=EARLY_STOPPING,
        verbose_eval=False,
    )
    train_time = time.time() - t0
    
    # Predict
    y_pred = bst.predict(dval)
    
    # === Metrics on ALL validation data ===
    errors = y_val - y_pred
    abs_errors = np.abs(errors)
    
    all_mae = float(np.mean(abs_errors))
    all_rmse = float(np.sqrt(np.mean(errors ** 2)))
    all_bias = float(np.mean(errors))  # positive = model underpredicts
    
    # MAPE (avoid division by zero)
    nonzero = y_val > 0
    all_mape = float(np.mean(np.abs(errors[nonzero]) / y_val[nonzero]) * 100) if nonzero.any() else None
    
    # === Metrics on REAL validation data only (what actually matters) ===
    real_mask = ~is_synth_val
    n_real_val = int(real_mask.sum())
    
    if n_real_val > 0:
        real_errors = errors[real_mask]
        real_abs = np.abs(real_errors)
        real_y = y_val[real_mask]
        
        real_mae = float(np.mean(real_abs))
        real_rmse = float(np.sqrt(np.mean(real_errors ** 2)))
        real_bias = float(np.mean(real_errors))
        real_median_ae = float(np.median(real_abs))
        real_p90_ae = float(np.percentile(real_abs, 90))
        
        nonzero_real = real_y > 0
        real_mape = float(np.mean(np.abs(real_errors[nonzero_real]) / real_y[nonzero_real]) * 100) if nonzero_real.any() else None
    else:
        real_mae = real_rmse = real_bias = real_median_ae = real_p90_ae = real_mape = None
    
    # === Error distribution buckets ===
    if n_real_val > 0:
        real_abs_arr = np.abs(real_errors)
        within_2 = float((real_abs_arr <= 2).mean() * 100)
        within_5 = float((real_abs_arr <= 5).mean() * 100)
        within_10 = float((real_abs_arr <= 10).mean() * 100)
    else:
        within_2 = within_5 = within_10 = None
    
    return {
        "entity_code": entity_code,
        "scheme": scheme_name,
        "n_real": data["n_real"],
        "n_synth": data["n_synth"],
        "n_train": train_end,
        "n_val": n - train_end,
        "n_real_val": n_real_val,
        "best_iteration": bst.best_iteration if hasattr(bst, "best_iteration") else NUM_ROUND,
        "train_time_sec": round(train_time, 2),
        # All-data metrics
        "all_mae": round(all_mae, 3),
        "all_rmse": round(all_rmse, 3),
        "all_bias": round(all_bias, 3),
        # Real-only metrics (primary)
        "real_mae": round(real_mae, 3) if real_mae is not None else None,
        "real_rmse": round(real_rmse, 3) if real_rmse is not None else None,
        "real_bias": round(real_bias, 3) if real_bias is not None else None,
        "real_median_ae": round(real_median_ae, 3) if real_median_ae is not None else None,
        "real_p90_ae": round(real_p90_ae, 3) if real_p90_ae is not None else None,
        "real_mape": round(real_mape, 2) if real_mape is not None else None,
        # Accuracy buckets (on real validation)
        "pct_within_2min": round(within_2, 1) if within_2 is not None else None,
        "pct_within_5min": round(within_5, 1) if within_5 is not None else None,
        "pct_within_10min": round(within_10, 1) if within_10 is not None else None,
    }


# ==============================================================================
# Experiment runner
# ==============================================================================

def run_experiment(scheme_names: list, entity_codes: list, output_dir: str):
    """
    Run weighting experiment for given schemes and entities.
    Saves per-entity results and aggregate comparison.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    all_results = []
    
    for entity_code in entity_codes:
        print(f"\n{'='*60}")
        print(f"Entity: {entity_code}")
        print(f"{'='*60}")
        
        # Load data once per entity (with synthetic)
        data_with_synth = load_entity_data(entity_code, include_synthetic=True)
        if data_with_synth is None:
            print(f"  SKIP: No data found for {entity_code}")
            continue
        
        # Also load real-only for real_only scheme
        data_real_only = load_entity_data(entity_code, include_synthetic=False)
        
        print(f"  Real: {data_with_synth['n_real']:,}  Synthetic: {data_with_synth['n_synth']:,}")
        
        for scheme_name in scheme_names:
            weight_fn = SCHEMES[scheme_name]
            
            # Use real-only data for real_only scheme (more efficient)
            if scheme_name == "real_only":
                data = data_real_only if data_real_only else data_with_synth
            else:
                data = data_with_synth
            
            print(f"\n  Scheme: {scheme_name}")
            result = train_and_evaluate(entity_code, data, weight_fn)
            
            if "error" in result:
                print(f"    ERROR: {result['error']}")
            else:
                print(f"    Real MAE: {result['real_mae']:.2f}  "
                      f"Bias: {result['real_bias']:+.2f}  "
                      f"Within 5min: {result['pct_within_5min']:.1f}%  "
                      f"Iters: {result['best_iteration']}  "
                      f"Time: {result['train_time_sec']:.1f}s")
            
            all_results.append(result)
    
    # Save raw results
    results_path = os.path.join(output_dir, "experiment_results.json")
    with open(results_path, "w") as f:
        json.dump({
            "experiment": "weighting_optimization",
            "run_at": datetime.now().isoformat(),
            "schemes": scheme_names,
            "entities": entity_codes,
            "results": all_results,
        }, f, indent=2)
    print(f"\nResults saved to {results_path}")
    
    # Generate comparison report
    generate_report(all_results, scheme_names, entity_codes, output_dir)
    
    return all_results


def generate_report(results: list, scheme_names: list, entity_codes: list, output_dir: str):
    """Generate a markdown comparison report."""
    
    # Filter to successful results
    valid = [r for r in results if "error" not in r and r.get("real_mae") is not None]
    
    if not valid:
        print("No valid results to report.")
        return
    
    lines = [
        "# Weighting Experiment Results",
        f"\n**Run:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Entities:** {len(entity_codes)}",
        f"**Schemes:** {', '.join(scheme_names)}",
        "",
        "## Aggregate Comparison (Real MAE)",
        "",
        "| Scheme | Mean MAE | Median MAE | Mean Bias | Mean %≤5min | Mean %≤10min |",
        "|--------|----------|------------|-----------|-------------|--------------|",
    ]
    
    for scheme in scheme_names:
        s_results = [r for r in valid if r["scheme"].startswith(scheme.replace("uniform_", "uniform_"))]
        # Fuzzy match for scheme names (adaptive/inverse_freq include params)
        if not s_results:
            s_results = [r for r in valid if scheme in r["scheme"]]
        
        if s_results:
            maes = [r["real_mae"] for r in s_results if r["real_mae"] is not None]
            biases = [r["real_bias"] for r in s_results if r["real_bias"] is not None]
            w5 = [r["pct_within_5min"] for r in s_results if r["pct_within_5min"] is not None]
            w10 = [r["pct_within_10min"] for r in s_results if r["pct_within_10min"] is not None]
            
            mean_mae = np.mean(maes) if maes else float("nan")
            med_mae = np.median(maes) if maes else float("nan")
            mean_bias = np.mean(biases) if biases else float("nan")
            mean_w5 = np.mean(w5) if w5 else float("nan")
            mean_w10 = np.mean(w10) if w10 else float("nan")
            
            lines.append(
                f"| {scheme} | {mean_mae:.2f} | {med_mae:.2f} | {mean_bias:+.2f} | "
                f"{mean_w5:.1f}% | {mean_w10:.1f}% |"
            )
    
    # Per-entity breakdown
    lines.extend([
        "",
        "## Per-Entity Results (Real MAE)",
        "",
    ])
    
    # Header
    header = "| Entity | n_real |"
    sep = "|--------|--------|"
    for scheme in scheme_names:
        short = scheme.replace("uniform_", "u")
        header += f" {short} |"
        sep += "------|"
    lines.append(header)
    lines.append(sep)
    
    for entity in entity_codes:
        e_results = {r["scheme"]: r for r in valid if r["entity_code"] == entity}
        if not e_results:
            continue
        
        n_real = next((r["n_real"] for r in e_results.values()), "?")
        row = f"| {entity} | {n_real:,} |"
        
        for scheme in scheme_names:
            # Find matching result (scheme name in results may include params)
            match = None
            for sname, r in e_results.items():
                if scheme in sname or sname.startswith(scheme):
                    match = r
                    break
            
            if match and match.get("real_mae") is not None:
                mae = match["real_mae"]
                row += f" {mae:.1f} |"
            else:
                row += " — |"
        
        lines.append(row)
    
    # Best scheme per entity
    lines.extend([
        "",
        "## Best Scheme Per Entity",
        "",
        "| Entity | n_real | Best Scheme | MAE | vs Current (3.5) |",
        "|--------|--------|-------------|-----|-------------------|",
    ])
    
    for entity in entity_codes:
        e_results = [r for r in valid if r["entity_code"] == entity and r.get("real_mae") is not None]
        if not e_results:
            continue
        
        best = min(e_results, key=lambda r: r["real_mae"])
        current = next((r for r in e_results if "3.5" in r["scheme"]), None)
        
        diff = ""
        if current and current.get("real_mae") is not None:
            delta = best["real_mae"] - current["real_mae"]
            diff = f"{delta:+.2f} min"
        
        lines.append(
            f"| {entity} | {best['n_real']:,} | {best['scheme']} | "
            f"{best['real_mae']:.2f} | {diff} |"
        )
    
    # Insights
    lines.extend([
        "",
        "## Key Questions to Answer",
        "",
        "1. **Does synthetic data help at all?** Compare `real_only` vs `uniform_3.5`",
        "2. **Is 3.5x the right ratio?** Compare uniform schemes (3.5 vs 5 vs 10 vs 20)",
        "3. **Should weighting be entity-specific?** Compare `adaptive` vs best uniform",
        "4. **Do data-poor entities benefit more from synthetic?** Check low-real entities",
        "5. **Is there a 'sweet spot' real count** where synthetic stops helping?",
    ])
    
    report_path = os.path.join(output_dir, "comparison_report.md")
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Report saved to {report_path}")


# ==============================================================================
# CLI
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Weighting experiment for real vs synthetic training data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--scheme", type=str, default="all",
        choices=list(SCHEMES.keys()) + ["all"],
        help="Weighting scheme to test (default: all)",
    )
    parser.add_argument(
        "--entities", type=str, default=None,
        help="Comma-separated entity codes (default: built-in experiment set)",
    )
    parser.add_argument(
        "--output-dir", type=str, default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Quick mode: only 5 entities, fewer rounds (for testing the framework)",
    )
    
    args = parser.parse_args()
    
    # Select schemes
    if args.scheme == "all":
        scheme_names = list(SCHEMES.keys())
    else:
        scheme_names = [args.scheme]
    
    # Select entities
    if args.entities:
        entity_codes = [e.strip() for e in args.entities.split(",")]
    elif args.quick:
        # Quick test: 5 entities spanning the range
        entity_codes = ["IA14", "DL16", "DL07", "EP155", "MK23"]
    else:
        entity_codes = EXPERIMENT_ENTITIES
    
    # Quick mode: fewer rounds
    if args.quick:
        global NUM_ROUND, EARLY_STOPPING
        NUM_ROUND = 200
        EARLY_STOPPING = 10
        print("⚡ Quick mode: 200 rounds, 10 early stopping")
    
    print(f"Weighting Experiment")
    print(f"{'='*60}")
    print(f"Schemes: {', '.join(scheme_names)}")
    print(f"Entities: {len(entity_codes)} ({', '.join(entity_codes[:5])}...)")
    print(f"Output: {args.output_dir}")
    print(f"XGBoost rounds: {NUM_ROUND} (early stop: {EARLY_STOPPING})")
    
    t0 = time.time()
    results = run_experiment(scheme_names, entity_codes, args.output_dir)
    elapsed = time.time() - t0
    
    print(f"\n{'='*60}")
    print(f"EXPERIMENT COMPLETE")
    print(f"{'='*60}")
    print(f"Total time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"Results: {len(results)} model runs")
    print(f"Output: {args.output_dir}/")


if __name__ == "__main__":
    main()
