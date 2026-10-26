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
| `api.py` | Serve SARIMA forecasts through FastAPI, fitted per request with `models/baselines/arima.py`. | `data/processed/feature_store.parquet` | HTTP API |
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
        +----------------------------------------+
        |                                        |
        v                                        v
Processing/feature_engineering.py       zero_shot.py / api.py
        |                                reads feature_store.parquet
        v                                directly — bypasses enrichment
data/processed/feature_store_enriched.parquet
        |
        v
finetune.py, arima.py, prophet_baseline.py,
evaluation, website export
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
  -d '{"station_id": "EM", "horizon_hours": 6}'
```

`horizon_hours` counts months (at most 6 are returned). Add `"as_of": "2025-06-30"` to
fit on history up to that date instead — that cutoff reproduces the leaderboard's SARIMA forecasts.

## Configuration Notes

- `configs/model.yaml` controls the modeled frequency, context length, forecast horizon, chronological split dates, quantile levels, and AutoGluon training settings.
- `configs/sources.yaml` controls source endpoints, API-key placeholders, venue IDs, agency IDs, and weather station coordinates.
- The API does not use Chronos or any forecast cache. Each `/forecast` fits SARIMA(0,1,1)(0,1,1,12) for one station on months from `data.train_start` up to `as_of` (default: the latest month in the store), with the same code and settings `benchmarks.py` scores for the leaderboard. Tests: `python -m pytest tests/`.
- `scripts/run_pipeline.sh` expects `.venv311/bin/python` to exist.

## Troubleshooting

- `FileNotFoundError: feature_store.parquet`: run `python machine_learning_files/merge_pipeline.py`.
- `No BART OD files found`: run `python machine_learning_files/fetch_bart_od.py` or place parsed BART parquet files in `data/raw/transit/bart/`.
- Chronos device errors: `chronos2.device` in `configs/model.yaml` defaults to `cpu`; set it to `mps` on Apple Silicon or `cuda` on a GPU machine as appropriate.
- AutoGluon errors with newer Python versions: recreate the environment with Python 3.11.
- `404 Unknown station`: station IDs are the store's codes (`EM`, `MT`, `12`, …) — list them with `GET /stations`.
- `400` with "months of history": the `as_of` leaves fewer than 24 months since `data.train_start`.
