"""Check whether WINDFOR hourly start times align with hourly WIND actuals."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.analysis import actuals_to_hourly, join_forecast_actual, select_day_ahead_forecast


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def main() -> None:
    forecasts = pd.read_parquet(DATA_DIR / "forecasts.parquet")
    actuals = pd.read_parquet(DATA_DIR / "actuals.parquet")
    delivery_days = pd.date_range("2026-01-02", "2026-02-01", freq="D").date
    selected = select_day_ahead_forecast(forecasts, delivery_days)
    hourly_actuals = actuals_to_hourly(actuals)

    for shift_hours in (-1, 0, 1):
        shifted = selected.copy()
        shifted["startTime"] = shifted["startTime"] + pd.Timedelta(hours=shift_hours)
        aligned = join_forecast_actual(shifted, hourly_actuals).dropna(
            subset=["forecast", "actual"]
        )
        mae = (aligned["forecast"] - aligned["actual"]).abs().mean()
        print(f"Forecast shift {shift_hours:+d}h: MAE {mae:.2f} MW ({len(aligned)} hours)")


if __name__ == "__main__":
    main()
