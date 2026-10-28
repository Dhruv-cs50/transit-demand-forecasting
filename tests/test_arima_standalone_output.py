"""
tests/test_arima_standalone_output.py
─────────────────────────────────────
R12: `python models/baselines/arima.py` (default cutoff = train_end) must not
write to the path benchmarks.py fills with Jul-Dec 2025 test forecasts. Only the
standalone CLI path moves; run_arima_all_stations keeps its default output_dir,
which is what benchmarks.py relies on.

    python -m pytest tests/test_arima_standalone_output.py -q
"""

from __future__ import annotations

import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models.baselines import arima  # noqa: E402

BENCHMARK_FILE = arima.OUTPUT_DIR / "arima_forecasts.parquet"
EXPORT_SCRIPT = (ROOT / "scripts" / "export_website_data.py").read_text()


class StandaloneOutputPath(unittest.TestCase):
    def test_benchmark_default_is_unchanged(self):
        default = inspect.signature(arima.run_arima_all_stations).parameters["output_dir"].default
        self.assertEqual(default, arima.OUTPUT_DIR)
        self.assertEqual(arima.OUTPUT_DIR, Path("models/baselines/outputs/arima"))
        # The website export reads the benchmark's file at this exact path.
        self.assertIn(str(BENCHMARK_FILE), EXPORT_SCRIPT)

    def test_standalone_default_differs_from_benchmark_path(self):
        standalone_file = arima.STANDALONE_OUTPUT_DIR / "arima_forecasts.parquet"
        self.assertNotEqual(standalone_file, BENCHMARK_FILE)
        self.assertNotEqual(arima.STANDALONE_OUTPUT_DIR, arima.OUTPUT_DIR)

    def test_main_passes_standalone_dir_to_the_pipeline(self):
        store = pd.DataFrame({
            "station_id": ["EM"] * 3,
            "timestamp": pd.to_datetime(["2022-01-01", "2022-02-01", "2022-03-01"]),
            "ridership": [1.0, 2.0, 3.0],
        })
        with tempfile.TemporaryDirectory() as tmp:
            store.to_parquet(Path(tmp) / "feature_store.parquet")
            with mock.patch.object(arima, "PROCESSED_DIR", Path(tmp)), \
                 mock.patch.object(arima, "load_config", return_value={"data": {}}), \
                 mock.patch.object(arima, "run_arima_all_stations") as run, \
                 mock.patch.object(sys, "argv", ["arima.py"]):
                arima.main()
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["output_dir"], arima.STANDALONE_OUTPUT_DIR)
        self.assertNotEqual(run.call_args.kwargs["output_dir"], arima.OUTPUT_DIR)


if __name__ == "__main__":
    unittest.main()
