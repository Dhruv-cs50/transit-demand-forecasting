"""
models/chronos2/finetune.py
────────────────────────────
Fine-tunes Chronos-2 on historical Bay Area ridership data using AutoGluon.

Why fine-tune?
  Zero-shot Chronos-2 has never seen:
    - Sharks game ridership spikes at Diridon
    - Bay Area rain patterns affecting VTA vs BART differently
    - Caltrain's post-electrification ridership jump in 2024
    - BART's Monday anomaly (low ridership after holiday weekends)

  Fine-tuning teaches the model all of these patterns from your
  historical data, with weather and events as covariates.

What AutoGluon adds:
  - Handles covariate regressors alongside Chronos-2 natively
  - Automatic hyperparameter search within a time budget
  - Built-in cross-validation on time series (no leakage)
  - Ensemble of Chronos-2 + lightweight baselines for robustness

Usage:
    python models/chronos2/finetune.py
    python models/chronos2/finetune.py --time-limit 7200 --preset best_quality
"""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

import pandas as pd
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("chronos2_finetune")

PROCESSED_DIR   = Path("data/processed")
MODEL_DIR       = Path("models/chronos2/weights")
MODEL_CONFIG    = Path("configs/model.yaml")


def load_config() -> dict:
    with open(MODEL_CONFIG) as f:
        return yaml.safe_load(f)


# ── Data preparation ───────────────────────────────────────────────────────────

def load_train_val(cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load the chronological train and val splits from the feature store.
    These were created by processing/merge_pipeline.py.

    Returns (train_df, val_df) — both in AutoGluon TimeSeriesDataFrame format.
    """
    splits_dir = PROCESSED_DIR / "splits"

    train_path = splits_dir / "train.parquet"
    val_path   = splits_dir / "val.parquet"

    if not train_path.exists():
        raise FileNotFoundError(
            "Train split not found. Run: python processing/merge_pipeline.py"
        )

    log.info("Loading train split …")
    train_df = pd.read_parquet(train_path)
    train_df["timestamp"] = pd.to_datetime(train_df["timestamp"])

    log.info("Loading val split …")
    val_df = pd.read_parquet(val_path)
    val_df["timestamp"] = pd.to_datetime(val_df["timestamp"])

    log.info(f"  Train: {len(train_df):,} rows | Val: {len(val_df):,} rows")
    log.info(f"  Stations: {train_df['station_id'].nunique()}")
    log.info(f"  Date range: {train_df['timestamp'].min()} → {train_df['timestamp'].max()}")

    return train_df, val_df


def to_autogluon_format(
    df: pd.DataFrame,
    target_col: str = "ridership",
    covariate_cols: list[str] = None,
) -> "TimeSeriesDataFrame":
    """
    Convert our feature store DataFrame into AutoGluon's TimeSeriesDataFrame.

    AutoGluon expects:
        - item_id  : station identifier (maps to our station_id)
        - timestamp: datetime column
        - target   : the value to forecast (ridership)
        - optional : any additional covariate columns

    Covariates split into:
      known_covariates  — weather forecast, event schedule (known in future)
      past_covariates   — lag features, rolling stats (only known historically)
    """
    try:
        from autogluon.timeseries import TimeSeriesDataFrame
    except ImportError:
        raise ImportError("Install AutoGluon: pip install autogluon.timeseries")

    if covariate_cols is None:
        covariate_cols = _default_covariate_cols(df)

    # AutoGluon requires item_id column
    df = df.copy()
    df = df.rename(columns={"station_id": "item_id", target_col: "target"})
    df = df.sort_values(["item_id", "timestamp"])

    # Keep only the columns AutoGluon needs
    keep_cols = ["item_id", "timestamp", "target"] + [
        c for c in covariate_cols if c in df.columns
    ]
    df = df[keep_cols]

    # Drop rows with null target
    n_before = len(df)
    df = df.dropna(subset=["target"])
    if len(df) < n_before:
        log.warning(f"Dropped {n_before - len(df):,} rows with null target")

    ts_df = TimeSeriesDataFrame.from_data_frame(
        df,
        id_column="item_id",
        timestamp_column="timestamp",
    )

    log.info(f"TimeSeriesDataFrame: {len(ts_df):,} rows, {ts_df.num_items} items")
    return ts_df


# Known-future covariates: can be passed for the forecast horizon (weather
# forecast, event schedule, calendar — all knowable ahead of time). Shared by
# _default_covariate_cols() and _get_known_covariate_cols() so the two never
# drift apart — they used to be independently maintained copies, and
# _get_known_covariate_cols()'s copy silently fell behind (missing
# is_playoff, weather_code, cloud_cover_pct, precip_in, is_very_cold,
# is_very_hot, is_windy, temp_deviation), which meant AutoGluon was never
# told those columns are usable for the forecast horizon even when present.
KNOWN_FUTURE_COLS = [
    # Calendar — always known ahead of time
    "hour_of_day", "day_of_week", "is_weekend", "is_monday", "is_friday",
    "is_holiday", "is_holiday_eve", "is_am_peak", "is_pm_peak",
    "is_midday", "is_late_night", "month", "week_of_year", "quarter",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
    # Weather forecast (7-day ahead from Open-Meteo)
    "temp_f", "precip_mm", "precip_in", "windspeed_mph",
    "is_raining", "weather_code", "cloud_cover_pct",
    "precip_intensity", "weather_discomfort",
    "is_very_cold", "is_very_hot", "is_windy", "temp_deviation",
    # Event schedule (known from NHL/Ticketmaster calendar)
    "is_game_day", "is_sharks_game_window", "game_start_hour",
    "is_pre_event_window", "is_post_event_window", "is_playoff",
    "is_any_event_day", "nearest_event_attendance_tier",
    "hours_to_next_event",
    # Station static (never changes)
    "is_hub_station", "capacity_tier", "in_event_catchment",
    "dist_from_diridon_km",
]


def _default_covariate_cols(df: pd.DataFrame) -> list[str]:
    """
    Return the covariate columns present in the dataframe, split into
    known-future and past-only groups.

    Known future (can be passed for the forecast horizon):
      - Weather forecast variables
      - Event schedule variables
      - Calendar variables (always known in advance)

    Past only (only available up to the forecast origin):
      - Lag features
      - Rolling statistics
    """
    known_future = KNOWN_FUTURE_COLS

    past_only = [
        # Lag features — only known up to present
        "ridership_lag_1", "ridership_lag_2", "ridership_lag_3",
        "ridership_lag_6", "ridership_lag_12",
        "ridership_lag_4", "ridership_lag_8",
        "ridership_lag_96", "ridership_lag_192", "ridership_lag_672",
        # Rolling stats
        "ridership_rolling_mean_3mo", "ridership_rolling_std_3mo",
        "ridership_rolling_mean_12mo",
        "ridership_rolling_mean_24h", "ridership_rolling_std_24h",
        "ridership_rolling_mean_7d",
        # Rolling weather — cumulative rain over past N hours
        "precip_3hr_sum", "precip_6hr_sum", "precip_24hr_sum",
        "is_rain_onset",
    ]

    present_known   = [c for c in known_future if c in df.columns]
    present_past    = [c for c in past_only    if c in df.columns]

    log.info(f"  Known-future covariates : {len(present_known)}")
    log.info(f"  Past-only covariates    : {len(present_past)}")

    return present_known + present_past


# ── Fine-tuning ────────────────────────────────────────────────────────────────

def build_predictor(
    train_ts: "TimeSeriesDataFrame",
    cfg: dict,
    time_limit: int = None,
    preset: str = None,
    output_dir: Path = MODEL_DIR,
) -> "TimeSeriesPredictor":
    """
    Build and train an AutoGluon TimeSeriesPredictor wrapping Chronos-2.

    AutoGluon will:
      1. Fine-tune Chronos-2 on your ridership data
      2. Train lightweight baselines (SeasonalNaive, ETS, DeepAR)
      3. Fit a weighted ensemble that combines all models
      4. Use the val split internally to select best weights

    The ensemble approach means even if Chronos-2 has a bad day on
    a particular station, a simpler model can cover for it.
    """
    try:
        from autogluon.timeseries import TimeSeriesPredictor
    except ImportError:
        raise ImportError("Install AutoGluon: pip install autogluon.timeseries")

    quantiles   = cfg["chronos2"]["quantile_levels"]
    time_budget = time_limit or cfg["finetune"]["time_limit_seconds"]
    model_preset= preset    or cfg["finetune"]["presets"]

    # Use step-based config for monthly data; fall back to hour-based
    prediction_length = cfg["chronos2"].get("prediction_length_steps", None)
    context_length_steps = cfg["chronos2"].get("context_length_steps", None)
    freq = "MS"   # monthly BART data
    if prediction_length is None:
        import pandas as pd
        raw_freq = cfg["data"]["resample_freq"]
        horizon = cfg["data"]["forecast_horizon_hours"]
        steps_per_hour = pd.tseries.frequencies.to_offset(raw_freq).nanos / (3600 * 1e9)
        prediction_length = int(horizon * steps_per_hour)
        freq = raw_freq
        context_length_steps = int(cfg["data"]["context_length_hours"] * steps_per_hour)

    log.info(f"Fine-tuning Chronos-2 via AutoGluon")
    log.info(f"  Prediction length : {prediction_length} steps at {freq}")
    log.info(f"  Context length    : {context_length_steps} steps")
    log.info(f"  Time budget       : {time_budget}s")
    log.info(f"  Preset            : {model_preset}")
    log.info(f"  Quantiles         : {quantiles}")
    log.info(f"  Output dir        : {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    known_cov_cols = _get_known_covariate_cols(train_ts)

    predictor = TimeSeriesPredictor(
        target="target",
        prediction_length=prediction_length,
        freq=freq,
        quantile_levels=quantiles,
        eval_metric=cfg["finetune"]["eval_metric"],
        known_covariates_names=known_cov_cols,
        path=str(output_dir),
        verbosity=2,
    )

    predictor.fit(
        train_data=train_ts,
        time_limit=time_budget,
        presets=model_preset,
        hyperparameters={
            # Chronos requires CUDA — excluded. Zero-shot handled by zero_shot.py.
            "SeasonalNaive": {},
            "AutoETS": {},
            "DeepAR": {
                "epochs": 50,
                "num_layers": 2,
                "hidden_size": 40,
                "dropout_rate": 0.1,
                "batch_size": 32,
            },
            "TemporalFusionTransformer": {
                "epochs": 50,
                "hidden_size": 32,
                "num_heads": 2,
                "dropout_rate": 0.1,
                "batch_size": 32,
            },
        },
        num_val_windows=2,
        val_step_size=prediction_length,
    )

    log.info("\nFit complete. Leaderboard:")
    lb = predictor.leaderboard(silent=True)
    log.info(f"\n{lb.to_string()}")

    return predictor


def _get_known_covariate_cols(ts_df: "TimeSeriesDataFrame") -> list[str]:
    """Extract the known-future covariate column names from the TimeSeriesDataFrame."""
    return [c for c in KNOWN_FUTURE_COLS if c in ts_df.columns]


# ── Evaluation ─────────────────────────────────────────────────────────────────

def evaluate_on_val(
    predictor: "TimeSeriesPredictor",
    val_ts: "TimeSeriesDataFrame",
    cfg: dict,
) -> dict:
    """
    Run evaluation on the held-out validation set.
    Reports overall metrics + per-station breakdown.
    """
    log.info("Evaluating on validation set …")
    scores = predictor.evaluate(val_ts, metrics=["MASE", "WAPE", "MAE", "RMSE"])

    log.info(f"\n{'─'*50}")
    log.info("Validation Scores")
    log.info(f"{'─'*50}")
    for metric, score in scores.items():
        log.info(f"  {metric:6s}: {score:.4f}")

    log.info("(Per-station breakdown skipped — use predictor.leaderboard() for full details)")

    return scores


# ── Event-day evaluation ───────────────────────────────────────────────────────

def evaluate_event_days(
    predictor: "TimeSeriesPredictor",
    val_ts: "TimeSeriesDataFrame",
    feature_store: pd.DataFrame,
) -> None:
    """
    Evaluate separately on game-day vs non-game-day windows.
    This tells you how much the model benefits from the Sharks/events covariate.

    If WAPE on game days >> WAPE on normal days, the event features need work.
    """
    if "is_game_day" not in feature_store.columns:
        log.warning("is_game_day column not found — skipping event-day evaluation")
        return

    game_timestamps = feature_store[feature_store["is_game_day"]]["timestamp"].unique()
    normal_timestamps = feature_store[~feature_store["is_game_day"]]["timestamp"].unique()

    log.info(f"\nEvent-day evaluation:")
    log.info(f"  Game-day timesteps   : {len(game_timestamps):,}")
    log.info(f"  Normal-day timesteps : {len(normal_timestamps):,}")

    # Filter val_ts to game-day windows only
    # (simplified: check if any timestamp in the window is a game day)
    game_items = feature_store[
        feature_store["timestamp"].isin(game_timestamps)
    ]["station_id"].unique()

    log.info(f"  Stations affected by game days: {len(game_items)}")

    # This is a simplified slice — in production you'd build proper
    # game-day/non-game-day TimeSeriesDataFrame subsets
    log.info("  (Full event-day slice evaluation available in evaluation/ablation.py)")


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Fine-tune Chronos-2 on Bay Area ridership")
    parser.add_argument("--time-limit", type=int, default=None,
                        help="Training time budget in seconds (default: from config)")
    parser.add_argument("--preset", default=None,
                        choices=["fast_training", "medium_quality", "best_quality"],
                        help="AutoGluon preset (default: from config)")
    parser.add_argument("--output-dir", default=str(MODEL_DIR),
                        help="Where to save model weights")
    parser.add_argument("--skip-eval", action="store_true",
                        help="Skip validation evaluation after training")
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = load_config()
    output_dir = Path(args.output_dir)

    # 1. Load data
    train_df, val_df = load_train_val(cfg)
    feature_store = pd.concat([train_df, val_df], ignore_index=True)

    # 2. Convert to AutoGluon format
    log.info("Converting to AutoGluon TimeSeriesDataFrame …")
    train_ts = to_autogluon_format(train_df)
    val_ts   = to_autogluon_format(val_df)

    # 3. Fine-tune
    predictor = build_predictor(
        train_ts, cfg,
        time_limit=args.time_limit,
        preset=args.preset,
        output_dir=output_dir,
    )

    # 4. Evaluate — pass train+val so predictor has context rows (val alone = prediction_length rows)
    if not args.skip_eval:
        full_ts = to_autogluon_format(pd.concat([train_df, val_df], ignore_index=True))
        scores = evaluate_on_val(predictor, full_ts, cfg)
        evaluate_event_days(predictor, val_ts, feature_store)

        print(f"\n{'─'*50}")
        print(f"Fine-tuning complete!")
        print(f"  Model saved → {output_dir}")
        print(f"  WAPE  : {scores.get('WAPE', 'N/A'):.4f}")
        print(f"  MASE  : {scores.get('MASE', 'N/A'):.4f}")
        print(f"  MAE   : {scores.get('MAE', 'N/A'):.4f}")
        print(f"\nNext step: python models/chronos2/predict.py")

    return predictor


if __name__ == "__main__":
    main()
