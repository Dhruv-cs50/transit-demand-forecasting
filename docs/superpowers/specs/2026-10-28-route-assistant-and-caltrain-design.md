# Route assistant and Caltrain ridership — design

Date: 2026-10-28. Target: 2026-11-15. Branch: `feature/nov15` (never merged to `main`
without the user's go-ahead). Brainstormed with the user section by section; every
decision below marked **(user)** was theirs, everything marked **(design)** is the
designer's call and open to change.

## 1. Intent

Two additions to the Bay Area Transit Demand Forecasting site:

1. **Route assistant.** A chat panel where a visitor asks how to get from A to B by
   transit and gets the fastest options across **BART, VTA and Caltrain**, with live
   service alerts, the weather at departure and events near either end taken into
   account. (user)
2. **Caltrain ridership.** Add Caltrain to the forecasting side of the project,
   alongside BART. (user)

Why: make the site useful to a rider, not only a reader of forecasts, and extend the
forecasting work beyond BART.

## 2. Goals, non-goals, anti-goals

**Goals**
- Answer Bay Area transit trip questions with real itineraries ranked fastest first,
  each with a one-line reason.
- Forecast Caltrain systemwide monthly ridership with the same rigour as BART
  (separate leaderboard, reproducible, gated).
- Ship a reviewable preview by about 2026-11-12, finished by 2026-11-15.

**Non-goals**
- Driving, rideshare or cycling comparisons — transit only, for now. (user)
- Live crowding prediction. The forecasting models are monthly.
- Monthly per-station Caltrain forecasts. Caltrain publishes per-station figures only
  annually. (user chose scope (a))
- User accounts or stored conversations.

**Anti-goals (would make it a failure even if it runs)**
- The assistant states a travel time that did not come from the routing engine.
- Weather or events are presented as measured effects on ridership. The project's own
  covariate experiment found none at monthly resolution.
- Any change to the live demo site, the live forecast API or the gated BART numbers.
- An unbounded bill.

## 3. Constraints

- Language model: **Grok via the xAI API**, the low-cost fast model. (user) It is
  pay-per-use, not free; the user sets a monthly spending limit in the xAI console.
- Routing: **Google Routes API, transit mode**, with alternatives. (user, option A)
  Billed to the existing project `cs-163-final-project-tra-f1136`; Google attribution
  shown with results, as its terms require.
- Live data: 511.org regional real-time service alerts (free token, default limit 60
  requests/hour); Open-Meteo forecast (no key); NHL schedule (no key); Ticketmaster
  (optional key).
- Keys never reach the browser: they live in Secret Manager.
- Nothing merges to `main` or deploys to the live hosts before the user approves.

## 4. Part 1 — Route assistant

### 4.1 Components

| Component | What it is | Depends on |
| --- | --- | --- |
| Chat panel | A widget on the main page and the map demo; shows ranked options and draws the chosen route on the map | `POST /chat` |
| `transit-assistant` | New Cloud Run service, separate from `transit-api`, one endpoint `POST /chat` (design) | Grok, the five tools |
| Tools | Five functions Grok may call (4.2) | Google Routes, 511, Open-Meteo, NHL/Ticketmaster, project data |
| Secrets | xAI key, Google Routes key, 511 token, optional Ticketmaster key | Secret Manager |

A separate service keeps a chatbot bug or traffic spike away from the forecast API the
demo relies on. (design, approved)

### 4.2 Tools (contracts)

1. `plan_trips(origin, destination, depart_at)` — Google Routes `computeRoutes`,
   `travelMode=TRANSIT`, `computeAlternativeRoutes=true`. Origin and destination are
   free-text addresses or place names (no separate geocoding). Returns for each option:
   total duration, departure and arrival time, legs (agency, line, from/to stop, duration,
   headsign), transfers, walking time. Agency labels are normalised to BART / VTA /
   Caltrain / other.
2. `service_alerts(agencies)` — 511 GTFS-RT service alerts for the agencies in the
   returned options; active alerts only, summarised.
3. `weather(lat, lng, time)` — Open-Meteo hourly forecast at the departure time:
   precipitation, temperature, wind.
4. `events_near(lat, lng, time)` — Sharks home games (NHL API) and, if a key is
   configured, Ticketmaster events within about 1.5 km and ±3 hours of the trip end
   points.
5. `station_context(station)` — retrieval over the project's own data: the station's
   typical monthly ridership level and the current SARIMA monthly forecast, always
   labelled "monthly context, not live crowding".

### 4.3 Flow

1. Visitor asks; the panel posts `{message, client_time}` to `/chat`.
2. Grok extracts origin, destination and departure time, asking one follow-up question
   if either end is missing.
3. Grok calls `plan_trips` once, then up to three of the other tools for the options it
   will present.
4. The service validates the draft answer: every time and duration in it must match the
   `plan_trips` output (see 4.5); otherwise it falls back to the template answer.
5. Response: ranked options (fastest first), a one-line reason each, caveats (alerts,
   weather, events), Google attribution, and route geometry for the map.

### 4.4 Errors and degraded answers (approved)

| Failure | Behaviour |
| --- | --- |
| Google Routes fails or times out | Say the trip could not be planned; link to Google Maps transit directions for the same origin and destination. Never guess times. |
| Alerts, weather or events fail | Answer anyway, with a note naming the missing context. |
| Out of area or not a trip question | State the scope (Bay Area trips on BART, VTA, Caltrain). |
| Grok down | Show the ranked options straight from Google Routes, labelled "summary unavailable". |

### 4.5 Guardrails (approved)

- Per question: one routing call, at most four tool calls in total; capped reply length.
- Per visitor: about 10 questions per hour per IP.
- Cache: identical routing requests 10 minutes; weather and alerts 5 minutes (also keeps
  511 under 60 requests/hour).
- Hard caps: xAI monthly limit (user sets), Google Cloud budget alert, `transit-assistant`
  max 2 instances.
- Logging: anonymous counts only (questions, tool failures, latency). No message text
  stored.
- Honesty rules in the system prompt and enforced in code: times only from Google;
  crowding only from monthly project data, labelled monthly; weather and events phrased as
  possibilities ("may be busier").

## 5. Part 2 — Caltrain ridership (scope (a))

### 5.1 Data

- **Monthly systemwide series:** "average weekday ridership" from Caltrain's Executive
  Director monthly reports (PDFs), as far back as published (target Jan 2019 on). A small
  extraction script reads each report; every value is hand-checked against its PDF and
  recorded in a tracked table with the report URL and file sha256, like
  `data/MANIFEST.md` for BART.
- **Per-station annual figures:** average mid-week boardings by origin station from each
  annual ridership report (FY2019–FY2026). Displayed, not modelled.
- The figures are Caltrain's estimates from a fare-media sales model (conductor counts and
  Clipper data in later years), not passenger counts; the site says so.

### 5.2 Breaks, modelled explicitly

- 2020–21 excluded, as for BART.
- Estimation-method changes (April 2020, June 2022): months on either side are flagged so
  a method change is not read as a ridership change.
- Electrification: a level-shift indicator from the full-service launch month (to be
  confirmed from Caltrain's reports; FY2026 ridership was up 37.6%).

### 5.3 Models and evaluation

- SARIMA with the electrification step, Prophet with a changepoint there, seasonal naive,
  Chronos-1 zero-shot — the BART set, so the comparison is like for like.
- Half-year holdouts as for BART where data allows; any choice made on earlier windows
  only; the test window scored once.
- About 45–55 usable months with a large break near the end: expect wider error than
  BART, and publish whatever the numbers are.

### 5.4 Where it lives

- Separate feature store, benchmark run and leaderboard; BART's gated numbers never move.
- New Caltrain section on the site: monthly series with breaks marked, forecast with
  bands, per-station annual table, model comparison.
- Cloud ingest: a `raw/caltrain/` folder in the existing bucket; new monthly figures added
  by hand after each report, as with BART workbooks.

## 6. Testing

- **Assistant, offline:** each tool against recorded responses (no network, no keys);
  parser for Routes output; guardrails (tool-call cap, rate limit, cache, degraded paths).
- **Assistant, scripted evaluation (~25 questions):** e.g. Diridon → SF weekday morning,
  Mountain View → SAP Center on a Sharks night, an out-of-area trip, a nonsense question.
  Pass means: every time in the answer equals Google's output; agencies labelled
  correctly; failures stated honestly.
- **Caltrain:** hand-verified extraction table; tests for the method-change flags and the
  electrification step; the BART reproducibility gate (two runs byte-identical, published
  numbers traced to one run).

## 7. Branching and previews

- All work on `feature/nov15`, cut from `main`; work branches merge into it, not into
  `main`. It is brought up to date with `main` after the Sprint 11 (Nov 3) work merges.
- Assistant deployed as its own Cloud Run service; site changes deployed to a Firebase
  **preview channel** (separate temporary URL). The live site and `transit-api` are not
  touched.
- Merge to `main` only after the user reviews the preview.

## 8. Effort and timeline

| Part | Work | Estimate (agent time) |
| --- | --- | --- |
| Assistant | Service, five tools, Grok orchestration | 1.5 days |
| | Chat panel, route drawn on the map | 1 day |
| | Guardrails, scripted evaluation, preview deploy | 1–1.5 days |
| Caltrain | Report extraction and hand-checked table | 1 day |
| | Models, breaks, backtest, gate | 1 day |
| | Site section, cloud folder | 1 day |
| **Total** | Two parallel lanes | **about 7–8 days** |

Start 2026-11-04 (after the demo). Preview around 2026-11-12; user review; finish
2026-11-15. The Caltrain extraction is low-risk and may start earlier if the user wants.

## 9. Needed from the user

- xAI API key, with a monthly spending limit set in the xAI console.
- 511.org token (free; emailed after registration).
- Optional: Ticketmaster API key.
- (Designer does: enable the Routes API, create a referrer-free server key in Secret
  Manager, set the budget alert.)

## 10. Left to the builder (design calls, changeable)

- The exact Grok model ID: the low-cost fast tier available on the xAI account at build
  time.
- Chat panel styling, within the site's existing design system.
- Cache store: in-memory per instance is enough at two instances; no Redis.
- Language for the system prompt and the template fallback answer.

## 11. Assumptions to verify early

- Google Routes transit results cover VTA light rail and Caltrain with usable real-time
  data in the Bay Area.
- Caltrain's monthly reports exist and are parseable back to 2019; if not, the series
  starts where they do, and the spec's "45–55 months" changes accordingly.
- The exact electrification launch month, from Caltrain's own documents.
- xAI pricing and any sign-up credit, read from the user's xAI console.
