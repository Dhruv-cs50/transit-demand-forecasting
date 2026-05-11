# Bay Area Transit Demand Forecasting

CS163 Data Science Senior Project - Dhruv Shah

Bay Area Transit Demand Forecasting is an end-to-end forecasting project for monthly BART station ridership. It builds a station-level feature store from public transit, weather, event, and calendar data; trains statistical and machine-learning forecasting models; evaluates them on chronological splits; and exports the results to a static Firebase-hosted website.

The current production path models BART origin-destination ridership at a month-start cadence. The codebase also includes ingestion and feature hooks for broader Bay Area transit feeds, event calendars, weather covariates, and road context so the project can expand beyond the current monthly BART target.

## Highlights

- Monthly station-level BART ridership forecasting with chronological train, validation, and test splits.
- External covariates from Open-Meteo weather and NHL/Ticketmaster event schedules.
- Baselines and model comparison across seasonal naive, SARIMA, Prophet, Chronos zero-shot, and AutoGluon time-series models.
- Data validation for required columns, missing windows, station coverage, and ridership anomalies.
- Static website export that turns feature stores and model outputs into JSON consumed by the frontend.
- FastAPI service for station forecasts with cached-output and live-inference paths.

## Current Results

The checked-in website comparison data currently reports:

| Model | MAE | WAPE | Predictions |
| --- | ---: | ---: | ---: |
| AutoETS (AutoGluon) | 46,783 | 14.2% | 300 |
| SARIMA | 73,955 | 22.5% | 300 |
| Prophet | 580,181 | 176.3% | 300 |

These values come from `website/data/model_comparison.json`. Re-run the pipeline and website export to refresh them after changing source data, features, or models.

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
|-- website/                       # static React/Babel frontend served by Firebase Hosting
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
| Train period | January 2021 through December 2022 |
| Validation period | January 2023 through June 2023 |
| Test period | July 2023 onward |
| Forecast quantiles | P10, P50, P90 |

The merge pipeline aggregates BART OD records to origin station-month totals, joins monthly weather summaries, computes monthly event indicators, adds calendar features, and writes chronological splits.

## Setup

Use Python 3.11 for the full ML stack. AutoGluon and Chronos dependencies are more stable on Python 3.11 than newer Python releases.

```bash
python3.11 -m venv .venv311
source .venv311/bin/activate
pip install --upgrade pip
pip install -r machine_learning_files/requirements.txt
```

Before running source fetchers, update `configs/sources.yaml` where credentials are required:

- `transit_511.api_key` for 511 SF Bay.
- `ticketmaster.api_key` for Ticketmaster Discovery API.
- Open-Meteo does not require an API key.
- PeMS usually requires manual authenticated downloads.

## Reproduce The Pipeline

Run the complete local workflow from the repository root:

```bash
bash scripts/run_pipeline.sh
```

That script performs:

1. Build `data/processed/feature_store.parquet` and chronological splits.
2. Build `data/processed/feature_store_enriched.parquet`.
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
| `data/processed/feature_store.parquet` | merged station-month feature store |
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
| Website | https://cs-163-final-project-tra-f1136.web.app |
| API | https://transit-api-308878596074.us-west2.run.app |
| API Playground | https://cs-163-final-project-tra-f1136.web.app/api-demo.html |
| API Docs (Swagger) | https://transit-api-308878596074.us-west2.run.app/docs |

## Cloud Deployment

### Infrastructure Overview

| Component | GCP Service | Details |
| --- | --- | --- |
| Website | Firebase Hosting | CDN-served static site, `website/` directory |
| API | Cloud Run | Serverless container, us-west2, auto-scales 0→N |
| Container image | Artifact Registry | `us-west2-docker.pkg.dev/<PROJECT_ID>/transit-repo/transit-api:tag1` |
| Build pipeline | Cloud Build | `cloudbuild.yaml` — builds `Dockerfile.api` for `linux/amd64` |

### Docker Containers

Two Dockerfiles are provided:

**`Dockerfile.api`** (inference service — used in production):
- Base: `python:3.11-slim`
- Copies pre-computed parquet forecasts from `models/chronos2/outputs/` into the image (fast path, no inference at startup)
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
| Docker images | Artifact Registry (`us-west2`) | Versioned container images for the API |
| Website assets | Firebase Hosting (global CDN) | HTML/CSS/JSX/JSON, edge-cached |
| Pre-computed forecasts | Baked into Docker image | `models/chronos2/outputs/*.parquet` copied at build time |
| Feature store | `data/processed/` | Parquet files for training and website export |

### System Design and Scalability

```
[Client Browser]
      |
      v
[Firebase Hosting CDN] ──── static HTML/JSX/JSON ────> rendered website
      |
      | POST /forecast, GET /stations
      v
[Cloud Run: transit-api] ──── reads ────> [baked-in parquet cache]
      |
      | cache miss (rare)
      v
[Chronos-2 live inference]
```

**Scalability properties:**
- **Cloud Run** scales to zero when idle and auto-scales horizontally under load; each instance is stateless
- **Firebase Hosting** serves assets from Google's global CDN with no origin servers for the website itself
- **Pre-computed parquet cache** means most API requests are parquet lookups with sub-100ms latency and no model load
- **Live inference path** (cache miss) runs Chronos-T5-Small on CPU; for higher throughput, swap Cloud Run CPU for GPU-backed instances or Vertex AI Prediction

## Website

The frontend is a static site in `website/`. It uses CDN-loaded React and Babel — no Node build step needed. The site reads generated JSON files from `website/data/`.

Live URL: **https://cs-163-final-project-tra-f1136.web.app**

Refresh website data:

```bash
python scripts/export_website_data.py --feature-store data/processed/feature_store_enriched.parquet
```

Deploy with Firebase Hosting:

```bash
firebase deploy --only hosting
```

## Forecast API

Live URL: **https://transit-api-308878596074.us-west2.run.app**

Model code: `machine_learning_files/api.py` (FastAPI service), `models/chronos2/finetune.py` (AutoGluon/Chronos training).

Start locally after building the feature store:

```bash
uvicorn machine_learning_files.api:app --reload --port 8000
```

Endpoints:

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Service health, model/store load status |
| `GET` | `/stations` | List of forecastable station IDs and names |
| `POST` | `/forecast` | Request P10/P50/P90 quantile forecasts |
| `GET` | `/docs` | Swagger UI (interactive API explorer) |

**Input** (`POST /forecast`):
```json
{ "station_id": "EM", "horizon_hours": 6 }
```

**Output** (`POST /forecast`):
```json
{
  "station_id": "EM",
  "station_name": "Embarcadero",
  "forecasts": [
    { "date": "2024-01-01", "p10": 42000, "p50": 58000, "p90": 74000 }
  ],
  "source": "cache"
}
```

The API serves from cached parquet in `models/chronos2/outputs/`. Cache miss triggers live Chronos-2 inference.

## Documentation

Additional project documentation:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - system flow, components, and artifact contracts.
- [docs/DATA_PIPELINE.md](docs/DATA_PIPELINE.md) - source data, rebuild steps, schema notes, and troubleshooting.
- [machine_learning_files/README.md](machine_learning_files/README.md) - ML-script guide for ingestion, forecasting, and API usage.

## Known Limitations

- The active modeled target is monthly BART OD ridership. Some files describe future higher-frequency transit support, but the current reliable pipeline is monthly.
- Weather and event data are currently aggregated to the monthly modeling cadence.
- `scripts/run_pipeline.sh` assumes `.venv311/bin/python` exists.
- Chronos defaults to `mps` in `configs/model.yaml`; change it to `cuda` or `cpu` on non-Apple-Silicon machines.
- Some source fetchers require external credentials or manual data access.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Feature store not found` | Run `python machine_learning_files/merge_pipeline.py`. |
| `feature_store_enriched.parquet` missing | Run `python Processing/feature_engineering.py`. |
| `No BART OD files found` | Run `python machine_learning_files/fetch_bart_od.py` or place BART parquet files in `data/raw/transit/bart/`. |
| AutoGluon import/install failures | Recreate the environment with Python 3.11. |
| Chronos device errors | Change `chronos2.device` in `configs/model.yaml`. |
| Website shows stale data | Re-run `scripts/export_website_data.py` before deploying. |
