"""
tests/test_export_all_or_nothing.py
───────────────────────────────────
scripts/export_website_data.py publishes its six website/data/*.json files all
or none: they are staged first and moved into the output directory only when
every one was produced. A failure anywhere (a refused forecasts.json, an
exception in any exporter, a move that fails midway) leaves the output
directory byte-for-byte as it was, with no staging directory left behind.

The exporters are replaced by stubs that write small files; what is under test
is main()'s staging and publishing, not the numbers.

    python -m unittest tests.test_export_all_or_nothing -v
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location("export_website_data", REPO / "scripts" / "export_website_data.py")
ewd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ewd)
logging.getLogger("export_website_data").setLevel(logging.CRITICAL)

FILES = ["forecasts.json", "forecasts_sarima.json", "model_comparison.json", "ridership_actuals.json",
         "stations_meta.json", "stations_ridership.json"]


class AllOrNothing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = Path(self.tmp.name) / "website"
        self.out = self.site / "data"
        self.out.mkdir(parents=True)
        for name in FILES:
            (self.out / name).write_text(f'"old {name}"')
        self.before = self._snapshot()

    def _snapshot(self):
        return {p.name: p.read_bytes() for p in self.out.iterdir()}

    def _stub_exporters(self, forecasts=None, comparison=None):
        """Patch everything main() calls so only the staging logic is real."""
        def write(name):
            def fn(*a):
                # export_ridership_actuals(df, out_dir) / export_model_comparison(out_dir)
                a[-1].joinpath(name).write_text(f'"new {name}"')
            return fn

        def fake_forecasts(out_dir, df):
            if forecasts:
                return forecasts
            (out_dir / "forecasts.json").write_text('"new forecasts.json"')
            return None

        patches = mock.patch.multiple(
            ewd,
            load_feature_store=lambda path: pd.DataFrame({"x": [1]}),
            check_station_ids=lambda df: None,
            compute_station_ridership=lambda df: pd.DataFrame(
                {"avg_monthly_ridership": [1.0]}),
            check_station_averages=lambda agg: None,
            require_leaderboard=lambda: None,
            build_ridership_json=lambda agg: {"a": 1},
            build_meta_json=lambda agg: [{"a": 1}],
            export_ridership_actuals=write("ridership_actuals.json"),
            export_forecasts=fake_forecasts,
            export_sarima_forecasts=lambda out_dir, df: (
                out_dir.joinpath("forecasts_sarima.json").write_text('"new forecasts_sarima.json"') and None),
            export_model_comparison=comparison or write("model_comparison.json"),
        )
        patches.start()
        self.addCleanup(patches.stop)

    def _main(self):
        with mock.patch.object(sys, "argv", ["export", "--out-dir", str(self.out)]):
            ewd.main()

    def assertUntouched(self):
        self.assertEqual(self._snapshot(), self.before)
        self.assertEqual(sorted(p.name for p in self.site.iterdir()), ["data"],
                         "a staging directory was left behind")

    def test_success_replaces_all_six_files(self):
        self._stub_exporters()
        self._main()
        self.assertEqual(sorted(self._snapshot()), FILES)
        for name, data in self._snapshot().items():
            self.assertNotIn(b"old", data, name)
        self.assertEqual(sorted(p.name for p in self.site.iterdir()), ["data"])

    def test_refused_forecasts_publish_nothing(self):
        self._stub_exporters(forecasts="calibrator missing")
        with self.assertRaises(SystemExit) as cm:
            self._main()
        self.assertEqual(cm.exception.code, 1)
        self.assertUntouched()

    def test_exporter_failing_midway_publishes_nothing(self):
        def boom(*a):
            raise RuntimeError("model_comparison exploded")
        self._stub_exporters(comparison=boom)
        with self.assertRaises(RuntimeError):
            self._main()
        self.assertUntouched()

    def test_failed_move_midway_restores_every_file(self):
        self._stub_exporters()
        real = os.replace
        calls = []

        def flaky(src, dst, *a, **k):
            # Fail on the third promotion into the output dir (not the
            # backup restores, which move the other way).
            if Path(dst).parent == self.out:
                calls.append(dst)
                if len(calls) == 3:
                    raise OSError("disk full")
            return real(src, dst, *a, **k)

        with mock.patch.object(ewd.os, "replace", flaky):
            with self.assertRaises(OSError):
                self._main()
        self.assertGreaterEqual(len(calls), 3)
        self.assertUntouched()

    def test_first_publish_into_empty_dir_rolls_back_to_empty(self):
        for p in list(self.out.iterdir()):
            p.unlink()
        self.before = {}
        self._stub_exporters()
        real = os.replace
        n = []

        def flaky(src, dst, *a, **k):
            if Path(dst).parent == self.out:
                n.append(dst)
                if len(n) == 2:
                    raise OSError("disk full")
            return real(src, dst, *a, **k)

        with mock.patch.object(ewd.os, "replace", flaky):
            with self.assertRaises(OSError):
                self._main()
        self.assertUntouched()


if __name__ == "__main__":
    unittest.main()
