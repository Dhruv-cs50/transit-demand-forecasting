"""
models/baselines/covariate_experiment.py
────────────────────────────────────────
Do weather and event covariates improve the monthly BART forecast?

Adds covariates as `exog` to the leaderboard's best model, SARIMA
(0,1,1)(0,1,1,12) per station, and changes nothing else. The plan, the arms and
the decision rule were fixed before any arm was scored:
docs/covariate-experiment-plan.md.

Each arm is scored on two windows:
  test        fit through val_end (2025-06-30), scored Jul-Dec 2025
  validation  fit through train_end (2024-12-31) on the store truncated to
              <= val_end, scored Jan-Jun 2025

and compared with the SARIMA control on the same window by a
station-clustered paired t-test (the decision) and the row-level
Diebold-Mariano test (reported only).

Writes evaluation/outputs/covariate_experiment.csv,
evaluation/outputs/covariate_experiment_stations.csv and the per-arm forecasts
under evaluation/outputs/covariate_experiment/. It never writes the
leaderboard, benchmark_results.csv or anything under website/: the export
copies every leaderboard row to the site, and an observed-weather row is not a
forecast anyone could have made at the forecast origin.

Usage (from the repo root):
    python models/baselines/covariate_experiment.py
"""

from __future__ import annotations

import copy
import hashlib
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# Run as a script, sys.path[0] is models/baselines/; make the repo root
# importable, as benchmarks.py does.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from models.baselines import benchmarks  # noqa: E402
from models.baselines.arima import run_arima_all_stations  # noqa: E402

log = logging.getLogger("covariate_experiment")

# ── Pre-registered (docs/covariate-experiment-plan.md). Do not change. ─────────

# `hours_to_event` is, despite its name, the number of events in the month
# (merge_pipeline.compute_event_features); the archive holds only Sharks home
# games.
ARMS = [
    ("SARIMA", None),  # control
    ("SARIMAX + weather (observed)", ["temp_f", "precip_mm"]),
    ("SARIMAX + Sharks games", ["hours_to_event"]),
    ("SARIMAX + weather (observed) + Sharks games", ["temp_f", "precip_mm", "hours_to_event"]),
]
CONTROL = ARMS[0][0]
ALPHA = 0.05
WINDOWS = ("test", "validation")

IMPROVES = "improves"
NO_IMPROVEMENT = "no measurable improvement"
# An arm (or its control) that was rejected, or whose paired test could not run,
# was never scored, so the rule has nothing to judge; saying "no measurable
# improvement" would read as a scored loss.
NOT_SCORED = "not scored"

# ── Outputs ────────────────────────────────────────────────────────────────────

TABLE_NAME = "covariate_experiment.csv"
STATIONS_NAME = "covariate_experiment_stations.csv"
RUNS_SUBDIR = "covariate_experiment"

# The overall-row columns of benchmarks.compute_metrics, in its order. Coverage_%
# is each model's own raw 80% band.
METRIC_COLUMNS = ["n", "WAPE_%", "MAE", "RMSE", "MAPE_%", "sMAPE_%", "Coverage_%", "MASE", "n_expected"]
COMPARISON_COLUMNS = [
    "clustered_mean_d", "clustered_t", "clustered_p",
    "stations_arm_better", "stations_control_better", "dm_p",
]
TABLE_COLUMNS = (
    ["window", "cutoff", "eval_start", "eval_end", "model", "covariates", "status"]
    + METRIC_COLUMNS + COMPARISON_COLUMNS + ["verdict"]
)
STATION_COLUMNS = ["window", "model", "station_id", "mae_control", "mae_arm", "d"]

KEYS = ["timestamp", "station_id"]


def slugify(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


assert len({slugify(label) for label, _ in ARMS}) == len(ARMS), "arm output dirs must be unique"


# ── Windows ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Window:
    name: str
    cutoff: pd.Timestamp       # last training timestamp allowed (inclusive)
    df: pd.DataFrame           # the data the models see
    cfg: dict                  # in-memory copy of the config for this window
    train: pd.DataFrame        # train_start <= ts <= cutoff
    evaluation: pd.DataFrame   # the scored rows
    horizon_steps: int
    freq: str


def _tz_matcher(df: pd.DataFrame):
    # Same convention as benchmarks.run_benchmarks: compare in df's tz space.
    aware = df["timestamp"].dt.tz is not None

    def match(value) -> pd.Timestamp:
        ts = pd.Timestamp(value)
        if aware:
            return ts.tz_localize("America/Los_Angeles") if ts.tzinfo is None \
                else ts.tz_convert("America/Los_Angeles")
        return ts.tz_localize(None) if ts.tzinfo is not None else ts

    return match


def build_window(df: pd.DataFrame, cfg: dict, name: str) -> Window:
    """
    The pre-registered windows. The config is copied and overridden in memory
    only; configs/model.yaml is never written.

      test        cutoff = val_end; data as loaded; scored on ts > cutoff
      validation  cutoff = train_end; data truncated to ts <= val_end;
                  scored on cutoff < ts <= val_end

    Raises ValueError unless every station has exactly forecast_horizon_steps
    evaluation months.
    """
    data = cfg["data"]
    match = _tz_matcher(df)
    h = int(data["forecast_horizon_steps"])
    freq = data.get("resample_freq", "MS")
    train_start = match(data["train_start"])
    val_end = match(data["val_end"])
    window_cfg = copy.deepcopy(cfg)

    if name == "test":
        cutoff = val_end
        window_df = df
        evaluation = window_df[window_df["timestamp"] > cutoff]
    elif name == "validation":
        cutoff = match(data["train_end"])
        window_df = df[df["timestamp"] <= val_end]
        evaluation = window_df[(window_df["timestamp"] > cutoff) & (window_df["timestamp"] <= val_end)]
        # benchmarks.py reads val_end as the train/test boundary.
        window_cfg["data"]["val_end"] = data["train_end"]
    else:
        raise ValueError(f"unknown window {name!r}; expected one of {WINDOWS}")

    train = window_df[(window_df["timestamp"] >= train_start) & (window_df["timestamp"] <= cutoff)]

    stations = pd.Index(window_df["station_id"].unique())
    per_station = evaluation.groupby("station_id")["timestamp"].nunique().reindex(stations, fill_value=0)
    wrong = per_station[per_station != h]
    duplicated = int(evaluation.duplicated(KEYS).sum())
    months = evaluation["timestamp"].nunique()
    if len(wrong) or duplicated or months != h or len(evaluation) != h * len(stations):
        shown = ", ".join(f"{s}={n}" for s, n in wrong.head(10).items())
        raise ValueError(
            f"{name} window: expected exactly {h} evaluation months for each of "
            f"{len(stations)} stations ({h * len(stations)} rows); got "
            f"{len(evaluation)} rows over {months} months, {duplicated} duplicate "
            f"row(s), {len(wrong)} station(s) with another count"
            + (f" ({shown})" if shown else "")
        )

    return Window(name, cutoff, window_df, window_cfg, train, evaluation, h, freq)


# ── Scoring one arm ────────────────────────────────────────────────────────────

def _rejection_reason(overall: dict) -> str:
    """Why accept_model_rows rejected this overall row (same checks, same order)."""
    n, n_expected = overall.get("n"), overall.get("n_expected")
    if n is not None and n_expected is not None and n < n_expected:
        missing = overall.get("missing_stations") or []
        shown = ", ".join(str(m) for m in missing[:10])
        more = f" (+{len(missing) - 10} more)" if len(missing) > 10 else ""
        return (f"forecast {n} of {n_expected} evaluation rows; no forecast for "
                f"{len(missing)} station(s): {shown}{more}")
    wape_pct = overall.get("WAPE_%")
    if wape_pct is None or np.isnan(wape_pct):
        return "no valid score (a forecast is missing)"
    if wape_pct > benchmarks.MAX_PLAUSIBLE_WAPE:
        return f"WAPE {wape_pct:,.1f}% exceeds {benchmarks.MAX_PLAUSIBLE_WAPE:.0f}% (fit diverged)"
    return "rejected by accept_model_rows"


def _base_row(window: Window, label: str, cols: list[str] | None) -> dict:
    row = {c: np.nan for c in TABLE_COLUMNS}
    row.update(
        window=window.name,
        cutoff=str(window.cutoff.date()),
        eval_start=str(window.evaluation["timestamp"].min().date()),
        eval_end=str(window.evaluation["timestamp"].max().date()),
        model=label,
        covariates=", ".join(cols) if cols else "none",
        status="",
        verdict="",
    )
    return row


class _ErrorRecords(logging.Handler):
    """Collects the per-station failures run_arima_all_stations logs (it logs
    and skips a failed station rather than raising)."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage().strip())

    def summary(self) -> str:
        if not self.messages:
            return ""
        # "❌ <label> failed for <station>: <reason>" -> count distinct reasons.
        reasons = pd.Series([m.split(": ", 1)[-1] for m in self.messages]).value_counts()
        shown = "; ".join(f"{n}× {reason}" for reason, n in reasons.head(2).items())
        more = f"; +{len(reasons) - 2} other reason(s)" if len(reasons) > 2 else ""
        return f" [{len(self.messages)} station fit(s) failed: {shown}{more}]"


def score_arm(window: Window, label: str, cols: list[str] | None, runs_dir: Path):
    """Fit and score one arm on one window. Returns (table row, preds or None).
    A rejected or empty arm comes back with status "rejected: ..." and NaN
    metrics; it is never dropped."""
    row = _base_row(window, label, cols)
    errors = _ErrorRecords()
    arima_log = logging.getLogger("arima_baseline")
    arima_log.addHandler(errors)
    try:
        preds = run_arima_all_stations(
            window.df,
            window.cfg,
            output_dir=runs_dir / window.name / slugify(label),
            train_cutoff=window.cutoff,
            horizon_steps=window.horizon_steps,
            freq=window.freq,
            exog_cols=cols,
            model_label=label,
        )
    finally:
        arima_log.removeHandler(errors)

    if preds is None or preds.empty:
        row["status"] = "rejected: no station produced a forecast" + errors.summary()
        log.error(f"  {label} [{window.name}] {row['status']}")
        return row, None

    raw = benchmarks.compute_metrics(window.evaluation, preds, label, train_df=window.train)
    overall = next((r for r in raw if r.get("slice") == "overall"), None)
    if overall is None:
        row["status"] = "rejected: no forecast overlaps the evaluation rows"
        log.error(f"  {label} [{window.name}] REJECTED: no forecast overlaps the evaluation rows")
        return row, None

    if not benchmarks.accept_model_rows(raw, f"{label} [{window.name}]"):
        row["n"], row["n_expected"] = overall.get("n"), overall.get("n_expected")
        row["status"] = "rejected: " + _rejection_reason(overall) + errors.summary()
        return row, None

    for key, value in overall.items():
        if key not in ("model", "slice", "missing_stations"):
            row[key] = value
    row["status"] = "ok"
    return row, preds


# ── Paired comparison with the control ─────────────────────────────────────────

def _paired(actuals: pd.DataFrame, preds_control: pd.DataFrame, preds_arm: pd.DataFrame) -> pd.DataFrame:
    sides = {
        "actuals": actuals[KEYS + ["ridership"]],
        "control": preds_control[KEYS + ["p50"]].rename(columns={"p50": "p50_control"}),
        "arm": preds_arm[KEYS + ["p50"]].rename(columns={"p50": "p50_arm"}),
    }
    for side, frame in sides.items():
        n_dup = int(frame.duplicated(KEYS).sum())
        if n_dup:
            raise ValueError(f"{side} has {n_dup} duplicate (timestamp, station_id) row(s)")

    merged = sides["actuals"]
    for side in ("control", "arm"):
        merged = merged.merge(sides[side], on=KEYS, how="outer", indicator="_pair")
        unpaired = merged["_pair"] != "both"
        if unpaired.any():
            only_left = int((merged["_pair"] == "left_only").sum())
            only_right = int((merged["_pair"] == "right_only").sum())
            raise ValueError(
                f"incomplete pairing with the {side} forecasts: {only_left} row(s) "
                f"without a {side} forecast, {only_right} {side} forecast(s) without "
                f"a matching row"
            )
        merged = merged.drop(columns="_pair")

    values = merged[["ridership", "p50_control", "p50_arm"]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"incomplete pairing: {int((~np.isfinite(values)).sum())} NaN or non-finite value(s)")

    counts = merged.groupby("station_id").size()
    if counts.nunique() != 1:
        raise ValueError(f"incomplete pairing: stations have different month counts ({counts.value_counts().to_dict()})")
    if len(counts) < 2:
        raise ValueError("the clustered test needs at least 2 stations")
    return merged


def station_clustered_test(
    actuals: pd.DataFrame,
    preds_control: pd.DataFrame,
    preds_arm: pd.DataFrame,
) -> dict:
    """
    Station-clustered paired test (the pre-registered decision test).

    e = |y - max(p50, 0)| per model; per station d_s = mean(e_control - e_arm)
    over its months; one-sample two-sided t-test of the d_s against 0.
    d_s > 0 means the arm was better at that station.

    Raises ValueError if the pairing is incomplete: the (timestamp,
    station_id) keys of the three frames differ, a key is duplicated, any
    value is NaN, or stations have different month counts.
    """
    from scipy import stats

    m = _paired(actuals, preds_control, preds_arm)
    y = m["ridership"].to_numpy(dtype=float)
    e_control = np.abs(y - np.maximum(m["p50_control"].to_numpy(dtype=float), 0))
    e_arm = np.abs(y - np.maximum(m["p50_arm"].to_numpy(dtype=float), 0))
    per_station = (
        m.assign(e_control=e_control, e_arm=e_arm, diff=e_control - e_arm)
        .groupby("station_id", sort=True)
        .agg(mae_control=("e_control", "mean"), mae_arm=("e_arm", "mean"), d=("diff", "mean"))
        .reset_index()
    )
    d = per_station["d"].to_numpy(dtype=float)
    t_stat, p_value = stats.ttest_1samp(d, 0.0)
    return {
        "n_stations": int(len(d)),
        "mean_d": float(d.mean()),
        "t": float(t_stat),
        "p": float(p_value),
        "stations_arm_better": int((d > 0).sum()),
        "stations_control_better": int((d < 0).sum()),
        "per_station": per_station,
    }


# ── Decision rule ──────────────────────────────────────────────────────────────

def _finite(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def decide_verdict(
    test_wape_arm,
    test_wape_control,
    test_p,
    test_mean_d,
    val_wape_arm,
    val_wape_control,
    alpha: float = ALPHA,
) -> str:
    """
    Pre-registered rule. "improves" only if all three hold:
      1. test WAPE of the arm < test WAPE of the control;
      2. test station-clustered p < alpha and mean_d > 0;
      3. validation WAPE of the arm < validation WAPE of the control.
    A missing or NaN input fails its condition.
    """
    v = [_finite(x) for x in (test_wape_arm, test_wape_control, test_p,
                              test_mean_d, val_wape_arm, val_wape_control)]
    t_arm, t_ctl, p, mean_d, v_arm, v_ctl = v
    c1 = t_arm is not None and t_ctl is not None and t_arm < t_ctl
    c2 = p is not None and mean_d is not None and p < alpha and mean_d > 0
    c3 = v_arm is not None and v_ctl is not None and v_arm < v_ctl
    return IMPROVES if (c1 and c2 and c3) else NO_IMPROVEMENT


# ── Run ────────────────────────────────────────────────────────────────────────

def format_console(table: pd.DataFrame) -> str:
    def num(x, fmt):
        return format(x, fmt) if pd.notna(x) else "—"

    out = [f"\n{'═' * 118}",
           "  COVARIATE EXPERIMENT — separate table, not the leaderboard (docs/covariate-experiment-plan.md)",
           f"{'═' * 118}",
           f"  {'window':<11}{'model':<46}{'n':>5}{'WAPE%':>8}{'Cov%':>7}"
           f"{'clust p':>9}{'arm>ctl':>8}{'ctl>arm':>8}{'DM p':>8}  verdict",
           f"  {'─' * 116}"]
    for _, r in table.iterrows():
        n = num(r["n"], ".0f") if r["status"] == "ok" else "—"
        out.append(
            f"  {r['window']:<11}{r['model']:<46}{n:>5}{num(r['WAPE_%'], '.2f'):>8}"
            f"{num(r['Coverage_%'], '.1f'):>7}{num(r['clustered_p'], '.4f'):>9}"
            f"{num(r['stations_arm_better'], '.0f'):>8}{num(r['stations_control_better'], '.0f'):>8}"
            f"{num(r['dm_p'], '.4f'):>8}  {r['verdict']}"
        )
        if r["status"] != "ok":
            out.append(f"  {'':<11}  └ {r['status']}")
    out.append("")
    out.append("  Coverage = each model's own raw 80% band. Decision: test WAPE below control, clustered p < 0.05")
    out.append("  with mean_d > 0, and validation WAPE below control. DM p is reported, not used to decide.")
    return "\n".join(out)


def run_experiment(df: pd.DataFrame, cfg: dict, eval_dir: Path = benchmarks.EVAL_DIR):
    """Score every arm on both windows, compare with the control, decide, and
    write the two tables under eval_dir. Returns (table, per-station table)."""
    eval_dir = Path(eval_dir)
    runs_dir = eval_dir / RUNS_SUBDIR
    rows: list[dict] = []
    station_frames: list[pd.DataFrame] = []

    for window_name in WINDOWS:
        window = build_window(df, cfg, window_name)
        log.info(
            f"\n=== {window_name} window: fit through {window.cutoff.date()}, scored "
            f"{window.evaluation['timestamp'].min().date()} .. "
            f"{window.evaluation['timestamp'].max().date()} "
            f"({len(window.evaluation)} rows, {window.evaluation['station_id'].nunique()} stations) ==="
        )
        window_rows, preds = {}, {}
        for label, cols in ARMS:
            log.info(f"\n--- {label} [{window_name}] ---")
            window_rows[label], preds[label] = score_arm(window, label, cols, runs_dir)

        control = preds[CONTROL]
        if control is None:
            log.error(f"  Control {CONTROL} was rejected on the {window_name} window; no arm can be compared")
        for label, _ in ARMS[1:]:
            row = window_rows[label]
            if control is None or preds[label] is None:
                continue
            try:
                ct = station_clustered_test(window.evaluation, control, preds[label])
            except ValueError as e:
                row["status"] = f"ok; clustered test not run: {e}"
                log.error(f"  {label} [{window_name}] clustered test not run: {e}")
            else:
                row.update(
                    clustered_mean_d=ct["mean_d"], clustered_t=ct["t"], clustered_p=ct["p"],
                    stations_arm_better=ct["stations_arm_better"],
                    stations_control_better=ct["stations_control_better"],
                )
                station_frames.append(ct["per_station"].assign(window=window_name, model=label))
            dm = benchmarks.diebold_mariano_test(
                window.evaluation, control, preds[label], model_a=CONTROL, model_b=label
            )
            row["dm_p"] = dm.get("p_value", np.nan) if dm else np.nan

        rows.extend(window_rows[label] for label, _ in ARMS)

    by_key = {(r["window"], r["model"]): r for r in rows}
    for label, _ in ARMS[1:]:
        test_row, val_row = by_key[("test", label)], by_key[("validation", label)]
        scored = [test_row, val_row, by_key[("test", CONTROL)], by_key[("validation", CONTROL)]]
        if any(r["status"] != "ok" for r in scored):
            test_row["verdict"] = NOT_SCORED
            continue
        test_row["verdict"] = decide_verdict(
            test_row["WAPE_%"], by_key[("test", CONTROL)]["WAPE_%"],
            test_row["clustered_p"], test_row["clustered_mean_d"],
            val_row["WAPE_%"], by_key[("validation", CONTROL)]["WAPE_%"],
        )

    table = pd.DataFrame(rows).reindex(columns=TABLE_COLUMNS)
    per_station = (
        pd.concat(station_frames, ignore_index=True).reindex(columns=STATION_COLUMNS)
        if station_frames else pd.DataFrame(columns=STATION_COLUMNS)
    )

    eval_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(eval_dir / TABLE_NAME, index=False)
    per_station.to_csv(eval_dir / STATIONS_NAME, index=False)
    print(format_console(table))
    log.info(f"\nExperiment table saved → {eval_dir / TABLE_NAME}")
    log.info(f"Per-station table saved → {eval_dir / STATIONS_NAME}")
    return table, per_station


def main() -> int:
    cfg = benchmarks.load_config()

    path = benchmarks.PROCESSED_DIR / "feature_store_enriched.parquet"
    if not path.exists():
        path = benchmarks.PROCESSED_DIR / "feature_store.parquet"
    if not path.exists():
        log.error("Feature store not found.")
        return 1

    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    log.info(f"Store: {path} (sha256 {hashlib.sha256(path.read_bytes()).hexdigest()})")

    table, _ = run_experiment(df, cfg)
    control_ok = (table.loc[table["model"] == CONTROL, "status"] == "ok").all()
    if not control_ok:
        log.error(f"Control {CONTROL} was rejected on at least one window; the experiment is not usable")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
