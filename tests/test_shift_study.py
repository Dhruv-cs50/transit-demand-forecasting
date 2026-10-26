"""
tests/test_shift_study.py
─────────────────────────
Sprint 6 in evaluation/interval_study.py: the six bias-shifted candidates, the
per-model rule (apply_rule with common=False), the layered config check, the
Sprint 6 tables, the windows shared with Sprint 5, and shift_study end to end
on synthetic pools (rolling_forecasts is replaced, so no model is fit and no
cached forecast is read).

    python -m unittest tests.test_shift_study -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evaluation.interval_study as study  # noqa: E402
from evaluation.calibration import (  # noqa: E402
    add_horizon, describe, fit_conformal, fit_shift_conformal, with_origin_horizon,
)
from evaluation.interval_study import (  # noqa: E402
    HALF_LIFE, INCUMBENT, LEVEL, SHIFT_CANDIDATES, SHIFT_ELIGIBLE, apply_rule,
    check_config_matches_shift_decision, markdown_tables, rule_table, scored_windows,
    shift_markdown_tables, shift_study,
)

CHRONOS = "Chronos1_ZeroShot (chronos-t5-small)"
MODELS = ["SeasonalNaive", "SARIMA", "Prophet", CHRONOS]
MODEL_KEYS = {"SeasonalNaive": "SeasonalNaive", "SARIMA": "SARIMA", "Prophet": "Prophet", CHRONOS: "Chronos"}
CFG = {"data": {"train_end": "2024-12-31", "val_end": "2025-06-30"}}
VAL_END = pd.Timestamp("2025-06-30")

# The board's six candidates (ab8183c), written out rather than derived, so a
# drift in SHIFT_CANDIDATES fails here.
BOARD = {
    "shift_hl1 relative/pooled": {"bias_at": "as_of", "bias_half_life": 1, "group": "pooled"},
    "shift_hl3 relative/pooled": {"bias_at": "as_of", "bias_half_life": 3, "group": "pooled"},
    "shift_hl1 relative/horizon": {"bias_at": "as_of", "bias_half_life": 1, "group": "horizon"},
    "shift_hl3 relative/horizon": {"bias_at": "as_of", "bias_half_life": 3, "group": "horizon"},
    "shift_origin_hl1 relative/pooled": {"bias_at": "origin", "bias_half_life": 1, "group": "pooled"},
    "shift_origin_hl3 relative/pooled": {"bias_at": "origin", "bias_half_life": 3, "group": "pooled"},
}


def _row(model, candidate, window, score, cov=80.0, below=8.0, above=12.0, eligible=True):
    if candidate == "incumbent":
        scheme = "own band"
    else:
        scheme = candidate.split(" ")[0]
    return {"model": model, "window": window, "candidate": candidate, "scheme": scheme,
            "eligible": eligible, "Coverage_%": cov, "Below_P10_%": below,
            "Above_P90_%": above, "IntervalScore_%": score}


def _both(model, candidate, score, **kw):
    return [_row(model, candidate, "B", score, **kw), _row(model, candidate, "V", score, **kw)]


def _rule(rows, models, common=True):
    return apply_rule(rule_table(pd.DataFrame(rows)), models, common=common)


# ── Candidate definitions ──────────────────────────────────────────────────────

class ShiftCandidatesTest(unittest.TestCase):
    def test_exactly_the_six_board_candidates_in_order(self):
        self.assertEqual(list(SHIFT_CANDIDATES), list(BOARD))
        self.assertEqual({k: dict(v) for k, v in SHIFT_CANDIDATES.items()}, BOARD)

    def test_eligible_models_and_the_width_settings(self):
        self.assertEqual(tuple(SHIFT_ELIGIBLE), ("SARIMA", "Chronos"))
        self.assertEqual(HALF_LIFE, 6)
        self.assertEqual(LEVEL, 0.8)


# ── The per-model rule ─────────────────────────────────────────────────────────

class PerModelRuleTest(unittest.TestCase):
    # "shift_hl3 relative/pooled" qualifies for both models but scores worse for
    # each than that model's own best qualifier.
    ROWS = (_both("A", "shift_hl3 relative/pooled", 25.0)
            + _both("A", "shift_hl1 relative/pooled", 20.0)
            + _both("B", "shift_hl3 relative/pooled", 25.0)
            + _both("B", "shift_origin_hl1 relative/pooled", 22.0))

    def test_each_model_takes_its_own_best_qualifier(self):
        _, common, d = _rule(self.ROWS, ["A", "B"], common=False)
        self.assertEqual(d["A"]["choice"], "shift_hl1 relative/pooled")
        self.assertEqual(d["B"]["choice"], "shift_origin_hl1 relative/pooled")
        self.assertEqual(d["A"]["basis"], "lowest-scoring qualifier for this model")
        self.assertEqual(d["A"]["mean_IntervalScore_%"], 20.0)
        self.assertTrue(common.empty)

    def test_contrast_the_sprint5_rule_picks_the_shared_method(self):
        _, common, d = _rule(self.ROWS, ["A", "B"])
        self.assertEqual(d["A"]["choice"], "shift_hl3 relative/pooled")
        self.assertEqual(d["B"]["choice"], "shift_hl3 relative/pooled")
        self.assertEqual(list(common["candidate"]), ["shift_hl3 relative/pooled"])

    def test_no_qualifier_keeps_the_current_entry(self):
        rows = (_both("A", "shift_hl1 relative/pooled", 20.0, cov=70.0)
                + [_row("A", "shift_hl3 relative/pooled", "B", 20.0),
                   _row("A", "shift_hl3 relative/pooled", "V", 20.0, above=16.0)]
                + _both("A", "shift_hl1 relative/horizon", np.inf))
        d = _rule(rows, ["A"], common=False)[2]
        self.assertEqual(d["A"], {"choice": "keep current entry", "basis": "no eligible candidate qualifies"})

    def test_ties_break_by_candidate_name_whatever_the_input_order(self):
        rows = (_both("A", "shift_origin_hl1 relative/pooled", 21.0)
                + _both("A", "shift_hl3 relative/pooled", 21.0)
                + _both("A", "shift_hl1 relative/pooled", 22.0))
        for r in (rows, rows[::-1]):
            self.assertEqual(_rule(r, ["A"], common=False)[2]["A"]["choice"], "shift_hl3 relative/pooled")

    def test_ties_use_the_unrounded_mean(self):
        # Means 20.008 and 20.006 both round to 20.01; the lower exact mean wins,
        # although the name order would pick shift_hl1.
        rows = ([_row("A", "shift_hl1 relative/pooled", "B", 20.0),
                 _row("A", "shift_hl1 relative/pooled", "V", 20.016)]
                + [_row("A", "shift_hl3 relative/pooled", "B", 20.0),
                   _row("A", "shift_hl3 relative/pooled", "V", 20.012)])
        self.assertEqual(_rule(rows, ["A"], common=False)[2]["A"]["choice"], "shift_hl3 relative/pooled")

    def test_non_eligible_rows_are_never_chosen(self):
        rows = (_both("A", "shift_hl1 relative/pooled", 10.0, eligible=False)
                + _both("A", "shift_hl3 relative/pooled", 30.0)
                + _both("B", "shift_hl1 relative/pooled", 10.0, eligible=False))
        sel, _, d = _rule(rows, ["A", "B"], common=False)
        self.assertEqual(d["A"]["choice"], "shift_hl3 relative/pooled")
        self.assertEqual(d["B"]["choice"], "keep current entry")
        self.assertNotIn("shift_hl1 relative/pooled", set(sel["candidate"]))

    def test_the_incumbent_can_be_a_models_own_best(self):
        rows = _both("A", "incumbent", 19.0) + _both("A", "shift_hl1 relative/pooled", 20.0)
        self.assertEqual(_rule(rows, ["A"], common=False)[2]["A"]["choice"], "incumbent")


# ── The layered config check ───────────────────────────────────────────────────

class ConfigMatchesShiftDecisionTest(unittest.TestCase):
    KEEP = {"choice": "keep current entry"}
    SARIMA_CFG = {"method": "none", "reason": "no method passed validation"}
    CHRONOS_CFG = {"method": "relative", "group": "pooled", "validated_for": "amazon/chronos-t5-small"}

    @staticmethod
    def shift_entry(name):
        spec = BOARD[name]
        return {"method": "shift_relative", "group": spec["group"], "scheme": "rolling", "half_life": 6,
                "bias_half_life": spec["bias_half_life"], "bias_at": spec["bias_at"],
                "first_origin": "2023-12-31"}

    def test_keep_passes_on_the_incumbent(self):
        check_config_matches_shift_decision("SARIMA", self.SARIMA_CFG, self.KEEP, INCUMBENT["SARIMA"])
        check_config_matches_shift_decision(CHRONOS, self.CHRONOS_CFG, self.KEEP, INCUMBENT["Chronos"])

    def test_choosing_the_incumbent_is_keeping_it(self):
        check_config_matches_shift_decision(CHRONOS, self.CHRONOS_CFG, {"choice": "incumbent"},
                                            INCUMBENT["Chronos"])
        with self.assertRaises(ValueError):
            check_config_matches_shift_decision(CHRONOS, self.shift_entry("shift_hl1 relative/pooled"),
                                                {"choice": "incumbent"}, INCUMBENT["Chronos"])

    def test_keep_with_a_shift_entry_raises(self):
        for name in BOARD:
            with self.assertRaises(ValueError, msg=name):
                check_config_matches_shift_decision(CHRONOS, self.shift_entry(name), self.KEEP,
                                                    INCUMBENT["Chronos"])

    def test_keep_with_stray_shift_keys_raises(self):
        # The Sprint 5 tuple matches the incumbent; the bias keys alone must stop it.
        for extra in ({"bias_half_life": 1}, {"bias_at": "as_of"}, {"bias_half_life": None}):
            with self.assertRaises(ValueError, msg=extra):
                check_config_matches_shift_decision(CHRONOS, {**self.CHRONOS_CFG, **extra}, self.KEEP,
                                                    INCUMBENT["Chronos"])
            with self.assertRaises(ValueError, msg=extra):
                check_config_matches_shift_decision("SARIMA", {**self.SARIMA_CFG, **extra}, self.KEEP,
                                                    INCUMBENT["SARIMA"])

    def test_keep_with_a_different_sprint5_entry_raises(self):
        rolling = {"method": "relative", "group": "pooled", "scheme": "rolling", "half_life": 6,
                   "first_origin": "2023-12-31"}
        with self.assertRaises(ValueError):
            check_config_matches_shift_decision(CHRONOS, rolling, self.KEEP, INCUMBENT["Chronos"])

    def test_each_choice_passes_on_its_exact_entry(self):
        for name in BOARD:
            check_config_matches_shift_decision("SARIMA", self.shift_entry(name), {"choice": name},
                                                INCUMBENT["SARIMA"])

    def test_a_wrong_setting_raises(self):
        flips = {"bias_half_life": {1: 3, 3: 1}, "bias_at": {"as_of": "origin", "origin": "as_of"},
                 "group": {"pooled": "horizon", "horizon": "pooled"}}
        for name in BOARD:
            good = self.shift_entry(name)
            changes = [{k: flips[k][good[k]]} for k in flips]
            changes += [{"half_life": 3}, {"half_life": None}, {"first_origin": "2024-06-30"},
                        {"scheme": "split"}, {"method": "asym_relative"}]
            for change in changes:
                with self.assertRaises(ValueError, msg=(name, change)):
                    check_config_matches_shift_decision("SARIMA", {**good, **change}, {"choice": name},
                                                        INCUMBENT["SARIMA"])
            for key in ("bias_half_life", "bias_at"):
                missing = {k: v for k, v in good.items() if k != key}
                with self.assertRaises(ValueError, msg=(name, key)):
                    check_config_matches_shift_decision("SARIMA", missing, {"choice": name}, INCUMBENT["SARIMA"])

    def test_a_sprint5_rolling_entry_for_a_shift_choice_raises(self):
        rolling = {"method": "relative", "group": "pooled", "scheme": "rolling", "half_life": 6,
                   "first_origin": "2023-12-31"}
        with self.assertRaises(ValueError):
            check_config_matches_shift_decision(CHRONOS, rolling, {"choice": "shift_hl1 relative/pooled"},
                                                INCUMBENT["Chronos"])

    def test_a_choice_that_is_not_a_sprint6_candidate_raises_naming_both_sides(self):
        rolling = {"method": "relative", "group": "pooled", "scheme": "rolling", "half_life": 6,
                   "first_origin": "2023-12-31"}
        with self.assertRaises(ValueError) as ctx:
            check_config_matches_shift_decision(CHRONOS, rolling, {"choice": "rolling_hl6 relative/pooled"},
                                                INCUMBENT["Chronos"])
        self.assertIn("rolling_hl6 relative/pooled", str(ctx.exception))
        self.assertIn("'relative'", str(ctx.exception))

    def test_the_error_names_the_config_and_the_choice(self):
        name = "shift_hl3 relative/horizon"
        with self.assertRaises(ValueError) as ctx:
            check_config_matches_shift_decision("SARIMA", self.SARIMA_CFG, {"choice": name}, INCUMBENT["SARIMA"])
        self.assertIn(name, str(ctx.exception))
        self.assertIn("'none'", str(ctx.exception))
        self.assertIn("shift_relative", str(ctx.exception))


# ── Tables ─────────────────────────────────────────────────────────────────────

class ShiftMarkdownTest(unittest.TestCase):
    def rule_all(self):
        rows = []
        for model in ("SARIMA", CHRONOS):
            rows += _both(model, "incumbent", 30.0, above=19.0)
            rows += _both(model, "shift_hl1 relative/pooled", 25.0)
        for model in ("SeasonalNaive", "Prophet"):
            rows += _both(model, "shift_hl1 relative/pooled", 21.0, eligible=False)
        return rule_table(pd.DataFrame(rows))

    def test_two_sections_with_the_eligible_rows_first(self):
        text = shift_markdown_tables(self.rule_all())
        head_e = "<!-- Eligible candidates: SARIMA, Chronos-1 -->"
        head_d = "<!-- Diagnostics: SeasonalNaive, Prophet (not eligible) -->"
        self.assertIn(head_e, text)
        self.assertIn(head_d, text)
        eligible, diagnostics = text.split(head_d)
        self.assertTrue(eligible.startswith(head_e))
        for name in ("| SARIMA |", "| Chronos-1 |"):
            self.assertIn(name, eligible)
            self.assertNotIn(name, diagnostics)
        for name in ("| SeasonalNaive |", "| Prophet |"):
            self.assertIn(name, diagnostics)
            self.assertNotIn(name, eligible)
        self.assertEqual(eligible.count("| incumbent |"), 2)
        self.assertEqual(diagnostics.count("| shift_hl1 relative/pooled |"), 2)

    def test_same_layout_as_the_sprint5_tables(self):
        r = self.rule_all()
        header = "| Model | Candidate | B coverage % | B below / above % | B score | V coverage %"
        # Sprint 5's eligible section, with every row marked eligible, prints every row.
        sprint5 = markdown_tables(r.assign(eligible=True)).splitlines()
        sprint6 = shift_markdown_tables(r).splitlines()
        self.assertTrue(any(line.startswith(header) for line in sprint6))
        # Every table line Sprint 6 writes is a line Sprint 5's formatter writes for the same rows.
        rows5 = {line for line in sprint5 if line.startswith("| ")}
        rows6 = [line for line in sprint6 if line.startswith("| ")]
        self.assertEqual(len(rows6), 2 + len(r))     # one header line per section, one line per row
        self.assertTrue(set(rows6) <= rows5)


# ── Windows (shared with Sprint 5) ─────────────────────────────────────────────

class ScoredWindowsTest(unittest.TestCase):
    def test_the_sprint5_windows(self):
        self.assertEqual(scored_windows(CFG, 6), {
            "B": (pd.Timestamp("2024-06-30"), "cal", "cal2"),
            "V": (pd.Timestamp("2024-12-31"), "eval", "cal"),
        })

    def test_a_moved_train_end_or_horizon_raises(self):
        for train_end, horizon in (("2025-01-31", 6), ("2024-11-30", 6), ("2024-12-31", 3)):
            cfg = {"data": {**CFG["data"], "train_end": train_end}}
            with self.assertRaises(ValueError, msg=(train_end, horizon)):
                scored_windows(cfg, horizon)

    def test_shift_study_stops_on_moved_windows(self):
        cfg = {"data": {**CFG["data"], "train_end": "2025-01-31"}}
        with self.assertRaises(ValueError):
            shift_study(None, cfg, MODELS, {}, MODEL_KEYS, 6, False, VAL_END)


# ── shift_study end to end on synthetic pools ──────────────────────────────────

STATIONS = [f"S{i:02d}" for i in range(10)]
BIAS = {"SeasonalNaive": 0.0, "SARIMA": 0.25, "Prophet": -0.01, CHRONOS: 0.06}


def _window(model: str, origin, noise: float = 0.03) -> pd.DataFrame:
    """Six months of forecasts from `origin` with their actuals: y = p50 * (1 + bias + noise)."""
    o = pd.Timestamp(origin)
    rng = np.random.default_rng(o.year * 12 + o.month + 1000 * MODELS.index(model))
    ts = pd.date_range(o + pd.offsets.MonthBegin(1), periods=6, freq="MS")
    df = pd.DataFrame([(t, s) for t in ts for s in STATIONS], columns=["timestamp", "station_id"])
    df["p50"] = 10_000.0
    df["p10"] = 9_000.0
    df["p90"] = 11_000.0
    df["ridership"] = df["p50"] * (1 + BIAS[model] + rng.normal(0, noise, len(df)))
    return add_horizon(df[["timestamp", "station_id", "ridership", "p10", "p50", "p90"]])


def _fake_rolling(calls):
    def fake(model, df, cfg, origins, horizon, refresh, cut=None):
        calls.append((model, [pd.Timestamp(o) for o in origins], cut))
        return pd.concat([with_origin_horizon(_window(model, o), o) for o in origins], ignore_index=True)
    return fake


def _frames():
    starts = {"cal2": "2023-12-31", "cal": "2024-06-30", "eval": "2024-12-31"}
    return {(m, k): _window(m, o) for m in MODELS for k, o in starts.items()}


class ShiftStudyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calls = []
        with mock.patch.object(study, "rolling_forecasts", _fake_rolling(cls.calls)):
            cls.out = shift_study(None, CFG, MODELS, _frames(), MODEL_KEYS, 6, False, VAL_END)
        cls.cand = cls.out["candidates"]

    def test_returns_the_five_tables(self):
        self.assertEqual(set(self.out), {"candidates", "rule_all", "selection", "decision", "checks"})

    def test_pools_are_sprint5s(self):
        expected = {"B": (pd.Timestamp("2024-06-30"), pd.date_range("2023-12-31", "2024-05-31", freq="ME")),
                    "V": (pd.Timestamp("2024-12-31"), pd.date_range("2023-12-31", "2024-11-30", freq="ME"))}
        self.assertEqual(len(self.calls), 2 * len(MODELS))
        for model, origins, cut in self.calls:
            T, want = next(v for v in expected.values() if v[0] == cut)
            self.assertEqual(origins, list(want), msg=(model, cut))

    def test_candidates_per_model_and_eligibility(self):
        names = set(BOARD)
        for model in MODELS:
            for w in ("B", "V"):
                got = self.cand[(self.cand["model"] == model) & (self.cand["window"] == w)]
                eligible = MODEL_KEYS[model] in ("SARIMA", "Chronos")
                self.assertEqual(set(got["candidate"]), names | ({"incumbent"} if eligible else set()))
                self.assertTrue((got["eligible"] == eligible).all(), msg=(model, w))
                self.assertTrue((got["n"] == 60).all())

    def test_scheme_method_group(self):
        shift = self.cand[self.cand["candidate"] != "incumbent"]
        for d in shift.to_dict("records"):
            spec = BOARD[d["candidate"]]
            self.assertEqual(d["scheme"], "shift" if spec["bias_at"] == "as_of" else "shift_origin")
            self.assertEqual(d["method"], "relative")
            self.assertEqual(d["group"], spec["group"])
        inc = self.cand[self.cand["candidate"] == "incumbent"].set_index("model")
        self.assertEqual(set(inc.loc["SARIMA", "scheme"]), {"own band"})
        self.assertEqual(set(inc.loc["SARIMA", "calibrator"]), {"own band"})
        self.assertEqual(set(inc.loc[CHRONOS, "scheme"]), {"single"})
        self.assertEqual(set(inc.loc[CHRONOS, "method"]), {"relative"})

    def test_the_incumbent_is_sprint5s(self):
        inc = self.cand[(self.cand["model"] == CHRONOS) & (self.cand["candidate"] == "incumbent")]
        prev = {"B": "cal2", "V": "cal"}
        frames = _frames()
        for d in inc.to_dict("records"):
            calib = fit_conformal(frames[(CHRONOS, prev[d["window"]])], "relative", "pooled", LEVEL)
            self.assertEqual(d["calibrator"], describe(calib))
            self.assertEqual(d["Clipped_rows"], 0)

    def test_calibrator_text(self):
        T = {"B": pd.Timestamp("2024-06-30"), "V": pd.Timestamp("2024-12-31")}
        for d in self.cand[self.cand["candidate"] != "incumbent"].to_dict("records"):
            spec = BOARD[d["candidate"]]
            origins = pd.date_range("2023-12-31", T[d["window"]] - pd.offsets.MonthEnd(1), freq="ME")
            pool = pd.concat([with_origin_horizon(_window(d["model"], o), o) for o in origins], ignore_index=True)
            calib = fit_shift_conformal(pool, spec["group"], LEVEL, T[d["window"]],
                                        bias_half_life=spec["bias_half_life"], half_life=6, bias_at=spec["bias_at"])
            b, w = list(calib["bias"].values()), list(calib["width"].values())
            if spec["group"] == "pooled":
                text = f"{describe(calib)}; bias {b[0]:.4f}; width {w[0]:.4f}"
            else:
                text = f"{describe(calib)}; bias {min(b):.4f}–{max(b):.4f}; width {min(w):.4f}–{max(w):.4f}"
            if spec["bias_at"] == "origin":
                text += f"; rows without a bias {calib['n_no_bias']}"
            self.assertEqual(d["calibrator"], text, msg=(d["model"], d["window"], d["candidate"]))

    def test_clipped_rows(self):
        shift = self.cand[self.cand["candidate"] != "incumbent"].set_index("model")
        # SARIMA's bias (0.25) is far beyond its spread: the clip binds on every row.
        self.assertTrue((shift.loc["SARIMA", "Clipped_rows"] == 60).all())
        # SeasonalNaive is unbiased: it never binds.
        self.assertTrue((shift.loc["SeasonalNaive", "Clipped_rows"] == 0).all())
        inc = self.cand[self.cand["candidate"] == "incumbent"]
        self.assertTrue((inc["Clipped_rows"] == 0).all())

    def test_checks(self):
        checks = self.out["checks"]
        self.assertEqual(len(checks), 2 * len(MODELS))
        by = checks.set_index(["model", "window"])
        for model in MODELS:
            self.assertEqual(by.loc[(model, "B"), "T"], "2024-06-30")
            self.assertEqual(by.loc[(model, "V"), "T"], "2024-12-31")
            self.assertEqual(by.loc[(model, "B"), "origins"], 6)
            self.assertEqual(by.loc[(model, "V"), "origins"], 12)
            # Resolved by T: B 6+5+4+3+2+1 = 21 months, V 7*6 + 5+4+3+2+1 = 57, times 10 stations.
            self.assertEqual(by.loc[(model, "B"), "pool_rows_resolved"], 210)
            self.assertEqual(by.loc[(model, "V"), "pool_rows_resolved"], 570)
            # The first origin (2023-12-31) has no earlier resolved row: its 60 rows have no bias.
            for name in ("shift_origin_hl1 relative/pooled", "shift_origin_hl3 relative/pooled"):
                for w in ("B", "V"):
                    self.assertEqual(by.loc[(model, w), f"n_no_bias {name}"], 60)

    def test_rule_is_per_model_on_the_eligible_models_only(self):
        self.assertEqual(set(self.out["decision"]), {"SARIMA", CHRONOS})
        self.assertEqual(set(self.out["rule_all"]["model"]), set(MODELS))
        self.assertEqual(set(self.out["selection"]["model"]), {"SARIMA", CHRONOS})
        expected = apply_rule(self.out["rule_all"], ["SARIMA", CHRONOS], common=False)[2]
        self.assertEqual(self.out["decision"], expected)


if __name__ == "__main__":
    unittest.main()
