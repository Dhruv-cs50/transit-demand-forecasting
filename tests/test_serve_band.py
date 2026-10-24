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

import datetime
import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
from models.baselines import benchmarks  # noqa: E402
from models.baselines.benchmarks import (  # noqa: E402
    calibrate_intervals,
    clear_saved_calibrators,
    compute_metrics,
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


FIT_END = "2024-12-31"


def _cfg(**models) -> dict:
    return {
        "data": {"train_end": FIT_END, "val_end": "2025-06-30"},
        "calibration": {"level": 0.8, "models": models},
    }


BAND = ["timestamp", "station_id", "p10", "p50", "p90"]

# Configs whose method is none (or missing) and whose reason is left blank.
BLANK_REASONS = (
    {"method": "none", "reason": None},
    {"method": "none", "reason": ""},
    {"method": "none", "reason": "   "},
    {"method": None, "reason": None},
    {"reason": None},
)


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

    def test_blank_reason_stays_raw(self):
        """`reason:` left empty or null in the YAML must not turn a raw model
        into a calibrated one."""
        for mcfg in BLANK_REASONS:
            with self.subTest(mcfg=mcfg):
                plan = interval_plan("SARIMA", _cfg(SARIMA=mcfg))
                self.assertFalse(plan["calibrated"])
                self.assertEqual(plan["method"], "none")
                self.assertIsNone(plan["group"])
                self.assertEqual(plan["reason"], "not validated")
                self.assertEqual(plan["label"], "raw: not validated")
                self.assertFalse(plan["checkpoint_mismatch"])

    def test_checkpoint_mismatch_is_a_flag(self):
        cfg = _cfg(Chronos={"method": "relative", "group": "pooled", "validated_for": "ckpt-a"},
                   SARIMA={"method": "none", "reason": "method validated for nothing yet"})
        self.assertTrue(interval_plan("Chronos", cfg, checkpoint="ckpt-b")["checkpoint_mismatch"])
        self.assertFalse(interval_plan("Chronos", cfg, checkpoint="ckpt-a")["checkpoint_mismatch"])
        self.assertFalse(interval_plan("Chronos", cfg)["checkpoint_mismatch"])
        # A reason that merely reads like a checkpoint mismatch is not one.
        self.assertFalse(interval_plan("SARIMA", cfg)["checkpoint_mismatch"])

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
        """The leaderboard's Interval_method strings, verbatim: what
        calibrate_intervals writes and what interval_plan serves."""
        val, test = _preds("2025-01-01", seed=1), _preds("2025-07-01", seed=2)[BAND]
        for key, mcfg, literal in (
            ("SARIMA", {"method": "none", "reason": "no method passed validation"},
             "raw: no method passed validation"),
            ("Prophet", {"method": "scaled", "group": "horizon"},
             "split-conformal scaled/horizon, fit on validation"),
            ("Chronos", {"method": "relative", "group": "pooled"},
             "split-conformal relative/pooled, fit on validation"),
        ):
            with self.subTest(key=key):
                cfg = _cfg(**{key: mcfg})
                _, label = calibrate_intervals(key, key, test, lambda: val[BAND], val, cfg)
                self.assertEqual(label, literal)
                self.assertEqual(interval_plan(key, cfg)["label"], literal)

    def test_blank_reason_is_scored_on_the_models_own_band(self):
        """The leaderboard row of a raw model with a blank reason: its own
        band, a real coverage figure, never FAILED."""
        val, test = _preds("2025-01-01", seed=1), _preds("2025-07-01", seed=2)
        actuals = test[["timestamp", "station_id", "ridership"]]
        for mcfg in BLANK_REASONS:
            with self.subTest(mcfg=mcfg):
                preds, label = calibrate_intervals(
                    "SARIMA", "SARIMA", test[BAND],
                    lambda: self.fail("a raw model must not forecast validation"),
                    val, _cfg(SARIMA=mcfg))
                self.assertEqual(label, "raw: not validated")
                for col in ("p10", "p50", "p90"):
                    np.testing.assert_array_equal(preds[col].to_numpy(), test[col].to_numpy())
                row = compute_metrics(actuals, preds, "SARIMA", interval_method=label)[0]
                self.assertTrue(np.isfinite(row["Coverage_%"]))
                self.assertEqual(row["Coverage_%"], row["Coverage_raw_%"])
                self.assertEqual(row["Interval_method"], "raw: not validated")

    def test_warning_is_logged_only_for_a_checkpoint_mismatch(self):
        val, test = _preds("2025-01-01", seed=1), _preds("2025-07-01", seed=2)[BAND]
        cfg = _cfg(Chronos={"method": "relative", "group": "pooled", "validated_for": "ckpt-a"},
                   SARIMA={"method": "none", "reason": "method validated for nothing yet"})
        with self.assertLogs("benchmarks", level="WARNING") as logs:
            calibrate_intervals("Chronos", "Chronos", test, lambda: val[BAND], val, cfg,
                                checkpoint="ckpt-b")
        self.assertIn("method validated for ckpt-a only", "\n".join(logs.output))
        with self.assertNoLogs("benchmarks", level="WARNING"):
            calibrate_intervals("SARIMA", "SARIMA", test, lambda: val[BAND], val, cfg)


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

    def test_blank_reason_serves_the_raw_band(self):
        self.path.write_text("not a calibrator")  # never read for a raw band
        for mcfg in BLANK_REASONS:
            with self.subTest(mcfg=mcfg):
                out, plan = serve_band(self.test, "SARIMA", _cfg(SARIMA=mcfg), calibrator_path=self.path)
                self.assertFalse(plan["calibrated"])
                self.assertEqual(plan["label"], "raw: not validated")
                for col in ("p10", "p50", "p90"):
                    np.testing.assert_array_equal(out[col].to_numpy(), self.test[col].to_numpy())

    def _save(self, method="scaled", group="horizon", level=0.8, **provenance):
        """A calibrator matching self.cfg's Prophet entry unless overridden.
        Pass fit_end=None to save one with no fit_end at all."""
        cal = fit_conformal(add_horizon(self.val), method=method, group=group, level=level)
        prov = {"model_key": "Prophet", "fit_end": FIT_END, **provenance}
        save_calibrator(cal, self.path, **{k: v for k, v in prov.items() if v is not None})

    def test_matching_calibrator_is_served(self):
        self._save()
        _, plan = serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)
        self.assertTrue(plan["calibrated"])
        self.assertEqual(plan["provenance"]["fit_end"], FIT_END)

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

    # Each refusal below differs from a servable calibrator in one respect
    # only, and the message must name that respect.

    def test_calibrator_for_another_method_is_refused(self):
        self._save(method="relative", group="pooled")
        with self.assertRaisesRegex(CalibratorUnavailable, r"does not match: method relative/pooled"):
            serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)

    def test_calibrator_for_another_model_is_refused(self):
        self._save(model_key="SARIMA")
        with self.assertRaisesRegex(CalibratorUnavailable, r"does not match: model 'SARIMA'"):
            serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)

    def test_calibrator_for_another_level_is_refused(self):
        self._save(level=0.9)
        with self.assertRaisesRegex(CalibratorUnavailable, r"does not match: level 0\.9 \(config: 0\.8\)"):
            serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)

    def test_calibrator_for_another_checkpoint_is_refused(self):
        cfg = _cfg(Chronos={"method": "relative", "group": "pooled"})
        self._save(method="relative", group="pooled", model_key="Chronos",
                   checkpoint="amazon/chronos-t5-small")
        with self.assertRaisesRegex(CalibratorUnavailable, r"does not match: checkpoint"):
            serve_band(self.test, "Chronos", cfg, calibrator_path=self.path, checkpoint="amazon/chronos-t5-base")
        serve_band(self.test, "Chronos", cfg, calibrator_path=self.path, checkpoint="amazon/chronos-t5-small")

    def test_calibrator_fitted_to_another_train_end_is_refused(self):
        """A file left by a run on other splits is stale even when method,
        level, model and checkpoint all match."""
        self._save(fit_end="2019-12-31")
        with self.assertRaisesRegex(CalibratorUnavailable, r"does not match: fit_end '2019-12-31' \(config train_end: '2024-12-31'\)"):
            serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)

    def test_calibrator_without_fit_end_is_refused(self):
        self._save(fit_end=None)
        with self.assertRaisesRegex(CalibratorUnavailable, r"does not match: fit_end None"):
            serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)

    def test_fit_end_is_not_checked_without_a_configured_train_end(self):
        self._save(fit_end=None)
        cfg = {"calibration": self.cfg["calibration"]}
        _, plan = serve_band(self.test, "Prophet", cfg, calibrator_path=self.path)
        self.assertTrue(plan["calibrated"])

    def test_unquoted_yaml_date_matches_the_saved_fit_end(self):
        # `train_end: 2024-12-31` without quotes loads as a datetime.date.
        self._save()
        cfg = {**self.cfg, "data": {"train_end": datetime.date(2024, 12, 31)}}
        serve_band(self.test, "Prophet", cfg, calibrator_path=self.path)

    # ── a file that cannot be read is refused, not raised ──

    def _valid_doc(self) -> dict:
        self._save()
        return json.loads(self.path.read_text())

    def test_unreadable_calibrator_is_refused(self):
        bad_provenance = {**self._valid_doc(), "provenance": [1]}
        for name, content in {
            "top-level list": "[]",
            "top-level string": '"x"',
            "top-level null": "null",
            "invalid JSON": "{not json",
            "truncated": '{"format": 1, "meth',
            "provenance not an object": json.dumps(bad_provenance),
        }.items():
            with self.subTest(name):
                self.path.write_text(content)
                with self.assertRaisesRegex(CalibratorUnavailable, "unreadable calibrator"):
                    serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)

    def test_undecodable_calibrator_is_refused(self):
        self.path.write_bytes(b"\xff\xfe\x00\x81")
        with self.assertRaisesRegex(CalibratorUnavailable, "unreadable calibrator"):
            serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)

    def test_directory_at_the_calibrator_path_is_refused(self):
        self.path.mkdir()
        with self.assertRaisesRegex(CalibratorUnavailable, "unreadable calibrator"):
            serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads any file")
    def test_calibrator_without_read_permission_is_refused(self):
        self._save()
        self.path.chmod(0)
        try:
            with self.assertRaisesRegex(CalibratorUnavailable, "unreadable calibrator"):
                serve_band(self.test, "Prophet", self.cfg, calibrator_path=self.path)
        finally:
            self.path.chmod(0o600)

    def test_load_calibrator_rejects_a_document_that_is_not_an_object(self):
        for content in ("[]", '"x"', "null", "3"):
            with self.subTest(content):
                self.path.write_text(content)
                with self.assertRaises(ValueError):
                    load_calibrator(self.path)
        self.path.write_text(json.dumps({**self._valid_doc(), "provenance": "x"}))
        with self.assertRaises(ValueError):
            load_calibrator(self.path)


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

    # The leaderboard row must not depend on whether the file could be written.

    def _without_a_file(self, cfg):
        return calibrate_intervals("M", "M", self.test, lambda: self.val[BAND], self.val, cfg)

    def test_unwritable_calibrator_path_leaves_the_scored_band_unchanged(self):
        cfg = _cfg(M={"method": "relative", "group": "pooled"})
        expected, expected_label = self._without_a_file(cfg)
        blocker = Path(self.tmp.name) / "blocker"
        blocker.write_text("a regular file where a directory should be")
        with self.assertLogs("benchmarks", level="ERROR"):
            got, label = calibrate_intervals("M", "M", self.test, lambda: self.val[BAND], self.val, cfg,
                                             calibrator_path=blocker / "M.json")
        pd.testing.assert_frame_equal(got, expected, check_exact=True)
        self.assertEqual(label, expected_label)
        self.assertEqual(label, "split-conformal relative/pooled, fit on validation")

    def test_save_error_leaves_the_scored_band_unchanged_and_no_partial_file(self):
        cfg = _cfg(M={"method": "relative", "group": "pooled"})
        expected, expected_label = self._without_a_file(cfg)
        self.path.parent.mkdir(parents=True)

        def disk_full(calibrator, path, **provenance):
            Path(path).write_text('{"format": 1, "meth')
            raise OSError("No space left on device")

        with mock.patch.object(benchmarks, "save_calibrator", side_effect=disk_full), \
                self.assertLogs("benchmarks", level="ERROR"):
            got, label = calibrate_intervals("M", "M", self.test, lambda: self.val[BAND], self.val, cfg,
                                             calibrator_path=self.path)
        pd.testing.assert_frame_equal(got, expected, check_exact=True)
        self.assertEqual(label, expected_label)
        self.assertFalse(self.path.exists())

    def test_unusable_calibrator_path_does_not_raise_for_raw_or_failed_models(self):
        blocker = Path(self.tmp.name) / "blocker"
        blocker.write_text("a regular file where a directory should be")
        path = blocker / "M.json"

        def boom():
            raise RuntimeError("no validation forecasts")

        _, label = calibrate_intervals("M", "M", self.test, boom, self.val,
                                       _cfg(M={"method": "relative"}), calibrator_path=path)
        self.assertTrue(label.startswith("FAILED"))
        _, label = calibrate_intervals("M", "M", self.test, boom, self.val,
                                       _cfg(M={"method": "none", "reason": "r"}), calibrator_path=path)
        self.assertEqual(label, "raw: r")


class ClearSavedCalibratorsTest(unittest.TestCase):
    """benchmarks.py removes every saved calibrator when a run starts, so a
    file present afterwards was fitted by that run (--quick, a crashed model
    or a skipped one leave nothing stale behind)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "calibrators"

    def tearDown(self):
        self.tmp.cleanup()

    def test_removes_every_json_directly_in_the_directory(self):
        self.dir.mkdir()
        for name in ("SARIMA.json", "Chronos.json"):
            (self.dir / name).write_text("{}")
        (self.dir / "notes.txt").write_text("not a calibrator")
        # A directory whose name matches *.json is skipped, not removed.
        (self.dir / "sub.json").mkdir()
        (self.dir / "sub.json" / "x.json").write_text("{}")
        self.assertEqual(clear_saved_calibrators(self.dir), 2)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["notes.txt", "sub.json"])
        self.assertTrue((self.dir / "sub.json" / "x.json").exists())

    def test_a_file_that_cannot_be_removed_fails_the_run(self):
        # Carrying on would leave an older run's calibrator to be served.
        self.dir.mkdir()
        (self.dir / "SARIMA.json").write_text("{}")
        with mock.patch.object(Path, "unlink", side_effect=PermissionError("read-only")):
            with self.assertRaises(PermissionError):
                clear_saved_calibrators(self.dir)

    def test_missing_directory_is_nothing_to_clear(self):
        self.assertEqual(clear_saved_calibrators(self.dir), 0)

    def test_run_benchmarks_clears_before_any_model_runs(self):
        self.dir.mkdir()
        (self.dir / "SARIMA.json").write_text("{}")
        # Only training and validation months: the run stops at "test set is
        # empty", before any model is fitted or any calibrator saved.
        ts = pd.date_range("2024-01-01", "2025-06-01", freq="MS")
        df = pd.DataFrame({"timestamp": ts, "station_id": "S0", "ridership": 1000.0})
        cfg = {"data": {"train_end": FIT_END, "val_end": "2025-06-30", "resample_freq": "MS",
                        "forecast_horizon_steps": 6}}
        with mock.patch.multiple(benchmarks, EVAL_DIR=Path(self.tmp.name) / "outputs",
                                 CALIBRATOR_DIR=self.dir):
            self.assertTrue(benchmarks.run_benchmarks(df, cfg).empty)
        self.assertEqual(list(self.dir.iterdir()), [])



class LateRejectionTest(unittest.TestCase):
    """A model rejected after its calibrator was saved leaves no calibrator."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "M.json"
        self.path.write_text("{}")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _rows(n: int) -> list[dict]:
        return [{"model": "M", "slice": "overall", "n": n, "n_expected": 300, "WAPE_%": 5.0}]

    def test_rejected_model_loses_its_calibrator(self):
        self.assertEqual(benchmarks.accept_rows_and_calibrator(self._rows(299), "M", self.path), [])
        self.assertFalse(self.path.exists())

    def test_accepted_model_keeps_its_calibrator(self):
        self.assertTrue(benchmarks.accept_rows_and_calibrator(self._rows(300), "M", self.path))
        self.assertTrue(self.path.exists())


class UnsearchableCalibratorTest(unittest.TestCase):
    def test_permission_error_on_lookup_is_refused_not_raised(self):
        cfg = _cfg(Prophet={"method": "scaled", "group": "horizon"})
        test = _preds("2025-07-01", seed=2)[BAND]
        with mock.patch.object(Path, "exists", side_effect=PermissionError("no search permission")):
            with self.assertRaises(CalibratorUnavailable):
                serve_band(test, "Prophet", cfg, calibrator_path=Path("x/Prophet.json"))


if __name__ == "__main__":
    unittest.main()
