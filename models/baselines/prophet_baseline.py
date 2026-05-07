"""
models/baselines/prophet.py
────────────────────────────
Prophet baseline for Bay Area transit ridership forecasting.

Prophet handles three things natively that matter for this project:
  - Multiple seasonalities (daily commute + weekly weekend pattern)
  - Holidays (US/CA public holidays)
  - Regressors (rain intensity, is_game_day as external covariates)

This gives us a strong classical baseline. If Chronos-2 can't beat
Prophet on game nights and rainy days, the neural model isn't earning
its complexity — and we need to know that.

Usage:
    python models/baselines/prophet.py
    python models/baselines/prophet.py --station EMBR --horizon 24
"""

from __future__ import annotations

import logging
from pathlib import Path

import holidays
import numpy as np
import pandas as pd
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("prophet_baseline")

PROCESSED_DIR = Path("data/processed")
OUTPUT_DIR    = Path("models/baselines/outputs/prophet")
CONFIG_PATH   = Path("configs/model.yaml")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── Holiday calendar ───────────────────────────────────────────────────────────

def make_holiday_df(start: str, end: str) -> pd.DataFrame:
    """Build a Prophet-compatible holiday DataFrame for US/CA."""
    ca_holidays = holidays.country_holidays("US", subdiv="CA",
                                            years=range(2019, 2027))
    rows = [{"holiday": name, "ds": pd.Timestamp(date)}
            for date, name in ca_holidays.items()]
    df = pd.DataFrame(rows)
    df["lower_window"] = 0
    df["upper_window"] = 1    # day-after effect (e.g. day after Thanksgiving)
    return df


# ── Per-station model ──────────────────────────────────────────────────────────

def fit_station(
    station_df: pd.DataFrame,
    station_id: str,
    cfg: dict,
) -> tuple:
    """
    Fit a Prophet model for a single station.

    Regressors added:
      - precip_intensity : rain bucket 0–4 (nonlinear weather signal)
      - is_game_day      : binary event flag
      - is_sharks_game   : Sharks-specific spike
      - is_holiday       : CA public holiday

    Returns (model, train_df) tuple.
    """
    try:
        from prophet import Prophet
    except ImportError:
        raise ImportError("Install Prophet: pip install prophet")

    cfg_prophet = cfg.get("prophet", {})

    # Prophet requires ds + y columns
    train = station_df.copy()
    train["ds"] = pd.to_datetime(train["timestamp"]).dt.tz_localize(None)  # Prophet needs tz-naive
    train["y"]  = train["ridership"].clip(lower=0)
    train = train.dropna(subset=["y"])

    # Build regressor list from available columns
    regressors = []
    for col in ["precip_intensity", "is_game_day", "is_sharks_game_window", "is_holiday"]:
        if col in train.columns:
            train[col] = train[col].astype(float).fillna(0)
            regressors.append(col)

    log.info(f"  Station {station_id}: {len(train):,} rows | regressors: {regressors}")

    holidays_df = make_holiday_df("2019-01-01", "2027-01-01")

    model = Prophet(
        yearly_seasonality  = cfg_prophet.get("yearly_seasonality", True),
        weekly_seasonality  = cfg_prophet.get("weekly_seasonality", True),
        daily_seasonality   = cfg_prophet.get("daily_seasonality", True),
        changepoint_prior_scale = cfg_prophet.get("changepoint_prior_scale", 0.05),
        holidays            = holidays_df,
        uncertainty_samples = 200,
    )

    # Add regressors
    for reg in regressors:
        model.add_regressor(reg, standardize=True)

    model.fit(train[["ds", "y"] + regressors])
    return model, train, regressors


def predict_station(
    model,
    future_df: pd.DataFrame,
    regressors: list[str],
    horizon_steps: int,
    last_ds: pd.Timestamp,
    freq: str,
) -> pd.DataFrame:
    """
    Run Prophet prediction for `horizon_steps` steps beyond `last_ds`.
    Attaches future regressor values from future_df if available.
    """
    # Build future DataFrame
    future_dates = pd.date_range(
        start=last_ds + pd.tseries.frequencies.to_offset(freq),
        periods=horizon_steps,
        freq=freq,
    )
    future = pd.DataFrame({"ds": future_dates})

    # Attach regressor values from future_df
    if not future_df.empty:
        future_df_copy = future_df.copy()
        future_df_copy["ds"] = pd.to_datetime(future_df_copy["timestamp"]).dt.tz_localize(None)
        for reg in regressors:
            if reg in future_df_copy.columns:
                future = future.merge(
                    future_df_copy[["ds", reg]],
                    on="ds", how="left"
                )
                future[reg] = future[reg].fillna(0).astype(float)
            else:
                future[reg] = 0.0
    else:
        for reg in regressors:
            future[reg] = 0.0

    forecast = model.predict(future)

    # Build output with P10/P50/P90
    result = pd.DataFrame({
        "timestamp": future_dates,
        "p10":       forecast["yhat_lower"].clip(lower=0).values,
        "p50":       forecast["yhat"].clip(lower=0).values,
        "p90":       forecast["yhat_upper"].clip(lower=0).values,
    })
    return result


# ── Full pipeline ──────────────────────────────────────────────────────────────

def run_prophet_all_stations(
    df: pd.DataFrame,
    cfg: dict,
    output_dir: Path = OUTPUT_DIR,
) -> pd.DataFrame:
    """
    Fit Prophet for every station and generate forecasts.
    Used by evaluation/benchmarks.py for head-to-head comparison.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    freq         = cfg["data"]["resample_freq"]
    train_end    = pd.Timestamp(cfg["data"]["train_end"], tz="America/Los_Angeles")
    val_end      = pd.Timestamp(cfg["data"]["val_end"],   tz="America/Los_Angeles")

    # Use step-based horizon for monthly data; fall back to hour-based
    horizon_steps = cfg["chronos2"].get("prediction_length_steps", None)
    if horizon_steps is None:
        horizon_hrs  = cfg["data"]["forecast_horizon_hours"]
        steps_per_hour = pd.tseries.frequencies.to_offset(freq).nanos / (3600 * 1e9)
        horizon_steps  = int(horizon_hrs * steps_per_hour)
    # For monthly data, Prophet freq should be monthly
    freq = "MS"  # month start — matches our monthly BART timestamps

    train_df = df[df["timestamp"] <= train_end]
    test_df  = df[df["timestamp"] >  val_end]

    stations = df["station_id"].unique()
    all_preds = []

    for station_id in stations:
        log.info(f"\nFitting Prophet for station: {station_id}")
        station_train = train_df[train_df["station_id"] == station_id]
        station_future = test_df[test_df["station_id"] == station_id]

        if len(station_train) < 3:   # need at least 3 data points
            log.warning(f"  Skipping {station_id} — not enough training data")
            continue

        try:
            model, _, regressors = fit_station(station_train, station_id, cfg)
            last_ds = pd.to_datetime(station_train["timestamp"].max()).tz_localize(None)
            preds = predict_station(
                model, station_future, regressors, horizon_steps, last_ds, freq
            )
            preds["station_id"] = station_id
            preds["model"]      = "Prophet"
            all_preds.append(preds)
            log.info(f"  ✅ {station_id}: {len(preds)} forecast steps")
        except Exception as e:
            log.error(f"  ❌ Prophet failed for {station_id}: {e}")

    if not all_preds:
        return pd.DataFrame()

    combined = pd.concat(all_preds, ignore_index=True)
    out = output_dir / "prophet_forecasts.parquet"
    combined.to_parquet(out, index=False)
    log.info(f"\nProphet forecasts saved → {out}")
    return combined


# ── Standalone ─────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run Prophet baseline")
    parser.add_argument("--station", default=None)
    parser.add_argument("--horizon", type=int, default=None)
    args = parser.parse_args()

    cfg = load_config()

    path = PROCESSED_DIR / "feature_store_enriched.parquet"
    if not path.exists():
        path = PROCESSED_DIR / "feature_store.parquet"
    if not path.exists():
        log.error("Feature store not found. Run: python processing/merge_pipeline.py")
        return

    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    if args.station:
        df = df[df["station_id"] == args.station]

    if args.horizon:
        cfg["data"]["forecast_horizon_hours"] = args.horizon

    run_prophet_all_stations(df, cfg)


if __name__ == "__main__":
    main()
