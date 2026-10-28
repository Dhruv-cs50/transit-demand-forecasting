"""
tests/test_ingest_gate.py
─────────────────────────
S9-05: the publish gate of the cloud ingestion job
(machine_learning_files/ingest_gate.py; docs/cloud-ingestion-design.md §2 step 5).

The committed feature store is the reference. Every test builds its candidate
from it in memory; nothing is written, so the tracked file's sha256 cannot
change. No network, no GCP.

Run from the repository root:
    python -m pytest -q tests/test_ingest_gate.py

The two tests that run the real SARIMA backtest (50 stations, ~5 s each) are the
tracked-store and tracked-plus-2026-01 cases; every failure test short-circuits
before the backtest (it only runs when all structural checks pass), and the
backtest's comparison logic is tested with the fit stubbed out.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from machine_learning_files import ingest_gate
from machine_learning_files.ingest_gate import GateReport, run_gate

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACKED_PATH = REPO_ROOT / "data" / "processed" / "feature_store.parquet"
TRACKED_SHA256_PREFIX = "aa02436d"

# statsmodels says this for every fit on ~30-48 monthly points; arima.py
# silences UserWarning at import, but pytest resets filters per test.
pytestmark = pytest.mark.filterwarnings("ignore:Too few observations:UserWarning")


# ── fixtures and builders ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tracked() -> pd.DataFrame:
    df = pd.read_parquet(TRACKED_PATH)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


@pytest.fixture(scope="module")
def served_months(tracked) -> list[pd.Timestamp]:
    return sorted(tracked["timestamp"].unique())


@pytest.fixture()
def cfg() -> dict:
    """The ingest.yaml shape the job will pass (configs/ingest.yaml `gate`).
    last_closed_month is fixed so the future-month rule is deterministic."""
    return {
        "gate": {
            "expected_stations": 50,
            "covariate_rtol": 1e-9,
            "sarima_backtest": {"as_of": "2025-06-30", "wape_pct": 3.21},
        },
        "last_closed_month": "2026-01-31",
    }


def add_month(df: pd.DataFrame, month: str, scale: float = 1.01) -> pd.DataFrame:
    """`df` plus one synthetic month cloned from its last month (all stations)."""
    last = df[df["timestamp"] == df["timestamp"].max()].copy()
    ts = pd.Timestamp(month)
    last["timestamp"] = ts
    last["period"] = ts
    last["month"] = ts.month
    last["ridership"] = last["ridership"] * scale
    return pd.concat([df, last], ignore_index=True)


def names(report: GateReport) -> set[str]:
    return {f.check for f in report.failures}


def check(report: GateReport, name: str):
    return next(c for c in report.checks if c.check == name)


# ── the tracked store and tracked + 2026-01 pass (real backtest) ──────────────

def test_tracked_store_passes_including_the_backtest(tracked, served_months, cfg):
    report = run_gate(tracked, tracked, served_months, cfg)

    assert report.passed, [str(f) for f in report.failures]
    assert report.failures == []
    # Every check ran, and the backtest reproduced the configured figure.
    assert {c.check for c in report.checks} >= {
        "validate_feature_store", "unique_keys", "station_set", "tracked_columns",
        "tracked_keys_present", "ridership_exact", "covariates_within_rtol",
        "served_months_retained", "no_future_month", "sarima_backtest",
    }
    assert all(c.status == "pass" for c in report.checks)
    assert check(report, "sarima_backtest").detail["wape_pct"] == 3.21


def test_tracked_plus_a_synthetic_2026_01_month_passes(tracked, served_months, cfg):
    candidate = add_month(tracked, "2026-01-01")
    report = run_gate(candidate, tracked, served_months, cfg)

    assert report.passed, [str(f) for f in report.failures]
    # The new month cannot move the 2025-06-30 backtest.
    assert check(report, "sarima_backtest").detail["wape_pct"] == 3.21


def test_the_gate_does_not_modify_its_inputs(tracked, served_months, cfg):
    candidate = add_month(tracked, "2026-01-01")
    before_c, before_t = candidate.copy(deep=True), tracked.copy(deep=True)
    run_gate(candidate.drop(index=candidate.index[:1]), tracked, served_months, cfg)
    pd.testing.assert_frame_equal(candidate, before_c)
    pd.testing.assert_frame_equal(tracked, before_t)


def test_tracked_store_file_is_untouched():
    digest = hashlib.sha256(TRACKED_PATH.read_bytes()).hexdigest()
    assert digest.startswith(TRACKED_SHA256_PREFIX)


# ── each tampering fails, with a named reason ─────────────────────────────────

def test_one_changed_ridership_cell_fails(tracked, served_months, cfg):
    candidate = tracked.copy()
    candidate.loc[candidate.index[1234], "ridership"] += 1.0

    report = run_gate(candidate, tracked, served_months, cfg)

    assert not report.passed
    assert "ridership_exact" in names(report)
    f = next(f for f in report.failures if f.check == "ridership_exact")
    assert f.detail["n_changed"] == 1
    assert check(report, "sarima_backtest").status == "skipped"


def test_a_dropped_station_month_fails(tracked, served_months, cfg):
    victim = tracked[(tracked["station_id"] == "EM") & (tracked["timestamp"] == "2025-09-01")]
    assert len(victim) == 1
    candidate = tracked.drop(index=victim.index)

    report = run_gate(candidate, tracked, served_months, cfg)

    assert not report.passed
    assert {"station_set", "tracked_keys_present"} <= names(report)
    f = next(f for f in report.failures if f.check == "station_set")
    assert f.detail["months"]["2025-09"]["missing"] == ["EM"]


def test_an_extra_station_in_a_month_fails(tracked, served_months, cfg):
    extra = tracked[tracked["timestamp"] == "2025-12-01"].iloc[:1].copy()
    extra["station_id"] = "ZZ"
    candidate = pd.concat([tracked, extra], ignore_index=True)

    report = run_gate(candidate, tracked, served_months, cfg)

    assert not report.passed
    assert "station_set" in names(report)


def test_a_duplicate_key_fails(tracked, served_months, cfg):
    candidate = pd.concat([tracked, tracked.iloc[[10]]], ignore_index=True)

    report = run_gate(candidate, tracked, served_months, cfg)

    assert not report.passed
    assert "unique_keys" in names(report)
    f = next(f for f in report.failures if f.check == "unique_keys")
    assert f.detail["n_duplicate_rows"] == 2  # both copies of the key
    # The strict validator independently rejects it.
    assert "validate_feature_store" in names(report)


def test_a_shrunken_month_set_fails(tracked, served_months, cfg):
    """The served store has a month the candidate lacks (here 2026-01, so every
    tracked key is still present: only the month-set rule can catch it)."""
    served = list(served_months) + [pd.Timestamp("2026-01-01")]

    report = run_gate(tracked, tracked, served, cfg)

    assert not report.passed
    assert names(report) == {"served_months_retained"}
    f = report.failures[0]
    assert f.detail["missing"] == ["2026-01"]


def test_a_candidate_that_lost_a_whole_month_fails(tracked, served_months, cfg):
    candidate = tracked[tracked["timestamp"] != "2025-12-01"]

    report = run_gate(candidate, tracked, served_months, cfg)

    assert not report.passed
    assert {"served_months_retained", "tracked_keys_present"} <= names(report)


def test_a_month_after_the_last_closed_month_fails(tracked, served_months, cfg):
    candidate = add_month(tracked, "2026-01-01")
    candidate = add_month(candidate, "2026-02-01")

    report = run_gate(candidate, tracked, served_months, cfg)

    assert not report.passed
    assert names(report) == {"no_future_month"}
    assert report.failures[0].detail["months"] == ["2026-02"]


def test_last_closed_month_argument_overrides_cfg(tracked, served_months, cfg):
    candidate = add_month(tracked, "2026-01-01")
    report = run_gate(candidate, tracked, served_months, cfg,
                      last_closed_month="2025-12-31")
    assert "no_future_month" in names(report)


def test_a_missing_last_closed_month_fails_closed(tracked, served_months, cfg):
    del cfg["last_closed_month"]
    report = run_gate(tracked, tracked, served_months, cfg)
    assert not report.passed
    assert "no_future_month" in names(report)


def test_a_missing_column_fails(tracked, served_months, cfg):
    report = run_gate(tracked.drop(columns=["temp_f"]), tracked, served_months, cfg)
    assert not report.passed
    assert "tracked_columns" in names(report)


# ── the covariate and ridership comparison rules (fast, no backtest) ──────────

def covariate_failures(candidate, tracked, rtol=1e-9):
    return ingest_gate.check_tracked_rows(candidate, tracked, covariate_rtol=rtol)


def test_covariates_within_rtol_pass_and_beyond_fail(tracked):
    near = tracked.copy()
    near["temp_f"] = near["temp_f"] * (1 + 1e-12)
    assert covariate_failures(near, tracked) == []

    far = tracked.copy()
    far["temp_f"] = far["temp_f"] * (1 + 1e-3)
    out = covariate_failures(far, tracked)
    assert [f.check for f in out] == ["covariates_within_rtol"]
    assert "temp_f" in out[0].detail["columns"]


def test_nan_equals_nan_in_covariates(tracked):
    assert tracked["game_start_hour"].isna().any()  # the fixture really has NaNs
    assert covariate_failures(tracked.copy(), tracked) == []

    broken = tracked.copy()
    idx = broken.index[broken["game_start_hour"].notna()][0]
    broken.loc[idx, "game_start_hour"] = np.nan  # a value became NaN: not equal
    out = covariate_failures(broken, tracked)
    assert [f.check for f in out] == ["covariates_within_rtol"]


def test_ridership_must_be_exactly_equal_not_within_rtol(tracked):
    nudged = tracked.copy()
    nudged.loc[nudged.index[0], "ridership"] *= 1 + 1e-12
    out = covariate_failures(nudged, tracked, rtol=1e-6)
    assert [f.check for f in out] == ["ridership_exact"]


def test_non_float_covariates_are_compared_exactly(tracked):
    flipped = tracked.copy()
    flipped.loc[flipped.index[5], "is_holiday"] = not flipped.loc[flipped.index[5], "is_holiday"]
    out = covariate_failures(flipped, tracked)
    assert [f.check for f in out] == ["covariates_within_rtol"]
    assert "is_holiday" in out[0].detail["columns"]


# ── the backtest check ────────────────────────────────────────────────────────

def test_backtest_wape_mismatch_fails_with_a_named_reason(tracked, served_months, cfg, monkeypatch):
    monkeypatch.setattr(ingest_gate, "sarima_backtest_wape", lambda *a, **k: 3.30)
    report = run_gate(tracked, tracked, served_months, cfg)
    assert not report.passed
    assert names(report) == {"sarima_backtest"}
    assert report.failures[0].detail == {"wape_pct": 3.3, "expected_pct": 3.21,
                                         "as_of": "2025-06-30"}


def test_backtest_wape_is_compared_at_two_decimals(tracked, served_months, cfg, monkeypatch):
    monkeypatch.setattr(ingest_gate, "sarima_backtest_wape", lambda *a, **k: 3.2149)
    assert run_gate(tracked, tracked, served_months, cfg).passed
    monkeypatch.setattr(ingest_gate, "sarima_backtest_wape", lambda *a, **k: 3.2151)
    assert not run_gate(tracked, tracked, served_months, cfg).passed


def test_a_backtest_that_cannot_run_is_a_named_failure_not_a_crash(tracked, served_months, cfg, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no statsmodels")
    monkeypatch.setattr(ingest_gate, "sarima_backtest_wape", boom)
    report = run_gate(tracked, tracked, served_months, cfg)
    assert not report.passed
    assert names(report) == {"sarima_backtest"}
    assert "no statsmodels" in report.failures[0].reason


def test_backtest_scores_the_candidate_against_tracked_actuals(tracked):
    """Three stations only, to stay fast. History comes from the candidate and
    actuals from `tracked`: skewing the candidate's history moves the WAPE."""
    model_cfg = ingest_gate.load_model_config()
    small = tracked[tracked["station_id"].isin(["EM", "MT", "WP"])]
    base = ingest_gate.sarima_backtest_wape(small, small, model_cfg, "2025-06-30")
    assert 0 < base < 20

    skewed = small.copy()
    skewed.loc[(skewed["station_id"] == "EM") & (skewed["timestamp"] <= "2025-06-30"),
               "ridership"] *= 3
    assert ingest_gate.sarima_backtest_wape(skewed, small, model_cfg, "2025-06-30") != base


def test_backtest_uses_only_the_six_months_after_as_of(tracked):
    """Months past the 6-month horizon (and the candidate's extra month) never
    enter the score."""
    model_cfg = ingest_gate.load_model_config()
    small = tracked[tracked["station_id"].isin(["EM", "MT", "WP"])]
    base = ingest_gate.sarima_backtest_wape(small, small, model_cfg, "2025-06-30")
    extended = add_month(small, "2026-01-01", scale=5.0)
    assert ingest_gate.sarima_backtest_wape(extended, small, model_cfg, "2025-06-30") == base


def test_report_serialises_to_json(tracked, served_months, cfg):
    import json
    candidate = tracked.copy()
    candidate.loc[candidate.index[0], "ridership"] += 1.0
    report = run_gate(candidate, tracked, served_months, cfg)
    doc = json.loads(json.dumps(report.to_dict()))
    assert doc["passed"] is False
    assert doc["failures"][0]["check"] == "ridership_exact"
    assert {c["check"] for c in doc["checks"]} >= {"sarima_backtest"}
