"""
tests/test_export_sarima_forecasts.py
─────────────────────────────────────
forecasts_sarima.json (scripts/export_website_data.py::export_sarima_forecasts)
publishes the SARIMA forecasts benchmarks.py scored, or is refused: the parquet
must reproduce the leaderboard's overall SARIMA row (n, WAPE_%, MAE, coverage)
against the feature-store actuals, and that row's band must be a "raw: ..."
label. Synthetic data only.

    python -m unittest tests.test_export_sarima_forecasts -v
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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from evaluation.metrics import coverage, mae, wape  # noqa: E402
from machine_learning_files.bart_stations import CODES  # noqa: E402

_spec = importlib.util.spec_from_file_location("export_website_data", REPO / "scripts" / "export_website_data.py")
ewd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ewd)
logging.getLogger("export_website_data").setLevel(logging.CRITICAL)

LABEL = "raw: no method passed validation"
STATIONS = list(CODES[:3])
MONTHS = pd.date_range("2025-07-01", periods=6, freq="MS")


class SarimaExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.out = root / "out"
        self.out.mkdir()
        self.preds_path = root / "arima_forecasts.parquet"
        self.leaderboard_path = root / "leaderboard.csv"
        rng = np.random.default_rng(0)
        rows, acts = [], []
        for s in STATIONS:
            for m in MONTHS:
                a = float(rng.integers(50_000, 90_000))
                p = a * float(rng.uniform(0.9, 1.1))
                rows.append(dict(timestamp=m, station_id=s, p10=p * 0.95, p50=p, p90=p * 1.05, model="SARIMA"))
                acts.append(dict(timestamp=m, station_id=s, ridership=a))
        self.preds = pd.DataFrame(rows)
        self.actuals = pd.DataFrame(acts)
        self._write_leaderboard()

    def _scores(self, preds=None):
        p = self.preds if preds is None else preds
        y = self.actuals["ridership"].to_numpy(float)
        return {
            "WAPE_%": round(wape(y, p["p50"].to_numpy(float)), 2),
            "MAE": round(mae(y, p["p50"].to_numpy(float)), 2),
            "Coverage_%": round(coverage(y, p["p10"].to_numpy(float), p["p90"].to_numpy(float)), 2),
        }

    def _write_leaderboard(self, **over):
        row = {"model": "SARIMA", "slice": "overall", "n": len(self.preds), **self._scores(),
               "Interval_method": LABEL}
        row["Coverage_raw_%"] = row["Coverage_%"]
        row.update(over)
        pd.DataFrame([row]).to_csv(self.leaderboard_path)
        self.preds.to_parquet(self.preds_path)

    def _run(self):
        with mock.patch.multiple(ewd, SARIMA_PREDS_PATH=self.preds_path, LEADERBOARD_PATH=self.leaderboard_path):
            return ewd.export_sarima_forecasts(self.out, self.actuals)

    def assertRefused(self, reason, fragment):
        self.assertIsNotNone(reason)
        self.assertIn(fragment, reason)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_publishes_records_with_model_and_label(self):
        self.assertIsNone(self._run())
        recs = json.loads((self.out / "forecasts_sarima.json").read_text())
        self.assertEqual(len(recs), len(self.preds))
        self.assertEqual(set(recs[0]), {"station_id", "month", "p10", "p50", "p90", "p10_raw", "p90_raw",
                                        "interval_method", "model"})
        self.assertEqual({r["model"] for r in recs}, {"SARIMA"})
        self.assertEqual({r["interval_method"] for r in recs}, {LABEL})
        self.assertTrue(all(r["p10"] == r["p10_raw"] and r["p90"] == r["p90_raw"] for r in recs))
        self.assertEqual(recs[0]["month"], "2025-07")

    def test_forecasts_from_another_cutoff_are_refused(self):
        # A standalone arima.py run (earlier cutoff) forecasts other months/values.
        self.preds = self.preds.assign(p50=self.preds["p50"] * 1.2, p10=self.preds["p10"] * 1.2, p90=self.preds["p90"] * 1.2)
        self.preds.to_parquet(self.preds_path)
        self.assertRefused(self._run(), "WAPE_%")

    def test_wrong_row_count_is_refused(self):
        self._write_leaderboard(n=len(self.preds) + 1)
        self.assertRefused(self._run(), "n=")

    def test_calibrated_label_is_refused(self):
        self._write_leaderboard(Interval_method="split-conformal relative/pooled, fit on validation")
        self.assertRefused(self._run(), "raw:")

    def test_missing_parquet_is_refused(self):
        self.preds_path.unlink()
        self.assertRefused(self._run(), "not found")

    def test_row_without_actual_is_refused(self):
        self.actuals = self.actuals.iloc[1:]
        self.assertRefused(self._run(), "no single feature-store actual")

    def test_unknown_station_is_refused(self):
        self.preds = self.preds.assign(station_id="ZZ")
        self.preds.to_parquet(self.preds_path)
        self.assertRefused(self._run(), "station table")


if __name__ == "__main__":
    unittest.main()
