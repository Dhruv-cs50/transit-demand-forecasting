# Data Pipeline Runbook

This runbook documents how to rebuild the project data, models, validation outputs, and website JSON from the repository root.

## Prerequisites

```bash
python3.11 -m venv .venv311
source .venv311/bin/activate
pip install --upgrade pip
pip install -r machine_learning_files/requirements.txt
```

Review `configs/sources.yaml` before running ingestion. Replace placeholder keys where needed.

## Source Data

| Source | Script | Notes |
| --- | --- | --- |
| BART OD ridership | `machine_learning_files/fetch_bart_od.py` | Current primary target source. Parsed outputs are expected under `data/raw/transit/bart/`. |
| 511 SF Bay transit | `machine_learning_files/fetch_511_transit.py` | Requires a 511 API key. Used for future higher-frequency expansion. |
| Open-Meteo weather | `machine_learning_files/fetch_weather_openmeteo.py` | No API key required. Uses station coordinates from `configs/sources.yaml`. |
| NHL and Ticketmaster events | `machine_learning_files/fetch_events.py` | NHL API is public; Ticketmaster requires an API key. |
| Caltrans PeMS roads | `models/baselines/fetch_pems_roads.py` | PeMS often requires authenticated manual download. |

## Rebuild Steps

### 1. Fetch raw data

Run only the fetchers needed for your current experiment:

```bash
python machine_learning_files/fetch_bart_od.py
python machine_learning_files/fetch_weather_openmeteo.py
python machine_learning_files/fetch_events.py
```

### 2. Build feature store and splits

```bash
python machine_learning_files/merge_pipeline.py
```

Expected outputs:

- `data/processed/feature_store.parquet`
- `data/processed/splits/train.parquet`
- `data/processed/splits/val.parquet`
- `data/processed/splits/test.parquet`

### 3. Add engineered features

```bash
python Processing/feature_engineering.py
```

Expected output:

- `data/processed/feature_store_enriched.parquet`

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
python models/chronos2/finetune.py --time-limit 1800
python models/baselines/benchmarks.py
```

Expected outputs include:

- `models/chronos2/outputs/zero_shot_forecasts_*.parquet`
- `models/baselines/outputs/`
- `models/chronos2/weights/`
- `evaluation/outputs/benchmark_leaderboard.csv`

### 6. Export website data

```bash
python scripts/export_website_data.py --feature-store data/processed/feature_store_enriched.parquet
```

Expected outputs:

- `website/data/stations_ridership.json`
- `website/data/stations_meta.json`
- `website/data/ridership_actuals.json`
- `website/data/forecasts.json`
- `website/data/model_comparison.json`

### 7. Deploy website

```bash
firebase deploy --only hosting
```

Firebase Hosting serves files from `website/` according to `firebase.json`.

## One-command Pipeline

After setup, the full scripted path is:

```bash
bash scripts/run_pipeline.sh
```

This script assumes `.venv311/bin/python` exists and that required raw data/API credentials are available.

## Feature Store Schema

The minimum columns expected by validators and downstream scripts are:

| Column | Type | Notes |
| --- | --- | --- |
| `timestamp` | datetime | Current cadence is month start. |
| `station_id` | string | BART OD origin station code in the active pipeline. |
| `ridership` | numeric | Forecast target. |

Common optional columns include:

- Station and source: `station_name`, `agency_id`, `transit_mode`
- Weather: `temp_f`, `precip_mm`, `is_raining`, `windspeed_mph`, `weather_code`, `cloud_cover_pct`
- Events: `is_game_day`, `hours_to_event`, `is_sharks_game`, `game_start_hour`, `is_playoff`
- Calendar: `hour_of_day`, `day_of_week`, `month`, `week_of_year`, `is_weekend`, `is_holiday`
- Engineered features: lags, rolling means/stds, cyclic encodings, precipitation intensity, event windows, and station static features

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `No BART OD files found` | Raw BART parquet files are missing. | Run `fetch_bart_od.py` or place files in `data/raw/transit/bart/`. |
| `Feature store not found` | Merge pipeline has not run. | Run `python machine_learning_files/merge_pipeline.py`. |
| `feature_store_enriched.parquet` missing | Feature engineering has not run. | Run `python Processing/feature_engineering.py`. |
| Validation flags missing windows | Split cadence or source coverage changed. | Confirm `configs/model.yaml` frequency and inspect source coverage by station. |
| Chronos fails to load on `mps` | Machine is not Apple Silicon or MPS is unavailable. | Set `chronos2.device` to `cuda` or `cpu` in `configs/model.yaml`. |
| AutoGluon install fails | Unsupported Python version or dependency conflict. | Recreate the environment with Python 3.11. |
| Website shows stale values | `website/data/*.json` was not regenerated. | Run `scripts/export_website_data.py` before deploy. |
