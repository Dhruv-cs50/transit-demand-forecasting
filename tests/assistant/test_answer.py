"""Digest, validator and template answer, against the recorded real fixtures.

Real inputs (tests/assistant/fixtures):
  routes_mv_to_sap.json          Google Routes, Mountain View -> SAP Center (Caltrain + VTA)
  alerts_511_rg.pb               511 regional alerts: 43 active VTA alerts
  nhl_sjs_week_2026-11-07.json   NHL Sharks schedule (two home games)
  open_meteo_sap.json            Open-Meteo forecast at SAP Center
Small hand-made options cover the edge rules (midnight, noon, DST, hours).
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import httpx
import pytest
import respx

from assistant import answer
from assistant import context_tools as ct
from assistant.answer import (
    DIGEST_LIMIT,
    allowed_tokens,
    build_digest,
    explanation_ok,
    template_explanation,
    template_from_digest,
    unverified_claims,
)
from assistant.config import DISPLAY_TZ
from assistant.routing import ROUTES_URL, plan_trips
from assistant.types import (
    Alert,
    Context,
    Event,
    Leg,
    StationContext,
    TripOption,
    TripQuery,
    Weather,
)

FIXTURES = Path(__file__).parent / "fixtures"
TZ = DISPLAY_TZ
UTC = timezone.utc
FEED_NOW = datetime.fromtimestamp(1793499118, tz=UTC)
TOKEN = "unit-test-token-0123456789"
ALERTS_URL = "https://api.511.org/transit/servicealerts"
METEO_URL = "https://api.open-meteo.com/v1/forecast"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def run(coro):
    return asyncio.run(coro)


def _plan(payload: dict) -> list[TripOption]:
    q = TripQuery("Mountain View Caltrain Station", "SAP Center", datetime(2026, 10, 30, 15, 0, tzinfo=UTC))

    async def go():
        with respx.mock:
            respx.post(ROUTES_URL).mock(return_value=httpx.Response(200, json=payload))
            async with httpx.AsyncClient() as client:
                return await plan_trips(q, client, "test-key")

    return run(go())


@lru_cache(maxsize=None)
def caltrain_options() -> tuple[TripOption, ...]:
    """The three best real MV -> SAP options (all Caltrain)."""
    return tuple(_plan(fixture("routes_mv_to_sap.json")))


@lru_cache(maxsize=None)
def mixed_options() -> tuple[TripOption, ...]:
    """Two real Caltrain options and the real VTA 52 + Rapid 522 option."""
    payload = fixture("routes_mv_to_sap.json")
    payload["routes"] = [payload["routes"][i] for i in (0, 1, 5)]
    return tuple(_plan(payload))


@lru_cache(maxsize=None)
def real_alerts() -> tuple[Alert, ...]:
    async def go():
        with respx.mock(assert_all_called=False) as m:
            m.get(ALERTS_URL).mock(
                return_value=httpx.Response(200, content=(FIXTURES / "alerts_511_rg.pb").read_bytes())
            )
            async with httpx.AsyncClient() as c:
                return await ct.service_alerts({"VTA", "BART", "Caltrain"}, c, TOKEN, now=FEED_NOW)

    ct.clear_caches()
    try:
        return run(go())
    finally:
        ct.clear_caches()


@lru_cache(maxsize=None)
def real_weather() -> Weather:
    async def go():
        with respx.mock(assert_all_called=False) as m:
            m.get(METEO_URL).mock(return_value=httpx.Response(200, json=fixture("open_meteo_sap.json")))
            async with httpx.AsyncClient() as c:
                return await ct.weather(37.3327, -121.9010, datetime(2026, 11, 10, 3, 0, tzinfo=UTC), c)

    ct.clear_caches()
    try:
        return run(go())
    finally:
        ct.clear_caches()


def real_events() -> tuple[Event, ...]:
    return tuple(ct._sharks_events(fixture("nhl_sjs_week_2026-11-07.json")))


def station(name: str = "Powell St.") -> StationContext:
    found = ct.station_context(name)
    assert found is not None
    return found


def ctx(**kw) -> Context:
    base = dict(alerts=(), weather=None, events=(), stations=(), missing=())
    base.update(kw)
    return Context(**base)


def pacific(h: int, m: int, day: int = 10) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime(2026, 11, day, h, m, tzinfo=ZoneInfo(TZ))


def option(depart: datetime, arrive: datetime, *, walk_s: int = 0, rank: int = 1, transfers: int = 0,
           agency: str = "Caltrain", line: str = "Express", legs: tuple[Leg, ...] | None = None) -> TripOption:
    legs = legs or (
        Leg("TRANSIT", agency, line, "Mountain View", "San Jose Diridon", depart, arrive,  # type: ignore[arg-type]
            int((arrive - depart).total_seconds()), "San Jose Diridon"),
    )
    return TripOption(
        rank=rank, depart=depart, arrive=arrive, duration_s=int((arrive - depart).total_seconds()),
        transfers=transfers, walk_s=walk_s, agencies=(agency,), legs=legs, polyline="x",
        origin_latlng=(37.39, -122.08), dest_latlng=(37.33, -121.90),
    )


# --- the real Mountain View -> SAP Center options -------------------------------


def test_real_option_times_are_what_the_digest_shows():
    first = caltrain_options()[0]
    d = build_digest([*caltrain_options()], ctx(), TZ)
    # Real fixture: walk 111 s, Caltrain Express 8:06-8:20 AM, walk 462 s.
    assert d["options"][0]["depart"] == "8:04 AM"
    assert d["options"][0]["arrive"] == "8:28 AM"
    assert d["options"][0]["minutes"] == 24
    assert d["options"][0]["walk_minutes"] == 10
    assert d["options"][0]["transfers"] == 0
    assert d["options"][0]["agencies"] == ["Caltrain"]
    assert d["options"][0]["lines"] == ["Caltrain Express"]
    assert first.duration_s == 1413


def test_accepts_exact_times():
    options = [*caltrain_options()]
    ok = (
        "Take the 8:06 AM Caltrain Express from Mountain View. You arrive at 8:28 AM, "
        "about 24 min door to door, with 10 min of walking."
    )
    assert explanation_ok(ok, options, TZ)
    # Same facts in 24-hour form and with "minutes".
    assert explanation_ok("Leaves 08:04, arrives 08:28 - 24 minutes in total.", options, TZ)
    # A text with no times or durations at all makes no claim to check.
    assert explanation_ok("The first option is the earliest arrival and has no transfers.", options, TZ)


def test_rejects_invented_minutes():
    options = [*caltrain_options()]  # 24, 28 and 29 minutes
    assert not explanation_ok("The ride takes 45 min.", options, TZ)
    assert not explanation_ok("It takes 25 minutes.", options, TZ)  # one off a real 24
    assert not explanation_ok("Option 1 takes 24 min but option 2 takes 31 min.", options, TZ)


def test_rejects_invented_clock_times():
    options = [*caltrain_options()]
    assert not explanation_ok("You arrive at 8:30 AM.", options, TZ)
    assert not explanation_ok("You arrive at 08:30.", options, TZ)
    assert not explanation_ok("Leave at 8:06 PM.", options, TZ)  # the 8:06 is a morning time
    assert not explanation_ok("Leave at 20:06.", options, TZ)
    assert not explanation_ok("Be there by 9 PM.", options, TZ)


@pytest.mark.parametrize(
    "text",
    [
        "It takes about an hour.",
        "Roughly half an hour end to end.",
        "A couple of minutes to walk.",
        "A few minutes of walking.",
        "Several minutes on foot.",
        "About an hour and a half.",
        "Around a quarter of an hour.",
        "A half-hour ride.",
        "Just under an hour.",
        "Allow a minute to transfer.",
    ],
)
def test_rejects_vague_duration(text):
    assert not explanation_ok(text, [*caltrain_options()], TZ)


def test_vague_phrases_do_not_catch_ordinary_words():
    options = [*caltrain_options()]
    assert explanation_ok("Avoid rush hour if you can; trains may be busier then.", options, TZ)
    assert explanation_ok("Take the express for the shortest ride.", options, TZ)


def test_word_numbers_and_ranges_are_checked():
    options = [*caltrain_options()]
    assert explanation_ok("About twenty-four minutes.", options, TZ)
    assert not explanation_ok("About twenty minutes.", options, TZ)
    assert not explanation_ok("Ten to twenty minutes of walking.", options, TZ)
    assert not explanation_ok("It is a 5-10 minute walk.", options, TZ)
    assert explanation_ok("It is a 24-minute ride.", options, TZ)
    assert not explanation_ok("It is a 40-minute ride.", options, TZ)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Arrives 8:28 AM", True),
        ("Arrives 8:28 am", True),
        ("Arrives 8:28AM", True),
        ("Arrives 8:28 a.m.", True),
        ("Arrives 08:28", True),
        ("Arrives 8:28", True),  # no AM/PM: ambiguous, so either reading may match
        ("Arrives 8:28 PM", False),
        ("Arrives 8:28 p.m.", False),
        ("Arrives 20:28", False),
        ("Arrives at 8 AM", False),  # 8:00 is not a time Google gave
        ("Arrives 8:29 AM", False),
        ("Leaves at 8:06 AM, 10 min walking", True),
        ("Leaves at 8:06 AM, 10 mins walking", True),
        ("Leaves at 8:06 AM, 11 min walking", False),
        ("Leaves 8:06", True),
    ],
)
def test_clock_formats(text, expected):
    assert explanation_ok(text, [*caltrain_options()], TZ) is expected


def test_allowed_tokens_cover_both_clock_formats_and_minute_forms():
    tokens = allowed_tokens([*caltrain_options()], TZ)
    assert {"8:04 AM", "08:04", "8:28 AM", "08:28", "8:06 AM", "08:06", "8:20 AM", "08:20"} <= tokens
    assert {"24 min", "24 minutes", "10 min", "10 minutes", "14 min", "14 minutes"} <= tokens
    assert "8:04 PM" not in tokens and "45 min" not in tokens


def test_every_allowed_token_passes_the_validator():
    options = [*caltrain_options()]
    for token in sorted(allowed_tokens(options, TZ)):
        assert explanation_ok(f"Note {token}.", options, TZ), token


# --- hand-made edge rules ---------------------------------------------------------


def test_times_are_pacific_not_utc_and_follow_dst():
    # 02:30 UTC on 2026-11-10 is 6:30 PM PST (the clocks changed on 1 November).
    winter = option(datetime(2026, 11, 10, 2, 30, tzinfo=UTC), datetime(2026, 11, 10, 3, 5, tzinfo=UTC))
    assert build_digest([winter], ctx(), TZ)["options"][0]["depart"] == "6:30 PM"
    assert explanation_ok("Leaves 6:30 PM.", [winter], TZ)
    assert not explanation_ok("Leaves 2:30 AM.", [winter], TZ)
    assert not explanation_ok("Leaves 10:30 AM.", [winter], TZ)
    # The same UTC clock time in July is 7:30 PM PDT.
    summer = option(datetime(2026, 7, 10, 2, 30, tzinfo=UTC), datetime(2026, 7, 10, 3, 5, tzinfo=UTC))
    assert build_digest([summer], ctx(), TZ)["options"][0]["depart"] == "7:30 PM"
    assert explanation_ok("Leaves 7:30 PM.", [summer], TZ)
    assert not explanation_ok("Leaves 6:30 PM.", [summer], TZ)


def test_midnight_and_noon_edges():
    late = option(pacific(23, 50), pacific(0, 20, day=11))
    d = build_digest([late], ctx(), TZ)["options"][0]
    assert (d["depart"], d["arrive"], d["minutes"]) == ("11:50 PM", "12:20 AM", 30)
    assert explanation_ok("Arrives 12:20 AM (00:20).", [late], TZ)
    assert not explanation_ok("Arrives 12:20 PM.", [late], TZ)
    assert not explanation_ok("Arrives around midnight.", [late], TZ)
    noon = option(pacific(11, 30), pacific(12, 0))
    assert explanation_ok("Arrives 12:00 PM, at noon.", [noon], TZ)
    assert explanation_ok("Arrives at 12 PM.", [noon], TZ)
    assert not explanation_ok("Arrives at midnight.", [noon], TZ)


def test_hours_are_exact_or_rejected():
    hour = option(pacific(18, 5), pacific(19, 5))  # exactly 60 minutes
    assert explanation_ok("A 60 min ride.", [hour], TZ)
    assert explanation_ok("A 1 hour ride.", [hour], TZ)
    assert not explanation_ok("About an hour.", [hour], TZ)
    long_ride = option(pacific(18, 5), pacific(19, 17))  # 72 minutes
    assert explanation_ok("It takes 1 hr 12 min.", [long_ride], TZ)
    assert explanation_ok("It takes 1 hour 12 minutes.", [long_ride], TZ)
    assert explanation_ok("It takes 72 minutes.", [long_ride], TZ)
    assert not explanation_ok("It takes 1 hour 10 minutes.", [long_ride], TZ)
    assert not explanation_ok("It takes 2 hours.", [long_ride], TZ)
    assert "1 hr 12 min" in allowed_tokens([long_ride], TZ)


def test_leg_times_and_durations_are_derivable():
    walk = Leg("WALK", None, None, None, None, None, None, 300, None)
    ride = Leg("TRANSIT", "BART", "Yellow-S", "Powell St.", "Lake Merritt", pacific(9, 12), pacific(9, 31),
               1140, "Antioch")
    o = option(pacific(9, 7), pacific(9, 36), walk_s=600, agency="BART", legs=(walk, ride, walk), transfers=0)
    assert explanation_ok("Board at 9:12 AM, off at 9:31 AM after 19 min on the train; walk 5 min.", [o], TZ)
    assert not explanation_ok("Board at 9:13 AM.", [o], TZ)


def test_blank_text_is_not_an_explanation():
    assert not explanation_ok("   ", [*caltrain_options()], TZ)


def test_non_clock_numbers_are_not_claims():
    options = [*caltrain_options()]
    assert explanation_ok("Option 2 costs about $3.50; the ratio is 3:1 and route 522 runs.", options, TZ)
    assert explanation_ok("Rain of 0.2 mm is possible, about 64°F, on 11/10/26.", options, TZ)


# --- digest -----------------------------------------------------------------------


def test_digest_is_json_able_and_has_the_planned_fields():
    c = ctx(
        alerts=real_alerts()[:2],
        weather=real_weather(),
        events=real_events(),
        stations=(station(),),
        missing=("events:ticketmaster",),
    )
    d = build_digest([*mixed_options()], c, TZ)
    assert json.loads(json.dumps(d)) == d
    assert set(d) >= {"options", "alerts", "weather", "events", "stations", "missing"}
    assert [o["rank"] for o in d["options"]] == [1, 2, 3]
    assert d["missing"] == ["events:ticketmaster"]
    assert set(d["weather"]) == {"temp_f", "precip_mm", "wind_kmh"}
    assert isinstance(d["weather"]["temp_f"], int)
    assert d["stations"][0]["label"] == "monthly context, not live crowding"
    vta = d["options"][2]
    assert vta["agencies"] == ["VTA"] and vta["transfers"] == 1
    assert vta["lines"] == ["VTA 52", "VTA Rapid 522"]


def test_digest_caps_alerts_at_three_from_the_real_511_feed():
    assert len(real_alerts()) == 43  # all active VTA alerts, mostly bus-stop closures
    d = build_digest([*mixed_options()], ctx(alerts=real_alerts()), TZ)
    assert len(d["alerts"]) == 3


def test_digest_ranks_alerts_by_relevance_to_the_trip():
    # The trip rides VTA Rapid 522. The five real 522 alerts must beat the 38
    # other VTA alerts, whatever order the feed lists them in.
    options = [*mixed_options()]
    for alerts in (real_alerts(), tuple(reversed(real_alerts()))):
        d = build_digest(options, ctx(alerts=alerts), TZ)
        assert len(d["alerts"]) == 3
        for a in d["alerts"]:
            assert a["agency"] == "VTA"
            assert re.search(r"\b522\b", a["header"]), a


def test_alert_matching_a_stop_beats_agency_only_and_line_matches():
    options = [option(pacific(9, 0), pacific(9, 30), agency="VTA", line="22",
                      legs=(Leg("TRANSIT", "VTA", "22", "El Camino & Castro", "Santa Clara & Montgomery",
                                pacific(9, 0), pacific(9, 30), 1800, "Eastridge"),))]
    alerts = (
        Alert("VTA", "Route 70: Reroute Due to Construction"),  # agency only
        Alert("VTA", "Route 22: Temporary Bus Stop Closure at El Camino and Page Mill"),  # line
        Alert("VTA", "Route 61: Bus Stop Closure at El Camino and Castro"),  # stop ("and" == "&")
        Alert("BART", "Powell St. Elevator Out of Service"),  # agency not in the trip
        Alert("VTA", "Tamien Station Elevator Out of Service"),  # agency only
    )
    got = [a["header"] for a in build_digest(options, ctx(alerts=alerts), TZ)["alerts"]]
    assert got[:2] == [alerts[2].header, alerts[1].header] or got[:2] == [alerts[1].header, alerts[2].header]
    assert set(got[:2]) == {alerts[1].header, alerts[2].header}
    assert got[2] in {alerts[0].header, alerts[4].header}
    assert alerts[3].header not in got
    assert len(got) == 3


def test_alerts_for_agencies_outside_the_trip_are_dropped():
    d = build_digest([*caltrain_options()], ctx(alerts=real_alerts()), TZ)  # Caltrain-only trip
    assert d["alerts"] == []


def real_risky_alert() -> Alert:
    # Real 511 header: "(10PM-5AM)" is a clock time Google never gave.
    return next(a for a in real_alerts() if "10PM-5AM" in a.header)


def test_real_alert_header_is_kept_and_its_times_become_allowed():
    risky = real_risky_alert()
    options = [*mixed_options()]
    d = build_digest(options, ctx(alerts=(risky,)), TZ)
    assert d["alerts"] == [{"agency": "VTA", "header": risky.header}]
    assert "(10PM-5AM)" in d["alerts"][0]["header"]
    # Figures in the source alert are now statable; anything else still is not.
    assert explanation_ok("The alert covers 10 PM to 5 AM.", options, TZ, digest=d)
    assert explanation_ok("Closures run 10PM-5AM.", options, TZ, digest=d)
    assert not explanation_ok("The alert covers 10 PM to 6 AM.", options, TZ, digest=d)
    assert not explanation_ok("The alert covers 10 PM to 5 AM.", options, TZ)  # no digest, old rules
    assert not explanation_ok("The alert covers 10 PM to 5 AM.", options, TZ, digest=build_digest(options, ctx(), TZ))
    assert {"10:00 PM", "22:00", "5:00 AM", "05:00"} <= allowed_tokens(options, TZ, digest=d)
    assert "10:00 PM" not in allowed_tokens(options, TZ)


def test_alert_header_is_cleaned_and_truncated_but_not_scrubbed():
    long_header = "Route 22: " + "Temporary closure notice " * 12 + "\x07 see https://example.com/a?b=1 or www.vta.org/x"
    alerts = (Alert("VTA", long_header), Alert("VTA", "Route 22: delays of 15 min\n\texpected"))
    d = build_digest([*mixed_options()], ctx(alerts=alerts), TZ)
    first, second = (a["header"] for a in d["alerts"])
    assert len(first) <= answer.ALERT_CHARS and first.endswith("\u2026")
    assert "http" not in first and "www." not in first and "\x07" not in first
    assert second == "Route 22: delays of 15 min expected"  # control characters become spaces, figures stay
    assert explanation_ok("Expect delays of 15 min.", [*mixed_options()], TZ, digest=d)
    assert not explanation_ok("Expect delays of 16 min.", [*mixed_options()], TZ, digest=d)


def test_a_time_in_neither_the_options_nor_the_digest_fails():
    options = [*mixed_options()]
    c = ctx(alerts=(real_risky_alert(),), events=real_events()[:1])
    d = build_digest(options, c, TZ)
    for text in ("The game is at 8:30 PM.", "Alerts end at 6 AM.", "It starts at 9 PM.", "About 33 min."):
        assert not explanation_ok(text, options, TZ, digest=d), text
    for text in ("The game starts at 7 PM.", "Puck drop 19:00.", "Alerts end at 5 AM.", "Leaves 9:08 AM."):
        assert explanation_ok(text, options, TZ, digest=d), text


def test_digest_caps_events_and_shows_pacific_start_times():
    many = tuple(
        Event(f"Game {i}", "SAP Center at San Jose", datetime(2026, 11, 10, 3, 0, tzinfo=UTC), 0.1 * i)
        for i in range(5)
    )
    d = build_digest([*caltrain_options()], ctx(events=many), TZ)
    assert len(d["events"]) == 3
    assert [e["name"] for e in d["events"]] == ["Game 0", "Game 1", "Game 2"]  # nearest first
    assert d["events"][0]["start"] == "7:00 PM"  # 03:00 UTC is 7 pm PST


def test_real_sharks_start_time_is_statable_with_the_digest():
    options = [*caltrain_options()]
    first_game = real_events()[0]
    d = build_digest(options, ctx(events=(first_game,)), TZ)
    # The NHL fixture's first home game: 2026-11-10T03:00Z.
    assert d["events"][0]["start"] == "7:00 PM"
    assert explanation_ok("Sharks vs New York Islanders at 7:00 PM.", options, TZ, digest=d)
    assert not explanation_ok("Sharks vs New York Islanders at 7:00 PM.", options, TZ)
    assert not explanation_ok("Sharks vs New York Islanders at 7:30 PM.", options, TZ, digest=d)
    assert "7:00 PM" in allowed_tokens(options, TZ, digest=d)


def test_digest_with_no_options_or_context_is_valid():
    d = build_digest([], ctx(missing=("weather",)), TZ)
    assert d["options"] == [] and d["alerts"] == [] and d["weather"] is None and d["missing"] == ["weather"]


def test_digest_under_size_limit():
    c = ctx(
        alerts=real_alerts(),
        weather=real_weather(),
        events=(*real_events(), Event("Hand-made show", "SAP Center at San Jose", pacific(19, 0), 0.2)),
        stations=(station("Powell St."), station("Lake Merritt")),
        missing=("events:ticketmaster",),
    )
    size = len(json.dumps(build_digest([*mixed_options()], c, TZ)))
    assert size < 6000 == DIGEST_LIMIT


def test_digest_size_on_the_largest_real_fixture_combination():
    # MV -> SAP routes (incl. the two-leg VTA option) + all 43 511 alerts + the NHL week.
    c = ctx(
        alerts=real_alerts(),
        weather=real_weather(),
        events=real_events(),
        stations=(station("Powell St."),),
        missing=(),
    )
    size = len(json.dumps(build_digest([*mixed_options()], c, TZ)))
    print(f"largest-fixture digest size: {size} characters")
    assert size < DIGEST_LIMIT


def test_digest_trims_to_the_limit_when_names_are_huge():
    long = "x" * 300
    legs = tuple(
        Leg("TRANSIT", "VTA", f"{i}{long}", f"{long} stop {i}", f"{long} end {i}", pacific(9, i), pacific(9, i + 5),
            300, long)
        for i in range(6)
    )
    options = [option(pacific(9, 0), pacific(10, 0), agency="VTA", legs=legs, rank=r) for r in (1, 2, 3)]
    c = ctx(
        alerts=tuple(Alert("VTA", f"Route {i}: {long}") for i in range(10)),
        events=tuple(Event(long, long, pacific(19, 0), 0.1) for _ in range(5)),
        stations=tuple(StationContext(long, 1, "2026-12", 1, "monthly context, not live crowding") for _ in range(4)),
        missing=("alerts",),
    )
    d = build_digest(options, c, TZ)
    assert len(json.dumps(d)) < DIGEST_LIMIT
    assert len(d["options"]) == 3  # the answer itself is never trimmed away


# --- template answer ---------------------------------------------------------------


def test_template_mentions_each_option_and_missing_tools():
    options = [*caltrain_options()]
    d = build_digest(options, ctx(missing=("weather", "events:ticketmaster")), TZ)
    text = template_explanation(options, ctx(missing=("weather", "events:ticketmaster")), TZ)
    for o in d["options"]:
        assert f"Option {o['rank']}" in text
        assert o["depart"] in text and o["arrive"] in text
    assert "weather" in text.lower() and "ticketmaster" in text.lower()
    assert explanation_ok(text, options, TZ)


def test_template_answer_for_mountain_view_to_sap_center():
    options = [*caltrain_options()]
    c = ctx(
        weather=real_weather(),
        events=real_events()[:1],
        stations=(),
        missing=("events:ticketmaster",),
    )
    text = template_explanation(options, c, TZ)
    print("\n" + text)
    assert "Caltrain Express" in text and "San Jose Diridon" in text
    assert "earliest arrival" in text.splitlines()[0]
    assert "starting 7:00 PM" in text
    assert explanation_ok(text, options, TZ, digest=build_digest(options, c, TZ))
    assert not explanation_ok(text, options, TZ)  # the game time is source data, not an option figure
    assert "Sharks" in text and "may" in text.lower()  # an event is a possibility, not a fact


def test_template_is_built_only_from_the_digest():
    options = [*mixed_options()]
    c = ctx(alerts=real_alerts(), weather=real_weather(), events=real_events(), stations=(station(),))
    assert template_explanation(options, c, TZ) == template_from_digest(build_digest(options, c, TZ))
    # Render a hand-made digest: only what it holds can appear.
    d = build_digest(options, ctx(), TZ)
    d["alerts"] = [{"agency": "VTA", "header": "SENTINEL-ALERT"}]
    assert "SENTINEL-ALERT" in template_from_digest(d)
    d["alerts"] = []
    assert "SENTINEL-ALERT" not in template_from_digest(d)


def test_template_uses_real_alert_headers_and_event_start_times():
    options = [*mixed_options()]
    risky = real_risky_alert()
    c = ctx(alerts=(risky,), events=real_events()[:1])
    d = build_digest(options, c, TZ)
    text = template_explanation(options, c, TZ)
    assert risky.header in text and "(10PM-5AM)" in text
    assert "7:00 PM" in text and "Sharks" in text
    assert explanation_ok(text, options, TZ, digest=d)


def real_cases() -> list[tuple[str, list[TripOption], Context]]:
    """Every real fixture combination, with the real alerts, weather and events."""
    extra_alerts = (
        Alert("BART", "Delays of about an hour at Powell St. until 5 PM, 15 min waits"),
        Alert("Caltrain", "Trains 20 minutes late; shuttle every half hour from 10:30 PM"),
        Alert("VTA", "Route 22: a few minutes of delay, a couple of minutes at night, 1 hr 5 min detour"),
    )
    games = real_events()
    cases = []
    for name in ("routes_bart.json", "routes_vta.json", "routes_mv_to_sap.json", "routes_recording.json"):
        cases.append((name, _plan(fixture(name))))
    cases.append(("mixed", [*mixed_options()]))
    cases.append(("no-options", []))
    out = []
    for name, options in cases:
        for label, alerts in (("none", ()), ("real", real_alerts()), ("synthetic", extra_alerts),
                              ("both", (*extra_alerts, *real_alerts()))):
            c = ctx(
                alerts=alerts,
                weather=real_weather(),
                events=games,
                stations=(station("Powell St."), station("Lake Merritt")),
                missing=("events:ticketmaster",),
            )
            out.append((f"{name}/{label}", list(options), c))
    return out


def test_template_always_passes_the_validator_with_its_digest():
    # Property over all real fixtures and the real/synthetic alerts: the
    # template never states a figure that neither the options nor the digest hold.
    cases = real_cases()
    assert len(cases) >= 20
    for label, options, c in cases:
        d = build_digest(options, c, TZ)
        text = template_explanation(options, c, TZ)
        assert explanation_ok(text, options, TZ, digest=d), (label, unverified_claims(text, options, TZ, digest=d))
        assert len(json.dumps(d)) < DIGEST_LIMIT, label


def test_template_flags_unique_best_options_without_inventing_numbers():
    fast = option(pacific(9, 0), pacific(9, 30), walk_s=900, transfers=1, rank=1)
    simple = option(pacific(9, 5), pacific(9, 40), walk_s=120, transfers=0, rank=2)
    text = template_explanation([fast, simple], ctx(), TZ)
    first, second = text.splitlines()[:2]
    assert "earliest arrival" in first and "fewest transfers" not in first
    assert "fewest transfers" in second and "least walking" in second
    assert explanation_ok(text, [fast, simple], TZ)


def test_template_with_no_options_says_so():
    text = template_explanation([], ctx(missing=("weather",)), TZ)
    assert "no transit option" in text.lower()
    assert "Option 1" not in text


def test_template_lists_at_most_three_alerts_and_labels_crowding():
    text = template_explanation(
        [*mixed_options()], ctx(alerts=real_alerts(), stations=(station(),)), TZ
    )
    assert text.count("Alert (VTA)") <= 3
    assert "monthly context, not live crowding" in text.lower()


def test_other_free_text_is_still_scrubbed_but_alerts_and_event_times_are_not():
    # Stops, lines, headsigns, event names, venues and station names are not
    # figure sources: a time or minute count in them would be unsupported.
    ride = Leg("TRANSIT", "VTA", "Express 15 min", "Stop at 9:45 PM", "End 20 minutes away",
               pacific(9, 0), pacific(9, 30), 1800, "Via 7 PM shuttle")
    o = option(pacific(9, 0), pacific(9, 30), agency="VTA", legs=(ride,))
    c = ctx(
        alerts=(Alert("VTA", "Route 22: delays of 15 min expected"),),
        events=(Event("Show at 7:30 PM", "Hall open 10 minutes early", pacific(19, 0), 0.1),),
        stations=(StationContext("Powell St. 5 min", 1000, "2026-12", 900, "monthly context, not live crowding"),),
    )
    d = build_digest([o], c, TZ)
    text = template_explanation([o], c, TZ)
    blob = json.dumps({k: v for k, v in d.items() if k != "alerts"})
    for bad in ("15 min", "9:45", "20 minutes", "7 PM", "7:30", "10 minutes", "5 min"):
        assert bad not in blob, bad
    assert "delays of 15 min expected" in text and "7:00 PM" in text  # alerts and the event time count
    assert explanation_ok(text, [o], TZ, digest=d)
    assert build_digest([o], ctx(events=(Event("Sharks vs Kings", "SAP Center", pacific(19, 0), 0.1),)), TZ)[
        "events"
    ][0]["name"] == "Sharks vs Kings"
