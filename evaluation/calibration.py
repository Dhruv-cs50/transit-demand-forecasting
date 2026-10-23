"""
evaluation/calibration.py
─────────────────────────
Split-conformal calibration of P10/P90 forecast intervals.

The models' own bands are not usable as 80% intervals: on the 2025-H2 holdout
Prophet's P10–P90 covered 46.0% of actuals, Chronos-1's 51.0%, SARIMA's 96.7%
and the seasonal-naive ±20% band 94.3%. Split conformal fixes the width from
held-out errors instead of from each model's assumptions:

  1. Forecast a calibration window the model never trained on (for the
     leaderboard: the validation split, from a fit that ends at train_end).
  2. Score each calibration row with a conformity score s(y, forecast).
  3. Take the finite-sample (1 - alpha) quantile q of those scores.
  4. Rebuild P10/P90 on the evaluation forecasts so that s <= q is exactly the
     condition "the actual falls inside the band".

P50 is never read for writing: point forecasts, and therefore WAPE/MAE/RMSE,
are identical before and after calibration.

Methods (`method`):
  scaled         s = max((p50 - y) / (p50 - p10), (y - p50) / (p90 - p50)).
                 Stretches or shrinks the model's own half-widths by q, so the
                 model's asymmetry and horizon growth are kept.
  relative       s = |y - p50| / p50. Band p50 * (1 ± q); ignores the model's
                 own band entirely.
  asym_relative  r = (y - p50) / p50, lower and upper tails calibrated
                 separately at alpha/2 each. Band p50 * (1 + q_lo),
                 p50 * (1 + q_hi); absorbs a systematic bias.

Groups (`group`): one quantile for all rows ("pooled"), one per forecast step
("horizon", 1 = first month after the origin), or one per station ("station").

The choice of method, and the measurements behind it, are in
docs/interval-calibration.md (produced by evaluation/interval_study.py).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

METHODS = ("scaled", "relative", "asym_relative")
GROUPS = ("pooled", "horizon", "station")

_BAND_COLS = ["p10", "p50", "p90"]


def conformal_quantile(scores: np.ndarray, level: float) -> float:
    """Finite-sample split-conformal quantile: the ceil((n+1)*level)-th smallest
    score. Returns +inf when n is too small for any finite score to guarantee
    `level` coverage (ceil((n+1)*level) > n)."""
    s = np.sort(np.asarray(scores, dtype=float))
    n = len(s)
    k = int(np.ceil((n + 1) * level))
    if n == 0 or k > n:
        return float("inf")
    return float(s[k - 1])


def add_horizon(preds: pd.DataFrame) -> pd.DataFrame:
    """Add `horizon`: the 1-based forecast step of each row within its station
    (earliest forecast timestamp = 1). Every model in this repository forecasts
    one contiguous block per station from a single origin."""
    out = preds.copy()
    out["horizon"] = (
        out.groupby("station_id")["timestamp"].rank(method="dense").astype(int)
    )
    return out


def _safe_ratio(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """num / den with a zero denominator mapped to 0 (num == 0) or ±inf."""
    with np.errstate(divide="ignore", invalid="ignore"):
        r = num / den
    return np.where((den == 0) & (num == 0), 0.0, r)


def _scores(y: np.ndarray, p10: np.ndarray, p50: np.ndarray, p90: np.ndarray,
            method: str) -> np.ndarray:
    if method == "scaled":
        lower = _safe_ratio(p50 - y, p50 - p10)
        upper = _safe_ratio(y - p50, p90 - p50)
        return np.maximum(lower, upper)
    if method == "relative":
        return np.abs(_safe_ratio(y - p50, p50))
    if method == "asym_relative":
        return _safe_ratio(y - p50, p50)
    raise ValueError(f"unknown calibration method {method!r}; expected one of {METHODS}")


def _group_keys(df: pd.DataFrame, group: str) -> pd.Series:
    if group == "pooled":
        return pd.Series("all", index=df.index)
    if group == "horizon":
        return (df["horizon"] if "horizon" in df.columns else add_horizon(df)["horizon"])
    if group == "station":
        return df["station_id"]
    raise ValueError(f"unknown calibration group {group!r}; expected one of {GROUPS}")


def fit_conformal(
    cal: pd.DataFrame,
    method: str = "scaled",
    group: str = "pooled",
    level: float = 0.8,
) -> dict:
    """Fit split-conformal quantiles from calibration forecasts.

    cal: one row per (station_id, timestamp) with the actual (`ridership`) and
        the model's p10/p50/p90 for a window the model did not train on.

    A row with no actual is left out. A row whose actual is present but whose
    forecast or interval bound is missing raises ValueError: calibrating on
    only the rows a model chose to forecast would understate its error, the
    same reason the leaderboard rejects such a model outright.

    Returns {"method", "group", "level", "n", "q"}; q maps each group key to a
    float, or to a (q_lo, q_hi) pair for asym_relative.
    """
    if method not in METHODS:
        raise ValueError(f"unknown calibration method {method!r}; expected one of {METHODS}")
    if group not in GROUPS:
        raise ValueError(f"unknown calibration group {group!r}; expected one of {GROUPS}")

    df = cal[cal["ridership"].notna()]
    incomplete = df[_BAND_COLS].isna().any(axis=1)
    if incomplete.any():
        missing = sorted(df.loc[incomplete, "station_id"].unique().tolist(), key=str)
        raise ValueError(
            f"calibration window incomplete: {int(incomplete.sum())} row(s) with an "
            f"actual but no forecast or interval bound (stations: {missing[:10]})"
        )

    y = df["ridership"].to_numpy(dtype=float)
    s = _scores(y, *(df[c].to_numpy(dtype=float) for c in _BAND_COLS), method=method)
    keys = _group_keys(df, group).to_numpy()

    alpha = 1.0 - level
    q = {}
    for key in pd.unique(keys):
        sk = s[keys == key]
        if method == "asym_relative":
            # Two one-sided conformal bounds at alpha/2 each; the lower one is
            # the upper quantile of the negated scores.
            q_lo = -conformal_quantile(-sk, 1.0 - alpha / 2)
            q_hi = conformal_quantile(sk, 1.0 - alpha / 2)
            q[_plain(key)] = (q_lo, q_hi)
        else:
            q[_plain(key)] = conformal_quantile(sk, level)

    return {"method": method, "group": group, "level": level, "n": int(len(df)), "q": q}


def _plain(key):
    """numpy scalar -> Python scalar, so calibrators print and compare cleanly."""
    return key.item() if hasattr(key, "item") else key


def apply_conformal(preds: pd.DataFrame, calibrator: dict) -> pd.DataFrame:
    """Rebuild p10/p90 from a fitted calibrator. p50 is returned untouched.

    The original bounds are kept as p10_raw/p90_raw. Bounds are ordered
    (p10 <= p50 <= p90) and floored at zero, as every model's raw output is. A
    missing input bound, or a row whose group has no fitted quantile (e.g. a
    station absent from the calibration window), comes out as NaN, so the
    metrics see a missing interval rather than a silently uncalibrated one.
    """
    method, group = calibrator["method"], calibrator["group"]
    out = preds.copy()
    out["p10_raw"] = preds["p10"]
    out["p90_raw"] = preds["p90"]

    p10 = preds["p10"].to_numpy(dtype=float)
    p50 = preds["p50"].to_numpy(dtype=float)
    p90 = preds["p90"].to_numpy(dtype=float)
    keys = _group_keys(preds, group).map(_plain)

    if method == "asym_relative":
        pairs = keys.map(calibrator["q"])
        q_lo = np.array([p[0] if isinstance(p, tuple) else np.nan for p in pairs], dtype=float)
        q_hi = np.array([p[1] if isinstance(p, tuple) else np.nan for p in pairs], dtype=float)
        lo = p50 * (1 + q_lo)
        hi = p50 * (1 + q_hi)
    else:
        q = keys.map(calibrator["q"]).to_numpy(dtype=float)
        if method == "scaled":
            lw, uw = p50 - p10, p90 - p50
            # A zero half-width stays zero (avoids inf * 0 when q is infinite).
            lo = np.where(lw == 0, p50, p50 - q * lw)
            hi = np.where(uw == 0, p50, p50 + q * uw)
            # ...unless the input itself was missing.
            lo = np.where(np.isnan(lw), np.nan, lo)
            hi = np.where(np.isnan(uw), np.nan, hi)
            lo = np.where(np.isnan(q), np.nan, lo)
            hi = np.where(np.isnan(q), np.nan, hi)
        elif method == "relative":
            lo = p50 * (1 - q)
            hi = p50 * (1 + q)
        else:
            raise ValueError(f"unknown calibration method {method!r}; expected one of {METHODS}")

    # NaN-preserving ordering and floor (np.minimum/np.maximum propagate NaN).
    lo = np.maximum(np.minimum(lo, p50), 0.0)
    hi = np.maximum(hi, p50)
    # The relative methods never read p10/p90; still honour a missing input.
    lo = np.where(np.isnan(p10), np.nan, lo)
    hi = np.where(np.isnan(p90), np.nan, hi)

    out["p10"] = lo
    out["p90"] = hi
    return out


def describe(calibrator: dict) -> str:
    """One-line summary for logs, e.g. 'scaled/pooled @0.8, n=300: q=1.87'."""
    qs = calibrator["q"]
    head = f"{calibrator['method']}/{calibrator['group']} @{calibrator['level']}, n={calibrator['n']}"
    if len(qs) == 1:
        (v,) = qs.values()
        val = f"({v[0]:+.4f}, {v[1]:+.4f})" if isinstance(v, tuple) else f"{v:.4f}"
        return f"{head}: q={val}"
    vals = [v[1] - v[0] if isinstance(v, tuple) else v for v in qs.values()]
    return f"{head}: {len(qs)} groups, q range {min(vals):.4f}–{max(vals):.4f}"
