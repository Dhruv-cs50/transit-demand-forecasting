"""
tests/test_serve_band.py
────────────────────────
Serving a calibrated band outside the benchmark run:

- a calibrator is saved by benchmarks.py and loaded again without loss
  (horizon keys stay ints, asymmetric quantiles stay pairs, infinite
  quantiles survive strict JSON);
- serve_band applies the band configs/model.yaml assigns, never changes P50,
  and labels which band it returned;
- a configured method with no matching saved calibrator is refused rather
  than served as the raw band.

Synthetic data only; no model is fitted.

    python -m unittest tests.test_serve_band -v
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
    CalibratorUnavailable,
    add_horizon,
    apply_conformal,
    fit_conformal,
    interval_plan,
    load_calibrator,
    save_calibrator,
    serve_band,
)
from models.baselines.benchmarks import calibrate_intervals  # noqa: E402

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
    return {
        "data": {"train_end": "2024-12-31", "val_end": "2025-06-30"},
        "calibration": {"level": 0.8, "models": models},
    }


BAND = ["timestamp", "station_id", "p10", "p50", "p90"]


class RoundTripTest(unittest.TestCase):
    """fit -> save -> load -> apply equals fit -> apply, bit for bit."""

    def setUp(self):
        self.val = add_horizon(_preds("2025-01-01", seed=1))
        self.test = add_horizon(_preds("2025-07-01", seed=2)[BAND])
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "cal.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _round_trip(self, method: str, group: str):
        cal = fit_conformal(self.val, method=method, group=group, level=0.8)
        save_calibrator(cal, self.path, model_key="M")
        loaded = load_calibrator(self.path)
        expected = apply_conformal(self.test, cal)
        got = apply_conformal(self.test, loaded)
        pd.testing.assert_frame_equal(got, expected, check_exact=True)
        self.assertFalse(got[["p10", "p90"]].isna().any().any())
        return cal, loaded

    def test_scaled_per_horizon_keeps_int_keys(self):
        cal, loaded = self._round_trip("scaled", "horizon")
        self.assertEqual(loaded["q"], cal["q"])
        self.assertTrue(all(type(k) is int for k in loaded["q"]))

    def test_relative_pooled(self):
        cal, loaded = self._round_trip("relative", "pooled")
        self.assertEqual(loaded["q"], cal["q"])

    def test_asymmetric_per_station_keeps_pairs(self):
        cal, loaded = self._round_trip("asym_relative", "station")
        self.assertEqual(loaded["q"], cal["q"])
        self.assertTrue(all(isinstance(v, tuple) for v in loaded["q"].values()))

    def test_infinite_quantile_is_strict_json(self):
        # Two rows per group: ceil(3 * 0.8) = 3 > 2, so every q is +inf.
        small = self.val[self.val["horizon"] <= 2]
        cal = fit_conformal(small, method="relative", group="station", level=0.8)
        self.assertTrue(all(np.isinf(v) for v in cal["q"].values()))
        save_calibrator(cal, self.path, model_key="M")
        text = self.path.read_text()
        json.loads(text, parse_constant=lambda c: self.fail(f"non-strict JSON constant {c}"))
        self.assertEqual(load_calibrator(self.path)["q"], cal["q"])

    def test_provenance_is_kept(self):
        cal = fit_conformal(self.val, method="relative", group="pooled")
        save_calibrator(cal, self.path, model_key="Chronos", checkpoint="amazon/chronos-t5-small")
        prov = load_calibrator(self.path)["provenance"]
        self.assertEqual(prov["model_key"], "Chronos")
        self.assertEqual(prov["checkpoint"], "amazon/chronos-t5-small")

    def test_unknown_format_is_refused(self):
        self.path.write_text(json.dumps({"format": 99, "method": "relative", "group": "pooled",
                                         "level": 0.8, "n": 1, "q": [["all", 0.1]]}))
        with self.assertRaises(ValueError):
            load_calibrator(self.path)


class IntervalPlanTest(unittest.TestCase):
    def test_none_is_raw_with_reason(self):
        plan = interval_plan("SARIMA", _cfg(SARIMA={"method": "none", "reason": "no method passed validation"}))
        self.assertFalse(plan["calibrated"])
        self.assertEqual(plan["label"], "raw: no method passed validation")
        self.assertIn("not calibrated", plan["description"])
        self.assertNotIn("80% interval", plan["description"])

    def test_unlisted_model_is_raw(self):
        plan = interval_plan("X", _cfg())
        self.assertFalse(plan["calibrated"])
        self.assertEqual(plan["label"], "raw: not validated")

    def test_configured_method(self):
        plan = interval_plan("Prophet", _cfg(Prophet={"method": "scaled", "group": "horizon"}))
        self.assertTrue(plan["calibrated"])
        self.assertEqual((plan["method"], plan["group"], plan["level"]), ("scaled", "horizon", 0.8))
        self.assertEqual(plan["label"], "split-conformal scaled/horizon, fit on validation")

    def test_other_checkpoint_is_raw(self):
        cfg = _cfg(Chronos={"method": "relative", "group": "pooled", "validated_for": "amazon/chronos-t5-small"})
        plan = interval_plan("Chronos", cfg, checkpoint="amazon/chronos-bolt-base")
        self.assertFalse(plan["calibrated"])
        self.assertEqual(plan["label"], "raw: method validated for amazon/chronos-t5-small only")
        self.assertTrue(interval_plan("Chronos", cfg, checkpoint="amazon/chronos-t5-small")["calibrated"])

    def test_labels_match_the_benchmark_leaderboard(self):
        """The leaderboard's Interval_method and the served label are one string."""
        val, test = _preds("2025-01-01", seed=1), _preds("2025-07-01", seed=2)[BAND]
        for key, mcfg in {
            "SARIMA": {"method": "none", "reason": "no method passed validation"},
            "Prophet": {"method": "scaled", "group": "horizon"},
            "Chronos": {"method": "relative", "group": "pooled"},
        }.items():
            cfg = _cfg(**{key: mcfg})
            _, label = calibrate_intervals(key, key, test, lambda: val[BAND], val, cfg)
            self.assertEqual(label, interval_plan(key, cfg)["label"])


class ServeBandTest(unittest.TestCase):
    def setUp(self):
        self.val = _preds("2025-01-01", seed=1)
        self.test = _preds("2025-07-01", seed=2)[BAND]
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "Prophet.json"
        self.cfg = _cfg(Prophet={"method": "scaled", "group": "horizon"},
                        SARIMA={"method": "none", "reason": "no method passed validation"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_raw_band_is_returned_unchanged_and_labelled(self):
        out, plan = serve_band(self.test, "SARIMA", self.cfg, calibrator_path=self.path)
        for col in ("p10", "p50", "p90"):
            np.testing.assert_array_equal(out[col].to_numpy(), self.test[col].to_numpy())
        np.testing.assert_array_equal(out["p10_raw"].to_numpy(), self.test["p10"].to_numpy())
        self.assertFalse(plan["calibrated"])
        self.assertEqual(plan["label"], "raw: no method passed validation")

    def test_raw_band_needs_no_calibrator_file(self):
        self.assertFalse(self.path.exists())
        serve_band(self.test, "SARIMA", self.cfg, calibrator_path=None)

    def test_calibrated_band_matches_benchmarks_and_keeps_p50(self):
        """The band served from the saved file is the band the leaderboard scored."""
        scored, _ = calibrate_intervals("Prophet", "Prophet", self.test, lambda: self.val[BAND],
                                        self.val, self.cfg, calibrator_path=self.path)
        self.assertTrue(self.path.exists())
        out, plan = serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)
        np.testing.assert_array_equal(out["p50"].to_numpy(), self.test["p50"].to_numpy())
        for col in ("p10", "p90", "p10_raw", "p90_raw"):
            np.testing.assert_array_equal(out[col].to_numpy(), scored[col].to_numpy())
        self.assertFalse(np.array_equal(out["p10"].to_numpy(), self.test["p10"].to_numpy()))
        self.assertTrue(plan["calibrated"])
        self.assertEqual(plan["n"], len(self.val))
        self.assertEqual(plan["label"], "split-conformal scaled/horizon, fit on validation")

    def test_missing_calibrator_is_refused(self):
        with self.assertRaises(CalibratorUnavailable):
            serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)
        with self.assertRaises(CalibratorUnavailable):
            serve_band(self.test, "Prophet", self.cfg, calibrator_path=None)

    def test_calibrator_for_another_method_is_refused(self):
        cal = fit_conformal(add_horizon(self.val), method="relative", group="pooled")
        save_calibrator(cal, self.path, model_key="Prophet")
        with self.assertRaises(CalibratorUnavailable):
            serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)

    def test_calibrator_for_another_model_is_refused(self):
        cal = fit_conformal(add_horizon(self.val), method="scaled", group="horizon")
        save_calibrator(cal, self.path, model_key="SARIMA")
        with self.assertRaises(CalibratorUnavailable):
            serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)

    def test_calibrator_for_another_checkpoint_is_refused(self):
        cfg = _cfg(Chronos={"method": "relative", "group": "pooled"})
        cal = fit_conformal(add_horizon(self.val), method="relative", group="pooled")
        save_calibrator(cal, self.path, model_key="Chronos", checkpoint="amazon/chronos-t5-small")
        with self.assertRaises(CalibratorUnavailable):
            serve_band(self.test, "Chronos", cfg, calibrator_path=self.path, checkpoint="amazon/chronos-t5-base")
        serve_band(self.test, "Chronos", cfg, calibrator_path=self.path, checkpoint="amazon/chronos-t5-small")


class BenchmarkPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.val = _preds("2025-01-01", seed=1)
        self.test = _preds("2025-07-01", seed=2)[BAND]
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sub" / "M.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_saved_with_window_and_label(self):
        cfg = _cfg(M={"method": "relative", "group": "pooled"})
        calibrate_intervals("M", "Model (ckpt)", self.test, lambda: self.val[BAND], self.val, cfg,
                            checkpoint="ckpt", calibrator_path=self.path)
        prov = load_calibrator(self.path)["provenance"]
        self.assertEqual(prov["model_key"], "M")
        self.assertEqual(prov["model"], "Model (ckpt)")
        self.assertEqual(prov["checkpoint"], "ckpt")
        self.assertEqual(prov["fit_end"], "2024-12-31")
        self.assertEqual(prov["window"], ["2025-01-01", "2025-06-01"])
        self.assertEqual(prov["label"], "split-conformal relative/pooled, fit on validation")

    def test_stale_file_removed_when_model_is_left_raw(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{}")
        calibrate_intervals("M", "M", self.test, lambda: self.val[BAND], self.val,
                            _cfg(M={"method": "none"}), calibrator_path=self.path)
        self.assertFalse(self.path.exists())

    def test_stale_file_removed_when_calibration_fails(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{}")

        def boom():
            raise RuntimeError("no validation forecasts")

        _, label = calibrate_intervals("M", "M", self.test, boom, self.val,
                                       _cfg(M={"method": "relative"}), calibrator_path=self.path)
        self.assertTrue(label.startswith("FAILED"))
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
