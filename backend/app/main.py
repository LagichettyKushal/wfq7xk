"""Snapshot-backed FastAPI service for day-ahead WIND forecast analysis."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
import json
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.analysis import (
    accuracy_summary,
    actuals_to_hourly,
    error_by_day,
    error_by_horizon,
    error_by_hour,
    error_by_output_band,
    select_day_ahead_forecast,
)


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
AVAILABLE_FROM = date(2026, 1, 2)
AVAILABLE_TO = date(2026, 2, 1)
LONDON_TZ = "Europe/London"
HORIZON_BANDS = [
    ("0-6h", 0, 6),
    ("6-12h", 6, 12),
    ("12-24h", 12, 24),
    ("24-36h", 24, 36),
    ("36-48h", 36, 48),
    ("48h+", 48, None),
]
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend-dist"


@lru_cache(maxsize=1)
def load_snapshot() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load the immutable parquet snapshot once on first endpoint use."""
    actuals = pd.read_parquet(DATA_DIR / "actuals.parquet")
    forecasts = pd.read_parquet(DATA_DIR / "forecasts.parquet")
    return actuals, forecasts, actuals_to_hourly(actuals)


app = FastAPI(title="Wind Forecast Portal API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def dataframe_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Produce JSON records with ISO datetimes and nulls instead of NaN."""
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def dataframe_record(frame: pd.DataFrame) -> dict[str, object]:
    """Produce a one-row JSON object with nulls instead of NaN."""
    records = dataframe_records(frame)
    return records[0] if records else {}


def utc_iso(value: object) -> str:
    """Format an aware UTC timestamp consistently for API metadata."""
    return pd.Timestamp(value).isoformat().replace("+00:00", "Z")


def validate_day(day: date) -> None:
    if not AVAILABLE_FROM <= day <= AVAILABLE_TO:
        raise HTTPException(
            status_code=422,
            detail=(
                f"day must be between {AVAILABLE_FROM.isoformat()} and "
                f"{AVAILABLE_TO.isoformat()}"
            ),
        )


def validate_range(from_day: date, to_day: date) -> None:
    validate_day(from_day)
    validate_day(to_day)
    if from_day > to_day:
        raise HTTPException(status_code=422, detail="from must be on or before to")


def requested_days(from_day: date, to_day: date) -> list[date]:
    return list(pd.date_range(from_day, to_day, freq="D").date)


@lru_cache(maxsize=None)
def selected_for_cutoff(cutoff_hour: int, cutoff_minute: int) -> pd.DataFrame:
    """Cache all delivery-day selections for each valid cutoff time."""
    _, forecasts, _ = load_snapshot()
    return select_day_ahead_forecast(
        forecasts,
        requested_days(AVAILABLE_FROM, AVAILABLE_TO),
        cutoff_hour=cutoff_hour,
        cutoff_minute=cutoff_minute,
        tz=LONDON_TZ,
    )


def all_selected(cutoff_hour: int, cutoff_minute: int) -> pd.DataFrame:
    return selected_for_cutoff(cutoff_hour, cutoff_minute)


def local_days(frame: pd.DataFrame, from_day: date, to_day: date) -> pd.DataFrame:
    """Filter timestamped data to inclusive London-local delivery dates."""
    work = frame.copy()
    local_date = pd.to_datetime(work["startTime"], utc=True).dt.tz_convert(LONDON_TZ).dt.date
    return work.loc[(local_date >= from_day) & (local_date <= to_day)].copy()


@app.get("/api/meta")
def meta(request: Request) -> dict[str, object]:
    actuals, forecasts, _ = load_snapshot()
    return {
        "delivery_days_available": {
            "from": AVAILABLE_FROM.isoformat(),
            "to": AVAILABLE_TO.isoformat(),
        },
        "default_cutoff": {"hour": 9, "minute": 0, "timezone": LONDON_TZ},
        "data_sources": {"actuals": "FUELHH (fuelType=WIND)", "forecasts": "WINDFOR"},
        "row_counts": {
            "actuals": len(actuals),
            "forecasts": len(forecasts),
        },
        "assumptions": [
            "The purchase decision for delivery day D is made on D-1 at the cutoff (default 09:00 Europe/London). This is an assumption, not the market gate time. Forecasts are published every 2 to 4 hours, so results change in steps as the cutoff moves.",
            "For each hour, the forecast used is the latest publication at or before the cutoff.",
            "Elexon does not define what WINDFOR startTime refers to. We align the forecast at T with the hourly actual starting at T. Shifting the alignment by up to 2 hours changed MAE by under 5%.",
            "Actuals are half-hourly; each hourly actual is the mean of the two half-hours starting at T and T+30 minutes.",
        ],
    }


@app.get("/api/day")
def day_view(
    request: Request,
    day: date,
    cutoff_hour: int = Query(9, ge=0, le=23),
    cutoff_minute: int = Query(0, ge=0, le=59),
) -> dict[str, object]:
    validate_day(day)
    _, _, hourly_actuals = load_snapshot()
    selected = local_days(all_selected(cutoff_hour, cutoff_minute), day, day)
    rows = selected.merge(hourly_actuals, on="startTime", how="left")[
        ["startTime", "actual", "forecast", "publishTime", "cutoff", "horizon_hours"]
    ]
    accuracy = accuracy_summary(
        rows, no_forecast_hours=int(rows["forecast"].isna().sum())
    )
    return {
        "day": day.isoformat(),
        "cutoff": utc_iso(rows["cutoff"].iloc[0]),
        "hours": dataframe_records(rows),
        "accuracy_summary": dataframe_record(accuracy),
    }


@app.get("/api/day/vintages")
def day_vintages(
    request: Request,
    day: date,
    cutoff_hour: int = Query(9, ge=0, le=23),
    cutoff_minute: int = Query(0, ge=0, le=59),
) -> dict[str, object]:
    validate_day(day)
    _, forecasts, _ = load_snapshot()
    selected = local_days(all_selected(cutoff_hour, cutoff_minute), day, day)
    cutoff = selected["cutoff"].iloc[0]
    selected_publish_times = set(selected["publishTime"].dropna())
    forecasts = local_days(forecasts, day, day)
    eligible = forecasts.loc[forecasts["publishTime"] <= cutoff]
    vintages = []
    for publish_time, rows in eligible.groupby("publishTime", sort=False):
        series = rows.rename(columns={"generation": "forecast"})[["startTime", "forecast"]]
        vintages.append(
            {
                "publishTime": publish_time,
                "hours": dataframe_records(series.sort_values("startTime")),
                "selected": publish_time in selected_publish_times,
            }
        )
    vintages.sort(key=lambda vintage: vintage["publishTime"], reverse=True)
    return {
        "day": day.isoformat(),
        "cutoff": utc_iso(cutoff),
        "vintages": vintages[:8],
    }


@app.get("/api/accuracy")
def accuracy_view(
    request: Request,
    from_day: date = Query(..., alias="from"),
    to_day: date = Query(..., alias="to"),
    cutoff_hour: int = Query(9, ge=0, le=23),
    cutoff_minute: int = Query(0, ge=0, le=59),
) -> dict[str, object]:
    validate_range(from_day, to_day)
    _, forecasts, hourly_actuals = load_snapshot()
    selected = local_days(
        all_selected(cutoff_hour, cutoff_minute), from_day, to_day
    )
    hourly_actuals = local_days(hourly_actuals, from_day, to_day)
    joined = selected.merge(hourly_actuals, on="startTime", how="inner")
    no_forecast_hours = int(selected["forecast"].isna().sum())
    all_forecasts = local_days(forecasts, from_day, to_day)
    return {
        "from": from_day.isoformat(),
        "to": to_day.isoformat(),
        "cutoff": {"hour": cutoff_hour, "minute": cutoff_minute, "timezone": LONDON_TZ},
        "no_forecast_hours": no_forecast_hours,
        "accuracy_summary": dataframe_record(
            accuracy_summary(joined, no_forecast_hours=no_forecast_hours)
        ),
        "by_hour": dataframe_records(error_by_hour(joined, LONDON_TZ)),
        "by_day": dataframe_records(error_by_day(joined, LONDON_TZ)),
        "by_output_band": dataframe_records(error_by_output_band(joined)),
        "by_horizon": dataframe_records(
            error_by_horizon(all_forecasts, hourly_actuals, HORIZON_BANDS)
        ),
    }


if FRONTEND_DIR.is_dir():
    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        """Serve the built single-page frontend, falling back to index.html."""
        root = FRONTEND_DIR.resolve()
        candidate = (root / path).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(root / "index.html")
