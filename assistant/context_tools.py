"""Context tools: service alerts, weather, nearby events and station context.

Each tool answers one question about the trip and none of them can change a
time or duration (those come only from Google Routes). ``gather_context`` runs
them concurrently, each under ``Settings.TOOL_TIMEOUT_S``; a tool that fails or
runs late contributes its name to ``Context.missing`` and never raises.

Secrets travel in query strings (511 token, Ticketmaster key), so HTTP errors
are re-raised as ``ToolError`` with only the host and status, never the URL.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

from assistant import station_data
from assistant.config import DISPLAY_TZ, Settings
from assistant.routing import normalise_agency
from assistant.types import (
    Alert,
    Context,
    Event,
    StationContext,
    TripOption,
    TripQuery,
    Weather,
)

log = logging.getLogger("assistant.context")

ALERTS_URL = "https://api.511.org/transit/servicealerts"
ALERTS_FEED = "RG"  # the regional feed carries every Bay Area agency
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
NHL_WEEK_URL = "https://api-web.nhle.com/v1/club-schedule/SJS/week/{date}"
TICKETMASTER_URL = "https://app.ticketmaster.com/discovery/v2/events.json"

# Copied from machine_learning_files/fetch_events.py VENUE_COORDS["sap_center"]
# (that module needs pandas, which the assistant image does not install); a
# test keeps the two in step.
SAP_CENTER = (37.3327, -121.9010)
EVENT_RADIUS_KM = 1.5
EVENT_WINDOW = timedelta(hours=3)
DEDUPE_WINDOW = timedelta(minutes=5)
DEDUPE_KM = 0.3

CACHE_TTL_S = 300
SCHEDULE_TTL_S = 3600
MAX_STATIONS = 4

# 511 names agencies by two-letter id; ``normalise_agency`` works on names.
_AGENCY_511_NAMES = {
    "BA": "Bay Area Rapid Transit",
    "CT": "Caltrain",
    "SC": "VTA",
}


class ToolError(Exception):
    """A context tool could not produce a result. Safe to log: no secrets."""


class TTLCache:
    """Tiny in-process cache whose entries expire ``ttl_s`` seconds after ``set``."""

    def __init__(self, ttl_s: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_s
        self._clock = clock
        self._items: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        hit = self._items.get(key)
        if hit is None:
            return None
        stored_at, value = hit
        if self._clock() - stored_at >= self._ttl:
            del self._items[key]
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        self._items[key] = (self._clock(), value)

    def clear(self) -> None:
        self._items.clear()


_alerts_cache = TTLCache(CACHE_TTL_S)
_weather_cache = TTLCache(CACHE_TTL_S)
_schedule_cache = TTLCache(SCHEDULE_TTL_S)


def clear_caches() -> None:
    for cache in (_alerts_cache, _weather_cache, _schedule_cache):
        cache.clear()


async def _get(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> httpx.Response:
    host = httpx.URL(url).host
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ToolError(f"{host} answered HTTP {exc.response.status_code}") from None
    except httpx.HTTPError as exc:
        raise ToolError(f"{host} request failed ({type(exc).__name__})") from None
    return response


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def _utc(when: datetime) -> datetime:
    if when.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return when.astimezone(timezone.utc)


# --- 511 service alerts -------------------------------------------------------


@dataclass(frozen=True)
class _FeedAlert:
    agency_ids: frozenset[str]
    header: str
    periods: tuple[tuple[int, int], ...]  # (start, end) epoch seconds, 0 = open

    def active(self, at: int) -> bool:
        if not self.periods:
            return True
        return any((s == 0 or s <= at) and (e == 0 or at <= e) for s, e in self.periods)


def _header(alert: Any) -> str:
    translations = list(alert.header_text.translation)
    for t in translations:
        if t.language in ("en", ""):
            return t.text.strip()
    return translations[0].text.strip() if translations else ""


def _parse_feed(content: bytes) -> tuple[_FeedAlert, ...]:
    from google.transit import gtfs_realtime_pb2

    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        feed.ParseFromString(content)
    except Exception:
        raise ToolError("511 alerts feed was not GTFS-realtime protobuf") from None
    entries = []
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        alert = entity.alert
        header = _header(alert)
        ids = frozenset(ie.agency_id for ie in alert.informed_entity if ie.agency_id)
        if not header or not ids:
            continue
        periods = tuple(
            (p.start if p.HasField("start") else 0, p.end if p.HasField("end") else 0)
            for p in alert.active_period
        )
        entries.append(_FeedAlert(ids, header, periods))
    return tuple(entries)


def _agency_label(agency_id: str) -> str:
    return normalise_agency(_AGENCY_511_NAMES.get(agency_id, agency_id))


async def service_alerts(
    agencies: set[str],
    client: httpx.AsyncClient,
    token: str,
    *,
    now: datetime | None = None,
) -> tuple[Alert, ...]:
    """Active 511 alerts for ``agencies`` (labels such as ``"BART"``), deduplicated.

    ``now`` exists so tests can pin "active" to the recording's own time.
    """
    if not agencies:
        return ()
    if not token:
        raise ToolError("no 511 token configured")
    entries = _alerts_cache.get(ALERTS_FEED)
    if entries is None:
        response = await _get(client, ALERTS_URL, {"agency": ALERTS_FEED, "api_key": token})
        entries = _parse_feed(response.content)
        _alerts_cache.set(ALERTS_FEED, entries)
    at = int((now or datetime.now(timezone.utc)).timestamp())
    seen: set[tuple[str, str]] = set()
    out: list[Alert] = []
    for entry in entries:
        if not entry.active(at):
            continue
        for label in sorted({_agency_label(i) for i in entry.agency_ids} & agencies):
            if (label, entry.header) not in seen:
                seen.add((label, entry.header))
                out.append(Alert(agency=label, header=entry.header))
    return tuple(out)


# --- weather ------------------------------------------------------------------


async def weather(lat: float, lng: float, when: datetime, client: httpx.AsyncClient) -> Weather:
    """Open-Meteo forecast for the hour nearest ``when``."""
    target = _utc(when)
    key = (round(lat, 2), round(lng, 2), target.date().isoformat())
    hourly = _weather_cache.get(key)
    if hourly is None:
        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lng:.4f}",
            "hourly": "temperature_2m,precipitation,wind_speed_10m",
            "timezone": "UTC",
            "start_date": target.date().isoformat(),
            "end_date": (target.date() + timedelta(days=1)).isoformat(),
        }
        response = await _get(client, WEATHER_URL, params)
        try:
            hourly = response.json()["hourly"]
            hourly = {k: hourly[k] for k in ("time", "temperature_2m", "precipitation", "wind_speed_10m")}
        except (ValueError, KeyError, TypeError):
            raise ToolError("Open-Meteo answered with an unexpected shape") from None
        _weather_cache.set(key, hourly)
    try:
        times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in hourly["time"]]
        if not times:
            raise ValueError("no hours")
        i = min(range(len(times)), key=lambda n: abs(times[n] - target))
        if abs(times[i] - target) > timedelta(hours=2):
            raise ValueError("forecast does not cover the requested time")
        precip, temp, wind = hourly["precipitation"][i], hourly["temperature_2m"][i], hourly["wind_speed_10m"][i]
        return Weather(precip_mm=float(precip), temp_c=float(temp), wind_kmh=float(wind))
    except (ValueError, TypeError, IndexError):
        raise ToolError("Open-Meteo forecast did not cover the requested hour") from None


# --- events -------------------------------------------------------------------


def _sharks_events(schedule: dict[str, Any]) -> list[Event]:
    events = []
    for game in schedule.get("games", []):
        if game.get("homeTeam", {}).get("abbrev") != "SJS":
            continue
        if game.get("gameScheduleState", "OK") != "OK":
            continue
        try:
            start = datetime.fromisoformat(game["startTimeUTC"].replace("Z", "+00:00"))
            away = game["awayTeam"]
            opponent = f"{away['placeName']['default']} {away['commonName']['default']}".strip()
            venue = game["venue"]["default"]
        except (KeyError, TypeError, ValueError):
            continue
        events.append(Event(name=f"Sharks vs {opponent}", venue=venue, start=start, distance_km=0.0))
    return events


async def _nhl_events(lat: float, lng: float, when: datetime, client: httpx.AsyncClient) -> list[Event]:
    point = (lat, lng)
    km = _haversine_km(point, SAP_CENTER)
    if km > EVENT_RADIUS_KM:
        return []  # no Sharks home game can be near this point: skip the request
    day = (when.astimezone(ZoneInfo(DISPLAY_TZ)) - timedelta(days=1)).date().isoformat()
    schedule = _schedule_cache.get(day)
    if schedule is None:
        response = await _get(client, NHL_WEEK_URL.format(date=day), {})
        try:
            schedule = response.json()
        except ValueError:
            raise ToolError("NHL schedule was not JSON") from None
        _schedule_cache.set(day, schedule)
    return [
        Event(e.name, e.venue, e.start, round(km, 3))
        for e in _sharks_events(schedule)
        if abs(e.start - when) <= EVENT_WINDOW
    ]


async def _ticketmaster_events(
    lat: float, lng: float, when: datetime, client: httpx.AsyncClient, key: str
) -> list[Event]:
    stamp = "%Y-%m-%dT%H:%M:%SZ"
    params = {
        "apikey": key,
        "latlong": f"{lat:.4f},{lng:.4f}",
        "radius": 2,
        "unit": "km",
        "startDateTime": (when - EVENT_WINDOW).strftime(stamp),
        "endDateTime": (when + EVENT_WINDOW).strftime(stamp),
        "size": 20,
        "sort": "date,asc",
    }
    response = await _get(client, TICKETMASTER_URL, params)
    try:
        raw = response.json().get("_embedded", {}).get("events", [])
    except (ValueError, AttributeError):
        raise ToolError("Ticketmaster answered with an unexpected shape") from None
    events = []
    for item in raw:
        try:
            stamp_text = item["dates"]["start"]["dateTime"]  # TBD-time events carry only localDate
            start = datetime.fromisoformat(stamp_text.replace("Z", "+00:00"))
            venue = item["_embedded"]["venues"][0]
            place = (float(venue["location"]["latitude"]), float(venue["location"]["longitude"]))
            name, venue_name = item["name"], venue["name"]
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        km = _haversine_km((lat, lng), place)
        if km <= EVENT_RADIUS_KM and abs(start - when) <= EVENT_WINDOW:
            events.append(Event(name, venue_name, start, round(km, 3)))
    return events


async def events_near(
    lat: float,
    lng: float,
    when: datetime,
    client: httpx.AsyncClient,
    tm_key: str | None,
) -> tuple[Event, ...]:
    """Sharks home games (NHL) and, with a key, Ticketmaster events near the point.

    Within 1.5 km and +-3 h of ``when``. Without ``tm_key`` Ticketmaster is
    skipped, not reported as missing: it was never configured.
    """
    when = _utc(when)
    events = await _nhl_events(lat, lng, when, client)
    if tm_key:
        for event in await _ticketmaster_events(lat, lng, when, client, tm_key):
            duplicate = any(abs(event.start - known.start) <= DEDUPE_WINDOW for known in events)
            if not duplicate:
                events.append(event)
    events.sort(key=lambda e: e.start)
    return tuple(events)


# --- station context ----------------------------------------------------------


def station_context(name: str) -> StationContext | None:
    """Monthly ridership context for a BART station, or ``None`` if unknown or ambiguous."""
    record = station_data.find_station(name)
    if record is None:
        return None
    return StationContext(
        station=record["name"],
        typical_monthly=record["typical_monthly"],
        forecast_month=record["forecast_month"],
        forecast_p50=record["forecast_p50"],
        label=station_data.LABEL,
    )


def _bart_stop_names(option: TripOption) -> list[str]:
    names: list[str] = []
    for leg in option.legs:
        if leg.mode == "TRANSIT" and leg.agency == "BART":
            for stop in (leg.from_stop, leg.to_stop):
                if stop and stop not in names:
                    names.append(stop)
    return names[:MAX_STATIONS]


async def _stations(options: list[TripOption]) -> tuple[StationContext, ...]:
    # One thread per name: the lookup is synchronous, and a thread per call
    # keeps it from holding up the event loop or the other tools.
    names = _bart_stop_names(options[0])
    found = await asyncio.gather(*(asyncio.to_thread(station_context, n) for n in names))
    unique: dict[str, StationContext] = {}
    for item in found:
        if item is not None:
            unique.setdefault(item.station, item)
    return tuple(unique.values())


# --- gather -------------------------------------------------------------------


async def _bounded(name: str, call: Any, timeout_s: float) -> tuple[str, Any, bool]:
    """Run one tool under the timeout. Returns ``(name, result, ok)``; never raises."""
    try:
        return name, await asyncio.wait_for(call, timeout_s), True
    except asyncio.TimeoutError:
        log.warning("context tool %s timed out after %.1fs", name, timeout_s)
    except Exception as exc:  # a tool must not take the answer down with it
        log.warning("context tool %s failed: %s", name, type(exc).__name__)
    return name, None, False


async def gather_context(
    options: list[TripOption],
    q: TripQuery,
    client: httpx.AsyncClient,
    settings: Settings,
) -> Context:
    """Run the four tools concurrently; each gets ``settings.TOOL_TIMEOUT_S``.

    Weather is for the origin at departure (the walk to the first stop), events
    for the destination at arrival. ``q`` is accepted for symmetry with routing.
    """
    if not options:
        return Context(alerts=(), weather=None, events=(), stations=(), missing=())
    top = options[0]
    agencies = {a for option in options for a in option.agencies}
    timeout = settings.TOOL_TIMEOUT_S
    results = await asyncio.gather(
        _bounded("alerts", service_alerts(agencies, client, settings.TOKEN_511), timeout),
        _bounded("weather", weather(*top.origin_latlng, top.depart, client), timeout),
        _bounded("events", events_near(*top.dest_latlng, top.arrive, client, settings.TICKETMASTER_KEY), timeout),
        _bounded("stations", _stations(options), timeout),
    )
    got = {name: value for name, value, ok in results if ok}
    return Context(
        alerts=got.get("alerts", ()),
        weather=got.get("weather"),
        events=got.get("events", ()),
        stations=got.get("stations", ()),
        missing=tuple(name for name, _, ok in results if not ok),
    )
