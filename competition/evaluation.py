"""
Evaluation Harness — Score challengers, build leaderboards, detect blend opportunities.

Runs daily after actuals arrive. Computes:
- Per-entity, per-challenger MAE and bias
- Rolling window analysis (7d, 30d, 90d)
- Leaderboard rankings
- Error correlation matrix for blend detection
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    EVALUATION_DIR,
    ROLLING_WINDOWS,
    BLEND_MAE_THRESHOLD,
    BLENDS_DIR,
)
from .ledger import read_ledger

logger = logging.getLogger(__name__)


def score_daily(eval_date: str | date | None = None) -> pd.DataFrame:
    """
    Score all challengers for a specific date.

    Computes MAE and bias per (challenger, entity) for the given date.

    Returns:
        DataFrame with columns: [prediction_date, entity_code, challenger_id, 
                                  predicted_actual, actual_wait, error, abs_error, bias]
    """
    if eval_date is None:
        eval_date = (date.today() - timedelta(days=1)).isoformat()
    eval_date = str(eval_date)

    ledger = read_ledger(start_date=eval_date, end_date=eval_date)

    if ledger.empty:
        logger.warning(f"No ledger entries for {eval_date}")
        return pd.DataFrame()

    # Filter to rows that have actuals
    scored = ledger[ledger["actual_wait"].notna()].copy()
    if scored.empty:
        logger.warning(f"No actuals available for {eval_date}")
        return pd.DataFrame()

    scored["error"] = scored["predicted_actual"] - scored["actual_wait"]
    scored["abs_error"] = scored["error"].abs()
    scored["bias"] = scored["error"]  # Positive = overprediction

    return scored


def compute_rolling_scores(
    end_date: str | date | None = None,
    windows: list[int] | None = None,
) -> pd.DataFrame:
    """
    Compute rolling-window MAE and bias per (challenger, entity).

    Args:
        end_date: End of evaluation window
        windows: List of window sizes in days (default: [7, 30, 90])

    Returns:
        DataFrame with columns: [challenger_id, entity_code, window_days, 
                                  mae, bias, n_days, start_date, end_date]
    """
    if windows is None:
        windows = ROLLING_WINDOWS
    if end_date is None:
        end_date = (date.today() - timedelta(days=1))
    end_date = pd.to_datetime(end_date).date()

    max_window = max(windows)
    start_date = end_date - timedelta(days=max_window)

    ledger = read_ledger(start_date=str(start_date), end_date=str(end_date))
    if ledger.empty:
        return pd.DataFrame()

    scored = ledger[ledger["actual_wait"].notna()].copy()
    if scored.empty:
        return pd.DataFrame()

    scored["error"] = scored["predicted_actual"] - scored["actual_wait"]
    scored["abs_error"] = scored["error"].abs()

    results = []
    for window in windows:
        window_start = end_date - timedelta(days=window)
        window_data = scored[scored["prediction_date"] >= window_start]

        if window_data.empty:
            continue

        grouped = window_data.groupby(["challenger_id", "entity_code"]).agg(
            mae=("abs_error", "mean"),
            bias=("error", "mean"),
            n_days=("prediction_date", "nunique"),
        ).reset_index()

        grouped["window_days"] = window
        grouped["start_date"] = str(window_start)
        grouped["end_date"] = str(end_date)
        results.append(grouped)

    if not results:
        return pd.DataFrame()

    return pd.concat(results, ignore_index=True)


def compute_entity_rankings(
    rolling_scores: pd.DataFrame | None = None,
    window_days: int = 30,
) -> pd.DataFrame:
    """
    Rank challengers per entity based on rolling MAE.

    Returns:
        DataFrame with columns: [entity_code, challenger_id, mae, rank, 
                                  is_best, beats_baseline]
    """
    if rolling_scores is None:
        rolling_scores = compute_rolling_scores()

    if rolling_scores.empty:
        return pd.DataFrame()

    window_data = rolling_scores[rolling_scores["window_days"] == window_days].copy()
    if window_data.empty:
        return pd.DataFrame()

    # Rank within each entity
    window_data["rank"] = window_data.groupby("entity_code")["mae"].rank(method="min")
    window_data["is_best"] = window_data["rank"] == 1

    # Check if each challenger beats baseline for each entity
    baseline = window_data[window_data["challenger_id"] == "baseline"][
        ["entity_code", "mae"]
    ].rename(columns={"mae": "baseline_mae"})

    if not baseline.empty:
        window_data = window_data.merge(baseline, on="entity_code", how="left")
        window_data["beats_baseline"] = window_data["mae"] < window_data["baseline_mae"]
        window_data.drop(columns=["baseline_mae"], inplace=True)
    else:
        window_data["beats_baseline"] = False

    return window_data.sort_values(["entity_code", "rank"]).reset_index(drop=True)


def compute_overall_rankings(
    entity_rankings: pd.DataFrame | None = None,
    window_days: int = 30,
) -> pd.DataFrame:
    """
    Compute overall challenger rankings (mean entity rank).

    Returns:
        DataFrame with columns: [challenger_id, mean_rank, median_mae, 
                                  entity_coverage, n_entities, overall_rank]
    """
    if entity_rankings is None:
        entity_rankings = compute_entity_rankings(window_days=window_days)

    if entity_rankings.empty:
        return pd.DataFrame()

    overall = entity_rankings.groupby("challenger_id").agg(
        mean_rank=("rank", "mean"),
        median_mae=("mae", "median"),
        mean_mae=("mae", "mean"),
        entity_coverage=("beats_baseline", "mean"),  # % of entities beating baseline
        n_entities=("entity_code", "nunique"),
    ).reset_index()

    overall["overall_rank"] = overall["mean_rank"].rank(method="min").astype(int)
    overall = overall.sort_values("overall_rank").reset_index(drop=True)

    return overall


def compute_error_correlation(
    end_date: str | date | None = None,
    window_days: int = 30,
) -> pd.DataFrame:
    """
    Compute error correlation matrix between challengers.
    
    Low correlation = high blend potential (models make different mistakes).

    Returns:
        DataFrame pivot: index=challenger_id, columns=challenger_id, values=correlation
    """
    if end_date is None:
        end_date = (date.today() - timedelta(days=1))
    end_date = pd.to_datetime(end_date).date()
    start_date = end_date - timedelta(days=window_days)

    ledger = read_ledger(start_date=str(start_date), end_date=str(end_date))
    if ledger.empty:
        return pd.DataFrame()

    scored = ledger[ledger["actual_wait"].notna()].copy()
    if scored.empty or scored["challenger_id"].nunique() < 2:
        return pd.DataFrame()

    scored["error"] = scored["predicted_actual"] - scored["actual_wait"]

    # Pivot: rows=(prediction_date, entity_code), columns=challenger_id, values=error
    pivot = scored.pivot_table(
        index=["prediction_date", "entity_code"],
        columns="challenger_id",
        values="error",
    )

    # Drop columns with too many NaNs
    pivot = pivot.dropna(axis=1, thresh=len(pivot) * 0.3)

    if pivot.shape[1] < 2:
        return pd.DataFrame()

    corr = pivot.corr()
    return corr


def generate_leaderboard(
    end_date: str | date | None = None,
    window_days: int = 30,
    output_path: Path | None = None,
) -> dict:
    """
    Generate the complete leaderboard JSON for Mission Control.

    Returns:
        Leaderboard dict (also written to evaluation/leaderboard.json)
    """
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)

    if end_date is None:
        end_date = (date.today() - timedelta(days=1))
    end_date_str = str(end_date)

    # Compute all metrics
    rolling = compute_rolling_scores(end_date=end_date)
    entity_ranks = compute_entity_rankings(rolling_scores=rolling, window_days=window_days)
    overall_ranks = compute_overall_rankings(entity_rankings=entity_ranks, window_days=window_days)
    corr_matrix = compute_error_correlation(end_date=end_date, window_days=window_days)

    # Build leaderboard
    leaderboard = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "evaluation_date": end_date_str,
        "window_days": window_days,
        "overall_rankings": [],
        "entity_heatmap": {},
        "blend_opportunities": [],
        "summary": {},
    }

    # Overall rankings
    if not overall_ranks.empty:
        for _, row in overall_ranks.iterrows():
            leaderboard["overall_rankings"].append({
                "challenger_id": row["challenger_id"],
                "overall_rank": int(row["overall_rank"]),
                "mean_rank": round(float(row["mean_rank"]), 2),
                "mean_mae": round(float(row["mean_mae"]), 2),
                "median_mae": round(float(row["median_mae"]), 2),
                "entity_coverage": round(float(row["entity_coverage"]) * 100, 1),
                "n_entities": int(row["n_entities"]),
            })

    # Entity heatmap (top entities only to keep JSON manageable)
    if not entity_ranks.empty:
        # Get top-20 entities by number of observations
        top_entities = (
            entity_ranks.groupby("entity_code")["n_days"]
            .max()
            .nlargest(40)
            .index.tolist()
        )
        for entity in top_entities:
            entity_data = entity_ranks[entity_ranks["entity_code"] == entity]
            leaderboard["entity_heatmap"][entity] = {
                row["challenger_id"]: {
                    "mae": round(float(row["mae"]), 2),
                    "rank": int(row["rank"]),
                    "bias": round(float(row["bias"]), 2),
                }
                for _, row in entity_data.iterrows()
            }

    # Blend opportunities (low error correlation pairs)
    if not corr_matrix.empty:
        challengers = corr_matrix.columns.tolist()
        for i, c1 in enumerate(challengers):
            for c2 in challengers[i + 1:]:
                corr_val = corr_matrix.loc[c1, c2]
                if not pd.isna(corr_val) and corr_val < 0.85:
                    # Check if MAEs are within threshold
                    if not overall_ranks.empty:
                        maes = overall_ranks.set_index("challenger_id")["mean_mae"]
                        if c1 in maes.index and c2 in maes.index:
                            mae1, mae2 = maes[c1], maes[c2]
                            mae_ratio = abs(mae1 - mae2) / max(mae1, mae2)
                            if mae_ratio <= BLEND_MAE_THRESHOLD:
                                leaderboard["blend_opportunities"].append({
                                    "challenger_1": c1,
                                    "challenger_2": c2,
                                    "error_correlation": round(float(corr_val), 3),
                                    "mae_1": round(float(mae1), 2),
                                    "mae_2": round(float(mae2), 2),
                                    "blend_potential": "high" if corr_val < 0.5 else "medium",
                                })

    # Summary
    leaderboard["summary"] = {
        "total_challengers": len(overall_ranks) if not overall_ranks.empty else 0,
        "total_entities_evaluated": entity_ranks["entity_code"].nunique() if not entity_ranks.empty else 0,
        "leader": overall_ranks.iloc[0]["challenger_id"] if not overall_ranks.empty else None,
        "blend_opportunities_count": len(leaderboard["blend_opportunities"]),
    }

    # Write to file
    if output_path is None:
        output_path = EVALUATION_DIR / "leaderboard.json"
    with open(output_path, "w") as f:
        json.dump(leaderboard, f, indent=2, default=str)
    logger.info(f"Leaderboard written to {output_path}")

    # Also save rolling scores and entity rankings as parquet
    if not rolling.empty:
        rolling.to_parquet(EVALUATION_DIR / "rolling_scores.parquet", index=False)
    if not entity_ranks.empty:
        entity_ranks.to_parquet(EVALUATION_DIR / "daily_scores.parquet", index=False)
    if not corr_matrix.empty:
        corr_matrix.to_parquet(EVALUATION_DIR / "correlation_matrix.parquet")

    return leaderboard


def find_blend_opportunities(
    end_date: str | date | None = None,
    window_days: int = 30,
    weight_step: float = 0.05,
) -> pd.DataFrame:
    """
    Grid search over blend weights for challenger pairs with low error correlation.

    Tests blending predictions from two challengers and measures resulting MAE.

    Returns:
        DataFrame with columns: [challenger_1, challenger_2, weight_1, weight_2,
                                  entity_code, blended_mae, best_individual_mae, improvement_pct]
    """
    if end_date is None:
        end_date = (date.today() - timedelta(days=1))
    end_date = pd.to_datetime(end_date).date()
    start_date = end_date - timedelta(days=window_days)

    ledger = read_ledger(start_date=str(start_date), end_date=str(end_date))
    if ledger.empty:
        return pd.DataFrame()

    scored = ledger[ledger["actual_wait"].notna()].copy()
    if scored.empty or scored["challenger_id"].nunique() < 2:
        return pd.DataFrame()

    challengers = sorted(scored["challenger_id"].unique())
    weights = np.arange(0.0, 1.0 + weight_step, weight_step)

    results = []
    for i, c1 in enumerate(challengers):
        for c2 in challengers[i + 1:]:
            # Get predictions for both challengers
            d1 = scored[scored["challenger_id"] == c1][
                ["prediction_date", "entity_code", "predicted_actual", "actual_wait"]
            ].rename(columns={"predicted_actual": "pred_1"})

            d2 = scored[scored["challenger_id"] == c2][
                ["prediction_date", "entity_code", "predicted_actual"]
            ].rename(columns={"predicted_actual": "pred_2"})

            merged = d1.merge(d2, on=["prediction_date", "entity_code"], how="inner")
            if merged.empty:
                continue

            # Individual MAEs per entity
            mae_1_by_entity = merged.groupby("entity_code").apply(
                lambda g: (g["pred_1"] - g["actual_wait"]).abs().mean()
            )
            mae_2_by_entity = merged.groupby("entity_code").apply(
                lambda g: (g["pred_2"] - g["actual_wait"]).abs().mean()
            )

            for entity in merged["entity_code"].unique():
                entity_data = merged[merged["entity_code"] == entity]
                best_individual = min(
                    mae_1_by_entity.get(entity, float("inf")),
                    mae_2_by_entity.get(entity, float("inf")),
                )

                best_blend_mae = float("inf")
                best_w1 = 0.5

                for w1 in weights:
                    w2 = 1.0 - w1
                    blended = w1 * entity_data["pred_1"] + w2 * entity_data["pred_2"]
                    blend_mae = (blended - entity_data["actual_wait"]).abs().mean()
                    if blend_mae < best_blend_mae:
                        best_blend_mae = blend_mae
                        best_w1 = w1

                improvement = (best_individual - best_blend_mae) / best_individual * 100

                results.append({
                    "challenger_1": c1,
                    "challenger_2": c2,
                    "weight_1": round(best_w1, 2),
                    "weight_2": round(1.0 - best_w1, 2),
                    "entity_code": entity,
                    "blended_mae": round(float(best_blend_mae), 3),
                    "best_individual_mae": round(float(best_individual), 3),
                    "improvement_pct": round(float(improvement), 2),
                    "n_observations": len(entity_data),
                })

    if not results:
        return pd.DataFrame()

    result_df = pd.DataFrame(results)

    # Save to blends directory
    BLENDS_DIR.mkdir(parents=True, exist_ok=True)
    result_df.to_parquet(BLENDS_DIR / "blend_results.parquet", index=False)
    logger.info(f"Blend analysis: {len(result_df)} entity-pair results saved")

    return result_df
