"""Offline stand-ins for the LLM (Claude or Gemini), Google Routes and the context tools.

``ASSISTANT_FAKE=1`` wires these into the app so the chat panel can be built
without keys, and the service tests use the same classes (configured per test),
so what the panel sees is what the tests check. Nothing here touches the network.

Fake-mode triggers, matched on the rider's place names or message:
  * a destination containing "nowhere": Google finds no transit route;
  * a place containing "error": Google Routes fails;
  * "invent" anywhere in the message: the fake model states a time Google never
    gave, so the template replacement can be seen;
  * "los angeles", "san diego" or "las vegas": out of area; "drive" or "uber":
    another mode; "weather" or "joke": off topic (a ``scope`` reply);
  * no "from X to Y": the model asks a follow-up question.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo

from assistant.config import DISPLAY_TZ
from assistant.routing import RoutingError
from assistant.types import Context, FollowUp, Leg, OutOfScope, TripOption, TripQuery, Weather

PT = ZoneInfo(DISPLAY_TZ)
_UNSET: Any = object()
_FROM_TO = re.compile(r"\bfrom\s+(?P<o>.+?)\s+to\s+(?P<d>.+?)(?:\s+(?:at|in|tomorrow|tonight|now)\b.*)?[.?!]*$", re.I)


def fake_options(depart_at: datetime) -> list[TripOption]:
    """Two plausible options that leave shortly after ``depart_at``."""
    base = depart_at.astimezone(PT).replace(second=0, microsecond=0)
    out = []
    for rank, (wait_min, ride_min, agency, line, headsign) in enumerate(
        [(7, 38, "Caltrain", "Express", "San Francisco"), (16, 46, "VTA", "Rapid 522", "Alum Rock")], start=1
    ):
        lead_s, trail_s = 3 * 60, 4 * 60
        leave = base + timedelta(minutes=wait_min)
        arrive = leave + timedelta(minutes=ride_min)
        legs = (
            Leg("WALK", None, None, None, None, None, None, lead_s, None),
            Leg("TRANSIT", agency, line, "Mountain View", "San Jose Diridon", leave, arrive,  # type: ignore[arg-type]
                ride_min * 60, headsign),
            Leg("WALK", None, None, None, None, None, None, trail_s, None),
        )
        start = leave - timedelta(seconds=lead_s)
        end = arrive + timedelta(seconds=trail_s)
        out.append(
            TripOption(
                rank=rank, depart=start, arrive=end, duration_s=int((end - start).total_seconds()),
                transfers=0, walk_s=lead_s + trail_s, agencies=(agency,), legs=legs, polyline="",
                origin_latlng=(37.3946, -122.0765), dest_latlng=(37.3327, -121.9010),
            )
        )
    return out


class FakeRouting:
    """Stands in for ``plan_trips``. ``plan`` counts calls."""

    def __init__(self, options: list[TripOption] | None = None, error: Exception | None = None, delay_s: float = 0):
        self.options = options
        self.error = error
        self.delay_s = delay_s
        self.calls = 0

    async def plan(self, q: TripQuery) -> list[TripOption]:
        self.calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.error is not None:
            raise self.error
        if "error" in (q.origin + " " + q.destination).lower():
            raise RoutingError("fake routing outage")
        if "nowhere" in q.destination.lower():
            return []
        return list(self.options) if self.options is not None else fake_options(q.depart_at)


class FakeContext:
    """Stands in for ``gather_context``: instant, one dry-weather reading."""

    def __init__(self, ctx: Context | None = None) -> None:
        self.ctx = ctx
        self.calls = 0

    async def gather(self, options: list[TripOption], q: TripQuery) -> Context:
        self.calls += 1
        if self.ctx is not None:
            return self.ctx
        return Context(alerts=(), weather=Weather(0.0, 15.0, 10.0), events=(), stations=(), missing=())


def canned_text(digest: dict[str, Any], invent: bool = False) -> str:
    """A short explanation built only from the digest's own figures."""
    sentences = [
        f"Option {o['rank']} leaves {o['depart']} and arrives {o['arrive']}, taking {o['minutes']} min."
        for o in digest.get("options", [])[:2]
    ]
    if invent:
        sentences.append("The next one is only 33 min away.")
    return " ".join(sentences)


class FakeGemini:
    """Stands in for the LLM client (``llm_claude.Claude`` or ``llm.Gemini``). Both methods count calls.

    ``query`` fixes call 1's answer (``None`` = unusable output, so the form);
    left unset, the message is read for "from X to Y". ``chunks`` fixes call 2's
    stream; left unset, ``canned_text`` is streamed in small pieces.
    """

    def __init__(
        self,
        *,
        query: Any = _UNSET,
        extract_error: Exception | None = None,
        extract_delay_s: float = 0,
        chunks: list[str] | None = None,
        chunk_delay_s: float = 0,
        explain_error: Exception | None = None,
    ) -> None:
        self.query = query
        self.extract_error = extract_error
        self.extract_delay_s = extract_delay_s
        self.chunks = chunks
        self.chunk_delay_s = chunk_delay_s
        self.explain_error = explain_error
        self.extract_calls = 0
        self.explain_calls = 0
        self.stream_closed = False  # set when the explain stream is closed, however it ended
        self._invent = False

    async def extract(self, message: str, now: datetime) -> TripQuery | FollowUp | OutOfScope | None:
        self.extract_calls += 1
        if self.extract_delay_s:
            await asyncio.sleep(self.extract_delay_s)
        if self.extract_error is not None:
            raise self.extract_error
        self._invent = "invent" in message.lower()
        if self.query is not _UNSET:
            return self.query
        low = message.lower()
        for word in ("los angeles", "san diego", "las vegas"):
            if word in low:
                return OutOfScope("out_of_area", word.title())
        if "drive" in low or "uber" in low:
            return OutOfScope("other_mode")
        if "weather" in low or "joke" in low:
            return OutOfScope("off_topic")
        found = _FROM_TO.search(message.strip())
        if not found:
            return FollowUp("Where are you starting from, and where would you like to go?")
        return TripQuery(found["o"].strip(), found["d"].strip(), now)

    async def explain_stream(self, digest: dict[str, Any]) -> AsyncIterator[str]:
        self.explain_calls += 1
        if self.explain_error is not None:
            raise self.explain_error
        chunks = self.chunks
        if chunks is None:
            text = canned_text(digest, self._invent)
            chunks = re.findall(r".{1,24}", text, re.S)
        try:
            for chunk in chunks:
                if self.chunk_delay_s:
                    await asyncio.sleep(self.chunk_delay_s)
                yield chunk
        finally:
            self.stream_closed = True
