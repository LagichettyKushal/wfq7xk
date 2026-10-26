"""Pure dataframe transformations for wind forecast alignment."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

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
