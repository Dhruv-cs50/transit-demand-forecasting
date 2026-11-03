# Route assistant: deploy and operate

The route assistant answers a rider's question ("Mountain View Caltrain to SAP
Center tonight") for BART, VTA and Caltrain. One `POST /chat` runs Gemini call 1
(question to origin, destination, time), one Google Routes call, four context
tools (alerts, weather, events, station context), then Gemini call 2 (a short
explanation, checked sentence by sentence). The reply streams as NDJSON. Code:
[`assistant/`](../assistant/). Design: [the plan](superpowers/plans/2026-11-04-route-assistant.md).

It is a separate Cloud Run service. It shares nothing with `transit-api`, the
ingest job, App Engine or Firebase, and none of them need to change to run it.

## What is deployed

| Item | Value |
| --- | --- |
| Project / region | `cs-163-final-project-tra-f1136` / `us-west2` |
| Service | Cloud Run `transit-assistant`, URL `https://transit-assistant-308878596074.us-west2.run.app` |
| Image | `us-west2-docker.pkg.dev/cs-163-final-project-tra-f1136/transit-repo/transit-assistant:<commit>`, deployed by digest |
| Build | `cloudbuild.assistant.yaml` builds `Dockerfile.assistant` (`python:3.11-slim`, `linux/amd64`, non-root, `assistant/requirements.txt`). Push only |
| Service account | `transit-assistant@cs-163-final-project-tra-f1136.iam.gserviceaccount.com`: `roles/aiplatform.user` (project) and `roles/secretmanager.secretAccessor` on `routes-api-key` and `token-511` only |
| Scaling | `--min-instances 0 --max-instances 2 --cpu-boost`, 1 vCPU, 512 MiB, concurrency 80 |
| Access | `--allow-unauthenticated` (a public page calls it); abuse is bounded by the rate limit and the instance cap |
| Env vars | `GCP_PROJECT`, `VERTEX_REGION=global`, `GEMINI_MODEL=gemini-3-flash-preview` |
| Secrets | `ROUTES_API_KEY` from `routes-api-key`, `TOKEN_511` from `token-511`. There is no Ticketmaster key, so Sharks games come from the NHL schedule only |

**Why `gemini-3-flash-preview` at `global`.** On 2026-11-01 it was the only
Gemini model this project could call, and only at location `global`;
`gemini-2.5-flash`, `gemini-2.5-flash-lite` and `gemini-3-flash` answered 404.
`GEMINI_MODEL` has no default on purpose (the service refuses to start without
it), so changing the model is an env-var change, not a code change. A preview
model can be withdrawn: if `/chat` starts returning the origin/destination form
for every question, check the Cloud Run logs for `extract failed` and re-run the
availability check below.

## Deploy

Run from a clean checkout of the commit you want to ship.

```bash
P=cs-163-final-project-tra-f1136
IMG=us-west2-docker.pkg.dev/$P/transit-repo/transit-assistant

# 1. Build and push, tagged with the commit (about 50 s).
gcloud builds submit --config=cloudbuild.assistant.yaml \
  --substitutions=_TAG=$(git rev-parse --short HEAD) .

# 2. Read the digest of the image you just pushed.
DIGEST=$(gcloud artifacts docker images describe $IMG:$(git rev-parse --short HEAD) \
  --format='value(image_summary.digest)')

# 3. Deploy by digest (a tag can move; a digest cannot).
gcloud run deploy transit-assistant --region us-west2 --image $IMG@$DIGEST \
  --service-account transit-assistant@$P.iam.gserviceaccount.com \
  --max-instances 2 --min-instances 0 --cpu-boost --allow-unauthenticated \
  --set-env-vars GCP_PROJECT=$P,VERTEX_REGION=global,GEMINI_MODEL=gemini-3-flash-preview \
  --set-secrets ROUTES_API_KEY=routes-api-key:latest,TOKEN_511=token-511:latest
```

Later deploys that change only the image can drop the flags after `--image`:
the service keeps its env vars, secrets and scaling.

Confirm what is live:

```bash
gcloud run services describe transit-assistant --region us-west2 \
  --format='value(spec.template.spec.containers[0].image)'
curl -s https://transit-assistant-308878596074.us-west2.run.app/health
# {"status":"ok","model":"gemini-3-flash-preview"}
```

The site panel (Task 7) should be pointed at the service URL after a deploy
only if the URL changed; it does not change between revisions.

### Testing a build without taking traffic

`gcloud run deploy ... --no-traffic --tag <name>` serves the revision at
`https://<name>---transit-assistant-<hash>-wl.a.run.app` while the live revision
keeps serving. Afterwards, deploy the image you want live and then run
`gcloud run services update-traffic transit-assistant --region us-west2 --to-latest`
and check `status.traffic` with `describe`: a `--no-traffic` deploy pins traffic
to the revision that was serving, and removing a tag can create a new revision
from the latest template. Delete test revisions when done.

## Check it works

```bash
URL=https://transit-assistant-308878596074.us-west2.run.app
curl -sN -H 'content-type: application/json' \
  -d '{"message":"Mountain View Caltrain to SAP Center tonight"}' $URL/chat
```

Expect, one JSON object per line: `options` first (with the route options and
`"attribution":"Routes by Google"`), several `text` events (or one `replace`),
`caveats`, then `done` with `latency_ms` per stage. An out-of-bounds message
(below) gives `scope` then `done`; an in-area trip with a missing end ("to SFO")
gives `follow_up`. Smoke test on 2026-11-01 (warm,
revision `00004`, image `e7825ae`):

| Question | First `options` | `done` | Notes |
| --- | --- | --- | --- |
| Mountain View Caltrain to SAP Center tonight | 1.5 s | 3.0 s (server total 2.5 s) | Caltrain, VTA, Caltrain options; 8 `text`, no `replace` |
| Diridon to San Francisco Caltrain tomorrow 8am | 1.8 s | 3.4 s | 3 Caltrain options |
| Berkeley BART to SFO tomorrow at 9am | 2.0 s | 4.1 s | 3 BART options |
| `asdf qwerty purple monkey dishwasher` | n/a | n/a | `follow_up` at 1.2 s |

The first request after a scale-from-zero start took 2.3 s to `options` and
6.3 s to `done` (`explain` 3.4 s); warm requests are in the table. A repeated
question inside 10 minutes skips the Routes call (routing cache).

## Out-of-bounds questions

The assistant answers only public-transit trips inside the Bay Area. Anything
else gets `{"type":"scope","reason":...,"text":...}` and then `done`, with no
Routes call and no Gemini call 2. Code decides; Gemini never writes the reply:

- **Gemini call 1** classifies. The extract schema has a required `scope`
  (`trip` | `out_of_scope`) and `scope_reason`: `out_of_area` (an end outside
  the Bay Area), `other_mode` (driving, flying, rideshare) or `off_topic`
  (weather, jokes, homework, chit-chat, nonsense, and prompt-injection
  attempts). `outside_place` names the end outside the area; it is used only
  if it is the trip's own origin or destination.
- **The box guard** checks every option's resolved `origin_latlng` and
  `dest_latlng` after routing (cached routes too). An end outside the box is
  answered as `out_of_area` and no options are shown. The box is
  lat 36.9 to 38.9, lng -123.6 to -121.2 (edges inclusive): the nine counties
  plus Caltrain and VTA to Gilroy (`assistant/scope.py`, `BAY_AREA_BOUNDS`).
  It is a rectangle, so Sacramento, Stockton, Davis and Santa Cruz fall inside
  it. For those, Gemini's `out_of_area` is the check. It also catches named
  places before routing: the `, San Francisco Bay Area, CA` suffix once pulled
  "Los Angeles" into SF, so the box alone did not catch that question.
- **The words** come from a hand-written pool in `assistant/scope.py`, five
  to six variants per reason, picked with `random.choice`. Out-of-area
  variants may name the rider's place, cleaned and cut to 40 characters.
  Every variant points the rider back at what the bot can do, and none
  contains times, numbers (other than in the example question), modes or
  routes. Tests check the whole pool.

## Client address and the rate limit

Each address may ask 10 questions an hour (`RATE_LIMIT_PER_HOUR`). The address
is the **last** `X-Forwarded-For` hop. Cloud Run (direct, no load balancer)
appends the real client address as the last hop and keeps whatever the client
sent before it. Verified on 2026-11-01 against a no-traffic revision with a
temporary log (since removed):

- no client header: `X-Forwarded-For` had 1 hop, the client's address;
- client sent `X-Forwarded-For: 1.2.3.4`: it arrived as `1.2.3.4,<client address>`,
  2 hops, so taking the last hop is correct and the first is forgeable;
- the TCP peer is always a Google `169.254.x.x` address, so falling back to it
  would put every rider in one bucket (it only happens if the header is absent);
- the request also carries `Forwarded`, `X-Forwarded-Proto` and
  `X-Cloud-Trace-Context`.

If a load balancer or Cloud CDN is ever put in front, the last hop becomes the
proxy and the limit must be re-derived (take the hop before the trusted proxy).
The limiter is per instance and in memory: with 2 instances the real ceiling is
20 an hour per address, and a restart resets it.

## Logs

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="transit-assistant"' \
  --limit 50 --freshness=1h
```

Per request there is one JSON line, `{"event":"chat","outcome":...,"latency_ms":{...},"events":{...}}`,
and nothing the rider typed. Verified on 2026-11-01 over 4 answered questions
and 1 follow-up: no question text, no place names, and neither secret value
appears in any log line (checked by searching every line for the exact secret
strings). The 511 `api_key` in the HTTP client's request log is rewritten to
`REDACTED` by `assistant/context_tools.py`. If you add logging, keep it that way:
do not log `message`, `ROUTES_API_KEY` or `TOKEN_511`.

## Rotate a secret

Cloud Run reads `:latest` when an instance starts, so a new secret version
needs a new revision.

```bash
# Routes key: create a new key in the console (API restriction: Routes API only),
# then add it as a new version without putting it in your shell history:
pbpaste | tr -d '\n' | gcloud secrets versions add routes-api-key --data-file=-

# 511 token: request a new one at https://511.org/open-data/token, then:
pbpaste | tr -d '\n' | gcloud secrets versions add token-511 --data-file=-

# New revision picks up :latest.
gcloud run services update transit-assistant --region us-west2 \
  --update-env-vars ROTATED=$(date +%Y%m%d)

# After /chat works with the new values, disable the old version and delete the old key.
gcloud secrets versions list routes-api-key
gcloud secrets versions disable <old-version> --secret=routes-api-key
```

Never paste a key into a file in the repository, a command line argument or a
chat. If a key is exposed, rotate it and delete the old one immediately.

## Costs

Cost per question is small and scales with questions asked, not with time: with
`--min-instances 0` an idle service costs nothing.

- **Cloud Run:** billed only while a request is being handled; the free tier
  covers a course project. `--max-instances 2` caps the spend.
- **Gemini (Vertex AI):** two Flash calls per answered question (at most 120 and
  250 output tokens, thinking off). A follow-up or form costs one call.
- **Google Routes:** one transit `computeRoutes` call per new question (cached
  10 minutes). Routes is billed per request; check the current SKU price and
  free monthly allowance on the Google Maps Platform pricing page.
- **511, Open-Meteo, NHL schedule:** free.
- **Backstops:** the rate limit above, the 500-character message cap, and the
  billing account's "$20 Monthly Budget Alert". A budget alert only emails; it
  does not stop spending. For a hard stop, turn the service off (below).

For a live demo, avoid the cold start and revert afterwards:

```bash
gcloud run services update transit-assistant --region us-west2 --min-instances=1   # before
gcloud run services update transit-assistant --region us-west2 --min-instances=0   # after
```

## Turn it off

Quickest, reversible, keeps the service and its config (callers get 403):

```bash
gcloud run services remove-iam-policy-binding transit-assistant --region us-west2 \
  --member=allUsers --role=roles/run.invoker
# back on:
gcloud run services add-iam-policy-binding transit-assistant --region us-west2 \
  --member=allUsers --role=roles/run.invoker
```

Permanent: `gcloud run services delete transit-assistant --region us-west2`. The
secrets, service account and images stay; delete them separately if wanted. The
site panel should also be hidden or pointed away, so riders do not see an error.
Turning the assistant off does not touch `transit-api` or the website.

## Local run (no keys, no network)

```bash
python3.11 -m venv .venv311 && .venv311/bin/pip install -r assistant/requirements.txt -r assistant/requirements-dev.txt
ASSISTANT_FAKE=1 .venv311/bin/uvicorn assistant.service:app --port 8080
.venv311/bin/python -m pytest tests/assistant
```
