"""Step 14: Content Generation.

Generates Twitter content JSONs for WTI predictions and observations.
Includes quality gate that validates data before marking content "ready".

Workflow:
1. Extract predicted WTI for tomorrow (WDW 4 parks)
2. Extract observed WTI for yesterday (WDW 4 parks)
3. Run quality gate on both datasets (5 checks)
4. Write content JSONs with status: "ready" or "held"
5. Post Discord warnings for held content

Output files:
  - content/predicted_YYYY-MM-DD.json
  - content/observed_YYYY-MM-DD.json
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple

import pandas as pd

from pipeline.config import PipelineConfig
from pipeline.core.db import read_connection
from pipeline.core.logging import PipelineLogger


# WDW park configuration
WDW_PARKS = {
    "MK": "Magic Kingdom",
    "EP": "EPCOT", 
    "HS": "Hollywood Studios",
    "AK": "Animal Kingdom"
}

# Quality gate thresholds
BOUNDS_MIN = 1.0
BOUNDS_MAX = 70.0
PEER_OUTLIER_THRESHOLD = 0.60  # 60%
DAY_JUMP_THRESHOLD = 15.0      # 15 WTI points


def _extract_wti_data(cfg: PipelineConfig, log: PipelineLogger, target_date: str, source: str) -> Dict[str, float] | None:
    """Extract WTI data for WDW parks on target date."""
    wti_path = cfg.wti_dir / "wti.parquet"
    
    if not wti_path.exists():
        log.error(f"WTI file not found: {wti_path}")
        return None
    
    try:
        with read_connection() as con:
            query = f"""
                SELECT park_code, wti
                FROM read_parquet('{wti_path}')
                WHERE park_date::DATE = '{target_date}'::DATE
                AND source = '{source}'
                AND park_code IN ('MK', 'EP', 'HS', 'AK')
            """
            df = con.execute(query).df()
            
            if df.empty:
                log.warning(f"No {source} WTI data found for {target_date}")
                return None
            
            # Convert to dict
            wti_data = dict(zip(df['park_code'], df['wti']))
            log.info(f"Extracted {source} WTI for {target_date}: {len(wti_data)} parks")
            
            return wti_data
            
    except Exception as e:
        log.error(f"Failed to extract {source} WTI data for {target_date}: {e}")
        return None


def _check_completeness(wti_data: Dict[str, float]) -> List[str]:
    """Check 1: All 4 WDW parks must be present."""
    failures = []
    missing_parks = []
    
    for park_code in WDW_PARKS.keys():
        if park_code not in wti_data or wti_data[park_code] is None:
            missing_parks.append(park_code)
    
    if missing_parks:
        failures.append(f"INCOMPLETE: Missing parks: {missing_parks}")
    
    return failures


def _check_absolute_bounds(wti_data: Dict[str, float]) -> List[str]:
    """Check 2: WTI must be within [1.0, 70.0]."""
    failures = []
    
    for park_code, wti in wti_data.items():
        if wti < BOUNDS_MIN or wti > BOUNDS_MAX:
            failures.append(f"OUT_OF_BOUNDS: {park_code} wti {wti} outside [{BOUNDS_MIN}, {BOUNDS_MAX}]")
    
    return failures


def _check_peer_outlier(wti_data: Dict[str, float]) -> List[str]:
    """Check 3: No park should deviate >60% from peer mean."""
    failures = []
    
    if len(wti_data) < 4:
        return failures  # Skip if incomplete data
    
    for park_code, wti in wti_data.items():
        # Calculate mean of the other 3 parks
        other_wtis = [v for k, v in wti_data.items() if k != park_code]
        if len(other_wtis) < 3:
            continue
        
        peer_mean = sum(other_wtis) / len(other_wtis)
        deviation = abs(wti - peer_mean) / peer_mean
        
        if deviation > PEER_OUTLIER_THRESHOLD:
            direction = "below" if wti < peer_mean else "above"
            failures.append(
                f"PEER_OUTLIER: {park_code} wti {wti} is {deviation:.0%} {direction} "
                f"peer mean {peer_mean:.1f} (threshold: {PEER_OUTLIER_THRESHOLD:.0%})"
            )
    
    return failures


def _check_day_jump(wti_data: Dict[str, float], cfg: PipelineConfig, target_date: str) -> List[str]:
    """Check 4: Day-over-day stability for predictions (<15 point jump)."""
    failures = []
    
    try:
        # Get yesterday's predicted data
        yesterday = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        yesterday_file = cfg.output_base / "content" / f"predicted_{yesterday}.json"
        
        if not yesterday_file.exists():
            # No baseline to compare against - skip check
            return failures
        
        with open(yesterday_file, 'r') as f:
            yesterday_data = json.load(f)
        
        if yesterday_data.get("status") != "ready":
            # Yesterday's data wasn't good - skip comparison  
            return failures
        
        # Build yesterday's WTI lookup
        yesterday_wti = {}
        for park in yesterday_data.get("parks", []):
            yesterday_wti[park["park_code"]] = park["wti"]
        
        # Compare each park
        for park_code, today_wti in wti_data.items():
            if park_code in yesterday_wti:
                yesterday_wti_val = yesterday_wti[park_code]
                jump = abs(today_wti - yesterday_wti_val)
                
                if jump > DAY_JUMP_THRESHOLD:
                    direction = "+" if today_wti > yesterday_wti_val else "-"
                    failures.append(
                        f"DAY_JUMP: {park_code} predicted wti jumped "
                        f"{yesterday_wti_val:.1f} → {today_wti:.1f} ({direction}{jump:.1f}, threshold: {DAY_JUMP_THRESHOLD})"
                    )
        
    except Exception as e:
        # Non-fatal - log but don't fail the quality gate
        pass
    
    return failures


def _check_staleness(cfg: PipelineConfig, run_date: str) -> List[str]:
    """Check 5: WTI parquet must have been modified today."""
    failures = []
    
    wti_path = cfg.wti_dir / "wti.parquet"
    if not wti_path.exists():
        failures.append("STALE_DATA: wti.parquet does not exist")
        return failures
    
    # Get file modification date
    mod_time = datetime.fromtimestamp(wti_path.stat().st_mtime)
    mod_date = mod_time.strftime("%Y-%m-%d")
    
    if mod_date != run_date:
        failures.append(f"STALE_DATA: wti.parquet last modified {mod_date}, expected {run_date}")
    
    return failures


def _run_quality_gate(wti_data: Dict[str, float], cfg: PipelineConfig, target_date: str, is_predicted: bool, run_date: str) -> Tuple[bool, List[str]]:
    """Run all quality gate checks. Returns (passed, failure_reasons)."""
    failures = []
    
    # Check 1: Completeness
    failures.extend(_check_completeness(wti_data))
    
    # Check 2: Absolute bounds
    failures.extend(_check_absolute_bounds(wti_data))
    
    # Check 3: Peer outlier
    failures.extend(_check_peer_outlier(wti_data))
    
    # Check 4: Day-over-day stability (predicted only)
    if is_predicted:
        failures.extend(_check_day_jump(wti_data, cfg, target_date))
    
    # Check 5: Staleness
    failures.extend(_check_staleness(cfg, run_date))
    
    passed = len(failures) == 0
    return passed, failures


def _create_content_json(content_type: str, target_date: str, wti_data: Dict[str, float], 
                        status: str, held_reasons: List[str], run_time: str) -> Dict[str, Any]:
    """Create the content JSON structure."""
    parks_data = []
    for park_code in ["MK", "EP", "HS", "AK"]:  # Consistent ordering
        if park_code in wti_data:
            parks_data.append({
                "park_code": park_code,
                "park_name": WDW_PARKS[park_code],
                "wti": round(wti_data[park_code], 1)
            })
    
    return {
        "type": content_type,
        "status": status,
        "held_reasons": held_reasons,
        "target_date": target_date,
        "generated_at": run_time,
        "generated_by": "s14_content v1.0",
        "property": "WDW",
        "parks": parks_data
    }


def _post_discord_warning(cfg: PipelineConfig, log: PipelineLogger, content_type: str, target_date: str, failures: List[str]):
    """Post warning to #wti-pipeline for held content."""
    try:
        failure_list = "\n".join(f"• {failure}" for failure in failures)
        message = f"⚠️ **Content Quality Gate: {content_type.title()} {target_date} HELD**\n```\n{failure_list}\n```"
        
        # Use Clawdbot message tool if available
        # For now, just log - Discord integration can be added later
        log.warning(f"HELD CONTENT ({content_type} {target_date}): {'; '.join(failures)}")
        
        # TODO: Add actual Discord posting when message tool is integrated
        # This would require importing clawdbot message functions
        
    except Exception as e:
        log.error(f"Failed to post Discord warning: {e}")


def run(cfg: PipelineConfig, log: PipelineLogger):
    """Main Step 14 execution."""
    log.info("Step 14: Content generation starting")
    
    # Setup
    run_time = datetime.now().isoformat()
    run_date = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Create content directory
    content_dir = cfg.output_base / "content"
    content_dir.mkdir(exist_ok=True)
    
    # Extract predicted WTI (tomorrow)
    log.info(f"Extracting predicted WTI for {tomorrow}")
    predicted_wti = _extract_wti_data(cfg, log, tomorrow, "forecast")
    
    if predicted_wti:
        # Run quality gate
        passed, failures = _run_quality_gate(predicted_wti, cfg, tomorrow, is_predicted=True, run_date=run_date)
        status = "ready" if passed else "held"
        
        if not passed:
            _post_discord_warning(cfg, log, "predicted", tomorrow, failures)
        
        # Create JSON
        content_json = _create_content_json("predicted", tomorrow, predicted_wti, status, failures, run_time)
        
        # Write file
        output_file = content_dir / f"predicted_{tomorrow}.json"
        with open(output_file, 'w') as f:
            json.dump(content_json, f, indent=2)
        
        log.info(f"Predicted content for {tomorrow}: {status} ({len(predicted_wti)} parks)")
        if failures:
            log.warning(f"Predicted quality gate failures: {'; '.join(failures)}")
    
    else:
        log.error(f"No predicted WTI data available for {tomorrow}")
    
    # Extract observed WTI (yesterday)  
    log.info(f"Extracting observed WTI for {yesterday}")
    observed_wti = _extract_wti_data(cfg, log, yesterday, "historical")
    
    if observed_wti:
        # Run quality gate (not predicted, so no day-jump check)
        passed, failures = _run_quality_gate(observed_wti, cfg, yesterday, is_predicted=False, run_date=run_date)
        status = "ready" if passed else "held"
        
        if not passed:
            _post_discord_warning(cfg, log, "observed", yesterday, failures)
        
        # Create JSON
        content_json = _create_content_json("observed", yesterday, observed_wti, status, failures, run_time)
        
        # Write file
        output_file = content_dir / f"observed_{yesterday}.json"
        with open(output_file, 'w') as f:
            json.dump(content_json, f, indent=2)
        
        log.info(f"Observed content for {yesterday}: {status} ({len(observed_wti)} parks)")
        if failures:
            log.warning(f"Observed quality gate failures: {'; '.join(failures)}")
    
    else:
        log.warning(f"No observed WTI data available for {yesterday}")
    
    log.info("Step 14: Content generation completed")