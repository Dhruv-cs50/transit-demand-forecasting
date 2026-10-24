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
    "label", "description"}. `label` is the exact string benchmarks.py writes
    to the leaderboard's Interval_method column, so a published band can be
    matched to the coverage figure that scored it. `description` is one plain
    sentence for people.

    A model that is not listed, or whose method is "none", keeps its own band.
    So does a model whose method was validated for a different checkpoint
    (`validated_for`) than the one that produced the forecasts.
    """
    ccfg = cfg.get("calibration") or {}
    mcfg = (ccfg.get("models") or {}).get(model_key) or {}
    level = float(ccfg.get("level", 0.8))
    method = mcfg.get("method", "none")
    group = mcfg.get("group", "pooled")
    plan = {"model_key": model_key, "level": level}

    reason = None
    if method in (None, "none"):
        reason = mcfg.get("reason", "not validated")
    else:
        validated_for = mcfg.get("validated_for")
        if validated_for and checkpoint and checkpoint != validated_for:
            reason = f"method validated for {validated_for} only"

    if reason is not None:
        plan.update(
            calibrated=False, method="none", group=None, reason=reason,
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
    result as it does a freshly fitted one. Raises ValueError on a file this
    code did not write."""
    doc = json.loads(Path(path).read_text())
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
        "provenance": doc.get("provenance") or {},
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
    missing, unreadable, or was fitted for another method, group, level, model
    or checkpoint: a stale calibrator would publish a band nobody scored.
    """
    plan = interval_plan(model_key, cfg, checkpoint)
    if not plan["calibrated"]:
        return no_calibration(preds), plan

    if calibrator_path is None or not Path(calibrator_path).exists():
        raise CalibratorUnavailable(
            f"{model_key}: configs/model.yaml calibrates this model's band "
            f"({plan['method']}/{plan['group']}) but no saved calibrator was found"
            f"{f' at {calibrator_path}' if calibrator_path is not None else ''}; "
            f"run models/baselines/benchmarks.py to fit it"
        )
    try:
        cal = load_calibrator(calibrator_path)
    except (ValueError, KeyError, TypeError) as e:
        raise CalibratorUnavailable(f"{model_key}: unreadable calibrator {calibrator_path}: {e}") from e

    prov = cal["provenance"]
    mismatches = []
    if (cal["method"], cal["group"]) != (plan["method"], plan["group"]):
        mismatches.append(f"method {cal['method']}/{cal['group']} (config: {plan['method']}/{plan['group']})")
    if cal["level"] != plan["level"]:
        mismatches.append(f"level {cal['level']} (config: {plan['level']})")
    if prov.get("model_key") != model_key:
        mismatches.append(f"model {prov.get('model_key')!r}")
    if checkpoint is not None and prov.get("checkpoint") != checkpoint:
        mismatches.append(f"checkpoint {prov.get('checkpoint')!r} (serving: {checkpoint!r})")
    if mismatches:
        raise CalibratorUnavailable(
            f"{model_key}: saved calibrator {calibrator_path} does not match: "
            + "; ".join(mismatches)
        )

    out = apply_conformal(add_horizon(preds), cal)
    if "horizon" not in preds.columns:
        out = out.drop(columns="horizon")
    return out, {**plan, "n": cal["n"], "provenance": prov}
