# Architecture

This project is organized as a batch forecasting pipeline with optional API serving and a static website export.

## System Flow

```text
source APIs and reports
        |
        v
raw parquet / csv files in data/raw/
        |
        v
feature store construction
        |
        v
feature engineering and validation
        |
        v
forecast models and benchmarks
        |
        +--> FastAPI forecast service
        |
        +--> website/data JSON export
```

## Main Components

| Component | Location | Responsibility |
| --- | --- | --- |
| Source configuration | `configs/sources.yaml` | API endpoints, station coordinates, venue IDs, and key placeholders. |
| Model configuration | `configs/model.yaml` | Granularity, split dates, context length, horizon, quantiles, and training settings. |
| Ingestion | `machine_learning_files/fetch_*.py`, `models/baselines/fetch_pems_roads.py` | Download or parse source data into `data/raw/`. |
| Feature store | `machine_learning_files/merge_pipeline.py` | Build `data/processed/feature_store.parquet` and chronological splits. |
| Feature engineering | `Processing/feature_engineering.py` | Add derived calendar, weather, event, lag, rolling, and station covariates. |
| Validation | `evaluation/validators.py` | Check schema, missing windows, station coverage, and ridership anomalies. |
| Forecasting | `machine_learning_files/zero_shot.py`, `models/chronos2/`, `models/baselines/` | Produce forecasts and model comparison outputs. |
| API | `machine_learning_files/api.py` | Serve cached or live forecasts through FastAPI. |
| Website export | `scripts/export_website_data.py` | Convert feature and model artifacts into `website/data/*.json`. |
| Website | `website/` | Static frontend deployed with Firebase Hosting. |

## Artifact Contracts

### Feature Store

`data/processed/feature_store.parquet` is the central table. The minimum required columns are:

| Column | Meaning |
| --- | --- |
| `timestamp` | modeled time period. Current cadence is month start (`MS`). |
| `station_id` | source station code, currently BART OD origin code. |
| `station_name` | human-readable station name when available. |
| `ridership` | target value to forecast. |
| `agency_id` | source agency code. Current BART value is `BA`. |
| `transit_mode` | mode label such as `rail`. |

Additional weather, event, and calendar columns are used when present. Feature engineering writes `data/processed/feature_store_enriched.parquet`.

### Splits

`machine_learning_files/merge_pipeline.py` creates chronological splits in `data/processed/splits/`:

- `train.parquet`: `train_start <= timestamp <= train_end`
- `val.parquet`: `train_end < timestamp <= val_end`
- `test.parquet`: `timestamp > val_end`

The split boundaries are configured in `configs/model.yaml`.

### Forecasts

Zero-shot forecasts are saved under `models/chronos2/outputs/` as timestamped parquet files. Baseline forecasts are saved under `models/baselines/outputs/`. The website export script reads the newest available outputs and writes:

- `website/data/stations_ridership.json`
- `website/data/stations_meta.json`
- `website/data/ridership_actuals.json`
- `website/data/forecasts.json`
- `website/data/model_comparison.json`

## Serving Modes

### Batch-first

The preferred workflow is to run the batch pipeline, generate forecast parquet files, export website JSON, and deploy the static website. This avoids loading Chronos during normal frontend usage.

### API fallback

The FastAPI app reads cached forecast parquet files first. If a requested station is not available in cached output, it loads the feature store and Chronos pipeline for live inference.

## Design Assumptions

- The current reliable modeling target is monthly BART station ridership from BART OD reports.
- Weather and event data are aggregated to the modeled monthly cadence in the active feature-store build.
- Higher-frequency transit and event features remain in the codebase for future extension.
- Chronological splits are used to avoid time leakage.
- Website data is generated from committed or locally produced artifacts rather than querying the API at runtime.
