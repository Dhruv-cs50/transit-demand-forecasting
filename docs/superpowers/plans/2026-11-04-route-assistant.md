# Route Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A chat panel on the site that answers Bay Area transit trip questions (BART, VTA, Caltrain) with Google Routes itineraries, explained by Gemini, with alerts, weather and events as context, fast and cheap.

**Architecture:** A new FastAPI service `transit-assistant` on Cloud Run. Per question the service runs exactly two Gemini (Vertex AI, Flash tier) calls — extract the trip, then explain the options — around one Google Routes call and four context tools run in parallel with 1.5 s timeouts. It streams NDJSON events: route options first, explanation second. A vanilla-JS panel (`website/assistant.js`) renders the stream on the main page and the map demo.

**Tech Stack:** Python 3.11, FastAPI, httpx (async), `google-genai` (Vertex AI mode), `gtfs-realtime-bindings`, pytest + respx; vanilla JS; Cloud Run, Secret Manager, Cloud Build.

**Spec:** `docs/superpowers/specs/2026-10-28-route-assistant-and-caltrain-design.md` (sections 1–4, 6–11).

## Global Constraints

- Branch `feature/nov15`; nothing merges to `main` or deploys to the live hosts without the user's approval. Site changes go to a Firebase preview channel only.
- Transit only (BART, VTA, Caltrain, walking). No driving.
- Times and durations shown to the user come only from Google Routes.
- Exactly two Gemini calls per answered question; Flash tier; call 2 input < 2k tokens, output ≤ 250 tokens.
- Context tools run concurrently, each with a 1.5 s timeout; a late or failed tool is dropped and named in the caveats.
- Latency targets (warm, measured at the client): first options p50 ≤ 2 s, p95 ≤ 3.5 s; full answer p50 ≤ 4 s, p95 ≤ 7 s.
- Guardrails: one routing call and at most four tool calls per question; 10 questions per hour per IP; routing cache 10 min, weather/alerts cache 5 min; max 2 Cloud Run instances; message length ≤ 500 characters.
- Keys only in Secret Manager; Gemini via the service account (`roles/aiplatform.user`), no key.
- Logs: anonymous counts and per-stage latency only; never message text.
- Crowding claims only from the project's monthly data, labelled "monthly context, not live crowding"; weather and events phrased as possibilities ("may be busier").
- Display times in America/Los_Angeles.

## Review Focus

1. **No transit route exists** (e.g. 2 a.m., or a place no line reaches): Google returns zero routes → the answer says no transit option was found and links to Google Maps transit directions; never an empty panel. → Task 2 `test_no_routes_returns_empty_list`, Task 6 `test_chat_no_routes_streams_fallback_link`.
2. **No time given, "now", or a time already past:** default to now in America/Los_Angeles; a past time is replaced by now and said so in the caveats. → Task 5 `test_extract_defaults_and_past_time`.
3. **Ambiguous place names** ("Civic Center" is both a BART station in SF and a VTA stop in San Jose): extraction appends ", San Francisco Bay Area, CA" to free text, and if the origin and destination resolve to the same place the answer asks which one was meant. → Task 2 `test_same_origin_and_destination_detected`.
4. **Gemini states a time Google did not give** (or reformats one, e.g. "about an hour" for 58 min): the validator rejects any clock time or minute count not present in the options; the template replaces the explanation. → Task 4 `test_rejects_invented_minutes`, `test_accepts_exact_times`.
5. **Prompt injection or oversized input** ("ignore your instructions…", 5,000 characters): input over 500 characters → HTTP 400; extraction output must parse against the JSON schema or the service shows the origin/destination form. → Task 6 `test_chat_rejects_long_message`, Task 5 `test_extract_invalid_json_returns_form`.

---

### Task 1: Package skeleton, types, config

**Files:**
- Create: `assistant/__init__.py`, `assistant/types.py`, `assistant/config.py`, `assistant/requirements.txt`
- Test: `tests/assistant/test_types.py`

**Interfaces:**
- Produces (all frozen dataclasses in `assistant/types.py`):
  - `TripQuery(origin: str, destination: str, depart_at: datetime, past_time_replaced: bool = False)` — `depart_at` tz-aware.
  - `FollowUp(question: str)`
  - `Leg(mode: Literal["TRANSIT","WALK"], agency: Literal["BART","VTA","Caltrain","other"] | None, line: str | None, from_stop: str | None, to_stop: str | None, depart: datetime | None, arrive: datetime | None, duration_s: int, headsign: str | None)`
  - `TripOption(rank: int, depart: datetime, arrive: datetime, duration_s: int, transfers: int, walk_s: int, agencies: tuple[str, ...], legs: tuple[Leg, ...], polyline: str, origin_latlng: tuple[float, float], dest_latlng: tuple[float, float])`
  - `Alert(agency: str, header: str)`, `Weather(precip_mm: float, temp_c: float, wind_kmh: float)`, `Event(name: str, venue: str, start: datetime, distance_km: float)`, `StationContext(station: str, typical_monthly: int, forecast_month: str, forecast_p50: int, label: str)`
  - `Context(alerts: tuple[Alert,...], weather: Weather | None, events: tuple[Event,...], stations: tuple[StationContext,...], missing: tuple[str,...])`
- `assistant/config.py`: `Settings` dataclass loaded by `load_settings() -> Settings` from env: `GCP_PROJECT`, `VERTEX_REGION` (default `us-west1`), `GEMINI_MODEL` (no default — must be set), `ROUTES_API_KEY`, `TOKEN_511`, `TICKETMASTER_KEY` (optional), `TOOL_TIMEOUT_S=1.5`, `EXPLAIN_TIMEOUT_S=4.0`, `RATE_LIMIT_PER_HOUR=10`, `MAX_MESSAGE_CHARS=500`, `TZ="America/Los_Angeles"`.

- [ ] **Step 1:** Create a Python 3.11 venv `~/.venvs/tdf-assistant-py311`; install fastapi, uvicorn[standard], httpx, google-genai, gtfs-realtime-bindings, pydantic, pytest, respx, pytest-asyncio; write the resolved exact versions into `assistant/requirements.txt` (`==` pins).
- [ ] **Step 2:** Write `tests/assistant/test_types.py::test_settings_require_model` — `load_settings()` with `GEMINI_MODEL` unset raises `RuntimeError`; with it set, `TOOL_TIMEOUT_S == 1.5` and `MAX_MESSAGE_CHARS == 500`. Run, expect FAIL.
- [ ] **Step 3:** Implement the types and config. Run, expect PASS.
- [ ] **Step 4:** Commit `feat(assistant): package skeleton, types, settings`.

### Task 2: `plan_trips` — Google Routes, transit

**Files:**
- Create: `assistant/routing.py`; fixtures `tests/assistant/fixtures/routes_mv_to_sap.json`, `routes_empty.json`, `routes_same_place.json`
- Test: `tests/assistant/test_routing.py`

**Interfaces:**
- Consumes: `TripQuery`, `TripOption`, `Leg` (Task 1).
- Produces: `async def plan_trips(q: TripQuery, client: httpx.AsyncClient, api_key: str) -> list[TripOption]` — POST `https://routes.googleapis.com/directions/v2:computeRoutes`, `travelMode=TRANSIT`, `computeAlternativeRoutes=true`, `departureTime=q.depart_at`, origin/destination as `{"address": …}` with ", San Francisco Bay Area, CA" appended when the text has no comma; field mask limited to the fields `TripOption` needs; returns ≤ 3 options sorted by `duration_s`, `rank` from 1. Raises `RoutingError` on HTTP error or timeout (2.5 s). `def normalise_agency(name: str) -> str` maps agency names containing "BART"/"Bay Area Rapid", "VTA"/"Valley Transportation", "Caltrain"/"Peninsula Corridor" to the three labels, else `"other"`. `def same_place(options_or_payload) -> bool`.
- Record fixtures once from the real API (Task 9 has the key); until then hand-write them from the documented response shape.

- [ ] **Step 1:** Tests: `test_parses_options_sorted_and_capped` (fixture → 3 options, ascending `duration_s`, agencies ⊆ {BART, VTA, Caltrain, other}, a Caltrain leg present for Mountain View → SAP Center); `test_normalise_agency` (four names → labels); `test_no_routes_returns_empty_list`; `test_same_origin_and_destination_detected`; `test_http_error_raises_routing_error` (respx 500). Run, expect FAIL.
- [ ] **Step 2:** Implement. Run, expect PASS.
- [ ] **Step 3:** Commit `feat(assistant): plan_trips via Google Routes transit`.

### Task 3: Context tools and `gather_context`

**Files:**
- Create: `assistant/context_tools.py`, `assistant/station_data.py`; fixtures for 511 alerts (protobuf bytes), Open-Meteo, NHL schedule
- Test: `tests/assistant/test_context_tools.py`

**Interfaces:**
- Consumes: Task 1 types; `TripOption.origin_latlng/dest_latlng`.
- Produces:
  - `async def service_alerts(agencies: set[str], client, token: str) -> tuple[Alert, ...]` — 511 `servicealerts?agency=RG&api_key=…`, active alerts whose informed entity agency maps (via `normalise_agency`) into `agencies`.
  - `async def weather(lat: float, lng: float, when: datetime, client) -> Weather` — Open-Meteo forecast API, hourly nearest to `when`.
  - `async def events_near(lat: float, lng: float, when: datetime, client, tm_key: str | None) -> tuple[Event, ...]` — NHL Sharks home games (SAP Center coordinates from `machine_learning_files/fetch_events.py`'s venue table) and Ticketmaster if `tm_key`, within 1.5 km and ±3 h.
  - `def station_context(name: str) -> StationContext | None` — from `website/data/stations_meta.json` + `stations_ridership.json` + `forecasts_sarima.json` bundled into the image; fuzzy match on station name; `label="monthly context, not live crowding"`.
  - `async def gather_context(options: list[TripOption], q: TripQuery, client, settings) -> Context` — runs the four concurrently with `asyncio.wait_for(…, settings.TOOL_TIMEOUT_S)`; a timed-out or failed tool contributes its name to `missing`.
  - `assistant/cache.py` is not separate: put `TTLCache(ttl_s: int)` with `get(key)`/`set(key, value)` in `context_tools.py`; weather and alerts use a 300 s cache.

- [ ] **Step 1:** Tests: one parsing test per tool from its fixture; `test_gather_context_times_out_slow_tool` (a tool sleeping 3 s → result in < 1.8 s, `"weather" in missing`); `test_gather_context_runs_concurrently` (four 1 s fakes complete in < 1.5 s); `test_station_context_label`; `test_ttl_cache_expires`. Run, expect FAIL.
- [ ] **Step 2:** Implement. Run, expect PASS.
- [ ] **Step 3:** Commit `feat(assistant): context tools with parallel timeouts`.

### Task 4: Validator, digest, template answer

**Files:**
- Create: `assistant/answer.py`
- Test: `tests/assistant/test_answer.py`

**Interfaces:**
- Consumes: Task 1 types.
- Produces:
  - `def build_digest(options: list[TripOption], ctx: Context, tz: str) -> dict` — compact JSON-able dict: per option rank, depart/arrive as `"6:05 PM"`, minutes, agencies, transfers, walk minutes, line names; alerts (≤ 3 headers), weather (rounded), events (≤ 3), station context labels, missing tools. Serialised size must stay under 6,000 characters (≈ 2k tokens).
  - `def allowed_tokens(options, tz) -> set[str]` — every clock time (`"6:05 PM"`, `"18:05"`) and minute count (`"52 min"`, `"52 minutes"`) derivable from the options.
  - `def explanation_ok(text: str, options, tz) -> bool` — every clock time and `N min(utes)` in `text` (regex) is in `allowed_tokens`; phrases like "about an hour" count as minute claims and fail.
  - `def template_explanation(options, ctx, tz) -> str` — deterministic one-line reason per option plus caveats, used when Gemini fails or `explanation_ok` is False.

- [ ] **Step 1:** Tests: `test_accepts_exact_times`; `test_rejects_invented_minutes` ("takes 45 min" when options are 52/58); `test_rejects_vague_duration` ("about an hour"); `test_digest_under_size_limit` (3 options, 3 alerts, 3 events → `len(json.dumps(d)) < 6000`); `test_template_mentions_each_option_and_missing_tools`. Run, expect FAIL.
- [ ] **Step 2:** Implement. Run, expect PASS.
- [ ] **Step 3:** Commit `feat(assistant): answer validator, digest, template`.

### Task 5: Gemini calls

**Files:**
- Create: `assistant/llm.py`, `assistant/prompts.py`
- Test: `tests/assistant/test_llm.py`

**Interfaces:**
- Consumes: `Settings`, `TripQuery`, `FollowUp`.
- Produces:
  - `class Gemini` with `__init__(settings)` creating a `google.genai.Client(vertexai=True, project=…, location=settings.VERTEX_REGION)`; the client is injectable for tests.
  - `async def extract(self, message: str, now: datetime) -> TripQuery | FollowUp | None` — call 1, `response_mime_type="application/json"` with a response schema `{origin, destination, depart_at|null, follow_up|null}`, max 120 output tokens; `None` when the output does not parse (service shows the form). `depart_at` null → `now`; a past `depart_at` → `now` with `past_time_replaced=True`.
  - `async def explain_stream(self, digest: dict) -> AsyncIterator[str]` — call 2, streamed, `max_output_tokens=250`, temperature 0.2.
- `assistant/prompts.py`: the two system prompts, containing the honesty rules from Global Constraints verbatim.

- [ ] **Step 1:** Tests with a fake client: `test_extract_parses_query`; `test_extract_defaults_and_past_time` (no time → `now`; yesterday → `now`, flag set); `test_extract_follow_up`; `test_extract_invalid_json_returns_form` (returns `None`); `test_explain_stream_yields_chunks_and_caps_tokens` (asserts the request config has `max_output_tokens == 250`). Run, expect FAIL.
- [ ] **Step 2:** Implement. Run, expect PASS.
- [ ] **Step 3:** Commit `feat(assistant): two Gemini calls on Vertex AI`.

### Task 6: `/chat` service, streaming, guardrails

**Files:**
- Create: `assistant/service.py`, `assistant/guardrails.py`
- Test: `tests/assistant/test_service.py`

**Interfaces:**
- Consumes: Tasks 2–5.
- Produces: FastAPI `app` with `GET /health` → `{"status":"ok","model":settings.GEMINI_MODEL}` and `POST /chat` body `{"message": str, "client_time": str}` → `application/x-ndjson` stream of events, in order:
  1. `{"type":"follow_up","question":…}` (then end) **or** `{"type":"form"}` (then end) **or**
  2. `{"type":"options","options":[…TripOption as JSON, times as ISO + display strings…],"attribution":"Routes by Google"}` — sent as soon as routing returns, before context;
  3. `{"type":"text","delta":…}` repeated (Gemini stream; buffered per sentence and checked with `explanation_ok`; on the first failing sentence, or if call 2 exceeds `EXPLAIN_TIMEOUT_S`, emit `{"type":"replace","text": template_explanation(…)}` and stop streaming Gemini);
  4. `{"type":"caveats","missing":[…],"notes":[…]}`;
  5. `{"type":"done","latency_ms":{"extract":…,"routing":…,"context":…,"explain":…,"total":…}}`.
  - No routes → `{"type":"options","options":[],"maps_link":"https://www.google.com/maps/dir/?api=1&origin=…&destination=…&travelmode=transit"}` then `done`.
  - `RoutingError` (HTTP error or 2.5 s timeout) → the same `maps_link` event with `"error":"routing_unavailable"`, then `done`; never a guessed time.
  - Gemini call 1 raises or times out → `{"type":"form"}` (same as unparseable output).
  - `guardrails.py`: `RateLimiter(limit: int, window_s: int).allow(ip: str) -> bool` (in-memory, per instance); routing results cached 600 s keyed on (origin, destination, depart_at rounded to 5 min).
  - Message > 500 chars → 400; rate limit exceeded → 429 with a friendly JSON message.
  - Logging: one structured log line per request with latencies and event counts, no text.
  - `ASSISTANT_FAKE=1` env: the app wires the same fakes the tests use (canned Routes fixture, canned Gemini text, instant tools), so the panel can be developed without keys.

- [ ] **Step 1:** Tests with fakes for Gemini, Routes and tools (FastAPI TestClient): `test_chat_streams_options_before_text` (event order); `test_chat_replaces_invented_time` (fake Gemini says "45 min" → a `replace` event); `test_chat_gemini_timeout_uses_template`; `test_chat_no_routes_streams_fallback_link`; `test_chat_routing_error_streams_fallback_link`; `test_chat_extract_exception_returns_form`; `test_chat_rejects_long_message` (501 chars → 400); `test_rate_limit_429_on_eleventh`; `test_two_gemini_calls_one_routing_call` (call counters); `test_logs_contain_no_message_text` (caplog). Run, expect FAIL.
- [ ] **Step 2:** Implement. Run, expect PASS.
- [ ] **Step 3:** Run the whole assistant suite: `~/.venvs/tdf-assistant-py311/bin/python -m pytest -q tests/assistant` → all pass.
- [ ] **Step 4:** Commit `feat(assistant): /chat NDJSON stream with guardrails`.

### Task 7: Chat panel (site and map demo)

**Files:**
- Create: `website/assistant.js`, `website/assistant.css`
- Modify: `website/index.html` (include, cache-buster), `website/transit-demo.html` (include; draw the chosen option's polyline with the page's existing renderer `R.line`)
- Test: browser verification (no JS test harness exists in the repo).

**Interfaces:**
- Consumes: the NDJSON events from Task 6.
- Produces: `window.TransitAssistant.mount(el: HTMLElement, opts: {apiBase: string, onRoute?: (option) => void})`. `apiBase` defaults to the assistant URL, overridable with `?assistant=` for local testing.

- [ ] **Step 1:** Implement: an input (maxlength 500), a streamed answer area that renders `options` as soon as they arrive (ranked cards: total minutes, depart → arrive, agency chips, transfers, walking), then explanation text, `replace`, caveats, the "Routes by Google" attribution, and a "waking…" note after 1.5 s without a first event. In `transit-demo.html`, `onRoute` draws the top option's polyline (decode Google's encoded polyline in `assistant.js`).
- [ ] **Step 2:** Verify in a browser against a local service (`uvicorn assistant.service:app --port 8090` with `ASSISTANT_FAKE=1`, Task 6): options paint before text; the template replacement shows; the empty-routes link shows; 375 px wide works; dark mode readable. Record screenshots in the PR description.
- [ ] **Step 3:** Commit `feat(site): route assistant panel on the main page and map demo`.

### Task 8: Container, build, infrastructure

**Files:**
- Create: `Dockerfile.assistant` (python:3.11-slim, `assistant/requirements.txt`, copies `assistant/` and the three `website/data/*.json` files `station_context` reads), `cloudbuild.assistant.yaml` (same pattern as `cloudbuild.yaml`: `_TAG` substitution, linux/amd64, push only)
- Create: `docs/assistant.md` (deploy and operate)

- [ ] **Step 1:** Infrastructure (orchestrator, under standing permission): enable `routes.googleapis.com`, `aiplatform.googleapis.com`, `secretmanager.googleapis.com`; create a Routes server key restricted to the Routes API; store it, the 511 token and (optional) Ticketmaster key in Secret Manager; create service account `transit-assistant` with `roles/aiplatform.user` and `roles/secretmanager.secretAccessor` on those secrets only; set a project budget alert.
- [ ] **Step 2:** Build with `gcloud builds submit --config=cloudbuild.assistant.yaml --substitutions=_TAG=$(git rev-parse --short HEAD) .`; deploy by digest: `gcloud run deploy transit-assistant --region us-west2 --service-account transit-assistant@… --max-instances 2 --cpu-boost --set-secrets ROUTES_API_KEY=…,TOKEN_511=… --set-env-vars GCP_PROJECT=…,VERTEX_REGION=us-west1,GEMINI_MODEL=<Flash model id available in Vertex at build time> --allow-unauthenticated`. Expected: `GET /health` returns the model id.
- [ ] **Step 3:** Record the Routes fixtures of Task 2 from the live API (one call each), re-run Task 2 tests against them, commit the fixtures.
- [ ] **Step 4:** Commit `build(assistant): container, Cloud Build, deploy runbook`.

### Task 9: Scripted evaluation and latency gate

**Files:**
- Create: `eval/assistant_questions.yaml` (25 questions), `eval/assistant_eval.py`
- Test: the eval itself, run against the deployed preview service

**Interfaces:**
- Produces: `python eval/assistant_eval.py --api <url> [--out eval/outputs/assistant_eval.json]` — exit 0 only if all checks pass. Per question it records time to the first `options` event and to `done`, and checks: every time in the final text is in `allowed_tokens` (import from `assistant.answer`); expected agencies appear (per question in the YAML, e.g. Mountain View → SAP Center expects Caltrain); out-of-area and nonsense questions get a scope message or form, never options. Aggregate: first-options p50 ≤ 2.0 s and p95 ≤ 3.5 s; done p50 ≤ 4.0 s and p95 ≤ 7.0 s (warm: one discarded warm-up request first).
- The 25 questions must include: Diridon → SF weekday 8 am; Mountain View → SAP Center on a Sharks home-game night; Berkeley → SFO; Millbrae BART ↔ Caltrain transfer; Civic Center (ambiguous); a 2 a.m. trip; "now"; a past time; an out-of-area trip (LA); a nonsense message; a 600-character message (expects 400).

- [ ] **Step 1:** Write the YAML and the script.
- [ ] **Step 2:** Run against the deployed service. Expected: exit 0. If latency fails, record per-stage latencies from the `done` events and fix the slowest stage before tuning anything else.
- [ ] **Step 3:** Commit `test(assistant): scripted evaluation with latency gate`.

### Task 10: Preview deploy and review

- [ ] **Step 1:** `firebase hosting:channel:deploy nov15-preview --expires 14d` from a clean export of `feature/nov15`; the preview's panel points at the deployed `transit-assistant`.
- [ ] **Step 2:** Run the Task 9 eval once more against the preview; attach its JSON summary and the latency table to the review request.
- [ ] **Step 3:** Hand the preview URL to the user. Merge to `main` and live deploy only on their approval.
