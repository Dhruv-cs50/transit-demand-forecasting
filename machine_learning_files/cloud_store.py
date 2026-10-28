"""
machine_learning_files/cloud_store.py
─────────────────────────────────────
The slice of object storage the cloud ingestion job uses
(docs/cloud-ingestion-design.md §5), with two implementations behind one
protocol so the whole job can be tested against a directory:

    LocalStorage(root)   a directory that behaves like a bucket
    GcsStorage(bucket)   Google Cloud Storage; `google.cloud.storage` is
                         imported inside the methods, never at module import
    open_store(uri)      `gs://bucket` or `file:///path`

What the job relies on, and what both implementations guarantee:

* **Generations.** Every object has an integer generation that increases each
  time the object is written (including a rewrite with identical bytes, and a
  delete followed by a re-create).
* **Preconditions.** `if_generation_match=g` makes a write or delete succeed
  only if the object's current generation is `g`; `0` means "the object must
  not exist". A failed precondition raises `PreconditionFailed` and changes
  nothing. `None` means unconditional. This is how `serving.json` is
  published last, under a precondition, so a lost race is detected (exit 3).
* **`updated` becomes mtime.** `download` sets the local file's mtime from the
  object's `updated`. The loaders in merge_pipeline.py sort files by mtime
  before de-duplicating, so a staged copy must carry the object's age, not the
  moment it was downloaded.
* **Missing objects.** `read_bytes` returns None; `download` raises
  FileNotFoundError; `delete` of an absent object is a no-op unless a
  precondition was given (which then cannot be met -> PreconditionFailed).

LocalStorage keeps no metadata of its own. An object is a file; its generation
is the file's mtime in nanoseconds (bumped by one if a rewrite would not
increase it) and its `updated` is the same mtime. So `file:///seed` can point
at a plain directory of files, and setting a file's mtime with `os.utime`
re-dates the object, which is how tests build "the later-updated object wins"
cases. Writes are atomic (temp file + rename) and serialised across processes
with an flock on `<root>/.lock`.

Object names are `/`-separated, relative, with no empty, `.` or `..`
components. Listing uses plain string prefixes like GCS, not directories.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Protocol, Tuple

try:  # POSIX only; the job runs on Linux and the tests on macOS/Linux.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)

# Names LocalStorage keeps at the top level of its root; never listed.
_LOCK_NAME = ".lock"
_TMP_DIR = ".tmp"


class PreconditionFailed(Exception):
    """An `if_generation_match` precondition was not met (HTTP 412 on GCS)."""


@dataclass(frozen=True)
class ObjInfo:
    name: str
    generation: int
    updated: dt.datetime  # timezone-aware, UTC
    size: int


class Store(Protocol):
    def list(self, prefix: str = "") -> list[ObjInfo]:
        """Objects whose name starts with `prefix`, sorted by name."""

    def download(self, name: str, dest: Path) -> ObjInfo:
        """Copy the object to `dest` (parents created) and set dest's mtime
        from the object's `updated`. FileNotFoundError if absent."""

    def upload(self, src: Path, name: str, *,
               if_generation_match: Optional[int] = None) -> ObjInfo: ...

    def read_bytes(self, name: str) -> Optional[Tuple[bytes, int]]:
        """(content, generation) or None if the object does not exist."""

    def write_bytes(self, name: str, data: bytes, *,
                    if_generation_match: Optional[int]) -> ObjInfo:
        """No default on purpose: unconditional is spelled `None`, and
        `0` means the object must not exist."""

    def delete(self, name: str, *,
               if_generation_match: Optional[int] = None) -> None: ...


def _to_datetime(ns: int) -> dt.datetime:
    return _EPOCH + dt.timedelta(microseconds=ns // 1000)


def _check_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("object name must be a non-empty string")
    if "\x00" in name or name.startswith("/"):
        raise ValueError(f"invalid object name: {name!r}")
    for part in name.split("/"):
        if part in ("", ".", ".."):
            raise ValueError(f"invalid object name: {name!r}")
    return name


# ── LocalStorage ──────────────────────────────────────────────────────────────

class LocalStorage:
    """A directory that behaves like a bucket (see the module docstring)."""

    def __init__(self, root) -> None:
        self.root = Path(root)

    # -- internals --------------------------------------------------------

    def _path(self, name: str) -> Path:
        return self.root / _check_name(name)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        if fcntl is None:  # pragma: no cover
            yield
            return
        with open(self.root / _LOCK_NAME, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _info(self, name: str, st: os.stat_result) -> ObjInfo:
        return ObjInfo(name=name, generation=st.st_mtime_ns,
                       updated=_to_datetime(st.st_mtime_ns), size=st.st_size)

    def _current(self, path: Path) -> Optional[os.stat_result]:
        try:
            return path.stat()
        except FileNotFoundError:
            return None

    @staticmethod
    def _check_precondition(cur: Optional[os.stat_result], want: Optional[int], name: str) -> None:
        if want is None:
            return
        have = 0 if cur is None else cur.st_mtime_ns
        if have != want:
            raise PreconditionFailed(
                f"{name}: generation is {have}, precondition required {want}")

    def _stage_tmp(self) -> Path:
        tmp_dir = self.root / _TMP_DIR
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=tmp_dir)
        os.close(fd)
        return Path(tmp)

    def _commit(self, tmp: Path, name: str, if_generation_match: Optional[int]) -> ObjInfo:
        """Atomically move a fully written temp file to `name`."""
        path = self._path(name)
        try:
            with self._locked():
                cur = self._current(path)
                self._check_precondition(cur, if_generation_match, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp, path)
                st = path.stat()
                if cur is not None and st.st_mtime_ns <= cur.st_mtime_ns:
                    # A rewrite must raise the generation even when the clock
                    # did not move (or the old mtime was set into the future).
                    bumped = cur.st_mtime_ns + 1
                    os.utime(path, ns=(bumped, bumped))
                    st = path.stat()
                return self._info(name, st)
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()

    # -- Store ------------------------------------------------------------

    def list(self, prefix: str = "") -> list[ObjInfo]:
        out: list[ObjInfo] = []
        if not self.root.is_dir():
            return out
        for dirpath, dirnames, filenames in os.walk(self.root):
            here = Path(dirpath)
            if here == self.root:
                dirnames[:] = [d for d in dirnames if d != _TMP_DIR]
                filenames = [f for f in filenames if f != _LOCK_NAME]
            for fn in filenames:
                p = here / fn
                name = p.relative_to(self.root).as_posix()
                if not name.startswith(prefix):
                    continue
                try:
                    st = p.stat()
                except FileNotFoundError:  # deleted while listing
                    continue
                out.append(self._info(name, st))
        out.sort(key=lambda o: o.name)
        return out

    def download(self, name: str, dest: Path) -> ObjInfo:
        path = self._path(name)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "rb") as src:
                st = os.fstat(src.fileno())  # same inode as the bytes we copy
                part = dest.with_name(dest.name + ".part")
                with open(part, "wb") as out:
                    shutil.copyfileobj(src, out)
        except FileNotFoundError:
            raise FileNotFoundError(f"no such object: {name}") from None
        os.replace(part, dest)
        os.utime(dest, ns=(st.st_mtime_ns, st.st_mtime_ns))
        return self._info(name, st)

    def upload(self, src: Path, name: str, *,
               if_generation_match: Optional[int] = None) -> ObjInfo:
        tmp = self._stage_tmp()
        shutil.copyfile(src, tmp)
        return self._commit(tmp, name, if_generation_match)

    def read_bytes(self, name: str) -> Optional[Tuple[bytes, int]]:
        path = self._path(name)
        try:
            with open(path, "rb") as fh:
                st = os.fstat(fh.fileno())
                data = fh.read()
        except FileNotFoundError:
            return None
        return data, st.st_mtime_ns

    def write_bytes(self, name: str, data: bytes, *,
                    if_generation_match: Optional[int]) -> ObjInfo:
        self._path(name)  # validate before touching disk
        tmp = self._stage_tmp()
        tmp.write_bytes(data)
        return self._commit(tmp, name, if_generation_match)

    def delete(self, name: str, *, if_generation_match: Optional[int] = None) -> None:
        path = self._path(name)
        with self._locked():
            cur = self._current(path)
            if cur is None and if_generation_match in (None, 0):
                return
            self._check_precondition(cur, if_generation_match, name)
            path.unlink()
            parent = path.parent
            while parent != self.root:  # tidy empty "directories"
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent


# ── GcsStorage ────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _translate_gcs_errors() -> Iterator[None]:
    """Map Google API errors onto ours without importing google at module
    load: every google.api_core.exceptions.GoogleAPICallError carries the HTTP
    status as `.code`."""
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - re-raised unless 404/412
        code = getattr(exc, "code", None)
        if code == 412:
            raise PreconditionFailed(str(exc)) from exc
        if code == 404:
            raise FileNotFoundError(str(exc)) from exc
        raise


class GcsStorage:
    """Google Cloud Storage. Needs `google-cloud-storage` only when a method
    is called; constructing the object imports nothing."""

    def __init__(self, bucket: str) -> None:
        self.bucket_name = bucket
        self._client = None
        self._bucket = None

    def _bkt(self):
        if self._bucket is None:
            from google.cloud import storage  # lazy: tests/dev need no google libs

            self._client = storage.Client()
            self._bucket = self._client.bucket(self.bucket_name)
        return self._bucket

    @staticmethod
    def _info(blob) -> ObjInfo:
        return ObjInfo(name=blob.name, generation=int(blob.generation),
                       updated=blob.updated, size=int(blob.size or 0))

    def list(self, prefix: str = "") -> list[ObjInfo]:
        self._bkt()
        with _translate_gcs_errors():
            blobs = self._client.list_blobs(self.bucket_name, prefix=prefix or None)
            return sorted((self._info(b) for b in blobs), key=lambda o: o.name)

    def download(self, name: str, dest: Path) -> ObjInfo:
        bucket = self._bkt()
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with _translate_gcs_errors():
            blob = bucket.get_blob(name)
            if blob is None:
                raise FileNotFoundError(f"no such object: {name}")
            part = dest.with_name(dest.name + ".part")
            # get_blob() returns a blob carrying its generation, and the client
            # sends it as the `generation` query parameter, so the bytes are the
            # generation just described. No precondition: a concurrent overwrite
            # must not surface as PreconditionFailed (that means a lost race).
            blob.download_to_filename(str(part))
        os.replace(part, dest)
        ts = blob.updated.timestamp()
        os.utime(dest, (ts, ts))
        return self._info(blob)

    def upload(self, src: Path, name: str, *,
               if_generation_match: Optional[int] = None) -> ObjInfo:
        blob = self._bkt().blob(name)
        with _translate_gcs_errors():
            blob.upload_from_filename(str(src), if_generation_match=if_generation_match)
        return self._info(blob)

    def read_bytes(self, name: str) -> Optional[Tuple[bytes, int]]:
        bucket = self._bkt()
        try:
            with _translate_gcs_errors():
                blob = bucket.get_blob(name)
                if blob is None:
                    return None
                data = blob.download_as_bytes()  # pinned to blob.generation, see download()
        except FileNotFoundError:  # deleted between get_blob and download
            return None
        return data, int(blob.generation)

    def write_bytes(self, name: str, data: bytes, *,
                    if_generation_match: Optional[int]) -> ObjInfo:
        blob = self._bkt().blob(name)
        with _translate_gcs_errors():
            blob.upload_from_string(data, if_generation_match=if_generation_match)
        return self._info(blob)

    def delete(self, name: str, *, if_generation_match: Optional[int] = None) -> None:
        blob = self._bkt().blob(name)
        try:
            with _translate_gcs_errors():
                blob.delete(if_generation_match=if_generation_match)
        except FileNotFoundError:
            if if_generation_match in (None, 0):
                return
            raise PreconditionFailed(
                f"{name}: object does not exist, precondition required {if_generation_match}"
            ) from None


# ── open_store ────────────────────────────────────────────────────────────────

def open_store(uri: str) -> "Store":
    """`gs://bucket` -> GcsStorage; `file:///abs/path` -> LocalStorage."""
    if isinstance(uri, str):
        if uri.startswith("gs://"):
            bucket = uri[len("gs://"):].rstrip("/")
            if not bucket:
                raise ValueError(f"missing bucket name in {uri!r}")
            if "/" in bucket:
                raise ValueError(
                    f"{uri!r}: bucket prefixes are not supported, use gs://<bucket>")
            return GcsStorage(bucket)
        if uri.startswith("file://"):
            path = uri[len("file://"):]
            if not path:
                raise ValueError(f"missing path in {uri!r}")
            return LocalStorage(Path(path))
    raise ValueError(f"unsupported store URI {uri!r}; use gs://<bucket> or file:///<path>")
