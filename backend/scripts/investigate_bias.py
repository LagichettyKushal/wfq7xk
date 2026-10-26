"""Read-only bias investigation for the January 2026 WIND snapshot."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import numpy as np
import pandas as pd


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.analysis import actuals_to_hourly, join_forecast_actual, select_day_ahead_forecast


DATA_DIR = BACKEND_DIR / "data"
LONDON_TZ = "Europe/London"
HORIZON_BANDS = [
    ("0-6h", 0, 6),
    ("6-12h", 6, 12),
    ("12-24h", 12, 24),
    ("24-36h", 24, 36),
    ("36-48h", 36, 48),
    ("48h+", 48, None),
]


def print_selected_summary(joined: pd.DataFrame) -> None:
    """Print overall, output-level, day, and hour bias observations."""
    errors = joined["forecast"] - joined["actual"]
    mean_actual = joined["actual"].mean()
    mean_forecast = joined["forecast"].mean()
    bias = errors.mean()
    print("Overall")
    print(f"mean actual: {mean_actual:.2f} MW")
    print(f"mean forecast: {mean_forecast:.2f} MW")
    print(f"mean error (forecast - actual): {bias:.2f} MW")
    print(f"error as % of mean actual: {100 * bias / mean_actual:.2f}%")

    usable_ratio = joined.loc[joined["actual"] != 0]
    slope, intercept = np.polyfit(usable_ratio["actual"], usable_ratio["forecast"], 1)
    fitted = slope * usable_ratio["actual"] + intercept
    r_squared = 1 - (
        ((usable_ratio["forecast"] - fitted) ** 2).sum()
        / ((usable_ratio["forecast"] - usable_ratio["forecast"].mean()) ** 2).sum()
    )
    ratios = usable_ratio["forecast"] / usable_ratio["actual"]
    print("\nConstant vs proportional")
    print(f"forecast = {slope:.6f} * actual + {intercept:.2f} MW")
    print(f"R^2: {r_squared:.6f}")
    print(f"mean forecast/actual: {ratios.mean():.6f}")
    print(f"median forecast/actual: {ratios.median():.6f}")

    by_band = joined.copy()
    by_band["band"] = pd.qcut(by_band["actual"], q=5, duplicates="drop")
    print("\nBy actual-output quintile")
    for band, rows in by_band.groupby("band", observed=True):
        band_errors = rows["forecast"] - rows["actual"]
        print(
            f"{band}: mean actual={rows['actual'].mean():.2f} MW, "
            f"mean error={band_errors.mean():.2f} MW, "
            f"MAE={band_errors.abs().mean():.2f} MW, count={len(rows)}"
        )

    by_day = joined.copy()
    by_day["delivery_day"] = by_day["startTime"].dt.tz_convert(LONDON_TZ).dt.date
    daily_bias = by_day.groupby("delivery_day").apply(
        lambda rows: (rows["forecast"] - rows["actual"]).mean(), include_groups=False
    )
    print("\nBy delivery day")
    for delivery_day, day_bias in daily_bias.items():
        print(f"{delivery_day}: mean error={day_bias:.2f} MW")
    print(f"Days with positive mean error: {(daily_bias > 0).sum()} of {len(daily_bias)}")

    by_hour = joined.copy()
    by_hour["london_hour"] = by_hour["startTime"].dt.tz_convert(LONDON_TZ).dt.hour
    print("\nBy London hour of day")
    for hour, rows in by_hour.groupby("london_hour"):
        hour_errors = rows["forecast"] - rows["actual"]
        print(
            f"{hour:02d}: mean error={hour_errors.mean():.2f} MW, "
            f"MAE={hour_errors.abs().mean():.2f} MW"
        )

    centered_errors = errors - bias
    print("\nAfter removing mean bias (context only)")
    print(f"MAE: {centered_errors.abs().mean():.2f} MW")
    print(f"RMSE: {np.sqrt((centered_errors**2).mean()):.2f} MW")


def print_horizon_summary(
    forecasts: pd.DataFrame,
    hourly_actuals: pd.DataFrame,
    from_day: date,
    to_day: date,
) -> None:
    """Print positive-horizon errors across publications in the delivery range."""
    work = forecasts.copy()
    work["startTime"] = pd.to_datetime(work["startTime"], utc=True)
    work["publishTime"] = pd.to_datetime(work["publishTime"], utc=True)
    local_start_dates = work["startTime"].dt.tz_convert(LONDON_TZ).dt.date
    work = work.loc[(local_start_dates >= from_day) & (local_start_dates <= to_day)]
    actual_local_dates = hourly_actuals["startTime"].dt.tz_convert(LONDON_TZ).dt.date
    hourly_actuals = hourly_actuals.loc[
        (actual_local_dates >= from_day) & (actual_local_dates <= to_day)
    ]
    work["horizon_hours"] = (
        (work["startTime"] - work["publishTime"]).dt.total_seconds() / 3600
    )
    joined = work.merge(hourly_actuals, on="startTime", how="inner").rename(
        columns={"generation": "forecast"}
    )
    joined = joined.loc[joined["horizon_hours"] > 0].copy()

    print(
        f"\nBy horizon (all publications, positive horizons only, "
        f"delivery days {from_day} to {to_day})"
    )
    for label, lower, upper in HORIZON_BANDS:
        mask = joined["horizon_hours"] >= lower
        if upper is not None:
            mask &= joined["horizon_hours"] < upper
        rows = joined.loc[mask]
        errors = rows["forecast"] - rows["actual"]
        print(
            f"{label}: mean error={errors.mean():.2f} MW, "
            f"MAE={errors.abs().mean():.2f} MW, count={len(rows)}"
        )


def main() -> None:
    forecasts = pd.read_parquet(DATA_DIR / "forecasts.parquet")
    actuals = pd.read_parquet(DATA_DIR / "actuals.parquet")
    delivery_days = pd.date_range("2026-01-02", "2026-02-01", freq="D").date
    selected = select_day_ahead_forecast(forecasts, delivery_days)
    hourly_actuals = actuals_to_hourly(actuals)
    joined = join_forecast_actual(selected, hourly_actuals).dropna(
        subset=["forecast", "actual"]
    )

    print_selected_summary(joined)
    print_horizon_summary(forecasts, hourly_actuals, delivery_days[0], delivery_days[-1])


if __name__ == "__main__":
    main()
