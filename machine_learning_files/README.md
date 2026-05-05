# Bay Area Traffic Forecasting

Multivariate traffic & transit ridership forecasting for the entire Bay Area,
with weather and events as external covariates. Powered by Chronos-2.

## Project structure

```
bay_area_traffic_forecast/
├── website/                          # ← Claude Code frontend (separate)
├── eda/
│   └── eda.py                        # ← Exploratory data analysis
│
├── ingestion/                        # One script per data source
│   ├── fetch_511_transit.py          # All Bay Area transit agencies (GTFS-RT)
│   ├── fetch_bart_od.py              # BART origin-destination monthly XLS
│   ├── fetch_pems_roads.py           # Caltrans PeMS District 4 freeway sensors
│   ├── fetch_weather_openmeteo.py    # Hourly weather per station lat/lng
│   └── fetch_events.py              # NHL (Sharks) + Ticketmaster events
│
├── data/
│   ├── raw/                          # Untouched source dumps
│   │   ├── transit/
│   │   ├── roads/
│   │   ├── weather/
│   │   └── events/
│   └── processed/
│       ├── feature_store.parquet     # Single merged feature table
│       └── splits/                   # train.parquet / val.parquet / test.parquet
│
├── processing/
│   ├── merge_pipeline.py             # Join all sources on timestamp + station_id
│   ├── feature_engineering.py        # Covariate construction
│   └── validators.py                 # Schema checks, missing-data alerts
│
├── models/
│   ├── chronos2/
│   │   ├── zero_shot.py              # Baseline inference, no training required
│   │   ├── finetune.py               # Fine-tune on historical data via AutoGluon
│   │   └── predict.py                # Production inference wrapper
│   └── baselines/
│       ├── prophet.py                # Handles seasonality + events natively
│       └── arima.py                  # SARIMA baseline
│
├── evaluation/
│   ├── metrics.py                    # MAE, RMSE, MAPE, WAPE per station/hour
│   ├── ablation.py                   # Covariate importance + event-day slices
│   └── benchmarks.py                 # Head-to-head model comparison
│
├── serving/
│   ├── api.py                        # FastAPI: POST /forecast → P10/P50/P90
│   └── scheduler.py                  # Nightly data pull + inference cron
│
├── notebooks/                        # One-off experiments
├── tests/
└── configs/
    ├── sources.yaml                  # API keys, station IDs, agency codes
    └── model.yaml                    # Horizon, context window, quantile levels
```

## Quickstart

```bash
pip install -r requirements.txt
cp configs/sources.yaml.example configs/sources.yaml  # fill in your API keys

# 1. Pull all data
python ingestion/fetch_511_transit.py
python ingestion/fetch_weather_openmeteo.py
python ingestion/fetch_events.py

# 2. Build feature store
python processing/merge_pipeline.py

# 3. Run zero-shot forecast (no training needed)
python models/chronos2/zero_shot.py

# 4. Serve
uvicorn serving.api:app --reload
```
