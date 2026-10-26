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

The leaderboard's SARIMA reads no covariate. Covariates are optional
(`exog_cols` in run_arima_all_stations) and are used only by the covariate
experiment (models/baselines/covariate_experiment.py), which writes its own
table and never the leaderboard. With `exog_cols=None` the fit is exactly the
covariate-free SARIMA.

Usage:
    python models/baselines/arima.py
    python models/baselines/arima.py --station EM
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# Quieten statsmodels' routine chatter, but never convergence failures: the
# blanket filter that used to live here hid ConvergenceWarning for the stations
# whose fits had diverged, so a model that never converged looked exactly like
# one that had.
from statsmodels.tools.sm_exceptions import ConvergenceWarning

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("always", category=ConvergenceWarning)

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
        # Airline model. The BART target has ~30 monthly observations per
        # station; with d=1 and D=1 at s=12 that leaves ~17 effective points,
        # which cannot support the 4 parameters of (1,1,1)(1,1,0,12). Two MA
        # terms fit that budget, and measured 6.89% WAPE against 7.32% for the
        # larger order on the same split.
        "order":          (0, 1, 1),
        "seasonal_order": (0, 1, 1, 12),   # annual seasonal period for monthly BART data
    },
}


def get_sarima_orders(freq: str) -> dict:
    fl = freq.lower()
    if "ms" in fl or "month" in fl or fl == "m":
        return SARIMA_ORDERS["monthly"]
    if "15" in fl or "min" in fl:
        return SARIMA_ORDERS["15min"]
    return SARIMA_ORDERS["hourly"]


# ── Exog (covariates) ──────────────────────────────────────────────────────────

def _future_index(last_train_ts: pd.Timestamp, horizon_steps: int, freq: str) -> pd.DatetimeIndex:
    """The `horizon_steps` timestamps forecast after `last_train_ts`."""
    return pd.date_range(
        start=last_train_ts + pd.tseries.frequencies.to_offset(freq),
        periods=horizon_steps,
        freq=freq,
        tz=last_train_ts.tzinfo if hasattr(last_train_ts, "tzinfo") else None,
    )


def _require_finite_exog(exog: pd.DataFrame, what: str) -> pd.DataFrame:
    """Cast to float and raise ValueError if any value is NaN or non-finite."""
    exog = pd.DataFrame(exog).astype(float)
    bad = ~np.isfinite(exog.to_numpy())
    if bad.any():
        cols = [str(c) for c, b in zip(exog.columns, bad.any(axis=0)) if b]
        months = exog.index[bad.any(axis=1)]
        raise ValueError(
            f"{what}: {int(bad.sum())} NaN or non-finite value(s) in {cols}, "
            f"{len(months)} month(s) from {months[0]} to {months[-1]}"
        )
    return exog


def _same_timestamps(a: pd.DatetimeIndex, b: pd.DatetimeIndex) -> bool:
    # The store is datetime64[us] and date_range may give [ns]; compare values,
    # not resolution.
    return len(a) == len(b) and a.as_unit("ns").equals(b.as_unit("ns"))


def _standardised_train_exog(
    station_train: pd.DataFrame,
    exog_cols: list[str],
    freq: str,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """
    One station's training exog: monthly means on the same index as the
    ridership series, standardised with this station's training-window mean
    and SD (ddof=0). Returns (standardised exog, mean, sd).
    """
    raw = (
        station_train
        .sort_values("timestamp")
        .set_index("timestamp")[exog_cols]
        .astype(float)
        .resample(freq)
        .mean()
    )
    raw = _require_finite_exog(raw, "training exog")
    mean = raw.mean()
    sd = raw.std(ddof=0)
    for col in exog_cols:
        # nunique catches a constant column whose float SD is a round-off
        # 1e-17 instead of 0, which would otherwise blow up into noise.
        if not (np.isfinite(sd[col]) and sd[col] > 0) or raw[col].nunique() < 2:
            raise ValueError(
                f"training exog column {col!r} has zero or undefined SD over the "
                f"training window (SD {float(sd[col]):.3g}); cannot standardise it"
            )
    return (raw - mean) / sd, mean, sd


def _future_exog(
    station_rows: pd.DataFrame,
    exog_cols: list[str],
    last_train_ts: pd.Timestamp,
    horizon_steps: int,
    freq: str,
    mean: pd.Series,
    sd: pd.Series,
) -> pd.DataFrame:
    """
    One station's exog for exactly the `horizon_steps` months after
    `last_train_ts`, scaled with the training window's mean and SD. Raises if
    any of those months has no row or a NaN value.
    """
    future_ts = _future_index(last_train_ts, horizon_steps, freq)
    rows = station_rows.sort_values("timestamp").set_index("timestamp")[exog_cols].astype(float)
    have_row = rows.iloc[:, 0].resample(freq).size().reindex(future_ts, fill_value=0)
    if (have_row.to_numpy() == 0).any():
        missing = [str(ts.date()) for ts, n in have_row.items() if n == 0]
        raise ValueError(f"future exog: no row for month(s) {missing}")
    raw = _require_finite_exog(rows.resample(freq).mean().reindex(future_ts), "future exog")
    return (raw - mean) / sd


# ── Per-station model ──────────────────────────────────────────────────────────

def fit_station(
    station_df: pd.DataFrame,
    station_id: str,
    freq: str,
    use_auto: bool = False,
    exog: pd.DataFrame | None = None,
) -> tuple:
    """
    Fit a SARIMA model for a single station.
    Returns (model_fit, last_train_timestamp).

    exog: optional, already-standardised float covariates indexed by
    timestamp. Reindexed to the resampled ridership series; any NaN or
    non-finite value raises ValueError. None fits the covariate-free model.
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

    if exog is not None:
        exog = _require_finite_exog(pd.DataFrame(exog).reindex(series.index), "training exog")

    if use_auto:
        # auto_arima only selects orders — still fit the final model with
        # statsmodels' SARIMAX so the returned object supports get_forecast(),
        # same as the fixed-order path below.
        auto_model, method = fit_auto_arima(series, freq)
        if auto_model is not None:
            orders = {
                "order": auto_model.order,
                "seasonal_order": auto_model.seasonal_order,
            }
        log.info(f"  auto_arima order selection: {method}")

    exog_note = f" with exog {list(exog.columns)}" if exog is not None else ""
    log.info(
        f"  Fitting SARIMA{orders['order']}×{orders['seasonal_order']} "
        f"for {station_id} ({len(series):,} obs){exog_note} …"
    )

    model = SARIMAX(
        series,
        exog=exog,
        order=orders["order"],
        seasonal_order=orders["seasonal_order"],
        # Without these constraints, MLE on a short series wanders to explosive
        # AR roots: 27 of 50 stations fitted |ar.L1| > 1 (one reached -13.8),
        # and their forecasts oscillated with growing amplitude — 4e4, -3e5,
        # 5e6, ... -1e10 against a training mean of 13,309. predict_station's
        # clip at zero then published an alternating 0 / astronomical series,
        # which is how SARIMA scored 29,423% WAPE.
        enforce_stationarity=True,
        enforce_invertibility=True,
        # No constant. With d=1 and D=1 the constant enters a twice-differenced
        # series, implying quadratic drift in levels; it was worth 4.65 WAPE
        # points of error on its own.
        trend="n",
    )

    # Use a faster optimiser for large datasets
    fit = model.fit(
        disp=False,
        method="lbfgs",
        maxiter=100,
    )

    # The module-level warnings filter hides ConvergenceWarning, so a station
    # that never converged used to look identical to one that did.
    converged = fit.mle_retvals.get("converged") if hasattr(fit, "mle_retvals") else None
    if converged is False:
        log.warning(
            f"  {station_id}: optimiser did NOT converge within maxiter — "
            f"treat this station's forecast as unreliable"
        )

    log.info(f"  ✅ AIC={fit.aic:.1f} | BIC={fit.bic:.1f} | converged={converged}")
    return fit, series.index[-1]


def predict_station(
    fit,
    last_train_ts: pd.Timestamp,
    horizon_steps: int,
    freq: str,
    confidence: float = 0.80,   # 80% interval → P10/P90
    exog_future: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Generate out-of-sample forecast with prediction intervals.
    Uses the fitted SARIMA model's built-in get_forecast().

    exog_future: required when the model was fitted with exog. Exactly
    `horizon_steps` rows, no NaN, indexed by the forecast months (statsmodels
    does not check the index, so a frame for the wrong months would otherwise
    be used silently).
    """
    future_ts = _future_index(last_train_ts, horizon_steps, freq)

    if exog_future is not None:
        exog_future = pd.DataFrame(exog_future)
        if len(exog_future) != horizon_steps:
            raise ValueError(
                f"future exog has {len(exog_future)} rows; expected exactly "
                f"{horizon_steps}"
            )
        if not (isinstance(exog_future.index, pd.DatetimeIndex)
                and _same_timestamps(exog_future.index, future_ts)):
            raise ValueError(
                f"future exog is indexed by {list(exog_future.index)}; expected "
                f"the forecast months {list(future_ts)}"
            )
        exog_future = _require_finite_exog(exog_future, "future exog")

    forecast_obj = fit.get_forecast(steps=horizon_steps, exog=exog_future)
    mean    = forecast_obj.predicted_mean.values
    ci      = forecast_obj.conf_int(alpha=1 - confidence)

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
            s = 96
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
    exog_cols: list[str] | None = None,
    model_label: str = "SARIMA",
) -> pd.DataFrame:
    """
    Fit SARIMA for every station and generate forecasts.
    Used by models/baselines/benchmarks.py for head-to-head comparison.

    exog_cols: optional covariate columns of `df` (SARIMAX). Per station, the
    training exog is the monthly mean over the training rows and the future
    exog is that station's rows for exactly the `horizon_steps` months after
    its last training month; both are standardised with the station's
    training-window mean and SD (ddof=0). A NaN, a missing future month or a
    zero-SD column fails that station (logged and skipped, like any other
    failed fit). None, the default, is the covariate-free SARIMA.
    model_label: written to the "model" column.
    """
    if exog_cols is not None:
        exog_cols = list(exog_cols)
        if not exog_cols:
            raise ValueError("exog_cols is empty; pass None for the covariate-free model")
        absent = [c for c in exog_cols if c not in df.columns]
        if absent:
            raise KeyError(f"exog column(s) not in the data: {absent}")

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
        horizon_hrs = cfg["data"]["forecast_horizon_hours"]
        steps_per_hour = pd.tseries.frequencies.to_offset(raw_freq).nanos / (3600 * 1e9)
        horizon_steps = int(horizon_hrs * steps_per_hour)

    train_df = df[df["timestamp"] <= cutoff]
    # Honour the configured training start, as the benchmark harness does when
    # it builds its own train_df. Differencing makes SARIMA far less sensitive
    # to the 2019 -> 2022 level break than Prophet, but training on a window
    # the config excludes is wrong regardless.
    train_start = cfg["data"].get("train_start")
    if train_start:
        train_df = train_df[train_df["timestamp"] >= _as_local_ts(train_start)]

    stations = df["station_id"].unique()
    all_preds = []

    for station_id in stations:
        log.info(f"\nFitting {model_label} for station: {station_id}")
        station_train = train_df[train_df["station_id"] == station_id]

        orders = get_sarima_orders(freq)
        min_obs = orders["seasonal_order"][3] * 2
        if len(station_train) < min_obs:
            log.warning(f"  Skipping {station_id} — need ≥{min_obs} obs")
            continue

        try:
            train_exog = future_exog = None
            if exog_cols is not None:
                train_exog, exog_mean, exog_sd = _standardised_train_exog(
                    station_train, exog_cols, freq
                )
            fit, last_ts = fit_station(
                station_train, station_id, freq, use_auto=use_auto, exog=train_exog
            )
            if exog_cols is not None:
                future_exog = _future_exog(
                    df[df["station_id"] == station_id], exog_cols, last_ts,
                    horizon_steps, freq, exog_mean, exog_sd,
                )
            preds = predict_station(fit, last_ts, horizon_steps, freq, exog_future=future_exog)
            preds["station_id"] = station_id
            preds["model"]      = model_label
            all_preds.append(preds)
        except Exception as e:
            log.error(f"  ❌ {model_label} failed for {station_id}: {e}")

    if not all_preds:
        return pd.DataFrame()

    combined = pd.concat(all_preds, ignore_index=True)
    out = output_dir / "arima_forecasts.parquet"
    combined.to_parquet(out, index=False)
    log.info(f"\n{model_label} forecasts saved → {out}")
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
