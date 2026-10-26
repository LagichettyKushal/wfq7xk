"""Pure dataframe transformations for wind forecast alignment."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Sequence

import numpy as np
import pandas as pd


def _delivery_hours(delivery_day: date, tz: str) -> pd.DatetimeIndex:
    """Return UTC hourly starts belonging to one local delivery day."""
    local_start = pd.Timestamp(delivery_day, tz=tz)
    local_end = pd.Timestamp(delivery_day + timedelta(days=1), tz=tz)
    return pd.date_range(local_start, local_end, freq="h", inclusive="left").tz_convert("UTC")


def _cutoff(delivery_day: date, cutoff_hour: int, cutoff_minute: int, tz: str) -> pd.Timestamp:
    """Build one timezone-aware local cutoff and express it in UTC."""
    local_cutoff = pd.Timestamp(
        delivery_day - timedelta(days=1),
        tz=tz,
    ).replace(hour=cutoff_hour, minute=cutoff_minute)
    return local_cutoff.tz_convert("UTC")


def select_day_ahead_forecast(
    forecasts: pd.DataFrame,
    delivery_days: Iterable[date],
    cutoff_hour: int = 9,
    cutoff_minute: int = 0,
    tz: str = "Europe/London",
) -> pd.DataFrame:
    """Select the newest eligible forecast per hourly delivery start.

    All timestamps returned are UTC-aware. Every local delivery-hour is present,
    even when no eligible forecast exists for it.
    """
    work = forecasts.copy()
    work["startTime"] = pd.to_datetime(work["startTime"], utc=True)
    work["publishTime"] = pd.to_datetime(work["publishTime"], utc=True)

    selected_days: list[pd.DataFrame] = []
    for delivery_day in delivery_days:
        expected_starts = _delivery_hours(delivery_day, tz)
        cutoff = _cutoff(delivery_day, cutoff_hour, cutoff_minute, tz)
        candidates = work.loc[
            work["startTime"].isin(expected_starts)
            & (work["publishTime"] <= cutoff),
            ["startTime", "generation", "publishTime"],
        ]
        newest = (
            candidates.sort_values(["startTime", "publishTime"])
            .drop_duplicates("startTime", keep="last")
            .rename(columns={"generation": "forecast"})
        )
        day = pd.DataFrame({"startTime": expected_starts}).merge(
            newest, on="startTime", how="left"
        )
        day["cutoff"] = cutoff
        day["horizon_hours"] = (
            (day["startTime"] - day["publishTime"]).dt.total_seconds() / 3600
        )
        selected_days.append(day)

    if not selected_days:
        return pd.DataFrame(
            columns=["startTime", "forecast", "publishTime", "cutoff", "horizon_hours"]
        )
    return pd.concat(selected_days, ignore_index=True)[
        ["startTime", "forecast", "publishTime", "cutoff", "horizon_hours"]
    ]


def actuals_to_hourly(actuals: pd.DataFrame) -> pd.DataFrame:
    """Average complete pairs of half-hourly MW actuals into hourly actuals."""
    work = actuals.copy()
    work["startTime"] = pd.to_datetime(work["startTime"], utc=True)
    work["hour_start"] = work["startTime"].dt.floor("h")

    hourly_rows: list[dict[str, object]] = []
    for hour_start, rows in work.groupby("hour_start", sort=True):
        expected = {hour_start, hour_start + pd.Timedelta(minutes=30)}
        if len(rows) == 2 and set(rows["startTime"]) == expected:
            hourly_rows.append(
                {"startTime": hour_start, "actual": rows["generation"].mean()}
            )
    return pd.DataFrame(hourly_rows, columns=["startTime", "actual"])


def join_forecast_actual(
    selected: pd.DataFrame, hourly_actuals: pd.DataFrame
) -> pd.DataFrame:
    """Inner-join selected forecast and hourly actual MW observations."""
    return selected.merge(hourly_actuals, on="startTime", how="inner")[
        ["startTime", "forecast", "actual", "publishTime", "horizon_hours"]
    ]


def _valid_pairs(joined: pd.DataFrame) -> pd.DataFrame:
    """Return forecast/actual pairs that can contribute to an error metric."""
    return joined.dropna(subset=["forecast", "actual"]).copy()


def accuracy_summary(
    joined: pd.DataFrame, no_forecast_hours: int = 0
) -> pd.DataFrame:
    """Summarise errors for matched forecast and actual values."""
    pairs = _valid_pairs(joined)
    errors = pairs["forecast"] - pairs["actual"]
    absolute_errors = errors.abs()
    mean_actual = pairs["actual"].mean()
    return pd.DataFrame(
        [
            {
                "n": len(pairs),
                "mean_actual": mean_actual,
                "mean_forecast": pairs["forecast"].mean(),
                "mae": absolute_errors.mean(),
                "rmse": np.sqrt((errors**2).mean()),
                "bias": errors.mean(),
                "mae_pct_of_mean_actual": 100 * absolute_errors.mean() / mean_actual,
                "p50_absolute_error": absolute_errors.quantile(0.50),
                "p90_absolute_error": absolute_errors.quantile(0.90),
                "p95_absolute_error": absolute_errors.quantile(0.95),
                "no_forecast_hours": no_forecast_hours,
            }
        ]
    )


def error_by_hour(joined: pd.DataFrame, tz: str) -> pd.DataFrame:
    """Group MAE and signed bias by local hour of a forecast delivery day."""
    pairs = _valid_pairs(joined)
    pairs["hour"] = pd.to_datetime(pairs["startTime"], utc=True).dt.tz_convert(tz).dt.hour
    pairs["error"] = pairs["forecast"] - pairs["actual"]
    return (
        pairs.groupby("hour", sort=True)
        .agg(mae=("error", lambda values: values.abs().mean()), bias=("error", "mean"), n=("error", "size"))
        .reset_index()
    )


def error_by_day(joined: pd.DataFrame, tz: str) -> pd.DataFrame:
    """Group MAE and signed bias by local delivery date."""
    pairs = _valid_pairs(joined)
    pairs["delivery_date"] = (
        pd.to_datetime(pairs["startTime"], utc=True).dt.tz_convert(tz).dt.date
    )
    pairs["error"] = pairs["forecast"] - pairs["actual"]
    return (
        pairs.groupby("delivery_date", sort=True)
        .agg(mae=("error", lambda values: values.abs().mean()), bias=("error", "mean"), n=("error", "size"))
        .reset_index()
    )


def error_by_output_band(joined: pd.DataFrame, bins: int = 5) -> pd.DataFrame:
    """Group errors by equal-count bands of observed actual generation."""
    pairs = _valid_pairs(joined)
    pairs["output_band"] = pd.qcut(pairs["actual"], q=bins, duplicates="drop")
    pairs["error"] = pairs["forecast"] - pairs["actual"]
    result = (
        pairs.groupby("output_band", observed=True, sort=True)
        .agg(
            mean_actual=("actual", "mean"),
            mae=("error", lambda values: values.abs().mean()),
            bias=("error", "mean"),
            n=("error", "size"),
        )
        .reset_index()
    )
    result["output_band"] = result["output_band"].astype(str)
    return result


def error_by_horizon(
    all_forecasts: pd.DataFrame,
    hourly_actuals: pd.DataFrame,
    bands: Sequence[tuple[str, float, float | None]],
) -> pd.DataFrame:
    """Group all positive-horizon publication errors into supplied horizon bands."""
    forecasts = all_forecasts.copy()
    forecasts["startTime"] = pd.to_datetime(forecasts["startTime"], utc=True)
    forecasts["publishTime"] = pd.to_datetime(forecasts["publishTime"], utc=True)
    forecasts["horizon_hours"] = (
        (forecasts["startTime"] - forecasts["publishTime"]).dt.total_seconds() / 3600
    )
    actuals = hourly_actuals.copy()
    actuals["startTime"] = pd.to_datetime(actuals["startTime"], utc=True)
    pairs = forecasts.merge(actuals, on="startTime", how="inner").dropna(
        subset=["generation", "actual"]
    )
    pairs = pairs.loc[pairs["horizon_hours"] > 0].copy()
    pairs["error"] = pairs["generation"] - pairs["actual"]

    rows: list[dict[str, object]] = []
    for label, lower, upper in bands:
        mask = pairs["horizon_hours"] >= lower
        if upper is not None:
            mask &= pairs["horizon_hours"] < upper
        band_pairs = pairs.loc[mask]
        rows.append(
            {
                "horizon_band": label,
                "mae": band_pairs["error"].abs().mean(),
                "bias": band_pairs["error"].mean(),
                "n": len(band_pairs),
            }
        )
    return pd.DataFrame(rows, columns=["horizon_band", "mae", "bias", "n"])
