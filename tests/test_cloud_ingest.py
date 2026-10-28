"""
tests/test_cloud_ingest.py
──────────────────────────
S9-06: the cloud ingestion job (machine_learning_files/cloud_ingest.py,
configs/ingest.yaml; docs/cloud-ingestion-design.md §2, §5, §7).

A LocalStorage directory stands in for the bucket and an injected builder for the
BART-workbook rebuild, so there is no GCP, no network and no BART data. The real
publish gate runs where the outcome matters (first publish, rerun); elsewhere a
stub gate keeps a test to a second. The job's merge_pipeline path patching is
tested against the real merge_pipeline.

Run from the repository root:
    python -m pytest -q tests/test_cloud_ingest.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

from machine_learning_files import cloud_ingest, ingest_gate
from machine_learning_files.cloud_ingest import (
    POINTER_KEYS,
    IngestError,
    build_candidate,
    input_fingerprint,
    main,
    merge_pipeline_paths,
    stage_inputs,
)
from machine_learning_files.cloud_store import LocalStorage, ObjInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACKED = REPO_ROOT / "data" / "processed" / "feature_store.parquet"
TRACKED_SHA = hashlib.sha256(TRACKED.read_bytes()).hexdigest()
NOW = dt.datetime(2026, 10, 28, 8, 0, 0, tzinfo=dt.timezone.utc)      # 01:00 in Los Angeles
RUN_ID = "20261028T080000Z-test01"
GIT_SHA = "abc1234"

pytestmark = pytest.mark.filterwarnings("ignore:Too few observations:UserWarning")


# ── helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """No test may reach gs://: the bucket is always passed as file://."""
    monkeypatch.delenv("INGEST_BUCKET", raising=False)
    monkeypatch.setenv("GIT_SHA", GIT_SHA)
    if importlib.util.find_spec("requests") is None:     # fetch_events imports it; nothing is requested
        monkeypatch.setitem(sys.modules, "requests", types.ModuleType("requests"))


@pytest.fixture(scope="module")
def tracked() -> pd.DataFrame:
    df = pd.read_parquet(TRACKED)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def add_month(df: pd.DataFrame, month: str, scale: float = 1.01) -> pd.DataFrame:
    last = df[df["timestamp"] == df["timestamp"].max()].copy()
    ts = pd.Timestamp(month)
    last["timestamp"] = ts
    last["period"] = ts
    last["month"] = ts.month
    last["ridership"] = last["ridership"] * scale
    return pd.concat([df, last], ignore_index=True)


@pytest.fixture(scope="module")
def candidate(tracked) -> pd.DataFrame:
    """The tracked store plus a synthetic 2026-01: what a rebuild with one new
    BART workbook would give (the gate test shows it passes)."""
    return add_month(tracked, "2026-01-01")


RAW = {   # object -> bytes: stand-ins for the pinned archive
    "raw/bart/Ridership_202501.xlsx": b"workbook-202501",
    "raw/bart/Ridership 2024.zip": b"zip-2024",
    "raw/weather/weather_all_stations_2024-01-01_2025-12-31.parquet": b"weather-archive",
    "raw/events/events_2024-01-01_2025-12-31.parquet": b"events-archive",
}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def make_cfg(**over) -> dict:
    cfg = cloud_ingest.load_config()
    cfg["pinned_inputs"] = {n: sha(b) for n, b in RAW.items()}
    cfg["sources"] = {  # three locations keep the fake fetches small
        "weather": {"station_coords": {"a": {"lat": 1.0, "lng": 2.0}, "b": {"lat": 3.0, "lng": 4.0}}},
        "nhl": {"sharks_team_id": "SJS"},
    }
    cfg.update(over)
    return cfg


def seed(bucket_dir: Path) -> LocalStorage:
    store = LocalStorage(bucket_dir)
    for name, data in RAW.items():
        store.write_bytes(name, data, if_generation_match=None)
    return store


def run(bucket_dir, *flags, cfg=None, builder=None, **kw) -> int:
    argv = ["--bucket", f"file://{bucket_dir}", *flags]
    return main(argv, cfg=cfg or make_cfg(), builder=builder, now=kw.pop("now", NOW),
                run_id=kw.pop("run_id", RUN_ID), **kw)


def stub_gate(monkeypatch, passed=True):
    def fake(candidate, tracked, served_months, cfg, *, last_closed_month=None, model_cfg=None):
        check = ingest_gate.CheckResult("stub", "pass" if passed else "fail", "stubbed")
        return ingest_gate.GateReport(passed, [] if passed else [check], [check])
    monkeypatch.setattr(cloud_ingest, "run_gate", fake)


def snapshot(store: LocalStorage) -> list[tuple[str, int]]:
    return [(o.name, o.generation) for o in store.list()]


def pointer_of(store: LocalStorage) -> dict:
    return json.loads(store.read_bytes("processed/serving.json")[0])


class Builder:
    """An injected builder that counts its calls."""

    def __init__(self, frame, hook=None):
        self.frame, self.hook, self.calls = frame, hook, 0

    def __call__(self, workdir):
        self.calls += 1
        if self.hook:
            self.hook()
        return self.frame


# ── first run publishes (real gate, once) ─────────────────────────────────────

@pytest.fixture(scope="module")
def published(tmp_path_factory, candidate):
    """A bucket after one real run: real gate, real backtest."""
    mp = pytest.MonkeyPatch()
    mp.setenv("GIT_SHA", GIT_SHA)
    try:
        bucket = tmp_path_factory.mktemp("published") / "bucket"
        seed(bucket)
        builder = Builder(candidate)
        code = run(bucket, "--skip-fetch", builder=builder)
        return {"dir": bucket, "code": code, "builder": builder, "tracked_sha_after": sha(TRACKED.read_bytes())}
    finally:
        mp.undo()


def copy_bucket(src: Path, tmp_path: Path) -> Path:
    dst = tmp_path / "bucket"
    shutil.copytree(src, dst)       # copy2: mtimes (and so generations) survive
    return dst


def test_first_run_publishes(published):
    store = LocalStorage(published["dir"])
    assert published["code"] == 0
    assert published["builder"].calls == 1

    names = [o.name for o in store.list("processed/")]
    assert names == [
        f"processed/runs/{RUN_ID}/feature_store.parquet",
        f"processed/runs/{RUN_ID}/gate.json",
        f"processed/runs/{RUN_ID}/manifest.json",
        "processed/serving.json",
    ]

    gate = json.loads(store.read_bytes(f"processed/runs/{RUN_ID}/gate.json")[0])
    assert gate["passed"] is True and gate["failures"] == []
    wape = next(c for c in gate["checks"] if c["check"] == "sarima_backtest")
    assert wape["detail"]["wape_pct"] == 3.21
    assert gate["run_id"] == RUN_ID and gate["git_sha"] == GIT_SHA

    manifest = json.loads(store.read_bytes(f"processed/runs/{RUN_ID}/manifest.json")[0])
    store_bytes = store.read_bytes(f"processed/runs/{RUN_ID}/feature_store.parquet")[0]
    assert manifest["git_sha"] == GIT_SHA
    assert manifest["store"]["sha256"] == sha(store_bytes)
    assert manifest["store"]["months"][-1] == "2026-01" and manifest["store"]["rows"] == 3050
    assert manifest["tracked_store_sha256"] == TRACKED_SHA
    assert manifest["gate"]["passed"] is True
    assert {i["name"]: i["sha256"] for i in manifest["inputs"]} == {n: sha(b) for n, b in RAW.items()}
    assert all(isinstance(i["generation"], int) for i in manifest["inputs"])


def test_the_pointer_has_exactly_the_serving_schema(published):
    store = LocalStorage(published["dir"])
    pointer = pointer_of(store)
    store_bytes = store.read_bytes(pointer["store_object"])[0]

    assert set(pointer) == set(POINTER_KEYS) == {
        "run_id", "store_object", "store_sha256", "input_fingerprint", "published_at"}
    assert pointer["run_id"] == RUN_ID
    assert pointer["store_object"] == f"processed/runs/{RUN_ID}/feature_store.parquet"
    assert ".." not in pointer["store_object"] and not pointer["store_object"].startswith("/")
    assert pointer["store_sha256"] == sha(store_bytes)
    assert pointer["input_fingerprint"] == input_fingerprint(store.list("raw/"))
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", pointer["published_at"])
    assert pointer["published_at"] == "2026-10-28T08:00:00Z"
    print("\nserving.json:", json.dumps(pointer, indent=2, sort_keys=True))


def test_api_accepts_the_pointer_and_verifies_the_store(published, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    monkeypatch.chdir(REPO_ROOT)
    from machine_learning_files import api   # imported, not edited

    base = Path(published["dir"])
    pointer = api._read_pointer(base)
    df, info = api._load_cloud_store(base, pointer)     # path check + sha256 verification
    assert info == {"source": "cloud", "run_id": RUN_ID, "sha256": pointer["store_sha256"]}
    assert df["timestamp"].max() == pd.Timestamp("2026-01-01")


def test_the_tracked_store_is_untouched(published):
    assert published["tracked_sha_after"] == TRACKED_SHA
    assert sha(TRACKED.read_bytes()) == TRACKED_SHA


def test_a_rerun_is_unchanged(published, tmp_path):
    bucket = copy_bucket(published["dir"], tmp_path)
    store = LocalStorage(bucket)
    before = snapshot(store)
    builder = Builder(None)                      # would fail if it were reached

    assert run(bucket, "--skip-fetch", builder=builder, run_id="never") == 0

    assert builder.calls == 0
    assert snapshot(store) == before             # no object written, not even a gate.json


def test_force_rebuilds_but_identical_content_is_not_republished(published, tmp_path, monkeypatch, candidate):
    stub_gate(monkeypatch)
    bucket = copy_bucket(published["dir"], tmp_path)
    store = LocalStorage(bucket)
    pointer_before = store.read_bytes("processed/serving.json")
    builder = Builder(candidate)

    assert run(bucket, "--skip-fetch", "--force", builder=builder, run_id="forced") == 0

    assert builder.calls == 1
    assert store.read_bytes("processed/serving.json") == pointer_before     # same bytes, same generation
    assert not store.list("processed/runs/forced/feature_store")
    assert store.read_bytes("processed/runs/forced/gate.json") is not None


def test_new_content_is_published_and_the_pointer_moves(published, tmp_path, monkeypatch, candidate):
    stub_gate(monkeypatch)
    bucket = copy_bucket(published["dir"], tmp_path)
    store = LocalStorage(bucket)
    store.write_bytes("raw/bart/Ridership_202502.xlsx", b"a new workbook", if_generation_match=0)
    plus_feb = add_month(candidate, "2026-02-01", 1.02)

    assert run(bucket, "--skip-fetch", builder=Builder(plus_feb), run_id="second") == 0

    pointer = pointer_of(store)
    assert pointer["run_id"] == "second"
    assert pointer["input_fingerprint"] == input_fingerprint(store.list("raw/"))
    assert store.read_bytes(pointer["store_object"]) is not None
    # The first run's outputs are write-once and still there.
    assert store.read_bytes(f"processed/runs/{RUN_ID}/feature_store.parquet") is not None


# ── the gate guards the pointer ───────────────────────────────────────────────

def test_a_gate_failure_writes_gate_json_and_leaves_no_pointer(tmp_path, candidate):
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    tampered = candidate.copy()
    tampered.loc[tampered.index[0], "ridership"] += 1.0       # one tracked cell moved

    assert run(bucket, "--skip-fetch", builder=Builder(tampered)) == 1

    gate = json.loads(store.read_bytes(f"processed/runs/{RUN_ID}/gate.json")[0])
    assert gate["passed"] is False
    assert {f["check"] for f in gate["failures"]} == {"ridership_exact"}
    assert store.read_bytes("processed/serving.json") is None
    assert [o.name for o in store.list("processed/")] == [f"processed/runs/{RUN_ID}/gate.json"]


def test_a_gate_failure_leaves_an_existing_pointer_untouched(published, tmp_path, candidate):
    bucket = copy_bucket(published["dir"], tmp_path)
    store = LocalStorage(bucket)
    before = store.read_bytes("processed/serving.json")
    dropped = candidate[~((candidate["station_id"] == "EM") & (candidate["timestamp"] == "2026-01-01"))]

    assert run(bucket, "--skip-fetch", "--force", builder=Builder(dropped), run_id="bad") == 1

    assert store.read_bytes("processed/serving.json") == before
    assert json.loads(store.read_bytes("processed/runs/bad/gate.json")[0])["passed"] is False
    assert not store.list("processed/runs/bad/feature_store")


def test_a_month_after_the_last_closed_month_fails_the_gate(tmp_path, candidate):
    """now is 2026-10-28, so September 2026 is the last month that may publish."""
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    assert run(bucket, "--skip-fetch", builder=Builder(add_month(candidate, "2026-10-01"))) == 1
    gate = json.loads(store.read_bytes(f"processed/runs/{RUN_ID}/gate.json")[0])
    assert {f["check"] for f in gate["failures"]} == {"no_future_month"}
    assert gate["last_closed_month"] == "2026-09-30"


def test_dropping_a_served_month_fails_the_gate(published, tmp_path, monkeypatch, tracked):
    bucket = copy_bucket(published["dir"], tmp_path)
    store = LocalStorage(bucket)
    store.write_bytes("raw/bart/Ridership_202502.xlsx", b"x", if_generation_match=0)   # new inputs
    before = store.read_bytes("processed/serving.json")
    # The tracked store alone has no 2026-01, which the served store does.
    assert run(bucket, "--skip-fetch", builder=Builder(tracked), run_id="shrunk") == 1
    gate = json.loads(store.read_bytes("processed/runs/shrunk/gate.json")[0])
    assert {f["check"] for f in gate["failures"]} == {"served_months_retained"}
    assert store.read_bytes("processed/serving.json") == before


# ── races ─────────────────────────────────────────────────────────────────────

def test_a_lost_race_exits_3_and_keeps_the_other_pointer(tmp_path, monkeypatch, candidate):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    other = json.dumps({"run_id": "other", "store_object": "processed/runs/other/feature_store.parquet",
                                "store_sha256": "0" * 64}).encode()

    def another_execution_publishes():
        store.write_bytes("processed/serving.json", other, if_generation_match=0)

    assert run(bucket, "--skip-fetch", builder=Builder(candidate, hook=another_execution_publishes)) == 3

    assert store.read_bytes("processed/serving.json")[0] == other
    # This execution's run outputs exist but nothing points at them.
    assert store.read_bytes(f"processed/runs/{RUN_ID}/gate.json") is not None


def test_a_race_against_an_existing_pointer_also_exits_3(published, tmp_path, monkeypatch, candidate):
    stub_gate(monkeypatch)
    bucket = copy_bucket(published["dir"], tmp_path)
    store = LocalStorage(bucket)
    store.write_bytes("raw/bart/Ridership_202502.xlsx", b"x", if_generation_match=0)
    plus_feb = add_month(candidate, "2026-02-01", 1.02)
    rival = store.read_bytes("processed/serving.json")[0]

    def rival_publishes():
        store.write_bytes("processed/serving.json", rival, if_generation_match=None)   # new generation

    assert run(bucket, "--skip-fetch", builder=Builder(plus_feb, hook=rival_publishes), run_id="late") == 3
    assert store.read_bytes("processed/serving.json")[0] == rival


def test_the_pointer_is_written_last(tmp_path, monkeypatch, candidate):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    inner = seed(bucket)
    writes = []

    class Recording:
        def __getattr__(self, attr):
            return getattr(inner, attr)

        def upload(self, src, name, **kw):
            writes.append(name)
            return inner.upload(src, name, **kw)

        def write_bytes(self, name, data, **kw):
            writes.append(name)
            return inner.write_bytes(name, data, **kw)

    monkeypatch.setattr(cloud_ingest, "open_store", lambda uri: Recording())
    assert run(bucket, "--skip-fetch", builder=Builder(candidate)) == 0
    assert writes == [f"processed/runs/{RUN_ID}/gate.json",
                      f"processed/runs/{RUN_ID}/feature_store.parquet",
                      f"processed/runs/{RUN_ID}/manifest.json",
                      "processed/serving.json"]


def test_a_garbage_pointer_is_replaced_under_its_generation(tmp_path, monkeypatch, candidate):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    store.write_bytes("processed/serving.json", b"{not json", if_generation_match=0)
    assert run(bucket, "--skip-fetch", builder=Builder(candidate)) == 0
    assert pointer_of(store)["run_id"] == RUN_ID


# ── fetch ─────────────────────────────────────────────────────────────────────

class OkWeather:
    def get_historical(self, lat, lng, start, end, timezone="America/Los_Angeles"):
        hours = ((end - start).days + 1) * 24
        return pd.DataFrame({"timestamp": pd.date_range(start, periods=hours, freq="h"),
                             "temp_f": 60.0, "precip_in": 0.0, "precip_mm": 0.0, "windspeed_mph": 5.0,
                             "cloud_cover_pct": 1.0, "humidity_pct": 2.0, "weather_code": 0,
                             "is_raining": False, "lat": lat, "lng": lng})


class DownWeather:
    def get_historical(self, *a, **k):
        raise RuntimeError("Open-Meteo is down")


class DownNHL:
    def get_schedule(self, *a, **k):
        raise RuntimeError("NHL API is down")


class OkNHL:
    def get_schedule(self, team, start, end):
        d = dt.date(2026, 2, 3)
        ts = pd.Timestamp("2026-02-03 19:00", tz="America/Los_Angeles")
        return pd.DataFrame([{"game_id": 1, "timestamp_start": ts, "timestamp_end": ts, "event_name": "x",
                              "event_type": "NHL Hockey", "venue": "sap_center", "is_sharks_game": True,
                              "home_or_away": "home", "game_type": 2, "season": "20252026"}])


def test_fetched_objects_join_the_inputs_and_the_fingerprint(tmp_path, monkeypatch, candidate):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    store = seed(bucket)

    code = run(bucket, builder=Builder(candidate), weather_client=OkWeather(), nhl_client=OkNHL())

    assert code == 0
    raw = [o.name for o in store.list("raw/")]
    assert "raw/weather/weather_all_stations_2026-01-01_2026-09-30.parquet" in raw
    assert "raw/events/events_2026-01-01_2026-09-30.parquet" in raw
    manifest = json.loads(store.read_bytes(f"processed/runs/{RUN_ID}/manifest.json")[0])
    assert {r["status"] for r in manifest["fetch"]} == {"written"}
    assert len(manifest["inputs"]) == len(RAW) + 2
    # Tomorrow's run fetches nothing new, so the fingerprint holds: unchanged.
    again = Builder(None)
    assert run(bucket, builder=again, weather_client=OkWeather(), nhl_client=OkNHL(), run_id="t2") == 0
    assert again.calls == 0


def test_a_fetch_failure_exits_2_but_the_rest_still_publishes(tmp_path, monkeypatch, candidate):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    builder = Builder(candidate)

    assert run(bucket, builder=builder, weather_client=DownWeather(), nhl_client=OkNHL()) == 2

    assert builder.calls == 1
    assert pointer_of(store)["run_id"] == RUN_ID                       # published anyway
    assert [o.name for o in store.list("raw/weather/")] == [
        "raw/weather/weather_all_stations_2024-01-01_2025-12-31.parquet"]   # the failed fetch wrote nothing
    assert "raw/events/events_2026-01-01_2026-09-30.parquet" in [o.name for o in store.list("raw/events/")]


def test_a_gate_failure_outranks_a_fetch_failure(tmp_path, monkeypatch, candidate):
    stub_gate(monkeypatch, passed=False)
    bucket = tmp_path / "bucket"
    seed(bucket)
    assert run(bucket, builder=Builder(candidate), weather_client=DownWeather(), nhl_client=OkNHL()) == 1


def test_a_fetch_failure_with_unchanged_inputs_still_exits_2(published, tmp_path):
    bucket = copy_bucket(published["dir"], tmp_path)
    assert run(bucket, builder=Builder(None), weather_client=DownWeather(), nhl_client=DownNHL()) == 2


# ── dry run, pins, config ─────────────────────────────────────────────────────

def test_dry_run_writes_nothing(tmp_path, monkeypatch, candidate, capsys):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    before = snapshot(store)

    code = run(bucket, "--dry-run", builder=Builder(candidate), weather_client=OkWeather(), nhl_client=OkNHL())

    assert code == 0
    assert snapshot(store) == before                    # no fetch, gate.json, run or pointer object
    summary = json.loads(capsys.readouterr().out)
    assert summary["dry_run"] is True and summary["gate_passed"] is True and summary["published"] is False
    assert {r["status"] for r in summary["fetch"]} == {"dry-run"}


def test_a_changed_pinned_input_fails_before_the_build(tmp_path, candidate):
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    store.write_bytes("raw/bart/Ridership 2024.zip", b"someone replaced this", if_generation_match=None)
    builder = Builder(candidate)

    assert run(bucket, "--skip-fetch", builder=builder) == 1

    assert builder.calls == 0
    assert store.list("processed/") == []


def test_a_missing_pinned_input_fails_before_the_build(tmp_path, candidate):
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    store.delete("raw/events/events_2024-01-01_2025-12-31.parquet")
    builder = Builder(candidate)
    assert run(bucket, "--skip-fetch", builder=builder) == 1
    assert builder.calls == 0


def test_a_builder_failure_exits_1(tmp_path):
    bucket = tmp_path / "bucket"
    store = seed(bucket)

    def boom(workdir):
        raise RuntimeError("merge exploded")

    assert run(bucket, "--skip-fetch", builder=boom) == 1
    assert store.list("processed/") == []


def test_no_bucket_is_exit_1_not_argparse_2(monkeypatch):
    cfg = make_cfg()
    cfg.pop("bucket")
    assert main(["--skip-fetch"], cfg=cfg) == 1
    with pytest.raises(SystemExit) as e:
        main(["--no-such-flag"], cfg=cfg)
    assert e.value.code == 1


def test_the_bucket_comes_from_the_env_and_a_bare_name_is_a_gs_bucket(monkeypatch):
    args = types.SimpleNamespace(bucket=None)
    monkeypatch.setenv("INGEST_BUCKET", "my-bucket")
    assert cloud_ingest._bucket_uri(args, {"bucket": "gs://other"}) == "gs://my-bucket"
    monkeypatch.delenv("INGEST_BUCKET")
    assert cloud_ingest._bucket_uri(args, {"bucket": "gs://other"}) == "gs://other"
    args.bucket = "file:///x"
    assert cloud_ingest._bucket_uri(args, {}) == "file:///x"


def test_ingest_yaml_matches_data_manifest():
    cfg = cloud_ingest.load_config()
    pinned = cfg["pinned_inputs"]
    assert len(pinned) == 20 and all(re.fullmatch(r"[0-9a-f]{64}", v) for v in pinned.values())
    assert cfg["fetch_floor"] == "2026-01-01" and cfg["archive_lag_days"] == 7
    assert cfg["gate"]["expected_stations"] == 50 and cfg["gate"]["covariate_rtol"] == 1e-9
    assert cfg["gate"]["sarima_backtest"] == {"as_of": "2025-06-30", "wape_pct": 3.21}
    assert cfg["serving_pointer"] == "processed/serving.json" and cfg["schedule"] == "15 3 * * *"
    assert cfg["bucket"].startswith("gs://")
    assert (REPO_ROOT / cfg["gate"]["tracked_store"]).exists()

    manifest = (REPO_ROOT / "data" / "MANIFEST.md").read_text()
    rows = re.findall(r"`([^`]+\.(?:zip|parquet))` \|[^|]*\|?[^`]*`([0-9a-f]{64})`", manifest)
    from_manifest = {name: h for name, h in rows}
    in_manifest = 0
    for obj, h in pinned.items():
        base = obj.rsplit("/", 1)[1]
        if base in from_manifest:
            assert from_manifest[base] == h, f"{obj} differs from data/MANIFEST.md"
            in_manifest += 1
    assert in_manifest == 8      # 4 zips + 4 covariate archives; the 12 loose 2025 workbooks are not listed there


def test_fingerprint_is_order_independent_and_generation_sensitive():
    t = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    a, b = ObjInfo("raw/a", 1, t, 1), ObjInfo("raw/b", 2, t, 1)
    assert input_fingerprint([a, b]) == input_fingerprint([b, a])
    assert input_fingerprint([a, b]) != input_fingerprint([a, ObjInfo("raw/b", 3, t, 1)])
    assert input_fingerprint([a, b]) != input_fingerprint([a])
    assert input_fingerprint([]) == hashlib.sha256(b"").hexdigest()


# ── staging, mtimes and the merge_pipeline paths ──────────────────────────────

def weather_file(store, name, temp, *, mtime_ns):
    buf = io.BytesIO()
    pd.DataFrame({"timestamp": [pd.Timestamp("2026-01-05 00:00")], "station": ["a"], "temp_f": [temp],
                  "precip_mm": [0.0]}).to_parquet(buf, index=False)
    store.write_bytes(name, buf.getvalue(), if_generation_match=None)
    path = store.root / name
    os.utime(path, ns=(mtime_ns, mtime_ns))


@pytest.mark.parametrize("newer", ["lexically_later", "lexically_earlier"])
def test_overlapping_weather_files_the_later_updated_value_wins(tmp_path, newer):
    """Staging carries `updated` onto mtime and merge_pipeline.load_weather sorts
    by mtime before de-duplicating, whatever the file names say."""
    store = LocalStorage(tmp_path / "bucket")
    early, late = 1_700_000_000_000_000_000, 1_800_000_000_000_000_000
    first = "raw/weather/weather_all_stations_2026-01-01_2026-02-28.parquet"     # sorts first
    second = "raw/weather/weather_all_stations_2026-01-01_2026-09-30.parquet"    # sorts second
    if newer == "lexically_later":
        weather_file(store, first, 10.0, mtime_ns=early)
        weather_file(store, second, 99.0, mtime_ns=late)
        expected = 99.0
    else:
        weather_file(store, first, 10.0, mtime_ns=late)
        weather_file(store, second, 99.0, mtime_ns=early)
        expected = 10.0

    workdir = tmp_path / "work"
    staged = stage_inputs(store, workdir)
    assert {o.name for o in staged} == {first, second}
    assert (workdir / first).stat().st_mtime_ns == (late if newer == "lexically_earlier" else early)

    from machine_learning_files import merge_pipeline
    with merge_pipeline_paths(workdir):
        df = merge_pipeline.load_weather("15min", {})
    assert len(df) == 1 and df["temp_f"].iloc[0] == expected


def test_staging_reports_the_generation_it_actually_downloaded(tmp_path):
    store = seed(tmp_path / "bucket")
    staged = stage_inputs(store, tmp_path / "work")
    assert sorted((o.name, o.generation) for o in staged) == sorted(snapshot(store))
    assert input_fingerprint(staged) == input_fingerprint(store.list("raw/"))


def test_an_object_that_vanishes_while_staging_is_a_staging_error_not_a_race(tmp_path):
    inner = seed(tmp_path / "bucket")

    class Vanishing:
        def list(self, prefix=""):
            return inner.list(prefix)

        def download(self, name, dest):
            raise FileNotFoundError(f"no such object: {name}")

    with pytest.raises(IngestError, match="staging failed"):
        stage_inputs(Vanishing(), tmp_path / "work")


def _fake_bart_months(workdir: Path):
    """Stand-in for the xlsx conversion: three months of two stations in the
    parquet layout bart_od_from_xlsx writes."""
    out = workdir / "raw" / "transit" / "bart"
    out.mkdir(parents=True, exist_ok=True)
    for month in (1, 2, 3):
        rows = []
        for origin, name in (("EM", "Embarcadero"), ("MB", "Millbrae")):
            for dest in ("EM", "MB"):
                rows.append({"period": pd.Timestamp(2026, month, 1), "year": 2026, "month": month,
                             "day_type": "Total Trips", "origin": origin, "origin_name": name,
                             "destination": dest, "destination_name": dest, "riders": 100.0 * month})
        pd.DataFrame(rows).to_parquet(out / f"bart_od_2026_{month:02d}.parquet", index=False)


def test_the_default_build_runs_real_merge_pipeline_inside_the_workdir(tmp_path, monkeypatch):
    from machine_learning_files import merge_pipeline as mp

    monkeypatch.setattr(cloud_ingest, "_convert_bart", _fake_bart_months)
    before = {k: getattr(mp, k) for k in ("RAW_DIR", "PROCESSED_DIR", "CONFIG_PATH", "MODEL_CONFIG_PATH")}
    cwd_listing = sorted(p.name for p in (REPO_ROOT / "data" / "processed").iterdir())
    workdir = tmp_path / "work"
    workdir.mkdir()

    df = build_candidate(workdir)                      # builder=None: the default path

    assert sorted(df["station_id"].unique()) == ["EM", "MB"] and len(df) == 6
    assert (workdir / "processed" / "feature_store.parquet").exists()
    assert not (workdir / "processed" / "splits").exists()           # build_feature_store, not main()
    assert {k: getattr(mp, k) for k in before} == before            # globals restored
    assert sorted(p.name for p in (REPO_ROOT / "data" / "processed").iterdir()) == cwd_listing
    assert sha(TRACKED.read_bytes()) == TRACKED_SHA


def test_merge_pipeline_paths_are_restored_after_a_failing_builder(tmp_path):
    from machine_learning_files import merge_pipeline as mp

    before = {k: getattr(mp, k) for k in ("RAW_DIR", "PROCESSED_DIR", "CONFIG_PATH", "MODEL_CONFIG_PATH")}
    seen = {}

    def boom(workdir):
        seen.update({k: getattr(mp, k) for k in before})
        raise RuntimeError("builder failed")

    with pytest.raises(RuntimeError):
        build_candidate(tmp_path, boom)

    wd = tmp_path.resolve()
    assert seen["RAW_DIR"] == wd / "raw" and seen["PROCESSED_DIR"] == wd / "processed"
    assert seen["CONFIG_PATH"] == wd / "configs" / "sources.yaml"
    assert seen["MODEL_CONFIG_PATH"] == wd / "configs" / "model.yaml"
    assert {k: getattr(mp, k) for k in before} == before


def test_an_empty_build_is_an_error(tmp_path):
    with pytest.raises(IngestError, match="empty"):
        build_candidate(tmp_path, lambda wd: pd.DataFrame())


def test_a_workbook_that_does_not_convert_fails_the_build(tmp_path, monkeypatch):
    """bart_od_from_xlsx.build() skips a workbook it cannot parse; the job must
    not turn that into a store silently missing a month."""
    pytest.importorskip("openpyxl")
    bart = tmp_path / "raw" / "bart"
    bart.mkdir(parents=True)
    pd.DataFrame({"a": [1]}).to_excel(bart / "Ridership_202601.xlsx", index=False)   # no OD sheet
    with pytest.raises(IngestError, match="2026-01"):
        cloud_ingest._convert_bart(tmp_path)
