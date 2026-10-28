"""
machine_learning_files/cloud_ingest.py
──────────────────────────────────────
The cloud ingestion job (docs/cloud-ingestion-design.md §2). Entrypoint of the
`transit-ingest` Cloud Run Job:

    python -m machine_learning_files.cloud_ingest [--bucket gs://b | file:///dir]
                                                  [--skip-fetch] [--force] [--dry-run]

Each run, in order:

 1. Fetch      closed-month weather and Sharks data into raw/ (ingest_fetch).
 2. Fingerprint  sha256 over the sorted `name:generation` of raw/**. Equal to
               the pointer's `input_fingerprint` -> "unchanged", exit 0 (--force
               runs on).
 3. Stage      download raw/** into a temp workdir, each file's mtime set from
               the object's `updated` (the loaders sort by mtime before
               de-duplicating); check the pinned sha256s in configs/ingest.yaml.
 4. Rebuild    bart_od_from_xlsx, then merge_pipeline.build_feature_store(), with
               merge_pipeline's RAW_DIR / PROCESSED_DIR / CONFIG_PATH /
               MODEL_CONFIG_PATH pointed at the workdir (and restored after).
               The tracked data/processed/feature_store.parquet is never written.
 5. Gate       ingest_gate.run_gate on the bytes that would be published.
               processed/runs/<run_id>/gate.json is always written. A failed gate
               exits 1 and leaves serving.json untouched.
 6. Publish    runs/<id>/feature_store.parquet, then manifest.json, then
               processed/serving.json last, under `if_generation_match` = the
               generation read at the start (0 if there was none). A lost race
               exits 3. A candidate whose content equals the served store is not
               published (exit 0).

Exit codes
    0  published, or nothing to publish (unchanged inputs / identical content)
    1  build, staging, pin or gate failure (also: no bucket configured)
    2  a fetch failed. The rest still ran; a published store still exits 2 so the
       failed execution is visible in `gcloud run jobs executions list`
    3  another execution moved serving.json (or a run object) first
    When 1 or 3 and a fetch failure coincide, 1 or 3 is returned.

--dry-run does everything except write to the store (fetches are made but not
saved; staging reads what is already in the bucket) and prints a JSON summary.

serving.json (read by api.py `_read_pointer`, scripts/smoke_cloud.sh) has exactly:
    run_id, store_object, store_sha256, input_fingerprint, published_at
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import glob
import hashlib
import io
import json
import logging
import os
import platform
import re
import secrets
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Iterator, Optional

import pandas as pd
import yaml

from machine_learning_files.cloud_store import ObjInfo, PreconditionFailed, open_store
from machine_learning_files.ingest_fetch import (
    FetchResult,
    fetch_sharks,
    fetch_weather,
    last_closed_month_end,
)
from machine_learning_files.ingest_gate import run_gate

log = logging.getLogger("machine_learning_files.cloud_ingest")

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "ingest.yaml"

RAW_PREFIX = "raw/"
RUNS_PREFIX = "processed/runs/"
STORE_FILENAME = "feature_store.parquet"
MONTH_RE = re.compile(r"Ridership_(\d{4})(\d{2})\.xlsx$", re.IGNORECASE)
POINTER_KEYS = ("run_id", "store_object", "store_sha256", "input_fingerprint", "published_at")

EXIT_OK, EXIT_FAILED, EXIT_FETCH, EXIT_RACE = 0, 1, 2, 3


class IngestError(Exception):
    """A build / staging / pin failure: the run exits 1 and publishes nothing."""


# ── small helpers ─────────────────────────────────────────────────────────────

def load_config(path: Path | str | None = None) -> dict:
    with open(path or DEFAULT_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_bytes(obj) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n").encode()


def _resolve_repo_path(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else REPO_ROOT / p


def _la_today(now: dt.datetime) -> dt.date:
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo("America/Los_Angeles")).date()
    except Exception:  # noqa: BLE001 - no tz database: the UTC date is within a day
        return now.astimezone(dt.timezone.utc).date()


class DryRunStore:
    """Reads pass through; writes and deletes are logged and dropped.
    `dry_run` is read by ingest_fetch to report "dry-run" instead of "written"."""

    dry_run = True

    def __init__(self, inner) -> None:
        self._inner = inner

    def list(self, prefix: str = ""):
        return self._inner.list(prefix)

    def download(self, name, dest):
        return self._inner.download(name, dest)

    def read_bytes(self, name):
        return self._inner.read_bytes(name)

    def upload(self, src, name, *, if_generation_match=None):
        log.info("[dry-run] would upload %s", name)
        return ObjInfo(name, 0, dt.datetime.now(dt.timezone.utc), Path(src).stat().st_size)

    def write_bytes(self, name, data, *, if_generation_match):
        log.info("[dry-run] would write %s (%d bytes)", name, len(data))
        return ObjInfo(name, 0, dt.datetime.now(dt.timezone.utc), len(data))

    def delete(self, name, *, if_generation_match=None):
        log.info("[dry-run] would delete %s", name)


# ── step 2: fingerprint ───────────────────────────────────────────────────────

def input_fingerprint(infos) -> str:
    """sha256 over the sorted `name:generation` lines of the given objects."""
    h = hashlib.sha256()
    for o in sorted(infos, key=lambda o: o.name):
        h.update(f"{o.name}:{o.generation}\n".encode())
    return h.hexdigest()


# ── step 3: stage and pin ─────────────────────────────────────────────────────

def stage_inputs(store, workdir: Path, prefix: str = RAW_PREFIX) -> list[ObjInfo]:
    """Download every object under `prefix` to workdir/<object name>, mtime set
    from `updated`. Returns the ObjInfos of the bytes actually staged (the
    generation `download` reports, not the one listed), so a fingerprint made
    from them describes exactly what gets built.

    An object that disappears between listing and download (an overlapping
    execution replaced a same-year weather file) is listed again once.
    """
    last_err: Exception | None = None
    for attempt in (1, 2):
        shutil.rmtree(workdir / prefix.rstrip("/"), ignore_errors=True)
        staged: list[ObjInfo] = []
        try:
            for info in store.list(prefix):
                staged.append(store.download(info.name, workdir / info.name))
            return staged
        except FileNotFoundError as e:
            last_err = e
            log.warning("staging attempt %d: %s", attempt, e)
    raise IngestError(f"staging failed, an input object kept disappearing: {last_err}")


def verify_pinned(workdir: Path, cfg: dict) -> None:
    """Every pinned object is present and has its pinned sha256."""
    problems = []
    for name, want in (cfg.get("pinned_inputs") or {}).items():
        path = workdir / name
        if not path.is_file():
            problems.append(f"{name}: missing from the bucket")
            continue
        got = sha256_file(path)
        if got != str(want).strip().lower():
            problems.append(f"{name}: sha256 is {got}, configs/ingest.yaml pins {want}")
    if problems:
        raise IngestError("pinned inputs do not match:\n  " + "\n  ".join(problems))


def inputs_manifest(workdir: Path, staged: list[ObjInfo]) -> list[dict]:
    return [{"name": o.name, "generation": o.generation, "updated": _iso(o.updated),
             "size": o.size, "sha256": sha256_file(workdir / o.name)}
            for o in sorted(staged, key=lambda o: o.name)]


# ── step 4: rebuild ───────────────────────────────────────────────────────────

_MERGE_PATHS = ("RAW_DIR", "PROCESSED_DIR", "CONFIG_PATH", "MODEL_CONFIG_PATH")


@contextlib.contextmanager
def merge_pipeline_paths(workdir: Path) -> Iterator[None]:
    """Point merge_pipeline's four path globals at `workdir` and restore them.

    merge_pipeline reads RAW_DIR, writes PROCESSED_DIR and loads CONFIG_PATH /
    MODEL_CONFIG_PATH through module globals that default to cwd-relative paths;
    in the image cwd is /app, where the tracked store lives, so unpatched it
    would overwrite it. configs/sources.yaml and model.yaml are copied into the
    workdir so the build is self-contained.
    """
    from machine_learning_files import merge_pipeline as mp

    workdir = Path(workdir).resolve()
    conf = workdir / "configs"
    conf.mkdir(parents=True, exist_ok=True)
    for fname in ("sources.yaml", "model.yaml"):
        shutil.copyfile(REPO_ROOT / "configs" / fname, conf / fname)
    (workdir / "raw").mkdir(parents=True, exist_ok=True)
    (workdir / "processed").mkdir(parents=True, exist_ok=True)

    saved = {k: getattr(mp, k) for k in _MERGE_PATHS}
    try:
        mp.RAW_DIR = workdir / "raw"
        mp.PROCESSED_DIR = workdir / "processed"
        mp.CONFIG_PATH = conf / "sources.yaml"
        mp.MODEL_CONFIG_PATH = conf / "model.yaml"
        yield
    finally:
        for k, v in saved.items():
            setattr(mp, k, v)


def _expected_bart_months(bart_dir: Path) -> set[tuple[int, int]]:
    months: set[tuple[int, int]] = set()
    for p in bart_dir.rglob("*"):
        if p.suffix.lower() == ".xlsx":
            m = MONTH_RE.search(p.name)
            if m:
                months.add((int(m.group(1)), int(m.group(2))))
        elif p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as zf:
                for member in zf.namelist():
                    m = MONTH_RE.search(member)
                    if m:
                        months.add((int(m.group(1)), int(m.group(2))))
    return months


def _convert_bart(workdir: Path) -> None:
    """raw/bart/*.zip|*.xlsx -> raw/transit/bart/bart_od_YYYY_MM.parquet.

    bart_od_from_xlsx.build() logs and skips a workbook it cannot parse; a month
    silently missing from the store is worse than a failed run, so every
    workbook month found must come out as a parquet.
    """
    from machine_learning_files import bart_od_from_xlsx

    bart_dir = workdir / "raw" / "bart"
    out_dir = workdir / "raw" / "transit" / "bart"
    zips = sorted(bart_dir.rglob("*.zip")) if bart_dir.is_dir() else []
    loose = bool(list(bart_dir.rglob("*.xlsx"))) if bart_dir.is_dir() else False
    if not zips and not loose:
        raise IngestError("no BART workbooks (raw/bart/*.zip or *.xlsx) in the bucket")

    expected = _expected_bart_months(bart_dir)
    if not expected:
        raise IngestError("raw/bart holds no Ridership_YYYYMM.xlsx workbook")
    written = bart_od_from_xlsx.build([glob.escape(str(z)) for z in zips],
                                      str(bart_dir) if loose else None, out_dir)
    got = {(int(m.group(1)), int(m.group(2)))
           for p in out_dir.glob("bart_od_*.parquet")
           if (m := re.match(r"bart_od_(\d{4})_(\d{2})\.parquet$", p.name))}
    missing = sorted(expected - got)
    if written == 0 or missing:
        raise IngestError("BART conversion lost month(s): "
                          + ", ".join(f"{y}-{m:02d}" for y, m in missing[:12]))


def _default_builder(workdir: Path) -> pd.DataFrame:
    from machine_learning_files import merge_pipeline

    _convert_bart(workdir)
    return merge_pipeline.build_feature_store()   # defaults: no splits, no date filter


def build_candidate(workdir: Path, builder: Optional[Callable[[Path], pd.DataFrame]] = None) -> pd.DataFrame:
    """Rebuild the feature store from the staged raw files in `workdir`.

    builder(workdir) -> DataFrame is injectable for tests. Whichever runs, it runs
    inside `merge_pipeline_paths`, so merge_pipeline can only see the workdir.
    """
    workdir = Path(workdir).resolve()
    with merge_pipeline_paths(workdir):
        df = (builder or _default_builder)(workdir)
    if df is None or len(df) == 0:
        raise IngestError("the rebuild produced an empty feature store")
    return df


# ── pointer ───────────────────────────────────────────────────────────────────

def read_pointer(store, name: str) -> tuple[Optional[dict], int]:
    """(pointer or None, generation or 0). A pointer that exists but is not
    valid is returned as None with its real generation, so the publish replaces
    it under the right precondition."""
    got = store.read_bytes(name)
    if got is None:
        return None, 0
    data, gen = got
    try:
        pointer = json.loads(data)
        if not isinstance(pointer, dict):
            raise ValueError("not a JSON object")
        for key in ("run_id", "store_object", "store_sha256"):
            if not isinstance(pointer.get(key), str) or not pointer[key].strip():
                raise ValueError(f"no string {key!r}")
        return pointer, gen
    except ValueError as e:
        log.warning("%s exists but is invalid (%s); it will be replaced", name, e)
        return None, gen


def served_store(store, pointer: Optional[dict]) -> tuple[Optional[bytes], Optional[pd.DataFrame]]:
    """(bytes, frame) of the store the pointer names, sha256-verified; (None,
    None) if there is no pointer or the store cannot be read."""
    if not pointer:
        return None, None
    try:
        got = store.read_bytes(pointer["store_object"])
        if got is None:
            raise ValueError("object is missing")
        data = got[0]
        if sha256_bytes(data) != pointer["store_sha256"].strip().lower():
            raise ValueError("sha256 does not match the pointer")
        return data, pd.read_parquet(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        log.warning("the served store %s is unreadable (%s); treating it as absent",
                    pointer.get("store_object"), e)
        return None, None


def _same_content(candidate: pd.DataFrame, candidate_sha: str,
                  served_bytes: Optional[bytes], served: Optional[pd.DataFrame]) -> bool:
    if served is None or served_bytes is None:
        return False
    if sha256_bytes(served_bytes) == candidate_sha:
        return True
    try:
        pd.testing.assert_frame_equal(candidate, served, check_exact=True)
        return True
    except AssertionError:
        return False


# ── the job ───────────────────────────────────────────────────────────────────

class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse exits 2, which here would read "a fetch failed"
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_FAILED)


def _parse_args(argv) -> argparse.Namespace:
    p = _Parser(prog="cloud_ingest", description="Fetch, rebuild, gate and publish the feature store")
    p.add_argument("--bucket", default=None,
                   help="gs://bucket or file:///dir (default: $INGEST_BUCKET, then configs/ingest.yaml)")
    p.add_argument("--config", default=None, help="path to ingest.yaml (default: configs/ingest.yaml)")
    p.add_argument("--skip-fetch", action="store_true", help="do not fetch weather or Sharks data")
    p.add_argument("--force", action="store_true", help="rebuild even if the inputs are unchanged")
    p.add_argument("--dry-run", action="store_true", help="do everything except write to the store")
    return p.parse_args(argv)


def _bucket_uri(args, cfg: dict) -> Optional[str]:
    uri = args.bucket or os.environ.get("INGEST_BUCKET") or cfg.get("bucket")
    if not uri:
        return None
    uri = uri.strip()
    return uri if "://" in uri else f"gs://{uri}"


def _done(code: int, fetch_failed: bool) -> int:
    """A fetch failure turns an otherwise-successful run into exit 2."""
    return EXIT_FETCH if code == EXIT_OK and fetch_failed else code


def main(argv=None, *, cfg: Optional[dict] = None,
         builder: Optional[Callable[[Path], pd.DataFrame]] = None,
         now: Optional[dt.datetime] = None, run_id: Optional[str] = None,
         weather_client=None, nhl_client=None) -> int:
    """Run the job; returns the exit code. The keyword arguments are test seams:
    a config dict, a builder, a fixed clock, a fixed run id and fake fetch clients."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    args = _parse_args(argv)
    cfg = cfg if cfg is not None else load_config(args.config)
    uri = _bucket_uri(args, cfg)
    if not uri:
        log.error("no bucket: pass --bucket, set INGEST_BUCKET, or set `bucket` in configs/ingest.yaml")
        return EXIT_FAILED
    try:
        return _run(args, cfg, uri, builder, now or dt.datetime.now(dt.timezone.utc),
                    run_id, weather_client, nhl_client)
    except IngestError as e:
        log.error("%s", e)
        return EXIT_FAILED
    except Exception:  # noqa: BLE001 - the job must always return an exit code
        log.exception("ingest failed")
        return EXIT_FAILED


def _run(args, cfg, uri, builder, now, run_id, weather_client, nhl_client) -> int:
    inner = open_store(uri)
    store = DryRunStore(inner) if args.dry_run else inner
    today = _la_today(now)
    lag = int(cfg.get("archive_lag_days", 7))
    pointer_name = cfg.get("serving_pointer", "processed/serving.json")
    log.info("ingest %s%s, today %s", uri, " (dry run)" if args.dry_run else "", today)

    # 1. fetch ---------------------------------------------------------------
    fetches: list[FetchResult] = []
    if args.skip_fetch:
        log.info("fetch skipped")
    else:
        for fn, client in ((fetch_weather, weather_client), (fetch_sharks, nhl_client)):
            try:
                fetches += fn(store, cfg, today, client=client)
            except Exception as e:  # noqa: BLE001 - e.g. no client could be built
                log.exception("%s failed", fn.__name__)
                fetches.append(FetchResult(fn.__name__.removeprefix("fetch_"), "", 0, "failed",
                                           f"{type(e).__name__}: {e}"))
        for r in fetches:
            log.info("fetch %-7s %-8s %s %s", r.source, r.status, r.object_name, r.detail)
    fetch_failed = any(r.failed for r in fetches)

    # 2. fingerprint ---------------------------------------------------------
    pointer, pointer_gen = read_pointer(store, pointer_name)
    listed = store.list(RAW_PREFIX)
    fingerprint = input_fingerprint(listed)
    if pointer and not args.force and pointer.get("input_fingerprint") == fingerprint:
        log.info("unchanged: the %d raw objects match run %s", len(listed), pointer["run_id"])
        return _done(EXIT_OK, fetch_failed)

    with tempfile.TemporaryDirectory(prefix="transit-ingest-") as tmp:
        workdir = Path(tmp)

        # 3. stage + pin -----------------------------------------------------
        staged = stage_inputs(store, workdir)
        fingerprint = input_fingerprint(staged)    # the bytes actually staged
        verify_pinned(workdir, cfg)
        inputs = inputs_manifest(workdir, staged)
        log.info("staged %d raw objects, fingerprint %s", len(staged), fingerprint[:12])

        # 4. rebuild ---------------------------------------------------------
        built = build_candidate(workdir, builder)
        # The bytes that would be published, read back: the gate judges the file,
        # not the in-memory frame that wrote it. (merge_pipeline writes the same
        # file with the same call; writing it here also covers injected builders.)
        store_path = workdir / "processed" / STORE_FILENAME
        store_path.parent.mkdir(parents=True, exist_ok=True)
        built.to_parquet(store_path, index=False)
        candidate_bytes = store_path.read_bytes()
        candidate = pd.read_parquet(io.BytesIO(candidate_bytes))
        candidate_sha = sha256_bytes(candidate_bytes)

        # 5. gate ------------------------------------------------------------
        gate_cfg = cfg["gate"]
        tracked_path = _resolve_repo_path(gate_cfg["tracked_store"])
        tracked = pd.read_parquet(tracked_path)
        served_bytes, served = served_store(store, pointer)
        served_months = (served if served is not None else tracked)["timestamp"]
        last_closed = last_closed_month_end(today, lag)
        report = run_gate(candidate, tracked, served_months, cfg, last_closed_month=last_closed)

        run_id = run_id or f"{now.astimezone(dt.timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
        run_dir = f"{RUNS_PREFIX}{run_id}/"
        git_sha = os.environ.get("GIT_SHA", "unknown")
        months = sorted(pd.to_datetime(candidate["timestamp"]).dt.strftime("%Y-%m").unique())
        gate_doc = {"run_id": run_id, "git_sha": git_sha, "created_at": _iso(now),
                    "input_fingerprint": fingerprint, "last_closed_month": str(last_closed),
                    "store_sha256": candidate_sha, **report.to_dict()}
        if report.passed:
            log.info("gate passed (%d checks)", len(report.checks))
        else:
            for f in report.failures:
                log.error("gate failed: %s", f)

        summary = {"dry_run": bool(args.dry_run), "run_id": run_id, "gate_passed": report.passed,
                   "months": [months[0], months[-1], len(months)], "store_sha256": candidate_sha,
                   "input_fingerprint": fingerprint, "fetch": [r.to_dict() for r in fetches],
                   "checks": {c.check: (c.reason or c.status) for c in report.checks}}

        try:
            store.write_bytes(run_dir + "gate.json", _json_bytes(gate_doc), if_generation_match=0)
        except PreconditionFailed:
            log.error("%sgate.json already exists: another execution has this run id", run_dir)
            return EXIT_RACE
        if not report.passed:
            summary["failures"] = [str(f) for f in report.failures]
            _emit(summary, args)
            return EXIT_FAILED

        # 6. publish ---------------------------------------------------------
        if _same_content(candidate, candidate_sha, served_bytes, served):
            log.info("identical to the served store (run %s); nothing to publish", pointer["run_id"])
            summary["published"] = False
            summary["reason"] = "identical to the served store"
            _emit(summary, args)
            return _done(EXIT_OK, fetch_failed)

        if args.dry_run:
            summary["published"] = False
            summary["reason"] = "dry run: would publish " + run_dir
            _emit(summary, args)
            return _done(EXIT_OK, fetch_failed)

        try:
            published = publish(store, run_id=run_id, store_path=store_path, store_sha256=candidate_sha,
                                pointer_name=pointer_name, pointer_generation=pointer_gen,
                                fingerprint=fingerprint, now=now,
                                manifest=_manifest(run_id, git_sha, now, fingerprint, inputs, candidate,
                                                   candidate_sha, months, report, gate_doc, fetches,
                                                   tracked_path, last_closed))
        except PreconditionFailed as e:
            log.error("lost the race: %s", e)
            summary["published"] = False
            summary["reason"] = "lost the race"
            _emit(summary, args)
            return EXIT_RACE
        log.info("published run %s (%s)", run_id, published["store_object"])
        summary["published"] = True
        summary["pointer"] = published
        _emit(summary, args)
        return _done(EXIT_OK, fetch_failed)


def _emit(summary: dict, args) -> None:
    if args.dry_run:
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))


def _manifest(run_id, git_sha, now, fingerprint, inputs, candidate, candidate_sha, months, report,
              gate_doc, fetches, tracked_path, last_closed) -> dict:
    return {
        "run_id": run_id,
        "git_sha": git_sha,
        "created_at": _iso(now),
        "input_fingerprint": fingerprint,
        "inputs": inputs,
        "store": {"object": f"{RUNS_PREFIX}{run_id}/{STORE_FILENAME}", "sha256": candidate_sha,
                  "rows": int(len(candidate)), "months": months},
        "gate": {"object": f"{RUNS_PREFIX}{run_id}/gate.json", "passed": report.passed,
                 "checks": [{"check": c.check, "status": c.status, "reason": c.reason}
                            for c in report.checks]},
        "last_closed_month": str(last_closed),
        "tracked_store_sha256": sha256_file(tracked_path),
        "fetch": [r.to_dict() for r in fetches],
        "runtime": {"python": platform.python_version(), "pandas": pd.__version__},
    }


def publish(store, *, run_id: str, store_path: Path, store_sha256: str, manifest: dict,
            pointer_name: str, pointer_generation: int, fingerprint: str,
            now: dt.datetime) -> dict:
    """Write the run's store and manifest (write-once), then the pointer last,
    under `if_generation_match`. Returns the pointer written. Raises
    PreconditionFailed if another execution got there first."""
    store_object = f"{RUNS_PREFIX}{run_id}/{STORE_FILENAME}"
    store.upload(store_path, store_object, if_generation_match=0)
    store.write_bytes(f"{RUNS_PREFIX}{run_id}/manifest.json", _json_bytes(manifest),
                      if_generation_match=0)
    pointer = {"run_id": run_id, "store_object": store_object, "store_sha256": store_sha256,
               "input_fingerprint": fingerprint, "published_at": _iso(now)}
    assert tuple(sorted(pointer)) == tuple(sorted(POINTER_KEYS))
    store.write_bytes(pointer_name, _json_bytes(pointer), if_generation_match=pointer_generation)
    return pointer


if __name__ == "__main__":
    sys.exit(main())
