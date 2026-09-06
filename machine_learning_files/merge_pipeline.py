"""
machine_learning_files/merge_pipeline.py
───────────────────────────────────────────
Joins all raw data sources into a single tidy feature store parquet file,
keyed on (timestamp, station_id).

Sources joined:
  1. Transit ridership   (data/raw/transit/)     — target variable
  2. Weather             (data/raw/weather/)      — past + future covariate
  3. Events              (data/raw/events/)       — future-known covariate

Road speed/flow (models/baselines/fetch_pems_roads.py) is fetched separately
but is not yet wired into this pipeline — no road_speed_mph/road_flow/lat/lng
columns are produced here despite earlier versions of this docstring claiming
otherwise.

Output: data/processed/feature_store.parquet
Schema:
    timestamp       datetime64[ns]  (tz-naive, wall-clock America/Los_Angeles)
    station_id      str
    agency_id       str
    transit_mode    str      (rail / bus / ferry / road)
    ridership       float64  ← TARGET
    temp_f          float64
    precip_mm       float64
    precip_in       float64
    is_raining      bool
    weather_code    int
    windspeed_mph   float64
    cloud_cover_pct float64
    humidity_pct    float64
    is_game_day     bool
    game_start_hour int      (NaN if no game)
    hours_to_event  float64  (hours until next event at a nearby venue)
    is_sharks_game  bool
    is_playoff      bool
    is_holiday      bool
    is_weekend      bool
    hour_of_day     int
    day_of_week     int      (0=Mon, 6=Sun)
    month           int
    is_am_peak      bool     (only present when timestamps carry sub-daily resolution)
    is_pm_peak      bool     (only present when timestamps carry sub-daily resolution)

Usage:
    python machine_learning_files/merge_pipeline.py
    python machine_learning_files/merge_pipeline.py --freq 15min --start 2020-01-01
"""

import argparse
import logging
from pathlib import Path

import pandas as pd
import yaml
from pandas.tseries.holiday import USFederalHolidayCalendar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("merge_pipeline")

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
CONFIG_PATH = Path("configs/sources.yaml")
MODEL_CONFIG_PATH = Path("configs/model.yaml")

# Direct name correspondence between the 7 weather-monitoring locations in
# configs/sources.yaml (weather.station_coords) and real BART station codes
# (cross-checked against fetch_bart_od.py's STATION_NAMES). "diridon" has no
# BART equivalent -- it's a Caltrain/VTA hub -- so it's intentionally left
# unmapped here; it still contributes to the regional fallback average below.
STATION_TO_WEATHER_STATION = {
    "EMBR": "embarcadero",
    "MLBR": "millbrae",
    "FRMT": "fremont_bart",
    "BERY": "berryessa",
    "SFIA": "sfo",
    "19TH": "oakland_19th",
}


def load_configs() -> tuple[dict, dict]:
    with open(CONFIG_PATH) as f:
        src_cfg = yaml.safe_load(f)
    with open(MODEL_CONFIG_PATH) as f:
        model_cfg = yaml.safe_load(f)
    return src_cfg, model_cfg


# ── Loaders ────────────────────────────────────────────────────────────────────

def load_transit(freq: str) -> pd.DataFrame:
    """
    Load all transit parquet files, combine, resample to target frequency.
    For now uses BART OD as the primary transit source.
    Plug in 511 stop-observation data here once processed.
    """
    log.info("Loading transit ridership data …")
    bart_dir = RAW_DIR / "transit" / "bart"
    # Match only the per-month files (bart_od_YYYY_MM.parquet). The broader
    # "bart_od_*.parquet" pattern also matched fetch_bart_od.py's consolidated
    # "bart_od_all.parquet" (all months already concatenated), which loaded
    # every month's ridership twice and silently doubled the target column.
    files = list(bart_dir.glob("bart_od_[0-9][0-9][0-9][0-9]_[0-9][0-9].parquet"))
    if not files:
        log.warning("No BART OD files found — transit column will be NaN")
        return pd.DataFrame()

    frames = []
    for f in sorted(files):
        df = pd.read_parquet(f)
        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)

    # BART's OD workbooks include a "Total Trips" sheet alongside the
    # "Weekday"/"Saturday"/"Sunday" sheets -- fetch_bart_od.py's
    # parse_bart_od_excel() tags every sheet as its own day_type without
    # distinguishing it (see transit_eda/notebooks/eda_complete.py's
    # sheet_map, which explicitly maps a "Total Trips (OD)" sheet to
    # day_type "Total" and excludes it before aggregating). Summing riders
    # across day_type below without dropping it would sum the Weekday +
    # Saturday + Sunday sheets *and* the sheet that is already their
    # monthly total on top, roughly doubling every station-month's
    # ridership -- the same double-counting failure mode as the
    # glob-collision bug fixed 2026-08-12, via a different mechanism.
    if "day_type" in combined.columns:
        combined = combined[~combined["day_type"].str.contains("total", case=False, na=False)]

    # Aggregate total riders per station per period (collapse day_types & destinations)
    # For forecasting we want total inbound ridership per station per time window
    station_monthly = (
        combined
        .groupby(["period", "origin", "origin_name"])["riders"]
        .sum()
        .reset_index()
        .rename(columns={"origin": "station_id", "origin_name": "station_name", "riders": "ridership"})
    )
    # Drop system-wide aggregate rows (e.g. "Exits") — not real station codes
    station_monthly = station_monthly[station_monthly["station_id"].str.len() <= 4]

    # Convert monthly → daily approximation (÷ 22 weekdays) and set to timestamp
    station_monthly["timestamp"] = pd.to_datetime(station_monthly["period"])
    station_monthly["ridership_daily_est"] = station_monthly["ridership"] / 22
    station_monthly["agency_id"] = "BA"
    station_monthly["transit_mode"] = "rail"

    log.info(f"  Loaded {len(station_monthly):,} station-month rows from BART OD")
    return station_monthly


def load_weather(freq: str, station_coords: dict) -> pd.DataFrame:
    """Load all weather parquet files and return combined hourly DataFrame."""
    log.info("Loading weather data …")
    hist_files = sorted((RAW_DIR / "weather").glob("weather_all_stations_*.parquet"))
    # fetch_forecast_all_stations() writes the nightly 7-day-ahead forecast under a
    # separate "weather_forecast_*" prefix — it must be loaded too, or the pipeline's
    # only source of future-known weather covariates is silently dropped.
    forecast_files = sorted((RAW_DIR / "weather").glob("weather_forecast_*.parquet"))
    if not hist_files and not forecast_files:
        log.warning("No weather files found")
        return pd.DataFrame()

    frames = []
    if hist_files:
        frames.append(pd.read_parquet(hist_files[-1]))  # most recent combined historical file
    if forecast_files:
        frames.append(pd.read_parquet(forecast_files[-1]))  # most recent forecast file
    df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if df["timestamp"].dt.tz is not None:
        # tz_convert(None) would shift to UTC before stripping the tz label; use
        # tz_convert to LA first, then tz_localize(None), matching every other
        # tz-stripping site in this file (see the comment at line ~437).
        df["timestamp"] = df["timestamp"].dt.tz_convert("America/Los_Angeles").dt.tz_localize(None)

    # Skip resample — resampling 5 years of hourly data to 15min creates millions
    # of intermediate rows. Monthly aggregation is done downstream in build_feature_store.
    df = df.dropna(subset=["timestamp"])

    log.info(f"  Loaded {len(df):,} weather rows")
    return df


def load_events() -> pd.DataFrame:
    """Load the most recent events parquet file."""
    log.info("Loading events data …")
    files = sorted((RAW_DIR / "events").glob("events_*.parquet"))
    if not files:
        log.warning("No events files found")
        return pd.DataFrame()

    df = pd.read_parquet(files[-1])
    df["timestamp_start"] = pd.to_datetime(df["timestamp_start"])
    if df["timestamp_start"].dt.tz is None:
        df["timestamp_start"] = df["timestamp_start"].dt.tz_localize("America/Los_Angeles")
    else:
        df["timestamp_start"] = df["timestamp_start"].dt.tz_convert("America/Los_Angeles")

    log.info(f"  Loaded {len(df):,} events")
    return df


# ── Event feature computation ──────────────────────────────────────────────────

def compute_event_features(
    timestamps: pd.Series,
    events: pd.DataFrame,
    venue_proximity_hrs: float = 4.0,
) -> pd.DataFrame:
    """
    Monthly aggregation: for each timestamp (month-start), count events in that month.
    - is_game_day    : True if ≥1 home game in that month
    - hours_to_event : number of home games in that month (repurposed as game count)
    - is_sharks_game : True if any Sharks game in that month
    - game_start_hour: modal game start hour in that month
    - is_playoff     : True if any playoff game in that month
    """
    n = len(timestamps)
    if events.empty:
        return pd.DataFrame({
            "is_game_day":     [False] * n,
            "hours_to_event":  [0.0] * n,
            "is_sharks_game":  [False] * n,
            "game_start_hour": [float("nan")] * n,
            "is_playoff":      [False] * n,
        }, index=timestamps.index)

    ev = events.copy()
    ev_ts = pd.to_datetime(ev["timestamp_start"])
    if ev_ts.dt.tz is not None:
        # tz_convert(None) would shift to UTC before stripping the tz label,
        # pushing evening LA events past midnight into the wrong month.
        # tz_localize(None) drops the tz label in place, preserving the
        # LA wall-clock value that _year/_month bucketing expects.
        ev_ts = ev_ts.dt.tz_localize(None)
    ev["_year"]  = ev_ts.dt.year
    ev["_month"] = ev_ts.dt.month

    ts_series = pd.to_datetime(timestamps)
    if ts_series.dt.tz is not None:
        ts_series = ts_series.dt.tz_localize(None)

    results = []
    for ts in ts_series:
        month_ev = ev[(ev["_year"] == ts.year) & (ev["_month"] == ts.month)]
        if month_ev.empty:
            results.append({
                "is_game_day":     False,
                "hours_to_event":  0.0,
                "is_sharks_game":  False,
                "game_start_hour": float("nan"),
                "is_playoff":      False,
            })
        else:
            mode_hour = month_ev["game_start_hour"].mode()
            results.append({
                "is_game_day":     True,
                "hours_to_event":  float(len(month_ev)),
                "is_sharks_game":  bool(month_ev["is_sharks_game"].any()) if "is_sharks_game" in month_ev.columns else False,
                "game_start_hour": float(mode_hour.iloc[0]) if not mode_hour.empty else float("nan"),
                "is_playoff":      bool(month_ev["is_playoff"].any()) if "is_playoff" in month_ev.columns else False,
            })

    return pd.DataFrame(results, index=timestamps.index)


# ── Calendar features ──────────────────────────────────────────────────────────

def add_calendar_features(df: pd.DataFrame, ts_col: str = "timestamp") -> pd.DataFrame:
    """Add time-based features that are free information (known in advance)."""
    us_holidays = set(
        USFederalHolidayCalendar()
        .holidays(start="2019-01-01", end="2030-12-31")
        .date
    )

    ts = df[ts_col]
    df["hour_of_day"]  = ts.dt.hour
    df["day_of_week"]  = ts.dt.dayofweek          # 0=Mon, 6=Sun
    df["is_weekend"]   = ts.dt.dayofweek >= 5
    df["month"]        = ts.dt.month
    df["week_of_year"] = ts.dt.isocalendar().week.astype(int)
    df["is_holiday"]   = ts.dt.date.map(lambda d: d in us_holidays)
    # Peak commute windows are only meaningful when timestamps actually carry
    # sub-daily resolution. At the monthly cadence this pipeline currently
    # runs at, every timestamp sits at midnight, so these would always
    # evaluate to constant False -- a dead signal fed straight into training
    # rather than a real "not currently peak" reading. Only add them when the
    # data can actually distinguish hours.
    if ts.dt.hour.nunique() > 1:
        df["is_am_peak"] = ts.dt.hour.between(7, 9)
        df["is_pm_peak"] = ts.dt.hour.between(16, 19)

    return df


# ── Main pipeline ──────────────────────────────────────────────────────────────

def build_feature_store(
    freq: str = "15min",
    start: str = None,
    end: str = None,
) -> pd.DataFrame:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    src_cfg, model_cfg = load_configs()

    # 1. Load each source
    transit_df = load_transit(freq)
    weather_df = load_weather(freq, src_cfg["weather"]["station_coords"])
    events_df  = load_events()

    if transit_df.empty:
        log.error("Transit data is empty — cannot build feature store")
        return pd.DataFrame()

    # 2. Build a base time grid from transit data timestamps
    # (In production this would be the 511 stop-observation data at 15-min resolution)
    # reset_index: load_transit() filters rows (dropping "Exits"-style aggregate
    # station codes), leaving a non-contiguous index. Section 3 below assigns
    # `.merge(...)` results (always a fresh 0..n-1 RangeIndex) back onto `base`
    # via `.where(...)`, which label-aligns on the index rather than position —
    # a gappy index there silently scrambles/NaNs the per-row weather match.
    base = transit_df.copy().reset_index(drop=True)

    # 3. Merge weather — aggregate hourly weather to monthly, join per-station
    # where a BART station maps to a dedicated weather-monitoring location,
    # falling back to the regional (all-locations) average everywhere else.
    if not weather_df.empty:
        weather_df = weather_df.rename(columns={"station": "weather_station"})
        wdf = weather_df.copy()
        wdf["timestamp"] = pd.to_datetime(wdf["timestamp"])
        if wdf["timestamp"].dt.tz is not None:
            wdf["timestamp"] = wdf["timestamp"].dt.tz_localize(None)
        wdf["_year"]  = wdf["timestamp"].dt.year
        wdf["_month"] = wdf["timestamp"].dt.month

        agg_kwargs = dict(
            temp_f=("temp_f", "mean"),
            precip_mm=("precip_mm", "mean"),
            precip_in=("precip_in", "mean"),
            windspeed_mph=("windspeed_mph", "mean"),
            is_raining=("is_raining", "mean"),
            # weather_code is a categorical WMO code — averaging it produces a
            # meaningless fractional value, so take the most common code instead.
            weather_code=("weather_code", lambda s: s.mode().iat[0] if not s.mode().empty else s.iloc[0]),
            cloud_cover_pct=("cloud_cover_pct", "mean"),
            humidity_pct=("humidity_pct", "mean"),
        )
        weather_cols = list(agg_kwargs.keys())

        # Previously this blended all 7 monitoring locations (including
        # "diridon", ~50mi from the Bay Area BART core) into one number per
        # month and joined it onto every station — every station got
        # identical weather regardless of where it actually sits.
        station_weather = (
            wdf.groupby(["weather_station", "_year", "_month"]).agg(**agg_kwargs).reset_index()
        )
        regional_weather = (
            wdf.groupby(["_year", "_month"]).agg(**agg_kwargs).reset_index()
        )
        log.info(
            f"Merging weather: {len(station_weather):,} per-station rows "
            f"(direct match for {len(STATION_TO_WEATHER_STATION)} stations) "
            f"+ {len(regional_weather):,} regional fallback rows …"
        )

        base_ts = pd.to_datetime(base["timestamp"])
        if base_ts.dt.tz is not None:
            base_ts = base_ts.dt.tz_localize(None)
        base["_year"]  = base_ts.dt.year
        base["_month"] = base_ts.dt.month
        base["weather_station"] = base["station_id"].map(STATION_TO_WEATHER_STATION)

        matched  = base.merge(station_weather, on=["weather_station", "_year", "_month"], how="left")
        fallback = base.merge(regional_weather, on=["_year", "_month"], how="left")
        # has_match alone only tells us the station *name* mapping exists, not that
        # station_weather actually has a row for it (e.g. that location's fetch
        # failed for a given month) — .where(has_match, ...) would then keep a NaN
        # from `matched` instead of falling back. fillna() catches both cases.
        for col in weather_cols:
            base[col] = matched[col].fillna(fallback[col])

        base = base.drop(columns=["_year", "_month", "weather_station"])

    # 4. Compute event features against the timestamp column
    if not events_df.empty and "timestamp" in base.columns:
        log.info("Computing event proximity features …")
        event_features = compute_event_features(
            base["timestamp"],
            events_df,
            venue_proximity_hrs=4.0,
        )
        base = pd.concat([base.reset_index(drop=True), event_features.reset_index(drop=True)], axis=1)
    else:
        base["is_game_day"] = False
        base["hours_to_event"] = float("nan")
        base["is_sharks_game"] = False
        base["game_start_hour"] = float("nan")
        base["is_playoff"] = False

    # 5. Calendar features
    if "timestamp" in base.columns:
        base = add_calendar_features(base, "timestamp")

    # 6. Date range filter (compare in the same tz space as base timestamps)
    if start:
        start_ts = pd.Timestamp(start)
        if base["timestamp"].dt.tz is not None:
            start_ts = start_ts.tz_localize("America/Los_Angeles") if start_ts.tzinfo is None \
                else start_ts.tz_convert("America/Los_Angeles")
        base = base[base["timestamp"] >= start_ts]
    if end:
        end_ts = pd.Timestamp(end)
        if base["timestamp"].dt.tz is not None:
            end_ts = end_ts.tz_localize("America/Los_Angeles") if end_ts.tzinfo is None \
                else end_ts.tz_convert("America/Los_Angeles")
        base = base[base["timestamp"] <= end_ts]

    # 7. Save
    out = PROCESSED_DIR / "feature_store.parquet"
    base.to_parquet(out, index=False)
    log.info(f"\nFeature store saved: {len(base):,} rows, {len(base.columns)} columns → {out}")
    log.info(f"Columns: {list(base.columns)}")
    return base


def make_splits(df: pd.DataFrame, train_end: str, val_end: str, train_start: str = None) -> None:
    """Chronological train/val/test split — no data leakage.

    train_start: optional lower bound for train set (excludes earlier years with data gaps).
    """
    splits_dir = PROCESSED_DIR / "splits"
    splits_dir.mkdir(parents=True, exist_ok=True)

    if "timestamp" not in df.columns:
        log.error("No timestamp column — cannot split")
        return

    ts = pd.to_datetime(df["timestamp"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_localize(None)

    # tz_convert(None) would shift to UTC before stripping the tz label (same
    # wrong-month hazard already fixed in compute_event_features above);
    # tz_convert to LA first, then tz_localize(None) to drop the label in
    # place and preserve the LA wall-clock value the date-string boundaries
    # (train_end/val_end) are meant to compare against.
    def _ts(s):
        ts = pd.Timestamp(s)
        return ts if ts.tzinfo is None else ts.tz_convert("America/Los_Angeles").tz_localize(None)

    train_ts = _ts(train_end)
    val_ts   = _ts(val_end)

    if train_start:
        start_ts = _ts(train_start)
        train_mask = (ts >= start_ts) & (ts <= train_ts)
        log.info(f"  train_start filter: {train_start} — excluding data before this date")
    else:
        train_mask = ts <= train_ts

    val_mask  = (ts > train_ts) & (ts <= val_ts)
    test_mask = ts > val_ts

    for name, mask in [("train", train_mask), ("val", val_mask), ("test", test_mask)]:
        split_df = df[mask]
        out = splits_dir / f"{name}.parquet"
        split_df.to_parquet(out, index=False)
        log.info(f"  {name:5s}: {len(split_df):>8,} rows → {out}")


def parse_args():
    parser = argparse.ArgumentParser(description="Build feature store from raw data")
    parser.add_argument("--freq", default="15min", help="Resample frequency (default: 15min)")
    parser.add_argument("--start", default=None, help="Start date filter")
    parser.add_argument("--end", default=None, help="End date filter")
    parser.add_argument("--no-split", action="store_true", help="Skip train/val/test split")
    return parser.parse_args()


def main():
    args = parse_args()
    _, model_cfg = load_configs()

    df = build_feature_store(args.freq, args.start, args.end)

    if not df.empty and not args.no_split:
        log.info("Creating train/val/test splits …")
        make_splits(
            df,
            train_end=model_cfg["data"]["train_end"],
            val_end=model_cfg["data"]["val_end"],
            train_start=model_cfg["data"].get("train_start"),
        )

    log.info("Pipeline complete.")


if __name__ == "__main__":
    main()
