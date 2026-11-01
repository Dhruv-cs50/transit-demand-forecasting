"""Digest, validator and template answer for the route assistant.

Every time and duration the user sees comes from Google Routes. Gemini only
explains, so its text is checked before it is shown: any clock time or minute
count it states must be one the options support, and vague durations ("about an
hour") are rejected because they re-state a figure Google gave exactly. When
Gemini fails or is rejected, ``template_explanation`` answers instead. The
template is rendered from the digest alone, and the digest scrubs every
free-text field it copies, so the template cannot contain a figure that the
validator would refuse.

One canonical form is shared by all three parts: a clock time is minutes since
midnight (Pacific, ``Settings.TZ``) and a duration is whole minutes.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from assistant.types import Alert, Context, Event, Leg, TripOption

DIGEST_LIMIT = 6000  # serialised characters, about 2k tokens
MAX_ALERTS = 3
MAX_EVENTS = 3
MAX_STATIONS = 4
MAX_TEXT = 140

GENERIC_ALERT = "There is a service alert on this agency; check its website for details."
GENERIC_EVENT = "an event"
GENERIC_PLACE = "a nearby place"
GENERIC_STOP = "a stop"
GENERIC_LINE = "this line"

# ----------------------------------------------------------------------------------
# Claims: what counts as a clock time or a duration in free text
# ----------------------------------------------------------------------------------

_ONES = (
    "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    "fifteen|sixteen|seventeen|eighteen|nineteen"
)
_UNITS = "one|two|three|four|five|six|seven|eight|nine"
_TENS = "twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
_NUM = rf"(?:\d+(?:\.\d+)?|(?:{_TENS})(?:[-\s](?:{_UNITS}))?|{_ONES})"
_MIN_UNIT = r"(?:minutes?|mins?)\b"
_HOUR_UNIT = r"(?:hours?|hrs?)\b"

_WORD_VALUES = {
    w: i
    for i, w in enumerate(_ONES.split("|"))
} | {w: 20 + 10 * i for i, w in enumerate(_TENS.split("|"))}

_AMPM = r"(?P<ap>[ap])\.?m(?![a-z])\.?"
_CLOCK_HM = re.compile(
    rf"(?<![\w.:/])(?P<h>\d{{1,2}}):(?P<m>\d{{2}})(?!\d)(?:\s*{_AMPM})?", re.I
)
_CLOCK_H = re.compile(rf"(?<![\w.:/])(?P<h>\d{{1,2}})\s*{_AMPM}", re.I)
_NOON = re.compile(r"\bnoon\b", re.I)
_MIDNIGHT = re.compile(r"\bmidnight\b", re.I)

_COMPOUND = re.compile(
    rf"(?<![\w.:/])(?P<h>{_NUM})\s*-?\s*{_HOUR_UNIT}"
    rf"(?:[\s,]*(?:and\s+)?(?P<m>{_NUM})\s*-?\s*{_MIN_UNIT})?",
    re.I,
)
# A hyphen joins two digits ("5-10 minutes"); between words it is part of one
# number ("twenty-four"), so words are only a range across "to" or a dash.
_RANGE = re.compile(
    rf"(?<![\w.:/])(?:(?P<a>\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(?P<b>{_NUM})"
    rf"|(?P<c>{_NUM})\s*(?:–|—|\bto)\s*(?P<d>{_NUM}))\s*-?\s*{_MIN_UNIT}",
    re.I,
)
_MINUTES = re.compile(rf"(?<![\w.:/])(?P<m>{_NUM})\s*-?\s*{_MIN_UNIT}", re.I)

# A duration stated without an exact figure. "rush hour" and "the express" are
# not here: only a quantified span of time is a claim.
_VAGUE = re.compile(
    r"\b(?:an?|half\s+an?|(?:a\s+)?quarter\s+of\s+an?)\s+(?:hour|hr)\b"
    r"|\b(?:half|quarter)[-\s]hour\b"
    r"|\bhour\s+and\s+a\s+half\b"
    r"|\band\s+a\s+half\s+(?:hours?|minutes?)\b"
    r"|\b(?:a\s+)?(?:couple|few|several|handful|bunch)\s+(?:of\s+)?(?:minutes?|mins?|hours?)\b"
    r"|\ban?\s+(?:minute|min)\b",
    re.I,
)


def _number(token: str) -> float:
    token = token.casefold().strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", token):
        return float(token)
    parts = re.split(r"[-\s]+", token)
    return float(sum(_WORD_VALUES[p] for p in parts))


def _blank(text: str, span: tuple[int, int]) -> str:
    return text[: span[0]] + " " * (span[1] - span[0]) + text[span[1] :]


def _clock_candidates(h: int, m: int, ap: str | None, has_zero: bool = False) -> set[int] | None:
    """Minutes since midnight a written time can mean; ``None`` if not a time."""
    if m > 59:
        return None
    if ap:
        if 1 <= h <= 12:
            return {(h % 12 + (12 if ap.casefold() == "p" else 0)) * 60 + m}
        return {h * 60 + m} if h <= 23 else None
    if h > 24:
        return None
    if has_zero or h >= 13 or h == 0:
        return {(h % 24) * 60 + m}
    # Bare "8:28": either reading may match a time Google gave.
    return {(h % 12) * 60 + m, (h % 12 + 12) * 60 + m}


def _scan(text: str) -> tuple[list[set[int]], list[float | None]]:
    """Every claim in ``text``: clock times and durations in whole minutes.

    Scanned in a fixed order, each match blanked before the next pass, so that
    "08:28 - 24 minutes" is a time and a duration (not the range "28 - 24"),
    "1 hr 12 min" is one 72-minute claim and "twenty-four minutes" is one 24.
    Clock times are sets of candidate minutes-of-day; a duration is a number of
    minutes, or ``None`` for one that is vague or not a whole minute count.
    """
    clocks: list[set[int]] = []
    durations: list[float | None] = []
    work = text

    def pass_clock(rx: re.Pattern[str], with_minutes: bool) -> None:
        nonlocal work
        for match in list(rx.finditer(work)):
            h = int(match["h"])
            m = int(match["m"]) if with_minutes else 0
            raw_h = match["h"]
            cands = _clock_candidates(h, m, match["ap"], has_zero=len(raw_h) == 2 and raw_h[0] == "0")
            if cands is None:
                continue
            clocks.append(cands)
            work = _blank(work, match.span())

    pass_clock(_CLOCK_HM, True)
    pass_clock(_CLOCK_H, False)
    for rx, value in ((_NOON, 12 * 60), (_MIDNIGHT, 0)):
        for match in list(rx.finditer(work)):
            clocks.append({value})
            work = _blank(work, match.span())

    for match in list(_COMPOUND.finditer(work)):
        total = _number(match["h"]) * 60 + (_number(match["m"]) if match["m"] else 0)
        durations.append(total)
        work = _blank(work, match.span())
    for match in list(_RANGE.finditer(work)):
        first, second = (match["a"], match["b"]) if match["a"] else (match["c"], match["d"])
        durations.extend((_number(first), _number(second)))
        work = _blank(work, match.span())
    for match in list(_MINUTES.finditer(work)):
        durations.append(_number(match["m"]))
        work = _blank(work, match.span())
    for match in list(_VAGUE.finditer(work)):
        durations.append(None)
        work = _blank(work, match.span())
    return clocks, durations


# ----------------------------------------------------------------------------------
# What the options support
# ----------------------------------------------------------------------------------


def _local(dt: datetime, tz: str) -> datetime:
    return dt.astimezone(ZoneInfo(tz))


def _floor_minute(dt: datetime, tz: str) -> datetime:
    """Departures round down: never tell someone to leave after the vehicle."""
    return _local(dt, tz).replace(second=0, microsecond=0)


def _ceil_minute(dt: datetime, tz: str) -> datetime:
    """Arrivals round up: never promise an earlier arrival than Google's."""
    local = _local(dt, tz)
    floor = local.replace(second=0, microsecond=0)
    return floor if floor == local else floor + timedelta(minutes=1)


def _mod(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _label12(dt: datetime) -> str:
    return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def _label24(dt: datetime) -> str:
    return f"{dt.hour:02d}:{dt.minute:02d}"


def _minutes(seconds: int) -> int:
    return int((seconds + 30) // 60)


def _span_minutes(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() // 60)


def _facts(options: list[TripOption], tz: str) -> tuple[set[int], set[int]]:
    """(clock times as minutes-of-day, durations in whole minutes) the options support."""
    clocks: set[int] = set()
    mins: set[int] = set()
    for o in options:
        depart, arrive = _floor_minute(o.depart, tz), _ceil_minute(o.arrive, tz)
        clocks |= {_mod(depart), _mod(arrive)}
        mins |= {_span_minutes(depart, arrive), _minutes(o.duration_s), _minutes(o.walk_s)}
        for leg in o.legs:
            mins.add(_minutes(leg.duration_s))
            if leg.depart is not None and leg.arrive is not None:
                ld, la = _floor_minute(leg.depart, tz), _ceil_minute(leg.arrive, tz)
                clocks |= {_mod(ld), _mod(la)}
                mins.add(_span_minutes(ld, la))
    return clocks, mins


def _duration_forms(n: int) -> list[str]:
    forms = [f"{n} min", f"{n} minutes"] if n != 1 else ["1 min", "1 minute"]
    if n >= 60:
        h, m = divmod(n, 60)
        hours = f"{h} hour" if h == 1 else f"{h} hours"
        if m == 0:
            forms += [f"{h} hr", hours]
        else:
            minutes = "1 minute" if m == 1 else f"{m} minutes"
            forms += [f"{h} hr {m} min", f"{hours} {minutes}"]
    return forms


def allowed_tokens(options: list[TripOption], tz: str) -> set[str]:
    """Every clock time and minute count derivable from the options, as written.

    Times come in 12-hour (``"6:05 PM"``) and 24-hour (``"18:05"``) form,
    counts as ``"52 min"`` and ``"52 minutes"`` (plus ``"1 hr 12 min"`` forms
    from an hour up). ``explanation_ok`` accepts the same facts in any other
    spelling too (``"6:05pm"``, ``"6.05"`` excepted).
    """
    clocks, mins = _facts(options, tz)
    tokens: set[str] = set()
    for value in clocks:
        h, m = divmod(value, 60)
        stamp = datetime(2000, 1, 1, h, m)
        tokens |= {_label12(stamp), _label24(stamp)}
    for n in mins:
        tokens |= set(_duration_forms(n))
    return tokens


def unverified_claims(text: str, options: list[TripOption], tz: str) -> list[str]:
    """Describe each clock time or duration in ``text`` the options do not support."""
    allowed_clocks, allowed_mins = _facts(options, tz)
    clocks, durations = _scan(text)
    bad: list[str] = []
    for cands in clocks:
        if not cands & allowed_clocks:
            bad.append("clock " + "/".join(sorted(f"{c // 60:02d}:{c % 60:02d}" for c in cands)))
    for value in durations:
        if value is None:
            bad.append("vague duration")
        elif value != int(value) or int(value) not in allowed_mins:
            bad.append(f"{value:g} min")
    return bad


def explanation_ok(text: str, options: list[TripOption], tz: str) -> bool:
    """True when every clock time and minute count in ``text`` is derivable.

    Blank text is not an explanation, so it fails (the template answers).
    """
    if not text or not text.strip():
        return False
    return not unverified_claims(text, options, tz)


# ----------------------------------------------------------------------------------
# Digest
# ----------------------------------------------------------------------------------


def _scrub(text: str | None, options: list[TripOption], tz: str, fallback: str, limit: int = MAX_TEXT) -> str:
    """Free text safe to repeat: unchanged unless it states an unsupported figure.

    The check runs on the whole text before it is truncated.
    """
    text = " ".join((text or "").split())
    if not text or unverified_claims(text, options, tz):
        return fallback
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:- ") + "…"
    return text


def _norm(text: str) -> str:
    text = text.casefold().replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


_GENERIC_LINES = {"express", "local", "limited", "weekday", "weekend", "rapid", "shuttle", "bullet", "owl"}


def _stop_keys(name: str | None) -> set[str]:
    if not name:
        return set()
    full = _norm(name)
    keys = {full}
    for suffix in (" caltrain station", " bart station", " station", " transit center"):
        if full.endswith(suffix):
            keys.add(full[: -len(suffix)])
    for prefix in ("san jose ", "san francisco ", "oakland "):
        if full.startswith(prefix):
            keys.add(full[len(prefix) :])
    return {k for k in keys if len(k) >= 5}


def _line_keys(line: str | None) -> tuple[set[str], set[str]]:
    """(route numbers, line-name phrases) used to recognise a line in an alert."""
    if not line:
        return set(), set()
    numbers = set(re.findall(r"\b\d+[a-z]?\b", line.casefold()))
    words = _norm(line)
    names = set() if numbers or words in _GENERIC_LINES or len(words) < 4 else {words}
    return numbers, names


def _relevance(alert: Alert, options: list[TripOption]) -> int | None:
    """``None`` when the alert's agency is not in the trip; else how many legs it matches.

    A match is the alert naming a stop or line of a leg of its own agency. Zero
    means the agency is on the trip but the alert names nothing on it.
    """
    padded = f" {_norm(alert.header)} "
    on_trip = False
    score = 0
    for option in options:
        for leg in option.legs:
            if leg.mode != "TRANSIT" or leg.agency != alert.agency:
                continue
            on_trip = True
            if any(f" {k} " in padded for stop in (leg.from_stop, leg.to_stop) for k in _stop_keys(stop)):
                score += 1
            numbers, names = _line_keys(leg.line)
            if numbers and re.search(r"\b(?:routes?|lines?)\b", padded):
                if any(re.search(rf"\b{n}\b", padded) for n in numbers):
                    score += 1
            if any(f" {n} " in padded for n in names):
                score += 1
    if not on_trip and alert.agency in {a for o in options for a in o.agencies}:
        on_trip = True
    return score if on_trip else None


def _rank_alerts(alerts: tuple[Alert, ...], options: list[TripOption], tz: str) -> list[dict[str, str]]:
    """At most ``MAX_ALERTS`` headers: those naming the trip's stops or lines first,
    then other alerts for agencies on the trip. Alerts for other agencies are dropped.
    A header that needs scrubbing sorts after one that does not."""
    ranked: list[tuple[tuple[int, int, int, int], Alert, str]] = []
    for i, alert in enumerate(alerts):
        score = _relevance(alert, options)
        if score is None:
            continue
        header = _scrub(alert.header, options, tz, GENERIC_ALERT)
        key = (0 if score else 1, 1 if header == GENERIC_ALERT else 0, -score, i)
        ranked.append((key, alert, header))
    ranked.sort(key=lambda r: r[0])
    return [{"agency": a.agency, "header": h} for _, a, h in ranked[:MAX_ALERTS]]


def _line_label(leg: Leg) -> str:
    agency = leg.agency if leg.agency and leg.agency != "other" else ""
    return " ".join(p for p in (agency, leg.line or "") if p)


def _digest_leg(leg: Leg, options: list[TripOption], tz: str) -> dict[str, Any]:
    if leg.mode == "WALK" or leg.depart is None or leg.arrive is None:
        return {"walk_minutes": _minutes(leg.duration_s)}
    depart, arrive = _floor_minute(leg.depart, tz), _ceil_minute(leg.arrive, tz)
    out: dict[str, Any] = {
        "agency": leg.agency,
        "line": _scrub(leg.line, options, tz, GENERIC_LINE, 40) if leg.line else None,
        "from": _scrub(leg.from_stop, options, tz, GENERIC_STOP, 60),
        "to": _scrub(leg.to_stop, options, tz, GENERIC_STOP, 60),
        "depart": _label12(depart),
        "arrive": _label12(arrive),
        "minutes": _span_minutes(depart, arrive),
    }
    if leg.headsign:
        out["toward"] = _scrub(leg.headsign, options, tz, "", 60) or None
    return {k: v for k, v in out.items() if v is not None}


def _digest_option(o: TripOption, options: list[TripOption], tz: str) -> dict[str, Any]:
    depart, arrive = _floor_minute(o.depart, tz), _ceil_minute(o.arrive, tz)
    legs = [_digest_leg(leg, options, tz) for leg in o.legs]
    lines: list[str] = []
    for leg, d in zip(o.legs, legs):
        if leg.mode == "TRANSIT":
            label = " ".join(p for p in (d.get("agency") if d.get("agency") != "other" else "", d.get("line")) if p)
            if label and label not in lines:
                lines.append(label)
    return {
        "rank": o.rank,
        "depart": _label12(depart),
        "arrive": _label12(arrive),
        "minutes": _span_minutes(depart, arrive),
        "agencies": list(o.agencies),
        "transfers": o.transfers,
        "walk_minutes": _minutes(o.walk_s),
        "lines": lines,
        "legs": legs,
    }


def _digest_events(events: tuple[Event, ...], options: list[TripOption], tz: str) -> list[dict[str, Any]]:
    # The start time is left out: it is a clock time the options cannot support,
    # so a sentence quoting it could never pass the validator.
    nearest = sorted(events, key=lambda e: (e.distance_km, e.start))[:MAX_EVENTS]
    return [
        {
            "name": _scrub(e.name, options, tz, GENERIC_EVENT, 80),
            "venue": _scrub(e.venue, options, tz, GENERIC_PLACE, 60),
            "distance_km": round(e.distance_km, 1),
        }
        for e in nearest
    ]


def _fit(digest: dict[str, Any]) -> dict[str, Any]:
    """Drop the least useful detail until the digest is under ``DIGEST_LIMIT``."""

    def size() -> int:
        return len(json.dumps(digest))

    steps = (
        lambda: digest.update(stations=digest["stations"][:1]),
        lambda: digest.update(stations=[]),
        lambda: digest.update(events=digest["events"][:1]),
        lambda: digest.update(events=[]),
        lambda: digest.update(alerts=digest["alerts"][:1]),
        lambda: digest.update(alerts=[]),
        lambda: [o.update(legs=[]) for o in digest["options"][1:]],
        lambda: [o.update(legs=[]) for o in digest["options"]],
        lambda: [o.update(lines=o["lines"][:2]) for o in digest["options"]],
    )
    for step in steps:
        if size() < DIGEST_LIMIT:
            break
        step()
    return digest


def build_digest(options: list[TripOption], ctx: Context, tz: str) -> dict[str, Any]:
    """Compact, JSON-able input for the explanation call.

    Times are Pacific (``tz``); departures are rounded down and arrivals up to
    the minute, and ``minutes`` is the span between the two displayed times.
    At most three alerts (most relevant to the trip first) and three events
    (nearest first). Serialised size is under ``DIGEST_LIMIT`` characters.
    """
    options = list(options)
    weather = None
    if ctx.weather is not None:
        weather = {
            "temp_f": int(round(ctx.weather.temp_c * 9 / 5 + 32)),
            "precip_mm": round(ctx.weather.precip_mm, 1),
            "wind_kmh": int(round(ctx.weather.wind_kmh)),
        }
    digest: dict[str, Any] = {
        "options": [_digest_option(o, options, tz) for o in options],
        "alerts": _rank_alerts(ctx.alerts, options, tz),
        "weather": weather,
        "events": _digest_events(ctx.events, options, tz),
        "stations": [
            {
                "station": _scrub(s.station, options, tz, "a station", 60),
                "typical_monthly": s.typical_monthly,
                "forecast_month": s.forecast_month,
                "forecast_p50": s.forecast_p50,
                "label": s.label,
            }
            for s in ctx.stations[:MAX_STATIONS]
        ],
        "missing": list(ctx.missing),
    }
    return _fit(digest)


# ----------------------------------------------------------------------------------
# Template answer
# ----------------------------------------------------------------------------------

_MISSING_NAMES = {
    "alerts": "service alerts",
    "weather": "the weather",
    "events": "nearby events",
    "stations": "station ridership context",
    "events:ticketmaster": "Ticketmaster events",
    "events:nhl": "the Sharks schedule",
}


def _missing_name(tool: str) -> str:
    return _MISSING_NAMES.get(tool, tool.replace(":", " ").replace("_", " "))


def _tags(options: list[dict[str, Any]], i: int) -> list[str]:
    """Plain-words reasons an option stands out; compared, never counted."""
    me = options[i]
    tags = ["earliest arrival"] if i == 0 else []
    others = [o for j, o in enumerate(options) if j != i]
    if others and all(me["transfers"] < o["transfers"] for o in others):
        tags.append("fewest transfers")
    if others and all(me["walk_minutes"] < o["walk_minutes"] for o in others):
        tags.append("least walking")
    return tags


def _transfers(n: int) -> str:
    return "no transfers" if n == 0 else f"{n} transfer" if n == 1 else f"{n} transfers"


def _option_line(options: list[dict[str, Any]], i: int) -> str:
    o = options[i]
    tags = _tags(options, i)
    head = f"Option {o['rank']}" + (f" ({', '.join(tags)})" if tags else "")
    parts = []
    for leg in o["legs"]:
        if "walk_minutes" in leg:
            continue
        label = " ".join(p for p in (leg["agency"] if leg.get("agency") != "other" else "", leg.get("line")) if p)
        parts.append(f"{label} from {leg['from']} to {leg['to']}".strip())
    ride = f" on {' then '.join(parts)}" if parts else ""
    return (
        f"{head}: leave {o['depart']}, arrive {o['arrive']} "
        f"({o['minutes']} min, {o['walk_minutes']} min walking, {_transfers(o['transfers'])}){ride}."
    )


def template_from_digest(digest: dict[str, Any]) -> str:
    """The fallback answer, rendered from ``digest`` and nothing else."""
    options = digest.get("options") or []
    lines: list[str] = []
    if not options:
        lines.append("No transit option was found for this trip.")
    for i in range(len(options)):
        lines.append(_option_line(options, i))
    for alert in digest.get("alerts") or []:
        lines.append(f"Alert ({alert['agency']}): {alert['header']}")
    weather = digest.get("weather")
    if weather:
        rain = "rain is possible" if weather["precip_mm"] >= 0.2 else "dry"
        lines.append(f"Weather near departure: about {weather['temp_f']}°F, {rain}.")
    for event in digest.get("events") or []:
        lines.append(f"{event['name']} at {event['venue']} may mean busier trains and stations nearby.")
    for s in (digest.get("stations") or [])[:2]:
        lines.append(
            f"Monthly context, not live crowding: {s['station']} typically sees about "
            f"{s['typical_monthly']:,} riders a month."
        )
    missing = digest.get("missing") or []
    if missing:
        names = ", ".join(dict.fromkeys(_missing_name(m) for m in missing))
        lines.append(f"Could not check: {names}.")
    return "\n".join(lines)


def template_explanation(options: list[TripOption], ctx: Context, tz: str) -> str:
    """Deterministic answer used when Gemini fails or ``explanation_ok`` is False."""
    return template_from_digest(build_digest(options, ctx, tz))
