"""Trip planning through the Google Routes API (transit mode only).

Every time and duration the assistant shows comes from here, and so from
Google: leg departure and arrival times are Google's own stop times, and a
trip's start and end are those times extended by the walking Google reports
before the first and after the last vehicle.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from assistant.config import DISPLAY_TZ
from assistant.types import Leg, TripOption, TripQuery

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Limited to what TripOption and Leg need: Google bills the Routes call by the
# fields requested and the response stays small.
FIELD_MASK = ",".join(
    [
        "routes.duration",
        "routes.distanceMeters",
        "routes.polyline.encodedPolyline",
        "routes.legs.startLocation",
        "routes.legs.endLocation",
        "routes.legs.steps.travelMode",
        "routes.legs.steps.staticDuration",
        "routes.legs.steps.transitDetails.stopDetails.departureStop.name",
        "routes.legs.steps.transitDetails.stopDetails.arrivalStop.name",
        "routes.legs.steps.transitDetails.stopDetails.departureTime",
        "routes.legs.steps.transitDetails.stopDetails.arrivalTime",
        "routes.legs.steps.transitDetails.headsign",
        "routes.legs.steps.transitDetails.transitLine.name",
        "routes.legs.steps.transitDetails.transitLine.nameShort",
        "routes.legs.steps.transitDetails.transitLine.agencies.name",
    ]
)

AREA_SUFFIX = ", San Francisco Bay Area, CA"
MAX_OPTIONS = 3
# The plan allows the Routes call 2.5 s (the 1.5 s Settings.TOOL_TIMEOUT_S is
# for the context tools); callers may override it.
ROUTES_TIMEOUT_S = 2.5
SAME_PLACE_M = 150.0


class RoutingError(Exception):
    """Google Routes failed, timed out, or answered with something unparseable."""


def normalise_agency(name: str) -> str:
    """Map a Google agency name to BART, VTA, Caltrain, or other."""
    n = (name or "").casefold()
    if "bart" in n.split() or "bay area rapid" in n or n == "bart":
        return "BART"
    if "vta" in n.split() or "valley transportation" in n:
        return "VTA"
    if "caltrain" in n or "peninsula corridor" in n:
        return "Caltrain"
    return "other"


def _address(text: str) -> str:
    text = text.strip()
    return text if "," in text else text + AREA_SUFFIX


def _seconds(duration: str | None) -> int:
    """Parse a protobuf duration string such as ``"840s"``."""
    if not duration:
        return 0
    return int(round(float(duration.rstrip("s"))))


def _when(stamp: str | None, tz: ZoneInfo) -> datetime | None:
    if not stamp:
        return None
    return datetime.fromisoformat(stamp).astimezone(tz)


def _latlng(location: dict[str, Any]) -> tuple[float, float]:
    point = location["latLng"]
    return (float(point["latitude"]), float(point["longitude"]))


def _parse_route(route: dict[str, Any], q: TripQuery, tz: ZoneInfo) -> TripOption | None:
    leg0 = route["legs"][0]
    legs: list[Leg] = []
    walk_run = 0
    walk_total = 0

    def flush_walk() -> None:
        nonlocal walk_run
        if walk_run:
            legs.append(Leg("WALK", None, None, None, None, None, None, walk_run, None))
            walk_run = 0

    for step in leg0.get("steps", []):
        details = step.get("transitDetails")
        if details is None:
            seconds = _seconds(step.get("staticDuration"))
            walk_run += seconds
            walk_total += seconds
            continue
        flush_walk()
        stops = details.get("stopDetails", {})
        line = details.get("transitLine", {})
        agencies = line.get("agencies") or [{}]
        legs.append(
            Leg(
                mode="TRANSIT",
                agency=normalise_agency(agencies[0].get("name", "")),  # type: ignore[arg-type]
                line=line.get("nameShort") or line.get("name"),
                from_stop=stops.get("departureStop", {}).get("name"),
                to_stop=stops.get("arrivalStop", {}).get("name"),
                depart=_when(stops.get("departureTime"), tz),
                arrive=_when(stops.get("arrivalTime"), tz),
                duration_s=_seconds(step.get("staticDuration")),
                headsign=details.get("headsign"),
            )
        )
    flush_walk()

    transit = [leg for leg in legs if leg.mode == "TRANSIT"]
    if not transit or transit[0].depart is None or transit[-1].arrive is None:
        # Walking only: not a transit option, so it is not offered.
        return None
    lead = legs[0].duration_s if legs[0].mode == "WALK" else 0
    trail = legs[-1].duration_s if legs[-1].mode == "WALK" else 0
    depart = transit[0].depart - timedelta(seconds=lead)
    arrive = transit[-1].arrive + timedelta(seconds=trail)
    agencies_seen: list[str] = []
    for leg in transit:
        if leg.agency not in agencies_seen:
            agencies_seen.append(leg.agency)  # type: ignore[arg-type]
    return TripOption(
        rank=0,
        depart=depart,
        arrive=arrive,
        duration_s=int((arrive - depart).total_seconds()),
        transfers=len(transit) - 1,
        walk_s=walk_total,
        agencies=tuple(agencies_seen),
        legs=tuple(legs),
        polyline=route.get("polyline", {}).get("encodedPolyline", ""),
        origin_latlng=_latlng(leg0["startLocation"]),
        dest_latlng=_latlng(leg0["endLocation"]),
    )


async def plan_trips(
    q: TripQuery,
    client: httpx.AsyncClient,
    api_key: str,
    timeout_s: float = ROUTES_TIMEOUT_S,
) -> list[TripOption]:
    """Up to three transit options, best arrival first; ``[]`` when none exist.

    Raises ``RoutingError`` on an HTTP error, a timeout, or an unreadable body.
    The key travels in a header and is never put in an error message.
    """
    body = {
        "origin": {"address": _address(q.origin)},
        "destination": {"address": _address(q.destination)},
        "travelMode": "TRANSIT",
        "computeAlternativeRoutes": True,
        "departureTime": q.depart_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK}
    try:
        response = await client.post(ROUTES_URL, json=body, headers=headers, timeout=timeout_s)
        response.raise_for_status()
        payload = response.json()
    except httpx.TimeoutException as exc:
        raise RoutingError("Google Routes timed out") from exc
    except httpx.HTTPStatusError as exc:
        raise RoutingError(f"Google Routes returned HTTP {exc.response.status_code}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise RoutingError(f"Google Routes request failed: {type(exc).__name__}") from exc

    tz = ZoneInfo(DISPLAY_TZ)
    try:
        parsed = [
            option
            for route in payload.get("routes", [])
            if (option := _parse_route(route, q, tz)) is not None
        ]
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        raise RoutingError("Google Routes response had an unexpected shape") from exc

    # Rank by arrival time: Google's own "duration" leaves out the wait for the
    # vehicle, so a quick trip that leaves much later is not the better answer.
    parsed.sort(key=lambda o: (o.arrive, o.duration_s))
    return [
        TripOption(**{**o.__dict__, "rank": i}) for i, o in enumerate(parsed[:MAX_OPTIONS], start=1)
    ]


def _normal_text(text: str) -> str:
    text = text.casefold()
    text = text.replace(AREA_SUFFIX.casefold(), "")
    return re.sub(r"[\s,]+", " ", text).strip()


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def same_place(subject: TripQuery | list[TripOption] | dict[str, Any]) -> bool:
    """Whether origin and destination are the same place.

    Accepts the query (same text once the area suffix is ignored: Google
    answers ``{}`` for identical text, which looks like "no route"), a list of
    parsed options, or a raw Routes payload (resolved endpoints within 150 m).
    """
    if isinstance(subject, TripQuery):
        return _normal_text(subject.origin) == _normal_text(subject.destination)
    if isinstance(subject, dict):
        routes = subject.get("routes") or []
        if not routes:
            return False
        leg = routes[0]["legs"][0]
        return _metres(_latlng(leg["startLocation"]), _latlng(leg["endLocation"])) <= SAME_PLACE_M
    if not subject:
        return False
    first = subject[0]
    return _metres(first.origin_latlng, first.dest_latlng) <= SAME_PLACE_M
