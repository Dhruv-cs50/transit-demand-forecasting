"""
tests/test_interval_test_breakdown.py
─────────────────────────────────────
Unit tests for the pure helpers of scripts/interval_test_breakdown.py, on
synthetic pools only: fit_band (which calibrator a configs/model.yaml entry
deploys) and by_group (per-horizon values for the output). main() reads the
test split and is never called here.

Run with the standard library, no pytest needed:
    python -m unittest tests.test_interval_test_breakdown -v
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from evaluation.calibration import (  # noqa: E402
    fit_rolling_conformal, fit_shift_conformal, with_origin_horizon,
)
from evaluation.interval_study import chronos_label, month_ends  # noqa: E402

# scripts/ is not a package; load the script as a module (main() is not run).
_spec = importlib.util.spec_from_file_location("interval_test_breakdown",
                                               REPO / "scripts" / "interval_test_breakdown.py")
itb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(itb)

AS_OF = pd.Timestamp("2025-06-30")
SHIFT = {"method": "shift_relative", "group": "horizon", "scheme": "rolling", "half_life": 6,
         "bias_half_life": 1, "bias_at": "as_of", "first_origin": "2023-12-31"}
ROLLING = {"method": "relative", "group": "pooled", "scheme": "rolling", "half_life": 6,
           "first_origin": "2023-12-31"}


def _pool(n_stations: int = 10, seed: int = 0) -> pd.DataFrame:
    """Forecasts from monthly origins 2023-12-31 .. 2025-05-31 whose bias grows
    with the origin and the horizon, so the bias and width half-lives give
    different calibrators (a swapped argument would show)."""
    rng = np.random.default_rng(seed)
    parts = []
    for i, o in enumerate(month_ends(pd.Timestamp("2023-12-31"), AS_OF - pd.offsets.MonthEnd(1))):
        ts = pd.date_range(o + pd.offsets.MonthBegin(1), periods=6, freq="MS")
        df = pd.DataFrame([(t, f"S{s:02d}") for s in range(n_stations) for t in ts],
                          columns=["timestamp", "station_id"])
        df["p50"] = 10_000.0
        df["p10"], df["p90"] = 9_500.0, 10_500.0
        h = np.tile(np.arange(1, 7), n_stations)
        df["ridership"] = df["p50"] * (1 + 0.01 * i + 0.005 * h + rng.normal(0, 0.03, len(df)))
        parts.append(with_origin_horizon(df, o))
    return pd.concat(parts, ignore_index=True)


class FitBand(unittest.TestCase):
    def setUp(self):
        self.pool = _pool()

    def test_shift_relative_entry_is_fit_shift_conformal_with_its_settings(self):
        got = itb.fit_band(self.pool, SHIFT, AS_OF)
        want = fit_shift_conformal(self.pool, "horizon", 0.8, AS_OF, bias_half_life=1, half_life=6,
                                   bias_at="as_of")
        self.assertEqual(got, want)
        self.assertEqual(got["scheme"], "shift")
        self.assertEqual(sorted(got["bias"]), [1, 2, 3, 4, 5, 6])

    def test_the_test_pool_tells_the_half_lives_apart(self):
        # Guards the test above: with the half-lives swapped the calibrator differs.
        swapped = fit_shift_conformal(self.pool, "horizon", 0.8, AS_OF, bias_half_life=6, half_life=1,
                                      bias_at="as_of")
        self.assertNotEqual(itb.fit_band(self.pool, SHIFT, AS_OF)["q"], swapped["q"])

    def test_other_rolling_entry_is_fit_rolling_conformal_unchanged(self):
        got = itb.fit_band(self.pool, ROLLING, AS_OF)
        want = fit_rolling_conformal(self.pool, "relative", "pooled", 0.8, AS_OF, half_life=6)
        self.assertEqual(got, want)
        self.assertEqual(got["scheme"], "rolling")

    def test_repo_config_routes_each_model(self):
        cfg = yaml.safe_load((REPO / "configs" / "model.yaml").read_text())
        models = cfg["calibration"]["models"]
        self.assertEqual(itb.fit_band(self.pool, models["Chronos"], AS_OF)["scheme"], "shift")
        for key in ("SeasonalNaive", "Prophet"):
            calib = itb.fit_band(self.pool, models[key], AS_OF)
            self.assertEqual(calib, fit_rolling_conformal(self.pool, models[key]["method"], models[key]["group"],
                                                          0.8, AS_OF, half_life=models[key]["half_life"]))

    def test_previous_band_is_keyed_by_the_configured_chronos_label(self):
        cfg = yaml.safe_load((REPO / "configs" / "model.yaml").read_text())
        self.assertIn(chronos_label(cfg), itb.PREVIOUS)


class ByGroup(unittest.TestCase):
    def test_sorted_by_group_and_rounded_to_4dp(self):
        got = itb.by_group({3: np.float64(0.123456), 1: 0.10004999, 2: -0.03456789})
        self.assertEqual(list(got), [1, 2, 3])
        self.assertEqual(got, {1: 0.1, 2: -0.0346, 3: 0.1235})
        self.assertTrue(all(type(v) is float for v in got.values()))
        # yaml.safe_dump must represent it (it refuses numpy scalars).
        yaml.safe_dump(got)


if __name__ == "__main__":
    unittest.main()
