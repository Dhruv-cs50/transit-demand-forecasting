"""
tests/test_api.py
─────────────────
Contract tests for the serving API (machine_learning_files/api.py) against the
committed feature store.

Run from the repository root:
    pip install fastapi==0.115.0 pydantic==2.7.0 pandas==2.2.0 pyarrow==16.0.0 \
        numpy==1.26.4 PyYAML==6.0.1 scipy==1.14.1 statsmodels==0.14.4 httpx pytest
    python -m pytest tests/
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

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


@pytest.mark.parametrize("horizon, expected_rows", [(1, 1), (3, 3), (168, 6)])
def test_horizon_truncates_and_caps_at_six_months(client, horizon, expected_rows):
    r = _forecast(client, station_id="EM", horizon_hours=horizon)
    assert r.status_code == 200, r.text
    assert len(r.json()["forecasts"]) == expected_rows


def test_unknown_station_is_404(client):
    r = _forecast(client, station_id="EMBR", horizon_hours=6)
    assert r.status_code == 404
    assert "EMBR" in r.json()["detail"]


@pytest.mark.parametrize("as_of", ["not-a-date", ""])
def test_malformed_as_of_is_400(client, as_of):
    r = _forecast(client, station_id="EM", horizon_hours=6, as_of=as_of)
    assert r.status_code == 400


@pytest.mark.parametrize("as_of", ["2023-06-01", "2018-01-01"])
def test_as_of_with_under_24_months_since_train_start_is_400(client, as_of):
    # 2022-01..2023-06 is 18 months; 2018 predates the store entirely.
    r = _forecast(client, station_id="EM", horizon_hours=6, as_of=as_of)
    assert r.status_code == 400, r.text


def test_health_names_the_served_model(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "SARIMA" in body["model"]
    assert "chronos" not in str(body).lower()
