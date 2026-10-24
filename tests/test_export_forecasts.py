"""
tests/test_export_forecasts.py
──────────────────────────────
forecasts.json (scripts/export_website_data.py::export_forecasts) publishes
the band the leaderboard scored:

- p10/p90 are the band configs/model.yaml assigns to Chronos, applied from the
  calibrator benchmarks.py saved; the model's own bounds ride along as
  p10_raw/p90_raw, every record names its band (`interval_method`, the
  leaderboard's Interval_method string), and P50 is the raw model output;
- the file is refused (nothing written, the reason returned) when that
  calibrator is missing or stale, when the leaderboard row names another band
  or another model, or when the exported band does not reproduce the row's
  Coverage_% / Coverage_raw_% against the feature-store actuals.

Synthetic data only; no model is fitted.

    python -m unittest tests.test_export_forecasts -v
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from evaluation.calibration import (  # noqa: E402
    add_horizon,
    apply_conformal,
    fit_conformal,
    save_calibrator,
)
from evaluation.metrics import coverage  # noqa: E402
from machine_learning_files.bart_stations import CODES  # noqa: E402

# scripts/ is not a package; load the script as a module.
_spec = importlib.util.spec_from_file_location("export_website_data", REPO / "scripts" / "export_website_data.py")
ewd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ewd)
logging.getLogger("export_website_data").setLevel(logging.CRITICAL)

CKPT = "amazon/chronos-t5-small"
MODEL_LABEL = "Chronos1_ZeroShot (chronos-t5-small)"
CALIBRATED_LABEL = "split-conformal relative/pooled, fit on validation"
RAW_REASON = "no method passed validation"
STATIONS = list(CODES[:5])
SENTINEL = '[{"previous": "run"}]'


def _frame(start: str, seed: int) -> pd.DataFrame:
    """Six months of forecasts and actuals per station. The model's own band
    (+-3%) is far narrower than its errors (sd 8%), so raw and calibrated
    coverage differ and neither is 0% or 100%."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=6, freq="MS")
    df = pd.DataFrame([(t, s) for s in STATIONS for t in ts], columns=["timestamp", "station_id"])
    df["p50"] = rng.uniform(5_000, 50_000, size=len(df))
    df["ridership"] = np.round(df["p50"] * (1 + rng.normal(0, 0.08, size=len(df))))
    df["p10"] = df["p50"] * 0.97
    df["p90"] = df["p50"] * 1.03
    return df


def _cfg(chronos: dict, model_id: str = CKPT) -> dict:
    return {
        "chronos2": {"model_id": model_id},
        "data": {"train_end": "2024-12-31", "val_end": "2025-06-30"},
        "calibration": {"level": 0.8, "models": {"Chronos": chronos}},
    }


CALIBRATED = {"method": "relative", "group": "pooled", "validated_for": CKPT}
RAW = {"method": "none", "reason": RAW_REASON}


class ExportForecastsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.preds_path = root / "chronos2_zeroshot_preds.parquet"
        self.leaderboard_path = root / "benchmark_leaderboard.csv"
        self.config_path = root / "model.yaml"
        self.calibrator_path = root / "calibrators" / "Chronos.json"
        self.out = root / "out"
        self.out.mkdir()
        # A previous run's file: a refusal must leave it exactly as it was.
        (self.out / "forecasts.json").write_text(SENTINEL)

        val = _frame("2025-01-01", seed=1)
        test = _frame("2025-07-01", seed=2)
        # The parquet as Predictor writes it (float32 bounds, a run stamp).
        preds = test[["timestamp", "station_id", "p10", "p50", "p90"]].astype(
            {"p10": "float32", "p50": "float32", "p90": "float32"})
        preds["generated_at"] = "2026-10-24T00:00:00+00:00"
        preds["model_mode"] = "zeroshot"
        preds.to_parquet(self.preds_path, index=False)
        self.preds = pd.read_parquet(self.preds_path)

        # The feature store: training, validation and test months.
        train = _frame("2024-07-01", seed=3)
        self.actuals = pd.concat([train, val, test], ignore_index=True)[["timestamp", "station_id", "ridership"]]

        self.cal = fit_conformal(add_horizon(val), method="relative", group="pooled", level=0.8)
        self._save_calibrator()
        self._write_config(CALIBRATED)

        # The coverage benchmarks.py would have written, computed independently
        # of export_forecasts: apply_conformal on the raw preds, scored on the
        # test actuals (same row order as preds), rounded as the leaderboard is.
        y = test["ridership"].to_numpy(dtype=float)
        self.expected_band = apply_conformal(add_horizon(self.preds), self.cal)
        self.cov_cal = round(coverage(y, self.expected_band["p10"].to_numpy(float),
                                      self.expected_band["p90"].to_numpy(float)), 2)
        self.cov_raw = round(coverage(y, self.preds["p10"].to_numpy(float),
                                      self.preds["p90"].to_numpy(float)), 2)
        # The fixture only tests something if the two bands score differently.
        assert self.cov_cal != self.cov_raw, (self.cov_cal, self.cov_raw)
        assert 0 < self.cov_raw < 100 and 0 < self.cov_cal < 100, (self.cov_cal, self.cov_raw)
        self._write_leaderboard()

    def tearDown(self):
        self.tmp.cleanup()

    # ── fixture writers ──────────────────────────────────────────────────────

    def _save_calibrator(self, **overrides):
        prov = dict(model_key="Chronos", model=MODEL_LABEL, checkpoint=CKPT, label=CALIBRATED_LABEL,
                    fit_end="2024-12-31", window=["2025-01-01", "2025-06-01"])
        prov.update(overrides)
        save_calibrator(self.cal, self.calibrator_path, **prov)

    def _write_config(self, chronos: dict, **kw):
        self.config_path.write_text(yaml.safe_dump(_cfg(chronos, **kw)))

    def _write_leaderboard(self, drop=(), **chronos_overrides):
        n = len(self.preds)
        chronos = {"model": MODEL_LABEL, "slice": "overall", "n": n, "WAPE_%": 9.7, "MAE": 1.0,
                   "MAPE_%": 9.3, "Coverage_%": self.cov_cal, "n_expected": n,
                   "Coverage_raw_%": self.cov_raw, "Interval_method": CALIBRATED_LABEL}
        chronos.update(chronos_overrides)
        other = {"model": "SARIMA", "slice": "overall", "n": n, "WAPE_%": 3.2, "MAE": 1.0,
                 "MAPE_%": 3.4, "Coverage_%": 96.67, "n_expected": n,
                 "Coverage_raw_%": 96.67, "Interval_method": f"raw: {RAW_REASON}"}
        lb = pd.DataFrame([other, chronos]).drop(columns=list(drop))
        lb.to_csv(self.leaderboard_path)

    def _run(self, actuals: pd.DataFrame | None = None):
        with mock.patch.multiple(
            ewd,
            PREDS_PATH=self.preds_path,
            LEADERBOARD_PATH=self.leaderboard_path,
            CONFIG_PATH=self.config_path,
            CALIBRATOR_PATH=self.calibrator_path,
        ):
            return ewd.export_forecasts(self.out, self.actuals if actuals is None else actuals)

    def _records(self) -> list:
        text = (self.out / "forecasts.json").read_text()
        return json.loads(text, parse_constant=lambda c: self.fail(f"non-strict JSON constant {c}"))

    def assertRefused(self, reason, *fragments):
        self.assertIsNotNone(reason, "forecasts.json was written")
        for fragment in fragments:
            self.assertIn(fragment, reason)
        self.assertEqual((self.out / "forecasts.json").read_text(), SENTINEL)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["forecasts.json"])

    # ── the published band ───────────────────────────────────────────────────

    def test_publishes_the_calibrated_band_with_raw_bounds_and_label(self):
        self.assertIsNone(self._run())
        records = self._records()

        self.assertIsInstance(records, list)
        self.assertEqual(len(records), len(self.preds))
        self.assertEqual(
            set(records[0]),
            {"station_id", "month", "p10", "p50", "p90", "p10_raw", "p90_raw", "interval_method"},
        )

        expected = self.expected_band.assign(
            station_id=self.expected_band["station_id"].astype(str),
            month=self.expected_band["timestamp"].dt.strftime("%Y-%m"),
        ).sort_values(["station_id", "month"], kind="stable")
        self.assertEqual([(r["station_id"], r["month"]) for r in records],
                         list(zip(expected["station_id"], expected["month"])))

        def whole(col):
            return [round(float(v), 0) for v in expected[col]]

        # P50 is the raw parquet's, untouched by calibration.
        self.assertEqual([r["p50"] for r in records], whole("p50"))
        # p10/p90 are the saved calibrator applied to the raw forecasts...
        self.assertEqual([r["p10"] for r in records], whole("p10"))
        self.assertEqual([r["p90"] for r in records], whole("p90"))
        # ...and the model's own band is kept beside them.
        self.assertEqual([r["p10_raw"] for r in records], whole("p10_raw"))
        self.assertEqual([r["p90_raw"] for r in records], whole("p90_raw"))
        self.assertNotEqual([r["p10"] for r in records], [r["p10_raw"] for r in records])
        self.assertEqual({r["interval_method"] for r in records}, {CALIBRATED_LABEL})

    def test_p50_is_the_raw_parquet_value(self):
        self.assertIsNone(self._run())
        raw = self.preds.assign(month=self.preds["timestamp"].dt.strftime("%Y-%m"))
        by_key = {(s, m): round(float(v), 0) for s, m, v in zip(raw["station_id"], raw["month"], raw["p50"])}
        for r in self._records():
            self.assertEqual(r["p50"], by_key[(r["station_id"], r["month"])])

    def test_timezone_aware_forecast_timestamps_still_join_the_actuals(self):
        self.preds.assign(timestamp=self.preds["timestamp"].dt.tz_localize("America/Los_Angeles")) \
            .to_parquet(self.preds_path, index=False)
        self.assertIsNone(self._run())
        self.assertEqual(len(self._records()), len(self.preds))

    def test_model_left_raw_by_config_publishes_its_own_band(self):
        self._write_config(RAW)
        self.calibrator_path.unlink()  # not needed for a raw band
        self._write_leaderboard(**{"Coverage_%": self.cov_raw, "Interval_method": f"raw: {RAW_REASON}"})
        self.assertIsNone(self._run())
        records = self._records()
        self.assertEqual({r["interval_method"] for r in records}, {f"raw: {RAW_REASON}"})
        for r in records:
            self.assertEqual(r["p10"], r["p10_raw"])
            self.assertEqual(r["p90"], r["p90_raw"])

    def test_model_left_raw_is_still_checked_against_coverage(self):
        self._write_config(RAW)
        # The leaderboard's Coverage_% is the calibrated figure, the band is raw.
        self._write_leaderboard(**{"Interval_method": f"raw: {RAW_REASON}"})
        self.assertRefused(self._run(), "Coverage_%")

    # ── refusals: the calibrator ─────────────────────────────────────────────

    def test_missing_calibrator_is_refused(self):
        self.calibrator_path.unlink()
        self.assertRefused(self._run(), "no saved calibrator")

    def test_calibrator_for_another_checkpoint_is_refused(self):
        self._save_calibrator(checkpoint="amazon/chronos-t5-base")
        self.assertRefused(self._run(), "does not match", "checkpoint")

    def test_calibrator_fitted_for_another_leaderboard_row_is_refused(self):
        self._save_calibrator(model="Chronos1_ZeroShot (chronos-t5-small) [older run]")
        self.assertRefused(self._run(), "fitted for", MODEL_LABEL)

    def test_missing_config_is_refused_not_raised(self):
        self.config_path.unlink()
        self.assertRefused(self._run(), str(self.config_path))

    def test_config_checkpoint_other_than_validated_is_refused(self):
        # The config now pins a checkpoint the method was not validated for, so
        # the band would be raw; the leaderboard scored a calibrated one.
        self._write_config(CALIBRATED, model_id="amazon/chronos-t5-base")
        self.assertRefused(self._run(), "Interval_method", "raw: method validated for")

    # ── refusals: the leaderboard row ────────────────────────────────────────

    def test_interval_method_mismatch_is_refused(self):
        self._write_leaderboard(Interval_method="split-conformal scaled/horizon, fit on validation")
        self.assertRefused(self._run(), "Interval_method", CALIBRATED_LABEL)

    def test_missing_interval_method_column_is_refused(self):
        self._write_leaderboard(drop=["Interval_method"])
        self.assertRefused(self._run(), "no Interval_method column")

    def test_empty_interval_method_is_refused(self):
        self._write_leaderboard(Interval_method=np.nan)
        self.assertRefused(self._run(), "Interval_method")

    def test_coverage_mismatch_is_refused(self):
        self._write_leaderboard(**{"Coverage_%": self.cov_cal + 0.01})
        self.assertRefused(self._run(), "Coverage_%")

    def test_raw_coverage_mismatch_is_refused(self):
        self._write_leaderboard(**{"Coverage_raw_%": self.cov_raw + 0.01})
        self.assertRefused(self._run(), "Coverage_raw_%")

    def test_nan_coverage_is_refused(self):
        self._write_leaderboard(**{"Coverage_%": np.nan})
        self.assertRefused(self._run(), "Coverage_%")

    def test_missing_coverage_column_is_refused(self):
        self._write_leaderboard(drop=["Coverage_%"])
        self.assertRefused(self._run(), "Coverage_%")

    def test_leaderboard_without_raw_coverage_checks_the_served_band_only(self):
        self._write_leaderboard(drop=["Coverage_raw_%"])
        self.assertIsNone(self._run())

    # ── refusals: the actuals ────────────────────────────────────────────────

    def test_exported_row_with_no_actual_is_refused(self):
        last = self.actuals.index[-1]
        self.assertRefused(self._run(self.actuals.drop(index=last)), "no feature-store actual")

    def test_exported_row_with_nan_actual_is_refused(self):
        actuals = self.actuals.copy()
        actuals.loc[actuals.index[-1], "ridership"] = np.nan
        self.assertRefused(self._run(actuals), "no feature-store actual")

    def test_duplicated_actual_is_refused(self):
        actuals = pd.concat([self.actuals, self.actuals.iloc[[-1]]], ignore_index=True)
        self.assertRefused(self._run(actuals), "more than one feature-store row")


if __name__ == "__main__":
    unittest.main()
