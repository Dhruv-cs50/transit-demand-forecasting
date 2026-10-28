"""
machine_learning_files/ingest_gate.py
─────────────────────────────────────
The publish gate of the cloud ingestion job (docs/cloud-ingestion-design.md §2
step 5). A rebuilt feature store is published only if `run_gate` passes.

    report = run_gate(candidate, tracked, served_months, cfg)
    report.passed      # bool
    report.failures    # [CheckResult] with status "fail", each with a named `check`
    report.checks      # every check, in order, with status pass / fail / skipped

`candidate` is the store the job just rebuilt, `tracked` the repo's committed
data/processed/feature_store.parquet (the reference), `served_months` the months
of the store the API serves now. Nothing is read from or written to disk, and
neither frame is modified.

Checks, in order (the name is what a failure reports):

    validate_feature_store    evaluation.validators STRICT mode raised
    unique_keys               a (station_id, timestamp) key appears twice
    station_set               a month lacks one of the tracked store's stations,
                              or has one it does not (and the tracked store
                              itself must have gate.expected_stations stations)
    tracked_columns           a tracked column is absent from the candidate
    tracked_keys_present      a tracked (station_id, timestamp) is absent
    ridership_exact          a tracked key's ridership differs at all
                              (NaN equals NaN)
    covariates_within_rtol   another tracked column differs (floats beyond
                              gate.covariate_rtol; NaN equals NaN; other dtypes
                              exactly)
    served_months_retained    the candidate lacks a month the served store has
    no_future_month           a month after the last closed month
    sarima_backtest           SARIMA fitted on the candidate up to `as_of`,
                              scored on the tracked store's next 6 months,
                              does not give gate.sarima_backtest.wape_pct (2 dp)

The backtest runs only when every other check passed (a store with duplicate
keys or missing stations cannot be scored meaningfully, and it is the one slow
check, ~5 s); otherwise it is reported as "skipped". A check that raises is a
failure named after the check, never an exception out of `run_gate`: the gate
fails closed.

`cfg` is the job's configs/ingest.yaml dict (the `gate` section is read; if
there is no `gate` key, `cfg` itself is taken as that section):

    gate:
      expected_stations: 50
      covariate_rtol: 1.0e-9
      sarima_backtest: {as_of: "2025-06-30", wape_pct: 3.21}
    last_closed_month: "2026-09-30"     # or the keyword argument; required

`last_closed_month` is any date inside the last month the job may publish
(`ingest_fetch.last_closed_month_end(today, lag_days)` fits). It is an input,
not read from a clock, so the gate is deterministic.

The backtest repeats `api._run_forecast` for each station: history clipped to
model.yaml's data.train_start and to months <= as_of, `fit_station`, then
`predict_station` for 6 steps; P50 is scored against the tracked store's
actuals with evaluation.metrics.wape pooled over all stations and months, as
models/baselines/benchmarks.py's compute_metrics does.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import numpy as np
import pandas as pd
import yaml

log = logging.getLogger("machine_learning_files.ingest_gate")

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_CONFIG_PATH = REPO_ROOT / "configs" / "model.yaml"

KEY = ["station_id", "timestamp"]
DEFAULT_COVARIATE_RTOL = 1e-9
DEFAULT_EXPECTED_STATIONS = 50
CHECK_ORDER = ["validate_feature_store", "unique_keys", "station_set", "tracked_columns",
               "tracked_keys_present", "ridership_exact", "covariates_within_rtol",
               "served_months_retained", "no_future_month", "sarima_backtest"]
# At most this many offending keys / months are listed in a failure's detail.
MAX_LISTED = 10


# ── result types ──────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    check: str
    status: str                      # "pass" | "fail" | "skipped"
    reason: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def __str__(self) -> str:
        return f"{self.check}: {self.reason}" if self.reason else self.check

    def to_dict(self) -> dict:
        return {"check": self.check, "status": self.status,
                "reason": self.reason, "detail": self.detail}


@dataclass
class GateReport:
    passed: bool
    failures: list[CheckResult]
    checks: list[CheckResult]

    def to_dict(self) -> dict:
        """JSON-ready, for runs/<id>/gate.json."""
        return {"passed": self.passed,
                "failures": [f.to_dict() for f in self.failures],
                "checks": [c.to_dict() for c in self.checks]}


def _ok(check: str, reason: str = "", **detail) -> CheckResult:
    return CheckResult(check, "pass", reason, detail)


def _fail(check: str, reason: str, **detail) -> CheckResult:
    return CheckResult(check, "fail", reason, detail)


# ── helpers ───────────────────────────────────────────────────────────────────

def _month(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m")


def _months(values: Iterable) -> list[str]:
    return sorted({_month(v) for v in values})


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    """A copy with `timestamp` as tz-naive datetime64[ns] (the pandas 3 build
    writes microseconds, the 3.11 / pandas 2.2 job reads whatever it wrote).
    Raises if a timestamp is missing or the column is absent."""
    out = df.copy()
    ts = pd.to_datetime(out["timestamp"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_localize(None)
    if ts.isna().any():
        raise ValueError(f"{int(ts.isna().sum())} row(s) have no timestamp")
    out["timestamp"] = ts.astype("datetime64[ns]")
    return out


def load_model_config(path: Path | str | None = None) -> dict:
    with open(path or MODEL_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _gate_section(cfg: dict) -> dict:
    return cfg["gate"] if isinstance(cfg.get("gate"), dict) else cfg


def _differs(a: pd.Series, b: pd.Series, rtol: Optional[float]) -> np.ndarray:
    """Boolean array, True where `a` and `b` differ. NaN equals NaN. rtol None
    means exact equality; otherwise floats may differ by rtol * |b|."""
    both_na = a.isna().to_numpy() & b.isna().to_numpy()
    one_na = a.isna().to_numpy() ^ b.isna().to_numpy()
    # b is the tracked side: unlike a, its dtype survives the left merge.
    numeric = pd.api.types.is_float_dtype(b)
    if numeric and rtol is not None:
        av = a.to_numpy(dtype="float64", na_value=np.nan)
        bv = b.to_numpy(dtype="float64", na_value=np.nan)
        close = np.isclose(av, bv, rtol=rtol, atol=0.0, equal_nan=True)
        return ~close
    eq = np.asarray((a == b).fillna(False), dtype=bool)
    return ~(eq | both_na) | one_na


# ── individual checks ─────────────────────────────────────────────────────────

def check_validator(candidate: pd.DataFrame) -> CheckResult:
    from evaluation.validators import Severity, ValidationMode, validate_feature_store
    try:
        results = validate_feature_store(candidate, mode=ValidationMode.STRICT)
    except ValueError as e:
        return _fail("validate_feature_store", str(e))
    warnings = [str(r) for r in results if r.severity == Severity.WARNING]
    return _ok("validate_feature_store", "no ERROR-level result", warnings=warnings)


def check_unique_keys(candidate: pd.DataFrame) -> CheckResult:
    dup = candidate.duplicated(subset=KEY, keep=False)
    if dup.any():
        keys = candidate.loc[dup, KEY].drop_duplicates().head(MAX_LISTED)
        return _fail(
            "unique_keys",
            f"{int(dup.sum())} rows share {int(candidate.loc[dup, KEY].drop_duplicates().shape[0])} duplicated (station_id, timestamp) key(s)",
            n_duplicate_rows=int(dup.sum()),
            examples=[f"{r.station_id}@{_month(r.timestamp)}" for r in keys.itertuples()],
        )
    return _ok("unique_keys")


def check_station_set(candidate: pd.DataFrame, tracked: pd.DataFrame,
                      expected_stations: int) -> CheckResult:
    expected = set(tracked["station_id"].unique())
    if len(expected) != expected_stations:
        return _fail(
            "station_set",
            f"the tracked store has {len(expected)} stations, config expects {expected_stations}",
            tracked_stations=len(expected), expected_stations=expected_stations,
        )
    bad: dict[str, dict] = {}
    for ts, stations in candidate.groupby("timestamp")["station_id"]:
        have = set(stations)
        if have != expected:
            bad[_month(ts)] = {"missing": sorted(expected - have),
                               "extra": sorted(have - expected)}
    if bad:
        shown = dict(list(bad.items())[:MAX_LISTED])
        return _fail(
            "station_set",
            f"{len(bad)} month(s) do not have exactly the tracked store's "
            f"{len(expected)} stations (first: {next(iter(shown))})",
            n_months=len(bad), months=shown,
        )
    return _ok("station_set", f"{len(expected)} stations in every month")


def check_tracked_rows(candidate: pd.DataFrame, tracked: pd.DataFrame, *,
                       covariate_rtol: float = DEFAULT_COVARIATE_RTOL) -> list[CheckResult]:
    """The four tracked-store comparisons, as failures only (empty = all pass):
    tracked_columns, tracked_keys_present, ridership_exact,
    covariates_within_rtol. Both frames need normalised timestamps."""
    failures: list[CheckResult] = []

    absent_cols = [c for c in tracked.columns if c not in candidate.columns]
    if absent_cols:
        failures.append(_fail("tracked_columns",
                              f"candidate lacks tracked column(s): {absent_cols}",
                              columns=absent_cols))
    if any(c not in candidate.columns for c in KEY):
        return failures

    cols = [c for c in tracked.columns if c in candidate.columns]
    # Duplicates are reported by unique_keys; compare on the first occurrence
    # so one bad row cannot multiply into many mismatches here.
    merged = tracked[cols].merge(
        candidate[cols].drop_duplicates(subset=KEY, keep="first"),
        on=KEY, how="left", suffixes=("_t", "_c"), indicator="_m",
    )
    absent = merged["_m"] == "left_only"
    if absent.any():
        keys = merged.loc[absent, KEY].head(MAX_LISTED)
        failures.append(_fail(
            "tracked_keys_present",
            f"{int(absent.sum())} tracked (station_id, timestamp) key(s) missing from the candidate",
            n_missing=int(absent.sum()),
            examples=[f"{r.station_id}@{_month(r.timestamp)}" for r in keys.itertuples()],
        ))
    present = merged[~absent]

    if "ridership" in cols:
        bad = _differs(present["ridership_c"], present["ridership_t"], rtol=None)
        if bad.any():
            rows = present.loc[bad].head(MAX_LISTED)
            failures.append(_fail(
                "ridership_exact",
                f"{int(bad.sum())} ridership value(s) differ from the tracked store",
                n_changed=int(bad.sum()),
                examples=[{"station_id": r.station_id, "month": _month(r.timestamp),
                           "tracked": None if pd.isna(r.ridership_t) else float(r.ridership_t),
                           "candidate": None if pd.isna(r.ridership_c) else float(r.ridership_c)}
                          for r in rows.itertuples()],
            ))

    changed: dict[str, int] = {}
    for c in cols:
        if c in KEY or c == "ridership":
            continue
        n = int(_differs(present[f"{c}_c"], present[f"{c}_t"], rtol=covariate_rtol).sum())
        if n:
            changed[c] = n
    if changed:
        failures.append(_fail(
            "covariates_within_rtol",
            f"covariate(s) differ from the tracked store beyond rtol={covariate_rtol:g}: "
            + ", ".join(f"{c} ({n} rows)" for c, n in list(changed.items())[:MAX_LISTED]),
            columns=changed, rtol=covariate_rtol,
        ))
    return failures


def check_served_months(candidate: pd.DataFrame, served_months: Iterable) -> CheckResult:
    have = set(_months(candidate["timestamp"]))
    served = set(_months(served_months))
    missing = sorted(served - have)
    if missing:
        return _fail("served_months_retained",
                     f"candidate lacks {len(missing)} month(s) the served store has: {missing[:MAX_LISTED]}",
                     missing=missing)
    return _ok("served_months_retained", f"all {len(served)} served months present")


def check_no_future_month(candidate: pd.DataFrame, last_closed_month) -> CheckResult:
    if last_closed_month is None:
        return _fail("no_future_month",
                     "last_closed_month was not provided (cfg['last_closed_month'] or the "
                     "keyword argument); the gate cannot rule out an unclosed month")
    limit = pd.Timestamp(last_closed_month).to_period("M").to_timestamp()
    late = candidate.loc[candidate["timestamp"] > limit, "timestamp"]
    if not late.empty:
        return _fail("no_future_month",
                     f"{late.nunique()} month(s) after the last closed month {_month(limit)}: "
                     f"{_months(late)[:MAX_LISTED]}",
                     last_closed_month=_month(limit), months=_months(late))
    return _ok("no_future_month", f"latest month <= {_month(limit)}")


# ── the SARIMA backtest ───────────────────────────────────────────────────────

def sarima_backtest_wape(candidate: pd.DataFrame, tracked: pd.DataFrame,
                         model_cfg: dict, as_of, horizon: Optional[int] = None) -> float:
    """Pooled WAPE (percent, unrounded) of SARIMA P50 forecasts made from
    `candidate` at `as_of`, against `tracked`'s actuals for the next `horizon`
    months (default data.forecast_horizon_steps) after `as_of`.

    Per station this is api._run_forecast: history = candidate rows with
    train_start <= timestamp <= as_of, at least two seasonal cycles of distinct
    months, `fit_station` then `predict_station`. A station that cannot be fitted
    or forecast raises: an incomplete backtest is not a score.
    """
    from evaluation.metrics import wape
    from models.baselines.arima import fit_station, get_sarima_orders, predict_station

    freq = model_cfg["data"].get("resample_freq", "MS")
    horizon = int(horizon or model_cfg["data"].get("forecast_horizon_steps", 6))
    as_of = pd.Timestamp(as_of)
    train_start = model_cfg["data"].get("train_start")
    min_months = get_sarima_orders(freq)["seasonal_order"][3] * 2

    target_months = sorted(tracked.loc[tracked["timestamp"] > as_of, "timestamp"].unique())[:horizon]
    if len(target_months) < horizon:
        raise ValueError(f"the tracked store has {len(target_months)} month(s) after "
                         f"{as_of:%Y-%m-%d}; the backtest needs {horizon}")
    actuals = tracked.loc[tracked["timestamp"].isin(target_months), KEY + ["ridership"]]
    stations = sorted(actuals["station_id"].unique())

    hist = candidate[candidate["timestamp"] <= as_of]
    if train_start:
        hist = hist[hist["timestamp"] >= pd.Timestamp(train_start)]

    preds = []
    for sid in stations:
        sdf = hist[hist["station_id"] == sid]
        n = sdf["timestamp"].nunique()
        if n < min_months:
            raise ValueError(f"{sid}: {n} months of history, SARIMA needs {min_months}")
        fit, last_ts = fit_station(sdf, sid, freq)
        p = predict_station(fit, last_ts, horizon, freq)
        p["station_id"] = sid
        preds.append(p)
    pred = pd.concat(preds, ignore_index=True)

    scored = actuals.merge(pred[["station_id", "timestamp", "p50"]], on=KEY, how="left")
    if scored["p50"].isna().any():
        raise ValueError(f"{int(scored['p50'].isna().sum())} of {len(scored)} station-months got no forecast")
    value = wape(scored["ridership"].to_numpy(dtype=float), scored["p50"].to_numpy(dtype=float))
    if not np.isfinite(value):
        raise ValueError("WAPE is not finite")
    return float(value)


def check_sarima_backtest(candidate: pd.DataFrame, tracked: pd.DataFrame,
                          gate: dict, model_cfg: Optional[dict] = None) -> CheckResult:
    spec = gate.get("sarima_backtest") or {}
    as_of, expected = spec.get("as_of"), spec.get("wape_pct")
    if as_of is None or expected is None:
        return _fail("sarima_backtest",
                     "gate.sarima_backtest needs both as_of and wape_pct in the config")
    model_cfg = model_cfg or load_model_config()
    wape_pct = sarima_backtest_wape(candidate, tracked, model_cfg, as_of, spec.get("horizon"))
    got = round(float(wape_pct), 2)
    detail = {"wape_pct": got, "expected_pct": round(float(expected), 2), "as_of": str(as_of)}
    if got != detail["expected_pct"]:
        return _fail("sarima_backtest",
                     f"SARIMA backtest at as_of={as_of} gives WAPE {got:.2f}%, expected {detail['expected_pct']:.2f}%",
                     **detail)
    return _ok("sarima_backtest", f"WAPE {got:.2f}% at as_of={as_of}", **detail)


# ── the gate ──────────────────────────────────────────────────────────────────

def _guarded(name: str, fn: Callable[[], CheckResult | list[CheckResult]]) -> list[CheckResult]:
    """Run one check; an exception becomes a failure named after the check."""
    try:
        out = fn()
    except Exception as e:  # fail closed: a broken check must not pass the gate
        log.exception("gate check %s raised", name)
        return [_fail(name, f"check raised {type(e).__name__}: {e}")]
    return out if isinstance(out, list) else [out]


def run_gate(candidate: pd.DataFrame, tracked: pd.DataFrame, served_months: Iterable,
             cfg: dict, *, last_closed_month=None,
             model_cfg: Optional[dict] = None) -> GateReport:
    """Run every publish check. See the module docstring.

    last_closed_month overrides cfg["last_closed_month"]; model_cfg defaults to
    configs/model.yaml (only data.train_start / resample_freq / horizon are read).
    """
    gate = _gate_section(cfg)
    if last_closed_month is None:
        last_closed_month = cfg.get("last_closed_month", gate.get("last_closed_month"))
    rtol = float(gate.get("covariate_rtol", DEFAULT_COVARIATE_RTOL))
    expected_stations = int(gate.get("expected_stations", DEFAULT_EXPECTED_STATIONS))

    checks: list[CheckResult] = []

    try:
        cand, ref = _normalise(candidate), _normalise(tracked)
        for df, who in ((cand, "candidate"), (ref, "tracked")):
            missing = [c for c in KEY if c not in df.columns]
            if missing:
                raise ValueError(f"{who} lacks key column(s) {missing}")
    except Exception as e:
        checks.append(_fail("input_frames", f"cannot read the frames: {type(e).__name__}: {e}"))
        checks.append(CheckResult("sarima_backtest", "skipped", "inputs unreadable"))
        return GateReport(False, [c for c in checks if c.status == "fail"], checks)

    checks += _guarded("validate_feature_store", lambda: check_validator(cand))
    checks += _guarded("unique_keys", lambda: check_unique_keys(cand))
    checks += _guarded("station_set", lambda: check_station_set(cand, ref, expected_stations))

    rows = _guarded("tracked_rows", lambda: check_tracked_rows(cand, ref, covariate_rtol=rtol))
    # check_tracked_rows reports failures only; add a pass entry for each check
    # it covers that did not fail, so `checks` always lists all of them.
    failed = {c.check for c in rows if c.status == "fail"}
    for name in ("tracked_columns", "tracked_keys_present", "ridership_exact",
                 "covariates_within_rtol"):
        if name not in failed and "tracked_rows" not in failed:
            checks.append(_ok(name))
    checks += rows

    checks += _guarded("served_months_retained", lambda: check_served_months(cand, served_months))
    checks += _guarded("no_future_month", lambda: check_no_future_month(cand, last_closed_month))

    if any(c.status == "fail" for c in checks):
        checks.append(CheckResult("sarima_backtest", "skipped",
                                  "skipped: a structural check failed; a store that fails them cannot be scored"))
    else:
        checks += _guarded("sarima_backtest", lambda: check_sarima_backtest(cand, ref, gate, model_cfg))

    checks.sort(key=lambda c: CHECK_ORDER.index(c.check) if c.check in CHECK_ORDER else len(CHECK_ORDER))
    failures = [c for c in checks if c.status == "fail"]
    return GateReport(passed=not failures, failures=failures, checks=checks)
