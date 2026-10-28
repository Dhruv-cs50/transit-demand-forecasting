# Data Pipeline Runbook

This runbook documents how to rebuild the project data, models, validation outputs, and website JSON from the repository root.

## Prerequisites

Python 3.14.0 and the pinned environment from the README's Setup section:

```bash
python3.14 -m venv ~/.venvs/tdf-py314
source ~/.venvs/tdf-py314/bin/activate
pip install -r requirements-lock.txt
```

`requirements-lock.txt` leaves out the serving stack; see the README.

Review `configs/sources.yaml` before running ingestion. Replace placeholder keys where needed.

## Source Data

| Source | Script | Notes |
| --- | --- | --- |
| BART OD ridership | `machine_learning_files/bart_od_from_xlsx.py` | Current primary target source. bart.gov answers automated requests with HTTP 403, so the Ridership workbooks are downloaded by hand (see `data/MANIFEST.md`); this script converts them into `data/raw/transit/bart/`. `fetch_bart_od.py` exists but cannot download them. |
| 511 SF Bay transit | `machine_learning_files/fetch_511_transit.py` | Requires a 511 API key. Used for future higher-frequency expansion. |
| Open-Meteo weather | `machine_learning_files/fetch_weather_openmeteo.py` | No API key required. Uses station coordinates from `configs/sources.yaml`. |
| NHL and Ticketmaster events | `machine_learning_files/fetch_events.py` | NHL API is public; Ticketmaster requires an API key. |
| Caltrans PeMS roads | `models/baselines/fetch_pems_roads.py` | PeMS often requires authenticated manual download. |

The cloud job fetches Open-Meteo weather and the Sharks schedule itself (see [Cloud ingest job](#cloud-ingest-job)); the commands below are the local path.

## Rebuild Steps

### 1. Fetch raw data

Run only the fetchers needed for your current experiment. BART's Ridership workbooks are downloaded by hand first (see `data/MANIFEST.md`); the first command converts them:

```bash
python machine_learning_files/bart_od_from_xlsx.py --zips /path/to/*.zip   # or --dir /path/to/workbooks
python machine_learning_files/fetch_weather_openmeteo.py
python machine_learning_files/fetch_events.py
```

### 2. Build feature store and splits

```bash
python machine_learning_files/merge_pipeline.py
```

Expected outputs:

- `data/processed/feature_store.parquet`
- `data/processed/splits/train.parquet` (pre-enrichment; overwritten by step 3)
- `data/processed/splits/val.parquet` (pre-enrichment; overwritten by step 3)
- `data/processed/splits/test.parquet` (pre-enrichment; overwritten by step 3)

### 3. Add engineered features

```bash
python Processing/feature_engineering.py
```

Expected output:

- `data/processed/feature_store_enriched.parquet`
- `data/processed/splits/{train,val,test}.parquet` — regenerated from the
  enriched store so downstream consumers (`evaluation/metrics.py`'s default
  `--actuals`) evaluate on the full enriched schema, not the raw one step 2
  wrote.

### 4. Validate data quality

```bash
python evaluation/validators.py --input data/processed/feature_store_enriched.parquet --mode lenient --freq MS
```

Use `--mode strict` when you want validation errors to halt automation.

### 5. Run forecasts and benchmarks

```bash
python machine_learning_files/zero_shot.py
python models/baselines/arima.py
python models/baselines/prophet_baseline.py
python models/baselines/benchmarks.py
```

Expected outputs include:

- `models/chronos2/outputs/zero_shot_forecasts_*.parquet` — written by
  `zero_shot.py`. Not what the website publishes; step 6 does not read it.
- `models/baselines/outputs/`
- `evaluation/outputs/benchmark_leaderboard.csv`
- `evaluation/outputs/chronos2_zeroshot_preds.parquet` — the Chronos
  zero-shot test-window predictions, written by `models/baselines/benchmarks.py`
  and scored on the leaderboard. Step 6 reads it for `forecasts.json`.

### 6. Export website data

```bash
python scripts/export_website_data.py --feature-store data/processed/feature_store_enriched.parquet
```

Run it from the repo root: the `evaluation/outputs/` inputs are read relative to
the working directory. Every station id in the outputs is the store's
two-letter BART workbook code (`EM`, `MT`, `12`, ...); names, website node ids
and weather locations come from `machine_learning_files/bart_stations.py`.

Expected outputs:

- `website/data/stations_ridership.json` — object keyed by station code, all
  stations: name, website node id (or null), average monthly ridership over the
  store's latest 12 months and that average on a 0–2.4 heat scale.
- `website/data/stations_meta.json` — list of all stations (`bart_id` = code)
  with API code, website node id, name, weather station and that average,
  highest average first.
- `website/data/ridership_actuals.json` — every feature-store row, keyed by
  station code and month: monthly ridership and a daily estimate.
- `website/data/forecasts.json` — keyed by station code and month: the Chronos
  zero-shot P10/P50/P90 test-month predictions that
  `models/baselines/benchmarks.py` scored on the leaderboard
  (`evaluation/outputs/chronos2_zeroshot_preds.parquet`). Needs `benchmarks.py`
  to have run with the Chronos row accepted: one overall Chronos row in
  `benchmark_leaderboard.csv`, every prediction `model_mode == "zeroshot"`,
  one prediction per station and month, and as many predictions as that row's
  `n` (and `n_expected`). Otherwise the export refuses it: an error is logged,
  nothing is published (the export stages every file and moves them into
  `website/data/` only if all succeed, so the previous set stays in place),
  and the export **exits 1**, so `scripts/run_pipeline.sh` stops before its
  deploy message.
- `website/data/model_comparison.json` — one entry per model from
  `evaluation/outputs/benchmark_leaderboard.csv`.

The export also exits 1 **before writing any file** when
`benchmark_leaderboard.csv` is missing (unless `--allow-val-fallback` is
given), or when any station in `bart_stations.py` has no feature-store rows in
the averaging window or a non-finite average.

### 7. Deploy website

```bash
gcloud app deploy website/app.yaml --quiet
```

The live site (https://cs-163-final-project-tra-f1136.wl.r.appspot.com) is served
by App Engine Standard, configured via `website/app.yaml` — not Firebase
Hosting. `firebase deploy --only hosting` will succeed without error but
publishes to an unused Firebase Hosting site, leaving the real production URL
unchanged.

## Cloud ingest job

Everything above runs on a laptop and writes the committed store. A second path
runs in Google Cloud and writes the store the live API serves. Design:
[`cloud-ingestion-design.md`](cloud-ingestion-design.md). The two stores are
built by the same `merge_pipeline.build_feature_store`, but the cloud store is
built on Python 3.11 / pandas 2.2 against the bucket, so its bytes differ from the
committed store (sha256 `6cde32d4…`); the job's gate compares values instead.

| | |
|---|---|
| Bucket | `gs://cs-163-final-project-tra-f1136-transit-data` (us-west1) |
| Job | Cloud Run Job `transit-ingest` (us-west2), image `transit-ingest:<commit>`, entrypoint `python -m machine_learning_files.cloud_ingest` |
| Trigger | Cloud Scheduler `transit-ingest-daily`, 03:15 America/Los_Angeles |
| Settings | `configs/ingest.yaml` (bucket, `fetch_floor` 2026-01-01, `archive_lag_days` 7, the 20 pinned input sha256s, gate) |

### What one run does

1. **Fetch** closed months only (a month that ended at least 7 days ago), never before
   2026-01-01, so the hand-seeded 2019–2025 archives are never touched: Open-Meteo weather for
   the 7 locations in `configs/sources.yaml` and the Sharks home schedule, one object per source per year
   (`raw/weather/weather_all_stations_<start>_<end>.parquet`, `raw/events/events_<start>_<end>.parquet`). A newer
   same-year object replaces the older one, and an object is never replaced by one with fewer rows.
2. **Fingerprint** the `raw/` object names and generations. Equal to the served pointer's
   `input_fingerprint`: log `unchanged`, exit 0, publish nothing (`--force` overrides).
3. **Stage** the inputs into a temp directory and check the 20 pinned sha256s; a missing or different
   input fails the run before anything is built.
4. **Rebuild** with `bart_od_from_xlsx.build` and `merge_pipeline.build_feature_store()`, pointed at the temp
   directory. The committed store is never written.
5. **Gate.** All of these must pass, and `processed/runs/<run_id>/gate.json` records each (the first run's passed all 10):
   `validate_feature_store` (strict); unique `(station_id, timestamp)`; the same 50 stations in every month;
   every key of the committed store present with `ridership` exactly equal and covariates within `1e-9`;
   every month already served is still present; no month after the last closed month; SARIMA fitted on the candidate
   at `as_of=2025-06-30` scores 3.21% WAPE over the 50 stations.
6. **Publish.** Write `runs/<run_id>/feature_store.parquet` and `manifest.json` (git SHA, input generations and sha256s, store
   sha256, months, gate results), then `processed/serving.json` last, only if its generation is still the one read.
   A failed gate writes `gate.json` alone and leaves the pointer untouched.

Exit codes: `0` published or unchanged; `1` the build or the gate failed; `2` a fetch failed (the rest still ran);
`3` another execution published first.

### What this does and does not change

- The API's SARIMA reads only `ridership`. Weather and Sharks data the job fetches cannot change a forecast. A new BART
  workbook can: it adds months, so the store's last month (`/health` `store_last_month`, 2025-12-01 on 2026-10-28) moves
  and the default forecast starts the month after it.
- **BART is manual.** bart.gov answers automated requests with HTTP 403. Download the workbook in a browser, upload it,
  and run the job (or wait for the 03:15 run). The API picks the new store up within `STORE_TTL_SECONDS` (600) or on its next cold start:

```bash
gcloud storage cp Ridership_2026MM.xlsx gs://cs-163-final-project-tra-f1136-transit-data/raw/bart/
gcloud run jobs execute transit-ingest --region us-west2 --wait
```

  The gate rejects a store with a month later than the last closed month.
  No 2026 workbook has been uploaded yet, so this path has not run in the cloud (story S9-13).
- The leaderboard, `benchmarks.py`, `export_website_data.py` and the website read the committed
  `data/processed/feature_store.parquet` (through `feature_store_enriched.parquet`, which `feature_engineering.py` builds from it). Only the API reads the cloud store.

### Operating it

| Task | Command |
|---|---|
| Latest executions | `gcloud run jobs executions list --job transit-ingest --region us-west2` |
| Run the job now | `gcloud run jobs execute transit-ingest --region us-west2 --wait` |
| What is served | `curl <API>/health` → `store_source`, `store_run_id`, `store_sha256`, `store_last_month` |
| What the pointer says | `gcloud storage cat gs://…-transit-data/processed/serving.json` |
| Why a run did not publish | `gcloud storage cat gs://…-transit-data/processed/runs/<run_id>/gate.json` |
| Check everything | `API_URL=<API> scripts/smoke_cloud.sh` (read-only; 7 checks) |
| Roll back | Run directories are write-once and the bucket keeps noncurrent object versions for 30 days, so an earlier `processed/serving.json` can be restored (design §6). Not rehearsed |
| Test without GCP | `python -m machine_learning_files.cloud_ingest --bucket file:///<dir> --dry-run` |

A failed gate never publishes. If the API cannot read or verify the cloud store it logs a warning and serves
the store baked into its image, and `/health` then reports `store_source: "baked"`.

## One-command Pipeline

After setup, the full scripted path is:

```bash
bash scripts/run_pipeline.sh
```

This script runs `.venv311/bin/python` if that file exists and `python3` from `PATH` otherwise, so activate the Prerequisites venv first (a leftover `.venv311/` takes precedence over it). It assumes the required raw data/API credentials are available.

## Feature Store Schema

The minimum columns expected by validators and downstream scripts are:

| Column | Type | Notes |
| --- | --- | --- |
| `timestamp` | datetime | Current cadence is month start. |
| `station_id` | string | Two-letter BART workbook code of the origin (entry) station, e.g. `EM`, `12`; the station table is `machine_learning_files/bart_stations.py`. |
| `ridership` | numeric | Forecast target. |

Common optional columns include:

- Station and source: `station_name`, `agency_id`, `transit_mode`
- Weather: `temp_f`, `precip_mm`, `precip_in`, `is_raining`, `windspeed_mph`, `weather_code`, `cloud_cover_pct`, `humidity_pct`
- Events: `is_game_day`, `hours_to_event`, `is_sharks_game`, `game_start_hour`, `is_playoff`
- Calendar: `hour_of_day`, `day_of_week`, `month`, `week_of_year`, `is_weekend`, `is_holiday`
- Engineered features: lags, rolling means/stds, cyclic encodings, precipitation intensity, event windows, and station static features

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `No BART OD files found` | Raw BART parquet files are missing. | bart.gov blocks automated downloads (HTTP 403): download the Ridership workbooks by hand and run `python machine_learning_files/bart_od_from_xlsx.py --zips <zips>` (see `data/MANIFEST.md`). `bart_od_from_csv.py` output is rejected by `merge_pipeline.py`. |
| `Feature store not found` | Merge pipeline has not run. | Run `python machine_learning_files/merge_pipeline.py`. |
| `feature_store_enriched.parquet` missing | Feature engineering has not run. | Run `python Processing/feature_engineering.py`. |
| Validation flags missing windows | Split cadence or source coverage changed. | Confirm `configs/model.yaml` frequency and inspect source coverage by station. |
| Chronos fails to load on `mps` | Machine is not Apple Silicon or MPS is unavailable. | Set `chronos2.device` to `cuda` or `cpu` in `configs/model.yaml`. |
| Website shows stale values | `website/data/*.json` was not regenerated. | Run `scripts/export_website_data.py` before deploy. |
