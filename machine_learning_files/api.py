"""
serving/api.py
───────────────
FastAPI service exposing the Chronos-2 forecast as a REST API.

Endpoints:
    POST /forecast   — returns P10/P50/P90 ridership for a station
    GET  /stations   — lists available station IDs
    GET  /health     — liveness check

Run locally:
    uvicorn serving.api:app --reload --port 8000

Example request:
    curl -X POST http://localhost:8000/forecast \\
         -H "Content-Type: application/json" \\
         -d '{"station_id": "EMBR", "horizon_hours": 24}'
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

log = logging.getLogger("serving.api")

# ── Lazy imports so the module loads even without ML deps installed ─────────────
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False
    log.warning("FastAPI not installed — run: pip install fastapi uvicorn")

PROCESSED_DIR = Path("data/processed")
MODEL_CONFIG_PATH = Path("configs/model.yaml")


def load_model_config() -> dict:
    with open(MODEL_CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── Pydantic models ────────────────────────────────────────────────────────────

if _FASTAPI_AVAILABLE:

    class ForecastRequest(BaseModel):
        station_id:    str           = Field(..., example="EMBR", description="BART/transit station code")
        horizon_hours: int           = Field(24, ge=1, le=168, description="Hours to forecast (1–168)")
        as_of:         Optional[str] = Field(None, example="2025-06-01T08:00:00", description="Forecast anchor time (ISO). Default: now.")

    class QuantileForecast(BaseModel):
        timestamp: str
        p10:       float
        p50:       float
        p90:       float

    class ForecastResponse(BaseModel):
        station_id:    str
        horizon_hours: int
        generated_at:  str
        forecasts:     list[QuantileForecast]

    class StationsResponse(BaseModel):
        stations: list[str]
        count:    int


# ── Model cache ────────────────────────────────────────────────────────────────

_pipeline = None
_feature_store: pd.DataFrame | None = None


@lru_cache(maxsize=1)
def _get_config() -> dict:
    return load_model_config()


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        from chronos import ChronosPipeline
        cfg = _get_config()
        log.info("Loading Chronos-2 pipeline …")
        _pipeline = ChronosPipeline.from_pretrained(
            cfg["chronos2"]["model_id"],
            device_map=cfg["chronos2"]["device"],
        )
        log.info("Chronos-2 ready")
    return _pipeline


def get_feature_store() -> pd.DataFrame:
    global _feature_store
    if _feature_store is None:
        path = PROCESSED_DIR / "feature_store.parquet"
        if not path.exists():
            raise RuntimeError("Feature store not found. Run the pipeline first.")
        _feature_store = pd.read_parquet(path)
        _feature_store["timestamp"] = pd.to_datetime(_feature_store["timestamp"])
        log.info(f"Feature store loaded: {len(_feature_store):,} rows")
    return _feature_store


# ── Forecast logic ─────────────────────────────────────────────────────────────

def _run_forecast(
    station_id: str,
    horizon_hours: int,
    as_of: pd.Timestamp | None,
) -> list[dict]:
    """Core forecast logic — loads pre-computed parquet first, falls back to live Chronos."""
    cfg = _get_config()

    # Fast path: serve from pre-computed zero-shot forecast parquet
    cached_dir = Path("models/chronos2/outputs")
    cached_files = sorted(cached_dir.glob("zero_shot_forecasts_*.parquet")) if cached_dir.exists() else []
    if cached_files:
        cached = pd.read_parquet(cached_files[-1])
        station_cache = cached[cached["station_id"] == station_id]
        if not station_cache.empty:
            q10_col = next((c for c in station_cache.columns if "0.1" in str(c)), None)
            q50_col = next((c for c in station_cache.columns if "0.5" in str(c)), None)
            q90_col = next((c for c in station_cache.columns if "0.9" in str(c)), None)
            results = []
            for _, row in station_cache.head(horizon_hours).iterrows():
                ts = row.get("timestamp", "")
                results.append({
                    "timestamp": str(ts),
                    "p10": max(0.0, float(row[q10_col])) if q10_col else 0.0,
                    "p50": max(0.0, float(row[q50_col])) if q50_col else 0.0,
                    "p90": max(0.0, float(row[q90_col])) if q90_col else 0.0,
                })
            if results:
                return results

    # Slow path: live Chronos inference
    from machine_learning_files.zero_shot import prepare_context, run_zero_shot_forecast

    df = get_feature_store()
    pipeline = get_pipeline()

    station_df = df[df["station_id"] == station_id]
    if station_df.empty:
        raise ValueError(f"Unknown station: {station_id}")

    if as_of is None:
        as_of = station_df["timestamp"].max()
    else:
        as_of = pd.Timestamp(as_of, tz="America/Los_Angeles")

    context_steps = cfg["chronos2"].get("context_length_steps", None)
    context_steps = cfg["data"].get("context_length_steps") or context_steps
    prediction_length = cfg["data"].get("forecast_horizon_steps") \
        or cfg["chronos2"].get("prediction_length_steps", 6)

    context_df, future_df = prepare_context(
        df, station_id, cfg["data"].get("context_length_hours"), as_of,
        context_steps=context_steps,
    )

    pred_df = run_zero_shot_forecast(
        pipeline, context_df, future_df,
        station_id, prediction_length,
        quantile_levels=[0.1, 0.5, 0.9],
    )

    q_cols = {
        "p10": next((c for c in pred_df.columns if "0.1" in str(c)), None),
        "p50": next((c for c in pred_df.columns if "0.5" in str(c) or c == "mean"), None),
        "p90": next((c for c in pred_df.columns if "0.9" in str(c)), None),
    }

    results = []
    for _, row in pred_df.iterrows():
        ts = row.get("timestamp", "")
        results.append({
            "timestamp": str(ts),
            "p10": max(0.0, float(row[q_cols["p10"]])) if q_cols["p10"] else float("nan"),
            "p50": max(0.0, float(row[q_cols["p50"]])) if q_cols["p50"] else float("nan"),
            "p90": max(0.0, float(row[q_cols["p90"]])) if q_cols["p90"] else float("nan"),
        })

    return results


# ── FastAPI app ────────────────────────────────────────────────────────────────

if _FASTAPI_AVAILABLE:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Pre-load the feature store on startup; clean up on shutdown."""
        try:
            get_feature_store()
            log.info("Feature store warm")
        except Exception as e:
            log.warning(f"Startup preload failed (will retry on first request): {e}")
        yield

    app = FastAPI(
        title="Bay Area Traffic Forecast API",
        description="Chronos-2 powered ridership forecasting for Bay Area transit stations",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {
            "status":       "ok",
            "timestamp":    datetime.utcnow().isoformat(),
            "model":        _get_config()["chronos2"]["model_id"],
            "store_loaded": _feature_store is not None,
            "model_loaded": _pipeline is not None,
        }

    @app.get("/stations", response_model=StationsResponse)
    def list_stations():
        df = get_feature_store()
        stations = sorted(df["station_id"].unique().tolist())
        return {"stations": stations, "count": len(stations)}

    @app.post("/forecast", response_model=ForecastResponse)
    def forecast(req: ForecastRequest):
        try:
            forecasts = _run_forecast(req.station_id, req.horizon_hours, req.as_of)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            log.exception("Forecast failed")
            raise HTTPException(status_code=500, detail=str(e))

        return {
            "station_id":    req.station_id,
            "horizon_hours": req.horizon_hours,
            "generated_at":  datetime.utcnow().isoformat(),
            "forecasts":     forecasts,
        }

    @app.get("/")
    def root():
        return {
            "service":  "Bay Area Traffic Forecast API",
            "docs":     "/docs",
            "health":   "/health",
            "stations": "/stations",
            "forecast": "POST /forecast",
        }
