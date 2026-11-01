"""The route assistant's HTTP service: ``POST /chat`` streams NDJSON events.

One question runs: Gemini call 1 (extract) -> one Google Routes call -> the
``options`` event, sent as soon as routing returns -> the four context tools ->
Gemini call 2 (explain), streamed and checked a sentence at a time -> ``caveats``
-> ``done``. Anything that cannot be trusted is replaced by the deterministic
template answer; a time Google did not give is never shown.

Events, one JSON object per line: ``follow_up`` | ``form`` (then the stream
ends), or ``options`` (with ``maps_link`` and no options when there is no route
or Routing failed), ``text``*, ``replace``?, ``caveats``, ``done``.

Logging: one structured line per request with latencies and event counts and
nothing the rider typed. CORS: the panel calls the service cross-origin from
the two site hosts (``ALLOWED_ORIGINS``) and, for development, from localhost.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from assistant import context_tools  # noqa: F401  (installs the httpx log redaction; keep it imported)
from assistant.answer import build_digest, explanation_ok, template_explanation
from assistant.config import DISPLAY_TZ, Settings, load_settings
from assistant.context_tools import gather_context
from assistant.routing import AREA_SUFFIX, RoutingError, plan_trips, same_place
from assistant.types import Context, FollowUp, TripOption, TripQuery

log = logging.getLogger("assistant.service")

TZ = DISPLAY_TZ
ATTRIBUTION = "Routes by Google"
EXTRACT_TIMEOUT_S = 2.5
# plan_trips has its own 2.5 s HTTP timeout; this outer bound catches anything that hangs past it.
ROUTING_DEADLINE_S = 3.0
ROUTING_CACHE_TTL_S = 600
CACHE_BUCKET_S = 300  # depart_at is rounded down to 5 minutes in the cache key
RATE_WINDOW_S = 3600
MAX_BODY_BYTES = 8192
MAX_IP_CHARS = 64
# The two hosts that serve the site (Firebase Hosting, App Engine); localhost on any port for development.
ALLOWED_ORIGINS = (
    "https://cs-163-final-project-tra-f1136.web.app",
    "https://cs-163-final-project-tra-f1136.wl.r.appspot.com",
)
LOCAL_ORIGIN_RE = r"http://(localhost|127\.0\.0\.1)(:\d+)?"

SAME_PLACE_QUESTION = "Your start and end look like the same place. Please give me a different destination."
SAFE_TEXT = "The route options are shown above. Check the times with Google Maps before you travel."
PAST_TIME_NOTE = "The time you gave has already passed, so these options start from now."
TEMPLATE_NOTE = "This summary was written directly from the route data."

PlanFn = Callable[[TripQuery], Awaitable[list[TripOption]]]
GatherFn = Callable[[list[TripOption], TripQuery], Awaitable[Context]]


@dataclass
class Services:
    """The three things the service calls out to. Tests and fake mode inject fakes."""

    gemini: Any  # .extract(message, now) and .explain_stream(digest)
    plan: PlanFn
    gather: GatherFn


def real_services(settings: Settings, http: httpx.AsyncClient, gemini: Any = None) -> Services:
    """Google Routes and the context tools over ``http``; Gemini on Vertex AI unless given."""
    if gemini is None:
        from assistant.llm import Gemini

        gemini = Gemini(settings)

    async def plan(q: TripQuery) -> list[TripOption]:
        return await plan_trips(q, http, settings.ROUTES_API_KEY)

    async def gather(options: list[TripOption], q: TripQuery) -> Context:
        return await gather_context(options, q, http, settings)

    return Services(gemini=gemini, plan=plan, gather=gather)


def fake_services() -> Services:
    from assistant.fakes import FakeContext, FakeGemini, FakeRouting

    routing, context = FakeRouting(), FakeContext()
    return Services(gemini=FakeGemini(), plan=routing.plan, gather=context.gather)


# --- request helpers --------------------------------------------------------------


def client_ip(request: Request) -> str:
    """The rider's address: the last ``X-Forwarded-For`` hop, else the peer.

    Cloud Run appends the real client address as the last hop; earlier hops are
    whatever the client sent, so trusting them would let anyone reset the limit.
    """
    last = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    if last and len(last) <= MAX_IP_CHARS:
        return last
    return request.client.host if request.client else "unknown"


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def cache_key(q: TripQuery) -> tuple[str, str, int]:
    return (_norm(q.origin), _norm(q.destination), int(q.depart_at.timestamp() // CACHE_BUCKET_S))


def _address(text: str) -> str:
    text = text.strip()
    return text if "," in text else text + AREA_SUFFIX


def maps_link(q: TripQuery) -> str:
    params = {
        "api": "1",
        "origin": _address(q.origin),
        "destination": _address(q.destination),
        "travelmode": "transit",
    }
    return "https://www.google.com/maps/dir/?" + urlencode(params, quote_via=quote)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(ZoneInfo(TZ)).isoformat() if dt else None


def option_json(option: TripOption, shown: dict[str, Any]) -> dict[str, Any]:
    """A TripOption as JSON: ISO times (Pacific) plus the display strings the explanation uses.

    ``shown`` is the matching option from ``build_digest``, so the panel and the
    validator format every time and minute count identically.
    """
    shown_legs = shown.get("legs") or []
    legs = []
    for i, leg in enumerate(option.legs):
        d = shown_legs[i] if i < len(shown_legs) else {}
        legs.append(
            {
                "mode": leg.mode,
                "agency": leg.agency,
                "line": leg.line,
                "from_stop": leg.from_stop,
                "to_stop": leg.to_stop,
                "depart": _iso(leg.depart),
                "arrive": _iso(leg.arrive),
                "depart_display": d.get("depart"),
                "arrive_display": d.get("arrive"),
                "duration_s": leg.duration_s,
                "minutes": d.get("minutes", d.get("walk_minutes")),
                "headsign": leg.headsign,
            }
        )
    return {
        "rank": option.rank,
        "depart": _iso(option.depart),
        "arrive": _iso(option.arrive),
        "depart_display": shown.get("depart"),
        "arrive_display": shown.get("arrive"),
        "duration_s": option.duration_s,
        "minutes": shown.get("minutes"),
        "transfers": option.transfers,
        "walk_s": option.walk_s,
        "walk_minutes": shown.get("walk_minutes"),
        "agencies": list(option.agencies),
        "lines": shown.get("lines", []),
        "legs": legs,
        "polyline": option.polyline,
        "origin_latlng": list(option.origin_latlng),
        "dest_latlng": list(option.dest_latlng),
    }


def options_event(options: list[TripOption]) -> dict[str, Any]:
    digest = build_digest(options, Context(alerts=(), weather=None, events=(), stations=(), missing=()), TZ)
    shown = digest["options"]
    return {
        "type": "options",
        "options": [option_json(o, shown[i] if i < len(shown) else {}) for i, o in enumerate(options)],
        "attribution": ATTRIBUTION,
    }


# Sentence = text up to . ! ? (plus closing quotes) followed by whitespace, or a newline.
_SENTENCE = re.compile(r".*?(?:[.!?]+[\"')\]]*\s+|\n\s*)", re.S)


def split_sentences(buffer: str) -> tuple[list[str], str]:
    """Complete sentences (each keeping its trailing whitespace) and the unfinished rest."""
    done: list[str] = []
    end = 0
    for match in _SENTENCE.finditer(buffer):
        done.append(match.group())
        end = match.end()
    return done, buffer[end:]


def _ms(since: float) -> int:
    return max(0, int(round((time.perf_counter() - since) * 1000)))


def _encode(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


class _Reject(Exception):
    """Gemini's explanation cannot be shown."""


# --- the explanation ----------------------------------------------------------------


async def _explain(
    services: Services, settings: Settings, options: list[TripOption], ctx: Context, digest: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    """``text`` events for each sentence that passes ``explanation_ok``.

    On the first failing sentence, an explanation timeout, an error from Gemini
    or an empty answer: stop the Gemini stream and yield one ``replace`` with
    the template.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + settings.EXPLAIN_TIMEOUT_S
    stream = None
    shown = ""
    buffer = ""

    def check(sentence: str) -> None:
        if not explanation_ok(sentence, options, TZ, digest=digest):
            raise _Reject

    try:
        stream = services.gemini.explain_stream(digest).__aiter__()
        while True:
            try:
                async with asyncio.timeout_at(deadline):
                    chunk = await stream.__anext__()
            except StopAsyncIteration:
                break
            buffer += chunk
            sentences, buffer = split_sentences(buffer)
            for sentence in sentences:
                check(sentence)
                shown += sentence
                yield {"type": "text", "delta": sentence}
        if buffer.strip():
            check(buffer)
            shown += buffer
            yield {"type": "text", "delta": buffer}
        check(shown)  # whole answer: also catches a claim that straddles two sentences
        return
    except (_Reject, Exception) as exc:  # noqa: BLE001  any failure of call 2 means the template
        if not isinstance(exc, _Reject):
            log.warning("explain stream failed: %s", type(exc).__name__)
    finally:
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:  # noqa: BLE001  closing is best effort
                pass
    text = template_explanation(options, ctx, TZ)
    if not explanation_ok(text, options, TZ, digest=digest):
        log.error("template answer failed its own validation")  # a bug; show the safe text instead
        text = SAFE_TEXT
    yield {"type": "replace", "text": text}


# --- the request ----------------------------------------------------------------------


async def stream_chat(rt: "_Runtime", message: str) -> AsyncIterator[bytes]:
    t0 = time.perf_counter()
    latency = {"extract": 0, "routing": 0, "context": 0, "explain": 0}
    counts: Counter[str] = Counter()
    info: dict[str, Any] = {"outcome": "error", "options": 0, "route_cache": None, "template": False}
    services, settings = rt.services, rt.settings
    context_task: asyncio.Task[Context] | None = None
    explainer: AsyncIterator[dict[str, Any]] | None = None

    def out(event: dict[str, Any]) -> bytes:
        counts[event["type"]] += 1
        return _encode(event)

    try:
        now = rt.now_fn()

        # 1. Gemini call 1.
        t = time.perf_counter()
        try:
            parsed = await asyncio.wait_for(services.gemini.extract(message, now), EXTRACT_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001  raise or timeout: show the form
            log.warning("extract failed: %s", type(exc).__name__)
            parsed = None
        latency["extract"] = _ms(t)
        if isinstance(parsed, FollowUp):
            info["outcome"] = "follow_up"
            yield out({"type": "follow_up", "question": parsed.question})
            return
        if not isinstance(parsed, TripQuery):
            info["outcome"] = "form"
            yield out({"type": "form"})
            return
        q = parsed
        if same_place(q):
            info["outcome"] = "same_place"
            yield out({"type": "follow_up", "question": SAME_PLACE_QUESTION})
            return

        # 2. One routing call (cached 10 min), bounded.
        t = time.perf_counter()
        key = cache_key(q)
        cached = rt.cache.get(key)
        routing_error = False
        if cached is not None:
            options, info["route_cache"] = list(cached), "hit"
        else:
            info["route_cache"] = "miss"
            try:
                options = await asyncio.wait_for(services.plan(q), ROUTING_DEADLINE_S)
                rt.cache.set(key, tuple(options))
            except (RoutingError, asyncio.TimeoutError) as exc:
                log.warning("routing failed: %s", type(exc).__name__)
                options, routing_error = [], True
        latency["routing"] = _ms(t)

        if routing_error or not options:
            info["outcome"] = "routing_unavailable" if routing_error else "no_routes"
            event: dict[str, Any] = {"type": "options", "options": [], "maps_link": maps_link(q)}
            if routing_error:
                event["error"] = "routing_unavailable"
            yield out(event)
            latency_total = {**latency, "total": _ms(t0)}
            yield out({"type": "done", "latency_ms": latency_total})
            return
        if same_place(options):  # Google resolved both ends to one spot
            info["outcome"] = "same_place"
            yield out({"type": "follow_up", "question": SAME_PLACE_QUESTION})
            return

        # 3. Start the context tools, then send the options while they run.
        info["options"] = len(options)
        t_ctx = time.perf_counter()
        context_task = asyncio.create_task(services.gather(options, q))
        yield out(options_event(options))
        try:
            ctx = await context_task
        except Exception as exc:  # noqa: BLE001  gather_context should not raise; never lose the answer
            log.warning("context failed: %s", type(exc).__name__)
            ctx = Context(alerts=(), weather=None, events=(), stations=(), missing=("context",))
        latency["context"] = _ms(t_ctx)

        # 4. Gemini call 2, validated sentence by sentence.
        t_exp = time.perf_counter()
        digest = build_digest(options, ctx, TZ)
        explainer = _explain(services, settings, options, ctx, digest)
        replaced = False
        async for event in explainer:
            replaced = replaced or event["type"] == "replace"
            yield out(event)
        latency["explain"] = _ms(t_exp)
        info["template"] = replaced

        notes: list[str] = []
        if q.past_time_replaced:
            notes.append(PAST_TIME_NOTE)
        if replaced:
            notes.append(TEMPLATE_NOTE)
        yield out({"type": "caveats", "missing": list(ctx.missing), "notes": notes})
        yield out({"type": "done", "latency_ms": {**latency, "total": _ms(t0)}})
        info["outcome"] = "answered"
    except Exception as exc:  # noqa: BLE001  a bug must not leave the panel hanging
        log.error("chat failed: %s", type(exc).__name__)
        if not counts["options"] and not counts["follow_up"] and not counts["form"]:
            yield out({"type": "form"})
        elif not counts["done"]:
            yield out({"type": "done", "latency_ms": {**latency, "total": _ms(t0)}})
    finally:
        if context_task is not None and not context_task.done():
            context_task.cancel()
        aclose = getattr(explainer, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:  # noqa: BLE001
                pass
        latency_log = {**latency, "total": _ms(t0)}
        log.info(
            json.dumps(
                {"event": "chat", **info, "latency_ms": latency_log, "events": dict(counts)},
                separators=(",", ":"),
            )
        )


# --- the app ----------------------------------------------------------------------------


@dataclass
class _Runtime:
    settings: Settings
    services: Services
    limiter: Any
    cache: Any
    now_fn: Callable[[], datetime]


def _configure_logging() -> None:
    """Make the per-request INFO line visible under uvicorn (it configures no root handler)."""
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")


def create_app(
    settings: Settings | None = None,
    services: Services | None = None,
    now_fn: Callable[[], datetime] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """Build the app.

    With ``settings`` and ``services`` (tests) or ``ASSISTANT_FAKE=1`` the app
    is ready at once; otherwise settings come from the environment and the
    clients are built at startup, so importing this module needs no environment.
    """
    from assistant.guardrails import RateLimiter, RoutingCache

    fake = os.environ.get("ASSISTANT_FAKE") == "1" and services is None
    now_fn = now_fn or (lambda: datetime.now(ZoneInfo(TZ)))

    def build(s: Settings, svc: Services) -> _Runtime:
        return _Runtime(
            settings=s,
            services=svc,
            limiter=RateLimiter(s.RATE_LIMIT_PER_HOUR, RATE_WINDOW_S),
            cache=RoutingCache(ROUTING_CACHE_TTL_S),
            now_fn=now_fn,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _configure_logging()
        owned: httpx.AsyncClient | None = None
        if app.state.rt is None:
            s = load_settings()
            owned = http_client or httpx.AsyncClient(timeout=httpx.Timeout(5.0))
            app.state.rt = build(s, real_services(s, owned))
        try:
            yield
        finally:
            if owned is not None:
                await owned.aclose()

    app = FastAPI(title="transit-assistant", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ALLOWED_ORIGINS),
        allow_origin_regex=LOCAL_ORIGIN_RE,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["Retry-After"],
        max_age=600,
    )
    app.state.rt = None
    if fake:
        app.state.rt = build(Settings(GEMINI_MODEL="fake-gemini"), fake_services())
    elif services is not None:
        app.state.rt = build(settings or load_settings(), services)

    def reject(status: int, error: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
        log.info(json.dumps({"event": "rejected", "reason": error, "status": status}, separators=(",", ":")))
        return JSONResponse({"error": error, "message": message}, status_code=status, headers=headers)

    @app.get("/health")
    async def health():
        rt: _Runtime | None = app.state.rt
        if rt is None:
            return JSONResponse({"status": "starting"}, status_code=503)
        return {"status": "ok", "model": rt.settings.GEMINI_MODEL}

    @app.post("/chat")
    async def chat(request: Request):
        rt: _Runtime | None = app.state.rt
        if rt is None:
            return JSONResponse({"error": "starting", "message": "The service is starting."}, status_code=503)
        limit = rt.settings.MAX_MESSAGE_CHARS
        declared = request.headers.get("content-length", "")
        too_big = declared.isdigit() and int(declared) > MAX_BODY_BYTES
        raw = b"" if too_big else (await request.body())[: MAX_BODY_BYTES + 1]
        if len(raw) > MAX_BODY_BYTES:
            raw = b""
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        message = body.get("message") if isinstance(body, dict) else None
        if not isinstance(message, str) or not message.strip():
            return reject(400, "bad_request", "Send a JSON body with a non-empty \"message\".")
        if len(message) > limit:
            return reject(400, "message_too_long", f"Please keep your question under {limit} characters.")
        ip = client_ip(request)
        if not rt.limiter.allow(ip):
            wait = rt.limiter.retry_after_s(ip)
            return reject(
                429,
                "rate_limited",
                f"You have reached the limit of {rt.settings.RATE_LIMIT_PER_HOUR} questions per hour. "
                "Please try again a little later.",
                {"Retry-After": str(wait)},
            )
        return StreamingResponse(
            stream_chat(rt, message),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
