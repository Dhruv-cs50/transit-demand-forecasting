"""
models/baselines/benchmarks.py
─────────────────────────────────
Head-to-head comparison of all models on the held-out test set.

Models compared:
  1. Seasonal Naive   — repeat same-time-last-week (zero-effort baseline)
  2. SARIMA           — classical statistical model
  3. Prophet          — classical + holidays + regressors
  4. Chronos (zero-shot) — foundation model, no fine-tuning

Produces:
  - Leaderboard table (WAPE, MAE, RMSE, MAPE, MASE)
  - Per-slice breakdown (game days, rainy days, AM peak, PM peak)
  - Latex-ready table for your project report

Usage:
    python models/baselines/benchmarks.py
    python models/baselines/benchmarks.py --quick   # skip slow baselines
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# Run as a script, sys.path[0] is models/baselines/, so sibling top-level
# packages are not importable and `from evaluation.metrics import ...` raises
# ModuleNotFoundError before anything executes. run_pipeline.sh invokes this
# file exactly that way, so step 6 never produced a leaderboard — which is why
# export_website_data.py kept taking its validation-split fallback.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.metrics import wape, mae, rmse, mape, smape, coverage, mase, _infer_seasonal_period
from evaluation.calibration import (
    add_horizon, apply_conformal, describe, fit_conformal, fit_rolling_conformal, fit_shift_conformal,
    interval_plan, no_calibration, save_calibrator, with_origin_horizon,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("benchmarks")

PROCESSED_DIR = Path("data/processed")
EVAL_DIR      = Path("evaluation/outputs")
CONFIG_PATH   = Path("configs/model.yaml")
# Calibration-window forecasts (validation split, from fits ending at
# train_end) go here, so they never overwrite the test forecasts each model
# saves under its default path.
CAL_DIR       = EVAL_DIR / "calibration"
# Fitted calibrators, one JSON per model key, read back by
# scripts/export_website_data.py through evaluation.calibration.serve_band.
CALIBRATOR_DIR = CAL_DIR / "calibrators"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── Test window ────────────────────────────────────────────────────────────────

def config_test_end(cfg: dict) -> pd.Timestamp:
    """data.test_end, the last timestamp the test split may hold (inclusive).

    There is no default. Without an end the test split is everything after
    val_end, so a month appended to the feature store (the nightly pipeline
    rebuilds it) would enter the test split and change every published number.
    """
    value = (cfg.get("data") or {}).get("test_end")
    if value is None or str(value).strip() == "":
        raise ValueError(
            "config data.test_end is missing: the test window is "
            "val_end < ts <= test_end and needs an explicit end (configs/model.yaml "
            "sets test_end: \"2025-12-31\"); without it a month added to the feature "
            "store would silently enter the test split"
        )
    return pd.Timestamp(value)


def match_store_tz(df: pd.DataFrame, ts: pd.Timestamp) -> pd.Timestamp:
    """`ts` in the same tz space as df["timestamp"]."""
    # Compare in the same tz space as df["timestamp"] — the feature store
    # is tz-naive by default, so hard-coding tz-aware cutoffs here raises
    # "Invalid comparison between dtype=datetime64[ns] and Timestamp".
    if df["timestamp"].dt.tz is not None:
        return ts.tz_localize("America/Los_Angeles") if ts.tzinfo is None \
            else ts.tz_convert("America/Los_Angeles")
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def select_test_window(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """The test split: rows with val_end < timestamp <= test_end.

    Both bounds come from cfg["data"] and are matched to the store's tz.
    Raises ValueError when data.test_end is missing or not after val_end.
    """
    val_end = match_store_tz(df, pd.Timestamp(cfg["data"]["val_end"]))
    test_end = match_store_tz(df, config_test_end(cfg))
    if test_end <= val_end:
        raise ValueError(f"config data.test_end ({test_end}) must be after data.val_end ({val_end})")
    return df[(df["timestamp"] > val_end) & (df["timestamp"] <= test_end)]


# ── Seasonal naive baseline ────────────────────────────────────────────────────

def seasonal_naive_forecast(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    freq: str,
    seasonality_hours: int = 168,   # 7-day seasonal period
) -> pd.DataFrame:
    """
    For each test row, predict the value from exactly
    `seasonality_hours` ago in the training data.
    This is the absolute minimum any model must beat.
    """
    if freq.upper() in {"MS", "M", "ME"} or "month" in freq.lower():
        lag = 12
    else:
        steps_per_hour = pd.tseries.frequencies.to_offset(freq).nanos / (3600 * 1e9)
        lag = int(seasonality_hours * steps_per_hour)
    all_preds = []

    for station_id, grp in test_df.groupby("station_id"):
        train_grp = train_df[train_df["station_id"] == station_id] \
            .sort_values("timestamp")

        if len(train_grp) < lag:
            continue

        # Repeat the last week of training data cyclically
        last_week = train_grp["ridership"].values[-lag:]
        n_test = len(grp)
        repeated = np.tile(last_week, (n_test // lag) + 1)[:n_test]

        # `repeated` is built assuming positional row i == the i-th chronological
        # test timestamp (e.g. repeated[0] is the seasonal-naive value for the
        # earliest test month). test_df's on-disk row order isn't guaranteed
        # sorted per station (predict.py/zero_shot.py/ablation.py all explicitly
        # re-sort after filtering by station for the same reason) — without
        # sorting here, np.tile's positionally-built array gets assigned to
        # whatever order grp's rows happen to be in, silently pairing each
        # timestamp with the wrong seasonal-naive value.
        grp = grp.sort_values("timestamp").copy()
        grp["p50"] = np.maximum(repeated, 0)
        grp["p10"] = grp["p50"] * 0.80
        grp["p90"] = grp["p50"] * 1.20
        grp["model"] = "SeasonalNaive"
        all_preds.append(grp[["timestamp", "station_id", "p10", "p50", "p90", "model"]])

    return pd.concat(all_preds, ignore_index=True) if all_preds else pd.DataFrame()


# ── Metrics computation ────────────────────────────────────────────────────────

# A model predicting a flat zero scores WAPE 100%. Anything worse has
# diverged, and no diverged fit belongs on a published leaderboard: the
# original 176.3% Prophet figure and a 29,423% SARIMA fit were both ranked as
# ordinary results because nothing checked whether the output was plausible.
MAX_PLAUSIBLE_WAPE = float(os.environ.get("MAX_PLAUSIBLE_WAPE", "100"))


def accept_model_rows(rows: list[dict], model_name: str) -> list[dict]:
    """Keep a model's metrics only if it forecast every test row and its overall
    WAPE is valid and physically sensible.

    A model is rejected when it did not forecast every test row (overall n <
    n_expected), when its overall WAPE is missing or NaN (at least one
    forecast was missing), or when it exceeds MAX_PLAUSIBLE_WAPE. A model is
    scored on every test row or not at all. Rejected models are reported
    loudly and left off the leaderboard. They are a failure to investigate,
    not a ranking to publish.
    """
    overall = next((r for r in rows if r.get("slice") == "overall"), None)
    if overall is None:
        return rows

    n_scored = overall.get("n")
    n_expected = overall.get("n_expected")
    if n_scored is not None and n_expected is not None and n_scored < n_expected:
        missing = overall.get("missing_stations") or []
        if missing:
            shown = ", ".join(str(m) for m in missing[:10])
            more = f" (+{len(missing) - 10} more)" if len(missing) > 10 else ""
            where = f" No forecast for {len(missing)} station(s): {shown}{more}."
        else:
            where = ""
        log.error(
            f"  {model_name} REJECTED: forecast {n_scored:,} of {n_expected:,} "
            f"test rows.{where} A model is scored on every test row or not at "
            f"all; excluded from the leaderboard; diagnose before reporting it."
        )
        return []

    wape_pct = overall.get("WAPE_%")
    if wape_pct is None or np.isnan(wape_pct):
        # evaluation.metrics returns NaN when a forecast is missing on a row
        # whose actual is present. A model must never be ranked on only the
        # rows it chose to forecast, so a NaN overall score is a failure.
        log.error(
            f"  {model_name} REJECTED: no valid score — at least one forecast "
            f"is missing; excluded from the leaderboard; diagnose before "
            f"reporting it."
        )
        return []
    if wape_pct is not None and wape_pct > MAX_PLAUSIBLE_WAPE:
        log.error(
            f"  {model_name} REJECTED: WAPE {wape_pct:,.1f}% exceeds "
            f"{MAX_PLAUSIBLE_WAPE:.0f}%, so it is worse than forecasting a "
            f"flat zero — the fit has diverged. Excluded from the leaderboard; "
            f"diagnose before reporting it."
        )
        return []
    return rows


def compute_metrics(
    actuals: pd.DataFrame,
    preds: pd.DataFrame,
    model_name: str,
    slices: dict = None,
    train_df: pd.DataFrame = None,
    interval_method: str = None,
) -> list[dict]:
    """
    Compute metrics for a model overall and on each diagnostic slice.
    slices: dict of {slice_name: boolean mask on merged df}
    train_df: training data used to scale MASE (mirrors evaluation.metrics._compute's
        contract). Omitted -> "MASE" is left out of every row, same as before this
        param existed.

    Every test row is kept (left merge), so a test row the model did not
    forecast reaches the metrics as a missing forecast (NaN metric) instead of
    silently dropping out of the score. Each row reports "n" (rows scored:
    actual and forecast both present) and "n_expected" (rows with an actual).
    When a slice has n < n_expected, the row also lists "missing_stations".

    When preds carry p10_raw/p90_raw (see calibrate_intervals), "Coverage_%"
    scores the calibrated p10/p90 and "Coverage_raw_%" the model's own band;
    interval_method, when given, is recorded as "Interval_method" so a reader
    can tell which band each row's Coverage_% scores.
    """
    has_raw = {"p10_raw", "p90_raw"}.issubset(preds.columns)
    band_cols = ["p10", "p50", "p90"] + (["p10_raw", "p90_raw"] if has_raw else [])
    merged = actuals.merge(
        preds[["timestamp", "station_id"] + band_cols],
        on=["timestamp", "station_id"],
        how="left",
        indicator="_forecast_merge",
    )
    if merged.empty or not (merged["_forecast_merge"] == "both").any():
        log.warning(f"No overlapping rows for {model_name}")
        return []
    merged = merged.drop(columns="_forecast_merge")

    rows = []

    # MASE scale is fixed for the whole training set, computed once here rather
    # than per-slice, matching evaluation.metrics._compute's own approach.
    y_train = seasonal_period = ids = None
    if train_df is not None and "ridership" in train_df.columns:
        seasonal_period = _infer_seasonal_period(train_df)
        train_sorted = train_df.sort_values("timestamp") if "timestamp" in train_df.columns else train_df
        train_valid = train_sorted.dropna(subset=["ridership"])
        y_train = train_valid["ridership"].values.astype(float)
        ids = train_valid["station_id"].values if "station_id" in train_valid.columns else None
        if len(y_train) <= seasonal_period:
            y_train = None

    def _metrics_row(label: str, subset: pd.DataFrame) -> dict | None:
        if subset.empty:
            return None
        y_true = subset["ridership"].values.astype(float)
        y_pred = np.maximum(subset["p50"].values.astype(float), 0)
        has_actual = ~np.isnan(y_true)
        has_forecast = ~np.isnan(y_pred)
        row = {
            "model":   model_name,
            "slice":   label,
            "n":       int(np.sum(has_actual & has_forecast)),
            "WAPE_%":  round(wape(y_true, y_pred),  2),
            "MAE":     round(mae(y_true, y_pred),   2),
            "RMSE":    round(rmse(y_true, y_pred),  2),
            "MAPE_%":  round(mape(y_true, y_pred),  2),
            "sMAPE_%": round(smape(y_true, y_pred), 2),
            "Coverage_%": round(coverage(y_true, subset["p10"].values.astype(float), subset["p90"].values.astype(float)), 2),
        }
        if y_train is not None:
            row["MASE"] = round(mase(y_true, y_pred, y_train, seasonality=seasonal_period, ids=ids), 4)
        # Appended last so every existing column keeps its position.
        row["n_expected"] = int(np.sum(has_actual))
        if has_raw:
            row["Coverage_raw_%"] = round(coverage(y_true, subset["p10_raw"].values.astype(float), subset["p90_raw"].values.astype(float)), 2)
        if interval_method is not None:
            row["Interval_method"] = interval_method
        if row["n"] < row["n_expected"]:
            unforecast = subset.loc[has_actual & ~has_forecast, "station_id"]
            row["missing_stations"] = sorted(unforecast.unique().tolist(), key=str)
        return row

    # Overall
    r = _metrics_row("overall", merged)
    if r:
        rows.append(r)

    # Standard slices
    standard_slices = {
        "game_day":            "is_game_day",
        "sharks_game":         "is_sharks_game_window",
        "rainy_day":           "is_raining",
        "am_peak":             "is_am_peak",
        "pm_peak":             "is_pm_peak",
        "holiday":             "is_holiday",
        "event_catchment":     "in_event_catchment",
    }
    for slice_name, col in standard_slices.items():
        if col in merged.columns:
            subset = merged[merged[col] == True]
            r = _metrics_row(slice_name, subset)
            if r:
                rows.append(r)

    # Custom slices
    if slices:
        for slice_name, mask in slices.items():
            if len(mask) == len(merged):
                r = _metrics_row(slice_name, merged[mask])
                if r:
                    rows.append(r)

    return rows


# ── Interval calibration ───────────────────────────────────────────────────────

def calibrate_intervals(
    model_key: str,
    model_name: str,
    test_preds: pd.DataFrame,
    make_val_preds,
    val_df: pd.DataFrame,
    cfg: dict,
    checkpoint: str = None,
    calibrator_path: Path = None,
    make_origin_preds=None,
    history_df: pd.DataFrame = None,
    as_of: pd.Timestamp = None,
) -> tuple[pd.DataFrame, str]:
    """Conformal P10/P90 for one model's test forecasts.

    The models' own bands are not 80% intervals (test coverage of the own
    bands: Prophet 46.0%, Chronos-1 51.0%, SARIMA 96.7%, SeasonalNaive 94.3%).
    A model with a calibration method in configs/model.yaml gets its test band
    from the conformal quantile of errors on data up to val_end: by default
    (`scheme: split`) its forecasts of the validation split from a fit that
    ends at train_end; with `scheme: rolling`, a pool over monthly origins
    (below). Methods were chosen per model on data up to val_end only, and a
    model for which no method passed keeps its own band — see
    docs/interval-calibration.md and evaluation/interval_study.py.

    model_key: stable config key (calibration.models.<key>), independent of
        the checkpoint-derived leaderboard label.
    checkpoint: the checkpoint that produced test_preds, for models whose
        weights are configurable. A method was validated for one checkpoint
        (`validated_for` in the config); a different one keeps its own band
        rather than inheriting a choice nobody measured for it.
    make_val_preds: zero-argument callable returning the model's validation-
        window forecasts. It is called after the test forecasts exist, so the
        test run is unchanged.
    calibrator_path: where to save the fitted calibrator, so the website
        export and the API serve the band this leaderboard row scores (see
        evaluation.calibration.serve_band). Any file already there is removed
        first: a model left raw, or a failed calibration, leaves no calibrator
        behind for a later step to apply. A file that cannot be removed or
        written is logged as an error and does not change the returned band or
        label; the export and the API then refuse this model's calibrated band
        for lack of a matching file.

    `scheme: rolling` (Sprint 5) calibrates on a pool instead of one window:
    forecasts from every monthly origin from `first_origin` to one month
    before `as_of` (the test forecast origin, val_end), each from a store cut
    at min(origin + horizon, as_of), scored against `history_df` rows on or
    before as_of, weighted 0.5**(age / half_life). make_origin_preds(origin,
    cut) returns one origin's forecasts; it too runs after the test forecasts.
    Chosen on validation only (evaluation/interval_study.py, adaptive_study).

    `method: shift_relative` (Sprint 6) uses the same rolling pool but fits a
    bias-shifted band with fit_shift_conformal: re-centred on the recency-
    weighted median relative error (bias_half_life; at the origin as_of, or
    at each pool origin with bias_at "origin") and widened by the weighted
    conformal quantile (half_life). It is stored and applied as an
    asym_relative calibrator, saved with provenance method_config
    "shift_relative" so serve_band never mistakes it for a Sprint 5 band. It
    needs scheme rolling, half_life, bias_half_life and bias_at; an entry
    without them fails before anything is forecast. Chosen on validation
    only (interval_study.py, shift_study). The full calibrator (bias, width
    and q per group, unrounded) is logged so it can be checked against the
    study's.

    P50 is returned untouched, so every point metric is identical to the
    uncalibrated run. Returns (preds, interval_method): preds with p10/p90
    replaced and the model's own bounds kept as p10_raw/p90_raw (unchanged
    copies for a model left raw), and a label saying which band Coverage_%
    scores. If calibration fails (e.g. a station has no validation forecast),
    the error is logged and p10/p90 come back NaN, so the leaderboard shows a
    missing calibrated coverage rather than quietly publishing the raw band
    under the calibrated column.
    """
    if calibrator_path is not None:
        _remove_calibrator(calibrator_path, model_name)

    plan = interval_plan(model_key, cfg, checkpoint)
    if not plan["calibrated"]:
        if plan["checkpoint_mismatch"]:
            log.warning(f"  {model_name}: calibration {plan['reason']}, not {checkpoint}; "
                        f"keeping the model's own band")
        return no_calibration(test_preds), plan["label"]

    method, group, label, scheme = plan["method"], plan["group"], plan["label"], plan["scheme"]
    shift = method == "shift_relative"
    if shift:
        # Checked before anything is forecast. As for half_life below, a
        # missing setting would silently be a band nobody chose.
        missing = ([f"scheme {scheme!r} instead of rolling"] if scheme != "rolling" else []) + [
            f"no {key}" for key, absent in (("half_life", not plan["half_life_given"]),
                                            ("bias_half_life", plan["bias_half_life"] is None),
                                            ("bias_at", plan["bias_at"] is None)) if absent]
        if missing:
            log.error(f"  {model_name}: shift_relative needs scheme rolling, half_life, "
                      f"bias_half_life and bias_at ({', '.join(missing)})")
            out = no_calibration(test_preds)
            out["p10"], out["p90"] = np.nan, np.nan
            return out, f"FAILED: {method}/{group} ({', '.join(missing)})"
    if scheme == "rolling" and not plan["half_life_given"]:
        # A missing half_life would silently mean equal weights, a different
        # method from the one chosen; null must be written out to ask for it.
        log.error(f"  {model_name}: scheme rolling needs half_life (null for equal weights)")
        out = no_calibration(test_preds)
        out["p10"], out["p90"] = np.nan, np.nan
        return out, f"FAILED: {method}/{group} (no half_life)"
    try:
        if shift:
            pool = _rolling_origin_pool(make_origin_preds, history_df, as_of,
                                        plan["first_origin"], cfg)
            calibrator = fit_shift_conformal(pool, group, plan["level"], as_of,
                                             bias_half_life=plan["bias_half_life"],
                                             half_life=plan["half_life"], bias_at=plan["bias_at"])
            calibrated = apply_conformal(with_origin_horizon(test_preds, as_of), calibrator)
            fit_end = (cfg.get("data") or {}).get("val_end")
            months = pd.to_datetime(pool.loc[pool["timestamp"] <= as_of, "timestamp"])
        elif scheme == "rolling":
            pool = _rolling_origin_pool(make_origin_preds, history_df, as_of,
                                        plan["first_origin"], cfg)
            calibrator = fit_rolling_conformal(pool, method, group, plan["level"], as_of,
                                               half_life=plan["half_life"])
            calibrated = apply_conformal(with_origin_horizon(test_preds, as_of), calibrator)
            # Fitted on every resolved target up to as_of (val_end).
            fit_end = (cfg.get("data") or {}).get("val_end")
            months = pd.to_datetime(pool.loc[pool["timestamp"] <= as_of, "timestamp"])
        elif scheme == "split":
            val_preds = make_val_preds()
            if val_preds is None or val_preds.empty:
                raise ValueError("no validation-window forecasts")
            cal = val_df[["timestamp", "station_id", "ridership"]].merge(
                val_preds[["timestamp", "station_id", "p10", "p50", "p90"]],
                on=["timestamp", "station_id"], how="left",
            )
            calibrator = fit_conformal(add_horizon(cal), method=method, group=group, level=plan["level"])
            calibrated = apply_conformal(add_horizon(test_preds), calibrator)
            fit_end = (cfg.get("data") or {}).get("train_end")
            months = pd.to_datetime(val_df["timestamp"])
        else:
            raise ValueError(f"unknown calibration scheme {scheme!r}")
        log.info(f"  interval calibration: {describe(calibrator)}")
        if shift:
            log.info("  interval calibrator (full): " + json.dumps(
                {"model": model_key, "n": calibrator["n"], "n_by_group": calibrator["n_by_group"],
                 "bias": calibrator["bias"], "width": calibrator["width"], "q": calibrator["q"],
                 "clipped_groups": calibrator["clipped_groups"]}, sort_keys=True))
    except Exception as e:
        log.error(
            f"  {model_name}: interval calibration FAILED ({e}); calibrated "
            f"P10/P90 set to NaN, so Coverage_% is NaN for this model. "
            f"Coverage_raw_% still reports the model's own band."
        )
        out = no_calibration(test_preds)
        out["p10"], out["p90"] = np.nan, np.nan
        return out, f"FAILED: {method}/{group}"

    # Saving is outside the scoring try: the leaderboard row scores the band
    # computed above whether or not the file can be written.
    if calibrator_path is not None:
        try:
            extra = ({"scheme": "rolling", "half_life": plan["half_life"],
                      "first_origin": str(plan["first_origin"])} if scheme == "rolling" else {})
            if shift:
                # The file's method is the calibrator's (asym_relative); this
                # records which configured method fitted it.
                extra.update(method_config="shift_relative", bias_half_life=plan["bias_half_life"],
                             bias_at=plan["bias_at"])
            save_calibrator(
                calibrator, calibrator_path,
                model_key=model_key, model=model_name, checkpoint=checkpoint, label=label,
                fit_end=str(fit_end),
                window=[months.min().strftime("%Y-%m-%d"), months.max().strftime("%Y-%m-%d")],
                **extra,
            )
            log.info(f"  calibrator saved → {calibrator_path}")
        except Exception as e:
            log.error(
                f"  {model_name}: could not save the calibrator to {calibrator_path} ({e!r}). "
                f"The leaderboard row is unaffected, but the website export and the API "
                f"will refuse this model's calibrated band until a run saves it."
            )
            # A partly written file must not be left for serve_band to find.
            _remove_calibrator(calibrator_path, model_name)
    return calibrated, label


def _remove_calibrator(path: Path, model_name: str) -> None:
    """Delete a saved calibrator if present. A failure is logged, not raised:
    whether a file can be removed must not change the leaderboard."""
    try:
        Path(path).unlink(missing_ok=True)
    except NotADirectoryError:
        pass  # a parent is a regular file, so no calibrator can exist there
    except OSError as e:
        log.error(f"  {model_name}: could not remove the calibrator at {path} ({e!r}); "
                  f"a stale file there could be served")


def accept_rows_and_calibrator(rows: list[dict], model_name: str, calibrator_path: Path) -> list[dict]:
    """accept_model_rows, and a rejected model's calibrator goes with it.

    A model can be rejected after calibrate_intervals saved its calibrator in
    this run (same fit_end), so serve_band would otherwise serve a band whose
    leaderboard row was never published."""
    accepted = accept_model_rows(rows, model_name)
    if not accepted:
        _remove_calibrator(calibrator_path, model_name)
    return accepted


def clear_saved_calibrators(directory: Path) -> int:
    """Remove every saved calibrator (*.json directly in `directory`) and return
    how many were removed. run_benchmarks calls this once at the start, so any
    calibrator present afterwards was fitted by that run: a --quick run, a
    model that crashes or is skipped, or a model rejected later, cannot leave
    an older run's file behind. A missing directory has nothing to clear; a
    file that cannot be removed raises, before any model has run."""
    directory = Path(directory)
    if not directory.is_dir():
        return 0
    removed = 0
    for path in sorted(directory.glob("*.json")):
        if path.is_dir() and not path.is_symlink():
            continue
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def _rolling_origin_pool(make_origin_preds, history_df: pd.DataFrame, as_of: pd.Timestamp,
                         first_origin, cfg: dict) -> pd.DataFrame:
    """Calibration pool for `scheme: rolling`: one block of forecasts per monthly
    origin first_origin .. as_of - 1 month, each merged onto its actuals (left
    merge, so a missing forecast fails the fit instead of dropping out) and
    tagged with its explicit origin and horizon. Nothing after as_of is read."""
    if make_origin_preds is None or history_df is None or as_of is None or first_origin is None:
        raise ValueError("rolling calibration needs make_origin_preds, history_df, as_of and first_origin")
    horizon = int(cfg["data"]["forecast_horizon_steps"])
    as_of = pd.Timestamp(as_of)
    first, tz = pd.Timestamp(first_origin), history_df["timestamp"].dt.tz
    if tz is not None and first.tzinfo is None:
        first = first.tz_localize(tz)
    elif tz is None and first.tzinfo is not None:
        first = first.tz_localize(None)
    actuals = history_df.loc[history_df["timestamp"] <= as_of, ["timestamp", "station_id", "ridership"]]
    parts = []
    for origin in pd.date_range(first, as_of - pd.offsets.MonthEnd(1), freq="ME"):
        cut = min(origin + pd.DateOffset(months=horizon), as_of)
        preds = make_origin_preds(origin, cut)
        if preds is None or preds.empty:
            raise ValueError(f"no forecasts from origin {origin:%Y-%m-%d}")
        window = actuals[(actuals["timestamp"] > origin) & (actuals["timestamp"] <= cut)]
        merged = window.merge(preds[["timestamp", "station_id", "p10", "p50", "p90"]],
                              on=["timestamp", "station_id"], how="left")
        parts.append(with_origin_horizon(merged, origin))
    if not parts:
        raise ValueError(f"no origins between {first_origin} and {as_of:%Y-%m-%d}")
    return pd.concat(parts, ignore_index=True)


def _forecast_checked(predictor, as_of, window_end, output_path: Path, mode: str) -> pd.DataFrame:
    """Predictor forecasts for a calibration window, refusing a silent backend
    fallback: calibrating Chronos on seasonal-naive errors would be the same
    misattribution the leaderboard already refuses for the test forecasts.

    Predictor reads its own on-disk store, which runs through the test split,
    and passes rows after `as_of` to the model as future covariates. For the
    calibration window it gets a store that ends at `window_end`, so no
    test-period row reaches a validation forecast. (chronos-t5-small ignores
    covariates, and its forecasts were checked identical either way; a
    covariate-aware checkpoint would not be.)"""
    full = predictor.get_feature_store()
    predictor._store = full[full["timestamp"] <= window_end]
    try:
        preds = predictor.forecast_all_stations(as_of=as_of, output_path=output_path, force_mode=mode)
    finally:
        predictor._store = full
    if getattr(predictor, "mode", None) != mode:
        raise RuntimeError(f"backend {mode!r} did not run for the calibration window "
                           f"(mode={getattr(predictor, 'mode', None)!r})")
    return preds


# ── Diebold-Mariano test ───────────────────────────────────────────────────────

def diebold_mariano_test(
    actuals: pd.DataFrame,
    preds_a: pd.DataFrame,  # baseline (e.g. Prophet)
    preds_b: pd.DataFrame,  # challenger (e.g. Chronos-2)
    model_a: str = "Prophet",
    model_b: str = "Chronos-2",
) -> dict:
    """
    Diebold-Mariano test: is model B significantly better than model A?
    H0: no difference in forecast accuracy.
    p < 0.05 → model B is significantly better.
    """
    try:
        from scipy import stats
    except ImportError:
        return {"error": "scipy not installed"}

    # Merge the two prediction sets together first, then join actuals once —
    # merging actuals into each side separately (the old approach) carried
    # "ridership" into both merged_a and merged_b, so the final merge's
    # suffixes turned it into ridership_a/ridership_b and left no plain
    # "ridership" column, raising KeyError below.
    preds_merged = preds_a[["timestamp","station_id","p50"]].merge(
        preds_b[["timestamp","station_id","p50"]],
        on=["timestamp","station_id"], suffixes=("_a","_b"),
    )
    common = preds_merged.merge(
        actuals[["timestamp","station_id","ridership"]],
        on=["timestamp","station_id"], how="inner",
    )
    if common.empty:
        return {}

    y_true = common["ridership"].values.astype(float)
    p50_a  = common["p50_a"].values.astype(float)
    p50_b  = common["p50_b"].values.astype(float)

    # Pair only the rows where the actual and both models' p50 are present.
    # This is a significance test between two models, not a score for either
    # of them (the leaderboard rejects any model that missed test rows; see
    # accept_model_rows). A single NaN row would poison d.mean()/t_stat/
    # p_value to NaN for the WHOLE comparison, and `p_value < 0.05` against
    # that NaN is always False -- so `winner` would fall through to model_a
    # even when model_b (the challenger) was actually better, misreporting an
    # undefined test as a clean loss.
    valid = ~(np.isnan(y_true) | np.isnan(p50_a) | np.isnan(p50_b))
    if valid.sum() < 2:
        return {}
    y_true, p50_a, p50_b = y_true[valid], p50_a[valid], p50_b[valid]

    e_a = np.abs(y_true - np.maximum(p50_a, 0))
    e_b = np.abs(y_true - np.maximum(p50_b, 0))
    d   = e_a - e_b   # positive = B is better

    t_stat, p_value = stats.ttest_1samp(d, 0)
    return {
        "model_a":   model_a,
        "model_b":   model_b,
        "mean_d":    round(float(d.mean()), 4),
        "t_stat":    round(float(t_stat), 4),
        "p_value":   round(float(p_value), 4),
        "significant_at_5pct": p_value < 0.05,
        "winner":    model_b if (d.mean() > 0 and p_value < 0.05) else model_a,
    }


# ── Main benchmark runner ──────────────────────────────────────────────────────

# MASE here is the forecast's MAE divided by the in-sample seasonal-naive MAE
# on the TRAINING series (evaluation.metrics.mase). Its value is not a
# comparison with the SeasonalNaive model scored on the test window, which is
# a separate row of this table and routinely has MASE > 1 itself. The CSV
# column stays "MASE" (stable schema for readers of the CSV); the printed and
# LaTeX tables label it so it cannot be read as a comparison with that row.
MASE_LABEL = "MASE (in-sample)"
MASE_NOTE_LINES = (
    "MASE (in-sample) = forecast MAE / in-sample seasonal-naive MAE, training series.",
    "Below 1 = below that in-sample error; NOT a comparison with the SeasonalNaive row.",
)


def format_leaderboard_console(leaderboard: pd.DataFrame) -> str:
    """Render the console leaderboard table (and the MASE note, once, below it)."""
    has_mase = "MASE" in leaderboard.columns
    has_raw = "Coverage_raw_%" in leaderboard.columns
    out = [f"\n{'═'*70}", "  MODEL BENCHMARK LEADERBOARD", f"{'═'*70}"]
    header = f"\n{'Rank':<6}{'Model':<25}{'WAPE%':>8}{'MAE':>10}{'RMSE':>10}{'MAPE%':>9}{'Cov%':>8}"
    if has_mase:
        header += f"{MASE_LABEL:>18}"
    if has_raw:
        header += f"{'RawCov%':>9}"
    out.append(header)
    out.append(f"{'─'*76}")
    for rank, row in leaderboard.iterrows():
        marker = " ← best" if rank == 1 else ""
        line = (f"  {rank:<4}{row['model']:<25}{row['WAPE_%']:>7.1f}%"
                f"{row['MAE']:>10.0f}{row['RMSE']:>10.0f}"
                f"{row['MAPE_%']:>8.1f}%{row['Coverage_%']:>7.1f}%")
        if has_mase:
            mase_val = row.get("MASE")
            line += f"{mase_val:>18.3f}" if pd.notna(mase_val) else f"{'n/a':>18}"
        if has_raw:
            raw_val = row.get("Coverage_raw_%")
            line += f"{raw_val:>8.1f}%" if pd.notna(raw_val) else f"{'n/a':>9}"
        out.append(line + marker)
    if has_mase:
        out.append("")
        out.extend(f"  {note}" for note in MASE_NOTE_LINES)
    if has_raw:
        out.append("  Cov% scores each row's Interval_method band; RawCov% the model's own band.")
    return "\n".join(out)


def leaderboard_latex(leaderboard: pd.DataFrame) -> str:
    """Render the report-ready LaTeX table. Needs jinja2 (raises ImportError without it)."""
    has_mase = "MASE" in leaderboard.columns
    has_raw = "Coverage_raw_%" in leaderboard.columns
    latex_cols = ["model", "WAPE_%", "MAE", "RMSE", "MAPE_%", "Coverage_%"]
    caption = "Model comparison on Bay Area transit test set"
    if has_mase:
        latex_cols.append("MASE")
        caption += ". " + " ".join(MASE_NOTE_LINES)
    if has_raw:
        # Coverage_% is calibrated for some rows and the model's own band for
        # others; without these columns the two read as the same quantity.
        latex_cols += ["Coverage_raw_%"] + (["Interval_method"] if "Interval_method" in leaderboard.columns else [])
        caption = caption.rstrip(".") + (". Coverage_% scores the band named in Interval_method "
                    "(conformal, fit on data up to the end of the validation split, or the model's own); "
                    "Coverage_raw_% scores the model's own band")
    table = leaderboard[latex_cols].rename(columns={"MASE": MASE_LABEL})
    return table.to_latex(
        index=True,
        float_format="%.2f",
        caption=caption,
        label="tab:benchmark",
    )


def run_benchmarks(
    df: pd.DataFrame,
    cfg: dict,
    quick: bool = False,
) -> pd.DataFrame:
    """
    Run all models on the test set and produce a leaderboard.
    """
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    # A config without data.test_end fails here, before the calibrators below
    # are deleted: a config error must not cost the last good run's files.
    config_test_end(cfg)
    # Every calibrator left by an earlier run goes first, so a file present
    # after this run was fitted by it (see clear_saved_calibrators).
    removed = clear_saved_calibrators(CALIBRATOR_DIR)
    log.info(f"Removed {removed} saved calibrator(s) from {CALIBRATOR_DIR} before this run")

    def _match_tz(ts: pd.Timestamp) -> pd.Timestamp:
        return match_store_tz(df, ts)

    freq       = cfg["data"].get("resample_freq", "MS")
    train_end  = _match_tz(pd.Timestamp(cfg["data"]["train_end"]))
    val_end    = _match_tz(pd.Timestamp(cfg["data"]["val_end"]))
    train_start = cfg["data"].get("train_start")
    horizon_steps = cfg["data"].get("forecast_horizon_steps") \
        or cfg["chronos2"].get("prediction_length_steps")

    train_df = df[df["timestamp"] <= val_end]
    if train_start:
        start_ts = _match_tz(pd.Timestamp(train_start))
        train_df = train_df[train_df["timestamp"] >= start_ts]
    # val_end < ts <= test_end. Bounded above so that a month added to the
    # store after the test window never enters the test split.
    test_df  = select_test_window(df, cfg)
    test_end = _match_tz(config_test_end(cfg))
    after = int((df["timestamp"] > test_end).sum())
    if after:
        log.info(f"{after:,} store row(s) after test_end {test_end:%Y-%m-%d} are outside the test split")
    # Validation split: the calibration window for the P10/P90 intervals
    # (see calibrate_intervals). Each model forecasts it from a fit that ends
    # at train_end, after its test forecast is made.
    val_df   = df[(df["timestamp"] > train_end) & (df["timestamp"] <= val_end)]

    if test_df.empty:
        log.error("Test set is empty — check your date ranges in model.yaml")
        return pd.DataFrame()

    log.info(f"Test set: {len(test_df):,} rows | {test_df['station_id'].nunique()} stations")

    all_rows = []
    model_preds = {}
    predictor = None

    # ── 1. Seasonal Naive ──────────────────────────────────────────────────────
    log.info("\n=== Seasonal Naive ===")
    naive_preds = seasonal_naive_forecast(train_df, test_df, freq)
    if not naive_preds.empty:
        naive_preds, naive_interval = calibrate_intervals(
            "SeasonalNaive", "SeasonalNaive", naive_preds,
            lambda: seasonal_naive_forecast(train_df[train_df["timestamp"] <= train_end], val_df, freq),
            val_df, cfg, calibrator_path=CALIBRATOR_DIR / "SeasonalNaive.json",
            make_origin_preds=lambda o, cut: seasonal_naive_forecast(
                train_df[train_df["timestamp"] <= o],
                df[(df["timestamp"] > o) & (df["timestamp"] <= cut)], freq),
            history_df=df[df["timestamp"] <= val_end], as_of=val_end,
        )
        model_preds["SeasonalNaive"] = naive_preds
        rows = compute_metrics(test_df, naive_preds, "SeasonalNaive", train_df=train_df,
                               interval_method=naive_interval)
        rows = accept_rows_and_calibrator(rows, "SeasonalNaive", CALIBRATOR_DIR / "SeasonalNaive.json")
        all_rows.extend(rows)
        log.info(f"  WAPE: {next((r['WAPE_%'] for r in rows if r['slice']=='overall'), 'N/A')}")

    if not quick:
        # ── 2. SARIMA ──────────────────────────────────────────────────────────
        log.info("\n=== SARIMA ===")
        try:
            from models.baselines.arima import run_arima_all_stations
            arima_preds = run_arima_all_stations(
                df, cfg, train_cutoff=val_end, horizon_steps=horizon_steps, freq=freq
            )
            if not arima_preds.empty:
                arima_preds, arima_interval = calibrate_intervals(
                    "SARIMA", "SARIMA", arima_preds,
                    lambda: run_arima_all_stations(
                        df, cfg, output_dir=CAL_DIR / "arima", train_cutoff=train_end,
                        horizon_steps=horizon_steps, freq=freq),
                    val_df, cfg, calibrator_path=CALIBRATOR_DIR / "SARIMA.json",
                )
                model_preds["SARIMA"] = arima_preds
                rows = compute_metrics(test_df, arima_preds, "SARIMA", train_df=train_df,
                                       interval_method=arima_interval)
                rows = accept_rows_and_calibrator(rows, "SARIMA", CALIBRATOR_DIR / "SARIMA.json")
                all_rows.extend(rows)
                log.info(f"  WAPE: {next((r['WAPE_%'] for r in rows if r['slice']=='overall'), 'N/A')}")
        except Exception as e:
            log.error(f"  SARIMA failed: {e}")

        # ── 3. Prophet ─────────────────────────────────────────────────────────
        log.info("\n=== Prophet ===")
        try:
            from models.baselines.prophet_baseline import run_prophet_all_stations
            prophet_preds = run_prophet_all_stations(
                df, cfg, train_cutoff=val_end, horizon_steps=horizon_steps, freq=freq
            )
            if not prophet_preds.empty:
                prophet_preds, prophet_interval = calibrate_intervals(
                    "Prophet", "Prophet", prophet_preds,
                    lambda: run_prophet_all_stations(
                        df, cfg, output_dir=CAL_DIR / "prophet", train_cutoff=train_end,
                        horizon_steps=horizon_steps, freq=freq),
                    val_df, cfg, calibrator_path=CALIBRATOR_DIR / "Prophet.json",
                    make_origin_preds=lambda o, cut: run_prophet_all_stations(
                        df[df["timestamp"] <= cut], cfg,
                        output_dir=CAL_DIR / "prophet_rolling" / f"{o:%Y-%m-%d}",
                        train_cutoff=o, horizon_steps=horizon_steps, freq=freq),
                    history_df=df[df["timestamp"] <= val_end], as_of=val_end,
                )
                model_preds["Prophet"] = prophet_preds
                rows = compute_metrics(test_df, prophet_preds, "Prophet", train_df=train_df,
                                       interval_method=prophet_interval)
                rows = accept_rows_and_calibrator(rows, "Prophet", CALIBRATOR_DIR / "Prophet.json")
                all_rows.extend(rows)
                log.info(f"  WAPE: {next((r['WAPE_%'] for r in rows if r['slice']=='overall'), 'N/A')}")
        except Exception as e:
            log.error(f"  Prophet failed: {e}")

    # ── 4. Chronos-2 zero-shot ─────────────────────────────────────────────────
    log.info("\n=== Chronos-2 (zero-shot) ===")
    try:
        from models.chronos2.predict import Predictor
        predictor = Predictor()
        # force_mode="zeroshot" pins the backend, so a result is never
        # attributed to Chronos unless Chronos ran (checked via mode below).
        zs_preds = predictor.forecast_all_stations(
            as_of=val_end,
            output_path=EVAL_DIR / "chronos2_zeroshot_preds.parquet",
            force_mode="zeroshot",
        )
        # Predictor falls back to seasonal naive when Chronos cannot be
        # imported, and returns those forecasts without raising. Publishing
        # them as "Chronos2_ZeroShot" puts a foundation-model result on the
        # leaderboard that was never computed — and it outranked the real
        # baselines when this was last run with `chronos` missing.
        # Name the row after the checkpoint that actually ran. configs/model.yaml
        # pins amazon/chronos-t5-small, which is Chronos-1 — labelling its output
        # "Chronos2" is the same misattribution as crediting a seasonal-naive
        # fallback to Chronos, just one level subtler.
        checkpoint = cfg.get("chronos2", {}).get("model_id", "unknown")
        family = "Chronos2" if "chronos-2" in checkpoint.lower() else "Chronos1"
        chronos_label = f"{family}_ZeroShot ({checkpoint.split('/')[-1]})"

        actual_mode = getattr(predictor, "mode", None)
        if actual_mode != "zeroshot":
            log.error(
                f"  Chronos-2 zero-shot did NOT run (backend mode="
                f"{actual_mode!r}); install `chronos-forecasting` to benchmark "
                f"it. Omitting from the leaderboard rather than attributing "
                f"fallback forecasts to Chronos."
            )
        elif not zs_preds.empty:
            zs_preds, zs_interval = calibrate_intervals(
                "Chronos", chronos_label, zs_preds,
                lambda: _forecast_checked(predictor, train_end, val_end,
                                          CAL_DIR / "chronos2_zeroshot_val_preds.parquet", "zeroshot"),
                val_df, cfg, checkpoint=checkpoint,
                calibrator_path=CALIBRATOR_DIR / "Chronos.json",
                # Rolling-origin pool (shift_relative): each origin's forecasts
                # from the store cut at min(origin + horizon, val_end), as in
                # interval_study.forecast. forecast_all_stations creates the
                # directory.
                make_origin_preds=lambda o, cut: _forecast_checked(
                    predictor, o, cut, CAL_DIR / "chronos2_zeroshot_rolling" / f"{o:%Y-%m-%d}.parquet",
                    "zeroshot"),
                history_df=df[df["timestamp"] <= val_end], as_of=val_end,
            )
            model_preds[chronos_label] = zs_preds
            rows = compute_metrics(test_df, zs_preds, chronos_label, train_df=train_df,
                                   interval_method=zs_interval)
            rows = accept_rows_and_calibrator(rows, chronos_label, CALIBRATOR_DIR / "Chronos.json")
            all_rows.extend(rows)
            log.info(f"  WAPE: {next((r['WAPE_%'] for r in rows if r['slice']=='overall'), 'N/A')}")
    except Exception as e:
        log.error(f"  Chronos-2 zero-shot failed: {e}")

    if not all_rows:
        log.error("No benchmark results generated")
        return pd.DataFrame()

    results_df = pd.DataFrame(all_rows)

    # ── Leaderboard ────────────────────────────────────────────────────────────
    leaderboard = (
        results_df[results_df["slice"] == "overall"]
        .sort_values("WAPE_%")
        .reset_index(drop=True)
    )
    leaderboard.index += 1  # rank from 1

    # ── Print report ───────────────────────────────────────────────────────────
    # 2026-09-24 wired MASE into compute_metrics()'s output rows (so
    # `leaderboard` genuinely carries a "MASE" column here), but never updated
    # this console table or the LaTeX table below to display it -- the module's
    # own docstring promises "Leaderboard table (WAPE, MAE, RMSE, MAPE, MASE)",
    # yet the actual printed leaderboard and report-ready LaTeX table silently
    # dropped MASE. Only the raw benchmark_leaderboard.csv (saved with all
    # columns) ever carried it.
    print(format_leaderboard_console(leaderboard))

    # ── Save ───────────────────────────────────────────────────────────────────
    # The leaderboard is written first and on its own. It is the artifact
    # export_website_data.py reads to build the published comparison table, and
    # it used to be written after the LaTeX export below — so a missing jinja2
    # (an optional pandas dependency needed only for the paper table) took the
    # whole run down and left no leaderboard behind.
    results_df.to_csv(EVAL_DIR / "benchmark_results.csv", index=False)
    leaderboard.to_csv(EVAL_DIR / "benchmark_leaderboard.csv")
    log.info(f"Leaderboard saved → {EVAL_DIR / 'benchmark_leaderboard.csv'}")

    # ── Latex table (cosmetic; never fatal) ────────────────────────────────────
    try:
        (EVAL_DIR / "benchmark_latex.tex").write_text(leaderboard_latex(leaderboard))
    except ImportError as e:
        log.warning(f"Skipping LaTeX table ({e}); leaderboard CSV is unaffected")

    log.info(f"\nAll benchmark outputs saved → {EVAL_DIR}/")
    return results_df


# ── Standalone ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run model benchmarks")
    parser.add_argument("--quick", action="store_true",
                        help="Skip slow baselines (SARIMA, Prophet)")
    args = parser.parse_args()

    cfg = load_config()

    path = PROCESSED_DIR / "feature_store_enriched.parquet"
    if not path.exists():
        path = PROCESSED_DIR / "feature_store.parquet"
    if not path.exists():
        log.error("Feature store not found.")
        return

    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    run_benchmarks(df, cfg, quick=args.quick)


if __name__ == "__main__":
    main()
