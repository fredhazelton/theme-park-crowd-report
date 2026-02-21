"""Global forecast horizon — single source of truth for all pipeline components."""
from datetime import date, timedelta

FORECAST_DAYS = 730  # ~2 years rolling window


def get_forecast_end_date() -> date:
    """Return the forecast horizon end date (today + FORECAST_DAYS)."""
    return date.today() + timedelta(days=FORECAST_DAYS)
