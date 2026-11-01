# Forecast API

Live: **https://transit-api-308878596074.us-west2.run.app** (Swagger UI at
[`/docs`](https://transit-api-308878596074.us-west2.run.app/docs)).
Code: `machine_learning_files/api.py`.

The API serves **SARIMA airline (0,1,1)(0,1,1,12)**, the leaderboard's best
model. Each `/forecast` fits it for the requested station on demand, with the
same functions `benchmarks.py` scores (`fit_station` / `predict_station` in
`models/baselines/arima.py`).

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Served model, P10/P90 band label, store source, run id, sha256 and last month |
| `GET` | `/stations` | Forecastable station IDs |
| `POST` | `/forecast` | P10/P50/P90 forecasts for one station |
| `GET` | `/docs` | Swagger UI |

## Request

```json
{ "station_id": "EM", "horizon_hours": 6, "as_of": "2025-06-30" }
```

- **`horizon_hours` counts months.** The name predates the monthly target. It
  defaults to 6; a larger request is clamped to 6, and the response's
  `horizon_hours` says how many rows came back, with a `warnings` entry.
- **`as_of`** (optional) is the forecast anchor. The history is the months from
  `data.train_start` (2022-01) that have ended on or before `as_of`: a
  month-end date keeps its own month, a mid-month date leaves it out. Without
  `as_of`, the history is Jan 2022 – Dec 2025 (the store's 2019 months are never
  used), so the forecast covers Jan–Jun 2026.

## What the numbers mean

- `"as_of": "2025-06-30"` reproduces the published Jul–Dec 2025 test forecasts
  exactly; that is where the 3.21% WAPE comes from. The default forecast, refit
  through Dec 2025, has not been scored.
- P10/P90 are SARIMA's own band (nominal 80%). It is not calibrated, because no
  method passed validation, and it covered 96.7% of test actuals (over-wide).
  Every response says so in its `interval` field.
- A NaN or infinite bound comes back as `null`, with a line in `warnings`.

## Response

```json
{
  "station_id": "EM",
  "horizon_hours": 6,
  "generated_at": "2026-10-28T10:54:52.637510Z",
  "model": "SARIMA(0, 1, 1)x(0, 1, 1, 12)",
  "interval": {
    "calibrated": false,
    "method": "none",
    "nominal_level": 0.8,
    "label": "raw: no method passed validation",
    "description": "SARIMA's own P10/P90 band (nominal 80%), not calibrated: no method passed validation."
  },
  "forecasts": [
    { "timestamp": "2026-01-01 00:00:00", "p10": 386519.9, "p50": 415136.9, "p90": 443753.8 }
  ],
  "warnings": []
}
```

A live response to `{"station_id": "EM", "horizon_hours": 6}` on 2026-10-28;
first of six rows shown, values rounded here.

## Errors

- Unknown station → `404`.
- Malformed `as_of`, or one that leaves fewer than 24 months of history → `400`.
- If `configs/model.yaml` names a calibration method for SARIMA but no matching
  fitted calibrator ships with the API → `503`, so a raw band is never served
  under a calibrated label.

## Where the data comes from

With `SERVING_STORE_DIR` set (as on Cloud Run), the API serves the latest store
the cloud ingest job published, verified by sha256, and falls back to the store
baked into its image on any failure. See [deployment.md](deployment.md#how-the-api-picks-its-store).

## Run and test locally

The feature store is committed, so no pipeline run is needed. The API runs on
Python 3.11, the version its image uses; its numpy, pandas, pyarrow, scipy and
statsmodels pins have no Python 3.14 wheels, so it gets its own venv:

```bash
python3.11 -m venv ~/.venvs/tdf-api-py311
source ~/.venvs/tdf-api-py311/bin/activate
pip install fastapi==0.115.0 "uvicorn[standard]==0.30.0" pydantic==2.7.0 pandas==2.2.0 pyarrow==16.0.0 numpy==1.26.4 PyYAML==6.0.1 scipy==1.14.1 patsy==1.0.1 statsmodels==0.14.4 httpx pytest
python -m pytest tests/test_api.py tests/test_api_serving_store.py
uvicorn machine_learning_files.api:app --reload --port 8080
```
