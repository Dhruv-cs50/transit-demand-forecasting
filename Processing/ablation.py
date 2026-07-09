"""
evaluation/ablation.py
───────────────────────
Ablation study — measures the accuracy impact of each covariate group
by systematically zeroing out feature groups and re-evaluating.

Ablation groups tested:
  1. Baseline        — no covariates at all (time series only)
  2. + Calendar      — add hour/day/holiday features
  3. + Weather       — add precipitation, temperature, wind
  4. + Events        — add Sharks games, concerts, event proximity
  5. + Station       — add hub flag, transit mode, distance from Diridon
  6. Full model      — all covariates (production configuration)

For each group we measure WAPE and MAE overall AND specifically on:
  - Sharks game windows (the key use case)
  - Rainy days (second most important signal)
  - AM/PM peak hours

This tells you exactly which data sources are earning their keep.

Usage:
    python evaluation/ablation.py
    python evaluation/ablation.py --model-dir models/chronos2/weights
"""

from __future__ import annotations

import argparse
import copy
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation.metrics import (
    MetricsReport,
    _compute,
    wape,
    mae,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ablation")

PROCESSED_DIR = Path("data/processed")
EVAL_DIR      = Path("evaluation/outputs")
MODEL_DIR     = Path("models/chronos2/weights")


# ── Covariate groups ───────────────────────────────────────────────────────────

# Define which columns belong to each group so we can zero them out
COVARIATE_GROUPS = {
    "calendar": [
        "hour_of_day", "day_of_week", "is_weekend", "is_monday", "is_friday",
        "is_holiday", "is_holiday_eve", "is_am_peak", "is_pm_peak",
        "is_midday", "is_late_night", "month", "week_of_year", "quarter",
        "hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
    ],
    "weather": [
        "temp_f", "precip_mm", "precip_in", "windspeed_mph", "is_raining",
        "precip_intensity", "weather_discomfort", "is_very_cold", "is_very_hot",
        "is_windy", "temp_deviation", "precip_3hr_sum", "precip_6hr_sum",
        "precip_24hr_sum", "is_rain_onset", "cloud_cover_pct", "humidity_pct",
    ],
    "events": [
        "is_game_day", "is_sharks_game_window", "game_start_hour",
        "is_pre_event_window", "is_post_event_window", "is_playoff",
        "is_any_event_day", "nearest_event_attendance_tier",
        "hours_to_next_event", "hours_since_last_event",
        "event_proximity_score",
    ],
    "station": [
        "is_hub_station", "capacity_tier", "in_event_catchment",
        "dist_from_diridon_km", "transit_mode",
    ],
    "lags": [
        "ridership_lag_1", "ridership_lag_2", "ridership_lag_3",
        "ridership_lag_6", "ridership_lag_12",
        "ridership_rolling_mean_3mo", "ridership_rolling_std_3mo",
        "ridership_rolling_mean_12mo",
        "ridership_lag_4", "ridership_lag_8",
        "ridership_lag_96", "ridership_lag_192", "ridership_lag_672",
        "ridership_rolling_mean_24h", "ridership_rolling_std_24h",
        "ridership_rolling_mean_7d",
    ],
}

# Cumulative ablation configurations (add one group at a time)
ABLATION_CONFIGS = {
    "1_baseline":          [],
    "2_plus_calendar":     ["calendar"],
    "3_plus_weather":      ["calendar", "weather"],
    "4_plus_events":       ["calendar", "weather", "events"],
    "5_plus_station":      ["calendar", "weather", "events", "station"],
    "6_full_model":        ["calendar", "weather", "events", "station", "lags"],
}


# ── Feature zeroing ────────────────────────────────────────────────────────────

def zero_out_groups(
    df: pd.DataFrame,
    include_groups: list[str],
) -> pd.DataFrame:
    """
    Return a copy of df where all covariate groups NOT in include_groups
    are zeroed out (numeric → 0, bool → False).

    This simulates running the model without those features.
    """
    df = df.copy()
    all_groups = list(COVARIATE_GROUPS.keys())
    exclude_groups = [g for g in all_groups if g not in include_groups]

    for group in exclude_groups:
        for col in COVARIATE_GROUPS[group]:
            if col not in df.columns:
                continue
            if df[col].dtype == bool or str(df[col].dtype) == "bool":
                df[col] = False
            elif df[col].dtype == object:
                pass  # leave string/categorical columns as-is
            else:
                df[col] = 0.0

    return df


# ── Model runner ───────────────────────────────────────────────────────────────

def run_inference_with_config(
    model_dir: Path,
    feature_store: pd.DataFrame,
    include_groups: list[str],
    cfg: dict,
) -> pd.DataFrame:
    """
    Run inference using the fine-tuned predictor with only the specified
    covariate groups active (all others zeroed out).

    Returns a DataFrame with columns: timestamp, station_id, p10, p50, p90
    """
    try:
        from autogluon.timeseries import TimeSeriesPredictor, TimeSeriesDataFrame
    except ImportError:
        raise ImportError("Install AutoGluon: pip install autogluon.timeseries")

    if not model_dir.exists():
        raise FileNotFoundError(
            f"Model not found at {model_dir}. "
            "Run: python models/chronos2/finetune.py first."
        )

    # Zero out excluded covariate groups
    ablated_df = zero_out_groups(feature_store, include_groups)

    # Convert to AutoGluon format
    ablated_df = ablated_df.copy()
    ablated_df = ablated_df.rename(columns={"station_id": "item_id", "ridership": "target"})
    ablated_df = ablated_df.sort_values(["item_id", "timestamp"])

    # Keep every covariate column the fine-tuned predictor was trained with —
    # not just the ones in `include_groups`. zero_out_groups() already zeroed
    # the excluded ones; dropping those columns entirely instead would hand
    # AutoGluon a schema missing its known_covariates_names for every config
    # except "6_full_model", breaking the very comparison ablation exists to run.
    all_covariate_cols = [c for group_cols in COVARIATE_GROUPS.values() for c in group_cols]
    ts_df = TimeSeriesDataFrame.from_data_frame(
        ablated_df[["item_id", "timestamp", "target"]
            + [c for c in all_covariate_cols if c in ablated_df.columns]
        ],
        id_column="item_id",
        timestamp_column="timestamp",
    )

    predictor = TimeSeriesPredictor.load(str(model_dir))
    prediction_length = cfg["data"].get("forecast_horizon_steps") \
        or cfg["chronos2"].get("prediction_length_steps")
    if prediction_length is None:
        freq = cfg["data"]["resample_freq"]
        horizon_hours = cfg["data"]["forecast_horizon_hours"]
        try:
            steps_per_hour = pd.tseries.frequencies.to_offset(freq).nanos / (3600 * 1e9)
            prediction_length = int(horizon_hours * steps_per_hour)
        except ValueError:
            # Non-fixed frequencies (e.g. "MS" for month-start) have no fixed
            # nanosecond duration — approximate using a 30-day month.
            prediction_length = max(1, round(horizon_hours / (30 * 24)))

    preds = predictor.predict(ts_df, prediction_length=prediction_length)

    # Convert AutoGluon output to flat DataFrame
    preds_df = preds.reset_index()
    preds_df = preds_df.rename(columns={
        "item_id":  "station_id",
        "0.1":      "p10",
        "mean":     "p50",
        "0.9":      "p90",
    })

    # Handle alternate column naming
    if "p50" not in preds_df.columns:
        q50_col = [c for c in preds_df.columns if "0.5" in str(c)]
        if q50_col:
            preds_df = preds_df.rename(columns={q50_col[0]: "p50"})

    return preds_df[["timestamp", "station_id", "p10", "p50", "p90"]]


# ── Slice evaluations ──────────────────────────────────────────────────────────

def eval_on_slices(
    actuals: pd.DataFrame,
    preds: pd.DataFrame,
    config_name: str,
) -> list[dict]:
    """
    Evaluate predictions across multiple diagnostic slices.
    Returns a list of result dicts for this ablation configuration.
    """
    merged = actuals.merge(preds, on=["timestamp", "station_id"], how="inner")
    if merged.empty:
        return []

    results = []

    def _row(label: str, subset: pd.DataFrame) -> dict | None:
        if subset.empty:
            return None
        y_true = subset["ridership"].values.astype(float)
        y_pred = subset["p50"].values.astype(float)
        y_pred = np.maximum(y_pred, 0.0)
        return {
            "config":    config_name,
            "slice":     label,
            "n":         len(subset),
            "WAPE_%":    round(wape(y_true, y_pred), 2),
            "MAE":       round(mae(y_true, y_pred),  2),
        }

    # Overall
    r = _row("overall", merged)
    if r: results.append(r)

    # Sharks game windows — the primary use case
    if "is_sharks_game_window" in merged.columns:
        sharks = merged[merged["is_sharks_game_window"] == True]
        r = _row("sharks_game_window", sharks)
        if r: results.append(r)

    # All game days
    if "is_game_day" in merged.columns:
        game = merged[merged["is_game_day"] == True]
        r = _row("game_day", game)
        if r: results.append(r)

    # Rainy days
    if "is_raining" in merged.columns:
        rainy = merged[merged["is_raining"] == True]
        r = _row("rainy_day", rainy)
        if r: results.append(r)

    # Heavy rain specifically
    if "precip_intensity" in merged.columns:
        heavy = merged[merged["precip_intensity"] >= 3]
        r = _row("heavy_rain", heavy)
        if r: results.append(r)

    # AM peak
    if "is_am_peak" in merged.columns:
        am = merged[merged["is_am_peak"] == True]
        r = _row("am_peak", am)
        if r: results.append(r)

    # PM peak
    if "is_pm_peak" in merged.columns:
        pm = merged[merged["is_pm_peak"] == True]
        r = _row("pm_peak", pm)
        if r: results.append(r)

    # Diridon catchment stations
    if "in_event_catchment" in merged.columns:
        catchment = merged[merged["in_event_catchment"] == True]
        r = _row("event_catchment_stations", catchment)
        if r: results.append(r)

    return results


# ── Main ablation runner ───────────────────────────────────────────────────────

def run_ablation(
    model_dir: Path,
    test_df: pd.DataFrame,
    feature_store: pd.DataFrame,
    cfg: dict,
    configs: dict = None,
) -> pd.DataFrame:
    """
    Run the full ablation study across all covariate configurations.

    For each config:
      1. Zero out excluded covariate groups in the feature store
      2. Run inference with the fine-tuned model
      3. Evaluate on all diagnostic slices
      4. Record WAPE and MAE

    Returns a tidy DataFrame with all results, ready for plotting/reporting.
    """
    if configs is None:
        configs = ABLATION_CONFIGS

    all_rows = []

    for config_name, include_groups in configs.items():
        log.info(f"\n{'─'*55}")
        log.info(f"Running ablation config: {config_name}")
        log.info(f"  Active groups: {include_groups or ['none (baseline)']}")

        try:
            preds = run_inference_with_config(
                model_dir, feature_store, include_groups, cfg
            )
            rows = eval_on_slices(test_df, preds, config_name)
            all_rows.extend(rows)
            log.info(f"  → {len(rows)} slice evaluations complete")
        except Exception as e:
            log.error(f"  Config {config_name} failed: {e}")

    results_df = pd.DataFrame(all_rows)
    return results_df


# ── Impact summary ─────────────────────────────────────────────────────────────

def summarise_impact(ablation_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the WAPE improvement of each covariate group over the previous step.

    E.g. "Adding weather features reduces WAPE on rainy days from 28.4% to 19.1%
          → 9.3 percentage point improvement."
    """
    if ablation_df.empty:
        return pd.DataFrame()

    configs_ordered = list(ABLATION_CONFIGS.keys())
    slices = ablation_df["slice"].unique()

    rows = []
    for sl in slices:
        slice_data = ablation_df[ablation_df["slice"] == sl]

        for i in range(1, len(configs_ordered)):
            prev_config = configs_ordered[i - 1]
            curr_config = configs_ordered[i]

            prev_row = slice_data[slice_data["config"] == prev_config]
            curr_row = slice_data[slice_data["config"] == curr_config]

            if prev_row.empty or curr_row.empty:
                continue

            prev_wape = prev_row["WAPE_%"].values[0]
            curr_wape = curr_row["WAPE_%"].values[0]
            delta     = prev_wape - curr_wape  # positive = improvement

            # Which group was added?
            prev_groups = set(ABLATION_CONFIGS[prev_config])
            curr_groups = set(ABLATION_CONFIGS[curr_config])
            added_group = list(curr_groups - prev_groups)

            rows.append({
                "slice":           sl,
                "added_group":     added_group[0] if added_group else "all",
                "prev_config":     prev_config,
                "curr_config":     curr_config,
                "prev_WAPE_%":     round(prev_wape, 2),
                "curr_WAPE_%":     round(curr_wape, 2),
                "WAPE_delta_pp":   round(delta, 2),
                "pct_improvement": round(delta / prev_wape * 100, 1) if prev_wape > 0 else 0,
            })

    impact_df = pd.DataFrame(rows).sort_values(
        ["slice", "WAPE_delta_pp"], ascending=[True, False]
    )
    return impact_df


def print_ablation_report(
    ablation_df: pd.DataFrame,
    impact_df: pd.DataFrame,
) -> None:
    """Print a readable ablation study report."""
    print(f"\n{'═'*65}")
    print("  ABLATION STUDY — COVARIATE IMPACT ANALYSIS")
    print(f"{'═'*65}")

    # Overall WAPE progression
    overall = ablation_df[ablation_df["slice"] == "overall"]
    if not overall.empty:
        print(f"\n📊 Overall WAPE progression (lower is better):")
        print(f"  {'Config':<35} {'WAPE':>8}  {'MAE':>8}")
        print(f"  {'─'*55}")
        for _, row in overall.iterrows():
            label = row["config"].replace("_", " ").title()
            print(f"  {label:<35} {row['WAPE_%']:>7.1f}%  {row['MAE']:>8.0f}")

    # Sharks game breakdown — most important use case
    sharks = ablation_df[ablation_df["slice"] == "sharks_game_window"]
    if not sharks.empty:
        print(f"\n🦈 Sharks Game Window WAPE (Diridon/VTA stations):")
        for _, row in sharks.iterrows():
            label = row["config"].replace("_", " ").title()
            print(f"  {label:<35} {row['WAPE_%']:>7.1f}%")

    # Rainy day breakdown
    rainy = ablation_df[ablation_df["slice"] == "rainy_day"]
    if not rainy.empty:
        print(f"\n🌧️  Rainy Day WAPE:")
        for _, row in rainy.iterrows():
            label = row["config"].replace("_", " ").title()
            print(f"  {label:<35} {row['WAPE_%']:>7.1f}%")

    # Key impact findings
    if not impact_df.empty:
        print(f"\n🎯 Biggest covariate impacts (WAPE reduction in pp):")
        top = impact_df.nlargest(8, "WAPE_delta_pp")
        for _, row in top.iterrows():
            if row["WAPE_delta_pp"] > 0:
                print(
                    f"  +{row['added_group']:12s} on [{row['slice']:30s}]"
                    f"  −{row['WAPE_delta_pp']:.1f}pp"
                    f"  ({row['pct_improvement']:.0f}% improvement)"
                )

    print(f"\n{'═'*65}\n")


# ── Lightweight offline ablation (no re-inference needed) ─────────────────────

def offline_covariate_correlation(
    feature_store: pd.DataFrame,
    target_col: str = "ridership",
) -> pd.DataFrame:
    """
    Quick diagnostic: compute correlation of each covariate with ridership.
    Does NOT require running the model — useful for exploratory analysis.

    High correlation → likely important feature.
    Near-zero correlation → feature may not be helping.
    """
    numeric_cols = feature_store.select_dtypes(include=[np.number]).columns.tolist()
    if target_col not in numeric_cols:
        return pd.DataFrame()

    corr_rows = []
    for col in numeric_cols:
        if col == target_col:
            continue
        valid = feature_store[[col, target_col]].dropna()
        if len(valid) < 10:
            continue
        pearson  = valid[col].corr(valid[target_col])
        spearman = valid[col].rank().corr(valid[target_col].rank())
        corr_rows.append({
            "feature":  col,
            "pearson":  round(pearson,  4),
            "spearman": round(spearman, 4),
            "abs_pearson": abs(pearson),
        })

    return pd.DataFrame(corr_rows).sort_values("abs_pearson", ascending=False)


def event_day_impact_table(
    feature_store: pd.DataFrame,
    target_col: str = "ridership",
) -> pd.DataFrame:
    """
    Without running the model, show the empirical ridership lift
    on event days vs normal days. This is the signal the model should learn.

    E.g. "Diridon ridership is 2.4× higher on Sharks game nights 6–9pm"
    """
    rows = []
    for station, grp in feature_store.groupby("station_id"):
        if target_col not in grp.columns:
            continue

        if "is_game_day" in grp.columns:
            normal_median = grp[grp["is_game_day"] == False][target_col].median()
        else:
            normal_median = grp[target_col].median()

        if "is_game_day" in grp.columns:
            game_median = grp[grp["is_game_day"] == True][target_col].median()
            if normal_median and normal_median > 0:
                rows.append({
                    "station_id":       station,
                    "event_type":       "any_game_day",
                    "normal_median":    round(normal_median, 1),
                    "event_median":     round(game_median, 1),
                    "lift_ratio":       round(game_median / normal_median, 2),
                })

        if "is_sharks_game_window" in grp.columns:
            sharks_median = grp[grp["is_sharks_game_window"] == True][target_col].median()
            if normal_median and normal_median > 0:
                rows.append({
                    "station_id":       station,
                    "event_type":       "sharks_game_window",
                    "normal_median":    round(normal_median, 1),
                    "event_median":     round(sharks_median, 1),
                    "lift_ratio":       round(sharks_median / normal_median, 2),
                })

    return pd.DataFrame(rows).sort_values("lift_ratio", ascending=False)


# ── Standalone script ──────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Run ablation study")
    parser.add_argument("--model-dir",    default=str(MODEL_DIR))
    parser.add_argument("--test",         default=str(PROCESSED_DIR / "splits/test.parquet"))
    parser.add_argument("--feature-store",default=str(PROCESSED_DIR / "feature_store_enriched.parquet"))
    parser.add_argument("--offline-only", action="store_true",
                        help="Only run correlation analysis, skip model inference")
    return parser.parse_args()


def main():
    import yaml
    args = parse_args()

    with open("configs/model.yaml") as f:
        cfg = yaml.safe_load(f)

    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    # Load data
    feature_store_path = Path(args.feature_store)
    test_path = Path(args.test)

    if not feature_store_path.exists():
        log.error(f"Feature store not found: {feature_store_path}")
        return

    log.info("Loading feature store …")
    feature_store = pd.read_parquet(feature_store_path)
    feature_store["timestamp"] = pd.to_datetime(feature_store["timestamp"])

    # ── Offline diagnostics (no model needed) ─────────────────────────────────

    log.info("Computing covariate correlations …")
    corr_df = offline_covariate_correlation(feature_store)
    if not corr_df.empty:
        print(f"\n📈 Top 20 features by correlation with ridership:")
        print(corr_df.head(20).to_string(index=False))
        corr_df.to_csv(EVAL_DIR / "covariate_correlations.csv", index=False)

    log.info("Computing event-day ridership lift …")
    lift_df = event_day_impact_table(feature_store)
    if not lift_df.empty:
        print(f"\n🦈 Event-day ridership lift (top stations):")
        print(lift_df.head(15).to_string(index=False))
        lift_df.to_csv(EVAL_DIR / "event_day_lift.csv", index=False)

    if args.offline_only:
        log.info("Offline-only mode — skipping model inference ablation")
        return

    # ── Full ablation (requires trained model) ────────────────────────────────

    model_dir = Path(args.model_dir)
    if not model_dir.exists():
        log.warning(
            f"Model not found at {model_dir}. "
            "Run finetune.py first, or use --offline-only for correlation analysis."
        )
        return

    if not test_path.exists():
        log.error(f"Test split not found: {test_path}")
        return

    test_df = pd.read_parquet(test_path)
    test_df["timestamp"] = pd.to_datetime(test_df["timestamp"])

    log.info("Running full ablation study …")
    ablation_df = run_ablation(model_dir, test_df, feature_store, cfg)

    if ablation_df.empty:
        log.error("Ablation produced no results")
        return

    impact_df = summarise_impact(ablation_df)
    print_ablation_report(ablation_df, impact_df)

    # Save results
    ablation_df.to_csv(EVAL_DIR / "ablation_results.csv", index=False)
    impact_df.to_csv(EVAL_DIR / "ablation_impact.csv", index=False)
    log.info(f"Ablation results saved → {EVAL_DIR}/")


if __name__ == "__main__":
    main()
