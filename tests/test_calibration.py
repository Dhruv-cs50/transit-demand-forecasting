"""
tests/test_calibration.py
─────────────────────────
Unit tests for evaluation/calibration.py (split-conformal widening of P10/P90).

Run with the standard library, no pytest needed:
    python -m unittest tests.test_calibration -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.calibration import (  # noqa: E402
    GROUPS,
    METHODS,
    add_horizon,
    apply_conformal,
    conformal_quantile,
    fit_conformal,
    no_calibration,
)
from evaluation.metrics import coverage  # noqa: E402


def _frame(n_stations: int, n_steps: int, rng: np.random.Generator,
           half_width_sd: float, bias: float = 0.0) -> pd.DataFrame:
    """Synthetic forecasts: y = p50 * (1 + bias + N(0, 0.05)); band = p50 * (1 ± k*0.05)."""
    stations = [f"S{i:02d}" for i in range(n_stations)]
    ts = pd.date_range("2025-01-01", periods=n_steps, freq="MS")
    rows = [(t, s) for s in stations for t in ts]
    df = pd.DataFrame(rows, columns=["timestamp", "station_id"])
    level = rng.uniform(5_000, 50_000, size=n_stations)
    df["p50"] = np.repeat(level, n_steps)
    df["ridership"] = df["p50"] * (1 + bias + rng.normal(0, 0.05, size=len(df)))
    df["p10"] = df["p50"] * (1 - half_width_sd * 0.05)
    df["p90"] = df["p50"] * (1 + half_width_sd * 0.05)
    return df


def _cov(df: pd.DataFrame) -> float:
    return coverage(df["ridership"].values, df["p10"].values, df["p90"].values)


class ConformalQuantileTest(unittest.TestCase):
    def test_finite_sample_rank(self):
        # ceil((10 + 1) * 0.8) = 9 → the 9th smallest of 1..10.
        self.assertEqual(conformal_quantile(np.arange(1, 11), 0.8), 9)

    def test_too_few_scores_is_infinite(self):
        # ceil((3 + 1) * 0.8) = 4 > 3: no finite quantile guarantees 80%.
        self.assertEqual(conformal_quantile(np.array([1.0, 2.0, 3.0]), 0.8), np.inf)

    def test_six_scores_take_the_maximum(self):
        # Per-station calibration on one 6-month window: ceil(7 * 0.8) = 6.
        self.assertEqual(conformal_quantile(np.array([3, 1, 4, 1, 5, 9.0]), 0.8), 9.0)


class ApplyConformalTest(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(0)

    def test_p50_is_never_changed(self):
        cal = _frame(20, 6, self.rng, half_width_sd=0.5)
        target = _frame(20, 6, self.rng, half_width_sd=0.5)
        for method in METHODS:
            for group in GROUPS:
                calib = fit_conformal(add_horizon(cal), method=method, group=group, level=0.8)
                out = apply_conformal(add_horizon(target), calib)
                np.testing.assert_array_equal(out["p50"].values, target["p50"].values)
                self.assertEqual(out["p50"].dtype, target["p50"].dtype)

    def test_no_calibration_keeps_band_and_reports_raw(self):
        target = _frame(10, 6, self.rng, half_width_sd=0.5)
        out = no_calibration(target)
        for col in ("p10", "p50", "p90"):
            np.testing.assert_array_equal(out[col].values, target[col].values)
        np.testing.assert_array_equal(out["p10_raw"].values, target["p10"].values)
        np.testing.assert_array_equal(out["p90_raw"].values, target["p90"].values)

    def test_raw_bounds_are_kept(self):
        cal = _frame(10, 6, self.rng, half_width_sd=0.5)
        target = _frame(10, 6, self.rng, half_width_sd=0.5)
        out = apply_conformal(target, fit_conformal(cal, "scaled", "pooled", 0.8))
        np.testing.assert_array_equal(out["p10_raw"].values, target["p10"].values)
        np.testing.assert_array_equal(out["p90_raw"].values, target["p90"].values)

    def test_narrow_band_is_widened_to_nominal(self):
        # Nominal 80% needs ±1.28 sd; the raw band is ±0.5 sd (~38% coverage).
        cal = _frame(400, 6, self.rng, half_width_sd=0.5)
        target = _frame(4000, 6, self.rng, half_width_sd=0.5)
        self.assertLess(_cov(target), 45)
        for method in METHODS:
            out = apply_conformal(target, fit_conformal(cal, method, "pooled", 0.8))
            self.assertAlmostEqual(_cov(out), 80, delta=2.0, msg=method)

    def test_wide_band_is_narrowed(self):
        cal = _frame(400, 6, self.rng, half_width_sd=3.0)
        target = _frame(400, 6, self.rng, half_width_sd=3.0)
        calib = fit_conformal(cal, "scaled", "pooled", 0.8)
        self.assertLess(calib["q"]["all"], 1.0)
        out = apply_conformal(target, calib)
        self.assertTrue(((out["p90"] - out["p10"]) < (target["p90"] - target["p10"])).all())

    def test_bounds_stay_ordered_and_non_negative(self):
        # Every residual positive: the asymmetric lower quantile is above P50,
        # which would put P10 above P50 if left unclipped.
        cal = _frame(50, 6, self.rng, half_width_sd=0.5, bias=0.5)
        target = _frame(50, 6, self.rng, half_width_sd=0.5)
        target.loc[0, ["p10", "p50", "p90"]] = [0.0, 1.0, 2.0]
        for method in METHODS:
            out = apply_conformal(target, fit_conformal(cal, method, "pooled", 0.8))
            self.assertTrue((out["p10"] <= out["p50"]).all(), method)
            self.assertTrue((out["p50"] <= out["p90"]).all(), method)
            self.assertTrue((out["p10"] >= 0).all(), method)

    def test_zero_half_width_gives_finite_scores(self):
        cal = _frame(10, 6, self.rng, half_width_sd=0.5)
        cal.loc[0, ["p10", "p90"]] = cal.loc[0, "p50"]
        cal.loc[0, "ridership"] = cal.loc[0, "p50"]
        calib = fit_conformal(cal, "scaled", "pooled", 0.8)
        self.assertTrue(np.isfinite(calib["q"]["all"]))

    def test_missing_target_bound_stays_missing(self):
        # A missing interval bound must reach the metrics as NaN so the
        # leaderboard still rejects it (benchmarks.accept_model_rows / #136).
        cal = _frame(10, 6, self.rng, half_width_sd=0.5)
        target = _frame(10, 6, self.rng, half_width_sd=0.5)
        target.loc[3, "p90"] = np.nan
        out = apply_conformal(target, fit_conformal(cal, "scaled", "pooled", 0.8))
        self.assertTrue(np.isnan(out.loc[3, "p90"]))
        self.assertTrue(np.isnan(_cov(out)))

    def test_station_without_calibration_gets_no_interval(self):
        cal = _frame(10, 6, self.rng, half_width_sd=0.5)
        target = _frame(11, 6, self.rng, half_width_sd=0.5)   # S10 never calibrated
        out = apply_conformal(target, fit_conformal(cal, "scaled", "station", 0.8))
        unseen = out["station_id"] == "S10"
        self.assertTrue(out.loc[unseen, ["p10", "p90"]].isna().all().all())
        self.assertTrue(out.loc[~unseen, ["p10", "p90"]].notna().all().all())


class FitConformalTest(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(1)

    def test_missing_forecast_in_calibration_raises(self):
        cal = _frame(10, 6, self.rng, half_width_sd=0.5)
        cal.loc[5, "p10"] = np.nan
        with self.assertRaises(ValueError):
            fit_conformal(cal, "scaled", "pooled", 0.8)

    def test_missing_actual_is_left_out(self):
        cal = _frame(10, 6, self.rng, half_width_sd=0.5)
        cal.loc[5, "ridership"] = np.nan
        calib = fit_conformal(cal, "scaled", "pooled", 0.8)
        self.assertEqual(calib["n"], len(cal) - 1)

    def test_unknown_method_or_group_raises(self):
        cal = _frame(10, 6, self.rng, half_width_sd=0.5)
        with self.assertRaises(ValueError):
            fit_conformal(cal, "nope", "pooled", 0.8)
        with self.assertRaises(ValueError):
            fit_conformal(cal, "scaled", "nope", 0.8)

    def test_asymmetric_method_corrects_bias(self):
        # Forecasts 4% low: a symmetric band centred on P50 splits its misses
        # unevenly; the asymmetric one puts ~10% in each tail. (A bias larger
        # than 1.28 sd would put the true P10 above P50, where apply_conformal
        # pins P10 at P50 rather than publish an incoherent band.)
        cal = _frame(400, 6, self.rng, half_width_sd=0.5, bias=0.04)
        target = _frame(4000, 6, self.rng, half_width_sd=0.5, bias=0.04)
        symmetric = apply_conformal(target, fit_conformal(cal, "relative", "pooled", 0.8))
        self.assertGreater((symmetric["ridership"] > symmetric["p90"]).mean() * 100, 15)
        out = apply_conformal(target, fit_conformal(cal, "asym_relative", "pooled", 0.8))
        below = (out["ridership"] < out["p10"]).mean() * 100
        above = (out["ridership"] > out["p90"]).mean() * 100
        self.assertAlmostEqual(below, 10, delta=2.0)
        self.assertAlmostEqual(above, 10, delta=2.0)


class AddHorizonTest(unittest.TestCase):
    def test_horizon_is_step_within_station(self):
        df = pd.DataFrame({
            "station_id": ["A", "A", "A", "B", "B"],
            "timestamp": pd.to_datetime(
                ["2025-03-01", "2025-01-01", "2025-02-01", "2025-02-01", "2025-01-01"]),
        })
        self.assertEqual(add_horizon(df)["horizon"].tolist(), [3, 1, 2, 2, 1])


if __name__ == "__main__":
    unittest.main()
