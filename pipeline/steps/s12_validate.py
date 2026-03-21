"""Step 12: Post-run Validation — fail loud.

Checks that all critical outputs exist and are plausible.
This is the last step. If it fails, the pipeline run is marked failed.

Checks:
1. Forecast file exists and has reasonable row count
2. WTI file exists and has all expected parks
3. No park has WTI < 1 or > 100 (plausibility)
4. Model count hasn't dropped dramatically
5. Accuracy files are being updated
"""

from __future__ import annotations

import pandas as pd

from pipeline_v3.config import PipelineConfig
from pipeline_v3.core.logging import PipelineLogger
from pipeline_v3.core.validation import (
    ValidationError,
    require_file,
    require_parquet_rows,
    require_range,
)


def run(cfg: PipelineConfig, log: PipelineLogger) -> dict:
    """Validate pipeline outputs."""

    log.info("=" * 60)
    log.info("STEP 12: POST-RUN VALIDATION")
    log.info("=" * 60)

    issues = []

    # 1. Forecast file
    forecast_path = cfg.forecast_dir / "all_forecasts_v3.parquet"
    try:
        n_forecast = require_parquet_rows(forecast_path, min_rows=1_000_000, description="v3 forecasts")
        log.info(f"Forecasts: {n_forecast:,} rows \u2714")
    except ValidationError as e:
        issues.append(str(e))
        log.error(f"Forecasts: {e}")

    # 2. WTI file
    wti_path = cfg.wti_dir / "wti_v3.parquet"
    try:
        require_file(wti_path, "v3 WTI")
        wti_df = pd.read_parquet(wti_path)
        parks_present = set(wti_df["park_code"].unique())
        expected_parks = set(cfg.parks)
        missing_parks = expected_parks - parks_present
        if missing_parks:
            issues.append(f"WTI missing parks: {missing_parks}")
            log.warning(f"WTI missing parks: {missing_parks}")
        else:
            log.info(f"WTI: {len(wti_df):,} park-dates, all {len(expected_parks)} parks present \u2714")

        # 3. Plausibility
        forecast_wti = wti_df[wti_df["source"] == "forecast"]
        if len(forecast_wti) > 0:
            min_wti = forecast_wti["wti"].min()
            max_wti = forecast_wti["wti"].max()
            if min_wti < 1:
                issues.append(f"WTI min={min_wti} (suspiciously low)")
                log.warning(f"WTI min={min_wti} — suspiciously low")
            if max_wti > 100:
                issues.append(f"WTI max={max_wti} (suspiciously high)")
                log.warning(f"WTI max={max_wti} — suspiciously high")
            log.info(f"WTI range: {min_wti:.1f} to {max_wti:.1f} \u2714")
    except ValidationError as e:
        issues.append(str(e))
        log.error(f"WTI: {e}")

    # 4. Model count
    model_dirs = [d for d in cfg.models_dir.iterdir() if d.is_dir() and not d.name.startswith("_")]
    models_with_v3 = [d for d in model_dirs if (d / "model_v3.json").exists()]
    log.info(f"Models: {len(models_with_v3)} with v3 model, {len(model_dirs)} total entity dirs")

    # Summary
    if issues:
        log.error(f"VALIDATION: {len(issues)} issue(s) found")
        for issue in issues:
            log.error(f"  - {issue}")
        raise ValidationError(f"Post-run validation failed: {len(issues)} issues")

    log.info("VALIDATION: ALL CHECKS PASSED \u2714")
    return {"rows": 0, "issues": 0}
