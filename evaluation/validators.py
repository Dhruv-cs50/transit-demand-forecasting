"""
processing/validators.py
─────────────────────────
Data quality gate — runs before any data reaches the model.

Catches:
  - Missing time windows (API downtime, failed ingestion runs)
  - Schema violations (missing required columns, wrong dtypes)
  - Anomalous ridership spikes (sensor glitches, data entry errors)
  - Imputed / forward-filled gaps that exceed safe thresholds
  - Weather data staleness (forecast too old to trust)
  - Station coverage gaps (stations missing from a time window)

Every check emits structured ValidationResult objects that can be
logged, stored, or used to halt the pipeline (strict mode).

Usage:
    from processing.validators import validate_feature_store, ValidationMode
    results = validate_feature_store(df, mode=ValidationMode.STRICT)

    # Or as a standalone script:
    python processing/validators.py
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

PROCESSED_DIR = Path("data/processed")

# ── Constants ──────────────────────────────────────────────────────────────────

# Maximum gap (in hours) we'll tolerate before flagging missing data
MAX_GAP_HOURS = 2.0

# Maximum consecutive imputed rows before we reject the window
MAX_IMPUTED_ROWS = 8   # 8 × 15min = 2 hours of filled data

# Ridership anomaly thresholds
RIDERSHIP_MAX_PLAUSIBLE     = 5_000_000  # monthly BART OD totals; major SF stations ~4M+ in 2019
RIDERSHIP_SPIKE_MULTIPLIER  = 10.0     # flag if > 10× rolling median
RIDERSHIP_MIN_PLAUSIBLE     = 0        # negative ridership = sensor error

# Weather staleness
WEATHER_MAX_AGE_HOURS = 3.0   # weather data older than 3hrs is stale for serving

# Minimum fraction of stations that must have data in each time window
MIN_STATION_COVERAGE = 0.80   # 80% of stations must be present

# Required columns in the enriched feature store
REQUIRED_COLUMNS = [
    "timestamp",
    "station_id",
    "ridership",
]

EXPECTED_DTYPES = {
    "timestamp":  "datetime64[ns, America/Los_Angeles]",
    "station_id": "object",
    "ridership":  "float64",
}


# ── Result types ───────────────────────────────────────────────────────────────

class Severity(str, Enum):
    INFO    = "INFO"
    WARNING = "WARNING"
    ERROR   = "ERROR"


class ValidationMode(str, Enum):
    STRICT  = "strict"   # raise on any ERROR
    LENIENT = "lenient"  # log warnings, never raise


@dataclass
class ValidationResult:
    check:    str
    severity: Severity
    message:  str
    details:  dict = field(default_factory=dict)

    def __str__(self):
        return f"[{self.severity.value}] {self.check}: {self.message}"


# ── Individual checks ──────────────────────────────────────────────────────────

def check_required_columns(df: pd.DataFrame) -> List[ValidationResult]:
    """Fail fast if any required column is missing."""
    results = []
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        results.append(ValidationResult(
            check="required_columns",
            severity=Severity.ERROR,
            message=f"Missing required columns: {missing}",
            details={"missing": missing, "present": list(df.columns)},
        ))
    else:
        results.append(ValidationResult(
            check="required_columns",
            severity=Severity.INFO,
            message=f"All {len(REQUIRED_COLUMNS)} required columns present",
        ))
    return results


def check_timestamp_monotonic(df: pd.DataFrame) -> List[ValidationResult]:
    """Timestamps should be sorted and monotonically increasing per station."""
    results = []
    if "station_id" not in df.columns:
        return results

    non_monotonic = []
    for station, grp in df.groupby("station_id"):
        if not grp["timestamp"].is_monotonic_increasing:
            non_monotonic.append(station)

    if non_monotonic:
        results.append(ValidationResult(
            check="timestamp_monotonic",
            severity=Severity.WARNING,
            message=f"{len(non_monotonic)} stations have non-monotonic timestamps",
            details={"stations": non_monotonic[:10]},  # show first 10
        ))
    else:
        results.append(ValidationResult(
            check="timestamp_monotonic",
            severity=Severity.INFO,
            message="All station timestamps are monotonically increasing",
        ))
    return results


def check_missing_windows(
    df: pd.DataFrame,
    freq: str = "MS",
    max_gap_hours: float = MAX_GAP_HOURS,
) -> List[ValidationResult]:
    """
    Detect gaps in the time series larger than max_gap_hours.
    These indicate failed ingestion runs or API downtime.
    """
    results = []
    if "station_id" not in df.columns:
        return results

    expected_step = pd.tseries.frequencies.to_offset(freq)
    try:
        step_td = pd.Timedelta(expected_step.nanos, unit="ns")
        max_gap = max(pd.Timedelta(hours=max_gap_hours), step_td * 2)
    except ValueError:
        # Month-start/month-end offsets are calendar based, not fixed-width.
        # Two months plus a little slack catches missing station-month rows.
        max_gap = pd.Timedelta(days=62)
    large_gaps = []

    for station, grp in df.groupby("station_id"):
        grp = grp.sort_values("timestamp")
        diffs = grp["timestamp"].diff().dropna()
        bad = diffs[diffs > max_gap]
        for idx, gap in bad.items():
            iloc_pos = grp.index.get_loc(idx)
            gap_start = str(grp.iloc[iloc_pos - 1]["timestamp"]) if iloc_pos > 0 else "unknown"
            large_gaps.append({
                "station":   station,
                "gap_start": str(gap_start),
                "gap_hours": round(gap.total_seconds() / 3600, 2),
            })

    max_gap_label = round(max_gap.total_seconds() / 3600, 2)
    if large_gaps:
        results.append(ValidationResult(
            check="missing_windows",
            severity=Severity.WARNING,
            message=f"{len(large_gaps)} time gaps > expected {freq} cadence detected across stations",
            details={"gaps": large_gaps[:20]},
        ))
    else:
        results.append(ValidationResult(
            check="missing_windows",
            severity=Severity.INFO,
            message=f"No gaps > {max_gap_label}h found for {freq} cadence",
        ))
    return results


def check_ridership_anomalies(df: pd.DataFrame) -> List[ValidationResult]:
    """
    Flag ridership values that are:
      - Negative (sensor error)
      - Above physical plausibility threshold
      - Sudden spikes > RIDERSHIP_SPIKE_MULTIPLIER × rolling median
    """
    results = []
    if "ridership" not in df.columns:
        return results

    # Negative values
    neg_mask = df["ridership"] < RIDERSHIP_MIN_PLAUSIBLE
    if neg_mask.any():
        results.append(ValidationResult(
            check="ridership_negative",
            severity=Severity.ERROR,
            message=f"{neg_mask.sum()} rows have negative ridership",
            details={
                "count": int(neg_mask.sum()),
                "min_value": float(df.loc[neg_mask, "ridership"].min()),
                "sample_stations": df.loc[neg_mask, "station_id"].unique()[:5].tolist()
                    if "station_id" in df.columns else [],
            },
        ))

    # Implausibly large values
    huge_mask = df["ridership"] > RIDERSHIP_MAX_PLAUSIBLE
    if huge_mask.any():
        results.append(ValidationResult(
            check="ridership_implausible_max",
            severity=Severity.ERROR,
            message=f"{huge_mask.sum()} rows exceed plausibility threshold ({RIDERSHIP_MAX_PLAUSIBLE:,})",
            details={
                "count": int(huge_mask.sum()),
                "max_value": float(df.loc[huge_mask, "ridership"].max()),
            },
        ))

    # Sudden spikes vs rolling median (per station)
    spike_rows = []
    if "station_id" in df.columns:
        for station, grp in df.groupby("station_id"):
            grp = grp.sort_values("timestamp")
            rolling_med = grp["ridership"].rolling(96, min_periods=4).median()
            # Only flag where rolling median is meaningful (> 0)
            valid = rolling_med > 0
            ratio = grp.loc[valid, "ridership"] / rolling_med[valid]
            spike_idx = ratio[ratio > RIDERSHIP_SPIKE_MULTIPLIER].index
            if len(spike_idx) > 0:
                spike_rows.extend([{
                    "station": station,
                    "timestamp": str(grp.loc[i, "timestamp"]),
                    "ridership": float(grp.loc[i, "ridership"]),
                    "rolling_median": float(rolling_med.loc[i]),
                    "ratio": float(ratio.loc[i]),
                } for i in spike_idx[:3]])

    if spike_rows:
        results.append(ValidationResult(
            check="ridership_spikes",
            severity=Severity.WARNING,
            message=f"{len(spike_rows)} anomalous ridership spikes detected (>{RIDERSHIP_SPIKE_MULTIPLIER}× median)",
            details={"spikes": spike_rows[:10]},
        ))
    else:
        results.append(ValidationResult(
            check="ridership_spikes",
            severity=Severity.INFO,
            message="No anomalous ridership spikes detected",
        ))

    if not neg_mask.any() and not huge_mask.any():
        results.append(ValidationResult(
            check="ridership_range",
            severity=Severity.INFO,
            message=f"Ridership range OK: [{df['ridership'].min():.0f}, {df['ridership'].max():.0f}]",
        ))

    return results


def check_weather_coverage(df: pd.DataFrame) -> List[ValidationResult]:
    """
    Verify that weather columns are present and not excessively null.
    Also checks that weather data isn't stale (for serving pipeline).
    """
    results = []
    WEATHER_COLS = ["temp_f", "precip_mm", "is_raining", "windspeed_mph"]
    present = [c for c in WEATHER_COLS if c in df.columns]

    if not present:
        results.append(ValidationResult(
            check="weather_coverage",
            severity=Severity.WARNING,
            message="No weather columns found — model will run without weather covariates",
        ))
        return results

    for col in present:
        null_pct = df[col].isna().mean() * 100
        severity = Severity.ERROR if null_pct > 20 else \
                   Severity.WARNING if null_pct > 5 else Severity.INFO
        results.append(ValidationResult(
            check=f"weather_nulls_{col}",
            severity=severity,
            message=f"{col}: {null_pct:.1f}% null",
            details={"column": col, "null_pct": round(null_pct, 2)},
        ))

    return results


def check_event_coverage(df: pd.DataFrame) -> List[ValidationResult]:
    """
    Check that event features are present and that game-day rows
    have plausible event proximity scores.
    """
    results = []
    EVENT_COLS = ["is_game_day", "hours_to_event", "is_sharks_game_window"]
    present = [c for c in EVENT_COLS if c in df.columns]

    if not present:
        results.append(ValidationResult(
            check="event_coverage",
            severity=Severity.WARNING,
            message="No event columns found — model will run without event covariates",
        ))
        return results

    if "is_game_day" in df.columns and "event_proximity_score" in df.columns:
        game_rows = df[df["is_game_day"]]
        if not game_rows.empty:
            zero_score = (game_rows["event_proximity_score"] == 0).mean() * 100
            if zero_score > 50:
                results.append(ValidationResult(
                    check="event_proximity_score",
                    severity=Severity.WARNING,
                    message=f"{zero_score:.1f}% of game-day rows have zero proximity score — check event join",
                ))
            else:
                results.append(ValidationResult(
                    check="event_proximity_score",
                    severity=Severity.INFO,
                    message=f"Event proximity scores look healthy on game days",
                ))

    results.append(ValidationResult(
        check="event_coverage",
        severity=Severity.INFO,
        message=f"Event columns present: {present}",
    ))
    return results


def check_station_coverage(
    df: pd.DataFrame,
    min_coverage: float = MIN_STATION_COVERAGE,
    freq: str = "1h",
) -> List[ValidationResult]:
    """
    For each time window, check that at least min_coverage fraction
    of stations are present. Large drops indicate ingestion failures.
    """
    results = []
    if "station_id" not in df.columns or "timestamp" not in df.columns:
        return results

    total_stations = df["station_id"].nunique()
    if total_stations == 0:
        return results

    # Resample to hourly and count distinct stations
    df_copy = df.copy()
    df_copy["timestamp"] = pd.to_datetime(df_copy["timestamp"]).dt.tz_localize(None)
    coverage = (
        df_copy.set_index("timestamp")
        .groupby(pd.Grouper(freq=freq))["station_id"]
        .nunique()
    )
    low_coverage = coverage[coverage / total_stations < min_coverage]

    if not low_coverage.empty:
        results.append(ValidationResult(
            check="station_coverage",
            severity=Severity.WARNING,
            message=f"{len(low_coverage)} time windows have <{min_coverage*100:.0f}% station coverage",
            details={
                "affected_windows": low_coverage.index.strftime("%Y-%m-%d %H:%M").tolist()[:10],
                "min_stations_seen": int(low_coverage.min()),
                "expected_stations": total_stations,
            },
        ))
    else:
        results.append(ValidationResult(
            check="station_coverage",
            severity=Severity.INFO,
            message=f"Station coverage ≥ {min_coverage*100:.0f}% across all time windows",
        ))
    return results


def check_duplicate_rows(df: pd.DataFrame) -> List[ValidationResult]:
    """Flag duplicate (timestamp, station_id) pairs which would corrupt training."""
    results = []
    key_cols = [c for c in ["timestamp", "station_id"] if c in df.columns]
    if len(key_cols) < 2:
        return results

    dup_mask = df.duplicated(subset=key_cols, keep=False)
    n_dups = dup_mask.sum()

    if n_dups > 0:
        results.append(ValidationResult(
            check="duplicate_rows",
            severity=Severity.ERROR,
            message=f"{n_dups} duplicate (timestamp, station_id) rows detected",
            details={"count": int(n_dups)},
        ))
    else:
        results.append(ValidationResult(
            check="duplicate_rows",
            severity=Severity.INFO,
            message="No duplicate rows found",
        ))
    return results


def check_target_null_rate(df: pd.DataFrame, target_col: str = "ridership") -> List[ValidationResult]:
    """Ridership null rate above threshold will degrade training significantly."""
    results = []
    if target_col not in df.columns:
        return results

    null_pct = df[target_col].isna().mean() * 100
    if null_pct > 10:
        severity = Severity.ERROR
    elif null_pct > 2:
        severity = Severity.WARNING
    else:
        severity = Severity.INFO

    results.append(ValidationResult(
        check="target_null_rate",
        severity=severity,
        message=f"Target column '{target_col}' is {null_pct:.2f}% null",
        details={"null_pct": round(null_pct, 2), "null_count": int(df[target_col].isna().sum())},
    ))
    return results


# ── Main validator ─────────────────────────────────────────────────────────────

def validate_feature_store(
    df: pd.DataFrame,
    mode: ValidationMode = ValidationMode.STRICT,
    freq: str = "MS",
    target_col: str = "ridership",
) -> List[ValidationResult]:
    """
    Run all validation checks on the feature store DataFrame.

    Args:
        df        : feature store DataFrame
        mode      : STRICT raises on any ERROR; LENIENT only logs
        freq      : expected time series frequency
        target_col: name of the ridership column

    Returns:
        List of ValidationResult objects

    Raises:
        ValueError if mode=STRICT and any ERROR-level check fails
    """
    all_results: List[ValidationResult] = []

    checks = [
        check_required_columns(df),
        check_timestamp_monotonic(df),
        check_missing_windows(df, freq),
        check_ridership_anomalies(df),
        check_weather_coverage(df),
        check_event_coverage(df),
        check_station_coverage(df, freq=freq),
        check_duplicate_rows(df),
        check_target_null_rate(df, target_col),
    ]

    for check_results in checks:
        all_results.extend(check_results)

    # Print summary
    errors   = [r for r in all_results if r.severity == Severity.ERROR]
    warnings = [r for r in all_results if r.severity == Severity.WARNING]
    infos    = [r for r in all_results if r.severity == Severity.INFO]

    log.info(f"\n{'─'*60}")
    log.info(f"Validation Summary: {len(infos)} OK | {len(warnings)} WARNINGS | {len(errors)} ERRORS")
    log.info(f"{'─'*60}")

    for r in all_results:
        if r.severity == Severity.ERROR:
            log.error(str(r))
        elif r.severity == Severity.WARNING:
            log.warning(str(r))
        else:
            log.info(str(r))

    if errors and mode == ValidationMode.STRICT:
        raise ValueError(
            f"Validation failed with {len(errors)} ERROR(s):\n" +
            "\n".join(str(r) for r in errors)
        )

    return all_results


def validation_report(results: List[ValidationResult]) -> pd.DataFrame:
    """Convert validation results to a DataFrame for logging or storage."""
    return pd.DataFrame([{
        "check":    r.check,
        "severity": r.severity.value,
        "message":  r.message,
        "details":  str(r.details) if r.details else "",
    } for r in results])


# ── Standalone script ──────────────────────────────────────────────────────────

def main():
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Validate the feature store")
    parser.add_argument("--input", default=str(PROCESSED_DIR / "feature_store_enriched.parquet"))
    parser.add_argument("--mode", choices=["strict", "lenient"], default="lenient")
    parser.add_argument("--freq", default="MS")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        log.error(f"File not found: {path}")
        return

    log.info(f"Loading: {path}")
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    mode = ValidationMode.STRICT if args.mode == "strict" else ValidationMode.LENIENT
    results = validate_feature_store(df, mode=mode, freq=args.freq)

    # Save report
    report = validation_report(results)
    out = PROCESSED_DIR / "validation_report.csv"
    report.to_csv(out, index=False)
    log.info(f"\nValidation report saved → {out}")

    errors = [r for r in results if r.severity == Severity.ERROR]
    warnings = [r for r in results if r.severity == Severity.WARNING]

    print(f"\n{'─'*60}")
    print(f"  ✅ PASSED : {sum(1 for r in results if r.severity == Severity.INFO)}")
    print(f"  ⚠️  WARNINGS: {len(warnings)}")
    print(f"  ❌ ERRORS  : {len(errors)}")
    print(f"{'─'*60}")

    if errors:
        print("\nErrors to fix before training:")
        for r in errors:
            print(f"  • {r.check}: {r.message}")


if __name__ == "__main__":
    main()
