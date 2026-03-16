"""
Prediction Ledger — The immutable record of all model predictions.

Every row = one model's prediction for one entity on one day.
Monthly parquet partitions for efficient querying.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .config import LEDGER_DIR

logger = logging.getLogger(__name__)

# Ledger schema
LEDGER_SCHEMA = pa.schema([
    pa.field("prediction_date", pa.date32()),       # The date being predicted
    pa.field("entity_code", pa.string()),            # e.g., MK01, AK07
    pa.field("challenger_id", pa.string()),          # e.g., "baseline", "xgb-highLR"
    pa.field("predicted_actual", pa.float32()),      # Predicted daily mean actual wait
    pa.field("actual_wait", pa.float32()),           # Ground truth (filled later)
    pa.field("submitted_at", pa.timestamp("us")),    # When prediction was submitted
])


def _ledger_path(year: int, month: int) -> Path:
    """Get path for a monthly ledger partition."""
    return LEDGER_DIR / f"predictions_{year:04d}-{month:02d}.parquet"


def submit_predictions(
    predictions: pd.DataFrame,
    challenger_id: str,
    prediction_date: str | None = None,
) -> int:
    """
    Submit a batch of predictions to the ledger.

    Args:
        predictions: DataFrame with columns [entity_code, prediction_date, predicted_actual]
        challenger_id: Unique identifier for the challenger
        prediction_date: Override date (ISO format). If None, uses dates from DataFrame.

    Returns:
        Number of rows submitted
    """
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)

    if predictions.empty:
        logger.warning(f"No predictions to submit for {challenger_id}")
        return 0

    # Normalize the DataFrame
    df = predictions.copy()
    df["challenger_id"] = challenger_id
    df["submitted_at"] = datetime.utcnow()

    if prediction_date is not None:
        df["prediction_date"] = pd.to_datetime(prediction_date).date()
    else:
        df["prediction_date"] = pd.to_datetime(df["prediction_date"]).dt.date

    # Ensure predicted_actual is float
    df["predicted_actual"] = df["predicted_actual"].astype("float32")

    # Add actual_wait as NaN (filled later by evaluation harness)
    if "actual_wait" not in df.columns:
        df["actual_wait"] = float("nan")
    df["actual_wait"] = df["actual_wait"].astype("float32")

    # Select and reorder columns
    df = df[["prediction_date", "entity_code", "challenger_id",
             "predicted_actual", "actual_wait", "submitted_at"]]

    # Partition by month and append
    submitted = 0
    for (year, month), group in df.groupby(
        [df["prediction_date"].apply(lambda d: d.year),
         df["prediction_date"].apply(lambda d: d.month)]
    ):
        path = _ledger_path(year, month)
        table = pa.Table.from_pandas(group, schema=LEDGER_SCHEMA, preserve_index=False)

        if path.exists():
            existing = pq.read_table(path)
            # Dedup: remove any existing rows for same (prediction_date, entity_code, challenger_id)
            existing_df = existing.to_pandas()
            merged = pd.concat([existing_df, group], ignore_index=True)
            merged = merged.drop_duplicates(
                subset=["prediction_date", "entity_code", "challenger_id"],
                keep="last"
            )
            table = pa.Table.from_pandas(merged, schema=LEDGER_SCHEMA, preserve_index=False)

        pq.write_table(table, path, compression="zstd")
        submitted += len(group)
        logger.info(f"Ledger: wrote {len(group)} rows to {path.name}")

    return submitted


def backfill_actuals(actuals: pd.DataFrame) -> int:
    """
    Fill in actual_wait values for predictions that have been scored.

    Args:
        actuals: DataFrame with [entity_code, prediction_date, actual_wait]

    Returns:
        Number of rows updated
    """
    if actuals.empty:
        return 0

    actuals = actuals.copy()
    actuals["prediction_date"] = pd.to_datetime(actuals["prediction_date"]).dt.date
    actuals["actual_wait"] = actuals["actual_wait"].astype("float32")

    updated = 0
    for (year, month), group in actuals.groupby(
        [actuals["prediction_date"].apply(lambda d: d.year),
         actuals["prediction_date"].apply(lambda d: d.month)]
    ):
        path = _ledger_path(year, month)
        if not path.exists():
            continue

        df = pq.read_table(path).to_pandas()
        actuals_map = group.set_index(["entity_code", "prediction_date"])["actual_wait"]

        mask = df.apply(
            lambda row: (row["entity_code"], row["prediction_date"]) in actuals_map.index,
            axis=1,
        )
        if mask.any():
            for idx in df[mask].index:
                key = (df.loc[idx, "entity_code"], df.loc[idx, "prediction_date"])
                if key in actuals_map.index:
                    df.loc[idx, "actual_wait"] = actuals_map[key]
                    updated += 1

            table = pa.Table.from_pandas(df, schema=LEDGER_SCHEMA, preserve_index=False)
            pq.write_table(table, path, compression="zstd")
            logger.info(f"Backfilled {mask.sum()} actuals in {path.name}")

    return updated


def read_ledger(
    start_date: str | None = None,
    end_date: str | None = None,
    challenger_ids: list[str] | None = None,
    entity_codes: list[str] | None = None,
) -> pd.DataFrame:
    """
    Read predictions from the ledger with optional filters.

    Returns:
        DataFrame with all ledger columns
    """
    if not LEDGER_DIR.exists():
        return pd.DataFrame(columns=[f.name for f in LEDGER_SCHEMA])

    files = sorted(LEDGER_DIR.glob("predictions_*.parquet"))
    if not files:
        return pd.DataFrame(columns=[f.name for f in LEDGER_SCHEMA])

    # Filter files by date range (approximate month-level filtering)
    if start_date or end_date:
        filtered_files = []
        for f in files:
            # Extract year-month from filename
            parts = f.stem.replace("predictions_", "").split("-")
            if len(parts) == 2:
                file_year, file_month = int(parts[0]), int(parts[1])
                if start_date:
                    sd = pd.to_datetime(start_date)
                    if file_year < sd.year or (file_year == sd.year and file_month < sd.month):
                        continue
                if end_date:
                    ed = pd.to_datetime(end_date)
                    if file_year > ed.year or (file_year == ed.year and file_month > ed.month):
                        continue
            filtered_files.append(f)
        files = filtered_files

    if not files:
        return pd.DataFrame(columns=[f.name for f in LEDGER_SCHEMA])

    dfs = [pq.read_table(f).to_pandas() for f in files]
    df = pd.concat(dfs, ignore_index=True)

    # Apply row-level filters
    if start_date:
        df = df[df["prediction_date"] >= pd.to_datetime(start_date).date()]
    if end_date:
        df = df[df["prediction_date"] <= pd.to_datetime(end_date).date()]
    if challenger_ids:
        df = df[df["challenger_id"].isin(challenger_ids)]
    if entity_codes:
        df = df[df["entity_code"].isin(entity_codes)]

    return df.sort_values(["prediction_date", "entity_code", "challenger_id"]).reset_index(drop=True)


def ledger_stats() -> dict:
    """Get summary statistics about the ledger."""
    df = read_ledger()
    if df.empty:
        return {"total_rows": 0, "challengers": [], "date_range": None}

    return {
        "total_rows": len(df),
        "challengers": sorted(df["challenger_id"].unique().tolist()),
        "entities": df["entity_code"].nunique(),
        "date_range": {
            "start": str(df["prediction_date"].min()),
            "end": str(df["prediction_date"].max()),
        },
        "rows_with_actuals": int(df["actual_wait"].notna().sum()),
        "rows_without_actuals": int(df["actual_wait"].isna().sum()),
    }
