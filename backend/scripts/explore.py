"""Print data-quality and coverage observations for the local Elexon snapshot."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
UTC = ZoneInfo("UTC")
LONDON = ZoneInfo("Europe/London")


def typical(values: pd.Series) -> str:
    """Return the median as a compact, robust typical value."""
    return str(values.median())


def print_common_report(label: str, frame: pd.DataFrame) -> None:
    print(f"\n{label}")
    print(f"Rows: {len(frame)}")
    print(f"startTime range: {frame['startTime'].min()} to {frame['startTime'].max()}")
    print(f"publishTime range: {frame['publishTime'].min()} to {frame['publishTime'].max()}")
    print(f"Duplicate full rows: {int(frame.duplicated().sum())}")
    print("Nulls: " + str(frame.isna().sum().to_dict()))
    print(f"Negative generation rows: {int((frame['generation'] < 0).sum())}")
    print(f"Zero generation rows: {int((frame['generation'] == 0).sum())}")


def explore_actuals(actuals: pd.DataFrame) -> None:
    print_common_report("ACTUALS (FUELHH WIND)", actuals)
    problems: list[str] = []
    for settlement_day, rows in actuals.groupby("settlementDate", sort=True):
        expected = pd.date_range(
            f"{settlement_day}T00:00:00Z", periods=48, freq="30min", tz="UTC"
        )
        observed = pd.DatetimeIndex(rows["startTime"].unique())
        missing = expected.difference(observed)
        extra = observed.difference(expected)
        if len(rows) != 48 or len(missing) or len(extra):
            problems.append(
                f"{settlement_day}: rows={len(rows)}, "
                f"missing={[str(value) for value in missing]}, "
                f"extra={[str(value) for value in extra]}"
            )
    print("Exactly 48 rows per settlement day: " + ("yes" if not problems else "no"))
    if problems:
        print("Missing or extra half-hours:")
        print("\n".join(problems))
    else:
        print("Missing or extra half-hours: none")


def explore_forecasts(forecasts: pd.DataFrame) -> None:
    print_common_report("FORECASTS (WINDFOR)", forecasts)
    publication_times = forecasts["publishTime"].drop_duplicates().sort_values()
    publication_gaps = publication_times.diff().dropna()
    horizons = forecasts["startTime"] - forecasts["publishTime"]
    print(f"Distinct publishTime values: {len(publication_times)}")
    print(
        "Publication gaps: "
        f"min={publication_gaps.min()}, max={publication_gaps.max()}, "
        f"typical={typical(publication_gaps)}"
    )
    print(
        "Forecast horizon: "
        f"min={horizons.min()}, max={horizons.max()}, typical={typical(horizons)}"
    )
    print("All startTime values on the UTC hour: " + str((forecasts["startTime"].dt.minute == 0).all()).lower())

    early_rows = forecasts[forecasts["startTime"] < forecasts["publishTime"]]
    print(
        "Publications contain startTime earlier than publishTime: "
        + (f"yes ({len(early_rows)} rows)" if len(early_rows) else "no")
    )

    print("\nDelivery-day publication coverage")
    incomplete: list[str] = []
    delivery_day = date(2026, 1, 2)
    while delivery_day <= date(2026, 2, 1):
        cutoff = pd.Timestamp(delivery_day - timedelta(days=1), tz=LONDON).replace(hour=9)
        cutoff_utc = cutoff.tz_convert(UTC)
        eligible = publication_times[publication_times <= cutoff_utc]
        if eligible.empty:
            message = f"{delivery_day}: no publication at or before {cutoff}"
            print(message)
            incomplete.append(message)
        else:
            latest = eligible.iloc[-1]
            start_times = pd.DatetimeIndex(
                forecasts.loc[forecasts["publishTime"] == latest, "startTime"].unique()
            )
            expected_hours = pd.date_range(
                f"{delivery_day}T00:00:00Z", periods=24, freq="h", tz="UTC"
            )
            covers_all = expected_hours.isin(start_times).all()
            message = (
                f"{delivery_day}: latest={latest}, "
                f"covers all 24 hours={'yes' if covers_all else 'no'}"
            )
            print(message)
            if not covers_all:
                incomplete.append(message)
        delivery_day += timedelta(days=1)

    print("Incomplete delivery days: " + ("none" if not incomplete else "; ".join(incomplete)))


def main() -> None:
    actuals = pd.read_parquet(DATA_DIR / "actuals.parquet")
    forecasts = pd.read_parquet(DATA_DIR / "forecasts.parquet")
    for frame in (actuals, forecasts):
        frame["startTime"] = pd.to_datetime(frame["startTime"], utc=True)
        frame["publishTime"] = pd.to_datetime(frame["publishTime"], utc=True)

    explore_actuals(actuals)
    explore_forecasts(forecasts)


if __name__ == "__main__":
    main()
