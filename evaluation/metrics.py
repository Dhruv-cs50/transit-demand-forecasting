"""
evaluation/metrics.py
──────────────────────
Computes forecast accuracy metrics for Bay Area transit ridership predictions.

Metrics computed:
  - MAE   : Mean Absolute Error — average magnitude of errors
  - RMSE  : Root Mean Squared Error — penalises large errors more heavily
  - MAPE  : Mean Absolute Percentage Error — scale-independent %
  - WAPE  : Weighted Absolute Percentage Error — robust to near-zero actuals
  - MASE  : Mean Absolute Scaled Error — compares vs seasonal naive baseline
  - sMAPE : Symmetric MAPE — handles both over and under forecasting equally

Breakdowns:
  - Overall (all stations, all hours)
  - Per station (which stations are hardest to forecast?)
  - Per hour-of-day (is the AM peak harder than midday?)
  - Per day-of-week (are Mondays anomalous?)
  - Event-day vs normal-day (does the model handle Sharks games well?)
  - Weather-day vs clear-day (does rain improve or hurt accuracy?)
  - By transit mode (rail vs bus vs ferry)

Usage:
    from evaluation.metrics import compute_all_metrics, print_report
    report = compute_all_metrics(actuals_df, predictions_df)
    print_report(report)

    # Or as a standalone script:
    python evaluation/metrics.py --actuals data/processed/splits/test.parquet \
                                  --predictions models/chronos2/outputs/forecasts.parquet
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

PROCESSED_DIR = Path("data/processed")
EVAL_DIR      = Path("evaluation/outputs")


# ── Core metric functions ──────────────────────────────────────────────────────

def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Error."""
    return float(np.mean(np.abs(y_pred - y_true)))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Root Mean Squared Error."""
    return float(np.sqrt(np.mean((y_pred - y_true) ** 2)))


def mape(y_true: np.ndarray, y_pred: np.ndarray, epsilon: float = 1.0) -> float:
    """
    Mean Absolute Percentage Error.
    Uses epsilon floor on actuals to avoid division by near-zero values
    (common in late-night windows with minimal ridership).
    """
    denom = np.maximum(np.abs(y_true), epsilon)
    return float(np.mean(np.abs(y_pred - y_true) / denom) * 100)


def wape(y_true: np.ndarray, y_pred: np.ndarray, epsilon: float = 1.0) -> float:
    """
    Weighted Absolute Percentage Error.
    More robust than MAPE for transit data because it weights errors by
    actual volume — a miss during peak hour counts more than a miss at 3am.

    WAPE = sum(|y_pred - y_true|) / sum(|y_true|)
    """
    denom = np.sum(np.abs(y_true))
    if denom < epsilon:
        return float("nan")
    return float(np.sum(np.abs(y_pred - y_true)) / denom * 100)


def smape(y_true: np.ndarray, y_pred: np.ndarray, epsilon: float = 1.0) -> float:
    """
    Symmetric MAPE — treats over and under forecasting equally.
    Useful because transit agencies care about both over-provisioning
    (wasted vehicles) and under-provisioning (overcrowded trains).
    """
    denom = (np.abs(y_true) + np.abs(y_pred)) / 2 + epsilon
    return float(np.mean(np.abs(y_pred - y_true) / denom) * 100)


def mase(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_train: np.ndarray,
    seasonality: int = 96,   # 96 × 15min = 24hr seasonal period
    ids: np.ndarray = None,
) -> float:
    """
    Mean Absolute Scaled Error.
    Scales MAE by the in-sample MAE of a seasonal naive forecast.
    MASE < 1.0 means the model beats the seasonal naive baseline.

    seasonality=96 → compare vs same-time-yesterday (24hrs at 15min freq)

    y_train must already be sorted chronologically. If `ids` is given
    (aligned 1:1 with y_train, e.g. station_id per row), the seasonal-naive
    lag is computed independently within each id's own run of rows instead
    of across the whole array — otherwise, when y_train concatenates
    multiple series (e.g. all stations stacked together), the lag silently
    diffs unrelated series against each other.
    """
    if ids is not None:
        naive_error_chunks = []
        for _, idx in pd.Series(np.arange(len(y_train))).groupby(pd.Series(ids), sort=False):
            vals = y_train[idx.values]
            if len(vals) > seasonality:
                naive_error_chunks.append(np.abs(vals[seasonality:] - vals[:-seasonality]))
        if not naive_error_chunks:
            return float("nan")
        naive_errors = np.concatenate(naive_error_chunks)
    else:
        if len(y_train) <= seasonality:
            return float("nan")
        naive_errors = np.abs(y_train[seasonality:] - y_train[:-seasonality])

    scale = np.mean(naive_errors)
    if scale < 1e-8:
        return float("nan")
    return float(np.mean(np.abs(y_pred - y_true)) / scale)


def _infer_seasonal_period(train_df: pd.DataFrame) -> int:
    """
    Infer the seasonal-naive lag from the training data's actual timestamp
    cadence, instead of assuming the 15-min-freq 96 default regardless of
    the pipeline's real granularity (this project's feature store is
    monthly — configs/model.yaml's `data.granularity` — for which 96 has
    no meaning and 12, the annual seasonal period, is correct).
    """
    if train_df is None or "timestamp" not in train_df.columns or len(train_df) < 2:
        return 96
    ts = pd.to_datetime(train_df["timestamp"]).sort_values().drop_duplicates()
    if len(ts) < 2:
        return 96
    median_delta = ts.diff().dropna().median()
    if median_delta >= pd.Timedelta(days=25):
        return 12   # monthly cadence → annual seasonal period
    if median_delta >= pd.Timedelta(hours=20):
        return 7    # daily cadence → weekly seasonal period
    if median_delta <= pd.Timedelta(minutes=20):
        return 96   # 15-min cadence → 24hr seasonal period
    return 24        # hourly cadence → 24hr seasonal period


def coverage(
    y_true: np.ndarray,
    y_lower: np.ndarray,
    y_upper: np.ndarray,
) -> float:
    """
    Prediction interval coverage rate.
    For P10/P90 intervals, we expect ~80% coverage.
    Significantly below 80% = intervals too narrow (overconfident).
    Significantly above 80% = intervals too wide (underconfident).
    """
    covered = (y_true >= y_lower) & (y_true <= y_upper)
    return float(np.mean(covered) * 100)


def interval_width(y_lower: np.ndarray, y_upper: np.ndarray) -> float:
    """Average width of the prediction interval (P90 - P10)."""
    return float(np.mean(y_upper - y_lower))


# ── Result container ───────────────────────────────────────────────────────────

@dataclass
class MetricsReport:
    """Holds all computed metrics with metadata."""
    label:    str                     # e.g. "Overall", "Station: EMBR"
    n:        int                     # number of predictions evaluated
    mae:      float
    rmse:     float
    mape:     float
    wape:     float
    smape:    float
    mase:     Optional[float] = None
    coverage: Optional[float] = None  # P10/P90 coverage rate
    int_width:Optional[float] = None  # avg P90-P10 width
    details:  dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "label":    self.label,
            "n":        self.n,
            "MAE":      round(self.mae,   2),
            "RMSE":     round(self.rmse,  2),
            "MAPE_%":   round(self.mape,  2),
            "WAPE_%":   round(self.wape,  2),
            "sMAPE_%":  round(self.smape, 2),
            "MASE":     round(self.mase,  4) if self.mase is not None else None,
            "Coverage_%": round(self.coverage, 1) if self.coverage is not None else None,
            "Int_Width":  round(self.int_width, 1) if self.int_width is not None else None,
        }

    def __str__(self) -> str:
        lines = [
            f"{'─'*55}",
            f"  {self.label}  (n={self.n:,})",
            f"{'─'*55}",
            f"  MAE     : {self.mae:>10.2f}  riders",
            f"  RMSE    : {self.rmse:>10.2f}  riders",
            f"  MAPE    : {self.mape:>10.2f}  %",
            f"  WAPE    : {self.wape:>10.2f}  %",
            f"  sMAPE   : {self.smape:>10.2f}  %",
        ]
        if self.mase is not None and not np.isnan(self.mase):
            lines.append(f"  MASE    : {self.mase:>10.4f}  ({'beats' if self.mase < 1 else 'trails'} naive)")
        elif self.mase is not None:
            lines.append(f"  MASE    : {'n/a':>10}  (undefined — insufficient seasonal history)")
        if self.coverage is not None:
            lines.append(f"  P10/P90 coverage: {self.coverage:.1f}%  (target: 80%)")
        if self.int_width is not None:
            lines.append(f"  Interval width  : {self.int_width:.1f} riders (avg P90-P10)")
        lines.append(f"{'─'*55}")
        return "\n".join(lines)


# ── Core evaluation function ───────────────────────────────────────────────────

def _compute(
    label: str,
    merged: pd.DataFrame,
    train_df: pd.DataFrame = None,
    pred_col: str = "p50",
    actual_col: str = "ridership",
    p10_col: str = "p10",
    p90_col: str = "p90",
) -> MetricsReport:
    """Compute all metrics for a merged actuals+predictions DataFrame."""
    if merged.empty:
        log.warning(f"Empty slice for '{label}' — skipping")
        return None

    y_true = merged[actual_col].values.astype(float)
    y_pred = merged[pred_col].values.astype(float)

    # Clip negatives (model can't predict negative ridership)
    y_pred = np.maximum(y_pred, 0.0)

    # MASE requires training data for scale
    mase_val = None
    if train_df is not None and actual_col in train_df.columns:
        seasonal_period = _infer_seasonal_period(train_df)
        train_sorted = train_df.sort_values("timestamp") if "timestamp" in train_df.columns else train_df
        train_valid = train_sorted.dropna(subset=[actual_col])
        y_train = train_valid[actual_col].values.astype(float)
        # Group the seasonal-naive scale by station so multi-station train_df
        # (e.g. overall_metrics' full training set) never diffs one station's
        # ridership against another's.
        ids = train_valid["station_id"].values if "station_id" in train_valid.columns else None
        if len(y_train) > seasonal_period:
            mase_val = mase(y_true, y_pred, y_train, seasonality=seasonal_period, ids=ids)

    # Prediction interval metrics
    cov_val = width_val = None
    if p10_col in merged.columns and p90_col in merged.columns:
        y_lower = np.maximum(merged[p10_col].values.astype(float), 0.0)
        y_upper = np.maximum(merged[p90_col].values.astype(float), 0.0)
        cov_val   = coverage(y_true, y_lower, y_upper)
        width_val = interval_width(y_lower, y_upper)

    return MetricsReport(
        label=label,
        n=len(merged),
        mae=mae(y_true, y_pred),
        rmse=rmse(y_true, y_pred),
        mape=mape(y_true, y_pred),
        wape=wape(y_true, y_pred),
        smape=smape(y_true, y_pred),
        mase=mase_val,
        coverage=cov_val,
        int_width=width_val,
    )


# ── Slice-based evaluations ────────────────────────────────────────────────────

def overall_metrics(
    merged: pd.DataFrame,
    train_df: pd.DataFrame = None,
    pred_col: str = "p50",
    actual_col: str = "ridership",
) -> MetricsReport:
    return _compute("Overall", merged, train_df, pred_col=pred_col, actual_col=actual_col)


def per_station_metrics(
    merged: pd.DataFrame,
    train_df: pd.DataFrame = None,
    top_n: int = None,
    pred_col: str = "p50",
    actual_col: str = "ridership",
) -> pd.DataFrame:
    """Return a DataFrame with metrics for each station, sorted by WAPE."""
    rows = []
    for station, grp in merged.groupby("station_id"):
        train_grp = train_df[train_df["station_id"] == station] \
            if train_df is not None else None
        r = _compute(f"Station: {station}", grp, train_grp, pred_col=pred_col, actual_col=actual_col)
        if r:
            d = r.to_dict()
            d["station_id"] = station
            rows.append(d)

    df = pd.DataFrame(rows).sort_values("WAPE_%")
    return df.head(top_n) if top_n else df


def per_hour_metrics(
    merged: pd.DataFrame,
    pred_col: str = "p50",
    actual_col: str = "ridership",
) -> pd.DataFrame:
    """Metrics broken down by hour of day — reveals peak vs off-peak accuracy."""
    if "hour_of_day" not in merged.columns:
        merged["hour_of_day"] = pd.to_datetime(merged["timestamp"]).dt.hour

    rows = []
    for hour, grp in merged.groupby("hour_of_day"):
        r = _compute(f"Hour {hour:02d}:00", grp, pred_col=pred_col, actual_col=actual_col)
        if r:
            d = r.to_dict()
            d["hour"] = hour
            rows.append(d)
    return pd.DataFrame(rows).sort_values("hour")


def per_dow_metrics(
    merged: pd.DataFrame,
    pred_col: str = "p50",
    actual_col: str = "ridership",
) -> pd.DataFrame:
    """Metrics by day of week — reveals Mon/Fri anomalies."""
    if "day_of_week" not in merged.columns:
        merged["day_of_week"] = pd.to_datetime(merged["timestamp"]).dt.dayofweek

    DOW_NAMES = {0:"Mon", 1:"Tue", 2:"Wed", 3:"Thu", 4:"Fri", 5:"Sat", 6:"Sun"}
    rows = []
    for dow, grp in merged.groupby("day_of_week"):
        r = _compute(f"{DOW_NAMES[dow]}", grp, pred_col=pred_col, actual_col=actual_col)
        if r:
            d = r.to_dict()
            d["dow"] = dow
            d["day_name"] = DOW_NAMES[dow]
            rows.append(d)
    return pd.DataFrame(rows).sort_values("dow")


def event_day_metrics(
    merged: pd.DataFrame,
    pred_col: str = "p50",
    actual_col: str = "ridership",
) -> dict[str, MetricsReport]:
    """
    Compare accuracy on game-day windows vs normal days.
    Key diagnostic: if game-day WAPE >> normal WAPE, the event features need work.
    """
    results = {}

    if "is_game_day" in merged.columns:
        game = merged[merged["is_game_day"] == True]
        normal = merged[merged["is_game_day"] == False]
        results["game_day"]    = _compute("Game Days",    game,   pred_col=pred_col, actual_col=actual_col)
        results["normal_day"]  = _compute("Normal Days",  normal, pred_col=pred_col, actual_col=actual_col)

    if "is_sharks_game_window" in merged.columns:
        sharks = merged[merged["is_sharks_game_window"] == True]
        results["sharks_game"] = _compute("Sharks Games", sharks, pred_col=pred_col, actual_col=actual_col)

    if "is_holiday" in merged.columns:
        holiday = merged[merged["is_holiday"] == True]
        results["holiday"] = _compute("Holidays", holiday, pred_col=pred_col, actual_col=actual_col)

    return results


def weather_day_metrics(
    merged: pd.DataFrame,
    pred_col: str = "p50",
    actual_col: str = "ridership",
) -> dict[str, MetricsReport]:
    """
    Compare accuracy on rainy vs clear days.
    Key diagnostic: rain should improve accuracy if weather covariates are working.
    """
    results = {}

    if "is_raining" in merged.columns:
        rainy = merged[merged["is_raining"] == True]
        clear = merged[merged["is_raining"] == False]
        results["rainy"] = _compute("Rainy",   rainy, pred_col=pred_col, actual_col=actual_col)
        results["clear"] = _compute("Clear",   clear, pred_col=pred_col, actual_col=actual_col)

    if "precip_intensity" in merged.columns:
        heavy = merged[merged["precip_intensity"] >= 3]
        results["heavy_rain"] = _compute("Heavy Rain", heavy, pred_col=pred_col, actual_col=actual_col)

    return results


def transit_mode_metrics(
    merged: pd.DataFrame,
    pred_col: str = "p50",
    actual_col: str = "ridership",
) -> pd.DataFrame:
    """Metrics by transit mode — rail vs bus vs ferry."""
    if "transit_mode" not in merged.columns:
        return pd.DataFrame()

    rows = []
    for mode, grp in merged.groupby("transit_mode"):
        r = _compute(f"Mode: {mode}", grp, pred_col=pred_col, actual_col=actual_col)
        if r:
            d = r.to_dict()
            d["transit_mode"] = mode
            rows.append(d)
    return pd.DataFrame(rows)


# ── Full report ────────────────────────────────────────────────────────────────

def compute_all_metrics(
    actuals_df: pd.DataFrame,
    predictions_df: pd.DataFrame,
    train_df: pd.DataFrame = None,
    pred_col: str = "p50",
    actual_col: str = "ridership",
) -> dict:
    """
    Merge actuals and predictions, then compute all metric slices.

    actuals_df     : test split with actual ridership values
    predictions_df : model output with p10, p50, p90 columns + timestamp + station_id
    train_df       : training data for MASE scaling (optional)

    Returns a dict of all MetricsReport objects and DataFrames.
    """
    log.info("Merging actuals and predictions …")

    # Ensure consistent types
    actuals_df = actuals_df.copy()
    predictions_df = predictions_df.copy()
    actuals_df["timestamp"]     = pd.to_datetime(actuals_df["timestamp"])
    predictions_df["timestamp"] = pd.to_datetime(predictions_df["timestamp"])

    # Join on timestamp + station_id
    merged = actuals_df.merge(
        predictions_df,
        on=["timestamp", "station_id"],
        how="inner",
        suffixes=("_actual", "_pred"),
    )

    if merged.empty:
        log.error("No matching rows between actuals and predictions — check timestamps")
        return {}

    log.info(f"Merged: {len(merged):,} rows across {merged['station_id'].nunique()} stations")

    results = {}

    # Overall
    log.info("Computing overall metrics …")
    results["overall"] = overall_metrics(merged, train_df, pred_col=pred_col, actual_col=actual_col)

    # Per station
    log.info("Computing per-station metrics …")
    results["per_station"] = per_station_metrics(merged, train_df, pred_col=pred_col, actual_col=actual_col)

    # Per hour
    log.info("Computing per-hour metrics …")
    results["per_hour"] = per_hour_metrics(merged, pred_col=pred_col, actual_col=actual_col)

    # Per day of week
    log.info("Computing per-DOW metrics …")
    results["per_dow"] = per_dow_metrics(merged, pred_col=pred_col, actual_col=actual_col)

    # Event days
    log.info("Computing event-day metrics …")
    results["event_days"] = event_day_metrics(merged, pred_col=pred_col, actual_col=actual_col)

    # Weather days
    log.info("Computing weather-day metrics …")
    results["weather_days"] = weather_day_metrics(merged, pred_col=pred_col, actual_col=actual_col)

    # Transit mode
    log.info("Computing transit-mode metrics …")
    results["transit_mode"] = transit_mode_metrics(merged, pred_col=pred_col, actual_col=actual_col)

    return results


def print_report(results: dict) -> None:
    """Print a human-readable summary of all metrics."""
    print(f"\n{'═'*55}")
    print("  BAY AREA TRANSIT FORECAST — EVALUATION REPORT")
    print(f"{'═'*55}")

    if "overall" in results and results["overall"]:
        print(results["overall"])

    if "event_days" in results:
        print("\n📅 Event Day Breakdown")
        for label, r in results["event_days"].items():
            if r:
                print(f"  {r.label:20s}  WAPE={r.wape:.1f}%  MAE={r.mae:.0f}")

    if "weather_days" in results:
        print("\n🌧️  Weather Breakdown")
        for label, r in results["weather_days"].items():
            if r:
                print(f"  {r.label:20s}  WAPE={r.wape:.1f}%  MAE={r.mae:.0f}")

    if "per_station" in results and not results["per_station"].empty:
        df = results["per_station"]
        print(f"\n🚉 Per-Station WAPE (5 best / 5 worst)")
        print("  BEST:")
        for _, row in df.head(5).iterrows():
            print(f"    {row['station_id']:10s}  WAPE={row['WAPE_%']:.1f}%")
        print("  WORST:")
        for _, row in df.tail(5).iterrows():
            print(f"    {row['station_id']:10s}  WAPE={row['WAPE_%']:.1f}%")

    if "per_hour" in results and not results["per_hour"].empty:
        df = results["per_hour"]
        print(f"\n⏰ Hourly WAPE (AM peak vs PM peak vs midday)")
        am   = df[df["hour"].between(7, 9)]["WAPE_%"].mean()
        mid  = df[df["hour"].between(10, 15)]["WAPE_%"].mean()
        pm   = df[df["hour"].between(16, 19)]["WAPE_%"].mean()
        late = df[(df["hour"] >= 22) | (df["hour"] <= 5)]["WAPE_%"].mean()
        print(f"  AM peak   (7–9am)  : {am:.1f}%")
        print(f"  Midday   (10–3pm)  : {mid:.1f}%")
        print(f"  PM peak  (4–7pm)   : {pm:.1f}%")
        print(f"  Late night (10pm+) : {late:.1f}%")

    print(f"\n{'═'*55}\n")


def save_report(results: dict, output_dir: Path = EVAL_DIR) -> None:
    """Save all metric tables to CSV files for storage / dashboards."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if "overall" in results and results["overall"]:
        pd.DataFrame([results["overall"].to_dict()]).to_csv(
            output_dir / "metrics_overall.csv", index=False
        )

    for key in ["per_station", "per_hour", "per_dow", "transit_mode"]:
        if key in results and not results[key].empty:
            results[key].to_csv(output_dir / f"metrics_{key}.csv", index=False)

    for group_key in ["event_days", "weather_days"]:
        if group_key in results:
            rows = [r.to_dict() for r in results[group_key].values() if r]
            if rows:
                pd.DataFrame(rows).to_csv(
                    output_dir / f"metrics_{group_key}.csv", index=False
                )

    log.info(f"All metrics saved → {output_dir}/")


# ── Standalone script ──────────────────────────────────────────────────────────

def main():
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Evaluate forecast accuracy")
    parser.add_argument(
        "--actuals",
        default=str(PROCESSED_DIR / "splits/test.parquet"),
        help="Path to actuals parquet (test split)",
    )
    parser.add_argument(
        "--predictions",
        default="models/chronos2/outputs/forecasts.parquet",
        help="Path to predictions parquet (p10, p50, p90 columns)",
    )
    parser.add_argument(
        "--train",
        default=str(PROCESSED_DIR / "splits/train.parquet"),
        help="Training data path for MASE scaling",
    )
    args = parser.parse_args()

    # Load data
    actuals_path = Path(args.actuals)
    preds_path   = Path(args.predictions)

    if not actuals_path.exists():
        log.error(f"Actuals not found: {actuals_path}")
        return
    if not preds_path.exists():
        log.error(f"Predictions not found: {preds_path}")
        return

    actuals_df     = pd.read_parquet(actuals_path)
    predictions_df = pd.read_parquet(preds_path)

    train_df = None
    train_path = Path(args.train)
    if train_path.exists():
        train_df = pd.read_parquet(train_path)

    # Compute and print
    results = compute_all_metrics(actuals_df, predictions_df, train_df)
    print_report(results)
    save_report(results)


if __name__ == "__main__":
    main()
