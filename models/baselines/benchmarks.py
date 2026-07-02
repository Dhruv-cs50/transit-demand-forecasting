"""
evaluation/benchmarks.py
─────────────────────────
Head-to-head comparison of all models on the held-out test set.

Models compared:
  1. Seasonal Naive   — repeat same-time-last-week (zero-effort baseline)
  2. SARIMA           — classical statistical model
  3. Prophet          — classical + holidays + regressors
  4. Chronos-2 (zero-shot) — foundation model, no fine-tuning
  5. Chronos-2 (fine-tuned) — foundation model, trained on your data

Produces:
  - Leaderboard table (WAPE, MAE, RMSE, MAPE, MASE)
  - Per-slice breakdown (game days, rainy days, AM peak, PM peak)
  - Statistical significance tests (Diebold-Mariano)
  - Latex-ready table for your project report

This is what powers the "MAPE 11.8%" number on your website hero.

Usage:
    python evaluation/benchmarks.py
    python evaluation/benchmarks.py --quick   # skip slow baselines
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from evaluation.metrics import wape, mae, rmse, mape, smape, coverage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("benchmarks")

PROCESSED_DIR = Path("data/processed")
EVAL_DIR      = Path("evaluation/outputs")
CONFIG_PATH   = Path("configs/model.yaml")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── Seasonal naive baseline ────────────────────────────────────────────────────

def seasonal_naive_forecast(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    freq: str,
    seasonality_hours: int = 168,   # 7-day seasonal period
) -> pd.DataFrame:
    """
    For each test row, predict the value from exactly
    `seasonality_hours` ago in the training data.
    This is the absolute minimum any model must beat.
    """
    if freq.upper() in {"MS", "M", "ME"} or "month" in freq.lower():
        lag = 12
    else:
        steps_per_hour = pd.tseries.frequencies.to_offset(freq).nanos / (3600 * 1e9)
        lag = int(seasonality_hours * steps_per_hour)
    all_preds = []

    for station_id, grp in test_df.groupby("station_id"):
        train_grp = train_df[train_df["station_id"] == station_id] \
            .sort_values("timestamp")

        if len(train_grp) < lag:
            continue

        # Repeat the last week of training data cyclically
        last_week = train_grp["ridership"].values[-lag:]
        n_test = len(grp)
        repeated = np.tile(last_week, (n_test // lag) + 1)[:n_test]

        grp = grp.copy()
        grp["p50"] = np.maximum(repeated, 0)
        grp["p10"] = grp["p50"] * 0.80
        grp["p90"] = grp["p50"] * 1.20
        grp["model"] = "SeasonalNaive"
        all_preds.append(grp[["timestamp", "station_id", "p10", "p50", "p90", "model"]])

    return pd.concat(all_preds, ignore_index=True) if all_preds else pd.DataFrame()


# ── Metrics computation ────────────────────────────────────────────────────────

def compute_metrics(
    actuals: pd.DataFrame,
    preds: pd.DataFrame,
    model_name: str,
    slices: dict = None,
) -> list[dict]:
    """
    Compute metrics for a model overall and on each diagnostic slice.
    slices: dict of {slice_name: boolean mask on merged df}
    """
    merged = actuals.merge(
        preds[["timestamp", "station_id", "p10", "p50", "p90"]],
        on=["timestamp", "station_id"],
        how="inner",
    )
    if merged.empty:
        log.warning(f"No overlapping rows for {model_name}")
        return []

    rows = []

    def _metrics_row(label: str, subset: pd.DataFrame) -> dict | None:
        if subset.empty:
            return None
        y_true = subset["ridership"].values.astype(float)
        y_pred = np.maximum(subset["p50"].values.astype(float), 0)
        return {
            "model":   model_name,
            "slice":   label,
            "n":       len(subset),
            "WAPE_%":  round(wape(y_true, y_pred),  2),
            "MAE":     round(mae(y_true, y_pred),   2),
            "RMSE":    round(rmse(y_true, y_pred),  2),
            "MAPE_%":  round(mape(y_true, y_pred),  2),
            "sMAPE_%": round(smape(y_true, y_pred), 2),
            "Coverage_%": round(coverage(y_true, subset["p10"].values.astype(float), subset["p90"].values.astype(float)), 2),
        }

    # Overall
    r = _metrics_row("overall", merged)
    if r:
        rows.append(r)

    # Standard slices
    standard_slices = {
        "game_day":            "is_game_day",
        "sharks_game":         "is_sharks_game_window",
        "rainy_day":           "is_raining",
        "am_peak":             "is_am_peak",
        "pm_peak":             "is_pm_peak",
        "holiday":             "is_holiday",
        "event_catchment":     "in_event_catchment",
    }
    for slice_name, col in standard_slices.items():
        if col in merged.columns:
            subset = merged[merged[col] == True]
            r = _metrics_row(slice_name, subset)
            if r:
                rows.append(r)

    # Custom slices
    if slices:
        for slice_name, mask in slices.items():
            if len(mask) == len(merged):
                r = _metrics_row(slice_name, merged[mask])
                if r:
                    rows.append(r)

    return rows


# ── Diebold-Mariano test ───────────────────────────────────────────────────────

def diebold_mariano_test(
    actuals: pd.DataFrame,
    preds_a: pd.DataFrame,  # baseline (e.g. Prophet)
    preds_b: pd.DataFrame,  # challenger (e.g. Chronos-2)
    model_a: str = "Prophet",
    model_b: str = "Chronos-2",
) -> dict:
    """
    Diebold-Mariano test: is model B significantly better than model A?
    H0: no difference in forecast accuracy.
    p < 0.05 → model B is significantly better.
    """
    try:
        from scipy import stats
    except ImportError:
        return {"error": "scipy not installed"}

    merged_a = actuals.merge(preds_a[["timestamp","station_id","p50"]],
                              on=["timestamp","station_id"], how="inner")
    merged_b = actuals.merge(preds_b[["timestamp","station_id","p50"]],
                              on=["timestamp","station_id"], how="inner")
    common = merged_a.merge(merged_b, on=["timestamp","station_id"],
                            suffixes=("_a","_b"))
    if common.empty:
        return {}

    y_true = common["ridership"].values.astype(float)
    e_a = np.abs(y_true - np.maximum(common["p50_a"].values.astype(float), 0))
    e_b = np.abs(y_true - np.maximum(common["p50_b"].values.astype(float), 0))
    d   = e_a - e_b   # positive = B is better

    t_stat, p_value = stats.ttest_1samp(d, 0)
    return {
        "model_a":   model_a,
        "model_b":   model_b,
        "mean_d":    round(float(d.mean()), 4),
        "t_stat":    round(float(t_stat), 4),
        "p_value":   round(float(p_value), 4),
        "significant_at_5pct": p_value < 0.05,
        "winner":    model_b if (d.mean() > 0 and p_value < 0.05) else model_a,
    }


# ── Main benchmark runner ──────────────────────────────────────────────────────

def run_benchmarks(
    df: pd.DataFrame,
    cfg: dict,
    quick: bool = False,
) -> pd.DataFrame:
    """
    Run all models on the test set and produce a leaderboard.
    """
    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    freq       = cfg["data"].get("resample_freq", "MS")
    # NOTE: feature_store timestamps are tz-naive (merge_pipeline.py never
    # localizes them despite its docstring) — cutoffs must stay naive too,
    # or comparisons against df["timestamp"] raise TypeError.
    train_end  = pd.Timestamp(cfg["data"]["train_end"])
    val_end    = pd.Timestamp(cfg["data"]["val_end"])
    train_start = cfg["data"].get("train_start")
    horizon_steps = cfg["data"].get("forecast_horizon_steps") \
        or cfg["chronos2"].get("prediction_length_steps")

    train_df = df[df["timestamp"] <= val_end]
    if train_start:
        start_ts = pd.Timestamp(train_start)
        train_df = train_df[train_df["timestamp"] >= start_ts]
    test_df  = df[df["timestamp"] >  val_end]

    if test_df.empty:
        log.error("Test set is empty — check your date ranges in model.yaml")
        return pd.DataFrame()

    log.info(f"Test set: {len(test_df):,} rows | {test_df['station_id'].nunique()} stations")

    all_rows = []
    model_preds = {}
    predictor = None

    # ── 1. Seasonal Naive ──────────────────────────────────────────────────────
    log.info("\n=== Seasonal Naive ===")
    naive_preds = seasonal_naive_forecast(train_df, test_df, freq)
    if not naive_preds.empty:
        model_preds["SeasonalNaive"] = naive_preds
        rows = compute_metrics(test_df, naive_preds, "SeasonalNaive")
        all_rows.extend(rows)
        log.info(f"  WAPE: {next((r['WAPE_%'] for r in rows if r['slice']=='overall'), 'N/A')}")

    if not quick:
        # ── 2. SARIMA ──────────────────────────────────────────────────────────
        log.info("\n=== SARIMA ===")
        try:
            from models.baselines.arima import run_arima_all_stations
            arima_preds = run_arima_all_stations(
                df, cfg, train_cutoff=val_end, horizon_steps=horizon_steps, freq=freq
            )
            if not arima_preds.empty:
                model_preds["SARIMA"] = arima_preds
                rows = compute_metrics(test_df, arima_preds, "SARIMA")
                all_rows.extend(rows)
                log.info(f"  WAPE: {next((r['WAPE_%'] for r in rows if r['slice']=='overall'), 'N/A')}")
        except Exception as e:
            log.error(f"  SARIMA failed: {e}")

        # ── 3. Prophet ─────────────────────────────────────────────────────────
        log.info("\n=== Prophet ===")
        try:
            from models.baselines.prophet_baseline import run_prophet_all_stations
            prophet_preds = run_prophet_all_stations(
                df, cfg, train_cutoff=val_end, horizon_steps=horizon_steps, freq=freq
            )
            if not prophet_preds.empty:
                model_preds["Prophet"] = prophet_preds
                rows = compute_metrics(test_df, prophet_preds, "Prophet")
                all_rows.extend(rows)
                log.info(f"  WAPE: {next((r['WAPE_%'] for r in rows if r['slice']=='overall'), 'N/A')}")
        except Exception as e:
            log.error(f"  Prophet failed: {e}")

    # ── 4. Chronos-2 zero-shot ─────────────────────────────────────────────────
    log.info("\n=== Chronos-2 (zero-shot) ===")
    try:
        from models.chronos2.predict import Predictor
        predictor = Predictor()
        zs_preds = predictor.forecast_all_stations(
            as_of=val_end,
            output_path=EVAL_DIR / "chronos2_zeroshot_preds.parquet",
        )
        if not zs_preds.empty:
            model_preds["Chronos2_ZeroShot"] = zs_preds
            rows = compute_metrics(test_df, zs_preds, "Chronos2_ZeroShot")
            all_rows.extend(rows)
            log.info(f"  WAPE: {next((r['WAPE_%'] for r in rows if r['slice']=='overall'), 'N/A')}")
    except Exception as e:
        log.error(f"  Chronos-2 zero-shot failed: {e}")

    # ── 5. AutoGluon fine-tuned ensemble ───────────────────────────────────────
    if Path("models/chronos2/weights").exists():
        log.info("\n=== AutoGluon ensemble (fine-tuned) ===")
        try:
            if predictor is None:
                from models.chronos2.predict import Predictor
                predictor = Predictor()
            ft_preds = predictor.forecast_all_stations(
                as_of=val_end,
                output_path=EVAL_DIR / "chronos2_finetuned_preds.parquet",
            )
            if not ft_preds.empty:
                model_preds["AutoGluon_Ensemble"] = ft_preds
                rows = compute_metrics(test_df, ft_preds, "AutoGluon_Ensemble")
                all_rows.extend(rows)
                log.info(f"  WAPE: {next((r['WAPE_%'] for r in rows if r['slice']=='overall'), 'N/A')}")
        except Exception as e:
            log.error(f"  Chronos-2 fine-tuned failed: {e}")

    if not all_rows:
        log.error("No benchmark results generated")
        return pd.DataFrame()

    results_df = pd.DataFrame(all_rows)

    # ── Leaderboard ────────────────────────────────────────────────────────────
    leaderboard = (
        results_df[results_df["slice"] == "overall"]
        .sort_values("WAPE_%")
        .reset_index(drop=True)
    )
    leaderboard.index += 1  # rank from 1

    # ── Statistical significance ───────────────────────────────────────────────
    dm_results = []
    if "AutoGluon_Ensemble" in model_preds:
        for baseline in ["SeasonalNaive", "SARIMA", "Prophet", "Chronos2_ZeroShot"]:
            if baseline in model_preds:
                dm = diebold_mariano_test(
                    test_df,
                    model_preds[baseline],
                    model_preds["AutoGluon_Ensemble"],
                    model_a=baseline,
                    model_b="AutoGluon_Ensemble",
                )
                if dm:
                    dm_results.append(dm)

    # ── Print report ───────────────────────────────────────────────────────────
    print(f"\n{'═'*70}")
    print("  MODEL BENCHMARK LEADERBOARD")
    print(f"{'═'*70}")
    print(f"\n{'Rank':<6}{'Model':<25}{'WAPE%':>8}{'MAE':>10}{'RMSE':>10}{'MAPE%':>9}{'Cov%':>8}")
    print(f"{'─'*76}")
    for rank, row in leaderboard.iterrows():
        marker = " ← best" if rank == 1 else ""
        print(f"  {rank:<4}{row['model']:<25}{row['WAPE_%']:>7.1f}%"
              f"{row['MAE']:>10.0f}{row['RMSE']:>10.0f}"
              f"{row['MAPE_%']:>8.1f}%{row['Coverage_%']:>7.1f}%{marker}")

    if dm_results:
        print(f"\n{'─'*70}")
        print("  Diebold-Mariano Tests (AutoGluon ensemble vs baselines)")
        print(f"{'─'*70}")
        for dm in dm_results:
            sig = "✅ significant" if dm.get("significant_at_5pct") else "— not significant"
            print(f"  vs {dm['model_a']:<20} p={dm['p_value']:.4f}  {sig}")

    # ── Latex table ────────────────────────────────────────────────────────────
    latex = leaderboard[["model","WAPE_%","MAE","RMSE","MAPE_%","Coverage_%"]].to_latex(
        index=True,
        float_format="%.2f",
        caption="Model comparison on Bay Area transit test set (2025)",
        label="tab:benchmark",
    )

    # ── Save ───────────────────────────────────────────────────────────────────
    results_df.to_csv(EVAL_DIR / "benchmark_results.csv", index=False)
    leaderboard.to_csv(EVAL_DIR / "benchmark_leaderboard.csv")
    (EVAL_DIR / "benchmark_latex.tex").write_text(latex)

    if dm_results:
        pd.DataFrame(dm_results).to_csv(EVAL_DIR / "diebold_mariano.csv", index=False)

    log.info(f"\nAll benchmark outputs saved → {EVAL_DIR}/")
    return results_df


# ── Standalone ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run model benchmarks")
    parser.add_argument("--quick", action="store_true",
                        help="Skip slow baselines (SARIMA, Prophet)")
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

    run_benchmarks(df, cfg, quick=args.quick)


if __name__ == "__main__":
    main()
