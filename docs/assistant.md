# Route assistant — deploy and operate

`transit-assistant` is the FastAPI `/chat` service behind the site's chat panel
(`website/assistant.js`). It answers BART / VTA / Caltrain trip questions with
Google Routes itineraries, explained by Gemini on Vertex AI.

| | |
|---|---|
| Project | `cs-163-final-project-tra-f1136` |
| Service | Cloud Run `transit-assistant`, region `us-west2` |
| URL | https://transit-assistant-308878596074.us-west2.run.app |
| Image | `us-west2-docker.pkg.dev/cs-163-final-project-tra-f1136/transit-repo/transit-assistant:<short sha>` |
| Service account | `transit-assistant@cs-163-final-project-tra-f1136.iam.gserviceaccount.com` |
| Model | `GEMINI_MODEL=gemini-3-flash-preview`, `VERTEX_REGION=global` |

## Model and region

On 2026-11-01 the only Flash-tier model served to this project was
`gemini-3-flash-preview`, and only at location `global`; it returns 404 at
`us-west1`, and `gemini-2.5-flash`, `gemini-2.5-flash-lite` and
`gemini-3-flash` return 404. `thinkingBudget: 0` is accepted. So the deploy sets
`VERTEX_REGION=global`, overriding the `us-west1` default in `assistant/config.py`.
Before changing the model, check it with one real call:

```bash
T=$(gcloud auth print-access-token)
curl -s -H "Authorization: Bearer $T" -H content-type:application/json \
  "https://aiplatform.googleapis.com/v1/projects/cs-163-final-project-tra-f1136/locations/global/publishers/google/models/<MODEL>:generateContent" \
  -d '{"contents":[{"role":"user","parts":[{"text":"Say OK"}]}],"generationConfig":{"maxOutputTokens":10,"thinkingConfig":{"thinkingBudget":0}}}'
```

## Build and deploy

Build from a clean checkout of the commit you mean to ship:

```bash
P=cs-163-final-project-tra-f1136
TAG=$(git rev-parse --short HEAD)
gcloud builds submit --config=cloudbuild.assistant.yaml --substitutions=_TAG=$TAG .

IMG=us-west2-docker.pkg.dev/$P/transit-repo/transit-assistant
DIGEST=$(gcloud artifacts docker images describe $IMG:$TAG --format='value(image_summary.digest)')

gcloud run deploy transit-assistant --region us-west2 \
  --image $IMG@$DIGEST \
  --service-account transit-assistant@$P.iam.gserviceaccount.com \
  --max-instances 2 --cpu-boost \
  --set-secrets ROUTES_API_KEY=routes-api-key:latest,TOKEN_511=token-511:latest \
  --set-env-vars GCP_PROJECT=$P,VERTEX_REGION=global,GEMINI_MODEL=gemini-3-flash-preview \
  --allow-unauthenticated
```

Deploy by digest, never by tag: a tag can move, a digest cannot. The build
context is filtered by both `.gcloudignore` and `.dockerignore`. Each keeps
`website/` out except the three `website/data` JSON files that `station_data`
reads (`stations_meta.json`, `stations_ridership.json`, `forecasts_sarima.json`).

Confirm what is live:

```bash
gcloud run services describe transit-assistant --region us-west2 \
  --format='value(spec.template.spec.containers[0].image)'
curl -s https://transit-assistant-308878596074.us-west2.run.app/health   # {"status":"ok","model":"..."}
```

Smoke test (NDJSON: `options`, then `text` deltas or one `replace`, then `caveats`, then `done` with `latency_ms`):

```bash
curl -s -X POST -H content-type:application/json \
  https://transit-assistant-308878596074.us-west2.run.app/chat \
  -d '{"message":"Powell St BART to 12th St Oakland tomorrow at 9am"}'
```

## Secrets

Keys live only in Secret Manager, and the service reads them as env vars through `--set-secrets`:

| Secret | Env var | Notes |
|---|---|---|
| `routes-api-key` | `ROUTES_API_KEY` | API key restricted to the Routes API only |
| `token-511` | `TOKEN_511` | 511.org token (service alerts) |
| *(none)* | `TICKETMASTER_KEY` | optional; unset, so events come from the NHL schedule only |

The service account holds `roles/secretmanager.secretAccessor` on those two
secrets only, not on the project. It holds `roles/aiplatform.user` on the
project. Gemini uses the service account, so no Gemini key exists.

To rotate a secret, add a new version and redeploy, because `:latest` is resolved when an instance starts:

```bash
printf '%s' "$NEW_VALUE" | gcloud secrets versions add routes-api-key --data-file=-
# redeploy (same command as above), then disable the old version:
gcloud secrets versions disable <OLD_VERSION> --secret routes-api-key
```

Never echo, log or commit a key. Request logs carry counts and per-stage
latency only, never the message text.

## CORS origins

`assistant/service.py` (`ALLOWED_ORIGINS`, `LOCAL_ORIGIN_RE`) allows:

- `https://cs-163-final-project-tra-f1136.web.app` (Firebase)
- `https://cs-163-final-project-tra-f1136.wl.r.appspot.com` (App Engine)
- `http://localhost[:port]` and `http://127.0.0.1[:port]` (local development)

A Firebase **preview channel** (`…--<channel>-<hash>.web.app`) is a different
origin, so it is blocked unless you add it to `ALLOWED_ORIGINS` and redeploy.
To check the allow header:

```bash
curl -s -i -X OPTIONS https://transit-assistant-308878596074.us-west2.run.app/chat \
  -H 'Origin: https://cs-163-final-project-tra-f1136.web.app' \
  -H 'Access-Control-Request-Method: POST' -H 'Access-Control-Request-Headers: content-type' \
  | grep -i access-control-allow-origin
```

The site finds the service through `ASSISTANT_URL` in `website/assistant.js`.
After changing it, bump `assistant.js?v=` in `website/index.html` and
`website/transit-demo.html`.

## Cost controls

- `--max-instances 2`, and min instances is 0, so an idle service costs nothing.
- Each answered question makes exactly two Flash calls with thinking off. Call 2
  takes under 2k input tokens and returns at most 250 output tokens.
- Each question makes one Routes call and at most four context tools. The
  routing cache lasts 10 min, and the weather and alerts caches last 5 min.
- Each IP gets 10 questions per hour, and a message may hold at most 500 characters.
- Budget: the existing "$20 Monthly Budget Alert" covers the billing account.
  Check it with `gcloud billing budgets list --billing-account=<ID>`.
- To stop all public spend at once, remove public access:
  `gcloud run services remove-iam-policy-binding transit-assistant --region us-west2 --member=allUsers --role=roles/run.invoker`.

## Rollback

Every deploy creates a revision. To list the revisions and send traffic back to an earlier one:

```bash
gcloud run revisions list --service transit-assistant --region us-west2
gcloud run services update-traffic transit-assistant --region us-west2 \
  --to-revisions <REVISION>=100
```

Or redeploy an older image by its digest, using the deploy command above with
that commit's tag. To point the site elsewhere without touching the service, change
`ASSISTANT_URL` in `website/assistant.js`, bump `?v=` and redeploy the site.
