"""
Tests for Processing.feature_engineering.add_lag_features.

The BART store has 2019 and 2022-2025 but no 2020-21 (never published), so
monthly lags must count calendar months, not rows: a 2022-01 row's lag_1 is
2021-12, which has no data, so it is NaN rather than 2019-12. The sub-monthly
(15-minute) branch is unchanged and still shifts by rows.
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Processing.feature_engineering import add_lag_features  # noqa: E402

LAG_COLS = [f"ridership_lag_{k}" for k in (1, 2, 3, 6, 12)]
ROLLING_COLS = [
    "ridership_rolling_mean_3mo",
    "ridership_rolling_std_3mo",
    "ridership_rolling_mean_12mo",
]
# (column, window, min_periods, statistic) as in add_lag_features.
ROLLING_SPECS = [
    ("ridership_rolling_mean_3mo", 3, 2, "mean"),
    ("ridership_rolling_std_3mo", 3, 2, "std"),
    ("ridership_rolling_mean_12mo", 12, 6, "mean"),
]

MONTHS = list(pd.period_range("2019-01", "2019-12", freq="M")) + list(
    pd.period_range("2022-01", "2023-12", freq="M")
)
STATION_BASE = {"A": 1000.0, "B": 5000.0}
MISSING = ("B", pd.Period("2023-05", freq="M"))  # interior month dropped for B only


def value(station: str, month: str | pd.Period) -> float:
    """Distinct per station and month; A's values (1001-1944) never overlap B's (5001-5944)."""
    p = pd.Period(month, freq="M")
    return STATION_BASE[station] + (p.year - 2019) * 200 + p.month ** 2


def monthly_panel() -> pd.DataFrame:
    rows = []
    for sid in STATION_BASE:
        for p in MONTHS:
            if (sid, p) == MISSING:
                continue
            rows.append({"timestamp": p.to_timestamp(), "station_id": sid, "ridership": value(sid, p)})
    return pd.DataFrame(rows)


def at(out: pd.DataFrame, station: str, month: str, col: str) -> float:
    sel = out[(out["station_id"] == station) & (out["timestamp"].dt.to_period("M") == pd.Period(month, "M"))]
    assert len(sel) == 1, (station, month)
    return sel[col].iloc[0]


@pytest.fixture(scope="module")
def out() -> pd.DataFrame:
    return add_lag_features(monthly_panel())


# ── Spot checks from the story ────────────────────────────────────────────────

@pytest.mark.parametrize("station", ["A", "B"])
def test_lags_do_not_reach_across_the_2020_21_gap(out, station):
    assert np.isnan(at(out, station, "2022-01", "ridership_lag_1"))
    assert np.isnan(at(out, station, "2022-06", "ridership_lag_12"))


@pytest.mark.parametrize("station", ["A", "B"])
def test_lags_count_calendar_months(out, station):
    assert at(out, station, "2023-03", "ridership_lag_12") == value(station, "2022-03")
    assert at(out, station, "2019-05", "ridership_lag_1") == value(station, "2019-04")


def test_missing_interior_month_gives_nan_only_for_that_station(out):
    assert np.isnan(at(out, "B", "2023-06", "ridership_lag_1"))
    assert at(out, "A", "2023-06", "ridership_lag_1") == value("A", "2023-05")


@pytest.mark.parametrize("station", ["A", "B"])
def test_rolling_windows_count_calendar_months(out, station):
    # 2022-02's 3-month window is 2021-11..2022-01: one observation < min_periods 2.
    assert np.isnan(at(out, station, "2022-02", "ridership_rolling_mean_3mo"))
    assert np.isnan(at(out, station, "2022-02", "ridership_rolling_std_3mo"))
    assert at(out, station, "2022-03", "ridership_rolling_mean_3mo") == pytest.approx(
        statistics.mean([value(station, "2022-01"), value(station, "2022-02")])
    )
    # 2022-07's 12-month window is 2021-07..2022-06: six observations = min_periods 6.
    assert at(out, station, "2022-07", "ridership_rolling_mean_12mo") == pytest.approx(
        statistics.mean([value(station, f"2022-0{m}") for m in range(1, 7)])
    )
    assert np.isnan(at(out, station, "2022-06", "ridership_rolling_mean_12mo"))
    assert at(out, station, "2023-04", "ridership_rolling_std_3mo") == pytest.approx(
        statistics.stdev([value(station, m) for m in ("2023-01", "2023-02", "2023-03")])
    )


def test_rolling_window_over_a_missing_month_counts_fewer_observations(out):
    # B's 2023-07 window is 2023-04..06 with 2023-05 missing: two observations.
    assert at(out, "B", "2023-07", "ridership_rolling_std_3mo") == pytest.approx(
        statistics.stdev([value("B", "2023-04"), value("B", "2023-06")])
    )
    assert at(out, "A", "2023-07", "ridership_rolling_std_3mo") == pytest.approx(
        statistics.stdev([value("A", m) for m in ("2023-04", "2023-05", "2023-06")])
    )


# ── Exhaustive oracle and no leakage between stations ─────────────────────────

def expected_row(station: str, p: pd.Period, present: dict) -> dict:
    exp = {}
    for col in LAG_COLS:
        k = int(col.rsplit("_", 1)[1])
        exp[col] = present.get((station, p - k), np.nan)
    for col, window, min_periods, stat in ROLLING_SPECS:
        obs = [present[(station, p - j)] for j in range(1, window + 1) if (station, p - j) in present]
        if len(obs) < min_periods:
            exp[col] = np.nan
        else:
            exp[col] = statistics.mean(obs) if stat == "mean" else statistics.stdev(obs)
    return exp


def test_every_cell_matches_a_calendar_month_oracle(out):
    present = {(sid, p): value(sid, p) for sid in STATION_BASE for p in MONTHS if (sid, p) != MISSING}
    for _, row in out.iterrows():
        exp = expected_row(row["station_id"], row["timestamp"].to_period("M"), present)
        for col, e in exp.items():
            got = row[col]
            if np.isnan(e):
                assert np.isnan(got), (row["station_id"], row["timestamp"], col, got)
            elif col in LAG_COLS:
                assert got == e, (row["station_id"], row["timestamp"], col)
            else:
                # pandas' online rolling variance carries ~1e-12 relative error here
                # (std ~4 on values ~5,000); a wrong window would be off by far more.
                assert got == pytest.approx(e, rel=1e-9), (row["station_id"], row["timestamp"], col)


def test_values_never_come_from_the_other_station(out):
    for sid in STATION_BASE:
        own = out[out["station_id"] == sid]
        own_values = set(own["ridership"])
        lo, hi = min(own_values), max(own_values)
        for col in LAG_COLS:
            assert set(own[col].dropna()) <= own_values, (sid, col)
        for col in ("ridership_rolling_mean_3mo", "ridership_rolling_mean_12mo"):
            vals = own[col].dropna()
            assert ((vals >= lo) & (vals <= hi)).all(), (sid, col)


# ── Shape: row order, columns, dtypes ─────────────────────────────────────────

def test_shuffled_input_returns_sorted_rows_float_columns_in_order():
    panel = monthly_panel()
    shuffled = panel.sample(frac=1.0, random_state=0)
    result = add_lag_features(shuffled)

    expected_index = shuffled.sort_values(["station_id", "timestamp"]).index
    assert result.index.equals(expected_index)
    assert list(result.columns) == ["timestamp", "station_id", "ridership"] + LAG_COLS + ROLLING_COLS
    for col in LAG_COLS + ROLLING_COLS:
        assert result[col].dtype == np.float64, col
    # Same values as the unshuffled run, row for row.
    pd.testing.assert_frame_equal(
        result.reset_index(drop=True), add_lag_features(panel).reset_index(drop=True)
    )


def test_day_of_month_and_timezone_do_not_matter(out):
    panel = monthly_panel()
    panel["timestamp"] = (panel["timestamp"] + pd.Timedelta(days=14, hours=18)).dt.tz_localize(
        "America/Los_Angeles"
    )
    result = add_lag_features(panel)
    pd.testing.assert_frame_equal(
        result[LAG_COLS + ROLLING_COLS].reset_index(drop=True),
        out[LAG_COLS + ROLLING_COLS].reset_index(drop=True),
    )


def test_two_rows_in_one_month_raise():
    panel = monthly_panel()
    dup = pd.DataFrame(
        [{"timestamp": pd.Timestamp("2022-03-15"), "station_id": "A", "ridership": 1.0}]
    )
    with pytest.raises(ValueError, match="2022-03"):
        add_lag_features(pd.concat([panel, dup], ignore_index=True))


# ── Sub-monthly branch: unchanged row shifts ──────────────────────────────────

def test_sub_monthly_output_is_a_plain_row_shift():
    n = 800  # > 672 so lag_672 and the 672-row window are exercised
    frames = []
    for sid, base in (("A", 0.0), ("B", 100_000.0)):
        ts = pd.date_range("2024-01-01", periods=n, freq="15min")
        frames.append(pd.DataFrame({"timestamp": ts, "station_id": sid, "ridership": base + np.arange(n) * 1.5 + (np.arange(n) % 7) ** 2}))
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.drop(index=[10, 400]).sample(frac=1.0, random_state=1)  # a gap: rows != time

    result = add_lag_features(panel)

    ref = panel.sort_values(["station_id", "timestamp"]).copy()
    g = ref.groupby("station_id")["ridership"]
    for lag in (4, 8, 12, 96, 192, 672):
        ref[f"ridership_lag_{lag}"] = g.shift(lag)
    ref["ridership_rolling_mean_24h"] = g.transform(lambda x: x.shift(1).rolling(96, min_periods=24).mean())
    ref["ridership_rolling_std_24h"] = g.transform(lambda x: x.shift(1).rolling(96, min_periods=24).std())
    ref["ridership_rolling_mean_7d"] = g.transform(lambda x: x.shift(1).rolling(672, min_periods=96).mean())

    pd.testing.assert_frame_equal(result, ref)
