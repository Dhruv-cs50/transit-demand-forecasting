"""
tests/test_shift_calibration.py
───────────────────────────────
Unit tests for the Sprint 6 bias-shifted band in evaluation/calibration.py:
the lower weighted median, and fit_shift_conformal with the bias estimated at
the band's origin T (bias_at="as_of") or at each pool row's own forecast
origin (bias_at="origin").

Offsets are dyadic (0.125, h/16, ...) wherever a test checks exact equality,
so r = (y - p50) / p50 is exact in floating point.

Run with the standard library, no pytest needed:
    python -m unittest tests.test_shift_calibration -v
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
    describe,
    fit_shift_conformal,
    rolling_pool,
    weighted_conformal_quantile,
    weighted_median,
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


def _with_offset(pool: pd.DataFrame, offset) -> pd.DataFrame:
    """Every actual set to p50 * (1 + offset); offset is a scalar or one value per row."""
    out = pool.copy()
    out["ridership"] = out["p50"] * (1 + offset)
    return out


MONTH_ENDS = [str(d.date()) for d in pd.date_range("2023-12-31", "2024-11-30", freq="ME")]
T_B = pd.Timestamp("2024-06-30")   # window B's origin
T_V = pd.Timestamp("2024-12-31")   # window V's origin


class WeightedMedianTest(unittest.TestCase):
    def test_unit_weights_odd_count_is_the_middle_value(self):
        self.assertEqual(weighted_median([5.0, 1.0, 3.0], np.ones(3)), 3.0)

    def test_unit_weights_even_count_is_the_lower_middle_value(self):
        self.assertEqual(weighted_median([4.0, 1.0, 3.0, 2.0], np.ones(4)), 2.0)

    def test_a_heavy_weight_dominates(self):
        self.assertEqual(weighted_median([1.0, 2.0, 3.0], [1.0, 1.0, 10.0]), 3.0)
        self.assertEqual(weighted_median([1.0, 2.0, 3.0], [10.0, 1.0, 1.0]), 1.0)

    def test_cumulative_weight_exactly_half_picks_that_value(self):
        # Total 8, half 4: cumulative 1, 4, 8 -> the second value reaches 4 exactly.
        self.assertEqual(weighted_median([10.0, 20.0, 30.0], [1.0, 3.0, 4.0]), 20.0)
        # Cumulative 3 == 0.5 * 6 already at the smaller value.
        self.assertEqual(weighted_median([2.0, 1.0], [3.0, 3.0]), 1.0)

    def test_empty_is_nan(self):
        self.assertTrue(np.isnan(weighted_median([], [])))
        self.assertTrue(np.isnan(weighted_median(np.array([]), np.array([]))))

    def test_returns_a_python_float(self):
        self.assertIs(type(weighted_median(np.array([1, 2, 3]), np.ones(3))), float)

    def test_order_of_input_does_not_matter(self):
        # Many tied values with non-dyadic weights, so the order in which tied
        # weights are summed could matter if the implementation let it.
        rng = np.random.default_rng(11)
        for n in (2, 7, 41, 400):
            v = rng.choice([-0.1, 0.0, 0.1, 0.2, 0.3], size=n)
            w = rng.choice([0.1, 0.3, 0.7], size=n)
            base = weighted_median(v, w)
            for _ in range(200):
                p = rng.permutation(n)
                self.assertEqual(weighted_median(v[p], w[p]), base, n)


class ShiftAtAsOfTest(unittest.TestCase):
    """bias_at="as_of": one bias per group, estimated at the band's origin T."""

    def test_constant_error_gives_that_bias_and_zero_width(self):
        c = 0.25
        pool = _with_offset(_pool([(o, 0.05) for o in MONTH_ENDS]), c)
        cal = fit_shift_conformal(pool, "pooled", 0.8, T_V, bias_half_life=1, half_life=6)
        self.assertEqual(cal["bias"], {"all": c})
        self.assertEqual(cal["width"], {"all": 0.0})
        self.assertEqual(cal["q"], {"all": (c, c)})
        self.assertEqual(cal["clipped_groups"], ["all"])
        n = len(rolling_pool(pool, T_V))
        self.assertEqual((cal["n"], cal["n_by_group"], cal["n_no_bias"]), (n, {"all": n}, 0))
        for key, value in [("method", "asym_relative"), ("group", "pooled"), ("level", 0.8),
                           ("scheme", "shift"), ("bias_at", "as_of"), ("bias_half_life", 1),
                           ("half_life", 6), ("as_of", "2024-12-31")]:
            self.assertEqual(cal[key], value, key)

        # Applied: P10 = P50 * 1.25 is above P50, so the ordering clip sets it to P50.
        target = _origin_forecasts("2024-12-31", ["A", "B"], 0.05, np.random.default_rng(9))
        out = apply_conformal(target, cal)
        np.testing.assert_array_equal(out["p10"].to_numpy(), target["p50"].to_numpy())
        np.testing.assert_array_equal(out["p90"].to_numpy(), target["p50"].to_numpy() * (1 + c))

    def test_constant_negative_error_clips_the_upper_bound(self):
        c = -0.25
        pool = _with_offset(_pool([(o, 0.05) for o in MONTH_ENDS]), c)
        cal = fit_shift_conformal(pool, "pooled", 0.8, T_V, bias_half_life=3, half_life=6)
        self.assertEqual(cal["q"], {"all": (c, c)})
        self.assertEqual(cal["clipped_groups"], ["all"])
        target = _origin_forecasts("2024-12-31", ["A", "B"], 0.05, np.random.default_rng(9))
        out = apply_conformal(target, cal)
        np.testing.assert_array_equal(out["p90"].to_numpy(), target["p50"].to_numpy())
        np.testing.assert_array_equal(out["p10"].to_numpy(), target["p50"].to_numpy() * (1 + c))

    def test_pooled_matches_a_direct_computation(self):
        pool = _pool([(o, 0.06) for o in MONTH_ENDS], n_stations=5, seed=4)
        pool["ridership"] = pool["ridership"] * 1.03
        df = rolling_pool(pool, T_V)
        r = ((df["ridership"] - df["p50"]) / df["p50"]).to_numpy()
        age = df["age"].to_numpy(dtype=float)
        for hb, hl in [(1, 6), (3, 6), (3, None)]:
            cal = fit_shift_conformal(pool, "pooled", 0.8, T_V, bias_half_life=hb, half_life=hl)
            m = weighted_median(r, 0.5 ** (age / hb))
            ww = np.ones(len(r)) if hl is None else 0.5 ** (age / hl)
            w = weighted_conformal_quantile(np.abs(r - m), ww, 0.8)
            self.assertTrue(np.isfinite(w) and w > abs(m), (hb, hl))
            self.assertEqual(cal["bias"], {"all": m}, (hb, hl))
            self.assertEqual(cal["width"], {"all": w}, (hb, hl))
            self.assertEqual(cal["q"], {"all": (m - w, m + w)}, (hb, hl))
            self.assertEqual(cal["weight_sum"], float(ww.sum()), (hb, hl))
            self.assertEqual(cal["clipped_groups"], [], (hb, hl))
            self.assertTrue(all(type(v) is float for v in cal["q"]["all"]))

    def test_recent_errors_set_the_bias_under_a_short_bias_half_life(self):
        c = 0.125
        pool = _pool([(o, 0.05) for o in MONTH_ENDS[:6]])
        recent = (pool["timestamp"] == pd.Timestamp("2024-06-01")).to_numpy()
        pool = _with_offset(pool, np.where(recent, c, -c))
        df = rolling_pool(pool, T_B)
        is_recent = (df["age"] == 0).to_numpy()
        # Many old rows at -c, fewer recent ones at +c (120 of 420) ...
        self.assertLess(is_recent.sum(), (~is_recent).sum())
        # ... but with a 1-month half-life the recent ones carry over half the weight.
        w1 = 0.5 ** df["age"].to_numpy(dtype=float)
        self.assertGreaterEqual(w1[is_recent].sum(), 0.5 * w1.sum())

        short = fit_shift_conformal(pool, "pooled", 0.8, T_B, bias_half_life=1, half_life=6)
        flat = fit_shift_conformal(pool, "pooled", 0.8, T_B, bias_half_life=1000, half_life=6)
        self.assertEqual(short["bias"], {"all": c})
        self.assertEqual(flat["bias"], {"all": -c})

    def test_each_horizon_recovers_its_own_offset(self):
        offsets = {h: (h - 3) / 16 for h in range(1, 7)}
        pool = _pool([(o, 0.05) for o in MONTH_ENDS])
        pool = _with_offset(pool, pool["horizon"].map(offsets))
        cal = fit_shift_conformal(pool, "horizon", 0.8, T_V, bias_half_life=3, half_life=6)
        self.assertEqual(cal["bias"], offsets)
        self.assertEqual(cal["width"], {h: 0.0 for h in offsets})
        self.assertEqual(cal["q"], {h: (c, c) for h, c in offsets.items()})
        # Horizon 3 has no bias, so its band is not clipped; every other horizon's is.
        self.assertEqual(sorted(cal["clipped_groups"]), [1, 2, 4, 5, 6])
        self.assertEqual(cal["n_by_group"], {1: 240, 2: 220, 3: 200, 4: 180, 5: 160, 6: 140})
        self.assertEqual(cal["n"], 1140)
        self.assertTrue(all(type(h) is int for h in cal["q"]))
        self.assertTrue(all(type(h) is int for h in cal["clipped_groups"]))

    def test_horizon_matches_a_direct_computation(self):
        pool = _pool([(o, 0.05) for o in MONTH_ENDS], n_stations=6, seed=3)
        pool["ridership"] = pool["ridership"] + pool["p50"] * pool["horizon"] * 0.01   # bias grows with h
        cal = fit_shift_conformal(pool, "horizon", 0.8, T_V, bias_half_life=1, half_life=6)
        df = rolling_pool(pool, T_V)
        r = ((df["ridership"] - df["p50"]) / df["p50"]).to_numpy()
        age = df["age"].to_numpy(dtype=float)
        h = df["horizon"].to_numpy()
        for k in range(1, 7):
            g = h == k
            m = weighted_median(r[g], 0.5 ** (age[g] / 1))
            w = weighted_conformal_quantile(np.abs(r[g] - m), 0.5 ** (age[g] / 6), 0.8)
            self.assertEqual(cal["q"][k], (m - w, m + w), k)
            self.assertEqual(cal["bias"][k], m, k)


class ShiftAtEachOriginTest(unittest.TestCase):
    """bias_at="origin": each pool row is scored against the bias its own origin saw."""

    # One station; three monthly origins, each forecasting three months ahead.
    # Rows a-f are resolved by AS_OF; the other three target later months.
    R = {("2024-01-31", "2024-02-01"): 0.0625,   # a  age 2 to AS_OF
         ("2024-01-31", "2024-03-01"): 0.25,     # b  age 1
         ("2024-01-31", "2024-04-01"): -0.125,   # c  age 0
         ("2024-02-29", "2024-03-01"): 0.125,    # d  age 1
         ("2024-02-29", "2024-04-01"): 0.5,      # e  age 0
         ("2024-02-29", "2024-05-01"): 4.0,      #    after AS_OF
         ("2024-03-31", "2024-04-01"): -0.25,    # f  age 0
         ("2024-03-31", "2024-05-01"): -0.75,    #    after AS_OF
         ("2024-03-31", "2024-06-01"): 8.0}      #    after AS_OF
    AS_OF = pd.Timestamp("2024-04-30")

    def _three_origins(self) -> pd.DataFrame:
        rows = [{"origin": pd.Timestamp(o), "timestamp": pd.Timestamp(t), "station_id": "A",
                 "p10": 900.0, "p50": 1000.0, "p90": 1100.0, "ridership": 1000.0 * (1 + r)}
                for (o, t), r in self.R.items()]
        return with_origin_horizon(pd.DataFrame(rows))

    def test_by_hand(self):
        cal = fit_shift_conformal(self._three_origins(), "pooled", 0.5, self.AS_OF,
                                  bias_half_life=1, half_life=1, bias_at="origin")
        # 2024-01-31: no earlier origin, so a, b, c have no bias and no score.
        # 2024-02-29: resolved = {a} -> m = 0.0625; s_d = 0.0625, s_e = 0.4375.
        # 2024-03-31: resolved = {a (age 1 to this origin, w 0.5), b (0, 1), d (0, 1)};
        #   half of 2.5 is 1.25; sorted 0.0625 (cum 0.5), 0.125 (cum 1.5) -> m = 0.125;
        #   s_f = |-0.25 - 0.125| = 0.375.
        # Width, AS_OF weights d 0.5, e 1, f 1: threshold 0.5 * (2.5 + 1) = 1.75;
        #   sorted 0.0625 (cum 0.5), 0.375 (1.5), 0.4375 (2.5) -> w = 0.4375.
        # Centre m(AS_OF) over all six rows, weights a .25, b .5, c 1, d .5, e 1, f 1:
        #   half of 4.25 is 2.125; -0.25 (1), -0.125 (2), 0.0625 (2.25) -> m = 0.0625.
        # Mistakes this catches: m(o) reading rows that target a month after o gives
        # w = 0.625; dropping a, b, c from the centre gives m = 0.125; scoring a, b, c
        # against a zero bias gives w = 0.375.
        self.assertEqual(cal["bias"], {"all": 0.0625})
        self.assertEqual(cal["width"], {"all": 0.4375})
        self.assertEqual(cal["q"], {"all": (-0.375, 0.5)})
        self.assertEqual(cal["n"], 3)
        self.assertEqual(cal["n_by_group"], {"all": 3})
        self.assertEqual(cal["n_no_bias"], 3)
        self.assertEqual(cal["weight_sum"], 2.5)
        self.assertEqual(cal["clipped_groups"], [])
        self.assertEqual((cal["scheme"], cal["bias_at"], cal["method"]), ("shift", "origin", "asym_relative"))

        # The band it gives: P10 = 1000 * (1 - 0.375), P90 = 1000 * (1 + 0.5).
        target = pd.DataFrame({"timestamp": [pd.Timestamp("2024-05-01")], "station_id": ["A"],
                               "origin": [self.AS_OF], "p10": [900.0], "p50": [1000.0], "p90": [1100.0]})
        out = apply_conformal(with_origin_horizon(target), cal)
        self.assertEqual((out["p10"].iloc[0], out["p50"].iloc[0], out["p90"].iloc[0]), (625.0, 1000.0, 1500.0))

    def test_same_pool_with_the_bias_at_as_of_by_hand(self):
        cal = fit_shift_conformal(self._three_origins(), "pooled", 0.5, self.AS_OF,
                                  bias_half_life=1, half_life=1, bias_at="as_of")
        # m = 0.0625 as above; s: a 0 (w .25), b .1875 (.5), c .1875 (1), d .0625 (.5),
        # e .4375 (1), f .3125 (1); threshold 0.5 * (4.25 + 1) = 2.625;
        # cumulative .25, .75, 1.25, 2.25, 3.25 -> w = 0.3125.
        self.assertEqual(cal["q"], {"all": (-0.25, 0.375)})
        self.assertEqual((cal["n"], cal["n_no_bias"], cal["weight_sum"]), (6, 0, 4.25))

    def test_first_origin_is_unscored_and_the_centre_is_the_bias_at_as_of(self):
        pool = _pool([(o, 0.05) for o in MONTH_ENDS])
        df = rolling_pool(pool, T_B)
        first = int((df["origin"] == df["origin"].min()).sum())
        self.assertEqual(first, 120)
        at_origin = fit_shift_conformal(pool, "pooled", 0.8, T_B, bias_half_life=1, half_life=6,
                                        bias_at="origin")
        at_as_of = fit_shift_conformal(pool, "pooled", 0.8, T_B, bias_half_life=1, half_life=6)
        self.assertEqual(at_origin["n_no_bias"], first)
        self.assertEqual(at_origin["n"], len(df) - first)
        self.assertEqual(at_origin["n_by_group"], {"all": len(df) - first})
        self.assertEqual(at_origin["bias"], at_as_of["bias"])

    def test_matches_a_direct_computation(self):
        # A bias that drifts with the target month, so each origin's estimate differs.
        pool = _pool([(o, 0.04) for o in MONTH_ENDS], n_stations=6, seed=8)
        drift = (pool["timestamp"].dt.month + 12 * (pool["timestamp"].dt.year - 2024)) * 0.01
        pool["ridership"] = pool["ridership"] * (1 + drift)
        df = rolling_pool(pool, T_V)
        r = (df["ridership"] - df["p50"]) / df["p50"]
        for hb in (1, 3):
            cal = fit_shift_conformal(pool, "pooled", 0.8, T_V, bias_half_life=hb, half_life=6,
                                      bias_at="origin")
            centre = pd.Series(np.nan, index=df.index)
            for o in sorted(df["origin"].unique()):
                seen = rolling_pool(df, o)   # resolved by o, age counted to o
                if len(seen):
                    centre.loc[(df["origin"] == o).to_numpy()] = weighted_median(
                        r.loc[seen.index].to_numpy(), 0.5 ** (seen["age"].to_numpy(dtype=float) / hb))
            scored = centre.notna().to_numpy()
            s = (r - centre).abs().to_numpy()[scored]
            ww = 0.5 ** (df["age"].to_numpy(dtype=float)[scored] / 6)
            w = weighted_conformal_quantile(s, ww, 0.8)
            m = weighted_median(r.to_numpy(), 0.5 ** (df["age"].to_numpy(dtype=float) / hb))
            self.assertTrue(np.isfinite(w), hb)
            self.assertEqual(cal["q"], {"all": (m - w, m + w)}, hb)
            self.assertEqual(cal["n"], int(scored.sum()), hb)
            self.assertEqual(cal["n_no_bias"], int((~scored).sum()), hb)
            self.assertEqual(cal["weight_sum"], float(ww.sum()), hb)


class ShiftInputsTest(unittest.TestCase):
    def setUp(self):
        self.pool = _pool([(o, 0.05) for o in MONTH_ENDS])

    def test_bias_at_each_origin_is_pooled_only(self):
        with self.assertRaises(ValueError):
            fit_shift_conformal(self.pool, "horizon", 0.8, T_B, bias_half_life=1, half_life=6,
                                bias_at="origin")

    def test_unknown_group_or_bias_at_raises(self):
        for group in ("station", "all", None):
            with self.subTest(group=group), self.assertRaises(ValueError):
                fit_shift_conformal(self.pool, group, 0.8, T_B, bias_half_life=1, half_life=6)
        for bias_at in ("T", "target", None):
            with self.subTest(bias_at=bias_at), self.assertRaises(ValueError):
                fit_shift_conformal(self.pool, "pooled", 0.8, T_B, bias_half_life=1, half_life=6,
                                    bias_at=bias_at)

    def test_bias_half_life_must_be_a_positive_number(self):
        for hb in (0, 0.0, -1, -3.0, float("nan"), None, "3"):
            with self.subTest(hb=hb), self.assertRaises(ValueError):
                fit_shift_conformal(self.pool, "pooled", 0.8, T_B, bias_half_life=hb, half_life=6)

    def test_rows_after_as_of_do_not_move_the_fit(self):
        later = (self.pool["timestamp"] > T_B).to_numpy()
        self.assertTrue(later.any())
        changed = self.pool.copy()
        changed.loc[later, "ridership"] = changed.loc[later, "ridership"] * 50.0
        self.assertFalse(changed["ridership"].equals(self.pool["ridership"]))
        for group, bias_at in [("pooled", "as_of"), ("horizon", "as_of"), ("pooled", "origin")]:
            base = fit_shift_conformal(self.pool, group, 0.8, T_B, bias_half_life=1, half_life=6,
                                       bias_at=bias_at)
            again = fit_shift_conformal(changed, group, 0.8, T_B, bias_half_life=1, half_life=6,
                                        bias_at=bias_at)
            self.assertEqual(base, again, (group, bias_at))

    def test_actual_with_missing_p50_raises(self):
        pool = self.pool.copy()
        first = pool.index[0]
        self.assertLessEqual(pool.loc[first, "timestamp"], T_B)
        self.assertTrue(pd.notna(pool.loc[first, "ridership"]))
        pool.loc[first, "p50"] = np.nan
        for bias_at in ("as_of", "origin"):
            with self.subTest(bias_at=bias_at), self.assertRaises(ValueError):
                fit_shift_conformal(pool, "pooled", 0.8, T_B, bias_half_life=1, half_life=6,
                                    bias_at=bias_at)

    def test_rows_without_an_actual_are_left_out(self):
        pool = self.pool.copy()
        pool.loc[pool.index[:5], ["ridership", "p50"]] = np.nan
        cal = fit_shift_conformal(pool, "pooled", 0.8, T_B, bias_half_life=1, half_life=6)
        self.assertEqual(cal["n"], len(rolling_pool(self.pool, T_B)) - 5)

    def test_pool_without_origin_or_horizon_raises(self):
        for col in ("origin", "horizon"):
            for bias_at in ("as_of", "origin"):
                with self.subTest(col=col, bias_at=bias_at), self.assertRaises(ValueError):
                    fit_shift_conformal(self.pool.drop(columns=col), "pooled", 0.8, T_B,
                                        bias_half_life=1, half_life=6, bias_at=bias_at)


class ApplyShiftTest(unittest.TestCase):
    def test_apply_never_moves_p50_and_keeps_bounds_ordered_and_floored(self):
        cases = [
            # (pool rel. error, extra bias, group, bias_at)
            (0.05, 0.10, "pooled", "as_of"),    # bias beyond the width: ordering clip binds
            (1.00, 0.00, "horizon", "as_of"),   # width beyond 1: the zero floor binds
            (0.20, -0.05, "pooled", "origin"),
        ]
        target = _origin_forecasts("2024-12-31", [f"T{i}" for i in range(4)], 0.05,
                                   np.random.default_rng(9))
        for rel_err, bias, group, bias_at in cases:
            with self.subTest(rel_err=rel_err, group=group, bias_at=bias_at):
                pool = _pool([(o, rel_err) for o in MONTH_ENDS], n_stations=10, seed=2)
                pool["ridership"] = pool["ridership"] * (1 + bias)
                cal = fit_shift_conformal(pool, group, 0.8, T_V, bias_half_life=3, half_life=6,
                                          bias_at=bias_at)
                out = apply_conformal(target, cal)
                pd.testing.assert_series_equal(out["p50"], target["p50"], check_exact=True)
                self.assertTrue((out["p10"] <= out["p50"]).all())
                self.assertTrue((out["p50"] <= out["p90"]).all())
                self.assertTrue((out["p10"] >= 0).all())
                if rel_err == 1.00:
                    self.assertTrue((out["p10"] == 0).any())
                if bias == 0.10:
                    self.assertEqual(cal["clipped_groups"], ["all"])
                    self.assertTrue((out["p10"] == out["p50"]).all())

    def test_describe_summarises_shift_calibrators(self):
        pool = _pool([(o, 0.05) for o in MONTH_ENDS])
        for group, bias_at in [("pooled", "as_of"), ("horizon", "as_of"), ("pooled", "origin")]:
            cal = fit_shift_conformal(pool, group, 0.8, T_V, bias_half_life=3, half_life=6,
                                      bias_at=bias_at)
            text = describe(cal)
            self.assertIsInstance(text, str)
            self.assertTrue(text.startswith(f"asym_relative/{group} @0.8, n={cal['n']}"), text)


if __name__ == "__main__":
    unittest.main()
