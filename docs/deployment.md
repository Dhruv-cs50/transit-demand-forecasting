# Cloud deployment

Everything runs in Google Cloud project `cs-163-final-project-tra-f1136`. Design
and rationale: [cloud-ingestion-design.md](cloud-ingestion-design.md). Overview
diagram: [README § Architecture](../README.md#architecture).

## Infrastructure

| Component | GCP service | Details |
| --- | --- | --- |
| Website | App Engine Standard (`python312`) and Firebase Hosting | Static files from `website/`; App Engine handlers in `website/app.yaml`, Firebase in `firebase.json` |
| Forecast API | Cloud Run service `transit-api` (us-west2) | FastAPI container; gen2, `--cpu-boost`; service account `transit-api` (`roles/storage.objectViewer` on the bucket only); the bucket is mounted read-only at `/mnt/store` with `SERVING_STORE_DIR=/mnt/store` |
| Data bucket | Cloud Storage `gs://cs-163-final-project-tra-f1136-transit-data` (us-west1) | Versioning on, public access prevented, uniform access, noncurrent versions deleted after 30 days |
| Ingest job | Cloud Run Job `transit-ingest` (us-west2) | Fetch → rebuild → gate → publish. 1 CPU, 2 GiB, 15 min timeout, no retries; service account `transit-ingest` (`roles/storage.objectUser` on the bucket only) |
| Scheduler | Cloud Scheduler `transit-ingest-daily` (us-west2) | 03:15 America/Los_Angeles; calls the job's `:run` endpoint as `transit-scheduler` (`roles/run.invoker` on the job only) |
| Images | Artifact Registry `us-west2-docker.pkg.dev/<project>/transit-repo` | `transit-api:<commit>` (and `:tag1`), `transit-ingest:<commit>` |
| Builds | Cloud Build | `cloudbuild.yaml` builds `Dockerfile.api`; `cloudbuild.ingest.yaml` builds `Dockerfile.ingest`; both `linux/amd64`, tagged with the commit. Neither deploys |

BigQuery, Cloud Functions and Pub/Sub are not used.

## What is live, and how to check

`GET https://transit-api-308878596074.us-west2.run.app/health` names the served
model and store: `store_source` (`cloud` or `baked`), `store_run_id`,
`store_sha256` and `store_last_month`.

Verified on 2026-10-28:

- The API runs image `transit-api:a156811` (deployed by digest
  `sha256:2d23c42f…`) and serves the cloud store published by run
  `20261028T084556Z-5e1329` (store sha256 `f19f6051…`, last month 2025-12).
- `scripts/smoke_cloud.sh` against the live system passed 7 of 7 checks,
  including 50 live `/forecast` calls at `as_of=2025-06-30` that score 3.21%
  WAPE over 300 station-months, matching the published leaderboard.
- The ingest job's first execution fetched Jan–Sep 2026 weather and Sharks data,
  rebuilt the store, passed all 10 gate checks and published in 1m04s. Two later
  runs logged `unchanged` and exited 0.
- Both website hosts serve `main`; all six `website/data/*.json` files are
  byte-identical to the repository.

Before 2026-10-28 the live API was a May 2026 image that answered `/forecast`
with `No module named 'chronos'`.

For a live demo, keep one instance warm and turn it off afterwards:

```bash
gcloud run services update transit-api --region us-west2 --min-instances=1   # before
gcloud run services update transit-api --region us-west2 --min-instances=0   # after
```

## What the cloud pipeline does not do

- **Forecasts do not refresh nightly.** The job fetches new weather and Sharks
  data, which no forecast reads (SARIMA uses `ridership` alone), and it
  publishes a new store only when its inputs change. The API's forecast origin
  moves only when a new BART workbook is uploaded.
- **BART ingestion is manual.** bart.gov answers automated requests with HTTP
  403, so each workbook is downloaded in a browser and uploaded to `raw/bart/`.
- **The cloud store is not byte-identical to the committed one.** The job builds
  on Python 3.11 / pandas 2.2; the committed store (`6cde32d4…`) was built on
  Python 3.14 / pandas 3. The gate checks that `ridership` is exactly equal and
  covariates agree within `1e-9`. The leaderboard, charts and website read the
  committed store.

## The publish gate

Every check must pass before a store is published; `gate.json` records each one.

1. `validate_feature_store` in strict mode reports no error.
2. `(station_id, timestamp)` keys are unique.
3. Every month has the committed store's 50 stations.
4. Every key of the committed store is present, with `ridership` exactly equal
   and covariates within `1e-9` (NaN equals NaN).
5. No month the API currently serves disappears.
6. No month is later than the last closed month.
7. SARIMA fitted on the candidate at `as_of=2025-06-30` still scores 3.21% WAPE
   over the 50 stations.

(The gate reports these as 10 named checks: `validate_feature_store`,
`unique_keys`, `station_set`, `tracked_columns`, `tracked_keys_present`,
`ridership_exact`, `covariates_within_rtol`, `served_months_retained`,
`no_future_month`, `sarima_backtest`.) A failed gate exits 1 and leaves the
serving pointer untouched.

## How the API picks its store

If `SERVING_STORE_DIR` is set, the API reads `processed/serving.json`, loads the
parquet it names and checks its sha256. Any failure logs a warning and the API
serves the store baked into its image. It re-reads the pointer every
`STORE_TTL_SECONDS` (default 600) and swaps to a new `run_id`; a failed reload
keeps the current store.

## Data in the bucket

| Data | Location | Notes |
| --- | --- | --- |
| Raw inputs | `raw/bart/`, `raw/weather/`, `raw/events/` | The 20 inputs the committed store was built from (4 BART zips, 12 monthly 2025 workbooks, 2 weather and 2 events archives), checked against sha256s pinned in `configs/ingest.yaml`, plus objects the job fetches (2026 weather and Sharks). BART workbooks are uploaded by hand |
| Published stores | `processed/runs/<run_id>/` | `feature_store.parquet`, `gate.json`, `manifest.json`. Written once, never overwritten |
| Serving pointer | `processed/serving.json` | The only overwritten object: `run_id`, `store_object`, `store_sha256`, `input_fingerprint`, `published_at`. Written last, only after the gate passes |

Forecasts are not stored: each `/forecast` fits SARIMA from the store.

## Containers

- **`Dockerfile.api`** (Cloud Run service): `python:3.11-slim`; copies `api.py`,
  `models/baselines/arima.py`, `evaluation/calibration.py`, `configs/model.yaml`
  and the committed feature store (the fallback); installs `statsmodels`. No
  forecast cache and no `chronos-forecasting`.
- **`Dockerfile.ingest`** (Cloud Run Job): the same pins plus `openpyxl`,
  `requests` and `google-cloud-storage`; entrypoint
  `python -m machine_learning_files.cloud_ingest`. `--dry-run` and
  `--bucket file:///<dir>` run it against a local directory with no GCP.
- **`Dockerfile`** (full pipeline): for reproducing results in a batch
  environment.

## Deploy commands

Tag every build with the commit, then deploy by digest so a revision names
exactly the image it runs. The bucket, service accounts and IAM bindings are
created once, as in [cloud-ingestion-design.md](cloud-ingestion-design.md) §5.

```bash
P=cs-163-final-project-tra-f1136
R=us-west2
B=$P-transit-data
TAG=$(git rev-parse --short HEAD)
REPO=us-west2-docker.pkg.dev/$P/transit-repo

# Ingest job: build, deploy, schedule
gcloud builds submit --config=cloudbuild.ingest.yaml --substitutions=_TAG=$TAG .
gcloud run jobs deploy transit-ingest --image $REPO/transit-ingest:$TAG --region $R \
  --service-account transit-ingest@$P.iam.gserviceaccount.com --set-env-vars INGEST_BUCKET=gs://$B \
  --cpu 1 --memory 2Gi --task-timeout 15m --max-retries 0
gcloud run jobs add-iam-policy-binding transit-ingest --region $R \
  --member serviceAccount:transit-scheduler@$P.iam.gserviceaccount.com --role roles/run.invoker
gcloud scheduler jobs create http transit-ingest-daily --location $R \
  --schedule "15 3 * * *" --time-zone America/Los_Angeles \
  --uri https://run.googleapis.com/v2/projects/$P/locations/$R/jobs/transit-ingest:run --http-method POST \
  --oauth-service-account-email transit-scheduler@$P.iam.gserviceaccount.com

# API: build, then deploy by digest with the bucket mounted read-only
gcloud builds submit --config=cloudbuild.yaml --substitutions=_TAG=$TAG .
DIGEST=$(gcloud artifacts docker images describe $REPO/transit-api:$TAG \
  --format='value(image_summary.digest)')
gcloud run deploy transit-api --image $REPO/transit-api@$DIGEST --region $R \
  --service-account transit-api@$P.iam.gserviceaccount.com --execution-environment gen2 --cpu-boost \
  --add-volume name=store,type=cloud-storage,bucket=$B,readonly=true \
  --add-volume-mount volume=store,mount-path=/mnt/store --set-env-vars SERVING_STORE_DIR=/mnt/store \
  --allow-unauthenticated --port 8080

# Website (from a clean checkout)
gcloud app deploy website/app.yaml --quiet
firebase deploy --only hosting
```

Add a BART month by hand, then check the system end to end:

```bash
gcloud storage cp Ridership_2026MM.xlsx gs://$B/raw/bart/
gcloud run jobs execute transit-ingest --region $R --wait
API_URL=https://transit-api-308878596074.us-west2.run.app scripts/smoke_cloud.sh
```

`scripts/smoke_cloud.sh --local` checks a local uvicorn and skips the `gcloud`
checks.

## Scalability

- **App Engine Standard and Firebase Hosting** serve static files and scale
  with no server management.
- **Cloud Run** scales 0→N stateless replicas by request concurrency.
- **Per-request SARIMA** is one small fit (about 48 monthly points). In a local
  container one forecast took 0.03–0.6 s; the `statsmodels` import (1–17 s
  there) runs at startup, so it lands on the cold start. Neither has been
  measured on Cloud Run. Nothing is cached between requests.
