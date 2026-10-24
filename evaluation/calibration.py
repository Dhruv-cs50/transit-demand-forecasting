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
    same reason the leaderboard scores such a model NaN (and, when a point
    forecast is missing, rejects it).

    Returns {"method", "group", "level", "n", "q"}; q maps each group key to a
    float, or to a (q_lo, q_hi) pair for asym_relative.
    """
    if method not in METHODS:
        raise ValueError(f"unknown calibration method {method!r}; expected one of {METHODS}")
    if group not in GROUPS:
        raise ValueError(f"unknown calibration group {group!r}; expected one of {GROUPS}")

    # Forecast steps are counted on the full window, before rows without an
    # actual are dropped; counting afterwards would shift a station's steps.
    if group == "horizon" and "horizon" not in cal.columns:
        cal = add_horizon(cal)
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
        lo = _times(p50, 1 + q_lo)
        hi = _times(p50, 1 + q_hi)
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
            lo = _times(p50, 1 - q)
            hi = _times(p50, 1 + q)
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


def _times(p50: np.ndarray, factor: np.ndarray) -> np.ndarray:
    """p50 * factor, except that a zero P50 with an infinite factor (a group
    too small for a finite quantile) gives an unbounded side rather than the
    NaN of 0 * inf. The caller floors the lower bound at zero."""
    with np.errstate(invalid="ignore"):
        out = p50 * factor
    return np.where((p50 == 0) & np.isinf(factor), np.sign(factor) * np.inf, out)


def no_calibration(preds: pd.DataFrame) -> pd.DataFrame:
    """The model's own band, in the same shape apply_conformal returns
    (p10_raw/p90_raw alongside an unchanged p10/p90), so raw and calibrated
    coverage can be reported side by side for every model."""
    out = preds.copy()
    out["p10_raw"] = preds["p10"]
    out["p90_raw"] = preds["p90"]
    return out


# ── Calibrations that track recent errors (Sprint 5) ──────────────────────────
#
# A single-window split-conformal quantile assumes next half-year's errors look
# like last half-year's; PR #138 measured 7-12 points of coverage lost to that
# drift. The functions below draw on many forecast origins instead of one:
#
#   pool        every forecast from rolling monthly origins whose target month
#               is resolved (on or before `as_of`), each row carrying `origin`,
#               `horizon` (months origin -> target) and `age` (months target ->
#               as_of). Horizon must be explicit: dense-ranking timestamps, as
#               add_horizon does for one window, mis-groups a frame that pools
#               several origins.
#   rolling     weighted split-conformal quantile over the pool (Barber et al.
#               2023): weight 0.5**(age / half_life), the scored point weighted 1.
#   aci         adaptive conformal inference (Gibbs & Candes 2021) run over the
#               pool's monthly target batches; the final alpha sets the level.
#
# All of them return a calibrator dict that apply_conformal accepts, so P50 is
# never touched.

def months_between(start, end):
    """Calendar months from `start` to `end` (Timestamps or datetime Series):
    2024-11-30 -> 2024-12-01 is 1, 2024-12-01 -> 2024-12-31 is 0."""
    def ym(x):
        if isinstance(x, pd.Series):
            return x.dt.year * 12 + x.dt.month
        x = pd.Timestamp(x)
        return x.year * 12 + x.month
    return ym(end) - ym(start)


def with_origin_horizon(preds: pd.DataFrame, origin=None) -> pd.DataFrame:
    """Tag forecasts with their `origin` (if given) and the explicit `horizon`
    = months from origin to target."""
    out = preds.copy()
    if origin is not None:
        out["origin"] = pd.Timestamp(origin)
    if "origin" not in out.columns:
        raise ValueError("with_origin_horizon needs an origin (argument or column)")
    out["origin"] = pd.to_datetime(out["origin"])
    out["horizon"] = months_between(out["origin"], pd.to_datetime(out["timestamp"])).astype(int)
    return out


def rolling_pool(pool: pd.DataFrame, as_of) -> pd.DataFrame:
    """Rows resolved by `as_of`: origin before as_of and target month on or
    before it, with `age` = months from target to as_of. Raises if `origin` or
    `horizon` is missing, or if a horizon disagrees with its origin."""
    missing = [c for c in ("origin", "horizon") if c not in pool.columns]
    if missing:
        raise ValueError(f"a multi-origin calibration pool needs explicit {missing} column(s); "
                         f"see with_origin_horizon")
    as_of = pd.Timestamp(as_of)
    ts = pd.to_datetime(pool["timestamp"])
    origin = pd.to_datetime(pool["origin"])
    expected = months_between(origin, ts)
    bad = pool["horizon"].to_numpy() != expected.to_numpy()
    if bad.any():
        raise ValueError(f"{int(bad.sum())} pool row(s) whose horizon is not months(origin -> target)")
    keep = (origin < as_of) & (ts <= as_of)
    out = pool[keep].copy()
    out["age"] = months_between(pd.to_datetime(out["timestamp"]), as_of).astype(int)
    return out


def weighted_conformal_quantile(scores: np.ndarray, weights: np.ndarray, level: float) -> float:
    """Weighted split-conformal quantile (Barber, Candes, Ramdas & Tibshirani
    2023): the smallest score s with sum(w_i : s_i <= s) >= level * (sum(w) + 1),
    the "+ 1" being the scored point's weight. +inf when no score reaches it.
    With unit weights this is exactly conformal_quantile."""
    s = np.asarray(scores, dtype=float)
    w = np.asarray(weights, dtype=float)
    if len(s) == 0:
        return float("inf")
    if np.all(w == 1.0):
        # Same arithmetic as the unweighted quantile, so the two agree exactly.
        return conformal_quantile(s, level)
    order = np.argsort(s, kind="stable")
    s, cum = s[order], np.cumsum(w[order])
    idx = int(np.searchsorted(cum, level * (w.sum() + 1.0), side="left"))
    return float("inf") if idx >= len(s) else float(s[idx])


def _tail_quantiles(s: np.ndarray, w: np.ndarray, method: str, alphas):
    """Quantile(s) for one group. `alphas` is the miss rate to allow: a float
    for the symmetric scores, a (lower, upper) pair for asym_relative."""
    if method == "asym_relative":
        a_lo, a_hi = alphas
        return (-weighted_conformal_quantile(-s, w, 1.0 - a_lo),
                weighted_conformal_quantile(s, w, 1.0 - a_hi))
    return weighted_conformal_quantile(s, w, 1.0 - alphas)


def _default_alphas(method: str, level: float):
    alpha = 1.0 - level
    return (alpha / 2, alpha / 2) if method == "asym_relative" else alpha


def _pool_scores(df: pd.DataFrame, method: str) -> np.ndarray:
    df = df[df["ridership"].notna()]
    incomplete = df[_BAND_COLS].isna().any(axis=1)
    if incomplete.any():
        missing = sorted(df.loc[incomplete, "station_id"].unique().tolist(), key=str)
        raise ValueError(
            f"calibration pool incomplete: {int(incomplete.sum())} row(s) with an actual "
            f"but no forecast or interval bound (stations: {missing[:10]})")
    y = df["ridership"].to_numpy(dtype=float)
    return _scores(y, *(df[c].to_numpy(dtype=float) for c in _BAND_COLS), method=method)


def fit_rolling_conformal(
    pool: pd.DataFrame,
    method: str,
    group: str,
    level: float,
    as_of,
    half_life: float | None = None,
    alphas=None,
) -> dict:
    """Split-conformal quantiles from a rolling-origin pool.

    pool: forecasts from several origins with `origin` and `horizon` columns
        (with_origin_horizon) and the actual in `ridership`. Only rows resolved
        by `as_of` are used (rolling_pool).
    half_life: months; each row is weighted 0.5**(age / half_life). None gives
        equal weights, which reproduces fit_conformal on the same rows.
    alphas: override the allowed miss rate (float, or a (lower, upper) pair for
        asym_relative); used by the within-window ACI diagnostic.

    group is "pooled" or "horizon" (the explicit column, never a rank).
    """
    if method not in METHODS:
        raise ValueError(f"unknown calibration method {method!r}; expected one of {METHODS}")
    if group not in ("pooled", "horizon"):
        raise ValueError(f"rolling calibration groups are 'pooled' or 'horizon', not {group!r}")
    df = rolling_pool(pool, as_of)
    df = df[df["ridership"].notna()]
    s = _pool_scores(df, method)
    w = (np.ones(len(df)) if half_life is None
         else 0.5 ** (df["age"].to_numpy(dtype=float) / float(half_life)))
    keys = (np.full(len(df), "all", dtype=object) if group == "pooled"
            else df["horizon"].to_numpy())
    alphas = _default_alphas(method, level) if alphas is None else alphas
    q, n_by = {}, {}
    for key in pd.unique(keys):
        m = keys == key
        q[_plain(key)] = _tail_quantiles(s[m], w[m], method, alphas)
        n_by[_plain(key)] = int(m.sum())
    return {"method": method, "group": group, "level": level, "n": int(len(df)), "q": q,
            "scheme": "rolling", "half_life": half_life, "as_of": str(pd.Timestamp(as_of).date()),
            "n_by_group": n_by}


def _clip_alpha(a: float, n: int) -> float:
    """Keep the quantile finite (alpha >= 1/(n+1)) and at least the median (<= 0.5)."""
    return float(min(max(a, 1.0 / (n + 1)), 0.5))


def fit_aci_conformal(pool: pd.DataFrame, method: str, level: float, as_of,
                      gamma: float = 0.1) -> dict:
    """Adaptive conformal inference over the pool's monthly target batches.

    For each target month m after the first, in order: the band for the rows
    whose target is m uses the (unweighted) conformal quantile of the rows
    whose target is before m, at level 1 - alpha_m; err_m is that batch's miss
    rate; alpha_{m+1} = alpha_m + gamma * (target - err_m). alpha starts at
    1 - level (or (1 - level)/2 per tail for asym_relative, one alpha per tail)
    and is clipped to [1/(n+1), 0.5] whenever it sets a quantile from n
    scores, so the quantile stays finite. The returned calibrator uses the
    final alpha on the whole pool. Pooled only.
    """
    if method not in METHODS:
        raise ValueError(f"unknown calibration method {method!r}; expected one of {METHODS}")
    df = rolling_pool(pool, as_of)
    df = df[df["ridership"].notna()]
    s = _pool_scores(df, method)
    month = pd.to_datetime(df["timestamp"]).dt.to_period("M").to_numpy()
    months = sorted(pd.unique(month))
    asym = method == "asym_relative"
    target = _default_alphas(method, level)
    alpha = target
    path = []
    ones = np.ones(len(s))
    for m in months[1:]:
        prev, batch = month < m, month == m
        n = int(prev.sum())
        if asym:
            alpha = (_clip_alpha(alpha[0], n), _clip_alpha(alpha[1], n))
            q_lo, q_hi = _tail_quantiles(s[prev], ones[prev], method, alpha)
            err_lo = float(np.mean(s[batch] < q_lo))
            err_hi = float(np.mean(s[batch] > q_hi))
            path.append(alpha)
            alpha = (alpha[0] + gamma * (target[0] - err_lo),
                     alpha[1] + gamma * (target[1] - err_hi))
        else:
            alpha = _clip_alpha(alpha, n)
            q_m = _tail_quantiles(s[prev], ones[prev], method, alpha)
            err = float(np.mean(s[batch] > q_m))
            path.append(alpha)
            alpha = alpha + gamma * (target - err)
    n = len(s)
    alpha = (_clip_alpha(alpha[0], n), _clip_alpha(alpha[1], n)) if asym else _clip_alpha(alpha, n)
    path.append(alpha)
    q = _tail_quantiles(s, ones, method, alpha)
    return {"method": method, "group": "pooled", "level": level, "n": int(n), "q": {"all": q},
            "scheme": "aci", "gamma": gamma, "as_of": str(pd.Timestamp(as_of).date()),
            "alpha_path": path, "alpha_final": alpha}


def describe(calibrator: dict) -> str:
    """One-line summary for logs, e.g. 'scaled/pooled @0.8, n=300: q=1.87'."""
    qs = calibrator["q"]
    head = f"{calibrator['method']}/{calibrator['group']} @{calibrator['level']}, n={calibrator['n']}"
    if len(qs) == 1:
        (v,) = qs.values()
        val = f"({v[0]:+.4f}, {v[1]:+.4f})" if isinstance(v, tuple) else f"{v:.4f}"
        return f"{head}: q={val}"
    if calibrator["method"] == "asym_relative":
        spans = [v[1] - v[0] for v in qs.values()]
        return f"{head}: {len(qs)} groups, q_hi - q_lo range {min(spans):.4f}–{max(spans):.4f}"
    vals = list(qs.values())
    return f"{head}: {len(qs)} groups, q range {min(vals):.4f}–{max(vals):.4f}"
