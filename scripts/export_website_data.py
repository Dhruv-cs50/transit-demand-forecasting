"""
scripts/export_website_data.py
────────────────────────────────
Reads the feature store and the benchmark run's outputs and exports the six
JSON files under website/data/. Every station id in them is BART's two-letter
workbook code (`EM`, `MT`, `12`, ...), i.e. the feature store's `station_id`;
no file is keyed by website node id. Station names, website node ids and
weather locations come from machine_learning_files/bart_stations.py, not from
the store's `station_name` column.

  stations_ridership.json
      Object keyed by code, every station, in the station table's order:
      station_name, website_id (transit-demo.html node id, or null),
      avg_monthly_ridership over the store's latest 12 months, `normalized`
      (that average on the 0-2.4 heat scale), first_month and last_month of
      the averaging window. Read by website/transit-demo.html.

  stations_meta.json
      List of every station, sorted by avg_monthly_ridership descending (ties
      by code): bart_id (the code), api_code, website_id, station_name,
      weather_station (or null), avg_monthly_ridership. Read by
      website/sections.jsx and website/api-demo.html.

  Both station files must list every station in the table. If a station has
  no store rows in the averaging window, or its average or heat level is not
  finite, an error names it and the script exits 1 before writing anything.

  ridership_actuals.json
      Every feature-store row, sorted by station then month: station_id,
      month (YYYY-MM), ridership, daily_est. Read by website/sections.jsx and
      website/charts.jsx.

  forecasts.json
      The Chronos zero-shot test-window forecasts that
      models/baselines/benchmarks.py wrote to
      evaluation/outputs/chronos2_zeroshot_preds.parquet and scored on the
      leaderboard, as a list sorted by station then month: station_id, month,
      p10, p50, p90, p10_raw, p90_raw, interval_method. p50 is the model's
      own. p10/p90 are the band the leaderboard's Coverage_% scored: the one
      configs/model.yaml assigns to Chronos, applied from the calibrator
      benchmarks.py saved to evaluation/outputs/calibration/calibrators/
      Chronos.json, or the model's own band if the config leaves it raw.
      p10_raw/p90_raw are the model's own bounds (what Coverage_raw_%
      scored) and interval_method is the leaderboard's Interval_method
      string for the band. Written only if the leaderboard has exactly one
      overall Chronos row, every prediction came from the zero-shot model,
      each (station_id, month) appears once, the number of predictions
      equals that row's `n` (and `n_expected`, when the leaderboard has it),
      a calibrated band's saved calibrator matches the config, the checkpoint
      and that row's model, the row's Interval_method names the band served,
      and the band (and the raw one) reproduce the row's Coverage_% (and
      Coverage_raw_%) against the feature store's actuals.
      Otherwise forecasts.json is refused: an error is logged, any existing
      forecasts.json is left as it is (and is then stale), the other files
      are still written, and the script exits 1 so scripts/run_pipeline.sh
      (set -e) stops before printing its deploy command. Read by
      website/sections.jsx and
      website/charts.jsx.

  forecasts_sarima.json
      SARIMA's test-window forecasts (the leaderboard's best model), same fields
      as forecasts.json plus `model`; p10/p90 are SARIMA's own band, labelled by
      the leaderboard's Interval_method. Refused unless the parquet reproduces
      the leaderboard's SARIMA row (n, WAPE, MAE, coverage).

  forecasts_prophet.json, forecasts_seasonal_naive.json
      Prophet's and seasonal naive's test-window forecasts, the same records as
      forecasts_sarima.json (station_id, month, p10, p50, p90, p10_raw, p90_raw,
      interval_method, model). p10/p90 are the band the leaderboard's Coverage_%
      scored (Interval_method says which: both are conformal-calibrated) and
      p10_raw/p90_raw the model's own. Prophet's come from the parquet
      benchmarks.py saved plus its saved calibrator (evaluation.calibration.
      serve_band, as for Chronos-1); seasonal naive's parquet already carries
      both bands. Each is refused unless it has one row per (station, month),
      as many as the leaderboard row's `n`, and reproduces that row's WAPE_%,
      MAE, Coverage_% and Coverage_raw_% against the feature-store actuals, and
      the band's label is the row's Interval_method.

  backtest_windows.json
      SARIMA, Prophet, Chronos-1 and seasonal naive on three half-year windows
      (models/baselines/backtest_windows.py): {"windows": [{id, fit_through,
      first_month, last_month}], "rows": [{window, model, wape, mae, n,
      coverage_own_band, stations_sarima_beats}], "source", "generated_by"}.
      coverage_own_band scores each model's own band (calibrators are fit on
      data to 2025-06-30, so the 2024 windows cannot use them); stations_sarima_beats
      is null for SARIMA. Refused unless the published window's (2025-H2) rows
      equal the leaderboard's overall rows in WAPE_%, MAE and n and its own-band
      coverage equals Coverage_raw_%.

  model_comparison.json
      The benchmark leaderboard (evaluation/outputs/benchmark_leaderboard.csv).
      Read by website/sections.jsx and website/charts.jsx.

If the leaderboard does not exist (and --allow-val-fallback is not given),
the script exits 1 before writing any file.

The nine files are all-or-nothing. They are written to a staging directory
beside the output directory and moved into it only when every one was produced
(os.replace, one file at a time, with the previous copies restored if a move
fails). A refused forecasts file or backtest_windows.json, or any error while
exporting, therefore leaves the output directory exactly as it was; nothing stale is published beside fresh
data.

The evaluation/outputs/ inputs are read relative to the working directory, so
run this from the repo root after benchmarks.py.

Usage:
    python scripts/export_website_data.py
    python scripts/export_website_data.py --feature-store data/processed/feature_store_enriched.parquet
"""

import argparse
import json
import logging
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# Run as a script, sys.path[0] is scripts/, so the repo's top-level packages
# are not importable without the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.calibration import CalibratorUnavailable, serve_band  # noqa: E402
from evaluation.metrics import coverage, mae as metric_mae, wape as metric_wape  # noqa: E402
from machine_learning_files.bart_stations import (  # noqa: E402
    BY_CODE,
    CODE_TO_NAME,
    CODE_TO_WEATHER_STATION,
    CODE_TO_WEBSITE_ID,
    CODES,
    STATIONS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("export_website_data")

# Set by --allow-val-fallback. Off by default: see export_model_comparison().
ALLOW_FALLBACK = False

# Number of most recent store months the per-station average covers.
AVERAGE_WINDOW_MONTHS = 12

# benchmarks.py outputs, relative to the working directory (the repo root).
LEADERBOARD_PATH = Path("evaluation/outputs/benchmark_leaderboard.csv")
PREDS_PATH = Path("evaluation/outputs/chronos2_zeroshot_preds.parquet")
CALIBRATOR_PATH = Path("evaluation/outputs/calibration/calibrators/Chronos.json")
# benchmarks.py's SARIMA test-window forecasts (train_cutoff = val_end). A
# standalone `models/baselines/arima.py` run writes the same file with another
# cutoff, so export_sarima_forecasts() checks it against the leaderboard row.
SARIMA_PREDS_PATH = Path("models/baselines/outputs/arima/arima_forecasts.parquet")
# Prophet's test-window forecasts (its model's own band; the calibrator
# benchmarks.py saved turns it into the band the leaderboard scored) and seasonal
# naive's (already carrying the scored band), written by the same benchmarks.py run.
PROPHET_PREDS_PATH = Path("models/baselines/outputs/prophet/prophet_forecasts.parquet")
PROPHET_CALIBRATOR_PATH = Path("evaluation/outputs/calibration/calibrators/Prophet.json")
SEASONAL_NAIVE_PREDS_PATH = Path("models/baselines/outputs/seasonal_naive/seasonal_naive_forecasts.parquet")
# models/baselines/backtest_windows.py's output.
BACKTEST_PATH = Path("evaluation/outputs/backtest_windows.csv")
BACKTEST_PUBLISHED_WINDOW = "2025-H2"
# The config benchmarks.py ran with: which band each model gets, and the
# Chronos checkpoint the calibrator must have been fitted for.
CONFIG_PATH = Path("configs/model.yaml")


def require_leaderboard() -> None:
    """Stop if there is no benchmark leaderboard and fallback was not asked for.

    main() calls this before writing anything, so a missing leaderboard
    leaves website/data/ as it was instead of partly regenerated.
    """
    if LEADERBOARD_PATH.exists() or ALLOW_FALLBACK:
        return
    log.error(
        f"{LEADERBOARD_PATH} not found — "
        "benchmarks.py has not produced a leaderboard.\n"
        "  Run: python models/baselines/benchmarks.py\n"
        "  The fallback path scores saved forecasts against the VALIDATION "
        "split rather than the test split, so its numbers are not "
        "comparable to a leaderboard run. To use it anyway, pass "
        "--allow-val-fallback."
    )
    raise SystemExit(1)


def load_feature_store(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Feature store not found: {path}")
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    log.info(f"Loaded feature store: {len(df):,} rows, {df['station_id'].nunique()} stations")
    return df


def check_station_ids(df: pd.DataFrame) -> None:
    """Stop if the store has a station_id the station table does not know.

    Every output takes names and ids from the table, so an unknown code would
    either fail on lookup or drop out of the files without notice.
    """
    unknown = sorted(set(df["station_id"].astype(str).unique()) - set(CODES))
    if unknown:
        log.error(
            f"Feature store station_ids not in machine_learning_files/bart_stations.py: "
            f"{unknown}. The store's station_id must be the two-letter BART workbook "
            f"code; add the station to the table or fix the store."
        )
        raise SystemExit(1)


def _month_strings(ts: pd.Series) -> pd.Series:
    """`YYYY-MM` for each timestamp, in its own wall-clock time."""
    ts = pd.to_datetime(ts)
    if ts.dt.tz is not None:
        ts = ts.dt.tz_localize(None)
    return ts.dt.strftime("%Y-%m")


def compute_station_ridership(df: pd.DataFrame) -> pd.DataFrame:
    """Average monthly ridership per station over the store's latest 12 months.

    The window is the latest AVERAGE_WINDOW_MONTHS distinct months in the
    store (by `timestamp`), not all of it. Averaging 2019 with 2022-25 mixes
    levels from either side of the roughly 2.9x COVID break, and BE
    (Berryessa) and ML (Milpitas) carry zero ridership for the months before
    they opened, so an all-months mean understates every station and those
    two most of all.

    Returns one row per station with columns station_id,
    avg_monthly_ridership, first_month, last_month (`YYYY-MM`) and n_months
    (distinct months the station has in the window). Logs a warning for any
    store station with fewer than AVERAGE_WINDOW_MONTHS months in the window.
    """
    rows = pd.DataFrame({
        "station_id": df["station_id"].astype(str).to_numpy(),
        "month": _month_strings(df["timestamp"]).to_numpy(),
        "ridership": df["ridership"].to_numpy(),
    })
    window = sorted(rows["month"].unique())[-AVERAGE_WINDOW_MONTHS:]
    in_window = rows[rows["month"].isin(window)]
    log.info(
        f"Station averages cover the latest {len(window)} store months: "
        f"{window[0]} … {window[-1]}"
    )

    agg = (
        in_window.groupby("station_id")
        .agg(
            avg_monthly_ridership=("ridership", "mean"),
            first_month=("month", "min"),
            last_month=("month", "max"),
            n_months=("month", "nunique"),
        )
        .reset_index()
    )

    n_by_station = agg.set_index("station_id")["n_months"]
    short = {
        code: int(n_by_station.get(code, 0))
        for code in sorted(rows["station_id"].unique())
        if n_by_station.get(code, 0) < AVERAGE_WINDOW_MONTHS
    }
    if short:
        log.warning(
            f"Stations with fewer than {AVERAGE_WINDOW_MONTHS} months in the "
            f"averaging window ({window[0]} … {window[-1]}): {short}"
        )
    return agg


def check_station_averages(agg: pd.DataFrame) -> None:
    """Stop unless every table station has a finite average and heat level.

    stations_ridership.json and stations_meta.json must list every station in
    the table. A station with no store rows in the averaging window would
    otherwise drop out of both files, and a non-finite average or
    `normalized` would be written as a bare NaN token, which is not JSON.
    """
    by_code = agg.set_index("station_id")
    normalized = normalize_to_heat_scale(by_code["avg_monthly_ridership"])
    no_rows = [code for code in CODES if code not in by_code.index]
    not_finite = [
        code for code in CODES
        if code in by_code.index and not (
            math.isfinite(float(by_code.at[code, "avg_monthly_ridership"]))
            and math.isfinite(float(normalized[code]))
        )
    ]
    if no_rows or not_finite:
        problems = []
        if no_rows:
            problems.append(f"stations with no feature-store rows in the averaging window: {no_rows}")
        if not_finite:
            problems.append(f"stations whose average or normalized level is not finite: {not_finite}")
        log.error(
            f"No files written: every station in "
            f"machine_learning_files/bart_stations.py must be in "
            f"stations_ridership.json and stations_meta.json; "
            f"{'; '.join(problems)}. Fix the feature store."
        )
        raise SystemExit(1)


def normalize_to_heat_scale(series: pd.Series, target_max: float = 2.4) -> pd.Series:
    """
    Normalize ridership to a 0–2.4 heat scale (website/transit-demo.html uses
    it as a BART node's level).
    Uses soft normalization: 95th percentile as the ceiling to avoid one
    outlier dominating the color scale.
    """
    ceiling = series.quantile(0.95)
    if ceiling == 0:
        return pd.Series(0.1, index=series.index)
    normalized = (series / ceiling * target_max).clip(upper=target_max)
    return normalized.round(3)


def build_ridership_json(agg: pd.DataFrame) -> dict:
    """Build the stations_ridership.json payload, keyed by code in table order."""
    by_code = agg.set_index("station_id")
    normalized = normalize_to_heat_scale(by_code["avg_monthly_ridership"])

    out = {}
    for station in STATIONS:
        code = station.code
        if code not in by_code.index:
            continue  # not in the window; compute_station_ridership() warned
        row = by_code.loc[code]
        out[code] = {
            "station_name": CODE_TO_NAME[code],
            "website_id": CODE_TO_WEBSITE_ID.get(code),
            "avg_monthly_ridership": round(float(row["avg_monthly_ridership"]), 0),
            "normalized": float(normalized[code]),
            "first_month": row["first_month"],
            "last_month": row["last_month"],
        }
    return out


def build_meta_json(agg: pd.DataFrame) -> list:
    """Build the stations_meta.json payload — flat list for dropdowns."""
    records = []
    for _, row in agg.iterrows():
        station = BY_CODE[row["station_id"]]
        records.append({
            "bart_id": station.code,
            "api_code": station.api_code,
            "website_id": CODE_TO_WEBSITE_ID.get(station.code),
            "station_name": CODE_TO_NAME[station.code],
            "weather_station": CODE_TO_WEATHER_STATION.get(station.code),
            "avg_monthly_ridership": round(float(row["avg_monthly_ridership"]), 0),
        })
    records.sort(key=lambda r: (-r["avg_monthly_ridership"], r["bart_id"]))
    return records


def export_ridership_actuals(df: pd.DataFrame, out_dir: Path) -> None:
    records = []
    for _, row in df.sort_values(["station_id", "timestamp"]).iterrows():
        ts = pd.to_datetime(row["timestamp"])
        if hasattr(ts, "tz") and ts.tz is not None:
            ts = ts.tz_localize(None)
        records.append({
            "station_id": str(row["station_id"]),
            "month":      ts.strftime("%Y-%m"),
            "ridership":  int(row["ridership"]),
            "daily_est":  round(float(row.get("ridership_daily_est", row["ridership"] / 22)), 1),
        })
    with open(out_dir / "ridership_actuals.json", "w") as f:
        json.dump(records, f)
    log.info(f"ridership_actuals.json → {out_dir / 'ridership_actuals.json'}  ({len(records)} records)")


def export_forecasts(out_dir: Path, actuals: pd.DataFrame) -> str | None:
    """Export the benchmark run's Chronos zero-shot forecasts, with the band
    the leaderboard scored.

    These are the predictions benchmarks.py scored on the leaderboard. When
    the Chronos backend cannot run, the Predictor falls back to seasonal
    naive, still writes the preds parquet (model_mode != "zeroshot"), and
    benchmarks.py leaves the Chronos row off the leaderboard. The same two
    signals gate this export, so fallback forecasts are never published as
    Chronos. The preds must also be the run that leaderboard row scored: one
    prediction per (station_id, month), as many as the row's `n` (and
    `n_expected`, when the leaderboard has that column).

    The parquet holds the model's own P10/P90, which the leaderboard reports
    as Coverage_raw_%; its Coverage_% scores the band configs/model.yaml
    assigns (for Chronos-1, the bias-shifted `shift_relative` band). Publishing the
    raw band beside that figure would show one band and the coverage of
    another, so p10/p90 are the assigned band (evaluation.calibration.
    serve_band applies the calibrator benchmarks.py saved, never refits it),
    p10_raw/p90_raw keep the model's own, P50 is unchanged, and every record
    carries the band's label as `interval_method`. Also refused:
      - the config is unreadable or names no chronos2.model_id;
      - the calibrator is missing, or was fitted for another method, model
        or checkpoint (CalibratorUnavailable);
      - the row's Interval_method is absent or is not the band's label;
      - the calibrator was fitted for another leaderboard model label;
      - an exported row has no actual (or more than one) in `actuals`;
      - the served band's coverage of `actuals`, rounded as the leaderboard
        rounds, is not the row's Coverage_% (nor the raw band's its
        Coverage_raw_%, when that column exists). The labels say which band
        was scored; this shows these are the numbers it scored.

    actuals: the feature store (station_id, timestamp, ridership). Only the
        exported rows are read, to check the coverage above; nothing is fit.

    Returns None when forecasts.json was written, or the reason it was
    refused. On refusal nothing is written or deleted; main() then exits 1.
    """
    preds_path = PREDS_PATH
    leaderboard_path = LEADERBOARD_PATH
    config_path = CONFIG_PATH
    calibrator_path = CALIBRATOR_PATH

    def _refuse(reason: str) -> str:
        log.error(
            f"forecasts.json NOT written: {reason}. Run "
            f"models/baselines/benchmarks.py with Chronos available; any "
            f"existing forecasts.json in {out_dir} is left unchanged."
        )
        return reason

    if not preds_path.exists():
        return _refuse(f"{preds_path} not found")
    if not leaderboard_path.exists():
        return _refuse(f"{leaderboard_path} not found")

    leaderboard = pd.read_csv(leaderboard_path)
    if not {"model", "slice"} <= set(leaderboard.columns):
        return _refuse(f"{leaderboard_path} has no model/slice columns")
    overall = leaderboard[leaderboard["slice"] == "overall"]
    chronos = overall[overall["model"].astype(str).str.startswith("Chronos")]
    if chronos.empty:
        return _refuse(
            f"{leaderboard_path} has no overall Chronos row (benchmarks.py "
            f"omits it when the zero-shot backend did not run)"
        )
    if len(chronos) > 1:
        return _refuse(
            f"{leaderboard_path} has {len(chronos)} overall Chronos rows "
            f"{sorted(chronos['model'].astype(str))}; cannot tell which one the "
            f"preds belong to"
        )
    chronos_row = chronos.iloc[0]
    model_label = str(chronos_row["model"])
    log.info(f"Forecasts model (leaderboard overall row): {model_label}")

    df = pd.read_parquet(preds_path)
    missing = {"timestamp", "station_id", "p10", "p50", "p90", "model_mode"} - set(df.columns)
    if missing:
        return _refuse(f"{preds_path} lacks columns {sorted(missing)}")
    if df.empty:
        return _refuse(f"{preds_path} has no rows")
    if not (df["model_mode"] == "zeroshot").all():
        modes = sorted(str(m) for m in df["model_mode"].unique())
        return _refuse(f"{preds_path} model_mode values {modes}, expected only 'zeroshot'")
    unknown = sorted(set(df["station_id"].astype(str).unique()) - set(CODES))
    if unknown:
        return _refuse(f"{preds_path} station_ids not in the station table: {unknown}")

    def _finite_or_none(val) -> float | None:
        # Quantile columns can legitimately be NaN (e.g. a station-month row
        # the model couldn't produce a full-horizon prediction for) — unlike
        # the other json.dump() calls in this file, this loop had no
        # isfinite() guard, so json.dump would emit a bare `NaN` token here,
        # which isn't valid JSON and breaks JSON.parse() for the whole file
        # (charts.jsx's Calibration chart and the BARTForecasts table both
        # silently render "no data" instead of just the affected station-month).
        fv = float(val)
        return round(fv, 0) if math.isfinite(fv) else None

    df = df.assign(
        station_id=df["station_id"].astype(str),
        month=_month_strings(df["timestamp"]),
    ).sort_values(["station_id", "month"], kind="stable")

    # Keyed on the month the records carry, so two timestamps in one month
    # count as a duplicate too.
    dup_keys = df.loc[df.duplicated(["station_id", "month"], keep=False), ["station_id", "month"]]
    if not dup_keys.empty:
        keys = sorted(set(map(tuple, dup_keys.to_numpy().tolist())))
        shown = ", ".join(f"{s} {m}" for s, m in keys[:10])
        more = f" (+{len(keys) - 10} more)" if len(keys) > 10 else ""
        return _refuse(
            f"{preds_path} has more than one prediction for {len(keys)} "
            f"(station_id, month) key(s): {shown}{more}"
        )

    if "n" not in leaderboard.columns:
        return _refuse(
            f"{leaderboard_path} has no `n` column, so the preds cannot be "
            f"tied to the {model_label} row"
        )
    count_cols = ["n"] + (["n_expected"] if "n_expected" in leaderboard.columns else [])
    for col in count_cols:
        val = float(pd.to_numeric(chronos_row[col], errors="coerce"))
        if not math.isfinite(val):
            return _refuse(f"{leaderboard_path} {model_label} overall `{col}` is {chronos_row[col]!r}")
        if val != len(df):
            return _refuse(
                f"{preds_path} has {len(df)} predictions but the leaderboard's "
                f"{model_label} overall row has {col}={val:g}; the preds are "
                f"not the run that row scored"
            )

    # The band. The checkpoint comes from the config benchmarks.py ran with;
    # serve_band refuses a calibrator fitted for another one.
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        checkpoint = cfg["chronos2"]["model_id"]
    except (OSError, yaml.YAMLError, KeyError, TypeError) as e:
        return _refuse(f"cannot read chronos2.model_id from {config_path}: {e!r}")
    try:
        # Months ahead are counted from val_end, the origin benchmarks.py
        # forecast and scored this band from.
        served, plan = serve_band(df, "Chronos", cfg, calibrator_path=calibrator_path,
                                  checkpoint=checkpoint, forecast_origin=cfg["data"]["val_end"])
    except (CalibratorUnavailable, ValueError, KeyError, TypeError) as e:
        return _refuse(str(e))

    # The leaderboard must say it scored this band. benchmarks.py writes the
    # same label string to Interval_method, so anything else means the config
    # or the calibrator changed since that run.
    if "Interval_method" not in leaderboard.columns:
        return _refuse(
            f"{leaderboard_path} has no Interval_method column, so it does not "
            f"say which band the {model_label} row scored"
        )
    scored_label = chronos_row["Interval_method"]
    if not isinstance(scored_label, str) or scored_label != plan["label"]:
        return _refuse(
            f"{leaderboard_path} {model_label} overall Interval_method is "
            f"{scored_label!r}, but the band configs/model.yaml assigns is "
            f"{plan['label']!r}"
        )
    if plan["calibrated"]:
        fitted_for = plan["provenance"].get("model")
        if fitted_for != model_label:
            return _refuse(
                f"{calibrator_path} was fitted for {fitted_for!r}, not the "
                f"leaderboard's {model_label!r}"
            )

    # Labels can agree while the numbers do not (a calibrator refit after the
    # leaderboard was written), so recompute the row's coverage from the rows
    # being published. Test-split actuals are only compared here, never fit.
    # Scored on the unrounded band, as benchmarks.py scored it.
    key = ["station_id", "month"]
    truth = pd.DataFrame({
        "station_id": actuals["station_id"].astype(str).to_numpy(),
        "month": _month_strings(actuals["timestamp"]).to_numpy(),
        "actual": pd.to_numeric(actuals["ridership"], errors="coerce").astype("float64").to_numpy(),
    })
    joined = served.merge(truth, on=key, how="left")
    if len(joined) != len(served):
        dup = joined.loc[joined.duplicated(key, keep=False), key].drop_duplicates()
        shown = ", ".join(f"{s} {m}" for s, m in dup.to_numpy().tolist()[:10])
        return _refuse(
            f"more than one feature-store row for {len(dup)} exported "
            f"(station_id, month) key(s): {shown}"
        )
    no_actual = joined["actual"].isna()
    if no_actual.any():
        keys = joined.loc[no_actual, key].to_numpy().tolist()
        shown = ", ".join(f"{s} {m}" for s, m in keys[:10])
        more = f" (+{len(keys) - 10} more)" if len(keys) > 10 else ""
        return _refuse(
            f"no feature-store actual for {len(keys)} exported (station_id, "
            f"month) key(s): {shown}{more}; the leaderboard's coverage cannot "
            f"be checked"
        )
    if "Coverage_%" not in leaderboard.columns:
        return _refuse(f"{leaderboard_path} has no Coverage_% column to check the band against")
    checks = [("Coverage_%", "p10", "p90", "the exported band")]
    if "Coverage_raw_%" in leaderboard.columns:
        checks.append(("Coverage_raw_%", "p10_raw", "p90_raw", "the model's own band"))
    y = joined["actual"].to_numpy(dtype=float)
    for col, lo, hi, what in checks:
        got = round(coverage(y, joined[lo].to_numpy(dtype=float), joined[hi].to_numpy(dtype=float)), 2)
        want = float(pd.to_numeric(chronos_row[col], errors="coerce"))
        # NaN on either side is a mismatch, not a pass.
        if not (math.isfinite(got) and math.isfinite(want)
                and math.isclose(got, want, abs_tol=1e-9)):
            return _refuse(
                f"{what} ({lo}/{hi}) covers {got}% of the feature-store actuals "
                f"but the leaderboard's {model_label} overall {col} is "
                f"{chronos_row[col]}; the leaderboard did not score these numbers"
            )

    records = [
        {
            "station_id":      row.station_id,
            "month":           row.month,
            "p10":             _finite_or_none(row.p10),
            "p50":             _finite_or_none(row.p50),
            "p90":             _finite_or_none(row.p90),
            "p10_raw":         _finite_or_none(row.p10_raw),
            "p90_raw":         _finite_or_none(row.p90_raw),
            "interval_method": plan["label"],
        }
        for row in served.itertuples(index=False)
    ]
    with open(out_dir / "forecasts.json", "w") as f:
        json.dump(records, f)
    log.info(
        f"forecasts.json → {out_dir / 'forecasts.json'}  ({len(records)} records, "
        f"{df['station_id'].nunique()} stations, {df['month'].min()} … {df['month'].max()}; "
        f"{model_label} from {preds_path}; band: {plan['label']}, coverage "
        f"{chronos_row['Coverage_%']}% as on the leaderboard)"
    )
    return None


def export_sarima_forecasts(out_dir: Path, actuals: pd.DataFrame) -> str | None:
    """Export SARIMA's test-window forecasts to forecasts_sarima.json.

    SARIMA is the leaderboard's best model, so the site shows its forecasts by
    default beside Chronos-1's (forecasts.json). Records have forecasts.json's
    fields plus `model`; p10/p90 are SARIMA's own band and p10_raw/p90_raw repeat
    them, so the two files read the same way.

    The parquet is the one benchmarks.py wrote and scored, and is refused unless
    it reproduces the leaderboard's overall SARIMA row against the feature-store
    actuals: row count (`n`), WAPE_%, MAE, Coverage_% and Coverage_raw_%, and the
    row's Interval_method must be a "raw: ..." label (its band is the model's
    own; a calibrated SARIMA band would need the calibrator applied here). A
    standalone arima.py run (another cutoff) therefore cannot be published.

    Returns None when written, else the reason it was refused; nothing is
    written on refusal, and main() then publishes nothing.
    """
    preds_path, leaderboard_path = SARIMA_PREDS_PATH, LEADERBOARD_PATH

    def _refuse(reason: str) -> str:
        log.error(f"forecasts_sarima.json NOT written: {reason}")
        return reason

    if not preds_path.exists():
        return _refuse(f"{preds_path} not found (run models/baselines/benchmarks.py)")
    if not leaderboard_path.exists():
        return _refuse(f"{leaderboard_path} not found")
    leaderboard = pd.read_csv(leaderboard_path)
    need = {"model", "slice", "n", "WAPE_%", "MAE", "Coverage_%", "Interval_method"}
    if not need <= set(leaderboard.columns):
        return _refuse(f"{leaderboard_path} lacks columns {sorted(need - set(leaderboard.columns))}")
    rows = leaderboard[(leaderboard["slice"] == "overall") & (leaderboard["model"].astype(str) == "SARIMA")]
    if len(rows) != 1:
        return _refuse(f"{leaderboard_path} has {len(rows)} overall SARIMA rows, expected 1")
    row = rows.iloc[0]
    label = row["Interval_method"]
    if not isinstance(label, str) or not label.startswith("raw:"):
        return _refuse(
            f"leaderboard SARIMA Interval_method is {label!r}, not a 'raw: ...' label; "
            f"this export publishes SARIMA's own band only"
        )

    df = pd.read_parquet(preds_path)
    missing = {"timestamp", "station_id", "p10", "p50", "p90"} - set(df.columns)
    if missing:
        return _refuse(f"{preds_path} lacks columns {sorted(missing)}")
    if "model" in df.columns and not (df["model"].astype(str) == "SARIMA").all():
        return _refuse(f"{preds_path} model column is not all 'SARIMA'")
    unknown = sorted(set(df["station_id"].astype(str).unique()) - set(CODES))
    if unknown:
        return _refuse(f"{preds_path} station_ids not in the station table: {unknown}")
    df = df.assign(station_id=df["station_id"].astype(str), month=_month_strings(df["timestamp"]))
    key = ["station_id", "month"]
    if df.duplicated(key).any():
        return _refuse(f"{preds_path} has more than one prediction for a (station_id, month)")
    if float(row["n"]) != len(df):
        return _refuse(f"{preds_path} has {len(df)} predictions but the leaderboard's SARIMA row has n={float(row['n']):g}")
    if not np.isfinite(df[["p10", "p50", "p90"]].to_numpy(dtype=float)).all():
        return _refuse(f"{preds_path} has non-finite quantiles")

    truth = pd.DataFrame({
        "station_id": actuals["station_id"].astype(str).to_numpy(),
        "month": _month_strings(actuals["timestamp"]).to_numpy(),
        "actual": pd.to_numeric(actuals["ridership"], errors="coerce").astype("float64").to_numpy(),
    })
    joined = df.merge(truth, on=key, how="left")
    if len(joined) != len(df) or joined["actual"].isna().any():
        return _refuse("an exported (station_id, month) has no single feature-store actual")
    y = joined["actual"].to_numpy(dtype=float)
    p50 = joined["p50"].to_numpy(dtype=float)
    checks = [
        ("WAPE_%", metric_wape(y, p50)),
        ("MAE", metric_mae(y, p50)),
        ("Coverage_%", coverage(y, joined["p10"].to_numpy(float), joined["p90"].to_numpy(float))),
    ]
    if "Coverage_raw_%" in leaderboard.columns:
        checks.append(("Coverage_raw_%", checks[2][1]))  # the band is the raw band
    for col, got in checks:
        got, want = round(float(got), 2), float(pd.to_numeric(row[col], errors="coerce"))
        if not (math.isfinite(got) and math.isfinite(want) and math.isclose(got, want, abs_tol=0.011)):
            return _refuse(
                f"{preds_path} scores {col}={got} against the feature-store actuals but the "
                f"leaderboard's SARIMA row has {want}; these are not the forecasts it scored"
            )

    records = [
        {
            "station_id": r.station_id,
            "month": r.month,
            "p10": round(float(r.p10), 0),
            "p50": round(float(r.p50), 0),
            "p90": round(float(r.p90), 0),
            "p10_raw": round(float(r.p10), 0),
            "p90_raw": round(float(r.p90), 0),
            "interval_method": label,
            "model": "SARIMA",
        }
        for r in df.sort_values(key, kind="stable").itertuples(index=False)
    ]
    with open(out_dir / "forecasts_sarima.json", "w") as f:
        json.dump(records, f)
    log.info(
        f"forecasts_sarima.json → {out_dir / 'forecasts_sarima.json'}  ({len(records)} records, "
        f"{df['station_id'].nunique()} stations, {df['month'].min()} … {df['month'].max()}; "
        f"band: {label}, coverage {row['Coverage_%']}% and WAPE {row['WAPE_%']}% as on the leaderboard)"
    )
    return None


def _export_checked_forecasts(
    out_dir: Path,
    actuals: pd.DataFrame,
    *,
    filename: str,
    model_label: str,
    preds_path: Path,
    model_key: str | None = None,
    calibrator_path: Path | None = None,
) -> str | None:
    """Export one baseline model's test-window forecasts, refused unless they
    are the ones its leaderboard row scored.

    With `model_key`, preds_path holds the model's own band and the band the
    leaderboard scored is the one configs/model.yaml assigns to that key, applied
    from the calibrator benchmarks.py saved (serve_band; nothing is refit).
    Without it, preds_path already carries the scored band as p10/p90 and the
    model's own as p10_raw/p90_raw, with the band's label in `interval_method`.

    Refused (returns the reason, writes nothing) unless the leaderboard has one
    overall row for `model_label`; the parquet has one prediction per
    (station_id, month), as many as the row's `n` (and `n_expected`), every
    quantile finite and every station in the table; the band's label is the row's
    Interval_method (and a calibrator was fitted for this model's label); every
    row has one feature-store actual; and WAPE_%, MAE, Coverage_% (served band)
    and Coverage_raw_% (own band), recomputed against the actuals and rounded as
    the leaderboard rounds, equal the row's.
    """
    leaderboard_path = LEADERBOARD_PATH

    def _refuse(reason: str) -> str:
        log.error(f"{filename} NOT written: {reason}")
        return reason

    if not preds_path.exists():
        return _refuse(f"{preds_path} not found (run models/baselines/benchmarks.py)")
    if not leaderboard_path.exists():
        return _refuse(f"{leaderboard_path} not found")
    leaderboard = pd.read_csv(leaderboard_path)
    need = {"model", "slice", "n", "WAPE_%", "MAE", "Coverage_%", "Coverage_raw_%", "Interval_method"}
    if not need <= set(leaderboard.columns):
        return _refuse(f"{leaderboard_path} lacks columns {sorted(need - set(leaderboard.columns))}")
    rows = leaderboard[(leaderboard["slice"] == "overall") & (leaderboard["model"].astype(str) == model_label)]
    if len(rows) != 1:
        return _refuse(f"{leaderboard_path} has {len(rows)} overall {model_label} rows, expected 1")
    row = rows.iloc[0]

    df = pd.read_parquet(preds_path)
    missing = {"timestamp", "station_id", "p10", "p50", "p90"} - set(df.columns)
    if missing:
        return _refuse(f"{preds_path} lacks columns {sorted(missing)}")
    if "model" in df.columns and not (df["model"].astype(str) == model_label).all():
        return _refuse(f"{preds_path} model column is not all {model_label!r}")
    unknown = sorted(set(df["station_id"].astype(str).unique()) - set(CODES))
    if unknown:
        return _refuse(f"{preds_path} station_ids not in the station table: {unknown}")
    df = df.assign(station_id=df["station_id"].astype(str), month=_month_strings(df["timestamp"]))
    key = ["station_id", "month"]
    if df.duplicated(key).any():
        return _refuse(f"{preds_path} has more than one prediction for a (station_id, month)")
    for col in ("n", "n_expected"):
        if col in leaderboard.columns and float(row[col]) != len(df):
            return _refuse(f"{preds_path} has {len(df)} predictions but the leaderboard's {model_label} "
                           f"row has {col}={float(row[col]):g}; these are not the forecasts it scored")
    if not np.isfinite(df[["p10", "p50", "p90"]].to_numpy(dtype=float)).all():
        return _refuse(f"{preds_path} has non-finite quantiles")

    scored_label = row["Interval_method"]
    if model_key is not None:
        try:
            with open(CONFIG_PATH) as f:
                cfg = yaml.safe_load(f) or {}
            served, plan = serve_band(df, model_key, cfg, calibrator_path=calibrator_path,
                                      forecast_origin=cfg["data"]["val_end"])
        except (OSError, yaml.YAMLError, CalibratorUnavailable, ValueError, KeyError, TypeError) as e:
            return _refuse(str(e))
        label = plan["label"]
        if plan["calibrated"] and plan["provenance"].get("model") != model_label:
            return _refuse(f"{calibrator_path} was fitted for {plan['provenance'].get('model')!r}, "
                           f"not the leaderboard's {model_label!r}")
    else:
        extra = {"p10_raw", "p90_raw", "interval_method"} - set(df.columns)
        if extra:
            return _refuse(f"{preds_path} lacks columns {sorted(extra)}")
        labels = set(df["interval_method"].astype(str))
        if len(labels) != 1:
            return _refuse(f"{preds_path} carries {len(labels)} interval_method labels, expected 1")
        label = labels.pop()
        served = df
        if not np.isfinite(df[["p10_raw", "p90_raw"]].to_numpy(dtype=float)).all():
            return _refuse(f"{preds_path} has non-finite raw quantiles")
    if not isinstance(scored_label, str) or scored_label != label:
        return _refuse(f"the leaderboard's {model_label} Interval_method is {scored_label!r}, but the band "
                       f"served here is {label!r}")
    if not np.isfinite(served[["p10", "p90"]].to_numpy(dtype=float)).all():
        return _refuse(f"the served {model_label} band has non-finite bounds")

    truth = pd.DataFrame({
        "station_id": actuals["station_id"].astype(str).to_numpy(),
        "month": _month_strings(actuals["timestamp"]).to_numpy(),
        "actual": pd.to_numeric(actuals["ridership"], errors="coerce").astype("float64").to_numpy(),
    })
    joined = served.merge(truth, on=key, how="left")
    if len(joined) != len(served) or joined["actual"].isna().any():
        return _refuse("an exported (station_id, month) has no single feature-store actual")
    y = joined["actual"].to_numpy(dtype=float)
    p50 = np.maximum(joined["p50"].to_numpy(dtype=float), 0)  # as compute_metrics scores it
    checks = [
        ("WAPE_%", metric_wape(y, p50)),
        ("MAE", metric_mae(y, p50)),
        ("Coverage_%", coverage(y, joined["p10"].to_numpy(float), joined["p90"].to_numpy(float))),
        ("Coverage_raw_%", coverage(y, joined["p10_raw"].to_numpy(float), joined["p90_raw"].to_numpy(float))),
    ]
    for col, got in checks:
        got, want = round(float(got), 2), float(pd.to_numeric(row[col], errors="coerce"))
        if not (math.isfinite(got) and math.isfinite(want) and math.isclose(got, want, abs_tol=1e-9)):
            return _refuse(f"{preds_path} scores {col}={got} against the feature-store actuals but the "
                           f"leaderboard's {model_label} row has {want}; these are not the forecasts it scored")

    records = [
        {
            "station_id": r.station_id,
            "month": r.month,
            "p10": round(float(r.p10), 0),
            "p50": round(float(r.p50), 0),
            "p90": round(float(r.p90), 0),
            "p10_raw": round(float(r.p10_raw), 0),
            "p90_raw": round(float(r.p90_raw), 0),
            "interval_method": label,
            "model": model_label,
        }
        for r in served.sort_values(key, kind="stable").itertuples(index=False)
    ]
    with open(out_dir / filename, "w") as f:
        json.dump(records, f)
    log.info(
        f"{filename} → {out_dir / filename}  ({len(records)} records, {df['station_id'].nunique()} stations, "
        f"{df['month'].min()} … {df['month'].max()}; band: {label}, coverage {row['Coverage_%']}% "
        f"and WAPE {row['WAPE_%']}% as on the leaderboard)"
    )
    return None


def export_prophet_forecasts(out_dir: Path, actuals: pd.DataFrame) -> str | None:
    """forecasts_prophet.json: Prophet's leaderboard forecasts (see _export_checked_forecasts)."""
    return _export_checked_forecasts(
        out_dir, actuals, filename="forecasts_prophet.json", model_label="Prophet",
        preds_path=PROPHET_PREDS_PATH, model_key="Prophet", calibrator_path=PROPHET_CALIBRATOR_PATH)


def export_seasonal_naive_forecasts(out_dir: Path, actuals: pd.DataFrame) -> str | None:
    """forecasts_seasonal_naive.json: the forecasts benchmarks.py saved for seasonal naive."""
    return _export_checked_forecasts(
        out_dir, actuals, filename="forecasts_seasonal_naive.json", model_label="SeasonalNaive",
        preds_path=SEASONAL_NAIVE_PREDS_PATH)


def export_backtest_windows(out_dir: Path) -> str | None:
    """backtest_windows.json from models/baselines/backtest_windows.py's CSV.

    Refused (returns the reason, writes nothing) unless the CSV has the columns
    below, each window has exactly the leaderboard's models, `n` is the same for
    every row of a window, SARIMA's stations_sarima_beats is empty and every
    other model's is a count of at most that n's stations, and the published
    window (2025-H2) equals the leaderboard's overall rows: WAPE_%, MAE and n,
    with coverage_own_band equal to Coverage_raw_%.
    """
    def _refuse(reason: str) -> str:
        log.error(f"backtest_windows.json NOT written: {reason}")
        return reason

    if not BACKTEST_PATH.exists():
        return _refuse(f"{BACKTEST_PATH} not found (run models/baselines/backtest_windows.py)")
    if not LEADERBOARD_PATH.exists():
        return _refuse(f"{LEADERBOARD_PATH} not found")
    table = pd.read_csv(BACKTEST_PATH)
    need = ["window", "fit_through", "first_month", "last_month", "model", "wape", "mae", "n",
            "coverage_own_band", "stations_sarima_beats"]
    if not set(need) <= set(table.columns):
        return _refuse(f"{BACKTEST_PATH} lacks columns {sorted(set(need) - set(table.columns))}")
    leaderboard = pd.read_csv(LEADERBOARD_PATH)
    overall = leaderboard[leaderboard["slice"] == "overall"]
    models = [str(m) for m in overall["model"]]
    if table.empty or table[need[:-1]].isna().any().any():
        return _refuse(f"{BACKTEST_PATH} is empty or has missing values")

    windows = (table.drop_duplicates("window")[["window", "fit_through", "first_month", "last_month"]]
               .rename(columns={"window": "id"}).to_dict("records"))
    if BACKTEST_PUBLISHED_WINDOW not in {w["id"] for w in windows}:
        return _refuse(f"{BACKTEST_PATH} has no {BACKTEST_PUBLISHED_WINDOW} window")
    for w in windows:
        part = table[table["window"] == w["id"]]
        if (part[["fit_through", "first_month", "last_month"]].nunique() != 1).any():
            return _refuse(f"window {w['id']} has more than one fit_through / first_month / last_month")
        if sorted(part["model"].astype(str)) != sorted(models):
            return _refuse(f"window {w['id']} has models {sorted(part['model'].astype(str))}, "
                           f"the leaderboard's are {sorted(models)}")
        if part["n"].nunique() != 1:
            return _refuse(f"window {w['id']} scored a different number of rows per model: {part['n'].tolist()}")
        beats = part.set_index("model")["stations_sarima_beats"]
        if "SARIMA" not in beats.index or pd.notna(beats["SARIMA"]):
            return _refuse(f"window {w['id']}: SARIMA's stations_sarima_beats must be empty")
        others = beats.drop("SARIMA")
        if others.isna().any() or ((others < 0) | (others > 300) | (others % 1 != 0)).any():
            return _refuse(f"window {w['id']}: stations_sarima_beats must be a station count for every other model")

    published = table[table["window"] == BACKTEST_PUBLISHED_WINDOW]
    for r in published.itertuples(index=False):
        lb = overall[overall["model"].astype(str) == r.model].iloc[0]
        for ours, theirs, col in ((r.wape, lb["WAPE_%"], "WAPE_%"), (r.mae, lb["MAE"], "MAE"),
                                  (r.n, lb["n"], "n"), (r.coverage_own_band, lb.get("Coverage_raw_%"), "Coverage_raw_%")):
            if not (math.isfinite(float(ours)) and pd.notna(theirs) and float(ours) == float(theirs)):
                return _refuse(f"{BACKTEST_PUBLISHED_WINDOW} {r.model}: {col} is {ours} in {BACKTEST_PATH} "
                               f"but {theirs} on the leaderboard")

    def _num(v, as_int=False):
        return None if pd.isna(v) else (int(v) if as_int else float(v))

    rows = [
        {
            "window": r.window, "model": r.model, "wape": _num(r.wape), "mae": _num(r.mae),
            "n": _num(r.n, True), "coverage_own_band": _num(r.coverage_own_band),
            "stations_sarima_beats": _num(r.stations_sarima_beats, True),
        }
        for r in table.itertuples(index=False)
    ]
    payload = {
        "windows": windows, "rows": rows,
        "source": str(BACKTEST_PATH), "generated_by": "models/baselines/backtest_windows.py",
    }
    with open(out_dir / "backtest_windows.json", "w") as f:
        json.dump(payload, f, indent=2)
    log.info(f"backtest_windows.json → {out_dir / 'backtest_windows.json'}  ({len(windows)} windows, {len(rows)} rows; "
             f"{BACKTEST_PUBLISHED_WINDOW} equals the leaderboard)")
    return None


def export_model_comparison(out_dir: Path) -> None:
    leaderboard_path = LEADERBOARD_PATH
    if leaderboard_path.exists():
        leaderboard = pd.read_csv(leaderboard_path)
        comparison = []
        for _, row in leaderboard.iterrows():
            comparison.append({
                "model": row["model"],
                # MAE/MAPE/WAPE can legitimately be NaN (e.g. metrics.py's wape()
                # returns NaN on a zero denominator) — json.dump would serialize
                # a bare `NaN` token, which isn't valid JSON and breaks every
                # website consumer's JSON.parse() for the whole comparison table.
                "MAE": round(float(row["MAE"]), 0) if pd.notna(row["MAE"]) else None,
                "MAPE_pct": round(float(row["MAPE_%"]), 1) if pd.notna(row["MAPE_%"]) else None,
                "WAPE_pct": round(float(row["WAPE_%"]), 1) if pd.notna(row["WAPE_%"]) else None,
                "Coverage_pct": round(float(row["Coverage_%"]), 1) if "Coverage_%" in row and pd.notna(row["Coverage_%"]) else None,
                # Coverage_pct scores the band named by Interval_method (a
                # conformal band fit on data up to val_end, or the model's own);
                # Coverage_raw_pct always scores the model's own band. Without
                # the label a calibrated and a raw coverage read the same.
                "Coverage_raw_pct": round(float(row["Coverage_raw_%"]), 1) if "Coverage_raw_%" in row and pd.notna(row["Coverage_raw_%"]) else None,
                "Interval_method": row["Interval_method"] if "Interval_method" in row and pd.notna(row["Interval_method"]) else None,
                "n_predictions": int(row["n"]) if "n" in row and pd.notna(row["n"]) else None,
                # Which code path produced this row. The two paths score
                # different splits, so a number is meaningless without it.
                "source": "benchmark_leaderboard",
                "scored_split": "test",
            })
        with open(out_dir / "model_comparison.json", "w") as f:
            json.dump(comparison, f, indent=2)
        log.info(f"model_comparison.json → {out_dir / 'model_comparison.json'}  ({len(comparison)} models from benchmark leaderboard)")
        return

    # No leaderboard means benchmarks.py did not complete. The branch below
    # scores whatever forecast parquets happen to be on disk against the
    # VALIDATION split, while the leaderboard scores the TEST split — so the
    # two paths are not interchangeable, and silently taking this one is how
    # Prophet's unreproducible 176.3% WAPE reached the published site and sat
    # there for five months. Require it to be asked for explicitly. main()
    # already checked this before writing anything; this is the backstop.
    require_leaderboard()

    log.warning("Using validation-split fallback — numbers are NOT comparable "
                "to a benchmarks.py leaderboard run")

    actuals_path = Path("data/processed/splits/val.parquet")
    if not actuals_path.exists():
        log.error("No val split either — cannot write model_comparison.json")
        raise SystemExit(1)
    actuals = pd.read_parquet(actuals_path)
    actuals["timestamp"] = pd.to_datetime(actuals["timestamp"])
    _ts = actuals["timestamp"].dt.tz_localize(None) if actuals["timestamp"].dt.tz is not None else actuals["timestamp"]
    actuals["month"] = _ts.dt.to_period("M").astype(str)

    comparison = []
    for model_name, path in [
        ("Prophet", Path("models/baselines/outputs/prophet/prophet_forecasts.parquet")),
        ("SARIMA",  Path("models/baselines/outputs/arima/arima_forecasts.parquet")),
    ]:
        if not path.exists():
            continue
        preds = pd.read_parquet(path)
        preds["timestamp"] = pd.to_datetime(preds["timestamp"])
        preds["month"] = preds["timestamp"].dt.to_period("M").astype(str)
        merged = preds.merge(
            actuals[["station_id", "month", "ridership"]].rename(columns={"ridership": "actual"}),
            on=["station_id", "month"], how="inner",
        )
        if merged.empty:
            continue
        y_pred = merged["p50"].values.astype(float)
        y_true = merged["actual"].values.astype(float)
        nonzero = y_true != 0
        mae  = float(abs(y_pred - y_true).mean())
        # nonzero can legitimately be empty (all-zero actuals in this station/month
        # slice) and abs(y_true).sum() can legitimately be zero — both produce a
        # bare NaN/Infinity float here, same failure mode already guarded against
        # in the leaderboard branch above. json.dump would emit an invalid `NaN`/
        # `Infinity` token and break every website consumer's JSON.parse().
        mape = float(abs((y_pred[nonzero] - y_true[nonzero]) / y_true[nonzero]).mean() * 100)
        wape = float(abs(y_pred - y_true).sum() / abs(y_true).sum() * 100)
        comparison.append({
            "model": model_name,
            "MAE": round(mae, 0) if math.isfinite(mae) else None,
            "MAPE_pct": round(mape, 1) if math.isfinite(mape) else None,
            "WAPE_pct": round(wape, 1) if math.isfinite(wape) else None,
            "n_predictions": len(merged),
            "source": "val_split_fallback",
            "scored_split": "val",
        })
    with open(out_dir / "model_comparison.json", "w") as f:
        json.dump(comparison, f, indent=2)
    log.info(f"model_comparison.json → {out_dir / 'model_comparison.json'}  ({len(comparison)} models)")


def publish_outputs(staging: Path, out_dir: Path) -> list[str]:
    """Move every file in `staging` into `out_dir`, all or none.

    Each move is an os.replace, so a reader never sees a half-written file.
    The set is not atomic, so each file being replaced is first copied into
    staging/.backup and put back if a later move fails; a file the target did
    not have is removed again. Returns the published file names.
    """
    names = sorted(p.name for p in staging.iterdir() if p.is_file())
    backup = staging / ".backup"
    backup.mkdir()
    out_dir.mkdir(parents=True, exist_ok=True)
    done: list[str] = []
    try:
        for name in names:
            target = out_dir / name
            if target.exists():
                shutil.copy2(target, backup / name)
            os.replace(staging / name, target)
            done.append(name)
    except BaseException:
        for name in done:
            if (backup / name).exists():
                os.replace(backup / name, out_dir / name)
            else:
                (out_dir / name).unlink(missing_ok=True)
        raise
    return names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--feature-store",
        default="data/processed/feature_store.parquet",
        help="Path to feature store parquet",
    )
    parser.add_argument(
        "--out-dir",
        default="website/data",
        help="Output directory for JSON files",
    )
    parser.add_argument(
        "--allow-val-fallback",
        action="store_true",
        help="Permit scoring saved forecasts against the validation split when "
             "no benchmark leaderboard exists. Those numbers are not comparable "
             "to a benchmarks.py run; off by default so a missing leaderboard "
             "fails instead of publishing silently.",
    )
    args = parser.parse_args()

    global ALLOW_FALLBACK
    ALLOW_FALLBACK = args.allow_val_fallback

    out_dir = Path(args.out_dir)

    # Every check that can stop the run goes before the first write, so a
    # failed input leaves website/data/ as it was rather than partly
    # regenerated.
    df = load_feature_store(Path(args.feature_store))
    check_station_ids(df)
    agg = compute_station_ridership(df)
    check_station_averages(agg)
    require_leaderboard()

    log.info(f"Station ridership range: {agg['avg_monthly_ridership'].min():,.0f} — "
             f"{agg['avg_monthly_ridership'].max():,.0f} riders/month")

    ridership_json = build_ridership_json(agg)
    meta_json = build_meta_json(agg)

    # Everything is written to a staging directory on the same filesystem as
    # out_dir (os.replace cannot cross filesystems) and published only if every
    # step succeeded; see publish_outputs().
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".export-staging-", dir=out_dir.parent))
    try:
        with open(staging / "stations_ridership.json", "w") as f:
            json.dump(ridership_json, f, indent=2)
        log.info(f"stations_ridership.json staged  ({len(ridership_json)} stations)")

        with open(staging / "stations_meta.json", "w") as f:
            json.dump(meta_json, f, indent=2)
        log.info(f"stations_meta.json      staged  ({len(meta_json)} stations)")

        export_ridership_actuals(df, staging)
        refusals = [r for r in (
            export_forecasts(staging, df),
            export_sarima_forecasts(staging, df),
            export_prophet_forecasts(staging, df),
            export_seasonal_naive_forecasts(staging, df),
            export_backtest_windows(staging),
        ) if r]
        forecasts_refused = "; ".join(refusals) if refusals else None
        export_model_comparison(staging)

        if forecasts_refused is not None:
            # Exit non-zero so scripts/run_pipeline.sh (set -e) stops before it
            # prints the deploy command. Nothing is published, so the old
            # forecasts.json is not left beside fresh data.
            log.error(
                f"A forecasts or backtest file was refused. Reason: {forecasts_refused}. "
                f"Nothing was published; {out_dir} is unchanged. Exiting 1."
            )
            raise SystemExit(1)

        published = publish_outputs(staging, out_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    log.info(f"Published {', '.join(published)} → {out_dir}")
    log.info("Done. Commit website/data/ to repo.")


if __name__ == "__main__":
    main()
