"""Caltrain benchmark across half-year holdout windows.

Scores four models on the half-year windows of ``configs/caltrain.yaml`` that pass the
admission rule, calling the BART model functions unchanged:

``SeasonalNaive``  ``benchmarks.seasonal_naive_forecast``, univariate
``SARIMA``         ``arima.fit_station`` / ``predict_station`` with exog = every step
                   column (``electrified`` and each ``method_*``)
``Prophet``        ``prophet_baseline.fit_station`` / ``predict_station`` with the same
                   columns as added regressors
``Chronos1_...``   the zero-shot ``Predictor`` path, univariate

The step columns are scheduled changes, so the six window months carry their configured
values as known-future covariates. They come from the config dates
(``electrification_start``, ``method_changes``), never from the store rows after the
cutoff, and no ``ridership`` after a window's cutoff reaches any fit: each model is given
the ``train_start <= timestamp <= cutoff`` slice only.

A candidate window is admitted when it has at least ``min_train_months`` usable months
before the cutoff, complete actuals, and every step column that is 1 anywhere in the
window has at least ``min_step_support_months`` months at 1 before the cutoff. Which
windows pass is computed, written to ``windows.csv`` with the reason for each rejection,
and never padded.

Outputs, all under ``evaluation/outputs/caltrain/`` (gitignored):
``leaderboard.csv`` (window, model, wape, mae, n, coverage_own_band, status; wape and
coverage are percentages, coverage scores the model's own p10-p90 band, uncalibrated),
``windows.csv`` and ``forecasts_<model>.parquet``.

Run ``python -m models.caltrain.benchmark`` from the repository root.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from machine_learning_files.caltrain_store import STATION_ID, load_config, step_column
from models.baselines import arima, prophet_baseline
from models.baselines.benchmarks import (
    accept_model_rows,
    compute_metrics,
    seasonal_naive_forecast,
)

log = logging.getLogger("caltrain_benchmark")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "evaluation" / "outputs" / "caltrain"
STORE_PATH = ROOT / "data" / "processed" / "caltrain_store.parquet"
FREQ = "MS"

LEADERBOARD_COLUMNS = ["window", "model", "wape", "mae", "n", "coverage_own_band", "status"]
INSUFFICIENT = "insufficient history"
# model key -> forecasts_<slug>.parquet
SLUGS = {
    "SeasonalNaive": "seasonal_naive",
    "SARIMA": "sarima",
    "Prophet": "prophet",
    "Chronos1": "chronos1",
}


# ── Schedule and slices ────────────────────────────────────────────────────────

def _month(value: str) -> pd.Timestamp:
    return pd.Timestamp(f"{value}-01")


def schedule_columns(cfg: dict) -> list[str]:
    """The step columns, in store order: ``electrified`` then one per method change
    inside the training window (``>= train_start``)."""
    train_start = _month(cfg["train_start"])
    changes = [c for c in sorted(cfg["method_changes"]) if _month(c) >= train_start]
    return ["electrified"] + [step_column(c) for c in changes]


def known_schedule(cfg: dict, months: pd.DatetimeIndex) -> pd.DataFrame:
    """Raw 0/1 step columns for `months`, computed from the config dates alone."""
    months = pd.DatetimeIndex(months)
    train_start = _month(cfg["train_start"])
    out = {"electrified": (months >= _month(cfg["electrification_start"])).astype("int64")}
    for change in sorted(cfg["method_changes"]):
        if _month(change) >= train_start:
            out[step_column(change)] = (months >= _month(change)).astype("int64")
    return pd.DataFrame(out, index=months)


def training_slice(store: pd.DataFrame, cfg: dict, cutoff: pd.Timestamp) -> pd.DataFrame:
    """The only rows a fit may see: ``train_start <= timestamp <= cutoff``, without the
    excluded months, oldest first."""
    excluded = {_month(m) for m in cfg["exclude"]}
    ts = pd.to_datetime(store["timestamp"])
    keep = (ts >= _month(cfg["train_start"])) & (ts <= cutoff) & ~ts.isin(excluded)
    keep &= store["station_id"] == STATION_ID
    return store[keep].sort_values("timestamp").reset_index(drop=True)


# ── Window rule ────────────────────────────────────────────────────────────────

def evaluate_windows(store: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """One row per candidate window with its admission verdict.

    Columns: window, start, end, cutoff, role (test / development / rejected), admitted,
    reason (empty when admitted), insufficient_history, usable_months, actual_months,
    and for every step column ``pre_<col>`` (months at 1 in train_start..cutoff) and
    ``win_<col>`` (months at 1 inside the window). Steps come from the config schedule.
    """
    bench = cfg["benchmark"]
    horizon = int(bench["horizon_steps"])
    min_train = int(bench["min_train_months"])
    min_support = int(bench["min_step_support_months"])
    cols = schedule_columns(cfg)
    excluded = {_month(m) for m in cfg["exclude"]}
    have = store.loc[
        (store["station_id"] == STATION_ID) & store["ridership"].notna(), "timestamp"
    ]
    have = set(pd.to_datetime(have))

    rows = []
    for w in bench["windows"]:
        start, end, cutoff = _month(w["start"]), _month(w["end"]), _month(w["cutoff"])
        if cutoff != start - pd.DateOffset(months=1):
            raise ValueError(
                f"window {w['name']}: cutoff {w['cutoff']} must be the month before start {w['start']}"
            )
        months = pd.date_range(start, end, freq=FREQ)
        if len(months) != horizon:
            raise ValueError(f"window {w['name']}: {len(months)} months, horizon_steps is {horizon}")

        train_months = pd.date_range(_month(cfg["train_start"]), cutoff, freq=FREQ)
        train_months = pd.DatetimeIndex([m for m in train_months if m not in excluded])
        usable = pd.DatetimeIndex([m for m in train_months if m in have])
        missing_actuals = [m.strftime("%Y-%m") for m in months if m not in have]

        reasons = []
        insufficient = len(usable) < min_train
        if insufficient:
            reasons.append(f"insufficient history ({len(usable)} < {min_train} usable months before the cutoff)")
        elif len(usable) < len(train_months):
            gaps = [m.strftime("%Y-%m") for m in train_months if m not in have]
            reasons.append(f"gap in training months ({', '.join(gaps)})")
        if missing_actuals:
            reasons.append(f"incomplete actuals (missing {', '.join(missing_actuals)})")

        train_sched = known_schedule(cfg, usable)
        win_sched = known_schedule(cfg, months)
        detail = {}
        for col in cols:
            pre, win = int(train_sched[col].sum()), int(win_sched[col].sum())
            detail[f"pre_{col}"], detail[f"win_{col}"] = pre, win
            if win > 0 and pre < min_support:
                reasons.append(
                    f"{col} is 1 in {win} window month(s) but has {pre} < {min_support} "
                    f"months at 1 before the cutoff"
                )
        admitted = not reasons
        role = "rejected"
        if admitted:
            role = "test" if w["name"] == bench["test_window"] else "development"
        rows.append({
            "window": w["name"], "start": w["start"], "end": w["end"], "cutoff": w["cutoff"],
            "role": role, "admitted": admitted, "reason": "; ".join(reasons),
            "insufficient_history": insufficient,
            "usable_months": len(usable), "actual_months": len(months) - len(missing_actuals),
            **detail,
        })
    return pd.DataFrame(rows)


# ── Models ─────────────────────────────────────────────────────────────────────

def _with_schedule(train: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    out = train.copy()
    sched = known_schedule(cfg, pd.DatetimeIndex(out["timestamp"]))
    for col in sched.columns:
        out[col] = sched[col].to_numpy()
    return out


def _seasonal_naive(train, months, cfg, cutoff):
    test = pd.DataFrame({"timestamp": months, "station_id": STATION_ID})
    return seasonal_naive_forecast(train, test, FREQ)


def _sarima(train, months, cfg, cutoff):
    cols = schedule_columns(cfg)
    fit_df = _with_schedule(train, cfg)
    exog, mean, sd = arima._standardised_train_exog(fit_df, cols, FREQ)
    fit, last_ts = arima.fit_station(fit_df, STATION_ID, FREQ, exog=exog)
    if last_ts != cutoff:
        raise RuntimeError(f"SARIMA fit ends {last_ts:%Y-%m}, expected the cutoff {cutoff:%Y-%m}")
    future = (known_schedule(cfg, months) - mean) / sd
    return arima.predict_station(fit, last_ts, len(months), FREQ, exog_future=future)


def _prophet(train, months, cfg, cutoff):
    cols = schedule_columns(cfg)
    fit_df = _with_schedule(train, cfg)
    model, _ = prophet_baseline.fit_station(
        fit_df, STATION_ID, {"prophet": cfg["prophet"]}, regressors=cols
    )
    return prophet_baseline.predict_station(
        model, len(months), cutoff, FREQ, future_regressors=known_schedule(cfg, months)[cols]
    )


def chronos_label() -> str:
    """The row name for the Chronos checkpoint that runs, as benchmarks.py names it."""
    from models.chronos2.predict import Predictor

    checkpoint = Predictor().cfg.get("chronos2", {}).get("model_id", "unknown")
    family = "Chronos2" if "chronos-2" in checkpoint.lower() else "Chronos1"
    return f"{family}_ZeroShot ({checkpoint.split('/')[-1]})"


def _chronos(train, months, cfg, cutoff):
    """Zero-shot Chronos through the shared Predictor, univariate.

    The Predictor reads its feature store from disk and is a process-wide singleton, so
    its store is swapped for the training slice for the call and restored afterwards.
    The slice ends at the cutoff, so it has no future rows and cannot leak.
    """
    from models.chronos2.predict import Predictor

    predictor = Predictor()
    horizon = predictor.cfg["data"].get("forecast_horizon_steps") \
        or predictor.cfg["chronos2"].get("prediction_length_steps")
    if horizon != len(months):
        raise RuntimeError(f"Predictor horizon is {horizon} steps, the window has {len(months)}")
    saved_store, saved_mode = predictor._store, predictor._mode
    try:
        predictor._store = train[["timestamp", "station_id", "ridership"]].copy()
        preds = predictor.forecast_all_stations(as_of=cutoff, force_mode="zeroshot")
        if predictor.mode != "zeroshot":
            raise RuntimeError(f"Chronos did not run (backend mode {predictor.mode!r})")
    finally:
        predictor._store, predictor._mode = saved_store, saved_mode
    if preds.empty:
        raise RuntimeError("Chronos produced no forecast")
    # generated_at is a wall-clock stamp; it must not reach the outputs.
    return preds[["timestamp", "p10", "p50", "p90"]]


def _model_runners() -> list[tuple[str, str, object]]:
    return [
        ("SeasonalNaive", "SeasonalNaive", _seasonal_naive),
        ("SARIMA", "SARIMA", _sarima),
        ("Prophet", "Prophet", _prophet),
        ("Chronos1", chronos_label(), _chronos),
    ]


# ── Scoring ────────────────────────────────────────────────────────────────────

def _normalised(preds: pd.DataFrame, months: pd.DatetimeIndex, label: str) -> pd.DataFrame:
    out = preds[["timestamp", "p10", "p50", "p90"]].copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"]).astype("datetime64[us]")
    out = out.sort_values("timestamp").reset_index(drop=True)
    if list(out["timestamp"]) != list(months.astype("datetime64[us]")):
        raise RuntimeError(f"{label} forecast months {list(out['timestamp'])} are not the window months")
    out["station_id"] = STATION_ID
    return out


def _score_cell(window: str, label: str, preds: pd.DataFrame, actuals: pd.DataFrame) -> dict:
    rows = compute_metrics(actuals, preds, label)
    overall = next((r for r in rows if r["slice"] == "overall"), None)
    if overall is None:
        raise RuntimeError("no overlapping forecast rows")
    status = "ok"
    if not accept_model_rows(rows, label):
        status = "rejected: forecast missing rows or WAPE above the plausibility ceiling"
    return {
        "window": window, "model": label, "wape": overall["WAPE_%"], "mae": overall["MAE"],
        "n": overall["n"], "coverage_own_band": overall["Coverage_%"], "status": status,
    }


def _empty_cell(window: str, label: str, status: str) -> dict:
    return {"window": window, "model": label, "wape": np.nan, "mae": np.nan, "n": 0,
            "coverage_own_band": np.nan, "status": status}


def run_caltrain_benchmark(
    store: pd.DataFrame, cfg: dict, out_dir: Path | str | None = None
) -> pd.DataFrame:
    """Run the four models on every admitted window and write the outputs.

    Returns the leaderboard: one row per window x model with columns window, model, wape,
    mae, n, coverage_own_band, status. ``status`` is ``ok``, ``insufficient history``
    (a window with fewer than ``min_train_months`` usable months: an explicit empty cell,
    never a zero), or a ``failed: ...`` / ``rejected: ...`` note for a cell that broke at
    run time. Writes only under `out_dir` (default ``evaluation/outputs/caltrain``).
    """
    out_dir = Path(out_dir) if out_dir is not None else DEFAULT_OUT_DIR
    store = store.copy()
    store["timestamp"] = pd.to_datetime(store["timestamp"]).astype("datetime64[us]")
    windows = evaluate_windows(store, cfg)
    test_window = cfg["benchmark"]["test_window"]
    admitted = windows[windows["admitted"]]
    if test_window not in set(admitted["window"]):
        raise ValueError(f"configured test window {test_window} was not admitted")
    runners = _model_runners()

    cells: list[dict] = []
    forecasts = {key: [] for key in SLUGS}
    for w in windows.itertuples():
        if not w.admitted:
            if w.insufficient_history:
                cells += [_empty_cell(w.window, label, INSUFFICIENT) for _, label, _ in runners]
            else:
                log.info("window %s not admitted: %s", w.window, w.reason)
            continue
        cutoff = _month(w.cutoff)
        months = pd.date_range(_month(w.start), _month(w.end), freq=FREQ)
        train = training_slice(store, cfg, cutoff)
        actuals = store[store["timestamp"].isin(months.astype("datetime64[us]"))
                        & (store["station_id"] == STATION_ID)][["timestamp", "station_id", "ridership"]]
        for key, label, runner in runners:
            try:
                preds = _normalised(runner(train, months, cfg, cutoff), months, label)
                cell = _score_cell(w.window, label, preds, actuals)
            except Exception as exc:  # an explicit failed cell, never a dropped row
                log.error("%s on %s failed: %s", label, w.window, exc)
                cells.append(_empty_cell(w.window, label, f"failed: {type(exc).__name__}: {exc}"))
                continue
            cells.append(cell)
            forecasts[key].append(preds.assign(window=w.window, model=label))

    leaderboard = pd.DataFrame(cells, columns=LEADERBOARD_COLUMNS)
    leaderboard["n"] = leaderboard["n"].astype("int64")

    out_dir.mkdir(parents=True, exist_ok=True)
    leaderboard.to_csv(out_dir / "leaderboard.csv", index=False)
    windows.to_csv(out_dir / "windows.csv", index=False)
    cols = ["window", "model", "timestamp", "station_id", "p10", "p50", "p90"]
    for key, slug in SLUGS.items():
        frames = forecasts[key]
        frame = pd.concat(frames, ignore_index=True)[cols] if frames else pd.DataFrame(columns=cols)
        frame.to_parquet(out_dir / f"forecasts_{slug}.parquet", index=False)
    return leaderboard


def main() -> None:
    cfg = load_config()
    store = pd.read_parquet(STORE_PATH)
    leaderboard = run_caltrain_benchmark(store, cfg)
    windows = pd.read_csv(DEFAULT_OUT_DIR / "windows.csv")
    pd.set_option("display.width", 200, "display.max_colwidth", 120)
    print(windows[["window", "role", "usable_months", "reason"]].to_string(index=False))
    print(leaderboard.to_string(index=False))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
