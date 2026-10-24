"""
tests/test_benchmark_calibration.py
───────────────────────────────────
How models/baselines/benchmarks.py applies interval calibration: the
per-model config, the failure path, the checkpoint guard and the leaderboard
columns. Synthetic data only; no model is fitted.

    python -m unittest tests.test_benchmark_calibration -v
"""

from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.calibration import (  # noqa: E402
    add_horizon, apply_conformal, describe, fit_conformal, fit_rolling_conformal, with_origin_horizon,
)
from models.baselines.benchmarks import (  # noqa: E402
    calibrate_intervals, compute_metrics, leaderboard_latex,
)

logging.getLogger("benchmarks").setLevel(logging.CRITICAL)


def _preds(start: str, n_stations: int = 8, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=6, freq="MS")
    rows = [(t, f"S{i}") for i in range(n_stations) for t in ts]
    df = pd.DataFrame(rows, columns=["timestamp", "station_id"])
    df["p50"] = rng.uniform(5_000, 50_000, size=len(df))
    df["ridership"] = df["p50"] * (1 + rng.normal(0, 0.05, size=len(df)))
    df["p10"] = df["p50"] * 0.98
    df["p90"] = df["p50"] * 1.02
    return df


def _cfg(**models) -> dict:
    return {"calibration": {"level": 0.8, "models": models}}


class CalibrateIntervalsTest(unittest.TestCase):
    def setUp(self):
        self.val = _preds("2025-01-01", seed=1)
        self.test = _preds("2025-07-01", seed=2)
        self.test_preds = self.test[["timestamp", "station_id", "p10", "p50", "p90"]]
        self.val_preds = self.val[["timestamp", "station_id", "p10", "p50", "p90"]]

    def test_method_none_keeps_band_and_labels_reason(self):
        out, label = calibrate_intervals(
            "SARIMA", "SARIMA", self.test_preds, lambda: self.fail("must not forecast"),
            self.val, _cfg(SARIMA={"method": "none", "reason": "no method passed validation"}))
        np.testing.assert_array_equal(out["p10"].values, self.test_preds["p10"].values)
        np.testing.assert_array_equal(out["p10_raw"].values, self.test_preds["p10"].values)
        self.assertEqual(label, "raw: no method passed validation")

    def test_unlisted_model_is_not_calibrated(self):
        out, label = calibrate_intervals("X", "X", self.test_preds, lambda: None, self.val, _cfg())
        np.testing.assert_array_equal(out["p90"].values, self.test_preds["p90"].values)
        self.assertEqual(label, "raw: not validated")

    def test_calibrated_band_matches_a_fit_on_the_validation_window(self):
        cfg = _cfg(Prophet={"method": "scaled", "group": "horizon"})
        out, label = calibrate_intervals("Prophet", "Prophet", self.test_preds,
                                         lambda: self.val_preds, self.val, cfg)
        expected = apply_conformal(add_horizon(self.test_preds),
                                   fit_conformal(add_horizon(self.val), "scaled", "horizon", 0.8))
        np.testing.assert_array_equal(out["p50"].values, self.test_preds["p50"].values)
        np.testing.assert_allclose(out["p10"].values, expected["p10"].values)
        np.testing.assert_allclose(out["p90"].values, expected["p90"].values)
        self.assertEqual(label, "split-conformal scaled/horizon, fit on validation")

    def test_failed_calibration_gives_nan_bounds_not_the_raw_band(self):
        def boom():
            raise RuntimeError("no validation forecast")
        out, label = calibrate_intervals("Prophet", "Prophet", self.test_preds, boom, self.val,
                                         _cfg(Prophet={"method": "scaled"}))
        self.assertTrue(out[["p10", "p90"]].isna().all().all())
        np.testing.assert_array_equal(out["p10_raw"].values, self.test_preds["p10"].values)
        np.testing.assert_array_equal(out["p50"].values, self.test_preds["p50"].values)
        self.assertTrue(label.startswith("FAILED"))

    def test_missing_validation_station_fails_loudly(self):
        partial = self.val_preds[self.val_preds["station_id"] != "S3"]
        out, label = calibrate_intervals("Prophet", "Prophet", self.test_preds, lambda: partial,
                                         self.val, _cfg(Prophet={"method": "scaled"}))
        self.assertTrue(label.startswith("FAILED"))
        self.assertTrue(out[["p10", "p90"]].isna().all().all())

    def test_other_checkpoint_does_not_inherit_the_method(self):
        cfg = _cfg(Chronos={"method": "relative", "validated_for": "amazon/chronos-t5-small"})
        out, label = calibrate_intervals("Chronos", "Chronos2_ZeroShot", self.test_preds,
                                         lambda: self.val_preds, self.val, cfg,
                                         checkpoint="amazon/chronos-2")
        np.testing.assert_array_equal(out["p10"].values, self.test_preds["p10"].values)
        self.assertIn("validated for amazon/chronos-t5-small", label)
        _, ok = calibrate_intervals("Chronos", "Chronos1", self.test_preds, lambda: self.val_preds,
                                    self.val, cfg, checkpoint="amazon/chronos-t5-small")
        self.assertTrue(ok.startswith("split-conformal"))


class LeaderboardColumnsTest(unittest.TestCase):
    def test_raw_coverage_and_method_are_appended_last(self):
        test = _preds("2025-07-01", seed=3)
        preds, label = calibrate_intervals(
            "Prophet", "Prophet", test[["timestamp", "station_id", "p10", "p50", "p90"]],
            lambda: _preds("2025-01-01", seed=4)[["timestamp", "station_id", "p10", "p50", "p90"]],
            _preds("2025-01-01", seed=4), _cfg(Prophet={"method": "relative"}))
        actuals = test[["timestamp", "station_id", "ridership"]]
        row = compute_metrics(actuals, preds, "Prophet", interval_method=label)[0]
        keys = list(row)
        self.assertEqual(keys[-3:], ["n_expected", "Coverage_raw_%", "Interval_method"])
        self.assertLess(row["Coverage_raw_%"], 40)        # ±2% band on 5% noise
        self.assertGreater(row["Coverage_%"], row["Coverage_raw_%"])

    def test_latex_table_labels_which_band_coverage_scores(self):
        lb = pd.DataFrame([{"model": "Prophet", "WAPE_%": 5.0, "MAE": 1.0, "RMSE": 1.0,
                            "MAPE_%": 5.0, "Coverage_%": 75.0, "Coverage_raw_%": 46.0,
                            "Interval_method": "split-conformal scaled/horizon, fit on validation"}])
        try:
            tex = leaderboard_latex(lb)
        except ImportError:
            self.skipTest("jinja2 not installed")
        self.assertRegex(tex, r"Coverage\\?_raw")          # the column, escaped or not
        self.assertRegex(tex, r"Interval\\?_method")
        self.assertIn("split-conformal scaled/horizon", tex)


class RollingSchemeTest(unittest.TestCase):
    """scheme: rolling (Sprint 5) — a pool of forecasts from monthly origins
    first_origin .. as_of - 1 month, each store cut at min(origin + 6, as_of)."""

    AS_OF = pd.Timestamp("2025-06-30")
    CFG = {"method": "relative", "group": "pooled", "scheme": "rolling",
           "half_life": 6, "first_origin": "2023-12-31"}

    def setUp(self):
        rng = np.random.default_rng(11)
        ts = pd.date_range("2022-01-01", "2025-12-01", freq="MS")
        rows = [(t, f"S{i}") for i in range(6) for t in ts]
        self.history = pd.DataFrame(rows, columns=["timestamp", "station_id"])
        self.history["ridership"] = 10_000 * (1 + rng.normal(0, 0.06, len(self.history)))
        self.test_preds = _preds("2025-07-01", n_stations=6, seed=12)[
            ["timestamp", "station_id", "p10", "p50", "p90"]]
        self.calls = []

    def _make(self, origin, cut):
        self.calls.append((origin, cut))
        ts = pd.date_range(origin + pd.offsets.MonthBegin(1), periods=6, freq="MS")
        out = pd.DataFrame([(t, f"S{i}") for i in range(6) for t in ts], columns=["timestamp", "station_id"])
        out["p50"], out["p10"], out["p90"] = 10_000.0, 9_800.0, 10_200.0
        return out

    def _run(self, history=None, make=None, mcfg=None):
        cfg = {"calibration": {"level": 0.8, "models": {"Prophet": mcfg or self.CFG}},
               "data": {"forecast_horizon_steps": 6}}
        return calibrate_intervals(
            "Prophet", "Prophet", self.test_preds, lambda: self.fail("rolling must not use the split path"),
            None, cfg, make_origin_preds=make or self._make,
            history_df=self.history if history is None else history, as_of=self.AS_OF)

    def test_origins_and_store_cuts(self):
        self._run()
        origins = [o for o, _ in self.calls]
        self.assertEqual(origins, list(pd.date_range("2023-12-31", "2025-05-31", freq="ME")))
        for o, cut in self.calls:
            self.assertEqual(cut, min(o + pd.DateOffset(months=6), self.AS_OF))

    def test_band_matches_a_rolling_fit_on_the_same_pool(self):
        out, label = self._run()
        pool = []
        for o in pd.date_range("2023-12-31", "2025-05-31", freq="ME"):
            cut = min(o + pd.DateOffset(months=6), self.AS_OF)
            actual = self.history[(self.history["timestamp"] > o) & (self.history["timestamp"] <= cut)]
            pool.append(with_origin_horizon(actual.merge(self._make(o, cut), on=["timestamp", "station_id"],
                                                         how="left"), o))
        calib = fit_rolling_conformal(pd.concat(pool), "relative", "pooled", 0.8, self.AS_OF, half_life=6)
        expected = apply_conformal(with_origin_horizon(self.test_preds, self.AS_OF), calib)
        np.testing.assert_array_equal(out["p50"].values, self.test_preds["p50"].values)
        np.testing.assert_allclose(out["p10"].values, expected["p10"].values)
        np.testing.assert_allclose(out["p90"].values, expected["p90"].values)
        self.assertEqual(out["horizon"].tolist(), with_origin_horizon(self.test_preds, self.AS_OF)["horizon"].tolist())
        self.assertIn("rolling-origin", label)
        self.assertIn("half-life 6", label)

    def test_rows_after_as_of_never_reach_the_pool(self):
        a, _ = self._run()
        noisy = self.history.copy()
        late = noisy["timestamp"] > self.AS_OF
        noisy.loc[late, "ridership"] *= 5
        b, _ = self._run(history=noisy)
        np.testing.assert_array_equal(a["p90"].values, b["p90"].values)

    def test_missing_origin_forecasts_fail_loudly(self):
        out, label = self._run(make=lambda o, cut: pd.DataFrame())
        self.assertTrue(label.startswith("FAILED"))
        self.assertTrue(out[["p10", "p90"]].isna().all().all())

    def test_unknown_scheme_fails_loudly(self):
        out, label = self._run(mcfg={**self.CFG, "scheme": "telepathy"})
        self.assertTrue(label.startswith("FAILED"))
        self.assertTrue(out[["p10", "p90"]].isna().all().all())


class CalibrationEdgeCasesTest(unittest.TestCase):
    def test_horizon_counted_before_missing_actuals_are_dropped(self):
        cal = _preds("2025-01-01", n_stations=2, seed=5).drop(columns=[])
        cal.loc[0, "ridership"] = np.nan          # S0's first month has no actual
        calib = fit_conformal(cal, "scaled", "horizon", 0.8)
        self.assertEqual(calib["n"], len(cal) - 1)
        # Step 1 lost one row; steps 2..6 keep both stations. With the bug,
        # S0's steps shifted and step 6 had a single row.
        self.assertEqual(sorted(calib["q"]), [1, 2, 3, 4, 5, 6])
        scores_at_6 = add_horizon(cal).query("horizon == 6")
        self.assertEqual(len(scores_at_6), 2)

    def test_zero_p50_with_infinite_quantile_is_unbounded_not_nan(self):
        cal = _preds("2025-01-01", n_stations=1, seed=6).head(3)   # too few for a finite q
        target = _preds("2025-07-01", n_stations=1, seed=7)
        target.loc[0, ["p10", "p50", "p90"]] = 0.0
        for method in ("relative", "asym_relative"):
            out = apply_conformal(target, fit_conformal(cal, method, "pooled", 0.8))
            self.assertEqual(out.loc[0, "p10"], 0.0, method)
            self.assertEqual(out.loc[0, "p90"], np.inf, method)

    def test_describe_asymmetric_groups(self):
        cal = _preds("2025-01-01", seed=8)
        text = describe(fit_conformal(cal, "asym_relative", "horizon", 0.8))
        self.assertIn("q_hi - q_lo range", text)


if __name__ == "__main__":
    unittest.main()
