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
    timestamp       datetime64      (tz-naive, wall-clock America/Los_Angeles)
    station_id      str
    agency_id       str
    transit_mode    str      (rail / bus / ferry / road)
    ridership       float64  ← TARGET (monthly Total-Trips boardings; see load_transit())
    temp_f          float64
    precip_mm       float64
    precip_in       float64
    is_raining      float64  (per-station-month mean fraction 0.0-1.0, NOT
                              bool -- feature_engineering.py recomputes this
                              column as an actual bool from precip_mm)
    weather_code    int
    windspeed_mph   float64
    cloud_cover_pct float64
    humidity_pct    float64
    is_game_day     boolean  (nullable; <NA> for a month the events archive does
                              not cover, False for a covered month with no
                              event -- see event_coverage())
    game_start_hour float64  (NaN if no game -- compute_event_features()
                              always emits a Python float here, so this
                              column can never actually be int dtype)
    hours_to_event  float64  (despite the name, this is a monthly home-game/
                              event COUNT for that station-month, not an
                              hours-scale value -- see compute_event_features();
                              NaN for a month the archive does not cover, 0.0
                              for a covered month with no event)
    is_sharks_game  boolean  (nullable, same coverage rule as is_game_day)
    is_playoff      boolean  (nullable, same coverage rule as is_game_day)
    is_holiday      bool
    is_weekend      bool
    hour_of_day     int
    day_of_week     int      (0=Mon, 6=Sun)
    month           int
    week_of_year    int
    is_am_peak      bool     (only present when timestamps carry sub-daily resolution)
    is_pm_peak      bool     (only present when timestamps carry sub-daily resolution)
    period          datetime64[ns]  (carried through from load_transit(); same
                                      month-start value as timestamp)
    station_name    str      (BART station name for station_id, from
                              machine_learning_files/bart_stations.py)
    ridership_daily_est float64  (ridership ÷ 22 weekdays; read by
                                   scripts/export_website_data.py)

Usage:
    python machine_learning_files/merge_pipeline.py
    python machine_learning_files/merge_pipeline.py --freq 15min --start 2020-01-01
"""

import argparse
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from pandas.tseries.holiday import USFederalHolidayCalendar

try:
    from machine_learning_files.bart_stations import CODE_TO_NAME, CODE_TO_WEATHER_STATION
except ImportError:  # run as a script from machine_learning_files/
    from bart_stations import CODE_TO_NAME, CODE_TO_WEATHER_STATION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("merge_pipeline")

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
CONFIG_PATH = Path("configs/sources.yaml")
MODEL_CONFIG_PATH = Path("configs/model.yaml")

# The six weather-monitoring locations in configs/sources.yaml
# (weather.station_coords) that name-match a BART station, keyed by the
# store's two-letter station_id, from the station table. "diridon" has no
# BART station -- it's a Caltrain/VTA hub -- so it stays unmapped and only
# contributes to the regional fallback average below.
STATION_TO_WEATHER_STATION = CODE_TO_WEATHER_STATION


def load_configs() -> tuple[dict, dict]:
    with open(CONFIG_PATH) as f:
        src_cfg = yaml.safe_load(f)
    with open(MODEL_CONFIG_PATH) as f:
        model_cfg = yaml.safe_load(f)
    return src_cfg, model_cfg


# ── Loaders ────────────────────────────────────────────────────────────────────

def _read_parquet_safe(path) -> pd.DataFrame | None:
    """
    Read one COVARIATE parquet file (weather/events), isolating a truncated or
    corrupt file so it cannot abort the whole load. Writes here are non-atomic,
    so a killed process can leave a corrupt file at its final path.

    Returns None on a corrupt file and leaves it in place: raw inputs are not
    always re-fetchable, so this never deletes. Only corrupt-file errors are
    caught (pyarrow raises ArrowInvalid, a ValueError, or an OSError); a
    missing parquet engine (ImportError) or MemoryError still propagates.
    Not used for the BART target: load_transit() must fail loudly.
    """
    try:
        return pd.read_parquet(path)
    except (OSError, ValueError) as e:
        log.warning(f"  Unreadable parquet file {path.name} ({e}) — skipping (file left in place)")
        return None


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

    # ── Target definition ──────────────────────────────────────────────────────
    # `ridership` is BART's actual monthly trip count for a station: the
    # "Total Trips" block, summed over destinations, keyed on the ENTRY station
    # (i.e. boardings originating there).
    #
    # The previous definition dropped that block and summed the three "Avg"
    # blocks instead. Those are average riders on a single day of each type, so
    # their sum is not a monthly quantity at all — it understated the real count
    # by a factor that varied 20x-39x per station-month, and it silently stripped
    # calendar effects (month length, weekday/weekend mix, holidays), which
    # flattered every error metric computed on it.
    #
    # BART's own identity confirms what each block holds, exactly for 2019-2023:
    #   avg_weekday x n_weekdays + avg_sat x n_saturdays + avg_sun x n_sundays
    #       == total_trips
    TOTAL_BLOCK = r"total"

    if "day_type" not in combined.columns:
        raise ValueError(
            "BART OD parquet files have no day_type column, so the Total Trips "
            "block cannot be identified. Rebuild them with "
            "machine_learning_files/bart_od_from_xlsx.py."
        )

    is_total = combined["day_type"].str.contains(TOTAL_BLOCK, case=False, na=False)

    # Every month must carry exactly one Total block. bart_od_from_csv.py builds
    # months from the three Avg sheets only and produces none, so a store built
    # or partly refreshed by it would otherwise yield an empty target and look
    # like a clean run with no data.
    blocks_per_period = (
        combined[is_total].groupby("period")["day_type"].nunique()
    )
    all_periods = pd.Index(combined["period"].unique())
    # A month with no Total block is absent from the groupby entirely, so it has
    # to be found by difference rather than by a count of zero.
    missing = all_periods.difference(blocks_per_period.index)
    multiple = blocks_per_period[blocks_per_period > 1]

    if len(missing) or len(multiple):
        detail = []
        if len(missing):
            detail.append(
                f"{len(missing)} month(s) with no Total block "
                f"(e.g. {[str(p)[:10] for p in missing[:3]]})"
            )
        if len(multiple):
            detail.append(
                f"{len(multiple)} month(s) with several "
                f"(e.g. {[str(p)[:10] for p in multiple.index[:3]]})"
            )
        raise ValueError(
            "Every month must carry exactly one 'Total' day_type block: "
            + "; ".join(detail)
            + ". Months built by bart_od_from_csv.py contain no Total block and "
              "cannot define this target — rebuild from the workbooks with "
              "machine_learning_files/bart_od_from_xlsx.py."
        )

    combined = combined[is_total]

    # Collapse destinations: total trips boarding at this station this month.
    station_monthly = (
        combined
        .groupby(["period", "origin", "origin_name"])["riders"]
        .sum()
        .reset_index()
        .rename(columns={"origin": "station_id", "origin_name": "station_name", "riders": "ridership"})
    )
    # Drop system-wide aggregate rows (e.g. "Exits") — not real station codes
    station_monthly = station_monthly[station_monthly["station_id"].str.len() <= 4]

    # Names come from the station table, whatever the raw parquets carry:
    # parquets built before it hold the code as origin_name. A station_id
    # missing from the table keeps its parquet name.
    unknown = sorted(set(station_monthly["station_id"]) - set(CODE_TO_NAME))
    if unknown:
        log.warning(f"  {len(unknown)} station_id(s) not in bart_stations.py, "
                    f"keeping the parquet's name: {unknown}")
    station_monthly["station_name"] = (
        station_monthly["station_id"].map(CODE_TO_NAME).fillna(station_monthly["station_name"])
    )

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
    # fetch_historical_all_stations() names its output
    # weather_all_stations_{start}_{end}.parquet, embedding the CLI --start/--end
    # args -- so a later backfill run with a narrower or differently-dated range
    # can sort lexicographically *before* an earlier, fuller run (same failure
    # mode documented on load_events() below). Load and concatenate every
    # historical file instead of just the lexicographically-last one, sorted by
    # actual file mtime (not filename -- a filename sort has no reliable
    # relationship to write recency once ranges overlap) so the dedup below
    # keeps the most-recently-written value for overlapping (timestamp, station)
    # rows.
    hist_files = sorted(
        (RAW_DIR / "weather").glob("weather_all_stations_*.parquet"),
        key=lambda p: p.stat().st_mtime,
    )
    # fetch_forecast_all_stations() writes the nightly 7-day-ahead forecast under a
    # separate "weather_forecast_*" prefix — it must be loaded too, or the pipeline's
    # only source of future-known weather covariates is silently dropped.
    forecast_files = sorted((RAW_DIR / "weather").glob("weather_forecast_*.parquet"))
    if not hist_files and not forecast_files:
        log.warning("No weather files found")
        return pd.DataFrame()

    # Tag each ROW with its own source FILE's mtime and sort by that before
    # dedup -- historical rows are concatenated ahead of forecast rows below
    # purely for readability, but that fixed order must not decide which
    # value keep="last" keeps. Without the mtime-based sort, a forecast row
    # always wins over a historical row for the same (timestamp, station)
    # even when the historical file was fetched *after* the forecast file
    # (e.g. a backfill re-run once Open-Meteo's archive catches up on a day
    # only a stale forecast file covered), silently overwriting an observed
    # value with a predicted one.
    #
    # hist_files can (and in production does) contain more than one file --
    # e.g. an original wide backfill plus one or more later, narrower
    # corrective re-fetches, none of which get cleaned up -- each written at
    # a different time. Tagging every row with a single group-wide
    # max(mtime across ALL hist_files) (as an earlier version of this fix
    # did) lets a row from an OLDER hist file silently borrow a completely
    # unrelated, newer hist file's mtime, so it can incorrectly "win" the
    # dedup over a genuinely fresher forecast row for the same key even
    # though the hist file that row actually came from predates that
    # forecast. Read and tag each hist file individually before
    # concatenating so every row carries its own source file's real mtime.
    frames = []
    if hist_files:
        hist_frames = []
        for f in hist_files:
            hdf = _read_parquet_safe(f)
            if hdf is None:
                continue
            hdf["_source_mtime"] = f.stat().st_mtime
            hist_frames.append(hdf)
        if hist_frames:
            hist_df = pd.concat(hist_frames, ignore_index=True)
            frames.append(hist_df)
    if forecast_files:
        forecast_file = forecast_files[-1]  # most recent forecast file
        forecast_df = _read_parquet_safe(forecast_file)
        if forecast_df is not None:
            forecast_df["_source_mtime"] = forecast_file.stat().st_mtime
            frames.append(forecast_df)
    if not frames:
        log.warning("No readable weather files found")
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    dedup_keys = [c for c in ("timestamp", "station") if c in df.columns]
    if dedup_keys:
        df = df.sort_values("_source_mtime").drop_duplicates(subset=dedup_keys, keep="last")
    df = df.drop(columns=["_source_mtime"])
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
    """
    Load and merge all events parquet files.

    fetch_events.py's fetch_all() names its output events_{start}_{end}.parquet
    for BOTH the one-time historical backfill (start=2019-01-01) and the nightly
    incremental fetch (start=today), so loading only the single most-recent file
    (by filename sort) permanently loses the historical file the moment a nightly
    run's filename first sorts after it -- every historical (year, month) then
    silently gets is_game_day=False/is_sharks_game=False/hours_to_event=0.0 in
    compute_event_features() below, zeroing out the Sharks-game signal across
    all of history. Load and concatenate every events_*.parquet file instead,
    sorted by actual file mtime (not filename -- a corrective re-fetch of an
    earlier date range writes a filename that sorts before a wider existing
    file regardless of which was actually written more recently), deduping
    on (timestamp_start, venue, event_name) so keep="last" below keeps the
    most-recently-written row, since NHL/Ticketmaster use different id
    columns (game_id vs event_id) that don't unify into one key.
    """
    log.info("Loading events data …")
    files = sorted(
        (RAW_DIR / "events").glob("events_*.parquet"),
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        log.warning("No events files found")
        return pd.DataFrame()

    frames, coverage = [], []
    for f in files:
        fdf = _read_parquet_safe(f)
        if fdf is None:
            continue
        frames.append(fdf)
        span = file_event_coverage(fdf, f)
        if span is not None:
            coverage.append(span)
    if not frames:
        log.warning("No readable events files found")
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["timestamp_start"] = pd.to_datetime(df["timestamp_start"])
    dedup_keys = [c for c in ("timestamp_start", "venue", "event_name") if c in df.columns]
    if dedup_keys:
        df = df.drop_duplicates(subset=dedup_keys, keep="last")
    if df["timestamp_start"].dt.tz is None:
        df["timestamp_start"] = df["timestamp_start"].dt.tz_localize("America/Los_Angeles")
    else:
        df["timestamp_start"] = df["timestamp_start"].dt.tz_convert("America/Los_Angeles")
    df.attrs["coverage"] = merge_coverage(coverage)

    log.info(f"  Loaded {len(df):,} events")
    return df


# ── Event archive coverage ─────────────────────────────────────────────────────
#
# A month with no event in the archive is only "no game" when the archive
# covers that month. Before it was added, a month no archive covered came out
# the same as an off-season month (False / 0 games), so a store rebuilt without
# the 2024-25 file would still have produced a Sharks row (docs/covariate-
# experiment.md). Coverage is a list of (first_day, last_day) spans carried on
# the events frame's .attrs["coverage"]; a month is covered only when the whole
# month lies inside one span.

_EVENT_FILE_RE = re.compile(r"events_\d{4}-\d{2}-\d{2}_(\d{4}-\d{2}-\d{2})\.parquet$")


def _wall_clock(ts: pd.Series) -> pd.Series:
    """Datetimes as tz-naive LA wall-clock, the value _year/_month bucketing uses."""
    ts = pd.to_datetime(ts)
    return ts.dt.tz_localize(None) if ts.dt.tz is not None else ts


def file_event_coverage(events: pd.DataFrame, path) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """
    The span one events file vouches for: from the first day of the month of its
    first event to the end date in its name (events_{start}_{end}.parquet).

    The start comes from the data, not the name: the 2019 file is named from
    2019-01-01 but its first game is 2019-09-17, so the months before September
    2019 were never fetched. The end comes from the name because the last game
    of a season says nothing about the off-season months after it; a name that
    does not parse falls back to the end of the last event's month. None when
    the file holds no events.
    """
    if events is None or events.empty or "timestamp_start" not in events.columns:
        return None
    ts = _wall_clock(events["timestamp_start"])
    start = ts.min().to_period("M").start_time
    match = _EVENT_FILE_RE.search(Path(path).name)
    end = pd.Timestamp(match.group(1)) if match else ts.max().to_period("M").end_time
    return start, end.normalize()


def merge_coverage(spans: list) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Sort spans and join overlapping or touching ones; a gap between files stays a gap."""
    merged: list[list[pd.Timestamp]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + pd.Timedelta(days=1):
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def event_coverage(events: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """
    Spans of months the events frame covers. The loaders record them in
    .attrs["coverage"]; for a frame built elsewhere, the span from its first to
    its last event month (months after the last game then read as unknown, the
    conservative side). Empty list: no archive, nothing is covered.
    """
    if events is None or events.empty:
        return []
    recorded = events.attrs.get("coverage")
    if recorded is not None:
        return list(recorded)
    ts = _wall_clock(events["timestamp_start"])
    return [(ts.min().to_period("M").start_time, ts.max().to_period("M").end_time.normalize())]


def months_covered(timestamps: pd.Series, coverage: list) -> np.ndarray:
    """True where the timestamp's whole calendar month lies inside one coverage span."""
    periods = _wall_clock(pd.Series(timestamps)).dt.to_period("M")
    first = periods.dt.start_time.to_numpy()
    last = periods.dt.end_time.dt.normalize().to_numpy()
    covered = np.zeros(len(periods), dtype=bool)
    for start, end in coverage:
        covered |= (first >= np.datetime64(start)) & (last <= np.datetime64(end))
    return covered


# ── Event feature computation ──────────────────────────────────────────────────

EVENT_FLAG_COLS = ("is_game_day", "is_sharks_game", "is_playoff")


def _event_frame(rows: list[dict], index) -> pd.DataFrame:
    """Rows of event features as a frame; flags are nullable boolean, so unknown stays <NA>."""
    out = pd.DataFrame(rows, index=index)
    for col in EVENT_FLAG_COLS:
        out[col] = out[col].astype("boolean")
    for col in ("hours_to_event", "game_start_hour"):
        out[col] = out[col].astype("float64")
    return out


_UNKNOWN_EVENT_ROW = {
    "is_game_day": pd.NA, "hours_to_event": np.nan, "is_sharks_game": pd.NA,
    "game_start_hour": np.nan, "is_playoff": pd.NA,
}


def unknown_event_features(index) -> pd.DataFrame:
    """Event columns for rows no events archive covers: <NA> / NaN, not False / 0."""
    return _event_frame([dict(_UNKNOWN_EVENT_ROW) for _ in range(len(index))], index)


def compute_event_features(
    timestamps: pd.Series,
    events: pd.DataFrame,
    venue_proximity_hrs: float = 4.0,
) -> pd.DataFrame:
    """
    Monthly aggregation: for each timestamp (month-start), count events in that month.
    - is_game_day    : True if >=1 event of ANY kind (Sharks game, concert, etc.)
                       from `events` fell in that month -- despite the name, this
                       is not scoped to home games specifically; use is_sharks_game
                       for that. hours_to_event/COVARIATE_GROUPS callers treat this
                       as a generic "any event this month" signal.
    - hours_to_event : number of events of any kind in that month (repurposed as event count)
    - is_sharks_game : True if any Sharks game in that month
    - game_start_hour: modal game start hour in that month
    - is_playoff     : True if any playoff game in that month

    A month the archive covers (event_coverage()) with no event is False / 0.0.
    A month it does not cover -- or any month, when there is no archive -- is
    unknown: <NA> flags and NaN counts, never False / 0.
    """
    if events.empty:
        return unknown_event_features(timestamps.index)

    ev = events.copy()
    ev_ts = _wall_clock(ev["timestamp_start"])
    # tz_convert(None) would shift to UTC before stripping the tz, pushing
    # evening LA events past midnight into the wrong month; _wall_clock drops
    # the tz label in place, preserving the LA wall-clock value that
    # _year/_month bucketing expects.
    ev["_year"]  = ev_ts.dt.year
    ev["_month"] = ev_ts.dt.month

    ts_series = _wall_clock(timestamps)
    covered = months_covered(ts_series, event_coverage(events))

    results = []
    for ts, is_covered in zip(ts_series, covered):
        if not is_covered:
            results.append(dict(_UNKNOWN_EVENT_ROW))
            continue
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

    return _event_frame(results, timestamps.index)


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
    # via `fillna()`, which label-aligns on the index rather than position —
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
        # No events archive: every month is unknown, not a month without a game.
        log.warning("No events archive: event columns are <NA> / NaN for every row")
        for col, values in unknown_event_features(base.index).items():
            base[col] = values

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


def make_splits(df: pd.DataFrame, train_end: str, val_end: str, train_start: str = None,
                *, test_end: str) -> None:
    """Chronological train/val/test split — no data leakage.

    train_start: optional lower bound for train set (excludes earlier years with data gaps).
    test_end: required upper bound of the test split (val_end < ts <= test_end),
        so a month added to the store after the test window never enters
        splits/test.parquet. Raises ValueError when it is missing.
    """
    if test_end is None or str(test_end).strip() == "":
        raise ValueError(
            "make_splits: data.test_end is missing from the config; the test split "
            "(val_end < ts <= test_end) needs an explicit end"
        )
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
    test_ts  = _ts(test_end)

    if train_start:
        start_ts = _ts(train_start)
        train_mask = (ts >= start_ts) & (ts <= train_ts)
        log.info(f"  train_start filter: {train_start} — excluding data before this date")
    else:
        train_mask = ts <= train_ts

    val_mask  = (ts > train_ts) & (ts <= val_ts)
    test_mask = (ts > val_ts) & (ts <= test_ts)

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
            test_end=model_cfg["data"].get("test_end"),
        )

    log.info("Pipeline complete.")


if __name__ == "__main__":
    main()
