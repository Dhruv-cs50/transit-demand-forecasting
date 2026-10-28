"""
evaluation.validators.check_event_coverage: the proximity-score check.

An enriched store built without an events archive has NaN event_proximity_score
(Processing/feature_engineering.py gives unknown, not 0.0). NaN is not equal to
0, so the check used to read such a store as "0% zero scores" and report it
healthy; a missing score is as unusable as a zero one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.validators import Severity, check_event_coverage  # noqa: E402


def _frame(is_game_day, score) -> pd.DataFrame:
    return pd.DataFrame({
        "is_game_day": pd.array(is_game_day, dtype="boolean"),
        "hours_to_event": [1.0] * len(is_game_day),
        "is_sharks_game_window": pd.array(is_game_day, dtype="boolean"),
        "event_proximity_score": score,
    })


def _proximity(results):
    return [r for r in results if r.check == "event_proximity_score"]


def test_all_nan_scores_on_game_days_warn():
    (r,) = _proximity(check_event_coverage(_frame([True] * 4, [np.nan] * 4)))
    assert r.severity == Severity.WARNING
    assert "100.0%" in r.message and "missing" in r.message


def test_all_zero_scores_still_warn():
    (r,) = _proximity(check_event_coverage(_frame([True] * 4, [0.0] * 4)))
    assert r.severity == Severity.WARNING
    assert "100.0%" in r.message


def test_real_scores_are_healthy():
    (r,) = _proximity(check_event_coverage(_frame([True] * 4, [0.5, 1.0, 0.25, 0.75])))
    assert r.severity == Severity.INFO


def test_zero_plus_missing_counts_together():
    (r,) = _proximity(check_event_coverage(_frame([True] * 4, [0.0, np.nan, np.nan, 1.0])))
    assert r.severity == Severity.WARNING
    assert "75.0%" in r.message and "25.0% zero, 50.0% missing" in r.message


def test_unknown_game_day_rows_are_not_game_rows_and_do_not_raise():
    # <NA> is_game_day must not be indexed as a mask, and must not count as a game day.
    df = _frame([True, True, None, None], [0.5, 1.0, np.nan, np.nan])
    (r,) = _proximity(check_event_coverage(df))
    assert r.severity == Severity.INFO


def test_no_game_day_rows_gives_no_proximity_result():
    assert _proximity(check_event_coverage(_frame([False, False], [np.nan, np.nan]))) == []
