"""Inspect small, live FUELHH and WINDFOR API responses without persisting data."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx


BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
FUELHH_PARAMS = {
    "settlementDateFrom": "2026-01-01",
    "settlementDateTo": "2026-01-02",
    "fuelType": "WIND",
}
WINDFOR_PARAMS = {
    "publishDateTimeFrom": "2026-01-01T00:00:00Z",
    "publishDateTimeTo": "2026-01-03T00:00:00Z",
}


def print_response(label: str, response: httpx.Response) -> list[dict[str, Any]]:
    """Print the requested response details and return its JSON rows."""
    print(f"\n{label}")
    print(f"URL: {response.url}")
    print(f"Status: {response.status_code}")
    response.raise_for_status()

    rows = response.json()
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise TypeError("Expected a JSON array of objects")

    columns = sorted({column for row in rows for column in row})
    print(f"Row count: {len(rows)}")
    print(f"Columns: {columns}")
    print("First 3 rows:")
    print(json.dumps(rows[:3], indent=2))
    return rows


def parse_api_datetime(value: str) -> datetime:
    """Parse Elexon's ISO-8601 UTC timestamps for summary comparisons."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> None:
    with httpx.Client(timeout=30.0) as client:
        fuelhh = client.get(f"{BASE_URL}/datasets/FUELHH/stream", params=FUELHH_PARAMS)
        print_response("FUELHH (WIND actuals)", fuelhh)

        windfor = client.get(
            f"{BASE_URL}/datasets/WINDFOR/stream", params=WINDFOR_PARAMS
        )
        forecasts = print_response("WINDFOR (forecast publish window)", windfor)

    publish_times = [parse_api_datetime(row["publishTime"]) for row in forecasts]
    start_times = [parse_api_datetime(row["startTime"]) for row in forecasts]
    print("\nWINDFOR time summary")
    print(f"Min publishTime: {min(publish_times).isoformat()}")
    print(f"Max publishTime: {max(publish_times).isoformat()}")
    print(f"Min startTime: {min(start_times).isoformat()}")
    print(f"Max startTime: {max(start_times).isoformat()}")
    print(f"Distinct publishTime values: {len(set(publish_times))}")


if __name__ == "__main__":
    main()
