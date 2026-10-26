"""
tests/test_interval_rule.py
───────────────────────────
The Sprint 5 selection rule as evaluation/interval_study.py applies it
(rule_table + apply_rule), on synthetic candidate scores.

    python -m unittest tests.test_interval_rule -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.interval_study import apply_rule, check_config_matches_decision, rule_table  # noqa: E402

GOOD = dict(cov=80.0, below=8.0, above=12.0)


def _row(model, candidate, window, score, cov=80.0, below=8.0, above=12.0, eligible=True):
    scheme = "own band" if candidate == "incumbent" else candidate.split(" ")[0]
    return {"model": model, "window": window, "candidate": candidate, "scheme": scheme,
            "eligible": eligible, "Coverage_%": cov, "Below_P10_%": below,
            "Above_P90_%": above, "IntervalScore_%": score}


def _both(model, candidate, score, **kw):
    return [_row(model, candidate, "B", score, **kw), _row(model, candidate, "V", score, **kw)]


def _decide(rows, models):
    return apply_rule(rule_table(pd.DataFrame(rows)), models)[2]


class RuleTest(unittest.TestCase):
    def test_must_pass_both_windows(self):
        rows = [_row("A", "rolling_hl6 x/pooled", "B", 20.0),
                _row("A", "rolling_hl6 x/pooled", "V", 20.0, cov=88.0)]
        self.assertEqual(_decide(rows, ["A"])["A"]["choice"], "keep current entry")

    def test_a_missing_window_fails(self):
        rows = [_row("A", "rolling_hl6 x/pooled", "B", 20.0)]
        self.assertEqual(_decide(rows, ["A"])["A"]["choice"], "keep current entry")

    def test_tail_limit_is_inclusive(self):
        rows = _both("A", "rolling_hl6 x/pooled", 20.0, cov=81.0, below=4.0, above=15.0)
        self.assertEqual(_decide(rows, ["A"])["A"]["choice"], "rolling_hl6 x/pooled")
        rows = _both("A", "rolling_hl6 x/pooled", 20.0, cov=81.0, below=3.99, above=15.01)
        self.assertEqual(_decide(rows, ["A"])["A"]["choice"], "keep current entry")

    def test_an_infinite_band_never_qualifies(self):
        # Coverage and tails pass, but the band is infinite somewhere: score NaN or inf.
        rows = _both("A", "aci_origin x/pooled", np.nan) + _both("A", "rolling_hl6 y/pooled", np.inf)
        self.assertEqual(_decide(rows, ["A"])["A"]["choice"], "keep current entry")

    def test_lowest_mean_score_wins_and_ties_break_by_name(self):
        rows = _both("A", "rolling_hl6 b/pooled", 21.0) + _both("A", "rolling_hl6 a/pooled", 21.0) \
            + _both("A", "rolling_hl6 c/pooled", 22.0)
        self.assertEqual(_decide(rows, ["A"])["A"]["choice"], "rolling_hl6 a/pooled")
        self.assertEqual(_decide(rows[::-1], ["A"])["A"]["choice"], "rolling_hl6 a/pooled")

    def test_one_method_for_every_model_is_preferred(self):
        rows = (_both("A", "rolling_hl6 x/pooled", 25.0) + _both("A", "aci_origin y/pooled", 20.0)
                + _both("B", "rolling_hl6 x/pooled", 25.0))
        d = _decide(rows, ["A", "B"])
        self.assertEqual(d["A"]["choice"], "rolling_hl6 x/pooled")
        self.assertEqual(d["B"]["choice"], "rolling_hl6 x/pooled")

    def test_incumbent_is_never_the_common_method(self):
        rows = _both("A", "incumbent", 20.0) + _both("B", "incumbent", 20.0)
        d = _decide(rows, ["A", "B"])
        self.assertEqual(d["A"]["basis"], "lowest-scoring qualifier for this model")

    def test_diagnostics_are_scored_but_never_chosen(self):
        rows = _both("A", "monthly_recal x/pooled", 10.0, eligible=False) + _both("A", "rolling_hl6 x/pooled", 30.0)
        table = rule_table(pd.DataFrame(rows))
        self.assertTrue(table.set_index("candidate").loc["monthly_recal x/pooled", "qualifies"])
        self.assertEqual(apply_rule(table, ["A"])[2]["A"]["choice"], "rolling_hl6 x/pooled")


class ConfigMatchesDecisionTest(unittest.TestCase):
    ROLLING = {"method": "relative", "group": "pooled", "scheme": "rolling",
               "half_life": 6, "first_origin": "2023-12-31"}
    CHOSEN = {"choice": "rolling_hl6 relative/pooled"}

    def test_the_validated_entry_passes(self):
        check_config_matches_decision("Prophet", self.ROLLING, self.CHOSEN, {"method": "scaled", "group": "horizon"})
        check_config_matches_decision("SARIMA", {"method": "none", "reason": "x"},
                                      {"choice": "keep current entry"}, {"method": "none"})

    def test_an_unvalidated_half_life_or_origin_stops(self):
        for change in ({"half_life": 3}, {"first_origin": "2024-06-30"}, {"group": "horizon"}):
            with self.assertRaises(ValueError, msg=change):
                check_config_matches_decision("Prophet", {**self.ROLLING, **change}, self.CHOSEN, {})

    def test_keeping_the_entry_means_the_incumbent(self):
        with self.assertRaises(ValueError):
            check_config_matches_decision("Chronos", self.ROLLING, {"choice": "keep current entry"},
                                          {"method": "relative", "group": "pooled"})


if __name__ == "__main__":
    unittest.main()
