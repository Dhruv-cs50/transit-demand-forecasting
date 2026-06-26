"""
models/baselines/arima.py
──────────────────────────
SARIMA baseline for Bay Area transit ridership forecasting.

SARIMA (Seasonal AutoRegressive Integrated Moving Average) is the
classical gold standard for time series. It explicitly models:
  - AR terms: autocorrelation (ridership now predicts ridership soon)
  - I terms:  differencing to remove trends
  - MA terms: moving average of past errors
  - S terms:  seasonal patterns (daily + weekly cycles)

No covariate support — that's intentional. If Chronos-2 (which does
use weather + events) can't beat a model with zero covariate knowledge,
something is wrong.

Usage:
    python models/baselines/arima.py
    python models/baselines/arima.py --station EMBR
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("arima_baseline")

PROCESSED_DIR = Path("data/processed")
OUTPUT_DIR    = Path("models/baselines/outputs/arima")
CONFIG_PATH   = Path("configs/model.yaml")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── SARIMA orders ──────────────────────────────────────────────────────────────

# Fixed orders tuned for Bay Area transit at hourly frequency.
# (p,d,q) × (P,D,Q,s) where s=24 for daily seasonality.
# For 15-min data, set s=96 (96 × 15min = 24hr).

SARIMA_ORDERS = {
    "hourly": {
        "order":          (2, 1, 2),
        "seasonal_order": (1, 1, 1, 24),   # daily seasonal period
    },
    "15min": {
        "order":          (2, 1, 2),
        "seasonal_order": (1, 1, 1, 96),   # 96 steps = 24hrs at 15min
    },
    "monthly": {
        "order":          (1, 1, 1),
        "seasonal_order": (1, 1, 0, 12),   # annual seasonal period for monthly BART data
    },
}


def get_sarima_orders(freq: str) -> dict:
    fl = freq.lower()
    if "ms" in fl or "month" in fl or fl == "m":
        return SARIMA_ORDERS["monthly"]
    if "15" in fl or "min" in fl:
        return SARIMA_ORDERS["15min"]
    return SARIMA_ORDERS["hourly"]


# ── Per-station model ──────────────────────────────────────────────────────────

def fit_station(
    station_df: pd.DataFrame,
    station_id: str,
    freq: str,
) -> tuple:
    """
    Fit a SARIMA model for a single station.
    Returns (model_fit, last_train_timestamp).
    """
    try:
        from statsmodels.tsa.statespace.sarimax import SARIMAX
    except ImportError:
        raise ImportError("Install statsmodels: pip install statsmodels")

    orders = get_sarima_orders(freq)

    series = (
        station_df
        .sort_values("timestamp")
        .set_index("timestamp")["ridership"]
        .resample(freq)
        .mean()
        .interpolate(method="time")
        .clip(lower=0)
    )

    if len(series) < orders["seasonal_order"][3] * 2:
        raise ValueError(
            f"Not enough data for SARIMA seasonal period "
            f"({len(series)} < {orders['seasonal_order'][3] * 2})"
        )

    log.info(
        f"  Fitting SARIMA{orders['order']}×{orders['seasonal_order']} "
        f"for {station_id} ({len(series):,} obs) …"
    )

    model = SARIMAX(
        series,
        order=orders["order"],
        seasonal_order=orders["seasonal_order"],
        enforce_stationarity=False,
        enforce_invertibility=False,
        trend="c",
    )

    # Use a faster optimiser for large datasets
    fit = model.fit(
        disp=False,
        method="lbfgs",
        maxiter=100,
    )

    log.info(f"  ✅ AIC={fit.aic:.1f} | BIC={fit.bic:.1f}")
    return fit, series.index[-1]


def predict_station(
    fit,
    last_train_ts: pd.Timestamp,
    horizon_steps: int,
    freq: str,
    confidence: float = 0.80,   # 80% interval → P10/P90
) -> pd.DataFrame:
    """
    Generate out-of-sample forecast with prediction intervals.
    Uses the fitted SARIMA model's built-in get_forecast().
    """
    forecast_obj = fit.get_forecast(steps=horizon_steps)
    mean    = forecast_obj.predicted_mean.values
    ci      = forecast_obj.conf_int(alpha=1 - confidence)

    future_ts = pd.date_range(
        start=last_train_ts + pd.tseries.frequencies.to_offset(freq),
        periods=horizon_steps,
        freq=freq,
        tz=last_train_ts.tzinfo if hasattr(last_train_ts, "tzinfo") else None,
    )

    result = pd.DataFrame({
        "timestamp": future_ts,
        "p10":       np.maximum(ci.iloc[:, 0].values, 0),   # lower CI
        "p50":       np.maximum(mean, 0),
        "p90":       np.maximum(ci.iloc[:, 1].values, 0),   # upper CI
    })
    return result


# ── Auto ARIMA helper ──────────────────────────────────────────────────────────

def fit_auto_arima(
    series: pd.Series,
    freq: str,
    max_p: int = 3,
    max_q: int = 3,
) -> tuple:
    """
    Use pmdarima's auto_arima to automatically select the best SARIMA
    order via AIC. Slower but more accurate than fixed orders.
    Falls back to fixed orders if pmdarima not installed.
    """
    try:
        import pmdarima as pm
        fl = freq.lower()
        if "ms" in fl or "month" in fl or fl == "m":
            s = 12
        elif "h" in fl:
            s = 24
        else:
            s = 96  # 15-min data: 96 steps per day
        model = pm.auto_arima(
            series,
            seasonal=True, m=s,
            start_p=1, max_p=max_p,
            start_q=0, max_q=max_q,
            d=1, D=1,
            information_criterion="aic",
            stepwise=True,
            error_action="ignore",
            suppress_warnings=True,
            n_jobs=-1,
        )
        return model, "auto"
    except ImportError:
        log.warning("pmdarima not installed — using fixed SARIMA orders")
        return None, "fixed"


# ── Full pipeline ──────────────────────────────────────────────────────────────

def run_arima_all_stations(
    df: pd.DataFrame,
    cfg: dict,
    output_dir: Path = OUTPUT_DIR,
    use_auto: bool = False,
    train_cutoff: str | pd.Timestamp = None,
    horizon_steps: int = None,
    freq: str = "MS",
) -> pd.DataFrame:
    """
    Fit SARIMA for every station and generate forecasts.
    Used by evaluation/benchmarks.py for head-to-head comparison.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    def _as_local_ts(value) -> pd.Timestamp:
        ts = pd.Timestamp(value)
        return ts.tz_localize("America/Los_Angeles") if ts.tzinfo is None else ts.tz_convert("America/Los_Angeles")

    train_end    = _as_local_ts(cfg["data"]["train_end"])
    cutoff       = _as_local_ts(train_cutoff) if train_cutoff is not None else train_end

    # Use step-based horizon for monthly data; fall back to hour-based
    horizon_steps = horizon_steps or cfg["data"].get("forecast_horizon_steps") \
        or cfg["chronos2"].get("prediction_length_steps", None)
    if horizon_steps is None:
        raw_freq = cfg["data"]["resample_freq"]
        horizon_hrs = cfg["data"]["forecast_horizon_hours"]
        steps_per_hour = pd.tseries.frequencies.to_offset(raw_freq).nanos / (3600 * 1e9)
        horizon_steps = int(horizon_hrs * steps_per_hour)

    train_df = df[df["timestamp"] <= cutoff]
    stations = df["station_id"].unique()
    all_preds = []

    for station_id in stations:
        log.info(f"\nFitting SARIMA for station: {station_id}")
        station_train = train_df[train_df["station_id"] == station_id]

        orders = get_sarima_orders(freq)
        min_obs = orders["seasonal_order"][3] * 2
        if len(station_train) < min_obs:
            log.warning(f"  Skipping {station_id} — need ≥{min_obs} obs")
            continue

        try:
            fit, last_ts = fit_station(station_train, station_id, freq)
            preds = predict_station(fit, last_ts, horizon_steps, freq)
            preds["station_id"] = station_id
            preds["model"]      = "SARIMA"
            all_preds.append(preds)
        except Exception as e:
            log.error(f"  ❌ ARIMA failed for {station_id}: {e}")

    if not all_preds:
        return pd.DataFrame()

    combined = pd.concat(all_preds, ignore_index=True)
    out = output_dir / "arima_forecasts.parquet"
    combined.to_parquet(out, index=False)
    log.info(f"\nSARIMA forecasts saved → {out}")
    return combined


# ── Standalone ─────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run SARIMA baseline")
    parser.add_argument("--station",   default=None)
    parser.add_argument("--auto",      action="store_true", help="Use auto_arima order selection")
    parser.add_argument("--horizon",   type=int, default=None)
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

    if args.station:
        df = df[df["station_id"] == args.station]

    if args.horizon:
        cfg["data"]["forecast_horizon_steps"] = args.horizon

    run_arima_all_stations(df, cfg, use_auto=args.auto)


if __name__ == "__main__":
    main()
