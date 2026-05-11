# Bay Area Transit Demand Forecasting

CS163 Data Science Senior Project - Dhruv Shah

This project forecasts Bay Area transit ridership with monthly BART station ridership as the current modeled target. The pipeline combines historical ridership, weather, event schedules, calendar features, baseline models, AutoGluon time-series models, and a static website that visualizes ridership and forecast outputs.

## What This Repository Contains

- Data ingestion scripts for BART, 511 transit, Open-Meteo weather, NHL/Ticketmaster events, and Caltrans PeMS road context.
- A feature-store pipeline that merges raw sources into station-month records.
- Feature engineering for calendar, weather, event, lag, rolling, and station-level covariates.
- Forecasting models: Chronos zero-shot, AutoGluon time-series training, SARIMA, Prophet, and benchmark comparison.
- Data validation and evaluation utilities.
- A static Firebase-hosted website backed by JSON files exported from the model outputs.

## Repository Layout

```text
.
|-- configs/
|   |-- model.yaml                 # model horizon, splits, quantiles, and training settings
|   `-- sources.yaml               # external source URLs, station coords, and API-key placeholders
|-- data/
|   |-- raw/                       # source downloads, not all files are committed
|   `-- processed/                 # feature_store.parquet and chronological splits
|-- machine_learning_files/
|   |-- fetch_511_transit.py       # 511 SF Bay transit feeds
|   |-- fetch_bart_od.py           # BART origin-destination ridership reports
|   |-- fetch_weather_openmeteo.py # Open-Meteo station weather
|   |-- fetch_events.py            # NHL Sharks and Ticketmaster events
|   |-- merge_pipeline.py          # raw data -> feature_store.parquet + splits
|   |-- zero_shot.py               # Chronos zero-shot forecasts
|   |-- api.py                     # FastAPI forecast service
|   `-- requirements.txt           # Python dependencies
|-- Processing/
|   |-- feature_engineering.py     # model-ready derived features
|   `-- ablation.py                # covariate and event-day analysis
|-- evaluation/
|   |-- validators.py              # schema, gap, and anomaly checks
|   `-- metrics.py                 # MAE, RMSE, MAPE, WAPE, MASE, sMAPE
|-- models/
|   |-- baselines/                 # SARIMA, Prophet, benchmark runner, PeMS fetcher
|   `-- chronos2/                  # AutoGluon training, prediction, and saved outputs
|-- scripts/
|   |-- run_pipeline.sh            # end-to-end local pipeline
|   `-- export_website_data.py     # feature/model outputs -> website/data/*.json
|-- transit_eda/                   # exploratory data and generated figures
|-- website/                       # static frontend served by Firebase Hosting
`-- docs/                          # architecture, data contracts, and runbook notes
```

## Current Modeling Scope

The active pipeline uses BART origin-destination ridership as monthly station-level data. `configs/model.yaml` sets a month-start cadence (`MS`), 24 months of context, and a 6-month forecast horizon. Some scripts retain support for higher-frequency transit, weather, and event data so the project can expand beyond the current BART monthly setup.

## Setup

Use Python 3.11 for the full ML stack. AutoGluon and Chronos dependencies are heavier than the website export utilities, so a dedicated environment is recommended.

```bash
python3.11 -m venv .venv311
source .venv311/bin/activate
pip install --upgrade pip
pip install -r machine_learning_files/requirements.txt
```

Fill in API keys in `configs/sources.yaml` when you need sources that require credentials:

- `transit_511.api_key` for 511 SF Bay.
- `ticketmaster.api_key` for Ticketmaster Discovery API.
- Open-Meteo does not require a key.
- PeMS typically requires a manual authenticated download flow.

## Quickstart

Run the complete local pipeline from the repository root:

```bash
bash scripts/run_pipeline.sh
```

The script rebuilds the feature store, adds engineered features, validates data, runs zero-shot and baseline models, trains the AutoGluon models, benchmarks results, and exports website JSON files.

For a smaller iterative workflow:

```bash
source .venv311/bin/activate

# Build the monthly feature store and train/val/test splits.
python machine_learning_files/merge_pipeline.py

# Add model-ready features.
python Processing/feature_engineering.py

# Validate the enriched feature store.
python evaluation/validators.py --input data/processed/feature_store_enriched.parquet --mode lenient --freq MS

# Run forecasts and baselines.
python machine_learning_files/zero_shot.py
python models/baselines/arima.py
python models/baselines/prophet_baseline.py
python models/chronos2/finetune.py --time-limit 1800
python models/baselines/benchmarks.py

# Refresh frontend data.
python scripts/export_website_data.py --feature-store data/processed/feature_store_enriched.parquet
```

## Key Outputs

| Path | Description |
| --- | --- |
| `data/processed/feature_store.parquet` | merged station-month feature store |
| `data/processed/feature_store_enriched.parquet` | feature-engineered model input |
| `data/processed/splits/{train,val,test}.parquet` | chronological splits from `configs/model.yaml` |
| `models/chronos2/outputs/zero_shot_forecasts_*.parquet` | Chronos zero-shot forecast artifacts |
| `models/baselines/outputs/` | SARIMA and Prophet forecast artifacts |
| `evaluation/outputs/benchmark_leaderboard.csv` | model comparison table used by the website export |
| `website/data/*.json` | static data files consumed by the frontend |

## Serve The API

After a feature store exists, start the FastAPI service:

```bash
uvicorn machine_learning_files.api:app --reload --port 8000
```

Useful endpoints:

- `GET /health`
- `GET /stations`
- `POST /forecast` with JSON such as `{"station_id": "EM", "horizon_hours": 6}`
- `GET /docs` for the interactive OpenAPI UI

The API first tries to serve from the newest precomputed `models/chronos2/outputs/zero_shot_forecasts_*.parquet`. If no cached forecast exists for a station, it falls back to live Chronos inference.

## Website

The website is static HTML/CSS/JS in `website/`. It reads JSON from `website/data/`, which is generated by:

```bash
python scripts/export_website_data.py --feature-store data/processed/feature_store_enriched.parquet
```

Firebase Hosting is configured in `firebase.json` with `website/` as the public directory:

```bash
firebase deploy --only hosting
```

## Documentation

More detailed project notes live in:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - system flow, modules, and artifact contracts.
- [docs/DATA_PIPELINE.md](docs/DATA_PIPELINE.md) - source data, feature store schema, splits, and troubleshooting.
- [machine_learning_files/README.md](machine_learning_files/README.md) - focused guide for ingestion, model, API, and ML scripts.

## Common Issues

- `Feature store not found`: run `python machine_learning_files/merge_pipeline.py` first.
- `feature_store_enriched.parquet` missing: run `python Processing/feature_engineering.py`.
- AutoGluon install or import errors: use Python 3.11 and reinstall `machine_learning_files/requirements.txt`.
- API keys still set to placeholders: update `configs/sources.yaml` before running credentialed fetchers.
- Firebase deploy shows stale data: regenerate `website/data/*.json` before deploying.
