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
  enriched store so downstream consumers (`finetune.py`'s `load_train_val()`,
  `evaluation/metrics.py`'s default `--actuals`, `Processing/ablation.py`'s
  default `--test`) train/evaluate on the full enriched schema, not the raw
  one step 2 wrote.

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
  to have run with the Chronos row accepted (an overall Chronos row in
  `benchmark_leaderboard.csv`, every prediction `model_mode == "zeroshot"`);
  otherwise an error is logged and no `forecasts.json` is written (an existing
  one is left as it is).
- `website/data/model_comparison.json` — one entry per model from
  `evaluation/outputs/benchmark_leaderboard.csv`.

### 7. Deploy website

```bash
gcloud app deploy website/app.yaml --quiet
```

The live site (https://cs-163-final-project-tra-f1136.wl.r.appspot.com) is served
by App Engine Standard, configured via `website/app.yaml` — not Firebase
Hosting. `firebase deploy --only hosting` will succeed without error but
publishes to an unused Firebase Hosting site, leaving the real production URL
unchanged.

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
| AutoGluon install fails | Unsupported Python version or dependency conflict. | Recreate the environment with Python 3.11. |
| Website shows stale values | `website/data/*.json` was not regenerated. | Run `scripts/export_website_data.py` before deploy. |
