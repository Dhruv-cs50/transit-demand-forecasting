"""
scripts/export_website_data.py
────────────────────────────────
Reads the feature store and the benchmark run's outputs and exports the five
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
      The Chronos zero-shot P10/P50/P90 test-window forecasts that
      models/baselines/benchmarks.py wrote to
      evaluation/outputs/chronos2_zeroshot_preds.parquet and scored on the
      leaderboard, sorted by station then month: station_id, month, p10, p50,
      p90. Written only if the leaderboard has exactly one overall Chronos
      row, every prediction came from the zero-shot model, each
      (station_id, month) appears once, and the number of predictions equals
      that row's `n` (and `n_expected`, when the leaderboard has it).
      Otherwise forecasts.json is refused: an error is logged, any existing
      forecasts.json is left as it is (and is then stale), the other files
      are still written, and the script exits 1 so scripts/run_pipeline.sh
      stops before its deploy step. Read by website/sections.jsx and
      website/charts.jsx.

  model_comparison.json
      The benchmark leaderboard (evaluation/outputs/benchmark_leaderboard.csv).
      Read by website/sections.jsx and website/charts.jsx.

If the leaderboard does not exist (and --allow-val-fallback is not given),
the script exits 1 before writing any file.

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
import sys
from pathlib import Path

import pandas as pd

# Run as a script, sys.path[0] is scripts/, so the repo's top-level packages
# are not importable without the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def export_forecasts(out_dir: Path) -> str | None:
    """Export the benchmark run's Chronos zero-shot forecasts.

    These are the predictions benchmarks.py scored on the leaderboard. When
    the Chronos backend cannot run, the Predictor falls back to seasonal
    naive, still writes the preds parquet (model_mode != "zeroshot"), and
    benchmarks.py leaves the Chronos row off the leaderboard. The same two
    signals gate this export, so fallback forecasts are never published as
    Chronos. The preds must also be the run that leaderboard row scored: one
    prediction per (station_id, month), as many as the row's `n` (and
    `n_expected`, when the leaderboard has that column).

    Returns None when forecasts.json was written, or the reason it was
    refused. On refusal nothing is written or deleted; main() then exits 1.
    """
    preds_path = PREDS_PATH
    leaderboard_path = LEADERBOARD_PATH

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

    records = [
        {
            "station_id": row.station_id,
            "month":      row.month,
            "p10":        _finite_or_none(row.p10),
            "p50":        _finite_or_none(row.p50),
            "p90":        _finite_or_none(row.p90),
        }
        for row in df.itertuples(index=False)
    ]
    with open(out_dir / "forecasts.json", "w") as f:
        json.dump(records, f)
    log.info(
        f"forecasts.json → {out_dir / 'forecasts.json'}  ({len(records)} records, "
        f"{df['station_id'].nunique()} stations, {df['month'].min()} … {df['month'].max()}; "
        f"{model_label} from {preds_path})"
    )
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
    # regenerated. A refused forecasts.json is the exception: the other files
    # are still written and the exit code reports it (below).
    df = load_feature_store(Path(args.feature_store))
    check_station_ids(df)
    agg = compute_station_ridership(df)
    check_station_averages(agg)
    require_leaderboard()

    log.info(f"Station ridership range: {agg['avg_monthly_ridership'].min():,.0f} — "
             f"{agg['avg_monthly_ridership'].max():,.0f} riders/month")

    ridership_json = build_ridership_json(agg)
    meta_json = build_meta_json(agg)

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "stations_ridership.json", "w") as f:
        json.dump(ridership_json, f, indent=2)
    log.info(f"stations_ridership.json → {out_dir / 'stations_ridership.json'}  ({len(ridership_json)} stations)")

    with open(out_dir / "stations_meta.json", "w") as f:
        json.dump(meta_json, f, indent=2)
    log.info(f"stations_meta.json     → {out_dir / 'stations_meta.json'}  ({len(meta_json)} stations)")

    export_ridership_actuals(df, out_dir)
    forecasts_refused = export_forecasts(out_dir)
    export_model_comparison(out_dir)

    if forecasts_refused is not None:
        # Exit non-zero so scripts/run_pipeline.sh (set -e) stops before its
        # deploy step instead of publishing the stale file beside fresh data.
        log.error(
            f"forecasts.json NOT written; {out_dir / 'forecasts.json'} (if "
            f"present) is stale. Reason: {forecasts_refused}. The other files "
            f"were written; exiting 1."
        )
        raise SystemExit(1)

    log.info("Done. Commit website/data/ to repo.")


if __name__ == "__main__":
    main()
