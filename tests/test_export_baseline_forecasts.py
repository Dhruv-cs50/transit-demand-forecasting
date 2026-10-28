"""
tests/test_export_baseline_forecasts.py
───────────────────────────────────────
forecasts_prophet.json, forecasts_seasonal_naive.json and backtest_windows.json
(scripts/export_website_data.py) publish what the leaderboard scored, or are
refused with nothing written:

- Prophet's p10/p90 are the band configs/model.yaml assigns it, applied from the
  calibrator benchmarks.py saved to the model's own forecasts; seasonal naive's
  parquet already carries the scored band and the model's own;
- each is refused unless it has the leaderboard row's `n` predictions, its band's
  label is the row's Interval_method, and WAPE_%, MAE, Coverage_% and
  Coverage_raw_% recomputed against the actuals equal the row's;
- backtest_windows.json is refused unless its 2025-H2 rows equal the
  leaderboard's overall rows.

Synthetic data only; no model is fitted.

    python -m unittest tests.test_export_baseline_forecasts -v
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

from evaluation.calibration import add_horizon, apply_conformal, fit_conformal, save_calibrator  # noqa: E402
from evaluation.metrics import coverage, mae, wape  # noqa: E402
from machine_learning_files.bart_stations import CODES  # noqa: E402

_spec = importlib.util.spec_from_file_location("export_website_data", REPO / "scripts" / "export_website_data.py")
ewd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ewd)
logging.getLogger("export_website_data").setLevel(logging.CRITICAL)

STATIONS = list(CODES[:5])
PROPHET_LABEL = "split-conformal relative/pooled, fit on validation"
NAIVE_LABEL = "rolling-origin conformal asym_relative/horizon (test)"
SENTINEL = '[{"previous": "run"}]'


def _frame(start: str, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=6, freq="MS")
    df = pd.DataFrame([(t, s) for s in STATIONS for t in ts], columns=["timestamp", "station_id"])
    df["p50"] = rng.uniform(5_000, 50_000, size=len(df))
    df["ridership"] = np.round(df["p50"] * (1 + rng.normal(0, 0.08, size=len(df))))
    df["p10"] = df["p50"] * 0.97
    df["p90"] = df["p50"] * 1.03
    return df


class BaselineExportBase(unittest.TestCase):
    """Common fixture: a test window of forecasts, the feature-store actuals and
    a leaderboard with Prophet and SeasonalNaive rows computed independently of
    the export."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.out = root / "out"
        self.out.mkdir()
        self.leaderboard_path = root / "leaderboard.csv"
        self.config_path = root / "model.yaml"
        self.calibrator_path = root / "calibrators" / "Prophet.json"
        self.prophet_path = root / "prophet_forecasts.parquet"
        self.naive_path = root / "seasonal_naive_forecasts.parquet"

        val = _frame("2025-01-01", seed=1)
        test = _frame("2025-07-01", seed=2)
        train = _frame("2024-07-01", seed=3)
        self.actuals = pd.concat([train, val, test], ignore_index=True)[["timestamp", "station_id", "ridership"]]
        self.test = test
        self.y = test["ridership"].to_numpy(dtype=float)

        # Prophet: its own band, a saved calibrator, the band the config assigns.
        self.prophet = test[["timestamp", "station_id", "p10", "p50", "p90"]].assign(model="Prophet")
        self.prophet.to_parquet(self.prophet_path, index=False)
        self.cal = fit_conformal(add_horizon(val), method="relative", group="pooled", level=0.8)
        save_calibrator(self.cal, self.calibrator_path, model_key="Prophet", model="Prophet",
                        checkpoint=None, label=PROPHET_LABEL, fit_end="2024-12-31",
                        window=["2025-01-01", "2025-06-01"])
        self.config_path.write_text(yaml.safe_dump({
            "data": {"train_end": "2024-12-31", "val_end": "2025-06-30"},
            "calibration": {"level": 0.8, "models": {"Prophet": {"method": "relative", "group": "pooled"}}},
        }))
        self.prophet_band = apply_conformal(add_horizon(self.prophet), self.cal)

        # Seasonal naive: the scored band saved with the model's own (+-20%).
        rng = np.random.default_rng(9)
        wide = test[["timestamp", "station_id", "p50"]].copy()
        wide["p10_raw"], wide["p90_raw"] = wide["p50"] * 0.8, wide["p50"] * 1.2
        wide["p10"] = wide["p50"] * (0.85 + rng.uniform(0, 0.01, len(wide)))
        wide["p90"] = wide["p50"] * (1.12 + rng.uniform(0, 0.01, len(wide)))
        wide["model"] = "SeasonalNaive"
        wide["interval_method"] = NAIVE_LABEL
        self.naive = wide
        wide.to_parquet(self.naive_path, index=False)
        self._write_leaderboard()

    def _cov(self, lo, hi):
        return round(coverage(self.y, np.asarray(lo, float), np.asarray(hi, float)), 2)

    def _row(self, label, preds, interval, cov, cov_raw):
        p50 = np.maximum(preds["p50"].to_numpy(float), 0)
        return {"model": label, "slice": "overall", "n": len(preds), "n_expected": len(preds),
                "WAPE_%": round(wape(self.y, p50), 2), "MAE": round(mae(self.y, p50), 2),
                "Coverage_%": cov, "Coverage_raw_%": cov_raw, "Interval_method": interval}

    def _write_leaderboard(self, **overrides):
        prophet = self._row("Prophet", self.prophet, PROPHET_LABEL,
                            self._cov(self.prophet_band["p10"], self.prophet_band["p90"]),
                            self._cov(self.prophet["p10"], self.prophet["p90"]))
        naive = self._row("SeasonalNaive", self.naive, NAIVE_LABEL,
                          self._cov(self.naive["p10"], self.naive["p90"]),
                          self._cov(self.naive["p10_raw"], self.naive["p90_raw"]))
        sarima = dict(naive, model="SARIMA", Interval_method="raw: no method passed validation")
        for who, change in overrides.items():
            {"prophet": prophet, "naive": naive}[who].update(change)
        pd.DataFrame([sarima, prophet, naive]).to_csv(self.leaderboard_path)

    def assertRefused(self, reason, filename, fragment):
        self.assertIsNotNone(reason, f"{filename} was written")
        self.assertIn(fragment, reason)
        self.assertEqual(list(self.out.iterdir()), [])


class ProphetExport(BaselineExportBase):
    def _run(self, actuals=None):
        with mock.patch.multiple(ewd, PROPHET_PREDS_PATH=self.prophet_path, LEADERBOARD_PATH=self.leaderboard_path,
                                 CONFIG_PATH=self.config_path, PROPHET_CALIBRATOR_PATH=self.calibrator_path):
            return ewd.export_prophet_forecasts(self.out, self.actuals if actuals is None else actuals)

    def test_publishes_the_calibrated_band_with_the_models_own_bounds(self):
        self.assertIsNone(self._run())
        recs = json.loads((self.out / "forecasts_prophet.json").read_text())
        self.assertEqual(len(recs), len(self.prophet))
        self.assertEqual(set(recs[0]), {"station_id", "month", "p10", "p50", "p90", "p10_raw", "p90_raw",
                                        "interval_method", "model"})
        self.assertEqual({r["model"] for r in recs}, {"Prophet"})
        self.assertEqual({r["interval_method"] for r in recs}, {PROPHET_LABEL})
        expected = self.prophet_band.assign(month=self.prophet_band["timestamp"].dt.strftime("%Y-%m")) \
            .sort_values(["station_id", "month"], kind="stable")
        self.assertEqual([r["p10"] for r in recs], list(np.round(expected["p10"].to_numpy(float), 0)))
        self.assertEqual([r["p10_raw"] for r in recs], list(np.round(expected["p10_raw"].to_numpy(float), 0)))
        self.assertEqual([r["p50"] for r in recs], list(np.round(expected["p50"].to_numpy(float), 0)))
        self.assertTrue(any(r["p10"] != r["p10_raw"] for r in recs))

    def test_missing_calibrator_is_refused(self):
        self.calibrator_path.unlink()
        self.assertRefused(self._run(), "forecasts_prophet.json", "no saved calibrator")

    def test_calibrator_fitted_for_another_model_is_refused(self):
        save_calibrator(self.cal, self.calibrator_path, model_key="Prophet", model="Prophet [older run]",
                        checkpoint=None, label=PROPHET_LABEL, fit_end="2024-12-31",
                        window=["2025-01-01", "2025-06-01"])
        self.assertRefused(self._run(), "forecasts_prophet.json", "fitted for")

    def test_leaderboard_naming_another_band_is_refused(self):
        self._write_leaderboard(prophet={"Interval_method": "raw: something else"})
        self.assertRefused(self._run(), "forecasts_prophet.json", "Interval_method")

    def test_wrong_row_count_is_refused(self):
        self._write_leaderboard(prophet={"n": len(self.prophet) + 1})
        self.assertRefused(self._run(), "forecasts_prophet.json", "n=")

    def test_forecasts_from_another_run_are_refused(self):
        self.prophet.assign(p50=self.prophet["p50"] * 1.3, p10=self.prophet["p10"] * 1.3,
                            p90=self.prophet["p90"] * 1.3).to_parquet(self.prophet_path, index=False)
        self.assertRefused(self._run(), "forecasts_prophet.json", "WAPE_%")

    def test_a_row_without_an_actual_is_refused(self):
        self.assertRefused(self._run(self.actuals.iloc[:-1]), "forecasts_prophet.json", "no single feature-store actual")

    def test_missing_parquet_is_refused(self):
        self.prophet_path.unlink()
        self.assertRefused(self._run(), "forecasts_prophet.json", "not found")


class SeasonalNaiveExport(BaselineExportBase):
    def _run(self):
        with mock.patch.multiple(ewd, SEASONAL_NAIVE_PREDS_PATH=self.naive_path, LEADERBOARD_PATH=self.leaderboard_path):
            return ewd.export_seasonal_naive_forecasts(self.out, self.actuals)

    def test_publishes_the_saved_scored_band_and_the_models_own(self):
        self.assertIsNone(self._run())
        recs = json.loads((self.out / "forecasts_seasonal_naive.json").read_text())
        self.assertEqual(len(recs), len(self.naive))
        self.assertEqual({r["model"] for r in recs}, {"SeasonalNaive"})
        self.assertEqual({r["interval_method"] for r in recs}, {NAIVE_LABEL})
        by_key = {(r["station_id"], r["month"]): r for r in recs}
        row = self.naive.iloc[0]
        r = by_key[(row.station_id, row.timestamp.strftime("%Y-%m"))]
        self.assertEqual((r["p10"], r["p90"]), (round(row.p10), round(row.p90)))
        self.assertEqual((r["p10_raw"], r["p90_raw"]), (round(row.p10_raw), round(row.p90_raw)))

    def test_band_label_not_the_leaderboards_is_refused(self):
        self._write_leaderboard(naive={"Interval_method": "raw: +-20%"})
        self.assertRefused(self._run(), "forecasts_seasonal_naive.json", "Interval_method")

    def test_band_that_the_leaderboard_did_not_score_is_refused(self):
        self.naive.assign(p90=self.naive["p90"] * 1.5).to_parquet(self.naive_path, index=False)
        self.assertRefused(self._run(), "forecasts_seasonal_naive.json", "Coverage_%")

    def test_a_parquet_without_the_raw_band_is_refused(self):
        self.naive.drop(columns=["p10_raw", "p90_raw"]).to_parquet(self.naive_path, index=False)
        self.assertRefused(self._run(), "forecasts_seasonal_naive.json", "lacks columns")

    def test_the_wrong_model_is_refused(self):
        self.naive.assign(model="Prophet").to_parquet(self.naive_path, index=False)
        self.assertRefused(self._run(), "forecasts_seasonal_naive.json", "model column")


class BacktestExport(unittest.TestCase):
    MODELS = ["SARIMA", "Prophet", "Chronos1_ZeroShot (chronos-t5-small)", "SeasonalNaive"]
    WINDOWS = [("2024-H2", "2024-06-30", "2024-07", "2024-12"), ("2025-H1", "2024-12-31", "2025-01", "2025-06"),
               ("2025-H2", "2025-06-30", "2025-07", "2025-12")]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.out = root / "out"
        self.out.mkdir()
        self.csv = root / "backtest_windows.csv"
        self.leaderboard_path = root / "leaderboard.csv"
        self.board = pd.DataFrame([
            {"model": m, "slice": "overall", "n": 300, "WAPE_%": w, "MAE": a, "Coverage_%": 80.0,
             "Coverage_raw_%": c, "Interval_method": "x"}
            for m, w, a, c in zip(self.MODELS, (3.21, 5.75, 9.7, 10.75), (3086.41, 5526.41, 9320.76, 10332.88),
                                  (96.67, 46.0, 51.0, 94.33))
        ])
        self.board.to_csv(self.leaderboard_path)
        rows = []
        for wid, fit, first, last in self.WINDOWS:
            for i, m in enumerate(self.MODELS):
                lb = self.board.iloc[i]
                same = wid == "2025-H2"
                rows.append(dict(window=wid, fit_through=fit, first_month=first, last_month=last, model=m,
                                 wape=lb["WAPE_%"] if same else lb["WAPE_%"] + 1, mae=lb["MAE"] if same else lb["MAE"] + 1,
                                 n=300, n_expected=300, coverage_own_band=lb["Coverage_raw_%"] if same else 70.0,
                                 stations_sarima_beats=np.nan if i == 0 else 40 + i))
        self.table = pd.DataFrame(rows)
        self._write()

    def _write(self):
        self.table.to_csv(self.csv, index=False)

    def _run(self):
        with mock.patch.multiple(ewd, BACKTEST_PATH=self.csv, LEADERBOARD_PATH=self.leaderboard_path):
            return ewd.export_backtest_windows(self.out)

    def assertRefused(self, fragment):
        reason = self._run()
        self.assertIsNotNone(reason)
        self.assertIn(fragment, reason)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_publishes_the_contract_shape(self):
        self.assertIsNone(self._run())
        data = json.loads((self.out / "backtest_windows.json").read_text())
        self.assertEqual(set(data), {"windows", "rows", "source", "generated_by"})
        self.assertEqual(data["windows"], [{"id": w, "fit_through": f, "first_month": a, "last_month": b}
                                           for w, f, a, b in self.WINDOWS])
        self.assertEqual(len(data["rows"]), 12)
        self.assertEqual(set(data["rows"][0]), {"window", "model", "wape", "mae", "n", "coverage_own_band",
                                                "stations_sarima_beats"})
        sarima = [r for r in data["rows"] if r["model"] == "SARIMA"]
        self.assertTrue(all(r["stations_sarima_beats"] is None for r in sarima))
        self.assertTrue(all(isinstance(r["stations_sarima_beats"], int) for r in data["rows"] if r["model"] != "SARIMA"))
        self.assertEqual(data["generated_by"], "models/baselines/backtest_windows.py")

    def test_published_window_not_equal_to_the_leaderboard_is_refused(self):
        self.table.loc[(self.table.window == "2025-H2") & (self.table.model == "SARIMA"), "wape"] = 3.22
        self._write()
        self.assertRefused("WAPE_%")

    def test_published_window_n_is_checked(self):
        self.table.loc[(self.table.window == "2025-H2") & (self.table.model == "Prophet"), "n"] = 299
        self.table.loc[(self.table.window == "2025-H2") & (self.table.model == "Prophet"), "n_expected"] = 299
        self._write()
        self.assertRefused("different number of rows")

    def test_own_band_coverage_must_equal_the_raw_coverage(self):
        self.table.loc[(self.table.window == "2025-H2") & (self.table.model == "Prophet"), "coverage_own_band"] = 74.0
        self._write()
        self.assertRefused("Coverage_raw_%")

    def test_a_window_missing_a_model_is_refused(self):
        self.table = self.table.drop(self.table.index[(self.table.window == "2024-H2") & (self.table.model == "Prophet")])
        self._write()
        self.assertRefused("2024-H2 has models")

    def test_sarima_must_have_no_station_count(self):
        self.table.loc[(self.table.window == "2025-H1") & (self.table.model == "SARIMA"), "stations_sarima_beats"] = 10
        self._write()
        self.assertRefused("SARIMA's stations_sarima_beats must be empty")

    def test_missing_csv_is_refused(self):
        self.csv.unlink()
        self.assertRefused("not found")


if __name__ == "__main__":
    unittest.main()
