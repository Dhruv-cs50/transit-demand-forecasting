"""Frozen value types shared by every stage of the route assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Agency = Literal["BART", "VTA", "Caltrain", "other"]


@dataclass(frozen=True)
class TripQuery:
    """A parsed trip request. ``depart_at`` is timezone-aware."""

    origin: str
    destination: str
    depart_at: datetime
    past_time_replaced: bool = False


@dataclass(frozen=True)
class FollowUp:
    """A clarifying question to ask instead of routing."""

    question: str


@dataclass(frozen=True)
class Leg:
    mode: Literal["TRANSIT", "WALK"]
    agency: Agency | None
    line: str | None
    from_stop: str | None
    to_stop: str | None
    depart: datetime | None
    arrive: datetime | None
    duration_s: int
    headsign: str | None


@dataclass(frozen=True)
class TripOption:
    rank: int
    depart: datetime
    arrive: datetime
    duration_s: int
    transfers: int
    walk_s: int
    agencies: tuple[str, ...]
    legs: tuple[Leg, ...]
    polyline: str
    origin_latlng: tuple[float, float]
    dest_latlng: tuple[float, float]


@dataclass(frozen=True)
class Alert:
    agency: str
    header: str


@dataclass(frozen=True)
class Weather:
    precip_mm: float
    temp_c: float
    wind_kmh: float


@dataclass(frozen=True)
class Event:
    name: str
    venue: str
    start: datetime
    distance_km: float


@dataclass(frozen=True)
class StationContext:
    station: str
    typical_monthly: int
    forecast_month: str
    forecast_p50: int
    label: str


@dataclass(frozen=True)
class Context:
    """Context-tool results. ``missing`` names tools that failed or timed out."""

    alerts: tuple[Alert, ...]
    weather: Weather | None
    events: tuple[Event, ...]
    stations: tuple[StationContext, ...]
    missing: tuple[str, ...]
