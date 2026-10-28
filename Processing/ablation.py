"""
Processing/ablation.py
───────────────────────
Offline covariate diagnostics on the enriched feature store: how strongly each
numeric covariate correlates with ridership, and the empirical ridership lift on
game days. Needs no model.

An earlier version also re-ran a fine-tuned AutoGluon predictor with covariate
groups zeroed out; that fine-tuning code never produced a result and was removed
(Sprint 8, S8-07).

Usage:
    python Processing/ablation.py
    python Processing/ablation.py --feature-store data/processed/feature_store_enriched.parquet
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ablation")

PROCESSED_DIR = Path("data/processed")
EVAL_DIR      = Path("evaluation/outputs")


# ── Offline covariate diagnostics (no model needed) ───────────────────────────

def offline_covariate_correlation(
    feature_store: pd.DataFrame,
    target_col: str = "ridership",
) -> pd.DataFrame:
    """
    Quick diagnostic: compute correlation of each covariate with ridership.
    Does NOT require running a model — useful for exploratory analysis.

    High correlation → likely important feature.
    Near-zero correlation → feature may not be helping.
    """
    # Include bool alongside np.number: pandas does not treat bool as a
    # numeric dtype, so a plain `select_dtypes(include=[np.number])` silently
    # dropped every boolean covariate (is_game_day, is_sharks_game_window,
    # is_raining, is_weekend, is_holiday, is_am_peak, is_pm_peak, is_playoff,
    # is_hub_station, ...) from this diagnostic -- exactly the event/weather
    # flag columns, and the single largest category of covariate columns.
    # `.corr()` on a bool column is well-defined (point-biserial correlation, the standard
    # way to correlate a binary flag with a continuous target), so there's no
    # reason to exclude it. Confirmed with a repro: a boolean column with a
    # real 500-unit ridership lift reported a 0.91 Pearson correlation once
    # included, versus being silently omitted from the report entirely
    # before this fix (with no error/warning -- the printed "top features"
    # table just looked complete while missing this whole class of columns).
    numeric_cols = feature_store.select_dtypes(include=[np.number, "bool"]).columns.tolist()
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
            if normal_median and normal_median > 0 and pd.notna(game_median):
                rows.append({
                    "station_id":       station,
                    "event_type":       "any_game_day",
                    "normal_median":    round(normal_median, 1),
                    "event_median":     round(game_median, 1),
                    "lift_ratio":       round(game_median / normal_median, 2),
                })

        if "is_sharks_game_window" in grp.columns:
            sharks_median = grp[grp["is_sharks_game_window"] == True][target_col].median()
            if normal_median and normal_median > 0 and pd.notna(sharks_median):
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
    parser = argparse.ArgumentParser(description="Offline covariate diagnostics")
    parser.add_argument("--feature-store", default=str(PROCESSED_DIR / "feature_store_enriched.parquet"))
    return parser.parse_args()


def main():
    args = parse_args()

    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    feature_store_path = Path(args.feature_store)
    if not feature_store_path.exists():
        log.error(f"Feature store not found: {feature_store_path}")
        return

    log.info("Loading feature store …")
    feature_store = pd.read_parquet(feature_store_path)
    feature_store["timestamp"] = pd.to_datetime(feature_store["timestamp"])

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


if __name__ == "__main__":
    main()
