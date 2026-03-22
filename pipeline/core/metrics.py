"""Pipeline metrics collection.

Collects timing, row counts, accuracy metrics across all steps.
Dumped to JSON at end of run for Barney's review.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class StepMetrics:
    """Metrics for a single pipeline step."""
    name: str
    status: str = "pending"  # pending, running, done, failed, skipped
    start_time: float = 0.0
    end_time: float = 0.0
    duration_sec: float = 0.0
    rows_in: int = 0
    rows_out: int = 0
    error: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class PipelineMetrics:
    """Metrics for the entire pipeline run."""
    run_date: str = ""
    run_start: str = ""
    run_end: str = ""
    shadow_mode: bool = False
    steps: dict[str, StepMetrics] = field(default_factory=dict)
    accuracy: dict = field(default_factory=dict)
    total_duration_sec: float = 0.0
    peak_memory_mb: float = 0.0
    status: str = "pending"  # pending, running, done, failed

    def start_step(self, name: str) -> StepMetrics:
        step = StepMetrics(name=name, status="running", start_time=time.time())
        self.steps[name] = step
        return step

    def end_step(self, name: str, rows_out: int = 0, **extra):
        step = self.steps[name]
        step.end_time = time.time()
        step.duration_sec = round(step.end_time - step.start_time, 2)
        step.rows_out = rows_out
        step.status = "done"
        step.extra = extra

    def fail_step(self, name: str, error: str):
        step = self.steps[name]
        step.end_time = time.time()
        step.duration_sec = round(step.end_time - step.start_time, 2)
        step.status = "failed"
        step.error = error

    def skip_step(self, name: str, reason: str):
        step = StepMetrics(name=name, status="skipped", error=reason)
        self.steps[name] = step

    def save(self, path: Path):
        """Write metrics to JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "run_date": self.run_date,
            "run_start": self.run_start,
            "run_end": datetime.now(timezone.utc).isoformat(),
            "shadow_mode": self.shadow_mode,
            "status": self.status,
            "total_duration_sec": self.total_duration_sec,
            "steps": {
                name: {
                    "status": s.status,
                    "duration_sec": s.duration_sec,
                    "rows_out": s.rows_out,
                    "error": s.error,
                    **s.extra,
                }
                for name, s in self.steps.items()
            },
            "accuracy": self.accuracy,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
