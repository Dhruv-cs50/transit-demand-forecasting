"""
tests/test_backtest_windows.py
──────────────────────────────
models/baselines/backtest_windows.py: all four leaderboard models on three
half-year windows.

- the windows are the six months after each fit_through, and the published one
  is the config's test window;
- a window's models see no row after its fit_through (changing every later
  actual leaves SARIMA's, Prophet's and seasonal naive's forecasts unchanged;
  Chronos is forecast from a store cut at the window's last month);
- on the published window (2025-H2) SARIMA, Prophet and seasonal naive score the
  leaderboard's WAPE, MAE, n and own-band coverage exactly (Chronos needs its
  weights and is covered by the script's own hard check);
- the hard check refuses a table that differs from the leaderboard; two runs
  write identical bytes.

The real-model tests use the committed feature store (ridership only).

    python -m pytest tests/test_backtest_windows.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from models.baselines import backtest_windows as bw  # noqa: E402
from models.baselines import benchmarks  # noqa: E402

# statsmodels says this for every fit on ~30-48 monthly points.
pytestmark = pytest.mark.filterwarnings("ignore:Too few observations:UserWarning")

CFG_PATH = REPO / "configs" / "model.yaml"
STORE_PATH = REPO / "data" / "processed" / "feature_store.parquet"
# The published leaderboard (docs/sprint-board.md, S7-13): overall rows.
PUBLISHED = {
    "SARIMA": dict(wape=3.21, mae=3086.41, n=300, own=96.67),
    "Prophet": dict(wape=5.75, mae=5526.41, n=300, own=46.0),
    "SeasonalNaive": dict(wape=10.75, mae=10332.88, n=300, own=94.33),
}


@pytest.fixture(scope="module")
def cfg() -> dict:
    return benchmarks.load_config()


@pytest.fixture(scope="module")
def store() -> pd.DataFrame:
    df = pd.read_parquet(STORE_PATH)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def window(wid: str) -> dict:
    return next(w for w in bw.WINDOWS if w["id"] == wid)


# ── Windows ────────────────────────────────────────────────────────────────────

def test_the_three_windows_are_valid_for_the_config(cfg):
    bw.check_windows(bw.WINDOWS, cfg)
    assert [w["id"] for w in bw.WINDOWS] == ["2024-H2", "2025-H1", "2025-H2"]


def test_published_window_is_the_configs_test_window(cfg):
    w = window(bw.PUBLISHED_WINDOW)
    assert pd.Timestamp(w["fit_through"]) == pd.Timestamp(cfg["data"]["val_end"])
    assert bw.month_end(w["last_month"]) == benchmarks.config_test_end(cfg)


@pytest.mark.parametrize("change, message", [
    ({"first_month": "2024-08"}, "forecasts months"),
    ({"last_month": "2025-01"}, "forecasts months"),
    ({"fit_through": "2024-06-29"}, "not a month end"),
])
def test_a_misaligned_window_is_refused(cfg, change, message):
    windows = [dict(w) for w in bw.WINDOWS]
    windows[0].update(change)
    with pytest.raises(ValueError, match=message):
        bw.check_windows(windows, cfg)


def test_a_published_window_that_is_not_the_test_window_is_refused(cfg):
    windows = [dict(w) for w in bw.WINDOWS]
    windows[2].update(fit_through="2025-05-31", first_month="2025-06", last_month="2025-11")
    with pytest.raises(ValueError, match="not the config's test window"):
        bw.check_windows(windows, cfg)


@pytest.mark.parametrize("wid", ["2024-H2", "2025-H1", "2025-H2"])
def test_window_frames_split_at_fit_through_and_hold_six_months(store, cfg, wid):
    w = window(wid)
    train, test = bw.window_frames(store, cfg, w)
    fit = pd.Timestamp(w["fit_through"])
    assert train["timestamp"].max() <= fit
    assert train["timestamp"].min() >= pd.Timestamp(cfg["data"]["train_start"])
    assert test["timestamp"].min() > fit
    months = sorted(test["timestamp"].dt.strftime("%Y-%m").unique())
    assert months == list(pd.period_range(w["first_month"], w["last_month"], freq="M").strftime("%Y-%m"))
    assert len(test) == 300 and test["station_id"].nunique() == 50
    assert set(test.index).isdisjoint(train.index)


def test_published_window_test_rows_are_the_benchmarks_test_split(store, cfg):
    _, test = bw.window_frames(store, cfg, window("2025-H2"))
    pd.testing.assert_frame_equal(test, benchmarks.select_test_window(store, cfg))


def test_published_window_train_rows_are_the_benchmarks_train_df(store, cfg):
    train, _ = bw.window_frames(store, cfg, window("2025-H2"))
    val_end = pd.Timestamp(cfg["data"]["val_end"])
    expected = store[(store["timestamp"] <= val_end) & (store["timestamp"] >= pd.Timestamp(cfg["data"]["train_start"]))]
    pd.testing.assert_frame_equal(train, expected)


# ── No data after fit_through ──────────────────────────────────────────────────

def _poisoned(store: pd.DataFrame, fit_through: str) -> pd.DataFrame:
    """The store with every ridership after fit_through replaced by nonsense."""
    out = store.copy()
    later = out["timestamp"] > pd.Timestamp(fit_through)
    out.loc[later, "ridership"] = out.loc[later, "ridership"] * 1000.0 + 12345.0
    return out


@pytest.mark.parametrize("wid", ["2024-H2", "2025-H1"])
def test_models_use_nothing_after_fit_through(store, cfg, wid, tmp_path):
    stations = sorted(store["station_id"].unique())[:3]
    small = store[store["station_id"].isin(stations)].reset_index(drop=True)
    w = window(wid)
    scratch_a, scratch_b = tmp_path / "arima", tmp_path / "prophet"
    freq = cfg["data"]["resample_freq"]

    from models.baselines.arima import run_arima_all_stations
    from models.baselines.prophet_baseline import run_prophet_all_stations

    def forecasts(frame):
        train, test = bw.window_frames(frame, cfg, w)
        fit = pd.Timestamp(w["fit_through"])
        return {
            "naive": benchmarks.seasonal_naive_forecast(train, test, freq),
            "sarima": run_arima_all_stations(frame, cfg, output_dir=scratch_a, train_cutoff=fit,
                                             horizon_steps=6, freq=freq),
            "prophet": run_prophet_all_stations(frame, cfg, output_dir=scratch_b, train_cutoff=fit,
                                                horizon_steps=6, freq=freq),
        }

    clean, dirty = forecasts(small), forecasts(_poisoned(small, w["fit_through"]))
    for name in clean:
        keep = ["timestamp", "station_id", "p10", "p50", "p90"]
        assert len(clean[name]) == 18, name
        pd.testing.assert_frame_equal(clean[name][keep].reset_index(drop=True),
                                      dirty[name][keep].reset_index(drop=True), obj=name)


class _FakePredictor:
    """Stands in for models.chronos2.predict.Predictor; records what it was given."""
    mode = "zeroshot"

    def __init__(self, store: pd.DataFrame):
        self._store = store
        self._full = store
        self.calls = []

    def get_feature_store(self):
        return self._store

    def forecast_all_stations(self, as_of=None, output_path=None, force_mode=None):
        self.calls.append((pd.Timestamp(as_of), self._store["timestamp"].max(), force_mode))
        return pd.DataFrame({"timestamp": [pd.Timestamp(as_of) + pd.offsets.MonthBegin(1)], "station_id": ["EM"],
                             "p10": [1.0], "p50": [2.0], "p90": [3.0]})


@pytest.mark.parametrize("wid, last", [("2024-H2", "2024-12-01"), ("2025-H1", "2025-06-01"), ("2025-H2", "2025-12-01")])
def test_chronos_is_forecast_from_a_store_cut_at_the_windows_last_month(store, cfg, tmp_path, wid, last):
    w = window(wid)
    predictor = _FakePredictor(store)
    benchmarks._forecast_checked(predictor, pd.Timestamp(w["fit_through"]), bw.month_end(w["last_month"]),
                                 tmp_path / "x.parquet", "zeroshot")
    (as_of, newest, mode), = predictor.calls
    assert as_of == pd.Timestamp(w["fit_through"]) and mode == "zeroshot"
    assert newest == pd.Timestamp(last)
    assert predictor._store is predictor._full  # restored


# ── Scoring, the hard check, reproducibility ───────────────────────────────────

def _fake_forecaster(bias: dict):
    """A stand-in for forecast_window: each model forecasts the actuals times (1 + bias)."""
    def run(df, cfg, w, predictor, scratch):
        _, test = bw.window_frames(df, cfg, w)
        out = {}
        for label in bw.model_labels(cfg):
            p50 = test["ridership"].to_numpy(float) * (1 + bias[label])
            out[label] = pd.DataFrame({"timestamp": test["timestamp"].to_numpy(), "station_id": test["station_id"].to_numpy(),
                                       "p10": p50 * 0.9, "p50": p50, "p90": p50 * 1.1})
        return out
    return run


def test_run_backtest_scores_each_window_and_counts_stations_sarima_beats(store, cfg):
    labels = bw.model_labels(cfg)
    bias = dict(zip(labels, (0.01, 0.02, 0.03, 0.04)))
    table, stations, forecasts = bw.run_backtest(store, cfg, forecaster=_fake_forecaster(bias))

    assert list(table.columns) == bw.CSV_COLUMNS
    assert len(table) == 12 and set(table["window"]) == {"2024-H2", "2025-H1", "2025-H2"}
    assert (table["n"] == 300).all() and (table["n_expected"] == 300).all()
    sarima = table[table["model"] == "SARIMA"]
    assert sarima["stations_sarima_beats"].isna().all()
    # SARIMA is the closest to the actuals at every station, so it beats every other model everywhere.
    assert (table[table["model"] != "SARIMA"]["stations_sarima_beats"] == 50).all()
    # A forecast 1% off has WAPE 1% (to rounding); bands of +-10% cover every actual.
    assert table.set_index(["window", "model"]).loc[("2025-H2", "SARIMA"), "wape"] == pytest.approx(1.0, abs=0.01)
    assert (table["coverage_own_band"] == 100.0).all()
    assert len(stations) == 12 * 50 and set(stations.columns) == set(bw.STATION_COLUMNS)
    assert set(forecasts) == {"2024-H2", "2025-H1", "2025-H2"}


def test_stations_sarima_beats_is_a_strict_count():
    stations = pd.DataFrame({
        "window": "w", "model": ["SARIMA"] * 3 + ["Prophet"] * 3,
        "station_id": list("ABC") * 2, "wape": [1.0, 2.0, 3.0, 2.0, 2.0, 1.0], "mae": 0.0, "n": 6,
    })
    assert bw.sarima_beats(stations, "w", "Prophet") == 1.0  # A only; B ties, C loses
    assert np.isnan(bw.sarima_beats(stations, "w", "SARIMA"))


def test_a_missing_model_stops_the_run(store, cfg):
    def partial(df, c, w, predictor, scratch):
        out = _fake_forecaster({m: 0.0 for m in bw.model_labels(c)})(df, c, w, predictor, scratch)
        out.pop("Prophet")
        return out
    with pytest.raises(RuntimeError, match="no forecasts from"):
        bw.run_backtest(store, cfg, forecaster=partial)


def test_a_model_that_missed_a_station_is_rejected(store, cfg):
    def short(df, c, w, predictor, scratch):
        out = _fake_forecaster({m: 0.0 for m in bw.model_labels(c)})(df, c, w, predictor, scratch)
        out["SARIMA"] = out["SARIMA"][out["SARIMA"]["station_id"] != "EM"]
        return out
    with pytest.raises(RuntimeError, match="rejected"):
        bw.run_backtest(store, cfg, forecaster=short)


def _leaderboard(table: pd.DataFrame) -> pd.DataFrame:
    pub = table[table["window"] == bw.PUBLISHED_WINDOW]
    return pd.DataFrame({"model": pub["model"], "slice": "overall", "WAPE_%": pub["wape"], "MAE": pub["mae"],
                         "n": pub["n"], "Coverage_raw_%": pub["coverage_own_band"]})


def test_the_hard_check_passes_on_equal_rows_and_names_every_difference(store, cfg):
    bias = dict(zip(bw.model_labels(cfg), (0.01, 0.02, 0.03, 0.04)))
    table, _, _ = bw.run_backtest(store, cfg, forecaster=_fake_forecaster(bias))
    board = _leaderboard(table)
    assert bw.check_against_leaderboard(table, board) == []

    for column, bad in (("WAPE_%", 99.0), ("MAE", 1.0), ("n", 299), ("Coverage_raw_%", 1.0)):
        broken = board.copy()
        broken.loc[broken["model"] == "Prophet", column] = bad
        problems = bw.check_against_leaderboard(table, broken)
        assert len(problems) == 1 and "Prophet" in problems[0] and column in problems[0], (column, problems)

    assert any("models differ" in p for p in bw.check_against_leaderboard(table, board[board["model"] != "SARIMA"]))


def test_main_writes_nothing_when_the_published_window_differs(store, cfg, tmp_path, monkeypatch):
    bias = dict(zip(bw.model_labels(cfg), (0.01, 0.02, 0.03, 0.04)))
    real = bw.run_backtest
    table, _, _ = real(store, cfg, forecaster=_fake_forecaster(bias))
    board = _leaderboard(table)
    board.loc[board["model"] == "SARIMA", "WAPE_%"] += 0.01
    lb = tmp_path / "leaderboard.csv"
    board.to_csv(lb, index=False)
    # main() runs the stand-in forecaster instead of the real models.
    monkeypatch.setattr(bw, "run_backtest", lambda df, c: real(df, c, forecaster=_fake_forecaster(bias)))
    out = tmp_path / "out"
    assert bw.main(["--feature-store", str(STORE_PATH), "--out-dir", str(out), "--leaderboard", str(lb)]) == 1
    assert not out.exists()
    # and with an equal leaderboard it writes the table
    _leaderboard(table).to_csv(lb, index=False)
    assert bw.main(["--feature-store", str(STORE_PATH), "--out-dir", str(out), "--leaderboard", str(lb)]) == 0
    assert (out / "backtest_windows.csv").exists() and (out / "backtest_windows_stations.csv").exists()


def test_main_without_a_leaderboard_stops(tmp_path):
    assert bw.main(["--out-dir", str(tmp_path / "o"), "--leaderboard", str(tmp_path / "none.csv")]) == 1


def test_two_runs_write_identical_bytes(store, cfg, tmp_path):
    bias = dict(zip(bw.model_labels(cfg), (0.01, 0.02, 0.03, 0.04)))
    dirs = []
    for i in (1, 2):
        table, stations, forecasts = bw.run_backtest(store, cfg, forecaster=_fake_forecaster(bias))
        d = tmp_path / f"run{i}"
        bw.write_outputs(table, stations, forecasts, d)
        dirs.append(d)
    files = sorted(p.relative_to(dirs[0]) for p in dirs[0].rglob("*") if p.is_file())
    assert len(files) == 2 + 12
    for f in files:
        assert (dirs[0] / f).read_bytes() == (dirs[1] / f).read_bytes(), f


# ── The published window equals the leaderboard (real models) ──────────────────

def _published_window_rows(store, cfg, models, scratch):
    """Run the real model functions on 2025-H2 and score them."""
    w = window(bw.PUBLISHED_WINDOW)
    train, test = bw.window_frames(store, cfg, w)
    freq = cfg["data"]["resample_freq"]
    fit = pd.Timestamp(w["fit_through"])
    out = {}
    if "SeasonalNaive" in models:
        out["SeasonalNaive"] = benchmarks.seasonal_naive_forecast(train, test, freq)
    if "SARIMA" in models:
        from models.baselines.arima import run_arima_all_stations
        out["SARIMA"] = run_arima_all_stations(store, cfg, output_dir=scratch / "arima", train_cutoff=fit,
                                               horizon_steps=6, freq=freq)
    if "Prophet" in models:
        from models.baselines.prophet_baseline import run_prophet_all_stations
        out["Prophet"] = run_prophet_all_stations(store, cfg, output_dir=scratch / "prophet", train_cutoff=fit,
                                                  horizon_steps=6, freq=freq)
    return {label: bw.score_model(test, train, preds, label)[0] for label, preds in out.items()}


@pytest.mark.parametrize("models", [("SeasonalNaive", "SARIMA", "Prophet")])
def test_published_window_rows_equal_the_leaderboard(store, cfg, models, tmp_path):
    rows = _published_window_rows(store, cfg, models, tmp_path)
    for label, want in PUBLISHED.items():
        got = rows[label]
        assert (got["WAPE_%"], got["MAE"], got["n"], got["Coverage_%"]) == (
            want["wape"], want["mae"], want["n"], want["own"]), label
