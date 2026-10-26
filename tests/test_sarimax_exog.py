"""
tests/test_sarimax_exog.py
──────────────────────────
Optional exog in models/baselines/arima.py: the default (no-exog) path is the
same fit as a direct SARIMAX call, bad exog fails the station instead of the
run, the label is applied, and exog actually reaches the model.

Synthetic panel only (two stations, monthly 2022-01 .. 2025-12, timestamps in
datetime64[us] like the feature store).

    python -m pytest tests/test_sarimax_exog.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.baselines.arima import (  # noqa: E402
    _future_exog,
    _standardised_train_exog,
    fit_station,
    predict_station,
    run_arima_all_stations,
)

FREQ = "MS"
H = 6
CUTOFF = "2025-06-30"
CFG = {
    "data": {
        "train_start": "2022-01-01",
        "train_end": "2024-12-31",
        "val_end": "2025-06-30",
        "forecast_horizon_steps": H,
        "resample_freq": FREQ,
    },
    "chronos2": {},
}
FUTURE = pd.date_range("2025-07-01", periods=H, freq=FREQ)


def _panel(seed: int = 0, stations=("AA", "BB"), beta_frac: float = 0.0) -> pd.DataFrame:
    """Yearly seasonality plus noise; ridership = ... + beta_frac * level * x."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2022-01-01", "2025-12-01", freq=FREQ).as_unit("us")
    m = np.arange(len(ts))
    frames = []
    for i, sid in enumerate(stations):
        level = 10_000.0 * (i + 1)
        x = rng.normal(size=len(ts))
        z = rng.normal(size=len(ts))
        y = (
            level
            + 0.15 * level * np.sin(2 * np.pi * m / 12)
            + beta_frac * level * x
            + rng.normal(0, 0.01 * level, size=len(ts))
        )
        frames.append(pd.DataFrame({
            "timestamp": ts, "station_id": sid, "ridership": y, "x": x, "z": z,
        }))
    return pd.concat(frames, ignore_index=True)


def _run(df: pd.DataFrame, out: Path, **kwargs) -> pd.DataFrame:
    return run_arima_all_stations(
        df, CFG, output_dir=out, train_cutoff=CUTOFF, horizon_steps=H, freq=FREQ, **kwargs
    )


def _train_rows(df: pd.DataFrame, sid: str) -> pd.DataFrame:
    return df[
        (df["station_id"] == sid)
        & (df["timestamp"] >= pd.Timestamp("2022-01-01"))
        & (df["timestamp"] <= pd.Timestamp(CUTOFF))
    ]


def _direct_sarimax(df: pd.DataFrame, sid: str):
    """The pre-registered SARIMA, fitted by hand with the leaderboard's settings."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    series = (
        _train_rows(df, sid)
        .sort_values("timestamp")
        .set_index("timestamp")["ridership"]
        .resample(FREQ)
        .mean()
        .interpolate(method="time")
        .clip(lower=0)
    )
    fit = SARIMAX(
        series,
        order=(0, 1, 1),
        seasonal_order=(0, 1, 1, 12),
        enforce_stationarity=True,
        enforce_invertibility=True,
        trend="n",
    ).fit(disp=False, method="lbfgs", maxiter=100)
    fc = fit.get_forecast(steps=H)
    ci = fc.conf_int(alpha=0.20)
    return (
        np.maximum(ci.iloc[:, 0].values, 0),
        np.maximum(fc.predicted_mean.values, 0),
        np.maximum(ci.iloc[:, 1].values, 0),
    )


def _mae(df: pd.DataFrame, preds: pd.DataFrame) -> float:
    m = preds.merge(df[["timestamp", "station_id", "ridership"]], on=["timestamp", "station_id"])
    assert len(m) == len(preds) == 2 * H
    return float(np.mean(np.abs(m["ridership"] - m["p50"])))


# ── (a) default path is the direct SARIMAX fit ─────────────────────────────────

def test_no_exog_matches_direct_sarimax(tmp_path):
    df = _panel()
    preds = _run(df, tmp_path)
    assert set(preds["station_id"]) == {"AA", "BB"}
    assert (preds["model"] == "SARIMA").all()
    for sid in ("AA", "BB"):
        got = preds[preds["station_id"] == sid].sort_values("timestamp")
        assert list(got["timestamp"]) == list(FUTURE)
        p10, p50, p90 = _direct_sarimax(df, sid)
        np.testing.assert_array_equal(got["p10"].values, p10)
        np.testing.assert_array_equal(got["p50"].values, p50)
        np.testing.assert_array_equal(got["p90"].values, p90)


# ── (b)-(d) bad exog fails that station, not the run ───────────────────────────

def test_nan_in_training_exog_fails_the_station(tmp_path):
    df = _panel()
    df.loc[(df["station_id"] == "AA") & (df["timestamp"] == pd.Timestamp("2023-03-01")), "x"] = np.nan
    preds = _run(df, tmp_path, exog_cols=["x"])
    assert set(preds["station_id"]) == {"BB"}


def test_missing_future_exog_month_fails_the_station(tmp_path):
    df = _panel()
    df = df[~((df["station_id"] == "AA") & (df["timestamp"] == pd.Timestamp("2025-08-01")))]
    preds = _run(df, tmp_path, exog_cols=["x"])
    assert set(preds["station_id"]) == {"BB"}


def test_nan_in_future_exog_fails_the_station(tmp_path):
    df = _panel()
    df.loc[(df["station_id"] == "AA") & (df["timestamp"] == pd.Timestamp("2025-11-01")), "x"] = np.nan
    preds = _run(df, tmp_path, exog_cols=["x"])
    assert set(preds["station_id"]) == {"BB"}


@pytest.mark.parametrize("constant", [3.0, 0.1])
def test_zero_variance_exog_fails_the_station(tmp_path, constant):
    # 0.1 is not exact in binary, so its float SD can come out as ~1e-17
    # rather than 0; it must still be treated as zero variance.
    df = _panel()
    df["k"] = df["x"]
    df.loc[df["station_id"] == "AA", "k"] = constant
    preds = _run(df, tmp_path, exog_cols=["k"])
    assert set(preds["station_id"]) == {"BB"}


def test_unknown_exog_column_raises(tmp_path):
    with pytest.raises(KeyError, match="not_a_column"):
        _run(_panel(), tmp_path, exog_cols=["x", "not_a_column"])


# ── (e) label ──────────────────────────────────────────────────────────────────

def test_model_label_is_applied(tmp_path):
    preds = _run(_panel(), tmp_path, exog_cols=["x", "z"], model_label="SARIMAX + test")
    assert set(preds["station_id"]) == {"AA", "BB"}
    assert (preds["model"] == "SARIMAX + test").all()


# ── (f) exog reaches the model ─────────────────────────────────────────────────

def test_exog_that_drives_y_lowers_out_of_sample_error(tmp_path):
    df = _panel(seed=3, beta_frac=0.10)
    plain = _run(df, tmp_path / "plain")
    with_x = _run(df, tmp_path / "exog", exog_cols=["x"], model_label="SARIMAX + x")
    mae_plain, mae_x = _mae(df, plain), _mae(df, with_x)
    assert mae_x < mae_plain
    # Not a near-tie: y moves by 10% of level per SD of x, noise is 1%.
    assert mae_x < 0.5 * mae_plain


# ── standardisation uses the training window only ──────────────────────────────

def test_standardisation_uses_training_window_stats():
    df = _panel()
    rows = df[df["station_id"] == "AA"]
    train = _train_rows(df, "AA")
    z_train, mean, sd = _standardised_train_exog(train, ["x", "z"], FREQ)
    np.testing.assert_allclose(z_train.mean().values, 0.0, atol=1e-12)
    np.testing.assert_allclose(z_train.std(ddof=0).values, 1.0, rtol=1e-12)
    raw_train = train.set_index("timestamp")[["x", "z"]]
    np.testing.assert_allclose(mean.values, raw_train.mean().values)
    np.testing.assert_allclose(sd.values, raw_train.std(ddof=0).values)

    # Future values are scaled with the training stats, and changing them does
    # not move the training stats.
    shifted = rows.copy()
    after = shifted["timestamp"] > pd.Timestamp(CUTOFF)
    shifted.loc[after, ["x", "z"]] += 100.0
    _, mean2, sd2 = _standardised_train_exog(_train_rows(shifted, "AA"), ["x", "z"], FREQ)
    pd.testing.assert_series_equal(mean, mean2)
    pd.testing.assert_series_equal(sd, sd2)
    z_future = _future_exog(shifted, ["x", "z"], z_train.index[-1], H, FREQ, mean, sd)
    raw_future = shifted.loc[after].set_index("timestamp")[["x", "z"]]
    np.testing.assert_allclose(z_future.values, ((raw_future - mean) / sd).values)
    assert list(z_future.index) == list(FUTURE)


# ── fit_station / predict_station validate what they are given ─────────────────

def test_fit_station_rejects_non_finite_exog():
    train = _train_rows(_panel(), "AA")
    z_train, _, _ = _standardised_train_exog(train, ["x"], FREQ)
    z_train.iloc[5, 0] = np.inf
    with pytest.raises(ValueError, match="non-finite"):
        fit_station(train, "AA", FREQ, exog=z_train)


def test_predict_station_validates_future_exog():
    df = _panel()
    train = _train_rows(df, "AA")
    z_train, mean, sd = _standardised_train_exog(train, ["x"], FREQ)
    fit, last_ts = fit_station(train, "AA", FREQ, exog=z_train)
    z_future = _future_exog(df[df["station_id"] == "AA"], ["x"], last_ts, H, FREQ, mean, sd)

    ok = predict_station(fit, last_ts, H, FREQ, exog_future=z_future)
    assert list(ok["timestamp"]) == list(FUTURE)

    with pytest.raises(ValueError, match="rows"):
        predict_station(fit, last_ts, H, FREQ, exog_future=z_future.iloc[:-1])
    nan_future = z_future.copy()
    nan_future.iloc[2, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        predict_station(fit, last_ts, H, FREQ, exog_future=nan_future)
    # statsmodels ignores the exog index, so a frame for the wrong months would
    # be used silently; predict_station must refuse it.
    shifted = z_future.copy()
    shifted.index = shifted.index + pd.DateOffset(months=1)
    with pytest.raises(ValueError, match="months"):
        predict_station(fit, last_ts, H, FREQ, exog_future=shifted)
