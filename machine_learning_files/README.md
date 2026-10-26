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

Use the pinned Python 3.14.0 environment from the root README's Setup section:

```bash
python3.14 -m venv ~/.venvs/tdf-py314
source ~/.venvs/tdf-py314/bin/activate
pip install -r requirements-lock.txt
```

`requirements-lock.txt` leaves out AutoGluon (it needs Python below 3.14) and the serving stack; see the root README for both.

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
python machine_learning_files/zero_shot.py --station EM --as-of 2023-06-01
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

The response carries `station_id`, `horizon_hours`, `generated_at`, `model`, `interval` and
`forecasts` (one `{timestamp, p10, p50, p90}` row per month). `interval` says which P10/P90
band was returned. For SARIMA it is the model's own band (nominal 80%), not calibrated
because no method passed validation:

```json
"model": "SARIMA(0, 1, 1)x(0, 1, 1, 12)",
"interval": {
  "calibrated": false,
  "method": "none",
  "nominal_level": 0.8,
  "label": "raw: no method passed validation",
  "description": "SARIMA's own P10/P90 band (nominal 80%), not calibrated: no method passed validation."
}
```

## Configuration Notes

- `configs/model.yaml` controls the modeled frequency, context length, forecast horizon, chronological split dates, quantile levels, and AutoGluon training settings.
- `configs/sources.yaml` controls source endpoints, API-key placeholders, venue IDs, agency IDs, and weather station coordinates.
- The API does not use Chronos or any forecast cache. Each `/forecast` fits SARIMA(0,1,1)(0,1,1,12) for one station on months from `data.train_start` up to `as_of` (default: the latest month in the store), with the same code and settings `benchmarks.py` scores for the leaderboard. Tests: `python -m pytest tests/`.
- `scripts/run_pipeline.sh` runs `.venv311/bin/python` if that file exists and `python3` from `PATH` otherwise, so activate the Setup venv first; a leftover `.venv311/` takes precedence over it.

## Troubleshooting

- `FileNotFoundError: feature_store.parquet`: run `python machine_learning_files/merge_pipeline.py`.
- `No BART OD files found`: bart.gov answers automated requests with HTTP 403, so `fetch_bart_od.py` cannot fill `data/raw/transit/bart/`. Download the Ridership workbooks by hand and run `python machine_learning_files/bart_od_from_xlsx.py --zips <zips>` (or `--dir <workbooks>`); see `data/MANIFEST.md`. Do not use `bart_od_from_csv.py` for the pipeline: `merge_pipeline.py` rejects the months it builds.
- Chronos device errors: `chronos2.device` in `configs/model.yaml` defaults to `cpu`; set it to `mps` on Apple Silicon or `cuda` on a GPU machine as appropriate.
- AutoGluon import/install errors: expected in the Setup environment, since `autogluon.timeseries` needs Python below 3.14 and is not in `requirements-lock.txt`. The published leaderboard does not use it; the root README's "Reproduce The Pipeline" section lists the four steps that produced it.
- `404 Unknown station`: station IDs are the store's codes (`EM`, `MT`, `12`, …) — list them with `GET /stations`.
- `400` with "months of history": the `as_of` leaves fewer than 24 months since `data.train_start`.
- `503` mentioning a calibrator: `configs/model.yaml` names a calibration method for SARIMA, but the API has no matching fitted calibrator: it is missing or unreadable, or it is stale or mismatched (fitted for another method, level, model or training cut-off). The API refuses rather than serve the raw band under a calibrated label. SARIMA's method is `none` today, so this only follows a config change.
