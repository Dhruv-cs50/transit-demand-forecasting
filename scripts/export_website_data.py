"""
scripts/export_website_data.py
────────────────────────────────
Reads the feature store and exports two JSON files consumed by the website:

  website/data/stations_ridership.json
      Per-station average monthly ridership + normalized heat scale (0-2.4)
      Used by transit-map.jsx to anchor station heat values to real data.

  website/data/stations_meta.json
      Station list with real names and BART IDs — used by Demo dropdowns.

Usage:
    python scripts/export_website_data.py
    python scripts/export_website_data.py --feature-store data/processed/feature_store_enriched.parquet
"""

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("export_website_data")

# Mapping from BART 2-letter codes in feature store → website station IDs in transit-map.jsx.
# Only codes that have a matching station in the website's BART_STATIONS array are included.
# Codes with no website counterpart (AS, EP, ML, NC, OA, SH, WC, WP, WS) are omitted.
BART_CODE_TO_WEBSITE_ID = {
    "12": "12th",   # 12th St. Oakland City Center
    "16": "16th",   # 16th St. Mission
    "19": "19th",   # 19th St. Oakland
    "24": "24th",   # 24th St. Mission
    "AN": "ant",    # Antioch
    "BE": "brb",    # Berryessa/North San José
    "BF": "bayp",   # Bay Fair
    "BK": "bky",    # Downtown Berkeley
    "BP": "bls",    # Balboa Park
    "CC": "cvc",    # Civic Center/UN Plaza (BART, distinct from VTA cvc)
    "CL": "col",    # Coliseum
    "CM": "colm",   # Colma
    "CN": "ccd",    # Concord
    "CV": "cas",    # Castro Valley
    "DC": "daly",   # Daly City
    "ED": "dub",    # Dublin/Pleasanton
    "EM": "emb",    # Embarcadero
    "EN": "elc",    # El Cerrito Del Norte → website's single "El Cerrito"
    "FM": "frm",    # Fremont
    "FV": "fvw",    # Fruitvale
    "GP": "gln",    # Glen Park
    "HY": "hyw",    # Hayward
    "LF": "lfy",    # Lafayette
    "LM": "lkm",    # Lake Merritt
    "MA": "mac",    # MacArthur
    "MB": "mil",    # Millbrae
    "MT": "mtg",    # Montgomery St.
    "NB": "nbk",    # North Berkeley
    "OR": "orn",    # Orinda
    "OW": "wo",     # West Oakland
    "PC": "pit",    # Pittsburg Center → website's Pittsburg
    "PH": "plh",    # Pleasant Hill/Contra Costa Centre
    "PL": "pwl",    # Powell St.
    "RM": "rich",   # Richmond
    "RR": "rkr",    # Rockridge
    "SB": "sbr",    # San Bruno
    "SL": "sl",     # San Leandro
    "SO": "sfo",    # SFO Airport
    "SS": "ssf",    # South San Francisco
    "UC": "unc",    # Union City
    "WD": "wdb",    # West Dublin/Pleasanton
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
        ts = pd.to_datetime(row["timestamp"])
        if hasattr(ts, "tz") and ts.tz is not None:
            ts = ts.tz_localize(None)
        records.append({
            "station_id": row["station_id"],
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
    records = []
    for _, row in df.iterrows():
        ts = row.get("timestamp", "")
        month_str = ts.strftime("%Y-%m") if hasattr(ts, "strftime") else str(ts)[:7]
        records.append({
            "station_id": row["station_id"],
            "month":  month_str,
            "p10":    round(float(row[q10_col]), 0) if q10_col else None,
            "p50":    round(float(row[q50_col]), 0) if q50_col else None,
            "p90":    round(float(row[q90_col]), 0) if q90_col else None,
        })
    with open(out_dir / "forecasts.json", "w") as f:
        json.dump(records, f)
    log.info(f"forecasts.json → {out_dir / 'forecasts.json'}  ({len(records)} records)")


def export_model_comparison(out_dir: Path) -> None:
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
        mape = float(abs((y_pred[nonzero] - y_true[nonzero]) / y_true[nonzero]).mean() * 100)
        wape = float(abs(y_pred - y_true).sum() / abs(y_true).sum() * 100)
        comparison.append({
            "model": model_name, "MAE": round(mae, 0),
            "MAPE_pct": round(mape, 1), "WAPE_pct": round(wape, 1),
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
