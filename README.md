# Bay Area Transit Demand Forecasting

CS163 Data Science Senior Project - Dhruv Shah

**🌐 Website (App Engine):** https://cs-163-final-project-tra-f1136.wl.r.appspot.com

**🗺 Interactive Map Demo:** https://cs-163-final-project-tra-f1136.wl.r.appspot.com/transit-demo.html

**⚡ API Playground (interactive):** https://cs-163-final-project-tra-f1136.wl.r.appspot.com/api-demo.html

**🔌 FastAPI REST service:** https://transit-api-308878596074.us-west2.run.app/docs

---

Bay Area Transit Demand Forecasting is an end-to-end forecasting project for monthly BART station ridership. It builds a station-level feature store from public transit, weather, event, and calendar data; trains statistical and machine-learning forecasting models; evaluates them on chronological splits; and exports the results to a static website hosted on Google App Engine.

The current production path models BART origin-destination ridership at a month-start cadence. The codebase also includes ingestion and feature hooks for broader Bay Area transit feeds, event calendars, weather covariates, and road context so the project can expand beyond the current monthly BART target.

## Highlights

- Monthly station-level BART ridership forecasting with chronological train, validation, and test splits.
- External covariates from Open-Meteo weather and NHL/Ticketmaster event schedules.
- Baselines and model comparison across seasonal naive, SARIMA, Prophet, Chronos zero-shot, and AutoGluon time-series models.
- Data validation for required columns, missing windows, station coverage, and ridership anomalies.
- Static website export that turns feature stores and model outputs into JSON consumed by the frontend.
- FastAPI service that fits the leaderboard's best model (SARIMA) per request for station forecasts.

## Current Results

Produced by a single `models/baselines/benchmarks.py` run against BART's actual
monthly trip counts, scored on **Jul–Dec 2025** — a holdout not used for model
selection. Each row of `website/data/model_comparison.json` carries `source`
and `scored_split` so any figure can be traced to the run that made it.

| Model | MAE | WAPE | Coverage (nominal 80%) | Model's own band | Interval | Predictions |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| SARIMA airline (0,1,1)(0,1,1,12) | 3,086 | 3.21% | 96.7% | 96.7% | own band (no method passed validation) | 300 |
| Prophet (per-station) | 5,526 | 5.75% | 74.7% | 46.0% | split-conformal, fit on validation | 300 |
| Chronos-1 zero-shot (`chronos-t5-small`) | 9,321 | 9.70% | 72.7% | 51.0% | split-conformal, fit on validation | 300 |
| Seasonal naive | 10,333 | 10.75% | 94.3% | 94.3% | own band (no method passed validation) | 300 |

All models are scored on the same 300 station-months (50 stations × 6 forecast
steps). Reproduce with `bash scripts/run_pipeline.sh`.

Prophet and Chronos both sample, so `configs/model.yaml` seeds them
(`prophet.seed`, `chronos2.seed`). Unseeded, Chronos moved between 8.06% and
9.70% WAPE and Prophet's coverage between 44% and 46% across otherwise
identical runs — a figure nobody can reproduce is not a result. Two consecutive
runs of the table above are bit-identical.

**Point accuracy is sound; interval calibration is not.** No P10–P90 band
here is a dependable 80% interval:
- Prophet's and Chronos-1's own bands were far too narrow (46% and 51%
  coverage). The leaderboard now widens them with split-conformal quantiles
  fit on the validation split, which lifts them to 74.7% and 72.7%. That is
  still short of 80%. Chronos-1's misses all fall above P90.
- SARIMA's and seasonal naive's bands are too wide (96.7%, 94.3%). No
  calibration method passed validation for them, so they are published
  unchanged.
- Calibration never touches the point forecast: WAPE and MAE are identical
  with or without it.

Errors shift from one half-year to the next, and a quantile fit on one
half-year does not carry over to the next. The method comparison, the
validation numbers it was chosen on, and why the earlier Prophet MCMC
attempt failed are in [docs/interval-calibration.md](docs/interval-calibration.md).
The API and `website/data/forecasts.json` still serve the models' own bands.

**AutoETS (AutoGluon) carries no row, deliberately rather than silently.**
`autogluon.timeseries` requires Python <3.14 and cannot be installed here, and
no code path in this repository has ever emitted an AutoETS result. A
previously published figure of 14.2% WAPE was hand-entered, not computed.

Two caveats on the Chronos row:

- The pinned checkpoint is `amazon/chronos-t5-small`, which is Chronos-**1**.
  Earlier material called it "Chronos-2"; the leaderboard label is now derived
  from the checkpoint so it cannot drift again.
- It runs **univariate**. `ChronosPipeline.predict_df` takes no `future_df`, so
  the covariate path in `zero_shot.py` raises and every station falls back to
  no covariates. The 9.70% is a no-covariate result.

`benchmarks.py` also refuses to publish what it did not measure: if
`chronos-forecasting` is absent the predictor silently falls back to seasonal
naive, and the row is omitted rather than credited to Chronos. Any model whose
WAPE exceeds 100% — worse than forecasting a flat zero — is rejected outright.

Earlier published figures (Prophet 176.3%, SARIMA 22.5%, AutoETS 14.2%) are
superseded. `benchmarks.py` could not execute at all — it failed on import — so
no leaderboard existed and the website export silently scored a different split.
See `updates/` for the audit trail.

## Repository Map

```text
.
|-- configs/
|   |-- model.yaml                 # cadence, split dates, horizon, quantiles, training config
|   `-- sources.yaml               # source endpoints, station coords, API-key placeholders
|-- data/
|   |-- raw/                       # source downloads and parsed raw artifacts
|   `-- processed/                 # feature stores, splits, and validation reports
|-- machine_learning_files/
|   |-- fetch_511_transit.py       # 511 SF Bay transit feed ingestion
|   |-- fetch_bart_od.py           # BART OD ridership report ingestion
|   |-- bart_od_from_xlsx.py       # BART OD parquet builder from the hand-downloaded bart.gov Ridership_YYYYMM.xlsx workbooks (see data/MANIFEST.md)
|   |-- bart_od_from_csv.py        # Legacy fallback from bart_clean.csv; has no Total block, so merge_pipeline.py rejects its output
|   |-- fetch_weather_openmeteo.py # Open-Meteo station weather ingestion
|   |-- fetch_events.py            # NHL and Ticketmaster event ingestion
|   |-- merge_pipeline.py          # raw sources -> feature_store.parquet + splits
|   |-- zero_shot.py               # Chronos zero-shot forecasts
|   |-- api.py                     # FastAPI forecast service
|   `-- requirements.txt           # Python dependencies
|-- Processing/
|   |-- feature_engineering.py     # derived weather, event, time, lag, and station features
|   `-- ablation.py                # covariate and event-day analysis
|-- evaluation/
|   |-- validators.py              # data quality checks
|   `-- metrics.py                 # MAE, RMSE, MAPE, WAPE, MASE, sMAPE, coverage
|-- models/
|   |-- baselines/                 # SARIMA, Prophet, benchmark runner, PeMS fetcher
|   `-- chronos2/                  # AutoGluon training, prediction, and saved outputs
|-- scripts/
|   |-- run_pipeline.sh            # end-to-end local pipeline
|   `-- export_website_data.py     # model artifacts -> website/data/*.json
|-- transit_eda/                   # EDA data, notebooks, and generated figures
|-- website/                       # static React/Babel frontend served by Google App Engine
`-- docs/                          # architecture and data-pipeline runbooks
```

## Modeling Scope

The active configuration in `configs/model.yaml` uses:

| Setting | Value |
| --- | --- |
| Granularity | monthly |
| Pandas frequency | `MS` |
| Target | BART station-month ridership |
| Context window | 24 months |
| Forecast horizon | 6 months |
| Train period | January 2022 through December 2024 (36 months) |
| Validation period | January 2025 through June 2025 |
| Test period | July 2025 through December 2025 |
| Forecast quantiles | P10, P50, P90 |

The merge pipeline aggregates BART OD records to origin station-month totals, joins monthly weather summaries, computes monthly event indicators, adds calendar features, and writes chronological splits.

## Setup

**Prerequisites:** Python 3.11, Git. AutoGluon and Chronos require Python 3.11 — newer versions have dependency conflicts.

```bash
# Clone
git clone https://github.com/Dhruv-cs50/transit-demand-forecasting.git
cd transit-demand-forecasting

# Create virtual environment with Python 3.11
python3.11 -m venv .venv311
source .venv311/bin/activate        # Windows: .venv311\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r machine_learning_files/requirements.txt
```

**API keys** — before running source fetchers, edit `configs/sources.yaml`:

| Key | Required for | Notes |
| --- | --- | --- |
| `transit_511.api_key` | 511 SF Bay feed | Free at 511.org |
| `ticketmaster.api_key` | Event data | Free developer account |
| Open-Meteo | Weather data | No key required |
| PeMS | Road data | Manual download, CALTRANS account |

The pipeline works without these keys if you skip the corresponding fetchers — BART OD data (the core dataset) requires no API key and is fetched directly.

## Reproduce The Pipeline

Run the complete local workflow from the repository root:

```bash
bash scripts/run_pipeline.sh
```

That script performs:

1. Build `data/processed/feature_store.parquet` and chronological splits.
2. Build `data/processed/feature_store_enriched.parquet`, then regenerate the
   chronological splits from it (step 1's splits are pre-enrichment and get
   overwritten here so `finetune.py` trains on the full enriched schema).
3. Validate the enriched feature store.
4. Run Chronos zero-shot forecasts.
5. Run SARIMA and Prophet baselines.
6. Train the AutoGluon time-series ensemble.
7. Run model benchmarks.
8. Export JSON files for the website.

For faster iteration, run individual steps:

```bash
source .venv311/bin/activate

python machine_learning_files/merge_pipeline.py
python Processing/feature_engineering.py
python evaluation/validators.py --input data/processed/feature_store_enriched.parquet --mode lenient --freq MS

python machine_learning_files/zero_shot.py
python models/baselines/arima.py
python models/baselines/prophet_baseline.py
python models/chronos2/finetune.py --time-limit 1800
python models/baselines/benchmarks.py

python scripts/export_website_data.py --feature-store data/processed/feature_store_enriched.parquet
```

## Important Artifacts

| Path | Description |
| --- | --- |
| `data/processed/feature_store.parquet` | merged station-month feature store — committed, and the only data the API reads (see [`data/MANIFEST.md`](data/MANIFEST.md)) |
| `data/processed/feature_store_enriched.parquet` | feature-engineered model input |
| `data/processed/splits/train.parquet` | training split |
| `data/processed/splits/val.parquet` | validation split |
| `data/processed/splits/test.parquet` | held-out test split |
| `data/processed/validation_report.csv` | latest validation summary |
| `models/chronos2/outputs/zero_shot_forecasts_*.parquet` | Chronos forecast artifacts |
| `models/baselines/outputs/arima/arima_forecasts.parquet` | SARIMA forecast artifact |
| `models/baselines/outputs/prophet/prophet_forecasts.parquet` | Prophet forecast artifact |
| `website/data/*.json` | static frontend data generated from model and feature artifacts |

## Live Deployment

| Service | URL |
| --- | --- |
| Website (App Engine) | https://cs-163-final-project-tra-f1136.wl.r.appspot.com |
| Interactive Map Demo | https://cs-163-final-project-tra-f1136.wl.r.appspot.com/transit-demo.html |
| API Playground | https://cs-163-final-project-tra-f1136.wl.r.appspot.com/api-demo.html |
| API (Cloud Run) | https://transit-api-308878596074.us-west2.run.app |
| API Docs (Swagger) | https://transit-api-308878596074.us-west2.run.app/docs |

The Cloud Run revision live at that URL was not built from this code. Checked
2026-10-22 (Pacific): it titles itself "Bay Area Traffic Forecast API … Chronos-2
powered" and answers `/forecast` from a Chronos cache for Jan–Jun 2024 on the
pre-Sprint-2 target definition (EM p50 1.16–1.45M riders/month, against 326–390k
actual for those months in the current feature store). The [Forecast API](#forecast-api) section describes
what `Dockerfile.api` builds; the live service matches it only after a rebuild
and redeploy.

## Cloud Deployment

### Infrastructure Overview

| Component | GCP Service | Details |
| --- | --- | --- |
| Website | App Engine Standard (`python312`) | Static file handlers, `website/` directory, `website/app.yaml` |
| API | Cloud Run | Serverless container, us-west2, auto-scales 0→N |
| Container image | Artifact Registry | `us-west2-docker.pkg.dev/<PROJECT_ID>/transit-repo/transit-api:tag1` |
| Build pipeline | Cloud Build | `cloudbuild.yaml` — builds `Dockerfile.api` for `linux/amd64` |

### Docker Containers

Two Dockerfiles are provided:

**`Dockerfile.api`** (inference service — used in production):
- Base: `python:3.11-slim`
- Copies `machine_learning_files/api.py`, `models/baselines/arima.py`, `configs/model.yaml` and the committed `data/processed/feature_store.parquet` into the image, and installs `statsmodels` for SARIMA. No forecast cache, no `chronos-forecasting`: each `/forecast` fits SARIMA for the requested station (see [Forecast API](#forecast-api)).
- Builds from a clean clone — every file it copies is in git
- Exposes FastAPI on port `$PORT` (Cloud Run injects this env var)
- Build: `docker build -f Dockerfile.api -t transit-api .`

**`Dockerfile`** (full pipeline):
- Runs the complete ingestion → feature engineering → training → export pipeline
- Used for reproducing results locally or in batch compute environments

### Cloud Run Deployment

The API image is built and pushed via Cloud Build, then deployed to Cloud Run:

```bash
# Build and push via Cloud Build
gcloud builds submit --config=cloudbuild.yaml .

# Deploy to Cloud Run (manual after build)
gcloud run deploy transit-api \
  --image us-west2-docker.pkg.dev/<PROJECT_ID>/transit-repo/transit-api:tag1 \
  --platform managed \
  --region us-west2 \
  --allow-unauthenticated \
  --port 8080
```

### Cloud Data Storage

| Data | Location | Notes |
| --- | --- | --- |
| Feature store parquet | `data/processed/feature_store.parquet` (committed) | `Dockerfile.api` bakes it in; `api.py`'s `get_feature_store()` reads it at serve time. The enriched store is not in the image — only the offline pipeline (benchmarks, training, validation, website export) reads it |
| Docker images | Artifact Registry (`us-west2`) | Versioned container images for the API |
| Website assets | App Engine Standard | HTML/CSS/JSX/JSON, served via static file handlers |
| Forecasts | Not stored | Computed per request from the feature store; the image holds no forecast cache |

### System Design and Scalability

```mermaid
flowchart LR
    subgraph Pipeline["Batch Pipeline (local / CI)"]
        RAW[Raw Data\nBART · Weather · Events]
        FS[feature_store.parquet\n+ feature_store_enriched.parquet]
        FC[Forecast\n*.parquet]
        JSON[website/data\n*.json]
        RAW --> FS --> FC --> JSON
    end

    subgraph GCP["Google Cloud Platform"]
        AR[Artifact Registry\nDocker image]
        CR[Cloud Run\ntransit-api]
        GAE[App Engine\nwebsite]
        FS -->|feature_store.parquet baked in| AR
        AR --> CR
        JSON -->|static files| GAE
    end

    USER([Browser]) -->|HTTPS| GAE
    GAE -->|POST /forecast| CR
```

**Scalability:**
- **App Engine Standard** — auto-scales instances, zero when idle, no server management
- **Cloud Run** — scales 0→N replicas per concurrency, each replica stateless
- **Per-request SARIMA** — each `/forecast` is one small model fit (48 monthly points). In a local container one forecast took 0.03–0.6 s and the startup `statsmodels` import 1–17 s, on a laptop under heavy load from other work; neither has been measured on Cloud Run. The import happens at startup, so it lands on the cold start rather than the first request. Nothing is cached between requests

Full architecture diagram: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## Website

The frontend is a static site in `website/`. It uses CDN-loaded React and Babel — no Node build step needed. The site reads generated JSON files from `website/data/`.

Live URL: **https://cs-163-final-project-tra-f1136.wl.r.appspot.com**

Refresh website data:

```bash
python scripts/export_website_data.py --feature-store data/processed/feature_store_enriched.parquet
```

Deploy with App Engine:

```bash
gcloud app deploy website/app.yaml --quiet
```

## Forecast API

Live URL: **https://transit-api-308878596074.us-west2.run.app**

(See the note under [Live Deployment](#live-deployment): that URL still runs an
older image.)

The API serves **SARIMA airline (0,1,1)(0,1,1,12)**, the leaderboard's best
model. Each `/forecast` fits it for the requested station on demand with the
same functions `benchmarks.py` scores (`fit_station` / `predict_station` in
`models/baselines/arima.py`):

- **History:** months from `data.train_start` (2022-01) whose start is `<= as_of`.
  Without `as_of`, that is Jan 2022 through Dec 2025 (the store's 2019 months
  are never used), so the forecast covers Jan–Jun 2026.
- **What the 3.21% means here:** it is the holdout score of this spec trained
  through Jun 2025 (`"as_of": "2025-06-30"` reproduces those forecasts exactly).
  The default forecast, refit through Dec 2025, has not been scored — its months
  have no actuals yet.
- **Intervals:** P10/P90 are SARIMA's 80% interval, which covered 96.7% of
  holdout actuals — over-wide; don't read it as a calibrated 80% band.
- **`horizon_hours` counts months.** The name predates the monthly target; at
  most 6 rows come back.
- **Errors:** unknown station → `404`; malformed `as_of`, or one that leaves
  fewer than 24 months of history → `400`.

Code: `machine_learning_files/api.py`. Tests (`requirements.txt` lacks `pytest` and `httpx`):

```bash
pip install fastapi==0.115.0 pydantic==2.7.0 pandas==2.2.0 pyarrow==16.0.0 numpy==1.26.4 PyYAML==6.0.1 scipy==1.14.1 statsmodels==0.14.4 httpx pytest
python -m pytest tests/
```

Start locally (the feature store is committed, so no pipeline run is needed):

```bash
uvicorn machine_learning_files.api:app --reload --port 8000
```

Endpoints:

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Service health, served model, feature-store load status |
| `GET` | `/stations` | List of forecastable station IDs |
| `POST` | `/forecast` | Request P10/P50/P90 quantile forecasts |
| `GET` | `/docs` | Swagger UI (interactive API explorer) |

**Input** (`POST /forecast`; `as_of` is optional):
```json
{ "station_id": "EM", "horizon_hours": 6 }
```

**Output** (`POST /forecast`), from an image built from `Dockerfile.api` — first
of six rows shown, values rounded here only:
```json
{
  "station_id": "EM",
  "horizon_hours": 6,
  "generated_at": "2026-10-23T03:31:46.115150Z",
  "forecasts": [
    { "timestamp": "2026-01-01 00:00:00", "p10": 386519.9, "p50": 415136.9, "p90": 443753.8 }
  ]
}
```


## Documentation

Additional project documentation:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - system flow, components, and artifact contracts.
- [docs/DATA_PIPELINE.md](docs/DATA_PIPELINE.md) - source data, rebuild steps, schema notes, and troubleshooting.
- [machine_learning_files/README.md](machine_learning_files/README.md) - ML-script guide for ingestion, forecasting, and API usage.

## Known Limitations

- The active modeled target is monthly BART OD ridership. Some files describe future higher-frequency transit support, but the current reliable pipeline is monthly.
- Weather and event data are currently aggregated to the monthly modeling cadence.
- `scripts/run_pipeline.sh` assumes `.venv311/bin/python` exists.
- Chronos (benchmarks only; the API does not run it) defaults to `cpu` in `configs/model.yaml`; change it to `mps` on Apple Silicon or `cuda` on a GPU machine for faster inference.
- Some source fetchers require external credentials or manual data access.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Feature store not found` | Run `python machine_learning_files/merge_pipeline.py`. |
| `feature_store_enriched.parquet` missing | Run `python Processing/feature_engineering.py`. |
| `No BART OD files found` | bart.gov answers automated requests with HTTP 403, so `fetch_bart_od.py` cannot fill `data/raw/transit/bart/`. Download the Ridership workbooks by hand and run `python machine_learning_files/bart_od_from_xlsx.py --zips <zips>` (see `data/MANIFEST.md`). Do not use `bart_od_from_csv.py` for the pipeline: `merge_pipeline.py` rejects the months it builds. |
| AutoGluon import/install failures | Recreate the environment with Python 3.11. |
| Chronos device errors | Change `chronos2.device` in `configs/model.yaml`. |
| Website shows stale data | Re-run `scripts/export_website_data.py` before deploying. |
