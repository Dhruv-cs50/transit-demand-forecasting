"""
evaluation/interval_study.py
────────────────────────────
Validation-only comparison of ways to make the P10/P90 bands usable as 80%
intervals. Produces the tables in docs/interval-calibration.md.

The test split (after data.val_end) is the clean holdout, so this script never
loads it: the feature store is cut at val_end on read, and every scored
timestamp is asserted to be on or before val_end.

Protocol (mirrors how the leaderboard calibrates, one window earlier):
  calibration  forecast 2024-H2 from a fit that ends 2024-06-30
  evaluation   forecast 2025-H1 (the validation split) from a fit that ends
               at data.train_end, widen with the calibration-window quantile,
               score coverage on 2025-H1
The leaderboard then does the same one step later: calibrate on 2025-H1
(fit ending train_end), apply to 2025-H2 (fit ending val_end).

Every forecast comes from the code path benchmarks.py uses for that model,
with only the forecast origin changed.

Sensitivity checks, reported but not used to choose a method:
  - two calibration windows (2024-H1 + 2024-H2). SARIMA's airline model gets
    exactly its 24-observation minimum on the 2024-H1 fit.
  - station-fold cross-validation inside 2025-H1 (calibrate on 40 stations,
    score the other 10). No time shift, so optimistic by construction.

Prophet with full posterior sampling (mcmc_samples) is measured as well. In
MCMC mode Prophet's yhat comes from posterior-mean parameters instead of the
MAP fit, so its P50 (and WAPE) differ from the leaderboard model's; it is
scored as a hybrid whose MCMC offsets are re-anchored on the MAP P50.

Usage:
    python evaluation/interval_study.py            # reuse cached forecasts
    python evaluation/interval_study.py --refresh  # refit every model
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.calibration import (  # noqa: E402
    GROUPS, METHODS, add_horizon, apply_conformal, describe, fit_conformal,
)
from evaluation.metrics import coverage  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("interval_study")
log.setLevel(logging.INFO)

PROCESSED_DIR = Path("data/processed")
CONFIG_PATH = Path("configs/model.yaml")
OUT_DIR = Path("evaluation/outputs/interval_study")

LEVEL = 0.8
ALPHA = 1 - LEVEL
# Pre-declared (docs/sprint-board.md, Sprint 4): a method qualifies if every
# model lands in this validation coverage band with neither tail above
# MAX_TAIL_MISS; among qualifiers the lowest mean relative interval score wins.
BAND = (75.0, 85.0)
MAX_TAIL_MISS = 15.0
MCMC_SAMPLES = 400      # 4 chains x 200 post-warmup draws = 800 posterior draws
N_FOLDS = 5


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_validation_store(cfg: dict) -> pd.DataFrame:
    """Feature store with everything after val_end removed at read time."""
    path = PROCESSED_DIR / "feature_store_enriched.parquet"
    if not path.exists():
        path = PROCESSED_DIR / "feature_store.parquet"
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if df["timestamp"].dt.tz is not None:
        raise ValueError("interval_study assumes the tz-naive feature store")
    val_end = pd.Timestamp(cfg["data"]["val_end"])
    df = df[df["timestamp"] <= val_end].reset_index(drop=True)
    assert df["timestamp"].max() <= val_end, "test-split rows leaked into the study"
    return df


# ── Forecasts per model and origin (same code paths as benchmarks.py) ─────────

def _target_window(df: pd.DataFrame, origin: pd.Timestamp, horizon: int) -> pd.DataFrame:
    end = origin + pd.DateOffset(months=horizon)
    return df[(df["timestamp"] > origin) & (df["timestamp"] <= end)]


def _store_as_of_window_end(df: pd.DataFrame, origin: pd.Timestamp, horizon: int) -> pd.DataFrame:
    """The store a model sees when forecasting from `origin`: history plus the
    forecast window's rows (Chronos reads future covariate rows from it), and
    nothing after — the same shape the leaderboard's test origin sees."""
    return df[df["timestamp"] <= origin + pd.DateOffset(months=horizon)]


def chronos_label(cfg: dict) -> str:
    checkpoint = cfg.get("chronos2", {}).get("model_id", "unknown")
    family = "Chronos2" if "chronos-2" in checkpoint.lower() else "Chronos1"
    return f"{family}_ZeroShot ({checkpoint.split('/')[-1]})"


def forecast(model: str, df: pd.DataFrame, cfg: dict, origin: pd.Timestamp,
             horizon: int, scratch: Path) -> pd.DataFrame:
    freq = cfg["data"].get("resample_freq", "MS")
    store = _store_as_of_window_end(df, origin, horizon)
    train_start = pd.Timestamp(cfg["data"]["train_start"])

    if model == "SeasonalNaive":
        from models.baselines.benchmarks import seasonal_naive_forecast
        train = store[(store["timestamp"] >= train_start) & (store["timestamp"] <= origin)]
        return seasonal_naive_forecast(train, _target_window(store, origin, horizon), freq)

    if model == "SARIMA":
        from models.baselines.arima import run_arima_all_stations
        return run_arima_all_stations(store, cfg, output_dir=scratch, train_cutoff=origin,
                                      horizon_steps=horizon, freq=freq)

    if model == "Prophet":
        from models.baselines.prophet_baseline import run_prophet_all_stations
        return run_prophet_all_stations(store, cfg, output_dir=scratch, train_cutoff=origin,
                                        horizon_steps=horizon, freq=freq)

    if model == "Prophet_MCMC":
        return prophet_mcmc_forecast(store, cfg, origin, horizon, freq, scratch)

    if model == chronos_label(cfg):
        from models.chronos2.predict import Predictor
        predictor = Predictor()
        saved = predictor._store
        # Predictor reads the on-disk store by default, which includes the
        # test split. Hand it the truncated one for this call only.
        predictor._store = store
        try:
            preds = predictor.forecast_all_stations(
                as_of=origin, output_path=scratch / "chronos_preds.parquet", force_mode="zeroshot")
        finally:
            predictor._store = saved
        if predictor.mode != "zeroshot":
            raise RuntimeError(f"Chronos did not run (mode={predictor.mode!r})")
        return preds

    raise ValueError(model)


def prophet_mcmc_forecast(store: pd.DataFrame, cfg: dict, origin: pd.Timestamp,
                          horizon: int, freq: str, scratch: Path) -> pd.DataFrame:
    """Prophet exactly as prophet_baseline.fit_station builds it, but with full
    posterior sampling. fit_station constructs `prophet.Prophet` at call time,
    so a seeded MCMC subclass is swapped in for the duration of the run; every
    other setting (Fourier order, holidays, changepoint prior, the numpy seed
    for predictive noise) stays the leaderboard model's.

    np.random.seed does not reach Stan's sampler, so the Stan seed is passed
    to fit() and from there to cmdstanpy."""
    import prophet
    from models.baselines import prophet_baseline

    seed = int(cfg.get("prophet", {}).get("seed", 42))
    diagnostics = []

    class _MCMCProphet(prophet.Prophet):
        def __init__(self, *args, **kwargs):
            kwargs["mcmc_samples"] = MCMC_SAMPLES
            super().__init__(*args, **kwargs)

        def fit(self, df, **kwargs):
            out = super().fit(df, seed=seed, show_progress=False, **kwargs)
            diagnostics.append(int(np.sum(self.params["divergent__"])))
            return out

    real = prophet.Prophet
    prophet.Prophet = _MCMCProphet
    try:
        t0 = time.time()
        preds = prophet_baseline.run_prophet_all_stations(
            store, cfg, output_dir=scratch, train_cutoff=origin, horizon_steps=horizon, freq=freq)
        elapsed = time.time() - t0
    finally:
        prophet.Prophet = real
    preds["model"] = "Prophet_MCMC"
    preds.attrs["divergent_transitions"] = int(sum(diagnostics))
    preds.attrs["fit_seconds"] = round(elapsed, 1)
    return preds


def cached_forecast(model: str, df: pd.DataFrame, cfg: dict, origin: pd.Timestamp,
                    horizon: int, refresh: bool) -> pd.DataFrame:
    tag = f"{model.split(' ')[0]}_{origin:%Y-%m-%d}"
    path = OUT_DIR / f"forecast_{tag}.parquet"
    meta = OUT_DIR / f"forecast_{tag}.meta.yaml"
    if path.exists() and not refresh:
        preds = pd.read_parquet(path)
        if meta.exists():
            preds.attrs.update(yaml.safe_load(meta.read_text()) or {})
        return preds
    scratch = OUT_DIR / "scratch" / tag
    scratch.mkdir(parents=True, exist_ok=True)
    log.info(f"forecasting {model} from {origin:%Y-%m-%d}")
    preds = forecast(model, df, cfg, origin, horizon, scratch)
    attrs = dict(preds.attrs)
    preds = preds[["timestamp", "station_id", "p10", "p50", "p90"]].copy()
    preds["timestamp"] = pd.to_datetime(preds["timestamp"])
    if preds["timestamp"].dt.tz is not None:
        preds["timestamp"] = preds["timestamp"].dt.tz_localize(None)
    preds.to_parquet(path, index=False)
    meta.write_text(yaml.safe_dump(attrs))
    return preds


def with_actuals(actuals: pd.DataFrame, preds: pd.DataFrame) -> pd.DataFrame:
    """Every actual kept (left merge), as benchmarks.compute_metrics does, so a
    missing forecast surfaces as NaN instead of dropping out."""
    out = actuals[["timestamp", "station_id", "ridership"]].merge(
        preds[["timestamp", "station_id", "p10", "p50", "p90"]],
        on=["timestamp", "station_id"], how="left")
    return add_horizon(out)


# ── Scoring ────────────────────────────────────────────────────────────────────

def score(frame: pd.DataFrame, val_end: pd.Timestamp) -> dict:
    assert frame["timestamp"].max() <= val_end, "scored a test-split row"
    y = frame["ridership"].to_numpy(float)
    lo = frame["p10"].to_numpy(float)
    mid = frame["p50"].to_numpy(float)
    hi = frame["p90"].to_numpy(float)
    cov = coverage(y, lo, hi)
    if np.isnan(cov):
        return {"n": len(frame), "Coverage_%": np.nan}
    below, above = y < lo, y > hi
    interval_score = (hi - lo) + (2 / ALPHA) * ((lo - y) * below + (y - hi) * above)
    per_month = frame.assign(_in=~(below | above)).groupby("timestamp")["_in"].mean() * 100
    return {
        "n": len(frame),
        "Coverage_%": round(cov, 2),
        "Below_P10_%": round(below.mean() * 100, 2),
        "Above_P90_%": round(above.mean() * 100, 2),
        "Width_%_of_P50": round(np.mean((hi - lo) / mid) * 100, 2),
        "IntervalScore_%": round(interval_score.sum() / y.sum() * 100, 2),
        "Coverage_by_month": " ".join(f"{v:.0f}" for v in per_month.values),
    }


def station_folds(frame: pd.DataFrame, method: str, group: str) -> pd.DataFrame:
    stations = sorted(frame["station_id"].unique(), key=str)
    fold_of = {s: i % N_FOLDS for i, s in enumerate(stations)}
    fold = frame["station_id"].map(fold_of)
    parts = []
    for k in range(N_FOLDS):
        calib = fit_conformal(frame[fold != k], method, group, LEVEL)
        parts.append(apply_conformal(frame[fold == k], calib))
    return pd.concat(parts).sort_index()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--refresh", action="store_true", help="refit every model")
    args = parser.parse_args()

    cfg = load_config()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_validation_store(cfg)
    val_end = pd.Timestamp(cfg["data"]["val_end"])
    train_end = pd.Timestamp(cfg["data"]["train_end"])
    horizon = int(cfg["data"]["forecast_horizon_steps"])

    origins = {
        "eval": train_end,                                   # -> 2025-H1 (validation)
        "cal": train_end - pd.DateOffset(months=horizon),    # -> 2024-H2
        "cal2": train_end - pd.DateOffset(months=2 * horizon),  # -> 2024-H1 (sensitivity)
    }
    origins = {k: v + pd.offsets.MonthEnd(0) for k, v in origins.items()}
    log.info("origins: " + ", ".join(f"{k}={v:%Y-%m-%d}" for k, v in origins.items()))

    models = ["SeasonalNaive", "SARIMA", "Prophet", chronos_label(cfg)]
    frames = {}
    for model in models:
        for key, origin in origins.items():
            preds = cached_forecast(model, df, cfg, origin, horizon, args.refresh)
            frames[(model, key)] = with_actuals(_target_window(df, origin, horizon), preds)

    rows, sens_rows = [], []
    for model in models:
        ev, cal, cal2 = (frames[(model, k)] for k in ("eval", "cal", "cal2"))
        rows.append({"model": model, "method": "raw", "group": "-", "q": "-", **score(ev, val_end)})
        for method in METHODS:
            for group in GROUPS:
                calib = fit_conformal(cal, method, group, LEVEL)
                rows.append({"model": model, "method": method, "group": group,
                             "q": describe(calib), **score(apply_conformal(ev, calib), val_end)})
                both = pd.concat([cal, cal2], ignore_index=True)
                calib2 = fit_conformal(both, method, group, LEVEL)
                sens_rows.append({"check": "cal=2024-H1+H2", "model": model, "method": method,
                                  "group": group, **score(apply_conformal(ev, calib2), val_end)})
                if group != "station":
                    sens_rows.append({"check": "station-fold CV in 2025-H1", "model": model,
                                      "method": method, "group": group,
                                      **score(station_folds(ev, method, group), val_end)})

    table = pd.DataFrame(rows)
    sens = pd.DataFrame(sens_rows)

    # ── Prophet MCMC (measured, not eligible) ──────────────────────────────────
    map_ev = frames[("Prophet", "eval")]
    mcmc = cached_forecast("Prophet_MCMC", df, cfg, origins["eval"], horizon, args.refresh)
    mcmc_ev = with_actuals(_target_window(df, origins["eval"], horizon), mcmc)
    hybrid = map_ev.copy()
    aligned = map_ev[["timestamp", "station_id"]].merge(mcmc_ev, on=["timestamp", "station_id"], how="left")
    hybrid["p10"] = (map_ev["p50"].values + (aligned["p10"] - aligned["p50"]).values).clip(min=0)
    hybrid["p90"] = map_ev["p50"].values + (aligned["p90"] - aligned["p50"]).values
    y = map_ev["ridership"].to_numpy(float)
    mcmc_rows = [
        {"variant": "MCMC, own P50", **score(mcmc_ev, val_end),
         "WAPE_%": round(np.abs(mcmc_ev["p50"] - y).sum() / y.sum() * 100, 2)},
        {"variant": "MCMC offsets on MAP P50", **score(hybrid, val_end),
         "WAPE_%": round(np.abs(map_ev["p50"] - y).sum() / y.sum() * 100, 2)},
    ]
    shift = (np.abs(aligned["p50"].values - map_ev["p50"].values) / map_ev["p50"].values) * 100
    mcmc_note = {
        "mcmc_samples": MCMC_SAMPLES,
        "divergent_transitions": mcmc.attrs.get("divergent_transitions"),
        "fit_seconds_50_stations": mcmc.attrs.get("fit_seconds"),
        "p50_shift_vs_MAP_mean_%": round(float(np.mean(shift)), 2),
        "p50_shift_vs_MAP_max_%": round(float(np.max(shift)), 2),
    }
    # Determinism: refit one station twice; the bands must match exactly.
    st = sorted(df["station_id"].unique(), key=str)[0]
    one = df[df["station_id"] == st]
    a = prophet_mcmc_forecast(one, cfg, origins["eval"], horizon, "MS", OUT_DIR / "scratch" / "det_a")
    b = prophet_mcmc_forecast(one, cfg, origins["eval"], horizon, "MS", OUT_DIR / "scratch" / "det_b")
    mcmc_note["two_runs_identical"] = bool(
        np.array_equal(a[["p10", "p50", "p90"]].values, b[["p10", "p50", "p90"]].values))

    # ── Selection, by the pre-declared rule ─────────────────────────────────────
    cand = table[table["method"] != "raw"].copy()
    cand["in_band"] = (cand["Coverage_%"].between(*BAND)
                       & (cand["Below_P10_%"] <= MAX_TAIL_MISS)
                       & (cand["Above_P90_%"] <= MAX_TAIL_MISS))
    per_method = cand.groupby(["method", "group"]).agg(
        all_models_qualify=("in_band", "all"),
        mean_interval_score=("IntervalScore_%", "mean"),
        worst_coverage_gap=("Coverage_%", lambda c: float(np.max(np.abs(c - 80)))),
    ).reset_index().sort_values("mean_interval_score")
    qualifiers = per_method[per_method["all_models_qualify"]]
    winner = qualifiers.iloc[0] if not qualifiers.empty else None

    # ── Write ──────────────────────────────────────────────────────────────────
    table.to_csv(OUT_DIR / "validation_methods.csv", index=False)
    sens.to_csv(OUT_DIR / "validation_sensitivity.csv", index=False)
    per_method.to_csv(OUT_DIR / "validation_selection.csv", index=False)
    pd.DataFrame(mcmc_rows).to_csv(OUT_DIR / "validation_prophet_mcmc.csv", index=False)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.max_colwidth", 60)
    print("\n=== Validation coverage (calibrate on 2024-H2, score 2025-H1) ===")
    print(table.to_string(index=False))
    print("\n=== Selection (pre-declared: every model 75–85%, tails <= 15%; lowest mean interval score) ===")
    print(per_method.to_string(index=False))
    if winner is not None:
        print(f"\nWINNER: {winner['method']}/{winner['group']}")
    else:
        print("\nNo single method qualifies for every model.")
        best = cand[cand["in_band"]].sort_values("IntervalScore_%").groupby("model").head(1)
        print("Per-model qualifiers with the lowest interval score:")
        print(best[["model", "method", "group", "Coverage_%", "IntervalScore_%"]].to_string(index=False))
    print("\n=== Sensitivity (not used for selection) ===")
    print(sens.to_string(index=False))
    print("\n=== Prophet MCMC on 2025-H1 (not eligible) ===")
    print(pd.DataFrame(mcmc_rows).to_string(index=False))
    print(yaml.safe_dump(mcmc_note, sort_keys=False))


if __name__ == "__main__":
    main()
