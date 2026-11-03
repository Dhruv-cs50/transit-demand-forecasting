"""Out-of-scope replies (``assistant.scope``): the hand-written pool and the Bay Area box.

Gemini only decides *that* a question is out of scope and why; every word the
rider reads comes from this pool, so a refusal can never carry directions.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from assistant import scope
from assistant.scope import (
    BAY_AREA_BOUNDS,
    EXAMPLE_QUESTION,
    MAX_PLACE_CHARS,
    REASONS,
    clean_place,
    in_bay_area,
    in_pool,
    scope_text,
)

FIXTURES = Path(__file__).parent / "fixtures"

# Travel advice, modes, roads and times that a refusal must never contain.
BANNED = re.compile(
    r"\b(drive|driving|drove|car|cars|uber|lyft|taxi|cab|rideshare|flight|flights|fly|flying|plane|airline|"
    r"amtrak|greyhound|flixbus|megabus|bus|buses|ferry|i-\d+|us-\d+|highway|freeway|interstate|route\s*\d+|"
    r"minutes?|mins?|hours?|hrs?|am|pm|a\.m\.|p\.m\.|tonight|tomorrow|today|noon|midnight)\b",
    re.I,
)
NUDGE = re.compile(r"\?|\{example\}")


def all_templates():
    for reason in REASONS:
        for template in scope.PLAIN_VARIANTS[reason] + scope.PLACE_VARIANTS.get(reason, ()):
            yield reason, template


def test_every_reason_has_five_or_six_plain_variants():
    assert set(REASONS) == {"out_of_area", "other_mode", "off_topic"}
    for reason in REASONS:
        assert 5 <= len(scope.PLAIN_VARIANTS[reason]) <= 6
    assert len(scope.PLACE_VARIANTS["out_of_area"]) >= 3
    assert set(scope.PLACE_VARIANTS) == {"out_of_area"}  # only out-of-area replies name a place


@pytest.mark.parametrize("reason,template", list(all_templates()))
def test_pool_has_no_times_numbers_or_travel_advice(reason, template):
    filled = template.format(example=EXAMPLE_QUESTION, place="Somewhere")
    outside_example = filled.replace(EXAMPLE_QUESTION, "")
    assert not re.search(r"\d", outside_example), filled  # numbers only inside the example question
    assert not BANNED.search(outside_example), filled
    assert NUDGE.search(template), template  # always points at what the bot can do
    assert "BART" in filled or "transit" in filled or "{example}" in template


@pytest.mark.parametrize("reason", REASONS)
def test_every_reason_produces_pool_text(reason):
    for seed in range(20):
        text = scope_text(reason, choice=random.Random(seed).choice)
        assert in_pool(reason, text)
        assert "{" not in text and "}" not in text
    other = next(r for r in REASONS if r != reason)
    assert not all(in_pool(other, scope_text(reason, choice=random.Random(s).choice)) for s in range(20))


@pytest.mark.parametrize("reason", REASONS)
def test_variants_vary_across_seeds(reason):
    texts = {scope_text(reason, choice=random.Random(seed).choice) for seed in range(40)}
    assert len(texts) >= 3


def test_default_choice_is_random_choice(monkeypatch):
    picked = []

    def first(seq):
        picked.append(tuple(seq))
        return seq[0]

    monkeypatch.setattr(scope.random, "choice", first)
    text = scope_text("off_topic")
    assert picked and text == scope.PLAIN_VARIANTS["off_topic"][0].format(example=EXAMPLE_QUESTION)


def test_place_name_is_inserted():
    for seed in range(20):
        text = scope_text("out_of_area", "San Diego", choice=random.Random(seed).choice)
        assert "San Diego" in text
        assert in_pool("out_of_area", text)


def test_place_name_is_truncated_and_cleaned():
    long = "The Very Long Name Of A Faraway Town Somewhere In Nevada Or Beyond"
    text = scope_text("out_of_area", long, choice=lambda seq: seq[0])
    shown = clean_place(long)
    assert shown is not None and len(shown) <= MAX_PLACE_CHARS and shown.endswith("…")
    assert shown in text and long not in text
    assert in_pool("out_of_area", text)

    assert clean_place("  San\tDiego \n") == "San Diego"
    assert clean_place("San\x00 Diego\x1b[31m") == "San Diego[31m"
    assert clean_place("   ") is None and clean_place(None) is None


def test_without_a_place_a_plain_variant_is_used():
    for seed in range(20):
        text = scope_text("out_of_area", None, choice=random.Random(seed).choice)
        assert text in {t.format(example=EXAMPLE_QUESTION) for t in scope.PLAIN_VARIANTS["out_of_area"]}
    # a place is never named for the other reasons
    assert "San Diego" not in scope_text("other_mode", "San Diego", choice=lambda seq: seq[0])


def test_in_pool_rejects_other_text():
    assert not in_pool("out_of_area", "Take I-5 south for about five hours.")
    assert not in_pool("off_topic", "")
    assert not in_pool("nope", scope_text("off_topic", choice=lambda seq: seq[0]))
    padded = scope_text("off_topic", choice=lambda seq: seq[0]) + " Also, drive."
    assert not in_pool("off_topic", padded)


# --- the Bay Area box ------------------------------------------------------------------


def test_bounds_are_the_documented_box():
    assert BAY_AREA_BOUNDS == {"lat_min": 36.9, "lat_max": 38.9, "lng_min": -123.6, "lng_max": -121.2}


MID_LAT, MID_LNG = 37.8, -122.4
EPS = 0.01


@pytest.mark.parametrize(
    "point,inside",
    [
        ((36.9 + EPS, MID_LNG), True), ((36.9 - EPS, MID_LNG), False),  # south edge (Gilroy is 37.0)
        ((38.9 - EPS, MID_LNG), True), ((38.9 + EPS, MID_LNG), False),  # north edge (Cloverdale 38.8)
        ((MID_LAT, -123.6 + EPS), True), ((MID_LAT, -123.6 - EPS), False),  # west edge (the coast)
        ((MID_LAT, -121.2 - EPS), True), ((MID_LAT, -121.2 + EPS), False),  # east edge (Santa Clara Co.)
    ],
)
def test_box_both_sides_of_each_edge(point, inside):
    assert in_bay_area(point) is inside


@pytest.mark.parametrize(
    "name,point",
    [
        ("Gilroy Caltrain", (37.0040, -121.5665)),
        ("Santa Rosa", (38.4404, -122.7141)),
        ("SFO", (37.6213, -122.3790)),
        ("Antioch BART", (37.9955, -121.7804)),
    ],
)
def test_box_contains_the_edges_of_the_service_area(name, point):
    assert in_bay_area(point), name


@pytest.mark.parametrize(
    "name,point",
    [
        ("Los Angeles", (34.0522, -118.2437)),
        ("San Diego", (32.7157, -117.1611)),
        ("Monterey", (36.6002, -121.8947)),
        ("Reno", (39.5296, -119.8138)),
        ("Modesto", (37.6391, -120.9969)),
    ],
)
def test_box_excludes_places_beyond_it(name, point):
    assert not in_bay_area(point), name


def test_every_recorded_route_endpoint_is_inside_the_box():
    """The real Google Routes recordings: start and end of every route pass the guard."""
    seen = 0
    for path in sorted(FIXTURES.glob("routes_*.json")):
        for route in json.loads(path.read_text()).get("routes", []):
            for leg in route.get("legs", []):
                for key in ("startLocation", "endLocation"):
                    ll = leg[key]["latLng"]
                    assert in_bay_area((ll["latitude"], ll["longitude"])), (path.name, key)
                    seen += 1
    assert seen >= 10


def test_bad_coordinates_are_outside():
    assert not in_bay_area((float("nan"), MID_LNG))
    assert not in_bay_area(None)  # type: ignore[arg-type]


# --- the deny-list: well-known places outside the area, checked before routing -------------

from assistant.scope import outside_place_named  # noqa: E402


@pytest.mark.parametrize(
    "written,named",
    [
        ("Los Angeles", "Los Angeles"),
        ("los angeles union station", "los angeles"),
        ("LA", "LA"),
        ("L.A.", "L.A."),
        ("downtown LA", "LA"),
        ("San Diego", "San Diego"),
        ("Sacramento", "Sacramento"),
        ("Sacramento Amtrak station", "Sacramento"),
        ("Fresno", "Fresno"),
        ("Bakersfield", "Bakersfield"),
        ("Stockton", "Stockton"),
        ("Modesto", "Modesto"),
        ("Santa Cruz", "Santa Cruz"),
        ("Santa Cruz Boardwalk", "Santa Cruz"),
        ("Monterey", "Monterey"),
        ("Monterey Bay Aquarium", "Monterey"),
        ("Reno", "Reno"),
        ("Lake Tahoe", "Lake Tahoe"),
        ("South Lake Tahoe", "Lake Tahoe"),
        ("Tahoe", "Tahoe"),
        ("Las Vegas", "Las Vegas"),
        ("Vegas", "Vegas"),
        ("Portland", "Portland"),
        ("Seattle", "Seattle"),
        ("New York", "New York"),
        ("NYC", "NYC"),
        ("Chicago", "Chicago"),
        ("Yosemite", "Yosemite"),
        ("Yosemite Valley", "Yosemite"),
    ],
)
def test_deny_list_names_places_outside_the_area(written, named):
    assert outside_place_named(written) == named


@pytest.mark.parametrize(
    "written",
    [
        "Los Altos",
        "San Jose",
        "Sacramento St",
        "Sacramento St.",
        "Sacramento Street",
        "1500 Sacramento Street, San Francisco",
        "Stockton St",
        "Stockton Street and Sutter",
        "Powell & Stockton",
        "Monterey Blvd",
        "Monterey Boulevard",
        "Monterey Heights",
        "Santa Cruz Ave, Menlo Park",
        "Chicago Way",
        "Portland Ave",
        "Yosemite Ave",
        "Fresno St",
        "La Honda",
        "Calle de la Playa",
        "Los Gatos",
        "Napa",  # one of the nine counties; VINE buses connect it to BART
        "Napa Valley",
        "Lorenzo",
        "Moreno Ave",
        "SAP Center",
        "Mountain View Caltrain",
    ],
)
def test_deny_list_leaves_bay_area_names_alone(written):
    assert outside_place_named(written) is None
