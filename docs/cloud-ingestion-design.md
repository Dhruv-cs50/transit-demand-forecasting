# Cloud ingestion on GCP and how the API reads it (S8-10 design, 2026-10-28)

Design by the systems architect for Sprint 9. Assumptions not verified from the repo are marked
**[A#]** and listed at the end.

## The fact that shapes the design

`merge_pipeline.build_feature_store` takes its rows from the BART months (`base = transit_df.copy()`),
and the API's SARIMA reads only `ridership`. New weather or Sharks data can never change a
forecast; only a new BART workbook adds months or moves the API's default forecast origin.
Nothing may claim "forecasts refresh nightly". The fetchers keep covariate columns complete for
months BART adds later; until a 2026 BART workbook is uploaded **[A1]** the pipeline does not
change what the API returns, but the API serves a store built, validated and published in the
cloud, and `/health` names it.

## 1. Components

| Keep | Why |
|---|---|
| GCS bucket `gs://cs-163-final-project-tra-f1136-transit-data`, `us-west1`, uniform access, public access prevented, versioning on, lifecycle deletes noncurrent versions after 30 days | Raw and processed data; Always Free region **[A2]**; data < 100 MB **[A3]** |
| Cloud Run Job `transit-ingest` (us-west2) | Fetch → stage → rebuild → gate → publish; batch, billed only while running |
| Cloud Scheduler `transit-ingest-daily` | HTTP POST to the job's `:run` endpoint with OAuth |
| Existing Cloud Run service `transit-api` | Mounts the bucket read-only as a Cloud Storage volume at `/mnt/store` (gen2, `roles/storage.objectViewer`); no GCS client library in the API |

Dropped: BigQuery (no query need; a fabricated BigQuery claim is in the repo's history), Cloud
Functions, Pub/Sub, cloud feature engineering (the API never reads the enriched store),
`models/baselines/scheduler.py` (runs Chronos), the root `Dockerfile` (torch/chronos), the
`weather_forecast_*` files. Eventarc → Workflows upload trigger is a stretch (S9-14).

Layout: `raw/bart/*.zip|*.xlsx` (manual), `raw/weather/weather_all_stations_<start>_<end>.parquet`,
`raw/events/events_<start>_<end>.parquet`; `processed/runs/<run_id>/{feature_store.parquet,
gate.json, manifest.json}` (write-once); `processed/serving.json` (the only overwritten object).

## 2. What the job does on each run

Daily 03:15 America/Los_Angeles; entrypoint `python -m machine_learning_files.cloud_ingest`.

1. **Fetch.** Only closed months (ended ≥ `archive_lag_days` = 7 days ago **[A4]**), never before
   `fetch_floor: 2026-01-01`, so 2019–2025 archives are never touched. Weather via
   `OpenMeteoClient.get_historical` for the 7 locations in `configs/sources.yaml`; Sharks via
   `NHLClient.get_schedule` + `enrich_events`. One object per source per year, existing naming,
   honest dates; a newer same-year object replaces (deletes) the older; never replace an object
   with one that has fewer rows (the NHL client swallows per-season failures).
2. **Fingerprint.** sha256 over sorted `name:generation` of `raw/**`; equal to
   `serving.json.input_fingerprint` → log "unchanged", exit 0 (unless `--force`).
3. **Stage.** Download raw objects into a temp workdir, set mtime from the object's `updated`
   (the loaders sort by mtime before de-duplicating); check the 9 pinned sha256s from MANIFEST
   (in `configs/ingest.yaml`); mismatch fails the run.
4. **Rebuild.** `bart_od_from_xlsx.build(...)` then `merge_pipeline.build_feature_store()` (default
   args, no splits) inside a context manager pointing `RAW_DIR`, `PROCESSED_DIR`, `CONFIG_PATH`,
   `MODEL_CONFIG_PATH` at the workdir. The tracked store is never written.
5. **Gate** (all must pass): `validate_feature_store(mode=STRICT)`; unique `(station_id, timestamp)`;
   every month has the tracked store's 50 stations; every tracked key present with `ridership`
   **exactly** equal and covariates within `rtol`; month set ⊇ the served store's; no month after
   the last closed month; SARIMA backtest at `as_of=2025-06-30` over 50 stations gives WAPE 3.21
   (2 dp).
6. **Publish.** Always write `runs/<id>/gate.json`; gate failure → exit 1, pointer untouched. Same
   content as served → exit 0. Else write `feature_store.parquet`, `manifest.json` (git SHA,
   input generations + sha256s, store sha256, months, gate results), then `serving.json` last with
   `if_generation_match`; lost race → exit 3.

Exit codes: 0 published/unchanged; 1 gate/build failure; 2 a fetch failed (rest completes);
3 another execution published first.

## 3. BART stays manual

bart.gov answers automated downloads with 403. Flow: download the workbook in a browser →
`gcloud storage cp Ridership_2026MM.xlsx gs://…/raw/bart/` → `gcloud run jobs execute
transit-ingest --region us-west2 --wait` (or the 03:15 run). The month reaches the API within the
10-minute TTL or on the next cold start.

## 4. Serving store vs scoring store

API (after S8-06): if `SERVING_STORE_DIR` is set, read `<dir>/processed/serving.json`, load the
named parquet, verify its sha256; any failure warns and falls back to the baked
`data/processed/feature_store.parquet`. Re-read the pointer every `STORE_TTL_SECONDS` (600) and swap
on a new `run_id`; a failed reload keeps the current store. `/health` adds `store_source`
(`cloud`/`baked`), `store_run_id`, `store_sha256`. Unset (local, tests) = today's behaviour.

Benchmarks, `export_website_data.py` and the site keep the tracked store (sha256 `aa02436d…`). The
gate guarantees ridership equals the tracked store through 2025-12, so `as_of=2025-06-30` gives
3.21 % on either store. The cloud store's bytes will not hash to `aa02436d` (built on Python 3.11 /
pandas 2.2); nothing claims byte equality.

May be said once S9-11's smoke check passes: a daily Cloud Run job on Cloud Scheduler fetches
Open-Meteo weather and the Sharks schedule into Cloud Storage, rebuilds the feature store from the
bucket, validates it and publishes it only if it passes; the forecast API runs SARIMA on Cloud Run
from the latest published store, named by `/health`; BART workbooks are downloaded by hand
(bart.gov blocks automated downloads); the leaderboard and charts come from the store committed in
the repo. Must not be said: forecasts refresh nightly; BART ingestion is automated; weather or
events affect forecasts; BigQuery; the cloud store equals `aa02436d`.

## 5. Code changes

- `machine_learning_files/cloud_store.py`: `ObjInfo(name, generation, updated, size)`; `Store` with
  `list(prefix)`, `download(name, dest)` (sets mtime), `upload(src, name, *, if_generation_match=None)`,
  `read_bytes(name) -> (bytes, gen) | None`, `write_bytes(name, data, *, if_generation_match)`
  (0 = must not exist), `delete(name, *, if_generation_match=None)`; `PreconditionFailed`;
  `LocalStorage(root)`, `GcsStorage(bucket)` (lazy `google.cloud.storage` import);
  `open_store(uri)` for `gs://…` or `file:///…`.
- `machine_learning_files/ingest_fetch.py`: `last_closed_month_end(today, lag_days)`,
  `fetch_window(today, floor)`, `fetch_weather(store, cfg, today, client=None)`,
  `fetch_sharks(store, cfg, today, client=None)` → `FetchResult(source, object_name, rows, status,
  detail)`; reuses the existing clients, fetcher files untouched.
- `machine_learning_files/ingest_gate.py`: `run_gate(candidate, tracked, served_months, cfg) ->
  GateReport(passed, failures, checks)`; SARIMA check uses `fit_station`/`predict_station` as
  `api._run_forecast` does.
- `machine_learning_files/cloud_ingest.py`: `main(argv)` with `--bucket` (default `$INGEST_BUCKET`),
  `--skip-fetch`, `--force`, `--dry-run`; `stage_inputs`, `input_fingerprint`,
  `build_candidate(workdir, builder=None)`, `publish`.
- `configs/ingest.yaml` (new): `bucket`, `fetch_floor`, `archive_lag_days`, `schedule: "15 3 * * *"`,
  `pinned_inputs` (9 sha256s from MANIFEST), `gate: {expected_stations: 50, tracked_store,
  covariate_rtol: 1e-9, sarima_backtest: {as_of: "2025-06-30", wape_pct: 3.21}}`,
  `serving_pointer: processed/serving.json`.
- `Dockerfile.ingest`: `python:3.11-slim`, `Dockerfile.api`'s pins plus `openpyxl==3.1.5`,
  `requests==2.32.3`, `google-cloud-storage==2.18.2` **[A5]**; copies `configs/`, the needed
  `machine_learning_files/*.py`, `models/baselines/arima.py`, `evaluation/validators.py`, the tracked
  store (gate reference); `ARG GIT_SHA`; `ENTRYPOINT ["python","-m","machine_learning_files.cloud_ingest"]`.
- `cloudbuild.ingest.yaml`: build `--platform=linux/amd64 --build-arg GIT_SHA=$_TAG -f
  Dockerfile.ingest -t us-west2-docker.pkg.dev/$PROJECT_ID/transit-repo/transit-ingest:$_TAG`, push.
- Changed later: `api.py` (S9-08), docs (S9-12), `website/sections.jsx` (S9-15). `Dockerfile.api`
  unchanged (baked store stays the fallback).

Deploy commands (run with the user; `P=cs-163-final-project-tra-f1136`, `R=us-west2`, `B=$P-transit-data`):

```bash
gcloud services enable cloudscheduler.googleapis.com cloudbuild.googleapis.com
gcloud storage buckets create gs://$B --location=us-west1 --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://$B --versioning
for s in transit-ingest transit-api transit-scheduler; do gcloud iam service-accounts create $s; done
gcloud storage buckets add-iam-policy-binding gs://$B --member=serviceAccount:transit-ingest@$P.iam.gserviceaccount.com --role=roles/storage.objectUser
gcloud storage buckets add-iam-policy-binding gs://$B --member=serviceAccount:transit-api@$P.iam.gserviceaccount.com --role=roles/storage.objectViewer
gcloud builds submit --config=cloudbuild.ingest.yaml --substitutions=_TAG=$(git rev-parse --short HEAD) .
gcloud run jobs deploy transit-ingest --image us-west2-docker.pkg.dev/$P/transit-repo/transit-ingest:$TAG --region $R \
  --service-account transit-ingest@$P.iam.gserviceaccount.com --set-env-vars INGEST_BUCKET=gs://$B \
  --cpu 1 --memory 2Gi --task-timeout 15m --max-retries 0
gcloud run jobs add-iam-policy-binding transit-ingest --region $R --member serviceAccount:transit-scheduler@$P.iam.gserviceaccount.com --role roles/run.invoker
gcloud scheduler jobs create http transit-ingest-daily --location $R --schedule "15 3 * * *" --time-zone America/Los_Angeles \
  --uri https://run.googleapis.com/v2/projects/$P/locations/$R/jobs/transit-ingest:run --http-method POST \
  --oauth-service-account-email transit-scheduler@$P.iam.gserviceaccount.com
gcloud run deploy transit-api --image …/transit-api:tag1 --region $R --service-account transit-api@$P.iam.gserviceaccount.com \
  --execution-environment gen2 --add-volume name=store,type=cloud-storage,bucket=$B,readonly=true \
  --add-volume-mount volume=store,mount-path=/mnt/store --set-env-vars SERVING_STORE_DIR=/mnt/store \
  --allow-unauthenticated --port 8080
```

## 6. Operations

IAM: ingest SA `objectUser` on the bucket only; API SA `objectViewer` on the bucket only (replaces
the default compute SA); scheduler SA `run.invoker` on the job only; optional trigger SA (S9-14)
**[A6]**. No deploy permission in Cloud Build.

Cost: ~30 runs/month, mostly 30 s no-ops, under 6k vCPU-s (free tier **[A7]**, else ~$0.10);
Scheduler 1 of 3 free jobs; storage < 100 MB free; second image may exceed Artifact Registry's
0.5 GB free (~$0.10). Expected $0–0.30/month.

Failure handling: a failed gate never publishes; run outputs are write-once; the pointer is written
last under a precondition; the API verifies sha256 and falls back to the baked store. Failures show
in `gcloud run jobs executions list`; 30 days of noncurrent versions allow rollback.

## 7. Tests (no GCP needed)

- `tests/test_cloud_store.py`: `LocalStorage` incl. mtime, preconditions, delete; `google` not imported.
- `tests/test_ingest_fetch.py`: window (2026-10-28 → through 2026-09-30), floor guard, deterministic
  names, same-year replace/delete, refuse to shrink, fetch failure writes nothing; fake clients.
- `tests/test_ingest_gate.py`: tracked store passes incl. 3.21; tracked + synthetic 2026-01 passes;
  fails on one changed ridership cell, dropped station-month, duplicate key, shrunken month set,
  future month.
- `tests/test_cloud_ingest.py` (`LocalStorage`, injected builder): first run publishes; rerun
  unchanged; gate failure writes `gate.json`, pointer untouched; race exits 3; tracked store sha
  unchanged; overlapping weather files with reversed `updated` → later-updated wins.
- `tests/test_api_serving_store.py` (`tdf-api-py311`): unset → baked; valid pointer → `cloud` +
  `/health` fields; sha mismatch / missing pointer / missing dir → baked; TTL reload picks up a new
  `run_id`; cloud store with an extra month still gives 3.21 at `as_of=2025-06-30`.
- Live smoke `scripts/smoke_cloud.sh` (read-only): latest execution succeeded; `serving.json`
  exists and its `gate.json` passed; `/health` `store_source == cloud`, sha matches the pointer;
  50 `/forecast` calls at `as_of=2025-06-30` give WAPE 3.21; default forecast starts the month after
  `store_last_month`.

## 8. Stories

P = parallel (disjoint files). U = needs the user.

| ID | Goal | Owner | Depends on | Files | Acceptance check | P/U |
|---|---|---|---|---|---|---|
| S9-01 | Auth; confirm billing; enable APIs; bucket, versioning, lifecycle, 3 SAs, bindings | user + orchestrator | — | — | bucket describe OK; exactly the 2 bucket bindings | U |
| S9-02 | Seed bucket: 5 BART zips → `raw/bart/`, 4 covariate archives → `raw/weather/`, `raw/events/`; sha256 vs MANIFEST first | user | S9-01 | — | 9 objects; 9 sha256 match | U |
| S9-03 | Storage abstraction | engineer | — | `cloud_store.py`, `tests/test_cloud_store.py` | Tests pass without google libs | P |
| S9-04 | Closed-month fetchers | engineer | S8-09 merged | `ingest_fetch.py`, `tests/test_ingest_fetch.py` | Tests pass, no network | P |
| S9-05 | Publish gate | engineer | — | `ingest_gate.py`, `tests/test_ingest_gate.py` | Tracked passes; each tampering fails with a named reason | P |
| S9-06 | Job orchestrator + config | engineer | S9-03..05 | `cloud_ingest.py`, `configs/ingest.yaml`, `tests/test_cloud_ingest.py` | E2E tests pass; tracked sha unchanged | — |
| S9-07 | Ingest image + build | engineer | S9-06 (entrypoint) | `Dockerfile.ingest`, `cloudbuild.ingest.yaml` | Build succeeds; `--bucket file:///seed --dry-run` exits 0 | P |
| S9-08 | API reads the cloud store, TTL + fallback | engineer | S8-06 merged | `api.py`, `tests/test_api_serving_store.py` | New + unchanged `test_api.py` pass (3.11) | P |
| S9-09 | Smoke script | QA | — | `scripts/smoke_cloud.sh` | shellcheck clean; dry run vs localhost passes | P |
| S9-10 | Deploy job; first execution | orchestrator + user | S9-01, S9-02, S9-07 | — | execution succeeded; `gate.json` passed; pointer written | U |
| S9-11 | Scheduler; redeploy API with volume (with S8-01); smoke | orchestrator + user | S9-08..10, S8-01 | — | scheduled run reports unchanged; smoke passes | U |
| S9-12 | Docs: README cloud sections, ARCHITECTURE, DATA_PIPELINE, MANIFEST, site-claims-audit | tech writer | S9-11 | 5 docs | Every §4 claim links to evidence | — |
| S9-13 | Live BART refresh if bart.gov has 2026 workbooks | user + orchestrator | S9-11 | — | `/health` last month moves; 3.21 holds | U |
| S9-14 | Stretch: upload trigger (Eventarc → Workflows → job) | engineer + user | S9-11 | `workflows/bart_upload.yaml` | upload to `raw/bart/` starts one execution | U |
| S9-15 | Site copy at `sections.jsx:158` + cache-buster | frontend engineer | S9-11, S8-08 | `website/sections.jsx` | Copy matches §4; parses | — |
| S9-16 | Stretch: alert on job failure | user | S9-11 | — | forced failure sends email | U |

Critical path: S9-01 → S9-02 → (S9-06, S9-07) → S9-10 → S9-11.

## Assumptions not verified

- **[A1]** Whether bart.gov has published any 2026 monthly workbooks.
- **[A2]** Always Free regions (`us-west1`, `us-central1`, `us-east1`; 5 GB), from secondary sources.
- **[A3]** BART zip sizes; `data/raw` is not in any checkout; the user's archive location.
- **[A4]** Open-Meteo archive lag (7 days chosen).
- **[A5]** The pins install on Python 3.11 without gcc; pandas 2.2 `merge_pipeline` covariates
  within `rtol` of the pandas 3 build (if not, loosen `rtol` for covariates only, never ridership).
- **[A6]** `run.invoker` suffices for the Workflows connector (Google's tutorial grants Run Admin).
- **[A7]** Cloud Run free tier covers jobs; Cloud Scheduler in us-west2; project billing enabled.
- S8-09's coverage rules; gcsfuse metadata cache staleness (~60 s, harmless); `NHLClient` and a
  calendar year's future games.
