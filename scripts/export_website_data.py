"""
scripts/export_website_data.py
────────────────────────────────
Reads the feature store and exports JSON files under website/data/. Two of
them are not currently read by any page in website/ (kept for a future
ridership heat-map integration; grep confirms no fetch() of either file
anywhere in website/*.jsx or *.html):

  website/data/stations_ridership.json
      Per-station average monthly ridership + normalized heat scale (0-2.4).
      Was consumed by website/transit-map.jsx, which was deleted 2026-07-12
      when the live map moved to transit-demo.html's Google Maps
      implementation (transit-demo.html uses its own hardcoded per-station
      heat multipliers instead, not this file).

  website/data/stations_meta.json
      Station list with real names and BART IDs. Not read by the "Real BART
      Data" section's station picker either — BARTForecasts in sections.jsx
      hardcodes its own KEY_STATIONS list instead.

The other three exports below (export_ridership_actuals/export_forecasts/
export_model_comparison) ARE consumed live, by sections.jsx and charts.jsx.

Usage:
    python scripts/export_website_data.py
    python scripts/export_website_data.py --feature-store data/processed/feature_store_enriched.parquet
"""

import argparse
import json
import logging
import math
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("export_website_data")

# Mapping from BART 4-letter station codes (machine_learning_files/fetch_bart_od.py's
# STATION_NAMES — the actual `station_id` values produced by merge_pipeline.py) →
# website station IDs used in website/transit-demo.html's station array.
# Codes with no website counterpart (ASHB, PLZA, MLPT, NCON, OAKL, PCTR, SHAY, WARM,
# WCRK) are omitted. PCTR ("Pittsburg Center", the Ebart infill station) has no
# distinct website node — PITT ("Pittsburg/Bay Point") maps to the website's single
# "pit" / "Pittsburg" entry.
BART_CODE_TO_WEBSITE_ID = {
    "12TH": "12th",  # 12th St. Oakland City Center
    "16TH": "16th",  # 16th St. Mission
    "19TH": "19th",  # 19th St. Oakland
    "24TH": "24th",  # 24th St. Mission
    "ANTC": "ant",   # Antioch
    "BALB": "bls",   # Balboa Park
    "BAYF": "bayp",  # Bay Fair
    "BERY": "brb",   # Berryessa/North San José
    "CAST": "cas",   # Castro Valley
    "CIVC": "cvc",   # Civic Center/UN Plaza
    "COLS": "col",   # Coliseum
    "COLM": "colm",  # Colma
    "CONC": "ccd",   # Concord
    "DALY": "daly",  # Daly City
    "DBRK": "bky",   # Downtown Berkeley
    "DUBL": "dub",   # Dublin/Pleasanton
    "DELN": "elc",   # El Cerrito Del Norte → website's single "El Cerrito"
    "EMBR": "emb",   # Embarcadero
    "FRMT": "frm",   # Fremont
    "FTVL": "fvw",   # Fruitvale
    "GLEN": "gln",   # Glen Park
    "HAYW": "hyw",   # Hayward
    "LAFY": "lfy",   # Lafayette
    "LAKE": "lkm",   # Lake Merritt
    "MCAR": "mac",   # MacArthur
    "MLBR": "mil",   # Millbrae
    "MONT": "mtg",   # Montgomery St.
    "NBRK": "nbk",   # North Berkeley
    "ORIN": "orn",   # Orinda
    "PITT": "pit",   # Pittsburg/Bay Point → website's Pittsburg
    "PHIL": "plh",   # Pleasant Hill/Contra Costa Centre
    "POWL": "pwl",   # Powell St.
    "RICH": "rich",  # Richmond
    "ROCK": "rkr",   # Rockridge
    "SBRN": "sbr",   # San Bruno
    "SFIA": "sfo",   # SFO Airport
    "SANL": "sl",    # San Leandro
    "SSAN": "ssf",   # South San Francisco
    "UCTY": "unc",   # Union City
    "WDUB": "wdb",   # West Dublin/Pleasanton
    "WOAK": "wo",    # West Oakland
}

WEBSITE_IDS_WITH_REAL_DATA = set(BART_CODE_TO_WEBSITE_ID.values())


def load_feature_store(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Feature store not found: {path}")
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    log.info(f"Loaded feature store: {len(df):,} rows, {df['station_id'].nunique()} stations")
    return df


def compute_station_ridership(df: pd.DataFrame) -> pd.DataFrame:
    """Average monthly ridership per station across all available months."""
    agg = (
        df.groupby(["station_id", "station_name"])["ridership"]
        .mean()
        .reset_index()
        .rename(columns={"ridership": "avg_monthly_ridership"})
    )
    return agg


def normalize_to_heat_scale(series: pd.Series, target_max: float = 2.4) -> pd.Series:
    """
    Normalize ridership to 0–2.4 scale matching transit-map.jsx heat range.
    Uses soft normalization: 95th percentile as the ceiling to avoid one
    outlier dominating the color scale.
    """
    ceiling = series.quantile(0.95)
    if ceiling == 0:
        return pd.Series(0.1, index=series.index)
    normalized = (series / ceiling * target_max).clip(upper=target_max)
    return normalized.round(3)


def build_ridership_json(agg: pd.DataFrame) -> dict:
    """Build the stations_ridership.json payload."""
    max_ridership = agg["avg_monthly_ridership"].quantile(0.95)
    agg = agg.copy()
    agg["normalized"] = normalize_to_heat_scale(agg["avg_monthly_ridership"])
    agg["website_id"] = agg["station_id"].map(BART_CODE_TO_WEBSITE_ID)

    out = {}
    for _, row in agg.iterrows():
        wid = row["website_id"]
        if not wid or wid not in WEBSITE_IDS_WITH_REAL_DATA:
            continue
        # baseAM slightly higher (commute direction), basePM symmetric
        # Real BART OD skews AM-inbound for SF/Oakland core stations.
        # Simple heuristic: core stations get AM boost, commuter get PM boost.
        norm = float(row["normalized"])
        out[wid] = {
            "bart_id": row["station_id"],
            "station_name": row["station_name"],
            "avg_monthly_ridership": round(float(row["avg_monthly_ridership"]), 0),
            "normalized": norm,
            "baseAM": round(norm * 1.05, 3),   # slight AM bias
            "basePM": round(norm * 0.95, 3),   # slight PM bias
        }

    return out


def build_meta_json(agg: pd.DataFrame) -> list:
    """Build the stations_meta.json payload — flat list for dropdowns."""
    records = []
    for _, row in agg.sort_values("avg_monthly_ridership", ascending=False).iterrows():
        wid = BART_CODE_TO_WEBSITE_ID.get(row["station_id"])
        records.append({
            "bart_id": row["station_id"],
            "website_id": wid or None,
            "station_name": row["station_name"],
            "avg_monthly_ridership": round(float(row["avg_monthly_ridership"]), 0),
        })
    return records


def export_ridership_actuals(df: pd.DataFrame, out_dir: Path) -> None:
    records = []
    for _, row in df.sort_values(["station_id", "timestamp"]).iterrows():
        # Map the 4-letter BART code (this DataFrame's real station_id,
        # per merge_pipeline.py) to the website_id convention that
        # build_ridership_json()/build_meta_json() already use below —
        # without this, this function wrote the raw 4-letter code through
        # unmapped, which never matched any website station identifier.
        # Stations with no website counterpart (see BART_CODE_TO_WEBSITE_ID's
        # header comment) are skipped, matching build_ridership_json().
        wid = BART_CODE_TO_WEBSITE_ID.get(row["station_id"])
        if not wid:
            continue
        ts = pd.to_datetime(row["timestamp"])
        if hasattr(ts, "tz") and ts.tz is not None:
            ts = ts.tz_localize(None)
        records.append({
            "station_id": wid,
            "month":      ts.strftime("%Y-%m"),
            "ridership":  int(row["ridership"]),
            "daily_est":  round(float(row.get("ridership_daily_est", row["ridership"] / 22)), 1),
        })
    with open(out_dir / "ridership_actuals.json", "w") as f:
        json.dump(records, f)
    log.info(f"ridership_actuals.json → {out_dir / 'ridership_actuals.json'}  ({len(records)} records)")


def export_forecasts(out_dir: Path) -> None:
    forecast_dir = Path("models/chronos2/outputs")
    files = sorted(forecast_dir.glob("zero_shot_forecasts_*.parquet"))
    if not files:
        log.warning("No forecast files found — skipping forecasts.json")
        return
    df = pd.read_parquet(files[-1])
    q10_col = next((c for c in df.columns if "0.1" in str(c)), None)
    q50_col = next((c for c in df.columns if "0.5" in str(c)), None)
    q90_col = next((c for c in df.columns if "0.9" in str(c)), None)

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

    records = []
    for _, row in df.iterrows():
        # Same website_id mapping as export_ridership_actuals() above — this
        # loop also wrote the raw 4-letter station_id through unmapped.
        wid = BART_CODE_TO_WEBSITE_ID.get(row["station_id"])
        if not wid:
            continue
        ts = row.get("timestamp", "")
        month_str = ts.strftime("%Y-%m") if hasattr(ts, "strftime") else str(ts)[:7]
        records.append({
            "station_id": wid,
            "month":  month_str,
            "p10":    _finite_or_none(row[q10_col]) if q10_col else None,
            "p50":    _finite_or_none(row[q50_col]) if q50_col else None,
            "p90":    _finite_or_none(row[q90_col]) if q90_col else None,
        })
    with open(out_dir / "forecasts.json", "w") as f:
        json.dump(records, f)
    log.info(f"forecasts.json → {out_dir / 'forecasts.json'}  ({len(records)} records)")


def export_model_comparison(out_dir: Path) -> None:
    leaderboard_path = Path("evaluation/outputs/benchmark_leaderboard.csv")
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
            })
        with open(out_dir / "model_comparison.json", "w") as f:
            json.dump(comparison, f, indent=2)
        log.info(f"model_comparison.json → {out_dir / 'model_comparison.json'}  ({len(comparison)} models from benchmark leaderboard)")
        return

    actuals_path = Path("data/processed/splits/val.parquet")
    if not actuals_path.exists():
        log.warning("No val split — skipping model_comparison.json")
        return
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
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_feature_store(Path(args.feature_store))
    agg = compute_station_ridership(df)

    log.info(f"Station ridership range: {agg['avg_monthly_ridership'].min():,.0f} — "
             f"{agg['avg_monthly_ridership'].max():,.0f} riders/month")

    ridership_json = build_ridership_json(agg)
    meta_json = build_meta_json(agg)

    with open(out_dir / "stations_ridership.json", "w") as f:
        json.dump(ridership_json, f, indent=2)
    log.info(f"stations_ridership.json → {out_dir / 'stations_ridership.json'}  ({len(ridership_json)} stations)")

    with open(out_dir / "stations_meta.json", "w") as f:
        json.dump(meta_json, f, indent=2)
    log.info(f"stations_meta.json     → {out_dir / 'stations_meta.json'}  ({len(meta_json)} stations)")

    export_ridership_actuals(df, out_dir)
    export_forecasts(out_dir)
    export_model_comparison(out_dir)

    log.info("Done. Commit website/data/ to repo.")


if __name__ == "__main__":
    main()
