"""
machine_learning_files/ingest_fetch.py
──────────────────────────────────────
Step 1 of the cloud ingestion job (docs/cloud-ingestion-design.md §2): fetch
closed-month weather and Sharks data into the bucket.

    last_closed_month_end(today, lag_days)   last day of the newest closed month
    fetch_window(today, floor)               (start, end) to fetch, or None
    fetch_weather(store, cfg, today, client=None)  -> list[FetchResult]
    fetch_sharks(store, cfg, today, client=None)   -> list[FetchResult]

One `FetchResult` per source per calendar year in the window (a window that
crosses New Year, e.g. a run in February 2027, writes a 2026 and a 2027 object).

What is fetched
───────────────
Only closed months: a month whose last day is at least `archive_lag_days`
(configs/ingest.yaml, 7) before `today`, because Open-Meteo's archive lags the
present. Never before `fetch_floor` (2026-01-01), so the hand-seeded 2019-2025
archives are never fetched again, replaced or deleted.

Objects
───────
One object per source per year, named exactly as merge_pipeline's loaders read
them (they glob `weather_all_stations_*.parquet` and `events_*.parquet`):

    raw/weather/weather_all_stations_<start>_<end>.parquet
    raw/events/events_<start>_<end>.parquet

where <start>/<end> are the dates actually covered (honest names). The
loaders concatenate every file and de-duplicate, so objects never need merging.

Rules, each tested in tests/test_ingest_fetch.py
────────────────────────────────────────────────
* An existing object for the same year whose range already covers the window
  is left alone and nothing is fetched: rewriting identical data would bump the
  object's generation, change the input fingerprint every night, and the job
  would never report "unchanged".
* A newer same-year object replaces the older one: the new object is written
  first (if_generation_match=0), then each older same-year object is deleted
  under its own generation. Only objects that start on or after `fetch_floor`
  and lie inside one calendar year are ever candidates.
* Never replace an object with one that has fewer rows. (`NHLClient` logs and
  swallows a failing season instead of raising, so a partial answer looks like
  success.) Status "refused"; nothing is written or deleted.
* A fetch failure writes nothing. Weather needs every location: one failed or
  short location fails the whole year, since a missing station would silently
  shift the regional average that fills other stations' months.
* `store.dry_run` true (cloud_ingest --dry-run) fetches but writes nothing.

Not covered: `NHLClient._seasons_in_range` treats a season as starting on
1 October, so September preseason games are only visible to a query whose end
date reaches 1 October. `_sharks_query_end` widens the query to that day and the
result is cut back to the window, so a window ending 30 September still gets
September's games.
"""

from __future__ import annotations

import calendar
import datetime as dt
import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
import yaml

from machine_learning_files.cloud_store import ObjInfo, PreconditionFailed

log = logging.getLogger("machine_learning_files.ingest_fetch")

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES_CONFIG_PATH = REPO_ROOT / "configs" / "sources.yaml"

DEFAULT_ARCHIVE_LAG_DAYS = 7
DEFAULT_FETCH_FLOOR = dt.date(2026, 1, 1)

WEATHER_PREFIX = "raw/weather/"
WEATHER_STEM = "weather_all_stations"
EVENTS_PREFIX = "raw/events/"
EVENTS_STEM = "events"

# A location's year of hourly rows must have no holes in these.
_WEATHER_NO_NAN = ("temp_f", "precip_mm")

# Statuses. "refused" and "failed" are failures (the job exits 2).
WRITTEN = "written"
UNCHANGED = "unchanged"
SKIPPED = "skipped"
REFUSED = "refused"
FAILED = "failed"
DRY_RUN = "dry-run"


@dataclass(frozen=True)
class FetchResult:
    source: str            # "weather" | "sharks"
    object_name: str       # the object this result is about ("" if none)
    rows: int              # rows in that object (or that would be written)
    status: str            # written | unchanged | skipped | refused | failed | dry-run
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.status in (FAILED, REFUSED)

    def to_dict(self) -> dict:
        return {"source": self.source, "object_name": self.object_name, "rows": self.rows,
                "status": self.status, "detail": self.detail}


# ── the window ────────────────────────────────────────────────────────────────

def _as_date(value) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def _month_end(d: dt.date) -> dt.date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def last_closed_month_end(today, lag_days: int = DEFAULT_ARCHIVE_LAG_DAYS) -> dt.date:
    """The last day of the newest month that ended at least `lag_days` before
    `today`: the latest month-end <= today - lag_days.

    2026-10-28, 7 -> 2026-09-30.  2026-11-07, 7 -> 2026-10-31 (ended exactly
    7 days ago).  2026-11-06, 7 -> 2026-09-30.
    """
    cutoff = _as_date(today) - dt.timedelta(days=int(lag_days))
    if cutoff == _month_end(cutoff):
        return cutoff
    return cutoff.replace(day=1) - dt.timedelta(days=1)


def fetch_window(today, floor=DEFAULT_FETCH_FLOOR,
                 lag_days: int = DEFAULT_ARCHIVE_LAG_DAYS) -> Optional[tuple[dt.date, dt.date]]:
    """(start, end) of what to fetch: `floor` through the last closed month's end.
    None when no month at or after `floor` has closed yet."""
    floor = _as_date(floor)
    end = last_closed_month_end(today, lag_days)
    if end < floor:
        return None
    return floor, end


def year_windows(today, floor=DEFAULT_FETCH_FLOOR,
                 lag_days: int = DEFAULT_ARCHIVE_LAG_DAYS) -> list[tuple[dt.date, dt.date]]:
    """`fetch_window` cut at New Year: one (start, end) per calendar year."""
    window = fetch_window(today, floor, lag_days)
    if window is None:
        return []
    start, end = window
    return [(max(start, dt.date(y, 1, 1)), min(end, dt.date(y, 12, 31)))
            for y in range(start.year, end.year + 1)]


def _window_from_cfg(cfg: dict, today) -> list[tuple[dt.date, dt.date]]:
    return year_windows(today,
                        cfg.get("fetch_floor", DEFAULT_FETCH_FLOOR),
                        int(cfg.get("archive_lag_days", DEFAULT_ARCHIVE_LAG_DAYS)))


def _sources_cfg(cfg: dict) -> dict:
    """configs/sources.yaml as a dict: cfg['sources'] if given (tests), else the file."""
    if isinstance(cfg.get("sources"), dict):
        return cfg["sources"]
    with open(cfg.get("sources_config", SOURCES_CONFIG_PATH)) as f:
        return yaml.safe_load(f)


# ── objects ───────────────────────────────────────────────────────────────────

def object_name(prefix: str, stem: str, start: dt.date, end: dt.date) -> str:
    return f"{prefix}{stem}_{start.isoformat()}_{end.isoformat()}.parquet"


def _same_year_objects(store, prefix: str, stem: str, year: int,
                       floor: dt.date) -> list[tuple[ObjInfo, dt.date, dt.date]]:
    """Objects this module may replace: named <stem>_<start>_<end>.parquet, start
    on or after the floor, start and end in `year`. The seeded multi-year
    archives and anything below the floor never match."""
    pattern = re.compile(
        rf"^{re.escape(prefix + stem)}_(\d{{4}}-\d{{2}}-\d{{2}})_(\d{{4}}-\d{{2}}-\d{{2}})\.parquet$")
    out = []
    for info in store.list(prefix + stem + "_"):
        m = pattern.match(info.name)
        if not m:
            continue
        try:
            s, e = dt.date.fromisoformat(m.group(1)), dt.date.fromisoformat(m.group(2))
        except ValueError:
            continue
        if s >= floor and s.year == year and e.year == year and s <= e:
            out.append((info, s, e))
    return out


def _parquet_rows(data: bytes) -> int:
    import pyarrow.parquet as pq
    return int(pq.ParquetFile(io.BytesIO(data)).metadata.num_rows)


def _existing_rows(store, info: ObjInfo) -> int:
    """Row count of an existing object; 0 if it vanished or cannot be read (a
    corrupt object is not worth protecting)."""
    got = store.read_bytes(info.name)
    if got is None:
        return 0
    try:
        return _parquet_rows(got[0])
    except Exception as e:  # noqa: BLE001
        log.warning("existing object %s is unreadable (%s); treating it as empty", info.name, e)
        return 0


def _to_parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def _sync_year(store, *, source: str, prefix: str, stem: str, start: dt.date, end: dt.date,
               floor: dt.date, fetch: Callable[[dt.date, dt.date], pd.DataFrame]) -> FetchResult:
    """Bring one source's one-year object up to `end`. Never raises."""
    name = object_name(prefix, stem, start, end)
    try:
        existing = _same_year_objects(store, prefix, stem, start.year, floor)

        for info, s, e in existing:
            if s <= start and e >= end:
                return FetchResult(source, info.name, _existing_rows(store, info), UNCHANGED,
                                   f"{info.name} already covers {start}..{end}; nothing fetched")

        df = fetch(start, end)
        rows = len(df)
        previous = [(info, _existing_rows(store, info)) for info, _, _ in existing]
        largest = max((n for _, n in previous), default=0)
        if rows < largest:
            return FetchResult(source, name, rows, REFUSED,
                               f"fetched {rows} rows, fewer than the {largest} in "
                               f"{', '.join(i.name for i, _ in previous)}; nothing written or deleted")

        if getattr(store, "dry_run", False):
            return FetchResult(source, name, rows, DRY_RUN,
                               f"would write {name}" + (
                                   f" and delete {', '.join(i.name for i, _ in previous)}" if previous else ""))

        try:
            store.write_bytes(name, _to_parquet_bytes(df), if_generation_match=0)
        except PreconditionFailed:
            return FetchResult(source, name, rows, UNCHANGED,
                               f"{name} was written by another execution first")

        deleted = []
        for info, _ in previous:
            if info.name == name:
                continue
            try:
                store.delete(info.name, if_generation_match=info.generation)
                deleted.append(info.name)
            except PreconditionFailed:
                log.warning("%s changed while being replaced; left in place", info.name)
        detail = f"wrote {name}" + (f"; deleted {', '.join(deleted)}" if deleted else "")
        return FetchResult(source, name, rows, WRITTEN, detail)
    except Exception as e:  # noqa: BLE001 - one source's failure must not stop the job
        log.exception("%s fetch for %s..%s failed", source, start, end)
        return FetchResult(source, name, 0, FAILED, f"{type(e).__name__}: {e}")


# ── weather ───────────────────────────────────────────────────────────────────

def fetch_weather(store, cfg: dict, today, client=None) -> list[FetchResult]:
    """Hourly Open-Meteo weather for the 7 locations in configs/sources.yaml
    (`weather.station_coords`), one `weather_all_stations_*` object per year.

    `client` is anything with OpenMeteoClient's `get_historical(lat, lng, start,
    end)`; default is a real OpenMeteoClient. `cfg` is configs/ingest.yaml.
    """
    windows = _window_from_cfg(cfg, today)
    if not windows:
        return [FetchResult("weather", "", 0, SKIPPED, "no closed month at or after fetch_floor")]
    floor = _as_date(cfg.get("fetch_floor", DEFAULT_FETCH_FLOOR))

    coords = _sources_cfg(cfg)["weather"]["station_coords"]
    if client is None:
        from machine_learning_files.fetch_weather_openmeteo import OpenMeteoClient
        client = OpenMeteoClient()

    def fetch(start: dt.date, end: dt.date) -> pd.DataFrame:
        expected = ((end - start).days + 1) * 24
        frames = []
        for station, c in coords.items():
            df = client.get_historical(c["lat"], c["lng"], start, end).copy()
            if len(df) != expected:
                raise ValueError(f"{station}: {len(df)} hourly rows for {start}..{end}, expected {expected}")
            holes = [col for col in _WEATHER_NO_NAN if col in df.columns and df[col].isna().any()]
            if holes:
                raise ValueError(f"{station}: missing values in {holes} for {start}..{end}")
            df["station"] = station
            frames.append(df)
        return pd.concat(frames, ignore_index=True)

    return [_sync_year(store, source="weather", prefix=WEATHER_PREFIX, stem=WEATHER_STEM,
                       start=s, end=e, floor=floor, fetch=fetch) for s, e in windows]


# ── Sharks ────────────────────────────────────────────────────────────────────

def _sharks_query_end(end: dt.date) -> dt.date:
    """NHLClient only visits a season whose assumed 1 October start is on or
    before the query end. Reach 1 October of end's year so a window closing
    in September sees that September's preseason games."""
    return max(end, dt.date(end.year, 10, 1))


def fetch_sharks(store, cfg: dict, today, client=None) -> list[FetchResult]:
    """San Jose Sharks home games at SAP Center, one `events_*` object per year.

    `client` is anything with NHLClient's `get_schedule(team, start, end)`;
    default is a real NHLClient. Rows go through fetch_events.enrich_events, as
    fetch_all() does. Ticketmaster is not used (no key).
    """
    windows = _window_from_cfg(cfg, today)
    if not windows:
        return [FetchResult("sharks", "", 0, SKIPPED, "no closed month at or after fetch_floor")]
    floor = _as_date(cfg.get("fetch_floor", DEFAULT_FETCH_FLOOR))

    team = cfg.get("sharks_team_id") or _sources_cfg(cfg)["nhl"]["sharks_team_id"]
    from machine_learning_files.fetch_events import enrich_events
    if client is None:
        from machine_learning_files.fetch_events import NHLClient
        client = NHLClient()

    def fetch(start: dt.date, end: dt.date) -> pd.DataFrame:
        games = client.get_schedule(team, start, _sharks_query_end(end))
        if games is None or games.empty:
            raise ValueError(
                f"the NHL schedule returned no home games for {start}..{end} "
                "(NHLClient logs and swallows a failing season, so this may be an outage)")
        ts = pd.to_datetime(games["timestamp_start"])
        local = ts.dt.tz_convert("America/Los_Angeles") if ts.dt.tz is not None else ts
        day = local.dt.date
        games = games[(day >= start) & (day <= end)]
        if games.empty:
            raise ValueError(f"no home games between {start} and {end} after trimming the query")
        out = enrich_events(games)
        return out.sort_values("timestamp_start").reset_index(drop=True)

    return [_sync_year(store, source="sharks", prefix=EVENTS_PREFIX, stem=EVENTS_STEM,
                       start=s, end=e, floor=floor, fetch=fetch) for s, e in windows]
