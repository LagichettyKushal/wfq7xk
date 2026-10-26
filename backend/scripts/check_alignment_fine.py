"""Empirically inspect how WINDFOR startTime aligns with WIND actuals."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.analysis import actuals_to_hourly, join_forecast_actual, select_day_ahead_forecast


DATA_DIR = BACKEND_DIR / "data"


def print_half_hourly_comparisons(
    selected: pd.DataFrame, actuals: pd.DataFrame
) -> None:
    """Compare each forecast start with actual half-hours around that start."""
    actual_values = actuals[["startTime", "generation"]].rename(
        columns={"generation": "actual"}
    )
    actual_values["startTime"] = pd.to_datetime(actual_values["startTime"], utc=True)

    print("Half-hourly actual comparison (actual at forecast startTime + offset)")
    for half_hours in range(-4, 4):
        offset = pd.Timedelta(minutes=30 * half_hours)
        comparison = selected[["startTime", "forecast"]].copy()
        comparison["actualTime"] = comparison["startTime"] + offset
        pairs = comparison.merge(
            actual_values,
            left_on="actualTime",
            right_on="startTime",
            how="inner",
        ).dropna(subset=["forecast", "actual"])
        errors = pairs["forecast"] - pairs["actual"]
        print(
            f"k={half_hours:+d} ({offset}): pairs={len(pairs)}, "
            f"MAE={errors.abs().mean():.2f} MW, "
            f"bias={errors.mean():.2f} MW, "
            f"correlation={pairs['forecast'].corr(pairs['actual']):.6f}"
        )


def print_hourly_mean_comparisons(selected: pd.DataFrame, actuals: pd.DataFrame) -> None:
    """Compare forecasts against hourly-mean actuals over half-hour shifts."""
    hourly_actuals = actuals_to_hourly(actuals)
    print("\nHourly-mean actual comparison (forecast startTime shift)")
    for shift_minutes in range(-120, 61, 30):
        shifted = selected.copy()
        shifted["startTime"] = shifted["startTime"] + pd.Timedelta(minutes=shift_minutes)
        pairs = join_forecast_actual(shifted, hourly_actuals).dropna(
            subset=["forecast", "actual"]
        )
        mae = (pairs["forecast"] - pairs["actual"]).abs().mean()
        print(f"shift={shift_minutes:+d} min: pairs={len(pairs)}, MAE={mae:.2f} MW")


def main() -> None:
    forecasts = pd.read_parquet(DATA_DIR / "forecasts.parquet")
    actuals = pd.read_parquet(DATA_DIR / "actuals.parquet")
    delivery_days = pd.date_range("2026-01-02", "2026-02-01", freq="D").date
    selected = select_day_ahead_forecast(forecasts, delivery_days)

    print_half_hourly_comparisons(selected, actuals)
    print_hourly_mean_comparisons(selected, actuals)


if __name__ == "__main__":
    main()
