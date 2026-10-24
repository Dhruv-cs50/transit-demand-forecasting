"""
scripts/interval_test_breakdown.py
──────────────────────────────────
Tail split, width and coverage by month of the Sprint 5 calibrated bands on
the test split, for docs/interval-calibration.md.

This reads the test split. It describes a result the leaderboard has already
scored; it chooses nothing. Run it only after models/baselines/benchmarks.py.

Each band is rebuilt with the same code the leaderboard uses, and its overall
coverage must equal the leaderboard's Coverage_% exactly, or the script stops.
The band each model published before Sprint 5 is rebuilt too, for comparison,
and must reproduce PR #138's published coverage (PREVIOUS).
  SeasonalNaive  forecasts recomputed (benchmarks.py does not save them);
                 calibrator from the study's cached rolling-origin forecasts
  Prophet        the leaderboard run's saved test forecasts
                 (models/baselines/outputs/prophet/prophet_forecasts.parquet)

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
    apply_conformal, fit_conformal, fit_rolling_conformal, no_calibration, with_origin_horizon,
)
from evaluation.interval_study import (  # noqa: E402
    _target_window, cached_forecast, load_validation_store, month_ends, rolling_forecasts, with_actuals,
)
from models.baselines.benchmarks import seasonal_naive_forecast  # noqa: E402

LEADERBOARD = Path("evaluation/outputs/benchmark_leaderboard.csv")
PROPHET_TEST = Path("models/baselines/outputs/prophet/prophet_forecasts.parquet")
# PR #138's published test coverage of the band each model used before Sprint 5.
PREVIOUS = {"SeasonalNaive": ("own band", 94.33), "Prophet": ("split-conformal scaled/horizon", 74.67)}


def breakdown(frame: pd.DataFrame) -> dict:
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
    test = store[store["timestamp"] > val_end]
    train = store[(store["timestamp"] >= pd.Timestamp(cfg["data"]["train_start"]))
                  & (store["timestamp"] <= val_end)]
    leaderboard = pd.read_csv(LEADERBOARD).set_index("model")

    # The calibration pool is built from validation-cut data only, as in the study.
    val_store = load_validation_store(cfg)
    models = cfg["calibration"]["models"]
    preds = {
        "SeasonalNaive": seasonal_naive_forecast(train, test, freq),
        "Prophet": pd.read_parquet(PROPHET_TEST),
    }
    out = {}
    for model, test_preds in preds.items():
        mcfg = models[model]
        assert mcfg.get("scheme") == "rolling", f"{model} is not on the rolling scheme"
        origins = month_ends(pd.Timestamp(mcfg["first_origin"]), val_end - pd.offsets.MonthEnd(1))
        pool = rolling_forecasts(model, val_store, cfg, origins, horizon, refresh=False, cut=val_end)
        calib = fit_rolling_conformal(pool, mcfg["method"], mcfg["group"], 0.8, val_end,
                                      half_life=mcfg["half_life"])
        test_preds = test_preds[["timestamp", "station_id", "p10", "p50", "p90"]].copy()
        test_preds["timestamp"] = pd.to_datetime(test_preds["timestamp"]).dt.tz_localize(None)
        banded = apply_conformal(with_origin_horizon(test_preds, val_end), calib)
        frame = test[["timestamp", "station_id", "ridership"]].merge(
            banded, on=["timestamp", "station_id"], how="left")
        row = breakdown(frame)
        published = float(leaderboard.loc[model, "Coverage_%"])
        if row["Coverage_%"] != published:
            raise SystemExit(f"{model}: recomputed coverage {row['Coverage_%']} != leaderboard {published}")

        # The band published before Sprint 5, rebuilt the way PR #138 built it.
        label, previous = PREVIOUS[model]
        if model == "SeasonalNaive":
            before = no_calibration(test_preds)
        else:
            train_end = pd.Timestamp(cfg["data"]["train_end"])
            val_fc = cached_forecast(model, val_store, cfg, train_end, horizon, refresh=False)
            cal = with_actuals(_target_window(val_store, train_end, horizon), val_fc)
            before = apply_conformal(with_origin_horizon(test_preds, val_end),
                                     fit_conformal(cal, "scaled", "horizon", 0.8))
        before = test[["timestamp", "station_id", "ridership"]].merge(
            before, on=["timestamp", "station_id"], how="left")
        prev_row = breakdown(before)
        if prev_row["Coverage_%"] != previous:
            raise SystemExit(f"{model}: rebuilt previous band covers {prev_row['Coverage_%']}, "
                             f"PR #138 published {previous}")
        out[model] = {"sprint5": {**row, "leaderboard_Coverage_%": published},
                      f"before ({label})": prev_row}

    print(yaml.safe_dump(out, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()
