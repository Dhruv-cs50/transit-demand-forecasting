"""The route assistant's two LLM calls on Claude, through the Anthropic API.

The same contract as ``assistant.llm.Gemini`` (``extract``, ``explain_stream``,
``warm``), with the same system prompts, user turns and call-1 parser
(``_to_query``), so the service does not know which provider it is talking to.

1. ``Claude.extract``: structured output against ``EXTRACT_JSON_SCHEMA`` (the
   Gemini schema translated to plain JSON Schema), <= ``EXTRACT_MAX_TOKENS``.
   A refusal, a reply cut off at the token cap, or no text block is ``None``,
   so the service shows the origin/destination form.
2. ``Claude.explain_stream``: the explanation as text deltas, <= ``EXPLAIN_MAX_TOKENS``.
   A refusal or a reply cut off at the token cap raises ``ClaudeRefusal`` once
   the stream ends, so the service replaces whatever was shown with the template.

Request shape, fixed for every call (Claude Haiku 5.5):

- No ``temperature``, ``top_p`` or ``top_k``: the model rejects them (HTTP 400).
- ``thinking`` disabled, at effort ``low`` (disabled is accepted only at
  low/medium/high). Thinking would count against the small token caps.
- No assistant prefill (HTTP 400) and no ``fallbacks`` (Haiku has none).
- Token caps sit above Gemini's 120/250: Haiku's tokenizer counts ~30% more
  tokens for the same text.

The client has a short timeout and no retries: the service bounds each call
(4 s by default) and a retry could not fit, while the SDK's defaults (10 min,
two retries) would hold a dead connection open. SDK errors are not caught here;
the service already treats any exception from a call as "show the form" (call
1), "use the template" (call 2) or "log and carry on" (warm-up).

The API key comes from ``ANTHROPIC_API_KEY`` (Secret Manager on Cloud Run). The
rider's text is only ever sent as the user turn.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, AsyncIterator

import anthropic
from google.genai import types

from assistant.config import Settings
from assistant.llm import (
    _FIELDS,
    EXTRACT_SCHEMA,
    WARMUP_CONTENTS,
    _explain_input,
    _extract_input,
    _to_query,
)
from assistant.prompts import EXPLAIN_SYSTEM, EXTRACT_SYSTEM
from assistant.types import FollowUp, OutOfScope, TripQuery

EXTRACT_MAX_TOKENS = 200
EXPLAIN_MAX_TOKENS = 350
WARMUP_MAX_TOKENS = 1
EFFORT = "low"
# The SDK timeout sits just above the service's own deadlines, so those fire first.
CLIENT_TIMEOUT_MARGIN_S = 1.0
# Replies that cannot be a complete answer: the form (call 1) or the template (call 2).
_UNUSABLE_STOPS = ("refusal", "max_tokens")


class ClaudeRefusal(RuntimeError):
    """The explanation is unusable: Claude declined (``refusal``) or hit the cap (``max_tokens``)."""


def _json_schema(schema: types.Schema) -> dict[str, Any]:
    """``EXTRACT_SCHEMA`` as plain JSON Schema for structured outputs.

    Same fields, order (``scope`` first), enums and descriptions. A nullable
    field is ``anyOf`` a string and null, so a nullable enum still admits null.
    Every field is required and no other key is allowed.
    """
    if list(schema.required or []) != list(_FIELDS):
        raise ValueError("EXTRACT_SCHEMA.required must list every field, in order")
    properties: dict[str, Any] = {}
    for name in _FIELDS:
        prop = schema.properties[name]
        if prop.type != types.Type.STRING:
            raise ValueError(f"EXTRACT_SCHEMA.{name}: only string fields are translated")
        base: dict[str, Any] = {"type": "string"}
        if prop.enum:
            base["enum"] = list(prop.enum)
        entry: dict[str, Any] = {"anyOf": [base, {"type": "null"}]} if prop.nullable else base
        if prop.description:
            entry = {"description": prop.description, **entry}
        properties[name] = entry
    return {"type": "object", "properties": properties, "required": list(_FIELDS), "additionalProperties": False}


EXTRACT_JSON_SCHEMA = _json_schema(EXTRACT_SCHEMA)


def _thinking_off() -> dict[str, str]:
    return {"type": "disabled"}


def _extract_format() -> dict[str, Any]:
    return {"type": "json_schema", "schema": EXTRACT_JSON_SCHEMA}


def _user(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


def _reply_text(response: Any) -> str | None:
    """The answer's text, read by block type (a thinking block may come first), or ``None``."""
    if getattr(response, "stop_reason", None) in _UNUSABLE_STOPS:
        return None
    content = getattr(response, "content", None) or []
    return next((b.text for b in content if getattr(b, "type", None) == "text"), None)


def client_timeout(settings: Settings) -> float:
    return float(max(settings.EXTRACT_TIMEOUT_S, settings.EXPLAIN_TIMEOUT_S) + CLIENT_TIMEOUT_MARGIN_S)


class Claude:
    """The two calls on Claude. ``client`` is injectable so tests never touch the network."""

    def __init__(self, settings: Settings, client: Any = None):
        self._model = settings.ANTHROPIC_MODEL
        self._client = client or anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            timeout=client_timeout(settings),
            max_retries=0,
        )

    async def warm(self) -> None:
        """Open the connection before the first rider asks: a one-token call on a fixed text.

        It carries the extract schema, so the API's one-time compile of a new
        schema (then cached) is paid here rather than inside the first rider's
        4 s extract. The one-token reply is cut off and thrown away. Raises on
        failure; the caller only logs.
        """
        await self._client.messages.create(
            model=self._model,
            max_tokens=WARMUP_MAX_TOKENS,
            messages=_user(WARMUP_CONTENTS),
            thinking=_thinking_off(),
            output_config={"effort": EFFORT, "format": _extract_format()},
        )

    async def extract(self, message: str, now: datetime) -> TripQuery | FollowUp | OutOfScope | None:
        """Call 1. ``None`` when the reply is refused, cut off, missing or does not parse."""
        now, tz, contents = _extract_input(message, now)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=EXTRACT_MAX_TOKENS,
            system=EXTRACT_SYSTEM,
            messages=_user(contents),
            thinking=_thinking_off(),
            output_config={"effort": EFFORT, "format": _extract_format()},
        )
        return _to_query(_reply_text(response), now, tz)

    async def explain_stream(self, digest: dict[str, Any]) -> AsyncIterator[str]:
        """Call 2: the explanation as text deltas. The request is sent on first iteration.

        Closing the generator early (the service's validator rejected a
        sentence) exits the ``async with`` and so closes the SDK stream.
        """
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=EXPLAIN_MAX_TOKENS,
            system=EXPLAIN_SYSTEM,
            messages=_user(_explain_input(digest)),
            thinking=_thinking_off(),
            output_config={"effort": EFFORT},
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    yield text
            final = await stream.get_final_message()
        stop = getattr(final, "stop_reason", None)
        if stop in _UNUSABLE_STOPS:
            # A refusal, or a reply cut off at the cap: the last sentence may be a fragment.
            raise ClaudeRefusal(f"explanation unusable: stop_reason={stop}")
