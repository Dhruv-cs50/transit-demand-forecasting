"""Tests for the Caltrain benchmark across half-year windows (Task 3).

The benchmark scores seasonal naive, SARIMA (exog = every step column), Prophet
(same columns as regressors) and zero-shot Chronos-1 (univariate) on the half-year
windows that pass the admission rule in configs/caltrain.yaml. The module is imported
inside each test so a missing module fails each test on its own.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parent.parent
CFG_PATH = ROOT / "configs" / "caltrain.yaml"

MODELS = ["SeasonalNaive", "SARIMA", "Prophet", "Chronos1_ZeroShot (chronos-t5-small)"]
COLUMNS = ["window", "model", "wape", "mae", "n", "coverage_own_band", "status"]
STEPS = ["electrified", "method_2023_11", "method_2025_01"]


def _bench():
    from models.caltrain import benchmark

    return benchmark


@pytest.fixture(scope="module")
def cfg() -> dict:
    return yaml.safe_load(CFG_PATH.read_text())


@pytest.fixture(scope="module")
def store(cfg, tmp_path_factory) -> pd.DataFrame:
    from machine_learning_files.caltrain_store import build_caltrain_store

    # Never write the committed parquet from a test.
    path = tmp_path_factory.mktemp("store") / "caltrain_store.parquet"
    return build_caltrain_store({**cfg, "store_path": str(path)})


def _hash_tree(paths: list[Path]) -> dict[str, str]:
    out = {}
    for p in paths:
        files = [p] if p.is_file() else sorted(f for f in p.rglob("*") if f.is_file()) if p.exists() else []
        for f in files:
            out[str(f.relative_to(ROOT))] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def _bart_paths() -> list[Path]:
    paths = [ROOT / "data" / "processed" / "feature_store.parquet"]
    paths += sorted((ROOT / "website" / "data").glob("*.json"))
    paths += [ROOT / "models" / "baselines" / "outputs", ROOT / "models" / "chronos2" / "outputs"]
    eval_out = ROOT / "evaluation" / "outputs"
    if eval_out.exists():
        paths += [p for p in sorted(eval_out.iterdir()) if p.name != "caltrain"]
    return paths


@pytest.fixture(scope="module")
def runs(store, cfg, tmp_path_factory):
    """Run the benchmark twice into separate directories, with a BART hash check around it.

    A third run uses a store whose post-cutoff ridership is multiplied by 10 and whose
    post-cutoff step columns are scrambled; its forecasts must not change.
    """
    bench = _bench()
    from models.chronos2.predict import Predictor

    before = _hash_tree(_bart_paths())
    predictor_store_before = Predictor()._store
    a, b, c = (tmp_path_factory.mktemp(n) for n in ("run_a", "run_b", "run_leak"))
    lb_a = bench.run_caltrain_benchmark(store, cfg, out_dir=a)
    lb_b = bench.run_caltrain_benchmark(store, cfg, out_dir=b)

    # Perturb everything after the last admitted cutoff minus one: a leak into any
    # earlier window's fit would move that window's forecasts.
    perturbed = store.copy()
    after = perturbed["timestamp"] > pd.Timestamp("2025-06-01")
    perturbed.loc[after, "ridership"] = perturbed.loc[after, "ridership"] * 10
    rng = np.random.default_rng(0)
    for col in STEPS:
        perturbed.loc[after, col] = rng.integers(0, 2, int(after.sum()))
    lb_c = bench.run_caltrain_benchmark(perturbed, cfg, out_dir=c)

    # Same again for the test window alone: only months after its own cutoff change.
    d = tmp_path_factory.mktemp("run_leak_test_window")
    only_test = {**cfg, "benchmark": {**cfg["benchmark"], "windows": [
        w for w in cfg["benchmark"]["windows"] if w["name"] == "2026-H1"]}}
    perturbed = store.copy()
    after = perturbed["timestamp"] > pd.Timestamp("2025-12-01")
    perturbed.loc[after, "ridership"] = perturbed.loc[after, "ridership"] * 10
    for col in STEPS:
        perturbed.loc[after, col] = rng.integers(0, 2, int(after.sum()))
    bench.run_caltrain_benchmark(perturbed, only_test, out_dir=d)
    after_run = _hash_tree(_bart_paths())
    return {
        "a": a, "b": b, "c": c, "d": d, "lb_a": lb_a, "lb_b": lb_b, "lb_c": lb_c,
        "bart_before": before, "bart_after": after_run,
        "predictor_store_before": predictor_store_before, "Predictor": Predictor,
    }


# --------------------------------------------------------------------------
# Window rule


def test_window_rule_admits_only_supported_windows(store, cfg):
    windows = _bench().evaluate_windows(store, cfg).set_index("window")
    assert list(windows.index) == [w["name"] for w in cfg["benchmark"]["windows"]]
    admitted = list(windows.index[windows["admitted"]])
    assert admitted == ["2025-H2", "2026-H1"]
    # Fewer than three windows is reported, never padded.
    assert len(admitted) < 3
    assert windows.loc["2026-H1", "role"] == "test"
    assert windows.loc["2025-H2", "role"] == "development"
    assert windows.loc["2024-H2", "role"] == "rejected"
    # Each rejection names its reason.
    assert "insufficient history" in windows.loc["2023-H2", "reason"]
    assert "electrified" in windows.loc["2024-H2", "reason"]
    assert "method_2023_11" in windows.loc["2024-H1", "reason"]
    assert "method_2025_01" in windows.loc["2025-H1", "reason"]
    assert "electrified" in windows.loc["2025-H1", "reason"]  # 4 months at 1 before the cutoff
    assert windows.loc["2025-H2", "reason"] == ""
    assert windows.loc["2025-H2", "pre_method_2025_01"] == 6  # exactly the minimum: admitted
    assert windows.loc["2025-H2", "usable_months"] >= 24


def _synthetic(step_month: str, last_month: str = "2025-12"):
    months = pd.date_range("2022-01-01", f"{last_month}-01", freq="MS")
    store = pd.DataFrame(
        {"timestamp": months, "station_id": "CALTRAIN_SYSTEM",
         "ridership": np.linspace(10000, 20000, len(months))}
    )
    cfg = {
        "electrification_start": "2099-01",
        "method_changes": [step_month],
        "exclude": [],
        "train_start": "2022-01",
        "benchmark": {
            "horizon_steps": 6, "min_train_months": 24, "min_step_support_months": 6,
            "test_window": "2025-H2",
            "windows": [{"name": "2025-H2", "start": "2025-07", "end": "2025-12", "cutoff": "2025-06"}],
        },
    }
    return store, cfg


def test_window_rule_requires_step_support():
    bench = _bench()
    # The step starts 2025-02: Feb..Jun is 5 months at 1 before the cutoff -> rejected.
    store, cfg = _synthetic("2025-02")
    row = bench.evaluate_windows(store, cfg).iloc[0]
    assert not row["admitted"]
    assert "method_2025_02" in row["reason"] and "5" in row["reason"]
    # The step starts 2025-01: Jan..Jun is 6 months -> admitted (>=, not >).
    store, cfg = _synthetic("2025-01")
    row = bench.evaluate_windows(store, cfg).iloc[0]
    assert row["admitted"], row["reason"]
    # A step that is 0 over the whole window needs no support.
    store, cfg = _synthetic("2026-03")
    assert bench.evaluate_windows(store, cfg).iloc[0]["admitted"]
    # A step with no training support at all is rejected.
    store, cfg = _synthetic("2025-08")
    assert not bench.evaluate_windows(store, cfg).iloc[0]["admitted"]


def test_window_rule_requires_complete_actuals():
    store, cfg = _synthetic("2025-01", last_month="2025-11")  # December 2025 missing
    row = _bench().evaluate_windows(store, cfg).iloc[0]
    assert not row["admitted"] and "incomplete actuals" in row["reason"]
    assert "2025-12" in row["reason"]


def test_window_cutoff_must_precede_start(cfg, store):
    bad = {**cfg, "benchmark": {**cfg["benchmark"], "windows": [
        {"name": "2025-H2", "start": "2025-07", "end": "2025-12", "cutoff": "2025-07"}]}}
    with pytest.raises(ValueError, match="cutoff"):
        _bench().evaluate_windows(store, bad)


# --------------------------------------------------------------------------
# Known future schedule and leakage


def test_step_known_future_and_no_leak(cfg, store, runs):
    bench = _bench()
    months = pd.date_range("2025-07-01", periods=6, freq="MS")
    sched = bench.known_schedule(cfg, months)
    assert list(sched.columns) == STEPS
    assert (sched["electrified"] == 1).all() and (sched["method_2023_11"] == 1).all()
    assert (sched["method_2025_01"] == 1).all()
    sched = bench.known_schedule(cfg, pd.date_range("2024-07-01", periods=6, freq="MS"))
    assert sched["electrified"].tolist() == [0, 0, 1, 1, 1, 1]  # 2024-09 launch
    assert sched["method_2025_01"].tolist() == [0, 0, 0, 0, 0, 0]
    assert sched["method_2023_11"].tolist() == [1] * 6

    # The training slice stops at the cutoff and starts at train_start.
    train = bench.training_slice(store, cfg, pd.Timestamp("2025-06-01"))
    assert train["timestamp"].max() == pd.Timestamp("2025-06-01")
    assert train["timestamp"].min() == pd.Timestamp("2022-01-01")
    assert len(train) == 42

    # Ridership and step columns after the cutoff changed; no forecast moved.
    for slug in ("seasonal_naive", "sarima", "prophet", "chronos1"):
        fa = pd.read_parquet(runs["a"] / f"forecasts_{slug}.parquet")
        fc = pd.read_parquet(runs["c"] / f"forecasts_{slug}.parquet")
        # The perturbation starts after 2025-06, the cutoff of 2025-H2, so both
        # admitted windows are checked (2026-H1 sees 2025-07..2025-12 as history).
        h2 = fa["window"] == "2025-H2"
        pd.testing.assert_frame_equal(
            fa[h2].reset_index(drop=True), fc[fc["window"] == "2025-H2"].reset_index(drop=True))
        fd = pd.read_parquet(runs["d"] / f"forecasts_{slug}.parquet")
        t = fa["window"] == "2026-H1"
        assert len(fd) == 6 and t.sum() == 6
        pd.testing.assert_frame_equal(fa[t].reset_index(drop=True), fd.reset_index(drop=True))
    # And the actuals did change, so the check could have failed.
    assert not runs["lb_a"].equals(runs["lb_c"])


def test_known_schedule_matches_the_store_columns(cfg, store):
    sched = _bench().known_schedule(cfg, pd.DatetimeIndex(store["timestamp"]))
    for col in STEPS:
        assert sched[col].tolist() == store[col].tolist(), col


# --------------------------------------------------------------------------
# Cells


def test_leaderboard_shape_and_status(runs, cfg):
    lb = runs["lb_a"]
    assert list(lb.columns) == COLUMNS
    ok = lb[lb["status"] == "ok"]
    assert sorted(ok["window"].unique()) == ["2025-H2", "2026-H1"]
    for w in ("2025-H2", "2026-H1"):
        cells = ok[ok["window"] == w]
        assert list(cells["model"]) == MODELS
        assert (cells["n"] == 6).all()
        assert cells[["wape", "mae", "coverage_own_band"]].notna().all().all()


def test_insufficient_history_cell(runs):
    lb = runs["lb_a"]
    for w in ("2023-H1", "2023-H2"):
        cells = lb[lb["window"] == w]
        assert list(cells["model"]) == MODELS  # never dropped
        assert (cells["status"] == "insufficient history").all()
        assert cells["wape"].isna().all() and (cells["n"] == 0).all()  # never a silent zero


def test_insufficient_history_cell_for_a_short_fit(cfg, store, tmp_path):
    # min_train_months raised above what 2025-H2 has: explicit cell, nothing fitted.
    strict = {**cfg, "benchmark": {**cfg["benchmark"], "min_train_months": 43}}
    lb = _bench().run_caltrain_benchmark(store, strict, out_dir=tmp_path)
    cells = lb[lb["window"] == "2025-H2"]
    assert (cells["status"] == "insufficient history").all()
    assert cells["wape"].isna().all()


# --------------------------------------------------------------------------
# Determinism and BART isolation


def test_two_runs_identical(runs):
    pd.testing.assert_frame_equal(runs["lb_a"], runs["lb_b"])
    names_a = sorted(p.name for p in runs["a"].iterdir())
    names_b = sorted(p.name for p in runs["b"].iterdir())
    assert names_a == names_b
    assert {"leaderboard.csv", "windows.csv"} <= set(names_a)
    for name in names_a:
        assert (runs["a"] / name).read_bytes() == (runs["b"] / name).read_bytes(), name


def test_bart_outputs_untouched(runs):
    bench = _bench()
    assert bench.DEFAULT_OUT_DIR == ROOT / "evaluation" / "outputs" / "caltrain"
    assert runs["bart_before"] == runs["bart_after"]
    assert (ROOT / "data" / "processed" / "feature_store.parquet").exists()
    # The shared Chronos predictor still holds whatever store it held before the run.
    assert runs["Predictor"]()._store is runs["predictor_store_before"]
    # Only the configured output directory was written, and no temporary work is left.
    assert sorted(p.name for p in runs["a"].iterdir()) == [
        "forecasts_chronos1.parquet", "forecasts_prophet.parquet", "forecasts_sarima.parquet",
        "forecasts_seasonal_naive.parquet", "leaderboard.csv", "windows.csv",
    ]
