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

import numpy as np
import pandas as pd
import yaml
from pandas.tseries.holiday import USFederalHolidayCalendar

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
    """Build a Prophet-compatible holiday DataFrame."""
    holiday_dates = USFederalHolidayCalendar().holidays(start=start, end=end)
    rows = [{"holiday": "US Federal Holiday", "ds": pd.Timestamp(date)}
            for date in holiday_dates]
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

    # Build regressor list from available columns. BART OD is monthly, so the
    # event signal is a month-level count/flag rather than an hourly window.
    regressors = []
    for col in [
        "precip_intensity",
        "precip_mm",
        "is_game_day",
        "is_sharks_game",
        "is_sharks_game_window",
        "is_holiday",
    ]:
        if col in train.columns:
            train[col] = train[col].astype(float).fillna(0)
            regressors.append(col)

    log.info(f"  Station {station_id}: {len(train):,} rows | regressors: {regressors}")

    holidays_df = make_holiday_df("2019-01-01", "2027-01-01")

    # Prophet's daily/weekly seasonalities are actively misleading on monthly
    # station-month data. Keep yearly seasonality only when enough history exists.
    monthly = train["ds"].dt.to_period("M").nunique() == len(train)
    yearly = cfg_prophet.get("yearly_seasonality", True)
    weekly = cfg_prophet.get("weekly_seasonality", True)
    daily = cfg_prophet.get("daily_seasonality", True)
    if monthly:
        weekly = False
        daily = False
        yearly = yearly and len(train) >= 18

    model = Prophet(
        yearly_seasonality  = yearly,
        weekly_seasonality  = weekly,
        daily_seasonality   = daily,
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
    train_cutoff: str | pd.Timestamp = None,
    horizon_steps: int = None,
    freq: str = "MS",
) -> pd.DataFrame:
    """
    Fit Prophet for every station and generate forecasts.
    Used by evaluation/benchmarks.py for head-to-head comparison.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    def _as_local_ts(value) -> pd.Timestamp:
        # feature_store timestamps are tz-naive — keep cutoffs naive so the
        # `df["timestamp"] <= cutoff` comparison below doesn't raise TypeError.
        ts = pd.Timestamp(value)
        return ts.tz_localize(None) if ts.tzinfo is not None else ts

    train_end    = _as_local_ts(cfg["data"]["train_end"])
    cutoff       = _as_local_ts(train_cutoff) if train_cutoff is not None else train_end

    # Use step-based horizon for monthly data; fall back to hour-based
    horizon_steps = horizon_steps or cfg["data"].get("forecast_horizon_steps") \
        or cfg["chronos2"].get("prediction_length_steps", None)
    if horizon_steps is None:
        raw_freq = cfg["data"]["resample_freq"]
        horizon_hrs  = cfg["data"]["forecast_horizon_hours"]
        steps_per_hour = pd.tseries.frequencies.to_offset(raw_freq).nanos / (3600 * 1e9)
        horizon_steps  = int(horizon_hrs * steps_per_hour)

    train_df = df[df["timestamp"] <= cutoff]
    future_df = df[df["timestamp"] > cutoff]

    stations = df["station_id"].unique()
    all_preds = []

    for station_id in stations:
        log.info(f"\nFitting Prophet for station: {station_id}")
        station_train = train_df[train_df["station_id"] == station_id]
        station_future = future_df[future_df["station_id"] == station_id]

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
        log.error("Feature store not found. Run: python machine_learning_files/merge_pipeline.py")
        return

    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    if args.station:
        df = df[df["station_id"] == args.station]

    if args.horizon:
        cfg["data"]["forecast_horizon_steps"] = args.horizon

    run_prophet_all_stations(df, cfg)


if __name__ == "__main__":
    main()
