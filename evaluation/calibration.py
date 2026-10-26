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

import json
import math
from pathlib import Path

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


def default_alphas(method: str, level: float):
    alpha = 1.0 - level
    return (alpha / 2, alpha / 2) if method == "asym_relative" else alpha


def _pool_scores(df: pd.DataFrame, method: str) -> np.ndarray:
    """Scores of pool rows; the caller has already dropped rows without an actual."""
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
    alphas = default_alphas(method, level) if alphas is None else alphas
    q, n_by = {}, {}
    for key in pd.unique(keys):
        m = keys == key
        q[_plain(key)] = _tail_quantiles(s[m], w[m], method, alphas)
        n_by[_plain(key)] = int(m.sum())
    return {"method": method, "group": group, "level": level, "n": int(len(df)), "q": q,
            "scheme": "rolling", "half_life": half_life, "as_of": str(pd.Timestamp(as_of).date()),
            "n_by_group": n_by, "weight_sum": float(w.sum())}


def clip_alpha(a: float, n: float) -> float:
    """Keep the quantile finite (alpha >= 1/(n+1)) and at least the median
    (<= 0.5). For a weighted quantile pass the total weight as n: the scored
    point's weight 1 then fits under level * (n + 1) <= n. A relative margin of
    1e-9 keeps float rounding in the weighted sum from tipping it to +inf."""
    return float(min(max(a, (1.0 + 1e-9) / (n + 1)), 0.5))


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
    target = default_alphas(method, level)
    alpha = target
    path = []
    ones = np.ones(len(s))
    for m in months[1:]:
        prev, batch = month < m, month == m
        n = int(prev.sum())
        if asym:
            alpha = (clip_alpha(alpha[0], n), clip_alpha(alpha[1], n))
            q_lo, q_hi = _tail_quantiles(s[prev], ones[prev], method, alpha)
            err_lo = float(np.mean(s[batch] < q_lo))
            err_hi = float(np.mean(s[batch] > q_hi))
            path.append(alpha)
            alpha = (alpha[0] + gamma * (target[0] - err_lo),
                     alpha[1] + gamma * (target[1] - err_hi))
        else:
            alpha = clip_alpha(alpha, n)
            q_m = _tail_quantiles(s[prev], ones[prev], method, alpha)
            err = float(np.mean(s[batch] > q_m))
            path.append(alpha)
            alpha = alpha + gamma * (target - err)
    n = len(s)
    alpha = (clip_alpha(alpha[0], n), clip_alpha(alpha[1], n)) if asym else clip_alpha(alpha, n)
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


# ── Which band a model gets, and serving it outside the benchmark run ─────────
#
# benchmarks.py fits each calibrator on the validation split (from a fit that
# ends at train_end) and saves it with save_calibrator. Anything that publishes
# a model's forecasts later — the website export, the API — calls serve_band,
# which applies that saved calibrator, never refits one, and says which band it
# returned. P50 is never changed.

CALIBRATOR_FORMAT = 1


class CalibratorUnavailable(RuntimeError):
    """configs/model.yaml names a calibration method for a model, but no saved
    calibrator matches it. Serving the raw band under that method's label would
    misstate the interval, so callers refuse instead (the API answers 503, the
    export writes nothing)."""


def interval_plan(model_key: str, cfg: dict, checkpoint: str | None = None) -> dict:
    """The band configs/model.yaml assigns to `model_key`.

    Returns {"model_key", "calibrated", "method", "group", "level", "reason",
    "checkpoint_mismatch", "label", "description"}. `label` is the exact
    string benchmarks.py writes to the leaderboard's Interval_method column,
    so a published band can be matched to the coverage figure that scored it.
    `description` is one plain sentence for people. `checkpoint_mismatch` is
    True only when a configured method is set aside because it was validated
    for another checkpoint.

    A model that is not listed, or whose method is "none" (or empty), keeps its
    own band; its reason is the configured one, or "not validated" when none is
    given. So does a model whose method was validated for a different
    checkpoint (`validated_for`) than the one that produced the forecasts.
    """
    ccfg = cfg.get("calibration") or {}
    mcfg = (ccfg.get("models") or {}).get(model_key) or {}
    level = float(ccfg.get("level", 0.8))
    method = mcfg.get("method", "none")
    group = mcfg.get("group", "pooled")
    plan = {"model_key": model_key, "level": level}

    # Raw or calibrated is decided here, from the method and the checkpoint
    # alone; the reason text only labels a raw band. (Deciding from the reason
    # turned `reason:` left blank in the YAML into "calibrated with method
    # none".)
    no_method = method in (None, "none")
    validated_for = mcfg.get("validated_for")
    checkpoint_mismatch = bool(
        not no_method and validated_for and checkpoint and checkpoint != validated_for
    )

    if no_method or checkpoint_mismatch:
        if checkpoint_mismatch:
            reason = f"method validated for {validated_for} only"
        else:
            reason = mcfg.get("reason")
            if reason is None or (isinstance(reason, str) and not reason.strip()):
                reason = "not validated"
        plan.update(
            calibrated=False, method="none", group=None, reason=reason,
            checkpoint_mismatch=checkpoint_mismatch,
            label=f"raw: {reason}",
            description=(f"{model_key}'s own P10/P90 band (nominal {level:.0%}), "
                         f"not calibrated: {reason}."),
        )
        return plan

    # An unknown method is not rejected here: fit_conformal and load_calibrator
    # reject it, which benchmarks.py reports as a FAILED calibration and
    # serve_band as CalibratorUnavailable.
    plan.update(
        calibrated=True, method=method, group=group, reason=None,
        checkpoint_mismatch=False,
        label=f"split-conformal {method}/{group}, fit on validation",
        description=(f"Split-conformal P10/P90 band ({method}/{group}, nominal "
                     f"{level:.0%}), fit on {model_key}'s validation-split errors."),
    )
    return plan


def _encode_float(v: float):
    """JSON has no inf/nan; write them as strings so the file stays strict JSON."""
    v = float(v)
    return v if math.isfinite(v) else str(v)


def _decode_float(v) -> float:
    return float(v)


def save_calibrator(calibrator: dict, path, **provenance) -> None:
    """Write a fitted calibrator to `path` as strict JSON.

    q is stored as a list of [key, value] pairs, not a JSON object: an object
    would turn horizon keys (ints) into strings, and apply_conformal would
    then find no quantile for any row. Asymmetric quantiles are stored as
    [q_lo, q_hi] and read back as tuples. `provenance` (model_key, checkpoint,
    calibration window, ...) is stored alongside and checked by serve_band.
    """
    q = []
    for key, val in calibrator["q"].items():
        if isinstance(key, bool) or not isinstance(key, (int, str)):
            raise TypeError(f"calibrator group key {key!r} is not an int or str")
        q.append([key, [_encode_float(x) for x in val] if isinstance(val, tuple) else _encode_float(val)])
    doc = {
        "format": CALIBRATOR_FORMAT,
        "method": calibrator["method"],
        "group": calibrator["group"],
        "level": float(calibrator["level"]),
        "n": int(calibrator["n"]),
        "q": q,
        "provenance": provenance,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n")


def load_calibrator(path) -> dict:
    """Read a calibrator written by save_calibrator; apply_conformal accepts the
    result as it does a freshly fitted one.

    Raises OSError when the file cannot be read, and ValueError (including
    json.JSONDecodeError) on a document this code did not write. A malformed
    `q` or `level` can also raise KeyError or TypeError; serve_band turns all
    of these into CalibratorUnavailable."""
    doc = json.loads(Path(path).read_text())
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: calibrator is a JSON {type(doc).__name__}, not an object")
    provenance = doc.get("provenance")
    if provenance is None:
        provenance = {}
    elif not isinstance(provenance, dict):
        raise ValueError(f"{path}: calibrator provenance is a JSON {type(provenance).__name__}, not an object")
    if doc.get("format") != CALIBRATOR_FORMAT:
        raise ValueError(f"{path}: calibrator format {doc.get('format')!r}, expected {CALIBRATOR_FORMAT}")
    method, group = doc.get("method"), doc.get("group")
    if method not in METHODS or group not in GROUPS:
        raise ValueError(f"{path}: unknown calibration method/group {method!r}/{group!r}")
    q = {}
    for key, val in doc["q"]:
        if isinstance(val, list):
            if method != "asym_relative" or len(val) != 2:
                raise ValueError(f"{path}: quantile pair for group {key!r} under method {method!r}")
            q[key] = (_decode_float(val[0]), _decode_float(val[1]))
        else:
            if method == "asym_relative":
                raise ValueError(f"{path}: asym_relative needs a (q_lo, q_hi) pair for group {key!r}")
            q[key] = _decode_float(val)
    return {
        "method": method,
        "group": group,
        "level": float(doc["level"]),
        "n": int(doc["n"]),
        "q": q,
        "provenance": provenance,
    }


def serve_band(
    preds: pd.DataFrame,
    model_key: str,
    cfg: dict,
    calibrator_path=None,
    checkpoint: str | None = None,
) -> tuple[pd.DataFrame, dict]:
    """The P10/P90 band configs/model.yaml assigns to `model_key`, applied to
    forecasts made outside the benchmark run.

    preds: one row per (station_id, timestamp) with p10/p50/p90, one
        contiguous forecast block per station (so `horizon` can be counted).
    calibrator_path: the file benchmarks.py saved for this model. Not read
        when the model keeps its own band.

    Returns (preds, plan). preds carries p10_raw/p90_raw (the model's own
    bounds) beside p10/p90 (the band served); P50 is untouched. plan is
    interval_plan's dict, plus "n" and "provenance" from the calibrator when
    one was applied.

    Raises CalibratorUnavailable when a method is configured but the file is
    missing, unreadable, or was fitted for another method, group, level,
    model, checkpoint or training split (provenance `fit_end` other than the
    config's data.train_end; checked only when the config names a train_end):
    a stale calibrator would publish a band nobody scored.
    """
    plan = interval_plan(model_key, cfg, checkpoint)
    if not plan["calibrated"]:
        return no_calibration(preds), plan

    try:
        present = calibrator_path is not None and Path(calibrator_path).exists()
    except OSError as e:  # e.g. an unsearchable parent directory on Python <= 3.11
        raise CalibratorUnavailable(f"{model_key}: cannot read calibrator {calibrator_path}: {e!r}") from e
    if not present:
        raise CalibratorUnavailable(
            f"{model_key}: configs/model.yaml calibrates this model's band "
            f"({plan['method']}/{plan['group']}) but no saved calibrator was found"
            f"{f' at {calibrator_path}' if calibrator_path is not None else ''}; "
            f"run models/baselines/benchmarks.py to fit it"
        )
    try:
        cal = load_calibrator(calibrator_path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        raise CalibratorUnavailable(f"{model_key}: unreadable calibrator {calibrator_path}: {e!r}") from e

    prov = cal["provenance"]
    train_end = (cfg.get("data") or {}).get("train_end")
    mismatches = []
    if (cal["method"], cal["group"]) != (plan["method"], plan["group"]):
        mismatches.append(f"method {cal['method']}/{cal['group']} (config: {plan['method']}/{plan['group']})")
    if cal["level"] != plan["level"]:
        mismatches.append(f"level {cal['level']} (config: {plan['level']})")
    if prov.get("model_key") != model_key:
        mismatches.append(f"model {prov.get('model_key')!r}")
    if checkpoint is not None and prov.get("checkpoint") != checkpoint:
        mismatches.append(f"checkpoint {prov.get('checkpoint')!r} (serving: {checkpoint!r})")
    # A calibrator from a run on other splits (or saved with no fit_end at
    # all) was not fitted on this config's validation window.
    if train_end is not None and ("fit_end" not in prov or str(prov["fit_end"]) != str(train_end)):
        mismatches.append(f"fit_end {prov.get('fit_end')!r} (config train_end: {str(train_end)!r})")
    if mismatches:
        raise CalibratorUnavailable(
            f"{model_key}: saved calibrator {calibrator_path} does not match: "
            + "; ".join(mismatches)
        )

    out = apply_conformal(add_horizon(preds), cal)
    if "horizon" not in preds.columns:
        out = out.drop(columns="horizon")
    return out, {**plan, "n": cal["n"], "provenance": prov}
