"""The route assistant's two LLM calls: the Gemini client, plus the parsing every provider shares.

``LLM_PROVIDER`` picks the client (``assistant.service.make_llm``): ``Claude`` in
``assistant.llm_claude`` (Anthropic API), or ``Gemini`` here (Vertex AI), which
is the rollback. Both send the same system prompts and user turns
(``_extract_input``, ``_explain_input``) and read call 1 with the same
``_to_query``, against the same seven fields (``EXTRACT_SCHEMA``).

Exactly two calls are made for an answered question; on Gemini, both on the Flash tier:

1. ``Gemini.extract``: the rider's message becomes a ``TripQuery`` (or a
   ``FollowUp``, an ``OutOfScope`` when the schema's ``scope`` says the question
   is out of bounds, or ``None`` when the output is unusable so the service
   shows the origin/destination form). JSON with a response schema, <= 120
   output tokens. The model only classifies: it never writes the refusal.
2. ``Gemini.explain_stream``: the digest becomes a short explanation, streamed,
   <= 250 output tokens, temperature 0.2. The service checks the text with
   ``explanation_ok`` before showing it.

Gemini is reached through ``google-genai`` in Vertex AI mode with the service
account (application default credentials): there is no API key. The rider's
text is only ever sent as ``contents``; the system prompt, response schema and
token caps are fixed, so a message cannot change them.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types

from assistant.config import DISPLAY_TZ, Settings
from assistant.prompts import EXPLAIN_SYSTEM, EXTRACT_SYSTEM
from assistant.scope import outside_place_named
from assistant.station_names import normalise_place
from assistant.types import FollowUp, OutOfScope, TripQuery

EXTRACT_MAX_TOKENS = 120
EXPLAIN_MAX_TOKENS = 250
EXPLAIN_TEMPERATURE = 0.2
MAX_PLACE_CHARS = 200
# The model rounds "now" to the minute; anything within this window of ``now`` is "now", not the past.
PAST_GRACE_S = 120
# The start-up warm-up: a fixed text and a one-token cap, so it costs almost nothing.
WARMUP_CONTENTS = "ping"
WARMUP_MAX_TOKENS = 1

_FIELDS = ("scope", "scope_reason", "outside_place", "origin", "destination", "depart_at", "follow_up")
SCOPES = ("trip", "out_of_scope")
SCOPE_REASONS = ("out_of_area", "other_mode", "off_topic")
# JSON schema for call 1. Every key is required; all but ``scope`` may be null, so the reply
# always has all seven. ``scope`` comes first so the model decides it before the places.
EXTRACT_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "scope": types.Schema(
            type=types.Type.STRING,
            enum=list(SCOPES),
            description="trip for a Bay Area public-transit trip request, else out_of_scope",
        ),
        "scope_reason": types.Schema(
            type=types.Type.STRING,
            enum=list(SCOPE_REASONS),
            nullable=True,
            description="Why it is out of scope, or null for a trip",
        ),
        "outside_place": types.Schema(
            type=types.Type.STRING,
            nullable=True,
            description="For out_of_area: the origin or destination outside the Bay Area, as written",
        ),
        "origin": types.Schema(type=types.Type.STRING, nullable=True, description="Origin place as written, or null"),
        "destination": types.Schema(
            type=types.Type.STRING, nullable=True, description="Destination place as written, or null"
        ),
        "depart_at": types.Schema(
            type=types.Type.STRING,
            nullable=True,
            description="Departure time, ISO 8601 with Pacific offset, or null for now",
        ),
        "follow_up": types.Schema(
            type=types.Type.STRING, nullable=True, description="Question to ask if origin or destination is missing"
        ),
    },
    required=list(_FIELDS),
    property_ordering=list(_FIELDS),
)

_UNUSABLE = object()


def _no_thinking() -> types.ThinkingConfig:
    # Thinking tokens count against max_output_tokens on Flash models: left on, they can
    # consume the 120/250 caps and return an empty answer.
    return types.ThinkingConfig(thinking_budget=0)


def _place(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= MAX_PLACE_CHARS else None


def _pacific(naive: datetime, tz: ZoneInfo, now: datetime) -> datetime:
    """A wall-clock time read as Pacific, as a real instant.

    An ambiguous time (the repeated 01:00-01:59 when clocks fall back) has two
    readings, ``fold`` 0 (PDT) and 1 (PST): the first one that is not in the past
    is taken, as that is the one the rider can still catch. A time in the
    spring-forward gap does not exist: it is read with the offset in force before
    the change (``fold`` 0), so 02:15 becomes 03:15 PDT. Either way the result is
    normalised through UTC, so its wall time and offset are real.
    """
    readings = [naive.replace(tzinfo=tz, fold=f).astimezone(timezone.utc) for f in (0, 1)]
    floor = now.astimezone(timezone.utc).timestamp() - PAST_GRACE_S
    chosen = next((r for r in readings if r.timestamp() >= floor), readings[0])
    return chosen.astimezone(tz)


def _parse_time(value: Any, tz: ZoneInfo, now: datetime) -> Any:
    """A tz-aware time, ``None`` for no time, or ``_UNUSABLE`` when it does not parse."""
    if value is None:
        return None
    if not isinstance(value, str):
        return _UNUSABLE
    if not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return _UNUSABLE
    if parsed.tzinfo is None:
        return _pacific(parsed, tz, now)
    return parsed.astimezone(timezone.utc).astimezone(tz)


def _extract_input(message: str, now: datetime) -> tuple[datetime, ZoneInfo, str]:
    """Call 1's user turn, shared by every provider: ``now`` in Pacific time, then the message as data."""
    tz = ZoneInfo(DISPLAY_TZ)
    now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    contents = f"now: {now.isoformat(timespec='seconds')} ({DISPLAY_TZ})\nrider message:\n{message}"
    return now, tz, contents


def _explain_input(digest: dict[str, Any]) -> str:
    """Call 2's user turn, shared by every provider: the digest is the only payload."""
    return "digest:\n" + json.dumps(digest, separators=(",", ":"))


class Gemini:
    """The two calls on Gemini. ``client`` is injectable so tests never touch the network."""

    def __init__(self, settings: Settings, client: Any = None):
        self._model = settings.GEMINI_MODEL
        self._client = client or genai.Client(
            vertexai=True, project=settings.GCP_PROJECT, location=settings.VERTEX_REGION
        )

    async def warm(self) -> None:
        """Open the connection and fetch credentials before the first rider asks.

        A one-token call on a fixed text to the same model, so the first real
        extract on a fresh instance does not pay for TLS, the token exchange and
        the model's first-request latency. Raises on failure; the caller only logs.
        """
        config = types.GenerateContentConfig(
            max_output_tokens=WARMUP_MAX_TOKENS, temperature=0.0, thinking_config=_no_thinking()
        )
        await self._client.aio.models.generate_content(model=self._model, contents=WARMUP_CONTENTS, config=config)

    async def extract(self, message: str, now: datetime) -> TripQuery | FollowUp | OutOfScope | None:
        """Call 1. ``None`` when the model's output does not parse against the schema."""
        now, tz, contents = _extract_input(message, now)
        config = types.GenerateContentConfig(
            system_instruction=EXTRACT_SYSTEM,
            response_mime_type="application/json",
            response_schema=EXTRACT_SCHEMA,
            max_output_tokens=EXTRACT_MAX_TOKENS,
            temperature=0.0,
            thinking_config=_no_thinking(),
        )
        response = await self._client.aio.models.generate_content(
            model=self._model, contents=contents, config=config
        )
        return _to_query(getattr(response, "text", None), now, tz)

    async def explain_stream(self, digest: dict[str, Any]) -> AsyncIterator[str]:
        """Call 2: the explanation as text chunks. The request is sent on first iteration."""
        config = types.GenerateContentConfig(
            system_instruction=EXPLAIN_SYSTEM,
            max_output_tokens=EXPLAIN_MAX_TOKENS,
            temperature=EXPLAIN_TEMPERATURE,
            thinking_config=_no_thinking(),
        )
        stream = await self._client.aio.models.generate_content_stream(
            model=self._model, contents=_explain_input(digest), config=config
        )
        async for chunk in stream:
            text = getattr(chunk, "text", None)
            if text:
                yield text


def _outside_place(data: dict[str, Any]) -> str | None:
    """The out-of-area place, only when it is (part of) the trip's own origin or destination.

    So whatever else the model writes in ``outside_place`` never reaches the reply.
    """
    outside = _place(data.get("outside_place"))
    if outside is None:
        return None
    o = outside.casefold()
    for end in (_place(data.get("origin")), _place(data.get("destination"))):
        if end is not None and (o == end.casefold() or o in end.casefold()):
            return outside
    return None


def _to_query(raw: str | None, now: datetime, tz: ZoneInfo) -> TripQuery | FollowUp | OutOfScope | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    # Scope first: an out-of-bounds question is declined even when it names no places.
    scope = data.get("scope")
    if scope == "out_of_scope":
        reason = data.get("scope_reason")
        if reason not in SCOPE_REASONS:
            reason = "off_topic"
        place = _outside_place(data) if reason == "out_of_area" else None
        return OutOfScope(reason, place)
    if scope != "trip":
        return None

    origin, destination = _place(data.get("origin")), _place(data.get("destination"))
    question = data.get("follow_up")
    question = question.strip() if isinstance(question, str) and question.strip() else None
    if origin is None or destination is None:
        # One end is known: a well-known place outside the area is refused now ("to San Diego"),
        # rather than asked about. The service runs the same deny-list once both ends are known.
        named = outside_place_named(destination) or outside_place_named(origin)
        if named is not None:
            return OutOfScope("out_of_area", named)
        # A place is missing (or unusable): ask, or fall back to the form when there is no question.
        return FollowUp(question) if question else None

    # "Winchester" -> "Winchester VTA station": only bare names on the station allowlist.
    origin, destination = normalise_place(origin), normalise_place(destination)

    depart = _parse_time(data.get("depart_at"), tz, now)
    if depart is _UNUSABLE:
        return None
    replaced = False
    # Compare instants, never Pacific wall clocks: two datetimes sharing one tzinfo
    # subtract and compare by wall time and ignore ``fold``, which is an hour wrong
    # around the fall-back hour.
    if depart is None:
        depart = now
    else:
        ago_s = now.timestamp() - depart.timestamp()  # timestamp() honours fold
        if ago_s > PAST_GRACE_S:
            depart, replaced = now, True
        elif ago_s > 0:
            depart = now
    return TripQuery(origin=origin, destination=destination, depart_at=depart, past_time_replaced=replaced)
