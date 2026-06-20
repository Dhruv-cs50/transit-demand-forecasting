"""
processing/merge_pipeline.py
─────────────────────────────
Joins all raw data sources into a single tidy feature store parquet file,
keyed on (timestamp, station_id).

Sources joined:
  1. Transit ridership   (data/raw/transit/)     — target variable
  2. Road speed/flow     (data/raw/roads/)        — road context
  3. Weather             (data/raw/weather/)      — past + future covariate
  4. Events              (data/raw/events/)       — future-known covariate

Output: data/processed/feature_store.parquet
Schema:
    timestamp       datetime64[ns, America/Los_Angeles]
    station_id      str
    agency_id       str
    transit_mode    str      (rail / bus / ferry / road)
    ridership       float64  ← TARGET
    road_speed_mph  float64
    road_flow       float64
    temp_f          float64
    precip_mm       float64
    is_raining      bool
    weather_code    int
    windspeed_mph   float64
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
    lat             float64
    lng             float64

Usage:
    python processing/merge_pipeline.py
    python processing/merge_pipeline.py --freq 15min --start 2020-01-01
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
    files = list(bart_dir.glob("bart_od_*.parquet"))
    if not files:
        log.warning("No BART OD files found — transit column will be NaN")
        return pd.DataFrame()

    frames = []
    for f in sorted(files):
        df = pd.read_parquet(f)
        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)

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
    files = sorted((RAW_DIR / "weather").glob("weather_all_stations_*.parquet"))
    if not files:
        log.warning("No weather files found")
        return pd.DataFrame()

    df = pd.read_parquet(files[-1])  # use the most recent combined file
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_convert(None)

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
    # Peak commute windows
    df["is_am_peak"]   = ts.dt.hour.between(7, 9)
    df["is_pm_peak"]   = ts.dt.hour.between(16, 19)

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
    base = transit_df.copy()

    # 3. Merge weather — aggregate hourly weather to monthly, join on year/month
    if not weather_df.empty:
        weather_df = weather_df.rename(columns={"station": "weather_station"})
        wdf = weather_df.copy()
        wdf["timestamp"] = pd.to_datetime(wdf["timestamp"])
        if wdf["timestamp"].dt.tz is not None:
            wdf["timestamp"] = wdf["timestamp"].dt.tz_localize(None)
        wdf["_year"]  = wdf["timestamp"].dt.year
        wdf["_month"] = wdf["timestamp"].dt.month
        monthly_weather = (
            wdf
            .groupby(["_year", "_month"])[[
                "temp_f", "precip_mm", "windspeed_mph",
                "is_raining", "weather_code", "cloud_cover_pct"
            ]]
            .mean()
            .reset_index()
        )
        log.info(f"Merging {len(monthly_weather):,} month-average weather rows …")

        base_ts = pd.to_datetime(base["timestamp"])
        if base_ts.dt.tz is not None:
            base_ts = base_ts.dt.tz_localize(None)
        base["_year"]  = base_ts.dt.year
        base["_month"] = base_ts.dt.month
        base = base.merge(monthly_weather, on=["_year", "_month"], how="left")
        base = base.drop(columns=["_year", "_month"])

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

    # 6. Date range filter — strip tz from filter boundary if column is tz-naive
    if start:
        start_ts = pd.Timestamp(start, tz="America/Los_Angeles")
        ts_col = pd.to_datetime(base["timestamp"])
        if ts_col.dt.tz is None:
            start_ts = start_ts.tz_localize(None)
        base = base[ts_col >= start_ts]
    if end:
        end_ts = pd.Timestamp(end, tz="America/Los_Angeles")
        ts_col = pd.to_datetime(base["timestamp"])
        if ts_col.dt.tz is None:
            end_ts = end_ts.tz_localize(None)
        base = base[ts_col <= end_ts]

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

    def _ts(s): return pd.Timestamp(s).tz_localize(None) if pd.Timestamp(s).tzinfo is None else pd.Timestamp(s).tz_convert(None)

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
