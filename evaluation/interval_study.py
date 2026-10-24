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

Sprint 5 (adaptive_study): calibrations that track recent errors, under the
rule fixed on docs/sprint-board.md before any of these numbers existed.
  pool        forecasts from rolling monthly origins 2023-12-31 .. T - 1 month,
              rows whose target is on or before T, store cut at
              min(origin + 6 months, T)
  windows     B = 2024-H2 scored from T = 2024-06-30, V = 2025-H1 from
              T = 2024-12-31; a candidate must qualify in both
  eligible    incumbent (configs/model.yaml), rolling_hl6 (weighted conformal,
              half-life 6 months) x 3 scores x {pooled, horizon}, aci_origin
              (gamma 0.1) x 3 scores
  diagnostic  rolling_eq, single-window variants, aci_window, monthly_recal
              (the last two use the scored window's own earlier actuals)

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
    GROUPS, METHODS, clip_alpha, default_alphas, add_horizon, apply_conformal, describe,
    fit_aci_conformal, fit_conformal, fit_rolling_conformal, no_calibration, with_origin_horizon,
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

# Sprint 5, fixed on docs/sprint-board.md (6daa610) before measuring.
ROLLING_START = pd.Timestamp("2023-12-31")   # first origin every model can use as deployed
HALF_LIFE = 6                                # months, rolling_hl6
GAMMA = 0.1                                  # ACI step size
SCORES = ("scaled", "relative", "asym_relative")
ELIGIBLE = ("incumbent", "rolling_hl6", "aci_origin")


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


def _store_as_of_window_end(df: pd.DataFrame, origin: pd.Timestamp, horizon: int,
                            cut: pd.Timestamp = None) -> pd.DataFrame:
    """The store a model sees when forecasting from `origin`: history plus the
    forecast window's rows (Chronos reads future covariate rows from it), and
    nothing after — the same shape the leaderboard's test origin sees. A
    rolling-origin forecast for a calibration pool is also cut at the pool's
    cutoff (`cut`), so no row after it reaches the forecast."""
    end = origin + pd.DateOffset(months=horizon)
    if cut is not None:
        end = min(end, cut)
    return df[df["timestamp"] <= end]


def chronos_label(cfg: dict) -> str:
    checkpoint = cfg.get("chronos2", {}).get("model_id", "unknown")
    family = "Chronos2" if "chronos-2" in checkpoint.lower() else "Chronos1"
    return f"{family}_ZeroShot ({checkpoint.split('/')[-1]})"


def forecast(model: str, df: pd.DataFrame, cfg: dict, origin: pd.Timestamp,
             horizon: int, scratch: Path, cut: pd.Timestamp = None) -> pd.DataFrame:
    freq = cfg["data"].get("resample_freq", "MS")
    store = _store_as_of_window_end(df, origin, horizon, cut)
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
                    horizon: int, refresh: bool, cut: pd.Timestamp = None) -> pd.DataFrame:
    tag = f"{model.split(' ')[0]}_{origin:%Y-%m-%d}"
    if cut is not None and cut < origin + pd.DateOffset(months=horizon):
        tag += f"_cut{cut:%Y-%m-%d}"
    else:
        cut = None   # a cut at or after the window end changes nothing
    path = OUT_DIR / f"forecast_{tag}.parquet"
    meta = OUT_DIR / f"forecast_{tag}.meta.yaml"
    if path.exists() and not refresh:
        preds = pd.read_parquet(path)
        if meta.exists():
            preds.attrs.update(yaml.safe_load(meta.read_text()) or {})
        return preds
    scratch = OUT_DIR / "scratch" / tag
    scratch.mkdir(parents=True, exist_ok=True)
    log.info(f"forecasting {model} from {origin:%Y-%m-%d}" + (f", store cut at {cut:%Y-%m-%d}" if cut else ""))
    preds = forecast(model, df, cfg, origin, horizon, scratch, cut)
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


# ── Sprint 5: calibrations that track recent errors ──────────────────────────

def month_ends(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    return list(pd.date_range(start, end, freq="ME"))


def rolling_forecasts(model: str, df: pd.DataFrame, cfg: dict, origins, horizon: int,
                      refresh: bool, cut: pd.Timestamp = None) -> pd.DataFrame:
    """Forecasts from every origin, each with its actuals (left merge, as
    with_actuals) and the explicit origin/horizon columns a pool needs."""
    parts = []
    for o in origins:
        preds = cached_forecast(model, df, cfg, o, horizon, refresh, cut=cut)
        parts.append(with_origin_horizon(with_actuals(_target_window(df, o, horizon), preds), o))
    return pd.concat(parts, ignore_index=True)


def aci_within_window(pool: pd.DataFrame, scored: pd.DataFrame, method: str,
                      as_of: pd.Timestamp) -> pd.DataFrame:
    """Diagnostic: scored month k uses rolling_hl6's quantile at level 1 - alpha_k;
    alpha is updated after each month with that month's miss rate."""
    target = default_alphas(method, LEVEL)
    alpha, parts = target, []
    for _, rows in scored.groupby("timestamp", sort=True):
        # Total weight, not the row count: the weighted quantile is finite only
        # while alpha >= 1 / (total weight + 1).
        n = fit_rolling_conformal(pool, method, "pooled", LEVEL, as_of, half_life=HALF_LIFE)["weight_sum"]
        if method == "asym_relative":
            alpha = (clip_alpha(alpha[0], n), clip_alpha(alpha[1], n))
        else:
            alpha = clip_alpha(alpha, n)
        cal = fit_rolling_conformal(pool, method, "pooled", LEVEL, as_of,
                                    half_life=HALF_LIFE, alphas=alpha)
        out = apply_conformal(rows, cal)
        y = out["ridership"].to_numpy(float)
        below = float(np.mean(y < out["p10"].to_numpy(float)))
        above = float(np.mean(y > out["p90"].to_numpy(float)))
        if method == "asym_relative":
            alpha = (alpha[0] + GAMMA * (target[0] - below), alpha[1] + GAMMA * (target[1] - above))
        else:
            alpha = alpha + GAMMA * (target - (below + above))
        parts.append(out)
    return pd.concat(parts).sort_index()


def monthly_recal(pool_full: pd.DataFrame, scored: pd.DataFrame, method: str,
                  as_of: pd.Timestamp) -> pd.DataFrame:
    """Diagnostic: rolling_hl6 refit before each scored month with every row
    resolved by then (origins <= as_of, including the scored window's own)."""
    parts = []
    for k, (_, rows) in enumerate(scored.groupby("timestamp", sort=True)):
        cutoff = as_of + pd.offsets.MonthEnd(k)
        cal = fit_rolling_conformal(pool_full, method, "pooled", LEVEL, cutoff, half_life=HALF_LIFE)
        parts.append(apply_conformal(rows, cal))
    return pd.concat(parts).sort_index()


def _q_summary(calib: dict) -> str:
    text = describe(calib)
    if calib.get("scheme") == "aci":
        a = calib["alpha_final"]
        text += f"; final alpha {a[0]:.4f}/{a[1]:.4f}" if isinstance(a, tuple) else f"; final alpha {a:.4f}"
    return text


def adaptive_study(df: pd.DataFrame, cfg: dict, models: list[str], frames: dict,
                   model_keys: dict, horizon: int, refresh: bool, val_end: pd.Timestamp) -> dict:
    """Score every Sprint 5 candidate on windows B and V and apply the rule
    fixed on docs/sprint-board.md. Returns the tables and the decision."""
    train_end = pd.Timestamp(cfg["data"]["train_end"]) + pd.offsets.MonthEnd(0)
    windows = {
        # name: (scored origin T, frame key of the scored window, frame key of the previous half-year)
        "B": (train_end - pd.DateOffset(months=horizon) + pd.offsets.MonthEnd(0), "cal", "cal2"),
        "V": (train_end, "eval", "cal"),
    }
    chosen = (cfg.get("calibration") or {}).get("models") or {}

    rows, checks = [], []
    for model in models:
        mcfg = chosen.get(model_keys[model]) or {}
        for wname, (T, scored_key, prev_key) in windows.items():
            scored = with_origin_horizon(frames[(model, scored_key)], T)
            prev = frames[(model, prev_key)]
            origins = month_ends(ROLLING_START, T - pd.offsets.MonthEnd(1))
            pool = rolling_forecasts(model, df, cfg, origins, horizon, refresh, cut=T)
            pool_full = pd.concat([rolling_forecasts(model, df, cfg, origins, horizon, refresh),
                                   scored], ignore_index=True)
            assert pool["timestamp"].max() <= val_end and pool_full["timestamp"].max() <= val_end, \
                "a pool row falls after val_end"

            # Store-cut check: a forecast cut at T must equal the uncut one on shared rows.
            key = ["timestamp", "station_id", "origin"]
            both = pool.merge(pool_full, on=key, suffixes=("_cut", "_full"))
            diff = max(float(np.nanmax(np.abs(both[f"{c}_cut"] - both[f"{c}_full"]))) for c in ("p10", "p50", "p90"))
            checks.append({"model": model, "window": wname, "T": f"{T:%Y-%m-%d}", "origins": len(origins),
                           "pool_rows_resolved": int(((pool["timestamp"] <= T)
                                                      & pool["ridership"].notna()).sum()),
                           "cut_vs_uncut_max_abs_diff": diff, "shared_rows": len(both)})

            def add(candidate, scheme, method, group, eligible, out, calib_text):
                rows.append({"model": model, "window": wname, "candidate": candidate, "scheme": scheme,
                             "method": method, "group": group, "eligible": eligible,
                             "calibrator": calib_text, **score(out, val_end)})

            # Incumbent: the current configs/model.yaml entry, fit on the previous half-year.
            imethod = mcfg.get("method", "none")
            if imethod in (None, "none"):
                add("incumbent", "own band", "-", "-", True, no_calibration(scored), "own band")
            else:
                igroup = mcfg.get("group", "pooled")
                calib = fit_conformal(prev, imethod, igroup, LEVEL)
                add("incumbent", "single", imethod, igroup, True, apply_conformal(scored, calib), describe(calib))

            for method in SCORES:
                for group in ("pooled", "horizon"):
                    for scheme, hl, eligible in (("rolling_hl6", HALF_LIFE, True), ("rolling_eq", None, False)):
                        calib = fit_rolling_conformal(pool, method, group, LEVEL, T, half_life=hl)
                        add(f"{scheme} {method}/{group}", scheme, method, group, eligible,
                            apply_conformal(scored, calib), describe(calib))
                    calib = fit_conformal(prev, method, group, LEVEL)
                    add(f"single {method}/{group}", "single", method, group, False,
                        apply_conformal(scored, calib), describe(calib))
                calib = fit_aci_conformal(pool, method, LEVEL, T, gamma=GAMMA)
                add(f"aci_origin {method}/pooled", "aci_origin", method, "pooled", True,
                    apply_conformal(scored, calib), _q_summary(calib))
                add(f"aci_window {method}/pooled", "aci_window", method, "pooled", False,
                    aci_within_window(pool, scored, method, T), "per month")
                add(f"monthly_recal {method}/pooled", "monthly_recal", method, "pooled", False,
                    monthly_recal(pool_full, scored, method, T), "per month")

    cand = pd.DataFrame(rows)
    checks = pd.DataFrame(checks)

    # ── The rule (docs/sprint-board.md, Sprint 5) ─────────────────────────────
    elig = cand[cand["eligible"]].copy()
    elig["passes"] = (elig["Coverage_%"].between(*BAND)
                      & (elig["Below_P10_%"] <= MAX_TAIL_MISS)
                      & (elig["Above_P90_%"] <= MAX_TAIL_MISS))
    wide = elig.pivot_table(index=["model", "candidate"], columns="window",
                            values=["passes", "Coverage_%", "Below_P10_%", "Above_P90_%", "IntervalScore_%"],
                            aggfunc="first")
    wide.columns = [f"{v}_{w}" for v, w in wide.columns]
    sel = wide.reset_index()
    # A window with no row (NaN) is a failure, never a pass.
    sel["qualifies"] = sel["passes_B"].eq(True) & sel["passes_V"].eq(True)
    sel["mean_IntervalScore_%"] = ((sel["IntervalScore_%_B"] + sel["IntervalScore_%_V"]) / 2).round(2)
    sel = sel.drop(columns=["passes_B", "passes_V"]).sort_values(["model", "mean_IntervalScore_%"])

    q = sel[sel["qualifies"]]
    common = (q[q["candidate"] != "incumbent"].groupby("candidate")
              .agg(models=("model", "nunique"), mean_score=("mean_IntervalScore_%", "mean")))
    common = common[common["models"] == len(models)].sort_values("mean_score")
    decision = {}
    if not common.empty:
        winner = common.index[0]
        decision = {m: {"choice": winner, "basis": "one method qualifies for every model"} for m in models}
    else:
        for m in models:
            qm = q[q["model"] == m].sort_values("mean_IntervalScore_%")
            if qm.empty:
                decision[m] = {"choice": "keep current entry", "basis": "no eligible candidate qualifies"}
            else:
                decision[m] = {"choice": qm.iloc[0]["candidate"], "basis": "lowest-scoring qualifier for this model",
                               "mean_IntervalScore_%": float(qm.iloc[0]["mean_IntervalScore_%"])}
    return {"candidates": cand, "selection": sel, "common": common.reset_index(),
            "checks": checks, "decision": decision}


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

    # ── Deployed calibrators: fit on 2025-H1, as benchmarks.py will ────────────
    # benchmarks.py fits each model's calibrator on its validation-window
    # forecasts (fit ending train_end) — the same forecasts as the "eval"
    # frames here — so these are the quantiles the test band will use.
    model_keys = {"SeasonalNaive": "SeasonalNaive", "SARIMA": "SARIMA",
                  "Prophet": "Prophet", chronos_label(cfg): "Chronos"}
    chosen = (cfg.get("calibration") or {}).get("models") or {}
    deployed = []
    for model in models:
        mcfg = chosen.get(model_keys[model]) or {}
        if mcfg.get("method", "none") == "none":
            deployed.append({"model": model, "calibrator": f"none ({mcfg.get('reason', 'not listed')})"})
            continue
        calib = fit_conformal(frames[(model, "eval")], mcfg["method"], mcfg.get("group", "pooled"), LEVEL)
        deployed.append({"model": model, "calibrator": describe(calib),
                         "q": {k: [round(x, 4) for x in v] if isinstance(v, tuple) else round(v, 4)
                               for k, v in calib["q"].items()}})

    # ── Sprint 5: calibrations that track recent errors ────────────────────────
    adaptive = adaptive_study(df, cfg, models, frames, model_keys, horizon, args.refresh, val_end)

    # ── Write ──────────────────────────────────────────────────────────────────
    adaptive["candidates"].to_csv(OUT_DIR / "adaptive_candidates.csv", index=False)
    adaptive["selection"].to_csv(OUT_DIR / "adaptive_selection.csv", index=False)
    adaptive["checks"].to_csv(OUT_DIR / "adaptive_checks.csv", index=False)
    (OUT_DIR / "adaptive_decision.yaml").write_text(
        yaml.safe_dump(adaptive["decision"], sort_keys=False, allow_unicode=True))
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
    print("=== Deployed calibrators (configs/model.yaml), fit on 2025-H1 validation forecasts ===")
    print(yaml.safe_dump(deployed, sort_keys=False, allow_unicode=True))

    print("\n=== Sprint 5: pools and store-cut check ===")
    print(adaptive["checks"].to_string(index=False))
    cols = ["model", "window", "candidate", "eligible", "Coverage_%", "Below_P10_%", "Above_P90_%",
            "Width_%_of_P50", "IntervalScore_%", "Coverage_by_month"]
    print("\n=== Sprint 5: every candidate, windows B (2024-H2) and V (2025-H1) ===")
    print(adaptive["candidates"][cols].to_string(index=False))
    print("\n=== Sprint 5: eligible candidates under the fixed rule (both windows) ===")
    print(adaptive["selection"].to_string(index=False))
    print("\nCommon qualifiers (every model):")
    print(adaptive["common"].to_string(index=False) if not adaptive["common"].empty else "  none")
    print("\nDecision:")
    print(yaml.safe_dump(adaptive["decision"], sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()
