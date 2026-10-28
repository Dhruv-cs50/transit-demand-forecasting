"""
tests/test_api_serving_store.py
───────────────────────────────
The API's serving store (machine_learning_files/api.py): with SERVING_STORE_DIR
set it reads <dir>/processed/serving.json and the parquet it names, verifying
the sha256; any failure falls back to the baked data/processed/feature_store
.parquet. Everything here uses a temp dir -- no GCP, no network.

Run in the serving environment (Python 3.11, see tests/test_api.py).
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pandas as pd
import pytest

# The serving stack is not in the Python 3.14 environment's lock: skip there.
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore:Too few observations:UserWarning")

REPO_ROOT = Path(__file__).resolve().parents[1]
BAKED = REPO_ROOT / "data/processed/feature_store.parquet"


@pytest.fixture
def api(monkeypatch):
    """api.py with an empty store cache, env cleared, cwd at the repo root.
    monkeypatch puts every module global back afterwards."""
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.delenv("SERVING_STORE_DIR", raising=False)
    monkeypatch.delenv("STORE_TTL_SECONDS", raising=False)
    import machine_learning_files.api as api

    monkeypatch.setattr(api, "_feature_store", None)
    monkeypatch.setattr(api, "_store_info", {"source": None, "run_id": None, "sha256": None})
    monkeypatch.setattr(api, "_store_checked_at", None)
    return api


@pytest.fixture
def client(api):
    # No `with`: startup would preload the store before the test sets its env.
    return TestClient(api.app)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _publish(root: Path, run_id: str, *, extra_month: bool = False, pointer_sha: str | None = None) -> Path:
    """Write processed/runs/<run_id>/feature_store.parquet and the pointer."""
    store = pd.read_parquet(BAKED)
    if extra_month:
        store["timestamp"] = pd.to_datetime(store["timestamp"])
        last = store[store["timestamp"] == store["timestamp"].max()].copy()
        last["timestamp"] = pd.Timestamp("2026-01-01")
        store = pd.concat([store, last], ignore_index=True)
    obj = Path("processed/runs") / run_id / "feature_store.parquet"
    (root / obj).parent.mkdir(parents=True, exist_ok=True)
    store.to_parquet(root / obj)
    pointer = {
        "run_id": run_id,
        "store_object": str(obj),
        "store_sha256": pointer_sha or _sha(root / obj),
        "input_fingerprint": "f" * 64,
        "published_at": "2026-10-29T10:15:00Z",
    }
    (root / "processed").mkdir(exist_ok=True)
    (root / "processed/serving.json").write_text(json.dumps(pointer))
    return root / obj


def _forecast_p50(client, **body):
    r = client.post("/forecast", json={"station_id": "EM", "horizon_hours": 6, **body})
    assert r.status_code == 200, r.text
    return [row["p50"] for row in r.json()["forecasts"]]


# ── Source selection ───────────────────────────────────────────────────────────

def test_health_before_any_load_names_no_source(api, client):
    body = client.get("/health").json()
    assert body["store_loaded"] is False
    assert (body["store_source"], body["store_run_id"], body["store_sha256"]) == (None, None, None)


def test_env_unset_serves_the_baked_store(api, client):
    health = client.get("/stations")  # loads the store
    assert health.status_code == 200
    body = client.get("/health").json()
    assert body["store_source"] == "baked"
    assert body["store_run_id"] is None
    assert body["store_sha256"] == _sha(BAKED)
    assert body["store_last_month"] == "2025-12-01"


def test_valid_pointer_serves_the_cloud_store(api, client, monkeypatch, tmp_path):
    obj = _publish(tmp_path, "run-1")
    monkeypatch.setenv("SERVING_STORE_DIR", str(tmp_path))
    assert client.get("/stations").status_code == 200
    body = client.get("/health").json()
    assert body["store_loaded"] is True
    assert body["store_source"] == "cloud"
    assert body["store_run_id"] == "run-1"
    assert body["store_sha256"] == _sha(obj)


@pytest.mark.parametrize("failure", ["sha_mismatch", "no_pointer", "no_dir", "bad_json", "missing_object", "escaping_path"])
def test_any_cloud_failure_falls_back_to_baked(api, client, monkeypatch, tmp_path, caplog, failure):
    root = tmp_path / "store"
    root.mkdir()
    if failure == "sha_mismatch":
        _publish(root, "run-1", pointer_sha="0" * 64)
    elif failure == "bad_json":
        (root / "processed").mkdir()
        (root / "processed/serving.json").write_text("{not json")
    elif failure == "missing_object":
        obj = _publish(root, "run-1")
        obj.unlink()
    elif failure == "escaping_path":
        _publish(root, "run-1")
        p = json.loads((root / "processed/serving.json").read_text())
        p["store_object"] = "../../" + str(BAKED)
        (root / "processed/serving.json").write_text(json.dumps(p))
    elif failure == "no_dir":
        root = tmp_path / "does-not-exist"
    monkeypatch.setenv("SERVING_STORE_DIR", str(root))

    with caplog.at_level("WARNING", logger="machine_learning_files.api"):
        assert client.get("/stations").status_code == 200
    body = client.get("/health").json()
    assert body["store_source"] == "baked"
    assert body["store_run_id"] is None
    assert any("falling back" in r.message.lower() for r in caplog.records)


def test_pointer_missing_a_required_field_falls_back(api, client, monkeypatch, tmp_path):
    _publish(tmp_path, "run-1")
    p = json.loads((tmp_path / "processed/serving.json").read_text())
    del p["store_sha256"]
    (tmp_path / "processed/serving.json").write_text(json.dumps(p))
    monkeypatch.setenv("SERVING_STORE_DIR", str(tmp_path))
    client.get("/stations")
    assert client.get("/health").json()["store_source"] == "baked"


# ── Same forecasts from either store ───────────────────────────────────────────

def test_cloud_store_with_an_extra_month_forecasts_identically_at_the_same_anchor(api, client, monkeypatch, tmp_path):
    baked = _forecast_p50(client, as_of="2025-06-30")
    api._feature_store = None
    api._store_checked_at = None

    _publish(tmp_path, "run-1", extra_month=True)
    monkeypatch.setenv("SERVING_STORE_DIR", str(tmp_path))
    assert _forecast_p50(client, as_of="2025-06-30") == baked
    body = client.get("/health").json()
    assert body["store_source"] == "cloud"
    assert body["store_last_month"] == "2026-01-01"


def test_default_origin_follows_the_cloud_stores_last_month(api, client, monkeypatch, tmp_path):
    _publish(tmp_path, "run-1", extra_month=True)
    monkeypatch.setenv("SERVING_STORE_DIR", str(tmp_path))
    rows = client.post("/forecast", json={"station_id": "EM", "horizon_hours": 6}).json()["forecasts"]
    assert rows[0]["timestamp"] == "2026-02-01 00:00:00"


# ── TTL reload ─────────────────────────────────────────────────────────────────

def test_ttl_reload_picks_up_a_new_run_id(api, client, monkeypatch, tmp_path):
    _publish(tmp_path, "run-1")
    monkeypatch.setenv("SERVING_STORE_DIR", str(tmp_path))
    monkeypatch.setenv("STORE_TTL_SECONDS", "0")
    client.get("/stations")
    assert client.get("/health").json()["store_run_id"] == "run-1"

    _publish(tmp_path, "run-2", extra_month=True)
    body = client.get("/health").json()
    assert body["store_run_id"] == "run-2"
    assert body["store_last_month"] == "2026-01-01"


def test_nothing_is_re_read_before_the_ttl_expires(api, client, monkeypatch, tmp_path):
    now = [1000.0]
    monkeypatch.setattr(api, "_clock", lambda: now[0])
    _publish(tmp_path, "run-1")
    monkeypatch.setenv("SERVING_STORE_DIR", str(tmp_path))
    client.get("/stations")

    _publish(tmp_path, "run-2")
    now[0] += 599
    assert client.get("/health").json()["store_run_id"] == "run-1"
    now[0] += 2
    assert client.get("/health").json()["store_run_id"] == "run-2"


def test_ttl_defaults_to_600_and_ignores_garbage(api, monkeypatch):
    assert api._store_ttl() == 600
    monkeypatch.setenv("STORE_TTL_SECONDS", "soon")
    assert api._store_ttl() == 600
    monkeypatch.setenv("STORE_TTL_SECONDS", "-5")
    assert api._store_ttl() == 600
    monkeypatch.setenv("STORE_TTL_SECONDS", "30")
    assert api._store_ttl() == 30


def test_failed_reload_keeps_the_current_store(api, client, monkeypatch, tmp_path):
    _publish(tmp_path, "run-1")
    monkeypatch.setenv("SERVING_STORE_DIR", str(tmp_path))
    monkeypatch.setenv("STORE_TTL_SECONDS", "0")
    client.get("/stations")

    _publish(tmp_path, "run-2", pointer_sha="0" * 64)  # sha mismatch
    body = client.get("/health").json()
    assert (body["store_source"], body["store_run_id"]) == ("cloud", "run-1")

    (tmp_path / "processed/serving.json").unlink()  # pointer gone
    body = client.get("/health").json()
    assert (body["store_source"], body["store_run_id"]) == ("cloud", "run-1")
    assert _forecast_p50(client, as_of="2025-06-30")


def test_unchanged_run_id_does_not_reload_the_parquet(api, client, monkeypatch, tmp_path):
    _publish(tmp_path, "run-1")
    monkeypatch.setenv("SERVING_STORE_DIR", str(tmp_path))
    monkeypatch.setenv("STORE_TTL_SECONDS", "0")
    client.get("/stations")

    def boom(*a, **k):
        raise AssertionError("parquet re-read for an unchanged run_id")

    monkeypatch.setattr(api.pd, "read_parquet", boom)
    assert client.get("/health").json()["store_run_id"] == "run-1"
    assert client.get("/stations").status_code == 200


def test_baked_fallback_upgrades_to_cloud_when_the_pointer_appears(api, client, monkeypatch, tmp_path):
    monkeypatch.setenv("SERVING_STORE_DIR", str(tmp_path))
    monkeypatch.setenv("STORE_TTL_SECONDS", "0")
    client.get("/stations")
    assert client.get("/health").json()["store_source"] == "baked"

    _publish(tmp_path, "run-1")
    body = client.get("/health").json()
    assert (body["store_source"], body["store_run_id"]) == ("cloud", "run-1")


# ── Threads ────────────────────────────────────────────────────────────────────

def test_concurrent_first_requests_load_the_store_once(api, monkeypatch, tmp_path):
    _publish(tmp_path, "run-1")
    monkeypatch.setenv("SERVING_STORE_DIR", str(tmp_path))
    real = api._load_cloud_store
    calls = []

    def counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(api, "_load_cloud_store", counting)
    results, errors = [], []

    def worker():
        try:
            results.append(api.get_feature_store())
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(calls) == 1
    assert all(r is results[0] for r in results)


def test_requests_during_reloads_never_see_a_half_built_store(api, monkeypatch, tmp_path):
    _publish(tmp_path, "run-0")
    monkeypatch.setenv("SERVING_STORE_DIR", str(tmp_path))
    monkeypatch.setenv("STORE_TTL_SECONDS", "0")
    api.get_feature_store()
    errors, stop = [], threading.Event()

    def reader():
        while not stop.is_set():
            try:
                df = api.get_feature_store()
                assert {"timestamp", "station_id", "ridership"} <= set(df.columns)
                assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])
            except Exception as e:  # pragma: no cover - failure path
                errors.append(e)
                return

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for i in range(1, 4):
        _publish(tmp_path, f"run-{i}", extra_month=bool(i % 2))
        api.get_feature_store()
    stop.set()
    for t in threads:
        t.join()
    assert not errors
