"""
tests/test_export_caltrain.py
─────────────────────────────
scripts/export_website_data.py --caltrain adds four Caltrain files to the
all-or-nothing export (Caltrain plan, Task 4):

  caltrain_series.json          [{month, awr, method_period, electrified}]
  caltrain_forecast.json        {model, window, fit_through, rows: [{month, p10, p50, p90}]}
                                the best model by WAPE on the test window
  caltrain_leaderboard.json     {windows: [...], rows: [...], test_window, source, generated_by};
                                each row carries `source` and `scored_split` (its window's role)
  caltrain_station_annual.json  [{fiscal_year, station, avg_midweek_boardings, report_url,
                                  first_month, last_month, basis}]

The Caltrain export is opt-in. Without the flag nothing Caltrain is read or
written, so the cloud ingest and the release gate keep working when the
gitignored Caltrain outputs are absent. With the flag, a missing Caltrain
output refuses the whole export: nothing is published.

The BART exporters are stubbed (as in test_export_all_or_nothing.py); the
Caltrain exporter runs for real on small fixture inputs.

    python -m pytest tests/test_export_caltrain.py -q
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

from evaluation.metrics import coverage, mae, wape  # noqa: E402

_spec = importlib.util.spec_from_file_location("export_website_data_ct", REPO / "scripts" / "export_website_data.py")
ewd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ewd)
logging.getLogger("export_website_data").setLevel(logging.CRITICAL)

BART_FILES = ["backtest_windows.json", "forecasts.json", "forecasts_prophet.json", "forecasts_sarima.json",
              "forecasts_seasonal_naive.json", "model_comparison.json", "ridership_actuals.json",
              "stations_meta.json", "stations_ridership.json"]
CALTRAIN_FILES = ["caltrain_forecast.json", "caltrain_leaderboard.json", "caltrain_series.json",
                  "caltrain_station_annual.json"]
CHRONOS = "Chronos1_ZeroShot (chronos-t5-small)"
# model label -> (forecasts_<slug>.parquet, p50 = actual * factor per window)
MODELS = {
    "SeasonalNaive": ("seasonal_naive", {"2023-H1": 1.20, "2023-H2": 0.80}),
    "SARIMA": ("sarima", {"2023-H1": 1.04, "2023-H2": 1.02}),
    "Prophet": ("prophet", {"2023-H1": 1.01, "2023-H2": 1.05}),
    CHRONOS: ("chronos1", {"2023-H1": 0.97, "2023-H2": 1.30}),
}


def _months(a: str, b: str) -> pd.DatetimeIndex:
    return pd.date_range(f"{a}-01", f"{b}-01", freq="MS")


def write_caltrain_inputs(root: Path) -> dict:
    """Small but complete Caltrain inputs under `root`; returns their paths.

    Store: 2019 plus 2022-01..2023-12 (2020-21 excluded), a method change at
    2023-07 and electrification from 2023-10. Windows: 2022-H1 insufficient
    history, 2022-H2 rejected by the step rule (no leaderboard rows), 2023-H1
    development (Prophet best) and 2023-H2 test (SARIMA best).
    """
    out = root / "evaluation" / "outputs" / "caltrain"
    out.mkdir(parents=True)
    months = _months("2019-01", "2019-12").append(_months("2022-01", "2023-12"))
    rng = np.random.default_rng(0)
    awr = np.round(20000 + 3000 * rng.random(len(months))).astype(float)
    store = pd.DataFrame({
        "timestamp": months.astype("datetime64[us]"),
        "station_id": "CALTRAIN_SYSTEM",
        "ridership": awr,
        "method_period": ["2019-02" if m.year == 2019 else ("2023-07" if m >= pd.Timestamp("2023-07-01") else "2020-04")
                          for m in months],
        "method_2023_07": (months >= pd.Timestamp("2023-07-01")).astype("int64"),
        "electrified": (months >= pd.Timestamp("2023-10-01")).astype("int64"),
    })
    store_path = root / "data" / "processed" / "caltrain_store.parquet"
    store_path.parent.mkdir(parents=True)
    store.to_parquet(store_path, index=False)
    actual = dict(zip(store["timestamp"], store["ridership"]))

    windows = pd.DataFrame([
        {"window": "2022-H1", "start": "2022-01", "end": "2022-06", "cutoff": "2021-12", "role": "rejected",
         "admitted": False, "reason": "insufficient history (0 < 24 usable months before the cutoff)",
         "insufficient_history": True, "usable_months": 0, "actual_months": 6},
        {"window": "2022-H2", "start": "2022-07", "end": "2022-12", "cutoff": "2022-06", "role": "rejected",
         "admitted": False, "reason": "electrified is 1 in 3 window month(s) but has 0 < 6 months at 1 before the cutoff",
         "insufficient_history": False, "usable_months": 30, "actual_months": 6},
        {"window": "2023-H1", "start": "2023-01", "end": "2023-06", "cutoff": "2022-12", "role": "development",
         "admitted": True, "reason": np.nan, "insufficient_history": False, "usable_months": 36, "actual_months": 6},
        {"window": "2023-H2", "start": "2023-07", "end": "2023-12", "cutoff": "2023-06", "role": "test",
         "admitted": True, "reason": np.nan, "insufficient_history": False, "usable_months": 42, "actual_months": 6},
    ])
    windows.to_csv(out / "windows.csv", index=False)

    rows = [{"window": "2022-H1", "model": m, "wape": np.nan, "mae": np.nan, "n": 0,
             "coverage_own_band": np.nan, "status": "insufficient history"} for m in MODELS]
    for model, (slug, factors) in MODELS.items():
        frames = []
        for win, start, end in (("2023-H1", "2023-01", "2023-06"), ("2023-H2", "2023-07", "2023-12")):
            ms = _months(start, end).astype("datetime64[us]")
            y = np.array([actual[m] for m in ms])
            p50 = y * factors[win]
            p10, p90 = p50 * 0.97, p50 * 1.03
            frames.append(pd.DataFrame({"window": win, "model": model, "timestamp": ms,
                                        "station_id": "CALTRAIN_SYSTEM", "p10": p10, "p50": p50, "p90": p90}))
            rows.append({"window": win, "model": model, "wape": round(wape(y, p50), 2), "mae": round(mae(y, p50), 2),
                         "n": 6, "coverage_own_band": round(coverage(y, p10, p90), 2), "status": "ok"})
        pd.concat(frames, ignore_index=True).to_parquet(out / f"forecasts_{slug}.parquet", index=False)
    pd.DataFrame(rows).to_csv(out / "leaderboard.csv", index=False)

    stations = pd.DataFrame([
        {"fiscal_year": fy, "station": st, "avg_midweek_boardings": v, "report_url": f"https://example.org/{fy}"}
        for fy, vals in ((2019, (15000, 7000)), (2024, (5000, 2000)), (2025, (7000, 3000)), (2026, (9000, 4000)))
        for st, v in zip(("San Francisco", "Palo Alto"), vals)
    ])
    stations_path = root / "data" / "caltrain" / "station_annual.csv"
    stations_path.parent.mkdir(parents=True)
    stations.to_csv(stations_path, index=False)

    config_path = root / "configs" / "caltrain.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(yaml.safe_dump({"benchmark": {"test_window": "2023-H2"}}))
    return {"dir": out, "store": store_path, "stations": stations_path, "config": config_path,
            "leaderboard": out / "leaderboard.csv", "windows": out / "windows.csv",
            **{f"forecasts_{slug}": out / f"forecasts_{slug}.parquet" for slug, _ in MODELS.values()}}


class CaltrainExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.site = root / "website"
        self.out = self.site / "data"
        self.out.mkdir(parents=True)
        for name in BART_FILES:
            (self.out / name).write_text(f'"old {name}"')
        self.inputs = write_caltrain_inputs(root / "repo")
        # create=True: the default-export test must run even against a script
        # that has no Caltrain constants at all.
        p = mock.patch.multiple(
            ewd,
            create=True,
            CALTRAIN_DIR=self.inputs["dir"],
            CALTRAIN_STORE_PATH=self.inputs["store"],
            CALTRAIN_STATIONS_PATH=self.inputs["stations"],
            CALTRAIN_CONFIG_PATH=self.inputs["config"],
        )
        p.start()
        self.addCleanup(p.stop)
        self._stub_bart()

    def _stub_bart(self):
        """Every BART exporter writes a fixed small file; only staging is real."""
        def write(name):
            def fn(*a):
                a[-1].joinpath(name).write_text(f'"new {name}"')
            return fn

        def write_ok(name):
            def fn(out_dir, *a):
                out_dir.joinpath(name).write_text(f'"new {name}"')
                return None
            return fn

        patches = mock.patch.multiple(
            ewd,
            load_feature_store=lambda path: pd.DataFrame({"x": [1]}),
            check_station_ids=lambda df: None,
            compute_station_ridership=lambda df: pd.DataFrame({"avg_monthly_ridership": [1.0]}),
            check_station_averages=lambda agg: None,
            require_leaderboard=lambda: None,
            build_ridership_json=lambda agg: {"a": 1},
            build_meta_json=lambda agg: [{"a": 1}],
            export_ridership_actuals=write("ridership_actuals.json"),
            export_forecasts=write_ok("forecasts.json"),
            export_sarima_forecasts=write_ok("forecasts_sarima.json"),
            export_prophet_forecasts=write_ok("forecasts_prophet.json"),
            export_seasonal_naive_forecasts=write_ok("forecasts_seasonal_naive.json"),
            export_backtest_windows=write_ok("backtest_windows.json"),
            export_model_comparison=write("model_comparison.json"),
        )
        patches.start()
        self.addCleanup(patches.stop)

    def _main(self, *flags):
        with mock.patch.object(sys, "argv", ["export", "--out-dir", str(self.out), *flags]):
            ewd.main()

    def _snapshot(self):
        return {p.name: p.read_bytes() for p in self.out.iterdir()}

    def _json(self, name):
        return json.loads((self.out / name).read_text())

    def assertNoStaging(self):
        self.assertEqual(sorted(p.name for p in self.site.iterdir()), ["data"],
                         "a staging directory was left behind")

    # ── contract ────────────────────────────────────────────────────────────
    def test_caltrain_files_written_with_contract(self):
        self._main("--caltrain")
        self.assertEqual(sorted(self._snapshot()), sorted(BART_FILES + CALTRAIN_FILES))
        for name in CALTRAIN_FILES:  # strict JSON: no NaN / Infinity tokens
            json.loads((self.out / name).read_text(), parse_constant=lambda c: self.fail(f"{name}: {c}"))

        store = pd.read_parquet(self.inputs["store"])
        series = self._json("caltrain_series.json")
        self.assertIsInstance(series, list)
        self.assertEqual(len(series), len(store))
        self.assertEqual(set(series[0]), {"month", "awr", "method_period", "electrified"})
        self.assertEqual(series[0], {"month": "2019-01", "awr": int(store["ridership"].iloc[0]),
                                     "method_period": "2019-02", "electrified": 0})
        self.assertNotIn("2020-06", {r["month"] for r in series})
        self.assertEqual([r["month"] for r in series], sorted(r["month"] for r in series))
        self.assertTrue(all(isinstance(r["awr"], int) for r in series))
        self.assertEqual(next(r["month"] for r in series if r["electrified"] == 1), "2023-10")

        fc = self._json("caltrain_forecast.json")
        self.assertEqual(fc["model"], "SARIMA")  # best on the TEST window; Prophet is best on 2023-H1
        self.assertEqual(fc["window"], "2023-H2")
        self.assertEqual(fc["fit_through"], "2023-06")
        self.assertEqual([r["month"] for r in fc["rows"]], [f"2023-{m:02d}" for m in range(7, 13)])
        self.assertEqual(set(fc["rows"][0]), {"month", "p10", "p50", "p90"})
        sar = pd.read_parquet(self.inputs["forecasts_sarima"]).query("window == '2023-H2'")
        self.assertAlmostEqual(fc["rows"][0]["p50"], float(sar["p50"].iloc[0]))

        lb = self._json("caltrain_leaderboard.json")
        self.assertEqual(lb["test_window"], "2023-H2")
        self.assertEqual(len(lb["rows"]), len(pd.read_csv(self.inputs["leaderboard"])))
        for r in lb["rows"]:
            self.assertEqual(set(r), {"window", "model", "wape", "mae", "n", "coverage_own_band", "status",
                                      "source", "scored_split"})
        role = {r["window"]: r["scored_split"] for r in lb["rows"]}
        self.assertEqual(role, {"2022-H1": "rejected", "2023-H1": "development", "2023-H2": "test"})
        ins = [r for r in lb["rows"] if r["window"] == "2022-H1"]
        self.assertTrue(all(r["status"] == "insufficient history" and r["wape"] is None for r in ins))
        wins = {w["window"]: w for w in lb["windows"]}
        self.assertEqual(list(wins), ["2022-H1", "2022-H2", "2023-H1", "2023-H2"])
        self.assertIn("electrified is 1", wins["2022-H2"]["reason"])
        self.assertIsNone(wins["2023-H2"]["reason"])
        self.assertEqual(wins["2023-H2"]["role"], "test")

        st = self._json("caltrain_station_annual.json")
        self.assertIsInstance(st, list)
        self.assertEqual(len(st), 8)
        by = {r["fiscal_year"]: r for r in st}
        self.assertEqual((by[2019]["first_month"], by[2019]["last_month"], by[2019]["basis"]),
                         ("2019-02", "2019-02", "count"))
        self.assertEqual((by[2024]["first_month"], by[2024]["last_month"]), ("2023-11", "2024-06"))
        self.assertEqual((by[2026]["first_month"], by[2026]["last_month"]), ("2025-07", "2026-06"))
        self.assertTrue(all(isinstance(r["avg_midweek_boardings"], int) for r in st))
        self.assertNoStaging()

    def test_existing_bart_json_byte_identical(self):
        self._main()
        without = self._snapshot()
        self._main("--caltrain")
        with_flag = self._snapshot()
        self.assertEqual(sorted(without), sorted(BART_FILES))
        self.assertEqual({k: with_flag[k] for k in BART_FILES}, without)

    def test_forecast_refused_when_parquet_disagrees_with_leaderboard(self):
        path = self.inputs["forecasts_sarima"]
        df = pd.read_parquet(path)
        df.loc[df["window"] == "2023-H2", "p50"] *= 1.01
        df.to_parquet(path, index=False)
        before = self._snapshot()
        with self.assertRaises(SystemExit) as cm:
            self._main("--caltrain")
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(self._snapshot(), before)
        self.assertNoStaging()

    # ── opt-in ──────────────────────────────────────────────────────────────
    def test_export_refuses_when_caltrain_outputs_missing(self):
        for key in ("leaderboard", "windows", "forecasts_sarima", "forecasts_chronos1", "store", "stations"):
            with self.subTest(missing=key):
                path = self.inputs[key]
                saved = path.read_bytes()
                path.unlink()
                before = self._snapshot()
                try:
                    with self.assertRaises(SystemExit) as cm:
                        self._main("--caltrain")
                    self.assertEqual(cm.exception.code, 1)
                    self.assertEqual(self._snapshot(), before, "something was published")
                    self.assertNoStaging()
                finally:
                    path.write_bytes(saved)

    def test_default_export_ignores_caltrain(self):
        # Every Caltrain output missing, and a committed Caltrain file already published.
        for p in self.inputs["dir"].iterdir():
            p.unlink()
        self.inputs["store"].unlink()
        (self.out / "caltrain_series.json").write_text('"committed"')
        self._main()
        snap = self._snapshot()
        self.assertEqual(sorted(snap), sorted(BART_FILES + ["caltrain_series.json"]))
        self.assertEqual(snap["caltrain_series.json"], b'"committed"')
        for name in BART_FILES:
            self.assertNotIn(b"old", snap[name], name)
        self.assertNoStaging()


if __name__ == "__main__":
    unittest.main()
