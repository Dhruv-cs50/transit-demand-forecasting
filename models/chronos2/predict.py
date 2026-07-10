"""
models/chronos2/predict.py
───────────────────────────
Production inference wrapper for the fine-tuned Chronos-2 model.

This is the single entry point called by:
  - serving/api.py        (FastAPI endpoint → Live demo on website)
  - serving/scheduler.py  (nightly batch forecast run)
  - evaluation scripts    (metrics, ablation)

It handles:
  - Loading the fine-tuned model (cached after first load)
  - Building context windows from the feature store
  - Attaching future-known covariates (weather forecast, event schedule)
  - Returning clean P10/P50/P90 forecasts per station
  - Graceful fallback to zero-shot if fine-tuned weights not found

Usage:
    from models.chronos2.predict import Predictor
    predictor = Predictor()
    result = predictor.forecast(station_id="DIRIDON", horizon_hours=24)
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

log = logging.getLogger(__name__)

MODEL_DIR     = Path("models/chronos2/weights")
PROCESSED_DIR = Path("data/processed")
CONFIG_PATH   = Path("configs/model.yaml")
RAW_DIR       = Path("data/raw")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── Model cache ────────────────────────────────────────────────────────────────

class Predictor:
    """
    Singleton-style predictor that caches the model and feature store
    in memory after the first call. Thread-safe for FastAPI workers.

    Falls back gracefully:
      1. Fine-tuned AutoGluon predictor (models/chronos2/weights/)
      2. Zero-shot Chronos-2 (no training needed)
      3. Seasonal naive (if Chronos not installed)
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialised = False
        return cls._instance

    def __init__(self):
        if self._initialised:
            return
        self.cfg         = load_config()
        self._predictor  = None   # AutoGluon TimeSeriesPredictor
        self._pipeline   = None   # Chronos2Pipeline (zero-shot fallback)
        self._store      = None   # feature store DataFrame
        self._mode       = None   # "finetuned" | "zeroshot" | "naive"
        self._initialised = True

    # ── Feature store ──────────────────────────────────────────────────────────

    def get_feature_store(self) -> pd.DataFrame:
        """Load and cache the enriched feature store."""
        if self._store is not None:
            return self._store

        for fname in [
            "feature_store_enriched.parquet",
            "feature_store.parquet",
        ]:
            path = PROCESSED_DIR / fname
            if path.exists():
                log.info(f"Loading feature store: {path}")
                df = pd.read_parquet(path)
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                self._store = df
                log.info(f"  {len(df):,} rows | {df['station_id'].nunique()} stations")
                return self._store

        raise FileNotFoundError(
            "No feature store found. Run: python processing/merge_pipeline.py"
        )

    # ── Model loading ──────────────────────────────────────────────────────────

    def _load_finetuned(self) -> bool:
        """Try to load the fine-tuned AutoGluon predictor."""
        if not MODEL_DIR.exists():
            return False
        try:
            from autogluon.timeseries import TimeSeriesPredictor
            self._predictor = TimeSeriesPredictor.load(str(MODEL_DIR))
            self._mode = "finetuned"
            log.info("✅ Loaded fine-tuned AutoGluon predictor")
            return True
        except Exception as e:
            log.warning(f"Fine-tuned model load failed: {e}")
            return False

    def _load_zeroshot(self) -> bool:
        """Fall back to zero-shot Chronos-2."""
        try:
            from chronos import Chronos2Pipeline
            model_id = self.cfg["chronos2"]["model_id"]
            device   = self.cfg["chronos2"]["device"]
            log.info(f"Loading zero-shot {model_id} on {device} …")
            self._pipeline = Chronos2Pipeline.from_pretrained(
                model_id, device_map=device
            )
            self._mode = "zeroshot"
            log.info("✅ Zero-shot Chronos-2 ready")
            return True
        except Exception as e:
            log.warning(f"Chronos-2 load failed: {e}")
            return False

    def _ensure_loaded(self):
        if self._mode is not None:
            return
        if not self._load_finetuned():
            if not self._load_zeroshot():
                self._mode = "naive"
                log.warning("⚠️  Using seasonal naive fallback — install chronos-forecasting")

    # ── Context builder ────────────────────────────────────────────────────────

    def _build_context(
        self,
        station_id: str,
        as_of: pd.Timestamp,
        context_hours: int = None,
        context_steps: int = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Slice the feature store into context (past) and future windows.

        Context: last `context_hours` of actual observed data.
        Future : rows after `as_of` — contains weather forecast and event flags
                 that are already known (from Open-Meteo 7-day forecast and
                 NHL/Ticketmaster schedule).
        """
        df = self.get_feature_store()
        station_df = df[df["station_id"] == station_id].sort_values("timestamp")

        if station_df.empty:
            raise ValueError(f"Unknown station: {station_id}")

        history_df = station_df[station_df["timestamp"] <= as_of].copy()
        if context_steps:
            context_df = history_df.tail(context_steps).copy()
        else:
            context_start = as_of - pd.Timedelta(hours=context_hours)
            context_df = history_df[history_df["timestamp"] >= context_start].copy()

        future_df = station_df[station_df["timestamp"] > as_of].copy()

        if len(context_df) < 24:
            log.warning(
                f"Only {len(context_df)} context rows for {station_id} "
                f"(need ≥24) — predictions may be unreliable"
            )

        return context_df, future_df

    # ── Seasonal naive fallback ────────────────────────────────────────────────

    def _naive_forecast(
        self,
        context_df: pd.DataFrame,
        horizon_steps: int,
        freq: str,
        quantile_levels: list[float],
    ) -> pd.DataFrame:
        """
        Seasonal naive: repeat the same-time-last-week values.
        Used as emergency fallback if neither Chronos nor AutoGluon available.
        """
        if context_df.empty or "ridership" not in context_df.columns:
            return pd.DataFrame()

        if freq.upper() in {"MS", "M", "ME"} or "month" in freq.lower():
            period = min(12, len(context_df))
        else:
            # 168 hours = 1 week at hourly; at 15min → 672 steps
            period = int(pd.tseries.frequencies.to_offset(freq).nanos / (3600 * 1e9)) * 168
        series = context_df.set_index("timestamp")["ridership"]

        last_ts  = series.index.max()
        future_ts = pd.date_range(
            start=last_ts + pd.tseries.frequencies.to_offset(freq),
            periods=horizon_steps,
            freq=freq,
            tz=last_ts.tzinfo,
        )

        rows = []
        for i, ts in enumerate(future_ts):
            lag_idx = len(series) - period + (i % period)
            lag_val = float(series.iloc[max(0, lag_idx)]) if len(series) > 0 else 0.0
            noise   = np.random.normal(0, lag_val * 0.05)
            rows.append({
                "timestamp":  ts,
                "p10": max(0, lag_val * 0.80),
                "p50": max(0, lag_val + noise),
                "p90": max(0, lag_val * 1.20),
            })

        return pd.DataFrame(rows)

    # ── Core forecast ──────────────────────────────────────────────────────────

    def forecast(
        self,
        station_id: str,
        horizon_hours: int = None,
        as_of: pd.Timestamp = None,
        quantile_levels: list[float] = None,
    ) -> pd.DataFrame:
        """
        Generate a forecast for a single station.

        Args:
            station_id     : transit station code (e.g. "DIRIDON", "EMBR")
            horizon_hours  : hours to forecast ahead (default from config)
            as_of          : forecast origin timestamp (default: latest in store)
            quantile_levels: e.g. [0.1, 0.5, 0.9] for P10/P50/P90

        Returns:
            DataFrame with columns: timestamp, p10, p50, p90, station_id
        """
        self._ensure_loaded()

        cfg             = self.cfg
        freq            = cfg["data"].get("resample_freq", "MS")
        context_hours   = cfg["data"].get("context_length_hours")
        context_steps   = cfg["data"].get("context_length_steps") \
            or cfg["chronos2"].get("context_length_steps")
        quantile_levels = quantile_levels or cfg["chronos2"]["quantile_levels"]

        horizon_steps = cfg["data"].get("forecast_horizon_steps") \
            or cfg["chronos2"].get("prediction_length_steps")
        if horizon_steps is None:
            horizon_hours = horizon_hours or cfg["data"]["forecast_horizon_hours"]
            try:
                steps_per_hour = pd.tseries.frequencies.to_offset(freq).nanos / (3600 * 1e9)
                horizon_steps = int(horizon_hours * steps_per_hour)
            except ValueError:
                # Non-fixed frequencies (e.g. "MS" for month-start) have no fixed
                # nanosecond duration — approximate using a 30-day month.
                horizon_steps = max(1, round(horizon_hours / (30 * 24)))

        # Resolve as_of
        df = self.get_feature_store()
        if as_of is None:
            station_ts = df[df["station_id"] == station_id]["timestamp"]
            as_of = station_ts.max() if not station_ts.empty else pd.Timestamp.now(tz="America/Los_Angeles")
        elif as_of.tzinfo is None:
            as_of = as_of.tz_localize("America/Los_Angeles")

        context_df, future_df = self._build_context(
            station_id, as_of,
            context_hours=context_hours,
            context_steps=context_steps,
        )

        log.info(
            f"Forecasting {station_id} | mode={self._mode} | "
            f"horizon={horizon_steps} steps at {freq} | context={len(context_df)} rows"
        )

        # ── Fine-tuned AutoGluon ───────────────────────────────────────────────
        if self._mode == "finetuned":
            preds = self._finetuned_forecast(
                context_df, future_df, station_id, horizon_steps, quantile_levels
            )

        # ── Zero-shot Chronos-2 ───────────────────────────────────────────────
        elif self._mode == "zeroshot":
            preds = self._zeroshot_forecast(
                context_df, future_df, station_id, horizon_steps, quantile_levels
            )

        # ── Seasonal naive fallback ───────────────────────────────────────────
        else:
            preds = self._naive_forecast(context_df, horizon_steps, freq, quantile_levels)

        if preds.empty:
            log.error(f"No predictions generated for {station_id}")
            return pd.DataFrame()

        preds["station_id"] = station_id
        preds["generated_at"] = datetime.utcnow().isoformat()
        preds["model_mode"] = self._mode

        # Clip negatives
        for col in ["p10", "p50", "p90"]:
            if col in preds.columns:
                preds[col] = preds[col].clip(lower=0)

        return preds[["timestamp", "station_id", "p10", "p50", "p90",
                       "generated_at", "model_mode"]]

    def _finetuned_forecast(
        self,
        context_df, future_df, station_id, horizon_steps, quantile_levels
    ) -> pd.DataFrame:
        from autogluon.timeseries import TimeSeriesDataFrame

        ctx = context_df.rename(columns={"station_id": "item_id", "ridership": "target"})
        ctx = ctx.sort_values("timestamp")

        ts_df = TimeSeriesDataFrame.from_data_frame(
            ctx[["item_id", "timestamp", "target"]
                + [c for c in ctx.columns if c not in ("item_id","timestamp","target")]],
            id_column="item_id",
            timestamp_column="timestamp",
        )

        preds = self._predictor.predict(ts_df, prediction_length=horizon_steps)
        preds_df = preds.reset_index()

        col_map = {}
        for c in preds_df.columns:
            if "0.1" in str(c): col_map[c] = "p10"
            elif "0.5" in str(c) or c == "mean": col_map[c] = "p50"
            elif "0.9" in str(c): col_map[c] = "p90"
        preds_df = preds_df.rename(columns=col_map)

        return preds_df[["timestamp", "p10", "p50", "p90"]]

    def _zeroshot_forecast(
        self,
        context_df, future_df, station_id, horizon_steps, quantile_levels
    ) -> pd.DataFrame:
        from machine_learning_files.zero_shot import run_zero_shot_forecast

        preds_df = run_zero_shot_forecast(
            self._pipeline, context_df, future_df,
            station_id, horizon_steps, quantile_levels,
        )

        col_map = {}
        for c in preds_df.columns:
            if "0.1" in str(c): col_map[c] = "p10"
            elif "0.5" in str(c) or c == "mean": col_map[c] = "p50"
            elif "0.9" in str(c): col_map[c] = "p90"
        preds_df = preds_df.rename(columns=col_map)

        keep = [c for c in ["timestamp","p10","p50","p90"] if c in preds_df.columns]
        return preds_df[keep]

    # ── Batch forecast (all stations) ──────────────────────────────────────────

    def forecast_all_stations(
        self,
        horizon_hours: int = None,
        as_of: pd.Timestamp = None,
        output_path: Path = None,
    ) -> pd.DataFrame:
        """
        Run forecasts for every station in the feature store.
        Used by serving/scheduler.py for nightly batch runs.
        """
        df = self.get_feature_store()
        stations = df["station_id"].unique()
        all_preds = []

        for station_id in stations:
            try:
                preds = self.forecast(station_id, horizon_hours, as_of)
                if not preds.empty:
                    all_preds.append(preds)
                    log.info(f"  ✅ {station_id}: {len(preds)} timesteps")
            except Exception as e:
                log.error(f"  ❌ {station_id}: {e}")

        if not all_preds:
            log.error("No forecasts generated")
            return pd.DataFrame()

        combined = pd.concat(all_preds, ignore_index=True)

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            combined.to_parquet(output_path, index=False)
            log.info(f"Batch forecasts saved → {output_path}")

        return combined

    # ── Convenience: ridership lift vs typical ─────────────────────────────────

    def ridership_lift(
        self,
        station_id: str,
        forecast_df: pd.DataFrame = None,
    ) -> dict:
        """
        Compute how much ridership is expected to deviate from the typical
        value for this hour/day-of-week combination.

        Returns:
            {
              "lift_pct": 34.2,          # e.g. +34% vs typical
              "typical_median": 610.0,
              "forecast_p50": 818.0,
              "reason": "Sharks home game · puck drop 7:00"
            }

        This is what powers the "+34% vs typical Tue 7pm" card on your website.
        """
        df = self.get_feature_store()
        station_df = df[df["station_id"] == station_id]

        if station_df.empty or forecast_df is None or forecast_df.empty:
            return {}

        # Typical for this calendar month. The feature store is monthly
        # (each timestamp is a month-start), so hour_of_day is always 0 and
        # day_of_week is just whichever weekday the 1st fell on — neither
        # is a meaningful "typical" filter at this granularity.
        now = forecast_df["timestamp"].iloc[0]
        typical_mask = (
            (station_df["timestamp"].dt.month == now.month) &
            (~station_df.get("is_game_day", pd.Series(False, index=station_df.index)))
        )
        typical_median = station_df[typical_mask]["ridership"].median()
        forecast_p50   = forecast_df["p50"].iloc[0]

        if pd.isna(typical_median) or typical_median <= 0:
            lift_pct = float("nan")
        else:
            lift_pct = ((forecast_p50 - typical_median) / typical_median) * 100

        # Build reason string
        reason = ""
        if "is_sharks_game_window" in station_df.columns:
            future_row = station_df[station_df["timestamp"] > now]
            if not future_row.empty and future_row.iloc[0].get("is_sharks_game_window"):
                hour = int(future_row.iloc[0].get("game_start_hour", 19))
                reason = f"Sharks home game · puck drop {hour}:00"
        if not reason and "is_raining" in station_df.columns:
            if station_df[station_df["timestamp"] > now].iloc[0].get("is_raining"):
                reason = "Rain in forecast · ridership shift expected"

        return {
            "lift_pct":       round(lift_pct, 1),
            "typical_median": round(float(typical_median), 1),
            "forecast_p50":   round(float(forecast_p50), 1),
            "reason":         reason,
        }


# ── Standalone usage ───────────────────────────────────────────────────────────

def main():
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Run production forecast")
    parser.add_argument("--station",  default="EMBR",  help="Station ID")
    parser.add_argument("--horizon",  type=int, default=24, help="Forecast horizon (hours)")
    parser.add_argument("--all",      action="store_true", help="Forecast all stations")
    parser.add_argument("--output",   default=None, help="Output parquet path")
    args = parser.parse_args()

    predictor = Predictor()

    if args.all:
        output = Path(args.output) if args.output else \
            Path("models/chronos2/outputs") / \
            f"forecasts_{datetime.now().strftime('%Y%m%d_%H%M')}.parquet"
        combined = predictor.forecast_all_stations(
            horizon_hours=args.horizon,
            output_path=output,
        )
        print(f"\nBatch complete: {len(combined):,} rows across "
              f"{combined['station_id'].nunique()} stations")
    else:
        preds = predictor.forecast(args.station, horizon_hours=args.horizon)
        if not preds.empty:
            lift = predictor.ridership_lift(args.station, preds)
            print(f"\n{'─'*50}")
            print(f"Station  : {args.station}")
            print(f"Horizon  : {args.horizon}h | Steps: {len(preds)}")
            print(f"Mode     : {preds['model_mode'].iloc[0]}")
            print(f"Lift     : {lift.get('lift_pct', 'N/A'):+.1f}% vs typical")
            print(f"Reason   : {lift.get('reason', 'N/A')}")
            print(f"\n{preds[['timestamp','p10','p50','p90']].head(12).to_string(index=False)}")


if __name__ == "__main__":
    main()
