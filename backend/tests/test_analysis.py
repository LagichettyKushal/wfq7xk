from datetime import date

import pandas as pd
import pytest

from app.analysis import (
    accuracy_summary,
    actuals_to_hourly,
    error_by_day,
    error_by_horizon,
    error_by_hour,
    error_by_output_band,
    select_day_ahead_forecast,
)


UTC = "UTC"


def forecasts(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["startTime", "publishTime", "generation"])


def test_publication_at_cutoff_is_included_and_later_one_is_excluded() -> None:
    frame = forecasts(
        [
            ("2026-01-02T00:00:00Z", "2026-01-01T09:00:00Z", 100.0),
            ("2026-01-02T00:00:00Z", "2026-01-01T09:01:00Z", 200.0),
        ]
    )

    result = select_day_ahead_forecast(frame, [date(2026, 1, 2)])

    row = result.iloc[0]
    assert row["forecast"] == 100.0
    assert row["publishTime"] == pd.Timestamp("2026-01-01T09:00:00Z")


def test_latest_eligible_publication_is_chosen() -> None:
    frame = forecasts(
        [
            ("2026-01-02T00:00:00Z", "2026-01-01T06:30:00Z", 100.0),
            ("2026-01-02T00:00:00Z", "2026-01-01T08:30:00Z", 150.0),
        ]
    )

    result = select_day_ahead_forecast(frame, [date(2026, 1, 2)])

    assert result.iloc[0]["forecast"] == 150.0


def test_post_cutoff_forecast_is_never_used() -> None:
    frame = forecasts(
        [("2026-01-02T00:00:00Z", "2026-01-01T09:01:00Z", 200.0)]
    )

    result = select_day_ahead_forecast(frame, [date(2026, 1, 2)])

    assert pd.isna(result.iloc[0]["forecast"])


def test_missing_forecast_is_a_nan_row_not_a_dropped_row() -> None:
    frame = forecasts(
        [("2026-01-02T00:00:00Z", "2026-01-01T08:00:00Z", 100.0)]
    )

    result = select_day_ahead_forecast(frame, [date(2026, 1, 2)])

    assert len(result) == 24
    assert result["forecast"].notna().sum() == 1
    assert pd.isna(result.iloc[1]["forecast"])


@pytest.mark.parametrize(
    ("delivery_day", "expected_cutoff"),
    [
        (date(2026, 7, 2), "2026-07-01T08:00:00Z"),
        (date(2026, 1, 2), "2026-01-01T09:00:00Z"),
    ],
)
def test_cutoff_uses_london_dst(delivery_day: date, expected_cutoff: str) -> None:
    result = select_day_ahead_forecast(forecasts([]), [delivery_day])

    assert result.iloc[0]["cutoff"] == pd.Timestamp(expected_cutoff)


def test_actuals_to_hourly_averages_and_skips_incomplete_hours() -> None:
    actuals = pd.DataFrame(
        [
            ("2026-01-02T00:00:00Z", 100.0),
            ("2026-01-02T00:30:00Z", 200.0),
            ("2026-01-02T01:00:00Z", 300.0),
        ],
        columns=["startTime", "generation"],
    )

    result = actuals_to_hourly(actuals)

    assert len(result) == 1
    assert result.iloc[0]["startTime"] == pd.Timestamp("2026-01-02T00:00:00Z")
    assert result.iloc[0]["actual"] == 150.0


def test_accuracy_summary_uses_signed_bias_and_absolute_error_percentiles() -> None:
    joined = pd.DataFrame(
        {
            "forecast": [10.0, 4.0, float("nan")],
            "actual": [8.0, 8.0, 10.0],
        }
    )

    result = accuracy_summary(joined, no_forecast_hours=1).iloc[0]

    assert result["n"] == 2
    assert result["mean_actual"] == 8.0
    assert result["mean_forecast"] == 7.0
    assert result["mae"] == 3.0
    assert result["rmse"] == pytest.approx(10**0.5)
    assert result["bias"] == -1.0
    assert result["mae_pct_of_mean_actual"] == 37.5
    assert result["p05_error"] == pytest.approx(-3.7)
    assert result["p95_error"] == pytest.approx(1.7)
    assert result["p50_absolute_error"] == 3.0
    assert result["p90_absolute_error"] == pytest.approx(3.8)
    assert result["p95_absolute_error"] == pytest.approx(3.9)
    assert result["no_forecast_hours"] == 1


def test_error_by_hour_and_day_convert_start_times_to_requested_timezone() -> None:
    joined = pd.DataFrame(
        {
            "startTime": ["2026-07-01T23:00:00Z", "2026-07-02T00:00:00Z", "2026-07-02T00:00:00Z"],
            "forecast": [12.0, 7.0, float("nan")],
            "actual": [10.0, 10.0, 10.0],
        }
    )

    by_hour = error_by_hour(joined, "Europe/London")
    by_day = error_by_day(joined, "Europe/London")

    assert by_hour.to_dict("records") == [
        {"hour": 0, "mae": 2.0, "bias": 2.0, "n": 1},
        {"hour": 1, "mae": 3.0, "bias": -3.0, "n": 1},
    ]
    assert by_day.to_dict("records") == [
        {"delivery_date": date(2026, 7, 2), "mae": 2.5, "bias": -0.5, "n": 2}
    ]


def test_error_by_output_band_calculates_hand_checked_group_values() -> None:
    joined = pd.DataFrame(
        {"forecast": [2.0, 1.0, 5.0, 4.0], "actual": [1.0, 2.0, 3.0, 4.0]}
    )

    result = error_by_output_band(joined, bins=2)

    assert result["mean_actual"].tolist() == [1.5, 3.5]
    assert result["output_band"].map(type).eq(str).all()
    assert result["mae"].tolist() == [1.0, 1.0]
    assert result["bias"].tolist() == [0.0, 1.0]
    assert result["n"].tolist() == [2, 2]


def test_error_by_horizon_excludes_non_positive_horizons_and_groups_bands() -> None:
    forecasts = pd.DataFrame(
        [
            ("2026-01-02T01:00:00Z", "2026-01-02T00:00:00Z", 12.0),
            ("2026-01-02T02:00:00Z", "2026-01-01T18:00:00Z", 20.0),
            ("2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z", 99.0),
        ],
        columns=["startTime", "publishTime", "generation"],
    )
    hourly_actuals = pd.DataFrame(
        [
            ("2026-01-02T00:00:00Z", 10.0),
            ("2026-01-02T01:00:00Z", 10.0),
            ("2026-01-02T02:00:00Z", 10.0),
        ],
        columns=["startTime", "actual"],
    )

    result = error_by_horizon(
        forecasts,
        hourly_actuals,
        [("0-6h", 0, 6), ("6-12h", 6, 12)],
    )

    assert result.to_dict("records") == [
        {"horizon_band": "0-6h", "mae": 2.0, "bias": 2.0, "n": 1},
        {"horizon_band": "6-12h", "mae": 10.0, "bias": 10.0, "n": 1},
    ]
