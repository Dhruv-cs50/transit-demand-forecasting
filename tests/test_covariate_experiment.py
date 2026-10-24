"""
tests/test_covariate_experiment.py
──────────────────────────────────
The covariate experiment's pre-registered pieces: the arms, the two windows,
the station-clustered paired test, the decision rule, and an end-to-end run on
a synthetic store that checks what is (and is not) written.

    python -m pytest tests/test_covariate_experiment.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models.baselines.covariate_experiment import (  # noqa: E402
    ARMS,
    IMPROVES,
    NO_IMPROVEMENT,
    TABLE_COLUMNS,
    build_window,
    decide_verdict,
    run_experiment,
    station_clustered_test,
)


def _repo_config() -> dict:
    with open(ROOT / "configs" / "model.yaml") as f:
        return yaml.safe_load(f)


def test_arms_are_the_pre_registered_ones():
    assert ARMS == [
        ("SARIMA", None),
        ("SARIMAX + weather (observed)", ["temp_f", "precip_mm"]),
        ("SARIMAX + Sharks games", ["hours_to_event"]),
        ("SARIMAX + weather (observed) + Sharks games", ["temp_f", "precip_mm", "hours_to_event"]),
    ]


# ── station-clustered paired test ──────────────────────────────────────────────

# Two months per station. (actual, control p50, arm p50) per month, chosen so
# each station's d_s = mean(|e_control| - |e_arm|) is known by hand.
_CASES = {
    "A": [(100, 90, 95), (100, 120, 105)],   # e_c 10, 20; e_a 5, 5   -> d_s = 10
    "B": [(50, 46, 56), (50, 54, 44)],       # e_c 4, 4;   e_a 6, 6   -> d_s = -2
    "C": [(10, -4, 8), (10, 10, 12)],        # p50 -4 clips to 0: e_c 10, 0; e_a 2, 2 -> d_s = 3
    "D": [(30, 27, 29), (30, 33, 31)],       # e_c 3, 3;   e_a 1, 1   -> d_s = 2
    "E": [(20, 22, 18), (20, 18, 22)],       # tie                    -> d_s = 0
}
_D_S = {"A": 10.0, "B": -2.0, "C": 3.0, "D": 2.0, "E": 0.0}
_MONTHS = pd.date_range("2025-01-01", periods=2, freq="MS").as_unit("us")


def _frames():
    actual, control, arm = [], [], []
    for sid, months in _CASES.items():
        for ts, (y, pc, pa) in zip(_MONTHS, months):
            actual.append({"timestamp": ts, "station_id": sid, "ridership": float(y)})
            control.append({"timestamp": ts, "station_id": sid, "p50": float(pc)})
            arm.append({"timestamp": ts, "station_id": sid, "p50": float(pa)})
    return pd.DataFrame(actual), pd.DataFrame(control), pd.DataFrame(arm)


def test_clustered_test_known_values():
    actual, control, arm = _frames()
    res = station_clustered_test(actual, control, arm)
    d = np.array([_D_S[s] for s in sorted(_D_S)])
    expected = stats.ttest_1samp(d, 0)
    assert res["n_stations"] == 5
    assert res["mean_d"] == pytest.approx(d.mean())          # 2.6; without the clip at 0 it would be 3.0
    assert res["stations_arm_better"] == 3                    # A, C, D
    assert res["stations_control_better"] == 1                # B; E is a tie
    assert res["t"] == pytest.approx(float(expected.statistic))
    assert res["p"] == pytest.approx(float(expected.pvalue))
    per = res["per_station"].set_index("station_id")
    assert per["d"].to_dict() == pytest.approx(_D_S)
    assert per.loc["A", "mae_control"] == pytest.approx(15.0)
    assert per.loc["A", "mae_arm"] == pytest.approx(5.0)


def test_clustered_test_ignores_row_order():
    actual, control, arm = _frames()
    shuffled = station_clustered_test(
        actual.sample(frac=1, random_state=1),
        control.sample(frac=1, random_state=2),
        arm.sample(frac=1, random_state=3),
    )
    assert shuffled["p"] == pytest.approx(station_clustered_test(actual, control, arm)["p"])


def test_clustered_test_raises_when_one_month_is_missing():
    actual, control, arm = _frames()
    with pytest.raises(ValueError, match="pair"):
        station_clustered_test(actual, control, arm.iloc[1:])


def test_clustered_test_raises_when_a_whole_station_is_missing():
    # The other four stations still have equal month counts, so only a full
    # key-set check catches this.
    actual, control, arm = _frames()
    with pytest.raises(ValueError, match="pair"):
        station_clustered_test(actual, control, arm[arm["station_id"] != "A"])


def test_clustered_test_raises_on_unequal_months_per_station():
    actual, control, arm = _frames()
    drop = lambda f: f[~((f["station_id"] == "B") & (f["timestamp"] == _MONTHS[1]))]  # noqa: E731
    with pytest.raises(ValueError, match="month"):
        station_clustered_test(drop(actual), drop(control), drop(arm))


@pytest.mark.parametrize("which", ["actual", "control", "arm"])
def test_clustered_test_raises_on_nan(which):
    frames = dict(zip(["actual", "control", "arm"], _frames()))
    col = "ridership" if which == "actual" else "p50"
    frames[which].loc[3, col] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        station_clustered_test(frames["actual"], frames["control"], frames["arm"])


def test_clustered_test_raises_on_duplicate_rows():
    actual, control, arm = _frames()
    with pytest.raises(ValueError, match="duplicate"):
        station_clustered_test(actual, control, pd.concat([arm, arm.iloc[[0]]]))


# ── windows ────────────────────────────────────────────────────────────────────

def _store(stations=("S1", "S2", "S3"), seed=0) -> pd.DataFrame:
    """Store-shaped panel: 2019, then the 2020-21 gap, then 2022-01 .. 2025-12.
    Weather is missing from 2024 on and event counts are 0 there, as in the
    gate2 store."""
    rng = np.random.default_rng(seed)
    ts = pd.DatetimeIndex(
        list(pd.date_range("2019-01-01", "2019-12-01", freq="MS"))
        + list(pd.date_range("2022-01-01", "2025-12-01", freq="MS"))
    ).as_unit("us")
    frames = []
    for i, sid in enumerate(stations):
        level = 8_000.0 * (i + 1)
        m = ts.month.to_numpy()
        y = level * (1 + 0.12 * np.sin(2 * np.pi * m / 12)) + rng.normal(0, 0.01 * level, len(ts))
        temp = 58 + 8 * np.sin(2 * np.pi * (m - 4) / 12) + rng.normal(0, 1, len(ts))
        precip = np.clip(rng.normal(0.08, 0.05, len(ts)), 0, None)
        season = np.isin(m, [1, 2, 3, 4, 10, 11, 12])
        games = np.where(season, rng.integers(2, 8, len(ts)), 0).astype(float)
        late = ts >= pd.Timestamp("2024-01-01")
        temp[late] = np.nan
        precip[late] = np.nan
        games[late] = 0.0
        frames.append(pd.DataFrame({
            "timestamp": ts, "station_id": sid, "ridership": y,
            "temp_f": temp, "precip_mm": precip, "hours_to_event": games,
        }))
    return pd.concat(frames, ignore_index=True)


def _months(frame: pd.DataFrame) -> list[pd.Timestamp]:
    return sorted(frame["timestamp"].unique())


def test_validation_window():
    cfg = _repo_config()
    before = copy.deepcopy(cfg)
    w = build_window(_store(), cfg, "validation")
    assert w.cutoff == pd.Timestamp("2024-12-31")
    assert _months(w.evaluation) == list(pd.date_range("2025-01-01", "2025-06-01", freq="MS"))
    assert (w.evaluation.groupby("station_id").size() == 6).all()
    assert len(w.evaluation) == 18
    assert w.df["timestamp"].max() == pd.Timestamp("2025-06-01")
    assert w.train["timestamp"].min() == pd.Timestamp("2022-01-01")
    assert w.train["timestamp"].max() == pd.Timestamp("2024-12-01")
    assert w.horizon_steps == 6
    assert w.cfg["data"]["val_end"] == "2024-12-31"
    assert cfg == before, "the loaded config must not be modified"


def test_test_window():
    cfg = _repo_config()
    w = build_window(_store(), cfg, "test")
    assert w.cutoff == pd.Timestamp("2025-06-30")
    assert _months(w.evaluation) == list(pd.date_range("2025-07-01", "2025-12-01", freq="MS"))
    assert (w.evaluation.groupby("station_id").size() == 6).all()
    assert w.df["timestamp"].max() == pd.Timestamp("2025-12-01")
    assert w.train["timestamp"].min() == pd.Timestamp("2022-01-01")
    assert w.train["timestamp"].max() == pd.Timestamp("2025-06-01")


def test_window_raises_on_an_extra_evaluation_month():
    store = _store()
    extra = store[(store["station_id"] == "S2") & (store["timestamp"] == pd.Timestamp("2025-12-01"))].copy()
    extra["timestamp"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="exactly 6"):
        build_window(pd.concat([store, extra], ignore_index=True), _repo_config(), "test")


def test_window_raises_on_a_missing_evaluation_month():
    store = _store()
    store = store[~((store["station_id"] == "S3") & (store["timestamp"] == pd.Timestamp("2025-03-01")))]
    with pytest.raises(ValueError, match="exactly 6"):
        build_window(store, _repo_config(), "validation")


def test_unknown_window_raises():
    with pytest.raises(ValueError):
        build_window(_store(), _repo_config(), "holdout")


# ── decision rule ──────────────────────────────────────────────────────────────

# (test WAPE arm, test WAPE control, clustered p, clustered mean_d,
#  validation WAPE arm, validation WAPE control) -> verdict
_GOOD = dict(test_wape_arm=3.0, test_wape_control=3.2, test_p=0.01, test_mean_d=5.0,
             val_wape_arm=4.0, val_wape_control=4.3)


@pytest.mark.parametrize("c1", [True, False])
@pytest.mark.parametrize("c2", [True, False])
@pytest.mark.parametrize("c3", [True, False])
def test_verdict_truth_table(c1, c2, c3):
    args = dict(_GOOD)
    if not c1:
        args["test_wape_arm"] = 3.3
    if not c2:
        args["test_p"] = 0.20
    if not c3:
        args["val_wape_arm"] = 4.5
    expected = IMPROVES if (c1 and c2 and c3) else NO_IMPROVEMENT
    assert decide_verdict(**args) == expected


@pytest.mark.parametrize("override", [
    {"test_wape_arm": 3.2},                    # tie is not "below"
    {"val_wape_arm": 4.3},                     # tie is not "below"
    {"test_p": 0.05},                          # p must be strictly below 0.05
    {"test_mean_d": -5.0},                     # significant, but the arm is worse
    {"test_mean_d": 0.0},
    {"test_wape_arm": float("nan")},           # rejected arm
    {"test_wape_control": float("nan")},       # rejected control
    {"test_p": float("nan")},                  # comparison not run
    {"test_mean_d": float("nan")},
    {"val_wape_arm": float("nan")},
    {"val_wape_control": float("nan")},
    {"test_p": None},
])
def test_verdict_edge_cases_are_not_improvements(override):
    assert decide_verdict(**{**_GOOD, **override}) == NO_IMPROVEMENT


# ── end to end on a synthetic store ────────────────────────────────────────────

def test_run_experiment_end_to_end(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    eval_dir = tmp_path / "eval"

    table, per_station = run_experiment(_store(), _repo_config(), eval_dir=eval_dir)

    assert list(table.columns[:7]) == ["window", "cutoff", "eval_start", "eval_end", "model", "covariates", "status"]
    assert list(table.columns) == TABLE_COLUMNS
    assert len(table) == 8
    assert list(table["window"]) == ["test"] * 4 + ["validation"] * 4
    assert list(table["model"]) == [label for label, _ in ARMS] * 2

    by = table.set_index(["window", "model"])
    for window, cutoff, start, end in [("test", "2025-06-30", "2025-07-01", "2025-12-01"),
                                       ("validation", "2024-12-31", "2025-01-01", "2025-06-01")]:
        ctl = by.loc[(window, "SARIMA")]
        assert ctl["status"] == "ok"
        assert ctl["n"] == 18 and np.isfinite(ctl["WAPE_%"])
        assert (ctl["cutoff"], ctl["eval_start"], ctl["eval_end"]) == (cutoff, start, end)
        assert ctl["covariates"] == "none"
        assert ctl["verdict"] == ""
        # Weather is NaN from 2024 on, so both weather arms fail every station.
        for label in ("SARIMAX + weather (observed)", "SARIMAX + weather (observed) + Sharks games"):
            row = by.loc[(window, label)]
            assert row["status"].startswith("rejected: no station produced a forecast")
            assert "3 station fit(s) failed: 3× training exog: " in row["status"]
            assert "NaN" in row["status"]
            assert np.isnan(row["WAPE_%"])
            assert np.isnan(row["clustered_p"])
        sharks = by.loc[(window, "SARIMAX + Sharks games")]
        assert sharks["status"] == "ok"
        assert sharks["covariates"] == "hours_to_event"
        assert 0 <= sharks["clustered_p"] <= 1
        assert sharks["stations_arm_better"] + sharks["stations_control_better"] <= 3

    for label, _ in ARMS[1:]:
        assert by.loc[("test", label), "verdict"] in (IMPROVES, NO_IMPROVEMENT)
        assert by.loc[("validation", label), "verdict"] == ""
    for label in ("SARIMAX + weather (observed)", "SARIMAX + weather (observed) + Sharks games"):
        assert by.loc[("test", label), "verdict"] == NO_IMPROVEMENT

    assert list(per_station.columns) == ["window", "model", "station_id", "mae_control", "mae_arm", "d"]
    assert set(per_station["model"]) == {"SARIMAX + Sharks games"}
    assert len(per_station) == 6

    # Written: the two tables and the per-arm forecasts. Nothing else, nowhere else.
    reread = pd.read_csv(eval_dir / "covariate_experiment.csv", keep_default_na=False, na_values=[""])
    assert list(reread.columns) == TABLE_COLUMNS and len(reread) == 8
    assert (eval_dir / "covariate_experiment_stations.csv").exists()
    assert (eval_dir / "covariate_experiment" / "test" / "sarima" / "arima_forecasts.parquet").exists()
    assert (eval_dir / "covariate_experiment" / "validation" / "sarimax-sharks-games" / "arima_forecasts.parquet").exists()
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert not any("leaderboard" in p or "benchmark_results" in p or "website" in p for p in written)
    assert list(cwd.iterdir()) == []
