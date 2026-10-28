# Data Pipeline Runbook

This runbook documents how to rebuild the project data, models, validation outputs, and website JSON from the repository root.

## Prerequisites

Python 3.14.0 and the pinned environment from the README's Setup section:

```bash
python3.14 -m venv ~/.venvs/tdf-py314
source ~/.venvs/tdf-py314/bin/activate
pip install -r requirements-lock.txt
```

`requirements-lock.txt` leaves out the serving stack; see the README.

Review `configs/sources.yaml` before running ingestion. Replace placeholder keys where needed.

## Source Data

| Source | Script | Notes |
| --- | --- | --- |
| BART OD ridership | `machine_learning_files/bart_od_from_xlsx.py` | Current primary target source. bart.gov answers automated requests with HTTP 403, so the Ridership workbooks are downloaded by hand (see `data/MANIFEST.md`); this script converts them into `data/raw/transit/bart/`. `fetch_bart_od.py` exists but cannot download them. |
| 511 SF Bay transit | `machine_learning_files/fetch_511_transit.py` | Requires a 511 API key. Used for future higher-frequency expansion. |
| Open-Meteo weather | `machine_learning_files/fetch_weather_openmeteo.py` | No API key required. Uses station coordinates from `configs/sources.yaml`. |
| NHL and Ticketmaster events | `machine_learning_files/fetch_events.py` | NHL API is public; Ticketmaster requires an API key. |
| Caltrans PeMS roads | `models/baselines/fetch_pems_roads.py` | PeMS often requires authenticated manual download. |

## Rebuild Steps

### 1. Fetch raw data

Run only the fetchers needed for your current experiment. BART's Ridership workbooks are downloaded by hand first (see `data/MANIFEST.md`); the first command converts them:

```bash
python machine_learning_files/bart_od_from_xlsx.py --zips /path/to/*.zip   # or --dir /path/to/workbooks
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
  enriched store so downstream consumers (`evaluation/metrics.py`'s default
  `--actuals`) evaluate on the full enriched schema, not the raw one step 2
  wrote.

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
python models/baselines/benchmarks.py
```

Expected outputs include:

- `models/chronos2/outputs/zero_shot_forecasts_*.parquet` — written by
  `zero_shot.py`. Not what the website publishes; step 6 does not read it.
- `models/baselines/outputs/`
- `evaluation/outputs/benchmark_leaderboard.csv`
- `evaluation/outputs/chronos2_zeroshot_preds.parquet` — the Chronos
  zero-shot test-window predictions, written by `models/baselines/benchmarks.py`
  and scored on the leaderboard. Step 6 reads it for `forecasts.json`.

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
  to have run with the Chronos row accepted: one overall Chronos row in
  `benchmark_leaderboard.csv`, every prediction `model_mode == "zeroshot"`,
  one prediction per station and month, and as many predictions as that row's
  `n` (and `n_expected`). Otherwise the export refuses it: an error is logged,
  nothing is published (the export stages every file and moves them into
  `website/data/` only if all succeed, so the previous set stays in place),
  and the export **exits 1**, so `scripts/run_pipeline.sh` stops before its
  deploy message.
- `website/data/model_comparison.json` — one entry per model from
  `evaluation/outputs/benchmark_leaderboard.csv`.

The export also exits 1 **before writing any file** when
`benchmark_leaderboard.csv` is missing (unless `--allow-val-fallback` is
given), or when any station in `bart_stations.py` has no feature-store rows in
the averaging window or a non-finite average.

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

This script runs `.venv311/bin/python` if that file exists and `python3` from `PATH` otherwise, so activate the Prerequisites venv first (a leftover `.venv311/` takes precedence over it). It assumes the required raw data/API credentials are available.

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
| Website shows stale values | `website/data/*.json` was not regenerated. | Run `scripts/export_website_data.py` before deploy. |
