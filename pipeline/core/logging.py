"""Structured logging for pipeline v3.

Every step emits structured events. No more parsing log files with regex.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class PipelineLogger:
    """Structured logger that emits both human-readable and JSON logs."""

    def __init__(self, step_name: str, log_dir: Path | None = None):
        self.step_name = step_name
        self.events: list[dict] = []
        self._start_time = time.time()

        # Standard Python logger for human-readable output
        self.logger = logging.getLogger(f"pipeline.{step_name}")
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")
            )
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def info(self, msg: str, **kwargs):
        """Log info with optional structured fields."""
        self.logger.info(msg)
        self._emit("info", msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        """Log warning — something unexpected but non-fatal."""
        self.logger.warning(msg)
        self._emit("warning", msg, **kwargs)

    def error(self, msg: str, **kwargs):
        """Log error — step failed. Pipeline should stop or skip."""
        self.logger.error(msg)
        self._emit("error", msg, **kwargs)

    def metric(self, name: str, value: float, **kwargs):
        """Log a numeric metric (MAE, duration, row count, etc.)."""
        self.logger.info(f"{name}={value}")
        self._emit("metric", name, value=value, **kwargs)

    def _emit(self, level: str, msg: str, **kwargs):
        """Emit a structured event."""
        event = {
            "step": self.step_name,
            "level": level,
            "message": msg,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_sec": round(time.time() - self._start_time, 2),
            **kwargs,
        }
        self.events.append(event)

    @contextmanager
    def timed(self, action: str, **kwargs):
        """Context manager that logs duration of an action."""
        start = time.time()
        self.info(f"Starting: {action}")
        try:
            yield
            duration = round(time.time() - start, 2)
            self.info(f"Completed: {action} ({duration}s)", duration_sec=duration, **kwargs)
        except Exception as e:
            duration = round(time.time() - start, 2)
            self.error(f"Failed: {action} ({duration}s) — {e}", duration_sec=duration, **kwargs)
            raise

    def save_events(self, path: Path):
        """Write all events to a JSONL file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            for event in self.events:
                f.write(json.dumps(event, default=str) + "\n")
