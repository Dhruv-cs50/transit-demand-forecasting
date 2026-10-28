"""
tests/test_cloud_store.py
─────────────────────────
The storage abstraction behind the cloud ingestion job
(machine_learning_files/cloud_store.py, docs/cloud-ingestion-design.md §5).

LocalStorage must behave like the slice of Cloud Storage the job relies on:
integer generations that grow on every write, `if_generation_match`
preconditions (0 = the object must not exist), and an `updated` time that
`download` copies onto the local file's mtime (the loaders sort by mtime
before de-duplicating). The tests run with no google libraries installed;
GcsStorage is exercised against a small in-process fake of
`google.cloud.storage` injected into sys.modules.

Run from the repository root:
    python -m pytest -q tests/test_cloud_store.py
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from machine_learning_files.cloud_store import (
    GcsStorage,
    LocalStorage,
    ObjInfo,
    PreconditionFailed,
    open_store,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path):
    return LocalStorage(tmp_path / "bucket")


# ── LocalStorage: basics ──────────────────────────────────────────────────────

def test_write_then_read_roundtrip(store):
    info = store.write_bytes("a/b.txt", b"hello", if_generation_match=0)
    assert isinstance(info, ObjInfo)
    assert info.name == "a/b.txt"
    assert info.size == 5
    assert isinstance(info.generation, int) and info.generation > 0
    assert info.updated.tzinfo is not None

    data, gen = store.read_bytes("a/b.txt")
    assert data == b"hello"
    assert gen == info.generation


def test_read_missing_returns_none(store):
    assert store.read_bytes("nope") is None


def test_list_by_prefix_is_sorted_and_prefix_not_directory(store):
    for n in ["raw/weather/w.parquet", "raw/bart/b.xlsx", "raw/bart/a.zip", "processed/x"]:
        store.write_bytes(n, b"1", if_generation_match=None)
    assert [o.name for o in store.list("raw/bart/")] == ["raw/bart/a.zip", "raw/bart/b.xlsx"]
    assert [o.name for o in store.list("raw/")] == [
        "raw/bart/a.zip", "raw/bart/b.xlsx", "raw/weather/w.parquet"]
    # GCS prefixes are plain string prefixes, not directories.
    assert [o.name for o in store.list("raw/bart/a")] == ["raw/bart/a.zip"]
    assert [o.name for o in store.list("zzz")] == []
    assert len(store.list("")) == 4
    assert len(store.list()) == 4


def test_list_hides_internal_files(store):
    store.write_bytes("k", b"1", if_generation_match=0)
    names = [o.name for o in store.list("")]
    assert names == ["k"]


def test_upload_and_download(tmp_path, store):
    src = tmp_path / "src.bin"
    src.write_bytes(b"\x00\x01\x02")
    info = store.upload(src, "raw/bart/src.bin")
    assert info.size == 3

    dest = tmp_path / "deep" / "dir" / "out.bin"
    got = store.download("raw/bart/src.bin", dest)
    assert dest.read_bytes() == b"\x00\x01\x02"
    assert got.generation == info.generation


def test_download_missing_raises_file_not_found(tmp_path, store):
    with pytest.raises(FileNotFoundError):
        store.download("nope", tmp_path / "x")


@pytest.mark.parametrize("bad", ["", "/abs", "../escape", "a/../../escape", "a//b"])
def test_rejects_unsafe_object_names(store, bad):
    with pytest.raises(ValueError):
        store.write_bytes(bad, b"x", if_generation_match=None)


# ── LocalStorage: generations and preconditions ───────────────────────────────

def test_generation_increases_on_every_write(store):
    gens = [store.write_bytes("k", str(i).encode(), if_generation_match=None).generation
            for i in range(5)]
    assert gens == sorted(set(gens)), "generations must strictly increase"


def test_generation_increases_even_when_content_is_identical(store):
    g1 = store.write_bytes("k", b"same", if_generation_match=None).generation
    g2 = store.write_bytes("k", b"same", if_generation_match=None).generation
    assert g2 > g1


def test_generation_increases_after_delete_and_recreate(store):
    g1 = store.write_bytes("k", b"1", if_generation_match=0).generation
    store.delete("k")
    g2 = store.write_bytes("k", b"1", if_generation_match=0).generation
    assert g2 > g1


def test_generation_match_zero_means_must_not_exist(store):
    store.write_bytes("k", b"1", if_generation_match=0)
    with pytest.raises(PreconditionFailed):
        store.write_bytes("k", b"2", if_generation_match=0)
    assert store.read_bytes("k")[0] == b"1"


def test_generation_match_must_equal_current(store):
    g1 = store.write_bytes("k", b"1", if_generation_match=0).generation
    with pytest.raises(PreconditionFailed):
        store.write_bytes("k", b"2", if_generation_match=g1 + 1)
    assert store.read_bytes("k") == (b"1", g1)
    g2 = store.write_bytes("k", b"2", if_generation_match=g1).generation
    assert g2 > g1
    # The stale generation can no longer win: this is the lost-race path.
    with pytest.raises(PreconditionFailed):
        store.write_bytes("k", b"3", if_generation_match=g1)
    assert store.read_bytes("k") == (b"2", g2)


def test_nonzero_generation_on_missing_object_fails(store):
    with pytest.raises(PreconditionFailed):
        store.write_bytes("k", b"1", if_generation_match=12345)
    assert store.read_bytes("k") is None


def test_upload_honours_preconditions(tmp_path, store):
    src = tmp_path / "f"
    src.write_bytes(b"1")
    g = store.upload(src, "k", if_generation_match=0).generation
    with pytest.raises(PreconditionFailed):
        store.upload(src, "k", if_generation_match=0)
    with pytest.raises(PreconditionFailed):
        store.upload(src, "k", if_generation_match=g + 1)
    assert store.upload(src, "k", if_generation_match=g).generation > g


def test_write_bytes_requires_precondition_keyword(store):
    # Design §5: `if_generation_match` is keyword-only and has no default on
    # write_bytes, so the "overwrite blindly" case must be spelled out as None.
    with pytest.raises(TypeError):
        store.write_bytes("k", b"1")  # type: ignore[call-arg]


def test_concurrent_creators_exactly_one_wins(store):
    import threading

    results = []

    def go(i):
        try:
            store.write_bytes("serving.json", str(i).encode(), if_generation_match=0)
            results.append("won")
        except PreconditionFailed:
            results.append("lost")

    threads = [threading.Thread(target=go, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("won") == 1 and results.count("lost") == 11


def test_failed_precondition_leaves_no_partial_state(store):
    store.write_bytes("k", b"1", if_generation_match=0)
    with pytest.raises(PreconditionFailed):
        store.write_bytes("k", b"2", if_generation_match=0)
    assert [o.name for o in store.list("")] == ["k"]


# ── LocalStorage: delete ──────────────────────────────────────────────────────

def test_delete_removes_object(store):
    store.write_bytes("a/k", b"1", if_generation_match=0)
    store.delete("a/k")
    assert store.read_bytes("a/k") is None
    assert store.list("") == []


def test_delete_missing_is_a_noop_without_precondition(store):
    store.delete("never-existed")


def test_delete_precondition(store):
    g = store.write_bytes("k", b"1", if_generation_match=0).generation
    with pytest.raises(PreconditionFailed):
        store.delete("k", if_generation_match=g + 1)
    assert store.read_bytes("k") is not None
    store.delete("k", if_generation_match=g)
    assert store.read_bytes("k") is None
    # A precondition on an object that is gone cannot be satisfied.
    with pytest.raises(PreconditionFailed):
        store.delete("k", if_generation_match=g)


# ── LocalStorage: updated and mtime ───────────────────────────────────────────

def test_download_sets_mtime_from_updated(tmp_path, store):
    store.write_bytes("raw/weather/w.parquet", b"data", if_generation_match=0)
    path = store.root / "raw" / "weather" / "w.parquet"
    # Pretend the object was last written long ago.
    old = dt.datetime(2026, 3, 1, 12, 30, 15, 250000, tzinfo=dt.timezone.utc)
    ts = old.timestamp()
    os.utime(path, (ts, ts))

    (info,) = store.list("raw/weather/")
    assert info.updated == old

    dest = tmp_path / "work" / "w.parquet"
    store.download("raw/weather/w.parquet", dest)
    assert dest.stat().st_mtime == pytest.approx(ts, abs=1e-3)


def test_download_orders_files_by_object_updated_not_download_order(tmp_path, store):
    """The loaders sort by mtime; the later-updated object must sort last
    no matter which one was downloaded first."""
    store.write_bytes("raw/weather/x.parquet", b"x", if_generation_match=0)
    store.write_bytes("raw/weather/y.parquet", b"y", if_generation_match=0)
    t_old = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp()
    t_new = dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc).timestamp()
    os.utime(store.root / "raw/weather/x.parquet", (t_new, t_new))   # x is newer
    os.utime(store.root / "raw/weather/y.parquet", (t_old, t_old))

    # Download the newer one first, the older one second.
    store.download("raw/weather/x.parquet", tmp_path / "x.parquet")
    store.download("raw/weather/y.parquet", tmp_path / "y.parquet")
    assert (tmp_path / "y.parquet").stat().st_mtime < (tmp_path / "x.parquet").stat().st_mtime


def test_updated_changes_on_rewrite(store):
    store.write_bytes("k", b"1", if_generation_match=0)
    u1 = store.list("")[0].updated
    store.write_bytes("k", b"2", if_generation_match=None)
    u2 = store.list("")[0].updated
    assert u2 >= u1


def test_seeded_directory_without_any_metadata_is_usable(tmp_path):
    """`--bucket file:///seed` points at a plain directory of files."""
    seed = tmp_path / "seed"
    (seed / "raw" / "bart").mkdir(parents=True)
    (seed / "raw" / "bart" / "Ridership_202601.xlsx").write_bytes(b"xlsx")
    s = LocalStorage(seed)
    (info,) = s.list("raw/")
    assert info.name == "raw/bart/Ridership_202601.xlsx"
    assert info.generation > 0
    data, gen = s.read_bytes(info.name)
    assert data == b"xlsx" and gen == info.generation


def test_generations_are_stable_across_instances(tmp_path):
    root = tmp_path / "b"
    g = LocalStorage(root).write_bytes("k", b"1", if_generation_match=0).generation
    other = LocalStorage(root)
    assert other.read_bytes("k")[1] == g
    assert other.list("")[0].generation == g
    other.write_bytes("k", b"2", if_generation_match=g)


# ── open_store ────────────────────────────────────────────────────────────────

def test_open_store_file_uri(tmp_path):
    s = open_store(f"file://{tmp_path}/b")
    assert isinstance(s, LocalStorage)
    assert s.root == tmp_path / "b"
    s.write_bytes("k", b"1", if_generation_match=0)
    assert (tmp_path / "b" / "k").read_bytes() == b"1"


def test_open_store_gs_uri_is_lazy_and_needs_no_google(monkeypatch):
    monkeypatch.delitem(sys.modules, "google", raising=False)
    s = open_store("gs://my-bucket")
    assert isinstance(s, GcsStorage)
    assert s.bucket_name == "my-bucket"
    assert "google" not in sys.modules, "constructing GcsStorage must not import google"


def test_open_store_gs_uri_with_trailing_slash_or_path(monkeypatch):
    assert open_store("gs://my-bucket/").bucket_name == "my-bucket"
    with pytest.raises(ValueError):
        open_store("gs://my-bucket/sub/prefix")  # prefixes are not supported


@pytest.mark.parametrize("bad", ["", "s3://b", "/just/a/path", "http://x", "gs://"])
def test_open_store_rejects_other_schemes(bad):
    with pytest.raises(ValueError):
        open_store(bad)


# ── no google libraries needed ────────────────────────────────────────────────

def test_localstorage_never_imports_google():
    """Run in a clean interpreter so no other test can have imported it."""
    code = (
        "import sys, tempfile, pathlib\n"
        "from machine_learning_files.cloud_store import LocalStorage, open_store, GcsStorage\n"
        "d = pathlib.Path(tempfile.mkdtemp())\n"
        "s = open_store(f'file://{d}')\n"
        "s.write_bytes('a/b', b'x', if_generation_match=0)\n"
        "s.upload(d / 'a' / 'b', 'c', if_generation_match=0)\n"
        "s.read_bytes('c'); s.list(''); s.download('c', d / 'out'); s.delete('c')\n"
        "GcsStorage('b')\n"
        "assert 'google' not in sys.modules, sorted(m for m in sys.modules if m.startswith('google'))\n"
        "print('ok')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True,
                         text=True, env={**os.environ, "PYTHONPATH": str(REPO_ROOT)})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


# ── GcsStorage against a fake google.cloud.storage ────────────────────────────

class _FakeGoogleError(Exception):
    def __init__(self, code, msg=""):
        super().__init__(f"{code} {msg}")
        self.code = code


class _FakeBlob:
    def __init__(self, bucket, name, generation=None, updated=None, size=None):
        self._bucket, self.name = bucket, name
        self.generation, self.updated, self.size = generation, updated, size

    def _check(self, if_generation_match):
        cur = self._bucket.objects.get(self.name)
        if if_generation_match is None:
            return
        if (if_generation_match == 0 and cur is not None) or (
                if_generation_match != 0 and (cur is None or cur["generation"] != if_generation_match)):
            raise _FakeGoogleError(412, "Precondition Failed")

    def _put(self, data, if_generation_match):
        self._check(if_generation_match)
        self._bucket.counter += 1
        self._bucket.objects[self.name] = {
            "data": data, "generation": self._bucket.counter,
            "updated": dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=self._bucket.counter)}
        o = self._bucket.objects[self.name]
        self.generation, self.updated, self.size = o["generation"], o["updated"], len(data)

    def upload_from_filename(self, filename, if_generation_match=None, **kw):
        self._bucket.calls.append(("upload_from_filename", self.name, if_generation_match))
        self._put(Path(filename).read_bytes(), if_generation_match)

    def upload_from_string(self, data, if_generation_match=None, **kw):
        self._bucket.calls.append(("upload_from_string", self.name, if_generation_match))
        self._put(data, if_generation_match)

    def download_to_filename(self, filename, if_generation_match=None, **kw):
        self._bucket.calls.append(("download_to_filename", self.name, if_generation_match))
        self._check(if_generation_match)
        Path(filename).write_bytes(self._bucket.objects[self.name]["data"])

    def download_as_bytes(self, if_generation_match=None, **kw):
        self._bucket.calls.append(("download_as_bytes", self.name, if_generation_match))
        self._check(if_generation_match)
        return self._bucket.objects[self.name]["data"]

    def delete(self, if_generation_match=None, **kw):
        self._bucket.calls.append(("delete", self.name, if_generation_match))
        if self.name not in self._bucket.objects:
            raise _FakeGoogleError(404, "Not Found")
        self._check(if_generation_match)
        del self._bucket.objects[self.name]


class _FakeBucket:
    def __init__(self):
        self.objects, self.counter, self.calls = {}, 0, []

    def blob(self, name):
        return _FakeBlob(self, name)

    def get_blob(self, name):
        o = self.objects.get(name)
        if o is None:
            return None
        return _FakeBlob(self, name, o["generation"], o["updated"], len(o["data"]))


class _FakeClient:
    bucket_obj = _FakeBucket()

    def bucket(self, name):
        self.bucket_obj.requested = name
        return self.bucket_obj

    def list_blobs(self, bucket_name, prefix=None):
        b = self.bucket_obj
        return [b.get_blob(n) for n in sorted(b.objects) if n.startswith(prefix or "")]


@pytest.fixture
def gcs(monkeypatch):
    _FakeClient.bucket_obj = _FakeBucket()
    google = types.ModuleType("google")
    cloud = types.ModuleType("google.cloud")
    storage = types.ModuleType("google.cloud.storage")
    storage.Client = _FakeClient
    google.cloud, cloud.storage = cloud, storage
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", storage)
    return GcsStorage("bkt"), _FakeClient.bucket_obj


def test_gcs_roundtrip_and_list(gcs, tmp_path):
    s, fake = gcs
    info = s.write_bytes("processed/serving.json", b"{}", if_generation_match=0)
    assert info.generation == 1 and info.size == 2
    assert s.read_bytes("processed/serving.json") == (b"{}", 1)
    assert s.read_bytes("missing") is None
    assert [o.name for o in s.list("processed/")] == ["processed/serving.json"]
    assert fake.requested == "bkt"


def test_gcs_maps_412_to_precondition_failed(gcs, tmp_path):
    s, _ = gcs
    s.write_bytes("k", b"1", if_generation_match=0)
    with pytest.raises(PreconditionFailed):
        s.write_bytes("k", b"2", if_generation_match=0)
    src = tmp_path / "f"
    src.write_bytes(b"3")
    with pytest.raises(PreconditionFailed):
        s.upload(src, "k", if_generation_match=999)
    with pytest.raises(PreconditionFailed):
        s.delete("k", if_generation_match=999)


def test_gcs_download_sets_mtime_and_adds_no_precondition(gcs, tmp_path):
    s, fake = gcs
    info = s.write_bytes("raw/weather/w", b"abc", if_generation_match=0)
    dest = tmp_path / "x" / "w"
    got = s.download("raw/weather/w", dest)
    assert dest.read_bytes() == b"abc"
    assert got.generation == info.generation
    assert dest.stat().st_mtime == pytest.approx(info.updated.timestamp(), abs=1e-3)
    # The client pins the generation itself (blob.generation is a query
    # parameter); a precondition here would turn a concurrent overwrite into
    # PreconditionFailed, which callers read as "lost the publish race".
    assert ("download_to_filename", "raw/weather/w", None) in fake.calls


def test_gcs_download_missing(gcs, tmp_path):
    s, _ = gcs
    with pytest.raises(FileNotFoundError):
        s.download("nope", tmp_path / "x")


def test_gcs_delete_missing_is_noop_unless_precondition(gcs):
    s, _ = gcs
    s.delete("nope")
    with pytest.raises(PreconditionFailed):
        s.delete("nope", if_generation_match=5)


def test_gcs_other_errors_propagate(gcs, monkeypatch):
    s, fake = gcs

    def boom(self, data, if_generation_match=None, **kw):
        raise _FakeGoogleError(503, "backend error")

    monkeypatch.setattr(_FakeBlob, "upload_from_string", boom)
    with pytest.raises(_FakeGoogleError):
        s.write_bytes("k", b"1", if_generation_match=0)
