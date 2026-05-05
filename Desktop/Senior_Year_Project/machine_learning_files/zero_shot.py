"""
models/chronos2/zero_shot.py
─────────────────────────────
Zero-shot Chronos-2 inference — no fine-tuning required.
Uses your historical ridership data as context, with weather and events
as past/future covariates, and forecasts the next N hours per station.

This is your baseline. Run it first to establish a performance floor
before investing in fine-tuning.

Usage:
    python models/chronos2/zero_shot.py
    python models/chronos2/zero_shot.py --station EMBR --horizon 24
"""

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("chronos2_zero_shot")

PROCESSED_DIR = Path("data/processed")
MODEL_CONFIG_PATH = Path("configs/model.yaml")


def load_model_config() -> dict:
    with open(MODEL_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_feature_store(station_id: str = None) -> pd.DataFrame:
    path = PROCESSED_DIR / "feature_store.parquet"
    if not path.exists():
        raise FileNotFoundError(
            "Feature store not found. Run: python processing/merge_pipeline.py"
        )
    df = pd.read_parquet(path)
    if station_id:
        df = df[df["station_id"] == station_id]
        if df.empty:
            raise ValueError(f"No data for station: {station_id}")
    return df


def build_chronos_pipeline(cfg: dict):
    """
    Load Chronos-2 from HuggingFace. Requires:
        pip install chronos-forecasting
    """
    try:
        from chronos import Chronos2Pipeline
    except ImportError:
        raise ImportError(
            "Install Chronos: pip install chronos-forecasting"
        )

    device = cfg["chronos2"]["device"]
    model_id = cfg["chronos2"]["model_id"]
    log.info(f"Loading {model_id} on {device} …")

    pipeline = Chronos2Pipeline.from_pretrained(
        model_id,
        device_map=device,
    )
    return pipeline


def prepare_context(
    df: pd.DataFrame,
    station_id: str,
    context_hours: int,
    as_of: pd.Timestamp = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split station data into:
      - context_df: the past `context_hours` of history fed to the model
      - future_df: the next `horizon_hours` with known future covariates
                   (weather forecast, event schedule)

    Returns (context_df, future_df).
    """
    station_df = df[df["station_id"] == station_id].sort_values("timestamp").copy()

    if as_of is None:
        as_of = station_df["timestamp"].max()

    context_start = as_of - pd.Timedelta(hours=context_hours)
    context_df = station_df[
        (station_df["timestamp"] >= context_start) &
        (station_df["timestamp"] <= as_of)
    ]

    # Future rows: rows after as_of (these exist if you've pre-loaded forecast data)
    future_df = station_df[station_df["timestamp"] > as_of]

    return context_df, future_df


def run_zero_shot_forecast(
    pipeline,
    context_df: pd.DataFrame,
    future_df: pd.DataFrame,
    station_id: str,
    prediction_length: int,
    quantile_levels: list[float],
) -> pd.DataFrame:
    """
    Run Chronos-2 zero-shot forecast for a single station.

    context_df  — historical ridership + past covariates
    future_df   — future-known covariates (weather forecast, events)
    """
    # Covariate columns available in the feature store
    past_covariate_cols = [
        "temp_f", "precip_mm", "is_raining", "windspeed_mph",
        "is_game_day", "is_sharks_game", "hours_to_event",
        "hour_of_day", "day_of_week", "is_weekend", "is_holiday",
        "is_am_peak", "is_pm_peak",
    ]

    # Only use covariates that exist in both context and future
    available_past = [c for c in past_covariate_cols if c in context_df.columns]
    available_future = [c for c in past_covariate_cols if c in future_df.columns]

    # Build the context input DataFrame for Chronos
    # Format: index=timestamp, column=target, optional covariate columns
    context_input = context_df.set_index("timestamp")[["ridership"] + available_past].copy()
    context_input = context_input.rename(columns={"ridership": "target"})

    # Optionally include future_df for future-known covariates
    future_input = None
    if not future_df.empty and available_future:
        future_input = future_df.set_index("timestamp")[available_future].copy()

    log.info(
        f"Station {station_id}: context={len(context_input)} timesteps, "
        f"covariates={available_past}, horizon={prediction_length}"
    )

    # Chronos-2 predict_df interface
    # Convert to the expected long format
    context_long = context_df[["timestamp", "station_id", "ridership"]].copy()
    context_long = context_long.rename(columns={"ridership": "target"})

    # Add past covariates as additional columns
    for col in available_past:
        if col in context_df.columns:
            context_long[col] = context_df[col].values

    future_long = None
    if future_input is not None:
        future_long = future_df[["timestamp", "station_id"] + available_future].copy()

    try:
        pred_df = pipeline.predict_df(
            context_long,
            future_df=future_long,
            prediction_length=prediction_length,
            quantile_levels=quantile_levels,
            id_column="station_id",
            timestamp_column="timestamp",
            target="target",
        )
    except TypeError:
        # Fallback: some versions don't support all kwargs — strip covariates
        log.warning("Falling back to univariate mode (no explicit covariates)")
        pred_df = pipeline.predict_df(
            context_long[["timestamp", "station_id", "target"]],
            prediction_length=prediction_length,
            quantile_levels=quantile_levels,
            id_column="station_id",
            timestamp_column="timestamp",
            target="target",
        )

    return pred_df


def evaluate_predictions(
    pred_df: pd.DataFrame,
    actuals_df: pd.DataFrame,
    quantile_levels: list[float],
) -> dict:
    """
    Compute MAE, RMSE, MAPE on the P50 (median) forecast.
    Also compute WAPE (Weighted Absolute Percentage Error).
    """
    if actuals_df.empty or pred_df.empty:
        return {}

    # Merge predictions with actuals on timestamp
    median_col = f"mean"  # Chronos calls it mean, or use the 0.5 quantile col
    if median_col not in pred_df.columns:
        q50_col = [c for c in pred_df.columns if "0.5" in str(c)]
        median_col = q50_col[0] if q50_col else pred_df.columns[-1]

    merged = pred_df.merge(
        actuals_df[["timestamp", "ridership"]].rename(columns={"ridership": "actual"}),
        on="timestamp",
        how="inner",
    )
    if merged.empty:
        log.warning("No overlapping timestamps between predictions and actuals")
        return {}

    y_pred = merged[median_col].values.astype(float)
    y_true = merged["actual"].values.astype(float)

    mae  = np.mean(np.abs(y_pred - y_true))
    rmse = np.sqrt(np.mean((y_pred - y_true) ** 2))
    # MAPE — guard against zero actuals
    nonzero = y_true != 0
    mape = np.mean(np.abs((y_pred[nonzero] - y_true[nonzero]) / y_true[nonzero])) * 100
    wape = np.sum(np.abs(y_pred - y_true)) / np.sum(np.abs(y_true)) * 100

    return {"MAE": mae, "RMSE": rmse, "MAPE_%": mape, "WAPE_%": wape, "n": len(merged)}


def forecast_all_stations(
    df: pd.DataFrame,
    pipeline,
    cfg: dict,
    output_dir: Path,
    as_of: pd.Timestamp = None,
) -> pd.DataFrame:
    """Run zero-shot forecasts for every station in the feature store."""
    output_dir.mkdir(parents=True, exist_ok=True)
    context_hours = cfg["data"]["context_length_hours"]
    horizon = cfg["data"]["forecast_horizon_hours"]
    freq = cfg["data"]["resample_freq"]
    # Convert hours → number of steps at target freq
    steps_per_hour = pd.tseries.frequencies.to_offset(freq).nanos / (3600 * 1e9)
    prediction_length = int(horizon * steps_per_hour)
    quantile_levels = cfg["chronos2"]["quantile_levels"]

    stations = df["station_id"].unique()
    all_preds = []
    metrics_rows = []

    for station_id in stations:
        log.info(f"\n{'─'*50}")
        log.info(f"Forecasting station: {station_id}")
        context_df, future_df = prepare_context(df, station_id, context_hours, as_of)

        if len(context_df) < 24:
            log.warning(f"  Insufficient context for {station_id} ({len(context_df)} rows) — skipping")
            continue

        try:
            pred_df = run_zero_shot_forecast(
                pipeline, context_df, future_df,
                station_id, prediction_length, quantile_levels,
            )
            pred_df["station_id"] = station_id
            all_preds.append(pred_df)

            # Evaluate if we have actuals for the forecast window
            if as_of is not None:
                actuals = df[
                    (df["station_id"] == station_id) &
                    (df["timestamp"] > as_of)
                ]
                m = evaluate_predictions(pred_df, actuals, quantile_levels)
                if m:
                    m["station_id"] = station_id
                    metrics_rows.append(m)
                    log.info(f"  MAE={m['MAE']:.1f}  RMSE={m['RMSE']:.1f}  WAPE={m['WAPE_%']:.1f}%")

        except Exception as e:
            log.error(f"  Forecast failed for {station_id}: {e}")

    if not all_preds:
        log.error("No forecasts generated")
        return pd.DataFrame()

    combined = pd.concat(all_preds, ignore_index=True)

    # Save predictions
    ts_str = (as_of or pd.Timestamp.now()).strftime("%Y%m%d_%H%M")
    out = output_dir / f"zero_shot_forecasts_{ts_str}.parquet"
    combined.to_parquet(out, index=False)
    log.info(f"\nForecasts saved → {out}")

    # Save metrics
    if metrics_rows:
        metrics_df = pd.DataFrame(metrics_rows)
        log.info(f"\n{'─'*50}")
        log.info("Zero-shot performance summary:")
        log.info(f"\n{metrics_df.to_string(index=False)}")
        metrics_df.to_parquet(output_dir / f"zero_shot_metrics_{ts_str}.parquet", index=False)

    return combined


def parse_args():
    parser = argparse.ArgumentParser(description="Run Chronos-2 zero-shot forecast")
    parser.add_argument("--station", default=None, help="Single station ID. Default: all stations.")
    parser.add_argument("--horizon", type=int, default=None, help="Override forecast horizon (hours)")
    parser.add_argument("--as-of", default=None, help="Forecast as of this date (YYYY-MM-DD). Default: latest.")
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = load_model_config()

    if args.horizon:
        cfg["data"]["forecast_horizon_hours"] = args.horizon

    df = load_feature_store(station_id=args.station)
    pipeline = build_chronos_pipeline(cfg)

    as_of = pd.Timestamp(args.as_of, tz="America/Los_Angeles") if args.as_of else None
    output_dir = Path("models/chronos2/outputs")

    if args.station:
        context_df, future_df = prepare_context(
            df, args.station, cfg["data"]["context_length_hours"], as_of
        )
        pred_df = run_zero_shot_forecast(
            pipeline, context_df, future_df,
            args.station,
            int(cfg["data"]["forecast_horizon_hours"]),
            cfg["chronos2"]["quantile_levels"],
        )
        print(pred_df.to_string())
    else:
        forecast_all_stations(df, pipeline, cfg, output_dir, as_of)


if __name__ == "__main__":
    main()
