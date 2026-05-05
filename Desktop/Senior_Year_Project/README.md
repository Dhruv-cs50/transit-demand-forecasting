# Bay Area Transit Demand Forecasting

CS163 Data Science Senior Project — Dhruv Shah

Multivariate ridership forecasting for Bay Area transit (BART, VTA, Caltrain) using Chronos-2 fine-tuned with weather and events as external covariates.

---

## Overview

This project forecasts transit ridership across Bay Area stations by combining:
- **Historical ridership** from BART, VTA, and 511 transit feeds
- **Weather data** (OpenMeteo hourly forecasts per station)
- **Events** (NHL Sharks games, Ticketmaster events near Diridon)
- **Road traffic** (Caltrans PeMS District 4 freeway sensors)

The primary model is **Chronos-2** (Amazon's time series foundation model) fine-tuned via AutoGluon. Classical baselines (SARIMA, Prophet) serve as benchmarks.

---

## Project Structure

```
Senior_Year_Project/
├── Final_eda/
│   └── eda.py                   # EDA: ridership patterns, event spikes, correlation heatmaps
│
├── machine_learning_files/
│   ├── fetch_511_transit.py     # All Bay Area transit agencies (GTFS-RT)
│   ├── fetch_bart_od.py         # BART origin-destination monthly XLS
│   ├── fetch_weather_openmeteo.py
│   ├── fetch_events.py          # NHL + Ticketmaster events
│   ├── merge_pipeline.py        # Join all sources on timestamp + station_id
│   ├── zero_shot.py             # Chronos-2 zero-shot baseline
│   ├── api.py                   # FastAPI: POST /forecast → P10/P50/P90
│   ├── sources.yaml             # API keys, station IDs, agency codes
│   └── requirements.txt
│
├── Processing/
│   ├── feature_engineering.py   # Covariates: rain effect, event proximity, peak hours
│   └── ablation.py              # Covariate importance + event-day analysis
│
├── evaluation/
│   ├── metrics.py               # MAE, RMSE, MAPE, WAPE, MASE, sMAPE
│   └── validators.py            # Schema checks, missing-data alerts
│
└── models/
    ├── chronos2/
    │   ├── finetune.py          # Fine-tune Chronos-2 via AutoGluon
    │   └── predict.py           # Production inference wrapper
    └── baselines/
        ├── arima.py             # SARIMA baseline (no covariates)
        ├── prophet.py           # Prophet baseline (seasonality + events)
        ├── benchmarks.py        # Head-to-head model comparison
        ├── fetch_pems_roads.py  # Caltrans PeMS road sensor data
        └── scheduler.py        # Nightly data pull + inference cron
```

---

## Quickstart

```bash
pip install -r machine_learning_files/requirements.txt

# 1. Pull data
python machine_learning_files/fetch_511_transit.py
python machine_learning_files/fetch_weather_openmeteo.py
python machine_learning_files/fetch_events.py
python machine_learning_files/fetch_bart_od.py

# 2. Build feature store
python machine_learning_files/merge_pipeline.py
python Processing/feature_engineering.py

# 3. Zero-shot forecast (no training needed)
python machine_learning_files/zero_shot.py

# 4. Fine-tune Chronos-2
python models/chronos2/finetune.py

# 5. Evaluate
python evaluation/metrics.py
python Processing/ablation.py

# 6. Serve
uvicorn machine_learning_files.api:app --reload
```

---

## Models

| Model | Covariates | Notes |
|-------|-----------|-------|
| SARIMA | None | Classical baseline |
| Prophet | Events | Handles seasonality natively |
| Chronos-2 zero-shot | None | Foundation model, no training |
| Chronos-2 fine-tuned | Weather + Events | Primary model |

---

## Data Sources

| Source | Data | Fetch script |
|--------|------|-------------|
| 511 SF Bay | GTFS-RT transit feeds | `fetch_511_transit.py` |
| BART API | Origin-destination ridership | `fetch_bart_od.py` |
| Caltrans PeMS | Freeway sensor counts | `fetch_pems_roads.py` |
| OpenMeteo | Hourly weather forecasts | `fetch_weather_openmeteo.py` |
| Ticketmaster + NHL | Events near stations | `fetch_events.py` |
