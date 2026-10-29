"""Task 1: package skeleton, types, settings."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from assistant.config import Settings, load_settings
from assistant.types import (
    Alert,
    Context,
    Event,
    FollowUp,
    Leg,
    StationContext,
    TripOption,
    TripQuery,
    Weather,
)

ENV_KEYS = [
    "GCP_PROJECT",
    "VERTEX_REGION",
    "GEMINI_MODEL",
    "ROUTES_API_KEY",
    "TOKEN_511",
    "TICKETMASTER_KEY",
    "TOOL_TIMEOUT_S",
    "EXPLAIN_TIMEOUT_S",
    "RATE_LIMIT_PER_HOUR",
    "MAX_MESSAGE_CHARS",
    "TZ",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_settings_require_model(monkeypatch):
    with pytest.raises(RuntimeError, match="GEMINI_MODEL"):
        load_settings()

    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    s = load_settings()
    assert isinstance(s, Settings)
    assert s.GEMINI_MODEL == "test-model"
    assert s.TOOL_TIMEOUT_S == 1.5
    assert s.MAX_MESSAGE_CHARS == 500


def test_settings_blank_model_is_rejected(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "   ")
    with pytest.raises(RuntimeError, match="GEMINI_MODEL"):
        load_settings()


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    s = load_settings()
    assert s.VERTEX_REGION == "us-west1"
    assert s.EXPLAIN_TIMEOUT_S == 4.0
    assert s.RATE_LIMIT_PER_HOUR == 10
    assert s.TZ == "America/Los_Angeles"
    assert s.TICKETMASTER_KEY is None
    assert s.GCP_PROJECT == ""
    assert s.ROUTES_API_KEY == ""
    assert s.TOKEN_511 == ""


def test_settings_read_env_overrides(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "m")
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("VERTEX_REGION", "us-central1")
    monkeypatch.setenv("ROUTES_API_KEY", "rk")
    monkeypatch.setenv("TOKEN_511", "t511")
    monkeypatch.setenv("TICKETMASTER_KEY", "tm")
    monkeypatch.setenv("TOOL_TIMEOUT_S", "0.5")
    monkeypatch.setenv("EXPLAIN_TIMEOUT_S", "2")
    monkeypatch.setenv("RATE_LIMIT_PER_HOUR", "3")
    monkeypatch.setenv("MAX_MESSAGE_CHARS", "100")
    s = load_settings()
    assert (s.GCP_PROJECT, s.VERTEX_REGION) == ("proj", "us-central1")
    assert (s.ROUTES_API_KEY, s.TOKEN_511, s.TICKETMASTER_KEY) == ("rk", "t511", "tm")
    assert s.TOOL_TIMEOUT_S == 0.5
    assert s.EXPLAIN_TIMEOUT_S == 2.0
    assert s.RATE_LIMIT_PER_HOUR == 3
    assert s.MAX_MESSAGE_CHARS == 100


def test_settings_tz_ignores_process_tz(monkeypatch):
    """The container's ambient TZ (often UTC) must not change display times."""
    monkeypatch.setenv("GEMINI_MODEL", "m")
    monkeypatch.setenv("TZ", "UTC")
    assert load_settings().TZ == "America/Los_Angeles"


def test_settings_do_not_repr_secrets(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "m")
    monkeypatch.setenv("ROUTES_API_KEY", "super-secret-routes")
    monkeypatch.setenv("TOKEN_511", "super-secret-511")
    monkeypatch.setenv("TICKETMASTER_KEY", "super-secret-tm")
    text = repr(load_settings())
    assert "super-secret" not in text


def test_settings_frozen(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "m")
    s = load_settings()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.GEMINI_MODEL = "other"  # type: ignore[misc]


T0 = datetime(2026, 11, 5, 18, 5, tzinfo=timezone.utc)


def _leg(**kw):
    base = dict(
        mode="TRANSIT",
        agency="Caltrain",
        line="Limited",
        from_stop="Mountain View",
        to_stop="San Jose Diridon",
        depart=T0,
        arrive=T0,
        duration_s=1200,
        headsign="San Francisco",
    )
    base.update(kw)
    return Leg(**base)


def test_trip_query_defaults():
    q = TripQuery(origin="A", destination="B", depart_at=T0)
    assert q.past_time_replaced is False
    assert q.depart_at.tzinfo is not None


def test_follow_up():
    assert FollowUp(question="Where to?").question == "Where to?"


def test_leg_fields():
    leg = _leg()
    assert leg.mode == "TRANSIT" and leg.agency == "Caltrain"
    walk = _leg(mode="WALK", agency=None, line=None, headsign=None)
    assert walk.agency is None


def test_trip_option_and_context_build():
    leg = _leg()
    opt = TripOption(
        rank=1,
        depart=T0,
        arrive=T0,
        duration_s=3600,
        transfers=0,
        walk_s=120,
        agencies=("Caltrain",),
        legs=(leg,),
        polyline="abc",
        origin_latlng=(37.39, -122.08),
        dest_latlng=(37.33, -121.90),
    )
    ctx = Context(
        alerts=(Alert(agency="BART", header="Delay"),),
        weather=Weather(precip_mm=0.0, temp_c=15.0, wind_kmh=10.0),
        events=(Event(name="Sharks", venue="SAP Center", start=T0, distance_km=0.2),),
        stations=(
            StationContext(
                station="Millbrae",
                typical_monthly=1000,
                forecast_month="2026-11",
                forecast_p50=1100,
                label="monthly context, not live crowding",
            ),
        ),
        missing=("weather",),
    )
    assert opt.legs[0] is leg
    assert ctx.missing == ("weather",)


@pytest.mark.parametrize(
    "obj",
    [
        TripQuery(origin="A", destination="B", depart_at=T0),
        FollowUp(question="q"),
        _leg(),
        Alert(agency="BART", header="h"),
        Weather(precip_mm=0.0, temp_c=1.0, wind_kmh=2.0),
        Event(name="n", venue="v", start=T0, distance_km=1.0),
        Context(alerts=(), weather=None, events=(), stations=(), missing=()),
    ],
)
def test_types_are_frozen(obj):
    assert dataclasses.is_dataclass(obj)
    field = dataclasses.fields(obj)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, field, "changed")
