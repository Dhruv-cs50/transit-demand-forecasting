# Architecture

## System Diagram

```mermaid
flowchart TD
    subgraph SRC["Data Sources"]
        S1[BART OD Reports\nbartlink.com]
        S2[Open-Meteo\nWeather API]
        S3[NHL / Ticketmaster\nEvents API]
        S4[511 SF Bay\nTransit Feed]
    end

    subgraph ING["Ingestion — machine_learning_files/"]
        I1[fetch_bart_od.py]
        I2[fetch_weather_openmeteo.py]
        I3[fetch_events.py]
        I4[fetch_511_transit.py]
    end

    subgraph PROC["Processing"]
        P1[merge_pipeline.py\nfeature_store.parquet]
        P2[feature_engineering.py\nfeature_store_enriched.parquet]
        P3[validators.py\nvalidation_report.csv]
    end

    subgraph TRAIN["Model Training"]
        M1[zero_shot.py\nChronos-2 zero-shot]
        M2[models/chronos2/finetune.py\nAutoGluon ensemble]
        M3[models/baselines/arima.py\nSARIMA]
        M4[models/baselines/prophet_baseline.py\nProphet]
    end

    subgraph OUT["Artifacts"]
        O1[models/chronos2/outputs/\n*.parquet forecasts]
        O2[website/data/\n*.json exports]
    end

    subgraph CLOUD["Google Cloud Platform"]
        subgraph BUILD["Cloud Build"]
            CB[cloudbuild.yaml\nDockerfile.api → image]
        end
        subgraph AR["Artifact Registry"]
            AR1[transit-repo/transit-api:tag1]
        end
        subgraph CR["Cloud Run — inference service"]
            API[machine_learning_files/api.py\nFastAPI  /health /stations /forecast]
        end
        subgraph GAE["App Engine Standard — website"]
            WEB[website/\nReact + Babel static site]
        end
        subgraph BQ["BigQuery — cloud database"]
            BQT[transit_data.feature_store\n1,800 rows · 50 stations]
        end
    end

    USER[Browser]

    S1 --> I1
    S2 --> I2
    S3 --> I3
    S4 --> I4

    I1 & I2 & I3 & I4 --> P1
    P1 --> P2
    P2 --> P3
    P2 --> M1 & M2 & M3 & M4
    M1 & M2 & M3 & M4 --> O1
    O1 --> O2

    P2 -->|bq load| BQT

    O2 -->|static JSON| WEB
    O1 -->|COPY into image| CB
    CB --> AR1
    AR1 --> CR
    CR --> API

    USER -->|HTTPS| WEB
    WEB -->|POST /forecast\nGET /stations| API
    API -->|parquet lookup| O1
```

## Component Responsibilities

| Component | Location | Responsibility |
| --- | --- | --- |
| Source configuration | `configs/sources.yaml` | API endpoints, station coordinates, venue IDs, key placeholders |
| Model configuration | `configs/model.yaml` | Granularity, split dates, context length, horizon, quantiles |
| Ingestion | `machine_learning_files/fetch_*.py` | Download source data into `data/raw/` |
| Feature store | `machine_learning_files/merge_pipeline.py` | Build `data/processed/feature_store.parquet` and chronological splits |
| Feature engineering | `Processing/feature_engineering.py` | Add calendar, weather, event, lag, rolling, station covariates |
| Validation | `evaluation/validators.py` | Schema checks, missing windows, coverage, anomaly detection |
| Forecasting | `machine_learning_files/zero_shot.py`, `models/chronos2/`, `models/baselines/` | Produce forecast parquet files |
| Website export | `scripts/export_website_data.py` | Convert model artifacts into `website/data/*.json` |
| API service | `machine_learning_files/api.py` | FastAPI: cached parquet lookup → live Chronos inference fallback |
| Website | `website/` | React/Babel static frontend deployed on App Engine Standard |
| Docker (pipeline) | `Dockerfile` | Reproducible full pipeline container |
| Docker (serving) | `Dockerfile.api` | Lightweight API image baked with pre-computed forecasts |
| Cloud build | `cloudbuild.yaml` | Build `Dockerfile.api` for `linux/amd64`, push to Artifact Registry |

## Data Flow

```
BART OD reports ──► fetch_bart_od.py ──► data/raw/transit/bart/
Open-Meteo API  ──► fetch_weather.py ──► data/raw/weather/
Events APIs     ──► fetch_events.py  ──► data/raw/events/
                           │
                           ▼
                  merge_pipeline.py
                           │
                  feature_store.parquet (station × month × covariates)
                           │
                  feature_engineering.py
                           │
                  feature_store_enriched.parquet ──► BigQuery
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         zero_shot     finetune.py   arima.py / prophet.py
              │            │            │
              └────────────┴────────────┘
                           │
                  models/*/outputs/*.parquet
                           │
                  ┌────────┴────────┐
                  ▼                 ▼
         Dockerfile.api      export_website_data.py
                  │                 │
          Cloud Run API      website/data/*.json
                  │                 │
                  └────────┬────────┘
                           ▼
                    App Engine Website
                           │
                        Browser
```

## Artifact Contracts

### Feature Store Schema (minimum required columns)

| Column | Type | Meaning |
| --- | --- | --- |
| `timestamp` | datetime | Month start (`MS` cadence) |
| `station_id` | string | BART OD origin station code |
| `station_name` | string | Human-readable station name |
| `ridership` | int | Monthly boardings (target variable) |
| `agency_id` | string | `BA` for BART |
| `transit_mode` | string | `rail` |

### API Endpoints

| Method | Path | Input | Output |
| --- | --- | --- | --- |
| GET | `/health` | — | `{status, model_loaded, store_loaded}` |
| GET | `/stations` | — | `[{station_id, station_name}]` |
| POST | `/forecast` | `{station_id, horizon_hours}` | `{station_id, forecasts: [{timestamp, p10, p50, p90}]}` |

### Chronological Splits

| Split | Period |
| --- | --- |
| Train | Jan 2021 – Dec 2022 |
| Validation | Jan 2023 – Jun 2023 |
| Test | Jul 2023 onward |

## Scalability

| Service | Scaling behaviour |
| --- | --- |
| App Engine Standard | Auto-scales instances; scales to zero when idle |
| Cloud Run | Scales 0→N replicas per request concurrency; stateless |
| BigQuery | Serverless; scales automatically for analytical queries |
| Pre-computed cache | Parquet lookup in Cloud Run — sub-100 ms, no model load |
| Live inference fallback | Chronos-T5-Small on CPU; upgrade path: GPU Cloud Run or Vertex AI |
