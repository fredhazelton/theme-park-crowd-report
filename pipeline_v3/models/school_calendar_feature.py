"""School Calendar Feature Integration for v4.

Loads the daily_aggregate CSV and provides a date → pct_on_break lookup
that can be merged into training and forecast DataFrames.

This is the synergy between hazeydata's two products:
- School calendar data makes crowd predictions better
- Better crowd predictions validate school calendar data's value

Usage in training:
    from pipeline_v3.models.school_calendar_feature import enrich_with_school_calendar
    entity_df = enrich_with_school_calendar(entity_df, cfg)
    # Now entity_df has 'pct_on_break' and 'is_break_season' columns

Usage in forecasting:
    forecast_grid = enrich_with_school_calendar(forecast_grid, cfg)
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from functools import lru_cache

import pandas as pd
import numpy as np

from pipeline_v3.config import PipelineConfig


# Where to find the school calendar data
# Check multiple locations in priority order
CALENDAR_PATHS = [
    "data/school_schedules/daily_aggregate_v3.csv",
    "data/school_schedules/daily_aggregate_v2.csv",
    "data/school_schedules/daily_aggregate.csv",
]


def _find_calendar_file(cfg: PipelineConfig) -> Path | None:
    """Find the school calendar aggregate file."""
    # Check relative to repo root (when running from repo)
    repo_root = cfg.output_base.parent / "theme-park-crowd-report"
    for rel_path in CALENDAR_PATHS:
        p = repo_root / rel_path
        if p.exists():
            return p

    # Check relative to output_base (when file is deployed alongside pipeline data)
    for rel_path in CALENDAR_PATHS:
        p = cfg.output_base / rel_path
        if p.exists():
            return p

    # Check in state dir (where Wilma might copy it)
    state_file = cfg.state_dir / "school_calendar_daily.csv"
    if state_file.exists():
        return state_file

    return None


def load_calendar_lookup(cfg: PipelineConfig) -> dict[str, float] | None:
    """Load school calendar data as a date string → pct_on_break lookup.

    Returns dict of {'2026-03-16': 26.7, '2026-03-30': 35.6, ...}
    or None if no calendar file found.
    """
    path = _find_calendar_file(cfg)
    if path is None:
        return None

    lookup = {}
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_str = row.get("date", "").strip()
            pct = row.get("pct_on_break", "0")
            if date_str:
                try:
                    lookup[date_str] = float(pct)
                except (ValueError, TypeError):
                    pass

    return lookup if lookup else None


def enrich_with_school_calendar(
    df: pd.DataFrame,
    cfg: PipelineConfig,
    date_column: str = "park_date",
) -> pd.DataFrame:
    """Add school calendar features to a DataFrame.

    Adds columns:
    - pct_on_break: national % of students on break (0-100)
    - is_break_season: binary flag, 1 if pct_on_break > 15%
    - break_intensity: bucketed (0=normal, 1=low_break, 2=moderate, 3=peak)

    If no calendar data is available, adds columns with neutral defaults
    (pct_on_break=0, is_break_season=0, break_intensity=0) so models
    still train without errors.
    """
    df = df.copy()
    lookup = load_calendar_lookup(cfg)

    if lookup is None:
        # No calendar data — add neutral defaults
        df["pct_on_break"] = 0.0
        df["is_break_season"] = 0
        df["break_intensity"] = 0
        return df

    # Convert park_date to string for lookup
    if date_column in df.columns:
        date_strings = pd.to_datetime(df[date_column]).dt.strftime("%Y-%m-%d")
        df["pct_on_break"] = date_strings.map(lookup).fillna(0.0).astype(np.float32)
    else:
        df["pct_on_break"] = 0.0

    # Binary: is this a significant break period?
    df["is_break_season"] = (df["pct_on_break"] > 15.0).astype(np.int8)

    # Bucketed intensity for the model to use as a categorical-like feature
    # 0 = normal school day (0-5% on break)
    # 1 = light break period (5-15%)
    # 2 = moderate break (15-35%)
    # 3 = peak break (>35% — peak spring break, summer, holidays)
    conditions = [
        df["pct_on_break"] <= 5,
        df["pct_on_break"] <= 15,
        df["pct_on_break"] <= 35,
        df["pct_on_break"] > 35,
    ]
    choices = [0, 1, 2, 3]
    df["break_intensity"] = np.select(conditions, choices, default=0).astype(np.int8)

    return df


def get_calendar_coverage_stats(cfg: PipelineConfig) -> dict:
    """Return stats about calendar data availability for logging."""
    path = _find_calendar_file(cfg)
    if path is None:
        return {"available": False, "path": None, "days": 0}

    lookup = load_calendar_lookup(cfg)
    n_days = len(lookup) if lookup else 0
    n_break_days = sum(1 for v in (lookup or {}).values() if v > 15.0)

    return {
        "available": True,
        "path": str(path),
        "days": n_days,
        "break_days": n_break_days,
    }
