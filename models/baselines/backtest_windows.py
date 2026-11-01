"""
models/baselines/backtest_windows.py
────────────────────────────────────
All four leaderboard models on three half-year windows, so "SARIMA is best"
rests on more than the one published test window.

    window    fit through   forecast
    2024-H2   2024-06-30    Jul–Dec 2024
    2025-H1   2024-12-31    Jan–Jun 2025
    2025-H2   2025-06-30    Jul–Dec 2025   (the published test window)

SARIMA, Prophet, Chronos-1 zero-shot and seasonal naive run through the same
functions, configs/model.yaml settings and seeds as models/baselines/
benchmarks.py: run_arima_all_stations, run_prophet_all_stations, Predictor
(zero-shot, store cut at the window's last month, as benchmarks.py cuts its
calibration windows) and seasonal_naive_forecast, with the same `train_start`
rule, the same 50 stations and the same 6 steps. No new model code, no tuning.
Each window sees only rows on or before its `fit_through`; a month after it
only reaches the scoring.

Bands are each model's OWN band, never a calibrated one: the calibrators are
fit on data to 2025-06-30, so applying them to the 2024 windows would score a
band fitted on its own future. `coverage_own_band` is therefore comparable
across windows; on 2025-H2 it equals the leaderboard's Coverage_raw_%, not its
Coverage_%.

Hard check: before anything is written, the 2025-H2 rows must equal the
leaderboard's overall row for the same model in WAPE_%, MAE and n (and
Coverage_raw_% against `coverage_own_band`). If they differ, the run stops with
the differences and writes nothing.

Writes, under --out-dir (default evaluation/outputs):
    backtest_windows.csv           one row per window x model
    backtest_windows_stations.csv  the same per station
    backtest_windows/<window>/<model>.parquet   the forecasts scored

`stations_sarima_beats` is the number of stations where SARIMA's WAPE is lower
than the model's in that window (empty for SARIMA). Nothing in the output
carries a timestamp, so two runs write identical bytes.

Usage (from the repo root, after models/baselines/benchmarks.py):
    python models/baselines/backtest_windows.py
    python models/baselines/backtest_windows.py --feature-store data/processed/feature_store_enriched.parquet
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

# Run as a script, sys.path[0] is models/baselines/; make the repo root importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.calibration import no_calibration  # noqa: E402
from evaluation.metrics import mae as metric_mae, wape as metric_wape  # noqa: E402
from models.baselines import benchmarks  # noqa: E402

log = logging.getLogger("backtest_windows")

# fit_through is the last day the models may see; the forecast is the six months
# after it. The third window is the published test window (checked against
# configs/model.yaml in check_windows).
WINDOWS = [
    {"id": "2024-H2", "fit_through": "2024-06-30", "first_month": "2024-07", "last_month": "2024-12"},
    {"id": "2025-H1", "fit_through": "2024-12-31", "first_month": "2025-01", "last_month": "2025-06"},
    {"id": "2025-H2", "fit_through": "2025-06-30", "first_month": "2025-07", "last_month": "2025-12"},
]
PUBLISHED_WINDOW = "2025-H2"
SARIMA = "SARIMA"
OWN_BAND_LABEL = "raw: the model's own band"

CSV_COLUMNS = ["window", "fit_through", "first_month", "last_month", "model",
               "wape", "mae", "n", "n_expected", "coverage_own_band", "stations_sarima_beats"]
STATION_COLUMNS = ["window", "model", "station_id", "wape", "mae", "n"]
OUT_DIR = Path("evaluation/outputs")


# ── Windows ────────────────────────────────────────────────────────────────────

def month_end(month: str) -> pd.Timestamp:
    """Last day of "YYYY-MM"."""
    return pd.Timestamp(f"{month}-01") + pd.offsets.MonthEnd(0)


def check_windows(windows: list[dict], cfg: dict) -> None:
    """Each window is the six months right after its fit_through, and the
    published one is the config's test window. Raises ValueError otherwise."""
    horizon = int(cfg["data"].get("forecast_horizon_steps") or cfg["chronos2"]["prediction_length_steps"])
    for w in windows:
        fit = pd.Timestamp(w["fit_through"])
        if fit != fit + pd.offsets.MonthEnd(0):
            raise ValueError(f"window {w['id']}: fit_through {w['fit_through']} is not a month end")
        first = (fit + pd.Timedelta(days=1)).strftime("%Y-%m")
        last = (fit + pd.DateOffset(months=horizon)).strftime("%Y-%m")
        if (w["first_month"], w["last_month"]) != (first, last):
            raise ValueError(
                f"window {w['id']}: forecasts months {w['first_month']}..{w['last_month']} but "
                f"{horizon} steps after {w['fit_through']} are {first}..{last}"
            )
    published = next(w for w in windows if w["id"] == PUBLISHED_WINDOW)
    val_end = pd.Timestamp(cfg["data"]["val_end"])
    test_end = benchmarks.config_test_end(cfg)
    if pd.Timestamp(published["fit_through"]) != val_end or month_end(published["last_month"]) != test_end:
        raise ValueError(
            f"window {PUBLISHED_WINDOW} ({published['fit_through']}..{published['last_month']}) is not the "
            f"config's test window (val_end {val_end:%Y-%m-%d}, test_end {test_end:%Y-%m-%d})"
        )


def window_frames(df: pd.DataFrame, cfg: dict, window: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(train, test) for a window. train: rows from data.train_start through
    fit_through, as benchmarks.run_benchmarks builds its train_df. test: the
    window's months, the rows that are scored."""
    fit = benchmarks.match_store_tz(df, pd.Timestamp(window["fit_through"]))
    end = benchmarks.match_store_tz(df, month_end(window["last_month"]))
    train = df[df["timestamp"] <= fit]
    train_start = cfg["data"].get("train_start")
    if train_start:
        train = train[train["timestamp"] >= benchmarks.match_store_tz(df, pd.Timestamp(train_start))]
    test = df[(df["timestamp"] > fit) & (df["timestamp"] <= end)]
    return train, test


# ── Models: the benchmark's own functions ──────────────────────────────────────

def chronos_label(cfg: dict) -> str:
    """The leaderboard's label for the Chronos row (see benchmarks.run_benchmarks)."""
    checkpoint = cfg.get("chronos2", {}).get("model_id", "unknown")
    family = "Chronos2" if "chronos-2" in checkpoint.lower() else "Chronos1"
    return f"{family}_ZeroShot ({checkpoint.split('/')[-1]})"


def model_labels(cfg: dict) -> list[str]:
    return [SARIMA, "Prophet", chronos_label(cfg), "SeasonalNaive"]


def forecast_window(df: pd.DataFrame, cfg: dict, window: dict, predictor, scratch: Path) -> dict[str, pd.DataFrame]:
    """Every model's forecasts for one window, keyed by leaderboard label, each
    with timestamp, station_id, p10, p50, p90 (the model's own band)."""
    freq = cfg["data"].get("resample_freq", "MS")
    horizon_steps = cfg["data"].get("forecast_horizon_steps") or cfg["chronos2"].get("prediction_length_steps")
    fit = benchmarks.match_store_tz(df, pd.Timestamp(window["fit_through"]))
    end = benchmarks.match_store_tz(df, month_end(window["last_month"]))
    train, test = window_frames(df, cfg, window)
    out: dict[str, pd.DataFrame] = {}

    log.info(f"[{window['id']}] seasonal naive")
    out["SeasonalNaive"] = benchmarks.seasonal_naive_forecast(train, test, freq)

    from models.baselines.arima import run_arima_all_stations
    log.info(f"[{window['id']}] SARIMA")
    out[SARIMA] = run_arima_all_stations(
        df, cfg, output_dir=scratch / "arima", train_cutoff=fit, horizon_steps=horizon_steps, freq=freq)

    from models.baselines.prophet_baseline import run_prophet_all_stations
    log.info(f"[{window['id']}] Prophet")
    out["Prophet"] = run_prophet_all_stations(
        df, cfg, output_dir=scratch / "prophet", train_cutoff=fit, horizon_steps=horizon_steps, freq=freq)

    log.info(f"[{window['id']}] Chronos zero-shot")
    # The store is cut at the window's last month, as benchmarks.py cuts its
    # calibration windows; for the published window that is the whole store.
    out[chronos_label(cfg)] = benchmarks._forecast_checked(
        predictor, fit, end, scratch / "chronos" / f"{window['id']}.parquet", "zeroshot")

    keep = ["timestamp", "station_id", "p10", "p50", "p90"]
    return {label: preds[keep].sort_values(["station_id", "timestamp"]).reset_index(drop=True)
            for label, preds in out.items() if preds is not None and not preds.empty}


# ── Scoring ────────────────────────────────────────────────────────────────────

def score_model(test: pd.DataFrame, train: pd.DataFrame, preds: pd.DataFrame, label: str) -> tuple[dict, pd.DataFrame]:
    """(overall row, per-station rows) for one model on one window, scored as
    benchmarks.compute_metrics scores the leaderboard, on the model's own band."""
    rows = benchmarks.compute_metrics(test, no_calibration(preds), label, train_df=train,
                                      interval_method=OWN_BAND_LABEL)
    overall = next((r for r in rows if r["slice"] == "overall"), None)
    if overall is None:
        raise RuntimeError(f"{label}: no forecast overlaps the window")
    if not benchmarks.accept_model_rows(rows, label):
        raise RuntimeError(f"{label}: rejected (forecast {overall['n']} of {overall['n_expected']} rows, "
                           f"WAPE {overall['WAPE_%']})")

    merged = test[["timestamp", "station_id", "ridership"]].merge(
        preds[["timestamp", "station_id", "p50"]], on=["timestamp", "station_id"], how="left")
    stations = []
    for station_id, grp in merged.groupby("station_id"):
        y = grp["ridership"].to_numpy(dtype=float)
        p = np.maximum(grp["p50"].to_numpy(dtype=float), 0)
        stations.append({"model": label, "station_id": str(station_id), "wape": metric_wape(y, p),
                         "mae": metric_mae(y, p), "n": int(np.sum(~np.isnan(y) & ~np.isnan(p)))})
    return overall, pd.DataFrame(stations)


def run_backtest(df: pd.DataFrame, cfg: dict, windows: list[dict] = WINDOWS,
                 forecaster=forecast_window) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Run every model on every window. Returns (windows x models table,
    per-station table, {window id: {label: forecasts}}). `forecaster` is
    forecast_window; tests pass a stand-in."""
    check_windows(windows, cfg)
    labels = model_labels(cfg)
    summary, per_station, forecasts = [], [], {}
    predictor = None
    with tempfile.TemporaryDirectory(prefix="backtest-windows-") as tmp:
        for w in windows:
            if predictor is None and forecaster is forecast_window:
                from models.chronos2.predict import Predictor
                predictor = Predictor()
            preds_by_model = forecaster(df, cfg, w, predictor, Path(tmp) / w["id"])
            absent = [m for m in labels if m not in preds_by_model]
            if absent:
                raise RuntimeError(f"[{w['id']}] no forecasts from {absent}")
            if predictor is not None and getattr(predictor, "mode", None) != "zeroshot":
                raise RuntimeError(f"[{w['id']}] Chronos backend mode is {getattr(predictor, 'mode', None)!r}, "
                                   f"not 'zeroshot'; seasonal-naive fallbacks must not be scored as Chronos")
            train, test = window_frames(df, cfg, w)
            forecasts[w["id"]] = preds_by_model
            for label in labels:
                overall, stations = score_model(test, train, preds_by_model[label], label)
                summary.append({
                    "window": w["id"], "fit_through": w["fit_through"],
                    "first_month": w["first_month"], "last_month": w["last_month"], "model": label,
                    "wape": overall["WAPE_%"], "mae": overall["MAE"], "n": overall["n"],
                    "n_expected": overall["n_expected"], "coverage_own_band": overall["Coverage_%"],
                })
                per_station.append(stations.assign(window=w["id"]))
    table = pd.DataFrame(summary)
    stations = pd.concat(per_station, ignore_index=True)[STATION_COLUMNS]
    table["stations_sarima_beats"] = [
        sarima_beats(stations, row.window, row.model) for row in table.itertuples(index=False)]
    return table[CSV_COLUMNS], stations, forecasts


def sarima_beats(stations: pd.DataFrame, window: str, model: str) -> float:
    """Stations where SARIMA's WAPE is lower than `model`'s in `window`; NaN for SARIMA."""
    if model == SARIMA:
        return np.nan
    w = stations[stations["window"] == window]
    a = w[w["model"] == SARIMA].set_index("station_id")["wape"]
    b = w[w["model"] == model].set_index("station_id")["wape"]
    both = a.index.intersection(b.index)
    return float((a.loc[both] < b.loc[both]).sum())


# ── The hard check ─────────────────────────────────────────────────────────────

def check_against_leaderboard(table: pd.DataFrame, leaderboard: pd.DataFrame) -> list[str]:
    """Differences between the published window's rows and the leaderboard's
    overall rows (WAPE_%, MAE, n, and Coverage_raw_% for coverage_own_band).
    Empty when they agree exactly."""
    problems = []
    overall = leaderboard[leaderboard["slice"] == "overall"]
    rows = table[table["window"] == PUBLISHED_WINDOW]
    if set(rows["model"]) != set(overall["model"].astype(str)):
        problems.append(f"models differ: backtest {sorted(rows['model'])} vs leaderboard {sorted(overall['model'].astype(str))}")
    for row in rows.itertuples(index=False):
        lb = overall[overall["model"].astype(str) == row.model]
        if len(lb) != 1:
            problems.append(f"{row.model}: {len(lb)} overall leaderboard rows")
            continue
        lb = lb.iloc[0]
        for ours, theirs, name in ((row.wape, lb["WAPE_%"], "WAPE_%"), (row.mae, lb["MAE"], "MAE"),
                                   (row.n, lb["n"], "n"), (row.coverage_own_band, lb["Coverage_raw_%"], "Coverage_raw_%")):
            if not (float(ours) == float(theirs)):
                problems.append(f"{row.model}: {name} {ours} != leaderboard {theirs}")
    return problems


# ── Output ─────────────────────────────────────────────────────────────────────

def slug(label: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in label).strip("_")


def write_outputs(table: pd.DataFrame, stations: pd.DataFrame, forecasts: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_dir / "backtest_windows.csv", index=False)
    stations.to_csv(out_dir / "backtest_windows_stations.csv", index=False)
    for window, by_model in forecasts.items():
        d = out_dir / "backtest_windows" / window
        d.mkdir(parents=True, exist_ok=True)
        for label, preds in by_model.items():
            preds.assign(model=label).to_parquet(d / f"{slug(label)}.parquet", index=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="All four models on three half-year windows")
    parser.add_argument("--feature-store", type=Path, default=None,
                        help="default: the enriched store if present, else the committed one (as benchmarks.py)")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--leaderboard", type=Path, default=OUT_DIR / "benchmark_leaderboard.csv")
    args = parser.parse_args(argv)

    if not args.leaderboard.exists():
        log.error(f"{args.leaderboard} not found: run models/baselines/benchmarks.py first; "
                  f"the {PUBLISHED_WINDOW} rows are checked against it")
        return 1
    path = args.feature_store
    if path is None:
        path = benchmarks.PROCESSED_DIR / "feature_store_enriched.parquet"
        if not path.exists():
            path = benchmarks.PROCESSED_DIR / "feature_store.parquet"
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    cfg = benchmarks.load_config()

    table, stations, forecasts = run_backtest(df, cfg)
    problems = check_against_leaderboard(table, pd.read_csv(args.leaderboard))
    if problems:
        log.error("the %s rows do not equal the leaderboard; nothing written:\n  %s",
                  PUBLISHED_WINDOW, "\n  ".join(problems))
        return 1
    write_outputs(table, stations, forecasts, args.out_dir)
    print(table.to_string(index=False))
    log.info(f"{PUBLISHED_WINDOW} rows equal the leaderboard (WAPE, MAE, n, own-band coverage); "
             f"wrote {args.out_dir / 'backtest_windows.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
