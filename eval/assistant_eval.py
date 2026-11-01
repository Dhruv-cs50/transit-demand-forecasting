"""Scripted evaluation and latency gate for the deployed route assistant.

    python eval/assistant_eval.py --api https://transit-assistant-....run.app \
        [--out eval/outputs/assistant_eval.json] [--spacing 0]

One discarded warm-up request, then each question in ``assistant_questions.yaml``
is sent to ``POST /chat``. For every question the script records the time to
the first ``options`` event and to ``done``, and checks:

* the final text (the ``text`` deltas, or the ``replace`` text) states no clock
  time or minute count that ``assistant.answer`` does not accept for the options;
* the expected agencies appear in the options, and so do any stop-name
  expectations (``dest_stop_contains`` / ``dest_stop_excludes``) and a relative
  departure window (``depart_offset_min``);
* out-of-area and nonsense questions get a ``follow_up`` or ``form``, never an
  ``options`` event.

Exit status: 0 when every check passes and the aggregate latency targets are
met (warm, warm-up excluded); 1 when something failed; 2 when the question set
would exceed the service's rate limit (nothing is sent).

Validator limit. The stream carries the options but not the digest (alert
headers, event start times) that the service validates against. So the text is
checked against the options only. A sentence whose unsupported figure sits next
to alert or event wording is reported as ``unverifiable``, not a failure: the
service already checked it against the real digest. An unsupported figure in
any other sentence is a failure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from assistant.answer import unverified_claims  # noqa: E402
from assistant.config import DISPLAY_TZ  # noqa: E402
from assistant.types import Leg, TripOption  # noqa: E402

SLEEP_FLAG_S = 2.0  # wall clock minus timing clock above this marks a sample as possibly slept through
RATE_LIMIT_PER_HOUR = 10  # the service's RATE_LIMIT_PER_HOUR; the warm-up counts against it too
DEFAULT_QUESTIONS = Path(__file__).with_name("assistant_questions.yaml")
DEFAULT_OUT = Path(__file__).with_name("outputs") / "assistant_eval.json"

# Seconds, warm. (first options, done) x (p50, p95).
TARGETS = {
    "first_options": {"p50": 2.0, "p95": 3.5},
    "done": {"p50": 4.0, "p95": 7.0},
}

# Wording that marks a sentence as quoting the digest (an alert header or an event start),
# which this script cannot see.
SOURCE_CUE = re.compile(
    r"\b(alerts?|advis\w*|delays?|delayed|disrupt\w*|detour\w*|bus bridge|shuttle|clos\w+|maintenance|"
    r"construction|single[- ]track\w*|resum\w*|until|through|games?|concerts?|events?|shows?|puck|"
    r"doors?|kick[- ]?off|starts?|starting|begins?|beginning|sharks)\b",
    re.I,
)


# --- parsing and summarising ---------------------------------------------------------------


def parse_ndjson(text: str) -> tuple[list[dict[str, Any]], int]:
    """The JSON-object lines of ``text`` and the number of non-blank lines that were not objects."""
    events: list[dict[str, Any]] = []
    bad = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(value, dict):
            events.append(value)
        else:
            bad += 1
    return events, bad


def final_text(events: Iterable[dict[str, Any]]) -> str:
    """What the rider reads: the last ``replace`` text if one came, else the ``text`` deltas."""
    shown = ""
    replaced: str | None = None
    for e in events:
        if e.get("type") == "text":
            shown += str(e.get("delta", ""))
        elif e.get("type") == "replace":
            replaced = str(e.get("text", ""))
    return replaced if replaced is not None else shown


def destination_stops(options: list[dict[str, Any]]) -> list[str | None]:
    """The arrival stop of the last transit leg of each option (None when it has no transit leg)."""
    stops: list[str | None] = []
    for o in options:
        transit = [leg for leg in o.get("legs") or [] if leg.get("mode") == "TRANSIT"]
        stops.append(transit[-1].get("to_stop") if transit else None)
    return stops


def summarize(timed: list[tuple[float, dict[str, Any]]], malformed: int = 0) -> dict[str, Any]:
    """One response as a record. ``timed`` is (seconds since the request was sent, event)."""
    kinds = [e.get("type", "?") for _, e in timed]
    events = [e for _, e in timed]
    first_options = next((t for t, e in timed if e.get("type") == "options"), None)
    done = next((t for t, e in timed if e.get("type") == "done"), None)
    options_event = next((e for e in events if e.get("type") == "options"), None)
    options = list((options_event or {}).get("options") or [])
    if options:
        outcome = "options"
    elif options_event is not None:
        outcome = "no_routes"
    elif "follow_up" in kinds:
        outcome = "follow_up"
    elif "form" in kinds:
        outcome = "form"
    else:
        outcome = "empty"
    done_event = next((e for e in events if e.get("type") == "done"), {})
    caveats = next((e for e in events if e.get("type") == "caveats"), {})
    follow_up = next((e for e in events if e.get("type") == "follow_up"), {})
    return {
        "outcome": outcome,
        "kinds": kinds,
        "first_options_s": first_options,
        "done_s": done,
        "end_s": timed[-1][0] if timed else None,
        "options": options,
        "agencies": sorted({a for o in options for a in o.get("agencies") or []}),
        "dest_stops": destination_stops(options),
        "attribution": (options_event or {}).get("attribution"),
        "text": final_text(events),
        "replaced": "replace" in kinds,
        "server_latency_ms": done_event.get("latency_ms") or {},
        "caveats": {"missing": caveats.get("missing", []), "notes": caveats.get("notes", [])},
        "question": follow_up.get("question"),
        "malformed_lines": malformed,
    }


# --- validation ------------------------------------------------------------------------------


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def options_from_json(options: list[dict[str, Any]]) -> list[TripOption]:
    """Rebuild ``TripOption`` objects from an ``options`` event (ISO times, Pacific offsets)."""
    out: list[TripOption] = []
    for o in options:
        legs = tuple(
            Leg(
                mode=leg["mode"],
                agency=leg.get("agency"),
                line=leg.get("line"),
                from_stop=leg.get("from_stop"),
                to_stop=leg.get("to_stop"),
                depart=_dt(leg.get("depart")),
                arrive=_dt(leg.get("arrive")),
                duration_s=int(leg.get("duration_s") or 0),
                headsign=leg.get("headsign"),
            )
            for leg in o.get("legs") or []
        )
        out.append(
            TripOption(
                rank=int(o.get("rank", len(out) + 1)),
                depart=_dt(o["depart"]),  # type: ignore[arg-type]
                arrive=_dt(o["arrive"]),  # type: ignore[arg-type]
                duration_s=int(o.get("duration_s") or 0),
                transfers=int(o.get("transfers") or 0),
                walk_s=int(o.get("walk_s") or 0),
                agencies=tuple(o.get("agencies") or ()),
                legs=legs,
                polyline=o.get("polyline") or "",
                origin_latlng=tuple(o.get("origin_latlng") or (0.0, 0.0)),  # type: ignore[arg-type]
                dest_latlng=tuple(o.get("dest_latlng") or (0.0, 0.0)),  # type: ignore[arg-type]
            )
        )
    return out


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def validate_text(text: str, options: list[TripOption]) -> dict[str, Any]:
    """``pass``, ``unverifiable`` (see the module docstring) or ``fail`` for the final text."""
    if not text or not text.strip():
        return {"status": "fail", "claims": ["empty text"], "sentences": []}
    claims: list[str] = []
    flagged: list[str] = []
    status = "pass"
    for sentence in _sentences(text):
        bad = unverified_claims(sentence, options, DISPLAY_TZ, digest=None)
        if not bad:
            continue
        claims += bad
        flagged.append(sentence.strip())
        if SOURCE_CUE.search(sentence):
            status = "unverifiable" if status == "pass" else status
        else:
            status = "fail"
    if status == "pass":
        straddle = unverified_claims(text, options, DISPLAY_TZ, digest=None)
        if straddle:  # a claim only visible across sentences
            return {"status": "fail", "claims": straddle, "sentences": [text.strip()]}
    return {"status": status, "claims": claims, "sentences": flagged}


# --- latency -----------------------------------------------------------------------------------


def percentile(values: Iterable[float], p: float) -> float | None:
    """The ``p``-th percentile by linear interpolation between closest ranks; None for no values."""
    xs = sorted(values)
    if not xs:
        return None
    rank = (len(xs) - 1) * p / 100
    lo = int(rank)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (rank - lo)


def aggregate(rows: list[dict[str, Any]], targets: dict[str, dict[str, float]] = TARGETS) -> dict[str, Any]:
    """p50/p95 of the first-options and done times against ``targets``; missing times are skipped."""
    out: dict[str, Any] = {}
    all_ok = True
    for name, key in (("first_options", "first_options_s"), ("done", "done_s")):
        values = [r[key] for r in rows if r.get(key) is not None]
        p50, p95 = percentile(values, 50), percentile(values, 95)
        ok = {
            "p50": p50 is not None and p50 <= targets[name]["p50"],
            "p95": p95 is not None and p95 <= targets[name]["p95"],
        }
        all_ok = all_ok and ok["p50"] and ok["p95"]
        out[name] = {"n": len(values), "p50": p50, "p95": p95, "target": targets[name], "ok": ok}
    out["ok"] = all_ok
    return out


# --- per-question checks ---------------------------------------------------------------------------


def _norm(text: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def _check(ok: bool, detail: Any = None, **extra: Any) -> dict[str, Any]:
    return {"ok": bool(ok), "detail": detail, **extra}


def check_question(
    q: dict[str, Any], s: dict[str, Any], requested_at: datetime | None = None
) -> dict[str, dict[str, Any]]:
    """The named checks for one question; every one must be ``ok`` for the question to pass."""
    if q.get("kind") == "refuse":
        return {"scope": _check(s["outcome"] in ("follow_up", "form"), s["outcome"])}

    checks: dict[str, dict[str, Any]] = {}
    has_options = s["outcome"] == "options"
    checks["options"] = _check(has_options, s["outcome"])
    checks["done"] = _check(s["done_s"] is not None, s["kinds"][-1] if s["kinds"] else None)
    expected = list(q.get("expect_agencies") or [])
    checks["agencies"] = _check(
        all(a in s["agencies"] for a in expected), s["agencies"], expected=expected
    )
    if has_options:
        verdict = validate_text(s["text"], options_from_json(s["options"]))
        checks["text_times"] = _check(
            verdict["status"] != "fail", verdict["claims"], status=verdict["status"], sentences=verdict["sentences"]
        )
    else:
        checks["text_times"] = _check(False, "no options to validate against", status="fail")

    must, must_not = q.get("dest_stop_contains"), q.get("dest_stop_excludes")
    if must or must_not:
        stops = [_norm(x) for x in s["dest_stops"]]
        good = bool(stops) and all(
            all(_norm(m) in stop for m in must or []) and not any(_norm(n) in stop for n in must_not or [])
            for stop in stops
        )
        checks["dest_stop"] = _check(good, s["dest_stops"], contains=must, excludes=must_not)

    window = q.get("depart_offset_min")
    if window:
        first = _dt(s["options"][0].get("depart")) if has_options else None
        if first is None or requested_at is None:
            checks["depart_offset"] = _check(False, "no departure to compare")
        else:
            minutes = (first - requested_at).total_seconds() / 60
            checks["depart_offset"] = _check(window[0] <= minutes <= window[1], round(minutes, 1), window=window)
    return checks


def question_ok(checks: dict[str, dict[str, Any]]) -> bool:
    return all(c["ok"] for c in checks.values())


# --- the question file -------------------------------------------------------------------------------


def load_questions(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """(warm-up message, questions). Needs PyYAML (imported here so the rest of the module does not)."""
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    questions = list(data["questions"])
    for q in questions:
        q.setdefault("kind", "route")
    return str(data["warmup"]["message"]), questions


# --- the run ---------------------------------------------------------------------------------------------


def ask(
    client: Any,
    message: str,
    clock: Callable[[], float] = time.perf_counter,
    wall: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """POST one question and time its events. Never raises: failures come back as ``outcome`` values.

    ``suspended_s`` is how much longer the wall clock ran than the timing clock. On macOS the timing
    clock stops while the computer sleeps, so a value over ``SLEEP_FLAG_S`` marks a sample the
    laptop's sleep may have distorted (it is reported, not dropped).
    """
    result = _ask(client, message, clock, wall)
    return result


def _ask(client: Any, message: str, clock: Callable[[], float], wall: Callable[[], float]) -> dict[str, Any]:
    requested_at = datetime.now(timezone.utc)
    w0 = wall()
    t0 = clock()

    def stamp(result: dict[str, Any]) -> dict[str, Any]:
        suspended = max(0.0, (wall() - w0) - (clock() - t0))
        return {**result, "suspended_s": round(suspended, 3), "suspect_sleep": suspended > SLEEP_FLAG_S}

    timed: list[tuple[float, dict[str, Any]]] = []
    malformed = 0
    try:
        with client.stream("POST", "/chat", json={"message": message}) as response:
            if response.status_code != 200:
                response.read()
                return stamp(
                    {
                        **summarize([]),
                        "outcome": "rate_limited" if response.status_code == 429 else "http_error",
                        "status": response.status_code,
                        "retry_after": response.headers.get("retry-after"),
                        "requested_at": requested_at.isoformat(),
                    }
                )
            for line in response.iter_lines():
                if not line.strip():
                    continue
                events, bad = parse_ndjson(line)
                malformed += bad
                now = clock() - t0
                timed.extend((now, e) for e in events)
    except Exception as exc:  # noqa: BLE001  a network failure is a result, not a crash
        return stamp(
            {
                **summarize(timed, malformed),
                "outcome": "error",
                "error": type(exc).__name__,
                "requested_at": requested_at.isoformat(),
            }
        )
    return stamp({**summarize(timed, malformed), "status": 200, "requested_at": requested_at.isoformat()})


def _compact(q: dict[str, Any], s: dict[str, Any], checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A question's record for the JSON file: the raw options are reduced to what a reader needs."""
    options = [
        {
            "depart": o.get("depart_display"),
            "arrive": o.get("arrive_display"),
            "minutes": o.get("minutes"),
            "agencies": o.get("agencies"),
            "lines": o.get("lines"),
            "to_stop": stop,
        }
        for o, stop in zip(s["options"], s["dest_stops"])
    ]
    keep = (
        "outcome", "status", "retry_after", "error", "first_options_s", "done_s", "end_s", "agencies",
        "kinds", "replaced", "server_latency_ms", "caveats", "question", "malformed_lines", "text",
        "attribution", "requested_at", "suspended_s", "suspect_sleep",
    )
    return {
        "id": q.get("id"),
        "message": q["message"],
        "kind": q.get("kind", "route"),
        **{k: s[k] for k in keep if k in s},
        "option_summary": options,
        "checks": checks,
        "ok": question_ok(checks),
    }


def run(
    api: str,
    questions_path: Path = DEFAULT_QUESTIONS,
    out: Path | None = DEFAULT_OUT,
    spacing_s: float = 0.0,
    client: Any = None,
    max_requests: int = RATE_LIMIT_PER_HOUR,
    latency_gate: bool = True,
    only: set[str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run the warm-up and the questions; write ``out``; return the exit status."""
    warmup, questions = load_questions(questions_path)
    if only:
        questions = [q for q in questions if q.get("id") in only]
    total = 1 + len(questions)
    if total > max_requests:
        print(
            f"refusing to send {total} requests (warm-up + {len(questions)} questions): "
            f"the service allows {max_requests} an hour per address. Use --only, or split the run across hours.",
            file=sys.stderr,
        )
        return 2

    import httpx

    owned = client is None
    if owned:
        client = httpx.Client(base_url=api.rstrip("/"), timeout=httpx.Timeout(10.0, read=30.0))
    started = datetime.now(timezone.utc)
    rate_limited = False
    results: list[dict[str, Any]] = []
    try:
        print(f"warm-up: {warmup!r}", file=sys.stderr)
        warm = ask(client, warmup)
        warm_record = {k: warm.get(k) for k in ("outcome", "status", "first_options_s", "done_s", "server_latency_ms")}
        rate_limited = warm["outcome"] == "rate_limited"
        for q in questions:
            if rate_limited:
                break
            if spacing_s:
                sleep(spacing_s)
            s = ask(client, q["message"])
            if s["outcome"] == "rate_limited":
                rate_limited = True
                results.append(_compact(q, s, {"request": _check(False, "429 rate limited")}))
                break
            requested = datetime.fromisoformat(s["requested_at"])
            checks = check_question(q, s, requested_at=requested)
            results.append(_compact(q, s, checks))
            mark = "ok  " if question_ok(checks) else "FAIL"
            print(
                f"{mark} {q.get('id')}: options {s['first_options_s']} s, done {s['done_s']} s, {s['outcome']}",
                file=sys.stderr,
            )
    finally:
        if owned:
            client.close()

    ran = {r["id"] for r in results}
    skipped = [q.get("id") for q in questions if q.get("id") not in ran]
    latency_rows = [r for r in results if r["kind"] == "route" and r["outcome"] == "options"]
    agg = aggregate(latency_rows)
    all_ok = bool(results) and not skipped and not rate_limited and all(r["ok"] for r in results)
    ok = all_ok and (agg["ok"] or not latency_gate)
    record = {
        "api": api,
        "started_at": started.isoformat(),
        "requests": (1 if warm else 0) + len(results),
        "warmup": warm_record,
        "questions": results,
        "skipped": skipped,
        "rate_limited": rate_limited,
        "aggregate": agg,
        "targets": TARGETS,
        "validator": "options only: the stream carries no digest, so alert and event figures are 'unverifiable'",
        "checks_ok": all_ok,
        "latency_ok": agg["ok"],
        "ok": ok,
    }
    if out is not None:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--api", required=True, help="service base URL, e.g. https://transit-assistant-....run.app")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    p.add_argument("--spacing", type=float, default=0.0, help="seconds to wait between questions")
    p.add_argument("--only", help="comma-separated question ids (the warm-up is always sent)")
    p.add_argument("--max-requests", type=int, default=RATE_LIMIT_PER_HOUR, help="refuse to send more than this")
    args = p.parse_args(argv)
    only = set(args.only.split(",")) if args.only else None
    return run(
        args.api, args.questions, args.out, args.spacing, max_requests=args.max_requests, only=only
    )


if __name__ == "__main__":
    sys.exit(main())
