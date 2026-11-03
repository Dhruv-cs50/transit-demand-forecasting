"""What the assistant says when a question is out of bounds, and the Bay Area box.

Code decides that a question is out of scope (Gemini call 1's ``scope`` and
``scope_reason``, or the box below applied to the endpoints Google resolved),
and the words come from the hand-written pool here, picked at random. Gemini
never writes a refusal, so one can never slip in directions for the trip it
declines. The only rider-derived text in a reply is the out-of-area place name,
cleaned and cut to ``MAX_PLACE_CHARS``.

Reasons:
  * ``out_of_area``: an end of the trip is outside the Bay Area;
  * ``other_mode``: driving, flying, rideshare or any other non-transit way;
  * ``off_topic``: not a trip request at all (weather, jokes, homework,
    chit-chat, nonsense) and prompt-injection attempts.
"""

from __future__ import annotations

import math
import random
import re
import unicodedata
from typing import Callable, Sequence

REASONS = ("out_of_area", "other_mode", "off_topic")
EXAMPLE_QUESTION = "Mountain View Caltrain to SAP Center at 6 PM"
MAX_PLACE_CHARS = 40

# Every variant nudges toward what the assistant can do: the example question or a question back.
# No times, no numbers outside the example and no word about how else to make the trip.
PLAIN_VARIANTS: dict[str, tuple[str, ...]] = {
    "out_of_area": (
        "That trip goes beyond the Bay Area, which is outside what I cover. "
        "I stick to BART, VTA and Caltrain — where in the Bay are you headed?",
        "Sorry, I can only plan trips within the San Francisco Bay Area on BART, VTA and Caltrain. "
        "Try something like \"{example}\".",
        "That one's outside my patch: I only know public transit around the Bay Area. "
        "Ask me about a BART, VTA or Caltrain trip, like \"{example}\".",
        "I only cover BART, VTA and Caltrain trips inside the Bay Area, so I can't help with that one. "
        "Got a trip around the Bay I can plan instead?",
        "That's farther afield than I go. I plan public-transit trips around the Bay Area on BART, "
        "VTA and Caltrain — for example \"{example}\".",
    ),
    "other_mode": (
        "I only plan public-transit trips on BART, VTA and Caltrain, so I can't help with that one. "
        "Want a transit route instead? Try \"{example}\".",
        "That's not something I can plan — I stick to BART, VTA and Caltrain. "
        "If you'd like to go by transit, where are you starting from and where are you headed?",
        "Sorry, transit is all I know: BART, VTA and Caltrain trips around the Bay Area. "
        "Try asking something like \"{example}\".",
        "I'm just a transit planner, so that's outside what I do. "
        "Where are you starting from, and where are you headed? I'll find you a BART, VTA or Caltrain route.",
        "I can't help with that kind of trip, but I'm happy to find you a BART, VTA or Caltrain route "
        "around the Bay. Where are you headed?",
    ),
    "off_topic": (
        "I can only help with public-transit trips around the Bay Area on BART, VTA and Caltrain. "
        "Try something like \"{example}\".",
        "That's outside what I can help with — I plan BART, VTA and Caltrain trips in the Bay Area. "
        "Where would you like to go?",
        "I'm a transit route planner, so I'll have to pass on that one. Ask me for a trip, like \"{example}\".",
        "Sorry, I can only plan trips on BART, VTA and Caltrain. "
        "Where are you starting from, and where are you headed?",
        "Hmm, I can't help with that, but I can find you a BART, VTA or Caltrain route around the Bay. "
        "Try \"{example}\".",
    ),
}

# Out-of-area variants that name the place the rider asked about.
PLACE_VARIANTS: dict[str, tuple[str, ...]] = {
    "out_of_area": (
        "{place} is a bit outside my patch — I only cover BART, VTA and Caltrain trips around the Bay Area. "
        "Where in the Bay are you headed?",
        "Sorry, {place} is beyond the area I know. I plan BART, VTA and Caltrain trips within the "
        "San Francisco Bay Area — try something like \"{example}\".",
        "I'd love to help, but {place} is outside the Bay Area, and I only know BART, VTA and Caltrain. "
        "Got a trip around the Bay I can plan instead?",
        "{place} is out of my range, I'm afraid: I stick to public transit within the Bay Area. "
        "Ask me about a BART, VTA or Caltrain trip, like \"{example}\".",
    ),
}

# The Bay Area box: the nine counties (San Francisco, San Mateo, Santa Clara, Alameda, Contra
# Costa, Marin, Napa, Solano, Sonoma) plus Caltrain and VTA down to Gilroy. Edges are inclusive.
# A rectangle is coarse: Sacramento, Stockton, Davis and Santa Cruz fall inside it, so this
# guard catches gross mis-geocodes (Los Angeles, San Diego, Reno, Monterey) and Gemini's
# ``out_of_area`` is the main check for places beyond the counties but inside the box.
BAY_AREA_BOUNDS = {"lat_min": 36.9, "lat_max": 38.9, "lng_min": -123.6, "lng_max": -121.2}

Choice = Callable[[Sequence[str]], str]

# Well-known places outside the area, matched against the rider's origin and destination
# before routing (so before the Bay Area suffix can pull "Los Angeles" into San Francisco).
# Case-insensitive, whole words, longest first. "LA" is matched in capitals only ("L.A." too),
# so "La Honda" and "Calle de la Playa" are not caught. Napa is deliberately absent: it is one
# of the nine counties, and Google Routes reaches it by VINE buses that connect to BART.
OUTSIDE_PLACES = (
    "Los Angeles", "San Diego", "Sacramento", "Fresno", "Bakersfield", "Stockton", "Modesto",
    "Santa Cruz", "Monterey", "Reno", "Lake Tahoe", "Tahoe", "Las Vegas", "Vegas",
    "Portland", "Seattle", "New York City", "New York", "NYC", "Chicago", "Yosemite",
)
# Many of those names are also Bay Area streets or districts (Sacramento St, Stockton St,
# Monterey Blvd, Santa Cruz Ave): a name followed by one of these words is not the place,
_STREET_WORDS = (
    "st", "street", "ave", "av", "avenue", "blvd", "boulevard", "rd", "road", "dr", "drive", "way", "ln",
    "lane", "pl", "place", "ct", "court", "ter", "terrace", "hwy", "highway", "expy", "expressway", "pkwy",
    "parkway", "cir", "circle", "sq", "square", "heights", "alley", "row", "walk",
)
# and neither is a name inside an intersection ("Powell & Stockton", "Stockton and Sutter").
_INTERSECTION = re.compile(r"&|@|/|\band\b|\bat\b", re.I)
_NAMES_RE = re.compile(
    r"(?<![\w.])(?:"
    + "|".join(re.escape(n).replace(r"\ ", r"\s+") for n in sorted(OUTSIDE_PLACES, key=len, reverse=True))
    + r")(?!\w)",
    re.I,
)
_LA_RE = re.compile(r"(?<![\w.])(?:L\.A\.|LA)(?!\w)")  # case-sensitive on purpose
_STREET_AFTER = re.compile(r"\.?\s+(?:" + "|".join(_STREET_WORDS) + r")\b", re.I)


def outside_place_named(place: str | None) -> str | None:
    """The well-known out-of-area place named in ``place`` (as written), or ``None``.

    ``None`` too when the name is a street ("Sacramento St") or part of an intersection.
    """
    if not isinstance(place, str) or not place.strip():
        return None
    if _INTERSECTION.search(place):
        return None
    for match in _NAMES_RE.finditer(place):
        if _STREET_AFTER.match(place, match.end()):
            continue
        return " ".join(match.group(0).split())
    found = _LA_RE.search(place)
    return found.group(0) if found else None


def in_bay_area(latlng: tuple[float, float]) -> bool:
    """Whether a (lat, lng) lies inside ``BAY_AREA_BOUNDS``; anything unreadable is outside."""
    try:
        lat, lng = float(latlng[0]), float(latlng[1])
    except (TypeError, ValueError, IndexError):
        return False
    if math.isnan(lat) or math.isnan(lng):
        return False
    b = BAY_AREA_BOUNDS
    return b["lat_min"] <= lat <= b["lat_max"] and b["lng_min"] <= lng <= b["lng_max"]


def clean_place(text: str | None) -> str | None:
    """A rider's place name as plain, short text: no control characters, one space, <= 40 chars."""
    if not isinstance(text, str):
        return None
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("C") or ch in " \t\n\r")
    text = " ".join(text.split())
    if not text:
        return None
    if len(text) > MAX_PLACE_CHARS:
        text = text[: MAX_PLACE_CHARS - 1].rstrip(" ,.;:-") + "…"
    return text


def scope_text(reason: str, place: str | None = None, choice: Choice | None = None) -> str:
    """One reply for ``reason``, picked with ``choice`` (``random.choice`` unless given).

    An out-of-area reply names ``place`` when one is given and usable; otherwise,
    and for the other reasons, a variant without a place is used.
    """
    pick = choice or random.choice
    if reason not in REASONS:
        reason = "off_topic"
    shown = clean_place(place) if reason in PLACE_VARIANTS else None
    pool = PLACE_VARIANTS[reason] if shown else PLAIN_VARIANTS[reason]
    return pick(pool).format(example=EXAMPLE_QUESTION, place=shown or "")


def _pattern(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{place\}|\{example\})", template)
    out = []
    for part in parts:
        if part == "{place}":
            out.append(r"[^\x00-\x1f]{1,%d}" % MAX_PLACE_CHARS)
        elif part == "{example}":
            out.append(re.escape(EXAMPLE_QUESTION))
        else:
            out.append(re.escape(part))
    return re.compile("".join(out))


_PATTERNS = {
    reason: tuple(_pattern(t) for t in PLAIN_VARIANTS[reason] + PLACE_VARIANTS.get(reason, ()))
    for reason in REASONS
}


def in_pool(reason: str, text: str) -> bool:
    """Whether ``text`` is one of ``reason``'s variants (with any place name filled in)."""
    if reason not in _PATTERNS or not isinstance(text, str):
        return False
    return any(p.fullmatch(text) for p in _PATTERNS[reason])
