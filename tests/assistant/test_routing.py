"""plan_trips against recorded Google Routes responses. No network: respx."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from assistant.routing import (
    FIELD_MASK,
    ROUTES_URL,
    RoutingError,
    normalise_agency,
    plan_trips,
    same_place,
)
from assistant.types import TripQuery

FIXTURES = Path(__file__).parent / "fixtures"
LABELS = {"BART", "VTA", "Caltrain", "other"}


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def query(origin: str = "Mountain View Caltrain Station", destination: str = "SAP Center") -> TripQuery:
    return TripQuery(
        origin=origin,
        destination=destination,
        depart_at=datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc),
    )


async def run(name: str, q: TripQuery | None = None):
    with respx.mock:
        respx.post(ROUTES_URL).mock(return_value=httpx.Response(200, json=fixture(name)))
        async with httpx.AsyncClient() as client:
            return await plan_trips(q or query(), client, "test-key")


@pytest.mark.asyncio
async def test_parses_options_sorted_and_capped():
    options = await run("routes_mv_to_sap.json")
    assert len(options) == 3  # six recorded alternatives, capped
    assert [o.rank for o in options] == [1, 2, 3]
    arrivals = [o.arrive for o in options]
    assert arrivals == sorted(arrivals)
    for o in options:
        assert set(o.agencies) <= LABELS
        assert o.duration_s == int((o.arrive - o.depart).total_seconds())
        assert o.depart.tzinfo is not None
        assert o.polyline
    first = options[0]
    caltrain = [leg for leg in first.legs if leg.agency == "Caltrain"]
    assert len(caltrain) == 1
    assert first.agencies == ("Caltrain",)
    assert caltrain[0].mode == "TRANSIT"
    assert caltrain[0].headsign == "San Jose Diridon"
    assert caltrain[0].from_stop == "Mountain View"
    assert caltrain[0].to_stop == "San Jose Diridon"
    assert caltrain[0].line == "Express"
    assert caltrain[0].duration_s == 840
    # Real times: Google's 15:06Z departure and 15:20Z arrival, plus the walks.
    assert caltrain[0].depart == datetime(2026, 10, 30, 15, 6, tzinfo=timezone.utc)
    assert caltrain[0].arrive == datetime(2026, 10, 30, 15, 20, tzinfo=timezone.utc)
    assert first.transfers == 0
    assert first.walk_s == 2 + 33 + 10 + 4 + 62 + 73 + 150 + 104 + 135
    # The trip starts when the leading walk starts, and ends after the last walk.
    assert (caltrain[0].depart - first.depart).total_seconds() == 2 + 33 + 10 + 4 + 62
    assert (first.arrive - caltrain[0].arrive).total_seconds() == 73 + 150 + 104 + 135


@pytest.mark.asyncio
async def test_consecutive_walk_steps_merge_into_one_leg():
    first = (await run("routes_mv_to_sap.json"))[0]
    modes = [leg.mode for leg in first.legs]
    assert modes == ["WALK", "TRANSIT", "WALK"]
    assert first.legs[0].duration_s == 111
    assert first.legs[0].agency is None
    assert first.legs[2].duration_s == 462


@pytest.mark.asyncio
async def test_times_are_pacific():
    first = (await run("routes_mv_to_sap.json"))[0]
    assert first.depart.tzname() == "PDT"
    assert first.depart.hour == 8


@pytest.mark.asyncio
async def test_bart_alternatives_rank_by_arrival_not_duration():
    options = await run("routes_bart.json")
    assert all(o.agencies == ("BART",) for o in options)
    arrivals = [o.arrive for o in options]
    assert arrivals == sorted(arrivals)
    # The recorded transfer trip (Blue then Orange, 1874 s) arrives before the
    # 1094 s Yellow trip that leaves later, so rank follows arrival time.
    assert [o.transfers for o in options] == [0, 0, 1]
    assert options[2].duration_s > options[1].duration_s


@pytest.mark.asyncio
async def test_vta_agency_normalised():
    options = await run("routes_vta.json")
    assert options and all(o.agencies == ("VTA",) for o in options)
    assert options[0].legs[0].line == "Green Line"


@pytest.mark.asyncio
async def test_latlng_from_leg_endpoints():
    first = (await run("routes_mv_to_sap.json"))[0]
    assert 37.3 < first.origin_latlng[0] < 37.5 and -122.2 < first.origin_latlng[1] < -122.0
    assert 37.3 < first.dest_latlng[0] < 37.4
    assert first.origin_latlng != first.dest_latlng


def test_normalise_agency():
    assert normalise_agency("Bay Area Rapid Transit") == "BART"
    assert normalise_agency("BART") == "BART"
    assert normalise_agency("Santa Clara Valley Transportation Authority") == "VTA"
    assert normalise_agency("VTA") == "VTA"
    assert normalise_agency("Caltrain") == "Caltrain"
    assert normalise_agency("Peninsula Corridor Joint Powers Board") == "Caltrain"
    assert normalise_agency("San Joaquin Joint Powers Authority") == "other"
    assert normalise_agency("") == "other"


@pytest.mark.asyncio
async def test_no_routes_returns_empty_list():
    assert await run("routes_empty.json") == []


@pytest.mark.asyncio
async def test_same_origin_and_destination_detected():
    # Identical text: Google answers {} (recorded), so the query itself is checked.
    q = query("Civic Center", "civic  center ")
    assert same_place(q)
    assert await run("routes_same_place.json", q) == []
    assert not same_place(query("Civic Center", "Powell Street"))
    # Free text and the same text with the area suffix already appended match.
    assert same_place(query("Civic Center", "Civic Center, San Francisco Bay Area, CA"))
    # Resolved options whose endpoints coincide.
    option = (await run("routes_bart.json"))[0]
    assert not same_place([option])
    assert same_place([replace(option, dest_latlng=option.origin_latlng)])
    # A raw payload whose route starts and ends at one point.
    payload = fixture("routes_bart.json")
    leg = payload["routes"][0]["legs"][0]
    leg["endLocation"] = leg["startLocation"]
    assert same_place(payload)
    assert not same_place(fixture("routes_bart.json"))
    assert not same_place({})
    assert not same_place([])


@pytest.mark.asyncio
async def test_request_shape():
    q = query("Mountain View Caltrain Station", "SAP Center, San Jose, CA")
    with respx.mock:
        route = respx.post(ROUTES_URL).mock(
            return_value=httpx.Response(200, json=fixture("routes_mv_to_sap.json"))
        )
        async with httpx.AsyncClient() as client:
            await plan_trips(q, client, "test-key")
    request = route.calls.last.request
    assert request.headers["X-Goog-Api-Key"] == "test-key"
    assert request.headers["X-Goog-FieldMask"] == FIELD_MASK
    body = json.loads(request.content)
    assert body["travelMode"] == "TRANSIT"
    assert body["computeAlternativeRoutes"] is True
    assert body["departureTime"] == "2026-10-30T15:00:00Z"
    # No comma: area appended. Has a comma: left alone.
    assert body["origin"] == {"address": "Mountain View Caltrain Station, San Francisco Bay Area, CA"}
    assert body["destination"] == {"address": "SAP Center, San Jose, CA"}
    assert "routes.legs.steps.transitDetails.stopDetails.arrivalTime" in FIELD_MASK


@pytest.mark.asyncio
async def test_http_error_raises_routing_error():
    with respx.mock:
        respx.post(ROUTES_URL).mock(return_value=httpx.Response(500, json={"error": {"code": 500}}))
        async with httpx.AsyncClient() as client:
            with pytest.raises(RoutingError):
                await plan_trips(query(), client, "test-key")


@pytest.mark.asyncio
async def test_timeout_raises_routing_error_without_leaking_key():
    with respx.mock:
        respx.post(ROUTES_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        async with httpx.AsyncClient() as client:
            with pytest.raises(RoutingError) as info:
                await plan_trips(query(), client, "secret-key-123")
    assert "secret-key-123" not in str(info.value)


@pytest.mark.asyncio
async def test_malformed_body_raises_routing_error():
    with respx.mock:
        respx.post(ROUTES_URL).mock(return_value=httpx.Response(200, content=b"<html>"))
        async with httpx.AsyncClient() as client:
            with pytest.raises(RoutingError):
                await plan_trips(query(), client, "test-key")
