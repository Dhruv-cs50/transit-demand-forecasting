"""The route assistant's two Gemini calls, on Vertex AI.

Exactly two calls are made for an answered question, both on the Flash tier:

1. ``Gemini.extract``: the rider's message becomes a ``TripQuery`` (or a
   ``FollowUp``, or ``None`` when the output is unusable so the service shows
   the origin/destination form). JSON with a response schema, <= 120 output
   tokens.
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
from datetime import datetime
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types

from assistant.config import DISPLAY_TZ, Settings
from assistant.prompts import EXPLAIN_SYSTEM, EXTRACT_SYSTEM
from assistant.types import FollowUp, TripQuery

EXTRACT_MAX_TOKENS = 120
EXPLAIN_MAX_TOKENS = 250
EXPLAIN_TEMPERATURE = 0.2
MAX_PLACE_CHARS = 200
# The model rounds "now" to the minute; anything within this window of ``now`` is "now", not the past.
PAST_GRACE_S = 120

_FIELDS = ("origin", "destination", "depart_at", "follow_up")
# JSON schema for call 1. Every key is required but may be null, so the reply always has all four.
EXTRACT_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
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


def _parse_time(value: Any, tz: ZoneInfo) -> Any:
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
    return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)


class Gemini:
    """The two calls. ``client`` is injectable so tests never touch the network."""

    def __init__(self, settings: Settings, client: Any = None):
        self._model = settings.GEMINI_MODEL
        self._client = client or genai.Client(
            vertexai=True, project=settings.GCP_PROJECT, location=settings.VERTEX_REGION
        )

    async def extract(self, message: str, now: datetime) -> TripQuery | FollowUp | None:
        """Call 1. ``None`` when the model's output does not parse against the schema."""
        tz = ZoneInfo(DISPLAY_TZ)
        now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
        config = types.GenerateContentConfig(
            system_instruction=EXTRACT_SYSTEM,
            response_mime_type="application/json",
            response_schema=EXTRACT_SCHEMA,
            max_output_tokens=EXTRACT_MAX_TOKENS,
            temperature=0.0,
            thinking_config=_no_thinking(),
        )
        contents = f"now: {now.isoformat(timespec='seconds')} ({DISPLAY_TZ})\nrider message:\n{message}"
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
        contents = "digest:\n" + json.dumps(digest, separators=(",", ":"))
        stream = await self._client.aio.models.generate_content_stream(
            model=self._model, contents=contents, config=config
        )
        async for chunk in stream:
            text = getattr(chunk, "text", None)
            if text:
                yield text


def _to_query(raw: str | None, now: datetime, tz: ZoneInfo) -> TripQuery | FollowUp | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    origin, destination = _place(data.get("origin")), _place(data.get("destination"))
    question = data.get("follow_up")
    question = question.strip() if isinstance(question, str) and question.strip() else None
    if origin is None or destination is None:
        # A place is missing (or unusable): ask, or fall back to the form when there is no question.
        return FollowUp(question) if question else None

    depart = _parse_time(data.get("depart_at"), tz)
    if depart is _UNUSABLE:
        return None
    replaced = False
    if depart is None:
        depart = now
    elif (now - depart).total_seconds() > PAST_GRACE_S:
        depart, replaced = now, True
    elif depart < now:
        depart = now
    return TripQuery(origin=origin, destination=destination, depart_at=depart, past_time_replaced=replaced)
