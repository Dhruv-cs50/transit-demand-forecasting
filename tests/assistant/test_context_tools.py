"""Context tools against recorded real responses. No network: respx.

Fixtures (all recorded once from the real source, see tests/assistant/fixtures):
  alerts_511_rg.pb               511 servicealerts?agency=RG (GTFS-RT protobuf)
  open_meteo_sap.json            Open-Meteo hourly forecast at SAP Center
  nhl_sjs_week_2026-11-07.json   NHL Sharks club schedule, week of 2026-11-07
"""

from __future__ import annotations

import ast
import asyncio
import gzip
import json
import logging
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx

from assistant import context_tools as ct
from assistant.config import Settings
from assistant.routing import ROUTES_URL, plan_trips
from assistant.types import (
    Alert,
    Context,
    Event,
    StationContext,
    TripQuery,
    Weather,
)

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]
TOKEN = "unit-test-token-0123456789"
UTC = timezone.utc

# The 511 feed's own header timestamp (when the fixture was recorded).
FEED_NOW = datetime.fromtimestamp(1793499118, tz=UTC)
# Sharks home game: SJS v NYI, 2026-11-09, puck drop 2026-11-10T03:00Z (7 pm PST).
GAME_START = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)
SAP = (37.3327, -121.9010)

NHL_URL = r"https://api-web\.nhle\.com/v1/club-schedule/SJS/week/.*"
METEO_URL = "https://api.open-meteo.com/v1/forecast"
ALERTS_URL = "https://api.511.org/transit/servicealerts"
TM_URL = "https://app.ticketmaster.com/discovery/v2/events.json"


@pytest.fixture(autouse=True)
def fresh_caches():
    ct.clear_caches()
    yield
    ct.clear_caches()


def alerts_bytes() -> bytes:
    return (FIXTURES / "alerts_511_rg.pb").read_bytes()


def meteo() -> dict:
    return json.loads((FIXTURES / "open_meteo_sap.json").read_text())


def nhl() -> dict:
    return json.loads((FIXTURES / "nhl_sjs_week_2026-11-07.json").read_text())


def settings(**kw) -> Settings:
    base = dict(GEMINI_MODEL="test-model", TOKEN_511=TOKEN)
    base.update(kw)
    return Settings(**base)


async def routes(name: str, origin="Powell St", dest="Lake Merritt"):
    q = TripQuery(origin, dest, datetime(2026, 10, 30, 15, 0, tzinfo=UTC))
    body = json.loads((FIXTURES / name).read_text())
    async with respx.mock(assert_all_called=False) as m:
        m.post(ROUTES_URL).mock(return_value=httpx.Response(200, json=body))
        async with httpx.AsyncClient() as c:
            options = await plan_trips(q, c, "key")
    # Move the trip into the hours the weather and schedule fixtures cover.
    return q, [
        replace(o, depart=GAME_START - timedelta(minutes=30), arrive=GAME_START) for o in options
    ]


# --- service_alerts ----------------------------------------------------------


@pytest.mark.asyncio
async def test_service_alerts_parses_real_feed_for_vta():
    with respx.mock(assert_all_called=False) as m:
        route = m.get(ALERTS_URL).mock(return_value=httpx.Response(200, content=alerts_bytes()))
        async with httpx.AsyncClient() as c:
            alerts = await ct.service_alerts({"VTA"}, c, TOKEN, now=FEED_NOW)
    q = route.calls.last.request.url.params
    assert q["agency"] == "RG" and q["api_key"] == TOKEN
    assert alerts and all(isinstance(a, Alert) and a.agency == "VTA" for a in alerts)
    headers = [a.header for a in alerts]
    assert "Tamien Station Elevator Out of Service" in headers  # open-ended, started
    assert "Branham Station Elevator Out of Service" in headers
    # Starts 2026-11-03, after the feed was recorded: not active yet.
    assert not any(h.startswith("Free Fares on VTA Bus and Light Rail for Election Day") for h in headers)
    # Duplicate headers in the feed are reported once.
    assert len(headers) == len(set(headers))


@pytest.mark.asyncio
async def test_service_alerts_filters_by_agency_and_active_period():
    async def alerts(agencies, now):
        with respx.mock(assert_all_called=False) as m:
            m.get(ALERTS_URL).mock(return_value=httpx.Response(200, content=alerts_bytes()))
            async with httpx.AsyncClient() as c:
                return await ct.service_alerts(agencies, c, TOKEN, now=now)

    # BART and Caltrain have no alerts in the recording.
    assert await alerts({"BART", "Caltrain"}, FEED_NOW) == ()
    assert await alerts(set(), FEED_NOW) == ()
    # Once the Election Day period starts, that alert becomes active.
    later = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)
    headers = [a.header for a in await alerts({"VTA"}, later)]
    assert any(h.startswith("Free Fares on VTA Bus and Light Rail for Election Day") for h in headers)
    # A period that ended is dropped (the 10/27-10/30 Route 42 reroute).
    assert not any(h.startswith("Route 42: Reroute Due To MCK") for h in headers)


@pytest.mark.asyncio
async def test_service_alerts_other_agencies_never_match():
    # AC Transit, Muni, SamTrans... are not BART, VTA or Caltrain: a trip that
    # uses one must not pull in their alerts under the label "other".
    with respx.mock(assert_all_called=False) as m:
        m.get(ALERTS_URL).mock(return_value=httpx.Response(200, content=alerts_bytes()))
        async with httpx.AsyncClient() as c:
            assert await ct.service_alerts({"other"}, c, TOKEN, now=FEED_NOW) == ()
            both = await ct.service_alerts({"other", "VTA"}, c, TOKEN, now=FEED_NOW)
    assert both and {a.agency for a in both} == {"VTA"}


@pytest.mark.asyncio
async def test_service_alerts_maps_bart_and_caltrain_agency_ids():
    # Synthetic feed: the real recording has no BART or Caltrain alerts today.
    from google.transit import gtfs_realtime_pb2 as gtfs

    feed = gtfs.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    for i, agency_id in enumerate(("BA", "CT", "AC")):
        e = feed.entity.add()
        e.id = str(i)
        e.alert.informed_entity.add().agency_id = agency_id
        t = e.alert.header_text.translation.add()
        t.text, t.language = f"header {agency_id}", "en"
    with respx.mock(assert_all_called=False) as m:
        m.get(ALERTS_URL).mock(return_value=httpx.Response(200, content=feed.SerializeToString()))
        async with httpx.AsyncClient() as c:
            got = await ct.service_alerts({"BART", "Caltrain"}, c, TOKEN, now=FEED_NOW)
    assert {(a.agency, a.header) for a in got} == {("BART", "header BA"), ("Caltrain", "header CT")}


@pytest.mark.asyncio
async def test_service_alerts_handles_gzip_body():
    body = gzip.compress(alerts_bytes())
    with respx.mock(assert_all_called=False) as m:
        m.get(ALERTS_URL).mock(
            return_value=httpx.Response(200, content=body, headers={"content-encoding": "gzip"})
        )
        async with httpx.AsyncClient() as c:
            alerts = await ct.service_alerts({"VTA"}, c, TOKEN, now=FEED_NOW)
    assert alerts


@pytest.mark.asyncio
async def test_service_alerts_error_never_leaks_token():
    with respx.mock(assert_all_called=False) as m:
        m.get(ALERTS_URL).mock(return_value=httpx.Response(401))
        async with httpx.AsyncClient() as c:
            with pytest.raises(ct.ToolError) as err:
                await ct.service_alerts({"VTA"}, c, TOKEN, now=FEED_NOW)
    assert TOKEN not in str(err.value) and TOKEN not in repr(err.value)


@pytest.mark.asyncio
async def test_service_alerts_cached_for_five_minutes():
    with respx.mock(assert_all_called=False) as m:
        route = m.get(ALERTS_URL).mock(return_value=httpx.Response(200, content=alerts_bytes()))
        async with httpx.AsyncClient() as c:
            await ct.service_alerts({"VTA"}, c, TOKEN, now=FEED_NOW)
            await ct.service_alerts({"BART"}, c, TOKEN, now=FEED_NOW)
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_secrets_never_reach_logs(caplog):
    # httpx logs "HTTP Request: GET <url>" with the query string, so the 511
    # token and Ticketmaster key would land in the logs without redaction.
    caplog.set_level(logging.DEBUG)
    key = "tm-test-key-abcdef"
    with respx.mock(assert_all_called=False) as m:
        m.get(ALERTS_URL).mock(return_value=httpx.Response(200, content=alerts_bytes()))
        m.get(TM_URL).mock(return_value=httpx.Response(200, json={}))
        m.get(url__regex=NHL_URL).mock(return_value=httpx.Response(200, json=nhl()))
        async with httpx.AsyncClient() as c:
            await ct.service_alerts({"VTA"}, c, TOKEN, now=FEED_NOW)
            await ct.events_near(*SAP, GAME_START, c, tm_key=key)
    assert "HTTP Request" in caplog.text  # request logging itself still works
    assert TOKEN not in caplog.text and key not in caplog.text


# --- weather -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_weather_picks_hour_nearest_to_when():
    when = datetime(2026, 11, 10, 3, 20, tzinfo=UTC)  # nearest hour is 03:00Z
    with respx.mock(assert_all_called=False) as m:
        route = m.get(METEO_URL).mock(return_value=httpx.Response(200, json=meteo()))
        async with httpx.AsyncClient() as c:
            w = await ct.weather(*SAP, when, c)
    p = route.calls.last.request.url.params
    assert p["timezone"] == "UTC" and p["start_date"] == "2026-11-10"
    assert {"temperature_2m", "precipitation", "wind_speed_10m"} <= set(p["hourly"].split(","))
    assert w == Weather(precip_mm=0.0, temp_c=17.0, wind_kmh=5.2)  # recorded 03:00Z values


@pytest.mark.asyncio
async def test_weather_rounds_to_next_hour_and_accepts_local_tz():
    pacific = timezone(timedelta(hours=-8))
    when = datetime(2026, 11, 9, 18, 40, tzinfo=pacific)  # 02:40Z, nearest 03:00Z
    with respx.mock(assert_all_called=False) as m:
        route = m.get(METEO_URL).mock(return_value=httpx.Response(200, json=meteo()))
        async with httpx.AsyncClient() as c:
            w = await ct.weather(*SAP, when, c)
    assert route.calls.last.request.url.params["start_date"] == "2026-11-10"
    assert w.temp_c == 17.0


@pytest.mark.asyncio
async def test_weather_bad_payload_raises_tool_error():
    with respx.mock(assert_all_called=False) as m:
        m.get(METEO_URL).mock(return_value=httpx.Response(200, json={"hourly": {"time": []}}))
        async with httpx.AsyncClient() as c:
            with pytest.raises(ct.ToolError):
                await ct.weather(*SAP, GAME_START, c)


@pytest.mark.asyncio
async def test_weather_cached_for_five_minutes():
    with respx.mock(assert_all_called=False) as m:
        route = m.get(METEO_URL).mock(return_value=httpx.Response(200, json=meteo()))
        async with httpx.AsyncClient() as c:
            await ct.weather(*SAP, GAME_START, c)
            await ct.weather(37.3329, -121.9012, GAME_START + timedelta(minutes=5), c)
    assert route.call_count == 1


# --- events_near -------------------------------------------------------------


@pytest.mark.asyncio
async def test_events_near_finds_sharks_home_game_at_sap_center():
    with respx.mock(assert_all_called=False) as m:
        m.get(url__regex=NHL_URL).mock(return_value=httpx.Response(200, json=nhl()))
        async with httpx.AsyncClient() as c:
            events = await ct.events_near(*SAP, GAME_START - timedelta(hours=1), c, None)
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, Event)
    assert e.name == "Sharks vs New York Islanders"
    assert e.venue == "SAP Center at San Jose"
    assert e.start == GAME_START and e.start.tzinfo is not None
    assert e.distance_km < 0.05


@pytest.mark.asyncio
async def test_events_near_ignores_away_games_and_outside_window():
    away_night = datetime(2026, 11, 8, 1, 0, tzinfo=UTC)  # SJS at DAL: not at SAP Center
    with respx.mock(assert_all_called=False) as m:
        m.get(url__regex=NHL_URL).mock(return_value=httpx.Response(200, json=nhl()))
        async with httpx.AsyncClient() as c:
            assert await ct.events_near(*SAP, away_night, c, None) == ()
            # 4 h before puck drop is outside +-3 h; exactly 3 h is inside.
            assert await ct.events_near(*SAP, GAME_START - timedelta(hours=4), c, None) == ()
            assert len(await ct.events_near(*SAP, GAME_START - timedelta(hours=3), c, None)) == 1
            assert len(await ct.events_near(*SAP, GAME_START + timedelta(hours=3), c, None)) == 1


@pytest.mark.asyncio
async def test_events_near_far_from_sap_makes_no_request():
    far = (37.7749, -122.4194)  # San Francisco: farther than 1.5 km from SAP Center
    with respx.mock(assert_all_called=False):  # any request would raise: nothing is mocked
        async with httpx.AsyncClient() as c:
            assert await ct.events_near(*far, GAME_START, c, None) == ()


@pytest.mark.asyncio
async def test_events_near_skips_ticketmaster_without_key():
    with respx.mock(assert_all_called=False) as m:
        tm = m.get(TM_URL).mock(return_value=httpx.Response(500))
        m.get(url__regex=NHL_URL).mock(return_value=httpx.Response(200, json=nhl()))
        async with httpx.AsyncClient() as c:
            events = await ct.events_near(*SAP, GAME_START, c, tm_key=None)
    assert tm.call_count == 0
    assert len(events) == 1


@pytest.mark.asyncio
async def test_events_near_ticketmaster_with_key_adds_and_dedupes():
    # Hand-built payload using the fields machine_learning_files/fetch_events.py
    # reads from the Discovery API; there is no key to record a real one with.
    key = "tm-test-key-abcdef"
    later = GAME_START + timedelta(hours=1)
    venue = {
        "name": "SAP Center at San Jose",
        "location": {"latitude": "37.3327", "longitude": "-121.9010"},
    }
    tm_body = {
        "_embedded": {
            "events": [
                {   # the Sharks game again: same start, same venue -> deduped
                    "name": "San Jose Sharks v New York Islanders",
                    "dates": {"start": {"dateTime": "2026-11-10T03:00:00Z"}},
                    "_embedded": {"venues": [venue]},
                },
                {
                    "name": "Concert at the Tank",
                    "dates": {"start": {"dateTime": later.strftime("%Y-%m-%dT%H:%M:%SZ")}},
                    "_embedded": {"venues": [venue]},
                },
                {   # TBD time: only a local date -> skipped
                    "name": "No time yet",
                    "dates": {"start": {"localDate": "2026-11-10"}},
                    "_embedded": {"venues": [venue]},
                },
            ]
        }
    }
    with respx.mock(assert_all_called=False) as m:
        tm = m.get(TM_URL).mock(return_value=httpx.Response(200, json=tm_body))
        m.get(url__regex=NHL_URL).mock(return_value=httpx.Response(200, json=nhl()))
        async with httpx.AsyncClient() as c:
            events = await ct.events_near(*SAP, GAME_START, c, tm_key=key)
    assert tm.calls.last.request.url.params["apikey"] == key
    assert sorted(e.name for e in events) == ["Concert at the Tank", "Sharks vs New York Islanders"]


@pytest.mark.asyncio
async def test_events_near_ticketmaster_error_never_leaks_key():
    key = "tm-test-key-abcdef"
    with respx.mock(assert_all_called=False) as m:
        m.get(TM_URL).mock(return_value=httpx.Response(429))
        m.get(url__regex=NHL_URL).mock(return_value=httpx.Response(200, json=nhl()))
        async with httpx.AsyncClient() as c:
            with pytest.raises(ct.ToolError) as err:
                await ct.events_near(*SAP, GAME_START, c, tm_key=key)
    assert key not in str(err.value)


def test_venue_table_matches_fetch_events_source():
    src = (ROOT / "machine_learning_files" / "fetch_events.py").read_text()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "VENUE_COORDS":
            table = ast.literal_eval(node.value)
            break
    else:  # pragma: no cover
        pytest.fail("VENUE_COORDS not found")
    assert ct.SAP_CENTER == (table["sap_center"]["lat"], table["sap_center"]["lng"])


# --- station_context ---------------------------------------------------------


def test_station_context_label():
    s = ct.station_context("Powell St")
    assert isinstance(s, StationContext)
    assert s.label == "monthly context, not live crowding"
    assert s.station == "Powell St."
    assert s.typical_monthly == 344882
    # The latest SARIMA month in the bundled data: the forecast nearest to today.
    assert (s.forecast_month, s.forecast_p50) == ("2025-12", 365997)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("12th St / Oakland", "12th St. Oakland City Center"),
        ("Powell Street Station", "Powell St."),
        ("lake merritt", "Lake Merritt"),
        ("Civic Center / UN Plaza", "Civic Center/UN Plaza"),
        ("Berryessa / North San Jose", "Berryessa/North San José"),
        ("San Francisco International Airport", "SFO"),
    ],
)
def test_station_context_fuzzy_matches_google_names(name, expected):
    assert ct.station_context(name).station == expected


@pytest.mark.parametrize("name", ["Mountain View", "Berkeley", "", "Nowhere Station", "Oakland"])
def test_station_context_returns_none_when_unknown_or_ambiguous(name):
    assert ct.station_context(name) is None


# --- TTLCache ----------------------------------------------------------------


def test_ttl_cache_expires():
    now = [100.0]
    cache = ct.TTLCache(300, clock=lambda: now[0])
    assert cache.get("k") is None
    cache.set("k", "v")
    assert cache.get("k") == "v"
    now[0] += 299
    assert cache.get("k") == "v"
    now[0] += 2
    assert cache.get("k") is None


# --- gather_context ----------------------------------------------------------


def mock_all_tools(m, *, weather_delay_s: float = 0.0):
    m.get(ALERTS_URL).mock(return_value=httpx.Response(200, content=alerts_bytes()))

    async def slow_weather(request):
        await asyncio.sleep(weather_delay_s)
        return httpx.Response(200, json=meteo())

    m.get(METEO_URL).mock(side_effect=slow_weather)
    m.get(url__regex=NHL_URL).mock(return_value=httpx.Response(200, json=nhl()))


@pytest.mark.asyncio
async def test_gather_context_with_real_fixtures():
    q, options = await routes("routes_bart.json")
    options = [
        replace(o, dest_latlng=SAP, agencies=("VTA", "BART")) for o in options
    ]
    with respx.mock(assert_all_called=False) as m:
        mock_all_tools(m)
        async with httpx.AsyncClient() as c:
            ctx = await ct.gather_context(options, q, c, settings())
    assert isinstance(ctx, Context)
    assert ctx.missing == ()
    assert any(a.agency == "VTA" for a in ctx.alerts)
    assert ctx.weather is not None
    assert [e.venue for e in ctx.events] == ["SAP Center at San Jose"]
    assert "Powell St." in {s.station for s in ctx.stations}  # boarding stop of the top option


@pytest.mark.asyncio
async def test_gather_context_finds_events_at_either_end():
    # The spec asks for events near either end of the trip: leaving SAP Center
    # after a game is as relevant as arriving for one.
    q, options = await routes("routes_bart.json")
    options = [replace(o, origin_latlng=SAP, arrive=GAME_START + timedelta(hours=9)) for o in options]
    options = [replace(o, depart=GAME_START) for o in options]
    with respx.mock(assert_all_called=False) as m:
        mock_all_tools(m)
        async with httpx.AsyncClient() as c:
            ctx = await ct.gather_context(options, q, c, settings())
    assert [e.venue for e in ctx.events] == ["SAP Center at San Jose"]  # once, not twice


@pytest.mark.asyncio
async def test_gather_context_alerts_are_those_active_at_departure():
    q, options = await routes("routes_bart.json")
    election_day = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)  # after the feed was recorded
    shifted = [replace(o, depart=election_day, arrive=election_day + timedelta(hours=1)) for o in options]
    shifted = [replace(o, agencies=("VTA",)) for o in shifted]
    with respx.mock(assert_all_called=False) as m:
        mock_all_tools(m)
        async with httpx.AsyncClient() as c:
            ctx = await ct.gather_context(shifted, q, c, settings())
    assert any(a.header.startswith("Free Fares on VTA Bus") for a in ctx.alerts)


@pytest.mark.asyncio
async def test_gather_context_times_out_slow_tool():
    q, options = await routes("routes_bart.json")
    with respx.mock(assert_all_called=False) as m:
        mock_all_tools(m, weather_delay_s=3.0)  # slow respx route
        async with httpx.AsyncClient() as c:
            t0 = time.perf_counter()
            ctx = await ct.gather_context(options, q, c, settings())
            elapsed = time.perf_counter() - t0
    assert elapsed < 1.8
    assert "weather" in ctx.missing and ctx.weather is None
    assert "alerts" not in ctx.missing  # the others still delivered


@pytest.mark.asyncio
async def test_gather_context_failed_tool_is_named_and_never_raises():
    q, options = await routes("routes_bart.json")
    with respx.mock(assert_all_called=False) as m:
        mock_all_tools(m)
        m.get(ALERTS_URL).mock(return_value=httpx.Response(500))
        m.get(METEO_URL).mock(side_effect=httpx.ConnectError("boom"))
        async with httpx.AsyncClient() as c:
            ctx = await ct.gather_context(options, q, c, settings())
    assert set(ctx.missing) == {"alerts", "weather"}
    assert ctx.alerts == () and ctx.weather is None


@pytest.mark.asyncio
async def test_gather_context_without_511_token_reports_alerts_missing():
    q, options = await routes("routes_bart.json")
    with respx.mock(assert_all_called=False) as m:
        mock_all_tools(m)
        async with httpx.AsyncClient() as c:
            ctx = await ct.gather_context(options, q, c, settings(TOKEN_511=""))
    assert ctx.missing == ("alerts",)


@pytest.mark.asyncio
async def test_gather_context_no_options_returns_empty_context():
    q = TripQuery("a", "b", GAME_START)
    async with httpx.AsyncClient() as c:
        ctx = await ct.gather_context([], q, c, settings())
    assert ctx == Context((), None, (), (), ())


@pytest.mark.asyncio
async def test_gather_context_runs_concurrently(monkeypatch):
    q, options = await routes("routes_bart.json")

    async def slow_alerts(*a, **k):
        await asyncio.sleep(1)
        return ()

    async def slow_weather(*a, **k):
        await asyncio.sleep(1)
        return Weather(0.0, 15.0, 5.0)

    async def slow_events(*a, **k):
        await asyncio.sleep(1)
        return ()

    def slow_station(name):  # sync tool: must not block the loop
        time.sleep(1)
        return None

    monkeypatch.setattr(ct, "service_alerts", slow_alerts)
    monkeypatch.setattr(ct, "weather", slow_weather)
    monkeypatch.setattr(ct, "events_near", slow_events)
    monkeypatch.setattr(ct, "station_context", slow_station)
    async with httpx.AsyncClient() as c:
        t0 = time.perf_counter()
        ctx = await ct.gather_context(options, q, c, settings(TOOL_TIMEOUT_S=1.45))
        elapsed = time.perf_counter() - t0
    assert elapsed < 1.5
    assert ctx.missing == ()
    assert ctx.weather == Weather(0.0, 15.0, 5.0)
