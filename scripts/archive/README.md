# Archive — Retired Scripts

These scripts are **formally retired** per V4 Amendment 001 (2026-03-25).

## Recently Retired (V4 Amendment 001)

### Legacy Pipeline Scripts
- **`run_daily_pipeline.sh`** — Superseded by `pipeline/pipeline.py`
- **`daily_accuracy_report.py`** — Superseded by `pipeline/steps/s10_accuracy.py`
- **`bias_correction_framework.py`** — Superseded by V4 bias correction in Step 9
- **`forecast_vectorized.py`** — Superseded by `pipeline/steps/s08_forecast.py`
- **`calculate_wti_simple.py`** — Superseded by `pipeline/steps/s09_wti.py`

**Note:** These scripts were modified by Wilma on 2026-03-24 under the mistaken belief they were part of the V4 pipeline. They are not. The V4 pipeline (`pipeline/pipeline.py`) is the production system.

## Previously Retired
- Various Windows PowerShell scripts from the TouringPlans.com era
- Experimental weighting and bias analysis scripts
- Legacy hybrid pipeline v2 components

## Archive Policy
Scripts in this directory are:
- ❌ Not executed by any production system
- ❌ Not maintained or updated
- ❌ May contain outdated dependencies or data paths
- ✅ Preserved for historical reference only

For current pipeline operations, see `pipeline/steps/` and the V4 Design specification.