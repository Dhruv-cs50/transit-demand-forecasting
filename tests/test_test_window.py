"""
tests/test_test_window.py
─────────────────────────
The test split has an end (S7-09b): val_end < ts <= data.test_end. A month
added to the feature store after test_end (the nightly pipeline appends one)
must not enter the test split, and a config without test_end must fail
rather than fall back to "everything after val_end".

    python -m pytest tests/test_test_window.py -q
"""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from machine_learning_files import merge_pipeline  # noqa: E402
from models.baselines import benchmarks  # noqa: E402
from models.baselines.benchmarks import config_test_end, select_test_window  # noqa: E402

TEST_MONTHS = list(pd.date_range("2025-07-01", "2025-12-01", freq="MS"))


def _repo_config() -> dict:
    with open(ROOT / "configs" / "model.yaml") as f:
        return yaml.safe_load(f)


def _store(tz: str | None = None) -> pd.DataFrame:
    """Three stations, monthly Jan 2022 - Dec 2025, as the tracked store ends."""
    ts = pd.date_range("2022-01-01", "2025-12-01", freq="MS", tz=tz)
    frames = [pd.DataFrame({"timestamp": ts, "station_id": sid,
                            "ridership": 1000.0 * (i + 1) + np.arange(len(ts), dtype=float)})
              for i, sid in enumerate(["S0", "S1", "S2"])]
    return pd.concat(frames, ignore_index=True)


def _with_2026_month(store: pd.DataFrame) -> pd.DataFrame:
    """The store plus a January 2026 row for every station."""
    dec = store[store["timestamp"].dt.month.eq(12) & store["timestamp"].dt.year.eq(2025)].copy()
    dec["timestamp"] = dec["timestamp"] + pd.DateOffset(months=1)
    dec["ridership"] = 99_999.0
    return pd.concat([store, dec], ignore_index=True)


def _rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(["station_id", "timestamp"]).reset_index(drop=True)


class _Stop(Exception):
    """Raised by a stand-in model to end run_benchmarks right after the split."""


class RepoConfigTest(unittest.TestCase):
    def test_the_repo_config_ends_the_test_window_in_december_2025(self):
        data = _repo_config()["data"]
        self.assertEqual(data["test_end"], "2025-12-31")
        # Six months, the forecast horizon every model is scored over.
        months = pd.date_range(pd.Timestamp(data["val_end"]) + pd.Timedelta(days=1),
                               pd.Timestamp(data["test_end"]), freq="MS")
        self.assertEqual(len(months), int(data["forecast_horizon_steps"]))


class SelectTestWindowTest(unittest.TestCase):
    def test_a_2026_month_does_not_change_the_test_rows(self):
        cfg = _repo_config()
        store = _store()
        before = _rows(select_test_window(store, cfg))
        after = _rows(select_test_window(_with_2026_month(store), cfg))
        pd.testing.assert_frame_equal(after, before)
        self.assertEqual(sorted(before["timestamp"].unique()), TEST_MONTHS)
        self.assertEqual(len(before), 6 * 3)

    def test_a_tz_aware_store_is_bounded_the_same_way(self):
        cfg = _repo_config()
        store = _store(tz="America/Los_Angeles")
        before = _rows(select_test_window(store, cfg))
        after = _rows(select_test_window(_with_2026_month(store), cfg))
        pd.testing.assert_frame_equal(after, before)
        self.assertEqual([t.tz_localize(None) for t in sorted(before["timestamp"].unique())],
                         TEST_MONTHS)

    def test_missing_test_end_raises(self):
        cfg = _repo_config()
        del cfg["data"]["test_end"]
        with self.assertRaisesRegex(ValueError, "test_end is missing"):
            select_test_window(_store(), cfg)
        with self.assertRaisesRegex(ValueError, "test_end is missing"):
            config_test_end(cfg)

    def test_empty_test_end_raises(self):
        cfg = _repo_config()
        cfg["data"]["test_end"] = ""
        with self.assertRaisesRegex(ValueError, "test_end is missing"):
            config_test_end(cfg)

    def test_test_end_not_after_val_end_raises(self):
        cfg = _repo_config()
        cfg["data"]["test_end"] = cfg["data"]["val_end"]
        with self.assertRaisesRegex(ValueError, "must be after data.val_end"):
            select_test_window(_store(), cfg)


class RunBenchmarksTestSplitTest(unittest.TestCase):
    """run_benchmarks scores the bounded window, and checks test_end first."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "outputs"
        self.calibrators = Path(self.tmp.name) / "calibrators"

    def tearDown(self):
        self.tmp.cleanup()

    def _test_df_seen_by_first_model(self, store: pd.DataFrame, cfg: dict) -> pd.DataFrame:
        seen = {}

        def stand_in(train_df, test_df, freq):
            seen["test_df"] = test_df.copy()
            raise _Stop

        with mock.patch.multiple(benchmarks, EVAL_DIR=self.out, CALIBRATOR_DIR=self.calibrators,
                                 seasonal_naive_forecast=stand_in):
            with self.assertRaises(_Stop):
                benchmarks.run_benchmarks(store, cfg, quick=True)
        return _rows(seen["test_df"])

    def test_a_2026_month_does_not_reach_the_scored_test_split(self):
        cfg = _repo_config()
        store = _store()
        before = self._test_df_seen_by_first_model(store, cfg)
        after = self._test_df_seen_by_first_model(_with_2026_month(store), cfg)
        pd.testing.assert_frame_equal(after, before)
        self.assertEqual(sorted(before["timestamp"].unique()), TEST_MONTHS)

    def test_missing_test_end_raises_before_any_calibrator_is_removed(self):
        self.calibrators.mkdir(parents=True)
        (self.calibrators / "SARIMA.json").write_text("{}")
        cfg = _repo_config()
        del cfg["data"]["test_end"]
        with mock.patch.multiple(benchmarks, EVAL_DIR=self.out, CALIBRATOR_DIR=self.calibrators):
            with self.assertRaisesRegex(ValueError, "test_end is missing"):
                benchmarks.run_benchmarks(_store(), cfg, quick=True)
        self.assertTrue((self.calibrators / "SARIMA.json").exists())


class MakeSplitsTest(unittest.TestCase):
    """splits/test.parquet (read by Processing/ablation.py and
    evaluation/metrics.py) is bounded the same way."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.processed = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _test_split(self, store: pd.DataFrame, data: dict) -> pd.DataFrame:
        with mock.patch.object(merge_pipeline, "PROCESSED_DIR", self.processed):
            merge_pipeline.make_splits(store, train_end=data["train_end"], val_end=data["val_end"],
                                       train_start=data.get("train_start"),
                                       test_end=data.get("test_end"))
        return _rows(pd.read_parquet(self.processed / "splits" / "test.parquet"))

    def test_a_2026_month_does_not_enter_the_test_split_file(self):
        data = _repo_config()["data"]
        store = _store()
        before = self._test_split(store, data)
        after = self._test_split(_with_2026_month(store), data)
        pd.testing.assert_frame_equal(after, before)
        self.assertEqual(sorted(before["timestamp"].unique()), TEST_MONTHS)

    def test_missing_test_end_raises(self):
        data = copy.deepcopy(_repo_config()["data"])
        del data["test_end"]
        with self.assertRaisesRegex(ValueError, "test_end is missing"):
            self._test_split(_store(), data)
        self.assertFalse((self.processed / "splits").exists())


if __name__ == "__main__":
    unittest.main()
