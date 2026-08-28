"""
Processing/feature_engineering.py
───────────────────────────────────
Transforms the raw merged dataset into a rich, model-ready feature matrix.

Every function here encodes domain knowledge about Bay Area transit behaviour:
  - HOW rain affects ridership (nonlinear — light drizzle barely matters)
  - WHEN Sharks games drive Diridon/VTA spikes (2–3 hrs before tip-off)
  - WHICH time windows are peak commute vs dead hours
  - HOW far in advance a scheduled event is "visible" to the model

The output of this file feeds directly into Chronos-2 as:
  - Past covariates  : things we know happened (historical weather, past games)
  - Future covariates: things we already know will happen (forecast, schedule)
  - Static features  : things that never change per station (mode, location)

Usage:
    from Processing.feature_engineering import build_features
    df = build_features(raw_df)

    # Or as a standalone script:
    python Processing/feature_engineering.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

log = logging.getLogger(__name__)

PROCESSED_DIR = Path("data/processed")

# ── Constants ──────────────────────────────────────────────────────────────────

# Precipitation thresholds (mm per hour) for bucketing
PRECIP_LIGHT  = 2.5    # < 2.5 mm/hr  → barely noticeable
PRECIP_MOD    = 7.6    # 2.5–7.6 mm/hr → moderate — people avoid buses
PRECIP_HEAVY  = 15.0   # > 15.0 mm/hr  → heavy — major ridership impact

# Event proximity windows
EVENT_APPROACH_HOURS   = 3.0   # ridership starts rising 3 hrs before event
EVENT_DEPARTURE_HOURS  = 1.5   # ridership spikes for ~1.5 hrs after event ends

# San Jose Diridon station coords — used for proximity-weighted event features
DIRIDON_LAT, DIRIDON_LNG = 37.3294, -121.9022

# Federal holidays; avoids an extra runtime dependency for the pipeline.
CA_HOLIDAYS = set(
    USFederalHolidayCalendar()
    .holidays(start="2019-01-01", end="2030-12-31")
    .date
)


# ── Time features ──────────────────────────────────────────────────────────────

def add_time_features(df: pd.DataFrame, ts_col: str = "timestamp") -> pd.DataFrame:
    """
    Cyclically encode time features so the model understands that
    hour 23 is close to hour 0 (not far from it as raw integers suggest).

    sin/cos encoding preserves circular continuity:
        hour_sin = sin(2π × hour / 24)
        hour_cos = cos(2π × hour / 24)
    """
    ts = df[ts_col]

    # Raw time components
    df["hour_of_day"]  = ts.dt.hour
    df["day_of_week"]  = ts.dt.dayofweek        # 0=Mon, 6=Sun
    df["month"]        = ts.dt.month
    df["week_of_year"] = ts.dt.isocalendar().week.astype(int)
    df["quarter"]      = ts.dt.quarter
    df["year"]         = ts.dt.year

    # Cyclic encodings — critical for Transformer-based models
    df["hour_sin"]    = np.sin(2 * np.pi * df["hour_of_day"] / 24)
    df["hour_cos"]    = np.cos(2 * np.pi * df["hour_of_day"] / 24)
    df["dow_sin"]     = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["dow_cos"]     = np.cos(2 * np.pi * df["day_of_week"] / 7)
    df["month_sin"]   = np.sin(2 * np.pi * (df["month"] - 1) / 12)
    df["month_cos"]   = np.cos(2 * np.pi * (df["month"] - 1) / 12)

    # Binary convenience flags
    df["is_weekend"]     = df["day_of_week"] >= 5
    df["is_monday"]      = df["day_of_week"] == 0   # Mondays often anomalous post-weekend
    df["is_friday"]      = df["day_of_week"] == 4   # Fridays have early PM peak

    # Commute windows (Bay Area-specific timing) — only meaningful when
    # timestamps actually carry sub-daily resolution. This pipeline runs at
    # monthly cadence (every timestamp at midnight), where these would be
    # constant dead signals (is_late_night permanently True, the rest always
    # False) fed straight into training. merge_pipeline.py's calendar
    # features already guard this the same way; this is the same function
    # re-run standalone by Processing/feature_engineering.py's own __main__,
    # which was overwriting the guarded columns with the unguarded ones.
    if ts.dt.hour.nunique() > 1:
        df["is_am_peak"]     = df["hour_of_day"].between(7, 9)    # 7–9am
        df["is_pm_peak"]     = df["hour_of_day"].between(16, 19)  # 4–7pm
        df["is_midday"]      = df["hour_of_day"].between(10, 15)
        df["is_late_night"]  = (df["hour_of_day"] >= 22) | (df["hour_of_day"] <= 5)

    # Holidays
    df["is_holiday"] = ts.dt.date.map(lambda d: d in CA_HOLIDAYS).astype(bool)
    df["is_holiday_eve"] = ts.dt.date.map(
        lambda d: (d + pd.Timedelta(days=1)) in CA_HOLIDAYS
    ).astype(bool)

    return df


# ── Weather features ───────────────────────────────────────────────────────────

def add_weather_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Encode weather in ways that reflect how it actually affects transit ridership.

    Key insight: the relationship between rain and ridership is nonlinear.
    Light rain barely matters. Moderate rain shifts some car commuters to transit.
    Heavy rain causes both mode shift AND service disruptions.

    We also add rolling weather features because commuters make decisions
    based on sustained weather, not just the current hour.
    """
    df = df.copy()

    # Guard: if weather cols absent, return as-is
    if "precip_mm" not in df.columns:
        log.warning("Weather columns not found — skipping weather features")
        return df

    # ── Precipitation ─────────────────────────────────────────────────────────
    df["is_raining"] = df["precip_mm"] > 0.1   # recompute from raw mm

    # Nonlinear bucket (0=dry, 1=light, 2=moderate, 3=heavy)
    df["precip_intensity"] = pd.cut(
        df["precip_mm"],
        bins=[-np.inf, 0.1, PRECIP_LIGHT, PRECIP_MOD, PRECIP_HEAVY, np.inf],
        labels=[0, 1, 2, 3, 4],
    ).astype(float)

    # Rolling precipitation: has it been raining consistently? Sort first —
    # this condition was previously inverted (sorted only when already
    # sorted), which would have corrupted these rolling calcs on unsorted input.
    if not df["timestamp"].is_monotonic_increasing:
        df = df.sort_values("timestamp")
    if "station_id" in df.columns:
        grp = df.groupby("station_id")["precip_mm"]
    else:
        grp = df["precip_mm"]

    # rolling(N) counts N *rows*, not N hours. At this pipeline's actual
    # monthly cadence that makes "precip_3hr_sum" a 3-month sum and
    # "precip_24hr_sum" a 24-month (2-year) sum, not short-term rain
    # accumulation — only meaningful when timestamps carry sub-daily
    # resolution, matching the guard used for peak-hour/event-window features.
    if df["timestamp"].dt.hour.nunique() > 1:
        df["precip_3hr_sum"]  = grp.transform(lambda x: x.rolling(3,  min_periods=1).sum())
        df["precip_6hr_sum"]  = grp.transform(lambda x: x.rolling(6,  min_periods=1).sum())
        df["precip_24hr_sum"] = grp.transform(lambda x: x.rolling(24, min_periods=1).sum())

    # Is it the FIRST hour of rain after a dry spell? (commuters unprepared)
    df["is_rain_onset"] = df["is_raining"] & ~df.groupby(
        "station_id" if "station_id" in df.columns else [True] * len(df)
    )["is_raining"].transform(lambda x: x.shift(1).fillna(False))

    # ── Temperature ───────────────────────────────────────────────────────────
    if "temp_f" in df.columns:
        # Extreme temp → people avoid waiting at stops
        df["is_very_cold"] = df["temp_f"] < 40
        df["is_very_hot"]  = df["temp_f"] > 90
        df["temp_deviation"] = df["temp_f"] - 65.0   # deviation from Bay Area "normal"

    # ── Wind ──────────────────────────────────────────────────────────────────
    if "windspeed_mph" in df.columns:
        df["is_windy"] = df["windspeed_mph"] > 20

    # ── Combined comfort score (lower = worse conditions) ─────────────────────
    df["weather_discomfort"] = (
        df.get("precip_intensity", pd.Series(0, index=df.index)) * 2.0
        + df.get("is_very_cold", pd.Series(False, index=df.index)).astype(float) * 1.5
        + df.get("is_very_hot",  pd.Series(False, index=df.index)).astype(float) * 1.0
        + df.get("is_windy",     pd.Series(False, index=df.index)).astype(float) * 0.5
    )

    return df


# ── Event features ─────────────────────────────────────────────────────────────

def _add_monthly_event_features(df: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """
    Monthly-cadence proxy for add_event_features()'s hour-windowed columns:
    was there an event (or specifically a Sharks game) anywhere in the row's
    calendar month, rather than within an hour-scale window of a specific
    timestamp. Mirrors merge_pipeline.py's compute_event_features(), which
    already buckets is_game_day/is_sharks_game/is_playoff the same way.
    """
    ev = events.copy()
    ev["_year"]  = ev["timestamp_start"].dt.year
    ev["_month"] = ev["timestamp_start"].dt.month
    if "is_sharks_game" not in ev.columns:
        ev["is_sharks_game"] = False

    monthly = (
        ev.groupby(["_year", "_month"])
        .agg(event_count=("timestamp_start", "size"), has_sharks=("is_sharks_game", "any"))
        .reset_index()
    )

    df["_year"]  = df["timestamp"].dt.year
    df["_month"] = df["timestamp"].dt.month
    df = df.merge(monthly, on=["_year", "_month"], how="left")
    df["event_count"] = df["event_count"].fillna(0).astype(int)
    df["has_sharks"]  = df["has_sharks"].fillna(False)

    df["is_any_event_day"]      = df["event_count"] > 0
    df["is_sharks_game_window"] = df["has_sharks"]
    # Approach/departure windows have no monthly-granularity equivalent.
    df["is_pre_event_window"]  = False
    df["is_post_event_window"] = False
    max_count = max(int(df["event_count"].max()), 1)
    df["event_proximity_score"] = df["event_count"] / max_count
    df["nearest_event_attendance_tier"] = (
        df["is_sharks_game_window"].astype(int) * 2  # major
        + (df["is_any_event_day"] & ~df["is_sharks_game_window"]).astype(int)  # minor
    )
    df["hours_to_next_event"]    = np.nan
    df["hours_since_last_event"] = np.nan

    return df.drop(columns=["_year", "_month", "event_count", "has_sharks"])


def add_event_features(
    df: pd.DataFrame,
    events: pd.DataFrame,
    approach_hours: float = EVENT_APPROACH_HOURS,
    departure_hours: float = EVENT_DEPARTURE_HOURS,
) -> pd.DataFrame:
    """
    Encode event proximity as continuous and binary features.

    The key insight for transit forecasting: ridership doesn't spike exactly
    at game time — it builds up 2–3 hours before and tapers off 1–2 hours after.

    We compute:
      hours_to_next_event   : how many hours until the next event starts
                              (negative = event already started)
      hours_since_last_event: how long since the last event ended
      is_pre_event_window   : True if within approach_hours before event start
      is_post_event_window  : True if within departure_hours after event end
      event_proximity_score : continuous 0→1 score peaking at event time
      is_sharks_game_window : specifically Sharks game window (Diridon/VTA spike)
    """
    if events.empty or "timestamp" not in df.columns:
        for col in [
            "hours_to_next_event", "hours_since_last_event",
            "is_pre_event_window", "is_post_event_window",
            "event_proximity_score", "is_sharks_game_window",
            "is_any_event_day", "nearest_event_attendance_tier",
        ]:
            df[col] = 0.0 if "hours" in col or "score" in col or "tier" in col else False
        return df

    df = df.copy()
    events = events.copy()

    # Ensure timestamps are timezone-aware
    for frame, col in [(df, "timestamp"), (events, "timestamp_start")]:
        if frame[col].dt.tz is None:
            frame[col] = frame[col].dt.tz_localize("America/Los_Angeles")

    # approach_hours/departure_hours-scale windows are only meaningful when
    # df's timestamps carry sub-daily resolution. At this pipeline's actual
    # monthly cadence every row sits at midnight-of-month, so a game at, say,
    # 19:00 is ~350+ hours away from the row it should be flagging — these
    # columns would silently be constant False/0 forever (the same dead-signal
    # class of bug already fixed for is_am_peak/is_pm_peak in
    # merge_pipeline.py). Fall back to a monthly event-presence proxy instead
    # of returning a permanently dead feature.
    if df["timestamp"].dt.hour.nunique() <= 1:
        return _add_monthly_event_features(df, events)

    ev_starts = events["timestamp_start"].values
    ev_ends   = events["timestamp_end"].values if "timestamp_end" in events.columns \
                else events["timestamp_start"].values + np.timedelta64(3, "h")
    ev_sharks = events["is_sharks_game"].values if "is_sharks_game" in events.columns \
                else np.zeros(len(events), dtype=bool)

    hours_to_next   = np.full(len(df), np.nan)
    hours_since_last= np.full(len(df), np.nan)
    proximity_score = np.zeros(len(df))
    is_pre_window   = np.zeros(len(df), dtype=bool)
    is_post_window  = np.zeros(len(df), dtype=bool)
    is_sharks_win   = np.zeros(len(df), dtype=bool)
    is_any_event    = np.zeros(len(df), dtype=bool)

    for i, ts in enumerate(df["timestamp"].values):
        # Time delta in hours to each event start
        delta_start = (ev_starts - ts) / np.timedelta64(1, "h")
        delta_end   = (ev_ends   - ts) / np.timedelta64(1, "h")

        # Next event
        future_mask = delta_start > 0
        if future_mask.any():
            hours_to_next[i] = delta_start[future_mask].min()

        # Last ended event
        past_mask = delta_end < 0
        if past_mask.any():
            hours_since_last[i] = -delta_end[past_mask].max()  # positive

        # Pre-event window: within approach_hours before start
        pre_mask = (delta_start >= 0) & (delta_start <= approach_hours)
        # During event: between start and end
        during_mask = (delta_start <= 0) & (delta_end >= 0)
        # Post-event: within departure_hours after end
        post_mask = (delta_end < 0) & (delta_end >= -departure_hours)

        active_mask = pre_mask | during_mask | post_mask
        is_pre_window[i]  = pre_mask.any()
        is_post_window[i] = post_mask.any()
        is_any_event[i]   = active_mask.any()

        if active_mask.any():
            is_sharks_win[i] = ev_sharks[active_mask].any()
            # Proximity score: Gaussian decay from event midpoint
            # Peak at event start, decays symmetrically
            best_delta = delta_start[active_mask]
            score = np.exp(-0.5 * (best_delta / approach_hours) ** 2).max()
            proximity_score[i] = float(score)

    df["hours_to_next_event"]    = hours_to_next
    df["hours_since_last_event"] = hours_since_last
    df["is_pre_event_window"]    = is_pre_window
    df["is_post_event_window"]   = is_post_window
    df["event_proximity_score"]  = proximity_score
    df["is_sharks_game_window"]  = is_sharks_win
    df["is_any_event_day"]       = is_any_event

    # Attendance tier (proxy for crowd size) — 0=none, 1=minor, 2=major
    df["nearest_event_attendance_tier"] = (
        df["is_sharks_game_window"].astype(int) * 2  # major
        + (df["is_any_event_day"] & ~df["is_sharks_game_window"]).astype(int)  # minor
    )

    return df


# ── Station / network features ─────────────────────────────────────────────────

def add_station_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add static features per station that never change but help the model
    understand spatial context.

    These are one-hot and ordinal encodings of:
      - Transit mode (rail is more capacity-constrained than bus)
      - Agency (different ridership patterns per operator)
      - Whether a station is a transfer hub (Diridon, Embarcadero, etc.)
      - Distance from Diridon (relevant for event impact radius)
    """
    if "station_id" not in df.columns:
        return df

    df = df.copy()

    # Transfer hub stations — multi-modal, highest baseline ridership
    # Note: Diridon is a Caltrain/VTA hub, not a BART station_id — it has no
    # entry here and is instead captured via dist_from_diridon_km/in_event_catchment below.
    HUB_STATIONS = {
        "EMBR", "MONT", "POWL", "CIVC",  # SF BART hubs
        "19TH", "MCAR",                    # Oakland hubs
        "MLBR", "SFIA",                    # Airport connections
        "BERY", "MLPT",                    # South Bay (Berryessa/Milpitas)
    }

    df["is_hub_station"] = df["station_id"].isin(HUB_STATIONS)

    # Transit mode encoding
    TRANSIT_MODE_MAP = {
        "BA": "heavy_rail", "CT": "commuter_rail", "VTA": "light_rail",
        "SF": "bus", "AC": "bus", "SM": "bus", "WTA": "ferry", "GF": "bus",
    }
    if "agency_id" in df.columns:
        df["transit_mode"] = df["agency_id"].map(TRANSIT_MODE_MAP).fillna("unknown")
        # Ordinal capacity encoding: ferry > heavy_rail > commuter_rail > light_rail > bus
        CAPACITY_ORDER = {
            "ferry": 4, "heavy_rail": 3, "commuter_rail": 2,
            "light_rail": 1, "bus": 0, "unknown": 0,
        }
        df["capacity_tier"] = df["transit_mode"].map(CAPACITY_ORDER)

    # Distance from Diridon (epicenter of Sharks game effect)
    if "lat" in df.columns and "lng" in df.columns:
        df["dist_from_diridon_km"] = np.sqrt(
            ((df["lat"] - DIRIDON_LAT) * 111.0) ** 2
            + ((df["lng"] - DIRIDON_LNG) * 111.0 * np.cos(np.radians(DIRIDON_LAT))) ** 2
        )
        # Stations within 5km of SAP Center are in the "event catchment zone"
        df["in_event_catchment"] = df["dist_from_diridon_km"] <= 5.0

    return df


# ── Lag features ───────────────────────────────────────────────────────────────

def add_lag_features(
    df: pd.DataFrame,
    target_col: str = "ridership",
    lags: list[int] = None,
) -> pd.DataFrame:
    """
    Add autoregressive lag features — the model's memory of what happened recently.

    Lags are chosen from the observed cadence. For current BART OD data this
    means monthly lags (1, 2, 3, 6, 12 months); for future 15-minute data this
    falls back to the original hourly/day/week lags.

    These help the baseline models (Prophet, ARIMA) and can also be
    used as additional context features alongside Chronos-2.
    """
    if target_col not in df.columns or "station_id" not in df.columns:
        return df

    df = df.sort_values(["station_id", "timestamp"]).copy()
    diffs = (
        df.groupby("station_id")["timestamp"]
        .diff()
        .dropna()
    )
    is_monthly = not diffs.empty and diffs.median() >= pd.Timedelta(days=25)

    if lags is None:
        lags = [1, 2, 3, 6, 12] if is_monthly else [4, 8, 12, 96, 192, 672]

    for lag in lags:
        col_name = f"{target_col}_lag_{lag}"
        df[col_name] = df.groupby("station_id")[target_col].transform(
            lambda x: x.shift(lag)
        )

    if is_monthly:
        df[f"{target_col}_rolling_mean_3mo"] = df.groupby("station_id")[target_col].transform(
            lambda x: x.shift(1).rolling(3, min_periods=2).mean()
        )
        df[f"{target_col}_rolling_std_3mo"] = df.groupby("station_id")[target_col].transform(
            lambda x: x.shift(1).rolling(3, min_periods=2).std()
        )
        df[f"{target_col}_rolling_mean_12mo"] = df.groupby("station_id")[target_col].transform(
            lambda x: x.shift(1).rolling(12, min_periods=6).mean()
        )
    else:
        df[f"{target_col}_rolling_mean_24h"] = df.groupby("station_id")[target_col].transform(
            lambda x: x.shift(1).rolling(96, min_periods=24).mean()
        )
        df[f"{target_col}_rolling_std_24h"] = df.groupby("station_id")[target_col].transform(
            lambda x: x.shift(1).rolling(96, min_periods=24).std()
        )
        df[f"{target_col}_rolling_mean_7d"] = df.groupby("station_id")[target_col].transform(
            lambda x: x.shift(1).rolling(672, min_periods=96).mean()
        )

    return df


# ── Main entry point ───────────────────────────────────────────────────────────

def build_features(
    df: pd.DataFrame,
    events: pd.DataFrame = None,
    target_col: str = "ridership",
    add_lags: bool = True,
) -> pd.DataFrame:
    """
    Full feature engineering pipeline. Run all transformations in sequence.

    Args:
        df       : merged raw DataFrame from merge_pipeline.py
        events   : events DataFrame (from fetch_events.py). If None, skips event features.
        target_col: name of the ridership column
        add_lags  : whether to compute lag features (skip for inference-only pipelines)

    Returns:
        Enriched DataFrame ready to pass into Chronos-2 or baseline models.
    """
    n_input = len(df)
    n_input_cols = len(df.columns)
    log.info(f"Building features for {n_input:,} rows …")

    df = add_time_features(df)
    log.info("  ✓ Time features added")

    df = add_weather_features(df)
    log.info("  ✓ Weather features added")

    if events is not None:
        df = add_event_features(df, events)
        log.info("  ✓ Event features added")

    df = add_station_features(df)
    log.info("  ✓ Station features added")

    if add_lags and target_col in df.columns:
        df = add_lag_features(df, target_col)
        log.info("  ✓ Lag features added")

    n_features = len(df.columns)
    n_new = n_features - n_input_cols
    log.info(f"  → {n_features} total feature columns (+{n_new} new) for {n_input:,} rows")

    return df


# ── Standalone script ──────────────────────────────────────────────────────────

def main():
    import yaml

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    feature_store_path = PROCESSED_DIR / "feature_store.parquet"
    events_path        = Path("data/raw/events")

    if not feature_store_path.exists():
        log.error("Feature store not found. Run: python machine_learning_files/merge_pipeline.py")
        return

    log.info("Loading feature store …")
    df = pd.read_parquet(feature_store_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Load events if available
    events = pd.DataFrame()
    event_files = sorted(events_path.glob("events_*.parquet"))
    if event_files:
        events = pd.read_parquet(event_files[-1])
        events["timestamp_start"] = pd.to_datetime(events["timestamp_start"])
        log.info(f"Loaded {len(events)} events")

    df_enriched = build_features(df, events=events)

    out = PROCESSED_DIR / "feature_store_enriched.parquet"
    df_enriched.to_parquet(out, index=False)
    log.info(f"Enriched feature store saved → {out}")

    # Print feature summary
    print(f"\n{'─'*60}")
    print(f"Feature Engineering Summary")
    print(f"{'─'*60}")
    print(f"Input rows      : {len(df):,}")
    print(f"Output columns  : {len(df_enriched.columns)}")
    print(f"\nFeature groups:")
    groups = {
        "Time":    [c for c in df_enriched.columns if any(x in c for x in ["hour", "day", "week", "month", "peak", "weekend", "holiday", "sin", "cos"])],
        "Weather": [c for c in df_enriched.columns if any(x in c for x in ["precip", "rain", "temp", "wind", "weather", "discomfort"])],
        "Events":  [c for c in df_enriched.columns if any(x in c for x in ["event", "sharks", "game"])],
        "Station": [c for c in df_enriched.columns if any(x in c for x in ["hub", "transit", "capacity", "diridon", "catchment"])],
        "Lags":    [c for c in df_enriched.columns if "lag" in c or "rolling" in c],
    }
    for group, cols in groups.items():
        print(f"  {group:8s}: {len(cols):3d} features")


if __name__ == "__main__":
    main()
