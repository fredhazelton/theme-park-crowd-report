#!/usr/bin/env python3
"""
Pipeline state tracking for skip-if-unchanged logic.
Tracks hashes/timestamps to avoid redundant expensive operations.
"""

import json
import hashlib
import os
from pathlib import Path
from datetime import datetime

STATE_FILE = Path("/home/wilma/hazeydata/pipeline/state/pipeline_state.json")

def load_state():
    """Load existing state or return empty dict."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def save_state(state):
    """Save state to file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)

def get_file_hash(path):
    """Get MD5 hash of a file (first 1MB for large files)."""
    if not os.path.exists(path):
        return None
    h = hashlib.md5()
    with open(path, 'rb') as f:
        h.update(f.read(1024 * 1024))  # First 1MB
    return h.hexdigest()

def get_dir_mtime(path):
    """Get latest mtime of files in directory."""
    if not os.path.exists(path):
        return None
    latest = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            mtime = os.path.getmtime(os.path.join(root, f))
            if mtime > latest:
                latest = mtime
    return latest if latest > 0 else None

def check_should_skip(step):
    """
    Check if a step should be skipped based on state.
    Returns (should_skip: bool, reason: str)
    """
    state = load_state()
    base = Path("/home/wilma/hazeydata/pipeline")
    
    if step == "training":
        # Skip if no entities have new observations since last modeling.
        # The entity_index.sqlite tracks latest_observed_at vs last_modeled_at.
        index_db = base / "state" / "entity_index.sqlite"
        if index_db.exists():
            import sqlite3
            with sqlite3.connect(str(index_db)) as conn:
                row = conn.execute("""
                    SELECT COUNT(*) FROM entity_index
                    WHERE last_modeled_at IS NULL
                       OR latest_observed_at > last_modeled_at
                """).fetchone()
                needs_modeling = row[0] if row else 0
            if needs_modeling == 0:
                return True, f"No entities need remodeling (all up to date)"
            return False, f"{needs_modeling} entities have new observations since last model"
        # Fallback: check matched_pairs hash
        pairs_file = base / "matched_pairs/all_pairs_v2.parquet"
        current_hash = get_file_hash(pairs_file)
        last_hash = state.get("matched_pairs_hash")
        
        if current_hash and current_hash == last_hash:
            return True, f"Matched pairs unchanged (hash: {current_hash[:8]})"
        return False, f"Matched pairs changed"
    
    elif step == "forecast":
        # Skip if models haven't changed
        models_dir = base / "models"
        current_mtime = get_dir_mtime(models_dir)
        last_mtime = state.get("models_mtime")
        
        if current_mtime and last_mtime and current_mtime <= last_mtime:
            return True, f"Models unchanged (mtime: {datetime.fromtimestamp(current_mtime)})"
        return False, f"Models changed"
    
    elif step == "wti":
        # Skip if forecasts haven't changed
        forecast_file = base / "curves/forecast_parquet/all_forecasts.parquet"
        current_hash = get_file_hash(forecast_file)
        last_hash = state.get("forecast_hash")
        
        if current_hash and current_hash == last_hash:
            return True, f"Forecasts unchanged (hash: {current_hash[:8]})"
        return False, f"Forecasts changed"
    
    return False, "Unknown step"

def update_state(step):
    """Update state after a step completes."""
    state = load_state()
    base = Path("/home/wilma/hazeydata/pipeline")
    
    if step == "training":
        pairs_file = base / "matched_pairs/all_pairs_v2.parquet"
        state["matched_pairs_hash"] = get_file_hash(pairs_file)
        state["training_completed"] = datetime.now().isoformat()
        
        # Also update models mtime
        models_dir = base / "models"
        state["models_mtime"] = get_dir_mtime(models_dir)
    
    elif step == "forecast":
        forecast_file = base / "curves/forecast_parquet/all_forecasts.parquet"
        state["forecast_hash"] = get_file_hash(forecast_file)
        state["forecast_completed"] = datetime.now().isoformat()
    
    elif step == "wti":
        state["wti_completed"] = datetime.now().isoformat()
    
    save_state(state)

def clear_state():
    """Clear all state (force full rebuild)."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    print("Pipeline state cleared")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: pipeline_state.py <check|update|clear|show> [step]")
        sys.exit(1)
    
    action = sys.argv[1]
    step = sys.argv[2] if len(sys.argv) > 2 else None
    
    if action == "check" and step:
        skip, reason = check_should_skip(step)
        print(f"{'SKIP' if skip else 'RUN'}: {reason}")
        sys.exit(0 if skip else 1)
    
    elif action == "update" and step:
        update_state(step)
        print(f"State updated for: {step}")
    
    elif action == "clear":
        clear_state()
    
    elif action == "show":
        state = load_state()
        print(json.dumps(state, indent=2, default=str))
    
    else:
        print("Usage: pipeline_state.py <check|update|clear|show> [step]")
        sys.exit(1)
