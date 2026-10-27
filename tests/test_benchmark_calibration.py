"""
tests/test_benchmark_calibration.py
───────────────────────────────────
How models/baselines/benchmarks.py applies interval calibration: the
per-model config, the failure path, the checkpoint guard and the leaderboard
columns. Synthetic data only; no model is fitted.

    python -m unittest tests.test_benchmark_calibration -v
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.calibration import (  # noqa: E402
    add_horizon, apply_conformal, describe, fit_conformal, fit_rolling_conformal, with_origin_horizon,
)
from evaluation.calibration import fit_shift_conformal, load_calibrator  # noqa: E402
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

    def test_missing_half_life_fails_instead_of_equal_weights(self):
        mcfg = {k: v for k, v in self.CFG.items() if k != "half_life"}
        out, label = self._run(mcfg=mcfg)
        self.assertTrue(label.startswith("FAILED"))
        self.assertTrue(out[["p10", "p90"]].isna().all().all())
        self.assertEqual(self.calls, [])

    def _cfg_with_data(self, mcfg=None):
        return {"calibration": {"level": 0.8, "models": {"Prophet": mcfg or self.CFG}},
                "data": {"forecast_horizon_steps": 6, "train_end": "2024-12-31", "val_end": "2025-06-30"}}

    def test_saved_rolling_calibrator_is_served_as_scored(self):
        import tempfile
        from evaluation.calibration import CalibratorUnavailable, load_calibrator, serve_band
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "Prophet.json"
            cfg = self._cfg_with_data()
            out, label = calibrate_intervals(
                "Prophet", "Prophet", self.test_preds, lambda: self.fail("split path"), None, cfg,
                calibrator_path=path, make_origin_preds=self._make, history_df=self.history, as_of=self.AS_OF)
            prov = load_calibrator(path)["provenance"]
            self.assertEqual((prov["fit_end"], prov["scheme"], prov["half_life"], prov["first_origin"]),
                             ("2025-06-30", "rolling", 6, "2023-12-31"))
            served, plan = serve_band(self.test_preds, "Prophet", cfg, calibrator_path=path)
            np.testing.assert_allclose(served["p10"].values, out["p10"].values)
            np.testing.assert_allclose(served["p90"].values, out["p90"].values)
            self.assertEqual(plan["label"], label)
            # A config that no longer asks for this rolling band refuses the file.
            for change in ({"scheme": "split"}, {"half_life": 3}, {"first_origin": "2024-06-30"}):
                with self.assertRaises(CalibratorUnavailable, msg=change):
                    serve_band(self.test_preds, "Prophet", self._cfg_with_data({**self.CFG, **change}),
                               calibrator_path=path)
            # So does a run on other splits.
            moved = self._cfg_with_data(); moved["data"]["val_end"] = "2025-12-31"
            with self.assertRaises(CalibratorUnavailable):
                serve_band(self.test_preds, "Prophet", moved, calibrator_path=path)

    def test_split_calibrator_is_refused_under_a_rolling_config(self):
        import tempfile
        from evaluation.calibration import CalibratorUnavailable, fit_conformal as fc, save_calibrator, serve_band
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "Prophet.json"
            cal = fc(_preds("2025-01-01", n_stations=6, seed=13), "relative", "pooled", 0.8)
            save_calibrator(cal, path, model_key="Prophet", fit_end="2025-06-30")
            with self.assertRaises(CalibratorUnavailable):
                serve_band(self.test_preds, "Prophet", self._cfg_with_data(), calibrator_path=path)

    def test_unknown_scheme_fails_loudly(self):
        out, label = self._run(mcfg={**self.CFG, "scheme": "telepathy"})
        self.assertTrue(label.startswith("FAILED"))
        self.assertTrue(out[["p10", "p90"]].isna().all().all())


def _month_index(t):
    """Months since 2023-01 (Timestamp or datetime Series)."""
    if isinstance(t, pd.Series):
        return (t.dt.year - 2023) * 12 + t.dt.month - 1
    t = pd.Timestamp(t)
    return (t.year - 2023) * 12 + t.month - 1


def _level(t):
    """A ridership level that keeps accelerating, so a forecast made at an
    origin under-forecasts by more at longer horizons and later origins: the
    bias differs by horizon, by origin and by how fast old errors decay."""
    m = _month_index(t)
    return 1 + 0.01 * m + 0.0008 * m ** 2


class ShiftSchemeTest(unittest.TestCase):
    """method: shift_relative (Sprint 6) — a bias-shifted band fit by
    fit_shift_conformal on the same rolling-origin pool as scheme rolling,
    applied as an asym_relative calibrator."""

    AS_OF = pd.Timestamp("2025-06-30")
    CKPT = "amazon/chronos-t5-small"
    CFG = {"method": "shift_relative", "group": "horizon", "scheme": "rolling", "half_life": 6,
           "bias_half_life": 1, "bias_at": "as_of", "first_origin": "2023-12-31",
           "validated_for": "amazon/chronos-t5-small"}
    LABEL = ("bias-shifted rolling-origin conformal relative/horizon, bias half-life 1 month(s) "
             "(at the forecast origin), width half-life 6 months, fit on data to val_end")

    def setUp(self):
        rng = np.random.default_rng(21)
        ts = pd.date_range("2022-01-01", "2025-12-01", freq="MS")
        rows = [(t, f"S{i}") for i in range(6) for t in ts]
        self.history = pd.DataFrame(rows, columns=["timestamp", "station_id"])
        self.history["ridership"] = (10_000 * _level(self.history["timestamp"])
                                     * (1 + rng.normal(0, 0.03, len(self.history))))
        self.test_preds = _preds("2025-07-01", n_stations=6, seed=12)[
            ["timestamp", "station_id", "p10", "p50", "p90"]]
        self.calls, self.val_calls = [], []

    def _make(self, origin, cut):
        self.calls.append((origin, cut))
        ts = pd.date_range(origin + pd.offsets.MonthBegin(1), periods=6, freq="MS")
        out = pd.DataFrame([(t, f"S{i}") for i in range(6) for t in ts], columns=["timestamp", "station_id"])
        out["p50"] = 10_000 * _level(origin)          # a persistence forecast from the origin
        out["p10"], out["p90"] = out["p50"] * 0.98, out["p50"] * 1.02
        return out

    def _val(self):
        self.val_calls.append(True)
        return None

    def _cfg(self, mcfg=None):
        return {"calibration": {"level": 0.8, "models": {"Chronos": self.CFG if mcfg is None else mcfg}},
                "data": {"forecast_horizon_steps": 6, "train_end": "2024-12-31", "val_end": "2025-06-30"}}

    def _run(self, mcfg=None, checkpoint=CKPT, path=None):
        return calibrate_intervals(
            "Chronos", "Chronos1_ZeroShot (chronos-t5-small)", self.test_preds, self._val, None,
            self._cfg(mcfg), checkpoint=checkpoint, calibrator_path=path,
            make_origin_preds=self._make, history_df=self.history, as_of=self.AS_OF)

    def _pool(self):
        """The pool, built independently of benchmarks.py."""
        pool = []
        for o in pd.date_range("2023-12-31", "2025-05-31", freq="ME"):
            cut = min(o + pd.DateOffset(months=6), self.AS_OF)
            actual = self.history[(self.history["timestamp"] > o) & (self.history["timestamp"] <= cut)]
            pool.append(with_origin_horizon(actual.merge(self._make(o, cut), on=["timestamp", "station_id"],
                                                         how="left"), o))
        self.calls.clear()
        return pd.concat(pool, ignore_index=True)

    def _expected(self, group="horizon", bias_half_life=1, half_life=6, bias_at="as_of"):
        cal = fit_shift_conformal(self._pool(), group, 0.8, self.AS_OF, bias_half_life=bias_half_life,
                                  half_life=half_life, bias_at=bias_at)
        return cal, apply_conformal(with_origin_horizon(self.test_preds, self.AS_OF), cal)

    def test_band_equals_a_shift_fit_on_the_same_pool(self):
        out, label = self._run()
        self.assertEqual(label, self.LABEL)
        self.assertEqual(self.val_calls, [])
        origins = [o for o, _ in self.calls]
        self.assertEqual(origins, list(pd.date_range("2023-12-31", "2025-05-31", freq="ME")))
        for o, cut in self.calls:
            self.assertEqual(cut, min(o + pd.DateOffset(months=6), self.AS_OF))
        cal, expected = self._expected()
        np.testing.assert_array_equal(out["p50"].values, self.test_preds["p50"].values)
        np.testing.assert_array_equal(out["p10"].values, expected["p10"].values)
        np.testing.assert_array_equal(out["p90"].values, expected["p90"].values)
        np.testing.assert_array_equal(out["p10_raw"].values, self.test_preds["p10"].values)
        # The data tells the settings apart, so a mis-wired setting cannot pass.
        self.assertGreater(min(cal["bias"].values()), 0.01)
        for other in ({"bias_half_life": 3}, {"half_life": 3}, {"bias_half_life": 6, "half_life": 1}):
            _, alt = self._expected(**other)
            self.assertFalse(np.array_equal(alt["p90"].values, expected["p90"].values), other)

    def test_bias_at_each_origin_pooled(self):
        mcfg = {**self.CFG, "group": "pooled", "bias_half_life": 3, "bias_at": "origin"}
        out, label = self._run(mcfg=mcfg)
        self.assertEqual(label, "bias-shifted rolling-origin conformal relative/pooled, bias half-life 3 "
                                "month(s) (at each origin), width half-life 6 months, fit on data to val_end")
        cal, expected = self._expected(group="pooled", bias_half_life=3, bias_at="origin")
        self.assertGreater(cal["n_no_bias"], 0)
        np.testing.assert_array_equal(out["p50"].values, self.test_preds["p50"].values)
        np.testing.assert_array_equal(out["p10"].values, expected["p10"].values)
        np.testing.assert_array_equal(out["p90"].values, expected["p90"].values)
        _, as_of_band = self._expected(group="pooled", bias_half_life=3, bias_at="as_of")
        self.assertFalse(np.array_equal(as_of_band["p90"].values, expected["p90"].values))

    def test_incomplete_entry_fails_before_forecasting(self):
        drop = lambda *keys: {k: v for k, v in self.CFG.items() if k not in keys}  # noqa: E731
        cases = (
            (drop("half_life"), "no half_life"),
            (drop("bias_half_life"), "no bias_half_life"),
            ({**self.CFG, "bias_half_life": None}, "no bias_half_life"),
            (drop("bias_at"), "no bias_at"),
            ({**self.CFG, "scheme": "split"}, "scheme 'split' instead of rolling"),
            (drop("scheme"), "scheme 'split' instead of rolling"),
            (drop("scheme", "half_life", "bias_at"),
             "scheme 'split' instead of rolling, no half_life, no bias_at"),
        )
        for mcfg, missing in cases:
            with self.subTest(missing=missing):
                self.calls.clear()
                with self.assertLogs("benchmarks", level="ERROR"):
                    out, label = self._run(mcfg=mcfg)
                self.assertEqual(label, f"FAILED: shift_relative/horizon ({missing})")
                self.assertTrue(out[["p10", "p90"]].isna().all().all())
                np.testing.assert_array_equal(out["p10_raw"].values, self.test_preds["p10"].values)
                np.testing.assert_array_equal(out["p50"].values, self.test_preds["p50"].values)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.val_calls, [])

    def test_fit_error_fails_with_the_method_label(self):
        out, label = self._run(mcfg={**self.CFG, "bias_at": "origin"})   # origin is pooled only
        self.assertEqual(label, "FAILED: shift_relative/horizon")
        self.assertTrue(out[["p10", "p90"]].isna().all().all())

    def test_other_checkpoint_keeps_the_raw_band_before_any_check(self):
        incomplete = {k: v for k, v in self.CFG.items() if k != "bias_at"}
        out, label = self._run(mcfg=incomplete, checkpoint="amazon/chronos-2")
        self.assertEqual(label, "raw: method validated for amazon/chronos-t5-small only")
        for col in ("p10", "p50", "p90"):
            np.testing.assert_array_equal(out[col].values, self.test_preds[col].values)
        self.assertEqual(self.calls, [])

    def test_full_calibrator_is_logged_at_full_precision(self):
        prefix = "  interval calibrator (full): "
        with self.assertLogs("benchmarks", level="INFO") as logs:
            self._run()
        messages = [r.getMessage() for r in logs.records]
        full = [m for m in messages if m.startswith(prefix)]
        self.assertEqual(len(full), 1, messages)
        doc = json.loads(full[0][len(prefix):])
        cal, _ = self._expected()
        self.assertEqual(sorted(doc), ["bias", "clipped_groups", "model", "n", "n_by_group", "q", "width"])
        self.assertEqual(doc["model"], "Chronos")
        self.assertEqual(doc["n"], cal["n"])
        self.assertEqual({int(k): v for k, v in doc["n_by_group"].items()}, cal["n_by_group"])
        self.assertEqual({int(k): v for k, v in doc["bias"].items()}, cal["bias"])
        self.assertEqual({int(k): v for k, v in doc["width"].items()}, cal["width"])
        self.assertEqual({int(k): tuple(v) for k, v in doc["q"].items()}, cal["q"])
        self.assertEqual(doc["clipped_groups"], cal["clipped_groups"])
        self.assertIn(f"  interval calibration: {describe(cal)}", messages)

    def test_saved_calibrator_is_asym_relative_with_shift_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "Chronos.json"
            self._run(path=path)
            self.assertEqual(json.loads(path.read_text())["method"], "asym_relative")
            saved = load_calibrator(path)
        cal, _ = self._expected()
        self.assertEqual((saved["method"], saved["group"], saved["level"], saved["n"]),
                         ("asym_relative", "horizon", 0.8, cal["n"]))
        self.assertEqual(saved["q"], cal["q"])
        prov = saved["provenance"]
        self.assertEqual(
            {k: prov.get(k) for k in ("method_config", "bias_half_life", "bias_at", "scheme", "half_life",
                                      "first_origin", "fit_end", "model_key", "checkpoint", "label",
                                      "window")},
            {"method_config": "shift_relative", "bias_half_life": 1, "bias_at": "as_of", "scheme": "rolling",
             "half_life": 6, "first_origin": "2023-12-31", "fit_end": "2025-06-30", "model_key": "Chronos",
             "checkpoint": self.CKPT, "label": self.LABEL, "window": ["2024-01-01", "2025-06-01"]})


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
