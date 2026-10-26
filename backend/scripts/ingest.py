"""Refresh the local Elexon WIND actuals and forecasts snapshot."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import httpx
import pandas as pd


BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 4
WEEK = timedelta(days=7)


def datetime_chunks(start: datetime, end: datetime) -> Iterator[tuple[datetime, datetime]]:
    """Yield consecutive, seven-day datetime windows, inclusive at boundaries."""
    current = start
    while current < end:
        next_boundary = min(current + WEEK, end)
        yield current, next_boundary
        current = next_boundary


def date_chunks(start: date, end: date) -> Iterator[tuple[date, date]]:
    """Yield consecutive, seven-day date windows, inclusive at boundaries."""
    current = start
    while current < end:
        next_boundary = min(current + WEEK, end)
        yield current, next_boundary
        current = next_boundary


def get_rows(
    client: httpx.Client, path: str, params: dict[str, str]
) -> list[dict[str, Any]]:
    """Fetch a JSON array with retries for transient API and network failures."""
    url = f"{BASE_URL}{path}"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.get(url, params=params)
            if response.status_code in {429, 500, 502, 503, 504}:
                response.raise_for_status()
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise TypeError(f"Expected a JSON array of objects from {response.url}")
            return rows
        except (httpx.HTTPError, TypeError) as error:
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(f"Failed after {MAX_ATTEMPTS} attempts: {url}") from error
            time.sleep(2 ** (attempt - 1))
    raise AssertionError("unreachable")


def normalise(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Normalise API rows into a deterministic UTC dataframe."""
    frame = pd.DataFrame(rows)
    for column in ("startTime", "publishTime"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="raise")
    frame["generation"] = pd.to_numeric(frame["generation"], errors="raise").astype(float)
    return frame.drop_duplicates().sort_values(
        [column for column in ("publishTime", "startTime") if column in frame]
    ).reset_index(drop=True)


def fetch_forecasts(client: httpx.Client) -> pd.DataFrame:
    """Fetch WINDFOR publications from 31 December through 31 January."""
    start = datetime(2025, 12, 31, tzinfo=timezone.utc)
    end = datetime(2026, 2, 1, tzinfo=timezone.utc)
    chunks = []
    for chunk_start, chunk_end in datetime_chunks(start, end):
        params = {
            "publishDateTimeFrom": chunk_start.isoformat().replace("+00:00", "Z"),
            "publishDateTimeTo": chunk_end.isoformat().replace("+00:00", "Z"),
        }
        print(f"WINDFOR {params}")
        chunks.append(normalise(get_rows(client, "/datasets/WINDFOR/stream", params)))
    return normalise(pd.concat(chunks, ignore_index=True).to_dict("records"))


def fetch_actuals(client: httpx.Client) -> pd.DataFrame:
    """Fetch FUELHH WIND settlement days from 1 January through 1 February."""
    start = date(2026, 1, 1)
    end = date(2026, 2, 1)
    chunks = []
    for chunk_start, chunk_end in date_chunks(start, end):
        params = {
            "settlementDateFrom": chunk_start.isoformat(),
            "settlementDateTo": chunk_end.isoformat(),
            "fuelType": "WIND",
        }
        print(f"FUELHH {params}")
        chunks.append(normalise(get_rows(client, "/datasets/FUELHH/stream", params)))
    return normalise(pd.concat(chunks, ignore_index=True).to_dict("records"))


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        forecasts = fetch_forecasts(client)
        actuals = fetch_actuals(client)

    forecasts.to_parquet(DATA_DIR / "forecasts.parquet", index=False)
    actuals.to_parquet(DATA_DIR / "actuals.parquet", index=False)
    print(f"Wrote {len(forecasts)} forecast rows to {DATA_DIR / 'forecasts.parquet'}")
    print(f"Wrote {len(actuals)} actual rows to {DATA_DIR / 'actuals.parquet'}")


if __name__ == "__main__":
    main()
