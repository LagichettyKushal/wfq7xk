from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.analysis import accuracy_summary, actuals_to_hourly, select_day_ahead_forecast
from app.main import AVAILABLE_FROM, AVAILABLE_TO, app


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_meta_returns_snapshot_metadata(client: TestClient) -> None:
    response = client.get("/api/meta")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "delivery_days_available",
        "default_cutoff",
        "data_sources",
        "row_counts",
        "assumptions",
    }
    assert body["row_counts"] == {"actuals": 1536, "forecasts": 18688}


def test_day_and_vintages_return_expected_keys(client: TestClient) -> None:
    day_response = client.get("/api/day?day=2026-01-02")
    vintage_response = client.get("/api/day/vintages?day=2026-01-02")

    assert day_response.status_code == 200
    assert set(day_response.json()) == {"day", "cutoff", "hours", "accuracy_summary"}
    assert len(day_response.json()["hours"]) == 24
    assert day_response.json()["hours"][0].keys() == {
        "startTime", "actual", "forecast", "publishTime", "cutoff", "horizon_hours"
    }
    assert vintage_response.status_code == 200
    assert set(vintage_response.json()) == {"day", "cutoff", "vintages"}
    assert vintage_response.json()["vintages"][0].keys() == {
        "publishTime", "hours", "selected"
    }


def test_accuracy_matches_direct_pure_function_result(client: TestClient) -> None:
    response = client.get("/api/accuracy?from=2026-01-02&to=2026-02-01")

    expected_selected = select_day_ahead_forecast(
        client.app.state.forecasts,
        pd.date_range(AVAILABLE_FROM, AVAILABLE_TO, freq="D").date,
    )
    expected_joined = expected_selected.merge(
        actuals_to_hourly(client.app.state.actuals), on="startTime", how="inner"
    )
    expected = accuracy_summary(expected_joined).iloc[0]
    body = response.json()

    assert response.status_code == 200
    assert set(body) >= {
        "accuracy_summary", "by_hour", "by_day", "by_output_band", "by_horizon", "no_forecast_hours"
    }
    assert body["accuracy_summary"]["n"] == expected["n"]
    assert body["accuracy_summary"]["mae"] == pytest.approx(expected["mae"])
    assert body["accuracy_summary"]["bias"] == pytest.approx(expected["bias"])


def test_out_of_range_day_returns_clear_422(client: TestClient) -> None:
    response = client.get("/api/day?day=2026-02-02")

    assert response.status_code == 422
    assert "between 2026-01-02 and 2026-02-01" in response.json()["detail"]


def test_missing_forecast_is_serialised_as_null(client: TestClient) -> None:
    missing_start = pd.Timestamp("2026-01-02T00:00:00Z")
    client.app.state.forecasts = client.app.state.forecasts.loc[
        client.app.state.forecasts["startTime"] != missing_start
    ].copy()
    client.app.state.selection_cache.clear()

    response = client.get("/api/day?day=2026-01-02")

    assert response.status_code == 200
    first_hour = response.json()["hours"][0]
    assert first_hour["forecast"] is None
    assert first_hour["publishTime"] is None
    assert first_hour["horizon_hours"] is None
