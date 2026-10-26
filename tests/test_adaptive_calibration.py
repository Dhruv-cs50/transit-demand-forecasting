"""
tests/test_adaptive_calibration.py
──────────────────────────────────
Unit tests for the calibrations in evaluation/calibration.py that track recent
errors: the weighted conformal quantile, the rolling-origin pool fit, and
adaptive conformal inference (ACI) over monthly batches.

Run with the standard library, no pytest needed:
    python -m unittest tests.test_adaptive_calibration -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.calibration import (  # noqa: E402
    apply_conformal,
    clip_alpha,
    conformal_quantile,
    fit_aci_conformal,
    fit_conformal,
    fit_rolling_conformal,
    months_between,
    rolling_pool,
    weighted_conformal_quantile,
    with_origin_horizon,
)


def _origin_forecasts(origin: str, stations: list[str], rel_err: float,
                      rng: np.random.Generator, horizon: int = 6,
                      half: float = 0.05) -> pd.DataFrame:
    """One origin's 6-month forecasts: y = p50 * (1 + N(0, rel_err))."""
    o = pd.Timestamp(origin)
    ts = pd.date_range(o + pd.offsets.MonthBegin(1), periods=horizon, freq="MS")
    rows = [(t, s) for s in stations for t in ts]
    df = pd.DataFrame(rows, columns=["timestamp", "station_id"])
    df["p50"] = 10_000.0
    df["ridership"] = df["p50"] * (1 + rng.normal(0, rel_err, size=len(df)))
    df["p10"] = df["p50"] * (1 - half)
    df["p90"] = df["p50"] * (1 + half)
    return with_origin_horizon(df, o)


def _pool(origins_err: list[tuple[str, float]], n_stations: int = 20, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    stations = [f"S{i:02d}" for i in range(n_stations)]
    return pd.concat([_origin_forecasts(o, stations, e, rng) for o, e in origins_err],
                     ignore_index=True)


MONTH_ENDS = [str(d.date()) for d in pd.date_range("2023-12-31", "2024-11-30", freq="ME")]


class WeightedQuantileTest(unittest.TestCase):
    def test_unit_weights_match_split_conformal(self):
        rng = np.random.default_rng(1)
        for n in range(1, 40):
            s = rng.normal(size=n)
            for level in (0.5, 0.8, 0.9, 0.95):
                self.assertEqual(weighted_conformal_quantile(s, np.ones(n), level),
                                 conformal_quantile(s, level), (n, level))

    def test_weight_on_a_recent_large_score_raises_the_quantile(self):
        s = np.array([1.0, 2.0, 3.0, 4.0])
        # Equal weights: threshold 0.5 * (4 + 1) = 2.5 -> third score.
        self.assertEqual(weighted_conformal_quantile(s, np.ones(4), 0.5), 3.0)
        # Old scores nearly ignored: threshold 0.5 * (1.3 + 1) = 1.15 -> 4.
        self.assertEqual(weighted_conformal_quantile(s, np.array([0.1, 0.1, 0.1, 1.0]), 0.5), 4.0)

    def test_too_little_weight_is_infinite(self):
        # threshold 0.8 * (2 + 1) = 2.4 > total weight 2.
        self.assertEqual(weighted_conformal_quantile(np.array([1.0, 2.0]), np.ones(2), 0.8), np.inf)

    def test_alpha_clipped_to_total_weight_keeps_a_weighted_quantile_finite(self):
        rng = np.random.default_rng(7)
        for n in (5, 50, 2850):
            s = rng.normal(size=n)
            w = 0.5 ** (rng.integers(0, 12, size=n) / 6)
            a = clip_alpha(1e-6, w.sum())
            self.assertTrue(np.isfinite(weighted_conformal_quantile(s, w, 1 - a)), n)
            # Clipped to the row count instead, the quantile is infinite.
            self.assertEqual(weighted_conformal_quantile(s, w, n / (n + 1)), np.inf)

    def test_order_of_input_does_not_matter(self):
        s = np.array([4.0, 1.0, 3.0, 2.0])
        w = np.array([1.0, 0.1, 0.1, 0.1])
        self.assertEqual(weighted_conformal_quantile(s, w, 0.5), 4.0)


class OriginTermsTest(unittest.TestCase):
    def test_months_between_counts_calendar_months(self):
        self.assertEqual(months_between(pd.Timestamp("2024-11-30"), pd.Timestamp("2024-12-01")), 1)
        self.assertEqual(months_between(pd.Timestamp("2024-12-01"), pd.Timestamp("2024-12-31")), 0)
        self.assertEqual(months_between(pd.Timestamp("2023-12-31"), pd.Timestamp("2024-06-01")), 6)

    def test_horizon_is_months_from_origin_not_rank(self):
        df = _origin_forecasts("2024-03-31", ["A"], 0.05, np.random.default_rng(0))
        df = df[df["timestamp"] != pd.Timestamp("2024-04-01")]   # first month missing
        df = with_origin_horizon(df, pd.Timestamp("2024-03-31"))
        self.assertEqual(df["horizon"].tolist(), [2, 3, 4, 5, 6])


class RollingPoolTest(unittest.TestCase):
    def test_pool_keeps_only_resolved_rows_from_earlier_origins(self):
        pool = _pool([(o, 0.05) for o in MONTH_ENDS])
        cut = rolling_pool(pool, pd.Timestamp("2024-06-30"))
        self.assertLessEqual(cut["timestamp"].max(), pd.Timestamp("2024-06-30"))
        self.assertLess(cut["origin"].max(), pd.Timestamp("2024-06-30"))
        # 6 origins (2023-12 .. 2024-05) resolving 6+5+4+3+2+1 months, 20 stations.
        self.assertEqual(len(cut), 21 * 20)
        self.assertEqual(sorted(cut["age"].unique().tolist()), [0, 1, 2, 3, 4, 5])

    def test_rows_after_as_of_do_not_move_the_quantile(self):
        pool = _pool([(o, 0.05) for o in MONTH_ENDS])
        as_of = pd.Timestamp("2024-06-30")
        base = fit_rolling_conformal(pool, "relative", "pooled", 0.8, as_of, half_life=6)
        later = pool["timestamp"] > as_of
        pool.loc[later, "ridership"] *= 3.0
        again = fit_rolling_conformal(pool, "relative", "pooled", 0.8, as_of, half_life=6)
        self.assertEqual(base["q"], again["q"])

    def test_missing_horizon_column_raises(self):
        pool = _pool([(o, 0.05) for o in MONTH_ENDS[:3]]).drop(columns="horizon")
        with self.assertRaises(ValueError):
            fit_rolling_conformal(pool, "scaled", "horizon", 0.8, pd.Timestamp("2024-06-30"))
        with self.assertRaises(ValueError):
            fit_rolling_conformal(pool, "scaled", "pooled", 0.8, pd.Timestamp("2024-06-30"))

    def test_horizon_inconsistent_with_origin_raises(self):
        pool = _pool([(o, 0.05) for o in MONTH_ENDS[:3]])
        pool.loc[pool.index[0], "horizon"] = 4
        with self.assertRaises(ValueError):
            fit_rolling_conformal(pool, "scaled", "horizon", 0.8, pd.Timestamp("2024-06-30"))

    def test_equal_weights_match_split_conformal_on_the_same_rows(self):
        pool = _pool([(o, 0.05) for o in MONTH_ENDS])
        as_of = pd.Timestamp("2024-12-31")
        resolved = rolling_pool(pool, as_of)
        for method in ("scaled", "relative", "asym_relative"):
            for group in ("pooled", "horizon"):
                rolled = fit_rolling_conformal(pool, method, group, 0.8, as_of, half_life=None)
                split = fit_conformal(resolved, method, group, 0.8)
                self.assertEqual(rolled["q"], split["q"], (method, group))

    def test_horizon_groups_use_the_explicit_horizon(self):
        pool = _pool([(o, 0.05) for o in MONTH_ENDS])
        cal = fit_rolling_conformal(pool, "relative", "horizon", 0.8, pd.Timestamp("2024-12-31"))
        self.assertEqual(sorted(cal["q"]), [1, 2, 3, 4, 5, 6])
        self.assertEqual(cal["n_by_group"], {1: 240, 2: 220, 3: 200, 4: 180, 5: 160, 6: 140})

    def test_recency_weights_follow_recent_errors(self):
        # Errors double for the last four target months before as_of.
        pool = _pool([(o, 0.03) for o in MONTH_ENDS])
        recent = pool["timestamp"] >= pd.Timestamp("2024-09-01")
        rng = np.random.default_rng(5)
        pool.loc[recent, "ridership"] = pool.loc[recent, "p50"] * (1 + rng.normal(0, 0.12, recent.sum()))
        as_of = pd.Timestamp("2024-12-31")
        equal = fit_rolling_conformal(pool, "relative", "pooled", 0.8, as_of, half_life=None)
        hl6 = fit_rolling_conformal(pool, "relative", "pooled", 0.8, as_of, half_life=6)
        self.assertGreater(hl6["q"]["all"], equal["q"]["all"])

    def test_incomplete_pool_row_raises(self):
        pool = _pool([(o, 0.05) for o in MONTH_ENDS[:3]])
        pool.loc[pool.index[0], "p90"] = np.nan
        with self.assertRaises(ValueError):
            fit_rolling_conformal(pool, "scaled", "pooled", 0.8, pd.Timestamp("2024-06-30"))

    def test_applying_a_rolling_calibrator_never_moves_p50(self):
        pool = _pool([(o, 0.05) for o in MONTH_ENDS])
        cal = fit_rolling_conformal(pool, "scaled", "horizon", 0.8, pd.Timestamp("2024-12-31"), half_life=6)
        target = _origin_forecasts("2024-12-31", ["A", "B"], 0.05, np.random.default_rng(9))
        out = apply_conformal(target, cal)
        pd.testing.assert_series_equal(out["p50"], target["p50"])
        self.assertTrue((out["p10"] <= out["p50"]).all() and (out["p50"] <= out["p90"]).all())


class ACITest(unittest.TestCase):
    def _three_months(self) -> pd.DataFrame:
        """Ten stations, one origin per month, horizon 1: relative scores 0.1, 0.5, 0.5."""
        rows = []
        for origin, ts, err in [("2023-12-31", "2024-01-01", 0.1),
                                ("2024-01-31", "2024-02-01", 0.5),
                                ("2024-02-29", "2024-03-01", 0.5)]:
            for i in range(10):
                rows.append({"timestamp": pd.Timestamp(ts), "station_id": f"S{i}",
                             "origin": pd.Timestamp(origin), "p50": 100.0,
                             "ridership": 100.0 * (1 + err), "p10": 90.0, "p90": 110.0})
        return with_origin_horizon(pd.DataFrame(rows))

    def test_recursion_by_hand(self):
        cal = fit_aci_conformal(self._three_months(), "relative", 0.8, pd.Timestamp("2024-03-31"), gamma=0.1)
        # Feb: pool = Jan (ten 0.1), alpha 0.2 -> q 0.1; Feb's 0.5s all miss -> alpha 0.2 + 0.1*(0.2-1) = 0.12.
        # Mar: pool = Jan+Feb (n 20), level 0.88 -> k = ceil(21*0.88) = 19 -> q 0.5; no miss -> 0.14.
        # Final: n 30, level 0.86 -> k = ceil(31*0.86) = 27 -> q 0.5.
        np.testing.assert_allclose(cal["alpha_path"], [0.2, 0.12, 0.14])
        self.assertAlmostEqual(cal["alpha_final"], 0.14)
        self.assertAlmostEqual(cal["q"]["all"], 0.5)
        self.assertEqual(cal["group"], "pooled")

    def test_alpha_is_clipped_so_the_quantile_stays_finite(self):
        # Every batch misses badly: alpha would go negative without the clip.
        rng = np.random.default_rng(3)
        stations = [f"S{i:02d}" for i in range(5)]
        pool = pd.concat([_origin_forecasts(o, stations, 0.02 * (k + 1) ** 2, rng)
                          for k, o in enumerate(MONTH_ENDS)], ignore_index=True)
        cal = fit_aci_conformal(pool, "relative", 0.8, pd.Timestamp("2024-12-31"), gamma=0.1)
        self.assertTrue(np.isfinite(cal["q"]["all"]))
        self.assertTrue(all(0 < a <= 0.5 for a in cal["alpha_path"]))

    def test_asymmetric_runs_one_alpha_per_tail(self):
        pool = self._three_months()
        cal = fit_aci_conformal(pool, "asym_relative", 0.8, pd.Timestamp("2024-03-31"), gamma=0.1)
        q_lo, q_hi = cal["q"]["all"]
        self.assertLessEqual(q_lo, q_hi)
        a_lo, a_hi = cal["alpha_final"]
        # All errors are positive, so only the upper tail misses: its alpha falls, the lower one rises.
        self.assertLess(a_hi, 0.1)
        self.assertGreater(a_lo, 0.1)

    def test_rows_after_as_of_are_ignored(self):
        pool = _pool([(o, 0.05) for o in MONTH_ENDS])
        as_of = pd.Timestamp("2024-06-30")
        a = fit_aci_conformal(pool, "scaled", 0.8, as_of)
        pool.loc[pool["timestamp"] > as_of, "ridership"] *= 2
        b = fit_aci_conformal(pool, "scaled", 0.8, as_of)
        self.assertEqual(a["q"], b["q"])
        self.assertEqual(a["alpha_path"], b["alpha_path"])


if __name__ == "__main__":
    unittest.main()
