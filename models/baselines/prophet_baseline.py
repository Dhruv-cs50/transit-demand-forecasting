"""
models/baselines/prophet_baseline.py
────────────────────────────────────
Prophet baseline for Bay Area transit ridership forecasting.

Trend, yearly seasonality and US federal holidays, fitted per station on the
month-start ridership target. Deliberately no external regressors — see
fit_station() for the measurements behind that.

This gives us a strong classical baseline to hold the neural models against:
if Chronos-2 cannot beat it, the extra complexity is not earning its place.

Usage:
    python models/baselines/prophet_baseline.py
    python models/baselines/prophet_baseline.py --station EMBR --horizon 24
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

    No external regressors: on the month-start BART target they cost 23 WAPE
    points (15.9% -> 39.1% on the test window), measured against the rebuilt
    feature store. Twelve training points per station cannot identify six
    regressor coefficients alongside a trend and yearly seasonality, and three
    of the six (is_game_day, is_sharks_game, is_sharks_game_window) are
    constant zero whenever events data is unavailable. Holidays are still
    passed through Prophet's own `holidays` argument.

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

    log.info(f"  Station {station_id}: {len(train):,} rows")

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
        # yearly_seasonality=True means Prophet's default fourier_order=10,
        # i.e. 20 seasonal regressors. With the holiday columns and changepoint
        # deltas that is ~47 free parameters against ~30 monthly points per
        # station: the model interpolates its training data, the MAP sigma_obs
        # collapses to the in-sample residual sd (0.29% of level), and the
        # p10-p90 band comes out roughly 22x too narrow — 7.9% coverage against
        # a nominal 80%. An explicit order sized to the data fixes both the
        # calibration and the point forecast (13.48% -> 6.45% WAPE).
        if yearly is True:
            yearly = int(cfg_prophet.get("yearly_fourier_order", 4))

    model = Prophet(
        yearly_seasonality  = yearly,
        weekly_seasonality  = weekly,
        daily_seasonality   = daily,
        changepoint_prior_scale = cfg_prophet.get("changepoint_prior_scale", 0.05),
        holidays            = holidays_df,
        uncertainty_samples = 200,
    )

    # Prophet draws `uncertainty_samples` paths to build yhat_lower/upper, so the
    # interval — and therefore coverage — is stochastic. Unseeded, coverage moved
    # between 44.0% and 46.0% across otherwise identical runs while WAPE stayed
    # fixed, which makes a published coverage figure unverifiable.
    seed = cfg_prophet.get("seed", cfg.get("chronos2", {}).get("seed"))
    if seed is not None:
        np.random.seed(int(seed))

    model.fit(train[["ds", "y"]])
    return model, train


def predict_station(
    model,
    horizon_steps: int,
    last_ds: pd.Timestamp,
    freq: str,
) -> pd.DataFrame:
    """
    Run Prophet prediction for `horizon_steps` steps beyond `last_ds`.
    """
    future_dates = pd.date_range(
        start=last_ds + pd.tseries.frequencies.to_offset(freq),
        periods=horizon_steps,
        freq=freq,
    )
    forecast = model.predict(pd.DataFrame({"ds": future_dates}))

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
        # Compare in the same tz space as df["timestamp"] — the feature store
        # is tz-naive by default, so forcing tz-aware here raises
        # "Invalid comparison between dtype=datetime64[ns] and Timestamp".
        ts = pd.Timestamp(value)
        if df["timestamp"].dt.tz is not None:
            return ts.tz_localize("America/Los_Angeles") if ts.tzinfo is None else ts.tz_convert("America/Los_Angeles")
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
    # Honour the configured training start. Without it Prophet trains from the
    # first row in the feature store, which for BART spans the 2019 -> 2022
    # discontinuity (~837k -> ~296k monthly riders per station, with 2020-21
    # absent). A smooth trend fitted across that break anchors the forecast far
    # above the post-2020 level. SARIMA survives the same data because
    # differencing re-anchors it to the recent level; Prophet does not.
    train_start = cfg["data"].get("train_start")
    if train_start:
        train_df = train_df[train_df["timestamp"] >= _as_local_ts(train_start)]


    stations = df["station_id"].unique()
    all_preds = []

    for station_id in stations:
        log.info(f"\nFitting Prophet for station: {station_id}")
        station_train = train_df[train_df["station_id"] == station_id]

        if len(station_train) < 3:   # need at least 3 data points
            log.warning(f"  Skipping {station_id} — not enough training data")
            continue

        try:
            model, _ = fit_station(station_train, station_id, cfg)
            last_ds = pd.to_datetime(station_train["timestamp"].max()).tz_localize(None)
            preds = predict_station(model, horizon_steps, last_ds, freq)
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
        cfg["data"]["forecast_horizon_steps"] = args.horizon

    run_prophet_all_stations(df, cfg)


if __name__ == "__main__":
    main()
