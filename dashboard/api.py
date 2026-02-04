"""
Dashboard API - Serves data for stream dashboard

Provides REST API endpoints for:
- WTI (Wait Time Index) data
- Live wait times
- Forecast data
- Crowd level calculations
- Pro tips

Usage:
    python dashboard/api.py
    # Runs on http://localhost:8051
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS

# Add src to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from utils.paths import get_output_base

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend

# Park code mapping (dashboard -> pipeline)
PARK_CODE_MAP = {
    "mk": "mk",
    "ep": "ep",
    "hs": "hs",
    "ak": "ak",
    "dl": "dl",  # Disneyland
    "ca": "ca",  # California Adventure
    "ioa": "ia",  # Islands of Adventure
    "usf": "uf",  # Universal Studios Florida
    "eu": "eu",  # Epic Universe
    "ush": "uh",  # Universal Studios Hollywood
    "tdl": "tdl",  # Tokyo Disneyland
    "tds": "tds",  # Tokyo DisneySea
}

# Reverse mapping (pipeline -> dashboard)
PARK_CODE_REVERSE = {v: k for k, v in PARK_CODE_MAP.items()}


# =============================================================================
# DATA LOADING FUNCTIONS
# =============================================================================

def get_output_base_path() -> Path:
    """Get output base path."""
    return Path(get_output_base()).resolve()


def load_wti_data(output_base: Path) -> Optional[pd.DataFrame]:
    """Load WTI data from parquet file."""
    wti_path = output_base / "wti" / "wti.parquet"
    if not wti_path.exists():
        # Try CSV fallback
        wti_path = output_base / "wti" / "wti.csv"
        if not wti_path.exists():
            return None
    
    try:
        if wti_path.suffix == ".parquet":
            df = pd.read_parquet(wti_path)
        else:
            df = pd.read_csv(wti_path)
        
        # Ensure park_date is date type
        if "park_date" in df.columns:
            df["park_date"] = pd.to_datetime(df["park_date"]).dt.date
        
        # Rename columns to match API expectations
        if "code" in df.columns and "entity_code" not in df.columns:
            df = df.rename(columns={"code": "entity_code"})
        return df
    except Exception as e:
        logger.error(f"Error loading WTI data: {e}")
        return None


def load_live_wait_times(output_base: Path, park_code: str) -> pd.DataFrame:
    """Load latest wait times from staging/queue_times for a park."""
    staging_dir = output_base / "staging" / "queue_times"
    if not staging_dir.exists():
        return pd.DataFrame()
    
    # Find all CSVs for this park
    pattern = f"{park_code}_*.csv"
    csvs = list(staging_dir.rglob(pattern))
    
    if not csvs:
        return pd.DataFrame()
    
    # Sort by modification time (newest first)
    csvs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    all_rows = []
    for csv_path in csvs[:5]:  # Check up to 5 most recent files
        try:
            df = pd.read_csv(csv_path, low_memory=False)
            if df.empty:
                continue
            
            # Filter for POSTED wait times only
            if "wait_time_type" in df.columns:
                df = df[df["wait_time_type"] == "POSTED"]
            
            if not df.empty:
                all_rows.append(df)
        except Exception as e:
            logger.warning(f"Error reading {csv_path}: {e}")
            continue
    
    if not all_rows:
        return pd.DataFrame()
    
    # Combine and get latest per entity
    combined = pd.concat(all_rows, ignore_index=True)
    
    # Convert observed_at to datetime for sorting
    if "observed_at" in combined.columns:
        combined["observed_at"] = pd.to_datetime(combined["observed_at"], errors="coerce")
        # Get latest observation per entity
        combined = combined.sort_values("observed_at", ascending=False)
        combined = combined.drop_duplicates(subset=["entity_code"], keep="first")
    
    return combined


def load_entity_metadata(output_base: Path) -> Optional[pd.DataFrame]:
    """Load entity metadata from dimentity.csv."""
    dim_path = output_base / "dimension_tables" / "dimentity.csv"
    if not dim_path.exists():
        return None
    
    try:
        df = pd.read_csv(dim_path, low_memory=False)
        # Rename columns to match API expectations
        if "code" in df.columns and "entity_code" not in df.columns:
            df = df.rename(columns={"code": "entity_code"})
        return df
    except Exception as e:
        logger.error(f"Error loading entity metadata: {e}")
        return None


def load_forecast_curves(output_base: Path, park_code: str, park_date: date) -> list[dict]:
    """Load forecast curves for all entities in a park for a given date."""
    curves_dir = output_base / "curves" / "forecast"
    if not curves_dir.exists():
        return []
    
    # Get all entities for this park
    entities_df = load_entity_metadata(output_base)
    if entities_df is None or entities_df.empty:
        return []
    
    # Filter entities by park
    if "park_code" in entities_df.columns:
        park_entities = entities_df[entities_df["park_code"].str.upper() == park_code.upper()]["entity_code"].tolist()
    else:
        # Fallback: derive from entity_code prefix
        park_prefix = park_code.upper()
        park_entities = entities_df[entities_df["entity_code"].str.startswith(park_prefix)]["entity_code"].tolist()
    
    curves = []
    date_str = park_date.strftime("%Y-%m-%d")
    
    for entity_code in park_entities:
        curve_path = curves_dir / f"{entity_code}_{date_str}.csv"
        if curve_path.exists():
            try:
                df = pd.read_csv(curve_path)
                # Find minimum wait time and its time slot
                if "actual_predicted" in df.columns and not df.empty:
                    min_idx = df["actual_predicted"].idxmin()
                    min_wait = df.loc[min_idx, "actual_predicted"]
                    min_time = df.loc[min_idx, "time_slot"] if "time_slot" in df.columns else None
                    
                    # Get entity name
                    entity_name = entity_code
                    if entities_df is not None:
                        entity_row = entities_df[entities_df["entity_code"] == entity_code]
                        if not entity_row.empty and "entity_name" in entity_row.columns:
                            entity_name = entity_row.iloc[0]["entity_name"]
                    
                    curves.append({
                        "entity_code": entity_code,
                        "entity_name": entity_name,
                        "min_wait": float(min_wait) if pd.notna(min_wait) else None,
                        "min_time": min_time,
                    })
            except Exception as e:
                logger.warning(f"Error reading forecast curve {curve_path}: {e}")
                continue
    
    return curves


# =============================================================================
# DATA PROCESSING FUNCTIONS
# =============================================================================

def wti_to_crowd_level(wti_minutes: float, historical_wti: Optional[pd.Series] = None) -> int:
    """
    Convert WTI (in minutes) to 1-10 crowd level scale.
    
    Uses percentile-based approach if historical data available,
    otherwise uses fixed thresholds.
    """
    if pd.isna(wti_minutes) or wti_minutes < 0:
        return 1
    
    # If we have historical data, use percentiles
    if historical_wti is not None and len(historical_wti) > 0:
        percentiles = [10, 25, 50, 75, 90]
        thresholds = [historical_wti.quantile(p / 100) for p in percentiles]
        
        if wti_minutes <= thresholds[0]:
            return 1
        elif wti_minutes <= thresholds[1]:
            return 3
        elif wti_minutes <= thresholds[2]:
            return 5
        elif wti_minutes <= thresholds[3]:
            return 7
        elif wti_minutes <= thresholds[4]:
            return 9
        else:
            return 10
    else:
        # Fixed thresholds (calibrate these based on your data)
        if wti_minutes <= 15:
            return 1
        elif wti_minutes <= 25:
            return 3
        elif wti_minutes <= 35:
            return 5
        elif wti_minutes <= 45:
            return 7
        elif wti_minutes <= 60:
            return 9
        else:
            return 10


def get_daily_wti(wti_df: pd.DataFrame, park_code: str, park_date: date) -> Optional[dict]:
    """Get daily aggregated WTI for a park and date."""
    if wti_df is None or wti_df.empty:
        return None
    
    # Filter by park and date
    park_data = wti_df[
        (wti_df["park_code"] == park_code) &
        (wti_df["park_date"] == park_date)
    ]
    
    if park_data.empty:
        return None
    
    # Aggregate across time slots
    avg_wti = park_data["wti"].mean()
    min_wti = park_data["wti"].min()
    max_wti = park_data["wti"].max()
    n_entities = park_data["n_entities"].max() if "n_entities" in park_data.columns else None
    
    return {
        "wti": float(avg_wti),
        "min": float(min_wti),
        "max": float(max_wti),
        "n_entities": int(n_entities) if pd.notna(n_entities) else None,
    }


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})


@app.route("/api/crowd-level/<park_code>", methods=["GET"])
def get_crowd_level(park_code: str):
    """Get current crowd level (1-10) for a park."""
    # Map dashboard park code to pipeline code
    pipeline_park = PARK_CODE_MAP.get(park_code.lower(), park_code.lower())
    
    # Get date (default to today)
    date_str = request.args.get("date")
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = date.today()
    else:
        target_date = date.today()
    
    output_base = get_output_base_path()
    wti_df = load_wti_data(output_base)
    
    if wti_df is None or wti_df.empty:
        return jsonify({"error": "No WTI data available"}), 404
    
    # Get historical WTI for percentile calculation
    historical = wti_df[
        (wti_df["park_code"] == pipeline_park) &
        (wti_df["park_date"] < target_date)
    ]["wti"]
    
    # Get today's WTI
    daily_wti = get_daily_wti(wti_df, pipeline_park, target_date)
    
    if daily_wti is None:
        return jsonify({"error": f"No WTI data for {park_code} on {target_date}"}), 404
    
    # Convert to crowd level
    crowd_level = wti_to_crowd_level(daily_wti["wti"], historical)
    
    # Get yesterday's WTI for comparison
    yesterday = target_date - timedelta(days=1)
    yesterday_wti = get_daily_wti(wti_df, pipeline_park, yesterday)
    vs_yesterday = None
    if yesterday_wti:
        vs_yesterday = ((daily_wti["wti"] - yesterday_wti["wti"]) / yesterday_wti["wti"]) * 100
    
    return jsonify({
        "park_code": park_code,
        "park_date": target_date.isoformat(),
        "crowd_level": crowd_level,
        "wti_minutes": daily_wti["wti"],
        "wti_min": daily_wti["min"],
        "wti_max": daily_wti["max"],
        "n_entities": daily_wti["n_entities"],
        "vs_yesterday_pct": round(vs_yesterday, 1) if vs_yesterday is not None else None,
    })


@app.route("/api/entities/<park_code>", methods=["GET"])
def get_entities(park_code: str):
    """Get all entities/attractions for a park from entity metadata."""
    pipeline_park = PARK_CODE_MAP.get(park_code.lower(), park_code.lower())
    output_base = get_output_base_path()
    
    entities_df = load_entity_metadata(output_base)
    if entities_df is None or entities_df.empty:
        return jsonify({"entities": []})
    
    # Filter entities by park
    if "park_code" in entities_df.columns:
        park_entities = entities_df[entities_df["park_code"].str.upper() == pipeline_park.upper()].copy()
    else:
        # Fallback: derive from entity_code prefix
        park_prefix = pipeline_park.upper()
        park_entities = entities_df[entities_df["entity_code"].str.startswith(park_prefix)].copy()
    
    if park_entities.empty:
        return jsonify({"entities": []})
    
    # Prepare results
    results = []
    for _, row in park_entities.iterrows():
        entity_code = str(row["entity_code"])
        entity_name = str(row["name"]) if "name" in row and pd.notna(row["name"]) else entity_code
        
        results.append({
            "entity_code": entity_code,
            "entity_name": entity_name,
        })
    
    # Sort by entity name
    results.sort(key=lambda x: x["entity_name"])
    
    return jsonify({"entities": results})


@app.route("/api/wait-times/<park_code>", methods=["GET"])
def get_wait_times(park_code: str):
    """Get top wait times for a park."""
    limit = int(request.args.get("limit", 5))
    pipeline_park = PARK_CODE_MAP.get(park_code.lower(), park_code.lower())
    
    output_base = get_output_base_path()
    wait_df = load_live_wait_times(output_base, pipeline_park)
    
    if wait_df.empty:
        return jsonify({"wait_times": []})
    
    # Load entity metadata for names
    entities_df = load_entity_metadata(output_base)
    
    # Prepare results
    results = []
    for _, row in wait_df.head(limit).iterrows():
        entity_code = str(row["entity_code"])
        wait_minutes = int(row["wait_time_minutes"]) if pd.notna(row.get("wait_time_minutes")) else None
        
        # Get entity name
        entity_name = entity_code
        if entities_df is not None and not entities_df.empty:
            entity_row = entities_df[entities_df["entity_code"] == entity_code]
            if not entity_row.empty and "entity_name" in entity_row.columns:
                entity_name = entity_row.iloc[0]["entity_name"]
        
        results.append({
            "entity_code": entity_code,
            "entity_name": entity_name,
            "wait_minutes": wait_minutes,
            "observed_at": str(row["observed_at"]) if "observed_at" in row else None,
        })
    
    # Sort by wait time descending
    results.sort(key=lambda x: x["wait_minutes"] if x["wait_minutes"] is not None else 0, reverse=True)
    
    return jsonify({"wait_times": results[:limit]})


@app.route("/api/forecast/<park_code>", methods=["GET"])
def get_forecast(park_code: str):
    """Get 7-day forecast for a park."""
    days = int(request.args.get("days", 7))
    pipeline_park = PARK_CODE_MAP.get(park_code.lower(), park_code.lower())
    
    output_base = get_output_base_path()
    wti_df = load_wti_data(output_base)
    
    if wti_df is None or wti_df.empty:
        return jsonify({"forecast": []})
    
    # Get historical WTI for percentile calculation
    historical = wti_df[
        (wti_df["park_code"] == pipeline_park) &
        (wti_df["park_date"] < date.today())
    ]["wti"]
    
    forecast = []
    for i in range(days):
        forecast_date = date.today() + timedelta(days=i)
        daily_wti = get_daily_wti(wti_df, pipeline_park, forecast_date)
        
        if daily_wti:
            crowd_level = wti_to_crowd_level(daily_wti["wti"], historical)
            forecast.append({
                "date": forecast_date.isoformat(),
                "crowd_level": crowd_level,
                "wti_minutes": daily_wti["wti"],
            })
        else:
            # No forecast data for this date
            forecast.append({
                "date": forecast_date.isoformat(),
                "crowd_level": None,
                "wti_minutes": None,
            })
    
    return jsonify({"forecast": forecast})


@app.route("/api/tip/<park_code>", methods=["GET"])
def get_tip(park_code: str):
    """Get a pro tip for a park based on forecast data."""
    pipeline_park = PARK_CODE_MAP.get(park_code.lower(), park_code.lower())
    output_base = get_output_base_path()
    
    # Load forecast curves for today
    today = date.today()
    curves = load_forecast_curves(output_base, pipeline_park, today)
    
    if not curves:
        return jsonify({"tip": None})
    
    # Find entity with best improvement opportunity
    # (highest max wait, significant drop at some point)
    best_tip = None
    max_improvement = 0
    
    for curve in curves:
        if curve["min_wait"] is not None:
            # For now, just find the one with lowest minimum
            # TODO: Calculate improvement (max - min) from full curve
            if best_tip is None or curve["min_wait"] < best_tip["min_wait"]:
                best_tip = curve
    
    if best_tip and best_tip["min_time"]:
        # Parse time slot to get hour
        try:
            time_str = best_tip["min_time"]
            if "T" in time_str:
                hour = int(time_str.split("T")[1].split(":")[0])
                period = "AM" if hour < 12 else "PM"
                hour_12 = hour if hour <= 12 else hour - 12
                if hour == 0:
                    hour_12 = 12
                
                tip_text = f"{best_tip['entity_name']} typically drops to {int(best_tip['min_wait'])} min around {hour_12} {period}. Set a reminder to check back then!"
            else:
                tip_text = f"{best_tip['entity_name']} typically drops to {int(best_tip['min_wait'])} min. Check forecast for best time!"
        except Exception:
            tip_text = f"{best_tip['entity_name']} typically drops to {int(best_tip['min_wait'])} min. Check forecast for best time!"
        
        return jsonify({"tip": tip_text})
    
    return jsonify({"tip": None})


@app.route("/api/stats/<park_code>", methods=["GET"])
def get_stats(park_code: str):
    """Get comprehensive stats for a park (for hero card)."""
    pipeline_park = PARK_CODE_MAP.get(park_code.lower(), park_code.lower())
    output_base = get_output_base_path()
    
    # Get crowd level data
    wti_df = load_wti_data(output_base)
    today = date.today()
    
    daily_wti = get_daily_wti(wti_df, pipeline_park, today) if wti_df is not None else None
    
    # Get wait times for average
    wait_df = load_live_wait_times(output_base, pipeline_park)
    avg_wait = None
    if not wait_df.empty and "wait_time_minutes" in wait_df.columns:
        avg_wait = wait_df["wait_time_minutes"].mean()
    
    # Get best time from forecast
    curves = load_forecast_curves(output_base, pipeline_park, today)
    best_time = None
    if curves:
        # Find time slot with lowest average wait across all entities
        # For now, use the tip entity's best time
        tip_data = get_tip(park_code)
        if tip_data and tip_data.get_json().get("tip"):
            # Extract time from tip text
            tip_text = tip_data.get_json()["tip"]
            # Simple extraction - could be improved
            import re
            time_match = re.search(r"around (\d+) (AM|PM)", tip_text)
            if time_match:
                best_time = f"{time_match.group(1)} {time_match.group(2)}"
    
    return jsonify({
        "park_code": park_code,
        "date": today.isoformat(),
        "avg_wait": round(avg_wait, 1) if avg_wait is not None else None,
        "best_time": best_time,
        "wti": daily_wti["wti"] if daily_wti else None,
    })


if __name__ == "__main__":
    logger.info("Starting Dashboard API server...")
    logger.info(f"Output base: {get_output_base_path()}")
    app.run(host="0.0.0.0", port=8051, debug=False)
