"""Bare station names become "<name> <agency> station" (``assistant.station_names``).

"Winchester to Santa Teresa" geocoded to places that were not the VTA light-rail
stations and returned two-hour Caltrain-plus-bus trips. A name is only expanded
when it is a known station of exactly one agency and not also a city, so the
"don't guess" rule holds.
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from assistant import station_names
from assistant.station_names import STATIONS, normalise_place

from test_llm import extract, reply  # noqa: E402

PT = ZoneInfo("America/Los_Angeles")


@pytest.mark.parametrize(
    "written,expected",
    [
        ("Winchester", "Winchester VTA station"),
        ("Santa Teresa", "Santa Teresa VTA station"),
        ("santa teresa", "santa teresa VTA station"),
        ("Winchester station", "Winchester VTA station"),
        ("Winchester Station", "Winchester VTA station"),
        ("Ohlone/Chynoweth", "Ohlone/Chynoweth VTA station"),
        ("Powell St", "Powell St BART station"),
        ("Powell Street", "Powell Street BART station"),
        ("powell st.", "powell st. BART station"),
        ("Rockridge", "Rockridge BART station"),
        ("Hillsdale", "Hillsdale Caltrain station"),
        ("California Ave", "California Ave Caltrain station"),
        ("  Winchester  ", "Winchester VTA station"),
    ],
)
def test_bare_single_agency_station_names_get_the_agency(written, expected):
    assert normalise_place(written) == expected


@pytest.mark.parametrize(
    "written",
    [
        "Winchester VTA",  # the rider already named the agency
        "Winchester light rail",
        "Powell St BART",
        "Hillsdale Caltrain station",
        "Mountain View",  # a city, and a Caltrain and a VTA station
        "Millbrae",  # BART and Caltrain
        "Milpitas",
        "Civic Center",  # BART (SF) and VTA (San Jose)
        "Tamien",  # Caltrain and VTA
        "San Jose Diridon",
        "Palo Alto",  # a city
        "SAP Center",
        "SFO",
        "Winchester Blvd and Hamilton Ave",
        "Winchester, San Jose",
        "12th St Oakland City Center BART",
    ],
)
def test_other_places_are_left_as_written(written):
    assert normalise_place(written) == written


def test_allowlist_is_single_agency_and_has_no_cities():
    seen: dict[str, str] = {}
    for agency, names in STATIONS.items():
        assert agency in {"BART", "Caltrain", "VTA"}
        for name in names:
            key = station_names._key(name)
            assert key not in seen, (name, agency, seen.get(key))
            seen[key] = agency
    for city in station_names.SHARED_OR_CITY:
        assert station_names._key(city) not in seen, city


def test_extract_normalises_bare_station_names():
    payload = reply(origin="Winchester", destination="Santa Teresa", depart_at="2026-11-10T09:00:00-08:00")
    now = datetime(2026, 11, 9, 20, 0, tzinfo=PT)
    q, client = extract(payload, message="Winchester to Santa Teresa on VTA light rail tomorrow at 9 am", now=now)
    assert (q.origin, q.destination) == ("Winchester VTA station", "Santa Teresa VTA station")


def test_extract_keeps_other_names_as_written():
    q, _ = extract(reply(origin="Mountain View Caltrain", destination="SAP Center"))
    assert (q.origin, q.destination) == ("Mountain View Caltrain", "SAP Center")


def test_follow_up_and_scope_paths_are_untouched():
    f, _ = extract(reply(origin=None, destination="Winchester", follow_up="Where are you starting from?"))
    assert f.question == "Where are you starting from?"
    r, _ = extract(json.dumps({**reply(), "scope": "out_of_scope", "scope_reason": "off_topic"}))
    assert r.reason == "off_topic"
