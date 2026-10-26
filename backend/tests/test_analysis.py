from datetime import date

import pandas as pd
import pytest

from app.analysis import actuals_to_hourly, select_day_ahead_forecast


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
