"""Bare station names, made unambiguous for Google before routing.

A rider writes "Winchester to Santa Teresa" and means the VTA light-rail
stations; geocoded as written (plus the Bay Area suffix) they land elsewhere
and Google offers two-hour Caltrain-plus-bus trips. So a place that is exactly
a known station name becomes "<name as written> <agency> station", for example
"Winchester VTA station".

The "don't guess" rule holds: only names on this short allowlist are expanded,
and the allowlist holds only names that belong to exactly one of BART, Caltrain
and VTA light rail and are not also a city. Names shared between agencies or
that are cities ("Millbrae", "Mountain View", "Civic Center", "Tamien",
"Palo Alto", see ``SHARED_OR_CITY``) are left exactly as written, as is
anything with an agency word, a comma or extra words.
"""

from __future__ import annotations

import re

STATIONS: dict[str, tuple[str, ...]] = {
    "BART": (
        "Embarcadero", "Montgomery St", "Powell St", "16th St Mission", "24th St Mission", "Glen Park",
        "Balboa Park", "West Oakland", "12th St Oakland", "19th St Oakland", "Lake Merritt", "Fruitvale",
        "Coliseum", "MacArthur", "Rockridge", "Ashby", "Downtown Berkeley", "North Berkeley",
        "El Cerrito Plaza", "El Cerrito del Norte", "Bay Fair", "South Hayward", "West Dublin",
        "Dublin/Pleasanton", "Pleasant Hill", "North Concord", "Pittsburg/Bay Point", "Pittsburg Center",
        "Warm Springs",
    ),
    "Caltrain": (
        "22nd St", "Hayward Park", "Hillsdale", "California Ave", "Lawrence", "College Park", "4th and King",
    ),
    "VTA": (
        "Winchester", "Santa Teresa", "Cottle", "Snell", "Ohlone/Chynoweth", "Branham", "Curtner",
        "Children's Discovery Museum", "St James", "Japantown/Ayer", "Metro/Airport", "Tasman", "Lick Mill",
        "Old Ironsides", "Reamwood", "Crossman", "Borregas", "Lockheed Martin", "Moffett Park", "Whisman",
        "Baypointe", "Cisco Way", "Great Mall", "Montague", "Hostetter", "Penitencia Creek",
        "Downtown Campbell", "Bascom", "Fruitdale", "Paseo de San Antonio",
    ),
}

# Never expanded: stations of two agencies, or names that are also cities.
SHARED_OR_CITY = (
    "Millbrae", "Milpitas", "Mountain View", "Civic Center", "Tamien", "Capitol", "Blossom Hill",
    "San Jose Diridon", "Diridon", "San Antonio", "Santa Clara", "Bayshore", "Berryessa", "San Bruno",
    "South San Francisco", "Palo Alto", "Sunnyvale", "Redwood City", "San Mateo", "Burlingame", "Fremont",
    "Hayward", "Richmond", "Concord", "Daly City", "Colma", "Antioch", "Walnut Creek", "Lafayette", "Orinda",
    "Union City", "San Leandro", "Castro Valley", "Menlo Park", "Belmont", "San Carlos", "Gilroy",
    "Morgan Hill", "San Martin", "Stanford", "San Francisco", "Oakland", "Berkeley", "San Jose", "Campbell",
)

_REWRITE = {"street": "st", "avenue": "ave", "saint": "st", "&": "and", "fourth": "4th"}
_TRAILING = re.compile(r"\s+(station|stn)\.?\s*$", re.I)


def _key(text: str) -> str:
    words = re.sub(r"[^a-z0-9&]+", " ", text.casefold().replace("'", "")).split()
    words = [_REWRITE.get(w, w) for w in words]
    if words and words[-1] in ("station", "stn"):
        words = words[:-1]
    return " ".join(words)


_LOOKUP = {_key(name): agency for agency, names in STATIONS.items() for name in names}


def normalise_place(place: str) -> str:
    """``place`` as "<name> <agency> station" when it is a bare allowlisted station name, else unchanged."""
    agency = _LOOKUP.get(_key(place)) if "," not in place else None
    if agency is None:
        return place
    name = _TRAILING.sub("", place.strip())
    return f"{name} {agency} station"
