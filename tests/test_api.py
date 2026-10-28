"""
tests/test_api.py
─────────────────
Contract tests for the serving API (machine_learning_files/api.py) against the
committed feature store.

Run from the repository root:
    pip install fastapi==0.115.0 "uvicorn[standard]==0.30.0" pydantic==2.7.0 \
        pandas==2.2.0 pyarrow==16.0.0 numpy==1.26.4 PyYAML==6.0.1 scipy==1.14.1 \
        patsy==1.0.1 statsmodels==0.14.4 httpx pytest
    python -m pytest tests/
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from evaluation.calibration import apply_conformal, fit_conformal, load_calibrator, save_calibrator

REPO_ROOT = Path(__file__).resolve().parents[1]

# statsmodels says this for every fit on ~30-48 monthly points; arima.py
# silences UserWarning at import, but pytest resets filters per test.
pytestmark = pytest.mark.filterwarnings("ignore:Too few observations:UserWarning")


@pytest.fixture(scope="module")
def client():
    # api.py resolves data/ and configs/ relative to the working directory,
    # as it does inside the image (WORKDIR /app).
    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    from machine_learning_files.api import app
    with TestClient(app) as c:
        yield c
    os.chdir(cwd)


def _forecast(client, **body):
    return client.post("/forecast", json=body)


def test_known_station_gets_six_monthly_forecasts_after_the_last_store_month(client):
    r = _forecast(client, station_id="EM", horizon_hours=6)
    assert r.status_code == 200, r.text
    rows = r.json()["forecasts"]
    assert [row["timestamp"] for row in rows] == [
        "2026-01-01 00:00:00", "2026-02-01 00:00:00", "2026-03-01 00:00:00",
        "2026-04-01 00:00:00", "2026-05-01 00:00:00", "2026-06-01 00:00:00",
    ]
    # Hand-checked with a direct statsmodels SARIMAX(0,1,1)(0,1,1,12) fit on
    # EM's 48 months 2022-01..2025-12. A fit that starts in 2019 (ignoring
    # train_start) interpolates across the missing 2020-21 months and lands
    # elsewhere.
    assert rows[0]["p50"] == pytest.approx(415137, abs=1)
    assert rows[5]["p50"] == pytest.approx(487928, abs=1)
    for row in rows:
        assert row["p10"] < row["p50"] < row["p90"]


def test_as_of_backtest_reproduces_the_published_sarima_wape(client):
    # The leaderboard scores SARIMA trained through val_end (2025-06-30) on the
    # Jul-Dec 2025 holdout: 3.21% WAPE over 300 station-months.
    store = pd.read_parquet(REPO_ROOT / "data/processed/feature_store.parquet")
    store["timestamp"] = pd.to_datetime(store["timestamp"])
    actuals = store[store["timestamp"] > "2025-06-30"].set_index(["station_id", "timestamp"])["ridership"]

    abs_err = total = 0.0
    n = 0
    for station in sorted(store["station_id"].unique()):
        r = _forecast(client, station_id=station, horizon_hours=6, as_of="2025-06-30")
        assert r.status_code == 200, (station, r.text)
        for row in r.json()["forecasts"]:
            actual = actuals[(station, pd.Timestamp(row["timestamp"]))]
            abs_err += abs(actual - row["p50"])
            total += abs(actual)
            n += 1
    assert n == 300
    assert round(abs_err / total * 100, 2) == 3.21


@pytest.mark.parametrize("horizon, expected_rows", [(1, 1), (3, 3), (6, 6), (7, 6), (24, 6), (168, 6)])
def test_horizon_truncates_and_caps_at_six_months(client, horizon, expected_rows):
    r = _forecast(client, station_id="EM", horizon_hours=horizon)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["forecasts"]) == expected_rows
    # The response says how many months it returned, not how many were asked for.
    assert body["horizon_hours"] == expected_rows


def test_horizon_above_six_is_clamped_with_a_warning(client):
    body = _forecast(client, station_id="EM", horizon_hours=24).json()
    assert body["horizon_hours"] == 6
    assert body["warnings"] == ["horizon_hours=24 exceeds the 6 months this model forecasts; returned 6."]


def test_horizon_within_six_has_no_horizon_warning(client):
    body = _forecast(client, station_id="EM", horizon_hours=3).json()
    assert body["horizon_hours"] == 3
    assert body["warnings"] == []


def test_horizon_defaults_to_six(client):
    r = client.post("/forecast", json={"station_id": "EM"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["horizon_hours"] == 6
    assert len(body["forecasts"]) == 6
    assert body["warnings"] == []


@pytest.mark.parametrize("horizon", [0, -1, 169])
def test_horizon_outside_1_to_168_is_422(client, horizon):
    assert _forecast(client, station_id="EM", horizon_hours=horizon).status_code == 422


def test_unknown_station_is_404(client):
    r = _forecast(client, station_id="EMBR", horizon_hours=6)
    assert r.status_code == 404
    assert "EMBR" in r.json()["detail"]


# ── as_of uses only months that have ended ─────────────────────────────────────
# A month's ridership is a month total, known only once the month is over. as_of
# keeps a month when that month's last day is on or before as_of's date, so a
# date in the middle of June cannot see June's total (a leak when someone passes
# today's date), while the month-end date 2025-06-30 keeps June.

def _p50s(client, **body):
    r = _forecast(client, station_id="EM", horizon_hours=6, **body)
    assert r.status_code == 200, r.text
    return [(row["timestamp"], row["p50"]) for row in r.json()["forecasts"]]


@pytest.mark.parametrize("as_of", ["2025-06-15", "2025-06-01", "2025-05-31"])
def test_mid_month_as_of_excludes_the_unfinished_month(client, as_of):
    rows = _p50s(client, as_of=as_of)
    assert rows[0][0] == "2025-06-01 00:00:00"
    assert rows == _p50s(client, as_of="2025-05-31")


def test_mid_month_as_of_differs_from_the_month_end_anchor(client):
    assert _p50s(client, as_of="2025-06-15") != _p50s(client, as_of="2025-06-30")


@pytest.mark.parametrize("as_of", ["2025-06-30", "2025-06-30T23:59:59", "2025-07-01", "2025-07-15"])
def test_month_end_date_keeps_its_own_month(client, as_of):
    rows = _p50s(client, as_of=as_of)
    assert rows[0][0] == "2025-07-01 00:00:00"
    assert rows == _p50s(client, as_of="2025-06-30")


@pytest.mark.parametrize("as_of", ["not-a-date", ""])
def test_malformed_as_of_is_400(client, as_of):
    r = _forecast(client, station_id="EM", horizon_hours=6, as_of=as_of)
    assert r.status_code == 400


@pytest.mark.parametrize("as_of", ["2023-06-01", "2018-01-01"])
def test_as_of_with_under_24_months_since_train_start_is_400(client, as_of):
    # 2022-01..2023-06 is 18 months; 2018 predates the store entirely.
    r = _forecast(client, station_id="EM", horizon_hours=6, as_of=as_of)
    assert r.status_code == 400, r.text


def test_a_failed_fit_for_a_known_station_is_500_not_404(client, monkeypatch):
    # numpy's LinAlgError subclasses ValueError, the type /forecast once
    # mapped wholesale to 404 "not found". A real numerical failure can't be
    # provoked from the committed store, so the fit is replaced.
    import models.baselines.arima as arima

    def failing_fit(*args, **kwargs):
        raise np.linalg.LinAlgError("Schur decomposition solver error.")

    monkeypatch.setattr(arima, "fit_station", failing_fit)
    r = _forecast(client, station_id="EM", horizon_hours=6)
    assert r.status_code == 500


def test_health_names_the_served_model(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "SARIMA" in body["model"]
    assert "chronos" not in str(body).lower()


def test_health_reports_the_store_and_what_is_served(client):
    body = client.get("/health").json()
    assert {"status", "timestamp", "model", "interval", "store_loaded", "store_last_month"} <= set(body)
    assert body["model"] == "SARIMA(0, 1, 1)x(0, 1, 1, 12)"
    assert body["store_loaded"] is True
    # The committed store ends 2025-12; /forecast's default anchor.
    assert body["store_last_month"] == "2025-12-01"


def test_health_before_the_store_loads_says_so_without_loading_it(client, monkeypatch):
    import machine_learning_files.api as api
    monkeypatch.setattr(api, "_feature_store", None)
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["store_loaded"] is False
    assert body["store_last_month"] is None
    assert api._feature_store is None


# ── Which P10/P90 band is served ───────────────────────────────────────────────
# configs/model.yaml leaves SARIMA's band raw (calibration.models.SARIMA:
# method none). The tests below check that the response says so, that the raw
# band is served as SARIMA produces it, and -- with the config patched to name
# a method -- that the saved calibrator's band is served instead, or a 503.

SARIMA_RAW_LABEL = "raw: no method passed validation"


def test_health_labels_the_served_band(client):
    assert client.get("/health").json()["interval"] == SARIMA_RAW_LABEL


def test_response_names_the_model_and_labels_sarimas_own_band(client):
    r = _forecast(client, station_id="EM", horizon_hours=6)
    assert r.status_code == 200, r.text
    body = r.json()
    assert list(body) == ["station_id", "horizon_hours", "generated_at", "model", "interval", "forecasts", "warnings"]
    assert body["model"] == "SARIMA(0, 1, 1)x(0, 1, 1, 12)"
    interval = body["interval"]
    assert interval["calibrated"] is False
    assert interval["method"] == "none"
    assert interval["nominal_level"] == 0.8
    assert interval["label"] == SARIMA_RAW_LABEL
    assert "not calibrated" in interval["description"]
    assert "80% interval" not in interval["description"]


def test_raw_band_is_served_as_sarima_produces_it(client):
    import machine_learning_files.api as api
    from models.baselines.arima import fit_station, predict_station

    cfg = api._get_config()
    freq = cfg["data"]["resample_freq"]
    store = pd.read_parquet(REPO_ROOT / "data/processed/feature_store.parquet")
    store["timestamp"] = pd.to_datetime(store["timestamp"])
    history = store[(store["station_id"] == "EM") & (store["timestamp"] >= cfg["data"]["train_start"])]
    fit, last_ts = fit_station(history, "EM", freq)
    direct = predict_station(fit, last_ts, 6, freq)

    rows = _forecast(client, station_id="EM", horizon_hours=6).json()["forecasts"]
    for col in ("p10", "p50", "p90"):
        assert [row[col] for row in rows] == direct[col].tolist(), col


def _calibrate_sarima_in_config(monkeypatch, calibrator_dir: Path) -> None:
    """Point the API at a config that names a method for SARIMA, and at
    `calibrator_dir` for the saved calibrator. The cached config is copied,
    not edited, and monkeypatch restores both afterwards."""
    import machine_learning_files.api as api

    cfg = copy.deepcopy(api._get_config())
    cfg["calibration"]["models"]["SARIMA"] = {"method": "relative", "group": "pooled"}
    monkeypatch.setattr(api, "_get_config", lambda: cfg)
    monkeypatch.setattr(api, "CALIBRATOR_DIR", calibrator_dir)


def _synthetic_calibrator() -> dict:
    """relative/pooled at 0.8 from 12 rows with errors of +-1%..6%: q = 0.06,
    a band clearly narrower than SARIMA's own and with P10 above zero."""
    cal = pd.DataFrame({
        "station_id": "X",
        "timestamp": pd.date_range("2025-01-01", periods=12, freq="MS"),
        "p10": 900.0, "p50": 1000.0, "p90": 1100.0,
    })
    cal["ridership"] = 1000.0 * (1 + np.array([1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6]) / 100)
    return fit_conformal(cal, method="relative", group="pooled", level=0.8)


def test_configured_calibration_rebuilds_p10_p90_and_keeps_p50(client, monkeypatch, tmp_path):
    raw = _forecast(client, station_id="EM", horizon_hours=6)
    assert raw.status_code == 200, raw.text
    raw_rows = pd.DataFrame(raw.json()["forecasts"]).assign(station_id="EM")

    import machine_learning_files.api as api

    path = tmp_path / "SARIMA.json"
    # serve_band refuses a calibrator fitted on other splits; benchmarks.py
    # records the config's train_end as fit_end.
    save_calibrator(_synthetic_calibrator(), path, model_key="SARIMA",
                    fit_end=str(api._get_config()["data"]["train_end"]))
    _calibrate_sarima_in_config(monkeypatch, tmp_path)

    r = _forecast(client, station_id="EM", horizon_hours=6)
    assert r.status_code == 200, r.text
    body = r.json()
    got = pd.DataFrame(body["forecasts"])
    expected = apply_conformal(raw_rows, load_calibrator(path))

    assert got["timestamp"].tolist() == raw_rows["timestamp"].tolist()
    assert got["p50"].tolist() == raw_rows["p50"].tolist()
    assert got["p10"].tolist() == [max(0.0, v) for v in expected["p10"]]
    assert got["p90"].tolist() == [max(0.0, v) for v in expected["p90"]]
    # Not vacuous: the served band is the calibrator's, not SARIMA's own.
    assert got["p10"].tolist() != raw_rows["p10"].tolist()
    assert got["p90"].tolist() != raw_rows["p90"].tolist()
    assert (got["p10"] > 0).all()

    interval = body["interval"]
    assert interval["calibrated"] is True
    assert interval["method"] == "relative"
    assert interval["nominal_level"] == 0.8
    assert interval["label"] == "split-conformal relative/pooled, fit on validation"
    assert body["model"] == "SARIMA(0, 1, 1)x(0, 1, 1, 12)"


def test_configured_calibration_without_a_saved_calibrator_is_503(client, monkeypatch, tmp_path):
    _calibrate_sarima_in_config(monkeypatch, tmp_path)  # tmp_path holds no SARIMA.json
    r = _forecast(client, station_id="EM", horizon_hours=6)
    assert r.status_code == 503, r.text
    assert "calibrator" in r.json()["detail"]


# ── Non-finite quantiles ───────────────────────────────────────────────────────
# statsmodels can return an infinite or NaN bound when a fit's forecast variance
# blows up. A response must stay valid JSON (no Infinity/NaN) and keep every
# month's row: the bad value is null and the top-level `warnings` list says so.


@pytest.mark.parametrize("bad", [np.inf, -np.inf, np.nan])
def test_non_finite_quantile_is_null_and_flagged_not_a_500(client, monkeypatch, bad):
    from models.baselines import arima

    real = arima.predict_station

    def with_bad_p90(*args, **kwargs):
        out = real(*args, **kwargs)
        out.loc[out.index[2], "p90"] = bad
        return out

    monkeypatch.setattr(arima, "predict_station", with_bad_p90)
    r = _forecast(client, station_id="EM", horizon_hours=6)
    assert r.status_code == 200, r.text
    assert "Infinity" not in r.text and "NaN" not in r.text
    body = r.json()
    rows = body["forecasts"]
    assert len(rows) == 6
    assert rows[2]["p90"] is None
    assert rows[2]["p10"] is not None and rows[2]["p50"] is not None
    assert all(row["p90"] is not None for i, row in enumerate(rows) if i != 2)
    assert body["warnings"] == [
        "2026-03-01 00:00:00: p90 is not finite; returned as null (the model gave no usable bound)."
    ]


def test_finite_forecast_carries_no_warnings(client):
    assert _forecast(client, station_id="EM", horizon_hours=6).json()["warnings"] == []
