"""
scripts/interval_test_breakdown.py
──────────────────────────────────
Tail split, width and coverage by month of the calibrated bands on the test
split, for docs/interval-calibration.md: Sprint 5's rolling bands for
SeasonalNaive and Prophet, Sprint 6's bias-shifted band for Chronos-1.

This reads the test split. It describes a result the leaderboard has already
scored; it chooses nothing. Run it only after models/baselines/benchmarks.py.

Each band is rebuilt with the leaderboard's calibration code
(evaluation/calibration.py) from the forecasts interval_study.py cached — the
same pool benchmarks.py builds, which the Sprint 5 review checked row by row —
and its overall
coverage must equal the leaderboard's Coverage_% exactly, or the script stops.
The calibrator is the one configs/model.yaml's entry names (fit_band):
fit_rolling_conformal for the Sprint 5 methods, fit_shift_conformal for
`shift_relative` (Sprint 6). The band each model published before its current
one is rebuilt too, for comparison, and must reproduce PR #138's published
coverage (PREVIOUS).
  SeasonalNaive  forecasts recomputed (benchmarks.py does not save them);
                 calibrator from the study's cached rolling-origin forecasts
  Prophet        the leaderboard run's saved test forecasts
                 (models/baselines/outputs/prophet/prophet_forecasts.parquet)
  Chronos-1      the leaderboard run's raw zero-shot test forecasts
                 (evaluation/outputs/chronos2_zeroshot_preds.parquet, written
                 before calibration); shift calibrator from the study's cached
                 rolling-origin forecasts; previous band Sprint 4's split-
                 conformal relative/pooled, fit on the cached 2025-H1 forecast
                 from train_end

Output: one block per model, in that order. SeasonalNaive and Prophet keep
their Sprint 5 block ("sprint5"); Chronos-1's is "sprint6" and carries the
calibrator's bias and width per horizon (4 dp).

Usage:
    python scripts/interval_test_breakdown.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.calibration import (  # noqa: E402
    add_horizon, apply_conformal, fit_conformal, fit_rolling_conformal, fit_shift_conformal,
    no_calibration, with_origin_horizon,
)
from evaluation.interval_study import (  # noqa: E402
    OUT_DIR, _target_window, cache_tag, cached_forecast, chronos_label, load_validation_store,
    month_ends, rolling_forecasts, with_actuals,
)
from models.baselines.benchmarks import seasonal_naive_forecast, select_test_window  # noqa: E402

LEADERBOARD = Path("evaluation/outputs/benchmark_leaderboard.csv")
PROPHET_TEST = Path("models/baselines/outputs/prophet/prophet_forecasts.parquet")
CHRONOS_TEST = Path("evaluation/outputs/chronos2_zeroshot_preds.parquet")
# PR #138's published test coverage of the band each model used before its
# current one (Sprint 5 for SeasonalNaive and Prophet, Sprint 6 for Chronos-1).
PREVIOUS = {"SeasonalNaive": ("own band", 94.33), "Prophet": ("split-conformal scaled/horizon", 74.67),
            "Chronos1_ZeroShot (chronos-t5-small)": ("split-conformal relative/pooled", 72.67)}


def fit_band(pool: pd.DataFrame, mcfg: dict, as_of) -> dict:
    """The calibrator a configs/model.yaml rolling entry deploys, fit on `pool`
    at `as_of` as the leaderboard fits it: `shift_relative` (Sprint 6) with
    fit_shift_conformal, any other method (Sprint 5) with fit_rolling_conformal."""
    if mcfg["method"] == "shift_relative":
        return fit_shift_conformal(pool, group=mcfg["group"], level=0.8, as_of=as_of,
                                   bias_half_life=mcfg["bias_half_life"], half_life=mcfg["half_life"],
                                   bias_at=mcfg["bias_at"])
    return fit_rolling_conformal(pool, mcfg["method"], mcfg["group"], 0.8, as_of,
                                 half_life=mcfg["half_life"])


def by_group(values: dict) -> dict:
    """A calibrator's per-group values (bias, width), in group order, to 4 dp."""
    return {k: round(float(v), 4) for k, v in sorted(values.items())}


def require_cached(model: str, origins, horizon: int, cut) -> None:
    """This script describes; it never fits. Stop if a forecast it needs was
    not left by interval_study.py."""
    missing = [o for o in origins
               if not (OUT_DIR / f"forecast_{cache_tag(model, o, horizon, cut)[0]}.parquet").exists()]
    if missing:
        raise SystemExit(f"{model}: no cached forecast for {len(missing)} origin(s), e.g. "
                         f"{missing[0]:%Y-%m-%d}; run evaluation/interval_study.py first")


def breakdown(frame: pd.DataFrame) -> dict:
    if frame[["p10", "p90"]].isna().any().any():
        raise SystemExit("a test row has no calibrated bound; every column here would be wrong")
    y = frame["ridership"].to_numpy(float)
    lo, hi = frame["p10"].to_numpy(float), frame["p90"].to_numpy(float)
    below, above = y < lo, y > hi
    by_month = frame.assign(_in=~(below | above)).groupby("timestamp")["_in"].mean() * 100
    return {
        "n": len(frame),
        "Coverage_%": round(float(np.mean(~(below | above)) * 100), 2),
        "Below_P10_%": round(float(below.mean() * 100), 2),
        "Above_P90_%": round(float(above.mean() * 100), 2),
        "Width_raw_%_of_P50": round(float(np.mean((frame["p90_raw"] - frame["p10_raw"]) / frame["p50"]) * 100), 2),
        "Width_%_of_P50": round(float(np.mean((hi - lo) / frame["p50"]) * 100), 2),
        "IntervalScore_%": round(float(((hi - lo) + 10 * ((lo - y) * below + (y - hi) * above)).sum()
                                       / y.sum() * 100), 2),
        "Coverage_by_month": " ".join(f"{v:.0f}" for v in by_month.values),
        # How far actuals strayed from P50: the 80th percentile of |y - P50| / P50.
        "AbsRelError_q80_%": round(float(np.quantile(np.abs(y - frame["p50"]) / frame["p50"], 0.8) * 100), 2),
    }


def main():
    cfg = yaml.safe_load(open("configs/model.yaml"))
    val_end = pd.Timestamp(cfg["data"]["val_end"])
    horizon = int(cfg["data"]["forecast_horizon_steps"])
    freq = cfg["data"].get("resample_freq", "MS")

    store = pd.read_parquet("data/processed/feature_store_enriched.parquet")
    store["timestamp"] = pd.to_datetime(store["timestamp"])
    # The leaderboard's test split, val_end < ts <= test_end (raises when
    # data.test_end is missing), so the coverage check below compares the
    # same rows benchmarks.py scored.
    test = select_test_window(store, cfg)
    train = store[(store["timestamp"] >= pd.Timestamp(cfg["data"]["train_start"]))
                  & (store["timestamp"] <= val_end)]
    leaderboard = pd.read_csv(LEADERBOARD).set_index("model")

    # The calibration pool is built from validation-cut data only, as in the study.
    val_store = load_validation_store(cfg)
    models = cfg["calibration"]["models"]
    chronos = chronos_label(cfg)   # the leaderboard row's and the study cache's name
    chronos_preds = pd.read_parquet(CHRONOS_TEST)
    if not (chronos_preds["model_mode"] == "zeroshot").all():
        # Predictor writes this file even when it falls back to seasonal naive.
        raise SystemExit(f"{CHRONOS_TEST}: not every row is a zero-shot Chronos forecast")
    preds = {
        "SeasonalNaive": seasonal_naive_forecast(train, test, freq),
        "Prophet": pd.read_parquet(PROPHET_TEST),
        chronos: chronos_preds,
    }
    # configs/model.yaml's key for each model; only Chronos-1's differs from its name.
    model_keys = {"SeasonalNaive": "SeasonalNaive", "Prophet": "Prophet", chronos: "Chronos"}
    out = {}
    for model, test_preds in preds.items():
        mcfg = models[model_keys[model]]
        assert mcfg.get("scheme") == "rolling", f"{model} is not on the rolling scheme"
        origins = month_ends(pd.Timestamp(mcfg["first_origin"]), val_end - pd.offsets.MonthEnd(1))
        require_cached(model, origins, horizon, val_end)
        pool = rolling_forecasts(model, val_store, cfg, origins, horizon, refresh=False, cut=val_end)
        calib = fit_band(pool, mcfg, val_end)
        test_preds = test_preds[["timestamp", "station_id", "p10", "p50", "p90"]].copy()
        test_preds["timestamp"] = pd.to_datetime(test_preds["timestamp"]).dt.tz_localize(None)
        banded = apply_conformal(with_origin_horizon(test_preds, val_end), calib)
        frame = test[["timestamp", "station_id", "ridership"]].merge(
            banded, on=["timestamp", "station_id"], how="left")
        row = breakdown(frame)
        published = float(leaderboard.loc[model, "Coverage_%"])
        if row["Coverage_%"] != published:
            raise SystemExit(f"{model}: recomputed coverage {row['Coverage_%']} != leaderboard {published}")

        # The band published before the current one, rebuilt the way PR #138 built it.
        label, previous = PREVIOUS[model]
        if model == "SeasonalNaive":
            before = no_calibration(test_preds)
        else:
            train_end = pd.Timestamp(cfg["data"]["train_end"])
            require_cached(model, [train_end], horizon, None)
            val_fc = cached_forecast(model, val_store, cfg, train_end, horizon, refresh=False)
            cal = with_actuals(_target_window(val_store, train_end, horizon), val_fc)
            if model == "Prophet":
                before = apply_conformal(with_origin_horizon(test_preds, val_end),
                                         fit_conformal(cal, "scaled", "horizon", 0.8))
            else:
                # Chronos-1: Sprint 4's split band, applied as benchmarks.py
                # applied a split calibrator (pooled, so the horizon is unused).
                before = apply_conformal(add_horizon(test_preds),
                                         fit_conformal(cal, "relative", "pooled", 0.8))
        before = test[["timestamp", "station_id", "ridership"]].merge(
            before, on=["timestamp", "station_id"], how="left")
        prev_row = breakdown(before)
        if prev_row["Coverage_%"] != previous:
            raise SystemExit(f"{model}: rebuilt previous band covers {prev_row['Coverage_%']}, "
                             f"PR #138 published {previous}")
        if mcfg["method"] == "shift_relative":
            current = {"sprint6": {**row, "leaderboard_Coverage_%": published,
                                   "bias": by_group(calib["bias"]), "width": by_group(calib["width"])}}
        else:
            current = {"sprint5": {**row, "leaderboard_Coverage_%": published}}
        out[model] = {**current, f"before ({label})": prev_row}

    print(yaml.safe_dump(out, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()
