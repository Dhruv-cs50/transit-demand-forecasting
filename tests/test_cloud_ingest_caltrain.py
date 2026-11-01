"""
tests/test_cloud_ingest_caltrain.py
───────────────────────────────────
Caltrain Task 5: the cloud ingestion job also stages raw/caltrain/awr_monthly.csv
(uploaded by hand after each Caltrain report), checks it, rebuilds the Caltrain
store with build_caltrain_store and publishes it beside the BART store.

The ruling that shapes every test here: the BART pipeline is live and daily, so
Caltrain must never block it.

  absent    -> skipped silently; the BART run is exactly what it was.
  present, passes the checks -> processed/runs/<id>/caltrain_store.parquet, listed
            in manifest.json.
  present, fails -> BART still publishes; no Caltrain artifact; manifest.json
            records {"caltrain": {"status": "rejected", "reason": ...}}; an ERROR
            line names the reason; the exit code follows BART only.

The checks: every month of the committed series is present with an identical value
unless the new row carries `revised_from`; months strictly increase; no month is
after the last closed month.

Same harness as tests/test_cloud_ingest.py: a LocalStorage directory for the
bucket, an injected builder for the BART rebuild, no GCP, no network.

Run from the repository root:
    python -m pytest -q tests/test_cloud_ingest_caltrain.py
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from pathlib import Path

import pandas as pd
import pytest

from machine_learning_files import cloud_ingest
from machine_learning_files.cloud_store import LocalStorage
from test_cloud_ingest import (   # the sibling suite's harness (tests/ is on sys.path)
    GIT_SHA,
    NOW,
    RUN_ID,
    TRACKED,
    Builder,
    add_month,
    pointer_of,
    run,
    seed,
    stub_gate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_CSV = REPO_ROOT / "data" / "caltrain" / "awr_monthly.csv"
RAW_CSV = "raw/caltrain/awr_monthly.csv"
RUN_DIR = f"processed/runs/{RUN_ID}/"
CT_STORE = RUN_DIR + "caltrain_store.parquet"

# The manifest keys and the run's objects before Caltrain existed.
LEGACY_MANIFEST_KEYS = {"run_id", "git_sha", "created_at", "input_fingerprint", "inputs", "store", "gate",
                        "last_closed_month", "tracked_store_sha256", "fetch", "runtime"}
LEGACY_RUN_OBJECTS = [RUN_DIR + "feature_store.parquet", RUN_DIR + "gate.json", RUN_DIR + "manifest.json"]

pytestmark = pytest.mark.filterwarnings("ignore:Too few observations:UserWarning")


# ── helpers ───────────────────────────────────────────────────────────────────

def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture(scope="module")
def candidate() -> pd.DataFrame:
    tracked = pd.read_parquet(TRACKED)
    tracked["timestamp"] = pd.to_datetime(tracked["timestamp"])
    return add_month(tracked, "2026-01-01")      # passes the real BART gate (test_cloud_ingest)


def committed() -> pd.DataFrame:
    return pd.read_csv(COMMITTED_CSV, dtype={"month": str})


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def good_csv() -> bytes:
    """The committed series plus one new closed month (NOW is 2026-10-28, so 2026-09 is the last)."""
    df = committed()
    new = {"month": "2026-09", "awr": 50123, "report_url": "https://example.test/sept", "sha256": "0" * 64,
           "revised_from": float("nan")}
    return csv_bytes(pd.concat([df, pd.DataFrame([new])], ignore_index=True))


def put_csv(store: LocalStorage, data: bytes) -> None:
    store.write_bytes(RAW_CSV, data, if_generation_match=None)


def run_names(store: LocalStorage) -> list[str]:
    return [o.name for o in store.list(RUN_DIR)]


def manifest_of(store: LocalStorage, run_id: str = RUN_ID) -> dict:
    return json.loads(store.read_bytes(f"processed/runs/{run_id}/manifest.json")[0])


def gate_of(store: LocalStorage, run_id: str = RUN_ID) -> dict:
    return json.loads(store.read_bytes(f"processed/runs/{run_id}/gate.json")[0])


def caltrain_errors(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.levelno >= logging.ERROR and "caltrain" in r.getMessage().lower()]


def bart_published(store: LocalStorage, builder: Builder) -> None:
    assert builder.calls == 1
    assert pointer_of(store)["run_id"] == RUN_ID
    assert store.read_bytes(RUN_DIR + "feature_store.parquet") is not None


# ── a good file is staged, checked, rebuilt and published ─────────────────────

def test_caltrain_csv_staged_and_published(tmp_path, monkeypatch, candidate, caplog):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    data = good_csv()
    put_csv(store, data)
    builder = Builder(candidate)

    assert run(bucket, "--skip-fetch", builder=builder) == 0

    bart_published(store, builder)
    assert run_names(store) == sorted(LEGACY_RUN_OBJECTS + [CT_STORE])
    ct = pd.read_parquet(io.BytesIO(store.read_bytes(CT_STORE)[0]))
    assert ct["station_id"].unique().tolist() == ["CALTRAIN_SYSTEM"]
    assert ct["timestamp"].max() == pd.Timestamp("2026-09-01")
    assert ct.loc[ct["timestamp"] == "2026-09-01", "ridership"].item() == 50123.0
    assert len(ct) == 69          # the 92 committed months + 2026-09, less the 24 COVID months

    manifest = manifest_of(store)
    entry = manifest["caltrain"]
    assert entry["status"] == "published"
    assert entry["object"] == CT_STORE
    assert entry["sha256"] == sha(store.read_bytes(CT_STORE)[0])
    assert entry["rows"] == len(ct)
    assert entry["months"][-1] == "2026-09"
    assert entry["input_sha256"] == sha(data)
    # The CSV is one of the run's inputs, so a changed file changes the fingerprint.
    assert RAW_CSV in {i["name"] for i in manifest["inputs"]}
    assert pointer_of(store)["input_fingerprint"] == cloud_ingest.input_fingerprint(store.list("raw/"))
    assert not caltrain_errors(caplog)


def test_the_pointer_is_still_written_last_with_caltrain(tmp_path, monkeypatch, candidate):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    inner = seed(bucket)
    put_csv(inner, good_csv())
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
    assert writes == [RUN_DIR + "gate.json", RUN_DIR + "feature_store.parquet", CT_STORE,
                      RUN_DIR + "manifest.json", "processed/serving.json"]


def test_a_revised_month_carrying_revised_from_is_accepted(tmp_path, monkeypatch, candidate):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    df = committed()
    i = df.index[df["month"] == "2025-03"][0]
    old = int(df.loc[i, "awr"])
    df.loc[i, "awr"] = old + 100
    df.loc[i, "revised_from"] = old
    put_csv(store, csv_bytes(df))

    assert run(bucket, "--skip-fetch", builder=Builder(candidate)) == 0

    assert manifest_of(store)["caltrain"]["status"] == "published"
    ct = pd.read_parquet(io.BytesIO(store.read_bytes(CT_STORE)[0]))
    assert ct.loc[ct["timestamp"] == "2025-03-01", "ridership"].item() == old + 100


# ── a bad file is rejected: BART is not blocked ───────────────────────────────

def _swap_two_months() -> bytes:
    df = committed()
    a, b = df.index[df["month"] == "2025-05"][0], df.index[df["month"] == "2025-06"][0]
    rows = df.copy()
    rows.iloc[a], rows.iloc[b] = df.iloc[b].copy(), df.iloc[a].copy()
    return csv_bytes(rows)


def _changed_history() -> bytes:
    df = committed()
    df.loc[df["month"] == "2025-03", "awr"] += 1       # a different value, no revised_from
    return csv_bytes(df)


def _missing_month() -> bytes:
    df = committed()
    return csv_bytes(df[df["month"] != "2024-05"])


def _future_month() -> bytes:
    df = committed()
    new = {"month": "2026-10", "awr": 50000, "report_url": "x", "sha256": "0" * 64, "revised_from": float("nan")}
    return csv_bytes(pd.concat([df, pd.DataFrame([new])], ignore_index=True))   # October is not closed yet


BAD = [
    pytest.param(_swap_two_months, "strictly increasing", id="non-increasing-month"),
    pytest.param(_changed_history, "2025-03", id="changed-history"),
    pytest.param(_missing_month, "2024-05", id="missing-committed-month"),
    pytest.param(_future_month, "2026-10", id="month-after-last-closed"),
    pytest.param(lambda: b"this,is\nnot,a,series\n\x00\x01", "", id="garbage"),
    pytest.param(lambda: b"month,awr\n2019-01,not-a-number\n", "", id="non-numeric-awr"),
    pytest.param(lambda: b"", "", id="empty-file"),
]


@pytest.mark.parametrize("make_bad,needle", BAD)
def test_a_bad_caltrain_file_is_rejected_and_bart_still_publishes(
        tmp_path, monkeypatch, candidate, caplog, make_bad, needle):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    put_csv(store, make_bad())
    builder = Builder(candidate)

    with caplog.at_level(logging.ERROR):
        code = run(bucket, "--skip-fetch", builder=builder)

    assert code == 0                                       # BART's result only
    bart_published(store, builder)
    assert run_names(store) == sorted(LEGACY_RUN_OBJECTS)      # no Caltrain artifact
    assert store.list(RUN_DIR + "caltrain_store") == []
    entry = manifest_of(store)["caltrain"]
    assert entry["status"] == "rejected"
    assert needle in entry["reason"] and entry["reason"].strip()
    assert set(entry) == {"status", "reason"}
    errors = caltrain_errors(caplog)
    assert errors and entry["reason"] in errors[0]
    assert gate_of(store)["caltrain"]["status"] == "rejected"


def test_caltrain_rejected_does_not_block_bart(tmp_path, monkeypatch, candidate, caplog):
    """The ruling in one test: a rejected file, a BART run that passes. Same
    BART bytes and the same pointer as a run with no Caltrain file at all."""
    stub_gate(monkeypatch)
    clean_bucket, bad_bucket = tmp_path / "clean", tmp_path / "bad"
    clean = seed(clean_bucket)
    bad = seed(bad_bucket)
    put_csv(bad, _changed_history())

    with caplog.at_level(logging.ERROR):
        assert run(clean_bucket, "--skip-fetch", builder=Builder(candidate)) == 0
        assert run(bad_bucket, "--skip-fetch", builder=Builder(candidate)) == 0

    assert clean.read_bytes(RUN_DIR + "feature_store.parquet")[0] == bad.read_bytes(RUN_DIR + "feature_store.parquet")[0]
    p_clean, p_bad = pointer_of(clean), pointer_of(bad)
    assert p_clean["store_sha256"] == p_bad["store_sha256"]
    assert p_bad["store_object"] == RUN_DIR + "feature_store.parquet"
    assert manifest_of(bad)["caltrain"]["status"] == "rejected"
    assert len(caltrain_errors(caplog)) == 1                 # only the bad run logged one


def test_a_failing_bart_gate_still_exits_1_with_a_good_caltrain_file(tmp_path, candidate):
    """The exit code follows BART: a BART gate failure is not softened by Caltrain,
    and nothing Caltrain is published without a BART publish."""
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    put_csv(store, good_csv())
    tampered = candidate.copy()
    tampered.loc[tampered.index[0], "ridership"] += 1.0

    assert run(bucket, "--skip-fetch", builder=Builder(tampered)) == 1

    assert store.read_bytes("processed/serving.json") is None
    assert store.list(RUN_DIR + "caltrain_store") == []
    assert [o.name for o in store.list("processed/")] == [RUN_DIR + "gate.json"]


def test_a_caltrain_publish_failure_does_not_block_bart(tmp_path, monkeypatch, candidate, caplog):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    inner = seed(bucket)
    put_csv(inner, good_csv())

    class FlakyCaltrain:
        def __getattr__(self, attr):
            return getattr(inner, attr)

        def upload(self, src, name, **kw):
            if name.endswith("caltrain_store.parquet"):
                raise OSError("simulated outage")
            return inner.upload(src, name, **kw)

    monkeypatch.setattr(cloud_ingest, "open_store", lambda uri: FlakyCaltrain())
    with caplog.at_level(logging.ERROR):
        assert run(bucket, "--skip-fetch", builder=Builder(candidate)) == 0

    assert pointer_of(inner)["run_id"] == RUN_ID
    entry = manifest_of(inner)["caltrain"]
    assert entry["status"] == "rejected" and "simulated outage" in entry["reason"]
    assert caltrain_errors(caplog)


# ── absent: skipped silently, BART untouched ──────────────────────────────────

def test_caltrain_absent_skips_and_bart_identical(tmp_path, monkeypatch, candidate, caplog):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    builder = Builder(candidate)

    with caplog.at_level(logging.INFO):
        assert run(bucket, "--skip-fetch", builder=builder) == 0

    bart_published(store, builder)
    # Exactly the objects, manifest keys and log lines the job had before Caltrain.
    assert [o.name for o in store.list("processed/")] == sorted(LEGACY_RUN_OBJECTS + ["processed/serving.json"])
    assert set(manifest_of(store)) == LEGACY_MANIFEST_KEYS
    assert "caltrain" not in gate_of(store)
    assert not [r for r in caplog.records if "caltrain" in r.getMessage().replace(str(bucket), "").lower()]
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_the_bart_store_is_byte_identical_with_and_without_the_caltrain_file(tmp_path, monkeypatch, candidate):
    stub_gate(monkeypatch)
    without, with_ct = tmp_path / "without", tmp_path / "with"
    a, b = seed(without), seed(with_ct)
    put_csv(b, good_csv())

    assert run(without, "--skip-fetch", builder=Builder(candidate)) == 0
    assert run(with_ct, "--skip-fetch", builder=Builder(candidate)) == 0

    name = RUN_DIR + "feature_store.parquet"
    assert a.read_bytes(name)[0] == b.read_bytes(name)[0]
    assert pointer_of(a)["store_sha256"] == pointer_of(b)["store_sha256"]


# ── the BART gate, three cases (real gate) ────────────────────────────────────
# test_bart_gate_unchanged: Caltrain absent, passing and failing give the same BART gate result.

@pytest.fixture(scope="module")
def gate_runs(tmp_path_factory, candidate):
    """One real-gate run each: no Caltrain file, a good one, a bad one."""
    mp = pytest.MonkeyPatch()
    mp.setenv("GIT_SHA", GIT_SHA)
    out = {}
    try:
        for case, data in (("absent", None), ("pass", good_csv()), ("fail", _changed_history())):
            bucket = tmp_path_factory.mktemp(case) / "bucket"
            store = seed(bucket)
            if data is not None:
                put_csv(store, data)
            code = run(bucket, "--skip-fetch", builder=Builder(candidate))
            out[case] = {"code": code, "store": store}
    finally:
        mp.undo()
    return out


def _bart_gate_view(store: LocalStorage) -> dict:
    g = gate_of(store)
    return {"passed": g["passed"], "failures": g["failures"], "checks": g["checks"],
            "store_sha256": g["store_sha256"], "last_closed_month": g["last_closed_month"]}


@pytest.mark.parametrize("case", ["absent", "pass", "fail"])
def test_bart_gate_unchanged(gate_runs, case):
    got, base = gate_runs[case], gate_runs["absent"]
    assert got["code"] == base["code"] == 0
    assert _bart_gate_view(got["store"]) == _bart_gate_view(base["store"])
    assert _bart_gate_view(got["store"])["passed"] is True
    assert pointer_of(got["store"])["store_sha256"] == pointer_of(base["store"])["store_sha256"]


# ── the new month is the whole point: later runs ──────────────────────────────

def test_a_new_caltrain_month_publishes_even_when_bart_is_unchanged(tmp_path, monkeypatch, candidate):
    """Uploading the next report's CSV changes the raw fingerprint but not the
    BART store. The run must still publish, or the month would never go live."""
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    assert run(bucket, "--skip-fetch", builder=Builder(candidate)) == 0       # first run: BART only
    assert "caltrain" not in manifest_of(store)

    put_csv(store, good_csv())
    assert run(bucket, "--skip-fetch", builder=Builder(candidate), run_id="second") == 0

    assert pointer_of(store)["run_id"] == "second"
    entry = manifest_of(store, "second")["caltrain"]
    assert entry["status"] == "published" and entry["object"] == "processed/runs/second/caltrain_store.parquet"
    assert store.read_bytes(entry["object"]) is not None
    assert pointer_of(store)["store_sha256"] == manifest_of(store, RUN_ID)["store"]["sha256"]   # BART bytes same


def test_an_unchanged_caltrain_store_is_not_republished(tmp_path, monkeypatch, candidate):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    put_csv(store, good_csv())
    assert run(bucket, "--skip-fetch", builder=Builder(candidate)) == 0
    before = store.read_bytes("processed/serving.json")

    assert run(bucket, "--skip-fetch", "--force", builder=Builder(candidate), run_id="forced") == 0

    assert store.read_bytes("processed/serving.json") == before
    assert not store.list("processed/runs/forced/caltrain_store")


def test_a_rejected_file_with_unchanged_bart_publishes_nothing_but_is_recorded(tmp_path, monkeypatch,
                                                                               candidate, caplog):
    stub_gate(monkeypatch)
    bucket = tmp_path / "bucket"
    store = seed(bucket)
    assert run(bucket, "--skip-fetch", builder=Builder(candidate)) == 0
    before = store.read_bytes("processed/serving.json")

    put_csv(store, _changed_history())
    with caplog.at_level(logging.ERROR):
        assert run(bucket, "--skip-fetch", builder=Builder(candidate), run_id="later") == 0

    assert store.read_bytes("processed/serving.json") == before        # nothing new to publish
    assert gate_of(store, "later")["caltrain"]["status"] == "rejected"  # but the reason is on record
    assert caltrain_errors(caplog)
