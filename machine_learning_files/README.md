# Machine Learning Files

This folder contains the ingestion, feature-store, zero-shot forecasting, API, and dependency files for the Bay Area transit demand forecasting pipeline. Run commands from the repository root so relative paths such as `data/raw/`, `data/processed/`, and `configs/` resolve correctly.

## Files

| File | Purpose | Main inputs | Main outputs |
| --- | --- | --- | --- |
| `fetch_511_transit.py` | Pull 511 SF Bay transit feed data. | `configs/sources.yaml` | `data/raw/transit/` |
| `fetch_bart_od.py` | Download and parse BART origin-destination ridership reports. | BART ridership reports | `data/raw/transit/bart/bart_od_*.parquet` |
| `fetch_weather_openmeteo.py` | Fetch station weather from Open-Meteo. | `configs/sources.yaml` station coordinates | `data/raw/weather/weather_all_stations_*.parquet` |
| `fetch_events.py` | Fetch Sharks and Ticketmaster event calendars. | NHL API, Ticketmaster API | `data/raw/events/events_*.parquet` |
| `merge_pipeline.py` | Merge raw ridership, weather, events, and calendar features. | `data/raw/*`, `configs/*.yaml` | `data/processed/feature_store.parquet`, `data/processed/splits/*.parquet` |
| `zero_shot.py` | Run Chronos zero-shot forecasts for one or all stations. | `data/processed/feature_store.parquet` | `models/chronos2/outputs/zero_shot_forecasts_*.parquet` |
| `api.py` | Serve forecasts through FastAPI. | feature store and/or cached forecast parquet | HTTP API |
| `requirements.txt` | Python dependency list for the ML stack. | Python 3.11 environment | installed packages |

## Setup

```bash
python3.11 -m venv .venv311
source .venv311/bin/activate
pip install --upgrade pip
pip install -r machine_learning_files/requirements.txt
```

Edit `configs/sources.yaml` before running credentialed fetchers. Open-Meteo works without a key. 511 and Ticketmaster require API keys.

## Data Flow

```text
external APIs / reports
        |
        v
data/raw/{transit,weather,events,roads}
        |
        v
machine_learning_files/merge_pipeline.py
        |
        v
data/processed/feature_store.parquet
data/processed/splits/{train,val,test}.parquet
        |
        v
Processing/feature_engineering.py
        |
        v
data/processed/feature_store_enriched.parquet
        |
        v
models, evaluation, API, website export
```

The current production-like target is monthly BART station ridership. `merge_pipeline.py` aggregates BART OD data to station-month records, joins month-level weather summaries, computes monthly event indicators, adds calendar fields, and writes chronological train/validation/test splits from `configs/model.yaml`.

## Typical Commands

Build the feature store and splits:

```bash
python machine_learning_files/merge_pipeline.py
```

Build only the feature store:

```bash
python machine_learning_files/merge_pipeline.py --no-split
```

Run Chronos zero-shot for all stations:

```bash
python machine_learning_files/zero_shot.py
```

Run Chronos zero-shot for one station:

```bash
python machine_learning_files/zero_shot.py --station EMBR --as-of 2023-06-01
```

Start the forecast API:

```bash
uvicorn machine_learning_files.api:app --reload --port 8000
```

Example request:

```bash
curl -X POST http://localhost:8000/forecast \
  -H "Content-Type: application/json" \
  -d '{"station_id": "EMBR", "horizon_hours": 6}'
```

## Configuration Notes

- `configs/model.yaml` controls the modeled frequency, context length, forecast horizon, chronological split dates, quantile levels, and AutoGluon training settings.
- `configs/sources.yaml` controls source endpoints, API-key placeholders, venue IDs, agency IDs, and weather station coordinates.
- The API serves cached forecasts first from `models/chronos2/outputs/` and falls back to live Chronos inference when needed.
- `scripts/run_pipeline.sh` expects `.venv311/bin/python` to exist.

## Troubleshooting

- `FileNotFoundError: feature_store.parquet`: run `python machine_learning_files/merge_pipeline.py`.
- `No BART OD files found`: run `python machine_learning_files/fetch_bart_od.py` or place parsed BART parquet files in `data/raw/transit/bart/`.
- Chronos device errors on non-Apple machines: change `chronos2.device` in `configs/model.yaml` from `mps` to `cuda` or `cpu` as appropriate.
- AutoGluon errors with newer Python versions: recreate the environment with Python 3.11.
- Empty API responses for a station: confirm the station ID exists with `GET /stations` and check the latest cached forecast parquet.
