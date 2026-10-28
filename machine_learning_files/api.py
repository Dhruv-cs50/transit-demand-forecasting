"""
machine_learning_files/api.py
───────────────
FastAPI service exposing the SARIMA baseline — the best-ranked model on the
benchmark leaderboard — as a REST API over monthly BART station ridership.

Each /forecast request fits SARIMA for one station on demand, using the same
spec and functions the leaderboard scores (models/baselines/arima.py): history
from data.train_start up to `as_of`, airline order (0,1,1)(0,1,1,12). The history
is the months that have ended by `as_of` (a month counts once its last day is on
or before as_of's date), so a date inside a month never sees that month's total.
`as_of` = data.val_end (2025-06-30) reproduces the leaderboard's SARIMA
forecasts; the default forecasts the months after the last one in the feature
store, which no benchmark has scored. `horizon_hours` counts months: at most 6
come back, a larger request is clamped with a `warnings` entry, and the response
echoes the number of rows returned.

P10/P90 is SARIMA's own prediction band (nominal 80%), not a calibrated 80%
interval: no calibration method passed validation for SARIMA
(configs/model.yaml `calibration.models.SARIMA`; measurements in
docs/interval-calibration.md), so the band is served as the model produces it.
Every response says which band it carries in `interval`, whose `label` is the
leaderboard's Interval_method string. The band comes from
evaluation/calibration.py's serve_band(): if the config ever names a method
for SARIMA, the API serves the calibrator benchmarks.py saved under
CALIBRATOR_DIR, and answers 503 when that file is missing or stale. P50 is
never changed.

Endpoints:
    POST /forecast   — returns P10/P50/P90 monthly ridership for a station,
                       naming the model and the P10/P90 band served. A
                       quantile the model could not produce (NaN or infinite)
                       is null, and `warnings` names each one.
    GET  /stations   — lists available station IDs
    GET  /health     — liveness check: the model and band served, whether the
                       feature store is loaded, its last month, and where it
                       came from (store_source / store_run_id / store_sha256)

Serving store (docs/cloud-ingestion-design.md §4):
    The history comes from the feature store. By default that is the copy baked
    into the image, data/processed/feature_store.parquet. If env SERVING_STORE_DIR
    is set (the Cloud Run service mounts the bucket there, read-only), the API
    reads <SERVING_STORE_DIR>/processed/serving.json, loads the parquet it names
    and checks its sha256. Any failure -- no directory, no pointer, bad JSON, a
    missing field, a missing object, a path outside the directory, a sha256
    mismatch, an unusable parquet -- logs a warning and serves the baked store
    instead. Only plain files are read; no Google library is imported.

    Every STORE_TTL_SECONDS (default 600) the next request re-reads the pointer
    and swaps in the new store when its run_id differs from the one served. A
    failed reload keeps the current store and tries again after another TTL. A
    swap never touches a request in flight: each request works on the frame it
    got, and a lock serializes loading within a process.

    serving.json is one JSON object (written by the cloud ingestion job, which
    overwrites it last, after the run's objects exist):
        run_id             str  required  identifies the run; a change triggers a swap
        store_object       str  required  feature store parquet, a path relative to
                                          SERVING_STORE_DIR (no "..", not absolute),
                                          e.g. "processed/runs/<run_id>/feature_store.parquet"
        store_sha256       str  required  hex sha256 of that file's bytes
        input_fingerprint  str  optional  hash of the run's inputs (not read here)
        published_at       str  optional  ISO-8601 UTC time of publication (not read here)
    The parquet needs timestamp, station_id and ridership columns, as the baked
    store has. /health reports store_source ("cloud" or "baked"), store_run_id
    (null for the baked store) and store_sha256 of the file served.

Run locally:
    uvicorn machine_learning_files.api:app --reload --port 8000

Example request:
    curl -X POST http://localhost:8000/forecast \\
         -H "Content-Type: application/json" \\
         -d '{"station_id": "EM", "horizon_hours": 6}'
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

# Imported eagerly (it needs only numpy/pandas): a missing copy in the image
# then fails at startup, not as a 500 on every /forecast.
from evaluation.calibration import interval_plan, serve_band

log = logging.getLogger("machine_learning_files.api")
# arima.py logs two INFO lines per fit, i.e. per /forecast. Keep its warnings
# (non-convergence) and drop the rest.
logging.getLogger("arima_baseline").setLevel(logging.WARNING)

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
# Where models/baselines/benchmarks.py saves fitted calibrators. Read only when
# configs/model.yaml names a calibration method for the served model.
CALIBRATOR_DIR = Path("evaluation/outputs/calibration/calibrators")
# The served model's key under calibration.models in configs/model.yaml.
CALIBRATION_KEY = "SARIMA"


class InvalidRequestError(Exception):
    """Malformed request input -> 400 (as opposed to a well-formed request
    for a station that doesn't exist -> UnknownStationError, 404)."""


class UnknownStationError(Exception):
    """station_id is not in the feature store -> 404. Deliberately not a
    ValueError: statsmodels/numpy failures inside a fit (numpy's
    LinAlgError subclasses ValueError) must reach the 500 handler instead
    of being reported as "not found"."""


def load_model_config() -> dict:
    with open(MODEL_CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── Pydantic models ────────────────────────────────────────────────────────────

if _FASTAPI_AVAILABLE:

    class ForecastRequest(BaseModel):
        station_id:    str           = Field(..., example="EM", description="BART station code as listed by GET /stations")
        # The name is historical: the data is monthly, so this counts months.
        # Values above data.forecast_horizon_steps (6) are accepted for older
        # clients, clamped to 6, and said so in the response's `warnings`.
        horizon_hours: int           = Field(6, ge=1, le=168, description="Months to forecast. At most 6 are returned: a larger value is clamped to 6 with a warning, and the response's horizon_hours says how many rows came back.")
        as_of:         Optional[str] = Field(None, example="2025-06-30", description="Forecast anchor (ISO date). The history is the months that have ended by then: a month counts once its last day is on or before as_of's date, so 2025-06-30 includes June and 2025-06-15 does not. Default: the latest month in the feature store.")

    class QuantileForecast(BaseModel):
        timestamp: str
        p10:       Optional[float] = None
        p50:       Optional[float] = None
        p90:       Optional[float] = None

    class IntervalInfo(BaseModel):
        calibrated:    bool  = Field(..., description="True if P10/P90 were rebuilt from validation-split errors; false if they are the model's own band")
        method:        str   = Field(..., description='Calibration method; "none" means the model\'s own band')
        nominal_level: float = Field(..., description="Coverage the band is meant to have (0.8 for P10-P90), not a measured coverage")
        label:         str   = Field(..., description="Same string as the benchmark leaderboard's Interval_method column")
        description:   str   = Field(..., description="One plain sentence saying which band this is")

    class ForecastResponse(BaseModel):
        station_id:    str
        horizon_hours: int          = Field(..., description="Months returned: the request's horizon_hours, or 6 when it asked for more")
        generated_at:  str
        model:         str          = Field(..., description="Model that produced the forecasts")
        interval:      IntervalInfo = Field(..., description="Which P10/P90 band the forecasts carry")
        forecasts:     list[QuantileForecast]
        warnings:      list[str]    = Field(default_factory=list, description="A request clamped to the 6-month horizon, and one line per quantile returned as null because the model gave no finite value; empty otherwise")

    class StationsResponse(BaseModel):
        stations: list[str]
        count:    int


# ── Feature-store cache ────────────────────────────────────────────────────────

_feature_store: pd.DataFrame | None = None
# Where _feature_store came from: {"source": "cloud"|"baked"|None, "run_id", "sha256"}.
_store_info: dict = {"source": None, "run_id": None, "sha256": None}
# _clock() when the store was loaded or the pointer last re-read (None: never).
_store_checked_at: float | None = None
# Serializes loading and swapping; requests that need neither never take it.
_store_lock = threading.Lock()
_clock = time.monotonic

SERVING_STORE_ENV = "SERVING_STORE_DIR"
SERVING_POINTER = Path("processed") / "serving.json"
DEFAULT_STORE_TTL_SECONDS = 600
_STORE_COLUMNS = {"timestamp", "station_id", "ridership"}


@lru_cache(maxsize=1)
def _get_config() -> dict:
    return load_model_config()


def _model_name() -> str:
    from models.baselines.arima import get_sarima_orders
    orders = get_sarima_orders(_get_config()["data"].get("resample_freq", "MS"))
    return f"SARIMA{orders['order']}x{orders['seasonal_order']}"


def _serving_dir() -> Path | None:
    value = os.environ.get(SERVING_STORE_ENV, "").strip()
    return Path(value) if value else None


def _store_ttl() -> float:
    """STORE_TTL_SECONDS, or 600 when unset, not a number, or negative."""
    try:
        ttl = float(os.environ["STORE_TTL_SECONDS"])
    except (KeyError, ValueError):
        return DEFAULT_STORE_TTL_SECONDS
    return ttl if ttl >= 0 else DEFAULT_STORE_TTL_SECONDS


def _parse_store(data: bytes) -> pd.DataFrame:
    df = pd.read_parquet(io.BytesIO(data))
    missing = _STORE_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"feature store lacks columns {sorted(missing)}")
    if df.empty:
        raise ValueError("feature store has no rows")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def _read_pointer(base: Path) -> dict:
    """<base>/processed/serving.json, checked for the fields the reader needs."""
    pointer = json.loads((base / SERVING_POINTER).read_text())
    if not isinstance(pointer, dict):
        raise ValueError("serving.json is not a JSON object")
    for key in ("run_id", "store_object", "store_sha256"):
        if not isinstance(pointer.get(key), str) or not pointer[key].strip():
            raise ValueError(f"serving.json lacks a string {key!r}")
    return pointer


def _load_cloud_store(base: Path, pointer: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """The store serving.json names, with its sha256 verified. Raises on any problem."""
    pointer = pointer or _read_pointer(base)
    root = base.resolve()
    obj = (base / pointer["store_object"]).resolve()
    if not obj.is_relative_to(root):
        raise ValueError(f"store_object {pointer['store_object']!r} is outside {base}")
    data = obj.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha != pointer["store_sha256"].strip().lower():
        raise ValueError(f"sha256 of {obj.name} is {sha}, serving.json says {pointer['store_sha256']}")
    return _parse_store(data), {"source": "cloud", "run_id": pointer["run_id"], "sha256": sha}


def _load_baked_store() -> tuple[pd.DataFrame, dict]:
    path = PROCESSED_DIR / "feature_store.parquet"
    if not path.exists():
        raise RuntimeError("Feature store not found. Run the pipeline first.")
    data = path.read_bytes()
    return _parse_store(data), {"source": "baked", "run_id": None, "sha256": hashlib.sha256(data).hexdigest()}


def _install_store(df: pd.DataFrame, info: dict) -> None:
    """Publish a fully built store. Callers hold _store_lock."""
    global _feature_store, _store_info, _store_checked_at
    _store_info = info
    _feature_store = df
    _store_checked_at = _clock()
    log.info(f"Feature store loaded: {len(df):,} rows ({info['source']}, run {info['run_id']})")


def _reload_due() -> bool:
    if _serving_dir() is None:
        return False
    return _store_checked_at is None or _clock() - _store_checked_at >= _store_ttl()


def _reload_serving_store(base: Path) -> None:
    """Swap in the pointer's store if its run_id is new. A failure keeps the
    current store. Callers hold _store_lock."""
    global _store_checked_at
    _store_checked_at = _clock()  # a failure waits a full TTL before the next try
    try:
        pointer = _read_pointer(base)
        if pointer["run_id"] == _store_info["run_id"]:
            return
        df, info = _load_cloud_store(base, pointer)
    except Exception as e:
        log.warning(f"Serving store reload from {base} failed ({e}); keeping {_store_info['source']} "
                    f"store (run {_store_info['run_id']})")
        return
    _install_store(df, info)


def get_feature_store() -> pd.DataFrame:
    """The store in use: loaded on first call, re-checked every STORE_TTL_SECONDS
    when SERVING_STORE_DIR is set. Thread-safe."""
    store = _feature_store
    if store is not None and not _reload_due():
        return store
    with _store_lock:
        if _feature_store is None:
            base = _serving_dir()
            if base is not None:
                try:
                    _install_store(*_load_cloud_store(base))
                    return _feature_store
                except Exception as e:
                    log.warning(f"Serving store {base} unusable ({e}); falling back to the baked feature store")
            _install_store(*_load_baked_store())
        elif _reload_due():
            _reload_serving_store(_serving_dir())
        return _feature_store


# ── Forecast logic ─────────────────────────────────────────────────────────────

def _clean_quantile(value) -> float | None:
    """Coerce a raw quantile cell to a JSON-safe value.

    NaN and +-inf both become None: JSON has no Infinity/NaN (the response
    encoder rejects them, which would turn a forecast into a 500), and an
    infinite bound is no more a usable number than a missing one. /forecast
    lists each such cell in the response's `warnings`.

    `max(0.0, x)` silently returns 0.0 when `x` is NaN (NaN always loses
    float comparisons, so `nan > 0.0` is False and `max` picks the first
    arg) -- turning a station-month the model genuinely couldn't forecast
    into a fake "0 riders" prediction. Returning None instead lets the
    response emit JSON `null` (which the frontends already render as "—"),
    matching how export_website_data.py handles NaN forecast cells.
    """
    if value is None or pd.isna(value) or not np.isfinite(value):
        return None
    return max(0.0, float(value))


def _null_quantile_warnings(rows: list[dict]) -> list[str]:
    """One line per P10/P50/P90 cell _clean_quantile returned as null."""
    return [
        f"{row['timestamp']}: {q} is not finite; returned as null (the model gave no usable bound)."
        for row in rows
        for q in ("p10", "p50", "p90")
        if row[q] is None
    ]


def _run_forecast(
    station_id: str,
    horizon_hours: int,
    as_of: pd.Timestamp | None,
) -> tuple[list[dict], dict]:
    """Fit SARIMA on one station's history up to `as_of` and forecast ahead.

    Mirrors run_arima_all_stations() in models/baselines/arima.py, which the
    benchmark leaderboard scores: history is clipped to data.train_start (the
    store jumps 2019 -> 2022, and fit_station() alone would interpolate across
    that gap), and the same minimum-history rule applies.

    Returns (rows, plan): rows carry P50 exactly as predict_station() gives it
    and the P10/P90 band serve_band() assigns; plan says which band that is.
    Raises CalibratorUnavailable (a RuntimeError -> 503) when the config names
    a calibration method but no matching saved calibrator exists.
    """
    from models.baselines.arima import fit_station, get_sarima_orders, predict_station

    cfg = _get_config()
    freq = cfg["data"].get("resample_freq", "MS")
    df = get_feature_store()

    station_df = df[df["station_id"] == station_id]
    if station_df.empty:
        raise UnknownStationError(f"Unknown station: {station_id}")

    if as_of is None:
        # The latest month in the store is complete, so its own end is the anchor.
        as_of = station_df["timestamp"].max() + pd.offsets.MonthEnd(0)
    else:
        # feature_store timestamps are tz-naive — keep as_of naive too, or the
        # history-window comparison below raises TypeError.
        try:
            as_of = pd.Timestamp(as_of)
            if pd.isna(as_of):
                # pd.Timestamp("") / "NaT" / "nan" parse successfully to NaT
                # instead of raising -- left unchecked, `<= as_of` against a
                # NaT anchor is all-False, silently producing an empty history
                # instead of a clean error.
                raise ValueError(f"as_of parsed to NaT: {as_of!r}")
        except ValueError as e:
            # pandas raises a ValueError subclass (DateParseError) for an
            # unparseable as_of string. Left uncaught it would reach the
            # generic 500 handler; a malformed *request* is a 400.
            raise InvalidRequestError(f"Invalid as_of value {as_of!r}: {e}") from e
        if station_df["timestamp"].dt.tz is not None:
            as_of = as_of.tz_localize("America/Los_Angeles") if as_of.tzinfo is None else as_of.tz_convert("America/Los_Angeles")
        elif as_of.tzinfo is not None:
            # Convert to LA wall-clock time before dropping the tz label — stripping
            # a non-LA offset directly would keep the wrong wall-clock digits (e.g.
            # 08:00 UTC silently becomes "08:00 naive" instead of the correct 01:00 PDT).
            as_of = as_of.tz_convert("America/Los_Angeles").tz_localize(None)

    # Keep the months that have ended: a month's ridership is its total, so a
    # month still in progress at as_of must not be in the history. A month
    # counts once its last day is on or before as_of's date (2025-06-30 keeps
    # June; 2025-06-15 does not).
    month_end = station_df["timestamp"] + pd.offsets.MonthEnd(0)
    history = station_df[month_end <= as_of.normalize()]
    train_start = cfg["data"].get("train_start")
    if train_start:
        start = pd.Timestamp(train_start)
        if station_df["timestamp"].dt.tz is not None:
            start = start.tz_localize("America/Los_Angeles")
        history = history[history["timestamp"] >= start]

    # Same floor run_arima_all_stations() applies (two seasonal cycles).
    # Checked here so a short history is a 400 rather than fit_station()'s
    # ValueError, which would surface as a 500.
    min_months = get_sarima_orders(freq)["seasonal_order"][3] * 2
    n_months = history["timestamp"].nunique()
    if n_months < min_months:
        raise InvalidRequestError(
            f"{station_id} has {n_months} months of history between "
            f"{train_start} and as_of {as_of}; SARIMA needs at least {min_months}."
        )

    steps = min(cfg["data"].get("forecast_horizon_steps", 6), horizon_hours)
    fit, last_ts = fit_station(history, station_id, freq)
    pred_df = predict_station(fit, last_ts, steps, freq)
    pred_df["station_id"] = station_id

    # The band configs/model.yaml assigns SARIMA: its own P10/P90 while the
    # method is "none" (the file is then never read), else the saved
    # calibrator's band. P50 passes through untouched either way.
    pred_df, plan = serve_band(
        pred_df, CALIBRATION_KEY, cfg,
        calibrator_path=CALIBRATOR_DIR / f"{CALIBRATION_KEY}.json",
        # Months ahead count from the last fitted month, as benchmarks.py
        # counts them from its forecast origin.
        forecast_origin=last_ts,
    )

    rows = [
        {
            "timestamp": str(row.timestamp),
            "p10": _clean_quantile(row.p10),
            "p50": _clean_quantile(row.p50),
            "p90": _clean_quantile(row.p90),
        }
        for row in pred_df.itertuples()
    ]
    return rows, plan


# ── FastAPI app ────────────────────────────────────────────────────────────────

if _FASTAPI_AVAILABLE:
    app = FastAPI(
        title="Bay Area Transit Forecast API",
        description=(
            "SARIMA monthly ridership forecasts (P10/P50/P90) for BART stations, fitted per request. "
            "Each response's `interval` says which P10/P90 band it carries."
        ),
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup():
        """Pre-load the feature store, and import statsmodels so the first
        /forecast doesn't pay for it (seconds on a cold container)."""
        try:
            get_feature_store()
            log.info("Feature store warm")
        except Exception as e:
            log.warning(f"Startup preload failed (will retry on first request): {e}")
        try:
            # fit_station() imports SARIMAX lazily; import it here instead.
            import models.baselines.arima  # noqa: F401
            import statsmodels.tsa.statespace.sarimax  # noqa: F401
        except Exception as e:
            log.warning(f"SARIMA import failed at startup: {e}")

    @app.get("/health")
    def health():
        # Reports the store without loading it: a failed startup preload
        # shows here as store_loaded false instead of being retried by a probe.
        if _feature_store is not None:
            try:
                get_feature_store()  # applies a due TTL reload; never loads
            except Exception as e:
                log.warning(f"Serving store refresh failed: {e}")
        with _store_lock:
            store = _feature_store
            info = _store_info if store is not None else {"source": None, "run_id": None, "sha256": None}
        last_month = None
        if store is not None and len(store):
            last_month = store["timestamp"].max().strftime("%Y-%m-%d")
        return {
            "status":       "ok",
            "timestamp":    datetime.utcnow().isoformat() + "Z",
            "model":        _model_name(),
            "interval":     interval_plan(CALIBRATION_KEY, _get_config())["label"],
            "store_loaded": store is not None,
            "store_last_month": last_month,
            "store_source": info["source"],
            "store_run_id": info["run_id"],
            "store_sha256": info["sha256"],
        }

    @app.get("/stations", response_model=StationsResponse)
    def list_stations():
        # get_feature_store() raises RuntimeError when the parquet is missing
        # (it is committed, so only a broken checkout or image hits this).
        # /forecast maps that to a 503 with a helpful detail message; this
        # endpoint does the same instead of FastAPI's bare, non-JSON 500.
        try:
            df = get_feature_store()
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        stations = sorted(df["station_id"].unique().tolist())
        return {"stations": stations, "count": len(stations)}

    @app.post("/forecast", response_model=ForecastResponse)
    def forecast(req: ForecastRequest):
        try:
            forecasts, plan = _run_forecast(req.station_id, req.horizon_hours, req.as_of)
        except InvalidRequestError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except UnknownStationError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except RuntimeError as e:
            # Also CalibratorUnavailable (a RuntimeError): the config names a
            # calibration method but its saved calibrator is missing or stale.
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            log.exception("Forecast failed")
            raise HTTPException(status_code=500, detail="Internal forecast error")

        # Say what came back, not what was asked for: a request above the
        # model's horizon gets 6 rows, a warning, and horizon_hours = 6.
        warnings = []
        if req.horizon_hours > len(forecasts):
            warnings.append(
                f"horizon_hours={req.horizon_hours} exceeds the {len(forecasts)} months this model "
                f"forecasts; returned {len(forecasts)}."
            )
        warnings += _null_quantile_warnings(forecasts)

        return {
            "station_id":    req.station_id,
            "horizon_hours": len(forecasts),
            # A bare isoformat() string with no "Z"/offset is parsed by the
            # browser's `new Date(...)` as LOCAL time (ECMA-262 Date Time
            # String Format), not UTC -- api-demo.html's `new
            # Date(data.generated_at).toLocaleTimeString()` showed a time off
            # by exactly the visitor's UTC offset. Append "Z" so it's parsed
            # as UTC and correctly converted to the visitor's local time.
            "generated_at":  datetime.utcnow().isoformat() + "Z",
            "model":         _model_name(),
            "interval": {
                "calibrated":    plan["calibrated"],
                "method":        plan["method"],
                "nominal_level": plan["level"],
                "label":         plan["label"],
                "description":   plan["description"],
            },
            "forecasts":     forecasts,
            "warnings":      warnings,
        }

    @app.get("/")
    def root():
        return {
            "service":  "Bay Area Transit Forecast API",
            "docs":     "/docs",
            "health":   "/health",
            "stations": "/stations",
            "forecast": "POST /forecast",
        }
