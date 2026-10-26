from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.analysis import accuracy_summary, select_day_ahead_forecast
from app import main
from app.main import AVAILABLE_FROM, AVAILABLE_TO, app


@pytest.fixture
def client() -> TestClient:
    yield TestClient(app)


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
    actuals, forecasts, hourly_actuals = main.load_snapshot()

    expected_selected = select_day_ahead_forecast(
        forecasts,
        pd.date_range(AVAILABLE_FROM, AVAILABLE_TO, freq="D").date,
    )
    expected_joined = expected_selected.merge(
        hourly_actuals, on="startTime", how="inner"
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
    assert body["accuracy_summary"]["p05_error"] == pytest.approx(expected["p05_error"])
    assert body["accuracy_summary"]["p95_error"] == pytest.approx(expected["p95_error"])


def test_out_of_range_day_returns_clear_422(client: TestClient) -> None:
    response = client.get("/api/day?day=2026-02-02")

    assert response.status_code == 422
    assert "between 2026-01-02 and 2026-02-01" in response.json()["detail"]


def test_missing_forecast_is_serialised_as_null(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    missing_start = pd.Timestamp("2026-01-02T00:00:00Z")
    actuals, forecasts, hourly_actuals = main.load_snapshot()
    modified_forecasts = forecasts.loc[
        forecasts["startTime"] != missing_start
    ].copy()
    monkeypatch.setattr(main, "load_snapshot", lambda: (actuals, modified_forecasts, hourly_actuals))
    main.selected_for_cutoff.cache_clear()

    response = client.get("/api/day?day=2026-01-02")

    assert response.status_code == 200
    first_hour = response.json()["hours"][0]
    assert first_hour["forecast"] is None
    assert first_hour["publishTime"] is None
    assert first_hour["horizon_hours"] is None
