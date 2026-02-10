#!/usr/bin/env python3
"""
Pipeline State — Data-Driven Skip Logic

===========================================================================
OVERVIEW
===========================================================================
Controls the --skip-if-unchanged behavior of run_daily_pipeline.sh.

Skip decisions are driven by DATA CHANGES, not output file hashes:

  Training:  Skip if no entities have new observations (entity_index)
  Forecast:  Skip if training didn't run this pipeline run (run manifest)
  WTI:       Skip if forecast didn't run this pipeline run (run manifest)

This ensures new observations always cascade through the full pipeline:
  New data → retrain → re-forecast → recalculate WTI

===========================================================================
RUN MANIFEST
===========================================================================
Each pipeline run creates a manifest tracking which steps actually ran.
Downstream steps check the manifest to decide whether to run:

  { "run_id": "2026-02-10T07:24:46",
    "started_at": "2026-02-10T07:24:46",
    "steps": {
      "training": { "ran": true, "reason": "42 entities have new observations" },
      "forecast": { "ran": true, "reason": "training ran this run" },
      "wti":      { "ran": true, "reason": "forecast ran this run" }
    }
  }

===========================================================================
ENTITY INDEX INTEGRATION
===========================================================================
The entity_index.sqlite database (maintained by ETL) tracks per-entity:
  - latest_observed_at: when the newest observation was recorded
  - last_modeled_at:    when we last trained a model for this entity

Training is needed when: latest_observed_at > last_modeled_at (or never modeled).

After training, hybrid_pipeline_v2.py marks trained entities via
mark_entity_modeled(), resetting their dirty state.

===========================================================================
USAGE
===========================================================================
  # Pipeline lifecycle (called by run_daily_pipeline.sh):
  pipeline_state.py start-run                  # Begin new run, create manifest
  pipeline_state.py check training             # Should we skip training?
  pipeline_state.py record training true       # Training ran
  pipeline_state.py record training false      # Training was skipped
  pipeline_state.py check forecast             # Should we skip forecast?
  pipeline_state.py check wti                  # Should we skip WTI?

  # Debugging / manual:
  pipeline_state.py show                       # Show persistent state
  pipeline_state.py show-manifest              # Show current run manifest
  pipeline_state.py dirty-entities             # List entities needing remodeling
  pipeline_state.py clear                      # Clear all state (force full run)
"""

import json
import hashlib
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

# ===========================================================================
# PATHS
# ===========================================================================

STATE_DIR = Path("/home/wilma/hazeydata/pipeline/state")
STATE_FILE = STATE_DIR / "pipeline_state.json"
MANIFEST_FILE = STATE_DIR / "run_manifest.json"
ENTITY_INDEX_DB = STATE_DIR / "entity_index.sqlite"


# ===========================================================================
# PERSISTENT STATE (across runs)
# ===========================================================================

def load_state():
    """Load persistent pipeline state."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    """Save persistent pipeline state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)


def clear_state():
    """Clear all state AND manifest (forces full rebuild on next run)."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print("Pipeline state cleared")
    if MANIFEST_FILE.exists():
        MANIFEST_FILE.unlink()
        print("Run manifest cleared")
    # Also clear last_modeled_at in entity_index so training re-runs all
    if ENTITY_INDEX_DB.exists():
        with sqlite3.connect(str(ENTITY_INDEX_DB)) as conn:
            conn.execute("UPDATE entity_index SET last_modeled_at = NULL")
            conn.commit()
        print("Entity index: cleared all last_modeled_at (all entities marked dirty)")


# ===========================================================================
# RUN MANIFEST (per-run tracking)
# ===========================================================================

def start_run():
    """
    Initialize a fresh run manifest. Called at pipeline start.
    Returns the run_id.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    manifest = {
        "run_id": run_id,
        "started_at": run_id,
        "steps": {},
    }
    with open(MANIFEST_FILE, 'w') as f:
        json.dump(manifest, f, indent=2)
    return run_id


def _load_manifest():
    """Load current run manifest, or empty if none."""
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE) as f:
            return json.load(f)
    return {"run_id": None, "steps": {}}


def record_step(step, ran, reason=None, details=None):
    """
    Record whether a step ran or was skipped in this run's manifest.

    Args:
        step: Step name (training, forecast, wti)
        ran: True if the step executed, False if skipped
        reason: Human-readable reason
        details: Optional dict with extra info (e.g. entities_trained)
    """
    manifest = _load_manifest()
    entry = {"ran": ran}
    if reason:
        entry["reason"] = reason
    if details:
        entry.update(details)
    entry["recorded_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    manifest["steps"][step] = entry
    with open(MANIFEST_FILE, 'w') as f:
        json.dump(manifest, f, indent=2)


def did_step_run(step):
    """Check if a step ran in the current run manifest."""
    manifest = _load_manifest()
    step_info = manifest.get("steps", {}).get(step, {})
    return step_info.get("ran", False)


# ===========================================================================
# DIRTY ENTITY DETECTION
# ===========================================================================

def get_dirty_entity_count():
    """
    Count entities that need remodeling: latest_observed_at > last_modeled_at
    or last_modeled_at IS NULL (never modeled).

    Returns (dirty_count, total_count).
    """
    if not ENTITY_INDEX_DB.exists():
        return 0, 0

    with sqlite3.connect(str(ENTITY_INDEX_DB)) as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE
                    WHEN last_modeled_at IS NULL
                      OR latest_observed_at > last_modeled_at
                    THEN 1 ELSE 0
                END) as dirty
            FROM entity_index
        """).fetchone()

    total = row[0] if row else 0
    dirty = row[1] if row and row[1] else 0
    return dirty, total


def list_dirty_entities(limit=20):
    """List entities that need remodeling, with their timestamps."""
    if not ENTITY_INDEX_DB.exists():
        return []

    with sqlite3.connect(str(ENTITY_INDEX_DB)) as conn:
        rows = conn.execute("""
            SELECT entity_code, latest_observed_at, last_modeled_at
            FROM entity_index
            WHERE last_modeled_at IS NULL
               OR latest_observed_at > last_modeled_at
            ORDER BY latest_observed_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

    return rows


# ===========================================================================
# SKIP DECISION LOGIC
# ===========================================================================

def check_should_skip(step):
    """
    Determine whether a pipeline step should be skipped.

    Returns (should_skip: bool, reason: str)

    Decision logic:
      training — Skip if no entities have new observations since last modeling.
                 Data source: entity_index.sqlite (latest_observed_at vs last_modeled_at)

      forecast — Skip if training did NOT run this pipeline run.
                 Data source: run manifest

      wti      — Skip if forecast did NOT run this pipeline run.
                 Data source: run manifest
    """
    if step == "training":
        dirty, total = get_dirty_entity_count()
        if dirty == 0:
            return True, f"No entities need remodeling (all {total} up to date)"
        return False, f"{dirty}/{total} entities have new observations since last model"

    elif step == "forecast":
        if did_step_run("training"):
            return False, "Training ran this run — forecasts need regenerating"
        return True, "Training was skipped (no new data) — forecasts still valid"

    elif step == "wti":
        if did_step_run("forecast"):
            return False, "Forecast ran this run — WTI needs recalculating"
        return True, "Forecast was skipped — WTI still valid"

    return False, f"Unknown step: {step}"


# ===========================================================================
# LEGACY: update_state (still called by run_daily_pipeline.sh after steps)
# ===========================================================================

def update_state(step):
    """
    Update persistent state after a step completes.
    Kept for backward compatibility with run_daily_pipeline.sh.
    """
    state = load_state()
    state[f"{step}_completed"] = datetime.now().isoformat()
    save_state(state)


# ===========================================================================
# CLI
# ===========================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: pipeline_state.py <command> [args]")
        print("")
        print("Commands:")
        print("  start-run              Initialize run manifest for new pipeline run")
        print("  check <step>           Check if step should be skipped (exit 0=skip, 1=run)")
        print("  record <step> <bool>   Record step ran (true) or skipped (false)")
        print("  update <step>          Update persistent state timestamp (legacy)")
        print("  dirty-entities         List entities needing remodeling")
        print("  show                   Show persistent state")
        print("  show-manifest          Show current run manifest")
        print("  clear                  Clear all state (force full rebuild)")
        sys.exit(1)

    action = sys.argv[1]

    if action == "start-run":
        run_id = start_run()
        print(f"Run manifest initialized: {run_id}")

    elif action == "check" and len(sys.argv) > 2:
        step = sys.argv[2]
        skip, reason = check_should_skip(step)
        print(f"{'SKIP' if skip else 'RUN'}: {reason}")
        # Exit 0 = skip, exit 1 = run (matches existing shell convention)
        sys.exit(0 if skip else 1)

    elif action == "record" and len(sys.argv) > 3:
        step = sys.argv[2]
        ran = sys.argv[3].lower() in ("true", "1", "yes")
        reason = sys.argv[4] if len(sys.argv) > 4 else None
        record_step(step, ran, reason)
        status = "ran" if ran else "skipped"
        print(f"Recorded: {step} {status}")

    elif action == "update" and len(sys.argv) > 2:
        step = sys.argv[2]
        update_state(step)
        print(f"State updated for: {step}")

    elif action == "dirty-entities":
        dirty, total = get_dirty_entity_count()
        print(f"Dirty entities: {dirty}/{total}")
        if dirty > 0:
            print("")
            entities = list_dirty_entities(limit=30)
            for code, obs_at, modeled_at in entities:
                modeled = modeled_at or "never"
                print(f"  {code:12s}  observed: {obs_at}  modeled: {modeled}")
            if dirty > 30:
                print(f"  ... and {dirty - 30} more")

    elif action == "show":
        state = load_state()
        print(json.dumps(state, indent=2, default=str))

    elif action == "show-manifest":
        manifest = _load_manifest()
        print(json.dumps(manifest, indent=2, default=str))

    elif action == "clear":
        clear_state()

    else:
        print(f"Unknown command: {action}")
        print("Run without arguments for usage info.")
        sys.exit(1)


if __name__ == "__main__":
    main()
